"""
Prompt Templates — ARIA BMS Agent
===================================
System prompt and user context builder for the LLM decision cycle.

Key improvements over v1:
  - Explicit CARBON BUDGET goal with real-time tracking
  - Chain-of-thought reasoning steps enforced in system prompt
  - Multi-objective trade-off guidance (energy vs comfort vs carbon)
  - MCP tool-calling instructions for Groq mode
  - Compact JSON format for Ollama (small model compatibility)
"""

import json


# ─────────────────────────────────────────────────────────────────────────────
# System Prompt — Chain-of-Thought MCP Agent
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are ARIA — Autonomous Resource Intelligence Agent for Building Management Systems.
You autonomously control a 5-zone commercial office building (600 m², New Delhi climate).

═══════════════════════════════════════════════════════════════
  THREE OPTIMIZATION GOALS (ranked by current status)
═══════════════════════════════════════════════════════════════

1. 🔋 ENERGY: Keep daily energy consumption BELOW 350 kWh/day
   (Baseline: 450 kWh/day → target ≥22% reduction)

2. 🌡️  COMFORT: Maintain PMV between -0.5 and +0.5 (ASHRAE 55)
   - Temperature: 20–26°C per zone
   - CO₂: below 1000 ppm (ventilation-driven)
   - Comfort score: ≥85/100

3. 🌿 CARBON: Emit less than 170 kg CO₂/day
   (Grid factor: 0.485 kg CO₂/kWh — Indian grid)
   Monitor cumulative_carbon_kg vs budget progress hourly.

═══════════════════════════════════════════════════════════════
  ZONES & CONTROL AUTHORITY
═══════════════════════════════════════════════════════════════

Zones: north, south, east (perimeter — has windows & solar gain)
       west (perimeter), core (interior — no solar gain)

Controls available via MCP tools:
  • HVAC setpoints (°C, 18–28) — higher = less cooling energy
  • Lighting levels (%, 0–100) — 0% for unoccupied zones
  • Ventilation rates (m³/s/person, 0.006–0.025) — CO₂-responsive
  • Demand response — emergency load shedding (all zones)
  • HVAC mode — cooling | heating | eco | off

═══════════════════════════════════════════════════════════════
  DECISION PROCEDURE (follow every cycle)
═══════════════════════════════════════════════════════════════

Step 1 — OBSERVE: Call get_all_zones_status() + get_energy_metrics()
Step 2 — FORECAST: Call get_weather_forecast() + get_occupancy_schedule()
Step 3 — REASON: Analyze the data against all three goals:
          • Is energy pace on track for <350 kWh? (check energy_saved_pct)
          • Are any zones violating PMV or CO₂ comfort limits?
          • Is carbon accumulation within 170 kg/day budget?
          • What is the next 2 hours' occupancy profile?
          • What solar/thermal loads are incoming?
Step 4 — ACT: Issue control commands using set_* tools
          • Prioritize biggest energy savers: lighting dimming, HVAC setback
          • Never let PMV drop below -1.0 or rise above +1.0
          • If CO₂ > 900 ppm → increase ventilation immediately
          • If carbon budget >80% used → apply aggressive setbacks
Step 5 — EXPLAIN: After all tool calls, provide a concise summary of:
          • What you observed (key metrics)
          • What actions you took and why
          • Expected energy/comfort/carbon impact

═══════════════════════════════════════════════════════════════
  ENERGY STRATEGY CHEAT SHEET
═══════════════════════════════════════════════════════════════

Hour 00–06 (night):      Max setback — HVAC 26°C, lights 5–15%, min vent
Hour 07–08 (ramp-up):    Pre-cool to 21.5°C before occupants arrive
Hour 09–11 (peak AM):    Balance comfort — daylight harvest perimeter zones
Hour 12–13 (lunch):      Moderate setback (50% occ) — raise setpoints 0.5°C
Hour 14–16 (peak PM):    Manage west/east solar gain — check CO₂ carefully
Hour 17–19 (wind-down):  Progressive setback as occupancy drops
Hour 20–23 (night):      Maximum setback — aim for minimal overnight load

DAYLIGHT HARVESTING: dim north/south/east/west to 40–55% when solar radiation
is high (10:00–15:00). Core zone has no daylight — keep at 80–85%.

CARBON-AWARE OPERATION: When cumulative_carbon_kg exceeds 70% of daily budget,
apply extra 0.5°C HVAC setpoint increase and 10% additional lighting reduction.
"""


# ─────────────────────────────────────────────────────────────────────────────
# User Prompt Builder (for Ollama JSON mode)
# ─────────────────────────────────────────────────────────────────────────────

def build_user_prompt(state: dict, goals: dict, hour: int) -> str:
    """Build the per-epoch user prompt for Ollama JSON mode."""
    if not state:
        return "No simulation data yet. Apply default energy-saving settings for early morning."

    totals  = state.get("totals", {})
    comfort = state.get("comfort", {})
    zones   = state.get("zones", {})
    occ     = state.get("occupancy_fraction", 0)
    outdoor = state.get("outdoor_temp", 30)

    # Daily budget progress
    cum_energy = totals.get("cumulative_energy_kwh", 0)
    cum_carbon = totals.get("cumulative_carbon_kg", 0)
    energy_budget = goals.get("daily_energy_budget_kwh", 350)
    carbon_budget = goals.get("daily_carbon_limit_kg", 170)
    energy_pace   = (cum_energy / max(1, hour)) * 24 if hour > 0 else 0
    carbon_pace   = (cum_carbon / max(1, hour)) * 24 if hour > 0 else 0
    energy_status = "⚠️ OVER BUDGET PACE" if energy_pace > energy_budget else "✅ on track"
    carbon_status = "⚠️ OVER BUDGET PACE" if carbon_pace > carbon_budget else "✅ on track"

    # Time context
    contexts = [
        (range(0, 7),   "Night — minimal occupancy. MAXIMUM energy savings mode."),
        (range(7, 9),   "Morning ramp-up — occupancy rising. Pre-cool if outdoor is hot."),
        (range(9, 12),  "Peak AM — full occupancy. Balance comfort and energy carefully."),
        (range(12, 14), "Lunch — ~50% occupancy. Moderate setback opportunity."),
        (range(14, 17), "Peak PM — full occupancy. West/east solar gain building. Watch CO₂."),
        (range(17, 20), "Wind-down — occupancy falling. Begin progressive energy setback."),
        (range(20, 24), "Night — very low occupancy. Max savings mode."),
    ]
    time_ctx = next(
        (desc for rng, desc in contexts if hour in rng),
        "Transition period."
    )

    # Zone summary
    zone_lines = []
    for z, zd in zones.items():
        pmv_flag = "⚠️" if abs(zd.get("pmv", 0)) > 0.5 else ""
        co2_flag = "⚠️" if zd.get("co2_ppm", 0) > 800 else ""
        zone_lines.append(
            f"  {z:5s}: {zd.get('temperature', 0):.1f}°C  "
            f"PMV={zd.get('pmv', 0):+.2f}{pmv_flag}  "
            f"CO₂={zd.get('co2_ppm', 0):.0f}ppm{co2_flag}  "
            f"Occ={zd.get('occupancy', 0)}ppl  "
            f"HVAC={zd.get('hvac_kw', 0):.2f}kW  "
            f"Light={zd.get('lighting_kw', 0):.2f}kW"
        )

    prompt = f"""HOUR {hour:02d}:00 — {time_ctx}

━━━━ REAL-TIME STATE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Outdoor temp    : {outdoor:.1f}°C
  Occupancy       : {occ*100:.0f}% ({int(occ*70)} of 70 people)
  Current load    : {totals.get('total_kw', 0):.1f} kW

━━━━ BUDGET TRACKING ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Energy used     : {cum_energy:.1f} kWh  (24h pace: {energy_pace:.0f} kWh/day, budget {energy_budget} kWh/day) {energy_status}
  Carbon emitted  : {cum_carbon:.1f} kg CO₂  (24h pace: {carbon_pace:.0f} kg/day, limit {carbon_budget} kg/day) {carbon_status}

━━━━ ZONE STATUS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{chr(10).join(zone_lines)}

━━━━ COMFORT SUMMARY ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Avg temp        : {comfort.get('avg_temp', 0):.1f}°C    (target: 20–26°C)
  Avg PMV         : {comfort.get('avg_pmv', 0):+.2f}       (target: -0.5 to +0.5)
  Avg CO₂         : {comfort.get('avg_co2', 0):.0f} ppm  (limit: 1000 ppm)
  Comfort score   : {comfort.get('comfort_score', 0):.1f}/100  (goal: ≥85)

━━━━ CURRENT CONTROLS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  HVAC setpoints  : {json.dumps(state.get('_controls', {}).get('hvac_setpoints', {}))}
  Lighting levels : {json.dumps(state.get('_controls', {}).get('lighting_levels', {}))}
  Ventilation     : {json.dumps(state.get('_controls', {}).get('ventilation_rates', {}))}

Based on this data, decide the OPTIMAL control settings for the NEXT hour.
Reason explicitly about energy, comfort, AND carbon goals.

Respond with ONLY valid JSON (no markdown, no explanation outside JSON):
{{
  "reasoning": "2–4 sentences: what you observed, what you decided, why, expected impact on energy/carbon/comfort",
  "actions": {{
    "hvac_setpoints":    {{"north": 22.0, "south": 22.0, "east": 22.0, "west": 22.0, "core": 22.0}},
    "lighting_levels":  {{"north": 80.0, "south": 80.0, "east": 80.0, "west": 80.0, "core": 80.0}},
    "ventilation_rates":{{"north": 0.01, "south": 0.01, "east": 0.01, "west": 0.01, "core": 0.01}}
  }},
  "priority": "energy"
}}
priority: "energy" | "comfort" | "carbon" | "balanced"
"""
    return prompt
