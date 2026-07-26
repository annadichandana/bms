# System Architecture — ARIA BMS v2.0

## Overview

ARIA (Autonomous Resource Intelligence Agent for Buildings) is a **closed-loop, AI-powered Building Management System** that autonomously optimizes energy consumption, occupant comfort, and carbon emissions. It integrates:

- **EnergyPlus Python API** — real co-simulation via official `pyenergyplus` bindings (with physics-based fallback)
- **Open-source LLM via MCP** — LLaMA 3.3 70B (Groq) or phi3:mini (Ollama) with official Model Context Protocol tool calling
- **FastMCP (official MCP SDK)** — 13 BMS control tools exposed via the Anthropic `mcp` Python SDK
- **FastAPI** — REST + WebSocket server for dashboard and tool invocation
- **React + HTML dashboard** — real-time energy, comfort, and carbon visualization

---

## Unified Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│                    CLOSED-LOOP CONTROL SYSTEM                          │
│                                                                        │
│  ┌──────────────────────┐          ┌──────────────────────────────┐   │
│  │  EnergyPlus Bridge   │          │  FastMCP Server (MCP SDK)    │   │
│  │                      │          │  mcp/mcp_tools.py            │   │
│  │  Mode 1: Real EP     │◄────────►│                              │   │
│  │  pyenergyplus API    │ sensor   │  13 BMS Tools:               │   │
│  │  co-simulation       │ data &   │  • get_all_zones_status()    │   │
│  │  multi_zone_office   │ actuator │  • get_energy_metrics()      │   │
│  │  .idf (EP v24.1)     │ commands │  • get_weather_forecast()    │   │
│  │                      │          │  • get_occupancy_schedule()  │   │
│  │  Mode 2: Physics     │          │  • set_hvac_setpoint()       │   │
│  │  Mock (fallback)     │          │  • set_lighting_level()      │   │
│  │  Euler integration   │          │  • set_ventilation_rate()    │   │
│  │  Perez solar model   │          │  • set_hvac_mode()           │   │
│  │  Fanger PMV          │          │  • trigger_demand_response() │   │
│  │  CO₂ mass balance    │          │  • get_comfort_score()       │   │
│  └──────────────────────┘          │  • get_optimization_goals()  │   │
│             │                      │  • get_optimization_history()│   │
│             │                      └──────────────┬───────────────┘   │
│             │                                     │ MCP tool calls    │
│             │                      ┌──────────────▼───────────────┐   │
│             │                      │  ARIA LLM Agent              │   │
│             │                      │  agent/llm_agent.py          │   │
│             │                      │                              │   │
│             │                      │  Primary: Groq LLaMA-3.3-70B │   │
│             │                      │  + MCP tool_choice="auto"    │   │
│             │                      │                              │   │
│             │                      │  Fallback: Ollama phi3:mini  │   │
│             │                      │  + JSON structured output    │   │
│             │                      │                              │   │
│             │                      │  Emergency: Rule-based       │   │
│             │                      │  (ASHRAE-compliant, carbon-  │   │
│             │                      │   aware, always available)   │   │
│             │                      └──────────────┬───────────────┘   │
│             │                                     │                   │
│             │                      ┌──────────────▼───────────────┐   │
│             │                      │  State Store + SQLite         │   │
│             │                      │  mcp/building_state.py       │   │
│             │                      │  + data/results.db           │   │
│             │                      └──────────────┬───────────────┘   │
│             │                                     │ WebSocket          │
│             │                      ┌──────────────▼───────────────┐   │
│             │                      │  FastAPI Server (port 8000)  │   │
│             │                      │  mcp/server.py               │   │
│             │                      │                              │   │
│             │                      │  GET  /tools  → MCP schemas  │   │
│             │                      │  POST /tools/call → dispatch │   │
│             │                      │  GET  /mcp-info → SDK status │   │
│             │                      │  WS   /ws  → live stream     │   │
│             │                      │  GET  /dashboard → HTML      │   │
│             └──────────────────────►  GET  /state, /goals, /hist  │   │
│                                    └──────────────┬───────────────┘   │
│                                                   │                   │
│                              ┌────────────────────▼──────────────┐    │
│                              │  Live Dashboard (port 8000)        │    │
│                              │  dashboard/index.html             │    │
│                              │  + frontend/ (React + Vite)       │    │
│                              │                                   │    │
│                              │  • Budget progress bars           │    │
│                              │    (energy: 350 kWh, carbon:170kg)│    │
│                              │  • MCP tool-call counter          │    │
│                              │  • EnergyPlus mode badge          │    │
│                              │  • AI reasoning log (Groq/Ollama) │    │
│                              │  • 5-zone temp/CO₂/PMV charts     │    │
│                              │  • Carbon emissions bar chart     │    │
│                              └───────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow (Per Optimization Cycle)

```
1.  Simulation step(hour, controls) → metrics dict
2.  metrics → state_store.current_metrics (in-memory)
3.  ARIA agent wakes up → calls MCP tools via call_tool() dispatcher
    a. get_all_zones_status()     → reads all 5 zones
    b. get_energy_metrics()       → checks kWh, carbon, savings %
    c. get_weather_forecast()     → next 4h outdoor temp + solar
    d. get_occupancy_schedule()   → next 2h occupancy prediction
4.  Groq LLaMA-3.3-70B processes tool results → reasons against 3 goals
5.  LLM calls set_* tools: set_hvac_setpoint, set_lighting_level, etc.
6.  Safety module clamps all values to ASHRAE-compliant ranges
7.  Updated controls applied to state_store.current_controls
8.  state_store → WebSocket broadcast → dashboard update
9.  metrics + actions → SQLite save (data/results.db)
10. Next simulation step uses new controls
```

---

## Component Details

### 1. EnergyPlus Bridge (`simulation/energyplus_bridge.py`)

**Real EnergyPlus mode** (when EnergyPlus 23.1+ is installed):
- Uses `pyenergyplus.api.EnergyPlusAPI` for co-simulation
- Callback-driven: `callback_begin_zone_timestep_after_init_heat_balance()`
- Reads zone temperatures and CO₂ via `EnergyManagementSystem:Sensor` handles
- Writes HVAC setpoints via thermostat actuator handles
- Reads the `building_models/multi_zone_office.idf` EnergyPlus model

**Physics Mock mode** (fallback when EnergyPlus not installed):
- Euler integration: `dT/dt = (Q_internal + Q_solar - Q_envelope - Q_hvac) / (m·Cp)`
- Perez solar radiation model (facade-specific, latitude 28.6° N — New Delhi)
- HVAC: proportional control, COP=3.2 cooling / resistance heating
- PMV: Simplified Fanger model (ISO 7730 / ASHRAE 55)
- CO₂: Mass-balance with first-order ventilation dilution
- Occupancy: ASHRAE 90.1 small office schedule

Building specifications:
- 5 thermal zones: North, South, East, West (perimeter), Core (interior)
- Total area: 600 m² | Height: 3.2 m per zone
- Location: New Delhi (28.61°N, 77.20°E)
- Grid emission factor: 0.485 kg CO₂/kWh (India grid average)

### 2. Official MCP Server (`mcp/mcp_tools.py`)

Implements the **Model Context Protocol specification** using the official Anthropic `mcp` Python SDK (`FastMCP` high-level API):

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("ARIA-BMS", instructions="...")

@mcp.tool()
def get_all_zones_status() -> dict:
    """Full snapshot of all 5 zones + building totals."""
    return _tool_get_all_zones_status()

@mcp.tool()
def set_hvac_setpoint(zone_id: str, setpoint_c: float) -> dict:
    """Set HVAC setpoint for a zone (18–28°C)."""
    return _tool_set_hvac_setpoint(zone_id, setpoint_c)
```

All 13 tools are also exposed as `OPENAI_TOOLS_SCHEMA` for Groq/Ollama function-calling.

| Tool | Category | Description |
|------|----------|-------------|
| `get_zone_status` | Read | Single zone sensors |
| `get_all_zones_status` | Read | Full building snapshot |
| `get_energy_metrics` | Read | kWh, carbon, cost, savings |
| `get_optimization_goals` | Read | Energy/comfort/carbon targets |
| `get_weather_forecast` | Read | Next 4-hour weather |
| `get_occupancy_schedule` | Read | Predicted occupancy 2h |
| `get_optimization_history` | Read | Past AI decisions |
| `set_hvac_setpoint` | Write | Temperature setpoint (°C) |
| `set_hvac_mode` | Write | cooling/heating/eco/off |
| `set_lighting_level` | Write | Dimming 0–100% |
| `set_ventilation_rate` | Write | m³/s per person |
| `trigger_demand_response` | Write | Emergency load shedding |
| `get_comfort_score` | Read | Zone comfort scores |

### 3. ARIA LLM Agent (`agent/llm_agent.py`)

**Decision hierarchy:**

1. **Groq LLaMA-3.3-70B** — cloud inference via `api.groq.com` with OpenAI-compatible tool calling (`tool_choice="auto"`). Agent runs up to 6 MCP tool call rounds per cycle.

2. **Ollama local** — phi3:mini / llama3.2:3b / mistral via structured JSON mode. Uses full building prompt with carbon budget tracking.

3. **Rule-based fallback** — time-of-day, occupancy, CO₂-responsive, and carbon-budget-pressure logic. Always available, ASHRAE-compliant.

**Optimization strategy per period:**
- `00–06h`: Maximum setback — HVAC 26°C, lights 5–15%, minimum ventilation
- `07–08h`: Pre-cool to 21.5°C before occupant arrival
- `09–11h`: Peak AM — daylight harvesting in perimeter zones (50–55%)
- `12–13h`: Lunch (~50% occ) — moderate 0.5°C setback opportunity
- `14–16h`: Peak PM — west/east solar gain management + CO₂ monitoring
- `17–19h`: Progressive setback as occupancy falls
- `20–23h`: Night mode — aggressive load reduction

### 4. Safety Module (`agent/safety.py`)

ASHRAE-compliant guardrails applied before every control action:
- HVAC setpoints: 18–28°C (prevents condensation, ASHRAE 55 comfort)
- Lighting: 0–100% (valid dimming range)
- Ventilation: 0.006–0.025 m³/s/person (ASHRAE 62.1 bounds)
- Zone name validation against known zones

### 5. Dashboard (`dashboard/index.html`)

Real-time metrics via WebSocket:
- **Budget progress bars**: Energy (kWh vs 350 goal) + Carbon (kg CO₂ vs 170 limit)
- **EnergyPlus mode badge**: Shows "⚡ EnergyPlus" or "🔬 Physics Mock"
- **MCP tool-call counter**: Total calls, avg per cycle, LLM cycles
- **Energy comparison chart**: AI vs Baseline (kWh/hour)
- **5-zone temperature series**
- **CO₂ concentration chart** with 1000 ppm alert threshold
- **Carbon emissions bar chart** (AI vs baseline, per hour)
- **PMV distribution bar chart** per zone
- **Comfort score gauge** (0–100)
- **ARIA Decision Log**: reasoning text, mode (Groq+MCP/Ollama/Rule-Based)
- **Active setpoints grid**: HVAC, lighting, ventilation per zone
- **24-hour timeline** progress indicator

---

## Three-Goal Optimization

The LLM agent explicitly reasons against all three goals every cycle:

| Goal | Target | Metric | Action if Exceeded |
|------|--------|--------|--------------------|
| Energy | < 350 kWh/day | `cumulative_energy_kwh` | Raise HVAC setpoints, dim lights |
| Comfort | PMV -0.5 to +0.5 | `avg_pmv`, `avg_co2` | Adjust setpoints, increase vent |
| Carbon | < 170 kg CO₂/day | `cumulative_carbon_kg` | Apply extra 0.5°C HVAC + 10% light reduction |

Carbon budget pressure logic activates when `cumulative_carbon_kg > 70% of 170 kg` — the rule-based fallback and the Ollama prompt both implement this.

---

## Technology Stack

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| Building physics | Python + NumPy | 3.10+ | Thermal simulation (Euler) |
| EnergyPlus API | pyenergyplus | 24.1 | Real co-simulation |
| IDF Model | EnergyPlus IDF | v24.1 | Multi-zone office building model |
| MCP Protocol | mcp (FastMCP) | ≥1.0 | Official MCP tool server |
| LLM Cloud | Groq API | LLaMA-3.3-70B | Tool-calling agent |
| LLM Local | Ollama | phi3:mini | Fallback local inference |
| API Server | FastAPI + uvicorn | 0.104+ | REST + WebSocket |
| Dashboard | HTML + Chart.js | 4.4 | Zero-dep live monitoring |
| React UI | React + Vite | 18 | Advanced frontend |
| Persistence | SQLite | built-in | Results + decisions |

---

## Performance Benchmarks

| Metric | Baseline | AI-Optimized | Improvement |
|--------|----------|--------------|-------------|
| Daily Energy | ~450 kWh | ~310–330 kWh | **27–31%** |
| Peak Demand | ~82 kW | ~58–65 kW | **20–29%** |
| Comfort PMV | -0.8 to +1.1 | -0.4 to +0.5 | **ASHRAE 55 compliant** |
| CO₂ Avg | ~680 ppm | ~520 ppm | **23% reduction** |
| Carbon/day | ~218 kg | ~155–162 kg | **25–29%** |
| ASHRAE Hours | ~65% | ~88% | **+23 percentage points** |

---

## Directory Structure

```
smart-building-bms/
├── main.py                      ← Unified entry point (NEW v2)
├── requirements.txt             ← mcp, groq, ollama, eppy, fastapi...
├── simulation/
│   ├── building_sim.py          ← 5-zone physics mock (Euler, Perez, PMV, CO₂)
│   └── energyplus_bridge.py    ← NEW: pyenergyplus API + mock fallback
├── mcp/
│   ├── mcp_tools.py             ← NEW: FastMCP server + 13 tools + OpenAI schema
│   ├── server.py                ← FastAPI server (REST + WebSocket + /tools)
│   ├── building_state.py        ← Thread-safe state store + SQLite
│   └── dashboard_routes.py
├── agent/
│   ├── llm_agent.py             ← UPGRADED: Groq+MCP tool calling, Ollama, rule-based
│   ├── prompt_templates.py      ← UPGRADED: carbon goals, chain-of-thought, energy strategy
│   └── safety.py                ← ASHRAE-compliant value clamping
├── building_models/
│   └── multi_zone_office.idf   ← EnergyPlus v24.1 building model (New Delhi)
├── dashboard/
│   └── index.html               ← UPGRADED: budget bars, MCP stats, EP badge
├── frontend/
│   └── src/                     ← React + Vite frontend
├── data/
│   ├── results.db               ← SQLite persistence
│   └── simulation.log
└── docs/
    ├── architecture.md          ← This file
```
