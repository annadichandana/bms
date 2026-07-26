"""
Safety Module — Input Validation & Clamping
============================================
Ensures all LLM-generated control values stay within
physically and operationally safe ranges before being
applied to the building simulation.

Provides both simple clamping and audit-trail versions
that return a list of clamping events for the dashboard.
"""

from typing import Dict, List, Tuple

# ── Safe ranges ───────────────────────────────────────────────────────────────

SETPOINT_MIN = 18.0   # °C  (below this risks condensation/freezing)
SETPOINT_MAX = 28.0   # °C  (above this violates ASHRAE 55 comfort)

LIGHTING_MIN = 0.0    # %   (fully off — allowed in unoccupied zones)
LIGHTING_MAX = 100.0  # %

VENTILATION_MIN = 0.006   # m³/s per person (ASHRAE 62.1 minimum)
VENTILATION_MAX = 0.025   # m³/s per person (economizer max)

VALID_ZONES = {"north", "south", "east", "west", "core"}


# ── Simple clamping (original API preserved) ──────────────────────────────────

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


# ── Audit clamping (returns events for the VALIDATE dashboard stage) ──────────

def clamp_setpoints_with_audit(
    proposed: Dict[str, float],
) -> Tuple[Dict[str, float], List[dict]]:
    """
    Clamp HVAC setpoints and return an audit trail of every clamped value.

    Returns:
        (clamped_dict, events_list)
        events_list contains one entry per zone where clamping occurred.
    """
    clamped: Dict[str, float] = {}
    events: List[dict] = []

    for zone, temp in proposed.items():
        if zone not in VALID_ZONES:
            continue
        raw = float(temp)
        safe = round(max(SETPOINT_MIN, min(SETPOINT_MAX, raw)), 1)
        clamped[zone] = safe
        if abs(safe - raw) > 0.05:
            events.append({
                "zone": zone,
                "type": "hvac",
                "proposed": round(raw, 1),
                "applied": safe,
                "limit": f"{SETPOINT_MIN}–{SETPOINT_MAX}°C",
                "reason": (
                    f"HVAC setpoint {raw:.1f}°C clamped to {safe:.1f}°C "
                    f"(ASHRAE operating range {SETPOINT_MIN}°C–{SETPOINT_MAX}°C)"
                ),
            })

    return clamped, events


def clamp_lighting_with_audit(
    proposed: Dict[str, float],
) -> Tuple[Dict[str, float], List[dict]]:
    """Clamp lighting levels and return an audit trail."""
    clamped: Dict[str, float] = {}
    events: List[dict] = []

    for zone, lvl in proposed.items():
        if zone not in VALID_ZONES:
            continue
        raw = float(lvl)
        safe = round(max(LIGHTING_MIN, min(LIGHTING_MAX, raw)), 1)
        clamped[zone] = safe
        if abs(safe - raw) > 0.1:
            events.append({
                "zone": zone,
                "type": "lighting",
                "proposed": round(raw, 1),
                "applied": safe,
                "limit": f"{LIGHTING_MIN}–{LIGHTING_MAX}%",
                "reason": (
                    f"Lighting level {raw:.1f}% clamped to {safe:.1f}% "
                    f"(valid range {LIGHTING_MIN}%–{LIGHTING_MAX}%)"
                ),
            })

    return clamped, events


def clamp_ventilation_with_audit(
    proposed: Dict[str, float],
) -> Tuple[Dict[str, float], List[dict]]:
    """Clamp ventilation rates and return an audit trail."""
    clamped: Dict[str, float] = {}
    events: List[dict] = []

    for zone, rate in proposed.items():
        if zone not in VALID_ZONES:
            continue
        raw = float(rate)
        safe = round(max(VENTILATION_MIN, min(VENTILATION_MAX, raw)), 4)
        clamped[zone] = safe
        if abs(safe - raw) > 1e-5:
            events.append({
                "zone": zone,
                "type": "ventilation",
                "proposed": round(raw, 4),
                "applied": safe,
                "limit": f"{VENTILATION_MIN}–{VENTILATION_MAX} m³/s",
                "reason": (
                    f"Ventilation rate {raw:.4f} m³/s clamped to {safe:.4f} m³/s "
                    f"(ASHRAE 62.1 bounds {VENTILATION_MIN}–{VENTILATION_MAX} m³/s)"
                ),
            })

    return clamped, events
