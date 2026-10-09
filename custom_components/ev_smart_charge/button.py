"""Buttons: clear the temporary trip plan, and confirm the cheapest plan (answers the phone question)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EvSmartChargeConfigEntry
from .entity import EvSmartChargeEntity
from .plan import MODE_SMART


async def async_setup_entry(hass: HomeAssistant, entry: EvSmartChargeConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([ClearTrip(entry.runtime_data, "trip_clear"), ConfirmPlan(entry.runtime_data, "confirm_plan")])


class ClearTrip(EvSmartChargeEntity, ButtonEntity):
    _attr_icon = "mdi:map-marker-remove-outline"

    async def async_press(self) -> None:
        self.planner.async_clear_trip()


class ConfirmPlan(EvSmartChargeEntity, ButtonEntity):
    _attr_icon = "mdi:check-circle-outline"

    async def async_press(self) -> None:
        self.planner.async_answer(MODE_SMART)
