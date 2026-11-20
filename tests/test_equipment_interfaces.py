"""Automated Test Suite for Standardized Equipment Interfaces."""

from backend.app.equipment.interfaces.auxiliary import AuxiliarySystemInterface
from backend.app.equipment.interfaces.battery import BatterySystemInterface
from backend.app.equipment.interfaces.bms import BMSInterface
from backend.app.equipment.interfaces.ems import EMSInterface
from backend.app.equipment.interfaces.grid import GridModelInterface
from backend.app.equipment.interfaces.grid_service import GridServiceInterface
from backend.app.equipment.interfaces.meter import MeterInterface
from backend.app.equipment.interfaces.pcs import PCSInterface
from backend.app.equipment.interfaces.plant_controller import PlantControllerInterface
from backend.app.equipment.interfaces.ppc import PPCInterface
from backend.app.equipment.interfaces.switchgear import SwitchgearInterface
from backend.app.equipment.interfaces.transformer import TransformerInterface
from backend.app.equipment.models import EquipmentType


def test_all_twelve_equipment_interfaces_instantiation() -> None:
    """Verify all 12 equipment domain interfaces instantiate with correct EquipmentType."""
    battery = BatterySystemInterface("BAT_01")
    assert battery.equipment_type == EquipmentType.BATTERY_SYSTEM

    bms = BMSInterface("BMS_01")
    assert bms.equipment_type == EquipmentType.BMS

    pcs = PCSInterface("PCS_01")
    assert pcs.equipment_type == EquipmentType.PCS

    transformer = TransformerInterface("XFRM_01")
    assert transformer.equipment_type == EquipmentType.TRANSFORMER

    switchgear = SwitchgearInterface("SWG_01")
    assert switchgear.equipment_type == EquipmentType.SWITCHGEAR

    meter = MeterInterface("MTR_01")
    assert meter.equipment_type == EquipmentType.METER

    aux = AuxiliarySystemInterface("AUX_01")
    assert aux.equipment_type == EquipmentType.AUXILIARY_SYSTEM

    grid = GridModelInterface("GRID_01")
    assert grid.equipment_type == EquipmentType.GRID_MODEL

    plant_ctrl = PlantControllerInterface("PCTRL_01")
    assert plant_ctrl.equipment_type == EquipmentType.PLANT_CONTROLLER

    ppc = PPCInterface("PPC_01")
    assert ppc.equipment_type == EquipmentType.PPC

    ems = EMSInterface("EMS_01")
    assert ems.equipment_type == EquipmentType.EMS

    grid_svc = GridServiceInterface("GSVC_01")
    assert grid_svc.equipment_type == EquipmentType.GRID_SERVICE


def test_equipment_health_reporting() -> None:
    """Verify equipment health report dictionary structure."""
    battery = BatterySystemInterface("BAT_TEST")
    health = battery.get_health()
    assert health["equipment_id"] == "BAT_TEST"
    assert health["equipment_type"] == EquipmentType.BATTERY_SYSTEM
    assert health["is_initialized"] is False
    assert health["active_alarms_count"] == 0
