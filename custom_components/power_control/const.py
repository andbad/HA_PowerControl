"""Constants for the Power Control integration."""

DOMAIN = "power_control"

# ── config_entry.data keys ────────────────────────────────────────────────────
CONF_INSTANCE_NAME = "instance_name"
CONF_GLOBAL_POWER_SENSOR = "global_power_sensor"
CONF_THRESHOLD_IMMEDIATE = "threshold_immediate"
CONF_THRESHOLD_DELAYED = "threshold_delayed"
CONF_DELAY_IMMEDIATE_SEC = "delay_immediate_sec"
CONF_DELAY_DELAYED_MIN = "delay_delayed_min"
CONF_WAIT_BETWEEN_STOPS_SEC = "wait_between_stops_sec"
CONF_WAIT_BETWEEN_STARTS_MIN = "wait_between_starts_min"
CONF_WAIT_BEFORE_START_MIN = "wait_before_start_min"
CONF_NOTIFY_ENTITY = "notify_entity"
CONF_NOTIFY_SERVICE = CONF_NOTIFY_ENTITY  # backwards-compat alias
CONF_NUM_LOADS = "num_loads"
CONF_LOADS = "loads"
CONF_DASHBOARD_LANGUAGE = "dashboard_language"

# ── per-load keys (inside CONF_LOADS list) ────────────────────────────────────
LOAD_NAME = "name"
LOAD_POWER_SENSOR = "power_sensor"
LOAD_SWITCH = "switch"
LOAD_AUTO_RESTART = "auto_restart"
LOAD_MIN_OFF_SEC = "min_off_sec"

# ── dashboard user-control ────────────────────────────────────────────────────
CONF_DASHBOARD_USER_CONTROLLED = "dashboard_user_controlled"
CONF_DASHBOARD_SKIPPED_VERSION = "dashboard_skipped_version"
NOTIF_ID_REGEN_CONFIRM = "power_control_regen_confirm"
SERVICE_REGENERATE_DASHBOARD = "regenerate_dashboard"

# ── misc ──────────────────────────────────────────────────────────────────────
UPDATE_INTERVAL_SEC = 5
MIN_ACTIVE_POWER_W = 10        # below this a load is considered off
