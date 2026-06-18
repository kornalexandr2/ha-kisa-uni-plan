"""Constants for the KiSa Plan Day integration."""

DOMAIN = "ha_kisa_uni_plan"

CONF_PLAN_NAME = "plan_name"
CONF_TIME = "start_time"
CONF_WORKDAYS_ONLY = "workdays_only"  # Легаси
CONF_SCHEDULE_TYPE = "schedule_type"
CONF_CUSTOM_DAYS = "custom_days"
CONF_WORKDAY_SENSOR = "workday_sensor"
CONF_STEPS = "steps"

SCHEDULE_EVERYDAY = "everyday"
SCHEDULE_WORKDAYS = "workdays"
SCHEDULE_WEEKENDS = "weekends"
SCHEDULE_CUSTOM = "custom"

CONF_STEP_ENTITY = "entity_id"
CONF_STEP_DELAY = "delay"
CONF_STEP_ENABLED = "enabled"
CONF_STEP_ACTION = "action"

DEFAULT_WORKDAY_SENSOR = "binary_sensor.workday_sensor"
