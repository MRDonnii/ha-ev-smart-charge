"""End-to-end tests in Home Assistant with a simulated Zaptec charger."""

from collections import defaultdict
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.ev_smart_charge import charger as charger_module
from custom_components.ev_smart_charge import planner as planner_module

DOMAIN = "ev_smart_charge"
MODE = "sensor.charger_mode"
SWITCH = "switch.charger_charging"
AUTHORIZE = "button.charger_authorize"


def prices(cheap_now: bool) -> list[dict]:
    start = dt_util.now().replace(minute=0, second=0, microsecond=0)
    result = []
    for hour in range(-1, 30):
        begin = start + timedelta(hours=hour)
        price = 0.1 if (cheap_now and hour == 0) else (0.5 if hour == 5 else 3.0)
        result.append({"start": begin.isoformat(), "end": (begin + timedelta(hours=1)).isoformat(), "price": price})
    return result


async def setup(hass: HomeAssistant, request, charger_state="connected_finished", charger=True, cheap_now=True,
                soc="50", grace=0, start_delay=0):
    hass.states.async_set("sensor.car_battery", soc)
    hass.states.async_set("sensor.price", "1.0", {"prices": prices(cheap_now), "unit_of_measurement": "kr/kWh"})
    options = {"battery_entity": "sensor.car_battery", "price_entities": ["sensor.price"],
               "battery_capacity_kwh": 60, "charger_type": "none"}
    if charger:
        zaptec = MockConfigEntry(domain="zaptec")
        zaptec.add_to_hass(hass)
        device = dr.async_get(hass).async_get_or_create(config_entry_id=zaptec.entry_id,
                                                        identifiers={("zaptec", "charger")})
        registry = er.async_get(hass)
        for domain, unique, object_id in (("sensor", "abc_charger_operation_mode", "charger_mode"),
                                          ("switch", "abc_charger_operation_mode", "charger_charging"),
                                          ("button", "abc_authorize_charge", "charger_authorize")):
            registry.async_get_or_create(domain, "zaptec", unique, device_id=device.id,
                                         config_entry=zaptec, suggested_object_id=object_id)
        hass.states.async_set(MODE, charger_state)
        hass.states.async_set(SWITCH, "on" if charger_state == "connected_charging" else "off")
        options |= {"charger_type": "zaptec", "zaptec_mode_entity": MODE}
    calls: dict[str, list[str]] = defaultdict(list)

    async def record(self, domain, service, entity_id):
        calls[f"{domain}.{service}"].append(entity_id)

    patcher = patch.object(charger_module.ChargerBackend, "_call", record)
    patcher.start()
    request.addfinalizer(patcher.stop)
    entry = MockConfigEntry(domain=DOMAIN, title="Bil", data=options, unique_id="sensor.car_battery")
    entry.add_to_hass(hass)
    for name, value in (("STARTUP_GRACE_SECONDS", grace), ("START_DELAY_SECONDS", start_delay)):
        patcher = patch.object(planner_module, name, value)
        patcher.start()
        request.addfinalizer(patcher.stop)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, calls


def state(hass, entity_id):
    return hass.states.get(entity_id).state


async def tick(hass, minutes=1):
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
    await hass.async_block_till_done()


async def test_plan_only_without_charger(hass: HomeAssistant, request):
    await setup(hass, request, charger=False)
    assert state(hass, "select.bil_charge_mode") == "smart"
    assert state(hass, "sensor.bil_charge_status") == "plan_only"
    assert state(hass, "binary_sensor.bil_charge_now") == "on"  # the cheapest hour is now
    assert float(state(hass, "sensor.bil_planned_charge_energy")) == pytest.approx(20.0)


async def test_starts_paused_charger_in_cheap_slot(hass: HomeAssistant, request):
    _, calls = await setup(hass, request)
    assert calls["switch.turn_on"] == [SWITCH]
    assert state(hass, "sensor.bil_charge_status") == "starting"


async def test_authorizes_waiting_charger(hass: HomeAssistant, request):
    _, calls = await setup(hass, request, charger_state="connected_requesting")
    assert calls["button.press"] == [AUTHORIZE]
    assert not calls["switch.turn_on"]


async def test_waits_when_expensive_and_stops_running_charge(hass: HomeAssistant, request):
    _, calls = await setup(hass, request, charger_state="connected_charging", cheap_now=False)
    assert calls["switch.turn_off"] == [SWITCH]
    hass.states.async_set(MODE, "connected_finished")
    await hass.async_block_till_done()
    assert state(hass, "sensor.bil_charge_status") == "waiting"
    expected = dt_util.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=5)
    assert dt_util.parse_datetime(state(hass, "sensor.bil_next_charge_start")) == expected


async def test_pause_mode_never_starts(hass: HomeAssistant, request):
    _, calls = await setup(hass, request, cheap_now=False)
    await hass.services.async_call("select", "select_option",
                                   {"entity_id": "select.bil_charge_mode", "option": "off"}, blocking=True)
    await tick(hass, 10)
    assert not calls["switch.turn_on"]
    assert state(hass, "sensor.bil_charge_status") == "paused"


async def test_manual_start_switches_to_charge_now_until_unplugged(hass: HomeAssistant, request):
    _, calls = await setup(hass, request, cheap_now=False)
    hass.states.async_set(MODE, "connected_charging")
    await hass.async_block_till_done()
    assert state(hass, "select.bil_charge_mode") == "now"
    assert not calls["switch.turn_off"]
    hass.states.async_set(MODE, "disconnected")
    await hass.async_block_till_done()
    assert state(hass, "select.bil_charge_mode") == "smart"


async def test_other_car_is_left_alone(hass: HomeAssistant, request):
    hass.states.async_set("binary_sensor.car_plug", "off")
    entry, calls = await setup(hass, request)
    options = {**entry.data, "car_plugged_entity": "binary_sensor.car_plug"}
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.async_block_till_done()
    await tick(hass, 5)
    assert state(hass, "sensor.bil_charge_status") == "other_car"


async def test_trip_with_coordinates(hass: HomeAssistant, request, aioclient_mock):
    aioclient_mock.get("https://router.project-osrm.org/route/v1/driving/10.0,56.0;10.5,56.5",
                       json={"code": "Ok", "routes": [{"distance": 100000, "duration": 3600}]})
    hass.config.latitude, hass.config.longitude = 56.0, 10.0
    await setup(hass, request, charger=False, cheap_now=False)
    departure = dt_util.now() + timedelta(hours=10)
    await hass.services.async_call("datetime", "set_value", {"entity_id": "datetime.bil_temporary_departure",
                                                             "datetime": departure}, blocking=True)
    await hass.services.async_call("text", "set_value", {"entity_id": "text.bil_trip_destination",
                                                         "value": "56.5, 10.5"}, blocking=True)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert float(state(hass, "sensor.bil_trip_distance")) == 100
    # 200 km * 180 Wh * 1.15 = 41.4 kWh -> 10 % + 69 % = 79 %
    assert float(state(hass, "sensor.bil_trip_soc_needed")) == pytest.approx(79.0)
    assert float(state(hass, "sensor.bil_plan_target_soc")) == 80  # the daily target is higher
    await hass.services.async_call("button", "press", {"entity_id": "button.bil_clear_temporary_plan"},
                                   blocking=True)
    assert state(hass, "datetime.bil_temporary_departure") == "unknown"


async def test_vehicle_model_is_guessed_from_the_car(hass: HomeAssistant, request):
    car = MockConfigEntry(domain="tesla_custom")
    car.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(config_entry_id=car.entry_id, identifiers={("tesla_custom", "1")},
                                                    manufacturer="Tesla", model="Model 3")
    registry = er.async_get(hass)
    registry.async_get_or_create("sensor", "tesla_custom", "vin_battery", device_id=device.id, config_entry=car,
                                 suggested_object_id="car_battery")
    registry.async_get_or_create("sensor", "tesla_custom", "vin_range", device_id=device.id, config_entry=car,
                                 suggested_object_id="car_range")
    hass.states.async_set("sensor.car_range", "307.6", {"unit_of_measurement": "km"})
    entry, _ = await setup(hass, request, charger=False, soc="75")
    attrs = hass.states.get("sensor.bil_charge_status").attributes
    assert attrs["vehicle_model"] == "model_3_rwd"
    assert attrs["vehicle_body"] == "model_3"
    assert attrs["battery_capacity_kwh"] == 60  # the configured capacity still wins


async def test_alternative_plans_are_priced(hass: HomeAssistant, request):
    await setup(hass, request, charger=False, cheap_now=False)
    alternatives = hass.states.get("sensor.bil_planned_charge_cost").attributes["alternatives"]
    assert set(alternatives) == {"now", "smart", "fixed", "price_cap"}
    # 20 kWh: now at 3 kr/kWh, the cheapest plan in the 0.5 kr hour and the default 22-06 window
    assert alternatives["now"]["cost"] > alternatives["smart"]["cost"]
    assert alternatives["smart"]["cost"] == float(hass.states.get("sensor.bil_planned_charge_cost").state)
    assert alternatives["fixed"]["start"] is not None


async def test_start_waits_for_a_steady_plan(hass: HomeAssistant, request, freezer):
    _, calls = await setup(hass, request, start_delay=15)
    assert not calls["switch.turn_on"]
    assert state(hass, "sensor.bil_charge_status") == "starting"
    freezer.tick(timedelta(seconds=17))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["switch.turn_on"] == [SWITCH]
