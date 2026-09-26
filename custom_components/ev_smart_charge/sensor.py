"""Charge plan sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import EvSmartChargeConfigEntry
from .entity import EvSmartChargeListenerEntity
from .planner import ChargePlanner

NO_PLAN = "—"


def _clock(value) -> str:
    return dt_util.as_local(value).strftime("%H:%M") if value else NO_PLAN


@dataclass(frozen=True, kw_only=True)
class PlanSensorDescription(SensorEntityDescription):
    value: Callable[[ChargePlanner], Any]


SENSORS: tuple[PlanSensorDescription, ...] = (
    PlanSensorDescription(key="best_charge_start", device_class=SensorDeviceClass.TIMESTAMP,
                          icon="mdi:clock-start", value=lambda p: p.result.start),
    PlanSensorDescription(key="best_charge_end", device_class=SensorDeviceClass.TIMESTAMP,
                          icon="mdi:clock-end", value=lambda p: p.result.end),
    PlanSensorDescription(key="best_charge_start_text", icon="mdi:car-clock",
                          value=lambda p: _clock(p.result.start)),
    PlanSensorDescription(key="best_charge_end_text", icon="mdi:clock-check-outline",
                          value=lambda p: _clock(p.result.end)),
    PlanSensorDescription(key="best_charge_price", device_class=SensorDeviceClass.MONETARY,
                          icon="mdi:cash", suggested_display_precision=2,
                          value=lambda p: p.result.price),
    PlanSensorDescription(key="missing_battery_kwh", device_class=SensorDeviceClass.ENERGY_STORAGE,
                          native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                          state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
                          icon="mdi:battery-arrow-up", value=lambda p: p.result.missing_battery_kwh),
    PlanSensorDescription(key="missing_wall_kwh", device_class=SensorDeviceClass.ENERGY_STORAGE,
                          native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                          state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
                          icon="mdi:transmission-tower", value=lambda p: p.result.missing_wall_kwh),
    PlanSensorDescription(key="charge_minutes_needed", device_class=SensorDeviceClass.DURATION,
                          native_unit_of_measurement=UnitOfTime.MINUTES,
                          state_class=SensorStateClass.MEASUREMENT, icon="mdi:timer-outline",
                          value=lambda p: p.result.minutes_needed),
    PlanSensorDescription(key="ready_by", device_class=SensorDeviceClass.TIMESTAMP,
                          icon="mdi:calendar-clock", value=lambda p: p.deadline),
)


async def async_setup_entry(hass: HomeAssistant, entry: EvSmartChargeConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(PlanSensor(entry.runtime_data, description) for description in SENSORS)


class PlanSensor(EvSmartChargeListenerEntity, SensorEntity):
    entity_description: PlanSensorDescription

    def __init__(self, planner: ChargePlanner, description: PlanSensorDescription) -> None:
        super().__init__(planner, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value(self.planner)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.key == "best_charge_price":
            return self.planner.price_unit or "kr"
        return self.entity_description.native_unit_of_measurement

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "best_charge_start":
            return None
        return {"deadline": self.planner.deadline, "price_slots": self.planner.slot_count}
