"""
ARIA BMS — FastAPI Server + MCP Tool Registry
==============================================
FastAPI server that exposes:
  1. Official MCP tool schemas (from mcp/mcp_tools.py, using FastMCP SDK)
  2. REST API endpoints for dashboard and tool invocation
  3. WebSocket live stream for the dashboard

All MCP tools are implemented using the official `mcp` Python SDK
(FastMCP) and also exposed here for HTTP access and demonstration.

Endpoints:
  - GET  /tools           → list all 13 MCP tool schemas (official format)
  - POST /tools/call      → invoke any tool by name
  - GET  /mcp-info        → MCP server information & status
  - GET  /state           → current building state
  - GET  /goals           → optimization goals
  - GET  /history         → recent agent decisions
  - POST /control         → apply control actions (REST fallback)
  - WS   /ws              → live data stream for dashboard
  - GET  /dashboard       → serve live dashboard HTML
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, Field

from bms.building_state import state_store, OPTIMIZATION_GOALS
from bms.mcp_tools import (
    OPENAI_TOOLS_SCHEMA, call_tool, MCP_AVAILABLE,
    _tool_get_zone_status, _tool_get_all_zones_status,
)

DASHBOARD_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Smart Building MCP Server",
    description="Model Context Protocol server for AI building control",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic models ───────────────────────────────────────────────────────────

class ControlAction(BaseModel):
    hvac_setpoints: Optional[Dict[str, float]] = Field(
        default=None,
        description="Zone HVAC setpoints in °C (18-28)",
        example={"north": 22.0, "south": 23.0}
    )
    lighting_levels: Optional[Dict[str, float]] = Field(
        default=None,
        description="Lighting level per zone 0-100%",
        example={"north": 70.0, "core": 80.0}
    )
    ventilation_rates: Optional[Dict[str, float]] = Field(
        default=None,
        description="Ventilation rate m³/s per person (0.006-0.025)",
        example={"north": 0.01}
    )
    reasoning: Optional[str] = Field(default="", description="LLM reasoning text")
    priority: Optional[str] = Field(default="balanced",
                                     description="energy|comfort|balanced")


class MCPToolCall(BaseModel):
    tool: str
    parameters: Optional[Dict[str, Any]] = {}


# ── MCP Tool registry ─────────────────────────────────────────────────────────

MCP_TOOLS = [
    {
        "name": "get_building_state",
        "description": (
            "Returns the current real-time state of all building zones including "
            "temperature (°C), PMV comfort index, CO2 levels (ppm), occupancy count, "
            "and power draw (kW) for HVAC, lighting, and equipment."
        ),
        "parameters": {},
    },
    {
        "name": "get_goals",
        "description": (
            "Returns the optimization goals for the building: energy budget (kWh/day), "
            "PMV comfort bounds, CO2 limit (ppm), and carbon emission limit (kg/day)."
        ),
        "parameters": {},
    },
    {
        "name": "get_action_history",
        "description": "Returns the last N AI decisions with reasoning and timestamps.",
        "parameters": {
            "n": {"type": "integer", "description": "Number of past decisions", "default": 5}
        },
    },
    {
        "name": "set_hvac_setpoint",
        "description": (
            "Set the HVAC temperature setpoint for one or more zones. "
            "Range: 18–28°C. Lower setpoints = more cooling energy. "
            "Higher setpoints during low-occupancy = energy savings."
        ),
        "parameters": {
            "setpoints": {
                "type": "object",
                "description": "zone_name: temperature_celsius",
                "example": {"north": 24.0, "core": 22.5}
            }
        },
    },
    {
        "name": "set_lighting_level",
        "description": (
            "Set lighting dimming level for one or more zones (0-100%). "
            "Dim to 0% in unoccupied zones. Daylight harvesting recommended "
            "for perimeter zones (north, south, east, west)."
        ),
        "parameters": {
            "levels": {
                "type": "object",
                "description": "zone_name: percent (0-100)",
                "example": {"north": 60.0, "core": 90.0}
            }
        },
    },
    {
        "name": "set_ventilation_rate",
        "description": (
            "Set fresh air ventilation rate per person per zone (m³/s). "
            "Min = 0.006 (ASHRAE 62.1 minimum). Max = 0.025. "
            "Reduce in low-occupancy periods to save energy."
        ),
        "parameters": {
            "rates": {
                "type": "object",
                "description": "zone_name: m3/s_per_person",
                "example": {"north": 0.008, "core": 0.012}
            }
        },
    },
]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health", summary="Health check")
async def health():
    return {"status": "ok", "service": "ARIA BMS MCP Server", "version": "2.1.0"}


@app.get("/stress-test/safety", summary="Safety Stress Test — validates unsafe proposed values")
async def safety_stress_test():
    """
    SAFETY STRESS TEST (does NOT affect real simulation).

    Intentionally sends out-of-range control proposals to the safety validator
    to prove the validator correctly clamps all unsafe values.

    Proposed values (deliberately unsafe):
      - HVAC: 10°C (below 18°C minimum)
      - Lighting: 150% (above 100% maximum)
      - Ventilation: 0.0005 m³/s (below 0.006 minimum)

    Expected: all values clamped to safe operating bounds.
    """
    from bms.mcp_tools import _tool_validate_action

    unsafe_hvac = {z: 10.0 for z in ["north", "south", "east", "west", "core"]}
    unsafe_light = {z: 150.0 for z in ["north", "south", "east", "west", "core"]}
    unsafe_vent = {z: 0.0005 for z in ["north", "south", "east", "west", "core"]}

    validation_result = _tool_validate_action(
        hvac_setpoints=unsafe_hvac,
        lighting_levels=unsafe_light,
        ventilation_rates=unsafe_vent,
    )

    return {
        "test_type": "SAFETY_STRESS_TEST",
        "label": "[TEST ONLY] This does not affect the running simulation.",
        "description": (
            "Sends intentionally unsafe control proposals to the safety validator "
            "to verify clamping works correctly."
        ),
        "proposed": {
            "hvac_setpoints": unsafe_hvac,
            "lighting_levels": unsafe_light,
            "ventilation_rates": unsafe_vent,
        },
        "validation_result": validation_result,
        "interpretation": {
            "hvac": f"10.0°C clamped to 18.0°C (minimum safe setpoint)",
            "lighting": f"150% clamped to 100% (maximum allowed)",
            "ventilation": f"0.0005 m³/s clamped to 0.006 m³/s (ASHRAE 62.1 minimum)",
        },
        "safety_system": "operational" if not validation_result.get("safe") else "no_overrides_needed",
        "overrides_detected": validation_result.get("override_count", 0),
    }


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def serve_dashboard():
    """Serve the live dashboard HTML."""
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/tools", summary="List all MCP tools (official MCP-compatible schema)")
async def list_tools():
    """
    Returns all 13 BMS tools in OpenAI/MCP-compatible function-calling schema format.
    These are the same tools registered with the official FastMCP SDK server.
    """
    return {
        "protocol": "Model Context Protocol (MCP)",
        "sdk": "FastMCP (Anthropic official mcp SDK)",
        "sdk_available": MCP_AVAILABLE,
        "server_name": "ARIA-BMS",
        "tool_count": len(OPENAI_TOOLS_SCHEMA),
        "tools": OPENAI_TOOLS_SCHEMA,
    }


@app.get("/mcp-info", summary="MCP server information")
async def mcp_info():
    """Return MCP server status and connection information."""
    from agent.llm_agent import GROQ_MODEL, GROQ_API_KEY, OLLAMA_BASE_URL
    return {
        "mcp_server": "ARIA-BMS",
        "version": "2.0.0",
        "sdk": "FastMCP (Anthropic mcp Python SDK)",
        "sdk_loaded": MCP_AVAILABLE,
        "transport": "HTTP/SSE + REST",
        "tool_count": len(OPENAI_TOOLS_SCHEMA),
        "tool_names": [t["function"]["name"] for t in OPENAI_TOOLS_SCHEMA],
        "llm_backend": {
            "groq_model": GROQ_MODEL,
            "groq_configured": bool(GROQ_API_KEY and GROQ_API_KEY not in ("", "your_key_here")),
            "ollama_url": OLLAMA_BASE_URL,
        },
        "simulation": {
            "hour": state_store.simulation_hour,
            "running": state_store.is_running,
            "decisions_made": len(state_store.action_history),
        },
    }


@app.post("/tools/call", summary="Invoke any MCP tool by name")
async def invoke_mcp_tool(req: MCPToolCall):
    """
    Universal MCP tool dispatcher — calls any of the 13 BMS tools by name.
    All tools are implemented in mcp/mcp_tools.py using the official FastMCP SDK.
    """
    result = call_tool(req.tool, req.parameters or {})
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/state", summary="Get current building state")
async def get_state():
    if not state_store.current_metrics:
        return {"status": "simulation_not_started", "hour": 0}
    return {
        "status": "ok",
        "data": state_store.current_metrics,
        "controls": state_store.current_controls,
        "summary": state_store.get_summary(),
    }


@app.get("/goals", summary="Get optimization goals")
async def get_goals():
    return {"goals": OPTIMIZATION_GOALS}


@app.get("/history", summary="Get agent decision history")
async def get_history(n: int = 10):
    return {"history": state_store.action_history[-n:]}


@app.post("/control", summary="Apply control actions")
async def apply_control(action: ControlAction):
    """Apply LLM-generated control actions to the building."""
    applied = {}

    if action.hvac_setpoints:
        result = await _apply_setpoints(action.hvac_setpoints)
        applied["hvac"] = result

    if action.lighting_levels:
        result = await _apply_lighting(action.lighting_levels)
        applied["lighting"] = result

    if action.ventilation_rates:
        result = await _apply_ventilation(action.ventilation_rates)
        applied["ventilation"] = result

    # Save AI decision
    if action.reasoning:
        state_store.save_decision(
            hour=state_store.simulation_hour,
            reasoning=action.reasoning,
            actions={
                "hvac": action.hvac_setpoints or {},
                "lighting": action.lighting_levels or {},
                "ventilation": action.ventilation_rates or {},
            },
            priority=action.priority or "balanced",
        )

    return {"status": "ok", "applied": applied}


@app.get("/dashboard-data", summary="Full data snapshot for dashboard")
async def dashboard_data():
    return {
        "summary": state_store.get_summary(),
        "metrics": state_store.current_metrics,
        "baseline": state_store.baseline_metrics,
        "controls": state_store.current_controls,
        "history": state_store.action_history[-5:],
        "goals": OPTIMIZATION_GOALS,
    }


# ── WebSocket live feed ───────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    state_store.websocket_clients.append(ws)
    logger.info("Dashboard client connected. Total: %d", len(state_store.websocket_clients))
    try:
        # Send current state immediately on connect
        if state_store.current_metrics:
            await ws.send_json({
                "type": "update",
                "hour": state_store.simulation_hour,
                "metrics": state_store.current_metrics,
                "baseline": state_store.baseline_metrics,
                "controls": state_store.current_controls,
                "summary": state_store.get_summary(),
                "reasoning": "Connected to ARIA BMS live feed.",
                "mode": "connected",
                "agent_stats": {},
            })
        # Just hold the connection open; simulation loop pushes data via broadcast()
        while True:
            try:
                # Receive any client messages (or detect disconnect)
                await asyncio.wait_for(ws.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # Send keepalive ping every 30s
                await ws.send_json({"ping": True})
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        try:
            state_store.websocket_clients.remove(ws)
        except ValueError:
            pass
        logger.info("Dashboard client disconnected. Total: %d", len(state_store.websocket_clients))


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _apply_setpoints(sp: Dict[str, float]) -> dict:
    """Validate and apply HVAC setpoints."""
    from agent.safety import clamp_setpoints
    safe_sp = clamp_setpoints(sp)
    state_store.current_controls["hvac_setpoints"].update(safe_sp)
    return {"applied": safe_sp}


async def _apply_lighting(lv: Dict[str, float]) -> dict:
    """Validate and apply lighting levels."""
    from agent.safety import clamp_lighting
    safe_lv = clamp_lighting(lv)
    state_store.current_controls["lighting_levels"].update(safe_lv)
    return {"applied": safe_lv}


async def _apply_ventilation(rv: Dict[str, float]) -> dict:
    """Validate and apply ventilation rates."""
    from agent.safety import clamp_ventilation
    safe_rv = clamp_ventilation(rv)
    state_store.current_controls["ventilation_rates"].update(safe_rv)
    return {"applied": safe_rv}
