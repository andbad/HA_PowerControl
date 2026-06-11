"""Tests for PowerControlCoordinator stop/start logic."""
from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.power_control.coordinator import (
    PowerControlCoordinator,
    LoadState,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_coordinator(hass, config_entry):
    """Build a coordinator without calling async_config_entry_first_refresh."""
    coord = PowerControlCoordinator.__new__(PowerControlCoordinator)
    coord.hass = hass
    coord.config_entry = config_entry
    coord.enabled = True
    coord.logger = MagicMock()
    coord.name = "power_control_test"
    coord.update_interval = None
    coord._listeners = {}
    coord._unsub_refresh = None
    coord._request_refresh_task = None
    coord._over_immediate_since = None
    coord._over_delayed_since = None
    coord._under_threshold_since = None
    coord._global_sensor_unsub = None
    coord._last_stop_at = None
    coord._last_start_at = None
    coord.data = None
    coord._loads = coord._build_loads()
    return coord


def set_load_power(hass, entity_id: str, watts: float):
    """Configure the mock hass state for a power sensor."""
    state = MagicMock()
    state.state = str(watts)

    original_get = hass.states.get.side_effect or hass.states.get

    def get_state(eid):
        if eid == entity_id:
            return state
        if callable(original_get):
            return original_get(eid)
        return None

    hass.states.get.side_effect = get_state
    return state


def set_switch_state(hass, entity_id: str, value: str):
    """Configure the mock hass state for a switch."""
    state = MagicMock()
    state.state = value
    existing = hass.states.get.side_effect

    def get_state(eid):
        if eid == entity_id:
            return state
        if callable(existing):
            return existing(eid)
        return None

    hass.states.get.side_effect = get_state


# ── LoadState unit tests ──────────────────────────────────────────────────────

class TestLoadState:
    def test_is_configured_both_set(self):
        load = LoadState("Test", "sensor.p", "switch.s", True)
        assert load.is_configured is True

    def test_is_configured_missing_switch(self):
        load = LoadState("Test", "sensor.p", "", True)
        assert load.is_configured is False

    def test_is_configured_missing_sensor(self):
        load = LoadState("Test", "", "switch.s", True)
        assert load.is_configured is False

    def test_is_suspended_when_power_saved(self):
        load = LoadState("Test", "sensor.p", "switch.s", True)
        load.suspended_power = 1500.0
        assert load.is_suspended is True

    def test_is_not_suspended_when_zero(self):
        load = LoadState("Test", "sensor.p", "switch.s", True)
        load.suspended_power = 0.0
        assert load.is_suspended is False


# ── Build loads ───────────────────────────────────────────────────────────────

class TestBuildLoads:
    def test_builds_correct_number(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        assert len(coord.loads) == 3

    def test_load_names(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        names = [l.name for l in coord.loads]
        assert names == ["Lavatrice", "Lavastoviglie", "Condizionatore"]

    def test_auto_restart_flag(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        assert coord.loads[0].auto_restart is True
        assert coord.loads[2].auto_restart is False  # Condizionatore

    def test_rebuild_preserves_suspended_power(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.loads[0].suspended_power = 1800.0
        coord.rebuild_loads()
        assert coord.loads[0].suspended_power == 1800.0

    def test_rebuild_trims_extra_loads(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.loads[0].suspended_power = 999.0
        # Simulate config reduced to 1 load
        mock_config_entry.data = {**mock_config_entry.data, "num_loads": 1,
                                   "loads": [mock_config_entry.data["loads"][0]]}
        coord.rebuild_loads()
        assert len(coord.loads) == 1


# ── Stop logic ────────────────────────────────────────────────────────────────

class TestStopLogic:
    @pytest.mark.asyncio
    async def test_no_action_below_threshold(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        # Power well below both thresholds
        await coord.async_check_and_stop(current_power=2000.0)
        mock_hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_timer_starts_above_immediate_threshold(
        self, mock_hass, mock_config_entry
    ):
        coord = make_coordinator(mock_hass, mock_config_entry)
        # First call: above threshold but timer not expired yet
        await coord.async_check_and_stop(current_power=3500.0)
        assert coord._over_immediate_since is not None
        mock_hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_shed_triggered_after_immediate_delay(
        self, mock_hass, mock_config_entry
    ):
        coord = make_coordinator(mock_hass, mock_config_entry)
        # Simulate timer already expired
        coord._over_immediate_since = datetime.now() - timedelta(seconds=60)

        # Load 2 (Condizionatore, index 2) is drawing 1500 W
        coord.loads[2].current_power = 1500.0
        coord.loads[2].switch_state = "on"

        await coord.async_check_and_stop(current_power=3500.0)

        mock_hass.services.async_call.assert_called_once_with(
            "switch", "turn_off", {"entity_id": "switch.condizionatore"}, blocking=True
        )
        assert coord.loads[2].suspended_power == 1500.0

    @pytest.mark.asyncio
    async def test_shed_skips_idle_loads(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord._over_immediate_since = datetime.now() - timedelta(seconds=60)

        # All loads report zero power (all idle)
        for load in coord.loads:
            load.current_power = 0.0
            load.switch_state = "on"

        await coord.async_check_and_stop(current_power=3500.0)
        mock_hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_shed_skips_already_suspended(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord._over_immediate_since = datetime.now() - timedelta(seconds=60)

        # All loads already suspended
        for load in coord.loads:
            load.current_power = 1000.0
            load.suspended_power = 1000.0
            load.switch_state = "off"

        await coord.async_check_and_stop(current_power=3500.0)
        mock_hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_shed_order_highest_index_first(self, mock_hass, mock_config_entry):
        """Lowest priority (highest index) must be shed first."""
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord._over_immediate_since = datetime.now() - timedelta(seconds=60)

        for i, load in enumerate(coord.loads):
            load.current_power = 1000.0
            load.switch_state = "on"

        await coord.async_check_and_stop(current_power=3500.0)

        # Should have turned off load index 2 (Condizionatore) — highest index
        call_args = mock_hass.services.async_call.call_args
        assert call_args.args[0] == "switch"
        assert call_args.args[1] == "turn_off"
        assert call_args.args[2]["entity_id"] == "switch.condizionatore"

    @pytest.mark.asyncio
    async def test_timer_resets_when_power_drops(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord._over_immediate_since = datetime.now() - timedelta(seconds=10)

        # Power drops back below threshold
        await coord.async_check_and_stop(current_power=2000.0)
        assert coord._over_immediate_since is None

    @pytest.mark.asyncio
    async def test_no_action_when_disabled(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.enabled = False
        coord._over_immediate_since = datetime.now() - timedelta(seconds=60)
        for load in coord.loads:
            load.current_power = 1500.0

        await coord.async_check_and_stop(current_power=4000.0)
        mock_hass.services.async_call.assert_not_called()


# ── Start logic ───────────────────────────────────────────────────────────────

class TestStartLogic:
    @pytest.mark.asyncio
    async def test_no_action_without_suspended_loads(
        self, mock_hass, mock_config_entry
    ):
        coord = make_coordinator(mock_hass, mock_config_entry)
        # No loads suspended
        await coord.async_check_and_start(current_power=1000.0)
        mock_hass.services.async_call.assert_not_called()
        assert coord._under_threshold_since is None

    @pytest.mark.asyncio
    async def test_timer_starts_when_headroom_ok(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.loads[1].suspended_power = 800.0   # Lavastoviglie suspended

        # current(1000) + suspended(800) = 1800 < threshold_delayed(3000) → headroom OK
        await coord.async_check_and_start(current_power=1000.0)
        assert coord._under_threshold_since is not None
        mock_hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_restore_when_no_headroom(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.loads[0].suspended_power = 2500.0   # Would push over threshold

        # current(1000) + suspended(2500) = 3500 > threshold_delayed(3000)
        await coord.async_check_and_start(current_power=1000.0)
        assert coord._under_threshold_since is None
        mock_hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_restore_triggered_after_wait(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.loads[0].suspended_power = 800.0   # Lavatrice

        # Timer already expired
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        await coord.async_check_and_start(current_power=1000.0)

        mock_hass.services.async_call.assert_called_once_with(
            "switch", "turn_on", {"entity_id": "switch.lavatrice"}, blocking=True
        )
        assert coord.loads[0].suspended_power == 0.0

    @pytest.mark.asyncio
    async def test_restore_order_lowest_index_first(self, mock_hass, mock_config_entry):
        """Highest priority (index 0) must be restored first."""
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.loads[0].suspended_power = 800.0
        coord.loads[1].suspended_power = 800.0
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        await coord.async_check_and_start(current_power=500.0)

        call_args = mock_hass.services.async_call.call_args
        assert call_args.args[0] == "switch"
        assert call_args.args[1] == "turn_on"
        assert call_args.args[2]["entity_id"] == "switch.lavatrice"

    @pytest.mark.asyncio
    async def test_restore_skips_keep_off(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.loads[0].suspended_power = 800.0
        coord.loads[0].keep_off = True
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        await coord.async_check_and_start(current_power=500.0)

        mock_hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_restore_skips_auto_restart_false_preserves_suspended(
        self, mock_hass, mock_config_entry
    ):
        coord = make_coordinator(mock_hass, mock_config_entry)
        # Condizionatore (index 2) has auto_restart=False
        coord.loads[2].suspended_power = 1500.0
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        await coord.async_check_and_start(current_power=500.0)

        mock_hass.services.async_call.assert_not_called()
        # suspended_power must NOT be cleared — auto_restart=False means keep it suspended
        assert coord.loads[2].suspended_power == 1500.0

    @pytest.mark.asyncio
    async def test_restore_skips_keep_off_restores_next(
        self, mock_hass, mock_config_entry
    ):
        """Load with keep_off=True is skipped; the next eligible load is restored."""
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.loads[0].suspended_power = 800.0
        coord.loads[0].keep_off = True           # blocked — must be skipped
        coord.loads[1].suspended_power = 500.0   # eligible — must be restored
        coord.loads[2].suspended_power = 0.0
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        await coord.async_check_and_start(current_power=100.0)

        call_args = mock_hass.services.async_call.call_args
        assert call_args.args[2]["entity_id"] == "switch.lavastoviglie"

    @pytest.mark.asyncio
    async def test_timer_resets_after_restore(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.loads[0].suspended_power = 800.0
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        await coord.async_check_and_start(current_power=500.0)

        assert coord._under_threshold_since is None


# ── Watchdog ──────────────────────────────────────────────────────────────────

class TestWatchdog:
    def test_clears_suspended_when_switch_back_on(
        self, mock_hass, mock_config_entry
    ):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.loads[0].suspended_power = 1800.0
        coord.loads[0].switch_state = "on"   # user turned it back on

        coord._watchdog_manual_restart()

        assert coord.loads[0].suspended_power == 0.0

    def test_does_not_clear_suspended_when_switch_off(
        self, mock_hass, mock_config_entry
    ):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.loads[0].suspended_power = 1800.0
        coord.loads[0].switch_state = "off"

        coord._watchdog_manual_restart()

        assert coord.loads[0].suspended_power == 1800.0


# ── reset helpers ─────────────────────────────────────────────────────────────

class TestResetHelpers:
    def test_reset_all_suspended(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        for load in coord.loads:
            load.suspended_power = 999.0
        coord.reset_all_suspended()
        assert all(l.suspended_power == 0.0 for l in coord.loads)

    def test_reset_single_load(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.loads[1].suspended_power = 500.0
        coord.reset_load_suspended(1)
        assert coord.loads[1].suspended_power == 0.0
        assert coord.loads[0].suspended_power == 0.0  # others untouched

    def test_reset_out_of_range_is_safe(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.reset_load_suspended(99)  # should not raise


# ── Global sensor listener ────────────────────────────────────────────────────

class TestGlobalSensorListener:
    def test_listener_registered_when_sensor_configured(
        self, mock_hass, mock_config_entry
    ):
        """setup_global_sensor_listener registers a listener when sensor is set."""
        mock_config_entry.data = {
            **mock_config_entry.data,
            "global_power_sensor": "sensor.shelly_em",
        }
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord._global_sensor_unsub = None

        unsub_mock = MagicMock()
        with patch(
            "custom_components.power_control.coordinator.async_track_state_change",
            return_value=unsub_mock,
        ) as track_mock:
            coord.setup_global_sensor_listener()

        track_mock.assert_called_once()
        # First positional arg is hass, second is the entity_id
        assert track_mock.call_args.args[1] == "sensor.shelly_em"
        assert coord._global_sensor_unsub is unsub_mock

    def test_listener_not_registered_without_sensor(
        self, mock_hass, mock_config_entry
    ):
        """No listener when global_power_sensor is empty."""
        mock_config_entry.data = {
            **mock_config_entry.data,
            "global_power_sensor": "",
        }
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord._global_sensor_unsub = None

        with patch(
            "custom_components.power_control.coordinator.async_track_state_change",
        ) as track_mock:
            coord.setup_global_sensor_listener()

        track_mock.assert_not_called()
        assert coord._global_sensor_unsub is None

    def test_previous_listener_cancelled_on_re_register(
        self, mock_hass, mock_config_entry
    ):
        """Re-calling setup cancels the old listener before registering new one."""
        mock_config_entry.data = {
            **mock_config_entry.data,
            "global_power_sensor": "sensor.shelly_em",
        }
        coord = make_coordinator(mock_hass, mock_config_entry)
        old_unsub = MagicMock()
        coord._global_sensor_unsub = old_unsub

        with patch(
            "custom_components.power_control.coordinator.async_track_state_change",
            return_value=MagicMock(),
        ):
            coord.setup_global_sensor_listener()

        old_unsub.assert_called_once()

    def test_async_shutdown_cancels_listener(self, mock_hass, mock_config_entry):
        """async_shutdown calls the unsub callback and clears it."""
        coord = make_coordinator(mock_hass, mock_config_entry)
        unsub = MagicMock()
        coord._global_sensor_unsub = unsub

        coord.async_shutdown()

        unsub.assert_called_once()
        assert coord._global_sensor_unsub is None

    def test_async_shutdown_safe_without_listener(
        self, mock_hass, mock_config_entry
    ):
        """async_shutdown is a no-op when no listener is registered."""
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord._global_sensor_unsub = None
        coord.async_shutdown()  # must not raise

    @pytest.mark.asyncio
    async def test_sensor_change_triggers_refresh(
        self, mock_hass, mock_config_entry
    ):
        """When the global sensor changes, async_request_refresh is scheduled."""
        mock_config_entry.data = {
            **mock_config_entry.data,
            "global_power_sensor": "sensor.shelly_em",
        }
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord._global_sensor_unsub = None

        captured_callback = None

        def capture_track(hass, entity_id, action):
            nonlocal captured_callback
            captured_callback = action
            return MagicMock()

        with patch(
            "custom_components.power_control.coordinator.async_track_state_change",
            side_effect=capture_track,
        ):
            coord.setup_global_sensor_listener()

        assert captured_callback is not None

        # Simulate a sensor state change
        new_state = MagicMock()
        new_state.state = "2500"
        def _create_task(coro):
            coro.close()  # prevent "coroutine never awaited" ResourceWarning
        mock_hass.async_create_task = MagicMock(side_effect=_create_task)

        captured_callback("sensor.shelly_em", None, new_state)

        mock_hass.async_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_sensor_change_ignored_when_unavailable(
        self, mock_hass, mock_config_entry
    ):
        """Unavailable/unknown sensor states do not trigger a refresh."""
        mock_config_entry.data = {
            **mock_config_entry.data,
            "global_power_sensor": "sensor.shelly_em",
        }
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord._global_sensor_unsub = None

        captured_callback = None

        def capture_track(hass, entity_id, action):
            nonlocal captured_callback
            captured_callback = action
            return MagicMock()

        with patch(
            "custom_components.power_control.coordinator.async_track_state_change",
            side_effect=capture_track,
        ):
            coord.setup_global_sensor_listener()

        mock_hass.async_create_task = MagicMock()

        for bad_state in ("unavailable", "unknown", None):
            new_state = MagicMock() if bad_state else None
            if new_state:
                new_state.state = bad_state
            captured_callback("sensor.shelly_em", None, new_state)

        mock_hass.async_create_task.assert_not_called()


# ── Cooldown mechanism ────────────────────────────────────────────────────────

class TestCooldown:
    """Verify that stop/start cooldowns work via timestamps, not asyncio.sleep."""

    @pytest.mark.asyncio
    async def test_stop_cooldown_blocks_second_shed(
        self, mock_hass, mock_config_entry
    ):
        """A second shed within wait_between_stops_sec is skipped."""
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord._over_immediate_since = datetime.now() - timedelta(seconds=60)
        for load in coord.loads:
            load.current_power = 1500.0
            load.switch_state = "on"

        # First shed — succeeds and sets _last_stop_at
        await coord.async_check_and_stop(current_power=4000.0)
        assert coord._last_stop_at is not None
        first_call_count = mock_hass.services.async_call.call_count

        # Second shed immediately after — blocked by cooldown
        await coord.async_check_and_stop(current_power=4000.0)
        assert mock_hass.services.async_call.call_count == first_call_count

    @pytest.mark.asyncio
    async def test_stop_cooldown_allows_shed_after_elapsed(
        self, mock_hass, mock_config_entry
    ):
        """A shed is allowed after wait_between_stops_sec have elapsed."""
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord._over_immediate_since = datetime.now() - timedelta(seconds=60)
        # Simulate last stop happened more than wait_sec ago
        coord._last_stop_at = datetime.now() - timedelta(seconds=999)
        coord.loads[2].current_power = 1500.0
        coord.loads[2].switch_state = "on"

        await coord.async_check_and_stop(current_power=4000.0)
        mock_hass.services.async_call.assert_called()

    @pytest.mark.asyncio
    async def test_start_cooldown_blocks_second_restore(
        self, mock_hass, mock_config_entry
    ):
        """A second restore within wait_between_starts_min is skipped."""
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.loads[0].suspended_power = 800.0
        coord.loads[1].suspended_power = 800.0
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        # First restore — succeeds and sets _last_start_at
        await coord.async_check_and_start(current_power=100.0)
        assert coord._last_start_at is not None
        assert coord.loads[0].suspended_power == 0.0  # load 0 was restored
        first_call_count = mock_hass.services.async_call.call_count

        # Reset timer to simulate enough time passed for threshold
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        # Second restore immediately after — blocked by cooldown
        await coord.async_check_and_start(current_power=100.0)
        assert mock_hass.services.async_call.call_count == first_call_count

    @pytest.mark.asyncio
    async def test_start_cooldown_allows_restore_after_elapsed(
        self, mock_hass, mock_config_entry
    ):
        """A restore is allowed after wait_between_starts_min have elapsed."""
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.loads[0].suspended_power = 800.0
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)
        # Simulate last start happened long ago
        coord._last_start_at = datetime.now() - timedelta(minutes=999)

        await coord.async_check_and_start(current_power=100.0)
        mock_hass.services.async_call.assert_called()

    def test_reset_all_suspended_clears_cooldowns(
        self, mock_hass, mock_config_entry
    ):
        """Disabling resets both cooldown timestamps."""
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord._last_stop_at = datetime.now()
        coord._last_start_at = datetime.now()

        coord.reset_all_suspended()

        assert coord._last_stop_at is None
        assert coord._last_start_at is None

    @pytest.mark.asyncio
    async def test_coordinator_does_not_block_during_cooldown(
        self, mock_hass, mock_config_entry
    ):
        """_async_update_data completes immediately even while cooldown is active.

        This is the core regression test: previously asyncio.sleep() would have
        blocked the coordinator for the full cooldown duration.
        """
        import time
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.enabled = True
        # Set a very long cooldown to ensure it would have blocked
        coord._last_stop_at = datetime.now()
        coord._last_start_at = datetime.now()

        # Patch the update method dependencies
        coord._refresh_load_states = AsyncMock()
        coord._read_global_power = MagicMock(return_value=5000.0)
        coord._watchdog_manual_restart = MagicMock()

        start = time.monotonic()
        # Call stop/start directly (simulating what _async_update_data does)
        await coord.async_check_and_stop(current_power=5000.0)
        await coord.async_check_and_start(current_power=5000.0)
        elapsed = time.monotonic() - start

        # Should complete in milliseconds, not seconds
        assert elapsed < 0.5, f"Coordinator blocked for {elapsed:.2f}s — cooldown not using timestamp"
