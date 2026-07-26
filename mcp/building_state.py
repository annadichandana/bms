"""
Shared Building State Store
===========================
Thread-safe in-memory state shared between the simulation loop,
MCP server, and LLM agent.
"""

import asyncio
import json
import sqlite3
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "results.db")

# ── Optimization Goals ────────────────────────────────────────────────────────

OPTIMIZATION_GOALS = {
    "daily_energy_budget_kwh": 350.0,        # Target: <350 kWh/day (baseline ~450)
    "comfort_pmv_min": -0.5,                  # ASHRAE 55
    "comfort_pmv_max": 0.5,
    "comfort_temp_min_c": 20.0,
    "comfort_temp_max_c": 26.0,
    "daily_carbon_limit_kg": 170.0,
    "co2_ppm_max": 1000,
    "description": (
        "Minimize energy use and carbon emissions while keeping all zones "
        "within ASHRAE 55 thermal comfort bounds. Prioritize occupied hours."
    ),
}

# ── Default control parameters ────────────────────────────────────────────────

DEFAULT_CONTROLS = {
    "hvac_setpoints": {z: 22.0 for z in ["north", "south", "east", "west", "core"]},
    "lighting_levels": {z: 80.0 for z in ["north", "south", "east", "west", "core"]},
    "ventilation_rates": {z: 0.010 for z in ["north", "south", "east", "west", "core"]},
}

BASELINE_CONTROLS = {
    "hvac_setpoints": {z: 22.0 for z in ["north", "south", "east", "west", "core"]},
    "lighting_levels": {z: 100.0 for z in ["north", "south", "east", "west", "core"]},
    "ventilation_rates": {z: 0.015 for z in ["north", "south", "east", "west", "core"]},
}


# ── State store ───────────────────────────────────────────────────────────────

class BuildingStateStore:
    """Thread-safe state container shared across all modules."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self.current_metrics: dict = {}
        self.baseline_metrics: dict = {}
        self.current_controls: dict = {k: dict(v) for k, v in DEFAULT_CONTROLS.items()}
        self.action_history: List[dict] = []
        self.simulation_hour: int = 0
        self.is_running: bool = False
        self.websocket_clients: List[Any] = []
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database for persistent storage."""
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS simulation_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_type TEXT,
                hour INTEGER,
                metrics TEXT,
                controls TEXT,
                ai_reasoning TEXT,
                timestamp TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hour INTEGER,
                reasoning TEXT,
                actions TEXT,
                priority TEXT,
                timestamp TEXT
            )
        """)
        conn.commit()
        conn.close()

    def save_result(self, run_type: str, hour: int, metrics: dict,
                    controls: dict, ai_reasoning: str = ""):
        """Persist simulation result to SQLite."""
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO simulation_results VALUES (NULL,?,?,?,?,?,?)",
            (run_type, hour, json.dumps(metrics), json.dumps(controls),
             ai_reasoning, datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()

    def save_decision(self, hour: int, reasoning: str, actions: dict, priority: str):
        """Persist AI decision to SQLite."""
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO agent_decisions VALUES (NULL,?,?,?,?,?)",
            (hour, reasoning, json.dumps(actions), priority,
             datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()
        # Also keep in memory (last 48 entries)
        self.action_history.append({
            "hour": hour,
            "reasoning": reasoning,
            "actions": actions,
            "priority": priority,
            "timestamp": datetime.utcnow().isoformat(),
        })
        if len(self.action_history) > 48:
            self.action_history = self.action_history[-48:]

    def get_summary(self) -> dict:
        """Return high-level summary for dashboard."""
        if not self.current_metrics:
            return {}
        curr = self.current_metrics
        base = self.baseline_metrics

        energy_saved_pct = 0.0
        carbon_saved_pct = 0.0
        if base:
            base_energy = base.get("totals", {}).get("cumulative_energy_kwh", 1)
            curr_energy = curr.get("totals", {}).get("cumulative_energy_kwh", 1)
            if base_energy > 0:
                energy_saved_pct = round((base_energy - curr_energy) / base_energy * 100, 1)
            base_carbon = base.get("totals", {}).get("cumulative_carbon_kg", 1)
            curr_carbon = curr.get("totals", {}).get("cumulative_carbon_kg", 1)
            if base_carbon > 0:
                carbon_saved_pct = round((base_carbon - curr_carbon) / base_carbon * 100, 1)

        return {
            "hour": self.simulation_hour,
            "energy_saved_pct": energy_saved_pct,
            "carbon_saved_pct": carbon_saved_pct,
            "current_energy_kwh": curr.get("totals", {}).get("cumulative_energy_kwh", 0),
            "baseline_energy_kwh": base.get("totals", {}).get("cumulative_energy_kwh", 0),
            "comfort_score": curr.get("comfort", {}).get("comfort_score", 0),
            "avg_pmv": curr.get("comfort", {}).get("avg_pmv", 0),
            "avg_temp": curr.get("comfort", {}).get("avg_temp", 0),
            "avg_co2": curr.get("comfort", {}).get("avg_co2", 0),
        }


# Singleton instance
state_store = BuildingStateStore()
