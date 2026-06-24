"""Config flow for Power Control integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    BooleanSelector,
)

from .migration import detect_old_package, read_old_config
from .const import (
    DOMAIN,
    CONF_INSTANCE_NAME,
    CONF_GLOBAL_POWER_SENSOR,
    CONF_THRESHOLD_IMMEDIATE,
    CONF_THRESHOLD_DELAYED,
    CONF_DELAY_IMMEDIATE_SEC,
    CONF_DELAY_DELAYED_MIN,
    CONF_WAIT_BETWEEN_STOPS_SEC,
    CONF_WAIT_BETWEEN_STARTS_MIN,
    CONF_WAIT_BEFORE_START_MIN,
    CONF_NOTIFY_ENTITY,
    CONF_NOTIFY_SERVICE,  # alias
    CONF_NUM_LOADS,
    CONF_LOADS,
    CONF_DASHBOARD_LANGUAGE,
    CONF_DASHBOARD_USER_CONTROLLED,
    LOAD_NAME,
    LOAD_POWER_SENSOR,
    LOAD_SWITCH,
    LOAD_AUTO_RESTART,
    LOAD_MIN_OFF_SEC,
)

_LOGGER = logging.getLogger(__name__)

_CONF_CREATE_DASHBOARD = "create_dashboard"
_SUPPORTED_LANGUAGES = ["en", "it", "de", "fr", "es"]

_INT_FIELDS = {
    CONF_THRESHOLD_IMMEDIATE,
    CONF_THRESHOLD_DELAYED,
    CONF_DELAY_IMMEDIATE_SEC,
    CONF_DELAY_DELAYED_MIN,
    CONF_WAIT_BETWEEN_STOPS_SEC,
    CONF_WAIT_BETWEEN_STARTS_MIN,
    CONF_WAIT_BEFORE_START_MIN,
}


def _coerce_ints(data: dict) -> dict:
    """Coerce NumberSelector float outputs to int; normalise None entity fields to ''."""
    _ENTITY_FIELDS = {CONF_GLOBAL_POWER_SENSOR, LOAD_POWER_SENSOR, LOAD_SWITCH}
    result = {}
    for k, v in data.items():
        if k in _INT_FIELDS and v is not None:
            result[k] = int(v)
        elif k in _ENTITY_FIELDS and v is None:
            result[k] = ""
        else:
            result[k] = v
    return result


# ── Shared schema builders ─────────────────────────────────────────────────────

def _global_schema(defaults: dict = {}) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_INSTANCE_NAME,
                default=defaults.get(CONF_INSTANCE_NAME, "Power Control"),
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),

            vol.Optional(
                CONF_GLOBAL_POWER_SENSOR,
                description={"suggested_value": defaults.get(CONF_GLOBAL_POWER_SENSOR, "")},
            ): EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power")),

            vol.Required(
                CONF_THRESHOLD_IMMEDIATE,
                default=defaults.get(CONF_THRESHOLD_IMMEDIATE, 3000),
            ): NumberSelector(NumberSelectorConfig(
                min=100, max=15000, step=100, unit_of_measurement="W",
                mode=NumberSelectorMode.SLIDER,
            )),
            vol.Required(
                CONF_THRESHOLD_DELAYED,
                default=defaults.get(CONF_THRESHOLD_DELAYED, 2700),
            ): NumberSelector(NumberSelectorConfig(
                min=100, max=15000, step=100, unit_of_measurement="W",
                mode=NumberSelectorMode.SLIDER,
            )),
            vol.Required(
                CONF_DELAY_IMMEDIATE_SEC,
                default=defaults.get(CONF_DELAY_IMMEDIATE_SEC, 30),
            ): NumberSelector(NumberSelectorConfig(
                min=5, max=60, step=1, unit_of_measurement="s",
                mode=NumberSelectorMode.SLIDER,
            )),
            vol.Required(
                CONF_DELAY_DELAYED_MIN,
                default=defaults.get(CONF_DELAY_DELAYED_MIN, 10),
            ): NumberSelector(NumberSelectorConfig(
                min=1, max=180, step=1, unit_of_measurement="min",
                mode=NumberSelectorMode.SLIDER,
            )),
            vol.Required(
                CONF_WAIT_BETWEEN_STOPS_SEC,
                default=defaults.get(CONF_WAIT_BETWEEN_STOPS_SEC, 10),
            ): NumberSelector(NumberSelectorConfig(
                min=5, max=60, step=1, unit_of_measurement="s",
                mode=NumberSelectorMode.SLIDER,
            )),
            vol.Required(
                CONF_WAIT_BETWEEN_STARTS_MIN,
                default=defaults.get(CONF_WAIT_BETWEEN_STARTS_MIN, 5),
            ): NumberSelector(NumberSelectorConfig(
                min=1, max=60, step=1, unit_of_measurement="min",
                mode=NumberSelectorMode.SLIDER,
            )),
            vol.Required(
                CONF_WAIT_BEFORE_START_MIN,
                default=defaults.get(CONF_WAIT_BEFORE_START_MIN, 5),
            ): NumberSelector(NumberSelectorConfig(
                min=1, max=60, step=1, unit_of_measurement="min",
                mode=NumberSelectorMode.SLIDER,
            )),

            vol.Optional(
                CONF_NOTIFY_ENTITY,
                description={"suggested_value": defaults.get(CONF_NOTIFY_ENTITY, "")},
            ): EntitySelector(EntitySelectorConfig(domain="notify")),
        }
    )


def _num_loads_schema(default: int = 3) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NUM_LOADS, default=default): vol.All(
                int, vol.Range(min=1, max=20)
            ),
        }
    )


def _load_schema(index: int, defaults: dict = {}) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                LOAD_NAME,
                default=defaults.get(LOAD_NAME, f"Load {index + 1}"),
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),

            vol.Optional(
                LOAD_POWER_SENSOR,
                description={"suggested_value": defaults.get(LOAD_POWER_SENSOR, "")},
            ): EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power")),

            vol.Optional(
                LOAD_SWITCH,
                description={"suggested_value": defaults.get(LOAD_SWITCH, "")},
            ): EntitySelector(EntitySelectorConfig(domain=["switch", "light"])),

            vol.Required(
                LOAD_AUTO_RESTART,
                default=defaults.get(LOAD_AUTO_RESTART, True),
            ): BooleanSelector(),

            vol.Optional(
                LOAD_MIN_OFF_SEC,
                default=defaults.get(LOAD_MIN_OFF_SEC, 0),
            ): NumberSelector(NumberSelectorConfig(
                min=0, max=3600, step=30, unit_of_measurement="s",
                mode=NumberSelectorMode.BOX,
            )),
        }
    )


# ── Initial config flow ────────────────────────────────────────────────────────

class PowerControlConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Power Control."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._loads: list[dict[str, Any]] = []
        self._num_loads: int = 0
        self._current_load_index: int = 0
        self._create_dashboard: bool = True
        self._from_migration: bool = False

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Route to migration or fresh setup."""
        if detect_old_package(self.hass):
            return await self.async_step_migrate()
        return await self.async_step_global()

    async def async_step_migrate(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Offer to import the old package config."""
        if user_input is not None:
            if user_input.get("migrate", True):
                imported = read_old_config(self.hass)
                self._data = {k: v for k, v in imported.items()
                              if k not in (CONF_NUM_LOADS, CONF_LOADS)}
                self._loads = imported.get(CONF_LOADS, [])
                self._num_loads = imported.get(CONF_NUM_LOADS, len(self._loads))
                return await self.async_step_migrate_confirm()
            return await self.async_step_global()

        detected_loads = sum(
            1 for i in range(1, 21)
            if self.hass.states.get(f"input_text.carico_{i}_potenza") is not None
            and self.hass.states.get(f"input_text.carico_{i}_potenza").state
            not in ("", "Seleziona")
        )
        return self.async_show_form(
            step_id="migrate",
            data_schema=vol.Schema(
                {vol.Required("migrate", default=True): BooleanSelector()}
            ),
            description_placeholders={"load_count": str(detected_loads)},
        )

    async def async_step_migrate_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show imported config for review."""
        if user_input is not None:
            if user_input.get("confirm", True):
                self._data[CONF_NUM_LOADS] = self._num_loads
                self._data[CONF_LOADS] = self._loads
                self._from_migration = True
                return await self.async_step_dashboard()
            return await self.async_step_global()

        load_names = ", ".join(
            l.get(LOAD_NAME, f"Load {i+1}")
            for i, l in enumerate(self._loads[:5])
        )
        if len(self._loads) > 5:
            load_names += f" ... (+{len(self._loads) - 5} altri)"

        return self.async_show_form(
            step_id="migrate_confirm",
            data_schema=vol.Schema(
                {vol.Required("confirm", default=True): BooleanSelector()}
            ),
            description_placeholders={
                "load_count": str(self._num_loads),
                "load_names": load_names,
                "threshold_immediate": str(self._data.get(CONF_THRESHOLD_IMMEDIATE, "?")),
                "threshold_delayed": str(self._data.get(CONF_THRESHOLD_DELAYED, "?")),
            },
        )

    async def async_step_global(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Global settings step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = _coerce_ints(user_input)
            if user_input[CONF_THRESHOLD_IMMEDIATE] <= user_input[CONF_THRESHOLD_DELAYED]:
                errors["base"] = "threshold_order"
            else:
                self._data.update(user_input)
                return await self.async_step_num_loads()

        return self.async_show_form(
            step_id="global",
            data_schema=_global_schema(self._data or {}),
            errors=errors,
        )

    async def async_step_num_loads(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """How many loads."""
        if user_input is not None:
            self._num_loads = user_input[CONF_NUM_LOADS]
            self._current_load_index = 0
            self._loads = []
            return await self.async_step_load()

        return self.async_show_form(
            step_id="num_loads",
            data_schema=_num_loads_schema(),
        )

    async def async_step_load(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """One step per load."""
        if user_input is not None:
            self._loads.append(_coerce_ints(user_input))
            self._current_load_index += 1

            if self._current_load_index >= self._num_loads:
                self._data[CONF_NUM_LOADS] = self._num_loads
                self._data[CONF_LOADS] = self._loads
                return await self.async_step_dashboard()

            return await self.async_step_load()

        return self.async_show_form(
            step_id="load",
            data_schema=_load_schema(self._current_load_index),
            description_placeholders={
                "load_number": str(self._current_load_index + 1),
                "total_loads": str(self._num_loads),
            },
        )

    async def async_step_dashboard(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask whether to create the Lovelace dashboard and in which language."""
        if user_input is not None:
            self._create_dashboard = user_input.get(_CONF_CREATE_DASHBOARD, True)
            self._data = {
                **self._data,
                _CONF_CREATE_DASHBOARD: self._create_dashboard,
                CONF_DASHBOARD_LANGUAGE: user_input.get(CONF_DASHBOARD_LANGUAGE, "en"),
                CONF_DASHBOARD_USER_CONTROLLED: user_input.get(CONF_DASHBOARD_USER_CONTROLLED, False),
            }
            if self._from_migration:
                return await self.async_step_migrate_cleanup()
            return self.async_create_entry(
                title=self._data[CONF_INSTANCE_NAME],
                data=self._data,
            )

        # Pre-select language: prefer context language (set by frontend),
        # fall back to HA system language, then "en"
        ctx_lang = (self.context.get("language") or "").split("-")[0].lower()
        sys_lang = (self.hass.config.language or "").split("-")[0].lower()
        for candidate in (ctx_lang, sys_lang):
            if candidate in _SUPPORTED_LANGUAGES:
                default_lang = candidate
                break
        else:
            default_lang = "en"
        _LOGGER.debug("[%s] Dashboard lang — ctx=%r sys=%r → %s", DOMAIN, ctx_lang, sys_lang, default_lang)

        return self.async_show_form(
            step_id="dashboard",
            data_schema=vol.Schema(
                {
                    vol.Required(_CONF_CREATE_DASHBOARD, default=True): BooleanSelector(),
                    vol.Required(
                        CONF_DASHBOARD_LANGUAGE, default=default_lang
                    ): SelectSelector(SelectSelectorConfig(
                        options=_SUPPORTED_LANGUAGES,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="dashboard_language",
                    )),
                    vol.Required(CONF_DASHBOARD_USER_CONTROLLED, default=False): BooleanSelector(),
                }
            ),
        )

    async def async_step_migrate_cleanup(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Inform the user about manual cleanup steps and disable old package."""
        if user_input is not None:
            # Disable old package to avoid conflicts
            if self.hass.states.get("input_boolean.attiva_power_control") is not None:
                await self.hass.services.async_call(
                    "input_boolean",
                    "turn_off",
                    {"entity_id": "input_boolean.attiva_power_control"},
                )
            return self.async_create_entry(
                title=self._data[CONF_INSTANCE_NAME],
                data=self._data,
            )

        return self.async_show_form(
            step_id="migrate_cleanup",
            data_schema=vol.Schema({}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PowerControlOptionsFlow:
        """Return the options flow."""
        return PowerControlOptionsFlow(config_entry)


# ── Options flow ───────────────────────────────────────────────────────────────

class PowerControlOptionsFlow(OptionsFlow):
    """Edit Power Control settings after initial setup."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Read current values from config_entry.data for pre-population.

        We copy the data into local state here so every form step can show
        the current values as defaults.  We intentionally do NOT store
        config_entry itself to avoid the deprecated _config_entry assignment.
        """
        # Snapshot current data — this is what every form will use as defaults
        self._data: dict[str, Any] = dict(config_entry.data)
        self._loads: list[dict[str, Any]] = list(
            config_entry.data.get(CONF_LOADS, [])
        )
        self._num_loads: int = int(config_entry.data.get(CONF_NUM_LOADS, 1))
        self._current_load_index: int = 0

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1 — global settings, pre-populated from current config."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = _coerce_ints(user_input)
            if user_input[CONF_THRESHOLD_IMMEDIATE] <= user_input[CONF_THRESHOLD_DELAYED]:
                errors["base"] = "threshold_order"
            else:
                self._data.update(user_input)
                return await self.async_step_num_loads()

        # Pass self._data so all current values appear as defaults
        return self.async_show_form(
            step_id="init",
            data_schema=_global_schema(self._data),
            errors=errors,
        )

    async def async_step_num_loads(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2 — number of loads, pre-populated."""
        if user_input is not None:
            new_num = int(user_input[CONF_NUM_LOADS])
            if new_num < len(self._loads):
                self._loads = self._loads[:new_num]
            elif new_num > len(self._loads):
                for i in range(len(self._loads), new_num):
                    self._loads.append({
                        LOAD_NAME: f"Load {i + 1}",
                        LOAD_POWER_SENSOR: "",
                        LOAD_SWITCH: "",
                        LOAD_AUTO_RESTART: True,
                        LOAD_MIN_OFF_SEC: 0,
                    })
            self._num_loads = new_num
            self._current_load_index = 0
            return await self.async_step_load()

        return self.async_show_form(
            step_id="num_loads",
            data_schema=_num_loads_schema(default=self._num_loads),
        )

    async def async_step_load(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 3..N — one step per load, pre-populated with existing values."""
        if user_input is not None:
            self._loads[self._current_load_index] = _coerce_ints(user_input)
            self._current_load_index += 1

            if self._current_load_index >= self._num_loads:
                return await self._save_and_finish()

            return await self.async_step_load()

        # Pre-populate with the current load's saved values
        current_defaults = self._loads[self._current_load_index]
        return self.async_show_form(
            step_id="load",
            data_schema=_load_schema(self._current_load_index, current_defaults),
            description_placeholders={
                "load_number": str(self._current_load_index + 1),
                "total_loads": str(self._num_loads),
            },
        )

    async def _save_and_finish(self) -> FlowResult:
        """Persist all changes to config_entry.data and close the flow.

        HA options flows normally save to config_entry.options, but we use
        config_entry.data as the single source of truth (the coordinator always
        reads from .data).  We update .data directly via async_update_entry and
        return an empty options dict so HA's options machinery stays happy.
        """
        self._data[CONF_NUM_LOADS] = self._num_loads
        self._data[CONF_LOADS] = self._loads

        # Persist to config_entry.data — the coordinator reads from here
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data=self._data,
        )
        _LOGGER.debug(
            "[%s] Options saved: %d loads, imm=%d W, del=%d W",
            DOMAIN,
            self._num_loads,
            self._data.get(CONF_THRESHOLD_IMMEDIATE, 0),
            self._data.get(CONF_THRESHOLD_DELAYED, 0),
        )

        # Sync suspended_power sensor entity_ids to current load names
        self._sync_suspended_sensor_entity_ids()

        # Return empty options — all data lives in .data, not .options
        return self.async_create_entry(title="", data={})

    def _sync_suspended_sensor_entity_ids(self) -> None:
        """Rename suspended_power sensor entity_ids to match current load names.

        When a load is renamed, the unique_id stays stable but _attr_name changes.
        HA keeps the old entity_id until explicitly updated. This method aligns
        entity_ids with the current load names so the auto-generated dashboard
        finds the correct entities after reconfigure.
        """
        registry = er.async_get(self.hass)
        entry_id = self.config_entry.entry_id
        loads_cfg = self._data.get(CONF_LOADS, [])

        for i, load_cfg in enumerate(loads_cfg):
            unique_id = f"{entry_id}_load_{i}_suspended"
            current_entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
            if current_entity_id is None:
                continue

            load_name = (load_cfg.get(LOAD_NAME) or "").strip()
            display_name = load_name if load_name else f"Load {i + 1}"
            expected_entity_id = (
                f"sensor.{slugify(f'power_control {display_name} suspended power')}"
            )

            if current_entity_id != expected_entity_id:
                try:
                    registry.async_update_entity(
                        current_entity_id, new_entity_id=expected_entity_id
                    )
                    _LOGGER.debug(
                        "[%s] Renamed sensor entity_id: %s → %s",
                        DOMAIN, current_entity_id, expected_entity_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning(
                        "[%s] Could not rename sensor entity_id %s → %s: %s",
                        DOMAIN, current_entity_id, expected_entity_id, exc,
                    )
