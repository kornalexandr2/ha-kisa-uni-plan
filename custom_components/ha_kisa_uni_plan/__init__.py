"""The KiSa Plan Day integration."""
from __future__ import annotations

import logging
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["switch"]


def _register_services(hass: HomeAssistant) -> None:
    """Register domain-level services (called once when the first entry loads)."""

    async def handle_run_now(call: ServiceCall) -> None:
        """Immediately run a plan's routine, ignoring the schedule."""
        entry_id: str = call.data["entry_id"]
        entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
        if not entry_data:
            _LOGGER.error("ha_kisa_uni_plan.run_now: plan '%s' not found", entry_id)
            return
        switch = entry_data.get("main_switch")
        if switch is not None:
            await switch.async_run_now()

    async def handle_cancel_run(call: ServiceCall) -> None:
        """Cancel the currently running plan routine."""
        entry_id: str = call.data["entry_id"]
        entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
        if not entry_data:
            _LOGGER.error("ha_kisa_uni_plan.cancel_run: plan '%s' not found", entry_id)
            return
        switch = entry_data.get("main_switch")
        if switch is not None:
            await switch.async_cancel_run()

    hass.services.async_register(
        DOMAIN,
        "run_now",
        handle_run_now,
        schema=vol.Schema({vol.Required("entry_id"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        "cancel_run",
        handle_cancel_run,
        schema=vol.Schema({vol.Required("entry_id"): cv.string}),
    )
    _LOGGER.debug("Registered services: run_now, cancel_run")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up KiSa Plan Day from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Per-entry runtime storage:
    #   step_states: {step_index: bool} — live enabled/disabled state for each step.
    #   main_switch: reference to KiSaPlanDaySwitch for service calls.
    hass.data[DOMAIN][entry.entry_id] = {
        "step_states": {},
        "main_switch": None,
    }

    # Forward to the switch platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # React to options changes
    entry.async_on_unload(entry.add_update_listener(update_listener))

    # Register HA services once for the whole domain
    if not hass.services.has_service(DOMAIN, "run_now"):
        _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

        # Remove services when the last entry is gone
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "run_now")
            hass.services.async_remove(DOMAIN, "cancel_run")
            _LOGGER.debug("Removed services: run_now, cancel_run")

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — triggered only by OptionsFlow, not by step-switch toggles."""
    await hass.config_entries.async_reload(entry.entry_id)
