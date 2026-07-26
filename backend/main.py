# Smart Building BMS - Main Application Entry Point
# AI-Powered Autonomous Building Management System
# Honeywell Hackathon 2024

import os
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Import modules
from state.manager import StateManager
from simulation.energyplus_wrapper import EnergyPlusWrapper
from mcp.tools import BMSTools
from mcp.server import BMSServer
from ai.agent import BMSAgent
from ai.prompts import SYSTEM_PROMPT

from api.routes import router as api_router
import api.routes as routes
from api.websocket import WebSocketManager

load_dotenv()

app = FastAPI(
    title="Smart Building BMS",
    description="AI-Powered Autonomous Building Management System",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
state_manager = StateManager()
energyplus_wrapper = EnergyPlusWrapper()
bms_tools = BMSTools(state_manager)
bms_server = BMSServer(bms_tools)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama3-70b-8192")
bms_agent = BMSAgent(
    groq_api_key=GROQ_API_KEY,
    model_name=GROQ_MODEL,
    mcp_server=bms_server,
    state_manager=state_manager
)

# Start simulation running by default
state_manager.simulation["running"] = True
state_manager.simulation["speed_multiplier"] = int(os.getenv("SIM_SPEED_MULTIPLIER", "10"))

# Set global references in routes
routes.state_manager = state_manager
routes.energyplus_wrapper = energyplus_wrapper
routes.bms_tools = bms_tools
routes.bms_server = bms_server
routes.bms_agent = bms_agent

websocket_manager = WebSocketManager()
scheduler = AsyncIOScheduler()

app.include_router(api_router)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket_manager.connect(websocket)
    try:
        # Send initial state immediately
        initial_state = state_manager.get_full_state()
        await websocket_manager.send_personal(websocket, initial_state)
        
        while True:
            # Keep alive
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)
    except Exception as e:
        websocket_manager.disconnect(websocket)

tick_counter = 0

async def simulation_loop():
    global tick_counter
    if not state_manager.simulation.get("running", False):
        return

    speed_multiplier = state_manager.simulation.get("speed_multiplier", 10)
    delta_minutes = speed_multiplier * 15
    
    # Run energyplus wrapper tick
    energyplus_wrapper.run_tick(state_manager, delta_minutes)
    
    tick_counter += 1
    # Every 4 ticks (= 1 sim hour), run agent
    if tick_counter >= 4:
        asyncio.create_task(bms_agent.run_optimization_cycle())
        tick_counter = 0
        
    full_state = state_manager.get_full_state()
    await websocket_manager.broadcast(full_state)

@app.on_event("startup")
async def startup_event():
    print("Starting Smart Building BMS API...")
    mode = getattr(energyplus_wrapper, "mode", "unknown")
    print(f"EnergyPlus Wrapper Mode: {mode}")
    
    # Scheduler tick interval: 1.5 seconds real time
    scheduler.add_job(simulation_loop, 'interval', seconds=1.5)
    scheduler.start()

@app.on_event("shutdown")
async def shutdown_event():
    print("Shutting down Smart Building BMS API...")
    scheduler.shutdown()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
