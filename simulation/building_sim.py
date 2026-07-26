"""
Building Physics Simulator
==========================
EnergyPlus-inspired thermal model for a 5-zone small office building.
Provides realistic energy, temperature, PMV, and CO2 simulation
without requiring a full EnergyPlus installation.

Zones: North, South, East, West (perimeter), Core (interior)
"""

import math
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ── Building constants ────────────────────────────────────────────────────────

ZONES = ["north", "south", "east", "west", "core"]

# Zone areas (m²) and thermal mass (kJ/K) — small 3-storey office
ZONE_AREA = {"north": 120, "south": 120, "east": 80, "west": 80, "core": 200}
ZONE_HEIGHT = 3.2  # m
ZONE_VOLUME = {z: ZONE_AREA[z] * ZONE_HEIGHT for z in ZONES}

# Thermal properties
ZONE_THERMAL_MASS = {z: ZONE_VOLUME[z] * 1.225 * 1.006 * 12 for z in ZONES}  # kJ/K
WALL_UA = {"north": 180, "south": 180, "east": 120, "west": 120, "core": 60}  # W/K
WINDOW_SHGC = 0.4          # Solar heat gain coefficient
WINDOW_AREA = {"north": 24, "south": 36, "east": 16, "west": 16, "core": 0}   # m²

# Equipment heat gains (W/m²)
EQUIPMENT_DENSITY = 12.0   # W/m²
PERSON_HEAT_GAIN = 130.0   # W/person (sensible + latent)
MAX_OCCUPANCY = {"north": 12, "south": 12, "east": 8, "west": 8, "core": 30}

# Lighting (W/m²)
MAX_LIGHTING_DENSITY = 10.5  # W/m²

# HVAC sizing (W per zone)
HVAC_CAPACITY = {z: ZONE_AREA[z] * 120 for z in ZONES}   # 120 W/m²
HVAC_COP = 3.2             # Coefficient of Performance

# Ventilation
MIN_VENTILATION = 0.006    # m³/s per person (ASHRAE 62.1)
MAX_VENTILATION = 0.025

# CO2
CO2_AMBIENT = 400          # ppm
CO2_PER_PERSON = 0.0053    # m³/s per person (metabolic)


# ── Solar radiation model ────────────────────────────────────────────────────

def solar_radiation(hour: float, month: int = 6) -> Dict[str, float]:
    """
    Simplified Perez solar radiation model.
    Returns incident radiation (W/m²) per facade.
    """
    # Solar declination
    day_of_year = (month - 1) * 30 + 15
    declination = 23.45 * math.sin(math.radians(360 / 365 * (day_of_year - 81)))
    lat = 28.6  # New Delhi latitude (generic commercial city)

    # Hour angle
    solar_noon = 12.0
    hour_angle = 15 * (hour - solar_noon)

    # Solar altitude
    sin_alt = (math.sin(math.radians(lat)) * math.sin(math.radians(declination))
               + math.cos(math.radians(lat)) * math.cos(math.radians(declination))
               * math.cos(math.radians(hour_angle)))
    altitude = math.degrees(math.asin(max(0, sin_alt)))

    if altitude <= 0:
        return {z: 0.0 for z in ZONES}

    # Direct normal irradiance
    dni = 900 * math.sin(math.radians(altitude))
    dhi = 150  # Diffuse horizontal

    # Azimuth
    cos_az = ((math.sin(math.radians(declination)) - sin_alt * math.sin(math.radians(lat)))
              / (math.cos(math.radians(altitude)) * math.cos(math.radians(lat)) + 1e-9))
    azimuth = math.degrees(math.acos(max(-1, min(1, cos_az))))
    if hour > solar_noon:
        azimuth = 360 - azimuth

    # Irradiance on each facade
    def facade_irr(surface_az):
        inc_angle = math.cos(math.radians(altitude)) * math.cos(math.radians(azimuth - surface_az))
        return max(0, dni * inc_angle + dhi * 0.5)

    return {
        "north": facade_irr(0) * WINDOW_SHGC * WINDOW_AREA["north"],
        "south": facade_irr(180) * WINDOW_SHGC * WINDOW_AREA["south"],
        "east":  facade_irr(90)  * WINDOW_SHGC * WINDOW_AREA["east"],
        "west":  facade_irr(270) * WINDOW_SHGC * WINDOW_AREA["west"],
        "core":  0.0,
    }


# ── Occupancy schedule ───────────────────────────────────────────────────────

def occupancy_fraction(hour: float) -> float:
    """Typical office occupancy fraction (0-1)."""
    if 0 <= hour < 7:
        return 0.02
    elif 7 <= hour < 8:
        return 0.1 + 0.5 * (hour - 7)
    elif 8 <= hour < 9:
        return 0.6 + 0.35 * (hour - 8)
    elif 9 <= hour < 12:
        return 0.95
    elif 12 <= hour < 13:
        return 0.5  # Lunch
    elif 13 <= hour < 17:
        return 0.95
    elif 17 <= hour < 18:
        return 0.7 - 0.6 * (hour - 17)
    elif 18 <= hour < 19:
        return 0.1 - 0.08 * (hour - 18)
    else:
        return 0.02


def outdoor_temperature(hour: float, day_temp: float = 35.0, night_temp: float = 24.0) -> float:
    """Sinusoidal outdoor temperature model (°C)."""
    return (day_temp + night_temp) / 2 + (day_temp - night_temp) / 2 * math.sin(
        math.radians((hour - 6) * 15))


# ── PMV calculation (Fanger model) ──────────────────────────────────────────

def calculate_pmv(t_air: float, rh: float = 50, met: float = 1.2, clo: float = 0.5,
                  v_air: float = 0.1) -> float:
    """
    Simplified linear PMV approximation (ISO 7730 / ASHRAE 55).
    Valid range: 10-30°C, 0-100% RH
    Returns value in range [-3, +3]. Comfort zone: [-0.5, +0.5]
    """
    # Calibrated for: 22°C = PMV 0.0, 26°C ≈ +0.8, 19°C ≈ -0.6
    t_neutral = 22.0 + (50 - rh) * 0.04  # RH adjustment
    pmv = (t_air - t_neutral) * 0.22
    return max(-3.0, min(3.0, round(pmv, 2)))



# ── Zone state dataclass ─────────────────────────────────────────────────────

@dataclass
class ZoneState:
    name: str
    temperature: float = 22.0    # °C
    co2_ppm: float = 450.0
    pmv: float = 0.0
    occupancy: int = 0
    hvac_power_kw: float = 0.0
    lighting_power_kw: float = 0.0
    equipment_power_kw: float = 0.0


# ── Main building simulator ──────────────────────────────────────────────────

class BuildingSimulator:
    """
    Physics-based building thermal simulation.
    Simulates one hour at a time with Euler integration.
    """

    def __init__(self):
        self.zones: Dict[str, ZoneState] = {
            z: ZoneState(name=z) for z in ZONES
        }
        self.hour = 0.0
        self.history: List[dict] = []
        self.total_energy_kwh = 0.0
        self.total_carbon_kg = 0.0
        self.dt_seconds = 3600  # 1 hour timestep

        # Initialize temperatures to a realistic pre-conditioned state
        for z in ZONES:
            self.zones[z].temperature = 22.0
            self.zones[z].co2_ppm = 420.0

        # Warm up simulation for 6 hours at night (hour 0-5) to equilibrate
        self._warmup()

    def _warmup(self):
        """Run 6 silent warm-up hours (hours 0-5) to reach thermal equilibrium."""
        night_sp = {z: 24.0 for z in ZONES}  # Night setback
        night_light = {z: 5.0 for z in ZONES}
        night_vent = {z: 0.006 for z in ZONES}
        for h in range(6):
            self.step(h, night_sp, night_light, night_vent)
        # Reset accumulators (warmup doesn't count)
        self.total_energy_kwh = 0.0
        self.total_carbon_kg = 0.0
        self.history = []

    def step(
        self,
        hour: float,
        hvac_setpoints: Dict[str, float],
        lighting_levels: Dict[str, float],  # 0-100 %
        ventilation_rates: Dict[str, float],  # m³/s per person
    ) -> dict:
        """
        Advance simulation by one hour.
        Returns dict with all zone metrics and building totals.
        """
        self.hour = hour
        t_outdoor = outdoor_temperature(hour)
        solar = solar_radiation(hour)
        occ_frac = occupancy_fraction(hour)

        zone_results = {}
        total_hvac_kw = 0.0
        total_lighting_kw = 0.0
        total_equipment_kw = 0.0

        for zone_name, zone in self.zones.items():
            sp = hvac_setpoints.get(zone_name, 22.0)
            light_pct = lighting_levels.get(zone_name, 80.0) / 100.0
            vent = ventilation_rates.get(zone_name, 0.01)

            # Occupancy
            max_occ = MAX_OCCUPANCY[zone_name]
            occupancy = max(0, int(max_occ * occ_frac))
            zone.occupancy = occupancy

            # Internal heat gains (W)
            q_people = occupancy * PERSON_HEAT_GAIN
            q_equipment = ZONE_AREA[zone_name] * EQUIPMENT_DENSITY * occ_frac
            q_lighting = ZONE_AREA[zone_name] * MAX_LIGHTING_DENSITY * light_pct
            q_solar = solar.get(zone_name, 0.0)

            # Envelope heat transfer (W) — positive = heat loss to outdoors
            q_envelope = WALL_UA[zone_name] * (zone.temperature - t_outdoor)

            # Ventilation load (W) — energy to condition fresh air
            vent_flow = vent * max(1, occupancy)  # m³/s
            q_ventilation = vent_flow * 1.225 * 1006 * (zone.temperature - t_outdoor)

            # Net heat surplus in zone (W) before HVAC
            q_surplus = q_people + q_equipment + q_lighting + q_solar - q_envelope - q_ventilation

            # HVAC setpoint tracking: proportional controller
            # Positive hvac_output = cooling (removes heat), negative = heating (adds heat)
            temp_error = zone.temperature - sp  # positive → too warm → need cooling
            kp = 5000.0  # Proportional gain W/°C
            hvac_required = kp * temp_error + q_surplus  # total HVAC action needed

            # Clamp to equipment capacity
            hvac_output = max(-HVAC_CAPACITY[zone_name],
                              min(HVAC_CAPACITY[zone_name], hvac_required))

            # New zone temperature (Euler integration)
            # dT = (gains - losses - hvac_removal) / thermal_mass
            dT_dt = (q_surplus - hvac_output) / (ZONE_THERMAL_MASS[zone_name] * 1000)
            zone.temperature += dT_dt * self.dt_seconds
            zone.temperature = round(zone.temperature, 2)

            # HVAC electricity (W → kW)  Cooling uses COP, Heating uses resistance
            if hvac_output > 0:  # Cooling
                hvac_elec_kw = hvac_output / (HVAC_COP * 1000)
            else:  # Heating
                hvac_elec_kw = abs(hvac_output) / (1.0 * 1000)
            zone.hvac_power_kw = round(hvac_elec_kw, 3)

            # Lighting electricity
            zone.lighting_power_kw = round(
                ZONE_AREA[zone_name] * MAX_LIGHTING_DENSITY * light_pct / 1000, 3)

            # Equipment electricity (always on during occupancy)
            zone.equipment_power_kw = round(
                ZONE_AREA[zone_name] * EQUIPMENT_DENSITY * occ_frac / 1000, 3)

            # CO2 mass balance (ppm, 1-hour timestep)
            # Generation: each person exhales ~0.3 L/min CO2 → raises ppm in zone
            # Ventilation: fresh air dilutes CO2 back toward ambient 400 ppm
            ach_vent = (vent * max(1, occupancy) * 3600) / ZONE_VOLUME[zone_name]  # air changes/hr
            # Steady-state CO2 with occupancy
            co2_ss = CO2_AMBIENT + (occupancy * 3500) / max(0.1, vent * max(1, occupancy) * 3600)
            # Exponential decay toward steady state (first-order ODE solution)
            tau = 1.0 / max(0.05, ach_vent)  # time constant in hours
            zone.co2_ppm = co2_ss + (zone.co2_ppm - co2_ss) * math.exp(-1.0 / max(0.1, tau))
            zone.co2_ppm = max(400, min(2500, round(zone.co2_ppm, 1)))

            # PMV
            zone.pmv = round(calculate_pmv(zone.temperature), 2)

            total_hvac_kw += zone.hvac_power_kw
            total_lighting_kw += zone.lighting_power_kw
            total_equipment_kw += zone.equipment_power_kw

            zone_results[zone_name] = {
                "temperature": zone.temperature,
                "pmv": zone.pmv,
                "co2_ppm": zone.co2_ppm,
                "occupancy": zone.occupancy,
                "hvac_kw": zone.hvac_power_kw,
                "lighting_kw": zone.lighting_power_kw,
                "equipment_kw": zone.equipment_power_kw,
            }

        # Building totals
        total_kw = total_hvac_kw + total_lighting_kw + total_equipment_kw
        energy_kwh = total_kw * 1.0  # 1 hour
        carbon_kg = energy_kwh * 0.485  # India grid emission factor (kg CO₂/kWh)

        self.total_energy_kwh += energy_kwh
        self.total_carbon_kg += carbon_kg

        avg_temp = round(
            sum(self.zones[z].temperature for z in ZONES) / len(ZONES), 2)
        avg_pmv = round(
            sum(self.zones[z].pmv for z in ZONES) / len(ZONES), 2)
        avg_co2 = round(
            sum(self.zones[z].co2_ppm for z in ZONES) / len(ZONES), 1)

        result = {
            "hour": hour,
            "outdoor_temp": round(t_outdoor, 1),
            "occupancy_fraction": round(occ_frac, 2),
            "zones": zone_results,
            "totals": {
                "hvac_kw": round(total_hvac_kw, 2),
                "lighting_kw": round(total_lighting_kw, 2),
                "equipment_kw": round(total_equipment_kw, 2),
                "total_kw": round(total_kw, 2),
                "energy_kwh": round(energy_kwh, 2),
                "carbon_kg": round(carbon_kg, 3),
                "cumulative_energy_kwh": round(self.total_energy_kwh, 2),
                "cumulative_carbon_kg": round(self.total_carbon_kg, 3),
            },
            "comfort": {
                "avg_temp": avg_temp,
                "avg_pmv": avg_pmv,
                "avg_co2": avg_co2,
                "comfort_score": _comfort_score(avg_pmv, avg_co2),
            },
        }
        self.history.append(result)
        return result

    def reset(self):
        """Reset simulation to initial conditions."""
        self.zones = {z: ZoneState(name=z) for z in ZONES}
        self.hour = 0.0
        self.history = []
        self.total_energy_kwh = 0.0
        self.total_carbon_kg = 0.0

    def get_current_state(self) -> dict:
        """Return current state snapshot for the agent."""
        if not self.history:
            return {}
        return self.history[-1]


def _comfort_score(pmv: float, co2: float) -> float:
    """Composite comfort score 0-100 (higher = better)."""
    pmv_score = max(0, 100 - abs(pmv) * 40)
    co2_score = max(0, 100 - max(0, co2 - 600) * 0.1)
    return round((pmv_score * 0.7 + co2_score * 0.3), 1)
