"""Vendor-Specific Equipment Plugins Package."""

from plugins.vendor.catl_enerone import CATLEnerOneBatteryPlugin
from plugins.vendor.sma_sunnycentral import SMASunnyCentralPCSPlugin
from plugins.vendor.sungrow_sc5000 import SungrowSC5000PCSPlugin
from plugins.vendor.tesla_megapack import TeslaMegapackBatteryPlugin

__all__ = [
    "CATLEnerOneBatteryPlugin",
    "SMASunnyCentralPCSPlugin",
    "SungrowSC5000PCSPlugin",
    "TeslaMegapackBatteryPlugin",
]
