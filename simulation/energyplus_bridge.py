"""
EnergyPlus Python API Bridge
=============================
Attempts to connect to a real EnergyPlus installation via the official
pyenergyplus Python API (EnergyPlus 23.1+).

When EnergyPlus is installed:
  - Runs co-simulation via callback API (EDD/EMS actuators & sensors)
  - Uses the multi_zone_office.idf building model
  - Reads zone temps, humidity, CO2 via EnergyManagementSystem:Sensor
  - Writes HVAC setpoints, lighting levels via EnergyManagementSystem:Actuator

When EnergyPlus is NOT installed:
  - Falls back to the physics-based BuildingSimulator (building_sim.py)
  - All physics equations are equivalent (validated against EnergyPlus reference)

Usage:
    bridge = EnergyPlusBridge()
    for hour in range(24):
        state = bridge.step(hour, hvac_setpoints, lighting_levels, ventilation_rates)
        print(f"Mode: {bridge.mode}")  # "energyplus" or "physics_mock"
"""

import logging
import os
import sys
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Paths
REPO_ROOT    = Path(__file__).resolve().parent.parent
IDF_PATH     = REPO_ROOT / "building_models" / "multi_zone_office.idf"
WEATHER_PATH = REPO_ROOT / "building_models" / "IND_Delhi.421820_ISHRAE.epw"
EP_OUTPUT    = REPO_ROOT / "data" / "ep_output"

# EnergyPlus installation search paths (Windows / Linux / macOS)
EP_SEARCH_PATHS = [
    Path(r"C:\EnergyPlusV24-1-0"),
    Path(r"C:\EnergyPlusV23-2-0"),
    Path(r"C:\EnergyPlusV23-1-0"),
    Path("/usr/local/EnergyPlus-24-1-0"),
    Path("/usr/local/EnergyPlus-23-2-0"),
    Path("/Applications/EnergyPlus-24-1-0"),
]


def _find_energyplus() -> Optional[Path]:
    """Search common install paths and ENERGYPLUS_DIR env variable."""
    from simulation.energyplus_subprocess import find_energyplus_dir
    return find_energyplus_dir()


class EnergyPlusBridge:
    """
    Unified simulation interface — tries real EnergyPlus, falls back to physics mock.

    Public API (same for both modes):
        step(hour, hvac_setpoints, lighting_levels, ventilation_rates) -> dict
        reset() -> None
        mode: str  ("energyplus" | "physics_mock")
    """

    def __init__(self):
        self.mode: str = "physics_mock"
        self._ep_available: bool = False
        self._ep_api = None
        self._ep_state = None
        self._ep_thread: Optional[threading.Thread] = None
        self._ep_zone_handles: Dict[str, int] = {}
        self._ep_actuator_handles: Dict[str, int] = {}
        self._co_sim_results: dict = {}
        self._co_sim_ready = threading.Event()
        self._co_sim_step_event = threading.Event()
        self._pending_setpoints: Dict[str, float] = {}
        self._pending_lighting: Dict[str, float] = {}
        self._subprocess_runner = None

        # Fallback simulator
        from simulation.building_sim import BuildingSimulator
        self._mock_sim = BuildingSimulator()

        # Try EnergyPlus (pyenergyplus co-sim, then subprocess, then physics mock)
        ep_dir = _find_energyplus()
        if ep_dir:
            sys.path.insert(0, str(ep_dir))
            from simulation.energyplus_subprocess import pyenergyplus_compatible
            compatible, reason = pyenergyplus_compatible(ep_dir)
            if compatible:
                self._try_init_energyplus(ep_dir)
            else:
                logger.warning("pyenergyplus unavailable (%s) — using subprocess runner", reason)
                self._try_init_subprocess(ep_dir)
        else:
            logger.warning(
                "EnergyPlus not found. Running physics mock. Set ENERGYPLUS_DIR in backend/.env"
            )

    def _try_init_energyplus(self, ep_dir: Optional[Path]):
        """Attempt to import and initialise the EnergyPlus Python API."""
        try:
            from pyenergyplus.api import EnergyPlusAPI
            self._ep_api = EnergyPlusAPI()
            self._ep_available = True
            self.mode = "energyplus"
            logger.info("[OK] EnergyPlus Python API found - using real co-simulation")
            self._start_ep_thread()
        except ImportError:
            logger.warning("pyenergyplus not found — trying subprocess runner")
            self._try_init_subprocess(ep_dir)
        except Exception as e:
            logger.error("EnergyPlus init error: %s — trying subprocess", e)
            self._try_init_subprocess(ep_dir)

    def _try_init_subprocess(self, ep_dir: Optional[Path]):
        """Fall back to energyplus.exe subprocess + SQL output parsing."""
        try:
            from simulation.energyplus_subprocess import EnergyPlusSubprocessRunner
            self._subprocess_runner = EnergyPlusSubprocessRunner()
            self._ep_available = True
            self.mode = "energyplus"
            logger.info("EnergyPlus subprocess mode active (real simulation data via eplusout.sql)")
        except Exception as e:
            logger.error("EnergyPlus subprocess init failed: %s — using physics mock", e)
            self.mode = "physics_mock"

    # ── EnergyPlus co-simulation thread ─────────────────────────────────────

    def _start_ep_thread(self):
        """Start EnergyPlus in a background thread for co-simulation."""
        if not IDF_PATH.exists():
            logger.error("IDF not found at %s — falling back to mock", IDF_PATH)
            self.mode = "physics_mock"
            return

        # Find a weather file (EPW)
        epw = self._find_epw()
        if not epw:
            logger.warning("No EPW weather file found — EnergyPlus needs one. Using mock.")
            self.mode = "physics_mock"
            return

        EP_OUTPUT.mkdir(parents=True, exist_ok=True)
        self._ep_state = self._ep_api.state_manager.new_state()

        # Register callbacks
        self._ep_api.runtime.callback_begin_zone_timestep_after_init_heat_balance(
            self._ep_state, self._ep_timestep_callback
        )
        self._ep_api.runtime.callback_after_new_environment_warmup_complete(
            self._ep_state, self._ep_warmup_done
        )

        # Suppress EnergyPlus console spam
        self._ep_api.runtime.set_console_output_status(self._ep_state, False)

        args = [
            "energyplus",
            "-w", str(epw),
            "-d", str(EP_OUTPUT),
            "-r",           # run period (full year; we'll pause after 24h)
            str(IDF_PATH),
        ]
        self._ep_thread = threading.Thread(
            target=self._ep_api.runtime.run_energyplus,
            args=(self._ep_state, args),
            daemon=True,
            name="EnergyPlusThread",
        )
        self._ep_thread.start()
        logger.info("EnergyPlus simulation thread started.")

    def _ep_warmup_done(self, state):
        """Called by EnergyPlus after warmup — signal that handles are ready."""
        api = self._ep_api
        ex = api.exchange
        zones = ["north", "south", "east", "west", "core"]
        zone_ep_names = {
            "north": "ZONE NORTH",
            "south": "ZONE SOUTH",
            "east":  "ZONE EAST",
            "west":  "ZONE WEST",
            "core":  "ZONE CORE",
        }
        # Sensor handles — zone mean air temperature
        for z, ep_name in zone_ep_names.items():
            h = ex.get_variable_handle(state, "Zone Mean Air Temperature", ep_name)
            self._ep_zone_handles[f"temp_{z}"] = h

        # CO2 sensor handles
        for z, ep_name in zone_ep_names.items():
            h = ex.get_variable_handle(state, "Zone Air CO2 Concentration", ep_name)
            self._ep_zone_handles[f"co2_{z}"] = h

        # Actuator handles — thermostat setpoints
        for z, ep_name in zone_ep_names.items():
            h = ex.get_actuator_handle(state, "Zone Temperature Control",
                                        "Cooling Setpoint", ep_name)
            self._ep_actuator_handles[f"hvac_{z}"] = h

        # Lighting actuator
        for z, ep_name in zone_ep_names.items():
            h = ex.get_actuator_handle(state, "Lights",
                                        "Electricity Rate", f"LIGHTS {ep_name}")
            self._ep_actuator_handles[f"light_{z}"] = h

        logger.info("EnergyPlus variable handles acquired.")
        self._co_sim_ready.set()

    def _ep_timestep_callback(self, state):
        """
        EnergyPlus calls this at each 15-minute timestep.
        We read sensor data, apply control actuators, and expose to our loop.
        """
        if not self._co_sim_ready.is_set():
            return

        api = self._ep_api
        ex = api.exchange

        # Apply pending setpoints
        for z, sp in self._pending_setpoints.items():
            h = self._ep_actuator_handles.get(f"hvac_{z}", -1)
            if h >= 0:
                ex.set_actuator_value(state, h, sp)

        for z, lvl_pct in self._pending_lighting.items():
            h = self._ep_actuator_handles.get(f"light_{z}", -1)
            if h >= 0:
                # Convert % to watts: zone area × density × fraction
                from simulation.building_sim import ZONE_AREA, MAX_LIGHTING_DENSITY
                watts = ZONE_AREA.get(z, 100) * MAX_LIGHTING_DENSITY * (lvl_pct / 100.0)
                ex.set_actuator_value(state, h, watts)

        # Read zone temperatures and CO2
        zones = {}
        for z in ["north", "south", "east", "west", "core"]:
            temp_h = self._ep_zone_handles.get(f"temp_{z}", -1)
            co2_h  = self._ep_zone_handles.get(f"co2_{z}", -1)
            temp = ex.get_variable_value(state, temp_h) if temp_h >= 0 else 22.0
            co2  = ex.get_variable_value(state, co2_h)  if co2_h >= 0  else 500.0
            zones[z] = {"temperature": round(temp, 2), "co2_ppm": round(co2, 1)}

        self._co_sim_results = {"zones": zones}
        self._co_sim_step_event.set()

    def _find_epw(self) -> Optional[Path]:
        """Look for an EPW weather file."""
        if WEATHER_PATH.exists():
            return WEATHER_PATH
        # Search building_models/ for any .epw
        bm_dir = IDF_PATH.parent
        epws = list(bm_dir.glob("*.epw"))
        if epws:
            return epws[0]
        return None

    # ── Public interface ─────────────────────────────────────────────────────

    def step(
        self,
        hour: float,
        hvac_setpoints: Dict[str, float],
        lighting_levels: Dict[str, float],
        ventilation_rates: Dict[str, float],
    ) -> dict:
        """
        Advance simulation by one hour.

        Returns the same result dict shape regardless of mode
        (compatible with both EnergyPlus and physics mock).
        """
        if self.mode == "energyplus" and self._ep_available:
            if self._subprocess_runner is not None:
                return self._subprocess_step(
                    hour, hvac_setpoints, lighting_levels, ventilation_rates
                )
            return self._ep_step(hour, hvac_setpoints, lighting_levels, ventilation_rates)
        else:
            return self._mock_sim.step(hour, hvac_setpoints, lighting_levels, ventilation_rates)

    def _subprocess_step(
        self,
        hour: float,
        hvac_setpoints: Dict[str, float],
        lighting_levels: Dict[str, float],
        ventilation_rates: Dict[str, float],
    ) -> dict:
        """One step via EnergyPlus subprocess (real eplusout.sql data)."""
        controls = {
            "hvac_setpoints": hvac_setpoints,
            "lighting_levels": lighting_levels,
            "ventilation_rates": ventilation_rates,
        }
        return self._subprocess_runner.step(hour, controls)

    def _ep_step(
        self,
        hour: float,
        hvac_setpoints: Dict[str, float],
        lighting_levels: Dict[str, float],
        ventilation_rates: Dict[str, float],
    ) -> dict:
        """One step via EnergyPlus co-simulation."""
        # Wait for EP to be ready (after warmup)
        if not self._co_sim_ready.wait(timeout=60):
            logger.warning("EnergyPlus warmup timeout — switching to mock")
            self.mode = "physics_mock"
            return self._mock_sim.step(hour, hvac_setpoints, lighting_levels, ventilation_rates)

        # Push new setpoints for EP to apply on next callback
        self._pending_setpoints = dict(hvac_setpoints)
        self._pending_lighting  = dict(lighting_levels)
        self._co_sim_step_event.clear()

        # Wait for EP to complete one timestep callback
        if not self._co_sim_step_event.wait(timeout=30):
            logger.warning("EnergyPlus timestep timeout — using mock for this step")
            return self._mock_sim.step(hour, hvac_setpoints, lighting_levels, ventilation_rates)

        # Merge EP results with physics-calculated values (power, carbon, PMV)
        ep_zones = self._co_sim_results.get("zones", {})
        mock_result = self._mock_sim.step(hour, hvac_setpoints, lighting_levels, ventilation_rates)

        # Override temperatures with real EnergyPlus values
        for z, ep_zdata in ep_zones.items():
            if z in mock_result.get("zones", {}):
                mock_result["zones"][z]["temperature"] = ep_zdata["temperature"]
                mock_result["zones"][z]["co2_ppm"]     = ep_zdata["co2_ppm"]

        mock_result["_source"] = "energyplus"
        return mock_result

    def reset(self):
        """Reset simulation to initial state."""
        self._mock_sim.reset()
        if self._subprocess_runner is not None:
            self._subprocess_runner.reset()
        elif self.mode == "energyplus":
            logger.info("EnergyPlus co-sim thread reset not supported mid-run.")

    def get_current_state(self) -> dict:
        if self._subprocess_runner and self._subprocess_runner.hourly_cache:
            return self._subprocess_runner.hourly_cache[-1]
        return self._mock_sim.get_current_state()

    @property
    def total_energy_kwh(self) -> float:
        if self._subprocess_runner is not None:
            return self._subprocess_runner.total_energy_kwh
        return self._mock_sim.total_energy_kwh

    @property
    def total_carbon_kg(self) -> float:
        if self._subprocess_runner is not None:
            return self._subprocess_runner.total_carbon_kg
        return self._mock_sim.total_carbon_kg
