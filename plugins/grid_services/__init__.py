"""Modular Grid Services Plugins Package."""

from plugins.grid_services.afrr import AFRRPlugin
from plugins.grid_services.energy_arbitrage import EnergyArbitragePlugin
from plugins.grid_services.fcr import FCRPlugin
from plugins.grid_services.mfrr import MFRRPlugin
from plugins.grid_services.peak_shaving import PeakShavingPlugin
from plugins.grid_services.renewable_smoothing import RenewableSmoothingPlugin
from plugins.grid_services.volt_var import VoltVarSupportPlugin

__all__ = [
    "AFRRPlugin",
    "EnergyArbitragePlugin",
    "FCRPlugin",
    "MFRRPlugin",
    "PeakShavingPlugin",
    "RenewableSmoothingPlugin",
    "VoltVarSupportPlugin",
]
