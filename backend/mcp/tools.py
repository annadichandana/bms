"""
ARIA BMS — Official MCP Server (FastMCP)
=========================================
Implements the Model Context Protocol (MCP) specification using the
official Anthropic `mcp` Python SDK (FastMCP high-level API).
This server exposes all building control tools to the LLM agent via
the standard MCP protocol, enabling true MCP-compliant tool calling.
Tools exposed:
  get_zone_status(zone_id)           — Read individual zone sensors
  get_all_zones_status()             — Full building snapshot
  get_energy_metrics()               — kWh, carbon, cost, savings
  get_optimization_goals()           — Energy/comfort/carbon targets
  get_weather_forecast()             — Next 4-hour weather prediction
  get_occupancy_schedule()           — Predicted occupancy next 2h
  get_optimization_history(n)        — Past AI decisions & outcomes
  set_hvac_setpoint(zone_id, sp)    — Set cooling/heating setpoint (°C)
  set_hvac_mode(zone_id, mode)       — cooling|heating|eco|off
  set_lighting_level(zone_id, lvl)  — 0–100% dimming
  set_ventilation_rate(zone_id, r)  — m³/s per person
  trigger_demand_response(zones)    — Emergency load shedding
  get_comfort_score()               — Zone-by-zone comfort (0–100)
Transport:
  The MCP server runs over HTTP/SSE (Server-Sent Events) so the agent
  can call it from within the same process or across the network.
  Port: 8001 (separate from the FastAPI dashboard on 8000)
"""
import logging
import math
import os
