"""Switch entity to enable/disable Power Control."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, CONF_INSTANCE_NAME
from .coordinator import PowerControlCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the enable/disable switch for this config entry."""
    coordinator: PowerControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PowerControlSwitch(coordinator, entry)])


class PowerControlSwitch(RestoreEntity, SwitchEntity):
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

    # ── State persistence across restarts ─────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """Restore previous on/off state after HA restart.

        Fresh install (no previous state): default to enabled=True and
        write the state immediately so the entity isn't left as "off"
        by default. Upgrade/restart with prior state: respect it as-is.
        """
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self._coordinator.enabled = last.state == "on"
            _LOGGER.debug(
                "[%s] Switch restored to: %s", DOMAIN, last.state
            )
        else:
            self._coordinator.enabled = True
            self.async_write_ha_state()
            _LOGGER.debug(
                "[%s] No previous state — defaulting switch to ON", DOMAIN
            )

    # ── SwitchEntity interface ─────────────────────────────────────────────────

    @property
    def is_on(self) -> bool:
        return self._coordinator.enabled

    async def async_turn_on(self, **kwargs) -> None:  # type: ignore[override]
        self._coordinator.enabled = True
        self.async_write_ha_state()
        _LOGGER.info("[%s] Power Control ENABLED", DOMAIN)

    async def async_turn_off(self, **kwargs) -> None:  # type: ignore[override]
        self._coordinator.enabled = False
        # Clear all suspended powers so loads are not stuck off
        self._coordinator.reset_all_suspended()
        self.async_write_ha_state()
        _LOGGER.info("[%s] Power Control DISABLED — all suspended powers cleared", DOMAIN)
