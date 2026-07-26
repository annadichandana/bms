"""
ARIA BMS — Official MCP Server (FastMCP)
=========================================
Implements the Model Context Protocol (MCP) specification using the
official Anthropic `mcp` Python SDK (FastMCP high-level API).

This server exposes all building control tools to the LLM agent via
the standard MCP protocol, enabling true MCP-compliant tool calling.

Tools exposed:
  get_zone_status(zone_id)           — Read individual zone sensors
  get_all_zones_status()             — Full building snapshot
  get_energy_metrics()               — kWh, carbon, cost, savings
  get_optimization_goals()           — Energy/comfort/carbon targets
  get_weather_forecast()             — Next 4-hour weather prediction
  get_occupancy_schedule()           — Predicted occupancy next 2h
  get_optimization_history(n)        — Past AI decisions & outcomes
  set_hvac_setpoint(zone_id, sp)    — Set cooling/heating setpoint (°C)
  set_hvac_mode(zone_id, mode)       — cooling|heating|eco|off
  set_lighting_level(zone_id, lvl)  — 0–100% dimming
  set_ventilation_rate(zone_id, r)  — m³/s per person
  trigger_demand_response(zones)    — Emergency load shedding
  get_comfort_score()               — Zone-by-zone comfort (0–100)

Transport:
  The MCP server runs over HTTP/SSE (Server-Sent Events) so the agent
  can call it from within the same process or across the network.
  Port: 8001 (separate from the FastAPI dashboard on 8000)
"""

import logging
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Try to import FastMCP (official MCP SDK) ─────────────────────────────────
try:
    # The official `mcp` package is installed; our local package is now named `bms`
    import importlib
    _mcp_sdk = importlib.import_module("mcp.server.fastmcp")
    FastMCP = _mcp_sdk.FastMCP
    MCP_AVAILABLE = True
    logger.info("[OK] Official MCP SDK (FastMCP) loaded")
except (ImportError, ModuleNotFoundError, AttributeError):
    MCP_AVAILABLE = False
    logger.warning(
        "[WARN] `mcp` package not installed. Run: pip install mcp\n"
        "    Falling back to REST-based MCP-compatible interface."
    )
    FastMCP = None

from bms.building_state import state_store, OPTIMIZATION_GOALS
from simulation.building_sim import (
    outdoor_temperature, occupancy_fraction, ZONES
)
from agent.safety import (
    clamp_setpoints, clamp_lighting, clamp_ventilation, VALID_ZONES
)

# ── Allowed values ────────────────────────────────────────────────────────────
VALID_HVAC_MODES = {"cooling", "heating", "eco", "off"}

# ── Initialize FastMCP server ─────────────────────────────────────────────────
if MCP_AVAILABLE:
    mcp = FastMCP(
        name="ARIA-BMS",
        instructions=(
            "You are ARIA, an autonomous AI agent controlling a 5-zone commercial office building. "
            "Use the available tools to read sensor data, analyze conditions, and issue control commands. "
            "Always check zone status before making decisions. Optimize for the three objectives: "
            "energy savings (target <350 kWh/day), occupant comfort (PMV -0.5 to +0.5), "
            "and carbon reduction (target <170 kg CO2/day)."
        ),
    )
else:
    mcp = None


# ─────────────────────────────────────────────────────────────────────────────
# Tool Implementations (called by both FastMCP and the fallback REST handler)
# ─────────────────────────────────────────────────────────────────────────────

def _tool_get_zone_status(zone_id: str) -> Dict[str, Any]:
    """Get the current status of a single building zone."""
    zone_id = zone_id.lower().strip()
    if zone_id not in VALID_ZONES:
        return {"error": f"Unknown zone '{zone_id}'. Valid zones: {sorted(VALID_ZONES)}"}

    metrics = state_store.current_metrics
    if not metrics:
        return {"status": "simulation_not_started", "zone_id": zone_id}

    zone_data = metrics.get("zones", {}).get(zone_id, {})
    controls  = state_store.current_controls
    hvac_sp   = controls.get("hvac_setpoints", {}).get(zone_id, 22.0)
    light_lvl = controls.get("lighting_levels", {}).get(zone_id, 80.0)
    vent_rate = controls.get("ventilation_rates", {}).get(zone_id, 0.01)

    return {
        "zone_id": zone_id,
        "temperature_c": zone_data.get("temperature", 0),
        "pmv": zone_data.get("pmv", 0),
        "co2_ppm": zone_data.get("co2_ppm", 0),
        "occupancy_count": zone_data.get("occupancy", 0),
        "hvac_power_kw": zone_data.get("hvac_kw", 0),
        "lighting_power_kw": zone_data.get("lighting_kw", 0),
        "equipment_power_kw": zone_data.get("equipment_kw", 0),
        "current_setpoint_c": hvac_sp,
        "current_lighting_pct": light_lvl,
        "current_ventilation_m3s": vent_rate,
    }


def _tool_get_all_zones_status() -> Dict[str, Any]:
    """Get a complete snapshot of all 5 building zones plus building totals."""
    metrics = state_store.current_metrics
    if not metrics:
        return {"status": "simulation_not_started"}

    zones_out = {}
    for z in ZONES:
        zones_out[z] = _tool_get_zone_status(z)

    return {
        "hour": metrics.get("hour", 0),
        "outdoor_temp_c": metrics.get("outdoor_temp", 0),
        "occupancy_fraction": metrics.get("occupancy_fraction", 0),
        "zones": zones_out,
        "building_totals": metrics.get("totals", {}),
        "comfort_summary": metrics.get("comfort", {}),
        "simulation_source": metrics.get("_source", "physics_mock"),
    }


def _tool_get_energy_metrics() -> Dict[str, Any]:
    """Get current energy consumption, carbon emissions, cost, and savings vs baseline."""
    summary = state_store.get_summary()
    metrics = state_store.current_metrics
    totals  = metrics.get("totals", {}) if metrics else {}

    energy_price   = float(os.environ.get("ENERGY_PRICE_PER_KWH", "0.12"))
    carbon_factor  = float(os.environ.get("CARBON_FACTOR_KG_PER_KWH", "0.485"))
    cumulative_kwh = totals.get("cumulative_energy_kwh", 0)

    return {
        "current_load_kw": totals.get("total_kw", 0),
        "hvac_kw": totals.get("hvac_kw", 0),
        "lighting_kw": totals.get("lighting_kw", 0),
        "equipment_kw": totals.get("equipment_kw", 0),
        "cumulative_energy_kwh": cumulative_kwh,
        "cumulative_carbon_kg": totals.get("cumulative_carbon_kg", 0),
        "estimated_cost_usd": round(cumulative_kwh * energy_price, 2),
        "energy_saved_pct": summary.get("energy_saved_pct", 0),
        "carbon_saved_pct": summary.get("carbon_saved_pct", 0),
        "baseline_energy_kwh": summary.get("baseline_energy_kwh", 0),
        "goals": {
            "daily_energy_budget_kwh": OPTIMIZATION_GOALS["daily_energy_budget_kwh"],
            "daily_carbon_limit_kg": OPTIMIZATION_GOALS["daily_carbon_limit_kg"],
            "carbon_factor_kg_per_kwh": carbon_factor,
        },
    }


def _tool_get_optimization_goals() -> Dict[str, Any]:
    """Return the building's energy, comfort, and carbon optimization targets."""
    return {
        "goals": OPTIMIZATION_GOALS,
        "current_hour": state_store.simulation_hour,
        "description": (
            "Minimize total energy use (target <350 kWh/day, ~22% below 450 kWh baseline). "
            "Maintain ASHRAE 55 thermal comfort (PMV -0.5 to +0.5). "
            "Reduce carbon emissions below 170 kg CO₂/day. "
            "Keep indoor CO₂ below 1000 ppm at all times."
        ),
    }


def _tool_get_weather_forecast() -> Dict[str, Any]:
    """Get the next 4-hour weather forecast (temperature and solar radiation estimate)."""
    hour = state_store.simulation_hour
    forecast = []
    for dh in range(1, 5):
        h = (hour + dh) % 24
        temp = outdoor_temperature(h)
        solar_est = max(0, 800 * math.sin(math.pi * (h - 6) / 12)) if 6 <= h <= 18 else 0
        forecast.append({
            "hour": h,
            "outdoor_temp_c": round(temp, 1),
            "solar_radiation_wm2": round(solar_est, 0),
            "is_peak_solar": 10 <= h <= 15,
        })
    return {
        "current_hour": hour,
        "forecast_hours": forecast,
        "note": "Simplified sinusoidal model — New Delhi climate reference (hot-dry summer)",
    }


def _tool_get_occupancy_schedule() -> Dict[str, Any]:
    """Get predicted occupancy for the next 2 hours."""
    hour = state_store.simulation_hour
    schedule = []
    for dh in range(3):
        h = (hour + dh) % 24
        frac = occupancy_fraction(h)
        schedule.append({
            "hour": h,
            "occupancy_fraction": round(frac, 2),
            "expected_people_total": int(70 * frac),  # 70-person building max
            "period": (
                "night" if h < 7 or h >= 20 else
                "ramp_up" if h < 9 else
                "lunch" if 12 <= h < 13 else
                "peak"
            ),
        })
    return {"current_hour": hour, "schedule": schedule}


def _tool_get_optimization_history(n: int = 5) -> Dict[str, Any]:
    """Get the last N AI optimization decisions with reasoning and energy impact."""
    n = max(1, min(n, 24))
    history = state_store.action_history[-n:]
    all_hist = state_store.action_history
    llm_count = sum(1 for d in all_hist if d.get("mode") in ("llm", "groq+mcp", "ollama"))
    llm_rate = llm_count / max(1, len(all_hist)) * 100
    return {
        "count": len(history),
        "decisions": history,
        "llm_success_rate": f"{llm_rate:.1f}%",
    }


def _tool_set_hvac_setpoint(zone_id: str, setpoint_c: float) -> Dict[str, Any]:
    """Set the HVAC cooling/heating setpoint for a zone (18–28°C)."""
    zone_id = zone_id.lower().strip()
    if zone_id not in VALID_ZONES:
        return {"error": f"Unknown zone: {zone_id}"}
    safe = clamp_setpoints({zone_id: setpoint_c})
    actual = safe.get(zone_id, setpoint_c)
    state_store.current_controls["hvac_setpoints"][zone_id] = actual
    return {
        "status": "ok",
        "zone_id": zone_id,
        "setpoint_applied_c": actual,
        "clamped": actual != setpoint_c,
        "energy_impact": (
            "lower setpoint = more cooling energy | "
            "higher setpoint during low occupancy = energy savings"
        ),
    }


def _tool_set_hvac_mode(zone_id: str, mode: str) -> Dict[str, Any]:
    """Set HVAC operating mode: cooling | heating | eco | off."""
    zone_id = zone_id.lower().strip()
    mode    = mode.lower().strip()
    if zone_id not in VALID_ZONES:
        return {"error": f"Unknown zone: {zone_id}"}
    if mode not in VALID_HVAC_MODES:
        return {"error": f"Invalid mode '{mode}'. Must be one of: {sorted(VALID_HVAC_MODES)}"}

    # Map mode to setpoint adjustment
    mode_setpoints = {"cooling": 22.0, "heating": 20.0, "eco": 26.0, "off": 28.0}
    sp = mode_setpoints[mode]
    state_store.current_controls["hvac_setpoints"][zone_id] = sp

    if mode == "eco":
        # Also raise ventilation slightly for eco
        current_vent = state_store.current_controls["ventilation_rates"].get(zone_id, 0.01)
        state_store.current_controls["ventilation_rates"][zone_id] = max(0.006, current_vent * 0.8)

    return {"status": "ok", "zone_id": zone_id, "mode": mode, "setpoint_c": sp}


def _tool_set_lighting_level(zone_id: str, level_pct: float) -> Dict[str, Any]:
    """Set lighting dimming level for a zone (0–100%). 0% = off, 100% = maximum."""
    zone_id = zone_id.lower().strip()
    if zone_id not in VALID_ZONES:
        return {"error": f"Unknown zone: {zone_id}"}
    safe = clamp_lighting({zone_id: level_pct})
    actual = safe.get(zone_id, level_pct)
    state_store.current_controls["lighting_levels"][zone_id] = actual

    from simulation.building_sim import ZONE_AREA, MAX_LIGHTING_DENSITY
    power_saved_w = ZONE_AREA.get(zone_id, 100) * MAX_LIGHTING_DENSITY * (1.0 - actual / 100.0)
    return {
        "status": "ok",
        "zone_id": zone_id,
        "level_applied_pct": actual,
        "estimated_power_saving_w": round(power_saved_w, 1),
    }


def _tool_set_ventilation_rate(zone_id: str, rate_m3s: float) -> Dict[str, Any]:
    """Set fresh air ventilation rate for a zone (m³/s per person, ASHRAE 62.1: 0.006–0.025)."""
    zone_id = zone_id.lower().strip()
    if zone_id not in VALID_ZONES:
        return {"error": f"Unknown zone: {zone_id}"}
    safe = clamp_ventilation({zone_id: rate_m3s})
    actual = safe.get(zone_id, rate_m3s)
    state_store.current_controls["ventilation_rates"][zone_id] = actual
    return {
        "status": "ok",
        "zone_id": zone_id,
        "rate_applied_m3s": actual,
        "ashrae_minimum": 0.006,
        "clamped": actual != rate_m3s,
    }


def _tool_trigger_demand_response(zones: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Emergency demand response — shed non-critical loads immediately.
    Raises HVAC setpoints to 26°C and dims lighting to 30% in specified zones.
    If zones is empty or None, applies to ALL zones.
    """
    target_zones = [z.lower().strip() for z in (zones or [])]
    target_zones = [z for z in target_zones if z in VALID_ZONES] or list(VALID_ZONES)

    actions_applied = []
    for z in target_zones:
        state_store.current_controls["hvac_setpoints"][z] = 26.0
        state_store.current_controls["lighting_levels"][z] = 30.0
        state_store.current_controls["ventilation_rates"][z] = 0.006  # ASHRAE min
        actions_applied.append(z)

    return {
        "status": "demand_response_activated",
        "zones_affected": actions_applied,
        "hvac_setpoint_c": 26.0,
        "lighting_pct": 30.0,
        "ventilation_m3s": 0.006,
        "estimated_load_reduction_pct": 25,
        "timestamp": datetime.utcnow().isoformat(),
    }


def _tool_get_comfort_score() -> Dict[str, Any]:
    """Get zone-by-zone and overall building comfort scores (0–100, higher is better)."""
    metrics = state_store.current_metrics
    if not metrics:
        return {"status": "simulation_not_started"}

    from simulation.building_sim import _comfort_score
    zone_scores = {}
    for z in ZONES:
        zd = metrics.get("zones", {}).get(z, {})
        pmv = zd.get("pmv", 0)
        co2 = zd.get("co2_ppm", 400)
        zone_scores[z] = {
            "comfort_score": _comfort_score(pmv, co2),
            "pmv": pmv,
            "co2_ppm": co2,
            "temperature_c": zd.get("temperature", 0),
            "occupancy": zd.get("occupancy", 0),
            "pmv_ok": -0.5 <= pmv <= 0.5,
            "co2_ok": co2 < 1000,
        }

    overall = metrics.get("comfort", {})
    return {
        "overall_comfort_score": overall.get("comfort_score", 0),
        "overall_pmv": overall.get("avg_pmv", 0),
        "overall_co2_ppm": overall.get("avg_co2", 0),
        "ashrae_compliant": -0.5 <= overall.get("avg_pmv", 0) <= 0.5,
        "zones": zone_scores,
        "goal_comfort_score": 85.0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Register tools with FastMCP (when official SDK is available)
# ─────────────────────────────────────────────────────────────────────────────

if MCP_AVAILABLE and mcp is not None:

    @mcp.tool()
    def get_zone_status(zone_id: str) -> dict:
        """
        Get the current real-time status of a single building zone.
        Returns: temperature (°C), PMV comfort index, CO2 (ppm),
        occupancy count, HVAC/lighting/equipment power draw (kW),
        and current control setpoints.
        """
        return _tool_get_zone_status(zone_id)

    @mcp.tool()
    def get_all_zones_status() -> dict:
        """
        Get a complete snapshot of all 5 building zones (north, south, east, west, core)
        plus building totals. Use this for the initial observation step.
        """
        return _tool_get_all_zones_status()

    @mcp.tool()
    def get_energy_metrics() -> dict:
        """
        Get current energy consumption (kW), cumulative energy (kWh),
        carbon emissions (kg CO₂), cost ($), and percentage savings vs baseline.
        """
        return _tool_get_energy_metrics()

    @mcp.tool()
    def get_optimization_goals() -> dict:
        """
        Get the building's optimization targets: daily energy budget (kWh),
        ASHRAE 55 PMV comfort bounds, CO₂ limit (ppm), and carbon emission limit (kg/day).
        """
        return _tool_get_optimization_goals()

    @mcp.tool()
    def get_weather_forecast() -> dict:
        """
        Get the next 4-hour weather forecast including outdoor temperature (°C)
        and solar radiation estimate (W/m²). Use for predictive pre-cooling/heating.
        """
        return _tool_get_weather_forecast()

    @mcp.tool()
    def get_occupancy_schedule() -> dict:
        """
        Get predicted occupancy fraction and headcount for the next 2 hours.
        Use for proactive setback scheduling in low-occupancy periods.
        """
        return _tool_get_occupancy_schedule()

    @mcp.tool()
    def get_optimization_history(n: int = 5) -> dict:
        """
        Get the last N AI optimization decisions with reasoning text, actions taken,
        and energy impact. Use to avoid repeating recent decisions.
        """
        return _tool_get_optimization_history(n)

    @mcp.tool()
    def set_hvac_setpoint(zone_id: str, setpoint_c: float) -> dict:
        """
        Set the HVAC temperature setpoint for a zone (18–28°C).
        Lower = more cooling energy. Higher during low occupancy = energy savings.
        Automatically clamped to ASHRAE-compliant range.
        """
        return _tool_set_hvac_setpoint(zone_id, setpoint_c)

    @mcp.tool()
    def set_hvac_mode(zone_id: str, mode: str) -> dict:
        """
        Set the HVAC operating mode for a zone.
        Modes: 'cooling' (22°C), 'heating' (20°C), 'eco' (26°C), 'off' (28°C).
        """
        return _tool_set_hvac_mode(zone_id, mode)

    @mcp.tool()
    def set_lighting_level(zone_id: str, level_pct: float) -> dict:
        """
        Set the lighting dimming level for a zone (0–100%).
        0% = off (unoccupied). Dim perimeter zones during daylight hours.
        """
        return _tool_set_lighting_level(zone_id, level_pct)

    @mcp.tool()
    def set_ventilation_rate(zone_id: str, rate_m3s: float) -> dict:
        """
        Set the fresh air ventilation rate for a zone (m³/s per person).
        ASHRAE 62.1 minimum: 0.006. Maximum: 0.025.
        Increase if CO₂ > 800 ppm. Reduce in low-occupancy periods.
        """
        return _tool_set_ventilation_rate(zone_id, rate_m3s)

    @mcp.tool()
    def trigger_demand_response(zones: Optional[List[str]] = None) -> dict:
        """
        Activate emergency demand response load shedding.
        Raises HVAC to 26°C and dims lighting to 30% in specified zones.
        Pass an empty list or None to apply to all zones.
        """
        return _tool_trigger_demand_response(zones)

    @mcp.tool()
    def get_comfort_score() -> dict:
        """
        Get zone-by-zone and overall building comfort scores (0–100).
        Includes PMV, CO₂, temperature, ASHRAE 55 compliance flag per zone.
        """
        return _tool_get_comfort_score()


# ─────────────────────────────────────────────────────────────────────────────
# Tool schema for OpenAI-compatible function calling (Groq / Ollama)
# Used by the agent when calling Groq's API directly
# ─────────────────────────────────────────────────────────────────────────────

OPENAI_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_zone_status",
            "description": "Get real-time status of a single building zone: temp, PMV, CO2, occupancy, power draw, setpoints.",
            "parameters": {
                "type": "object",
                "properties": {
                    "zone_id": {
                        "type": "string",
                        "enum": ["north", "south", "east", "west", "core"],
                        "description": "Zone identifier",
                    }
                },
                "required": ["zone_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_all_zones_status",
            "description": "Get complete snapshot of all 5 zones plus building totals. Use for initial observation.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_energy_metrics",
            "description": "Get current energy (kW), cumulative kWh, carbon kg CO₂, cost, and % savings vs baseline.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_optimization_goals",
            "description": "Get building optimization targets: energy budget, PMV bounds, CO₂ limit, carbon limit.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather_forecast",
            "description": "Get next 4-hour weather: outdoor temperature and solar radiation. Use for predictive pre-cooling.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_occupancy_schedule",
            "description": "Get predicted occupancy for next 2 hours. Use for proactive setback scheduling.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_optimization_history",
            "description": "Get last N AI decisions with reasoning and energy impact.",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {
                        "type": "integer",
                        "description": "Number of past decisions to retrieve (1–24)",
                        "default": 3,
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_hvac_setpoint",
            "description": "Set HVAC setpoint for a zone (18–28°C). Higher during low occupancy saves energy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "zone_id": {
                        "type": "string",
                        "enum": ["north", "south", "east", "west", "core"],
                    },
                    "setpoint_c": {
                        "type": "number",
                        "description": "Target temperature in Celsius (18.0–28.0)",
                    },
                },
                "required": ["zone_id", "setpoint_c"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_hvac_mode",
            "description": "Set HVAC mode: cooling|heating|eco|off. Eco raises setpoint to 26°C.",
            "parameters": {
                "type": "object",
                "properties": {
                    "zone_id": {
                        "type": "string",
                        "enum": ["north", "south", "east", "west", "core"],
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["cooling", "heating", "eco", "off"],
                    },
                },
                "required": ["zone_id", "mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_lighting_level",
            "description": "Set lighting level for a zone (0–100%). 0% for unoccupied zones.",
            "parameters": {
                "type": "object",
                "properties": {
                    "zone_id": {
                        "type": "string",
                        "enum": ["north", "south", "east", "west", "core"],
                    },
                    "level_pct": {
                        "type": "number",
                        "description": "Dimming level 0–100%",
                    },
                },
                "required": ["zone_id", "level_pct"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_ventilation_rate",
            "description": "Set ventilation rate (m³/s per person, ASHRAE min 0.006). Increase if CO₂>800ppm.",
            "parameters": {
                "type": "object",
                "properties": {
                    "zone_id": {
                        "type": "string",
                        "enum": ["north", "south", "east", "west", "core"],
                    },
                    "rate_m3s": {
                        "type": "number",
                        "description": "Ventilation rate in m³/s per person (0.006–0.025)",
                    },
                },
                "required": ["zone_id", "rate_m3s"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_demand_response",
            "description": "Emergency load shedding: raises HVAC to 26°C, dims lighting to 30% in zones.",
            "parameters": {
                "type": "object",
                "properties": {
                    "zones": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["north", "south", "east", "west", "core"]},
                        "description": "Zones to apply demand response. Empty = all zones.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_comfort_score",
            "description": "Get zone-by-zone comfort scores (0–100) including PMV, CO₂, ASHRAE compliance.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Universal tool dispatcher (used by agent regardless of MCP availability)
# ─────────────────────────────────────────────────────────────────────────────

TOOL_REGISTRY = {
    "get_zone_status":         lambda args: _tool_get_zone_status(**args),
    "get_all_zones_status":    lambda args: _tool_get_all_zones_status(),
    "get_energy_metrics":      lambda args: _tool_get_energy_metrics(),
    "get_optimization_goals":  lambda args: _tool_get_optimization_goals(),
    "get_weather_forecast":    lambda args: _tool_get_weather_forecast(),
    "get_occupancy_schedule":  lambda args: _tool_get_occupancy_schedule(),
    "get_optimization_history":lambda args: _tool_get_optimization_history(**args),
    "set_hvac_setpoint":       lambda args: _tool_set_hvac_setpoint(**args),
    "set_hvac_mode":           lambda args: _tool_set_hvac_mode(**args),
    "set_lighting_level":      lambda args: _tool_set_lighting_level(**args),
    "set_ventilation_rate":    lambda args: _tool_set_ventilation_rate(**args),
    "trigger_demand_response": lambda args: _tool_trigger_demand_response(**args),
    "get_comfort_score":       lambda args: _tool_get_comfort_score(),
}


def call_tool(tool_name: str, args: dict) -> dict:
    """Universal tool dispatcher — call any MCP tool by name with arguments."""
    handler = TOOL_REGISTRY.get(tool_name)
    if not handler:
        return {"error": f"Unknown tool: {tool_name}. Available: {list(TOOL_REGISTRY.keys())}"}
    try:
        return handler(args)
    except Exception as e:
        logger.error("Tool '%s' error: %s", tool_name, e, exc_info=True)
        return {"error": str(e), "tool": tool_name}
