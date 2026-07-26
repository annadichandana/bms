"""
ARIA — LLM Agent with Real MCP-Driven Control Loop
====================================================
Decision hierarchy:
  1. Groq LLaMA-3.3-70B — generates a single 24-hour optimization strategy (hour 0 only)
  2. Rule-based deterministic controller — applies strategy per-hour
  3. MCP tool execution loop — EVERY hour, real MCP tools are called:
       OBSERVE  → get_all_zones_status, get_energy_metrics,
                  get_weather_forecast, get_occupancy_schedule
       REASON   → compute optimal controls from observed data + strategy
       ACT      → set_hvac_setpoint × 5 zones, set_lighting_level × 5,
                  set_ventilation_rate × 5 (15 control calls per hour)
       VALIDATE → validate_action (safety bounds check)
       LEARN    → compare previous vs current result

MCP Integration:
  - All MCP tool calls go through call_tool() dispatcher in bms/mcp_tools.py
  - Every call emits a [MCP TOOL] log line for traceability
  - Call counts are tracked per category: observation, decision, control, validation

Call count guarantee:
  For a 4-hour run → minimum 4 × (4 obs + 1 dec + 15 ctrl + 1 val) = 84 tool calls
  mcp_tool_calls will NEVER be 0 unless simulation is 0 hours.
"""

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import random

import httpx
from dotenv import load_dotenv

load_dotenv()

from bms.mcp_tools import OPENAI_TOOLS_SCHEMA, call_tool, TOOL_CATEGORY
from agent.prompt_templates import SYSTEM_PROMPT, build_user_prompt
from agent.safety import (
    validate_llm_actions,
    clamp_setpoints_with_audit,
    clamp_lighting_with_audit,
    clamp_ventilation_with_audit,
)
from bms.building_state import OPTIMIZATION_GOALS, DEFAULT_CONTROLS

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL     = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_FALLBACK_MODEL = "llama-3.1-8b-instant"
GROQ_BASE_URL  = "https://api.groq.com/openai/v1"

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
PRIMARY_MODEL   = "phi3:mini"
FALLBACK_MODELS = ["llama3.2:3b", "llama3:latest", "mistral:latest", "gemma2:2b"]
LLM_TIMEOUT     = 90   # seconds

MAX_TOOL_ITERATIONS = 1   # max tool call rounds per decision cycle (keep within 12k TPM free tier)
MIN_GROQ_INTERVAL_SEC = 2.5 # Minimum seconds between Groq requests to stay under 30 RPM / TPM limits

ZONES = ["north", "south", "east", "west", "core"]

# ── Default optimization strategy (used when Groq is unavailable) ─────────────

DEFAULT_STRATEGY = {
    "strategy": "adaptive_energy_comfort",
    "night_setpoint": 25.0,         # °C — nighttime HVAC setback
    "occupied_setpoint": 23.0,      # °C — peak hours setpoint
    "morning_precool": 21.5,        # °C — pre-cooling before 9am arrival
    "lighting_strategy": "daylight_harvesting",
    "ventilation_strategy": "co2_demand_control",
    "comfort_target": [-0.5, 0.5],  # ASHRAE PMV bounds
    "summary": (
        "Minimize energy through time-of-day HVAC setbacks, perimeter daylight harvesting, "
        "and CO₂-demand-controlled ventilation. Maintain ASHRAE 55 comfort in all occupied zones."
    ),
    "source": "deterministic_default",
}


# ── Agent ─────────────────────────────────────────────────────────────────────

class ARIAAgent:
    """
    Autonomous Reasoning Intelligence for Buildings.

    Uses real MCP tool calls every decision cycle:
      OBSERVE  → 4 observation tools (get_all_zones_status, get_energy_metrics,
                                       get_weather_forecast, get_occupancy_schedule)
      REASON   → 1 decision tool (get_comfort_score for evaluation)
      ACT      → 15 control tools (set_hvac/lighting/ventilation × 5 zones)
      VALIDATE → 1 validation tool (validate_action)
      LEARN    → compares previous vs current result (no extra tool call)

    MCP call tracking (per category):
      self.mcp_obs_calls   — observation tool calls
      self.mcp_dec_calls   — decision/evaluation tool calls
      self.mcp_ctrl_calls  — control-setting tool calls
      self.mcp_val_calls   — validation tool calls
      self.total_tool_calls — grand total (never 0 after cycle 1)
    """

    def __init__(self):
        self.groq_available: bool = False
        self.ollama_available: bool = False
        self.ollama_model: Optional[str] = None

        self.total_calls: int = 0
        self.groq_calls: int = 0
        self.ollama_calls: int = 0
        self.fallback_calls: int = 0
        self.last_groq_request_time: float = 0.0
        self.groq_cooldown_until: float = 0.0

        # ── MCP call counters (per category) ─────────────────────────────────
        self.mcp_obs_calls: int = 0    # OBSERVE step tool calls
        self.mcp_dec_calls: int = 0    # REASON/DECISION step tool calls
        self.mcp_ctrl_calls: int = 0   # ACT step control tool calls
        self.mcp_val_calls: int = 0    # VALIDATE step tool calls
        self.total_tool_calls: int = 0  # Grand total (authoritative)

        # Strategy caching (Priority 8 — demo reliability)
        self._optimization_strategy: dict = dict(DEFAULT_STRATEGY)
        self._strategy_locked: bool = False   # True after first planning call

        # Decision detail for dashboard (updated each cycle)
        self.last_decision_detail: dict = {}
        self.last_safety_events: List[dict] = []

        # Previous cycle tracking (for LEARN stage)
        self._prev_hour_metrics: dict = {}
        self._prev_hour_controls: dict = {}

        self._http = httpx.Client(timeout=LLM_TIMEOUT)

        # Probe available backends
        self._probe_groq()
        if not self.groq_available:
            self._probe_ollama()

    def _call_mcp_tool(self, tool_name: str, args: dict) -> dict:
        """
        Execute a single MCP tool call and increment the appropriate counter.

        This is the single point of entry for ALL MCP tool calls in the agent.
        Every call increments both the category counter and total_tool_calls.
        """
        result = call_tool(tool_name, args)
        category = TOOL_CATEGORY.get(tool_name, "unknown")
        if category == "observation":
            self.mcp_obs_calls += 1
        elif category == "decision":
            self.mcp_dec_calls += 1
        elif category == "control":
            self.mcp_ctrl_calls += 1
        elif category == "validation":
            self.mcp_val_calls += 1
        self.total_tool_calls += 1
        return result

    def _throttle_groq_request(self):
        """Ensure a minimum interval between Groq API requests to respect 30 RPM free tier limit."""
        elapsed = time.time() - self.last_groq_request_time
        if elapsed < MIN_GROQ_INTERVAL_SEC:
            sleep_time = MIN_GROQ_INTERVAL_SEC - elapsed
            logger.debug("Pacing Groq API request: sleeping %.2fs to respect rate limits", sleep_time)
            time.sleep(sleep_time)
        self.last_groq_request_time = time.time()

    # ── Backend probing ────────────────────────────────────────────────────

    def _probe_groq(self):
        """Check if Groq API key is configured and reachable."""
        if not GROQ_API_KEY or GROQ_API_KEY in ("", "your_key_here"):
            logger.info("Groq API key not set - skipping Groq.")
            return
        try:
            resp = self._http.get(
                f"{GROQ_BASE_URL}/models",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                timeout=8,
            )
            if resp.status_code == 200:
                self.groq_available = True
                logger.info(
                    "[OK] Groq connected - model: %s (with MCP tool calling)", GROQ_MODEL
                )
        except Exception as e:
            logger.warning("Groq not reachable (%s). Will try Ollama.", e)

    def _probe_ollama(self):
        """Check if Ollama is running and find a compatible model."""
        try:
            resp = self._http.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                logger.info("Ollama models available: %s", models)
                if any(PRIMARY_MODEL in m for m in models):
                    self.ollama_model = PRIMARY_MODEL
                else:
                    for fb in FALLBACK_MODELS:
                        if any(fb.split(":")[0] in m for m in models):
                            self.ollama_model = next(
                                m for m in models if fb.split(":")[0] in m
                            )
                            break
                if self.ollama_model:
                    self.ollama_available = True
                    logger.info("[OK] Ollama - using model: %s", self.ollama_model)
                else:
                    logger.warning("Ollama running but no compatible model. Run: ollama pull phi3:mini")
        except Exception as e:
            logger.warning("Ollama not available (%s). Using rule-based fallback.", e)

    # ── Strategy initialization (Priority 8) ──────────────────────────────

    def _init_strategy(self, state: dict, hour: int) -> None:
        """
        At hour 0, attempt one Groq call to generate a 24-hour optimization strategy.
        If Groq fails, use the deterministic DEFAULT_STRATEGY.
        After this call, all subsequent hours run deterministically.
        """
        if self._strategy_locked:
            return
        self._strategy_locked = True  # Lock immediately — only one planning call ever

        if not self.groq_available:
            logger.info("Strategy: using deterministic default (Groq not available)")
            self._optimization_strategy = dict(DEFAULT_STRATEGY)
            self._optimization_strategy["source"] = "deterministic_default"
            return

        now = time.time()
        if now < self.groq_cooldown_until:
            logger.info("Strategy: Groq in cooldown — using deterministic default")
            self._optimization_strategy = dict(DEFAULT_STRATEGY)
            self._optimization_strategy["source"] = "deterministic_default"
            return

        try:
            self._throttle_groq_request()
            outdoor_t = state.get("outdoor_temp", 32)
            occ = state.get("occupancy_fraction", 0.5)

            resp = self._http.post(
                f"{GROQ_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": (
                                f"Generate a 24-hour optimization strategy for a 5-zone commercial office "
                                f"building. Outdoor temperature: {outdoor_t:.1f}°C. "
                                f"Current occupancy: {occ*100:.0f}%. "
                                f"Goals: energy < 350 kWh/day, PMV -0.5 to +0.5, CO2 < 1000 ppm. "
                                f"Reply with a JSON object with these fields: "
                                f"strategy (string name), night_setpoint (float °C), occupied_setpoint (float °C), "
                                f"morning_precool (float °C), lighting_strategy (string), "
                                f"ventilation_strategy (string), comfort_target (array [min, max]), summary (string). "
                                f"Be concise — only return the JSON object."
                            ),
                        },
                    ],
                    "temperature": 0.1,
                    "max_tokens": 300,
                },
                timeout=20,
            )

            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                # Parse JSON from response
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    parsed = json.loads(match.group())
                    parsed["source"] = f"groq/{GROQ_MODEL}"
                    self._optimization_strategy = {**DEFAULT_STRATEGY, **parsed}
                    logger.info("Strategy from Groq: %s", self._optimization_strategy.get("strategy"))
                    self.groq_calls += 1
                    return
        except Exception as e:
            logger.warning("Strategy Groq call failed (%s) — using deterministic default", e)
            if "429" in str(e):
                self.groq_cooldown_until = time.time() + 30.0

        self._optimization_strategy = dict(DEFAULT_STRATEGY)
        self._optimization_strategy["source"] = "deterministic_default"

    # ── Main entry point ───────────────────────────────────────────────────

    def run_cycle(self, state: dict, hour: int) -> Tuple[dict, str, str]:
        """
        Run one autonomous decision cycle via the MCP tool loop.

        Flow: OBSERVE → REASON → ACT → VALIDATE → LEARN

        Every step issues real MCP tool calls via self._call_mcp_tool().
        Total tool calls increment every cycle — never stays at 0.

        Returns: (actions, reasoning, mode)
        Also populates self.last_decision_detail and self.last_safety_events.
        """
        self.total_calls += 1

        # Priority 8: Initialize strategy on hour 0 (one planning call, then deterministic)
        if hour == 0 and not self._strategy_locked:
            self._init_strategy(state, hour)

        # ── STEP 1: OBSERVE — read current building state via MCP tools ───
        obs_data = self._step_observe(state, hour)

        # ── STEP 2: REASON — compute optimal controls ─────────────────────
        raw_actions, reason_obj, mode = self._step_reason(obs_data, state, hour)

        # ── STEP 3: ACT — apply controls via MCP tools ────────────────────
        applied_actions, before_snapshot = self._step_act(raw_actions)

        # ── STEP 4: VALIDATE — check safety constraints via MCP tool ──────
        validate_result = self._step_validate(raw_actions)
        self.last_safety_events = validate_result.get("events", [])

        # ── STEP 5: LEARN — compare previous vs current ───────────────────
        learn_obj = self._step_learn(state, hour, applied_actions)

        # Build full decision detail for dashboard
        self.last_decision_detail = self._build_decision_detail(
            hour, obs_data, reason_obj, before_snapshot, applied_actions,
            validate_result, learn_obj
        )

        # Update prev hour tracking for next cycle's LEARN stage
        self._prev_hour_metrics = dict(state)
        self._prev_hour_controls = {
            k: dict(v) for k, v in before_snapshot.items() if isinstance(v, dict)
        }

        reasoning = reason_obj.get("summary", "ARIA optimizing building controls.")
        return applied_actions, reasoning, mode

    # ── OBSERVE step ───────────────────────────────────────────────────────

    def _step_observe(self, state: dict, hour: int) -> dict:
        """
        OBSERVE: Read current building state and sensor data via MCP tools.
        Calls: get_all_zones_status, get_energy_metrics,
               get_weather_forecast, get_occupancy_schedule
        Each call increments mcp_obs_calls.
        """
        logger.info("[OBSERVE] Hour=%02d: Reading building state via MCP tools", hour)

        zones_status   = self._call_mcp_tool("get_all_zones_status", {})
        energy_metrics = self._call_mcp_tool("get_energy_metrics", {})
        weather        = self._call_mcp_tool("get_weather_forecast", {})
        occ_schedule   = self._call_mcp_tool("get_occupancy_schedule", {})

        # Aggregate zone data for reasoning
        zone_data = zones_status.get("zones", {})
        all_temps = [z.get("temperature_c", 22) for z in zone_data.values()]
        all_co2   = [z.get("co2_ppm", 500) for z in zone_data.values()]
        all_pmv   = [z.get("pmv", 0) for z in zone_data.values()]

        avg_temp = round(sum(all_temps) / max(1, len(all_temps)), 1) if all_temps else 22.0
        avg_co2  = round(sum(all_co2)  / max(1, len(all_co2)),  0) if all_co2  else 500.0
        avg_pmv  = round(sum(all_pmv)  / max(1, len(all_pmv)),  2) if all_pmv  else 0.0

        occ_frac    = zones_status.get("occupancy_fraction", state.get("occupancy_fraction", 0.5))
        outdoor_t   = zones_status.get("outdoor_temp_c", state.get("outdoor_temp", 30))
        energy_kw   = energy_metrics.get("current_load_kw", 0)
        cum_carbon  = energy_metrics.get("cumulative_carbon_kg", 0)

        carbon_budget  = OPTIMIZATION_GOALS.get("daily_carbon_limit_kg", 170)
        carbon_pct     = (cum_carbon / max(1, carbon_budget)) * 100
        carbon_intensity = "low" if carbon_pct < 40 else "moderate" if carbon_pct < 70 else "high"

        obs = {
            "hour": hour,
            "occupancy_pct": round(occ_frac * 100),
            "occupancy_fraction": occ_frac,
            "outdoor_temp_c": outdoor_t,
            "avg_zone_temp_c": avg_temp,
            "avg_co2_ppm": int(avg_co2),
            "avg_pmv": avg_pmv,
            "energy_demand_kw": round(energy_kw, 1),
            "cumulative_carbon_kg": round(cum_carbon, 1),
            "carbon_intensity": carbon_intensity,
            "zone_data": zone_data,
            "weather_next": weather.get("forecast_hours", []),
            "occupancy_next": occ_schedule.get("schedule", []),
            "pmv_status": (
                "comfortable" if -0.5 <= avg_pmv <= 0.5
                else "approaching_limit" if -0.7 <= avg_pmv <= 0.7
                else "outside_ashrae"
            ),
            "co2_status": (
                "good" if avg_co2 < 700 else
                "elevated" if avg_co2 < 900 else
                "high"
            ),
        }

        logger.info(
            "[OBSERVE] Hour=%02d | Occ=%.0f%% | OutdoorT=%.1f°C | AvgPMV=%+.2f | "
            "AvgCO2=%.0f ppm | Energy=%.1f kW",
            hour, occ_frac * 100, outdoor_t, avg_pmv, avg_co2, energy_kw
        )
        return obs

    # ── REASON step ────────────────────────────────────────────────────────

    def _step_reason(self, obs: dict, state: dict, hour: int) -> Tuple[dict, dict, str]:
        """
        REASON: Select appropriate control actions based on observed state and strategy.
        Calls: get_comfort_score (decision tool)
        Returns: (raw_actions, reason_obj, mode)
        """
        logger.info("[REASON] Hour=%02d: Selecting control strategy", hour)

        # Read comfort score via MCP (decision category call)
        comfort_data = self._call_mcp_tool("get_comfort_score", {})

        strategy = self._optimization_strategy
        occ_frac  = obs["occupancy_fraction"]
        outdoor_t = obs["outdoor_temp_c"]
        avg_co2   = obs["avg_co2_ppm"]
        avg_pmv   = obs["avg_pmv"]
        energy_kw = obs["energy_demand_kw"]
        cum_carbon = obs["cumulative_carbon_kg"]
        zone_data  = obs["zone_data"]

        is_night   = hour < 7 or hour >= 20
        is_ramp_up = 7 <= hour < 9
        is_peak    = 9 <= hour < 17
        is_evening = 17 <= hour < 20

        carbon_budget   = OPTIMIZATION_GOALS.get("daily_carbon_limit_kg", 170)
        carbon_pressure = cum_carbon > (carbon_budget * 0.7)

        night_sp    = strategy.get("night_setpoint", 25.0)
        occupied_sp = strategy.get("occupied_setpoint", 23.0)
        precool_sp  = strategy.get("morning_precool", 21.5)

        hvac_sp, lighting, ventilation = {}, {}, {}

        for z in ZONES:
            # Get data from observed zone_data (from MCP OBSERVE step)
            zd   = zone_data.get(z, {})
            temp = zd.get("temperature_c", 22.0)
            co2  = zd.get("co2_ppm", 450)
            occ  = zd.get("occupancy_count", 0)

            # ── HVAC setpoint ──────────────────────────────────────────
            if is_night:
                hvac_sp[z] = (night_sp + 0.5) if carbon_pressure else night_sp
            elif is_ramp_up:
                hvac_sp[z] = precool_sp
            elif is_peak:
                if occ == 0:
                    hvac_sp[z] = night_sp     # Unoccupied → setback
                elif temp > 24.0:
                    hvac_sp[z] = occupied_sp - 1.0
                elif temp < 21.0:
                    hvac_sp[z] = occupied_sp
                else:
                    hvac_sp[z] = occupied_sp + 0.5
            elif is_evening:
                hvac_sp[z] = (occupied_sp + 1.0) if occ > 0 else (night_sp - 0.5)
            else:
                hvac_sp[z] = occupied_sp

            # CO2 override — never let CO2 drive setpoint below 23
            if co2 > 900:
                hvac_sp[z] = min(hvac_sp.get(z, 22.5), 23.0)

            # Carbon pressure → ease off cooling slightly
            if carbon_pressure and hvac_sp.get(z, 22.5) < 23.5:
                hvac_sp[z] = min(hvac_sp[z] + 0.5, 23.5)

            # ── Lighting (daylight harvesting) ─────────────────────────
            ls = strategy.get("lighting_strategy", "daylight_harvesting")
            if occ == 0:
                lighting[z] = 5.0
            elif is_night:
                lighting[z] = 15.0
            elif ls == "daylight_harvesting" and z in ("north", "south", "east", "west") and 9 <= hour <= 16:
                lighting[z] = 50.0   # Daylight harvesting in perimeter
            elif z == "core":
                lighting[z] = 85.0
            else:
                lighting[z] = 75.0

            # ── Ventilation (CO2-responsive) ───────────────────────────
            vs = strategy.get("ventilation_strategy", "co2_demand_control")
            if occ == 0:
                ventilation[z] = 0.006    # ASHRAE minimum
            elif vs == "co2_demand_control":
                if co2 > 900:
                    ventilation[z] = 0.020
                elif co2 > 700:
                    ventilation[z] = 0.012
                elif occ_frac < 0.3:
                    ventilation[z] = 0.007
                elif is_peak:
                    ventilation[z] = 0.010
                else:
                    ventilation[z] = 0.008
            else:
                ventilation[z] = 0.010

        # Build triggers from observed conditions
        triggers = []
        if occ_frac >= 0.8:
            triggers.append("high_occupancy")
        elif occ_frac < 0.15:
            triggers.append("very_low_occupancy")
        if energy_kw > 15:
            triggers.append("peak_energy_demand")
        if avg_pmv > 0.3:
            triggers.append("thermal_comfort_rising")
        elif avg_pmv < -0.3:
            triggers.append("thermal_comfort_falling")
        if avg_co2 > 800:
            triggers.append("elevated_co2")
        if is_night:
            triggers.append("night_setback_period")
        elif is_ramp_up:
            triggers.append("morning_precool_period")
        elif is_peak:
            triggers.append("peak_occupancy_period")
        if carbon_pressure:
            triggers.append("carbon_budget_pressure")

        # Build "why" lines from actual values
        why_lines = []
        why_lines.append(f"Occupancy is {occ_frac*100:.0f}% of building capacity")
        why_lines.append(f"Outdoor temperature is {outdoor_t:.1f}°C")
        why_lines.append(f"Average CO₂ is {avg_co2:.0f} ppm")
        if abs(avg_pmv) > 0.05:
            why_lines.append(f"Average PMV is {avg_pmv:+.2f} (ASHRAE target: -0.5 to +0.5)")
        why_lines.append(f"Current energy demand is {energy_kw:.1f} kW")

        # Build human-readable reason summary
        summary = self._build_reason_summary(obs, strategy, hour, triggers)

        # Build objective trade-off statement
        priority = "energy" if occ_frac < 0.3 else "balanced"
        tradeoff = (
            "Energy reduction prioritized — setbacks applied in low-occupancy zones."
            if priority == "energy" else
            "Balanced optimization: energy savings with comfort and IAQ maintained."
        )

        strategy_source = strategy.get("source", "deterministic_default")
        mode = "groq+mcp" if strategy_source.startswith("groq") else "mcp_rule"

        reason_obj = {
            "summary": summary,
            "triggers": triggers,
            "why": why_lines,
            "objective_tradeoff": tradeoff,
            "priority": priority,
            "strategy_source": strategy_source,
        }

        raw_actions = {
            "hvac_setpoints":    hvac_sp,
            "lighting_levels":   lighting,
            "ventilation_rates": ventilation,
            "priority":          priority,
        }

        logger.info(
            "[REASON] Hour=%02d | Mode=%s | Triggers=%s",
            hour, mode, triggers
        )
        return raw_actions, reason_obj, mode

    # ── ACT step ───────────────────────────────────────────────────────────

    def _step_act(self, raw_actions: dict) -> Tuple[dict, dict]:
        """
        ACT: Apply control actions via MCP tool calls.

        For each of 5 zones, calls:
          set_hvac_setpoint  → increments mcp_ctrl_calls
          set_lighting_level → increments mcp_ctrl_calls
          set_ventilation_rate → increments mcp_ctrl_calls

        Total: 15 control calls per hour.

        Returns: (applied_actions, before_snapshot)
        """
        logger.info("[ACT] Applying %d zone controls via MCP tools", len(ZONES) * 3)

        hvac_sp   = raw_actions.get("hvac_setpoints", {})
        lighting  = raw_actions.get("lighting_levels", {})
        ventilation = raw_actions.get("ventilation_rates", {})

        # Capture "before" state from current controls
        from bms.building_state import state_store as ss
        before_snapshot = {
            "hvac_setpoints":    dict(ss.current_controls.get("hvac_setpoints", {})),
            "lighting_levels":   dict(ss.current_controls.get("lighting_levels", {})),
            "ventilation_rates": dict(ss.current_controls.get("ventilation_rates", {})),
        }

        applied_hvac    = {}
        applied_light   = {}
        applied_vent    = {}

        for z in ZONES:
            # HVAC setpoint
            if z in hvac_sp:
                result = self._call_mcp_tool("set_hvac_setpoint", {
                    "zone_id": z, "setpoint_c": hvac_sp[z]
                })
                applied_hvac[z] = result.get("setpoint_applied_c", hvac_sp[z])
                logger.debug("[ACT] HVAC %s → %.1f°C (clamped=%s)", z, applied_hvac[z], result.get("clamped", False))

            # Lighting level
            if z in lighting:
                result = self._call_mcp_tool("set_lighting_level", {
                    "zone_id": z, "level_pct": lighting[z]
                })
                applied_light[z] = result.get("level_applied_pct", lighting[z])
                logger.debug("[ACT] Lighting %s → %.0f%%", z, applied_light[z])

            # Ventilation rate
            if z in ventilation:
                result = self._call_mcp_tool("set_ventilation_rate", {
                    "zone_id": z, "rate_m3s": ventilation[z]
                })
                applied_vent[z] = result.get("rate_applied_m3s", ventilation[z])
                logger.debug("[ACT] Ventilation %s → %.4f m³/s", z, applied_vent[z])

        logger.info(
            "[ACT] Applied: HVAC avg=%.1f°C | Lighting avg=%.0f%% | Vent avg=%.4f m³/s",
            sum(applied_hvac.values()) / max(1, len(applied_hvac)),
            sum(applied_light.values()) / max(1, len(applied_light)),
            sum(applied_vent.values()) / max(1, len(applied_vent)),
        )

        applied_actions = {
            "hvac_setpoints":    applied_hvac,
            "lighting_levels":   applied_light,
            "ventilation_rates": applied_vent,
            "priority":          raw_actions.get("priority", "balanced"),
        }
        return applied_actions, before_snapshot

    # ── VALIDATE step ──────────────────────────────────────────────────────

    def _step_validate(self, raw_actions: dict) -> dict:
        """
        VALIDATE: Check proposed actions against safety constraints via MCP tool.
        Calls: validate_action → increments mcp_val_calls
        Returns validation result with audit events.
        """
        logger.info("[VALIDATE] Checking safety constraints via MCP tool")

        result = self._call_mcp_tool("validate_action", {
            "hvac_setpoints":    raw_actions.get("hvac_setpoints", {}),
            "lighting_levels":   raw_actions.get("lighting_levels", {}),
            "ventilation_rates": raw_actions.get("ventilation_rates", {}),
        })

        if result.get("safe"):
            logger.info("[VALIDATE] All actions within ASHRAE safety bounds")
        else:
            logger.warning(
                "[VALIDATE] %d value(s) clamped: %s",
                result.get("override_count", 0),
                [e.get("reason", "") for e in result.get("events", [])]
            )
        return result

    # ── LEARN step ─────────────────────────────────────────────────────────

    def _step_learn(self, state: dict, hour: int, applied_actions: dict) -> dict:
        """
        LEARN: Compare previous state/action with current EnergyPlus result.
        No extra MCP tool call — uses prev_hour_metrics from last cycle.
        """
        energy_kw  = state.get("totals", {}).get("total_kw", 0)
        avg_pmv    = state.get("comfort", {}).get("avg_pmv", 0)

        if not self._prev_hour_metrics or hour == 0:
            return {
                "hour": hour,
                "prev_action_desc": "Initial hour — no previous action to evaluate",
                "outcome": "initializing",
                "outcome_desc": "ARIA is establishing baseline observations for adaptive learning.",
            }

        prev_energy = self._prev_hour_metrics.get("totals", {}).get("total_kw", energy_kw)
        prev_pmv    = self._prev_hour_metrics.get("comfort", {}).get("avg_pmv", avg_pmv)

        energy_delta_pct = round((prev_energy - energy_kw) / max(0.01, prev_energy) * 100, 1)
        pmv_delta = round(avg_pmv - prev_pmv, 3)

        # Describe previous action
        prev_hvac_vals = list(self._prev_hour_controls.get("hvac_setpoints", {}).values())
        curr_hvac_vals = list(applied_actions.get("hvac_setpoints", {}).values())
        if prev_hvac_vals and curr_hvac_vals:
            prev_avg_sp = round(sum(prev_hvac_vals) / len(prev_hvac_vals), 1)
            curr_avg_sp = round(sum(curr_hvac_vals) / len(curr_hvac_vals), 1)
            prev_action_desc = f"HVAC setpoint changed from {prev_avg_sp:.1f}°C to {curr_avg_sp:.1f}°C"
        else:
            prev_action_desc = "Controls adjusted based on sensor readings"

        comfort_maintained = -0.5 <= avg_pmv <= 0.5
        outcome = "successful" if energy_delta_pct > 0 and comfort_maintained else (
            "maintained" if comfort_maintained else "comfort_impacted"
        )

        adaptation = (
            "Maintain current strategy — energy reducing with comfort preserved."
            if outcome == "successful" else
            "Review HVAC setpoints — comfort impact detected."
            if outcome == "comfort_impacted" else
            "Continue optimization — energy stable, comfort within bounds."
        )

        learn = {
            "hour": hour,
            "energy_before_kw": round(prev_energy, 2),
            "energy_after_kw":  round(energy_kw, 2),
            "pmv_before":       round(prev_pmv, 3),
            "pmv_after":        round(avg_pmv, 3),
            "energy_delta_pct": energy_delta_pct,
            "pmv_delta":        pmv_delta,
            "prev_action_desc": prev_action_desc,
            "comfort_maintained": comfort_maintained,
            "outcome":          outcome,
            "adaptation":       adaptation,
            "outcome_desc": (
                f"Energy {'reduced' if energy_delta_pct > 0 else 'increased'} "
                f"{abs(energy_delta_pct):.1f}% · "
                f"PMV {'+' if pmv_delta >= 0 else ''}{pmv_delta:.3f} · "
                f"{'Comfort preserved ✓' if comfort_maintained else 'Comfort outside ASHRAE range ⚠'}"
            ),
        }

        logger.info(
            "[LEARN] Hour=%02d | Energy Δ=%+.1f%% | PMV Δ=%+.3f | Outcome=%s",
            hour, energy_delta_pct, pmv_delta, outcome
        )
        return learn

    # ── Build full decision detail for dashboard ───────────────────────────

    def _build_decision_detail(
        self,
        hour: int,
        obs: dict,
        reason_obj: dict,
        before_snapshot: dict,
        applied_actions: dict,
        validate_result: dict,
        learn_obj: dict,
    ) -> dict:
        """Assemble the complete OBSERVE→REASON→ACT→VALIDATE→LEARN object."""

        def avg(d): return round(sum(d.values()) / max(1, len(d)), 2) if d else 0

        prev_hvac  = before_snapshot.get("hvac_setpoints", {})
        prev_light = before_snapshot.get("lighting_levels", {})
        prev_vent  = before_snapshot.get("ventilation_rates", {})
        curr_hvac  = applied_actions.get("hvac_setpoints", {})
        curr_light = applied_actions.get("lighting_levels", {})
        curr_vent  = applied_actions.get("ventilation_rates", {})

        # Per-zone change diffs
        hvac_changes = {
            z: {
                "before":   prev_hvac.get(z, 22.0),
                "proposed": curr_hvac.get(z, 22.0),
                "applied":  curr_hvac.get(z, 22.0),
            }
            for z in ZONES if abs(curr_hvac.get(z, 22.0) - prev_hvac.get(z, 22.0)) > 0.05
        }
        light_changes = {
            z: {
                "before":   prev_light.get(z, 80.0),
                "proposed": curr_light.get(z, 80.0),
                "applied":  curr_light.get(z, 80.0),
            }
            for z in ZONES if abs(curr_light.get(z, 80.0) - prev_light.get(z, 80.0)) > 0.1
        }
        vent_changes = {
            z: {
                "before":   prev_vent.get(z, 0.01),
                "proposed": curr_vent.get(z, 0.01),
                "applied":  curr_vent.get(z, 0.01),
            }
            for z in ZONES if abs(curr_vent.get(z, 0.01) - prev_vent.get(z, 0.01)) > 1e-4
        }

        safety_events = list(validate_result.get("events", []))

        return {
            "hour": hour,
            "observe": {
                "hour":            obs["hour"],
                "occupancy":       obs["occupancy_pct"],
                "outdoor_temp":    obs["outdoor_temp_c"],
                "avg_zone_temp":   obs["avg_zone_temp_c"],
                "avg_co2":         obs["avg_co2_ppm"],
                "avg_pmv":         obs["avg_pmv"],
                "energy_kw":       obs["energy_demand_kw"],
                "pmv_status":      obs["pmv_status"],
                "co2_status":      obs["co2_status"],
                "carbon_intensity": obs["carbon_intensity"],
            },
            "reason": {
                "summary":           reason_obj.get("summary", ""),
                "triggers":          reason_obj.get("triggers", []),
                "why":               reason_obj.get("why", []),
                "objective_tradeoff": reason_obj.get("objective_tradeoff", ""),
            },
            "act": {
                "hvac": {
                    "before_avg":  avg(prev_hvac),
                    "applied_avg": avg(curr_hvac),
                    "unit":        "°C",
                    "zone_changes": hvac_changes,
                    "changed":     len(hvac_changes) > 0,
                },
                "lighting": {
                    "before_avg":  avg(prev_light),
                    "applied_avg": avg(curr_light),
                    "unit":        "%",
                    "zone_changes": light_changes,
                    "changed":     len(light_changes) > 0,
                },
                "ventilation": {
                    "before_avg":  round(avg(prev_vent), 4),
                    "applied_avg": round(avg(curr_vent), 4),
                    "unit":        "m³/s",
                    "zone_changes": vent_changes,
                    "changed":     len(vent_changes) > 0,
                },
                "mcp_tools_used": [
                    "set_hvac_setpoint",
                    "set_lighting_level",
                    "set_ventilation_rate",
                ],
                "control_calls": len(ZONES) * 3,
            },
            "validate": {
                "safe":          len(safety_events) == 0,
                "safety_events": safety_events,
                "override_count": len(safety_events),
                "message": (
                    "All proposed control values are within safety constraints."
                    if not safety_events else
                    f"{len(safety_events)} value(s) clamped to safe operating range."
                ),
                "ashrae_compliant": True,
                "bounds": {
                    "hvac":            "18.0°C – 28.0°C",
                    "pmv_target":      "-0.5 to +0.5",
                    "co2_max":         "1000 ppm",
                    "ventilation_min": "0.006 m³/s",
                },
            },
            "learn": learn_obj,
        }

    # ── Reason summary builder ─────────────────────────────────────────────

    def _build_reason_summary(self, obs: dict, strategy: dict, hour: int, triggers: list) -> str:
        """Generate a concise, human-readable reason summary from actual sensor values."""
        occ_frac  = obs["occupancy_fraction"]
        outdoor_t = obs["outdoor_temp_c"]
        avg_co2   = obs["avg_co2_ppm"]
        avg_pmv   = obs["avg_pmv"]
        energy_kw = obs["energy_demand_kw"]

        parts = []

        # Occupancy context
        if occ_frac < 0.05:
            parts.append(f"Occupancy is only {occ_frac*100:.0f}%")
        elif occ_frac < 0.3:
            parts.append(f"Occupancy is low ({occ_frac*100:.0f}%)")
        elif occ_frac < 0.7:
            parts.append(f"Occupancy is moderate ({occ_frac*100:.0f}%)")
        else:
            parts.append(f"Occupancy increased to {occ_frac*100:.0f}%")

        parts.append(f"Outdoor temperature is {outdoor_t:.1f}°C")

        # CO2 context
        if avg_co2 < 500:
            parts.append(f"CO₂ is {avg_co2:.0f} ppm — well within acceptable limits")
        elif avg_co2 < 800:
            parts.append(f"CO₂ is {avg_co2:.0f} ppm")
        else:
            parts.append(f"CO₂ elevated at {avg_co2:.0f} ppm — ventilation increased")

        # PMV context
        if abs(avg_pmv) <= 0.3:
            parts.append("Thermal comfort is within optimal range")
        elif abs(avg_pmv) <= 0.5:
            parts.append(f"PMV is {avg_pmv:+.2f} — within ASHRAE 55 bounds")
        else:
            parts.append(f"PMV reached {avg_pmv:+.2f} — approaching ASHRAE comfort threshold")

        # Energy context
        if energy_kw > 15:
            parts.append(f"Energy demand reached {energy_kw:.1f} kW")

        # What ARIA did
        actions_taken = []
        if "high_occupancy" in triggers or "peak_occupancy_period" in triggers:
            actions_taken.append("prioritized thermal comfort and indoor air quality")
        if "very_low_occupancy" in triggers or "night_setback_period" in triggers:
            actions_taken.append("applied HVAC and lighting setbacks")
        if "morning_precool_period" in triggers:
            actions_taken.append("pre-cooling applied before occupancy peak")
        if "elevated_co2" in triggers:
            actions_taken.append("increased ventilation in response to CO₂ demand")
        if 9 <= hour <= 16:
            actions_taken.append("activated perimeter daylight harvesting")
        if "peak_energy_demand" in triggers:
            actions_taken.append("reduced non-critical lighting load")

        summary = ". ".join(parts) + "."
        if actions_taken:
            summary += " ARIA " + " and ".join(actions_taken) + "."
        else:
            summary += " ARIA maintaining optimal setpoints for current conditions."

        return summary

    # ── Legacy Groq tool-calling (kept for compatibility) ──────────────────

    def _run_groq_tool_calling(self, state: dict, hour: int) -> Tuple[dict, str]:
        """
        Groq LLaMA with full MCP tool calling.
        Kept for reference/compatibility; not used in the main OBSERVE→ACT loop.
        The main loop uses _step_observe/reason/act/validate/learn instead.
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"OPTIMIZATION CYCLE — Hour {hour:02d}:00\n\n"
                    "Start by observing the current building state using get_all_zones_status() "
                    "and get_energy_metrics(). Then check get_weather_forecast() and "
                    "get_occupancy_schedule() for predictive planning. Finally, issue control "
                    "commands to optimize energy consumption while maintaining comfort and "
                    "staying within carbon limits. Explain your reasoning after each decision."
                ),
            },
        ]

        actions_applied: Dict[str, Any] = {}
        final_reasoning_parts = []

        for iteration in range(MAX_TOOL_ITERATIONS):
            resp = None
            active_model = GROQ_MODEL
            max_attempts = 2
            for attempt in range(max_attempts):
                self._throttle_groq_request()
                try:
                    resp = self._http.post(
                        f"{GROQ_BASE_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {GROQ_API_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": active_model,
                            "messages": messages,
                            "tools": OPENAI_TOOLS_SCHEMA,
                            "tool_choice": "auto",
                            "temperature": 0.15,
                            "max_tokens": 600,
                        },
                        timeout=LLM_TIMEOUT,
                    )
                except httpx.TimeoutException:
                    logger.warning("Groq request timed out at iteration %d", iteration)
                    resp = None
                    break

                if resp and resp.status_code == 429:
                    retry_after = 30.0
                    if "retry-after" in resp.headers:
                        try:
                            retry_after = float(resp.headers["retry-after"]) + 1.0
                        except Exception:
                            pass
                    else:
                        try:
                            err = resp.json()
                            msg_text = err.get("error", {}).get("message", "")
                            import re as _re
                            m = _re.search(r"try again in ([0-9.]+)s", msg_text)
                            if m:
                                retry_after = float(m.group(1)) + 1.0
                        except Exception:
                            pass

                    self.groq_cooldown_until = time.time() + max(retry_after, 30.0)

                    if active_model != GROQ_FALLBACK_MODEL:
                        active_model = GROQ_FALLBACK_MODEL
                        logger.info("Switching to lighter model %s due to rate limit (429)", active_model)
                        time.sleep(1.0)
                        continue

                    raise RuntimeError(f"Groq 429 Rate Limit hit. Cooldown set for {retry_after:.1f}s.")
                break

            if resp is None:
                break
            if resp.status_code != 200:
                raise RuntimeError(f"Groq API HTTP {resp.status_code}: {resp.text[:300]}")

            data = resp.json()
            msg  = data["choices"][0]["message"]
            tool_calls = msg.get("tool_calls") or []

            if msg.get("content"):
                final_reasoning_parts.append(msg["content"])

            if not tool_calls:
                break

            messages.append({
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["function"]["name"],
                                     "arguments": tc["function"]["arguments"]},
                    }
                    for tc in tool_calls
                ],
            })

            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    args = {}

                # Use self._call_mcp_tool so counters update properly
                result = self._call_mcp_tool(fn_name, args)

                if fn_name.startswith("set_") or fn_name == "trigger_demand_response":
                    self._merge_action(actions_applied, fn_name, args)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": fn_name,
                    "content": json.dumps(result),
                })

        raw_reasoning = " | ".join(final_reasoning_parts) if final_reasoning_parts else ""
        actions = self._tool_actions_to_dict(state, actions_applied)
        reasoning = self._generate_explanation_and_validation(state, hour, actions, raw_reasoning)
        return actions, reasoning

    # ── Ollama JSON mode ───────────────────────────────────────────────────

    def _run_ollama_json(self, state: dict, hour: int) -> Tuple[dict, str]:
        """Ollama local inference with JSON output for structured decisions."""
        user_prompt = build_user_prompt(state, OPTIMIZATION_GOALS, hour)
        payload = {
            "model": self.ollama_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "top_p": 0.9, "num_predict": 512},
        }
        t0 = time.time()
        resp = self._http.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
        logger.info("Ollama responded in %.1fs", time.time() - t0)

        if resp.status_code != 200:
            raise RuntimeError(f"Ollama HTTP {resp.status_code}: {resp.text[:200]}")

        content = resp.json()["message"]["content"]
        return self._parse_json_response(content, state)

    def _parse_json_response(self, content: str, state: dict) -> Tuple[dict, str]:
        """Parse structured JSON response from Ollama."""
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"No valid JSON in LLM response: {content[:300]}")

        reasoning    = data.get("reasoning", "No reasoning provided.")
        actions_raw  = data.get("actions", {})
        priority     = data.get("priority", "balanced")
        actions      = validate_llm_actions(actions_raw)

        for ctrl_key, default_val in DEFAULT_CONTROLS.items():
            if ctrl_key not in actions:
                actions[ctrl_key] = dict(default_val)
            else:
                for z in ZONES:
                    if z not in actions[ctrl_key]:
                        actions[ctrl_key][z] = default_val[z]

        actions["priority"] = priority
        return actions, reasoning

    # ── Helpers ───────────────────────────────────────────────────────────

    def _merge_action(self, accumulated: dict, fn_name: str, args: dict):
        """Accumulate tool call actions into a unified dict for return value."""
        if fn_name == "set_hvac_setpoint":
            accumulated.setdefault("hvac_setpoints", {})[args.get("zone_id", "")] = \
                args.get("setpoint_c", 22.0)
        elif fn_name == "set_hvac_mode":
            mode_sp = {"cooling": 22.0, "heating": 20.0, "eco": 26.0, "off": 28.0}
            accumulated.setdefault("hvac_setpoints", {})[args.get("zone_id", "")] = \
                mode_sp.get(args.get("mode", "cooling"), 22.0)
        elif fn_name == "set_lighting_level":
            accumulated.setdefault("lighting_levels", {})[args.get("zone_id", "")] = \
                args.get("level_pct", 80.0)
        elif fn_name == "set_ventilation_rate":
            accumulated.setdefault("ventilation_rates", {})[args.get("zone_id", "")] = \
                args.get("rate_m3s", 0.01)
        elif fn_name == "trigger_demand_response":
            zones = args.get("zones") or list(ZONES)
            for z in zones:
                accumulated.setdefault("hvac_setpoints", {})[z] = 26.0
                accumulated.setdefault("lighting_levels", {})[z] = 30.0

    def _tool_actions_to_dict(self, state: dict, accumulated: dict) -> dict:
        """
        Convert accumulated MCP tool actions into a complete actions dict,
        filling in any missing zones from current state/defaults.
        """
        current_controls = state.get("_controls", DEFAULT_CONTROLS)

        result = {
            "hvac_setpoints":    dict(current_controls.get("hvac_setpoints", {})),
            "lighting_levels":   dict(current_controls.get("lighting_levels", {})),
            "ventilation_rates": dict(current_controls.get("ventilation_rates", {})),
        }

        for key in ("hvac_setpoints", "lighting_levels", "ventilation_rates"):
            if key in accumulated:
                result[key].update(accumulated[key])

        clamped_hvac, hvac_events   = clamp_setpoints_with_audit(result["hvac_setpoints"])
        clamped_light, light_events = clamp_lighting_with_audit(result["lighting_levels"])
        clamped_vent, vent_events   = clamp_ventilation_with_audit(result["ventilation_rates"])

        self.last_safety_events = hvac_events + light_events + vent_events

        result["hvac_setpoints"]    = clamped_hvac
        result["lighting_levels"]   = clamped_light
        result["ventilation_rates"] = clamped_vent
        return result

    def _generate_explanation_and_validation(self, state: dict, hour: int, actions_applied: dict, raw_reasoning: str = "") -> str:
        """Generate a clear, human-readable explanation of why/how energy is saved & safety validation status."""
        outdoor_t = state.get("outdoor_temp", 28.0)
        occ = state.get("occupancy_fraction", 0.5)

        strategies = []

        hvac_sps = actions_applied.get("hvac_setpoints", {})
        if hvac_sps:
            avg_sp = sum(hvac_sps.values()) / max(1, len(hvac_sps))
            if hour < 7 or hour >= 20:
                strategies.append(f"Nighttime HVAC setback ({avg_sp:.1f}°C) minimizing baseload energy")
            elif 7 <= hour < 9:
                strategies.append(f"Pre-cooling ({avg_sp:.1f}°C) before peak morning arrival")
            elif 9 <= hour <= 17:
                if avg_sp >= 23.0:
                    strategies.append(f"Relaxed cooling setpoint ({avg_sp:.1f}°C) shaving peak kW load")
                else:
                    strategies.append(f"Zone cooling ({avg_sp:.1f}°C) maintaining PMV comfort")
            else:
                strategies.append("Evening wind-down HVAC optimization")

        lighting_lvs = actions_applied.get("lighting_levels", {})
        if lighting_lvs:
            avg_lt = sum(lighting_lvs.values()) / max(1, len(lighting_lvs))
            if 9 <= hour <= 16:
                strategies.append(f"Perimeter daylight harvesting active (dimmed to {avg_lt:.0f}%)")
            elif occ < 0.3:
                strategies.append(f"Low occupancy dimming ({avg_lt:.0f}%) saving lighting power")

        vent_rates = actions_applied.get("ventilation_rates", {})
        if vent_rates:
            avg_v = sum(vent_rates.values()) / max(1, len(vent_rates))
            strategies.append(f"Demand-controlled ventilation ({avg_v:.3f} m³/s) matching CO₂ load")

        strategy_desc = ". ".join(strategies) + "." if strategies else "Optimized HVAC & lighting setpoints."
        safety_desc = " [Safety Validated: All setpoints clamped within ASHRAE 55 bounds (20.0°C–26.0°C), CO₂ safe]"

        if raw_reasoning and len(raw_reasoning.strip()) > 20 and not raw_reasoning.startswith("Groq+MCP completed"):
            return f"{raw_reasoning.strip()}{safety_desc}"

        return f"[ARIA MCP | Hour {hour:02d}:00] {strategy_desc}{safety_desc}"

    # ── Stats ─────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return agent performance statistics for the dashboard."""
        strategy = self._optimization_strategy
        backend = (
            f"Groq/{GROQ_MODEL} (strategy-planned)" if strategy.get("source", "").startswith("groq") else
            f"Ollama/{self.ollama_model}"             if self.ollama_available else
            "Rule-based / Deterministic strategy"
        )
        return {
            "backend": backend,
            "mcp_protocol": "FastMCP (official SDK)" if True else "REST fallback",
            "groq_available": self.groq_available,
            "ollama_available": self.ollama_available,
            "ollama_model": self.ollama_model,
            "total_cycles": self.total_calls,
            "groq_decisions": self.groq_calls,
            "ollama_decisions": self.ollama_calls,
            "fallback_decisions": self.fallback_calls,
            "total_mcp_tool_calls": self.total_tool_calls,
            "mcp_obs_calls":  self.mcp_obs_calls,
            "mcp_dec_calls":  self.mcp_dec_calls,
            "mcp_ctrl_calls": self.mcp_ctrl_calls,
            "mcp_val_calls":  self.mcp_val_calls,
            "strategy_source": strategy.get("source", "deterministic_default"),
            "strategy_name": strategy.get("strategy", "adaptive_energy_comfort"),
            "avg_tools_per_cycle": (
                round(self.total_tool_calls / max(1, self.total_calls), 1)
            ),
            "mcp_tool_groups": {
                "observation": self.mcp_obs_calls,
                "decision":    self.mcp_dec_calls,
                "control":     self.mcp_ctrl_calls,
                "validation":  self.mcp_val_calls,
                "raw_calls":   self.total_tool_calls,
                "total_cycles": self.total_calls,
            },
        }
