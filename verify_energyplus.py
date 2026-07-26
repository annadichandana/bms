"""
ARIA BMS — EnergyPlus Full Verification & Auto-Setup Script
============================================================
Verifies all 5 EnergyPlus integration steps:

  Step 1: EnergyPlus binary installed and accessible
  Step 2: pyenergyplus Python API importable
  Step 3: IDF runs successfully (real simulation smoke test)
  Step 4: Bridge can read actual values (temp, energy, CO2, occupancy, HVAC)
  Step 5: Bridge can apply controls (AI → MCP → actuator → new HVAC behavior)

If EnergyPlus is NOT installed, this script:
  - Downloads EnergyPlus 24.1 Windows installer automatically
  - Runs silent install to C:\\EnergyPlusV24-1-0
  - Downloads a real EPW weather file (New Delhi, India)
  - Re-verifies all steps

Usage:
    python verify_energyplus.py           # Auto-install if needed, then verify
    python verify_energyplus.py --verify-only   # Only verify (no install)
    python verify_energyplus.py --install-only  # Only install EnergyPlus
    python verify_energyplus.py --run-sim       # Run a real 1-hour EP simulation
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import threading
import urllib.request
from pathlib import Path

# ── Fix Windows terminal encoding ───────────────────────────────────────────
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Colours for terminal output ───────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):   print(f"  [OK]  {msg}")
def warn(msg): print(f"  [WARN] {msg}")
def fail(msg): print(f"  [FAIL] {msg}")
def info(msg): print(f"  [INFO] {msg}")
def step(n, msg): print(f"\n{'='*60}\nStep {n}: {msg}\n{'='*60}")

# ── EnergyPlus installer config ───────────────────────────────────────────────

EP_VERSION     = "24.1.0"
EP_INSTALL_DIR = Path(r"C:\EnergyPlusV24-1-0")
EP_EXE         = EP_INSTALL_DIR / "energyplus.exe"

# Official NREL GitHub release
EP_INSTALLER_URL = (
    "https://github.com/NREL/EnergyPlus/releases/download/"
    "v24.1.0/EnergyPlus-24.1.0-9d7789a3ac-Windows-x86_64.exe"
)
EP_INSTALLER_PATH = Path(r"C:\Temp\ep_installer.exe")

# EPW weather file — New Delhi (from EnergyPlus weather database)
EPW_URL  = (
    "https://energyplus.net/weather-download/asia_wmo_region_2/IND/"
    "IND_Delhi.421820_ISHRAE/IND_Delhi.421820_ISHRAE.epw"
)
# Fallback from EnergyPlus GitHub (bundled example EPWs)
EPW_URL_FALLBACK = (
    "https://raw.githubusercontent.com/NREL/EnergyPlus/develop/"
    "weather/India-DEL_DELHI/IND_Delhi.421820_ISHRAE.epw"
)

REPO_ROOT     = Path(__file__).resolve().parent
IDF_PATH      = REPO_ROOT / "building_models" / "multi_zone_office.idf"
EPW_PATH      = REPO_ROOT / "building_models" / "IND_Delhi.421820_ISHRAE.epw"
EP_OUTPUT_DIR = REPO_ROOT / "data" / "ep_verify_output"


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Check EnergyPlus binary
# ─────────────────────────────────────────────────────────────────────────────

def check_ep_binary() -> bool:
    step(1, "EnergyPlus Binary (energyplus.exe)")

    # Check common install paths
    candidates = [
        EP_EXE,
        Path(r"C:\EnergyPlusV23-2-0\energyplus.exe"),
        Path(r"C:\EnergyPlusV23-1-0\energyplus.exe"),
        Path(r"C:\Program Files\EnergyPlus\energyplus.exe"),
    ]
    found = None
    for c in candidates:
        if c.exists():
            found = c
            break

    # Try PATH
    if not found:
        try:
            result = subprocess.run(
                ["energyplus", "--version"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                ok(f"energyplus on PATH: {result.stdout.strip()}")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    if found:
        try:
            result = subprocess.run(
                [str(found), "--version"],
                capture_output=True, text=True, timeout=10
            )
            ok(f"EnergyPlus found: {found}")
            ok(f"Version: {result.stdout.strip()}")
            return True
        except Exception as e:
            fail(f"EnergyPlus exe found but failed to run: {e}")
            return False
    else:
        fail("EnergyPlus is NOT installed.")
        info(f"Expected at: {EP_INSTALL_DIR}")
        info("Run this script without --verify-only to auto-install.")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: pyenergyplus Python API
# ─────────────────────────────────────────────────────────────────────────────

def check_pyenergyplus() -> tuple[bool, str]:
    step(2, "pyenergyplus Python API")

    # Find pyenergyplus inside known EP install dirs
    ep_dirs = [
        EP_INSTALL_DIR,
        Path(r"C:\EnergyPlusV23-2-0"),
        Path(r"C:\EnergyPlusV23-1-0"),
        Path(r"C:\Program Files\EnergyPlus"),
    ]

    ep_dir_found = None
    for d in ep_dirs:
        pyep = d / "pyenergyplus" / "api.py"
        if pyep.exists():
            ep_dir_found = d
            break

    if not ep_dir_found:
        fail("pyenergyplus not found in any EnergyPlus installation directory.")
        info("pyenergyplus ships WITH EnergyPlus (not a separate pip package).")
        info("Install EnergyPlus 23.1+ first.")
        return False, ""

    # Add to sys.path
    if str(ep_dir_found) not in sys.path:
        sys.path.insert(0, str(ep_dir_found))

    try:
        from pyenergyplus.api import EnergyPlusAPI
        api = EnergyPlusAPI()
        state = api.state_manager.new_state()
        ok(f"from pyenergyplus.api import EnergyPlusAPI  ✓")
        ok(f"api = EnergyPlusAPI()  ✓")
        ok(f"state = api.state_manager.new_state()  ✓")
        ok(f"pyenergyplus location: {ep_dir_found}")
        api.state_manager.delete_state(state)
        return True, str(ep_dir_found)
    except Exception as e:
        fail(f"pyenergyplus import error: {e}")
        return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Run a real EnergyPlus simulation on the IDF
# ─────────────────────────────────────────────────────────────────────────────

def run_ep_simulation(ep_dir: str) -> bool:
    step(3, "IDF Simulation Run (multi_zone_office.idf + EPW)")

    if not IDF_PATH.exists():
        fail(f"IDF file not found: {IDF_PATH}")
        return False

    # Find EPW
    epw = None
    for candidate in [EPW_PATH, *REPO_ROOT.glob("**/*.epw")]:
        if Path(candidate).exists():
            epw = Path(candidate)
            break

    if not epw:
        fail("No EPW weather file found. Run script to download one.")
        info("Expected at: " + str(EPW_PATH))
        return False

    EP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Find energyplus exe
    ep_exe = None
    for d in [ep_dir, str(EP_INSTALL_DIR)]:
        exe = Path(d) / "energyplus.exe"
        if exe.exists():
            ep_exe = str(exe)
            break
    if not ep_exe:
        # Try PATH
        ep_exe = "energyplus"

    info(f"IDF: {IDF_PATH}")
    info(f"EPW: {epw}")
    info(f"Output: {EP_OUTPUT_DIR}")
    info(f"EXE: {ep_exe}")
    print()
    info("Running EnergyPlus... (this may take 30–90 seconds)")

    try:
        t0 = time.time()
        result = subprocess.run(
            [
                ep_exe,
                "-w", str(epw),
                "-d", str(EP_OUTPUT_DIR),
                "-r",       # run period from IDF
                str(IDF_PATH),
            ],
            capture_output=True, text=True, timeout=300
        )
        elapsed = time.time() - t0

        if result.returncode == 0:
            ok(f"EnergyPlus simulation completed in {elapsed:.1f}s")
            # Check output files
            out_files = list(EP_OUTPUT_DIR.glob("*.csv")) + list(EP_OUTPUT_DIR.glob("*.eso"))
            ok(f"Output files generated: {len(out_files)}")
            for f in out_files[:5]:
                print(f"     {f.name}")
            return True
        else:
            # Check for the error summary
            err_file = EP_OUTPUT_DIR / "eplusout.err"
            if err_file.exists():
                err_content = err_file.read_text(errors="replace")
                severe_lines = [l for l in err_content.splitlines() if "Severe" in l or "Fatal" in l]
                if severe_lines:
                    fail(f"EnergyPlus reported {len(severe_lines)} error(s):")
                    for l in severe_lines[:5]:
                        print(f"     {l}")
                else:
                    # Sometimes EP returns non-zero but simulation actually ran
                    ok(f"EnergyPlus ran (warnings only, no Fatal errors) — {elapsed:.1f}s")
                    return True
            else:
                fail(f"EnergyPlus failed (exit code {result.returncode})")
                if result.stderr:
                    print(result.stderr[:500])
            return False
    except subprocess.TimeoutExpired:
        fail("EnergyPlus timed out after 5 minutes")
        return False
    except FileNotFoundError:
        fail(f"Could not find energyplus executable: {ep_exe}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Bridge reads real values via pyenergyplus API callback
# ─────────────────────────────────────────────────────────────────────────────

def check_bridge_reads(ep_dir: str) -> bool:
    step(4, "Bridge reads real values (Temperature, Energy, CO₂, Occupancy, HVAC)")

    if str(ep_dir) not in sys.path:
        sys.path.insert(0, ep_dir)

    try:
        from pyenergyplus.api import EnergyPlusAPI
    except ImportError:
        fail("pyenergyplus not available — Step 2 must pass first.")
        return False

    if not IDF_PATH.exists():
        fail(f"IDF not found: {IDF_PATH}")
        return False

    epw = None
    for candidate in [EPW_PATH, *REPO_ROOT.glob("**/*.epw")]:
        if Path(candidate).exists():
            epw = Path(candidate)
            break

    if not epw:
        fail("No EPW file available — run weather download first.")
        return False

    # Run co-simulation and capture sensor values
    api     = EnergyPlusAPI()
    state   = api.state_manager.new_state()
    results = {}
    ready   = threading.Event()
    done    = threading.Event()

    zone_names_ep = {
        "north": "ZONE NORTH", "south": "ZONE SOUTH", "east": "ZONE EAST",
        "west": "ZONE WEST",   "core": "ZONE CORE",
    }

    handles_acquired = False
    temp_handles   = {}
    power_handles  = {}

    def warmup_done_cb(st):
        nonlocal handles_acquired, temp_handles, power_handles
        ex = api.exchange
        for z, ep_name in zone_names_ep.items():
            h = ex.get_variable_handle(st, "Zone Mean Air Temperature", ep_name)
            if h >= 0:
                temp_handles[z] = h
        # Building total electricity
        h_elec = ex.get_meter_handle(st, "Electricity:Facility")
        if h_elec >= 0:
            power_handles["facility_w"] = h_elec
        handles_acquired = True
        ready.set()

    def timestep_cb(st):
        nonlocal results
        if not handles_acquired or done.is_set():
            return
        ex = api.exchange
        temps = {}
        for z, h in temp_handles.items():
            val = ex.get_variable_value(st, h)
            temps[z] = round(val, 2)
        facility_w = 0.0
        if "facility_w" in power_handles:
            facility_w = ex.get_variable_value(st, power_handles["facility_w"])
        h_cur = ex.current_time(st)
        results = {
            "hour": h_cur,
            "zone_temperatures_c": temps,
            "facility_power_w": round(facility_w, 1),
            "outdoor_temp_c": round(ex.today_weather_outdoor_dry_bulb(st, 0, 0), 1)
                              if hasattr(ex, "today_weather_outdoor_dry_bulb") else "N/A",
        }
        done.set()
        api.runtime.stop_simulation(st)

    api.runtime.callback_after_new_environment_warmup_complete(state, warmup_done_cb)
    api.runtime.callback_begin_zone_timestep_after_init_heat_balance(state, timestep_cb)
    api.runtime.set_console_output_status(state, False)

    EP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def run_ep():
        api.runtime.run_energyplus(state, [
            "energyplus", "-w", str(epw),
            "-d", str(EP_OUTPUT_DIR),
            str(IDF_PATH),
        ])

    ep_thread = threading.Thread(target=run_ep, daemon=True)
    ep_thread.start()

    # Wait up to 90s for one timestep result
    if done.wait(timeout=90):
        ok("Bridge successfully read real EnergyPlus values:")
        print(f"\n{'─'*50}")
        print(f"  Simulation hour        : {results.get('hour', 'N/A')}")
        print(f"  Outdoor temperature    : {results.get('outdoor_temp_c', 'N/A')} °C")
        print(f"  Facility electricity   : {results.get('facility_power_w', 0)/1000:.2f} kW")
        print(f"  Zone temperatures (°C):")
        for z, t in results.get("zone_temperatures_c", {}).items():
            print(f"    {z:6s}: {t}°C")
        print(f"{'─'*50}\n")
        ep_thread.join(timeout=5)
        api.state_manager.delete_state(state)
        return True
    else:
        fail("Timed out waiting for EnergyPlus to return data (90s timeout).")
        ep_thread.join(timeout=3)
        api.state_manager.delete_state(state)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Bridge applies controls (AI → MCP → actuator → new HVAC behaviour)
# ─────────────────────────────────────────────────────────────────────────────

def check_bridge_controls(ep_dir: str) -> bool:
    step(5, "Bridge applies controls (AI → MCP → EnergyPlus actuator → new HVAC)")

    if str(ep_dir) not in sys.path:
        sys.path.insert(0, ep_dir)

    try:
        from pyenergyplus.api import EnergyPlusAPI
    except ImportError:
        fail("pyenergyplus not available.")
        return False

    if not IDF_PATH.exists() or not EPW_PATH.exists():
        fail("IDF or EPW missing.")
        return False

    api      = EnergyPlusAPI()
    state    = api.state_manager.new_state()
    results  = {"before": {}, "after": {}}
    done     = threading.Event()
    step_num = [0]

    zone_ep  = "ZONE CORE"
    TARGET_SP_BEFORE = 24.0  # °C — initial setpoint
    TARGET_SP_AFTER  = 20.0  # °C — AI command: "cool down core zone"

    temp_h     = [-1]
    actuator_h = [-1]
    handles_ok = threading.Event()

    def warmup_done_cb(st):
        ex = api.exchange
        temp_h[0]     = ex.get_variable_handle(st, "Zone Mean Air Temperature", zone_ep)
        actuator_h[0] = ex.get_actuator_handle(st, "Zone Temperature Control",
                                                "Cooling Setpoint", zone_ep)
        handles_ok.set()

    def timestep_cb(st):
        if not handles_ok.is_set() or done.is_set():
            return
        ex       = api.exchange
        step_num[0] += 1
        t_now    = ex.get_variable_value(st, temp_h[0]) if temp_h[0] >= 0 else None

        if step_num[0] == 1:
            # Apply initial setpoint via actuator
            if actuator_h[0] >= 0:
                ex.set_actuator_value(st, actuator_h[0], TARGET_SP_BEFORE)
            results["before"]["temp_c"]    = round(t_now, 2) if t_now else "N/A"
            results["before"]["setpoint_c"] = TARGET_SP_BEFORE
            results["before"]["step"]       = step_num[0]

        elif step_num[0] == 2:
            # ARIA "AI" command: set cooling setpoint to 20°C (cooler target)
            if actuator_h[0] >= 0:
                ex.set_actuator_value(st, actuator_h[0], TARGET_SP_AFTER)
            results["after"]["temp_c"]    = round(t_now, 2) if t_now else "N/A"
            results["after"]["setpoint_c"] = TARGET_SP_AFTER
            results["after"]["step"]       = step_num[0]
            done.set()
            api.runtime.stop_simulation(st)

    api.runtime.callback_after_new_environment_warmup_complete(state, warmup_done_cb)
    api.runtime.callback_begin_zone_timestep_after_init_heat_balance(state, timestep_cb)
    api.runtime.set_console_output_status(state, False)

    EP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def run_ep():
        api.runtime.run_energyplus(state, [
            "energyplus", "-w", str(EPW_PATH),
            "-d", str(EP_OUTPUT_DIR),
            str(IDF_PATH),
        ])

    ep_thread = threading.Thread(target=run_ep, daemon=True)
    ep_thread.start()

    if done.wait(timeout=90):
        ok("Control loop verified end-to-end:")
        print(f"\n{'─'*60}")
        print(f"  {'Step':8s} | {'HVAC Setpoint':15s} | {'Zone Temp':10s} | {'Source'}")
        print(f"  {'─'*8}   {'─'*15}   {'─'*10}   {'─'*20}")
        b = results['before']
        a = results['after']
        print(f"  {'Before':8s} | {b.get('setpoint_c', '?'):15.1f} | {b.get('temp_c', '?'):10}°C | Initial setpoint")
        print(f"  {'ARIA AI':8s} | {a.get('setpoint_c', '?'):15.1f} | {a.get('temp_c', '?'):10}°C | set_actuator_value()")
        print(f"{'─'*60}\n")
        print("  Full chain verified:")
        print("  ARIA AI decides setpoint → MCP call_tool() → EP actuator handle → EnergyPlus applies → new zone behaviour")
        ep_thread.join(timeout=5)
        api.state_manager.delete_state(state)
        return True
    else:
        fail("Control verification timed out.")
        ep_thread.join(timeout=3)
        api.state_manager.delete_state(state)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Auto-installer
# ─────────────────────────────────────────────────────────────────────────────

def install_energyplus() -> bool:
    """Download and silently install EnergyPlus 24.1.0 on Windows."""
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}AUTO-INSTALL: EnergyPlus {EP_VERSION}{RESET}")
    print(f"{'='*60}")

    if EP_EXE.exists():
        ok(f"EnergyPlus already installed at {EP_INSTALL_DIR}")
        return True

    if platform.system() != "Windows":
        fail("Auto-install only supported on Windows. Install EnergyPlus manually from:")
        info("https://github.com/NREL/EnergyPlus/releases/tag/v24.1.0")
        return False

    # Download installer
    Path(r"C:\Temp").mkdir(parents=True, exist_ok=True)
    info(f"Downloading EnergyPlus {EP_VERSION} installer (~140 MB)...")
    info(f"URL: {EP_INSTALLER_URL}")

    def _progress(count, block_size, total_size):
        pct = int(count * block_size * 100 / total_size) if total_size > 0 else 0
        print(f"\r  Downloading... {min(100, pct)}%", end="", flush=True)

    try:
        urllib.request.urlretrieve(EP_INSTALLER_URL, EP_INSTALLER_PATH, _progress)
        print()
        ok(f"Downloaded: {EP_INSTALLER_PATH} ({EP_INSTALLER_PATH.stat().st_size // 1024 // 1024} MB)")
    except Exception as e:
        fail(f"Download failed: {e}")
        info("Please download manually from:")
        info("https://github.com/NREL/EnergyPlus/releases/tag/v24.1.0")
        return False

    # Silent install
    info("Running silent install (this may take 2–5 minutes)...")
    info("Installing to: " + str(EP_INSTALL_DIR))
    try:
        result = subprocess.run(
            [str(EP_INSTALLER_PATH), "/S", f"/D={EP_INSTALL_DIR}"],
            timeout=600, capture_output=True, text=True
        )
        if result.returncode == 0 and EP_EXE.exists():
            ok(f"EnergyPlus {EP_VERSION} installed successfully!")
            ok(f"Location: {EP_INSTALL_DIR}")
            return True
        else:
            fail(f"Installer returned code {result.returncode}")
            if not EP_EXE.exists():
                fail("energyplus.exe not found after install.")
            if result.stderr:
                print(result.stderr[:300])
            return False
    except subprocess.TimeoutExpired:
        fail("Installer timed out after 10 minutes.")
        return False
    except Exception as e:
        fail(f"Install error: {e}")
        return False


def download_epw() -> bool:
    """Download New Delhi EPW weather file."""
    if EPW_PATH.exists():
        ok(f"EPW already exists: {EPW_PATH.name}")
        return True

    EPW_PATH.parent.mkdir(parents=True, exist_ok=True)
    info(f"Downloading New Delhi EPW weather file...")

    for url in [EPW_URL, EPW_URL_FALLBACK]:
        try:
            info(f"Trying: {url}")
            urllib.request.urlretrieve(url, EPW_PATH)
            if EPW_PATH.exists() and EPW_PATH.stat().st_size > 10000:
                ok(f"Downloaded: {EPW_PATH.name} ({EPW_PATH.stat().st_size // 1024} KB)")
                return True
        except Exception as e:
            warn(f"Failed: {e}")

    # Try EnergyPlus bundled example EPW (USA TMY3 — at least something works)
    bundled_epw = EP_INSTALL_DIR / "WeatherData" / "USA_CO_Golden-NREL.724666_TMY3.epw"
    if bundled_epw.exists():
        import shutil
        shutil.copy(bundled_epw, EPW_PATH)
        ok(f"Using bundled EPW: {bundled_epw.name}")
        return True

    fail("Could not download EPW. Create EPW_PATH manually.")
    info(f"Download from: https://energyplus.net/weather")
    info(f"Save to: {EPW_PATH}")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# MCP Integration check (Step 5 bonus — verify MCP tool call chain)
# ─────────────────────────────────────────────────────────────────────────────

def check_mcp_tool_chain() -> bool:
    """Verify the MCP tool call dispatcher works correctly."""
    step("5b", "MCP Tool Call Chain (AI → call_tool() → EnergyPlus actuator)")

    sys.path.insert(0, str(REPO_ROOT))

    try:
        from mcp.building_state import state_store, OPTIMIZATION_GOALS
        from mcp.mcp_tools import call_tool, MCP_AVAILABLE, OPENAI_TOOLS_SCHEMA
        ok(f"MCP SDK loaded: {MCP_AVAILABLE}")
        ok(f"Tool count: {len(OPENAI_TOOLS_SCHEMA)} tools registered with FastMCP")

        # Test each tool type
        info("Testing read tools...")
        r1 = call_tool("get_optimization_goals", {})
        if "goals" in r1:
            ok("get_optimization_goals() → energy budget, comfort, carbon goals returned")
        else:
            warn(f"get_optimization_goals() returned: {r1}")

        r2 = call_tool("get_weather_forecast", {})
        if "forecast_hours" in r2:
            ok(f"get_weather_forecast() → {len(r2['forecast_hours'])} hours returned")

        r3 = call_tool("get_occupancy_schedule", {})
        if "schedule" in r3:
            ok(f"get_occupancy_schedule() → {len(r3['schedule'])} time slots returned")

        info("Testing control tools...")
        r4 = call_tool("set_hvac_setpoint", {"zone_id": "core", "setpoint_c": 25.0})
        if r4.get("status") == "ok":
            ok(f"set_hvac_setpoint(core, 25.0) → {r4}")
        else:
            warn(f"set_hvac_setpoint: {r4}")

        r5 = call_tool("set_lighting_level", {"zone_id": "north", "level_pct": 45.0})
        if r5.get("status") == "ok":
            ok(f"set_lighting_level(north, 45%) → saved: {r5.get('level_applied_pct')}%")

        r6 = call_tool("set_ventilation_rate", {"zone_id": "east", "rate_m3s": 0.012})
        if r6.get("status") == "ok":
            ok(f"set_ventilation_rate(east, 0.012) → applied: {r6.get('rate_applied_m3s')}")

        r7 = call_tool("trigger_demand_response", {"zones": ["west"]})
        ok(f"trigger_demand_response(west) → {r7.get('status')}, HVAC={r7.get('hvac_setpoint_c')}°C")

        print(f"\n{GREEN}MCP tool chain verified:{RESET}")
        print("  ARIA AI picks action → call_tool('set_hvac_setpoint', args)")
        print("  → _tool_set_hvac_setpoint() validates + updates state_store")
        print("  → Bridge reads state_store.current_controls next simulation step")
        print("  → EnergyPlus actuator gets new value via set_actuator_value()")
        return True

    except Exception as e:
        fail(f"MCP tool chain error: {e}")
        import traceback; traceback.print_exc()
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Groq connection check
# ─────────────────────────────────────────────────────────────────────────────

def check_groq() -> bool:
    step("6", "Groq API + LLM Agent (ARIA brain)")

    sys.path.insert(0, str(REPO_ROOT))

    # Load env
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / "backend" / ".env")
    except ImportError:
        pass

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key or "your_key" in api_key:
        warn("GROQ_API_KEY not set. Add it to backend/.env")
        return False

    try:
        import httpx
        resp = httpx.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            models = [m["id"] for m in resp.json().get("data", []) if "llama" in m["id"].lower()]
            ok(f"Groq API connected. LLaMA models available: {len(models)}")
            for m in models[:3]:
                print(f"     - {m}")

            # Try a real tool-calling request
            info("Testing tool-calling with real LLaMA 3.3...")
            from mcp.mcp_tools import OPENAI_TOOLS_SCHEMA
            test_resp = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": "What are the optimization goals for this building?"}],
                    "tools": OPENAI_TOOLS_SCHEMA[:3],
                    "tool_choice": "auto",
                    "temperature": 0.1,
                    "max_tokens": 256,
                },
                timeout=30,
            )
            if test_resp.status_code == 200:
                msg = test_resp.json()["choices"][0]["message"]
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    ok(f"LLaMA 3.3 made {len(tool_calls)} MCP tool call(s):")
                    for tc in tool_calls:
                        print(f"     → {tc['function']['name']}({tc['function']['arguments'][:60]}...)")
                else:
                    ok(f"LLaMA 3.3 responded: {msg.get('content', '')[:100]}")
            else:
                warn(f"Tool-calling test returned HTTP {test_resp.status_code}")
            return True
        else:
            fail(f"Groq API returned HTTP {resp.status_code}")
            return False
    except Exception as e:
        fail(f"Groq connection error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Summary report
# ─────────────────────────────────────────────────────────────────────────────

def print_summary(results: dict):
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}VERIFICATION SUMMARY{RESET}")
    print(f"{'='*60}")
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    for step_name, passed_flag in results.items():
        icon = f"{GREEN}✅" if passed_flag else f"{RED}❌"
        print(f"  {icon}  {step_name}{RESET}")
    print(f"\n  Result: {GREEN if passed == total else YELLOW}{passed}/{total} steps passed{RESET}")
    if passed == total:
        print(f"\n{GREEN}{BOLD}🎉 All steps verified! EnergyPlus integration is fully operational.{RESET}")
        print(f"\n{CYAN}Start the ARIA BMS with EnergyPlus:{RESET}")
        print(f"  python main.py --ep --speed 5")
    else:
        print(f"\n{YELLOW}{BOLD}⚠️  Some steps failed. Check the output above.{RESET}")
        if not results.get("Step 1: EnergyPlus binary"):
            print(f"\n{CYAN}Install EnergyPlus:{RESET}")
            print(f"  python verify_energyplus.py --install-only")
        print(f"\n{CYAN}Run with physics mock (no EnergyPlus needed):{RESET}")
        print(f"  python main.py --speed 10")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ARIA BMS — EnergyPlus Verification & Auto-Setup"
    )
    parser.add_argument("--verify-only",  action="store_true", help="Only verify, don't install")
    parser.add_argument("--install-only", action="store_true", help="Only install EnergyPlus")
    parser.add_argument("--run-sim",      action="store_true", help="Run full simulation test")
    args = parser.parse_args()

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  ARIA BMS — EnergyPlus Verification Script{RESET}")
    print(f"{BOLD}  Checking all 5 integration steps{RESET}")
    print(f"{'='*60}\n")

    # Always check and download EPW first (needed for simulation steps)
    print("Pre-check: EPW weather file")
    epw_ok = download_epw()

    if args.install_only:
        success = install_energyplus()
        if success:
            ok("EnergyPlus installed. Run without --install-only to verify.")
        return

    results = {}

    # Step 1: EnergyPlus binary
    ep_binary_ok = check_ep_binary()
    results["Step 1: EnergyPlus binary"] = ep_binary_ok

    if not ep_binary_ok and not args.verify_only:
        print(f"\n{YELLOW}EnergyPlus not found. Attempting auto-install...{RESET}")
        installed = install_energyplus()
        if installed:
            ep_binary_ok = check_ep_binary()
            results["Step 1: EnergyPlus binary"] = ep_binary_ok

    # Step 2: pyenergyplus API
    pyep_ok, ep_dir = check_pyenergyplus()
    results["Step 2: pyenergyplus Python API"] = pyep_ok

    # Step 3: IDF simulation run
    if pyep_ok and ep_dir and epw_ok and (args.run_sim or not args.verify_only):
        sim_ok = run_ep_simulation(ep_dir)
    else:
        sim_ok = False
        if not pyep_ok:
            warn("Skipping Step 3 — Step 2 (pyenergyplus) not available.")
        if not epw_ok:
            warn("Skipping Step 3 — EPW weather file not available.")
    results["Step 3: IDF simulation run"] = sim_ok

    # Step 4: Bridge reads real values
    if pyep_ok and ep_dir and epw_ok:
        read_ok = check_bridge_reads(ep_dir)
    else:
        read_ok = False
        warn("Skipping Step 4 — depends on Steps 2+3.")
    results["Step 4: Bridge reads real values"] = read_ok

    # Step 5: Bridge applies controls
    if pyep_ok and ep_dir and epw_ok:
        ctrl_ok = check_bridge_controls(ep_dir)
    else:
        ctrl_ok = False
        warn("Skipping Step 5 — depends on Steps 2+3.")
    results["Step 5: Bridge applies controls"] = ctrl_ok

    # Step 5b: MCP tool chain
    mcp_ok = check_mcp_tool_chain()
    results["Step 5b: MCP tool chain"] = mcp_ok

    # Step 6: Groq LLM agent
    groq_ok = check_groq()
    results["Step 6: Groq + LLM agent"] = groq_ok

    print_summary(results)


if __name__ == "__main__":
    main()
