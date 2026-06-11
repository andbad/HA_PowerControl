"""The Power Control integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, CONF_NOTIFY_ENTITY, CONF_NOTIFY_SERVICE, CONF_LOADS
from .dashboard import async_create_dashboard, async_remove_dashboard
from .coordinator import PowerControlCoordinator
from .notify import async_notify

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]

# Service schemas
_LOAD_INDEX_SCHEMA = vol.Schema(
    {vol.Required("load_index"): vol.All(int, vol.Range(min=0, max=19))}
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Power Control from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = PowerControlCoordinator(hass, entry)
    await coordinator.async_restore_state()
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Register state-change listener on the global power sensor (if configured)
    coordinator.setup_global_sensor_listener()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Create Lovelace dashboard if the user requested it during setup
    if entry.data.get("create_dashboard", False):
        await async_create_dashboard(hass, entry)


    _register_services(hass)

    _LOGGER.debug("[%s] Setup complete for entry %s", DOMAIN, entry.entry_id)
    return True


def _register_services(hass: HomeAssistant) -> None:
    """Register HA services for Power Control. Safe to call multiple times."""

    if hass.services.has_service(DOMAIN, "enable"):
        return  # already registered (multiple config entries)

    def _get_coordinator(call: ServiceCall) -> PowerControlCoordinator | None:
        """Return the first coordinator found (single-entry assumption)."""
        entries = hass.data.get(DOMAIN, {})
        if not entries:
            _LOGGER.warning("[%s] Service called but no active entry found", DOMAIN)
            return None
        return next(iter(entries.values()))

    async def handle_enable(call: ServiceCall) -> None:
        coord = _get_coordinator(call)
        if coord:
            coord.enabled = True
            await coord.async_request_refresh()
            _LOGGER.info("[%s] Service: Power Control enabled", DOMAIN)

    async def handle_disable(call: ServiceCall) -> None:
        coord = _get_coordinator(call)
        if coord:
            coord.enabled = False
            coord.reset_all_suspended()
            await coord.async_request_refresh()
            _LOGGER.info("[%s] Service: Power Control disabled", DOMAIN)

    async def handle_reset_load(call: ServiceCall) -> None:
        coord = _get_coordinator(call)
        if coord:
            index: int = call.data["load_index"]
            coord.reset_load_suspended(index)
            await coord.async_request_refresh()

    async def handle_force_stop_load(call: ServiceCall) -> None:
        coord = _get_coordinator(call)
        if not coord:
            return
        index: int = call.data["load_index"]
        loads = coord.loads
        if index >= len(loads):
            _LOGGER.warning("[%s] force_stop_load: index %d out of range", DOMAIN, index)
            return
        load = loads[index]
        if not load.is_configured:
            _LOGGER.warning("[%s] force_stop_load: load %d not configured", DOMAIN, index)
            return
        # Save power and turn off
        ps = hass.states.get(load.power_sensor)
        power = 0.0
        if ps and ps.state not in ("unavailable", "unknown"):
            try:
                power = float(ps.state)
            except ValueError:
                pass
        load.suspended_power = max(power, 1.0)   # at least 1 W so it's marked suspended
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": load.switch}, blocking=True
        )
        notify_entity: str = coord.config_entry.data.get(CONF_NOTIFY_ENTITY, "")
        await async_notify(
            hass, notify_entity,
            title="Distacco manuale",
            message=f"{load.name} distaccato manualmente.",
        )
        await coord.async_request_refresh()
        _LOGGER.info("[%s] Service: force-stopped load %d '%s'", DOMAIN, index, load.name)

    async def handle_force_start_load(call: ServiceCall) -> None:
        coord = _get_coordinator(call)
        if not coord:
            return
        index: int = call.data["load_index"]
        loads = coord.loads
        if index >= len(loads):
            _LOGGER.warning("[%s] force_start_load: index %d out of range", DOMAIN, index)
            return
        load = loads[index]
        if not load.is_configured:
            _LOGGER.warning("[%s] force_start_load: load %d not configured", DOMAIN, index)
            return
        load.suspended_power = 0.0
        load.keep_off = False
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": load.switch}, blocking=True
        )
        notify_entity: str = coord.config_entry.data.get(CONF_NOTIFY_ENTITY, "")
        await async_notify(
            hass, notify_entity,
            title="Riattivazione manuale",
            message=f"{load.name} riattivato manualmente.",
        )
        await coord.async_request_refresh()
        _LOGGER.info("[%s] Service: force-started load %d '%s'", DOMAIN, index, load.name)


    _MOVE_LOAD_SCHEMA = vol.Schema({
        vol.Required("load_index"): vol.All(int, vol.Range(min=0, max=19)),
        vol.Required("direction"): vol.In(["up", "down"]),
    })

    async def handle_move_load(call: ServiceCall) -> None:
        coord = _get_coordinator(call)
        if not coord:
            return
        index: int = call.data["load_index"]
        direction: str = call.data["direction"]
        loads: list = list(coord.config_entry.data.get(CONF_LOADS, []))
        swap = index - 1 if direction == "up" else index + 1
        if swap < 0 or swap >= len(loads):
            _LOGGER.warning("[%s] move_load: index %d cannot move %s", DOMAIN, index, direction)
            return
        loads[index], loads[swap] = loads[swap], loads[index]
        hass.config_entries.async_update_entry(
            coord.config_entry,
            data={**coord.config_entry.data, CONF_LOADS: loads},
        )
        coord.rebuild_loads()
        await coord.async_request_refresh()
        _LOGGER.info("[%s] Service: moved load %d %s (now at %d)", DOMAIN, index, direction, swap)

    hass.services.async_register(DOMAIN, "enable", handle_enable)
    hass.services.async_register(DOMAIN, "disable", handle_disable)
    hass.services.async_register(DOMAIN, "reset_load", handle_reset_load, schema=_LOAD_INDEX_SCHEMA)
    hass.services.async_register(DOMAIN, "force_stop_load", handle_force_stop_load, schema=_LOAD_INDEX_SCHEMA)
    hass.services.async_register(DOMAIN, "force_start_load", handle_force_start_load, schema=_LOAD_INDEX_SCHEMA)
    hass.services.async_register(DOMAIN, "move_load", handle_move_load, schema=_MOVE_LOAD_SCHEMA)

    _LOGGER.debug("[%s] Services registered", DOMAIN)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update: rebuild load list without full reload."""
    coordinator: PowerControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.rebuild_loads()
    coordinator.setup_global_sensor_listener()
    await coordinator.async_request_refresh()
    _LOGGER.debug("[%s] Loads rebuilt after options update", DOMAIN)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Power Control config entry."""
    coordinator: PowerControlCoordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        coordinator.async_shutdown()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    # Remove services only when last entry is unloaded
    if not hass.data.get(DOMAIN):
        for service in ["enable", "disable", "reset_load", "force_stop_load", "force_start_load", "move_load"]:
            hass.services.async_remove(DOMAIN, service)
        _LOGGER.debug("[%s] Services unregistered", DOMAIN)
        # Remove dashboard (only once, when the last entry is gone)
        if entry.data.get("create_dashboard", False):
            await async_remove_dashboard(hass)

    _LOGGER.debug("[%s] Unloaded entry %s (ok=%s)", DOMAIN, entry.entry_id, unload_ok)
    return unload_ok
