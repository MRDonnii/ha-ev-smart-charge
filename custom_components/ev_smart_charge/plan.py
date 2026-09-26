"""Pure charge plan calculation. No Home Assistant imports, so it can be unit tested directly."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta

SLOT = timedelta(minutes=15)
# Windows whose total price differs by less than this are treated as equal; the later one wins,
# so the car is charged as close to the deadline as the price allows.
TIE_EPSILON = 0.08

PRICE_LIST_KEYS = ("prices", "raw_today", "raw_tomorrow", "today_prices", "tomorrow_prices",
                   "forecast", "data")
START_KEYS = ("start", "start_time", "startsAt", "from", "hour", "time")
END_KEYS = ("end", "end_time", "endsAt", "to")
PRICE_KEYS = ("price", "value", "total", "price_inc_vat", "electricity_price")


@dataclass(frozen=True)
class PriceSlot:
    start: datetime
    end: datetime
    price: float


@dataclass(frozen=True)
class PlanInput:
    soc: float | None
    target_soc: float
    capacity_kwh: float
    efficiency: float
    power_kw: float
    price_factor: float
    deadline: datetime | None
    slots: list[PriceSlot]


@dataclass(frozen=True)
class PlanResult:
    missing_battery_kwh: float | None
    missing_wall_kwh: float | None
    minutes_needed: float | None
    start: datetime | None
    end: datetime | None
    price: float | None


def _to_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _first(item: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


def parse_price_attributes(attributes: dict) -> list[PriceSlot]:
    """Read price intervals from a price entity's attributes (Strømligning, Nord Pool,
    Energi Data Service and similar) and split them into 15-minute slots."""
    raw: list[tuple[datetime, datetime | None, float]] = []
    for key in PRICE_LIST_KEYS:
        items = attributes.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            start = _to_datetime(_first(item, START_KEYS))
            price = _first(item, PRICE_KEYS)
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue
            if start is None or start.tzinfo is None or math.isnan(price):
                continue
            end = _to_datetime(_first(item, END_KEYS))
            raw.append((start, end if end and end.tzinfo else None, price))
    raw.sort(key=lambda entry: entry[0])
    slots: dict[datetime, PriceSlot] = {}
    for index, (start, end, price) in enumerate(raw):
        if end is None:
            # No end given: the interval lasts until the next start, or as long as the previous one.
            following = raw[index + 1][0] if index + 1 < len(raw) else None
            previous = raw[index - 1][0] if index else None
            if following and following - start <= timedelta(hours=1):
                end = following
            elif previous and start - previous <= timedelta(hours=1):
                end = start + (start - previous)
            else:
                end = start + timedelta(hours=1)
        cursor = start
        while cursor + SLOT <= end:
            slots.setdefault(cursor, PriceSlot(cursor, cursor + SLOT, price))
            cursor += SLOT
    return sorted(slots.values(), key=lambda slot: slot.start)


def next_deadline(now: datetime, ready_by: time) -> datetime:
    """The next occurrence of the ready-by clock time, in now's time zone."""
    candidate = datetime.combine(now.date(), ready_by, tzinfo=now.tzinfo)
    if candidate <= now:
        candidate = datetime.combine(now.date() + timedelta(days=1), ready_by, tzinfo=now.tzinfo)
    return candidate


def calculate(data: PlanInput, now: datetime) -> PlanResult:
    if data.soc is None or data.capacity_kwh <= 0:
        return PlanResult(None, None, None, None, None, None)
    missing_pct = max(data.target_soc - data.soc, 0.0)
    missing_battery = data.capacity_kwh * missing_pct / 100
    missing_wall = missing_battery / data.efficiency if data.efficiency > 0 else 0.0
    minutes = missing_wall / data.power_kw * 60 if data.power_kw > 0 else 0.0
    result = dict(missing_battery_kwh=round(missing_battery, 2), missing_wall_kwh=round(missing_wall, 2),
                  minutes_needed=round(minutes))
    if missing_wall <= 0 or data.power_kw <= 0 or data.deadline is None:
        return PlanResult(**result, start=None, end=None, price=None)

    needed = max(math.ceil(minutes / 15 - 1e-9), 1)
    usable = [slot for slot in data.slots if slot.end > now and slot.end <= data.deadline]
    best_total: float | None = None
    best_index: int | None = None
    for index in range(len(usable) - needed + 1):
        chunk = usable[index:index + needed]
        if any(chunk[j].end != chunk[j + 1].start for j in range(needed - 1)):
            continue
        total = sum(slot.price for slot in chunk)
        if best_total is None or total < best_total - TIE_EPSILON:
            best_total, best_index = total, index
        elif abs(total - best_total) <= TIE_EPSILON:
            best_index = index
    if best_index is None:
        return PlanResult(**result, start=None, end=None, price=None)

    start = usable[best_index].start
    remaining = missing_wall
    cost = 0.0
    for slot in usable[best_index:]:
        if remaining <= 0:
            break
        kwh = min(data.power_kw * 0.25, remaining)
        cost += kwh * slot.price * data.price_factor
        remaining -= kwh
    return PlanResult(**result, start=start, end=start + timedelta(minutes=minutes),
                      price=round(cost, 2))
