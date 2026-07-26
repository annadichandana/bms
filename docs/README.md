# ARIA — AI-Powered Autonomous Smart Building Optimization System
### Honeywell Hackathon Submission

---

## Quick Start (3 commands)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional but recommended) Pull lightweight LLM via Ollama
#    Install Ollama from: https://ollama.com/download
ollama pull phi3:mini

# 3. Run the system
python main.py
```

Then open: **http://localhost:8000/dashboard**

---

## Project Structure

```
smart-building-bms/
├── simulation/building_sim.py    ← EnergyPlus-inspired physics model
├── mcp/server.py                 ← MCP Tool Server (FastAPI)
├── mcp/building_state.py         ← Shared state + SQLite persistence
├── agent/llm_agent.py            ← ARIA LLM Agent (Ollama)
├── agent/prompt_templates.py     ← AI prompts
├── agent/safety.py               ← Input validation guardrails
├── dashboard/index.html          ← Live savings dashboard
├── data/results.db               ← SQLite results (auto-created)
├── main.py                       ← Orchestration entry point
└── requirements.txt
```

---

## CLI Options

```bash
python main.py --hours 24 --speed 5.0        # 24hr sim, 5x speed
python main.py --hours 8  --speed 10.0       # Quick demo (8 hours)
python main.py --no-baseline --speed 20.0    # Skip baseline, fast demo
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/dashboard` | Live dashboard UI |
| GET | `/state` | Current building state |
| GET | `/goals` | Optimization goals |
| GET | `/history` | AI decision history |
| POST | `/control` | Apply control actions |
| GET | `/tools` | List MCP tools |
| POST | `/tools/call` | Invoke MCP tool |
| WS | `/ws` | Live WebSocket feed |
| GET | `/docs` | Swagger API docs |

---

## Requirements

- Python 3.10+
- Windows 10/11
- 4GB RAM minimum (8GB for LLM mode)
- Ollama (optional — rule-based fallback works without it)
