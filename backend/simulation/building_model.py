import math
from datetime import timedelta
from simulation.zones import ZONE_CONFIGS, get_outdoor_temp
from state.manager import StateManager

class BuildingModel:
    def __init__(self):
        self.zones = ZONE_CONFIGS

    def solar_irradiance(self, hour: float) -> float:
        if 6 <= hour <= 18:
            return 800 * math.sin((hour - 6) * math.pi / 12)
        return 0.0

    def step(self, state_manager: StateManager, delta_minutes: float):
        state_manager.simulation['tick_count'] += 1
        current_time = state_manager.simulation['sim_time']
        
        new_time = current_time + timedelta(minutes=delta_minutes)
        state_manager.simulation['sim_time'] = new_time
        
        hour = new_time.hour + new_time.minute / 60.0
        
        outdoor_temp = get_outdoor_temp(hour)
        state_manager.simulation['outdoor_temp'] = outdoor_temp
        
        total_tick_kwh = 0.0
        total_baseline_kwh = 0.0
        
        for zone_id, config in self.zones.items():
            zone_state = state_manager.get_zone(zone_id)
            
            sched_hour = new_time.hour
            frac = config['occupancy_schedule'].get(sched_hour, 0)
            occupancy = int(config['max_occupancy'] * frac)
            state_manager.update_zone(zone_id, occupancy=occupancy)
            zone_state = state_manager.get_zone(zone_id)
            
            heat_gain_w = occupancy * config['heat_gain_per_person_w']
            lighting_power_w = (zone_state['lighting_level'] / 100.0) * config['lighting_power_density_w_m2'] * config['area_m2']
            plug_load_w = config['plug_load_density_w_m2'] * config['area_m2']
            Q_internal = heat_gain_w + lighting_power_w + plug_load_w
            
            Q_solar = config['window_area_m2'] * self.solar_irradiance(hour) * 0.6
            
            temp = zone_state['temperature']
            setpoint = zone_state['hvac_setpoint']
            hvac_capacity_w = config['hvac_capacity_kw'] * 1000
            thermal_mass = config['thermal_mass_kj_per_k']
            
            Q_hvac = 0.0
            mode = zone_state['hvac_mode']
            if mode == 'cooling':
                Q_hvac = -min(hvac_capacity_w, max(0, temp - setpoint) * thermal_mass / 60)
            elif mode == 'heating':
                Q_hvac = min(hvac_capacity_w, max(0, setpoint - temp) * thermal_mass / 60)
            elif mode == 'eco':
                if temp > setpoint:
                    Q_hvac = -min(hvac_capacity_w * 0.6, max(0, temp - setpoint) * thermal_mass / 60)
                else:
                    Q_hvac = min(hvac_capacity_w * 0.6, max(0, setpoint - temp) * thermal_mass / 60)
            
            wall_area = 2 * (math.sqrt(config['area_m2']) * 4) * config['height_m']
            Q_loss = (config['u_value_walls'] * wall_area + config['u_value_windows'] * config['window_area_m2']) * (temp - outdoor_temp)
            
            dT = (Q_internal + Q_solar - Q_hvac - Q_loss) * (delta_minutes * 60) / (thermal_mass * 1000)
            
            def clamp(val, mn, mx):
                return max(mn, min(val, mx))
                
            new_temp = clamp(temp + dT, 10, 50)
            
            base_co2 = 400.0
            if occupancy > 0:
                target_co2 = base_co2 + occupancy * 15
                new_co2 = zone_state['co2_ppm'] + (target_co2 - zone_state['co2_ppm']) * 0.1
            else:
                new_co2 = zone_state['co2_ppm'] + (base_co2 - zone_state['co2_ppm']) * 0.1
                
            new_humidity = clamp(zone_state['humidity'] + (50 - zone_state['humidity']) * 0.05, 30, 70)
            
            hvac_power_kw = abs(Q_hvac) / 1000 / config['hvac_cop']
            light_kw = lighting_power_w / 1000
            plug_kw = plug_load_w / 1000
            
            state_manager.update_zone(
                zone_id,
                temperature=new_temp,
                co2_ppm=new_co2,
                humidity=new_humidity,
                hvac_power_kw=hvac_power_kw,
                lighting_power_kw=light_kw,
                plug_load_kw=plug_kw
            )
            
            total_tick_kwh += (hvac_power_kw + light_kw + plug_kw) * (delta_minutes / 60)
            total_baseline_kwh += zone_state.get('base_load_kw', 10.0) * (delta_minutes / 60)
            
        state_manager.update_energy(total_tick_kwh, total_baseline_kwh)

    def get_comfort_score(self, state_manager: StateManager) -> float:
        total_score = 0
        count = 0
        for zone_id, config in self.zones.items():
            zone_state = state_manager.get_zone(zone_id)
            temp = zone_state['temperature']
            co2 = zone_state['co2_ppm']
            
            score = 100.0
            if temp < config['comfort_temp_min']:
                score -= (config['comfort_temp_min'] - temp) * 10
            elif temp > config['comfort_temp_max']:
                score -= (temp - config['comfort_temp_max']) * 10
                
            if co2 > config['comfort_co2_max']:
                score -= (co2 - config['comfort_co2_max']) * 0.1
                
            total_score += max(0, score)
            count += 1
            
        return total_score / max(1, count)
