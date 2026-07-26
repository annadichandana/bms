import threading
from datetime import datetime
from typing import Dict, List, Any

class StateManager:
    ENERGY_PRICE_PER_KWH = 0.12
    CARBON_FACTOR = 0.233

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.zones = {
                'office': {
                    'temperature': 26.0,
                    'humidity': 50.0,
                    'co2_ppm': 450.0,
                    'occupancy': 0,
                    'max_occupancy': 50,
                    'hvac_mode': 'off',
                    'hvac_setpoint': 22.0,
                    'lighting_level': 0,
                    'hvac_power_kw': 0.0,
                    'lighting_power_kw': 0.0,
                    'plug_load_kw': 0.0,
                    'base_load_kw': 25.0
                },
                'lobby': {
                    'temperature': 28.0,
                    'humidity': 55.0,
                    'co2_ppm': 420.0,
                    'occupancy': 0,
                    'max_occupancy': 30,
                    'hvac_mode': 'off',
                    'hvac_setpoint': 22.0,
                    'lighting_level': 0,
                    'hvac_power_kw': 0.0,
                    'lighting_power_kw': 0.0,
                    'plug_load_kw': 0.0,
                    'base_load_kw': 8.0
                },
                'server_room': {
                    'temperature': 18.0,
                    'humidity': 40.0,
                    'co2_ppm': 400.0,
                    'occupancy': 0,
                    'max_occupancy': 2,
                    'hvac_mode': 'cooling',
                    'hvac_setpoint': 18.0,
                    'lighting_level': 0,
                    'hvac_power_kw': 0.0,
                    'lighting_power_kw': 0.0,
                    'plug_load_kw': 20.0,
                    'base_load_kw': 15.0
                }
            }
            self.simulation = {
                'sim_time': datetime.now().replace(hour=8, minute=0, second=0, microsecond=0),
                'outdoor_temp': 25.0,
                'outdoor_humidity': 60.0,
                'speed_multiplier': 10,
                'running': False,
                'tick_count': 0
            }
            self.energy = {
                'total_kwh': 0.0,
                'baseline_kwh': 0.0,
                'savings_pct': 0.0,
                'carbon_kg': 0.0,
                'cost_usd': 0.0,
                'savings_usd': 0.0
            }
            self.ai_log: List[Dict[str, Any]] = []

    def get_full_state(self):
        with self.lock:
            return {
                'zones': {k: v.copy() for k, v in self.zones.items()},
                'simulation': self.simulation.copy(),
                'energy': self.energy.copy(),
                'ai_log': self.ai_log.copy()
            }

    def get_zone(self, zone_id: str):
        with self.lock:
            return self.zones.get(zone_id, {}).copy()

    def update_zone(self, zone_id: str, **kwargs):
        with self.lock:
            if zone_id in self.zones:
                self.zones[zone_id].update(kwargs)

    def update_energy(self, delta_kwh: float, delta_baseline_kwh: float):
        with self.lock:
            self.energy['total_kwh'] += delta_kwh
            self.energy['baseline_kwh'] += delta_baseline_kwh
            
            if self.energy['baseline_kwh'] > 0:
                savings = max(0, self.energy['baseline_kwh'] - self.energy['total_kwh'])
                self.energy['savings_pct'] = (savings / self.energy['baseline_kwh']) * 100
            
            self.energy['carbon_kg'] = self.energy['total_kwh'] * self.CARBON_FACTOR
            self.energy['cost_usd'] = self.energy['total_kwh'] * self.ENERGY_PRICE_PER_KWH
            
            savings_kwh = max(0, self.energy['baseline_kwh'] - self.energy['total_kwh'])
            self.energy['savings_usd'] = savings_kwh * self.ENERGY_PRICE_PER_KWH

    def add_ai_log_entry(self, entry: Dict[str, Any]):
        with self.lock:
            self.ai_log.insert(0, entry)

    def get_ai_log(self, n: int = 20):
        with self.lock:
            return self.ai_log[:n]

    def set_sim_speed(self, multiplier: int):
        with self.lock:
            self.simulation['speed_multiplier'] = multiplier
