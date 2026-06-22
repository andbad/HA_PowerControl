"""Integration tests for Power Control sensor entities."""
from __future__ import annotations

import pytest

from homeassistant.const import STATE_UNAVAILABLE


class TestGlobalSensors:
    async def test_all_global_sensors_created(self, hass, setup_integration):
        """All four global sensors must exist after setup."""
        sensors = [
            "sensor.power_control_current_power",
            "sensor.power_control_suspended_power",
            "sensor.power_control_immediate_threshold",
            "sensor.power_control_delayed_threshold",
        ]
        for entity_id in sensors:
            state = hass.states.get(entity_id)
            assert state is not None, f"Missing: {entity_id}"

    async def test_threshold_sensors_match_config(self, hass, setup_integration):
        """Threshold sensors must reflect the configured values."""
        imm = hass.states.get("sensor.power_control_immediate_threshold")
        delayed = hass.states.get("sensor.power_control_delayed_threshold")
        assert float(imm.state) == 3300.0
        assert float(delayed.state) == 3000.0

    async def test_power_sensors_have_watt_unit(self, hass, setup_integration):
        """All power sensors must declare W as unit of measurement."""
        sensors = [
            "sensor.power_control_current_power",
            "sensor.power_control_suspended_power",
        ]
        for entity_id in sensors:
            state = hass.states.get(entity_id)
            assert state.attributes.get("unit_of_measurement") == "W", entity_id

    async def test_power_sensors_have_power_device_class(self, hass, setup_integration):
        """Active power sensors must declare power device class."""
        sensors = [
            "sensor.power_control_current_power",
        ]
        for entity_id in sensors:
            state = hass.states.get(entity_id)
            assert state.attributes.get("device_class") == "power", entity_id

    async def test_current_power_zero_with_no_sensors(self, hass, setup_integration):
        """Without real sensors, current power sums to 0."""
        state = hass.states.get("sensor.power_control_current_power")
        assert float(state.state) == 0.0

    async def test_current_power_sums_load_sensors(
        self, hass, setup_integration
    ):
        """Without a global sensor, current_power = sum of load sensor readings."""
        hass, coordinator, _ = setup_integration

        # Set power readings for two loads
        hass.states.async_set("sensor.potenza_lavatrice", "1200")
        hass.states.async_set("sensor.potenza_lavastoviglie", "800")

        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

        state = hass.states.get("sensor.power_control_current_power")
        assert float(state.state) == 2000.0

    async def test_suspended_power_starts_at_zero(self, hass, setup_integration):
        """Suspended power must be 0 at startup (no loads shed yet)."""
        state = hass.states.get("sensor.power_control_suspended_power")
        assert float(state.state) == 0.0


class TestPerLoadSensors:
    async def test_per_load_sensors_created(self, hass, setup_integration):
        """One suspended-power sensor per configured load must exist."""
        _, coordinator, _ = setup_integration
        for i, load in enumerate(coordinator.loads):
            # Sensor name is derived from load name
            entity_id = f"sensor.power_control_{load.name.lower()}_suspended_power"
            state = hass.states.get(entity_id)
            assert state is not None, f"Missing sensor for load {i}: {entity_id}"

    async def test_per_load_sensor_attributes(self, hass, setup_integration):
        """Per-load sensor must expose expected extra attributes."""
        _, coordinator, _ = setup_integration
        load_name = coordinator.loads[0].name.lower()
        entity_id = f"sensor.power_control_{load_name}_suspended_power"
        state = hass.states.get(entity_id)
        assert state is not None
        attrs = state.attributes
        assert "load_index" in attrs
        assert "current_power_w" in attrs
        assert "switch_state" in attrs
        assert "auto_restart" in attrs
        assert "is_suspended" in attrs

    async def test_per_load_sensor_suspended_starts_zero(
        self, hass, setup_integration
    ):
        """Suspended power for each load starts at 0."""
        _, coordinator, _ = setup_integration
        for load in coordinator.loads:
            entity_id = (
                f"sensor.power_control_{load.name.lower()}_suspended_power"
            )
            state = hass.states.get(entity_id)
            if state:
                assert float(state.state) == 0.0

    async def test_per_load_sensor_reflects_suspended_power(
        self, hass, setup_integration
    ):
        """After coordinator sheds a load, its sensor value updates."""
        hass, coordinator, _ = setup_integration
        # Manually mark load 0 as suspended
        coordinator.loads[0].suspended_power = 1800.0
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

        load_name = coordinator.loads[0].name.lower()
        entity_id = f"sensor.power_control_{load_name}_suspended_power"
        state = hass.states.get(entity_id)
        assert state is not None
        assert float(state.state) == 1800.0


class TestDeviceGrouping:
    async def test_all_entities_share_one_device(
        self, hass, setup_integration, device_registry
    ):
        """All Power Control entities must belong to a single device."""
        from custom_components.power_control.const import DOMAIN
        _, _, entry = setup_integration
        devices = device_registry.devices.get_devices_for_config_entry_id(
            entry.entry_id
        )
        assert len(devices) == 1

    async def test_device_has_correct_name(
        self, hass, setup_integration, device_registry
    ):
        """The device must be named after the instance_name config value."""
        _, _, entry = setup_integration
        devices = device_registry.devices.get_devices_for_config_entry_id(
            entry.entry_id
        )
        device = list(devices)[0]
        assert device.name == "Power Control"


class TestLoadSensorIcon:
    """Tests for dynamic icon badge on per-load sensors (#5).

    Tests use the entity's icon property directly to avoid interference
    from _refresh_load_states overwriting switch_state during async_request_refresh.
    """

    def _get_load_entity(self, hass, coordinator, index=0):
        from custom_components.power_control.sensor import PowerControlLoadSensor
        for entity in hass.states.async_all():
            pass  # just to ensure entities registered
        # Find the entity object via platform entities
        load = coordinator.loads[index]
        from unittest.mock import MagicMock
        entry = MagicMock()
        entry.entry_id = coordinator.config_entry.entry_id
        entity = PowerControlLoadSensor(coordinator, coordinator.config_entry, index)
        return entity

    def test_icon_active(self, hass, setup_integration):
        """Active load (switch on, not suspended) → green plug icon."""
        _, coordinator, _ = setup_integration
        entity = self._get_load_entity(hass, coordinator)
        coordinator.loads[0].switch_state = "on"
        coordinator.loads[0].suspended_power = 0.0
        coordinator.loads[0].keep_off = False
        assert entity.icon == "mdi:power-plug"

    def test_icon_suspended(self, hass, setup_integration):
        """Suspended load → off plug icon."""
        _, coordinator, _ = setup_integration
        entity = self._get_load_entity(hass, coordinator)
        coordinator.loads[0].suspended_power = 1500.0
        coordinator.loads[0].keep_off = False
        assert entity.icon == "mdi:power-plug-off"

    def test_icon_keep_off(self, hass, setup_integration):
        """Blocked load (keep_off=True) → cancel icon."""
        _, coordinator, _ = setup_integration
        entity = self._get_load_entity(hass, coordinator)
        coordinator.loads[0].keep_off = True
        assert entity.icon == "mdi:cancel"

    def test_icon_unavailable(self, hass, setup_integration):
        """Unavailable switch → outline plug icon."""
        _, coordinator, _ = setup_integration
        entity = self._get_load_entity(hass, coordinator)
        coordinator.loads[0].switch_state = "unavailable"
        coordinator.loads[0].suspended_power = 0.0
        coordinator.loads[0].keep_off = False
        assert entity.icon == "mdi:power-plug-outline"
