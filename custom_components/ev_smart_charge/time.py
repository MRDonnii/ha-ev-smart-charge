"""Ready-by clock time."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import EvSmartChargeConfigEntry
from .entity import EvSmartChargeEntity


async def async_setup_entry(hass: HomeAssistant, entry: EvSmartChargeConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([ReadyByTime(entry.runtime_data, "ready_by_time")])


class ReadyByTime(EvSmartChargeEntity, TimeEntity, RestoreEntity):
    _attr_should_poll = False
    _attr_icon = "mdi:clock-check-outline"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last:
            try:
                self.planner.async_set_ready_by(time.fromisoformat(last.state))
            except ValueError:
                pass

    @property
    def native_value(self) -> time:
        return self.planner.ready_by

    async def async_set_value(self, value: time) -> None:
        self.planner.async_set_ready_by(value.replace(second=0, microsecond=0))
        self.async_write_ha_state()
