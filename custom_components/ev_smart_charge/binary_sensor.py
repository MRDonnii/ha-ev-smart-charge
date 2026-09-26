"""Plug-in reminder: on during the 15 minutes before the planned start."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import EvSmartChargeConfigEntry
from .entity import EvSmartChargeListenerEntity


async def async_setup_entry(hass: HomeAssistant, entry: EvSmartChargeConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([PlugInNow(entry.runtime_data, "plug_in_now")])


class PlugInNow(EvSmartChargeListenerEntity, BinarySensorEntity):
    _attr_icon = "mdi:power-plug"

    @property
    def is_on(self) -> bool:
        start = self.planner.result.start
        return bool(start) and start - timedelta(minutes=15) <= dt_util.now() <= start
