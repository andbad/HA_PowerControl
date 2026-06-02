"""Notification helper for Power Control integration."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_NOTIFY_SERVICE

_LOGGER = logging.getLogger(__name__)


async def async_notify(
    hass: HomeAssistant,
    notify_service: str,
    title: str,
    message: str,
) -> None:
    """Send a notification via the configured notify service.

    Silently skips if no service is configured or the service does not exist.
    Uses ``continue_on_error`` semantics: a failed notification never raises.
    """
    if not notify_service:
        return

    # Validate service exists before calling to avoid HA error logs
    domain, _, service_name = notify_service.partition(".")
    if not hass.services.has_service(domain, service_name):
        _LOGGER.warning(
            "[%s] Notify service '%s' not found — skipping notification",
            DOMAIN,
            notify_service,
        )
        return

    try:
        await hass.services.async_call(
            domain,
            service_name,
            {"title": title, "message": message},
            blocking=False,   # fire-and-forget — don't stall the coordinator
        )
        _LOGGER.debug(
            "[%s] Notification sent via %s: [%s] %s",
            DOMAIN, notify_service, title, message,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "[%s] Failed to send notification via '%s': %s",
            DOMAIN, notify_service, err,
        )
