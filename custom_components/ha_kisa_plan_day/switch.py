"""Switch platform for KiSa Plan Day."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.restore_state import RestoreEntity
import homeassistant.util.dt as dt_util
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN,
    CONF_TIME,
    CONF_WORKDAYS_ONLY,
    CONF_WORKDAY_SENSOR,
    CONF_STEPS,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the KiSa Plan Day switch."""
    entities = [KiSaPlanDaySwitch(hass, config_entry)]
    
    # Add child switches for each step
    steps = config_entry.options.get("steps", [])
    for index, step in enumerate(steps):
        entities.append(KiSaPlanStepSwitch(hass, config_entry, index, step))
        
    async_add_entities(entities, True)


class KiSaPlanDaySwitch(SwitchEntity, RestoreEntity):
    """Representation of a KiSa Plan Day switch."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the switch."""
        self.hass = hass
        self.config_entry = config_entry
        self._attr_name = config_entry.title
        self._attr_unique_id = config_entry.entry_id
        self._attr_is_on = True
        self._attr_icon = "mdi:calendar-check"
        self._unsub_timer = None
        self._routine_task = None

    @property
    def extra_state_attributes(self):
        """Return entity specific state attributes."""
        options = self.config_entry.options
        data = self.config_entry.data
        return {
            "start_time": options.get(CONF_TIME, data.get(CONF_TIME)),
            "workdays_only": options.get(CONF_WORKDAYS_ONLY, data.get(CONF_WORKDAYS_ONLY)),
            "steps_count": len(options.get("steps", [])),
        }

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"

        self._setup_timer()

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity which will be removed."""
        if self._unsub_timer:
            self._unsub_timer()
        if self._routine_task:
            self._routine_task.cancel()
        await super().async_will_remove_from_hass()

    def _setup_timer(self):
        """Set up the daily timer."""
        if self._unsub_timer:
            self._unsub_timer()

        options = self.config_entry.options
        data = self.config_entry.data
        time_str = options.get(CONF_TIME, data.get(CONF_TIME))
        
        parsed_time = dt_util.parse_time(time_str)
        if parsed_time is None:
            _LOGGER.error("Invalid time format: %s", time_str)
            return

        self._unsub_timer = async_track_time_change(
            self.hass, self._handle_timer_fire, hour=parsed_time.hour, minute=parsed_time.minute, second=parsed_time.second
        )
        _LOGGER.debug("Timer set for %02d:%02d:%02d", parsed_time.hour, parsed_time.minute, parsed_time.second)

    @callback
    async def _handle_timer_fire(self, _now: datetime) -> None:
        """Handle the timer firing."""
        if not self._attr_is_on:
            _LOGGER.debug("Plan %s is disabled, skipping", self.name)
            return

        options = self.config_entry.options
        data = self.config_entry.data
        
        workdays_only = options.get(CONF_WORKDAYS_ONLY, data.get(CONF_WORKDAYS_ONLY))
        if workdays_only:
            workday_sensor = data.get(CONF_WORKDAY_SENSOR, self.config_entry.options.get(CONF_WORKDAY_SENSOR, "binary_sensor.workday_sensor"))
            state = self.hass.states.get(workday_sensor)
            if state and state.state != "on":
                _LOGGER.debug("Not a workday according to %s, skipping", workday_sensor)
                return

        _LOGGER.info("Starting routine: %s", self.name)
        if self._routine_task and not self._routine_task.done():
            self._routine_task.cancel()
        self._routine_task = self.hass.async_create_task(self._run_routine())

    async def _run_routine(self):
        """Run the steps of the routine."""
        try:
            steps = self.config_entry.options.get("steps", [])
            for index, step in enumerate(steps):
                if not self._attr_is_on:
                    _LOGGER.info("Routine %s interrupted (switch turned off)", self.name)
                    break
                
                # Check child switch state
                child_switch_id = f"switch.{self.config_entry.title.lower().replace(' ', '_')}_step_{index}"
                child_state = self.hass.states.get(child_switch_id)
                
                # Fallback to step config if entity doesn't exist yet
                is_step_enabled = True
                if child_state:
                    is_step_enabled = child_state.state == "on"
                else:
                    is_step_enabled = step.get("enabled", True)

                if not is_step_enabled:
                    _LOGGER.debug("Step %s is disabled, skipping", index)
                    continue

                entity_id = step.get("entity_id")
                action = step.get("action", "turn_on")
                delay = step.get("delay", 0)

                if delay > 0:
                    _LOGGER.debug("Waiting %s seconds before next step", delay)
                    await asyncio.sleep(delay)
                    
                    # Check again after sleep
                    if not self._attr_is_on:
                        _LOGGER.info("Routine %s interrupted after delay (switch turned off)", self.name)
                        break

                domain = entity_id.split(".")[0]
                # Map simple actions to service names
                service = action
                
                _LOGGER.info("Executing step: %s %s on %s", domain, service, entity_id)
                await self.hass.services.async_call(
                    domain, service, {"entity_id": entity_id}, blocking=True
                )
        except asyncio.CancelledError:
            _LOGGER.info("Routine %s was cancelled", self.name)
            raise

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the plan on."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the plan off."""
        self._attr_is_on = False
        if self._routine_task and not self._routine_task.done():
            self._routine_task.cancel()
        self.async_write_ha_state()


class KiSaPlanStepSwitch(SwitchEntity, RestoreEntity):
    """Representation of a child step switch."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, index: int, step_config: dict[str, Any]) -> None:
        """Initialize the child switch."""
        self.hass = hass
        self.config_entry = config_entry
        self.index = index
        self.step_config = step_config
        
        plan_name = config_entry.title
        target_entity = step_config.get("entity_id", "unknown")
        
        self._attr_name = f"{plan_name} Step {index} ({target_entity})"
        self._attr_unique_id = f"{config_entry.entry_id}_step_{index}"
        self._attr_is_on = step_config.get("enabled", True)
        self._attr_icon = "mdi:format-list-checks"

    @property
    def extra_state_attributes(self):
        """Return entity specific state attributes."""
        return {
            "target_entity": self.step_config.get("entity_id"),
            "action": self.step_config.get("action"),
            "delay": self.step_config.get("delay"),
            "order": self.index,
        }

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the step on."""
        self._attr_is_on = True
        self._update_config_entry_options()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the step off."""
        self._attr_is_on = False
        self._update_config_entry_options()
        self.async_write_ha_state()
        
    def _update_config_entry_options(self):
        """Update the enabled state in the config entry options."""
        options = dict(self.config_entry.options)
        steps = list(options.get("steps", []))
        if self.index < len(steps):
            step = dict(steps[self.index])
            step["enabled"] = self._attr_is_on
            steps[self.index] = step
            options["steps"] = steps
            
            self.hass.config_entries.async_update_entry(
                self.config_entry, options=options
            )
