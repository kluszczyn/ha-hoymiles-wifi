"""Constants for the Hoymiles integration."""

DOMAIN = "hoymiles_wifi"
NAME = "Hoymiles"
DOMAIN = "hoymiles_wifi"
DOMAIN_DATA = f"{DOMAIN}_data"
CONFIG_VERSION = 5

ISSUE_URL = "https://github.com/suaveolent/ha-hoymiles-wifi/issues"

CONF_UPDATE_INTERVAL = "update_interval"
CONF_DTU_SERIAL_NUMBER = "dtu_serial_number"
CONF_INVERTERS = "inverters"
CONF_THREE_PHASE_INVERTERS = "three_phase_inverters"
CONF_HYBRID_INVERTERS = "hybrid_inverters"
CONF_PORTS = "ports"
CONF_METERS = "meters"
CONF_IS_ENCRYPTED = "is_encrypted"
CONF_ENC_RAND = "enc_rand"
CONF_TIMEOUT = "timeout"

DEFAULT_UPDATE_INTERVAL_SECONDS = 35
MIN_UPDATE_INTERVAL_SECONDS = 1
DEFAULT_TIMEOUT_SECONDS = 10
MIN_TIMEOUT_SECONDS = 1

DEFAULT_CONFIG_UPDATE_INTERVAL_SECONDS = 60 * 5
DEFAULT_APP_INFO_UPDATE_INTERVAL_SECONDS = 60 * 60 * 2


HASS_DATA_COORDINATOR = "data_coordinator"
HASS_CONFIG_COORDINATOR = "config_coordinator"
HASS_APP_INFO_COORDINATOR = "app_info_coordinator"
HASS_ENERGY_STORAGE_DATA_COORDINATOR = "energy_stroage_data_coordinator"
HASS_DTU = "dtu"
HASS_DATA_UNSUB_OPTIONS_UPDATE_LISTENER = "unsub_options_update_listener"


FCTN_GENERATE_DTU_VERSION_STRING = "generate_dtu_version_string"
FCTN_GENERATE_INVERTER_HW_VERSION_STRING = "generate_version_string"
FCTN_GENERATE_INVERTER_SW_VERSION_STRING = "generate_sw_version_string"

STARTUP_MESSAGE = f"""

-------------------------------------------------------------------
{NAME}
This is a custom integration!
If you have any issues with it please open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""

from enum import StrEnum

class BatteryStatus(StrEnum):
    """Battery status states."""
    STANDBY = "standby"
    CHARGING = "charging"
    DISCHARGING = "discharging"
    SLEEP = "sleep"
    FLOAT_CHARGING = "float_charging"
    EQUALIZATION_CHARGING = "equalization_charging"
    UNKNOWN = "unknown"

class InverterStatus(StrEnum):
    """Inverter status states."""
    POWER_ON_INIT = "power_on_init"
    STANDBY = "standby"
    GRID_ON_TEST = "grid_on_test"
    GRID_ON = "grid_on"
    FAULT = "fault"
    GRID_OFF = "grid_off"
    BYPASS = "bypass"
    PV_CHARGE_BAT = "pv_charge_bat"
    GEN_MODE = "gen_mode"
    UNKNOWN = "unknown"

class EmsWorkingMode(StrEnum):
    """EMS working mode states."""
    SELF_CONSUMPTION = "self_consumption"
    ECONOMY = "economy"
    BACKUP = "backup"
    OFF_GRID = "off_grid"
    FORCE_CHARGE = "force_charge"
    FORCE_DISCHARGE = "force_discharge"
    PEAK_SHAVING = "peak_shaving"
    TIME_OF_USE = "time_of_use"
    UNKNOWN = "unknown"

BATTERY_STATUS_MAP: dict[int, BatteryStatus] = {
    0: BatteryStatus.STANDBY,
    1: BatteryStatus.CHARGING,
    2: BatteryStatus.DISCHARGING,
    3: BatteryStatus.SLEEP,
    4: BatteryStatus.FLOAT_CHARGING,
    5: BatteryStatus.EQUALIZATION_CHARGING,
}

INVERTER_STATUS_MAP: dict[int, InverterStatus] = {
    0: InverterStatus.POWER_ON_INIT,
    1: InverterStatus.STANDBY,
    2: InverterStatus.GRID_ON_TEST,
    3: InverterStatus.GRID_ON,
    4: InverterStatus.FAULT,
    5: InverterStatus.GRID_OFF,
    6: InverterStatus.BYPASS,
    7: InverterStatus.PV_CHARGE_BAT,
    8: InverterStatus.GEN_MODE,
}

EMS_WORKING_MODE_MAP: dict[int, EmsWorkingMode] = {
    1: EmsWorkingMode.SELF_CONSUMPTION,
    2: EmsWorkingMode.ECONOMY,
    3: EmsWorkingMode.BACKUP,
    4: EmsWorkingMode.OFF_GRID,
    5: EmsWorkingMode.FORCE_CHARGE,
    6: EmsWorkingMode.FORCE_DISCHARGE,
    7: EmsWorkingMode.PEAK_SHAVING,
    8: EmsWorkingMode.TIME_OF_USE,
}

