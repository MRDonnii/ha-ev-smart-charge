"""Config flow for EV Smart Charge."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .charger import zaptec_siblings
from .const import (
    CHARGER_NONE,
    CHARGER_SWITCH,
    CHARGER_TYPES,
    CHARGER_ZAPTEC,
    CONF_BATTERY_ENTITY,
    CONF_CAPACITY,
    CONF_CAR_PLUGGED_ENTITY,
    CONF_CHARGE_SWITCH,
    CONF_CHARGER_TYPE,
    CONF_PRICE_ENTITIES,
    CONF_ZAPTEC_MODE_ENTITY,
    DEFAULT_CAPACITY,
    DOMAIN,
)
from .plan import parse_price_attributes

OPTIONAL_ENTITIES = (CONF_ZAPTEC_MODE_ENTITY, CONF_CHARGE_SWITCH, CONF_CAR_PLUGGED_ENTITY)


def _schema(defaults: dict[str, Any], with_name: bool) -> vol.Schema:
    fields: dict = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "Smart ladeplan"))] = str
    fields[vol.Required(CONF_BATTERY_ENTITY, default=defaults.get(CONF_BATTERY_ENTITY, vol.UNDEFINED))] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")))
    fields[vol.Required(CONF_PRICE_ENTITIES, default=defaults.get(CONF_PRICE_ENTITIES, vol.UNDEFINED))] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor", "binary_sensor"],
                                                              multiple=True)))
    fields[vol.Required(CONF_CAPACITY, default=defaults.get(CONF_CAPACITY, DEFAULT_CAPACITY))] = (
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
    fields[vol.Optional(CONF_CAR_PLUGGED_ENTITY,
                        description={"suggested_value": defaults.get(CONF_CAR_PLUGGED_ENTITY)})] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"])))
    return vol.Schema(fields)


def _validate(hass, user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
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
            errors = _validate(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_BATTERY_ENTITY])
                self._abort_if_unique_id_configured()
                name = user_input.pop(CONF_NAME)
                return self.async_create_entry(title=name, data=_clean(user_input))
        return self.async_show_form(step_id="user", data_schema=_schema(user_input or {}, True),
                                    errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EvSmartChargeOptionsFlow()


class EvSmartChargeOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(self.hass, user_input)
            if not errors:
                return self.async_create_entry(data=_clean(user_input))
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            current = {key: value for key, value in current.items() if key not in OPTIONAL_ENTITIES}
            current.update(user_input)
        return self.async_show_form(step_id="init", data_schema=_schema(current, False), errors=errors)
