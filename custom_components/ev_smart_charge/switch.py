"""Whether the temporary trip is a round trip."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import EvSmartChargeConfigEntry
from .entity import EvSmartChargeListenerEntity


async def async_setup_entry(hass: HomeAssistant, entry: EvSmartChargeConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([TripRoundTrip(entry.runtime_data, "trip_round_trip")])


class TripRoundTrip(EvSmartChargeListenerEntity, SwitchEntity, RestoreEntity):
    _attr_icon = "mdi:swap-horizontal"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state in ("on", "off"):
            self.planner.trip.round_trip = last.state == "on"

    @property
    def is_on(self) -> bool:
        return self.planner.trip.round_trip

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.planner.async_set_trip_round_trip(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.planner.async_set_trip_round_trip(False)
