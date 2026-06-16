"""Config flow for KiSa Plan Day integration."""
from __future__ import annotations

import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_PLAN_NAME,
    CONF_TIME,
    CONF_WORKDAYS_ONLY,
    CONF_WORKDAY_SENSOR,
    DEFAULT_WORKDAY_SENSOR,
)

_LOGGER = logging.getLogger(__name__)

class KiSaPlanDayConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for KiSa Plan Day."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_PLAN_NAME], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PLAN_NAME): str,
                    vol.Required(CONF_TIME): selector.TimeSelector(),
                    vol.Optional(CONF_WORKDAYS_ONLY, default=False): bool,
                    vol.Optional(CONF_WORKDAY_SENSOR, default=DEFAULT_WORKDAY_SENSOR): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="binary_sensor")
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return KiSaPlanDayOptionsFlowHandler(config_entry)


class KiSaPlanDayOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for KiSa Plan Day."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry
        # Храним шаги в экземпляре на время одной сессии
        self.steps = []
        self.current_edit_index = None

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        try:
            _LOGGER.debug("Init Options Flow for: %s", self.config_entry.title)
            # Инициализируем шаги при первом запуске
            self.steps = list(self.config_entry.options.get("steps", []))
            return await self.async_step_menu()
        except Exception as e:
            _LOGGER.exception("Error in async_step_init: %s", e)
            return self.async_abort(reason="unknown")

    async def async_step_menu(self, user_input=None):
        """Show menu for options."""
        try:
            menu_options = {
                "add_step": "Добавить шаг",
                "manage_steps": "Управление шагами",
                "settings": "Общие настройки",
            }
            return self.async_show_menu(
                step_id="menu",
                menu_options=menu_options,
            )
        except Exception as e:
            _LOGGER.exception("Error in async_step_menu: %s", e)
            return self.async_abort(reason="unknown")

    async def async_step_settings(self, user_input=None):
        """Manage general settings."""
        try:
            if user_input is not None:
                return self.async_create_entry(title="", data={**self.config_entry.options, **user_input, "steps": self.steps})

            return self.async_show_form(
                step_id="settings",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_TIME, default=self.config_entry.options.get(CONF_TIME, self.config_entry.data.get(CONF_TIME))): selector.TimeSelector(),
                        vol.Optional(CONF_WORKDAYS_ONLY, default=self.config_entry.options.get(CONF_WORKDAYS_ONLY, self.config_entry.data.get(CONF_WORKDAYS_ONLY))): bool,
                    }
                ),
            )
        except Exception as e:
            _LOGGER.exception("Error in async_step_settings: %s", e)
            return self.async_abort(reason="unknown")

    async def async_step_add_step(self, user_input=None):
        """Add a new step."""
        try:
            if user_input is not None:
                self.steps.append(user_input)
                return self.async_create_entry(title="", data={**self.config_entry.options, "steps": self.steps})

            return self.async_show_form(
                step_id="add_step",
                data_schema=vol.Schema(
                    {
                        vol.Required("entity_id"): selector.EntitySelector(),
                        vol.Required("action", default="turn_on"): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=["turn_on", "turn_off", "toggle"],
                                mode=selector.SelectSelectorMode.DROPDOWN,
                            )
                        ),
                        vol.Required("delay", default=0): selector.NumberSelector(
                            selector.NumberSelectorConfig(min=0, max=3600, unit_of_measurement="сек")
                        ),
                        vol.Required("enabled", default=True): bool,
                    }
                ),
            )
        except Exception as e:
            _LOGGER.exception("Error in async_step_add_step: %s", e)
            return self.async_abort(reason="unknown")

    async def async_step_manage_steps(self, user_input=None):
        """Show list of steps to manage."""
        try:
            if not self.steps:
                return await self.async_step_menu()

            if user_input is not None:
                selected = user_input.get("selected_step")
                if selected == "clear_all":
                    self.steps = []
                    return self.async_create_entry(title="", data={**self.config_entry.options, "steps": self.steps})
                elif selected is not None:
                    self.current_edit_index = int(selected)
                    return await self.async_step_edit_step()

            options = {str(i): f"Шаг {i+1}: {step.get('entity_id')} ({step.get('action')})" for i, step in enumerate(self.steps)}
            options["clear_all"] = "Удалить все шаги"

            return self.async_show_form(
                step_id="manage_steps",
                data_schema=vol.Schema(
                    {
                        vol.Required("selected_step"): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[{"value": k, "label": v} for k, v in options.items()],
                                mode=selector.SelectSelectorMode.DROPDOWN,
                            )
                        ),
                    }
                ),
            )
        except Exception as e:
            _LOGGER.exception("Error in async_step_manage_steps: %s", e)
            return self.async_abort(reason="unknown")

    async def async_step_edit_step(self, user_input=None):
        """Edit or remove a specific step."""
        try:
            if self.current_edit_index is None or self.current_edit_index >= len(self.steps):
                return await self.async_step_menu()

            current_step = self.steps[self.current_edit_index]

            if user_input is not None:
                if user_input.get("delete"):
                    self.steps.pop(self.current_edit_index)
                else:
                    new_index = int(user_input.get("order", self.current_edit_index))
                    
                    updated_step = {
                        "entity_id": user_input["entity_id"],
                        "action": user_input["action"],
                        "delay": user_input["delay"],
                        "enabled": user_input["enabled"],
                    }
                    
                    self.steps.pop(self.current_edit_index)
                    
                    # Insert at new index, clamped to valid range
                    new_index = max(0, min(new_index, len(self.steps)))
                    self.steps.insert(new_index, updated_step)
                    
                return self.async_create_entry(title="", data={**self.config_entry.options, "steps": self.steps})

            return self.async_show_form(
                step_id="edit_step",
                data_schema=vol.Schema(
                    {
                        vol.Required("entity_id", default=current_step.get("entity_id")): selector.EntitySelector(),
                        vol.Required("action", default=current_step.get("action", "turn_on")): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=["turn_on", "turn_off", "toggle"],
                                mode=selector.SelectSelectorMode.DROPDOWN,
                            )
                        ),
                        vol.Required("delay", default=current_step.get("delay", 0)): selector.NumberSelector(
                            selector.NumberSelectorConfig(min=0, max=3600, unit_of_measurement="сек")
                        ),
                        vol.Required("enabled", default=current_step.get("enabled", True)): bool,
                        vol.Required("order", default=self.current_edit_index): selector.NumberSelector(
                            selector.NumberSelectorConfig(min=0, max=max(0, len(self.steps) - 1), mode=selector.NumberSelectorMode.BOX)
                        ),
                        vol.Optional("delete", default=False): bool,
                    }
                ),
                description_placeholder={"step_num": str(self.current_edit_index + 1)},
            )
        except Exception as e:
            _LOGGER.exception("Error in async_step_edit_step: %s", e)
            return self.async_abort(reason="unknown")
