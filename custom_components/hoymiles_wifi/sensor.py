"""Support for Hoymiles sensors mapped with modern HA Core standards."""

import dataclasses
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum
import logging
import re

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfReactivePower,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import hoymiles_wifi.hoymiles
from hoymiles_wifi.hoymiles import DTUType, get_dtu_model_type

from .const import (
    BatteryStatus,
    InverterStatus,
    EmsWorkingMode,
    BATTERY_STATUS_MAP,
    INVERTER_STATUS_MAP,
    EMS_WORKING_MODE_MAP,
    CONF_DTU_SERIAL_NUMBER,
    CONF_INVERTERS,
    CONF_HYBRID_INVERTERS,
    CONF_METERS,
    CONF_PORTS,
    CONF_THREE_PHASE_INVERTERS,
    DOMAIN,
    FCTN_GENERATE_DTU_VERSION_STRING,
    FCTN_GENERATE_INVERTER_HW_VERSION_STRING,
    FCTN_GENERATE_INVERTER_SW_VERSION_STRING,
    HASS_APP_INFO_COORDINATOR,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
    HASS_ENERGY_STORAGE_DATA_COORDINATOR,
)
from .entity import (
    HoymilesCoordinatorEntity,
    HoymilesEntityDescription,
    DeviceType,
)

_LOGGER = logging.getLogger(__name__)


class ConversionAction(Enum):
    """Enumeration for conversion actions."""

    HEX = 1


@dataclass(frozen=True)
class HoymilesSensorEntityDescriptionMixin:
    """Mixin for required keys."""


@dataclass(frozen=True)
class HoymilesSensorEntityDescription(
    HoymilesEntityDescription, SensorEntityDescription
):
    """Describes Hoymiles data sensor entity."""

    conversion_factor: float = None
    reset_at_midnight: bool = False
    version_translation_function: str = None
    version_prefix: str = None
    assume_state: bool = False
    requires_device_type: int = DeviceType.ALL_DEVICES
    force_keep_maximum_within_day: bool = False


@dataclass(frozen=True)
class HoymilesEnergyStorageSensorEntityDescription(
    HoymilesEntityDescription, SensorEntityDescription
):
    """Describes Hoymiles energy storage data sensor entity."""

    conversion_factor: float = None
    reset_at_midnight: bool = False
    version_translation_function: str = None
    version_prefix: str = None
    assume_state: bool = False
    force_keep_maximum_within_day: bool = False
    suggested_display_precision: int = None
    is_bms_device: bool = False  # True routes the entity to the Battery device, False keeps it in the Inverter device
    is_battery_pack_device: bool = False
    is_smart_load_device: bool = False
    is_external_meter_device: bool = False
    is_generator_device: bool = False


@dataclass(frozen=True)
class HoymilesDiagnosticEntityDescription(
    HoymilesEntityDescription, SensorEntityDescription
):
    """Describes Hoymiles diagnostic sensor entity."""

    conversion: ConversionAction = None
    separator: str = None


HOYMILES_SENSORS = [
    HoymilesSensorEntityDescription(
        key="dtu_power",
        translation_key="ac_active_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        is_dtu_sensor=True,
        supported_dtu_types=[
            DTUType.DTU_G100,
            DTUType.DTU_W100,
            DTUType.DTU_LITE_S,
            DTUType.DTU_LITE,
            DTUType.DTU_PRO,
            DTUType.DTU_PRO_S,
            DTUType.DTUBI,
            DTUType.DTU_W_LITE,
        ],
    ),
    HoymilesSensorEntityDescription(
        key="dtu_daily_energy",
        translation_key="ac_daily_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        reset_at_midnight=True,
        force_keep_maximum_within_day=True,
        is_dtu_sensor=True,
        supported_dtu_types=[
            DTUType.DTU_G100,
            DTUType.DTU_W100,
            DTUType.DTU_LITE_S,
            DTUType.DTU_LITE,
            DTUType.DTU_PRO,
            DTUType.DTU_PRO_S,
            DTUType.DTUBI,
            DTUType.DTU_W_LITE,
        ],
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[<inverter_count>].active_power",
        translation_key="ac_active_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[<inverter_count>].reactive_power",
        translation_key="ac_reactive_power",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[<inverter_count>].voltage",
        translation_key="grid_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[<inverter_count>].current",
        translation_key="ac_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[<inverter_count>].frequency",
        translation_key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[<inverter_count>].power_factor",
        translation_key="inverter_power_factor",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[<inverter_count>].temperature",
        translation_key="inverter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[<inverter_count>].warning_number",
        translation_key="inverter_warning_number",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].active_power",
        translation_key="ac_active_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].reactive_power",
        translation_key="ac_reactive_power",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].voltage_phase_A",
        translation_key="voltage_phase_A",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].voltage_phase_B",
        translation_key="voltage_phase_B",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].voltage_phase_C",
        translation_key="voltage_phase_C",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].voltage_line_AB",
        translation_key="voltage_line_AB",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].voltage_line_BC",
        translation_key="voltage_line_BC",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].voltage_line_CA",
        translation_key="voltage_line_CA",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].frequency",
        translation_key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].current_phase_A",
        translation_key="current_phase_A",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].current_phase_B",
        translation_key="current_phase_B",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].current_phase_C",
        translation_key="current_phase_C",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].power_factor",
        translation_key="inverter_power_factor",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].temperature",
        translation_key="inverter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].warning_number",
        translation_key="inverter_warning_number",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[<pv_count>].voltage",
        translation_key="port_dc_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[<pv_count>].current",
        translation_key="port_dc_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[<pv_count>].power",
        translation_key="port_dc_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[<pv_count>].energy_total",
        translation_key="port_dc_total_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[<pv_count>].energy_daily",
        translation_key="port_dc_daily_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        reset_at_midnight=True,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[<pv_count>].error_code",
        translation_key="port_error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].phase_total_power",
        translation_key="phase_total_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=10,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].phase_A_power",
        translation_key="phase_A_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=10,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].phase_B_power",
        translation_key="phase_B_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=10,
        requires_device_type=DeviceType.THREE_PHASE_METER,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].phase_C_power",
        translation_key="phase_C_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=10,
        requires_device_type=DeviceType.THREE_PHASE_METER,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].power_factor_total",
        translation_key="power_factor_total",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].energy_total_power",
        translation_key="energy_total_power",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=10.0,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].energy_phase_A",
        translation_key="energy_phase_A",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=10.0,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].energy_phase_B",
        translation_key="energy_phase_B",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        requires_device_type=DeviceType.THREE_PHASE_METER,
        conversion_factor=10.0,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].energy_phase_C",
        translation_key="energy_phase_C",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        requires_device_type=DeviceType.THREE_PHASE_METER,
        conversion_factor=10.0,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].energy_total_consumed",
        translation_key="energy_total_consumed",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=10.0,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].energy_phase_A_consumed",
        translation_key="energy_phase_A_consumed",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=10.0,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].energy_phase_B_consumed",
        translation_key="energy_phase_B_consumed",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        requires_device_type=DeviceType.THREE_PHASE_METER,
        conversion_factor=10.0,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].energy_phase_C_consumed",
        translation_key="energy_phase_C_consumed",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        requires_device_type=DeviceType.THREE_PHASE_METER,
        conversion_factor=10.0,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].voltage_phase_A",
        translation_key="voltage_phase_A",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].voltage_phase_B",
        translation_key="voltage_phase_B",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        requires_device_type=DeviceType.THREE_PHASE_METER,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].voltage_phase_C",
        translation_key="voltage_phase_C",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        requires_device_type=DeviceType.THREE_PHASE_METER,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].current_phase_A",
        translation_key="current_phase_A",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].current_phase_B",
        translation_key="current_phase_B",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        requires_device_type=DeviceType.THREE_PHASE_METER,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].current_phase_C",
        translation_key="current_phase_C",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        requires_device_type=DeviceType.THREE_PHASE_METER,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].power_factor_phase_A",
        translation_key="power_factor_phase_A",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].power_factor_phase_B",
        translation_key="power_factor_phase_B",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        requires_device_type=DeviceType.THREE_PHASE_METER,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].power_factor_phase_C",
        translation_key="power_factor_phase_C",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        requires_device_type=DeviceType.THREE_PHASE_METER,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]

CONFIG_DIAGNOSTIC_SENSORS = [
    HoymilesDiagnosticEntityDescription(
        key="wifi_ssid",
        translation_key="wifi_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:wifi",
        is_dtu_sensor=True,
    ),
    HoymilesDiagnosticEntityDescription(
        key="meter_kind",
        translation_key="meter_kind",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_dtu_sensor=True,
    ),
    HoymilesDiagnosticEntityDescription(
        key="wifi_mac_[0-5]",
        translation_key="mac_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        separator=":",
        conversion=ConversionAction.HEX,
        is_dtu_sensor=True,
    ),
    HoymilesDiagnosticEntityDescription(
        key="wifi_ip_addr_[0-3]",
        translation_key="ip_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        separator=".",
        is_dtu_sensor=True,
    ),
    HoymilesDiagnosticEntityDescription(
        key="dtu_ap_ssid",
        translation_key="dtu_ap_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:access-point",
        is_dtu_sensor=True,
    ),
]

APP_INFO_SENSORS: tuple[HoymilesSensorEntityDescription, ...] = (
    HoymilesSensorEntityDescription(
        key="dtu_info.dtu_sw_version",
        translation_key="dtu_sw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        version_translation_function=FCTN_GENERATE_DTU_VERSION_STRING,
        version_prefix="V",
        is_dtu_sensor=True,
        assume_state=True,
    ),
    HoymilesSensorEntityDescription(
        key="dtu_info.dtu_hw_version",
        translation_key="dtu_hw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        version_translation_function=FCTN_GENERATE_DTU_VERSION_STRING,
        version_prefix="H",
        is_dtu_sensor=True,
        assume_state=True,
    ),
    HoymilesSensorEntityDescription(
        key="pv_info[<inverter_count>].pv_sw_version",
        translation_key="pv_sw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        version_translation_function=FCTN_GENERATE_INVERTER_SW_VERSION_STRING,
        version_prefix="V",
        assume_state=True,
    ),
    HoymilesSensorEntityDescription(
        key="pv_info[<inverter_count>].pv_hw_version",
        translation_key="pv_hw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        version_translation_function=FCTN_GENERATE_INVERTER_HW_VERSION_STRING,
        version_prefix="H",
        assume_state=True,
    ),
    HoymilesSensorEntityDescription(
        key="dtu_info.signal_strength",
        translation_key="signal_strength",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:wifi",
        is_dtu_sensor=True,
    ),
)

HOYMILES_ENERGY_STORAGE_SENSORS = [
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].ems_mode",
        translation_key="ems_working_mode",
        device_class=SensorDeviceClass.ENUM,
        options=[mode.value for mode in EmsWorkingMode],
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.state_of_charge",
        translation_key="state_of_charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        is_bms_device=True,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].power_flow.pv_to_load",
        translation_key="pv_to_load",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].power_flow.pv_to_battery",
        translation_key="pv_to_battery",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].power_flow.pv_to_grid",
        translation_key="pv_to_grid",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].power_flow.battery_to_load",
        translation_key="battery_to_load",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].power_flow.grid_to_load",
        translation_key="grid_to_load",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].power_flow.battery_to_grid",
        translation_key="battery_to_grid",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].production.energy_to_load",
        translation_key="energy_to_load",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
        suggested_display_precision=1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].production.energy_to_battery",
        translation_key="energy_to_battery",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
        suggested_display_precision=1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].production.energy_to_grid",
        translation_key="energy_to_grid",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
        suggested_display_precision=1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].consumption.energy_from_pv",
        translation_key="energy_from_pv",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
        suggested_display_precision=1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].consumption.energy_from_battery",
        translation_key="energy_from_battery",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
        suggested_display_precision=1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].consumption.energy_from_grid",
        translation_key="energy_from_grid",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
        suggested_display_precision=1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_panels[<pv_panel_count>].voltage",
        translation_key="pv_panel_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_panels[<pv_panel_count>].current",
        translation_key="pv_panel_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_panels[<pv_panel_count>].power",
        translation_key="pv_panel_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_panels[<pv_panel_count>].energy",
        translation_key="pv_panel_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
        suggested_display_precision=1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.state_of_health",
        translation_key="state_of_health",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.voltage",
        translation_key="battery_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        suggested_display_precision=1,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.internal_charge_mode",
        translation_key="battery_charge_current_limit",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.internal_discharge_mode",
        translation_key="battery_discharge_current_limit",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.cell_voltage_high",
        translation_key="battery_charge_voltage_limit",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        suggested_display_precision=1,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=True,  # Remains visible by default
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.cell_voltage_low",
        translation_key="battery_discharge_voltage_limit",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        suggested_display_precision=1,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=True,  # Remains visible by default
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.temp_high_charge",
        translation_key="battery_cell_temp_max",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.temp_low_charge",
        translation_key="battery_cell_temp_min",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.temp_high_module",
        translation_key="temp_high_module",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.temp_low_module",
        translation_key="temp_low_module",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.energy_charged",
        translation_key="energy_charged",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
        suggested_display_precision=1,
        is_bms_device=True,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.energy_discharged",
        translation_key="energy_discharged",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
        suggested_display_precision=1,
        is_bms_device=True,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.voltage_charge_high",
        translation_key="battery_cell_voltage_max",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.001,
        suggested_display_precision=3,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.voltage_charge_low",
        translation_key="battery_cell_voltage_min",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.001,
        suggested_display_precision=3,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.voltage_module_high",
        translation_key="voltage_module_high",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.001,
        suggested_display_precision=3,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.voltage_module_low",
        translation_key="voltage_module_low",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.001,
        suggested_display_precision=3,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.param.frequency",
        translation_key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.phases[<phase_count>].voltage",
        translation_key="grid_voltage_phase",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.phases[<phase_count>].current",
        translation_key="grid_current_phase",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.phases[<phase_count>].active_power",
        translation_key="grid_active_power_phase",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.phases[<phase_count>].reactive_power",
        translation_key="grid_reactive_power_phase",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.phases[<phase_count>].power_factor",
        translation_key="grid_power_factor_phase",
        native_unit_of_measurement=PERCENTAGE,
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.phases[<phase_count>].energy_frequency",
        translation_key="grid_energy_exported_phase",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
        suggested_display_precision=1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.phases[<phase_count>].energy_consumed",
        translation_key="grid_energy_consumed_phase",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
        suggested_display_precision=1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].load.param.status",
        translation_key="load_status",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].load.param.frequency",
        translation_key="load_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].load.phases[<phase_count>].voltage",
        translation_key="load_voltage_phase",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].load.phases[<phase_count>].active_power",
        translation_key="load_active_power_phase",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].load.phases[<phase_count>].energy_consumed",
        translation_key="load_energy_consumed_phase",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
        suggested_display_precision=1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.status",
        translation_key="inverter_status",
        device_class=SensorDeviceClass.ENUM,
        options=[status.value for status in InverterStatus],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.frequency",
        translation_key="inverter_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.isolation_resistance",
        translation_key="inverter_isolation_resistance",
        native_unit_of_measurement="kΩ",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.leakage_current",
        translation_key="inverter_leakage_current",
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.drm_signal",
        translation_key="inverter_drm_signal",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].voltage",
        translation_key="inverter_voltage_phase",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].current",
        translation_key="inverter_current_phase",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].active_power",
        translation_key="inverter_active_power_phase",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].reactive_power",
        translation_key="inverter_reactive_power_phase",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].dc_current",
        translation_key="inverter_ac_dc_injection_current_phase",
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].dc_voltage",
        translation_key="inverter_ac_dc_injection_voltage_phase",
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].eps_voltage",
        translation_key="inverter_eps_voltage_phase",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].eps_current",
        translation_key="inverter_eps_current_phase",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].eps_power",
        translation_key="inverter_eps_power_phase",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_inverter.param.status",
        translation_key="pv_inverter_status",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_inverter.param.frequency",
        translation_key="pv_inverter_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_inverter.phases[<phase_count>].voltage",
        translation_key="pv_inverter_voltage_phase",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_inverter.phases[<phase_count>].current",
        translation_key="pv_inverter_current_phase",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_inverter.phases[<phase_count>].active_power",
        translation_key="pv_inverter_active_power_phase",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_inverter.phases[<phase_count>].reactive_power",
        translation_key="pv_inverter_reactive_power_phase",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_inverter.phases[<phase_count>].energy",
        translation_key="pv_inverter_energy_phase",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
        suggested_display_precision=1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.fan_speed_1",
        translation_key="inverter_fan_speed",
        native_unit_of_measurement="RPM",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.fan_speed_2",
        translation_key="inverter_fan_speed_2",
        native_unit_of_measurement="RPM",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.temp_inverter",
        translation_key="inverter_temperature_inside",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.temp_pv",
        translation_key="inverter_temperature_heatsink",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.temp_internal",
        translation_key="inverter_temperature_transformer",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # BRANCH: BATTERY_MANAGEMENT
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.type",
        translation_key="battery_type",
        device_class=None,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.status",
        translation_key="battery_status",
        device_class=SensorDeviceClass.ENUM,
        options=[status.value for status in BatteryStatus],
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.fault_code",
        translation_key="battery_fault_code",
        device_class=None,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.current",
        translation_key="battery_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.power",
        translation_key="battery_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=1.0,
        is_bms_device=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # BRANCH: GRID
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.param.status",
        translation_key="grid_status",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.param.power_factor_deviation",
        translation_key="grid_power_factor_deviation",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.phases[<phase_count>].line_status",
        translation_key="grid_line_status",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    # BRANCH: INVERTER
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.role",
        translation_key="inverter_role",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.main_frequency",
        translation_key="inverter_main_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.secondary_frequency",
        translation_key="inverter_secondary_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.anti_islanding_fault",
        translation_key="inverter_anti_islanding_fault",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.dc_bus_voltage",
        translation_key="inverter_dc_bus_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.dc_bus_voltage_p",
        translation_key="inverter_dc_bus_voltage_p",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.dc_bus_voltage_n",
        translation_key="inverter_dc_bus_voltage_n",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.battery_voltage",
        translation_key="inverter_battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.battery_current",
        translation_key="inverter_battery_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.battery_power",
        translation_key="inverter_battery_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=1.0,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.fan_speed_3",
        translation_key="inverter_fan_speed_3",
        native_unit_of_measurement="RPM",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.arc_fault_ok",
        translation_key="inverter_arc_fault_status",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.coa_status",
        translation_key="inverter_coa_status",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.ips_enable",
        translation_key="inverter_ips_enable",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.temp_battery",
        translation_key="inverter_battery_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.ex_fan_speed_1",
        translation_key="inverter_ex_fan_speed_1",
        native_unit_of_measurement="RPM",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.ex_fan_speed_2",
        translation_key="inverter_ex_fan_speed_2",
        native_unit_of_measurement="RPM",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.ex_fan_speed_3",
        translation_key="inverter_ex_fan_speed_3",
        native_unit_of_measurement="RPM",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].line_status",
        translation_key="inverter_line_status",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    # BRANCH: EXTERNAL METERS
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].external_meters[<meter_count>].fault_code",
        translation_key="external_meter_fault_code",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_external_meter_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].external_meters[<meter_count>].temp_environment",
        translation_key="external_meter_env_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_external_meter_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].external_meters[<meter_count>].temp_copper",
        translation_key="external_meter_copper_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_external_meter_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].external_meters[<meter_count>].relay_status",
        translation_key="external_meter_relay_status",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_external_meter_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].external_meters[<meter_count>].status",
        translation_key="external_meter_status",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_external_meter_device=True,    ),
    # BRANCH: GENERATOR
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].generator.param.status",
        translation_key="generator_status",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_generator_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].generator.param.frequency",
        translation_key="generator_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_generator_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].generator.phases[<phase_count>].voltage",
        translation_key="generator_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_generator_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].generator.phases[<phase_count>].current",
        translation_key="generator_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_generator_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].generator.phases[<phase_count>].active_power",
        translation_key="generator_active_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=1.0,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_generator_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].generator.phases[<phase_count>].energy",
        translation_key="generator_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.001,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_generator_device=True,    ),
    # BRANCH: SMART_LOADS
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].smart_loads[<load_count>].total_power",
        translation_key="smart_load_total_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=1.0,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_smart_load_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].smart_loads[<load_count>].phases[<phase_count>].voltage",
        translation_key="smart_load_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_smart_load_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].smart_loads[<load_count>].phases[<phase_count>].current",
        translation_key="smart_load_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_smart_load_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].smart_loads[<load_count>].phases[<phase_count>].active_power",
        translation_key="smart_load_active_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=1.0,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_smart_load_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].smart_loads[<load_count>].phases[<phase_count>].energy_consumed",
        translation_key="smart_load_energy_consumed",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.001,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_smart_load_device=True,    ),
    # BRANCH: BATTERY_PACKS (BMS Modules)
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].serial_number",
        translation_key="battery_pack_serial",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].status",
        translation_key="battery_pack_status",
        device_class=SensorDeviceClass.ENUM,
        options=[status.value for status in BatteryStatus],
        entity_category=EntityCategory.DIAGNOSTIC,
        is_battery_pack_device=True,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].health_status",
        translation_key="battery_pack_health",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].dcdc_fault_code",
        translation_key="battery_pack_dcdc_fault",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].output_voltage",
        translation_key="battery_pack_out_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].current_limit_1",
        translation_key="battery_pack_curr_limit_chg",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].current_limit_2",
        translation_key="battery_pack_curr_limit_dchg",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].high_voltage",
        translation_key="battery_pack_high_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].low_voltage",
        translation_key="battery_pack_low_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].temp_environment",
        translation_key="battery_pack_env_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].temp_radiator",
        translation_key="battery_pack_rad_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].temp_fet_p",
        translation_key="battery_pack_fet_p_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].temp_fet_n",
        translation_key="battery_pack_fet_n_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].bms_fault_code",
        translation_key="battery_pack_bms_fault",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].state_of_charge",
        translation_key="battery_pack_soc",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].state_of_health",
        translation_key="battery_pack_soh",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].voltage",
        translation_key="battery_pack_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].current",
        translation_key="battery_pack_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].power",
        translation_key="battery_pack_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=1.0,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].cell_voltage_high",
        translation_key="battery_pack_cell_v_high",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.001,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].cell_voltage_low",
        translation_key="battery_pack_cell_v_low",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.001,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].temp_high_charge",
        translation_key="battery_pack_temp_h_chg",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].temp_low_charge",
        translation_key="battery_pack_temp_l_chg",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].voltage_charge_high",
        translation_key="battery_pack_v_chg_high",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].voltage_charge_low",
        translation_key="battery_pack_v_chg_low",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].energy_discharged",
        translation_key="battery_pack_energy_dchg",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_packs[<pack_count>].energy_charged",
        translation_key="battery_pack_energy_chg",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,

        is_battery_pack_device=True,    ),
    # BRANCH: INTEGRATED_POWER_SYSTEM
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].integrated_power_system.ovp1_vt",
        translation_key="ips_overvoltage_protection",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].integrated_power_system.uvp1_vt",
        translation_key="ips_undervoltage_protection",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].integrated_power_system.ofp1_ft",
        translation_key="ips_overfrequency_protection",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].integrated_power_system.ufp1_ft",
        translation_key="ips_underfrequency_protection",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].integrated_power_system.error_code",
        translation_key="ips_error_code",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor platform."""

    hass_data = hass.data[DOMAIN][config_entry.entry_id]
    data_coordinator = hass_data.get(HASS_DATA_COORDINATOR, None)
    config_coordinator = hass_data.get(HASS_CONFIG_COORDINATOR, None)
    app_info_coordinator = hass_data.get(HASS_APP_INFO_COORDINATOR, None)
    energy_storage_data_coordinator = hass_data.get(
        HASS_ENERGY_STORAGE_DATA_COORDINATOR, None
    )
    dtu_serial_number = config_entry.data[CONF_DTU_SERIAL_NUMBER]
    single_phase_inverters = config_entry.data.get(CONF_INVERTERS, [])
    three_phase_inverters = config_entry.data.get(CONF_THREE_PHASE_INVERTERS, [])
    hybrid_inverters = config_entry.data.get(CONF_HYBRID_INVERTERS, [])
    meters = config_entry.data.get(CONF_METERS, [])
    inverters = single_phase_inverters + three_phase_inverters
    ports = config_entry.data[CONF_PORTS]
    sensors = []

    # Real Data Sensors

    if inverters:
        for description in HOYMILES_SENSORS:
            device_class = description.device_class
            if device_class == SensorDeviceClass.ENERGY:
                class_name = HoymilesEnergySensorEntity
            else:
                class_name = HoymilesDataSensorEntity

            if "sgs_data" in description.key and single_phase_inverters:
                sensor_entities = get_sensors_for_description(
                    config_entry,
                    description,
                    data_coordinator,
                    class_name,
                    dtu_serial_number,
                    single_phase_inverters,
                    [],
                )
                sensors.extend(sensor_entities)

            elif "tgs_data" in description.key and three_phase_inverters:
                sensor_entities = get_sensors_for_description(
                    config_entry,
                    description,
                    data_coordinator,
                    class_name,
                    dtu_serial_number,
                    three_phase_inverters,
                    [],
                )
                sensors.extend(sensor_entities)
            elif "meter" in description.key and meters:
                sensor_entities = get_sensors_for_description(
                    config_entry,
                    description,
                    data_coordinator,
                    class_name,
                    dtu_serial_number,
                    [],
                    [],
                    meters,
                )
                sensors.extend(sensor_entities)

            else:
                sensor_entities = get_sensors_for_description(
                    config_entry,
                    description,
                    data_coordinator,
                    class_name,
                    dtu_serial_number,
                    [],
                    ports,
                )
                sensors.extend(sensor_entities)

        for description in CONFIG_DIAGNOSTIC_SENSORS:
            sensor_entities = get_sensors_for_description(
                config_entry,
                description,
                config_coordinator,
                HoymilesDiagnosticSensorEntity,
                dtu_serial_number,
                inverters,
                ports,
            )
            sensors.extend(sensor_entities)

        for description in APP_INFO_SENSORS:
            sensor_entities = get_sensors_for_description(
                config_entry,
                description,
                app_info_coordinator,
                HoymilesDataSensorEntity,
                dtu_serial_number,
                inverters,
                ports,
            )
            sensors.extend(sensor_entities)

    if hybrid_inverters:
        for description in HOYMILES_ENERGY_STORAGE_SENSORS:
            entity_class = HoymilesEnergyStorageSensorEntity
            sensor_entities = get_sensors_for_hybrid_inverter_description(
                config_entry,
                description,
                energy_storage_data_coordinator,
                entity_class,
                dtu_serial_number,
                hybrid_inverters,
            )
            sensors.extend(sensor_entities)

    async_add_entities(sensors)


def get_sensors_for_description(
    config_entry: ConfigEntry,
    description: SensorEntityDescription,
    coordinator: HoymilesCoordinatorEntity,
    class_name: SensorEntity,
    dtu_serial_number: str,
    inverters: list,
    ports: list,
    meters: list = [],
) -> list[SensorEntity]:
    """Get sensors for the given description."""

    sensors = []

    if "<inverter_count>" in description.key:
        for index, inverter_serial in enumerate(inverters):
            new_key = description.key.replace("<inverter_count>", str(index))
            updated_description = dataclasses.replace(
                description, key=new_key, serial_number=inverter_serial
            )
            sensor = class_name(config_entry, updated_description, coordinator)
            sensors.append(sensor)
    elif "<pv_count>" in description.key:
        for index, port in enumerate(ports):
            inverter_serial = port["inverter_serial_number"]
            port_number = port["port_number"]
            new_key = str(description.key).replace("<pv_count>", str(index))
            updated_description = dataclasses.replace(
                description,
                key=new_key,
                serial_number=inverter_serial,
                port_number=port_number,
            )
            sensor = class_name(config_entry, updated_description, coordinator)
            sensors.append(sensor)
    elif "meter_count" in description.key:
        for index, meter in enumerate(meters):
            meter_serial = meter["meter_serial_number"]
            meter_type = meter["device_type"]

            if description.requires_device_type.value in (
                DeviceType.ALL_DEVICES.value,
                meter_type,
            ):
                new_key = description.key.replace("<meter_count>", str(index))
                updated_description = dataclasses.replace(
                    description, key=new_key, serial_number=meter_serial
                )
                sensor = class_name(config_entry, updated_description, coordinator)
                sensors.append(sensor)
    else:
        if description.supported_dtu_types is not None:
            serial_bytes = bytes.fromhex(dtu_serial_number)

            dtu_type = None
            try:
                dtu_type = get_dtu_model_type(serial_bytes)
            except ValueError as e:
                _LOGGER.error(f"Error getting DTU model type: {e}")

        if (
            description.supported_dtu_types is None
            or dtu_type in description.supported_dtu_types
        ):
            updated_description = dataclasses.replace(
                description, serial_number=dtu_serial_number
            )
            sensor = class_name(config_entry, updated_description, coordinator)
            sensors.append(sensor)

    return sensors


def get_sensors_for_hybrid_inverter_description(
    config_entry: ConfigEntry,
    description: SensorEntityDescription,
    coordinator: HoymilesCoordinatorEntity,
    class_name: SensorEntity,
    dtu_serial_number: str,
    inverters: list,
) -> list[SensorEntity]:
    """Get sensors for the given description."""

    sensors = []

    if "<inverter_count>" in description.key:
        for index, inverter in enumerate(inverters):
            # Master/Slave Node Isolation:
            # - Master (index == 0) gets all sensors.
            # - Slaves (index > 0) only get sensors in the pv_panels (pvs), battery_management (bms) and inverter (inv) trees.
            # Grid, load, and power flow are DTU-level or shared infrastructure, so we skip them for slaves.
            if index > 0:
                is_allowed_slave_sensor = False
                for allowed_sub in (".pv_panels", ".battery_management", ".inverter.", ".ems_mode"):
                    if allowed_sub in description.key:
                        is_allowed_slave_sensor = True
                        break
                if not is_allowed_slave_sensor:
                    continue

            # Pobranie danych telemetrycznych inwertera
            inv_data = None
            if coordinator and coordinator.data:
                inverters_data = None
                if isinstance(coordinator.data, dict) and "inverters" in coordinator.data:
                    inverters_data = coordinator.data["inverters"]
                elif hasattr(coordinator.data, "inverters"):
                    inverters_data = getattr(coordinator.data, "inverters")
                
                if inverters_data:
                    serial = inverter.get("inverter_serial_number")
                    if serial in inverters_data:
                        inv_data = inverters_data[serial]
                    elif str(serial) in inverters_data:
                        inv_data = inverters_data[str(serial)]

            if "generator" in description.key:
                if not inv_data:
                    continue
                generator_data = inv_data.get("generator") if isinstance(inv_data, dict) else getattr(inv_data, "generator", None)
                if not generator_data:
                    continue
                status = generator_data.get("status") if isinstance(generator_data, dict) else getattr(generator_data, "status", None)
                if status == 0 or status is None:
                    continue

            new_key = description.key.replace("<inverter_count>", str(index))

            if "<pv_panel_count>" in description.key:
                # TODO: Dynamically determine number of PV panels
                for pv_index in range(0, 2):
                    new_pv_index_key = new_key.replace(
                        "<pv_panel_count>", str(pv_index)
                    )
                    updated_description = dataclasses.replace(
                        description,
                        key=new_pv_index_key,
                        serial_number=inverter["inverter_serial_number"],
                        model_name=inverter["model_name"],
                        port_number=pv_index + 1,
                    )
                    sensor = class_name(config_entry, updated_description, coordinator)
                    sensors.append(sensor)

            elif "<load_count>" in description.key:
                if not inv_data:
                    continue
                smart_loads = inv_data.get("smart_loads") if isinstance(inv_data, dict) else getattr(inv_data, "smart_loads", [])
                if not smart_loads:
                    continue
                first_load = smart_loads[0]
                is_empty = False
                if hasattr(first_load, "ListFields"):
                    is_empty = not first_load.ListFields()
                elif isinstance(first_load, dict):
                    is_empty = not any(first_load.values())
                if is_empty:
                    continue

                for load_index in range(0, 2):
                    new_load_key = new_key.replace("<load_count>", str(load_index))
                    if "<phase_count>" in description.key:
                        is_three_phase = False
                        if hasattr(coordinator, "three_phase_inverters_set"):
                            is_three_phase = str(inverter["inverter_serial_number"]) in coordinator.three_phase_inverters_set

                        phases_to_create = [0, 1, 2] if is_three_phase else [0]
                        for phase_index in phases_to_create:
                            new_phase_index_key = new_load_key.replace(
                                "<phase_count>", str(phase_index)
                            )
                            phase_label = ["A", "B", "C"][phase_index] if is_three_phase else None
                            updated_description = dataclasses.replace(
                                description,
                                key=new_phase_index_key,
                                serial_number=inverter["inverter_serial_number"],
                                model_name=inverter["model_name"],
                                phase=phase_label,
                            )
                            sensor = class_name(config_entry, updated_description, coordinator)
                            sensors.append(sensor)
                    else:
                        updated_description = dataclasses.replace(
                            description,
                            key=new_load_key,
                            serial_number=inverter["inverter_serial_number"],
                            model_name=inverter["model_name"],
                        )
                        sensor = class_name(config_entry, updated_description, coordinator)
                        sensors.append(sensor)

            elif "<pack_count>" in description.key:
                if not inv_data:
                    continue
                battery_packs = inv_data.get("battery_packs") if isinstance(inv_data, dict) else getattr(inv_data, "battery_packs", [])
                if not battery_packs:
                    continue
                first_pack = battery_packs[0]
                sn = first_pack.get("serial_number") if isinstance(first_pack, dict) else getattr(first_pack, "serial_number", None)
                if sn in (0, "0", "", None):
                    continue

                for pack_index in range(0, 4):
                    new_pack_key = new_key.replace("<pack_count>", str(pack_index))
                    updated_description = dataclasses.replace(
                        description,
                        key=new_pack_key,
                        serial_number=inverter["inverter_serial_number"],
                        model_name=inverter["model_name"],
                    )
                    sensor = class_name(config_entry, updated_description, coordinator)
                    sensors.append(sensor)

            elif "<meter_count>" in description.key:
                if not inv_data:
                    continue
                external_meters = inv_data.get("external_meters") if isinstance(inv_data, dict) else getattr(inv_data, "external_meters", [])
                if not external_meters:
                    continue

                for meter_index in range(0, 2):
                    new_meter_key = new_key.replace("<meter_count>", str(meter_index))
                    updated_description = dataclasses.replace(
                        description,
                        key=new_meter_key,
                        serial_number=inverter["inverter_serial_number"],
                        model_name=inverter["model_name"],
                    )
                    sensor = class_name(config_entry, updated_description, coordinator)
                    sensors.append(sensor)

            elif "<phase_count>" in description.key:
                # Read phase configuration topology directly from coordinator static cache
                is_three_phase = False
                if hasattr(coordinator, "three_phase_inverters_set"):
                    is_three_phase = str(inverter["inverter_serial_number"]) in coordinator.three_phase_inverters_set

                if is_three_phase:
                    phases_to_create = [0, 1, 2]
                else:
                    # Single-phase: create only index 0, but without a phase label
                    phases_to_create = [0]

                for phase_index in phases_to_create:
                    new_phase_index_key = new_key.replace(
                        "<phase_count>", str(phase_index)
                    )
                    # For 3-phase: set phase label ("A"/"B"/"C"). For 1-phase: leave phase=None.
                    phase_label = ["A", "B", "C"][phase_index] if is_three_phase else None
                    updated_description = dataclasses.replace(
                        description,
                        key=new_phase_index_key,
                        serial_number=inverter["inverter_serial_number"],
                        model_name=inverter["model_name"],
                        phase=phase_label,
                    )
                    sensor = class_name(config_entry, updated_description, coordinator)
                    sensors.append(sensor)

            else:
                updated_description = dataclasses.replace(
                    description,
                    key=new_key,
                    serial_number=inverter["inverter_serial_number"],
                    model_name=inverter["model_name"],
                )
                sensor = class_name(config_entry, updated_description, coordinator)
                sensors.append(sensor)

    else:
        updated_description = dataclasses.replace(
            description, serial_number=dtu_serial_number
        )
        sensor = class_name(config_entry, updated_description, coordinator)
        sensors.append(sensor)

    return sensors


class HoymilesDataSensorEntity(HoymilesCoordinatorEntity, RestoreSensor):
    """Represents a sensor entity for Hoymiles data."""

    _attr_has_entity_name = True  # Aktywacja nowoczesnego standardu nazw HA

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: HoymilesSensorEntityDescription,
        coordinator: HoymilesCoordinatorEntity,
    ):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(config_entry, description, coordinator)

        self._attribute_name = description.key
        self._conversion_factor = description.conversion_factor
        self._version_translation_function = description.version_translation_function
        self._version_prefix = description.version_prefix
        self._native_value = None
        self._assumed_state = False
        self._last_known_value = None
        self._last_successful_update = None
        self._last_update_state = None

        self.update_state_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def native_value(self):
        """Return the native value of the sensor."""
        if self._native_value == 0.0:
            if self.entity_description.assume_state:
                return self._last_known_value
            elif (
                self._last_successful_update is not None
                and datetime.now() - self._last_successful_update
                <= timedelta(minutes=3)
            ):
                _LOGGER.debug(
                    "[%s] Returning last known value: %s, instead of 0.0 to cope with inverter in offline mode.",
                    self.name,
                    self._last_known_value,
                )
                self._assumed_state = True
                return self._last_known_value
        else:
            self._last_successful_update = datetime.now()
            self._last_known_value = self._native_value
        self._assumed_state = False
        return self._native_value

    @property
    def assumed_state(self):
        """Return the assumed state of the sensor."""
        return self._assumed_state

    def update_state_value(self):
        """Update the state value of the sensor based on the coordinator data."""
        new_native_value = 0.0

        if self.coordinator is not None and (
            not hasattr(self.coordinator, "data") or self.coordinator.data is None
        ):
            new_native_value = 0.0
        elif "[" in self._attribute_name and "]" in self._attribute_name:
            # Extracting the list index and attribute dynamically
            attribute_name, index = self._attribute_name.split("[")
            index = int(index.split("]")[0])
            nested_attribute = (
                self._attribute_name.split("].")[1]
                if "]." in self._attribute_name
                else None
            )

            attribute = getattr(self.coordinator.data, attribute_name.split("[")[0], [])

            if index < len(attribute):
                if nested_attribute is not None:
                    new_native_value = getattr(attribute[index], nested_attribute, None)
                else:
                    new_native_value = attribute[index]
            else:
                new_native_value = None
        elif "." in self._attribute_name:
            attribute_parts = self._attribute_name.split(".")
            attribute = self.coordinator.data
            for part in attribute_parts:
                attribute = getattr(attribute, part, None)
            new_native_value = attribute

        else:
            new_native_value = getattr(
                self.coordinator.data, self._attribute_name, None
            )

        if new_native_value is not None and self._conversion_factor is not None:
            new_native_value *= self._conversion_factor

        if (
            new_native_value is not None
            and new_native_value != 0.0
            and self._version_translation_function is not None
        ):
            new_native_value = getattr(
                hoymiles_wifi.hoymiles, self._version_translation_function
            )(int(new_native_value))

        if (
            new_native_value is not None
            and new_native_value != 0.0
            and self._version_prefix is not None
        ):
            new_native_value = f"{self._version_prefix}{new_native_value}"

        if (
            self.entity_description.force_keep_maximum_within_day
            and self._last_update_state is not None
            and self._last_update_state.date() == datetime.now().date()
        ):
            new_native_value = max(new_native_value, self._native_value)

        self._last_update_state = datetime.now()
        self._native_value = new_native_value

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()

        state = await self.async_get_last_sensor_data()
        if state:
            self.last_known_value = state.native_value


class HoymilesEnergySensorEntity(HoymilesDataSensorEntity, RestoreSensor):
    """Represents an energy sensor entity for Hoymiles data."""

    _attr_has_entity_name = True

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: HoymilesDiagnosticEntityDescription,
        coordinator: HoymilesCoordinatorEntity,
    ):
        """Initialize the HoymilesEnergySensorEntity."""
        super().__init__(config_entry, description, coordinator)
        # Important to set to None to not mess with long term stats
        self._last_known_value = None

    def schedule_midnight_reset(self, reset_sensor_value: bool = True):
        """Schedule the reset function to run again at the next midnight."""
        now = datetime.now()
        midnight = datetime.combine(now.date(), time(0, 0))
        midnight = midnight + timedelta(days=1) if now > midnight else midnight
        time_until_midnight = (midnight - datetime.now()).total_seconds()

        if reset_sensor_value:
            self.reset_sensor_value()

        self.hass.loop.call_later(time_until_midnight, self.schedule_midnight_reset)

    def reset_sensor_value(self):
        """Reset the sensor value."""
        self._last_known_value = 0

    @property
    def native_value(self):
        """Return the native value of the sensor."""
        super_native_value = super().native_value
        # For an energy sensor a value of 0 would mess up long term stats because of how total_increasing works
        if super_native_value == 0.0:
            _LOGGER.debug(
                "Returning last known value instead of 0.0 for %s to avoid resetting total_increasing counter",
                self.name,
            )
            self._assumed_state = True
            return self._last_known_value
        self._last_known_value = super_native_value
        self._assumed_state = False
        return super_native_value

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()

        state = await self.async_get_last_sensor_data()
        if state:
            self._last_known_value = state.native_value

        if self.entity_description.reset_at_midnight:
            self.schedule_midnight_reset(reset_sensor_value=False)


class HoymilesDiagnosticSensorEntity(
    HoymilesCoordinatorEntity, RestoreSensor, SensorEntity
):
    """Represents a diagnostic sensor entity for Hoymiles data."""

    _attr_has_entity_name = True

    def __init__(self, config_entry, description, coordinator):
        """Initialize the HoymilesSensorEntity."""
        super().__init__(config_entry, description, coordinator)

        self._attribute_name = description.key
        self._conversion = description.conversion
        self._separator = description.separator
        self._native_value = None
        self._assumed_state = False

        self.update_state_value()
        self._last_known_value = self._native_value

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def native_value(self):
        """Return the native value of the sensor."""
        if self._native_value is None:
            self._assumed_state = True
            return self._last_known_value

        self._last_known_value = self._native_value
        self._assumed_state = False
        return self._native_value

    def update_state_value(self):
        """Update the state value of the sensor."""

        if "[" in self._attribute_name and "]" in self._attribute_name:
            attribute_parts = self._attribute_name.split("[")
            attribute_name = attribute_parts[0]
            index_range = attribute_parts[1].split("]")[0]
            start, end = map(int, index_range.split("-"))

            new_attribute_names = [
                f"{attribute_name}{i}" for i in range(start, end + 1)
            ]
            attribute_values = [
                str(getattr(self.coordinator.data, attr, ""))
                for attr in new_attribute_names
            ]

            if "" in attribute_values:
                self._native_value = None
            else:
                self._native_value = self._separator.join(attribute_values)
        else:
            self._native_value = getattr(
                self.coordinator.data, self._attribute_name, None
            )

        if self._native_value is not None and self._conversion == ConversionAction.HEX:
            self._native_value = self._separator.join(
                hex(int(value))[2:]
                for value in self._native_value.split(self._separator)
            ).upper()

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        state = await self.async_get_last_sensor_data()
        if state:
            self._last_known_value = state.native_value


class HoymilesEnergyStorageSensorEntity(HoymilesCoordinatorEntity, RestoreSensor):
    """Represents a sensor entity for Hoymiles data."""

    _attr_has_entity_name = True  # Nowoczesna architektura nazw HA

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: HoymilesEnergyStorageSensorEntityDescription,
        coordinator: HoymilesCoordinatorEntity,
    ):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(config_entry, description, coordinator)

        self._attribute_name = description.key
        self._conversion_factor = description.conversion_factor
        self._version_translation_function = description.version_translation_function
        self._version_prefix = description.version_prefix
        self._native_value = None
        self._assumed_state = False
        self._last_known_value = None
        self._last_successful_update = None
        self._last_update_state = None

        if description.suggested_display_precision is not None:
            self._attr_suggested_display_precision = description.suggested_display_precision

        self.update_state_value()


    @property
    def translation_placeholders(self) -> dict[str, str] | None:
        """Injects dynamic values directly into the HA translation engine."""
        placeholders = {}
        if hasattr(self.entity_description, "phase") and self.entity_description.phase:
            placeholders["phase"] = f" {self.entity_description.phase}"
        else:
            placeholders["phase"] = ""
            
        if hasattr(self.entity_description, "port_number") and self.entity_description.port_number:
            placeholders["port_number"] = str(self.entity_description.port_number)
            
        return placeholders

    @property
    def device_info(self) -> DeviceInfo:
        """Dynamically builds complete and rich device metadata directly at the entity level."""
        serial = getattr(self.entity_description, "serial_number", "unknown")
        dtu_serial = getattr(self.coordinator, "dtu_serial_number", "unknown")
        
        config_entry = getattr(self.coordinator, "config_entry", None)
        
        path = self._attribute_name
        inv_idx = 0
        if path.startswith("[") and "]" in path:
            try:
                inv_idx = int(path.split("[")[1].split("]")[0])
            except (ValueError, IndexError):
                pass
        
        role_suffix = "M" if inv_idx == 0 else f"S{inv_idx}"
        
        inverter_info = {}
        if config_entry and inv_idx < len(config_entry.data.get("hybrid_inverters", [])):
            inverter_info = config_entry.data["hybrid_inverters"][inv_idx]
        
        is_three_phase = str(serial) in getattr(self.coordinator, "three_phase_inverters_set", set())
        phase_str = "3-phase" if is_three_phase else "1-phase"
        
        sw_m_ver = inverter_info.get("sw_m_ver", "Unknown")
        sw_s_ver = inverter_info.get("sw_s_ver", "Unknown")
        sw_sys_ver = inverter_info.get("sw_sys_ver", "Unknown")
        pv_num = inverter_info.get("pv_num", 0)
        bms_cap = inverter_info.get("bms_cap", 0)
        bms_cap_val = f"{bms_cap * 0.1:.1f} kWh" if bms_cap else "None"
        
        sw_version_str = f"Power: {sw_m_ver} | Safety: {sw_s_ver} | System: {sw_sys_ver}"
        hw_version_str = f"{phase_str} | {pv_num} PV strings | Battery capacity: {bms_cap_val}"
        model_name = inverter_info.get("model_name", "HYS Hybrid Inverter")

        if getattr(self.entity_description, "is_bms_device", False):
            return DeviceInfo(
                identifiers={(DOMAIN, f"battery_{serial}")},
                name=f"Battery {role_suffix}",
                manufacturer="Hoymiles",
                model=f"Integrated BMS Storage Pack ({phase_str})",
                via_device=(DOMAIN, f"inverter_{serial}"),
                sw_version=sw_version_str,
                hw_version=hw_version_str,
            )

        if getattr(self.entity_description, "is_battery_pack_device", False):
            pack_idx = "X"
            if ".battery_packs[" in path:
                try:
                    pack_idx = path.split(".battery_packs[")[1].split("]")[0]
                except (ValueError, IndexError):
                    pass
            return DeviceInfo(
                identifiers={(DOMAIN, f"battery_pack_{serial}_{pack_idx}")},
                name=f"Battery Pack {pack_idx} ({role_suffix})",
                manufacturer="Hoymiles",
                model=f"Battery Pack Module",
                via_device=(DOMAIN, f"inverter_{serial}"),
            )

        if getattr(self.entity_description, "is_smart_load_device", False):
            load_idx = "X"
            if ".smart_loads[" in path:
                try:
                    load_idx = path.split(".smart_loads[")[1].split("]")[0]
                except (ValueError, IndexError):
                    pass
            return DeviceInfo(
                identifiers={(DOMAIN, f"smart_load_{serial}_{load_idx}")},
                name=f"Smart Load {load_idx} ({role_suffix})",
                manufacturer="Hoymiles",
                model=f"Smart Load Terminal",
                via_device=(DOMAIN, f"inverter_{serial}"),
            )

        if getattr(self.entity_description, "is_external_meter_device", False):
            meter_idx = "X"
            if ".external_meters[" in path:
                try:
                    meter_idx = path.split(".external_meters[")[1].split("]")[0]
                except (ValueError, IndexError):
                    pass
            return DeviceInfo(
                identifiers={(DOMAIN, f"external_meter_{serial}_{meter_idx}")},
                name=f"External Meter {meter_idx} ({role_suffix})",
                manufacturer="Hoymiles",
                model=f"External Energy Meter",
                via_device=(DOMAIN, f"inverter_{serial}"),
            )

        if getattr(self.entity_description, "is_generator_device", False):
            return DeviceInfo(
                identifiers={(DOMAIN, f"generator_{serial}")},
                name=f"Generator ({role_suffix})",
                manufacturer="Hoymiles",
                model=f"Generator Terminal",
                via_device=(DOMAIN, f"inverter_{serial}"),
            )

        return DeviceInfo(
            identifiers={(DOMAIN, f"inverter_{serial}")},
            name=f"Inverter {role_suffix}",
            manufacturer="Hoymiles",
            model=model_name,
            sw_version=sw_version_str,
            hw_version=hw_version_str,
            via_device=(DOMAIN, dtu_serial) if not getattr(self.entity_description, "is_dtu_sensor", False) else None,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def native_value(self):
        """Return the native value of the sensor."""
        if self._native_value is not None:
            self._last_successful_update = datetime.now()
            self._last_known_value = self._native_value
            self._assumed_state = False
            return self._native_value

        if self.entity_description.assume_state:
            return self._last_known_value
        elif (
            self._last_successful_update is not None
            and datetime.now() - self._last_successful_update
            <= timedelta(minutes=3)
        ):
            _LOGGER.debug(
                "[%s] Returning last known value: %s, instead of None to cope with inverter in offline mode.",
                self.name,
                self._last_known_value,
            )
            self._assumed_state = True
            return self._last_known_value

        self._assumed_state = False
        return None

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        path = self._attribute_name
        if path.startswith("[") and "]" in path:
            try:
                inv_idx = int(path.split("[")[1].split("]")[0])
                role_infix = "m" if inv_idx == 0 else f"s{inv_idx}"
                path = path.replace(f"[{inv_idx}]", role_infix)
            except Exception:
                pass
        return {"source": path}

    @property
    def assumed_state(self):
        """Return the assumed state of the sensor."""
        return self._assumed_state

    def update_state_value(self):
        """Update the state value of the sensor based on the coordinator data."""
        new_native_value = 0.0

        if (
            self.coordinator is None
            or not hasattr(self.coordinator, "data")
            or self.coordinator.data is None
        ):
            self._native_value = 0.0
            return

        def resolve_path(obj, path):
            tokens = re.findall(r"\w+|\[\d+\]", path)
            for token in tokens:
                if obj is None:
                    return None
                if token.startswith("["):
                    index = int(token[1:-1])
                    try:
                        obj = obj[index]
                    except (IndexError, TypeError):
                        logging.debug(
                            "Index %d out of range for object: %s (normal when loading/offline)", index, obj
                        )
                        return None
                else:
                    obj = getattr(obj, token, None)
            return obj

        new_native_value = resolve_path(self.coordinator.data, self._attribute_name)

        if new_native_value in (32767, 65535):
            self._native_value = None
            return

        if new_native_value is not None and self.entity_description.device_class == SensorDeviceClass.ENUM:
            try:
                val_int = int(new_native_value)
                if self.entity_description.translation_key == "battery_status" or self.entity_description.translation_key == "battery_pack_status":
                    new_native_value = BATTERY_STATUS_MAP.get(val_int, BatteryStatus.UNKNOWN).value
                elif self.entity_description.translation_key == "inverter_status":
                    new_native_value = INVERTER_STATUS_MAP.get(val_int, InverterStatus.UNKNOWN).value
                elif self.entity_description.translation_key == "ems_working_mode":
                    new_native_value = EMS_WORKING_MODE_MAP.get(val_int, EmsWorkingMode.UNKNOWN).value
            except (ValueError, TypeError):
                pass

        if new_native_value is not None and self._conversion_factor is not None:
            new_native_value *= self._conversion_factor

        if (
            new_native_value is not None
            and new_native_value != 0.0
            and self._version_translation_function is not None
        ):
            new_native_value = getattr(
                hoymiles_wifi.hoymiles, self._version_translation_function
            )(int(new_native_value))

        if (
            new_native_value is not None
            and new_native_value != 0.0
            and self._version_prefix is not None
        ):
            new_native_value = f"{self._version_prefix}{new_native_value}"

        if (
            self.entity_description.force_keep_maximum_within_day
            and self._last_update_state is not None
            and self._last_update_state.date() == datetime.now().date()
        ):
            new_native_value = max(new_native_value, self._native_value)

        self._last_update_state = datetime.now()
        self._native_value = new_native_value

        async def async_added_to_hass(self) -> None:
            """Call when entity about to be added to hass."""
            await super().async_added_to_hass()

            state = await self.async_get_last_sensor_data()
            if state:
                self.last_known_value = state.native_value


# Mapping of numeric EMS/BMS working mode values to human-readable labels

