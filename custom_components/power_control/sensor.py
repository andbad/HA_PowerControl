"""Sensor entities for Power Control integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_INSTANCE_NAME,
    CONF_THRESHOLD_IMMEDIATE,
    CONF_THRESHOLD_DELAYED,
)
from .coordinator import PowerControlCoordinator, PowerControlData

_LOGGER = logging.getLogger(__name__)


# ── Entity descriptions ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class PowerControlSensorDescription(SensorEntityDescription):
    """Extends SensorEntityDescription with a value extractor."""
    # Callable receives (coordinator, config_entry) and returns the sensor value
    value_fn: Any = None


GLOBAL_SENSOR_DESCRIPTIONS: tuple[PowerControlSensorDescription, ...] = (
    PowerControlSensorDescription(
        key="current_power",
        name="Current power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        value_fn=lambda coord, _entry: coord.data.current_power,
    ),
    PowerControlSensorDescription(
        key="suspended_power",
        name="Suspended power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:pause-circle-outline",
        value_fn=lambda coord, _entry: coord.data.total_suspended_power,
    ),
    PowerControlSensorDescription(
        key="threshold_immediate",
        name="Immediate threshold",
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:flash-alert",
        # Reads effective threshold — reflects runtime override set via set_thresholds service
        value_fn=lambda coord, _entry: coord.thresholds[0],
    ),
    PowerControlSensorDescription(
        key="threshold_delayed",
        name="Delayed threshold",
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:flash-outline",
        value_fn=lambda coord, _entry: coord.thresholds[1],
    ),
)


# ── Platform setup ────────────────────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create sensor entities for this config entry."""
    coordinator: PowerControlCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[PowerControlSensor] = []

    # Global sensors
    for description in GLOBAL_SENSOR_DESCRIPTIONS:
        entities.append(
            PowerControlSensor(coordinator, entry, description)
        )

    # Per-load sensors (one per configured load)
    for i, load in enumerate(coordinator.loads):
        entities.append(
            PowerControlLoadSensor(coordinator, entry, i)
        )

    async_add_entities(entities)
    _LOGGER.debug(
        "[%s] Registered %d sensor entities (%d global + %d per-load)",
        DOMAIN,
        len(entities),
        len(GLOBAL_SENSOR_DESCRIPTIONS),
        len(coordinator.loads),
    )


# ── Shared device info helper ─────────────────────────────────────────────────

def _device_info(entry: ConfigEntry) -> DeviceInfo:
    """Single HA device grouping all Power Control entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get(CONF_INSTANCE_NAME, "Power Control"),
        manufacturer="HA PowerControl",
        model="Power Control",
        sw_version="1.0.0",
    )


# ── Global sensor entity ──────────────────────────────────────────────────────

class PowerControlSensor(
    CoordinatorEntity[PowerControlCoordinator], SensorEntity
):
    """A sensor derived from global coordinator data."""

    entity_description: PowerControlSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PowerControlCoordinator,
        entry: ConfigEntry,
        description: PowerControlSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> float | None:
        """Return current sensor value via the description's value_fn."""
        if self.coordinator.data is None:
            return None
        try:
            return round(self.entity_description.value_fn(self.coordinator, self._entry), 1)
        except Exception:
            return None

    @property
    def extra_state_attributes(self) -> dict:
        """Expose timer state and per-load suspended power on the current_power sensor."""
        if self.entity_description.key != "current_power":
            return {}
        attrs = dict(self.coordinator.timer_state)
        if self.coordinator.data is not None:
            for i, load in enumerate(self.coordinator.data.loads):
                attrs[f"load_{i}_suspended_w"] = load.suspended_power
        return attrs


# ── Per-load sensor entity ────────────────────────────────────────────────────

class PowerControlLoadSensor(
    CoordinatorEntity[PowerControlCoordinator], SensorEntity
):
    """Sensor reporting the suspended power of a single managed load."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(
        self,
        coordinator: PowerControlCoordinator,
        entry: ConfigEntry,
        load_index: int,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._load_index = load_index
        load = coordinator.loads[load_index]
        load_name = (load.name or "").strip()
        display_name = load_name if load_name else f"Load {load_index + 1}"
        self._attr_unique_id = f"{entry.entry_id}_load_{load_index}_suspended"
        self._attr_name = f"{display_name} - suspended power"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> float | None:
        """Return the suspended power for this load."""
        if self.coordinator.data is None:
            return None
        loads = self.coordinator.data.loads
        if self._load_index >= len(loads):
            return None
        return loads[self._load_index].suspended_power

    @property
    def icon(self) -> str:
        """Return an icon reflecting the load status."""
        if self.coordinator.data is None:
            return "mdi:power-plug-outline"
        loads = self.coordinator.data.loads
        if self._load_index >= len(loads):
            return "mdi:power-plug-outline"
        load = loads[self._load_index]
        if load.keep_off:
            return "mdi:cancel"
        if load.is_suspended:
            return "mdi:power-plug-off"
        if load.switch_state in ("unavailable", "unknown"):
            return "mdi:power-plug-outline"
        return "mdi:power-plug"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose load details as attributes for dashboard use."""
        if self.coordinator.data is None:
            return {}
        loads = self.coordinator.data.loads
        if self._load_index >= len(loads):
            return {}
        load = loads[self._load_index]
        return {
            "load_index": self._load_index,
            "current_power_w": load.current_power,
            "switch_state": load.switch_state,
            "auto_restart": load.auto_restart,
            "keep_off": load.keep_off,
            "is_suspended": load.is_suspended,
        }
