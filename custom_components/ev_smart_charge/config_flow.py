"""Config flow for EV Smart Charge."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .charger import zaptec_siblings
from .const import (
    CHARGER_NONE,
    CHARGER_SWITCH,
    CHARGER_TYPES,
    CHARGER_ZAPTEC,
    CONF_BATTERY_ENTITY,
    CONF_CAPACITY,
    CONF_CAR_DEVICE,
    CONF_CAR_PLUGGED_ENTITY,
    CONF_CHARGE_SWITCH,
    CONF_CHARGER_TYPE,
    CONF_NOTIFY_ONLY_HOME,
    CONF_NOTIFY_SERVICES,
    CONF_PRICE_ENTITIES,
    CONF_VEHICLE_MODEL,
    CONF_ZAPTEC_MODE_ENTITY,
    DOMAIN,
    VEHICLE_AUTO,
)
from .plan import parse_price_attributes
from .vehicles import OTHER, VEHICLES

OPTIONAL_ENTITIES = (CONF_ZAPTEC_MODE_ENTITY, CONF_CHARGE_SWITCH, CONF_CAR_PLUGGED_ENTITY, CONF_CAPACITY,
                     CONF_CAR_DEVICE)
VEHICLE_OPTIONS = [
    selector.SelectOptionDict(value=VEHICLE_AUTO, label="Automatic / Automatisk"),
    *(selector.SelectOptionDict(value=vehicle.key, label=f"Tesla {vehicle.name}") for vehicle in VEHICLES),
    selector.SelectOptionDict(value=OTHER, label="Other car / Anden bil"),
]


def car_entities(hass, device_id: str) -> tuple[str | None, str | None, str | None]:
    """The name, battery level sensor and plug sensor of a car's device."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None, None, None
    battery = plug = None
    for entry in er.async_entries_for_device(er.async_get(hass), device_id):
        if entry.disabled_by:
            continue
        device_class = entry.device_class or entry.original_device_class
        if entry.domain == "sensor" and device_class == "battery" and battery is None:
            battery = entry.entity_id
        elif entry.domain == "binary_sensor" and device_class == "plug" and plug is None:
            plug = entry.entity_id
    return device.name_by_user or device.name, battery, plug


def _schema(defaults: dict[str, Any], with_name: bool, phones: list[str] | None = None) -> vol.Schema:
    fields: dict = {}
    if with_name:
        fields[vol.Optional(CONF_NAME, description={"suggested_value": defaults.get(CONF_NAME)})] = str
    fields[vol.Optional(CONF_CAR_DEVICE, description={"suggested_value": defaults.get(CONF_CAR_DEVICE)})] = (
        selector.DeviceSelector(selector.DeviceSelectorConfig(
            entity=[selector.EntityFilterSelectorConfig(domain="sensor", device_class="battery")])))
    fields[vol.Optional(CONF_BATTERY_ENTITY, description={"suggested_value": defaults.get(CONF_BATTERY_ENTITY)})] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")))
    fields[vol.Optional(CONF_CAR_PLUGGED_ENTITY,
                        description={"suggested_value": defaults.get(CONF_CAR_PLUGGED_ENTITY)})] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"])))
    fields[vol.Required(CONF_PRICE_ENTITIES, default=defaults.get(CONF_PRICE_ENTITIES, vol.UNDEFINED))] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor", "binary_sensor"],
                                                              multiple=True)))
    fields[vol.Required(CONF_VEHICLE_MODEL, default=defaults.get(CONF_VEHICLE_MODEL, VEHICLE_AUTO))] = (
        selector.SelectSelector(selector.SelectSelectorConfig(options=VEHICLE_OPTIONS,
                                                              mode=selector.SelectSelectorMode.DROPDOWN)))
    fields[vol.Optional(CONF_CAPACITY, description={"suggested_value": defaults.get(CONF_CAPACITY)})] = (
        selector.NumberSelector(selector.NumberSelectorConfig(
            min=5, max=250, step=0.1, unit_of_measurement="kWh", mode=selector.NumberSelectorMode.BOX)))
    fields[vol.Required(CONF_CHARGER_TYPE, default=defaults.get(CONF_CHARGER_TYPE, CHARGER_NONE))] = (
        selector.SelectSelector(selector.SelectSelectorConfig(
            options=CHARGER_TYPES, translation_key=CONF_CHARGER_TYPE, mode=selector.SelectSelectorMode.LIST)))
    fields[vol.Optional(CONF_ZAPTEC_MODE_ENTITY,
                        description={"suggested_value": defaults.get(CONF_ZAPTEC_MODE_ENTITY)})] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", integration="zaptec")))
    fields[vol.Optional(CONF_CHARGE_SWITCH, description={"suggested_value": defaults.get(CONF_CHARGE_SWITCH)})] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain="switch")))
    options = sorted(set(phones or []) | set(defaults.get(CONF_NOTIFY_SERVICES) or []))
    fields[vol.Optional(CONF_NOTIFY_SERVICES, description={"suggested_value": defaults.get(CONF_NOTIFY_SERVICES)})] = (
        selector.SelectSelector(selector.SelectSelectorConfig(options=options, multiple=True, custom_value=True,
                                                              mode=selector.SelectSelectorMode.DROPDOWN)))
    fields[vol.Optional(CONF_NOTIFY_ONLY_HOME, default=bool(defaults.get(CONF_NOTIFY_ONLY_HOME, False)))] = (
        selector.BooleanSelector())
    return vol.Schema(fields)


def _phones(hass) -> list[str]:
    """Companion app notify services, e.g. mobile_app_my_phone."""
    return sorted(name for name in hass.services.async_services().get("notify", {}) if name.startswith("mobile_app_"))


def _link_car(hass, user_input: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    """Fill the battery and plug sensors (and the name) from the chosen car device. A newly chosen
    car replaces the sensors of the previous one."""
    data = dict(user_input)
    device_id = data.get(CONF_CAR_DEVICE)
    if not device_id:
        return data
    name, battery, plug = car_entities(hass, device_id)
    changed = device_id != previous.get(CONF_CAR_DEVICE)
    if battery and (changed or not data.get(CONF_BATTERY_ENTITY)):
        data[CONF_BATTERY_ENTITY] = battery
    if plug and (changed or not data.get(CONF_CAR_PLUGGED_ENTITY)):
        data[CONF_CAR_PLUGGED_ENTITY] = plug
    if name and CONF_NAME in data and not data[CONF_NAME]:
        data[CONF_NAME] = name
    return data


def _validate(hass, user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not user_input.get(CONF_BATTERY_ENTITY):
        return {CONF_BATTERY_ENTITY: "battery_required"}
    battery = hass.states.get(user_input[CONF_BATTERY_ENTITY])
    try:
        float(battery.state) if battery else None
    except (TypeError, ValueError):
        if battery.state not in ("unknown", "unavailable"):
            errors[CONF_BATTERY_ENTITY] = "not_numeric"
    if not any(
        (state := hass.states.get(entity_id)) and parse_price_attributes(dict(state.attributes))
        for entity_id in user_input[CONF_PRICE_ENTITIES]
    ):
        errors[CONF_PRICE_ENTITIES] = "no_prices"
    kind = user_input.get(CONF_CHARGER_TYPE, CHARGER_NONE)
    if kind == CHARGER_ZAPTEC:
        mode_entity = user_input.get(CONF_ZAPTEC_MODE_ENTITY)
        if not mode_entity:
            errors[CONF_ZAPTEC_MODE_ENTITY] = "required_for_zaptec"
        elif zaptec_siblings(hass, mode_entity)[0] is None:
            errors[CONF_ZAPTEC_MODE_ENTITY] = "zaptec_switch_missing"
    elif kind == CHARGER_SWITCH and not user_input.get(CONF_CHARGE_SWITCH):
        errors[CONF_CHARGE_SWITCH] = "required_for_switch"
    return errors


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    """Optional entity fields the user emptied are dropped, so an old value does not come back."""
    return {key: value for key, value in user_input.items() if key not in OPTIONAL_ENTITIES or value}


class EvSmartChargeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = _link_car(self.hass, {CONF_NAME: "", **user_input}, {})
            errors = _validate(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_BATTERY_ENTITY])
                self._abort_if_unique_id_configured()
                name = user_input.pop(CONF_NAME) or "Smart ladeplan"
                return self.async_create_entry(title=name, data=_clean(user_input))
        return self.async_show_form(step_id="user", data_schema=_schema(user_input or {}, True, _phones(self.hass)),
                                    errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EvSmartChargeOptionsFlow()


class EvSmartChargeOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = dict(self.config_entry.options or self.config_entry.data)
        if user_input is not None:
            user_input = _link_car(self.hass, user_input, current)
            errors = _validate(self.hass, user_input)
            if not errors:
                return self.async_create_entry(data=_clean(user_input))
            current = {key: value for key, value in current.items() if key not in OPTIONAL_ENTITIES}
            current.update(user_input)
        return self.async_show_form(step_id="init", data_schema=_schema(current, False, _phones(self.hass)),
                                    errors=errors)
