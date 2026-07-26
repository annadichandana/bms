from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

# Globals to be set by main.py
state_manager = None
energyplus_wrapper = None
bms_tools = None
bms_server = None
bms_agent = None

class SetpointRequest(BaseModel):
    zone_id: str
    setpoint: float

class ModeRequest(BaseModel):
    zone_id: str
    mode: str

class LightingRequest(BaseModel):
    zone_id: str
    level: float

class SpeedRequest(BaseModel):
    multiplier: int

@router.get("/api/status")
def get_status():
    return state_manager.get_full_state()

@router.get("/api/zones")
def get_zones():
    state = state_manager.get_full_state()
    return state.get("zones", {})

@router.get("/api/zones/{zone_id}")
def get_zone(zone_id: str):
    zone = state_manager.get_zone(zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    return zone

@router.get("/api/energy")
def get_energy():
    state = state_manager.get_full_state()
    return state.get("energy", {})

@router.get("/api/ai-log")
def get_ai_log():
    return state_manager.get_ai_log(20)

@router.post("/api/control/hvac-setpoint")
def update_hvac_setpoint(req: SetpointRequest):
    zone = state_manager.get_zone(req.zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    if req.setpoint < 16 or req.setpoint > 28:
        raise HTTPException(status_code=400, detail="Setpoint must be between 16 and 28°C")
    state_manager.update_zone(req.zone_id, hvac_setpoint=req.setpoint)
    return {"status": "success", "message": f"Updated setpoint for {req.zone_id} to {req.setpoint}°C"}

@router.post("/api/control/hvac-mode")
def update_hvac_mode(req: ModeRequest):
    zone = state_manager.get_zone(req.zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    valid_modes = ["cooling", "heating", "eco", "off"]
    if req.mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Mode must be one of: {valid_modes}")
    state_manager.update_zone(req.zone_id, hvac_mode=req.mode)
    return {"status": "success", "message": f"Updated HVAC mode for {req.zone_id} to {req.mode}"}

@router.post("/api/control/lighting")
def update_lighting(req: LightingRequest):
    zone = state_manager.get_zone(req.zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    level = max(0, min(100, int(req.level)))
    state_manager.update_zone(req.zone_id, lighting_level=level)
    return {"status": "success", "message": f"Updated lighting for {req.zone_id} to {level}%"}

@router.post("/api/control/demand-response")
def trigger_demand_response():
    if bms_tools:
        result = bms_tools.trigger_demand_response()
        return result
    return {"status": "success", "message": "Demand response triggered"}

@router.post("/api/simulation/speed")
def set_sim_speed(req: SpeedRequest):
    if req.multiplier < 1 or req.multiplier > 100:
        raise HTTPException(status_code=400, detail="Multiplier must be between 1 and 100")
    state_manager.set_sim_speed(req.multiplier)
    return {"status": "success", "multiplier": req.multiplier}

@router.post("/api/simulation/start")
def start_simulation():
    state_manager.simulation["running"] = True
    return {"status": "success", "message": "Simulation started"}

@router.post("/api/simulation/stop")
def stop_simulation():
    state_manager.simulation["running"] = False
    return {"status": "success", "message": "Simulation stopped"}

@router.post("/api/simulation/reset")
def reset_simulation():
    state_manager.reset()
    return {"status": "success", "message": "Simulation reset"}

@router.get("/api/health")
def health_check():
    mode = getattr(energyplus_wrapper, "mode", "unknown") if energyplus_wrapper else "unknown"
    return {
        "status": "ok",
        "mode": mode,
        "ai_connected": bms_agent is not None,
        "groq_key_set": bool(state_manager) and True
    }
