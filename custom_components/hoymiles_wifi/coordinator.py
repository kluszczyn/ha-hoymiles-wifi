"""Coordinator for Hoymiles integration."""

from datetime import timedelta
import logging

import homeassistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
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
            _LOGGER.debug(
                "Unable to retrieve real data new. Inverter might be offline."
            )
        return response


class HoymilesConfigUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Config coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = await self._dtu.async_get_config()

        if not response:
            _LOGGER.debug("Unable to retrieve config data. Inverter might be offline.")

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
            _LOGGER.debug(
                "Unable to retrieve app information data. Inverter might be offline."
            )
        return response


class HoymilesGatewayInfoUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Gateway Info coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles gateway info coordinator update")

        response = await self._dtu.async_get_gateway_info()

        if not response:
            _LOGGER.debug("Unable to retrieve gateway info. Inverter might be offline.")
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
            _LOGGER.debug(
                "Unable to retrieve network information. Inverter might be offline."
            )
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
        super().__init__(hass, dtu, config_entry, update_interval)

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles energy storage coordinator update")

        from hoymiles_wifi.hys import HysClient
        hys = HysClient(self._dtu)
        responses = []

        # inverter has keys: inverter_serial_number, model_name, and optionally addr (default to index + 1)
        for idx, inverter in enumerate(self._inverters):
            # In Master-Slave topology:
            # - Master (index 0) has addr=1 -> number=1 (represented as slave_index = 1)
            # - Slave S1 (index 1) has addr=2 -> number=2
            slave_index = idx + 1
            
            _LOGGER.debug(
                "Fetching telemetry for hybrid inverter %s (index: %d, routing number: %d)",
                inverter["inverter_serial_number"],
                idx,
                slave_index,
            )
            storage_data = await hys.async_get_hys_telemetry(
                dtu_sn=int(self._dtu_serial_number),
                inverter_sn=int(inverter["inverter_serial_number"]),
                slave_index=slave_index,
            )
            if storage_data is not None:
                responses.append(storage_data)

        if not responses:
            _LOGGER.debug(
                "Unable to retrieve energy storage data. Inverter might be offline."
            )
        return responses
