"""Notification helper for Power Control integration."""
from __future__ import annotations

import logging

from homeassistant.components.notify import (
    ATTR_MESSAGE,
    ATTR_TITLE,
    SERVICE_SEND_MESSAGE,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_NOTIFY_DOMAIN = "notify"


async def async_notify(
    hass: HomeAssistant,
    notify_entity: str,
    title: str,
    message: str,
) -> None:
    """Send a notification via a notify entity (modern HA notify platform).

    Uses ``notify.send_message`` with the entity as the target — the pattern
    that works for all current HA notification backends including:
    - Home Assistant Companion app (mobile_app)
    - Telegram bot (2025.11+)
    - Pushover, Slack, and any other integration exposing a notify entity

    Silently skips if no entity is configured or the entity does not exist.
    Never raises — a failed notification must not affect the coordinator.
    """
    if not notify_entity:
        return

    # Verify the entity exists in the state machine
    state = hass.states.get(notify_entity)
    if state is None:
        _LOGGER.warning(
            "[%s] Notify entity '%s' not found in state machine — "
            "check that the notification integration is configured correctly",
            DOMAIN,
            notify_entity,
        )
        return

    # Verify the notify.send_message service is available
    if not hass.services.has_service(_NOTIFY_DOMAIN, SERVICE_SEND_MESSAGE):
        _LOGGER.warning(
            "[%s] Service notify.send_message not available — skipping notification",
            DOMAIN,
        )
        return

    try:
        await hass.services.async_call(
            _NOTIFY_DOMAIN,
            SERVICE_SEND_MESSAGE,
            {
                ATTR_MESSAGE: message,
                ATTR_TITLE: title,
            },
            target={ATTR_ENTITY_ID: notify_entity},
            blocking=False,  # fire-and-forget — don't stall the coordinator
        )
        _LOGGER.debug(
            "[%s] Notification sent to %s: [%s] %s",
            DOMAIN, notify_entity, title, message,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "[%s] Failed to send notification to '%s': %s",
            DOMAIN, notify_entity, err,
        )
