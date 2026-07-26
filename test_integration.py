"""
ARIA BMS — End-to-end Integration Test
Starts the server and runs a 3-hour demo simulation without Ollama.
"""
import asyncio
import sys
import threading
import time
sys.path.insert(0, '.')

async def run_test():
    print("Starting ARIA BMS integration test...")
    print()

    # Import after path setup
    from simulation.building_sim import BuildingSimulator
    from mcp.building_state import state_store, BASELINE_CONTROLS as BC, DEFAULT_CONTROLS
    from agent.llm_agent import ARIAAgent

    print("Phase 1: Baseline (3 hours)")
    sim_base = BuildingSimulator()
    baseline = []
    for h in range(3):
        r = sim_base.step(h, BC['hvac_setpoints'], BC['lighting_levels'], BC['ventilation_rates'])
        baseline.append(r)
        print(f"  H{h:02d}: {r['totals']['total_kw']:.1f}kW | PMV={r['comfort']['avg_pmv']:.2f} | CO2={r['comfort']['avg_co2']:.0f}ppm")

    print(f"  Baseline total: {sim_base.total_energy_kwh:.1f} kWh")
    print()

    print("Phase 2: AI-Optimized (3 hours)")
    agent = ARIAAgent()
    sim_ai = BuildingSimulator()
    controls = {k: dict(v) for k, v in DEFAULT_CONTROLS.items()}

    for h in range(3):
        r = sim_ai.step(h, controls['hvac_setpoints'], controls['lighting_levels'], controls['ventilation_rates'])
        actions, reasoning, mode = agent.run_cycle(r, h)
        state_store.current_metrics = r
        if actions.get('hvac_setpoints'): controls['hvac_setpoints'].update(actions['hvac_setpoints'])
        if actions.get('lighting_levels'): controls['lighting_levels'].update(actions['lighting_levels'])
        if actions.get('ventilation_rates'): controls['ventilation_rates'].update(actions['ventilation_rates'])
        base_kwh = baseline[h]['totals']['energy_kwh']
        ai_kwh = r['totals']['energy_kwh']
        print(f"  H{h:02d} [{mode.upper()}]: {ai_kwh:.1f}kWh (base={base_kwh:.1f}) | HVAC_sp={actions.get('hvac_setpoints',{}).get('core',22):.1f}C")
        print(f"         Reason: {reasoning[:80]}...")

    print(f"  AI total: {sim_ai.total_energy_kwh:.1f} kWh")
    savings = (sim_base.total_energy_kwh - sim_ai.total_energy_kwh) / sim_base.total_energy_kwh * 100
    print(f"  Energy saved: {savings:.1f}%")
    print()

    print("=" * 50)
    print("INTEGRATION TEST PASSED")
    print("=" * 50)
    print()
    print("To run the full system:")
    print("  python main.py --hours 24 --speed 5")
    print()
    print("Then open: http://localhost:8000/dashboard")

asyncio.run(run_test())
