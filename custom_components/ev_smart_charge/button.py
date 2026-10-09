"""Clear the temporary trip plan."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EvSmartChargeConfigEntry
from .entity import EvSmartChargeEntity


async def async_setup_entry(hass: HomeAssistant, entry: EvSmartChargeConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([ClearTrip(entry.runtime_data, "trip_clear")])


class ClearTrip(EvSmartChargeEntity, ButtonEntity):
    _attr_icon = "mdi:map-marker-remove-outline"

    async def async_press(self) -> None:
        self.planner.async_clear_trip()
