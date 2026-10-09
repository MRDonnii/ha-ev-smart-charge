"""Destination of a temporary trip plan: an address, "lat,lon" or a zone entity id."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import EvSmartChargeConfigEntry
from .entity import EvSmartChargeListenerEntity


async def async_setup_entry(hass: HomeAssistant, entry: EvSmartChargeConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([TripDestination(entry.runtime_data, "trip_destination")])


class TripDestination(EvSmartChargeListenerEntity, TextEntity, RestoreEntity):
    _attr_icon = "mdi:map-marker-path"
    _attr_native_min = 0
    _attr_native_max = 255

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state not in ("unknown", "unavailable", ""):
            self.planner.async_set_trip_destination(last.state)

    @property
    def native_value(self) -> str:
        return self.planner.trip.destination

    async def async_set_value(self, value: str) -> None:
        self.planner.async_set_trip_destination(value)
