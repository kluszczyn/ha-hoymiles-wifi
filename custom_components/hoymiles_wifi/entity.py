"""Entity base for Hoymiles entities."""

from dataclasses import dataclass
import logging

from enum import Enum

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from hoymiles_wifi.hoymiles import (
    DTUType,
    get_dtu_model_name,
    get_inverter_model_name,
    get_meter_model_name,
)

from .const import CONF_DTU_SERIAL_NUMBER, DOMAIN, CONF_HYBRID_INVERTERS, CONF_THREE_PHASE_INVERTERS
from .coordinator import (
    HoymilesDataUpdateCoordinator,
)

_LOGGER = logging.getLogger(__name__)


class DeviceType(Enum):
    """Device type."""

    ALL_DEVICES = 0
    SINGLE_PHASE_METER = 1
    THREE_PHASE_METER = 3


@dataclass(frozen=True)
class HoymilesEntityDescription(EntityDescription):
    """Class to describe a Hoymiles Button entity."""

    is_dtu_sensor: bool = False
    serial_number: str = None
    port_number: int = None
    supported_dtu_types: list[DTUType] = None
    phase: str = None
    model_name: str = None


class HoymilesEntity(Entity):
    """Base class for Hoymiles entities."""

    _attr_has_entity_name = True

    def __init__(self, config_entry: ConfigEntry, description: EntityDescription, coordinator: HoymilesDataUpdateCoordinator = None):
        """Initialize the Hoymiles entity."""
        super().__init__()
        self.entity_description = description
        self._config_entry = config_entry
        self._coordinator = coordinator
        self.hass = coordinator.hass if coordinator else None
        
        key = description.key
        suggested_object_id = None
        
        # Check if we are in a multi-inverter configuration
        hybrid_inverters = config_entry.data.get(CONF_HYBRID_INVERTERS, [])
        is_multi_inverter = len(hybrid_inverters) > 1

        if key.startswith("[") and "]" in key:
            try:
                # Extract index
                inv_idx = int(key.split("[")[1].split("]")[0])
                cleaned_key = key.replace(f"[{inv_idx}].", "")

                if is_multi_inverter:
                    infix = "m" if inv_idx == 0 else f"s{inv_idx}"
                    if cleaned_key == "ems_mode":
                        suggested_object_id = f"hybrid_{infix}"
                        self._attr_unique_id = f"hoymiles_{config_entry.entry_id}_hybrid_{infix}"
                    else:
                        suggested_object_id = f"hybrid_inverter_{infix}_{cleaned_key.replace('.', '_')}"
                        self._attr_unique_id = f"hoymiles_{config_entry.entry_id}_hybrid_inverter_{infix}_{cleaned_key}"
                else:
                    if cleaned_key == "ems_mode":
                        suggested_object_id = "hybrid"
                        self._attr_unique_id = f"hoymiles_{config_entry.entry_id}_hybrid"
                    else:
                        suggested_object_id = f"hybrid_inverter_{cleaned_key.replace('.', '_')}"
                        self._attr_unique_id = f"hoymiles_{config_entry.entry_id}_hybrid_inverter_{cleaned_key}"
            except Exception:
                suggested_object_id = key.replace('.', '_')
                self._attr_unique_id = f"hoymiles_{config_entry.entry_id}_{key}"
        else:
            suggested_object_id = key.replace('.', '_')
            self._attr_unique_id = f"hoymiles_{config_entry.entry_id}_{key}"

        if description.port_number:
            self._attr_translation_placeholders = {
                "port_number": f"{description.port_number}"
            }
        if description.phase:
            self._attr_translation_placeholders = {"phase": f"{description.phase}"}

        cleaned_key = key
        inv_idx = 0
        if key.startswith("[") and "]" in key:
            try:
                inv_idx = int(key.split("[")[1].split("]")[0])
                cleaned_key = key.replace(f"[{inv_idx}].", "")
            except Exception:
                pass

        if cleaned_key == "ems_mode":
            self._attr_name = ""
            self._attr_has_entity_name = True

        dtu_serial_number = config_entry.data[CONF_DTU_SERIAL_NUMBER]
        serial_number = str(self.entity_description.serial_number)

        dtu_serial_str = str(dtu_serial_number).lower()
        inv_serial_str = str(serial_number).lower()

        if description.phase:
            # 3-phase inverter: set phase placeholder ("A", "B", or "C")
            self._attr_translation_placeholders = {"phase": f" {description.phase}"}
        else:
            # 1-phase inverter: phase is None → add empty placeholder so
            # translation strings using {phase} still render without a suffix
            if hasattr(description, "phase") and description.phase is None:
                # Only strip if the translation key contains "phase" (i.e. is a phase-type sensor)
                # Check translation_key to decide
                tk = getattr(description, "translation_key", "") or ""
                if "_phase" in tk:
                    self._attr_translation_placeholders = {"phase": ""}


        if suggested_object_id:
            self._attr_suggested_object_id = suggested_object_id

        device_name_override = None
        
        is_hybrid = False
        if key.startswith("[") and "]" in key:
            try:
                inv_idx = int(key.split("[")[1].split("]")[0])
                if 0 <= inv_idx < len(hybrid_inverters):
                    is_hybrid = True
            except Exception:
                pass

        # SAFE RESOLUTION OF DEVICE MODEL NAMES TO PREVENT CRASHES FROM UNKNOWN SERIALS
        if self.entity_description.is_dtu_sensor is True:
            device_translation_key = "dtu"
            serial_str = str(self.entity_description.serial_number)
            try:
                device_model = get_dtu_model_name(serial_str)
            except Exception:
                try:
                    hex_serial = hex(int(serial_str))[2:]
                    if len(hex_serial) % 2 != 0:
                        hex_serial = "0" + hex_serial
                    device_model = get_dtu_model_name(hex_serial)
                except Exception:
                    device_model = "HYS Built-in DTU"
        else:
            if "meter" in self.entity_description.key:
                device_translation_key = "meter"
                try:
                    device_model = get_meter_model_name(self.entity_description.serial_number)
                except Exception:
                    device_model = "Chint Smart Meter"
            elif is_hybrid:
                inverter_info = hybrid_inverters[inv_idx]
                raw_model = inverter_info.get("model_name", "Hybrid Inverter")
                device_translation_key = "hybrid_inverter"
                
                bms_cap_str = ""
                bms_cap = inverter_info.get("bms_cap", 0)
                if bms_cap:
                    bms_cap_str = f", {bms_cap * 0.1:.1f} kWh battery"
                
                role_str = "Master" if inv_idx == 0 else f"Slave #{inv_idx}"
                device_model = f"{raw_model} ({role_str}{bms_cap_str})"
                
                if inv_idx == 0:
                    device_name_override = "Hybrid M"
                else:
                    device_name_override = f"Hybrid S{inv_idx}"
            else:
                device_translation_key = "inverter"
                try:
                    device_model = get_inverter_model_name(self.entity_description.serial_number)
                except Exception:
                    device_model = "Hoymiles Inverter"

        device_info = DeviceInfo(
            identifiers={(DOMAIN, inv_serial_str)},
            translation_key=device_translation_key,
            manufacturer="Hoymiles",
            serial_number=inv_serial_str.upper(),
            model=device_model,
        )
        
        if device_name_override:
            device_info["name"] = device_name_override

            if 0 <= inv_idx < len(hybrid_inverters):
                inverter_info = hybrid_inverters[inv_idx]
                
                from .const import HASS_ENERGY_STORAGE_DATA_COORDINATOR
                is_three_phase = False
                if self.hass:
                    hass_data = self.hass.data[DOMAIN][config_entry.entry_id]
                    coord = hass_data.get(HASS_ENERGY_STORAGE_DATA_COORDINATOR, None)
                    if coord and hasattr(coord, "three_phase_inverters_set"):
                        is_three_phase = inv_serial_str in coord.three_phase_inverters_set
                phase_str = "3-phase" if is_three_phase else "1-phase"

                sw_m_ver = inverter_info.get("sw_m_ver", "Unknown")
                sw_s_ver = inverter_info.get("sw_s_ver", "Unknown")
                sw_sys_ver = inverter_info.get("sw_sys_ver", "Unknown")
                pv_num = inverter_info.get("pv_num", 0)
                bms_cap = inverter_info.get("bms_cap", 0)
                bms_cap_val = f"{bms_cap * 0.1:.1f} kWh" if bms_cap else "None"

                device_info["sw_version"] = f"Power: {sw_m_ver} | Safety: {sw_s_ver} | System: {sw_sys_ver}"
                device_info["hw_version"] = f"{phase_str} | {pv_num} PV strings | Battery capacity: {bms_cap_val}"

        if not self.entity_description.is_dtu_sensor:
            device_info["via_device"] = (DOMAIN, dtu_serial_str)

        self._attr_device_info = device_info


class HoymilesCoordinatorEntity(CoordinatorEntity, HoymilesEntity):
    """Represents a Hoymiles coordinator entity."""

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: EntityDescription,
        coordinator: HoymilesDataUpdateCoordinator,
    ):
        """Pass coordinator to CoordinatorEntity."""
        CoordinatorEntity.__init__(self, coordinator)
        HoymilesEntity.__init__(self, config_entry, description, coordinator)