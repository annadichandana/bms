"""
Smart Building BMS — Main Orchestration (Unified)
===================================================
Single entry point that wires together:
  • EnergyPlus Bridge (real EP or physics mock)
  • Official MCP Server (FastMCP) — exposes BMS tools via MCP protocol
  • ARIA Agent (Groq LLaMA-3.3-70B with MCP tool calling / Ollama / rule-based)
  • FastAPI server — dashboard WebSocket + REST API + MCP HTTP endpoints
  • Closed-loop simulation: baseline → AI-optimized, 24-hour run

Usage:
    python main.py                          # 24h sim, 3x speed
    python main.py --speed 10               # fast demo
    python main.py --speed 1                # slow/visible
    python main.py --no-baseline            # skip baseline phase
    python main.py --ep                     # force EnergyPlus mode (if installed)
    python main.py --hours 48               # 2-day simulation

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
from bms.building_state import state_store, DEFAULT_CONTROLS, BASELINE_CONTROLS as BC
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
|   ARIA BMS — Autonomous Resource Intelligence Agent   v2.0       |
|   AI-Powered Smart Building Optimization                          |
+==================================================================+
|   Dashboard   ->  http://localhost:8000/dashboard                 |
|   API Docs    ->  http://localhost:8000/docs                      |
|   MCP Tools   ->  http://localhost:8000/tools                     |
|   Live State  ->  http://localhost:8000/state                     |
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

    agent = ARIAAgent()
    stats = agent.get_stats()
    logger.info("Agent backend  : %s", stats["backend"])
    logger.info("MCP protocol   : %s", stats["mcp_protocol"])
    logger.info("EnergyPlus mode: %s", bridge.mode)

    controls = {k: dict(v) for k, v in DEFAULT_CONTROLS.items()}
    state_store.is_running = True

    for h in range(hours):
        state_store.simulation_hour = h

        # 1. Step simulation
        result = bridge.step(
            hour=h,
            hvac_setpoints=controls["hvac_setpoints"],
            lighting_levels=controls["lighting_levels"],
            ventilation_rates=controls["ventilation_rates"],
        )
        result["_controls"] = {k: dict(v) for k, v in controls.items()}

        state_store.current_metrics = result
        if h < len(baseline_results):
            state_store.baseline_metrics = baseline_results[h]

        # 2. ARIA decision cycle (observe → reason → act via MCP tools)
        actions, reasoning, mode = agent.run_cycle(result, h)

        # 3. Apply to controls for NEXT epoch
        for key in ("hvac_setpoints", "lighting_levels", "ventilation_rates"):
            if key in actions:
                controls[key].update(actions[key])

        state_store.current_controls = {k: dict(v) for k, v in controls.items()}

        # 4. Persist
        state_store.save_decision(h, reasoning, actions, actions.get("priority", "balanced"))
        state_store.save_result("ai_optimized", h, result, controls, reasoning)

        # 5. Summary
        summary = state_store.get_summary()
        agent_stats = agent.get_stats()

        logger.info(
            "ARIA h=%02d [%s] | %.1f kW | PMV=%+.2f | Saved=%.1f%% | "
            "Comfort=%.0f/100 | MCP calls=%d",
            h, mode.upper(),
            result["totals"]["total_kw"],
            result["comfort"]["avg_pmv"],
            summary.get("energy_saved_pct", 0),
            result["comfort"]["comfort_score"],
            agent_stats.get("total_mcp_tool_calls", 0),
        )
        logger.info("  ARIA: %s", reasoning[:120])

        # 6. Broadcast to dashboard
        await broadcast({
            "type": "update",
            "hour": h,
            "metrics": result,
            "baseline": state_store.baseline_metrics,
            "controls": state_store.current_controls,
            "summary": summary,
            "reasoning": reasoning,
            "mode": mode,
            "agent_stats": agent_stats,
            "ep_mode": bridge.mode,
        })

        await asyncio.sleep(epoch_delay)

    state_store.is_running = False

    # Final summary
    logger.info("=" * 66)
    logger.info("SIMULATION COMPLETE")
    if baseline_results:
        base_e  = baseline_results[-1]["totals"]["cumulative_energy_kwh"]
        ai_e    = bridge.total_energy_kwh
        base_c  = baseline_results[-1]["totals"]["cumulative_carbon_kg"]
        ai_c    = bridge.total_carbon_kg
        e_saved = (base_e - ai_e) / max(1, base_e) * 100
        c_saved = (base_c - ai_c) / max(1, base_c) * 100

        logger.info("Simulation mode  : %s", bridge.mode)
        logger.info("LLM backend      : %s", agent.get_stats()["backend"])
        logger.info("MCP tool calls   : %d total", agent.get_stats()["total_mcp_tool_calls"])
        logger.info("Baseline energy  : %.1f kWh", base_e)
        logger.info("AI energy        : %.1f kWh (saved %.1f%%)", ai_e, e_saved)
        logger.info("Baseline carbon  : %.1f kg CO2", base_c)
        logger.info("AI carbon        : %.1f kg CO2 (saved %.1f%%)", ai_c, c_saved)
        logger.info("=" * 66)

        await broadcast({
            "type": "complete",
            "summary": {
                "baseline_energy_kwh":  round(base_e, 2),
                "ai_energy_kwh":        round(ai_e, 2),
                "energy_saved_pct":     round(e_saved, 1),
                "baseline_carbon_kg":   round(base_c, 2),
                "ai_carbon_kg":         round(ai_c, 2),
                "carbon_saved_pct":     round(c_saved, 1),
                "ep_mode":              bridge.mode,
                "agent_stats":          agent.get_stats(),
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
    args = parser.parse_args()

    try:
        asyncio.run(main(
            hours=args.hours,
            speed=args.speed,
            skip_baseline=args.no_baseline,
            force_ep=args.ep,
        ))
    except KeyboardInterrupt:
        print("\n[ARIA] Stopped by user. Dashboard data preserved in data/results.db")
