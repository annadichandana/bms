"""Quick 4-hour smoke test — no server, pure agent loop."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from bms.building_state import state_store
from agent.llm_agent import ARIAAgent
from simulation.energyplus_bridge import EnergyPlusBridge

print("=== ARIA BMS Smoke Test ===")
run_id = state_store.reset_for_new_run()
print(f"Run ID: {run_id}")

bridge = EnergyPlusBridge()
print(f"Simulation mode: {bridge.mode}")

agent = ARIAAgent()

for h in range(4):
    result = bridge.step(
        hour=h,
        hvac_setpoints={z: 22.0 for z in ["north","south","east","west","core"]},
        lighting_levels={z: 80.0 for z in ["north","south","east","west","core"]},
        ventilation_rates={z: 0.010 for z in ["north","south","east","west","core"]},
    )
    result["_controls"] = {}
    state_store.current_metrics = result

    actions, reasoning, mode = agent.run_cycle(result, h)
    stats = agent.get_stats()
    g = stats["mcp_tool_groups"]

    print(f"  Hour {h:02d}: mode={mode}")
    print(f"    MCP obs={g['observation']} dec={g['decision']} ctrl={g['control']} val={g['validation']} total={g['raw_calls']}")
    snippet = reasoning[:90] + "..." if len(reasoning) > 90 else reasoning
    print(f"    Reasoning: {snippet}")
    dd = agent.last_decision_detail
    safe = dd.get("validate", {}).get("safe", True)
    triggers = dd.get("reason", {}).get("triggers", [])
    print(f"    Safety: {'OK' if safe else 'OVERRIDES APPLIED'} | Triggers: {triggers}")

print()
final = agent.get_stats()
print(f"Total MCP executions : {final['total_mcp_tool_calls']}")
print(f"Per cycle average    : {final['avg_tools_per_cycle']}")
print(f"Safety events        : {len(agent.last_safety_events)}")
print(f"Strategy source      : {final['strategy_source']}")
print(f"Decision detail keys : {list(agent.last_decision_detail.keys())}")
print("=== SMOKE TEST COMPLETE ===")
