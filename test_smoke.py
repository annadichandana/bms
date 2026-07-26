"""Quick smoke test for all modules."""
import sys
sys.path.insert(0, '.')

print("Testing simulation module...")
from simulation.building_sim import BuildingSimulator
sim = BuildingSimulator()
result = sim.step(
    hour=9,
    hvac_setpoints={'north':22,'south':22,'east':22,'west':22,'core':22},
    lighting_levels={'north':80,'south':80,'east':80,'west':80,'core':80},
    ventilation_rates={'north':0.01,'south':0.01,'east':0.01,'west':0.01,'core':0.01}
)
print("  OK - Total load:", result['totals']['total_kw'], "kW")
print("  OK - Avg temp:", result['comfort']['avg_temp'], "C")
print("  OK - PMV:", result['comfort']['avg_pmv'])
print("  OK - CO2:", result['comfort']['avg_co2'], "ppm")
print("  OK - Energy:", result['totals']['energy_kwh'], "kWh")

print()
print("Testing 24-hour baseline simulation...")
sim2 = BuildingSimulator()
from mcp.building_state import BASELINE_CONTROLS as BC
for h in range(24):
    r = sim2.step(
        hour=h,
        hvac_setpoints=BC['hvac_setpoints'],
        lighting_levels=BC['lighting_levels'],
        ventilation_rates=BC['ventilation_rates'],
    )
print("  OK - 24-hour baseline done. Total:", round(sim2.total_energy_kwh, 1), "kWh")

print()
print("Testing safety module...")
from agent.safety import validate_llm_actions
safe = validate_llm_actions({
    'hvac_setpoints': {'north': 35.0, 'south': 15.0},
    'lighting_levels': {'core': 150.0},
    'ventilation_rates': {'north': 0.001}
})
print("  OK - Clamped setpoints:", safe)

print()
print("Testing agent fallback...")
from agent.llm_agent import ARIAAgent
from agent.prompt_templates import build_user_prompt, SYSTEM_PROMPT
agent = ARIAAgent()
actions, reasoning, mode = agent.run_cycle(result, 9)
print("  OK - Mode:", mode)
print("  OK - Priority:", actions.get('priority'))
print("  OK - Reasoning:", reasoning[:80], "...")
print("  OK - HVAC setpoints:", actions.get('hvac_setpoints'))

print()
print("=" * 50)
print("ALL TESTS PASSED")
print("=" * 50)
