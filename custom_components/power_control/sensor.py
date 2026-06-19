"""Integration tests for Power Control sensor entities."""
from __future__ import annotations

import pytest

from homeassistant.const import STATE_UNAVAILABLE


class TestGlobalSensors:
    async def test_all_global_sensors_created(self, hass, setup_integration):
        """All four global sensors must exist after setup."""
        sensors = [
            "sensor.power_control_potenza_attuale",
            "sensor.power_control_potenza_sospesa",
            "sensor.power_control_soglia_distacco_immediato",
            "sensor.power_control_soglia_distacco_ritardato",
        ]
        for entity_id in sensors:
            state = hass.states.get(entity_id)
            assert state is not None, f"Missing: {entity_id}"

    async def test_threshold_sensors_match_config(self, hass, setup_integration):
        """Threshold sensors must reflect the configured values."""
        imm = hass.states.get("sensor.power_control_soglia_distacco_immediato")
        delayed = hass.states.get("sensor.power_control_soglia_distacco_ritardato")
        assert float(imm.state) == 3300.0
        assert float(delayed.state) == 3000.0

    async def test_power_sensors_have_watt_unit(self, hass, setup_integration):
        """All power sensors must declare W as unit of measurement."""
        sensors = [
            "sensor.power_control_potenza_attuale",
            "sensor.power_control_potenza_sospesa",
        ]
        for entity_id in sensors:
            state = hass.states.get(entity_id)
            assert state.attributes.get("unit_of_measurement") == "W", entity_id

    async def test_power_sensors_have_power_device_class(self, hass, setup_integration):
        """Active power sensors must declare power device class."""
        sensors = [
            "sensor.power_control_potenza_attuale",
        ]
        for entity_id in sensors:
            state = hass.states.get(entity_id)
            assert state.attributes.get("device_class") == "power", entity_id

    async def test_current_power_zero_with_no_sensors(self, hass, setup_integration):
        """Without real sensors, current power sums to 0."""
        state = hass.states.get("sensor.power_control_potenza_attuale")
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

        state = hass.states.get("sensor.power_control_potenza_attuale")
        assert float(state.state) == 2000.0

    async def test_suspended_power_starts_at_zero(self, hass, setup_integration):
        """Suspended power must be 0 at startup (no loads shed yet)."""
        state = hass.states.get("sensor.power_control_potenza_sospesa")
        assert float(state.state) == 0.0


class TestPerLoadSensors:
    async def test_per_load_sensors_created(self, hass, setup_integration):
        """One suspended-power sensor per configured load must exist."""
        _, coordinator, _ = setup_integration
        for i, load in enumerate(coordinator.loads):
            # Sensor name is derived from load name
            entity_id = f"sensor.power_control_{load.name.lower()}_potenza_sospesa"
            state = hass.states.get(entity_id)
            assert state is not None, f"Missing sensor for load {i}: {entity_id}"

    async def test_per_load_sensor_attributes(self, hass, setup_integration):
        """Per-load sensor must expose expected extra attributes."""
        _, coordinator, _ = setup_integration
        load_name = coordinator.loads[0].name.lower()
        entity_id = f"sensor.power_control_{load_name}_potenza_sospesa"
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
                f"sensor.power_control_{load.name.lower()}_potenza_sospesa"
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
        entity_id = f"sensor.power_control_{load_name}_potenza_sospesa"
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
