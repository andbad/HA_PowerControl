"""Tests for the Power Control notification helper."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.power_control.notify import async_notify


class TestAsyncNotify:
    @pytest.mark.asyncio
    async def test_skips_when_service_empty(self):
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        await async_notify(hass, "", "Titolo", "Messaggio")
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_service_not_registered(self):
        hass = MagicMock()
        hass.services.has_service = MagicMock(return_value=False)
        hass.services.async_call = AsyncMock()
        await async_notify(hass, "notify.inesistente", "Titolo", "Messaggio")
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_service_when_registered(self):
        hass = MagicMock()
        hass.services.has_service = MagicMock(return_value=True)
        hass.services.async_call = AsyncMock()
        await async_notify(hass, "notify.mobile", "Titolo", "Messaggio")
        hass.services.async_call.assert_called_once_with(
            "notify",
            "mobile",
            {"title": "Titolo", "message": "Messaggio"},
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_does_not_raise_on_service_error(self):
        hass = MagicMock()
        hass.services.has_service = MagicMock(return_value=True)
        hass.services.async_call = AsyncMock(side_effect=Exception("boom"))
        # Must not propagate the exception
        await async_notify(hass, "notify.mobile", "Titolo", "Messaggio")
