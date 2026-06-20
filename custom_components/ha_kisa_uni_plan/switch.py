"""Switch platform for KiSa Plan Day."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.restore_state import RestoreEntity
import homeassistant.util.dt as dt_util

from .const import (
    CONF_CUSTOM_DAYS,
    CONF_SCHEDULE_TYPE,
    CONF_STEPS,
    CONF_TIME,
    CONF_WORKDAY_SENSOR,
    CONF_WORKDAYS_ONLY,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the KiSa Plan Day switches."""
    main_switch = KiSaPlanDaySwitch(hass, config_entry)
    entities: list[SwitchEntity] = [main_switch]

    # Store a reference so HA services can reach the switch directly
    if DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]:
        hass.data[DOMAIN][config_entry.entry_id]["main_switch"] = main_switch

    # Create one child switch per step
    steps: list[dict[str, Any]] = config_entry.options.get(CONF_STEPS, [])
    for index, step in enumerate(steps):
        entities.append(KiSaPlanStepSwitch(hass, config_entry, index, step))

    async_add_entities(entities, True)


# ---------------------------------------------------------------------------
# Main plan switch
# ---------------------------------------------------------------------------

class KiSaPlanDaySwitch(SwitchEntity, RestoreEntity):
    """Master switch that schedules and runs a plan's step sequence."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the switch."""
        self.hass = hass
        self.config_entry = config_entry
        self._attr_name = config_entry.title
        self._attr_unique_id = config_entry.entry_id
        self._attr_is_on = True
        self._attr_icon = "mdi:calendar-check"
        self._unsub_timer: Any = None
        self._routine_task: asyncio.Task[None] | None = None
        # History tracking
        self._last_run: datetime | None = None
        self._last_run_status: str = "never"   # never | running | completed | interrupted | skipped

    # ------------------------------------------------------------------
    # Device grouping
    # ------------------------------------------------------------------

    @property
    def device_info(self) -> DeviceInfo:
        """Group all plan entities under a single HA device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.config_entry.entry_id)},
            name=self.config_entry.title,
            manufacturer="KiSa",
            model="Uni Plan",
            entry_type=DeviceEntryType.SERVICE,
        )

    # ------------------------------------------------------------------
    # State attributes
    # ------------------------------------------------------------------

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        options = self.config_entry.options
        data = self.config_entry.data
        time_str: str | None = options.get(CONF_TIME, data.get(CONF_TIME))

        # Next scheduled run (always tomorrow if today's time has passed)
        next_run: str | None = None
        if time_str:
            parsed = dt_util.parse_time(time_str)
            if parsed:
                now = dt_util.now()
                candidate = now.replace(
                    hour=parsed.hour,
                    minute=parsed.minute,
                    second=0,
                    microsecond=0,
                )
                if candidate <= now:
                    candidate += timedelta(days=1)
                next_run = candidate.isoformat()

        return {
            "start_time": time_str,
            "schedule_type": options.get(
                CONF_SCHEDULE_TYPE,
                data.get(CONF_SCHEDULE_TYPE, "everyday"),
            ),
            "steps_count": len(options.get(CONF_STEPS, [])),
            "is_running": (
                self._routine_task is not None and not self._routine_task.done()
            ),
            "next_run": next_run,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "last_run_status": self._last_run_status,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Restore state and arm the timer when HA starts."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"

        self._setup_timer()

    async def async_will_remove_from_hass(self) -> None:
        """Clean up timer and cancel any running task."""
        if self._unsub_timer:
            self._unsub_timer()
        await self._cancel_task_safe()
        await super().async_will_remove_from_hass()

    # ------------------------------------------------------------------
    # Timer setup
    # ------------------------------------------------------------------

    def _setup_timer(self) -> None:
        """Arm (or re-arm) the daily timer."""
        if self._unsub_timer:
            self._unsub_timer()

        options = self.config_entry.options
        data = self.config_entry.data
        time_str: str | None = options.get(CONF_TIME, data.get(CONF_TIME))

        parsed_time = dt_util.parse_time(time_str) if time_str else None
        if parsed_time is None:
            _LOGGER.error("Invalid or missing time value: %r", time_str)
            return

        self._unsub_timer = async_track_time_change(
            self.hass,
            self._handle_timer_fire,
            hour=parsed_time.hour,
            minute=parsed_time.minute,
            second=parsed_time.second,
        )
        _LOGGER.debug(
            "Timer armed for %02d:%02d:%02d",
            parsed_time.hour,
            parsed_time.minute,
            parsed_time.second,
        )

    # ------------------------------------------------------------------
    # Timer callback — must be a plain @callback (sync), not async
    # ------------------------------------------------------------------

    @callback
    def _handle_timer_fire(self, _now: datetime) -> None:
        """Sync entry-point: schedule check & routine start are handled async."""
        self.hass.async_create_task(self._async_handle_timer(_now))

    async def _async_handle_timer(self, _now: datetime) -> None:
        """Evaluate schedule and launch the routine if applicable."""
        if not self._attr_is_on:
            _LOGGER.debug("Plan '%s' is disabled — skipping", self.name)
            return

        options = self.config_entry.options
        data = self.config_entry.data

        # Legacy: CONF_WORKDAYS_ONLY → map to schedule_type
        legacy_workdays = options.get(CONF_WORKDAYS_ONLY, data.get(CONF_WORKDAYS_ONLY))
        default_schedule = "workdays" if legacy_workdays else "everyday"
        schedule_type: str = options.get(
            CONF_SCHEDULE_TYPE, data.get(CONF_SCHEDULE_TYPE, default_schedule)
        )

        if schedule_type != "everyday":
            workday_sensor: str = options.get(
                CONF_WORKDAY_SENSOR,
                data.get(CONF_WORKDAY_SENSOR, "binary_sensor.workday_sensor"),
            )
            sensor_state = self.hass.states.get(workday_sensor)
            is_workday = sensor_state is not None and sensor_state.state == "on"

            if schedule_type == "workdays" and not is_workday:
                _LOGGER.debug("'%s': not a workday — skipping", self.name)
                self._last_run_status = "skipped"
                self.async_write_ha_state()
                return

            if schedule_type == "weekends" and is_workday:
                _LOGGER.debug("'%s': is a workday — skipping weekend schedule", self.name)
                self._last_run_status = "skipped"
                self.async_write_ha_state()
                return

            if schedule_type == "custom":
                custom_days: list[str] = options.get(
                    CONF_CUSTOM_DAYS, data.get(CONF_CUSTOM_DAYS, [])
                )
                weekdays_map = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
                today_str = weekdays_map[_now.weekday()]
                if today_str not in custom_days:
                    _LOGGER.debug(
                        "'%s': today (%s) not in custom days %s — skipping",
                        self.name, today_str, custom_days,
                    )
                    self._last_run_status = "skipped"
                    self.async_write_ha_state()
                    return

        _LOGGER.info("Starting routine: '%s'", self.name)
        await self._cancel_task_safe()
        self._routine_task = self.hass.async_create_task(self._run_routine())

    # ------------------------------------------------------------------
    # Public API for HA services
    # ------------------------------------------------------------------

    async def async_run_now(self) -> None:
        """Start the routine immediately (used by ha_kisa_uni_plan.run_now service)."""
        if not self._attr_is_on:
            _LOGGER.warning("'%s' is disabled — cannot run on demand", self.name)
            return
        if self._routine_task and not self._routine_task.done():
            _LOGGER.warning("'%s' is already running", self.name)
            return
        _LOGGER.info("Running '%s' on demand", self.name)
        self._routine_task = self.hass.async_create_task(self._run_routine())

    async def async_cancel_run(self) -> None:
        """Cancel the running routine (used by ha_kisa_uni_plan.cancel_run service)."""
        if self._routine_task and not self._routine_task.done():
            _LOGGER.info("Cancelling routine: '%s'", self.name)
            await self._cancel_task_safe()
        else:
            _LOGGER.debug("'%s' is not currently running", self.name)

    # ------------------------------------------------------------------
    # Routine execution
    # ------------------------------------------------------------------

    async def _run_routine(self) -> None:
        """Execute the step sequence."""
        self._last_run = dt_util.now()
        self._last_run_status = "running"
        self.async_write_ha_state()

        all_steps_done = False
        try:
            steps: list[dict[str, Any]] = self.config_entry.options.get(CONF_STEPS, [])
            # Step enabled/disabled states live in hass.data — no entity_id lookup needed
            step_states: dict[int, bool] = (
                self.hass.data
                .get(DOMAIN, {})
                .get(self.config_entry.entry_id, {})
                .get("step_states", {})
            )

            for index, step in enumerate(steps):
                # Stop if main switch was turned off during execution
                if not self._attr_is_on:
                    _LOGGER.info("'%s': interrupted at step %s (switch off)", self.name, index)
                    break

                # Check per-step enabled state (hass.data takes priority over config)
                is_step_enabled: bool = step_states.get(index, step.get("enabled", True))
                if not is_step_enabled:
                    _LOGGER.debug("Step %s disabled — skipping", index)
                    continue

                entity_id: str | None = step.get("entity_id")
                if not entity_id:
                    _LOGGER.warning("Step %s has no entity_id — skipping", index)
                    continue

                action: str = step.get("action", "turn_on")
                delay: float = float(step.get("delay", 0))

                if delay > 0:
                    _LOGGER.debug("Step %s: waiting %.1f s", index, delay)
                    await asyncio.sleep(delay)
                    # Re-check after sleep
                    if not self._attr_is_on:
                        _LOGGER.info(
                            "'%s': interrupted after delay at step %s", self.name, index
                        )
                        break

                service_domain = entity_id.split(".")[0]
                _LOGGER.info(
                    "Step %s: %s.%s → %s", index, service_domain, action, entity_id
                )
                await self.hass.services.async_call(
                    service_domain,
                    action,
                    {"entity_id": entity_id},
                    blocking=True,
                )
            else:
                # for…else: executes only when loop wasn't broken
                all_steps_done = True

            self._last_run_status = "completed" if all_steps_done else "interrupted"

        except asyncio.CancelledError:
            self._last_run_status = "interrupted"
            _LOGGER.info("'%s': routine cancelled", self.name)
            raise
        finally:
            self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Switch control
    # ------------------------------------------------------------------

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the plan."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the plan and interrupt any running routine."""
        self._attr_is_on = False
        await self._cancel_task_safe()
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _cancel_task_safe(self) -> None:
        """Cancel the routine task and await it to ensure clean shutdown."""
        if self._routine_task and not self._routine_task.done():
            self._routine_task.cancel()
            try:
                await self._routine_task
            except asyncio.CancelledError:
                pass


# ---------------------------------------------------------------------------
# Per-step child switch
# ---------------------------------------------------------------------------

class KiSaPlanStepSwitch(SwitchEntity, RestoreEntity):
    """Child switch that enables/disables a single step of the plan."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        index: int,
        step_config: dict[str, Any],
    ) -> None:
        """Initialize the step switch."""
        self.hass = hass
        self.config_entry = config_entry
        self.index = index
        self.step_config = step_config

        plan_name = config_entry.title
        target_entity: str = step_config.get("entity_id", "")

        # Build a short, human-readable display name
        if target_entity:
            friendly_target = target_entity.split(".")[-1].replace("_", " ").title()
        else:
            friendly_target = "Unknown"

        self._attr_name = f"{plan_name}: Шаг {index + 1} — {friendly_target}"
        self._attr_unique_id = f"{config_entry.entry_id}_step_{index}"
        self._attr_is_on = step_config.get("enabled", True)
        self._attr_icon = "mdi:format-list-checks"

    @property
    def device_info(self) -> DeviceInfo:
        """Belong to the same device as the master switch."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.config_entry.entry_id)},
            name=self.config_entry.title,
            manufacturer="KiSa",
            model="Uni Plan",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return step metadata."""
        return {
            "target_entity": self.step_config.get("entity_id"),
            "action": self.step_config.get("action"),
            "delay": self.step_config.get("delay"),
            "order": self.index,
        }

    async def async_added_to_hass(self) -> None:
        """Restore last known state and sync it into hass.data."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"

        # Populate hass.data so _run_routine can read enabled state immediately
        self._save_state_to_hass_data()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable this step."""
        self._attr_is_on = True
        self._save_state_to_hass_data()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable this step (skipped during next routine run)."""
        self._attr_is_on = False
        self._save_state_to_hass_data()
        self.async_write_ha_state()

    def _save_state_to_hass_data(self) -> None:
        """Write enabled state to hass.data — no config_entry update, no reload."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        if entry_data is not None:
            entry_data.setdefault("step_states", {})[self.index] = self._attr_is_on
