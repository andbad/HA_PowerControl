"""Tests for dashboard rebuild behavior after options reconfigure."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.power_control.const import DOMAIN, CONF_DASHBOARD_USER_CONTROLLED

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.conftest import SAMPLE_DATA


async def _setup(hass, enable_custom_integrations, user_controlled: bool):
    data = {**SAMPLE_DATA, "create_dashboard": True, CONF_DASHBOARD_USER_CONTROLLED: user_controlled}
    entry = MockConfigEntry(domain=DOMAIN, data=data, options={}, title="PC")
    entry.add_to_hass(hass)
    with patch(
        "custom_components.power_control._async_handle_dashboard_setup",
        return_value=None,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


class TestDashboardRebuildOnReconfigure:
    @pytest.mark.asyncio
    async def test_rebuilds_when_not_user_controlled(
        self, hass, enable_custom_integrations
    ):
        entry = await _setup(hass, enable_custom_integrations, user_controlled=False)

        from custom_components.power_control import _async_update_listener

        with patch(
            "custom_components.power_control.async_rebuild_dashboard"
        ) as mock_rebuild:
            await _async_update_listener(hass, entry)
            mock_rebuild.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_when_user_controlled(
        self, hass, enable_custom_integrations
    ):
        entry = await _setup(hass, enable_custom_integrations, user_controlled=True)

        from custom_components.power_control import _async_update_listener

        with patch(
            "custom_components.power_control.async_rebuild_dashboard"
        ) as mock_rebuild:
            await _async_update_listener(hass, entry)
            mock_rebuild.assert_not_called()
