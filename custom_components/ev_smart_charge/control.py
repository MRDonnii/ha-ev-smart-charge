"""Decides when to send start/stop to the charger. No Home Assistant imports, so it can be unit tested."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class ChargerState(StrEnum):
    UNKNOWN = "unknown"
    DISCONNECTED = "disconnected"
    READY = "ready"  # car connected, waiting to be started or authorised
    CHARGING = "charging"
    PAUSED = "paused"  # car connected, charging stopped or finished


class Action(StrEnum):
    NONE = "none"
    START = "start"
    STOP = "stop"


class Event(StrEnum):
    PLUGGED = "plugged"
    UNPLUGGED = "unplugged"
    MANUAL_START = "manual_start"
    EXTERNAL_STOP = "external_stop"


CONNECTED = (ChargerState.READY, ChargerState.CHARGING, ChargerState.PAUSED)


@dataclass
class Controller:
    """Sends a command only when the charger is not already where the plan wants it, waits for the
    charger to react before trying again, and gives up after a few attempts. A start or stop that
    did not come from here is reported, so the plan can follow the user instead of fighting them."""

    retry_after: timedelta = timedelta(minutes=3)
    own_command_window: timedelta = timedelta(minutes=5)
    max_start_attempts: int = 3

    state: ChargerState | None = None
    last_command: Action = Action.NONE
    last_command_at: datetime | None = None
    start_attempts: int = 0
    blocked: bool = False  # the car or the user stopped the charging; do not restart on our own
    last_desired: bool | None = None

    def _own(self, action: Action, now: datetime) -> bool:
        return (self.last_command == action and self.last_command_at is not None
                and now - self.last_command_at <= self.own_command_window)

    def reset(self) -> None:
        self.start_attempts = 0
        self.blocked = False

    def observe(self, state: ChargerState, now: datetime) -> Event | None:
        previous, self.state = self.state, state
        if previous is None or previous == state or state == ChargerState.UNKNOWN:
            return None
        if state == ChargerState.DISCONNECTED:
            self.reset()
            return Event.UNPLUGGED if previous != ChargerState.UNKNOWN else None
        if previous in (ChargerState.DISCONNECTED, ChargerState.UNKNOWN):
            self.reset()
            if previous == ChargerState.DISCONNECTED:
                return Event.PLUGGED
            return None
        if state == ChargerState.CHARGING:
            self.start_attempts = 0
            return None if self._own(Action.START, now) else Event.MANUAL_START
        if previous == ChargerState.CHARGING and not self._own(Action.STOP, now):
            self.blocked = True
            return Event.EXTERNAL_STOP
        return None

    @property
    def gave_up(self) -> bool:
        return self.start_attempts >= self.max_start_attempts

    def decide(self, desired: bool, now: datetime) -> Action:
        if desired != self.last_desired:
            self.last_desired = desired
            self.reset()
        state = self.state
        if state not in CONNECTED:
            return Action.NONE
        waiting = self.last_command_at is not None and now - self.last_command_at < self.retry_after
        if desired and state != ChargerState.CHARGING:
            if self.blocked or self.gave_up or (waiting and self.last_command == Action.START):
                return Action.NONE
            self.start_attempts += 1
            return self._command(Action.START, now)
        if not desired and state == ChargerState.CHARGING:
            if waiting and self.last_command == Action.STOP:
                return Action.NONE
            return self._command(Action.STOP, now)
        return Action.NONE

    def _command(self, action: Action, now: datetime) -> Action:
        self.last_command, self.last_command_at = action, now
        return action
