"""Config flow for Power Control integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
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
    LOAD_NAME,
    LOAD_POWER_SENSOR,
    LOAD_SWITCH,
    LOAD_AUTO_RESTART,
)

_LOGGER = logging.getLogger(__name__)


_CONF_CREATE_DASHBOARD = "create_dashboard"

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
    """Coerce NumberSelector float outputs to int for numeric config fields.

    Also normalises optional entity fields from None (frontend sends None
    when left blank) to empty string so downstream code can do `if value:`
    checks uniformly.
    """
    _ENTITY_FIELDS = {
        CONF_GLOBAL_POWER_SENSOR,
        LOAD_POWER_SENSOR,
        LOAD_SWITCH,
    }
    result = {}
    for k, v in data.items():
        if k in _INT_FIELDS and v is not None:
            result[k] = int(v)
        elif k in _ENTITY_FIELDS and v is None:
            result[k] = ""
        else:
            result[k] = v
    return result


def _global_schema(defaults: dict = {}) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_INSTANCE_NAME,
                default=defaults.get(CONF_INSTANCE_NAME, "Power Control"),
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),

            # Entity picker filtered to power sensors only
            vol.Optional(
                CONF_GLOBAL_POWER_SENSOR,
            ): EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class="power")
            ),

            vol.Required(
                CONF_THRESHOLD_IMMEDIATE,
                default=defaults.get(CONF_THRESHOLD_IMMEDIATE, 3000),
            ): NumberSelector(
                NumberSelectorConfig(min=100, max=15000, step=100, unit_of_measurement="W", mode=NumberSelectorMode.SLIDER)
            ),
            vol.Required(
                CONF_THRESHOLD_DELAYED,
                default=defaults.get(CONF_THRESHOLD_DELAYED, 2700),
            ): NumberSelector(
                NumberSelectorConfig(min=100, max=15000, step=100, unit_of_measurement="W", mode=NumberSelectorMode.SLIDER)
            ),
            vol.Required(
                CONF_DELAY_IMMEDIATE_SEC,
                default=defaults.get(CONF_DELAY_IMMEDIATE_SEC, 30),
            ): NumberSelector(
                NumberSelectorConfig(min=5, max=60, step=1, unit_of_measurement="s", mode=NumberSelectorMode.SLIDER)
            ),
            vol.Required(
                CONF_DELAY_DELAYED_MIN,
                default=defaults.get(CONF_DELAY_DELAYED_MIN, 10),
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=180, step=1, unit_of_measurement="min", mode=NumberSelectorMode.SLIDER)
            ),
            vol.Required(
                CONF_WAIT_BETWEEN_STOPS_SEC,
                default=defaults.get(CONF_WAIT_BETWEEN_STOPS_SEC, 10),
            ): NumberSelector(
                NumberSelectorConfig(min=5, max=60, step=1, unit_of_measurement="s", mode=NumberSelectorMode.SLIDER)
            ),
            vol.Required(
                CONF_WAIT_BETWEEN_STARTS_MIN,
                default=defaults.get(CONF_WAIT_BETWEEN_STARTS_MIN, 5),
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=60, step=1, unit_of_measurement="min", mode=NumberSelectorMode.SLIDER)
            ),
            vol.Required(
                CONF_WAIT_BEFORE_START_MIN,
                default=defaults.get(CONF_WAIT_BEFORE_START_MIN, 5),
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=60, step=1, unit_of_measurement="min", mode=NumberSelectorMode.SLIDER)
            ),

            # Entity picker filtered to notify entities
            # Works with: Companion app, Telegram (2025.11+), Pushover, etc.
            vol.Optional(
                CONF_NOTIFY_ENTITY,
            ): EntitySelector(
                EntitySelectorConfig(domain="notify")
            ),
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
                default=defaults.get(LOAD_NAME, f"Carico {index + 1}"),
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),

            # Dropdown filtered to power sensors (device_class=power)
            vol.Optional(
                LOAD_POWER_SENSOR,
            ): EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class="power")
            ),

            # Dropdown filtered to switches and lights (common controllable loads)
            vol.Optional(
                LOAD_SWITCH,
            ): EntitySelector(
                EntitySelectorConfig(domain=["switch", "light"])
            ),

            vol.Required(
                LOAD_AUTO_RESTART,
                default=defaults.get(LOAD_AUTO_RESTART, True),
            ): BooleanSelector(),
        }
    )


class PowerControlConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Power Control."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}
        self._loads: list[dict[str, Any]] = []
        self._num_loads: int = 0
        self._current_load_index: int = 0
        self._create_dashboard: bool = True
        self._migrating: bool = False

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 0 — detect old package and offer migration, or go straight to setup."""
        if detect_old_package(self.hass):
            return await self.async_step_migrate()
        return await self.async_step_global()

    async def async_step_migrate(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Offer to import configuration from the old pc.yaml package."""
        if user_input is not None:
            if user_input.get("migrate", True):
                # Read config from old entities
                migrated = read_old_config(self.hass)
                self._migrating = True
                self._data.update({
                    k: v for k, v in migrated.items()
                    if not k.startswith("_")
                    and k not in (CONF_NUM_LOADS, CONF_LOADS)
                })
                self._loads = migrated.get(CONF_LOADS, [])
                self._num_loads = len(self._loads)
                # Skip wizard, go straight to confirmation
                return await self.async_step_migrate_confirm()
            # User declined migration — proceed with normal setup
            return await self.async_step_global()

        detected_loads = len([
            i for i in range(1, 21)
            if self.hass.states.get(f"input_text.carico_{i}_switch") is not None
            and self.hass.states.get(f"input_text.carico_{i}_switch").state not in
               ("", "Seleziona", "unknown", "unavailable")
        ])

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
        """Show the imported config for review before creating the entry."""
        if user_input is not None:
            if user_input.get("confirm", True):
                self._data[CONF_NUM_LOADS] = self._num_loads
                self._data[CONF_LOADS] = self._loads
                return await self.async_step_dashboard()
            # User wants to edit manually — pre-fill the wizard
            self._migrating = False
            return await self.async_step_global()

        # Build summary for display
        load_names = ", ".join(
            l.get(LOAD_NAME, f"Carico {i+1}")
            for i, l in enumerate(self._loads[:5])
        )
        if len(self._loads) > 5:
            load_names += f" ... (+{len(self._loads) - 5} altri)"

        imm = self._data.get(CONF_THRESHOLD_IMMEDIATE, "?")
        delayed = self._data.get(CONF_THRESHOLD_DELAYED, "?")

        return self.async_show_form(
            step_id="migrate_confirm",
            data_schema=vol.Schema(
                {vol.Required("confirm", default=True): BooleanSelector()}
            ),
            description_placeholders={
                "load_count": str(self._num_loads),
                "load_names": load_names,
                "threshold_immediate": str(imm),
                "threshold_delayed": str(delayed),
            },
        )

    async def async_step_global(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Global settings step (normal setup path)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # NumberSelector returns float — coerce timing/threshold fields to int
            user_input = _coerce_ints(user_input)
            # Validate that thresholds are coherent
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
        """Step 2 — how many loads to configure."""
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
        """Step 3..N — one step per load."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._loads.append(_coerce_ints(user_input))
            self._current_load_index += 1

            if self._current_load_index >= self._num_loads:
                # All loads configured — ask about dashboard
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
            errors=errors,
        )


    async def async_step_dashboard(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Final step — ask whether to create the Lovelace dashboard."""
        if user_input is not None:
            self._create_dashboard = user_input.get(_CONF_CREATE_DASHBOARD, True)
            return self.async_create_entry(
                title=self._data[CONF_INSTANCE_NAME],
                data={**self._data, _CONF_CREATE_DASHBOARD: self._create_dashboard},
            )

        return self.async_show_form(
            step_id="dashboard",
            data_schema=vol.Schema(
                {vol.Required(_CONF_CREATE_DASHBOARD, default=True): BooleanSelector()}
            ),
        )
    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PowerControlOptionsFlow:
        """Return the options flow."""
        return PowerControlOptionsFlow(config_entry)


class PowerControlOptionsFlow(OptionsFlow):
    """Handle options for Power Control (edit after first setup)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self._data: dict[str, Any] = dict(config_entry.data)
        self._loads: list[dict[str, Any]] = list(config_entry.data.get(CONF_LOADS, []))
        self._num_loads: int = config_entry.data.get(CONF_NUM_LOADS, 1)
        self._current_load_index: int = 0

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1 — edit global settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = _coerce_ints(user_input)
            if user_input[CONF_THRESHOLD_IMMEDIATE] <= user_input[CONF_THRESHOLD_DELAYED]:
                errors["base"] = "threshold_order"
            else:
                self._data.update(user_input)
                return await self.async_step_num_loads()

        return self.async_show_form(
            step_id="init",
            data_schema=_global_schema(self._data),
            errors=errors,
        )

    async def async_step_num_loads(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit number of loads."""
        if user_input is not None:
            new_num = user_input[CONF_NUM_LOADS]
            # Trim or extend the existing loads list
            if new_num < len(self._loads):
                self._loads = self._loads[:new_num]
            elif new_num > len(self._loads):
                for i in range(len(self._loads), new_num):
                    self._loads.append(
                        {
                            LOAD_NAME: f"Carico {i + 1}",
                            LOAD_POWER_SENSOR: "",
                            LOAD_SWITCH: "",
                            LOAD_AUTO_RESTART: True,
                        }
                    )
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
        """Edit a single load."""
        if user_input is not None:
            self._loads[self._current_load_index] = user_input
            self._current_load_index += 1

            if self._current_load_index >= self._num_loads:
                self._data[CONF_NUM_LOADS] = self._num_loads
                self._data[CONF_LOADS] = self._loads
                return self.async_create_entry(title="", data=self._data)

            return await self.async_step_load()

        current_defaults = self._loads[self._current_load_index]
        return self.async_show_form(
            step_id="load",
            data_schema=_load_schema(self._current_load_index, current_defaults),
            description_placeholders={
                "load_number": str(self._current_load_index + 1),
                "total_loads": str(self._num_loads),
            },
        )
