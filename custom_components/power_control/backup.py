"""Save and restore the integration's configuration across full removal.

When a user removes the config entry entirely (not just unloads/uninstalls
the files), Home Assistant discards entry.data/entry.options permanently.
This module snapshots that data to a Store on removal, so the config flow
can offer to restore it if the integration is set up again later.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION = 1
_STORAGE_KEY = "power_control_backup"


def _get_store(hass: HomeAssistant) -> Store:
    return Store(hass, _STORAGE_VERSION, _STORAGE_KEY)


async def async_save_backup(
    hass: HomeAssistant, data: dict[str, Any], options: dict[str, Any]
) -> None:
    """Snapshot config entry data/options for later restore."""
    store = _get_store(hass)
    await store.async_save({"data": data, "options": options})
    _LOGGER.debug("[power_control] Configuration backup saved")


async def async_load_backup(hass: HomeAssistant) -> dict[str, Any] | None:
    """Return the saved backup, or None if none exists."""
    store = _get_store(hass)
    return await store.async_load()


async def async_clear_backup(hass: HomeAssistant) -> None:
    """Remove any saved backup (called after a successful restore)."""
    store = _get_store(hass)
    await store.async_remove()
    _LOGGER.debug("[power_control] Configuration backup cleared")
