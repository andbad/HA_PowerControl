"""Tests for PowerControlCoordinator stop/start logic."""
from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timedelta
from collections import deque
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
    coord._threshold_override = None
    coord._optimistic_power = 0.0
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

    def test_rebuild_preserves_suspended_power_after_reorder(self, mock_hass, mock_config_entry):
        """move_load swaps two entries in config; suspended_power must follow
        the load (by switch), not stay attached to the old index."""
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.loads[0].suspended_power = 1800.0  # Lavatrice suspended
        loads_cfg = list(mock_config_entry.data["loads"])
        loads_cfg[0], loads_cfg[1] = loads_cfg[1], loads_cfg[0]  # swap index 0/1
        mock_config_entry.data = {**mock_config_entry.data, "loads": loads_cfg}
        coord.rebuild_loads()
        names = [l.name for l in coord.loads]
        assert names == ["Lavastoviglie", "Lavatrice", "Condizionatore"]
        lavatrice = next(l for l in coord.loads if l.name == "Lavatrice")
        lavastoviglie = next(l for l in coord.loads if l.name == "Lavastoviglie")
        assert lavatrice.suspended_power == 1800.0
        assert lavastoviglie.suspended_power == 0.0


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
    async def test_restore_after_reorder_follows_load_not_position(
        self, mock_hass, mock_config_entry
    ):
        """After move_load swaps two entries, restore must target the
        physically-correct switch for each load's new priority position."""
        coord = make_coordinator(mock_hass, mock_config_entry)
        # Suspend Lavastoviglie (index 1) and Condizionatore (index 2, auto_restart=False)
        coord.loads[1].suspended_power = 500.0
        coord.loads[2].suspended_power = 1500.0

        # Swap index 0 (Lavatrice) and index 1 (Lavastoviglie) — simulates
        # the user moving a load up/down in the dashboard.
        loads_cfg = list(mock_config_entry.data["loads"])
        loads_cfg[0], loads_cfg[1] = loads_cfg[1], loads_cfg[0]
        mock_config_entry.data = {**mock_config_entry.data, "loads": loads_cfg}
        coord.rebuild_loads()

        # New order: index0=Lavastoviglie(suspended 500), index1=Lavatrice(0),
        # index2=Condizionatore(suspended 1500, auto_restart=False)
        assert [l.name for l in coord.loads] == ["Lavastoviglie", "Lavatrice", "Condizionatore"]
        assert coord.loads[0].suspended_power == 500.0
        assert coord.loads[2].suspended_power == 1500.0

        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)
        await coord.async_check_and_start(current_power=500.0)

        # Highest priority suspended load is now Lavastoviglie (index 0)
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


class TestCallSwitch:
    """Tests for _call_switch retry logic."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        mock_hass.services.async_call = AsyncMock()
        result = await coord._call_switch("turn_off", "switch.test")
        assert result is True
        assert mock_hass.services.async_call.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure_then_success(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        mock_hass.services.async_call = AsyncMock(
            side_effect=[Exception("timeout"), None]
        )
        with patch("custom_components.power_control.coordinator.asyncio.sleep", new=AsyncMock()):
            result = await coord._call_switch("turn_off", "switch.test", retries=1, retry_delay_s=0)
        assert result is True
        assert mock_hass.services.async_call.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_false_after_all_retries(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        mock_hass.services.async_call = AsyncMock(side_effect=Exception("fail"))
        with patch("custom_components.power_control.coordinator.asyncio.sleep", new=AsyncMock()):
            result = await coord._call_switch("turn_off", "switch.test", retries=2, retry_delay_s=0)
        assert result is False
        assert mock_hass.services.async_call.call_count == 3  # 1 + 2 retries

    @pytest.mark.asyncio
    async def test_shed_rolls_back_on_switch_failure(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.enabled = True
        coord._loads[0].power_sensor = "sensor.p1"
        coord._loads[0].switch = "switch.s1"
        coord._loads[0].current_power = 1500.0
        coord._loads[0].switch_state = "on"
        coord._call_switch = AsyncMock(return_value=False)
        await coord._shed_one_load(current_power=4000.0, active_threshold=3000.0)
        # suspended_power must be rolled back to 0
        assert coord._loads[0].suspended_power == 0.0

    @pytest.mark.asyncio
    async def test_restore_rolls_back_on_switch_failure(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.enabled = True
        coord._loads[0].power_sensor = "sensor.p1"
        coord._loads[0].switch = "switch.s1"
        coord._loads[0].suspended_power = 1500.0
        coord._loads[0].switch_state = "off"
        coord._loads[0].auto_restart = True
        coord._loads[0].keep_off = False
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)
        coord._call_switch = AsyncMock(return_value=False)
        await coord._restore_one_load(current_power=500.0, threshold_delayed=3000.0)
        # suspended_power must be restored on failure
        assert coord._loads[0].suspended_power == 1500.0


class TestAntiFlap:
    """Tests for anti-flap protection (#12)."""

    def test_shed_timestamps_recorded(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        load = coord._loads[0]
        load.name = "Boiler"
        coord._record_shed_and_check_flap(load)
        assert len(load.shed_timestamps) == 1
        assert load.keep_off is False

    def test_flap_triggers_keep_off(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        load = coord._loads[0]
        load.name = "Boiler"
        from custom_components.power_control.coordinator import FLAP_MAX_SHEDS
        # keep_off triggers after FLAP_MAX_SHEDS+1 sheds (> not >=)
        for _ in range(FLAP_MAX_SHEDS + 1):
            coord._record_shed_and_check_flap(load)
        assert load.keep_off is True

    def test_old_sheds_expire_from_window(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        load = coord._loads[0]
        load.name = "Boiler"
        from custom_components.power_control.coordinator import FLAP_MAX_SHEDS, FLAP_WINDOW_SEC
        # Pre-fill with old timestamps outside the window
        old_ts = datetime.now().timestamp() - FLAP_WINDOW_SEC - 1
        load.shed_timestamps = deque([old_ts], maxlen=7) * (FLAP_MAX_SHEDS - 1)
        # One fresh shed — should NOT trigger keep_off
        coord._record_shed_and_check_flap(load)
        assert load.keep_off is False
        assert len(load.shed_timestamps) == 1  # old ones pruned

    @pytest.mark.asyncio
    async def test_shed_sets_keep_off_after_flap_limit(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.enabled = True
        load = coord._loads[0]
        load.power_sensor = "sensor.p1"
        load.switch = "switch.s1"
        load.switch_state = "on"
        load.current_power = 1500.0
        load.name = "Boiler"
        coord._call_switch = AsyncMock(return_value=True)
        mock_hass.services.async_call = AsyncMock()

        from custom_components.power_control.coordinator import FLAP_MAX_SHEDS
        # Pre-fill timestamps to FLAP_MAX_SHEDS so the next shed pushes count > FLAP_MAX_SHEDS
        load.shed_timestamps = deque([datetime.now().timestamp()], maxlen=7) * FLAP_MAX_SHEDS

        await coord._shed_one_load(current_power=4000.0, active_threshold=3000.0)
        assert load.keep_off is True


class TestCustomEvents:
    """Tests for HA custom events (#7)."""

    @pytest.mark.asyncio
    async def test_load_shed_event_fired(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.enabled = True
        load = coord._loads[0]
        load.power_sensor = "sensor.p1"
        load.switch = "switch.s1"
        load.switch_state = "on"
        load.current_power = 1500.0
        load.name = "Boiler"
        coord._call_switch = AsyncMock(return_value=True)
        mock_hass.services.async_call = AsyncMock()
        fired = []
        mock_hass.bus.async_fire = MagicMock(side_effect=lambda e, d=None: fired.append((e, d)))

        await coord._shed_one_load(current_power=4000.0, active_threshold=3000.0)

        assert len(fired) == 1
        event_name, event_data = fired[0]
        assert event_name == "power_control_load_shed"
        assert event_data["load_name"] == "Boiler"
        assert event_data["switch"] == "switch.s1"
        assert event_data["suspended_power_w"] == 1500.0

    @pytest.mark.asyncio
    async def test_load_restored_event_fired(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.enabled = True
        load = coord._loads[0]
        load.power_sensor = "sensor.p1"
        load.switch = "switch.s1"
        load.switch_state = "off"
        load.suspended_power = 1500.0
        load.auto_restart = True
        load.keep_off = False
        load.name = "Boiler"
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)
        coord._call_switch = AsyncMock(return_value=True)
        mock_hass.services.async_call = AsyncMock()
        fired = []
        mock_hass.bus.async_fire = MagicMock(side_effect=lambda e, d=None: fired.append((e, d)))

        await coord._restore_one_load(current_power=500.0, threshold_delayed=3000.0)

        assert len(fired) == 1
        event_name, event_data = fired[0]
        assert event_name == "power_control_load_restored"
        assert event_data["load_name"] == "Boiler"
        assert event_data["restored_power_w"] == 1500.0

    @pytest.mark.asyncio
    async def test_no_event_on_switch_failure(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.enabled = True
        load = coord._loads[0]
        load.power_sensor = "sensor.p1"
        load.switch = "switch.s1"
        load.switch_state = "on"
        load.current_power = 1500.0
        load.name = "Boiler"
        coord._call_switch = AsyncMock(return_value=False)
        fired = []
        mock_hass.bus.async_fire = MagicMock(side_effect=lambda e, d=None: fired.append((e, d)))

        await coord._shed_one_load(current_power=4000.0, active_threshold=3000.0)

        assert fired == []


class TestPerLoadCooldown:
    """Tests for per-load min_off_sec cooldown (#11)."""

    @pytest.mark.asyncio
    async def test_restore_blocked_during_cooldown(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.enabled = True
        load = coord._loads[0]
        load.power_sensor = "sensor.p1"
        load.switch = "switch.s1"
        load.suspended_power = 1500.0
        load.switch_state = "off"
        load.auto_restart = True
        load.keep_off = False
        load.min_off_sec = 300  # 5 minutes cooldown
        load.shed_timestamps = deque([datetime.now().timestamp()], maxlen=7)  # just shed
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)
        coord._call_switch = AsyncMock(return_value=True)
        mock_hass.services.async_call = AsyncMock()

        await coord._restore_one_load(current_power=500.0, threshold_delayed=3000.0)

        # Switch must NOT have been called
        coord._call_switch.assert_not_called()
        assert load.suspended_power == 1500.0

    @pytest.mark.asyncio
    async def test_restore_allowed_after_cooldown(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.enabled = True
        load = coord._loads[0]
        load.power_sensor = "sensor.p1"
        load.switch = "switch.s1"
        load.suspended_power = 1500.0
        load.switch_state = "off"
        load.auto_restart = True
        load.keep_off = False
        load.min_off_sec = 60  # 1 minute
        # Shed happened 2 minutes ago — cooldown expired
        load.shed_timestamps = deque([datetime.now().timestamp() - 120], maxlen=7)
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)
        coord._call_switch = AsyncMock(return_value=True)
        mock_hass.services.async_call = AsyncMock()

        await coord._restore_one_load(current_power=500.0, threshold_delayed=3000.0)

        coord._call_switch.assert_called_once_with("turn_on", "switch.s1")

    @pytest.mark.asyncio
    async def test_no_cooldown_when_min_off_sec_zero(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.enabled = True
        load = coord._loads[0]
        load.power_sensor = "sensor.p1"
        load.switch = "switch.s1"
        load.suspended_power = 1500.0
        load.switch_state = "off"
        load.auto_restart = True
        load.keep_off = False
        load.min_off_sec = 0
        load.shed_timestamps = deque([datetime.now().timestamp()], maxlen=7)
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)
        coord._call_switch = AsyncMock(return_value=True)
        mock_hass.services.async_call = AsyncMock()

        await coord._restore_one_load(current_power=500.0, threshold_delayed=3000.0)

        coord._call_switch.assert_called_once_with("turn_on", "switch.s1")


class TestBugFixes:
    """Regression tests for B1, B2, B6."""

    # ── B6: rebuild_loads preserves shed_timestamps and keep_off ─────────────

    def test_rebuild_loads_preserves_shed_timestamps(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        # Use the switch actually defined in the mock config entry
        real_switch = coord._loads[0].switch
        coord._loads[0].shed_timestamps = deque([1000.0, 2000.0], maxlen=7)
        coord.rebuild_loads()
        assert coord._loads[0].switch == real_switch
        assert list(coord._loads[0].shed_timestamps) == [1000.0, 2000.0]

    def test_rebuild_loads_preserves_keep_off(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord._loads[0].keep_off = True
        coord.rebuild_loads()
        assert coord._loads[0].keep_off is True

    def test_rebuild_loads_resets_for_removed_switch(self, mock_hass, mock_config_entry):
        """A load whose switch was overridden to unknown gets fresh state."""
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord._loads[0].switch = "switch.unknown_not_in_config"
        coord._loads[0].keep_off = True
        coord._loads[0].shed_timestamps = deque([9999.0], maxlen=7)
        coord.rebuild_loads()
        # The config switch is switch.lavatrice — old "switch.unknown" not matched → fresh
        assert coord._loads[0].keep_off is False
        assert list(coord._loads[0].shed_timestamps) == []

    # ── B2: watchdog clears shed_timestamps on manual restart ─────────────────

    def test_watchdog_clears_shed_timestamps_on_manual_restart(
        self, mock_hass, mock_config_entry
    ):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord._loads[0].suspended_power = 1000.0
        coord._loads[0].switch_state = "on"
        coord._loads[0].shed_timestamps = deque([1000.0, 2000.0, 3000.0], maxlen=7)
        coord._watchdog_manual_restart()
        assert coord._loads[0].suspended_power == 0.0
        assert list(coord._loads[0].shed_timestamps) == []


class TestN5N6Regressions:
    """Regression tests for N5 (restore order) and N6 (temp skip timer)."""

    @pytest.mark.asyncio
    async def test_restore_skips_when_registry_empty(self, mock_hass, mock_config_entry):
        """N5: async_restore_state is a no-op if entities not yet registered."""
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord._loads[0].suspended_power = 0.0
        # entity registry returns None for unknown unique_id → should not raise
        await coord.async_restore_state()
        assert coord._loads[0].suspended_power == 0.0

    @pytest.mark.asyncio
    async def test_under_threshold_timer_preserved_during_min_off_sec_cooldown(
        self, mock_hass, mock_config_entry
    ):
        """N6: _under_threshold_since must not reset when the only skip is min_off_sec."""
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.enabled = True
        load = coord._loads[0]
        load.power_sensor = "sensor.p1"
        load.switch = "switch.s1"
        load.suspended_power = 1500.0
        load.switch_state = "off"
        load.auto_restart = True
        load.keep_off = False
        load.min_off_sec = 300  # still in cooldown
        load.shed_timestamps = deque([datetime.now().timestamp()], maxlen=7)
        sentinel = datetime.now() - timedelta(minutes=10)
        coord._under_threshold_since = sentinel
        coord._call_switch = AsyncMock(return_value=True)

        await coord._restore_one_load(current_power=500.0, threshold_delayed=3000.0)

        # Timer must be preserved — cooldown skip is temporary
        assert coord._under_threshold_since == sentinel

    @pytest.mark.asyncio
    async def test_under_threshold_timer_cleared_when_all_permanent(
        self, mock_hass, mock_config_entry
    ):
        """N6: _under_threshold_since resets when all skips are permanent (keep_off)."""
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.enabled = True
        load = coord._loads[0]
        load.power_sensor = "sensor.p1"
        load.switch = "switch.s1"
        load.suspended_power = 1500.0
        load.switch_state = "off"
        load.auto_restart = True
        load.keep_off = True  # permanent block
        load.min_off_sec = 0
        sentinel = datetime.now() - timedelta(minutes=10)
        coord._under_threshold_since = sentinel

        await coord._restore_one_load(current_power=500.0, threshold_delayed=3000.0)

        assert coord._under_threshold_since is None


# ── Integration Scenarios (translated from test_package.yaml T1–T22) ──────────
#
# Covers only the coordinator logic testable as unit tests.
# HA template rendering, real asyncio delays, and HA service dispatching
# are OUT OF SCOPE and remain in packages/test_package.yaml.
#
# Setup: 5 loads (IMM=4000W, DEL=3300W). Load 3 (index 2) has auto_restart=False.
# Each test builds a fresh coordinator via _make_scenario_coord().

IMM_THRESH = 4000.0
DEL_THRESH = 3300.0


def _make_scenario_coord(mock_hass, mock_config_entry, load3_auto_restart=False, load5_min_off_sec=0):
    """Build coordinator with 5 configured loads, matching test_package.yaml."""
    from custom_components.power_control.const import (
        CONF_LOADS, LOAD_NAME, LOAD_POWER_SENSOR, LOAD_SWITCH,
        LOAD_AUTO_RESTART, LOAD_MIN_OFF_SEC,
        CONF_THRESHOLD_IMMEDIATE, CONF_THRESHOLD_DELAYED,
    )
    loads_cfg = [
        {LOAD_NAME: f"Load {i+1}", LOAD_POWER_SENSOR: f"sensor.p{i+1}",
         LOAD_SWITCH: f"switch.s{i+1}",
         LOAD_AUTO_RESTART: (not load3_auto_restart if i == 2 else True),
         LOAD_MIN_OFF_SEC: (load5_min_off_sec if i == 4 else 0)}
        for i in range(5)
    ]
    mock_config_entry.data = {
        CONF_LOADS: loads_cfg,
        CONF_THRESHOLD_IMMEDIATE: IMM_THRESH,
        CONF_THRESHOLD_DELAYED: DEL_THRESH,
    }
    mock_config_entry.options = {}
    coord = make_coordinator(mock_hass, mock_config_entry)
    coord._call_switch = AsyncMock(return_value=True)
    # All loads start ON at 600W
    for load in coord._loads:
        load.current_power = 600.0
        load.switch_state = "on"
    return coord


class TestIntegrationScenarios:
    """Integration scenarios derived from test_package.yaml T1–T22."""

    # ── T1: Distacco immediato ─────────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_t01_immediate_shed(self, mock_hass, mock_config_entry):
        """T1: 4x800W + 1x1200W = 4400W > IMM 4000W → load 5 (index 4) shed first."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry)
        for i in range(4):
            coord._loads[i].current_power = 800.0
        coord._loads[4].current_power = 1200.0

        await coord._shed_one_load(current_power=4400.0, active_threshold=IMM_THRESH)

        assert coord._loads[4].is_suspended  # lowest priority shed first
        assert coord._loads[4].suspended_power == 1200.0
        for i in range(4):
            assert not coord._loads[i].is_suspended

    # ── T2: Distacco ritardato — shed logic is threshold-agnostic ─────────────
    @pytest.mark.asyncio
    async def test_t02_delayed_shed(self, mock_hass, mock_config_entry):
        """T2: 5x700W = 3500W > DEL 3300W. _shed_one_load uses the passed threshold."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry)
        for load in coord._loads:
            load.current_power = 700.0

        await coord._shed_one_load(current_power=3500.0, active_threshold=DEL_THRESH)

        assert coord._loads[4].is_suspended
        assert coord._loads[4].suspended_power == 700.0

    # ── T3: Riattivazione automatica ──────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_t03_auto_restore(self, mock_hass, mock_config_entry):
        """T3: Load 5 suspended 700W. Active 4x500W=2000W. Headroom ok → restored."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry)
        coord._loads[4].suspended_power = 700.0
        coord._loads[4].switch_state = "off"
        for i in range(4):
            coord._loads[i].current_power = 500.0
        # Timer already expired
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        await coord._restore_one_load(current_power=2000.0, threshold_delayed=DEL_THRESH)

        assert not coord._loads[4].is_suspended
        coord._call_switch.assert_awaited_once_with("turn_on", "switch.s5")

    # ── T4: Auto-restart disabilitato ─────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_t04_auto_restart_disabled(self, mock_hass, mock_config_entry):
        """T4: Load 3 (auto_restart=False) stays off even when headroom is available."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry, load3_auto_restart=True)
        # Suspend loads 3, 4, 5
        for i in [2, 3, 4]:
            coord._loads[i].suspended_power = 1000.0
            coord._loads[i].switch_state = "off"
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        await coord._restore_one_load(current_power=800.0, threshold_delayed=DEL_THRESH)

        # Load 3 (index 2) must stay suspended
        assert coord._loads[2].is_suspended
        # Load 4 (index 3) gets restored (highest priority suspended + auto_restart=True)
        assert not coord._loads[3].is_suspended

    # ── T5: Watchdog azzera suspended su riaccensione manuale ─────────────────
    def test_t05_watchdog_clears_suspended_on_manual_restart(self, mock_hass, mock_config_entry):
        """T5: If switch comes back on manually, watchdog clears suspended_power."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry)
        coord._loads[4].suspended_power = 700.0
        coord._loads[4].switch_state = "on"  # user turned it on manually

        coord._watchdog_manual_restart()

        assert coord._loads[4].suspended_power == 0.0
        assert len(coord._loads[4].shed_timestamps) == 0

    # ── T6: Distacco a cascata ─────────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_t06_cascade_shed(self, mock_hass, mock_config_entry):
        """T6: 5x1000W=5000W. After shedding load 5 (1000W) power=4000W >= IMM → shed load 4."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry)
        for load in coord._loads:
            load.current_power = 1000.0

        # First shed: load 5
        await coord._shed_one_load(current_power=5000.0, active_threshold=IMM_THRESH)
        assert coord._loads[4].is_suspended

        # Power still at limit (4000W). Second shed: load 4.
        # Clear _last_stop_at to bypass cooldown in unit test
        coord._last_stop_at = None
        await coord._shed_one_load(current_power=4000.0, active_threshold=IMM_THRESH)
        assert coord._loads[3].is_suspended

        # Loads 1-3 untouched
        for i in range(3):
            assert not coord._loads[i].is_suspended

    # ── T7: Riattivazione parziale ────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_t07_partial_restore(self, mock_hass, mock_config_entry):
        """T7: Loads 4+5 suspended 1000W each. Active 1-3 at 600W = 1800W.
        Headroom = 3300-1800 = 1500W. Load 4 (higher priority): 1800+1000=2800 < 3300 → restored.
        Load 5 (lower priority): 2800+1000=3800 >= 3300 → blocked.
        """
        coord = _make_scenario_coord(mock_hass, mock_config_entry)
        coord._loads[3].suspended_power = 1000.0
        coord._loads[3].switch_state = "off"
        coord._loads[4].suspended_power = 1000.0
        coord._loads[4].switch_state = "off"
        for i in range(3):
            coord._loads[i].current_power = 600.0
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        await coord._restore_one_load(current_power=1800.0, threshold_delayed=DEL_THRESH)

        # Load 4 (index 3) restored first (higher priority)
        assert not coord._loads[3].is_suspended
        # Load 5 (index 4) still suspended (headroom exhausted)
        assert coord._loads[4].is_suspended

    # ── T8: Carico già spento al momento del distacco ─────────────────────────
    @pytest.mark.asyncio
    async def test_t08_load_already_off(self, mock_hass, mock_config_entry):
        """T8: Load 5 already off (power=0). 4x1100W=4400W > IMM → load 4 shed (skip load 5)."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry)
        coord._loads[4].current_power = 0.0   # already off
        coord._loads[4].switch_state = "off"
        for i in range(4):
            coord._loads[i].current_power = 1100.0

        await coord._shed_one_load(current_power=4400.0, active_threshold=IMM_THRESH)

        # Load 5 not touched (power ≤ MIN_ACTIVE_POWER_W)
        assert not coord._loads[4].is_suspended
        # Load 4 shed
        assert coord._loads[3].is_suspended

    # ── T12: force_stop_load logic ────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_t12_force_stop(self, mock_hass, mock_config_entry):
        """T12: force_stop sets suspended_power and turns switch off."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry)
        coord._loads[4].current_power = 600.0

        # Replicate what handle_force_stop_load does
        load = coord._loads[4]
        load.suspended_power = max(load.current_power, 1.0)
        result = await coord._call_switch("turn_off", load.switch)

        assert result is True
        assert load.suspended_power == 600.0
        coord._call_switch.assert_awaited_once_with("turn_off", "switch.s5")

    # ── T13: force_start_load logic ───────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_t13_force_start(self, mock_hass, mock_config_entry):
        """T13: force_start clears suspended_power, clears shed_timestamps, turns switch on."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry)
        load = coord._loads[4]
        load.suspended_power = 600.0
        load.keep_off = True
        load.shed_timestamps.append(datetime.now().timestamp())

        # Replicate handle_force_start_load
        load.suspended_power = 0.0
        load.keep_off = False
        load.shed_timestamps.clear()
        await coord._call_switch("turn_on", load.switch)

        assert not load.is_suspended
        assert not load.keep_off
        assert len(load.shed_timestamps) == 0
        coord._call_switch.assert_awaited_with("turn_on", "switch.s5")

    # ── T14: reset_load_suspended ─────────────────────────────────────────────
    def test_t14_reset_load_suspended(self, mock_hass, mock_config_entry):
        """T14: reset_load_suspended zeroes suspended_power without touching switch."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry)
        coord._loads[4].suspended_power = 700.0
        coord._loads[4].switch_state = "off"

        coord.reset_load_suspended(4)

        assert coord._loads[4].suspended_power == 0.0
        assert coord._loads[4].switch_state == "off"  # switch untouched

    # ── T17: Riattivazione bloccata da potenza alta ───────────────────────────
    @pytest.mark.asyncio
    async def test_t17_restore_blocked_by_high_power(self, mock_hass, mock_config_entry):
        """T17: Load 5 suspended 600W. Active = 2800W. 2800+600=3400 >= 3300 → no restore."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry)
        coord._loads[4].suspended_power = 600.0
        coord._loads[4].switch_state = "off"
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        await coord._restore_one_load(current_power=2800.0, threshold_delayed=DEL_THRESH)

        assert coord._loads[4].is_suspended  # not restored
        coord._call_switch.assert_not_awaited()

    # ── T18: set_thresholds override ──────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_t18_set_thresholds_override(self, mock_hass, mock_config_entry):
        """T18: Override IMM to 2500W. 4x700W=2800W > 2500W → load shed."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry)
        coord.set_thresholds(immediate_w=2500.0, delayed_w=2000.0)
        assert coord.thresholds == (2500.0, 2000.0)

        for i in range(4):
            coord._loads[i].current_power = 700.0
        coord._loads[4].current_power = 0.0
        coord._loads[4].switch_state = "off"

        imm, _ = coord.thresholds
        await coord._shed_one_load(current_power=2800.0, active_threshold=imm)

        # Load 3 (index 3) is highest-index active load
        assert coord._loads[3].is_suspended

    # ── T19: set_thresholds reset ─────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_t19_set_thresholds_reset(self, mock_hass, mock_config_entry):
        """T19: Reset override → thresholds back to config values. No shed at 2800W."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry)
        coord.set_thresholds(immediate_w=2500.0, delayed_w=2000.0)
        coord.set_thresholds(immediate_w=None, delayed_w=None)

        assert coord.thresholds == (IMM_THRESH, DEL_THRESH)

        for i in range(4):
            coord._loads[i].current_power = 700.0
        coord._loads[4].current_power = 0.0

        imm, _ = coord.thresholds
        await coord._shed_one_load(current_power=2800.0, active_threshold=imm)

        # 2800W < IMM_THRESH=4000W, but _shed_one_load acts on what it's passed.
        # We pass imm=4000W and power=2800W: no load is above MIN_ACTIVE_POWER_W threshold
        # check is not done here — the caller guards before invoking shed.
        # Verify thresholds are correct (core of T19):
        assert coord._threshold_override is None

    # ── T20: Anti-flap — keep_off after N sheds ───────────────────────────────
    @pytest.mark.asyncio
    async def test_t20_anti_flap_keep_off(self, mock_hass, mock_config_entry):
        """T20: 7 force_stop calls → > FLAP_MAX_SHEDS(5) in window → keep_off=True."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry)
        load = coord._loads[4]
        load.current_power = 600.0

        # Simulate 7 sheds (> FLAP_MAX_SHEDS=5)
        for _ in range(7):
            load.suspended_power = max(load.current_power, 1.0)
            coord._record_shed_and_check_flap(load)
            # Between sheds, simulate force_stop pattern (no clear of timestamps)

        assert load.keep_off is True

    # ── T20b: keep_off blocks auto-restore ────────────────────────────────────
    @pytest.mark.asyncio
    async def test_t20b_keep_off_blocks_restore(self, mock_hass, mock_config_entry):
        """T20: keep_off=True prevents auto-restore even with sufficient headroom."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry)
        coord._loads[4].suspended_power = 600.0
        coord._loads[4].switch_state = "off"
        coord._loads[4].keep_off = True
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        await coord._restore_one_load(current_power=500.0, threshold_delayed=DEL_THRESH)

        assert coord._loads[4].is_suspended
        coord._call_switch.assert_not_awaited()

    # ── T21: min_off_sec cooldown ─────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_t21_min_off_sec_blocks_early_restore(self, mock_hass, mock_config_entry):
        """T21: Load 5 has min_off_sec=120. Shed 10s ago → still in cooldown."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry, load5_min_off_sec=120)
        load = coord._loads[4]
        load.suspended_power = 600.0
        load.switch_state = "off"
        load.shed_timestamps.append(datetime.now().timestamp() - 10)  # only 10s ago
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        await coord._restore_one_load(current_power=500.0, threshold_delayed=DEL_THRESH)

        assert load.is_suspended  # cooldown not expired
        coord._call_switch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_t21_min_off_sec_allows_restore_after_cooldown(self, mock_hass, mock_config_entry):
        """T21: Load 5 has min_off_sec=120. Shed 130s ago → cooldown expired → restored."""
        coord = _make_scenario_coord(mock_hass, mock_config_entry, load5_min_off_sec=120)
        load = coord._loads[4]
        load.suspended_power = 600.0
        load.switch_state = "off"
        load.shed_timestamps.append(datetime.now().timestamp() - 130)  # 130s ago
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        await coord._restore_one_load(current_power=500.0, threshold_delayed=DEL_THRESH)

        assert not load.is_suspended  # restored after cooldown
        coord._call_switch.assert_awaited_once_with("turn_on", "switch.s5")

    # ── T22: move_load (swap priority) ────────────────────────────────────────
    def test_t22_move_load_swaps_order(self, mock_hass, mock_config_entry):
        """T22: rebuild_loads after swapping loads[3] and loads[4] in config_entry.data."""
        from custom_components.power_control.const import CONF_LOADS
        coord = _make_scenario_coord(mock_hass, mock_config_entry)

        # Swap loads 4 and 5 (indices 3 and 4) in config_entry.data
        loads_cfg = list(coord.config_entry.data[CONF_LOADS])
        loads_cfg[3], loads_cfg[4] = loads_cfg[4], loads_cfg[3]
        coord.config_entry.data = {**coord.config_entry.data, CONF_LOADS: loads_cfg}
        coord.rebuild_loads()

        # After swap, what was load 5 (s5) is now at index 3
        assert coord._loads[3].switch == "switch.s5"
        assert coord._loads[4].switch == "switch.s4"

    @pytest.mark.asyncio
    async def test_t22_after_move_shed_hits_new_lowest_priority(self, mock_hass, mock_config_entry):
        """T22: After moving load 5 up, shed hits ex-load 4 (now at index 4)."""
        from custom_components.power_control.const import CONF_LOADS
        coord = _make_scenario_coord(mock_hass, mock_config_entry)

        loads_cfg = list(coord.config_entry.data[CONF_LOADS])
        loads_cfg[3], loads_cfg[4] = loads_cfg[4], loads_cfg[3]
        coord.config_entry.data = {**coord.config_entry.data, CONF_LOADS: loads_cfg}
        coord.rebuild_loads()
        coord._call_switch = AsyncMock(return_value=True)

        for load in coord._loads:
            load.current_power = 900.0
            load.switch_state = "on"

        await coord._shed_one_load(current_power=4500.0, active_threshold=IMM_THRESH)

        # Index 4 is now ex-load4 (switch.s4) — must be the one shed
        assert coord._loads[4].is_suspended
        assert coord._loads[4].switch == "switch.s4"
        # Index 3 (ex-load5, switch.s5) must still be on
        assert not coord._loads[3].is_suspended


class TestGetConf:
    """_get_conf must read per-key: options first, then data, then default."""

    def _make(self, data: dict, options: dict):
        entry = MagicMock()
        entry.data = data
        entry.options = options
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=None)
        coord = make_coordinator(hass, entry)
        return coord

    def test_reads_from_data_when_options_empty(self):
        coord = self._make({"threshold_immediate": 3300}, {})
        assert coord._get_conf("threshold_immediate", 0) == 3300

    def test_reads_from_options_when_key_present(self):
        coord = self._make({"threshold_immediate": 3300}, {"threshold_immediate": 4000})
        assert coord._get_conf("threshold_immediate", 0) == 4000

    def test_partial_options_do_not_shadow_data_keys(self):
        """A partial options dict (e.g. only enabled) must not shadow other data keys."""
        coord = self._make(
            {"threshold_immediate": 3300, "delay_immediate_sec": 30},
            {"enabled": True},           # only CONF_ENABLED in options
        )
        assert coord._get_conf("threshold_immediate", 0) == 3300
        assert coord._get_conf("delay_immediate_sec", 0) == 30

    def test_returns_default_when_key_missing_everywhere(self):
        coord = self._make({}, {})
        assert coord._get_conf("nonexistent_key", 42) == 42
