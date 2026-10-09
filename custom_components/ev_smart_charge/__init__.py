"""EV Smart Charge: charge plans from any electricity price sensor, optionally controlling the charger."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .planner import ChargePlanner

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.DATETIME, Platform.NUMBER, Platform.SELECT,
             Platform.SENSOR, Platform.SWITCH, Platform.TEXT, Platform.TIME]

type EvSmartChargeConfigEntry = ConfigEntry[ChargePlanner]


async def async_setup_entry(hass: HomeAssistant, entry: EvSmartChargeConfigEntry) -> bool:
    planner = ChargePlanner(hass, entry)
    entry.runtime_data = planner
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    planner.async_start()
    entry.async_on_unload(planner.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EvSmartChargeConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: EvSmartChargeConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
