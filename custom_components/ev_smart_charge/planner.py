"""Keeps the charge plan up to date from the configured battery and price entities."""

from __future__ import annotations

from collections.abc import Callable
from datetime import time, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BATTERY_ENTITY,
    CONF_CAPACITY,
    CONF_PRICE_ENTITIES,
    DEFAULT_CAPACITY,
    DEFAULT_EFFICIENCY,
    DEFAULT_POWER_KW,
    DEFAULT_PRICE_FACTOR,
    DEFAULT_READY_BY,
    DEFAULT_TARGET_SOC,
)
from .plan import PlanInput, PlanResult, calculate, next_deadline, parse_price_attributes


class ChargePlanner:
    """Holds the user settings (owned by the number/time entities) and the latest plan."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.settings: dict[str, float] = {
            "target_soc": DEFAULT_TARGET_SOC,
            "charge_power_kw": DEFAULT_POWER_KW,
            "efficiency": DEFAULT_EFFICIENCY,
            "price_factor": DEFAULT_PRICE_FACTOR,
        }
        self.ready_by: time = time.fromisoformat(DEFAULT_READY_BY)
        self.result = PlanResult(None, None, None, None, None, None)
        self.deadline = None
        self.price_unit: str | None = None
        self.slot_count = 0
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []

    @property
    def options(self) -> dict:
        return {**self.entry.data, **self.entry.options}

    @property
    def battery_entity(self) -> str:
        return self.options[CONF_BATTERY_ENTITY]

    @property
    def price_entities(self) -> list[str]:
        return list(self.options.get(CONF_PRICE_ENTITIES) or [])

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def async_start(self) -> None:
        self._unsubs.append(async_track_state_change_event(
            self.hass, [self.battery_entity, *self.price_entities], self._on_state))
        self._unsubs.append(async_track_time_interval(
            self.hass, self._on_tick, timedelta(minutes=1)))
        self.async_recalculate()

    @callback
    def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()

    @callback
    def _on_state(self, _event: Event) -> None:
        self.async_recalculate()

    @callback
    def _on_tick(self, _now) -> None:
        self.async_recalculate()

    @callback
    def async_set_setting(self, key: str, value: float) -> None:
        self.settings[key] = value
        self.async_recalculate()

    @callback
    def async_set_ready_by(self, value: time) -> None:
        self.ready_by = value
        self.async_recalculate()

    def _battery_soc(self) -> float | None:
        state = self.hass.states.get(self.battery_entity)
        try:
            return float(state.state) if state else None
        except (TypeError, ValueError):
            return None

    @callback
    def async_recalculate(self) -> None:
        now = dt_util.now()
        slots = []
        self.price_unit = None
        for entity_id in self.price_entities:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            slots.extend(parse_price_attributes(dict(state.attributes)))
            unit = state.attributes.get("unit_of_measurement")
            if unit and not self.price_unit:
                self.price_unit = str(unit).split("/")[0].strip() or None
        unique = {slot.start: slot for slot in slots}
        ordered = [unique[key] for key in sorted(unique)]
        self.slot_count = len(ordered)
        self.deadline = next_deadline(now, self.ready_by)
        self.result = calculate(PlanInput(
            soc=self._battery_soc(),
            target_soc=self.settings["target_soc"],
            capacity_kwh=float(self.options.get(CONF_CAPACITY, DEFAULT_CAPACITY)),
            efficiency=self.settings["efficiency"],
            power_kw=self.settings["charge_power_kw"],
            price_factor=self.settings["price_factor"],
            deadline=self.deadline,
            slots=ordered,
        ), now)
        for update in list(self._listeners):
            update()
