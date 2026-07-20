"""Coordinator for Hoymiles integration."""

from datetime import timedelta
import logging

import homeassistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from hoymiles_wifi.dtu import DTU
from .util import is_encrypted_dtu, async_check_and_update_enc_rand


from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.BINARY_SENSOR, Platform.BUTTON]


class HoymilesDataUpdateCoordinator(DataUpdateCoordinator):
    """Base data update coordinator for Hoymiles integration."""

    def __init__(
        self,
        hass: homeassistant,
        dtu: DTU,
        config_entry: ConfigEntry,
        update_interval: timedelta,
    ) -> None:
        """Initialize the HoymilesCoordinatorEntity."""
        self._dtu = dtu
        self._hass = hass
        self._config_entry = config_entry

        _LOGGER.debug(
            "Setup entry with update interval %s. IP: %s",
            update_interval,
            config_entry.data.get(CONF_HOST),
        )

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)

    def get_dtu(self) -> DTU:
        """Get the DTU object."""
        return self._dtu


class HoymilesRealDataUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Data coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = await self._dtu.async_get_real_data_new()

        if not response:
            _LOGGER.warning(
                "Unable to retrieve real data new. Inverter might be offline."
            )
            raise UpdateFailed("Unable to retrieve real data new.")
        return response


class HoymilesConfigUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Config coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = await self._dtu.async_get_config()

        if not response:
            _LOGGER.warning("Unable to retrieve config data. Inverter might be offline.")
            raise UpdateFailed("Unable to retrieve config data.")

        return response


class HoymilesAppInfoUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """App Info coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = await self._dtu.async_app_information_data()

        if response and response.dtu_info.dfs:
            if is_encrypted_dtu(response.dtu_info.dfs):
                await async_check_and_update_enc_rand(
                    self._hass,
                    self._config_entry,
                    self._dtu,
                    response.dtu_info.enc_rand.hex(),
                )

        if not response:
            _LOGGER.warning(
                "Unable to retrieve app information data. Inverter might be offline."
            )
            raise UpdateFailed("Unable to retrieve app information data.")
        return response


class HoymilesGatewayInfoUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Gateway Info coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles gateway info coordinator update")

        response = await self._dtu.async_get_gateway_info()

        if not response:
            _LOGGER.warning("Unable to retrieve gateway info. Inverter might be offline.")
            raise UpdateFailed("Unable to retrieve gateway info.")
        return response


class HoymilesGatewayNetworkInfoUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Gateway Network Info coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles network info coordinator update")

        response = await self._dtu.async_get_gateway_network_info(
            dtu_serial_number=int(self._dtu_serial_number)
        )

        if not response:
            _LOGGER.warning(
                "Unable to retrieve network information. Inverter might be offline."
            )
            raise UpdateFailed("Unable to retrieve network information.")
        return response


class HoymilesEnergyStorageUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Energy Storage Update coordinator for Hoymiles integration."""

    def __init__(
        self,
        hass: homeassistant,
        dtu: DTU,
        config_entry: ConfigEntry,
        update_interval: timedelta,
        dtu_serial_number: int,
        inverters: list[int],
    ) -> None:
        self._dtu_serial_number = dtu_serial_number
        self._inverters = inverters
        self.three_phase_inverters_set = set()
        self.ems_configs = {}  # Cache for detailed EMS config dicts
        self._last_mode_codes = {}  # Keep track of last mode codes to detect changes
        super().__init__(hass, dtu, config_entry, update_interval)

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles energy storage coordinator update")

        from hoymiles_wifi.hys import HysClient
        from google.protobuf.json_format import MessageToDict
        hys = HysClient(self._dtu)
        responses = []

        # inverter has keys: inverter_serial_number, model_name, and optionally addr (default to index + 1)
        for idx, inverter in enumerate(self._inverters):
            # In Master-Slave topology:
            # - Master (index 0) has addr=1 -> number=1 (represented as slave_index = 1)
            # - Slave S1 (index 1) has addr=2 -> number=2
            slave_index = idx + 1
            inv_sn = int(inverter["inverter_serial_number"])
            inv_sn_str = str(inv_sn)
            
            _LOGGER.debug(
                "Fetching telemetry for hybrid inverter %s (index: %d, routing number: %d)",
                inv_sn,
                idx,
                slave_index,
            )
            storage_data = await hys.async_get_hys_telemetry(
                dtu_sn=int(self._dtu_serial_number),
                inverter_sn=inv_sn,
                slave_index=slave_index,
            )
            if storage_data is not None:
                responses.append(storage_data)
                # Static topology phase verification:
                if hasattr(storage_data, "inv") and hasattr(storage_data.inv, "phase") and len(storage_data.inv.phase) >= 3:
                    self.three_phase_inverters_set.add(inv_sn_str.lower())

                # Fetch detailed EMS configuration only for Master inverter (idx == 0)
                if idx == 0:
                    current_mode_code = getattr(storage_data, "ems_mode", None)
                    last_mode_code = self._last_mode_codes.get(inv_sn_str)
                    
                    # Fetch if not yet fetched, or if the mode has changed
                    if inv_sn_str not in self.ems_configs or current_mode_code != last_mode_code:
                        _LOGGER.debug("Fetching detailed EMS config for Master inverter %s", inv_sn)
                        try:
                            ems_config_pb = await self._dtu.async_get_energy_storage_working_mode(
                                dtu_serial_number=int(self._dtu_serial_number),
                                inverter_serial_number=inv_sn,
                            )
                            if ems_config_pb is not None:
                                # Convert protobuf msg to dictionary
                                self.ems_configs[inv_sn_str] = MessageToDict(
                                    ems_config_pb,
                                    preserving_proto_field_name=True,
                                    always_print_fields_with_no_presence=True,
                                )
                                if current_mode_code is not None:
                                    self._last_mode_codes[inv_sn_str] = current_mode_code
                        except Exception as e:
                            _LOGGER.warning("Failed to fetch EMS config for inverter %s: %s", inv_sn, e)

        if not responses:
            _LOGGER.warning(
                "Unable to retrieve energy storage data. Inverter might be offline."
            )
            raise UpdateFailed("Unable to retrieve energy storage data.")
        return responses

