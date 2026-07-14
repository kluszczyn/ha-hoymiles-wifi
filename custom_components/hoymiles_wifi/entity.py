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

from .const import CONF_DTU_SERIAL_NUMBER, DOMAIN, CONF_HYBRID_INVERTERS
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


class HoymilesEntity(Entity):
    """Base class for Hoymiles entities."""

    _attr_has_entity_name = True

    def __init__(self, config_entry: ConfigEntry, description: EntityDescription):
        """Initialize the Hoymiles entity."""
        super().__init__()
        self.entity_description = description
        self._config_entry = config_entry
        self._attr_unique_id = f"hoymiles_{config_entry.entry_id}_{description.key}"

        if description.port_number:
            self._attr_translation_placeholders = {
                "port_number": f"{description.port_number}"
            }
        if description.phase:
            self._attr_translation_placeholders = {"phase": f"{description.phase}"}

        dtu_serial_number = config_entry.data[CONF_DTU_SERIAL_NUMBER]

        serial_number = str(self.entity_description.serial_number)

        # Determine Master vs Slave name and nominal battery capacity info for device model
        device_name_override = None
        if self.entity_description.is_dtu_sensor is True:
            device_translation_key = "dtu"
            device_model = get_dtu_model_name(self.entity_description.serial_number)
        else:
            if "meter" in self.entity_description.key:
                device_model = get_meter_model_name(
                    self.entity_description.serial_number
                )
                device_translation_key = "meter"
            else:
                if (
                    hasattr(self.entity_description, "model_name")
                    and self.entity_description.model_name
                ):
                    # We are a hybrid inverter
                    raw_model = self.entity_description.model_name
                    device_translation_key = "hybrid_inverter"
                    
                    # Extract index to check Master/Slave routing
                    # self.entity_description.key is in format: "[index].production.energy_to_load"
                    inv_idx = 0
                    if self.entity_description.key.startswith("[") and "]" in self.entity_description.key:
                        try:
                            inv_idx = int(self.entity_description.key.split("[")[1].split("]")[0])
                        except Exception:
                            pass
                    
                    # Look up in coordinator/config_entry hybrid_inverters list to find capacity
                    bms_cap_str = ""
                    hybrid_inverters = config_entry.data.get(CONF_HYBRID_INVERTERS, [])
                    if 0 <= inv_idx < len(hybrid_inverters):
                        # The registration response info (or config_entry data) could have bms_cap
                        inverter_info = hybrid_inverters[inv_idx]
                        bms_cap = inverter_info.get("bms_cap", 0)
                        if bms_cap:
                            bms_cap_str = f", {bms_cap * 0.1:.1f} kWh battery"
                    
                    role_str = "Master" if inv_idx == 0 else f"Slave #{inv_idx}"
                    device_model = f"{raw_model} ({role_str}{bms_cap_str})"
                    
                    # Ensure device name in registry is formatted: "Inverter" (Master) or "Inverter S1", "Inverter S2" etc.
                    if inv_idx == 0:
                        device_name_override = "Inverter"
                    else:
                        device_name_override = f"Inverter S{inv_idx}"
                else:
                    device_model = get_inverter_model_name(
                        self.entity_description.serial_number
                    )
                    device_translation_key = "inverter"

        device_info = DeviceInfo(
            identifiers={(DOMAIN, serial_number)},
            translation_key=device_translation_key,
            manufacturer="Hoymiles",
            serial_number=serial_number.upper(),
            model=device_model,
        )
        if device_name_override:
            device_info["name"] = device_name_override

        if not self.entity_description.is_dtu_sensor:
            device_info["via_device"] = (DOMAIN, dtu_serial_number)

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
        HoymilesEntity.__init__(self, config_entry, description)
