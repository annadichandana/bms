import json

class BMSServer:
    def __init__(self, tools):
        self.tools = tools

    @property
    def tools_schema(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_zone_status",
                    "description": "Get current environmental and energy status for a specific building zone",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "zone_id": {
                                "type": "string",
                                "enum": ["office", "lobby", "server_room"],
                                "description": "The zone to query"
                            }
                        },
                        "required": ["zone_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_all_zones_status",
                    "description": "Get status for all 3 zones plus a summary",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_energy_metrics",
                    "description": "Get energy metrics like consumed, saved, cost, and carbon",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "set_hvac_setpoint",
                    "description": "Set the HVAC setpoint for a zone (16-28C)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "zone_id": {
                                "type": "string",
                                "enum": ["office", "lobby", "server_room"],
                                "description": "The zone to update"
                            },
                            "setpoint": {
                                "type": "number",
                                "description": "Setpoint in Celsius (16-28)"
                            }
                        },
                        "required": ["zone_id", "setpoint"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "set_hvac_mode",
                    "description": "Set the HVAC mode for a zone",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "zone_id": {
                                "type": "string",
                                "enum": ["office", "lobby", "server_room"],
                                "description": "The zone to update"
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["cooling", "heating", "eco", "off"],
                                "description": "The mode to set"
                            }
                        },
                        "required": ["zone_id", "mode"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "set_lighting_level",
                    "description": "Set lighting level for a zone (0-100)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "zone_id": {
                                "type": "string",
                                "enum": ["office", "lobby", "server_room"],
                                "description": "The zone to update"
                            },
                            "level": {
                                "type": "integer",
                                "description": "Lighting level from 0 to 100"
                            }
                        },
                        "required": ["zone_id", "level"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_weather_forecast",
                    "description": "Get next 4 hours weather forecast",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_occupancy_schedule",
                    "description": "Get next 4 hours predicted occupancy for a zone",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "zone_id": {
                                "type": "string",
                                "enum": ["office", "lobby", "server_room"],
                                "description": "The zone to query"
                            }
                        },
                        "required": ["zone_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "trigger_demand_response",
                    "description": "Activates emergency load shedding",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_optimization_history",
                    "description": "Get last n AI decisions from state manager ai_log",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "n": {
                                "type": "integer",
                                "description": "Number of history records to retrieve (default 5)"
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_comfort_score",
                    "description": "Get per-zone and overall building comfort scores",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            }
        ]

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        func = getattr(self.tools, tool_name, None)
        if not func:
            return {"error": f"Tool {tool_name} not found"}
        
        try:
            return func(**arguments)
        except Exception as e:
            return {"error": str(e)}
