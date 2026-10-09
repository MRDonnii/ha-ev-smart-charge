"""Charge mode: how the charger is controlled."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import EvSmartChargeConfigEntry
from .entity import EvSmartChargeListenerEntity
from .plan import MODES


async def async_setup_entry(hass: HomeAssistant, entry: EvSmartChargeConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([ChargeModeSelect(entry.runtime_data, "charge_mode")])


class ChargeModeSelect(EvSmartChargeListenerEntity, SelectEntity, RestoreEntity):
    _attr_icon = "mdi:ev-station"
    _attr_options = list(MODES)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state in MODES:
            before = last.attributes.get("mode_before_now")
            if before in MODES:
                self.planner.mode_before_now = before
            self.planner.async_set_mode(last.state, restore=True)

    @property
    def current_option(self) -> str:
        return self.planner.mode

    @property
    def extra_state_attributes(self) -> dict:
        return {"mode_before_now": self.planner.mode_before_now}

    async def async_select_option(self, option: str) -> None:
        self.planner.async_set_mode(option)
