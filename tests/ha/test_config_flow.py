"""Adding cars: pick the car's device and its sensors are linked automatically."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .test_integration import DOMAIN, prices


def car(hass, name: str, vin: str) -> str:
    entry = MockConfigEntry(domain="tesla_custom")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, identifiers={("tesla_custom", vin)},
                                                    manufacturer="Tesla", model="Model 3", name=name)
    registry = er.async_get(hass)
    slug = name.lower()
    registry.async_get_or_create("sensor", "tesla_custom", f"{vin}_battery", device_id=device.id, config_entry=entry,
                                 suggested_object_id=f"{slug}_battery", original_device_class="battery")
    registry.async_get_or_create("binary_sensor", "tesla_custom", f"{vin}_charger", device_id=device.id,
                                 config_entry=entry, suggested_object_id=f"{slug}_charger",
                                 original_device_class="plug")
    hass.states.async_set(f"sensor.{slug}_battery", "60")
    hass.states.async_set(f"binary_sensor.{slug}_charger", "on")
    return device.id


async def add(hass, **user_input):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    return await hass.config_entries.flow.async_configure(result["flow_id"], {
        "price_entities": ["sensor.price"], "vehicle_model": "auto", "charger_type": "none", **user_input})


async def test_two_cars_each_linked_to_their_own_sensors(hass: HomeAssistant):
    hass.states.async_set("sensor.price", "1", {"prices": prices(False)})
    first, second = car(hass, "Alpha", "1"), car(hass, "Beta", "2")
    result = await add(hass, car_device=first)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Alpha"
    assert result["data"]["battery_entity"] == "sensor.alpha_battery"
    assert result["data"]["car_plugged_entity"] == "binary_sensor.alpha_charger"
    result = await add(hass, car_device=second, name="Familiebilen")
    assert result["title"] == "Familiebilen"
    assert result["data"]["battery_entity"] == "sensor.beta_battery"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2
    assert (await add(hass, car_device=first))["reason"] == "already_configured"


async def test_battery_is_needed_without_a_car(hass: HomeAssistant):
    hass.states.async_set("sensor.price", "1", {"prices": prices(False)})
    result = await add(hass)
    assert result["errors"] == {"battery_entity": "battery_required"}


async def test_options_switch_car(hass: HomeAssistant):
    hass.states.async_set("sensor.price", "1", {"prices": prices(False)})
    first, second = car(hass, "Alpha", "1"), car(hass, "Beta", "2")
    entry = hass.config_entries.async_get_entry((await add(hass, car_device=first))["result"].entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "car_device": second, "battery_entity": "sensor.alpha_battery", "price_entities": ["sensor.price"],
        "vehicle_model": "auto", "charger_type": "none"})
    assert result["data"]["battery_entity"] == "sensor.beta_battery"
    assert result["data"]["car_plugged_entity"] == "binary_sensor.beta_charger"
