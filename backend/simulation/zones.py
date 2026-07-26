import math

ZONE_CONFIGS = {
  'office': {
    'name': 'Open Office',
    'area_m2': 400,
    'height_m': 3.0,
    'thermal_mass_kj_per_k': 2800,  # mass * Cp
    'window_area_m2': 80,
    'u_value_walls': 0.35,
    'u_value_windows': 1.8,
    'max_occupancy': 50,
    'occupancy_schedule': {  # hour -> fraction of max
      0:0, 1:0, 2:0, 3:0, 4:0, 5:0, 6:0.1, 7:0.3,
      8:0.7, 9:0.9, 10:1.0, 11:1.0, 12:0.6, 13:0.8,
      14:1.0, 15:0.9, 16:0.8, 17:0.5, 18:0.2, 19:0.1,
      20:0, 21:0, 22:0, 23:0
    },
    'lighting_power_density_w_m2': 10.0,
    'plug_load_density_w_m2': 15.0,
    'heat_gain_per_person_w': 75,
    'hvac_capacity_kw': 60,
    'hvac_cop': 3.5,
    'comfort_temp_min': 21.0,
    'comfort_temp_max': 24.0,
    'comfort_co2_max': 1000,
  },
  'lobby': {
    'name': 'Main Lobby',
    'area_m2': 120,
    'height_m': 5.0,
    'thermal_mass_kj_per_k': 1200,
    'window_area_m2': 60,
    'u_value_walls': 0.40,
    'u_value_windows': 2.0,
    'max_occupancy': 30,
    'occupancy_schedule': {
      0:0, 1:0, 2:0, 3:0, 4:0, 5:0, 6:0.2, 7:0.5,
      8:0.8, 9:0.6, 10:0.5, 11:0.5, 12:0.7, 13:0.6,
      14:0.5, 15:0.6, 16:0.7, 17:0.8, 18:0.5, 19:0.2,
      20:0.1, 21:0, 22:0, 23:0
    },
    'lighting_power_density_w_m2': 8.0,
    'plug_load_density_w_m2': 2.0,
    'heat_gain_per_person_w': 75,
    'hvac_capacity_kw': 20,
    'hvac_cop': 3.2,
    'comfort_temp_min': 20.0,
    'comfort_temp_max': 25.0,
    'comfort_co2_max': 1200,
  },
  'server_room': {
    'name': 'Server Room',
    'area_m2': 80,
    'height_m': 3.0,
    'thermal_mass_kj_per_k': 400,
    'window_area_m2': 0,
    'u_value_walls': 0.20,
    'u_value_windows': 0,
    'max_occupancy': 2,
    'occupancy_schedule': {h: 0 for h in range(24)},
    'lighting_power_density_w_m2': 5.0,
    'plug_load_density_w_m2': 250.0,  # servers
    'heat_gain_per_person_w': 75,
    'hvac_capacity_kw': 40,
    'hvac_cop': 4.0,
    'comfort_temp_min': 16.0,
    'comfort_temp_max': 22.0,
    'comfort_co2_max': 2000,
  }
}

def get_outdoor_temp(hour: int) -> float:
    # 22 at 04:00, 35 at 14:00. Average = 28.5, Amplitude = 6.5
    return 28.5 - 6.5 * math.cos((hour - 4) * math.pi / 12)
