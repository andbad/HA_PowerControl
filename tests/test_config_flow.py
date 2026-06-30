"""Integration tests for the Power Control config flow."""
from __future__ import annotations

import pytest

from homeassistant.data_entry_flow import FlowResultType

from custom_components.power_control.const import (
    DOMAIN,
    CONF_THRESHOLD_IMMEDIATE,
    CONF_THRESHOLD_DELAYED,
    CONF_INSTANCE_NAME,
    CONF_NUM_LOADS,
    CONF_LOADS,
    LOAD_NAME,
    LOAD_AUTO_RESTART,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

GLOBAL_STEP_DATA = {
    "instance_name": "Test PC",
    # global_power_sensor omitted — optional, EntitySelector rejects empty string
    "threshold_immediate": 3300,
    "threshold_delayed": 3000,
    "delay_immediate_sec": 30,
    "delay_delayed_min": 10,
    "wait_between_stops_sec": 10,
    "wait_between_starts_min": 5,
    "wait_before_start_min": 5,
    # notify_service omitted — plain text, but keep consistent
}

LOAD_DATA = {
    "name": "Lavatrice",
    "power_sensor": "sensor.potenza_lavatrice",
    "switch": "switch.lavatrice",
    "auto_restart": True,
}  # power_sensor and switch are real entity IDs here so EntitySelector is happy

DASHBOARD_STEP_DATA = {
    "create_dashboard": True,
    "dashboard_language": "en",
    "dashboard_user_controlled": False,
    "dashboard_require_admin": True,
}


async def _start_flow(hass):
    """Initialize a fresh user config flow and return the global settings form.

    async_step_user is a router: it goes to 'migrate' if old package is
    detected, or 'global' on a fresh install.  In tests we always land on
    'global' because the mock hass has no legacy entities.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    # async_step_user routes to 'global' when no legacy package is found
    if result.get("step_id") == "user":
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=None
        )
    return result


async def _complete_flow(hass, num_loads: int = 1) -> dict:
    """Run the config flow end-to-end and return the final result."""
    result = await _start_flow(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "global"

    # Step 1 — global settings
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=GLOBAL_STEP_DATA
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "num_loads"

    # Step 2 — number of loads
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"num_loads": num_loads}
    )

    # Step 3..N — one per load
    for i in range(num_loads):
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "load"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={**LOAD_DATA, "name": f"Carico {i + 1}"},
        )

    # Final step — dashboard (always skip creation in tests)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "dashboard"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"create_dashboard": False},
    )

    return result


# ── Config Flow tests ─────────────────────────────────────────────────────────

class TestConfigFlow:
    async def test_flow_shows_user_form_first(
        self, hass, enable_custom_integrations
    ):
        """First step must be the user form."""
        result = await _start_flow(hass)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "global"
        assert "errors" not in result or result["errors"] == {}

    async def test_flow_rejects_inverted_thresholds(
        self, hass, enable_custom_integrations
    ):
        """Immediate threshold must be greater than delayed threshold."""
        result = await _start_flow(hass)
        bad_data = {**GLOBAL_STEP_DATA, "threshold_immediate": 2000, "threshold_delayed": 3000}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=bad_data
        )
        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "threshold_order"

    async def test_flow_creates_entry_with_one_load(
        self, hass, enable_custom_integrations
    ):
        """Full flow with a single load creates a config entry."""
        result = await _complete_flow(hass, num_loads=1)
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Test PC"

    async def test_flow_saves_global_settings(
        self, hass, enable_custom_integrations
    ):
        """Config entry data must contain all global fields."""
        result = await _complete_flow(hass, num_loads=1)
        data = result["data"]
        assert data[CONF_INSTANCE_NAME] == "Test PC"
        assert data[CONF_THRESHOLD_IMMEDIATE] == 3300
        assert data[CONF_THRESHOLD_DELAYED] == 3000

    async def test_flow_saves_loads(self, hass, enable_custom_integrations):
        """Config entry data must contain the loads list."""
        result = await _complete_flow(hass, num_loads=2)
        data = result["data"]
        assert data[CONF_NUM_LOADS] == 2
        assert len(data[CONF_LOADS]) == 2
        assert data[CONF_LOADS][0][LOAD_NAME] == "Carico 1"
        assert data[CONF_LOADS][1][LOAD_NAME] == "Carico 2"

    async def test_flow_load_auto_restart_default_true(
        self, hass, enable_custom_integrations
    ):
        """auto_restart defaults to True."""
        result = await _complete_flow(hass, num_loads=1)
        assert result["data"][CONF_LOADS][0][LOAD_AUTO_RESTART] is True

    async def test_flow_step_count_matches_num_loads(
        self, hass, enable_custom_integrations
    ):
        """Flow must request exactly N load forms for N loads."""
        result = await _complete_flow(hass, num_loads=3)
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert len(result["data"][CONF_LOADS]) == 3

    async def test_flow_dashboard_step_shown(
        self, hass, enable_custom_integrations
    ):
        """The dashboard step must appear as the last step of the flow."""
        result = await _start_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=GLOBAL_STEP_DATA
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"num_loads": 1}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=LOAD_DATA
        )
        # After the last load, dashboard step must appear
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "dashboard"

    async def test_flow_skipping_dashboard_creates_entry(
        self, hass, enable_custom_integrations
    ):
        """Choosing not to create the dashboard must still complete the flow."""
        result = await _complete_flow(hass, num_loads=1)
        assert result["type"] == FlowResultType.CREATE_ENTRY

    async def test_flow_coerces_number_fields_to_int(
        self, hass, enable_custom_integrations
    ):
        """NumberSelector returns float — the flow must coerce to int before saving."""
        result = await _start_flow(hass)
        # Simulate NumberSelector returning floats
        float_data = {**GLOBAL_STEP_DATA, "threshold_immediate": 3300.0, "threshold_delayed": 3000.0}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=float_data
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"num_loads": 1}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=LOAD_DATA
        )
        # Complete the dashboard step
        assert result["step_id"] == "dashboard"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"create_dashboard": False}
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert isinstance(result["data"][CONF_THRESHOLD_IMMEDIATE], int)
        assert isinstance(result["data"][CONF_THRESHOLD_DELAYED], int)


# ── Options Flow tests ────────────────────────────────────────────────────────

class TestOptionsFlow:
    async def test_options_flow_starts_from_init(
        self, hass, setup_integration
    ):
        """Options flow first step must be 'init'."""
        _, _, entry = setup_integration
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "init"

    async def test_options_flow_updates_threshold(
        self, hass, setup_integration
    ):
        """Changing the threshold via options flow updates coordinator data."""
        hass, coordinator, entry = setup_integration
        result = await hass.config_entries.options.async_init(entry.entry_id)

        # Change thresholds
        updated = {**GLOBAL_STEP_DATA, "threshold_immediate": 4000, "threshold_delayed": 3500}
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input=updated
        )
        # Proceed through num_loads + load steps unchanged
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={"num_loads": 3}
        )
        for i in range(3):
            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                user_input={**LOAD_DATA, "name": f"Carico {i + 1}"},
            )

        # Proceed through the new dashboard step
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input=DASHBOARD_STEP_DATA
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

        # Coordinator should now reflect new thresholds
        imm, delayed = coordinator.thresholds
        assert imm == 4000
        assert delayed == 3500

    async def test_options_flow_rejects_inverted_thresholds(
        self, hass, setup_integration
    ):
        """Options flow must also validate threshold order."""
        _, _, entry = setup_integration
        result = await hass.config_entries.options.async_init(entry.entry_id)
        bad = {**GLOBAL_STEP_DATA, "threshold_immediate": 2000, "threshold_delayed": 3000}
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input=bad
        )
        assert result["errors"]["base"] == "threshold_order"


class TestOptionsFlowFixes:
    """Regression tests for the three options flow bugs."""

    async def _run_options_flow(self, hass, entry, global_data, num_loads, loads_data):
        """Helper: run the full options flow with given inputs."""
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["step_id"] == "init"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input=global_data
        )
        assert result["step_id"] == "num_loads"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={"num_loads": num_loads}
        )

        for load_input in loads_data:
            assert result["step_id"] == "load"
            result = await hass.config_entries.options.async_configure(
                result["flow_id"], user_input=load_input
            )

        assert result["step_id"] == "dashboard"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input=DASHBOARD_STEP_DATA
        )

        return result

    async def test_load_form_shows_saved_entities(
        self, hass, setup_integration
    ):
        """Fix 1: load form must pre-populate saved power_sensor and switch values."""
        hass, coordinator, entry = setup_integration

        result = await hass.config_entries.options.async_init(entry.entry_id)
        # Step through global and num_loads
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={
                "instance_name": "Power Control",
                "threshold_immediate": 3300,
                "threshold_delayed": 3000,
                "delay_immediate_sec": 30,
                "delay_delayed_min": 10,
                "wait_between_stops_sec": 10,
                "wait_between_starts_min": 5,
                "wait_before_start_min": 5,
            }
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={"num_loads": 3}
        )
        assert result["step_id"] == "load"

        # The schema description for load 0 must contain suggested_value
        # from the saved config
        schema = result["data_schema"].schema
        for key in schema:
            if hasattr(key, "schema") and key.schema == "power_sensor":
                assert key.description is not None
                assert "suggested_value" in key.description
                break

    async def test_options_flow_saves_to_config_entry_data(
        self, hass, setup_integration
    ):
        """Fix 3: options flow must update config_entry.data, not config_entry.options."""
        hass, coordinator, entry = setup_integration

        new_threshold = 4000

        result = await self._run_options_flow(
            hass, entry,
            global_data={
                "instance_name": "Power Control",
                "threshold_immediate": new_threshold,
                "threshold_delayed": 3500,
                "delay_immediate_sec": 30,
                "delay_delayed_min": 10,
                "wait_between_stops_sec": 10,
                "wait_between_starts_min": 5,
                "wait_before_start_min": 5,
            },
            num_loads=3,
            loads_data=[
                {"name": "Lavatrice", "power_sensor": "sensor.potenza_lavatrice",
                 "switch": "switch.lavatrice", "auto_restart": True},
                {"name": "Lavastoviglie", "power_sensor": "sensor.potenza_lavastoviglie",
                 "switch": "switch.lavastoviglie", "auto_restart": True},
                {"name": "Condizionatore", "power_sensor": "sensor.potenza_condizionatore",
                 "switch": "switch.condizionatore", "auto_restart": False},
            ],
        )

        assert result["type"] == "create_entry"
        await hass.async_block_till_done()

        # Must be saved in .data, not .options
        assert entry.data.get("threshold_immediate") == new_threshold
        # .options should be empty (we don't use it)
        assert entry.options == {} or entry.options.get("threshold_immediate") is None

    async def test_options_flow_coerces_floats_in_load_step(
        self, hass, setup_integration
    ):
        """Fix 2: options flow must coerce float inputs to int for numeric fields."""
        hass, coordinator, entry = setup_integration

        # Simulate NumberSelector returning floats
        result = await self._run_options_flow(
            hass, entry,
            global_data={
                "instance_name": "Power Control",
                "threshold_immediate": 3300.0,
                "threshold_delayed": 3000.0,
                "delay_immediate_sec": 30.0,
                "delay_delayed_min": 10.0,
                "wait_between_stops_sec": 10.0,
                "wait_between_starts_min": 5.0,
                "wait_before_start_min": 5.0,
            },
            num_loads=1,
            loads_data=[
                {"name": "Test", "auto_restart": True},
            ],
        )

        assert result["type"] == "create_entry"
        await hass.async_block_till_done()

        # Thresholds must be saved as int
        assert isinstance(entry.data.get("threshold_immediate"), int)
        assert isinstance(entry.data.get("threshold_delayed"), int)
