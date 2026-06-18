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
    CONF_SCHEDULE_TYPE,
    CONF_CUSTOM_DAYS,
    CONF_WORKDAY_SENSOR,
    DEFAULT_WORKDAY_SENSOR,
    SCHEDULE_EVERYDAY,
    SCHEDULE_WORKDAYS,
    SCHEDULE_WEEKENDS,
    SCHEDULE_CUSTOM,
)

_LOGGER = logging.getLogger(__name__)

class KiSaPlanDayConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for KiSa Plan Day."""

    VERSION = 1

    def __init__(self):
        """Initialize the flow."""
        self._temp_user_data = {}

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            self._temp_user_data = user_input
            if user_input.get(CONF_SCHEDULE_TYPE) == SCHEDULE_CUSTOM:
                return await self.async_step_custom_days_setup()
            
            return self.async_create_entry(title=user_input[CONF_PLAN_NAME], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PLAN_NAME): str,
                    vol.Required(CONF_TIME): selector.TimeSelector(),
                    vol.Required(CONF_SCHEDULE_TYPE, default=SCHEDULE_EVERYDAY): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[SCHEDULE_EVERYDAY, SCHEDULE_WORKDAYS, SCHEDULE_WEEKENDS, SCHEDULE_CUSTOM],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            translation_key="schedule_type",
                        )
                    ),
                    vol.Optional(CONF_WORKDAY_SENSOR, default=DEFAULT_WORKDAY_SENSOR): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="binary_sensor")
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_custom_days_setup(self, user_input=None):
        """Handle custom days setup."""
        if user_input is not None:
            final_data = {**self._temp_user_data, **user_input}
            return self.async_create_entry(title=final_data[CONF_PLAN_NAME], data=final_data)

        return self.async_show_form(
            step_id="custom_days_setup",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CUSTOM_DAYS, default=[]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                            translation_key="custom_days",
                        )
                    ),
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        _LOGGER.error(">>> HA KISA UNI PLAN: async_get_options_flow called for entry %s", config_entry.entry_id)
        try:
            return KiSaPlanDayOptionsFlowHandler(config_entry)
        except Exception as e:
            _LOGGER.error(">>> HA KISA UNI PLAN: CRITICAL ERROR in async_get_options_flow: %s", e, exc_info=True)
            raise


class KiSaPlanDayOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for KiSa Plan Day."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        _LOGGER.error(">>> HA KISA UNI PLAN: Init OptionsFlowHandler")
        try:
            self.entry = config_entry
            self.steps = []
            self.current_edit_index = None
            self._temp_settings = {}
            _LOGGER.error(">>> HA KISA UNI PLAN: OptionsFlowHandler initialized successfully")
        except Exception as e:
            _LOGGER.error(">>> HA KISA UNI PLAN: CRITICAL ERROR in __init__: %s", e, exc_info=True)
            raise

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        _LOGGER.error(">>> HA KISA UNI PLAN: async_step_init started, user_input: %s", user_input)
        try:
            self.steps = list(self.entry.options.get("steps", []))
            
            if user_input is not None:
                action = user_input.get("action")
                _LOGGER.error(">>> HA KISA UNI PLAN: User selected action: %s", action)
                if action == "settings":
                    return await self.async_step_settings()
                elif action == "add_step":
                    return await self.async_step_add_step()
                elif action == "manage_steps":
                    return await self.async_step_manage_steps()
                elif action == "card_info":
                    return await self.async_step_card_info()

            _LOGGER.error(">>> HA KISA UNI PLAN: Showing init form")
            
            action_map = {"turn_on": "Включить", "turn_off": "Выключить", "toggle": "Переключить"}
            summary = ""
            for i, step in enumerate(self.steps):
                ent_id = step.get('entity_id')
                action = step.get('action')
                delay = step.get('delay', 0)
                enabled = step.get('enabled', True)
                
                # Пытаемся получить человеческое имя сущности
                state = self.hass.states.get(ent_id) if ent_id else None
                friendly_name = state.name if state else "Неизвестный объект"
                action_ru = action_map.get(action, action)
                
                status_icon = "✅" if enabled else "❌"
                
                summary += f"{status_icon} **Шаг {i+1}:** {action_ru} **{friendly_name}**\n"
                summary += f"   _{ent_id}_\n"
                if delay > 0:
                    summary += f"   ⏱ Задержка: {delay} сек.\n"
                summary += "\n"

            if not summary:
                summary = "План пока пуст. Добавьте шаги через меню ниже."

            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema(
                    {
                        vol.Required("action", default="settings"): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    {"value": "settings", "label": "⚙️ Общие настройки плана"},
                                    {"value": "add_step", "label": "➕ Добавить новый шаг"},
                                    {"value": "manage_steps", "label": "✏️ Редактировать / Удалить шаги"},
                                    {"value": "card_info", "label": "ℹ️ Инструкция по дашборду"},
                                ],
                                mode=selector.SelectSelectorMode.DROPDOWN,
                            )
                        ),
                    }
                ),
                description_placeholders={
                    "plan_summary": summary,
                    "plan_name": self.entry.title
                }
            )
        except Exception as e:
            _LOGGER.error(">>> HA KISA UNI PLAN: CRITICAL ERROR in async_step_init: %s", e, exc_info=True)
            return self.async_abort(reason="unknown")

    async def async_step_card_info(self, user_input=None):
        """Show dashboard card instructions."""
        if user_input is not None:
            return await self.async_step_init()

        plan_name = self.entry.title
        switch_id = f"switch.{plan_name.lower().replace(' ', '_')}"
        
        yaml_template = """type: markdown
title: План {plan_name}
content: >-
  {% set switch_id = "{switch_id}" %}

  **Статус плана:** {{ states(switch_id) }}


  **Шаги плана:**
  
  {% set ns = namespace(found=false) %}
  {% for state in states.switch if state.entity_id.startswith(switch_id + '_step_') %}
    {% set ns.found = true %}
    - **Шаг {{ state.attributes.order + 1 }}**: {{ state.attributes.action }} -> {{ state.attributes.target_entity }}
      (Задержка: {{ state.attributes.delay }} сек.)
      *Статус шага: {{ state.state }}*
  {% endfor %}

  {% if not ns.found %}
    Шаги пока не добавлены.
  {% endif %}"""

        yaml_code = yaml_template.replace("{plan_name}", plan_name).replace("{switch_id}", switch_id)

        return self.async_show_form(
            step_id="card_info",
            data_schema=vol.Schema({}),
            description_placeholders={"yaml_code": yaml_code}
        )

    async def async_step_settings(self, user_input=None):
        """Manage general settings."""
        try:
            if user_input is not None:
                self._temp_settings = user_input
                if user_input.get(CONF_SCHEDULE_TYPE) == SCHEDULE_CUSTOM:
                    return await self.async_step_custom_days()
                
                return self.async_create_entry(title="", data={**self.entry.options, **user_input, "steps": self.steps})

            cur_time = self.entry.options.get(CONF_TIME, self.entry.data.get(CONF_TIME, "00:00:00"))
            
            legacy_workdays = self.entry.options.get(CONF_WORKDAYS_ONLY, self.entry.data.get(CONF_WORKDAYS_ONLY))
            default_schedule = SCHEDULE_WORKDAYS if legacy_workdays else SCHEDULE_EVERYDAY
            cur_schedule = self.entry.options.get(CONF_SCHEDULE_TYPE, self.entry.data.get(CONF_SCHEDULE_TYPE, default_schedule))

            return self.async_show_form(
                step_id="settings",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_TIME, default=cur_time): selector.TimeSelector(),
                        vol.Required(CONF_SCHEDULE_TYPE, default=cur_schedule): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[SCHEDULE_EVERYDAY, SCHEDULE_WORKDAYS, SCHEDULE_WEEKENDS, SCHEDULE_CUSTOM],
                                mode=selector.SelectSelectorMode.DROPDOWN,
                                translation_key="schedule_type",
                            )
                        ),
                    }
                ),
            )
        except Exception as e:
            _LOGGER.error(">>> HA KISA UNI PLAN: CRITICAL ERROR in async_step_settings: %s", e, exc_info=True)
            return self.async_abort(reason="unknown")

    async def async_step_custom_days(self, user_input=None):
        """Handle custom days selection in options."""
        if user_input is not None:
            final_data = {**self.entry.options, **self._temp_settings, **user_input, "steps": self.steps}
            return self.async_create_entry(title="", data=final_data)

        cur_custom_days = self.entry.options.get(CONF_CUSTOM_DAYS, self.entry.data.get(CONF_CUSTOM_DAYS, []))

        return self.async_show_form(
            step_id="custom_days",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CUSTOM_DAYS, default=cur_custom_days): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                            translation_key="custom_days",
                        )
                    ),
                }
            ),
        )

    async def async_step_add_step(self, user_input=None):
        """Add a new step."""
        try:
            if user_input is not None:
                self.steps.append(user_input)
                return self.async_create_entry(title="", data={**self.entry.options, "steps": self.steps})

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
            _LOGGER.error(">>> HA KISA UNI PLAN: CRITICAL ERROR in async_step_add_step: %s", e, exc_info=True)
            return self.async_abort(reason="unknown")

    async def async_step_manage_steps(self, user_input=None):
        """Show list of steps to manage."""
        try:
            if not self.steps:
                return await self.async_step_init()

            if user_input is not None:
                selected = user_input.get("selected_step")
                if selected == "clear_all":
                    self.steps = []
                    return self.async_create_entry(title="", data={**self.entry.options, "steps": self.steps})
                elif selected is not None:
                    self.current_edit_index = int(selected)
                    return await self.async_step_edit_step()

            options_list = []
            action_map = {"turn_on": "Включить", "turn_off": "Выключить", "toggle": "Переключить"}
            
            for i, step in enumerate(self.steps):
                ent_id = step.get('entity_id')
                state = self.hass.states.get(ent_id) if ent_id else None
                friendly_name = state.name if state else ent_id
                action_ru = action_map.get(step.get('action'), step.get('action'))
                
                label = f"Шаг {i+1}: {friendly_name} ({action_ru})"
                options_list.append({"value": str(i), "label": label})
                
            options_list.append({"value": "clear_all", "label": "🗑️ Удалить все шаги"})

            return self.async_show_form(
                step_id="manage_steps",
                data_schema=vol.Schema(
                    {
                        vol.Required("selected_step"): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=options_list,
                                mode=selector.SelectSelectorMode.DROPDOWN,
                            )
                        ),
                    }
                ),
            )
        except Exception as e:
            _LOGGER.error(">>> HA KISA UNI PLAN: CRITICAL ERROR in async_step_manage_steps: %s", e, exc_info=True)
            return self.async_abort(reason="unknown")

    async def async_step_edit_step(self, user_input=None):
        """Edit or remove a specific step."""
        try:
            if self.current_edit_index is None or self.current_edit_index >= len(self.steps):
                return await self.async_step_init()

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
                    
                    new_index = max(0, min(new_index, len(self.steps)))
                    self.steps.insert(new_index, updated_step)
                    
                return self.async_create_entry(title="", data={**self.entry.options, "steps": self.steps})

            schema = {}
            ent_id = current_step.get("entity_id")
            if ent_id:
                schema[vol.Required("entity_id", default=ent_id)] = selector.EntitySelector()
            else:
                schema[vol.Required("entity_id")] = selector.EntitySelector()

            schema[vol.Required("action", default=current_step.get("action", "turn_on"))] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["turn_on", "turn_off", "toggle"],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
            schema[vol.Required("delay", default=current_step.get("delay", 0))] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=3600, unit_of_measurement="сек")
            )
            schema[vol.Required("enabled", default=current_step.get("enabled", True))] = bool
            
            max_idx = max(0, len(self.steps) - 1)
            if max_idx > 0:
                schema[vol.Required("order", default=self.current_edit_index)] = selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=max_idx, mode=selector.NumberSelectorMode.BOX)
                )
            
            schema[vol.Optional("delete", default=False)] = bool

            return self.async_show_form(
                step_id="edit_step",
                data_schema=vol.Schema(schema),
                description_placeholders={"step_num": str(self.current_edit_index + 1)},
            )
        except Exception as e:
            _LOGGER.error(">>> HA KISA UNI PLAN: CRITICAL ERROR in async_step_edit_step: %s", e, exc_info=True)
            return self.async_abort(reason="unknown")