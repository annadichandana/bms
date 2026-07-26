"""
ARIA — Upgraded LLM Agent with Groq Tool-Calling + MCP Integration
====================================================================
Decision hierarchy:
  1. Groq LLaMA-3.3-70B with OpenAI-compatible tool calling (via MCP tools schema)
  2. Ollama local (phi3:mini / llama3.2:3b) with JSON mode
  3. Rule-based fallback (always available, ASHRAE-compliant)

MCP Integration:
  - All tools are defined in mcp/mcp_tools.py using the official MCP SDK
  - The OPENAI_TOOLS_SCHEMA is passed to Groq for native function calling
  - Tool calls are executed via call_tool() dispatcher (same functions as MCP server)

Decision cycle (every simulated hour):
  1. Observe: call get_all_zones_status(), get_energy_metrics()
  2. Forecast: call get_weather_forecast(), get_occupancy_schedule()
  3. Reason: LLM reasons with chain-of-thought against all three goals:
             energy (<350 kWh/day), comfort (PMV -0.5 to +0.5), carbon (<170 kg/day)
  4. Act: LLM calls set_hvac_setpoint, set_lighting_level, set_ventilation_rate etc.
  5. Validate: Safety module clamps all values before applying
  6. Log: Decision + reasoning saved to state store and SQLite
"""

import json
import logging
import os
import re
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from mcp.mcp_tools import OPENAI_TOOLS_SCHEMA, call_tool
from agent.prompt_templates import SYSTEM_PROMPT, build_user_prompt
from agent.safety import validate_llm_actions
from mcp.building_state import OPTIMIZATION_GOALS, DEFAULT_CONTROLS

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL     = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_BASE_URL  = "https://api.groq.com/openai/v1"

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
PRIMARY_MODEL   = "phi3:mini"
FALLBACK_MODELS = ["llama3.2:3b", "llama3:latest", "mistral:latest", "gemma2:2b"]
LLM_TIMEOUT     = 90   # seconds

MAX_TOOL_ITERATIONS = 6   # max tool call rounds per decision cycle


# ── Agent ─────────────────────────────────────────────────────────────────────

class ARIAAgent:
    """
    Autonomous Reasoning Intelligence for Buildings.

    Uses MCP tool schemas for LLM function-calling, executes tools via
    the shared MCP tool dispatcher, and falls back gracefully when
    cloud/local LLMs are unavailable.
    """

    def __init__(self):
        self.groq_available: bool = False
        self.ollama_available: bool = False
        self.ollama_model: Optional[str] = None

        self.total_calls: int = 0
        self.groq_calls: int = 0
        self.ollama_calls: int = 0
        self.fallback_calls: int = 0
        self.total_tool_calls: int = 0

        self._http = httpx.Client(timeout=LLM_TIMEOUT)

        # Probe available backends
        self._probe_groq()
        if not self.groq_available:
            self._probe_ollama()

    # ── Backend probing ────────────────────────────────────────────────────

    def _probe_groq(self):
        """Check if Groq API key is configured and reachable."""
        if not GROQ_API_KEY or GROQ_API_KEY in ("", "your_key_here"):
            logger.info("Groq API key not set — skipping Groq.")
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
                    "✅ Groq connected — model: %s (with MCP tool calling)", GROQ_MODEL
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
                    logger.info("✅ Ollama — using model: %s", self.ollama_model)
                else:
                    logger.warning("Ollama running but no compatible model. Run: ollama pull phi3:mini")
        except Exception as e:
            logger.warning("Ollama not available (%s). Using rule-based fallback.", e)

    # ── Main entry point ───────────────────────────────────────────────────

    def run_cycle(self, state: dict, hour: int) -> Tuple[dict, str, str]:
        """
        Run one autonomous decision cycle.

        Observes state → reasons → calls MCP tools → returns (actions, reasoning, mode).
        """
        self.total_calls += 1

        if self.groq_available:
            try:
                actions, reasoning = self._run_groq_tool_calling(state, hour)
                self.groq_calls += 1
                return actions, reasoning, "groq+mcp"
            except Exception as e:
                logger.error("Groq tool-calling cycle failed: %s", e)

        if self.ollama_available and self.ollama_model:
            try:
                actions, reasoning = self._run_ollama_json(state, hour)
                self.ollama_calls += 1
                return actions, reasoning, "ollama"
            except Exception as e:
                logger.error("Ollama cycle failed: %s", e)

        actions, reasoning = self._rule_based_fallback(state, hour)
        self.fallback_calls += 1
        return actions, reasoning, "fallback"

    # ── Groq with MCP tool calling ─────────────────────────────────────────

    def _run_groq_tool_calling(self, state: dict, hour: int) -> Tuple[dict, str]:
        """
        Groq LLaMA-3.3-70B with full MCP tool calling.

        The agent autonomously:
          1. Observes all zones and energy metrics via tools
          2. Checks weather forecast and occupancy schedule
          3. Reasons about energy, comfort, and carbon goals
          4. Issues control commands via set_* tools
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
            try:
                resp = self._http.post(
                    f"{GROQ_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {GROQ_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": GROQ_MODEL,
                        "messages": messages,
                        "tools": OPENAI_TOOLS_SCHEMA,
                        "tool_choice": "auto",
                        "temperature": 0.15,
                        "max_tokens": 1024,
                    },
                    timeout=LLM_TIMEOUT,
                )
            except httpx.TimeoutException:
                logger.warning("Groq request timed out at iteration %d", iteration)
                break

            if resp.status_code != 200:
                raise RuntimeError(f"Groq API HTTP {resp.status_code}: {resp.text[:300]}")

            data = resp.json()
            msg  = data["choices"][0]["message"]
            tool_calls = msg.get("tool_calls") or []

            # Collect any text reasoning from this turn
            if msg.get("content"):
                final_reasoning_parts.append(msg["content"])

            # If no tool calls → LLM is done reasoning
            if not tool_calls:
                break

            # Append assistant message with tool calls
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

            # Execute each tool call
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    args = {}

                self.total_tool_calls += 1
                logger.debug("MCP tool call: %s(%s)", fn_name, args)
                result = call_tool(fn_name, args)

                # Track control actions for return value
                if fn_name.startswith("set_") or fn_name == "trigger_demand_response":
                    self._merge_action(actions_applied, fn_name, args)

                # Add tool result to conversation
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": fn_name,
                    "content": json.dumps(result),
                })

        reasoning = " | ".join(final_reasoning_parts) if final_reasoning_parts else (
            f"Groq+MCP completed {self.total_tool_calls} tool calls at hour {hour:02d}."
        )

        # Convert accumulated tool actions to the standard actions dict
        actions = self._tool_actions_to_dict(state, actions_applied)
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

        # Fill missing zones from defaults
        zones = ["north", "south", "east", "west", "core"]
        for ctrl_key, default_val in DEFAULT_CONTROLS.items():
            if ctrl_key not in actions:
                actions[ctrl_key] = dict(default_val)
            else:
                for z in zones:
                    if z not in actions[ctrl_key]:
                        actions[ctrl_key][z] = default_val[z]

        actions["priority"] = priority
        return actions, reasoning

    # ── Rule-based fallback ────────────────────────────────────────────────

    def _rule_based_fallback(self, state: dict, hour: int) -> Tuple[dict, str]:
        """
        Expert rule-based optimizer — always available as final fallback.
        Implements time-of-day, occupancy-based, CO2-responsive, and
        carbon-aware logic aligned with ASHRAE 55 and ASHRAE 62.1.
        """
        zones = ["north", "south", "east", "west", "core"]
        occ_frac    = (state or {}).get("occupancy_fraction", 0.5)
        zone_data   = (state or {}).get("zones", {})
        outdoor_t   = (state or {}).get("outdoor_temp", 30)
        cum_carbon  = (state or {}).get("totals", {}).get("cumulative_carbon_kg", 0)

        is_night    = hour < 7 or hour >= 20
        is_ramp_up  = 7 <= hour < 9
        is_peak     = 9 <= hour < 17
        is_evening  = 17 <= hour < 20

        # Carbon budget pressure (tighten setbacks if >70% of daily budget used)
        carbon_pressure = cum_carbon > (OPTIMIZATION_GOALS["daily_carbon_limit_kg"] * 0.7)

        hvac_sp, lighting, ventilation = {}, {}, {}

        for z in zones:
            zd   = zone_data.get(z, {})
            temp = zd.get("temperature", 22.0)
            co2  = zd.get("co2_ppm", 450)
            occ  = zd.get("occupancy", 0)

            # ── HVAC setpoint ─────────────────────────────────────────
            if is_night:
                hvac_sp[z] = 26.0 if carbon_pressure else 24.5
            elif is_ramp_up:
                hvac_sp[z] = 21.5  # Pre-cool before arrival
            elif is_peak:
                if occ == 0:
                    hvac_sp[z] = 26.0  # Unoccupied → aggressive setback
                elif temp > 24.0:
                    hvac_sp[z] = 22.0
                elif temp < 21.0:
                    hvac_sp[z] = 23.0
                else:
                    hvac_sp[z] = 22.5
            elif is_evening:
                hvac_sp[z] = 23.5 if occ > 0 else 25.5

            # CO2 override — never let CO2 drive setpoint below 23
            if co2 > 900:
                hvac_sp[z] = min(hvac_sp.get(z, 22.5), 23.0)

            # Carbon pressure → ease off cooling slightly
            if carbon_pressure and hvac_sp.get(z, 22.5) < 23.5:
                hvac_sp[z] = min(hvac_sp[z] + 0.5, 23.5)

            # ── Lighting (major savings lever) ────────────────────────
            if occ == 0:
                lighting[z] = 5.0
            elif is_night:
                lighting[z] = 15.0
            elif z in ("north", "south", "east", "west") and 9 <= hour <= 16:
                lighting[z] = 50.0   # Daylight harvesting in perimeter
            elif z == "core":
                lighting[z] = 85.0
            else:
                lighting[z] = 75.0

            # ── Ventilation (CO2-responsive) ──────────────────────────
            if occ == 0:
                ventilation[z] = 0.006    # ASHRAE minimum
            elif co2 > 900:
                ventilation[z] = 0.020    # High CO2 response
            elif co2 > 700:
                ventilation[z] = 0.012    # Elevated CO2 moderate response
            elif occ_frac < 0.3:
                ventilation[z] = 0.007    # Low occupancy: reduce
            elif is_peak:
                ventilation[z] = 0.010
            else:
                ventilation[z] = 0.008

        period_desc = (
            "night setback (carbon pressure active)" if is_night and carbon_pressure else
            "night setback" if is_night else
            "morning pre-cool" if is_ramp_up else
            "peak hours — daylight harvesting + demand ventilation" if is_peak else
            "evening wind-down"
        )
        reason = (
            f"[Rule-based | {period_desc}] "
            f"Hour={hour:02d}, Occ={occ_frac*100:.0f}%, OutdoorT={outdoor_t:.1f}°C, "
            f"CumCarbon={cum_carbon:.1f}kg (budget={OPTIMIZATION_GOALS['daily_carbon_limit_kg']}kg). "
            f"Lighting dimmed in perimeter zones (daylight harvesting). "
            f"Ventilation scaled to CO2 demand. HVAC setbacks during low-occupancy hours."
        )

        return {
            "hvac_setpoints":    hvac_sp,
            "lighting_levels":   lighting,
            "ventilation_rates": ventilation,
            "priority": "energy" if occ_frac < 0.3 else "balanced",
        }, reason

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
            zones = args.get("zones") or list(["north", "south", "east", "west", "core"])
            for z in zones:
                accumulated.setdefault("hvac_setpoints", {})[z] = 26.0
                accumulated.setdefault("lighting_levels", {})[z] = 30.0

    def _tool_actions_to_dict(self, state: dict, accumulated: dict) -> dict:
        """
        Convert accumulated MCP tool actions into a complete actions dict,
        filling in any missing zones from current state/defaults.
        """
        zones = ["north", "south", "east", "west", "core"]
        current_controls = state.get("_controls", DEFAULT_CONTROLS)

        # Start from current controls as base
        result = {
            "hvac_setpoints":    dict(current_controls.get("hvac_setpoints", {})),
            "lighting_levels":   dict(current_controls.get("lighting_levels", {})),
            "ventilation_rates": dict(current_controls.get("ventilation_rates", {})),
        }

        # Apply any changes the LLM made via tool calls
        for key in ("hvac_setpoints", "lighting_levels", "ventilation_rates"):
            if key in accumulated:
                result[key].update(accumulated[key])

        # Safety validation
        from agent.safety import clamp_setpoints, clamp_lighting, clamp_ventilation
        result["hvac_setpoints"]    = clamp_setpoints(result["hvac_setpoints"])
        result["lighting_levels"]   = clamp_lighting(result["lighting_levels"])
        result["ventilation_rates"] = clamp_ventilation(result["ventilation_rates"])
        result["priority"] = "balanced"

        return result

    # ── Stats ─────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return agent performance statistics for the dashboard."""
        backend = (
            f"Groq/{GROQ_MODEL} (MCP tool-calling)" if self.groq_available else
            f"Ollama/{self.ollama_model}"             if self.ollama_available else
            "Rule-based fallback"
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
            "avg_tools_per_cycle": (
                round(self.total_tool_calls / max(1, self.groq_calls + self.ollama_calls), 1)
            ),
        }
