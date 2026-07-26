"""
Safety Module — Input Validation & Clamping
============================================
Ensures all LLM-generated control values stay within
physically and operationally safe ranges before being
applied to the building simulation.
"""

from typing import Dict

# ── Safe ranges ───────────────────────────────────────────────────────────────

SETPOINT_MIN = 18.0   # °C  (below this risks condensation/freezing)
SETPOINT_MAX = 28.0   # °C  (above this violates ASHRAE 55 comfort)

LIGHTING_MIN = 0.0    # %   (fully off — allowed in unoccupied zones)
LIGHTING_MAX = 100.0  # %

VENTILATION_MIN = 0.006   # m³/s per person (ASHRAE 62.1 minimum)
VENTILATION_MAX = 0.025   # m³/s per person (economizer max)

VALID_ZONES = {"north", "south", "east", "west", "core"}


def clamp_setpoints(setpoints: Dict[str, float]) -> Dict[str, float]:
    """Clamp HVAC setpoints to safe temperature range."""
    return {
        zone: round(max(SETPOINT_MIN, min(SETPOINT_MAX, float(temp))), 1)
        for zone, temp in setpoints.items()
        if zone in VALID_ZONES
    }


def clamp_lighting(levels: Dict[str, float]) -> Dict[str, float]:
    """Clamp lighting levels to 0-100%."""
    return {
        zone: round(max(LIGHTING_MIN, min(LIGHTING_MAX, float(lvl))), 1)
        for zone, lvl in levels.items()
        if zone in VALID_ZONES
    }


def clamp_ventilation(rates: Dict[str, float]) -> Dict[str, float]:
    """Clamp ventilation rates to ASHRAE 62.1 bounds."""
    return {
        zone: round(max(VENTILATION_MIN, min(VENTILATION_MAX, float(rate))), 4)
        for zone, rate in rates.items()
        if zone in VALID_ZONES
    }


def validate_llm_actions(actions: dict) -> dict:
    """
    Validate and sanitize the full action dict from the LLM.
    Returns a cleaned dict with only safe values.
    """
    safe = {}
    if "hvac_setpoints" in actions and isinstance(actions["hvac_setpoints"], dict):
        safe["hvac_setpoints"] = clamp_setpoints(actions["hvac_setpoints"])
    if "lighting_levels" in actions and isinstance(actions["lighting_levels"], dict):
        safe["lighting_levels"] = clamp_lighting(actions["lighting_levels"])
    if "ventilation_rates" in actions and isinstance(actions["ventilation_rates"], dict):
        safe["ventilation_rates"] = clamp_ventilation(actions["ventilation_rates"])
    return safe
