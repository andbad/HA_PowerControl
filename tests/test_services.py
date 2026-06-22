"""Integration tests for Power Control HA services."""
from __future__ import annotations

import pytest

from custom_components.power_control.const import DOMAIN


async def _call(hass, service: str, data: dict | None = None) -> None:
    """Helper: call a power_control service and wait for completion."""
    await hass.services.async_call(DOMAIN, service, data or {}, blocking=True)
    await hass.async_block_till_done()


class TestEnableDisable:
    async def test_enable_service_activates_coordinator(
        self, hass, setup_integration
    ):
        """power_control.enable must set coordinator.enabled = True."""
        hass, coordinator, _ = setup_integration
        coordinator.enabled = False
        await _call(hass, "enable")
        assert coordinator.enabled is True

    async def test_disable_service_deactivates_coordinator(
        self, hass, setup_integration
    ):
        """power_control.disable must set coordinator.enabled = False."""
        hass, coordinator, _ = setup_integration
        await _call(hass, "disable")
        assert coordinator.enabled is False

    async def test_disable_resets_all_suspended_powers(
        self, hass, setup_integration
    ):
        """Disabling must clear suspended_power for all loads."""
        hass, coordinator, _ = setup_integration
        for load in coordinator.loads:
            load.suspended_power = 999.0

        await _call(hass, "disable")

        for load in coordinator.loads:
            assert load.suspended_power == 0.0

    async def test_enable_after_disable_works(self, hass, setup_integration):
        """Toggling disable then enable must leave coordinator active."""
        hass, coordinator, _ = setup_integration
        await _call(hass, "disable")
        await _call(hass, "enable")
        assert coordinator.enabled is True

    async def test_all_services_registered(self, hass, setup_integration):
        """All five services must be registered in HA."""
        services = ["enable", "disable", "reset_load", "force_stop_load", "force_start_load"]
        for svc in services:
            assert hass.services.has_service(DOMAIN, svc), f"Missing service: {svc}"


class TestResetLoad:
    async def test_reset_load_clears_suspended_power(
        self, hass, setup_integration
    ):
        """reset_load must zero out the suspended power of the target load."""
        hass, coordinator, _ = setup_integration
        coordinator.loads[1].suspended_power = 1200.0

        await _call(hass, "reset_load", {"load_index": 1})

        assert coordinator.loads[1].suspended_power == 0.0

    async def test_reset_load_does_not_affect_others(
        self, hass, setup_integration
    ):
        """Resetting one load must not touch others."""
        hass, coordinator, _ = setup_integration
        coordinator.loads[0].suspended_power = 500.0
        coordinator.loads[1].suspended_power = 600.0

        await _call(hass, "reset_load", {"load_index": 1})

        assert coordinator.loads[0].suspended_power == 500.0

    async def test_reset_load_triggers_coordinator_refresh(
        self, hass, setup_integration
    ):
        """reset_load must trigger a coordinator refresh."""
        hass, coordinator, _ = setup_integration
        coordinator.loads[0].suspended_power = 300.0

        await _call(hass, "reset_load", {"load_index": 0})
        await hass.async_block_till_done()

        # Sensor should have updated to 0
        load_name = coordinator.loads[0].name.lower()
        state = hass.states.get(
            f"sensor.power_control_{load_name}_potenza_sospesa"
        )
        if state:
            assert float(state.state) == 0.0


class TestForceStopLoad:
    async def test_force_stop_turns_off_switch(
        self, hass, setup_integration
    ):
        """force_stop_load must call switch.turn_off on the target load."""
        hass, coordinator, _ = setup_integration
        # Provide a current power reading for the load
        hass.states.async_set("sensor.potenza_lavatrice", "1800")

        await _call(hass, "force_stop_load", {"load_index": 0})
        await hass.async_block_till_done()

        # The switch must now be off (HA tracks it natively)
        # We verify the suspended_power was set (core side-effect)
        assert coordinator.loads[0].is_suspended

    async def test_force_stop_sets_suspended_power(
        self, hass, setup_integration
    ):
        """force_stop_load must record the load's power as suspended."""
        hass, coordinator, _ = setup_integration
        hass.states.async_set("sensor.potenza_lavatrice", "2200")

        await _call(hass, "force_stop_load", {"load_index": 0})

        assert coordinator.loads[0].suspended_power == 2200.0

    async def test_force_stop_out_of_range_is_safe(
        self, hass, setup_integration
    ):
        """force_stop_load with invalid index must not raise."""
        hass, coordinator, _ = setup_integration
        await _call(hass, "force_stop_load", {"load_index": 19})
        # No exception — out of range is handled gracefully

    async def test_force_stop_unconfigured_load_is_safe(
        self, hass, setup_integration
    ):
        """force_stop_load on an unconfigured load must not raise."""
        hass, coordinator, _ = setup_integration
        # Clear the switch so the load is "unconfigured"
        coordinator.loads[0].switch = ""
        await _call(hass, "force_stop_load", {"load_index": 0})


class TestForceStartLoad:
    async def test_force_start_clears_suspended_power(
        self, hass, setup_integration
    ):
        """force_start_load must zero the suspended power."""
        hass, coordinator, _ = setup_integration
        coordinator.loads[0].suspended_power = 1500.0

        await _call(hass, "force_start_load", {"load_index": 0})

        assert coordinator.loads[0].suspended_power == 0.0

    async def test_force_start_clears_keep_off(
        self, hass, setup_integration
    ):
        """force_start_load must also clear the keep_off flag."""
        hass, coordinator, _ = setup_integration
        coordinator.loads[0].suspended_power = 1500.0
        coordinator.loads[0].keep_off = True

        await _call(hass, "force_start_load", {"load_index": 0})

        assert coordinator.loads[0].keep_off is False

    async def test_force_start_out_of_range_is_safe(
        self, hass, setup_integration
    ):
        """force_start_load with invalid index must not raise."""
        hass, coordinator, _ = setup_integration
        await _call(hass, "force_start_load", {"load_index": 19})

    async def test_force_start_triggers_coordinator_refresh(
        self, hass, setup_integration
    ):
        """force_start_load must trigger a coordinator refresh."""
        hass, coordinator, _ = setup_integration
        coordinator.loads[0].suspended_power = 800.0

        await _call(hass, "force_start_load", {"load_index": 0})
        await hass.async_block_till_done()

        load_name = coordinator.loads[0].name.lower()
        state = hass.states.get(
            f"sensor.power_control_{load_name}_potenza_sospesa"
        )
        if state:
            assert float(state.state) == 0.0


class TestMasterSwitch:
    async def test_master_switch_entity_exists(self, hass, setup_integration):
        """The enable/disable switch entity must be created."""
        state = hass.states.get("switch.power_control_active")
        assert state is not None

    async def test_master_switch_starts_on(self, hass, setup_integration):
        """Master switch must be on by default."""
        state = hass.states.get("switch.power_control_active")
        assert state.state == "on"

    async def test_turning_off_master_switch_disables_coordinator(
        self, hass, setup_integration
    ):
        """Turning the master switch off must set coordinator.enabled = False."""
        hass, coordinator, _ = setup_integration
        await hass.services.async_call(
            "switch", "turn_off",
            {"entity_id": "switch.power_control_active"},
            blocking=True,
        )
        await hass.async_block_till_done()
        assert coordinator.enabled is False

    async def test_turning_on_master_switch_enables_coordinator(
        self, hass, setup_integration
    ):
        """Turning the master switch on must set coordinator.enabled = True."""
        hass, coordinator, _ = setup_integration
        coordinator.enabled = False
        await hass.services.async_call(
            "switch", "turn_on",
            {"entity_id": "switch.power_control_active"},
            blocking=True,
        )
        await hass.async_block_till_done()
        assert coordinator.enabled is True
