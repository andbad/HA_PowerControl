"""Button entities for Power Control integration."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    CONF_INSTANCE_NAME,
    CONF_DASHBOARD_USER_CONTROLLED,
    NOTIF_ID_REGEN_CONFIRM,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities — only when user_controlled is enabled."""
    if not entry.data.get(CONF_DASHBOARD_USER_CONTROLLED, False):
        return

    async_add_entities([PowerControlRegenButton(hass, entry)])


class PowerControlRegenButton(ButtonEntity):
    """Button that triggers the dashboard-regeneration confirmation notification."""

    _attr_has_entity_name = True
    _attr_translation_key = "regenerate_dashboard"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        instance = entry.data.get(CONF_INSTANCE_NAME, DOMAIN)
        self._attr_unique_id = f"{entry.entry_id}_regen_dashboard"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    async def async_press(self) -> None:
        """Show confirmation notification instead of regenerating directly."""
        from .dashboard import DASHBOARD_VERSION
        entry = self._entry
        instance = entry.data.get(CONF_INSTANCE_NAME, DOMAIN)

        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "notification_id": NOTIF_ID_REGEN_CONFIRM,
                "title": f"PowerControl — Aggiorna dashboard",
                "message": (
                    f"La dashboard **{instance}** verrà ricreata "
                    f"(versione {DASHBOARD_VERSION}).\n\n"
                    "⚠️ **Tutte le personalizzazioni andranno perse.** "
                    "Vuoi procedere?\n\n"
                    f"[✅ Conferma aggiornamento](/api/power_control/regen_confirm/{entry.entry_id}/confirm)  "
                    f"[❌ Annulla](/api/power_control/regen_confirm/{entry.entry_id}/cancel)"
                ),
            },
        )
        _LOGGER.debug("[%s] Regen confirmation notification created", DOMAIN)
