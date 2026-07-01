"""Tests for the Power Control backup/restore helpers."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.power_control.backup import (
    async_save_backup,
    async_load_backup,
    async_clear_backup,
)

_SAMPLE_DATA = {"instance_name": "Test PC", "threshold_immediate": 3300}
_SAMPLE_OPTIONS = {"enabled": True}


def _make_hass():
    hass = MagicMock()
    return hass


class TestBackup:
    @pytest.mark.asyncio
    async def test_save_then_load_returns_same_data(self):
        """Saved data can be loaded back intact."""
        stored = {}

        async def fake_save(payload):
            stored["value"] = payload

        async def fake_load():
            return stored.get("value")

        hass = _make_hass()
        with patch(
            "custom_components.power_control.backup.Store"
        ) as MockStore:
            instance = MockStore.return_value
            instance.async_save = AsyncMock(side_effect=fake_save)
            instance.async_load = AsyncMock(side_effect=fake_load)

            await async_save_backup(hass, _SAMPLE_DATA, _SAMPLE_OPTIONS)
            result = await async_load_backup(hass)

        assert result["data"] == _SAMPLE_DATA
        assert result["options"] == _SAMPLE_OPTIONS

    @pytest.mark.asyncio
    async def test_load_returns_none_when_empty(self):
        """Returns None when no backup exists."""
        hass = _make_hass()
        with patch(
            "custom_components.power_control.backup.Store"
        ) as MockStore:
            instance = MockStore.return_value
            instance.async_load = AsyncMock(return_value=None)

            result = await async_load_backup(hass)

        assert result is None

    @pytest.mark.asyncio
    async def test_clear_calls_async_remove(self):
        """Clear delegates to Store.async_remove."""
        hass = _make_hass()
        with patch(
            "custom_components.power_control.backup.Store"
        ) as MockStore:
            instance = MockStore.return_value
            instance.async_remove = AsyncMock()

            await async_clear_backup(hass)

            instance.async_remove.assert_called_once()
