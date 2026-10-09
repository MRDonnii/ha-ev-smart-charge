"""Keeps the charge plan up to date and, when a charger is configured, starts and stops it."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from . import trip
from .charger import ChargerBackend, create_backend
from .const import (
    CONF_BATTERY_ENTITY,
    CONF_CAPACITY,
    CONF_CAR_PLUGGED_ENTITY,
    CONF_PRICE_ENTITIES,
    DEFAULT_CAPACITY,
    DEFAULT_CONSUMPTION,
    DEFAULT_EFFICIENCY,
    DEFAULT_FIXED_END,
    DEFAULT_FIXED_START,
    DEFAULT_MIN_SOC,
    DEFAULT_POWER_KW,
    DEFAULT_PRICE_CAP,
    DEFAULT_PRICE_FACTOR,
    DEFAULT_READY_BY,
    DEFAULT_TARGET_SOC,
    DEFAULT_TRIP_MARGIN,
    DEFAULT_TRIP_RESERVE,
    STARTUP_GRACE_SECONDS,
    STATUS_CHARGING,
    STATUS_DISCONNECTED,
    STATUS_DONE,
    STATUS_MANUAL,
    STATUS_NOT_RESPONDING,
    STATUS_OTHER_CAR,
    STATUS_PAUSED,
    STATUS_PLAN_ONLY,
    STATUS_STARTING,
    STATUS_STOPPED_EXTERNALLY,
    STATUS_UNKNOWN,
    STATUS_WAITING,
)
from .control import CONNECTED, Action, ChargerState, Controller
from .control import Event as ChargerEvent
from .plan import (
    MODE_FIXED,
    MODE_MANUAL,
    MODE_NOW,
    MODE_OFF,
    MODE_PRICE_CAP,
    MODE_SMART,
    Constraint,
    PlanInput,
    PlanResult,
    Schedule,
    ScheduleInput,
    build_schedule,
    build_timeline,
    calculate,
    fixed_window,
    floor_quarter,
    next_deadline,
    parse_price_attributes,
)

_LOGGER = logging.getLogger(__name__)

PLUGGED_STATES = (STATE_ON, "true", "plugged", "connected", "plugged_in")
HOLD_MODES = (MODE_SMART, MODE_FIXED, MODE_PRICE_CAP)
LOOKUP_RETRY = timedelta(minutes=5)


@dataclass
class TripState:
    departure: datetime | None = None
    destination: str = ""
    round_trip: bool = True
    route: trip.Route | None = None
    error: str | None = None
    looking_up: bool = False
    last_lookup: datetime | None = None


class ChargePlanner:
    """Holds the user settings (owned by the number/time/select/... entities) and the latest plan."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.settings: dict[str, float] = {
            "target_soc": DEFAULT_TARGET_SOC,
            "charge_power_kw": DEFAULT_POWER_KW,
            "efficiency": DEFAULT_EFFICIENCY,
            "price_factor": DEFAULT_PRICE_FACTOR,
            "price_cap": DEFAULT_PRICE_CAP,
            "min_soc": DEFAULT_MIN_SOC,
            "consumption": DEFAULT_CONSUMPTION,
            "trip_margin": DEFAULT_TRIP_MARGIN,
            "trip_reserve": DEFAULT_TRIP_RESERVE,
        }
        self.times: dict[str, time] = {
            "ready_by_time": time.fromisoformat(DEFAULT_READY_BY),
            "fixed_start": time.fromisoformat(DEFAULT_FIXED_START),
            "fixed_end": time.fromisoformat(DEFAULT_FIXED_END),
        }
        self.mode = MODE_SMART
        self.mode_before_now = MODE_SMART
        # Set once the charger has been connected while in "charge now"; a disconnect after that ends it.
        # Stored with the select entity, so an unplug while Home Assistant was down is noticed too.
        self.now_seen_connected = False
        self.trip = TripState()
        self.result = PlanResult(None, None, None, None, None, None)
        self.schedule = Schedule()
        self.deadline: datetime | None = None
        self.price_unit: str | None = None
        self.slot_count = 0
        self.status = STATUS_PLAN_ONLY
        self.charge_desired = False
        self.charger_state = ChargerState.UNKNOWN
        self.car_present = True
        self.backend: ChargerBackend | None = None
        self.controller = Controller()
        self._hold_until: datetime | None = None
        self._started_at: datetime | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []

    # -- configuration -----------------------------------------------------------------------

    @property
    def options(self) -> dict:
        return {**self.entry.data, **self.entry.options}

    @property
    def battery_entity(self) -> str:
        return self.options[CONF_BATTERY_ENTITY]

    @property
    def price_entities(self) -> list[str]:
        return list(self.options.get(CONF_PRICE_ENTITIES) or [])

    @property
    def plugged_entity(self) -> str | None:
        return self.options.get(CONF_CAR_PLUGGED_ENTITY) or None

    @property
    def capacity(self) -> float:
        return float(self.options.get(CONF_CAPACITY, DEFAULT_CAPACITY))

    @property
    def ready_by(self) -> time:
        return self.times["ready_by_time"]

    @property
    def controls_charger(self) -> bool:
        return self.backend is not None

    # -- lifecycle -----------------------------------------------------------------------------

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def async_start(self) -> None:
        self._started_at = dt_util.utcnow()
        self.backend = create_backend(self.hass, self.options, self.plugged_entity)
        watched = [self.battery_entity, *self.price_entities]
        if self.plugged_entity:
            watched.append(self.plugged_entity)
        if self.backend:
            watched.extend(self.backend.entities)
        self._unsubs.append(async_track_state_change_event(self.hass, list(dict.fromkeys(watched)), self._on_state))
        self._unsubs.append(async_track_time_interval(self.hass, self._on_tick, timedelta(minutes=1)))
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
        trip_state = self.trip
        if (trip_state.destination and trip_state.route is None and not trip_state.looking_up
                and trip_state.error == "lookup_failed" and trip_state.last_lookup
                and dt_util.utcnow() - trip_state.last_lookup >= LOOKUP_RETRY):
            self._start_lookup()
        self.async_recalculate()

    # -- setters used by the entities ----------------------------------------------------------

    @callback
    def async_set_setting(self, key: str, value: float) -> None:
        self.settings[key] = value
        self.async_recalculate()

    @callback
    def async_set_time(self, key: str, value: time) -> None:
        self.times[key] = value
        self.async_recalculate()

    @callback
    def async_set_ready_by(self, value: time) -> None:
        self.async_set_time("ready_by_time", value)

    @callback
    def async_set_mode(self, mode: str, restore: bool = False) -> None:
        if mode == MODE_NOW and self.mode != MODE_NOW and not restore:
            self.mode_before_now = self.mode
            self.now_seen_connected = False
        self.mode = mode
        self._hold_until = None
        if not restore:
            self.controller.reset()
        self.async_recalculate()

    @callback
    def async_set_trip_departure(self, value: datetime | None) -> None:
        self.trip.departure = value
        self.async_recalculate()

    @callback
    def async_set_trip_round_trip(self, value: bool) -> None:
        self.trip.round_trip = value
        self.async_recalculate()

    @callback
    def async_set_trip_destination(self, value: str, route: trip.Route | None = None) -> None:
        """Set the destination. A route restored from before a restart is used as is, without a lookup."""
        self.trip.destination = (value or "").strip()
        self.trip.route = route
        self.trip.error = None
        if self.trip.destination and route is None:
            self._start_lookup()
        self.async_recalculate()

    @callback
    def _start_lookup(self) -> None:
        self.trip.looking_up = True
        self.trip.last_lookup = dt_util.utcnow()
        self.entry.async_create_background_task(
            self.hass, self._async_lookup(self.trip.destination), "ev_smart_charge_route")

    @callback
    def async_clear_trip(self) -> None:
        self.trip = TripState()
        self.async_recalculate()

    # -- trip ------------------------------------------------------------------------------------

    def _home(self) -> tuple[float, float]:
        return self.hass.config.latitude, self.hass.config.longitude

    async def _async_lookup(self, text: str) -> None:
        route: trip.Route | None = None
        error: str | None = None
        try:
            route = await self._async_route(text)
            if route is None:
                error = "not_found"
        except Exception as err:  # noqa: BLE001 - network and parse errors all mean "no route"
            _LOGGER.warning("Route lookup for %s failed: %s", text, err)
            error = "lookup_failed"
        if text != self.trip.destination:
            return  # the destination changed while we were looking up
        self.trip.route, self.trip.error, self.trip.looking_up = route, error, False
        self.async_recalculate()

    async def _async_route(self, text: str) -> trip.Route | None:
        origin = self._home()
        name = text
        target: tuple[float, float] | None = None
        if text.startswith("zone.") and (zone := self.hass.states.get(text)):
            target = (zone.attributes["latitude"], zone.attributes["longitude"])
            name = zone.name
        elif coordinates := trip.parse_coordinates(text):
            target = coordinates
        session = async_get_clientsession(self.hass)
        if target is None:
            found = await trip.async_geocode(session, text, self.hass.config.language)
            if found is None:
                return None
            target, name = (found[0], found[1]), found[2]
        try:
            road = await trip.async_road_distance(session, origin, target)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Road distance failed, using straight line: %s", err)
            road = None
        if road:
            return trip.Route(round(road[0], 1), round(road[1]), name, target[0], target[1], "route")
        straight = trip.haversine_km(*origin, *target) * trip.DETOUR_FACTOR
        return trip.Route(round(straight, 1), None, name, target[0], target[1], "straight_line")

    @property
    def trip_active(self) -> bool:
        return self.trip.departure is not None

    @property
    def trip_energy_kwh(self) -> float | None:
        if self.trip.route is None:
            return None
        return round(trip.trip_energy_kwh(self.trip.route.distance_km, self.trip.round_trip,
                                          self.settings["consumption"], self.settings["trip_margin"]), 1)

    @property
    def trip_target_soc(self) -> float | None:
        energy = self.trip_energy_kwh
        if energy is None:
            return None
        return round(trip.trip_target_soc(energy, self.capacity, self.settings["trip_reserve"]), 1)

    # -- plan and control ------------------------------------------------------------------------

    def _battery_soc(self) -> float | None:
        state = self.hass.states.get(self.battery_entity)
        try:
            return float(state.state) if state else None
        except (TypeError, ValueError):
            return None

    def _car_present(self) -> bool:
        """False only when the car's own plug sensor says it is not plugged in (another car is)."""
        if not self.plugged_entity or (state := self.hass.states.get(self.plugged_entity)) is None:
            return True
        if state.state == STATE_OFF or state.state in ("false", "unplugged", "disconnected"):
            return False
        return state.state.lower() in PLUGGED_STATES or state.state in ("unknown", "unavailable")

    def constraints(self, now: datetime) -> tuple[Constraint, ...]:
        target = self.settings["target_soc"]
        result = []
        if self.mode in (MODE_SMART, MODE_MANUAL):
            result.append(Constraint(self.deadline, target))
        if self.trip_active and self.trip.departure > now:
            trip_target = self.trip_target_soc
            result.append(Constraint(self.trip.departure, min(max(target, trip_target or 0.0), 100.0)))
        return tuple(result)

    @callback
    def async_recalculate(self) -> None:
        now = dt_util.now()
        if self.trip.departure is not None and self.trip.departure <= now:
            _LOGGER.debug("Trip departure passed, clearing the temporary plan")
            self.trip = TripState()

        if self.backend:
            self.charger_state = self.backend.state()
            self.car_present = self._car_present()
            event = self.controller.observe(self.charger_state, now)
            self._handle_event(event)
            if self.mode == MODE_NOW:
                if self.charger_state in CONNECTED:
                    self.now_seen_connected = True
                elif self.charger_state == ChargerState.DISCONNECTED and self.now_seen_connected:
                    _LOGGER.debug("Car unplugged, charge now ends")
                    self.mode = self.mode_before_now if self.mode_before_now != MODE_NOW else MODE_SMART
                    self.now_seen_connected = False

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
        soc = self._battery_soc()
        self.result = calculate(PlanInput(
            soc=soc,
            target_soc=self.settings["target_soc"],
            capacity_kwh=self.capacity,
            efficiency=self.settings["efficiency"],
            power_kw=self.settings["charge_power_kw"],
            price_factor=self.settings["price_factor"],
            deadline=self.deadline,
            slots=ordered,
        ), now)

        window = fixed_window(now, self.times["fixed_start"], self.times["fixed_end"])
        constraints = self.constraints(now)
        horizon = max([self.deadline, window[1], *(c.deadline for c in constraints)])
        self.schedule = build_schedule(ScheduleInput(
            mode=self.mode,
            soc=soc,
            target_soc=self.settings["target_soc"],
            capacity_kwh=self.capacity,
            efficiency=self.settings["efficiency"],
            power_kw=self.settings["charge_power_kw"],
            price_factor=self.settings["price_factor"],
            timeline=build_timeline(now, ordered, horizon),
            constraints=constraints,
            window=window if self.mode == MODE_FIXED else None,
            price_cap=self.settings["price_cap"],
            min_soc=self.settings["min_soc"],
        ), now)

        self._control(now)
        for update in list(self._listeners):
            update()

    @callback
    def _handle_event(self, event: ChargerEvent | None) -> None:
        if event is None:
            return
        _LOGGER.debug("Charger event %s (mode %s)", event, self.mode)
        if event == ChargerEvent.UNPLUGGED:
            self._hold_until = None
        elif event == ChargerEvent.MANUAL_START and self.car_present and self.mode not in (MODE_NOW, MODE_MANUAL):
            # Started from the charger's app or the car: follow the user and charge now.
            self.mode_before_now, self.mode = self.mode, MODE_NOW
            self.now_seen_connected = True
            self.controller.last_desired = True

    def desired(self, now: datetime) -> bool:
        """Should the car charge right now according to the plan."""
        if self.mode in (MODE_OFF, MODE_MANUAL):
            return False
        if self.schedule.charge_now:
            if self.charger_state == ChargerState.CHARGING and self.mode in HOLD_MODES:
                # Keep going to the end of the quarter, so small plan changes do not toggle the charger.
                self._hold_until = floor_quarter(now) + timedelta(minutes=15)
            return True
        if (self._hold_until and now < self._hold_until and self.mode in HOLD_MODES
                and self.schedule.energy_kwh > 0 and self.charger_state == ChargerState.CHARGING):
            return True
        self._hold_until = None
        return False

    @callback
    def _control(self, now: datetime) -> None:
        desired = self.charge_desired = self.desired(now)
        if self.backend is None:
            self.status = STATUS_PLAN_ONLY
            return
        state = self.charger_state
        self.status = self._status(state, desired)
        if self.mode == MODE_MANUAL or not self.car_present:
            return
        if self.mode != MODE_NOW and (self._battery_soc() is None or not self.slot_count):
            # Right after a restart the car or the price sensor may not be loaded yet: leave the
            # charger as it is instead of acting on a plan made without them.
            return
        if self._started_at and (dt_util.utcnow() - self._started_at).total_seconds() < STARTUP_GRACE_SECONDS:
            return
        action = self.controller.decide(desired, now)
        if action == Action.NONE:
            return
        _LOGGER.info("%s: %s charging (mode %s, charger %s)", self.entry.title, action, self.mode, state)
        if action == Action.START:
            self.status = STATUS_STARTING
        self.entry.async_create_task(self.hass, self.backend.async_command(action, state), "ev_smart_charge_command")

    def _status(self, state: ChargerState, desired: bool) -> str:
        if self.mode == MODE_MANUAL:
            return STATUS_MANUAL
        if state == ChargerState.DISCONNECTED:
            return STATUS_DISCONNECTED
        if state == ChargerState.UNKNOWN:
            return STATUS_UNKNOWN
        if not self.car_present:
            return STATUS_OTHER_CAR
        if state == ChargerState.CHARGING:
            return STATUS_CHARGING
        if desired and self.controller.blocked:
            return STATUS_STOPPED_EXTERNALLY
        if desired and self.controller.gave_up:
            return STATUS_NOT_RESPONDING
        if self.mode == MODE_OFF:
            return STATUS_PAUSED
        if desired:
            return STATUS_STARTING
        if self.schedule.energy_kwh <= 0 and self.mode != MODE_NOW:
            return STATUS_DONE
        return STATUS_WAITING
