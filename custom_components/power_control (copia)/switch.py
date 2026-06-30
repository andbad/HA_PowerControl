"""Switch entity to enable/disable Power Control."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_INSTANCE_NAME, CONF_ENABLED
from .coordinator import PowerControlCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the enable/disable switch for this config entry."""
    coordinator: PowerControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.enabled = entry.options.get(CONF_ENABLED, True)
    async_add_entities([PowerControlSwitch(coordinator, entry)])


class PowerControlSwitch(SwitchEntity):
    """Master switch that enables or disables the power shedding logic."""

    _attr_has_entity_name = True
    _attr_name = "Active"
    _attr_icon = "mdi:car-cruise-control"
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: PowerControlCoordinator,
        entry: ConfigEntry,
    ) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_enabled"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get(CONF_INSTANCE_NAME, "Power Control"),
            manufacturer="HA PowerControl",
            model="Power Control",
            sw_version="1.0.0",
        )

    # ── SwitchEntity interface ─────────────────────────────────────────────────

    @property
    def is_on(self) -> bool:
        return self._coordinator.enabled

    async def async_turn_on(self, **kwargs) -> None:  # type: ignore[override]
        self._coordinator.enabled = True
        self.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, CONF_ENABLED: True}
        )
        self.async_write_ha_state()
        _LOGGER.info("[%s] Power Control ENABLED", DOMAIN)

    async def async_turn_off(self, **kwargs) -> None:  # type: ignore[override]
        self._coordinator.enabled = False
        self.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, CONF_ENABLED: False}
        )
        # Clear all suspended powers so loads are not stuck off
        self._coordinator.reset_all_suspended()
        self.async_write_ha_state()
        _LOGGER.info("[%s] Power Control DISABLED — all suspended powers cleared", DOMAIN)
