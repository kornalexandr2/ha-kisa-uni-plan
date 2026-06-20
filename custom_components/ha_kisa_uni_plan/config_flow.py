"""Config flow for KiSa Plan Day integration."""
from __future__ import annotations

import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CUSTOM_DAYS,
    CONF_PLAN_NAME,
    CONF_SCHEDULE_TYPE,
    CONF_STEPS,
    CONF_TIME,
    CONF_WORKDAY_SENSOR,
    CONF_WORKDAYS_ONLY,
    DEFAULT_WORKDAY_SENSOR,
    DOMAIN,
    SCHEDULE_CUSTOM,
    SCHEDULE_EVERYDAY,
    SCHEDULE_WEEKENDS,
    SCHEDULE_WORKDAYS,
)

_LOGGER = logging.getLogger(__name__)


class KiSaPlanDayConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for KiSa Plan Day."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._temp_user_data: dict = {}

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._temp_user_data = user_input
            if user_input.get(CONF_SCHEDULE_TYPE) == SCHEDULE_CUSTOM:
                return await self.async_step_custom_days_setup()
            return self.async_create_entry(
                title=user_input[CONF_PLAN_NAME], data=user_input
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PLAN_NAME): str,
                    vol.Required(CONF_TIME): selector.TimeSelector(),
                    vol.Required(
                        CONF_SCHEDULE_TYPE, default=SCHEDULE_EVERYDAY
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                SCHEDULE_EVERYDAY,
                                SCHEDULE_WORKDAYS,
                                SCHEDULE_WEEKENDS,
                                SCHEDULE_CUSTOM,
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            translation_key="schedule_type",
                        )
                    ),
                    vol.Optional(
                        CONF_WORKDAY_SENSOR, default=DEFAULT_WORKDAY_SENSOR
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="binary_sensor")
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_custom_days_setup(self, user_input=None):
        """Second step: pick custom weekdays."""
        if user_input is not None:
            final_data = {**self._temp_user_data, **user_input}
            return self.async_create_entry(
                title=final_data[CONF_PLAN_NAME], data=final_data
            )

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
        """Return the options flow handler."""
        return KiSaPlanDayOptionsFlowHandler(config_entry)


# ---------------------------------------------------------------------------
# Options Flow
# ---------------------------------------------------------------------------

class KiSaPlanDayOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for KiSa Plan Day."""

    def __init__(self, config_entry) -> None:
        """Initialize options flow."""
        self.entry = config_entry
        self.steps: list[dict] = []
        self.current_edit_index: int | None = None
        self._temp_settings: dict = {}

    async def async_step_init(self, user_input=None):
        """Main menu — show plan summary and action selector."""
        try:
            self.steps = list(self.entry.options.get(CONF_STEPS, []))

            if user_input is not None:
                action = user_input.get("action")
                _LOGGER.debug("Options menu action: %s", action)
                if action == "settings":
                    return await self.async_step_settings()
                if action == "add_step":
                    return await self.async_step_add_step()
                if action == "manage_steps":
                    return await self.async_step_manage_steps()
                if action == "card_info":
                    return await self.async_step_card_info()

            action_map = {
                "turn_on": "Включить",
                "turn_off": "Выключить",
                "toggle": "Переключить",
            }
            summary = ""
            for i, step in enumerate(self.steps):
                ent_id = step.get("entity_id")
                step_action = step.get("action")
                delay = step.get("delay", 0)
                enabled = step.get("enabled", True)

                state = self.hass.states.get(ent_id) if ent_id else None
                friendly_name = state.name if state else "Неизвестный объект"
                action_ru = action_map.get(step_action, step_action)
                status_icon = "✅" if enabled else "❌"

                summary += f"{status_icon} **Шаг {i + 1}:** {action_ru} **{friendly_name}**\n"
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
                                    {"value": "settings",      "label": "⚙️ Общие настройки плана"},
                                    {"value": "add_step",      "label": "➕ Добавить новый шаг"},
                                    {"value": "manage_steps",  "label": "✏️ Редактировать / Удалить шаги"},
                                    {"value": "card_info",     "label": "ℹ️ Инструкция по дашборду"},
                                ],
                                mode=selector.SelectSelectorMode.DROPDOWN,
                            )
                        ),
                    }
                ),
                description_placeholders={
                    "plan_summary": summary,
                    "plan_name": self.entry.title,
                },
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Error in options init step: %s", exc, exc_info=True)
            return self.async_abort(reason="unknown")

    async def async_step_card_info(self, user_input=None):
        """Show a ready-made Markdown card YAML for the dashboard."""
        if user_input is not None:
            return await self.async_step_init()

        plan_name = self.entry.title
        switch_id = f"switch.{plan_name.lower().replace(' ', '_')}"

        yaml_template = (
            "type: markdown\n"
            f"title: План {plan_name}\n"
            "content: >-\n"
            f'  {{% set switch_id = "{switch_id}" %}}\n\n'
            "  **Статус плана:** {{ states(switch_id) }}\n\n\n"
            "  **Шаги плана:**\n\n"
            "  {% set ns = namespace(found=false) %}\n"
            "  {% for state in states.switch if state.entity_id.startswith(switch_id + '_step_') %}\n"
            "    {% set ns.found = true %}\n"
            "    - **Шаг {{ state.attributes.order + 1 }}**: "
            "{{ state.attributes.action }} -> {{ state.attributes.target_entity }}\n"
            "      (Задержка: {{ state.attributes.delay }} сек.)\n"
            "      *Статус шага: {{ state.state }}*\n"
            "  {% endfor %}\n\n"
            "  {% if not ns.found %}\n"
            "    Шаги пока не добавлены.\n"
            "  {% endif %}"
        )

        return self.async_show_form(
            step_id="card_info",
            data_schema=vol.Schema({}),
            description_placeholders={"yaml_code": yaml_template},
        )

    async def async_step_settings(self, user_input=None):
        """Edit general plan settings (time, schedule, workday sensor)."""
        try:
            if user_input is not None:
                self._temp_settings = user_input
                if user_input.get(CONF_SCHEDULE_TYPE) == SCHEDULE_CUSTOM:
                    return await self.async_step_custom_days()
                return self.async_create_entry(
                    title="",
                    data={**self.entry.options, **user_input, CONF_STEPS: self.steps},
                )

            cur_time = self.entry.options.get(
                CONF_TIME, self.entry.data.get(CONF_TIME, "00:00:00")
            )
            legacy_workdays = self.entry.options.get(
                CONF_WORKDAYS_ONLY, self.entry.data.get(CONF_WORKDAYS_ONLY)
            )
            default_schedule = SCHEDULE_WORKDAYS if legacy_workdays else SCHEDULE_EVERYDAY
            cur_schedule = self.entry.options.get(
                CONF_SCHEDULE_TYPE,
                self.entry.data.get(CONF_SCHEDULE_TYPE, default_schedule),
            )
            cur_workday_sensor = self.entry.options.get(
                CONF_WORKDAY_SENSOR,
                self.entry.data.get(CONF_WORKDAY_SENSOR, DEFAULT_WORKDAY_SENSOR),
            )

            return self.async_show_form(
                step_id="settings",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_TIME, default=cur_time): selector.TimeSelector(),
                        vol.Required(
                            CONF_SCHEDULE_TYPE, default=cur_schedule
                        ): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    SCHEDULE_EVERYDAY,
                                    SCHEDULE_WORKDAYS,
                                    SCHEDULE_WEEKENDS,
                                    SCHEDULE_CUSTOM,
                                ],
                                mode=selector.SelectSelectorMode.DROPDOWN,
                                translation_key="schedule_type",
                            )
                        ),
                        vol.Optional(
                            CONF_WORKDAY_SENSOR, default=cur_workday_sensor
                        ): selector.EntitySelector(
                            selector.EntitySelectorConfig(domain="binary_sensor")
                        ),
                    }
                ),
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Error in settings step: %s", exc, exc_info=True)
            return self.async_abort(reason="unknown")

    async def async_step_custom_days(self, user_input=None):
        """Pick custom weekdays (Options Flow variant)."""
        if user_input is not None:
            final_data = {
                **self.entry.options,
                **self._temp_settings,
                **user_input,
                CONF_STEPS: self.steps,
            }
            return self.async_create_entry(title="", data=final_data)

        cur_custom_days = self.entry.options.get(
            CONF_CUSTOM_DAYS, self.entry.data.get(CONF_CUSTOM_DAYS, [])
        )
        return self.async_show_form(
            step_id="custom_days",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CUSTOM_DAYS, default=cur_custom_days
                    ): selector.SelectSelector(
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
        """Add a new step to the plan."""
        try:
            if user_input is not None:
                self.steps.append(user_input)
                return self.async_create_entry(
                    title="",
                    data={**self.entry.options, CONF_STEPS: self.steps},
                )

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
                            selector.NumberSelectorConfig(
                                min=0, max=3600, unit_of_measurement="сек"
                            )
                        ),
                        vol.Required("enabled", default=True): bool,
                    }
                ),
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Error in add_step: %s", exc, exc_info=True)
            return self.async_abort(reason="unknown")

    async def async_step_manage_steps(self, user_input=None):
        """List existing steps; select one to edit or delete all."""
        try:
            if not self.steps:
                return await self.async_step_init()

            if user_input is not None:
                selected = user_input.get("selected_step")
                if selected == "clear_all":
                    self.steps = []
                    return self.async_create_entry(
                        title="",
                        data={**self.entry.options, CONF_STEPS: self.steps},
                    )
                if selected is not None:
                    self.current_edit_index = int(selected)
                    return await self.async_step_edit_step()

            action_map = {
                "turn_on": "Включить",
                "turn_off": "Выключить",
                "toggle": "Переключить",
            }
            options_list = []
            for i, step in enumerate(self.steps):
                ent_id = step.get("entity_id")
                state = self.hass.states.get(ent_id) if ent_id else None
                friendly_name = state.name if state else ent_id
                action_ru = action_map.get(step.get("action"), step.get("action"))
                label = f"Шаг {i + 1}: {friendly_name} ({action_ru})"
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
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Error in manage_steps: %s", exc, exc_info=True)
            return self.async_abort(reason="unknown")

    async def async_step_edit_step(self, user_input=None):
        """Edit or delete a specific step."""
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
                        "action":    user_input["action"],
                        "delay":     user_input["delay"],
                        "enabled":   user_input["enabled"],
                    }
                    self.steps.pop(self.current_edit_index)
                    new_index = max(0, min(new_index, len(self.steps)))
                    self.steps.insert(new_index, updated_step)

                return self.async_create_entry(
                    title="",
                    data={**self.entry.options, CONF_STEPS: self.steps},
                )

            ent_id = current_step.get("entity_id")
            schema: dict = {}
            schema[vol.Required("entity_id", default=ent_id) if ent_id else vol.Required("entity_id")] = (
                selector.EntitySelector()
            )
            schema[vol.Required("action", default=current_step.get("action", "turn_on"))] = (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["turn_on", "turn_off", "toggle"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            )
            schema[vol.Required("delay", default=current_step.get("delay", 0))] = (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=3600, unit_of_measurement="сек"
                    )
                )
            )
            schema[vol.Required("enabled", default=current_step.get("enabled", True))] = bool

            max_idx = max(0, len(self.steps) - 1)
            if max_idx > 0:
                schema[vol.Required("order", default=self.current_edit_index)] = (
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=max_idx, mode=selector.NumberSelectorMode.BOX
                        )
                    )
                )

            schema[vol.Optional("delete", default=False)] = bool

            return self.async_show_form(
                step_id="edit_step",
                data_schema=vol.Schema(schema),
                description_placeholders={"step_num": str(self.current_edit_index + 1)},
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Error in edit_step: %s", exc, exc_info=True)
            return self.async_abort(reason="unknown")