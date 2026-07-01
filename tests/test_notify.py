"""Tests for the Power Control notification helper (notify.send_message pattern)."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.power_control.notify import async_notify


def _make_hass(
    entity_exists: bool = True,
    send_message_available: bool = True,
    legacy_service_exists: bool = True,
):
    """Build a mock hass for notify tests."""
    hass = MagicMock()

    # State machine
    state = MagicMock()
    state.state = "unknown"
    hass.states.get = MagicMock(return_value=state if entity_exists else None)

    # Services: send_message drives the modern path; the service_name check
    # drives the legacy path.
    def _has_service(domain, service):
        if service == "send_message":
            return send_message_available
        # Any other service name simulates whether a legacy service exists.
        return legacy_service_exists

    hass.services.has_service = MagicMock(side_effect=_has_service)
    hass.services.async_call = AsyncMock()

    return hass


class TestAsyncNotify:
    @pytest.mark.asyncio
    async def test_skips_when_entity_empty(self):
        """No call when notify_entity is empty string."""
        hass = _make_hass()
        await async_notify(hass, "", "Title", "Message")
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_entity_and_legacy_service_missing(self):
        """No call when neither the entity nor a legacy service exists."""
        hass = _make_hass(entity_exists=False, legacy_service_exists=False)
        await async_notify(hass, "notify.telegram_bot_chat", "Title", "Message")
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_legacy_when_entity_missing(self):
        """Calls legacy service when entity is absent but service exists."""
        hass = _make_hass(entity_exists=False, legacy_service_exists=True)
        await async_notify(hass, "notify.telegram_bot_chat", "Title", "Message")
        hass.services.async_call.assert_called_once_with(
            "notify", "telegram_bot_chat",
            {"message": "Message", "title": "Title"},
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_skips_when_send_message_not_available(self):
        """No call when notify.send_message service is not registered."""
        hass = _make_hass(send_message_available=False)
        await async_notify(hass, "notify.telegram_bot_chat", "Title", "Message")
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_notify_send_message(self):
        """Uses notify.send_message with entity as target."""
        hass = _make_hass()
        await async_notify(hass, "notify.telegram_bot_chat", "Titolo", "Messaggio")

        hass.services.async_call.assert_called_once()
        call = hass.services.async_call.call_args

        # Service must be notify.send_message
        assert call.args[0] == "notify"
        assert call.args[1] == "send_message"

        # Data must contain message and title
        data = call.args[2]
        assert data["message"] == "Messaggio"
        assert data["title"] == "Titolo"

        # Target must reference the entity_id
        target = call.kwargs.get("target") or {}
        assert target.get("entity_id") == "notify.telegram_bot_chat"

    @pytest.mark.asyncio
    async def test_works_with_companion_app_entity(self):
        """Pattern works identically for mobile_app entities."""
        hass = _make_hass()
        await async_notify(hass, "notify.mobile_app_iphone", "Distacco", "Lavatrice spenta")

        call = hass.services.async_call.call_args
        assert call.args[0] == "notify"
        assert call.args[1] == "send_message"
        target = call.kwargs.get("target") or {}
        assert target.get("entity_id") == "notify.mobile_app_iphone"

    @pytest.mark.asyncio
    async def test_uses_blocking_false(self):
        """Notification must be fire-and-forget (blocking=False)."""
        hass = _make_hass()
        await async_notify(hass, "notify.telegram_bot_chat", "T", "M")

        call = hass.services.async_call.call_args
        assert call.kwargs.get("blocking") is False

    @pytest.mark.asyncio
    async def test_does_not_raise_on_service_error(self):
        """Exceptions from the notify service must not propagate."""
        hass = _make_hass()
        hass.services.async_call = AsyncMock(side_effect=Exception("connection error"))
        # Must not raise
        await async_notify(hass, "notify.telegram_bot_chat", "T", "M")
