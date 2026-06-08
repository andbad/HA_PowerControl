"""pytest configuration and shared fixtures for Power Control tests."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

pytest_plugins = "pytest_homeassistant_custom_component"

from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.power_control.const import DOMAIN

# ── Shared config data ────────────────────────────────────────────────────────

SAMPLE_DATA = {
    "instance_name": "Power Control",
    "global_power_sensor": "",
    "threshold_immediate": 3300,
    "threshold_delayed": 3000,
    "delay_immediate_sec": 5,
    "delay_delayed_min": 1,
    "wait_between_stops_sec": 1,
    "wait_between_starts_min": 1,
    "wait_before_start_min": 1,
    "notify_entity": "",
    "num_loads": 3,
    "loads": [
        {
            "name": "Lavatrice",
            "power_sensor": "sensor.potenza_lavatrice",
            "switch": "switch.lavatrice",
            "auto_restart": True,
        },
        {
            "name": "Lavastoviglie",
            "power_sensor": "sensor.potenza_lavastoviglie",
            "switch": "switch.lavastoviglie",
            "auto_restart": True,
        },
        {
            "name": "Condizionatore",
            "power_sensor": "sensor.potenza_condizionatore",
            "switch": "switch.condizionatore",
            "auto_restart": False,
        },
    ],
}


# ── Integration-level fixtures (use real hass) ────────────────────────────────

@pytest.fixture
def config_entry(hass):
    """Return a MockConfigEntry already added to hass."""
    entry = MockConfigEntry(domain=DOMAIN, data=SAMPLE_DATA, title="Power Control")
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_integration(hass, config_entry, enable_custom_integrations):
    """Set up Power Control and return (hass, coordinator, entry)."""
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    return hass, coordinator, config_entry


# ── Unit-test fixtures (use mock hass) ────────────────────────────────────────

@pytest.fixture
def mock_config_entry_data():
    """Minimal config_entry data for a 3-load setup."""
    return SAMPLE_DATA.copy()


@pytest.fixture
def mock_config_entry(mock_config_entry_data):
    """Mock ConfigEntry with realistic data."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id_001"
    entry.data = mock_config_entry_data
    return entry


@pytest.fixture
def mock_hass():
    """Mock HomeAssistant instance with controllable state machine."""
    hass = MagicMock()
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=True)
    hass.states.get = MagicMock(return_value=None)
    return hass


def make_state(value: str):
    """Helper: create a mock HA state object."""
    s = MagicMock()
    s.state = value
    return s
