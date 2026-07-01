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
    """Send a notification, supporting both the modern and legacy HA notify systems.

    Two formats are accepted in ``notify_entity``:
    - A modern notify entity (e.g. ``notify.mobile_app_phone``) — sent via
      ``notify.send_message`` with the entity as the target. Covers the
      Companion app, Telegram (2025.11+), Pushover, Slack, etc.
    - A legacy notify service name (e.g. ``lg_webos_tv``, or a notification
      group such as ``tutti`` created with the old ``notify: group`` YAML
      platform) — sent by calling ``notify.<service_name>`` directly, since
      these targets have no entity in the state machine. This covers
      integrations that have not migrated to the notify entity platform yet.

    Silently skips if no value is configured. Never raises — a failed
    notification must not affect the coordinator.
    """
    if not notify_entity:
        return

    # Strip a leading "notify." prefix if present, since legacy service
    # names are called as notify.<name>, not notify.notify.<name>.
    service_name = notify_entity.removeprefix(f"{_NOTIFY_DOMAIN}.")

    # Prefer the modern notify-entity path when the entity actually exists.
    if hass.states.get(notify_entity) is not None:
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
                {ATTR_MESSAGE: message, ATTR_TITLE: title},
                target={ATTR_ENTITY_ID: notify_entity},
                blocking=False,  # fire-and-forget — don't stall the coordinator
            )
            _LOGGER.debug(
                "[%s] Notification sent to entity %s: [%s] %s",
                DOMAIN, notify_entity, title, message,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "[%s] Failed to send notification to '%s': %s",
                DOMAIN, notify_entity, err,
            )
        return

    # Fall back to the legacy notify service (group or non-migrated integration).
    if not hass.services.has_service(_NOTIFY_DOMAIN, service_name):
        _LOGGER.warning(
            "[%s] Notify target '%s' not found as an entity nor as a "
            "notify service (notify.%s) — check the configured value",
            DOMAIN, notify_entity, service_name,
        )
        return

    try:
        await hass.services.async_call(
            _NOTIFY_DOMAIN,
            service_name,
            {ATTR_MESSAGE: message, ATTR_TITLE: title},
            blocking=False,  # fire-and-forget — don't stall the coordinator
        )
        _LOGGER.debug(
            "[%s] Notification sent via legacy service notify.%s: [%s] %s",
            DOMAIN, service_name, title, message,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "[%s] Failed to send notification via legacy service 'notify.%s': %s",
            DOMAIN, service_name, err,
        )
