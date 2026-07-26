import asyncio
import json
import logging
from datetime import datetime
from groq import Groq
from .prompts import SYSTEM_PROMPT, build_context_message

logger = logging.getLogger(__name__)

class BMSAgent:
    def __init__(self, groq_api_key: str, model_name: str, mcp_server, state_manager):
        self.client = Groq(api_key=groq_api_key)
        self.model_name = model_name
        self.mcp_server = mcp_server
        self.state_manager = state_manager
        self.is_running = False
        logger.info(f"BMSAgent initialized with model: {model_name}")

    async def run_optimization_cycle(self):
        """Run one AI optimization cycle using Groq LLaMA 3 with MCP tool calling."""
        if self.is_running:
            return {"error": "Cycle already running"}

        self.is_running = True
        try:
            before_kwh = self.state_manager.energy.get("total_kwh", 0)
            sim_state = self.state_manager.simulation
            sim_time_dt = sim_state.get("sim_time", datetime.now())
            sim_time = sim_time_dt.strftime("%Y-%m-%d %H:%M") if isinstance(sim_time_dt, datetime) else str(sim_time_dt)
            outdoor_temp = sim_state.get("outdoor_temp", 25.0)
            tick_count = sim_state.get("tick_count", 0)
            hour = sim_time_dt.hour if isinstance(sim_time_dt, datetime) else 12

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_context_message(sim_time, outdoor_temp, tick_count)}
            ]

            actions_taken = []
            final_reasoning = ""

            for iteration in range(5):
                try:
                    response = self.client.chat.completions.create(
                        model=self.model_name,
                        messages=messages,
                        tools=self.mcp_server.tools_schema,
                        tool_choice="auto",
                        max_tokens=1024,
                        temperature=0.2
                    )
                except Exception as api_err:
                    err_str = str(api_err)
                    logger.warning(f"Groq API call warning: {err_str[:150]}")
                    
                    # Fallback rule-based optimization if Groq tool formatting fails on a tick
                    final_reasoning = self._run_rule_fallback(hour, outdoor_temp, actions_taken)
                    break

                response_message = response.choices[0].message

                # Handle text response with no tool calls
                if not response_message.tool_calls:
                    content = response_message.content or ""
                    if content:
                        final_reasoning = content
                    break

                # Append assistant tool call message
                messages.append({
                    "role": "assistant",
                    "content": response_message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                        }
                        for tc in response_message.tool_calls
                    ]
                })

                # Execute tool calls
                for tool_call in response_message.tool_calls:
                    func_name = tool_call.function.name
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except Exception:
                        args = {}

                    if func_name.startswith("set_") or func_name == "trigger_demand_response":
                        actions_taken.append({"tool": func_name, "args": args})

                    result = self.mcp_server.call_tool(func_name, args)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": func_name,
                        "content": json.dumps(result)
                    })

            if not final_reasoning:
                final_reasoning = f"Autonomous BMS Cycle at {sim_time}: Executed {len(actions_taken)} control actions to optimize thermal and energy performance."

            after_kwh = self.state_manager.energy.get("total_kwh", 0)
            energy_impact = round(after_kwh - before_kwh, 4)

            self.state_manager.add_ai_log_entry({
                "tick": tick_count,
                "sim_time": sim_time,
                "reasoning": final_reasoning,
                "actions": actions_taken,
                "energy_impact": energy_impact,
                "timestamp": datetime.now().isoformat()
            })

            return {
                "reasoning": final_reasoning,
                "actions": actions_taken,
                "energy_impact": energy_impact
            }

        except Exception as e:
            logger.error(f"Error in BMSAgent cycle: {e}")
            return {"error": str(e)}
        finally:
            self.is_running = False

    def _run_rule_fallback(self, hour: int, outdoor_temp: float, actions_taken: list) -> str:
        """Rule-based fallback strategy when LLM tool format parsing encounters API strictness."""
        reasons = []
        # Office logic
        if 8 <= hour <= 17:
            self.state_manager.update_zone('office', hvac_mode='cooling', hvac_setpoint=22.0, lighting_level=80)
            actions_taken.extend([
                {"tool": "set_hvac_mode", "args": {"zone_id": "office", "mode": "cooling"}},
                {"tool": "set_hvac_setpoint", "args": {"zone_id": "office", "setpoint": 22.0}},
                {"tool": "set_lighting_level", "args": {"zone_id": "office", "level": 80}}
            ])
            reasons.append("Occupied hours: Office set to 22°C cooling, 80% lighting.")
        else:
            self.state_manager.update_zone('office', hvac_mode='eco', hvac_setpoint=25.0, lighting_level=10)
            actions_taken.extend([
                {"tool": "set_hvac_mode", "args": {"zone_id": "office", "mode": "eco"}},
                {"tool": "set_hvac_setpoint", "args": {"zone_id": "office", "setpoint": 25.0}},
                {"tool": "set_lighting_level", "args": {"zone_id": "office", "level": 10}}
            ])
            reasons.append("Unoccupied hours: Office set to Eco 25°C, 10% lighting.")

        # Server room logic (always cooling 18°C)
        self.state_manager.update_zone('server_room', hvac_mode='cooling', hvac_setpoint=18.0, lighting_level=0)
        actions_taken.extend([
            {"tool": "set_hvac_mode", "args": {"zone_id": "server_room", "mode": "cooling"}},
            {"tool": "set_hvac_setpoint", "args": {"zone_id": "server_room", "setpoint": 18.0}}
        ])
        reasons.append("Server Room: Critical cooling maintained at 18°C.")

        # Lobby logic
        lobby_mode = 'cooling' if (8 <= hour <= 18 and outdoor_temp > 28) else 'eco'
        self.state_manager.update_zone('lobby', hvac_mode=lobby_mode, hvac_setpoint=23.0, lighting_level=50)
        actions_taken.append({"tool": "set_hvac_mode", "args": {"zone_id": "lobby", "mode": lobby_mode}})
        reasons.append(f"Lobby: Set to {lobby_mode} at 23°C.")

        return "BMS Optimization Cycle: " + " ".join(reasons)
