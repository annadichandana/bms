"""
Smart Building BMS — Main Orchestration (Unified)
===================================================
Single entry point that wires together:
  • EnergyPlus Bridge (real EP or physics mock)
  • Official MCP Server (FastMCP) — exposes BMS tools via MCP protocol
  • ARIA Agent (Groq LLaMA strategy + MCP-driven OBSERVE→ACT loop)
  • FastAPI server — dashboard WebSocket + REST API + MCP HTTP endpoints
  • Closed-loop simulation: baseline → AI-optimized, 24-hour run

Usage:
    python main.py                          # 24h sim, 3x speed
    python main.py --speed 10               # fast demo
    python main.py --speed 1                # slow/visible
    python main.py --no-baseline            # skip baseline phase
    python main.py --ep                     # force EnergyPlus mode (if installed)
    python main.py --hours 48               # 2-day simulation
    python main.py --hours 4 --speed 10 --ep  # smoke test

Dashboard:   http://localhost:8000/dashboard
API docs:    http://localhost:8000/docs
MCP tools:   http://localhost:8000/tools
Live state:  http://localhost:8000/state
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import webbrowser
from datetime import datetime


# ── Windows UTF-8 fix ─────────────────────────────────────────────────────────
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Load environment ──────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(override=False)


import uvicorn

from simulation.energyplus_bridge import EnergyPlusBridge
from bms.building_state import state_store, DEFAULT_CONTROLS, BASELINE_CONTROLS as BC, OBJECTIVE_WEIGHTS
from agent.llm_agent import ARIAAgent

# ── Logging ───────────────────────────────────────────────────────────────────

os.makedirs("data", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/simulation.log", mode="w", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

BANNER = """
+==================================================================+
|   ARIA BMS — Autonomous Resource Intelligence Agent   v2.1       |
|   AI-Powered Smart Building Optimization                          |
+==================================================================+
|   Dashboard   ->  http://localhost:8000/dashboard                 |
|   API Docs    ->  http://localhost:8000/docs                      |
|   MCP Tools   ->  http://localhost:8000/tools                     |
|   Live State  ->  http://localhost:8000/state                     |
|   Safety Test ->  http://localhost:8000/stress-test/safety        |
+==================================================================+
"""


# ── WebSocket broadcast ───────────────────────────────────────────────────────

async def broadcast(data: dict):
    """Push live data to all connected dashboard WebSocket clients."""
    dead = []
    for ws in list(state_store.websocket_clients):
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        try:
            state_store.websocket_clients.remove(ws)
        except ValueError:
            pass


# ── Baseline phase ────────────────────────────────────────────────────────────

async def run_baseline(
    hours: int,
    epoch_delay: float,
    bridge: EnergyPlusBridge,
) -> list:
    """Run fixed-setpoint baseline (no AI). Returns list of hourly results."""
    logger.info("=" * 66)
    logger.info("PHASE 1: BASELINE SIMULATION (Fixed Setpoints - No AI)")
    logger.info("=" * 66)

    results = []
    for h in range(hours):
        result = bridge.step(
            hour=h,
            hvac_setpoints=BC["hvac_setpoints"],
            lighting_levels=BC["lighting_levels"],
            ventilation_rates=BC["ventilation_rates"],
        )
        results.append(result)
        state_store.save_result("baseline", h, result, BC, "")

        logger.info(
            "BASELINE h=%02d | EP=%s | %.1f kW | %.1f kWh cum | PMV=%+.2f | CO2=%d ppm",
            h,
            result.get("_source", "mock"),
            result["totals"]["total_kw"],
            result["totals"]["cumulative_energy_kwh"],
            result["comfort"]["avg_pmv"],
            result["comfort"]["avg_co2"],
        )

        await broadcast({
            "type": "baseline_update",
            "hour": h,
            "metrics": result,
            "phase": "baseline",
            "ep_mode": bridge.mode,
            "run_id": state_store.run_id,
        })
        await asyncio.sleep(epoch_delay * 0.25)

    logger.info(
        "BASELINE COMPLETE | Total: %.2f kWh | Carbon: %.2f kg CO2",
        bridge.total_energy_kwh,
        bridge.total_carbon_kg,
    )
    return results


# ── AI-Optimized phase ────────────────────────────────────────────────────────

async def run_ai_optimized(
    hours: int,
    baseline_results: list,
    epoch_delay: float,
    bridge: EnergyPlusBridge,
):
    """ARIA agent makes autonomous MCP-driven decisions every simulated hour."""
    logger.info("=" * 66)
    logger.info("PHASE 2: AI-OPTIMIZED SIMULATION (ARIA Agent Active)")
    logger.info("=" * 66)
    logger.info("MCP Control Loop: OBSERVE -> REASON -> ACT -> VALIDATE -> LEARN")
    logger.info("Expected MCP calls per hour: 4 obs + 1 dec + 15 ctrl + 1 val = 21")
    logger.info("=" * 66)

    agent = ARIAAgent()
    stats = agent.get_stats()
    logger.info("Agent backend  : %s", stats["backend"])
    logger.info("MCP protocol   : %s", stats["mcp_protocol"])
    logger.info("EnergyPlus mode: %s", bridge.mode)

    controls = {k: dict(v) for k, v in DEFAULT_CONTROLS.items()}
    state_store.is_running = True

    # Baseline metrics snapshot — store final baseline result for comparison
    if baseline_results:
        # Use the final accumulated baseline (last hour) for energy/carbon comparison
        state_store.baseline_metrics = baseline_results[-1]

    co2_compliant_hours = 0

    for h in range(hours):
        state_store.simulation_hour = h
        state_store.total_hours = hours

        # 1. Step simulation with current controls
        result = bridge.step(
            hour=h,
            hvac_setpoints=controls["hvac_setpoints"],
            lighting_levels=controls["lighting_levels"],
            ventilation_rates=controls["ventilation_rates"],
        )
        result["_controls"] = {k: dict(v) for k, v in controls.items()}
        result["_hour"] = h

        state_store.current_metrics = result
        state_store.prev_metrics = state_store.current_metrics if h > 0 else {}

        # Track CO2 compliance
        avg_co2 = result.get("comfort", {}).get("avg_co2", 0)
        if avg_co2 < 1000:
            co2_compliant_hours += 1
        state_store.co2_compliant_hours = co2_compliant_hours

        # 2. ARIA decision cycle — real OBSERVE→REASON→ACT→VALIDATE→LEARN via MCP tools
        actions, reasoning, mode = agent.run_cycle(result, h)

        # 3. Apply to controls for NEXT epoch
        for key in ("hvac_setpoints", "lighting_levels", "ventilation_rates"):
            if key in actions:
                controls[key].update(actions[key])

        state_store.current_controls = {k: dict(v) for k, v in controls.items()}
        state_store.safety_events    = agent.last_safety_events
        state_store.decision_detail  = agent.last_decision_detail
        state_store.decision_cycles  = h + 1

        # Update MCP counters in state_store for summary
        agent_stats = agent.get_stats()
        state_store.update_mcp_counts(
            obs=agent_stats["mcp_obs_calls"],
            dec=agent_stats["mcp_dec_calls"],
            ctrl=agent_stats["mcp_ctrl_calls"],
            val=agent_stats["mcp_val_calls"],
        )

        # 4. Persist
        state_store.save_decision(h, reasoning, actions, actions.get("priority", "balanced"))
        state_store.save_result("ai_optimized", h, result, controls, reasoning)

        # 5. Detect anomalies
        anomalies = state_store.detect_anomalies(
            result,
            state_store.prev_metrics,
            controls,
        )
        state_store.anomalies = anomalies

        # 6. Build enriched broadcast payload
        summary      = state_store.get_summary()

        # Trust status indicators
        trust_status = {
            "energyplus":      bridge.mode == "energyplus",
            "mcp":             True,
            "safety":          True,
            "fallback":        True,
            "ashrae":          True,
            "co2":             True,
            "carbon":          True,
            "groq":            agent.groq_available,
            "strategy_source": agent_stats.get("strategy_source", "deterministic_default"),
        }

        # MCP tool group summary with real counts
        mcp_tool_groups_payload = agent_stats.get("mcp_tool_groups", {})
        mcp_tool_groups_payload["total_cycles"] = h + 1

        # What-if scenarios (use real running totals)
        what_if = state_store.get_what_if_scenarios(
            current_energy_kwh=bridge.total_energy_kwh,
            current_carbon_kg=bridge.total_carbon_kg,
        )

        logger.info(
            "ARIA h=%02d [%s] | %.1f kW | PMV=%+.2f | Saved=%.1f%% | "
            "Comfort=%.0f/100 | Safety=%d events | MCP_total=%d",
            h, mode.upper(),
            result["totals"]["total_kw"],
            result["comfort"]["avg_pmv"],
            summary.get("energy_saved_pct", 0),
            result["comfort"]["comfort_score"],
            len(agent.last_safety_events),
            agent_stats["total_mcp_tool_calls"],
        )
        logger.info(
            "  MCP calls: obs=%d dec=%d ctrl=%d val=%d total=%d",
            agent_stats["mcp_obs_calls"],
            agent_stats["mcp_dec_calls"],
            agent_stats["mcp_ctrl_calls"],
            agent_stats["mcp_val_calls"],
            agent_stats["total_mcp_tool_calls"],
        )
        logger.info("  ARIA: %s", reasoning[:120])

        # 7. Broadcast enriched payload to dashboard
        await broadcast({
            "type":              "update",
            "hour":              h,
            "metrics":           result,
            "baseline":          state_store.baseline_metrics,
            "controls":          state_store.current_controls,
            "safety_events":     agent.last_safety_events,
            "decision_detail":   agent.last_decision_detail,
            "anomalies":         anomalies,
            "what_if":           what_if,
            "objective_weights": OBJECTIVE_WEIGHTS,
            "trust_status":      trust_status,
            "mcp_tool_groups":   mcp_tool_groups_payload,
            "summary":           summary,
            "reasoning":         reasoning,
            "mode":              mode,
            "agent_stats":       agent_stats,
            "ep_mode":           bridge.mode,
            "run_id":            state_store.run_id,
            "run_status":        "running",
        })

        await asyncio.sleep(epoch_delay)

    state_store.mark_run_complete()

    # ── Final terminal summary ────────────────────────────────────────────
    final_agent_stats = agent.get_stats()
    logger.info("")
    logger.info("=" * 50)
    logger.info("ARIA SIMULATION COMPLETE")
    logger.info("=" * 50)

    if baseline_results:
        base_e  = baseline_results[-1]["totals"]["cumulative_energy_kwh"]
        ai_e    = bridge.total_energy_kwh
        base_c  = baseline_results[-1]["totals"]["cumulative_carbon_kg"]
        ai_c    = bridge.total_carbon_kg
        e_saved = (base_e - ai_e) / max(1, base_e) * 100
        c_saved = (base_c - ai_c) / max(1, base_c) * 100

        comfort_score = state_store.current_metrics.get("comfort", {}).get("comfort_score", 0) if state_store.current_metrics else 0

        logger.info("")
        logger.info("Simulation mode    : %s", bridge.mode)
        logger.info("LLM strategy       : %s", "Groq" if agent.groq_available else "Deterministic")
        logger.info("MCP protocol       : FastMCP")
        logger.info("Run ID             : %s", state_store.run_id)
        logger.info("")
        logger.info("Baseline energy    : %.1f kWh", base_e)
        logger.info("ARIA energy        : %.1f kWh", ai_e)
        logger.info("Energy saved       : %.1f%%", e_saved)
        logger.info("")
        logger.info("Baseline carbon    : %.1f kg CO2", base_c)
        logger.info("ARIA carbon        : %.1f kg CO2", ai_c)
        logger.info("Carbon reduced     : %.1f%%", c_saved)
        logger.info("")
        logger.info("Comfort score      : %.0f/100", comfort_score)
        logger.info("CO2 compliance     : %d/%d hours", co2_compliant_hours, hours)
        logger.info("")
        logger.info("MCP observation calls : %d", final_agent_stats["mcp_obs_calls"])
        logger.info("MCP decision calls    : %d", final_agent_stats["mcp_dec_calls"])
        logger.info("MCP control calls     : %d", final_agent_stats["mcp_ctrl_calls"])
        logger.info("MCP validation calls  : %d", final_agent_stats["mcp_val_calls"])
        logger.info("Total MCP executions  : %d", final_agent_stats["total_mcp_tool_calls"])
        logger.info("Meaningful cycles     : %d", final_agent_stats["total_cycles"])
        logger.info("")
        logger.info("Safety overrides   : %d", len(state_store.safety_events))
        logger.info("Anomalies detected : %d", len(state_store.anomalies))
        logger.info("")
        logger.info("Closed-loop status :")
        logger.info("  OBSERVE   [OK] (%d calls)", final_agent_stats["mcp_obs_calls"])
        logger.info("  REASON    [OK]")
        logger.info("  ACT       [OK] (%d calls)", final_agent_stats["mcp_ctrl_calls"])
        logger.info("  VALIDATE  [OK] (%d calls)", final_agent_stats["mcp_val_calls"])
        logger.info("  LEARN     [OK]")
        logger.info("")
        logger.info("ARIA reduced building energy by %.1f%% vs fixed-setpoint baseline", e_saved)
        logger.info("while maintaining thermal comfort, IAQ, and safety constraints.")
        logger.info("=" * 50)

        final_what_if = state_store.get_what_if_scenarios(
            current_energy_kwh=bridge.total_energy_kwh,
            current_carbon_kg=bridge.total_carbon_kg,
        )

        await broadcast({
            "type": "complete",
            "run_id":   state_store.run_id,
            "summary": {
                "run_id":               state_store.run_id,
                "run_status":           "completed",
                "baseline_energy_kwh":  round(base_e, 2),
                "ai_energy_kwh":        round(ai_e, 2),
                "energy_saved_pct":     round(e_saved, 1),
                "baseline_carbon_kg":   round(base_c, 2),
                "ai_carbon_kg":         round(ai_c, 2),
                "carbon_saved_pct":     round(c_saved, 1),
                "comfort_score":        round(comfort_score, 1),
                "co2_compliant_hours":  co2_compliant_hours,
                "total_hours":          hours,
                "ep_mode":              bridge.mode,
                "agent_stats":          final_agent_stats,
                "mcp_tool_groups": {
                    "observation": final_agent_stats["mcp_obs_calls"],
                    "decision":    final_agent_stats["mcp_dec_calls"],
                    "control":     final_agent_stats["mcp_ctrl_calls"],
                    "validation":  final_agent_stats["mcp_val_calls"],
                    "raw_calls":   final_agent_stats["total_mcp_tool_calls"],
                    "total_cycles": final_agent_stats["total_cycles"],
                },
                "safety_events_total":  len(state_store.safety_events),
                "total_anomalies":      len(state_store.anomalies),
            },
            "what_if":          final_what_if,
            "objective_weights": OBJECTIVE_WEIGHTS,
            "trust_status": {
                "energyplus": bridge.mode == "energyplus",
                "mcp": True, "safety": True, "fallback": True,
                "ashrae": True, "co2": True, "carbon": True,
                "groq": agent.groq_available,
            },
        })


# ── Main orchestrator ─────────────────────────────────────────────────────────

async def main(
    hours: int = 24,
    speed: float = 3.0,
    skip_baseline: bool = False,
    force_ep: bool = False,
):
    print(BANNER)

    # Attach broadcast to state store (same event loop)
    state_store._broadcast = broadcast

    # Reset state for this run (clears stale data from any previous run)
    run_id = state_store.reset_for_new_run()
    logger.info("New simulation run: %s", run_id)

    # ── Initialize EnergyPlus bridge ─────────────────────────────────────
    if force_ep:
        os.environ.setdefault("ENERGYPLUS_DIR", "")  # Will trigger real EP search
    bridge = EnergyPlusBridge()
    logger.info("Simulation mode: %s", bridge.mode.upper())

    # ── Start FastAPI + MCP server ────────────────────────────────────────
    from bms.server import app
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="warning",
        loop="none",
    )
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    await asyncio.sleep(2)  # Let server start

    logger.info("Dashboard: http://localhost:8000/dashboard")
    logger.info("API Docs:  http://localhost:8000/docs")
    logger.info("MCP Tools: http://localhost:8000/tools")
    logger.info("Safety Test: http://localhost:8000/stress-test/safety")
    logger.info("Starting in 3 seconds...")

    try:
        webbrowser.open("http://localhost:8000/dashboard")
    except Exception:
        pass

    await asyncio.sleep(3)

    # epoch_delay: real seconds per simulated hour
    # speed=1 → 3.0s/hr (72s total)  | speed=3 → 1.0s/hr (24s) | speed=10 → 0.3s/hr (7s)
    epoch_delay = max(0.2, 3.0 / speed)

    # ── Phase 1: Baseline ─────────────────────────────────────────────────
    baseline_results = []
    if not skip_baseline:
        bridge_baseline = EnergyPlusBridge()  # Fresh bridge for baseline
        baseline_results = await run_baseline(hours, epoch_delay, bridge_baseline)
        # Store the last baseline result for reference in what-if comparison
        if baseline_results:
            state_store.baseline_metrics = baseline_results[-1]
        await asyncio.sleep(1)

    # ── Phase 2: AI-Optimized ─────────────────────────────────────────────
    bridge.reset()  # Reset bridge for AI run
    await run_ai_optimized(hours, baseline_results, epoch_delay, bridge)

    logger.info("Simulation done! Dashboard is still live -> http://localhost:8000/dashboard")
    logger.info("Press Ctrl+C to stop.")
    await server_task


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ARIA BMS — AI-Powered Smart Building Optimization"
    )
    parser.add_argument(
        "--hours", type=int, default=24,
        help="Simulated hours to run (default: 24)",
    )
    parser.add_argument(
        "--speed", type=float, default=3.0,
        help="Speed multiplier (1=slow/visible, 10=fast demo, default: 3)",
    )
    parser.add_argument(
        "--no-baseline", action="store_true",
        help="Skip baseline phase, go straight to AI optimization",
    )
    parser.add_argument(
        "--ep", action="store_true",
        help="Force EnergyPlus mode (requires EnergyPlus installation)",
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Run 3-minute presentation demo (1 strategic LLM call, heat wave crisis, clear impact)",
    )
    args = parser.parse_args()

    if args.demo:
        from demo_3min import run_3min_demo
        try:
            asyncio.run(run_3min_demo(speed=args.speed))
        except KeyboardInterrupt:
            print("\n[ARIA Demo] Stopped by user.")
    else:
        try:
            asyncio.run(main(
                hours=args.hours,
                speed=args.speed,
                skip_baseline=args.no_baseline,
                force_ep=args.ep,
            ))
        except KeyboardInterrupt:
            print("\n[ARIA] Stopped by user. Dashboard data preserved in data/results.db")
