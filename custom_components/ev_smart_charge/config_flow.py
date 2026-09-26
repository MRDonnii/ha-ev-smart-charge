"""Config flow for EV Smart Charge."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_ENTITY,
    CONF_CAPACITY,
    CONF_PRICE_ENTITIES,
    DEFAULT_CAPACITY,
    DOMAIN,
)
from .plan import parse_price_attributes


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
    return errors


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
                return self.async_create_entry(title=name, data=user_input)
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
                return self.async_create_entry(data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options, **(user_input or {})}
        return self.async_show_form(step_id="init", data_schema=_schema(current, False), errors=errors)
