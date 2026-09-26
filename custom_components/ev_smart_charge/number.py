"""Plan settings: target SOC, charging power, efficiency and price factor."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EvSmartChargeConfigEntry
from .entity import EvSmartChargeEntity
from .planner import ChargePlanner

NUMBERS: tuple[NumberEntityDescription, ...] = (
    NumberEntityDescription(key="target_soc", icon="mdi:battery-charging-80",
                            native_min_value=10, native_max_value=100, native_step=1,
                            native_unit_of_measurement=PERCENTAGE, mode=NumberMode.SLIDER),
    NumberEntityDescription(key="charge_power_kw", icon="mdi:ev-station",
                            native_min_value=1, native_max_value=22, native_step=0.1,
                            native_unit_of_measurement=UnitOfPower.KILO_WATT,
                            mode=NumberMode.BOX, entity_category=EntityCategory.CONFIG),
    NumberEntityDescription(key="efficiency", icon="mdi:percent-circle-outline",
                            native_min_value=0.5, native_max_value=1, native_step=0.01,
                            mode=NumberMode.BOX, entity_category=EntityCategory.CONFIG),
    NumberEntityDescription(key="price_factor", icon="mdi:multiplication",
                            native_min_value=0, native_max_value=5, native_step=0.01,
                            mode=NumberMode.BOX, entity_category=EntityCategory.CONFIG),
)


async def async_setup_entry(hass: HomeAssistant, entry: EvSmartChargeConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(PlanNumber(entry.runtime_data, description) for description in NUMBERS)


class PlanNumber(EvSmartChargeEntity, RestoreNumber):
    _attr_should_poll = False

    def __init__(self, planner: ChargePlanner, description: NumberEntityDescription) -> None:
        super().__init__(planner, description.key)
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last and last.native_value is not None:
            self.planner.async_set_setting(self.entity_description.key, float(last.native_value))

    @property
    def native_value(self) -> float:
        return self.planner.settings[self.entity_description.key]

    async def async_set_native_value(self, value: float) -> None:
        self.planner.async_set_setting(self.entity_description.key, float(value))
        self.async_write_ha_state()
