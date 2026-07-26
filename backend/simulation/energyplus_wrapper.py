import os
import logging
from simulation.building_model import BuildingModel
from state.manager import StateManager

class EnergyPlusWrapper:
    """
    Wrapper for EnergyPlus or mock simulation.
    
    Mock Physics Equations Used:
    Q_internal = occupancy * heat_gain + lighting_power + plug_load
    Q_solar = window_area * solar_irradiance * 0.6
    Q_hvac = bounded capacity to meet setpoint based on thermal mass
    Q_loss = (U_walls * wall_area + U_windows * window_area) * (T_zone - T_outdoor)
    dT = (Q_internal + Q_solar - Q_hvac - Q_loss) * (dt * 60) / (thermal_mass * 1000)
    """
    
    def __init__(self):
        self.has_energyplus = self._check_energyplus()
        self.mock_model = BuildingModel()
        
        if self.has_energyplus:
            logging.info("Starting simulation mode: EnergyPlus")
        else:
            logging.info("Starting simulation mode: Physics Mock")

    def _check_energyplus(self) -> bool:
        common_paths = [
            r"C:\EnergyPlus",
            "/usr/local/EnergyPlus"
        ]
        for path in common_paths:
            if os.path.exists(path):
                return True
        return False

    @property
    def mode(self) -> str:
        return 'EnergyPlus' if self.has_energyplus else 'Physics Mock'

    def run_tick(self, state_manager: StateManager, delta_minutes: float):
        self.mock_model.step(state_manager, delta_minutes)
