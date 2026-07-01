"""Tests for Power Control switch entity (enabled state persistence)."""
from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.power_control.const import DOMAIN, CONF_ENABLED

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.conftest import SAMPLE_DATA


# ── helpers ───────────────────────────────────────────────────────────────────

async def _setup(hass, enable_custom_integrations, options: dict):
    entry = MockConfigEntry(
        domain=DOMAIN, data=SAMPLE_DATA, options=options, title="PC"
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    return entry, coordinator


# ── tests ─────────────────────────────────────────────────────────────────────

class TestSwitchEnabled:
    @pytest.mark.asyncio
    async def test_fresh_install_defaults_to_enabled(
        self, hass, enable_custom_integrations
    ):
        """No options → coordinator.enabled defaults to True."""
        _, coordinator = await _setup(hass, enable_custom_integrations, options={})
        assert coordinator.enabled is True

    @pytest.mark.asyncio
    async def test_options_enabled_true_sets_coordinator(
        self, hass, enable_custom_integrations
    ):
        """options={enabled: True} → coordinator.enabled is True."""
        _, coordinator = await _setup(
            hass, enable_custom_integrations, options={CONF_ENABLED: True}
        )
        assert coordinator.enabled is True

    @pytest.mark.asyncio
    async def test_options_enabled_false_sets_coordinator(
        self, hass, enable_custom_integrations
    ):
        """options={enabled: False} simulates an upgrade with switch previously OFF."""
        _, coordinator = await _setup(
            hass, enable_custom_integrations, options={CONF_ENABLED: False}
        )
        assert coordinator.enabled is False

    @pytest.mark.asyncio
    async def test_turn_on_persists_to_options(
        self, hass, enable_custom_integrations
    ):
        """Turning on the switch writes enabled=True to config_entry.options."""
        entry, _ = await _setup(
            hass, enable_custom_integrations, options={CONF_ENABLED: False}
        )
        await hass.services.async_call(
            "switch", "turn_on",
            {"entity_id": "switch.power_control_active"},
            blocking=True,
        )
        await hass.async_block_till_done()
        assert entry.options.get(CONF_ENABLED) is True

    @pytest.mark.asyncio
    async def test_turn_off_persists_to_options(
        self, hass, enable_custom_integrations
    ):
        """Turning off the switch writes enabled=False to config_entry.options."""
        entry, _ = await _setup(
            hass, enable_custom_integrations, options={CONF_ENABLED: True}
        )
        await hass.services.async_call(
            "switch", "turn_off",
            {"entity_id": "switch.power_control_active"},
            blocking=True,
        )
        await hass.async_block_till_done()
        assert entry.options.get(CONF_ENABLED) is False
