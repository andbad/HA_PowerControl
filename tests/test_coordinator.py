"""Tests for PowerControlCoordinator stop/start logic."""
from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch, call

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

        with patch("asyncio.sleep", new_callable=AsyncMock):
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

        with patch("asyncio.sleep", new_callable=AsyncMock):
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

        with patch("asyncio.sleep", new_callable=AsyncMock):
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

        with patch("asyncio.sleep", new_callable=AsyncMock):
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

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await coord.async_check_and_start(current_power=500.0)

        mock_hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_restore_skips_auto_restart_false_and_clears_suspended(
        self, mock_hass, mock_config_entry
    ):
        coord = make_coordinator(mock_hass, mock_config_entry)
        # Condizionatore (index 2) has auto_restart=False
        coord.loads[2].suspended_power = 1500.0
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await coord.async_check_and_start(current_power=500.0)

        mock_hass.services.async_call.assert_not_called()
        # suspended_power must be cleared so it no longer blocks headroom
        assert coord.loads[2].suspended_power == 0.0

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

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await coord.async_check_and_start(current_power=100.0)

        call_args = mock_hass.services.async_call.call_args
        assert call_args.args[2]["entity_id"] == "switch.lavastoviglie"

    @pytest.mark.asyncio
    async def test_timer_resets_after_restore(self, mock_hass, mock_config_entry):
        coord = make_coordinator(mock_hass, mock_config_entry)
        coord.loads[0].suspended_power = 800.0
        coord._under_threshold_since = datetime.now() - timedelta(minutes=10)

        with patch("asyncio.sleep", new_callable=AsyncMock):
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
