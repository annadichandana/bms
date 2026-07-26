"""Physics validation test."""
import sys
sys.path.insert(0, '.')
from simulation.building_sim import BuildingSimulator
from mcp.building_state import BASELINE_CONTROLS as BC

sim = BuildingSimulator()
print("BASELINE 24-HOUR RUN:")
for h in range(24):
    r = sim.step(h, BC['hvac_setpoints'], BC['lighting_levels'], BC['ventilation_rates'])
    if h % 3 == 0:
        c = r['comfort']
        t = r['totals']
        print(f"  H{h:02d}: temp={c['avg_temp']}C  PMV={c['avg_pmv']}  CO2={c['avg_co2']}ppm  load={t['total_kw']}kW")

print(f"  Total: {sim.total_energy_kwh:.1f} kWh | Carbon: {sim.total_carbon_kg:.1f} kg")
print()

# AI optimized test
from agent.llm_agent import ARIAAgent
sim2 = BuildingSimulator()
agent = ARIAAgent()
print("AI-OPTIMIZED 24-HOUR RUN (fallback mode):")
for h in range(24):
    r = sim2.step(h, {'north':22,'south':22,'east':22,'west':22,'core':22},
                  {'north':80,'south':80,'east':80,'west':80,'core':80},
                  {'north':0.01,'south':0.01,'east':0.01,'west':0.01,'core':0.01})
    actions, reasoning, mode = agent.run_cycle(r, h)
    if h % 3 == 0:
        c = r['comfort']
        t = r['totals']
        print(f"  H{h:02d}: temp={c['avg_temp']}C  PMV={c['avg_pmv']}  load={t['total_kw']}kW  sp={actions.get('hvac_setpoints',{}).get('core',22)}")
print(f"  Total: {sim2.total_energy_kwh:.1f} kWh | Carbon: {sim2.total_carbon_kg:.1f} kg")
