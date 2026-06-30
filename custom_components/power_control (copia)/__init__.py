"""The Power Control integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
import homeassistant.helpers.config_validation as cv
from homeassistant.util import slugify

from .const import (
    DOMAIN, CONF_NOTIFY_ENTITY, CONF_NOTIFY_SERVICE, CONF_LOADS,
    CONF_DASHBOARD_USER_CONTROLLED, CONF_DASHBOARD_SKIPPED_VERSION,
    CONF_DASHBOARD_LANGUAGE,
    NOTIF_ID_REGEN_CONFIRM, SERVICE_REGENERATE_DASHBOARD,
)
from .dashboard import async_create_dashboard, async_remove_dashboard, async_rebuild_dashboard, DASHBOARD_VERSION, translate
from .coordinator import PowerControlCoordinator
from .notify import async_notify
from .backup import async_save_backup

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON]

# Service schemas
_LOAD_INDEX_SCHEMA = vol.Schema(
    {vol.Required("load_index"): vol.All(int, vol.Range(min=0, max=19))}
)

_SET_THRESHOLDS_SCHEMA = vol.Schema(
    {
        vol.Optional("immediate_threshold"): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional("delayed_threshold"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)


_GLOBAL_ENTITY_ID_MAP: dict[str, str] = {
    "sensor.power_control_potenza_attuale":          "sensor.power_control_current_power",
    "sensor.power_control_potenza_sospesa":          "sensor.power_control_suspended_power",
    "sensor.power_control_soglia_distacco_immediato": "sensor.power_control_immediate_threshold",
    "sensor.power_control_soglia_distacco_ritardato": "sensor.power_control_delayed_threshold",
}


def _migrate_entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rename Italian entity_ids to English for existing installations.

    Called once at setup. Safe to run repeatedly — skips already-migrated
    entries and logs a warning on conflict without raising.
    """
    registry = er.async_get(hass)

    # 1. Global sensors — fixed mapping
    for old_id, new_id in _GLOBAL_ENTITY_ID_MAP.items():
        entity_entry = registry.async_get(old_id)
        if entity_entry is None:
            continue
        if registry.async_get(new_id) is not None:
            _LOGGER.warning(
                "[%s] Cannot migrate %s → %s: target already exists",
                DOMAIN, old_id, new_id,
            )
            continue
        try:
            registry.async_update_entity(old_id, new_entity_id=new_id)
            _LOGGER.info("[%s] Migrated entity_id: %s → %s", DOMAIN, old_id, new_id)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("[%s] Migration failed %s → %s: %s", DOMAIN, old_id, new_id, exc)

    # 2. Per-load suspended_power sensors — derive from current load names
    loads_cfg = entry.data.get("loads", [])
    for i, load_cfg in enumerate(loads_cfg):
        unique_id = f"{entry.entry_id}_load_{i}_suspended"
        current_entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if current_entity_id is None:
            continue

        load_name = (load_cfg.get("name") or "").strip()
        display_name = load_name if load_name else f"Load {i + 1}"
        expected_entity_id = f"sensor.{slugify(f'power_control {display_name} suspended power')}"

        if current_entity_id == expected_entity_id:
            continue
        if registry.async_get(expected_entity_id) is not None:
            _LOGGER.warning(
                "[%s] Cannot migrate %s → %s: target already exists",
                DOMAIN, current_entity_id, expected_entity_id,
            )
            continue
        try:
            registry.async_update_entity(current_entity_id, new_entity_id=expected_entity_id)
            _LOGGER.info("[%s] Migrated entity_id: %s → %s", DOMAIN, current_entity_id, expected_entity_id)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("[%s] Migration failed %s → %s: %s", DOMAIN, current_entity_id, expected_entity_id, exc)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Power Control from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    _migrate_entity_ids(hass, entry)

    coordinator = PowerControlCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Register state-change listener on the global power sensor (if configured)
    coordinator.setup_global_sensor_listener()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Restore suspended_power from sensor state — must happen after platforms are
    # set up so the entity registry contains the per-load sensor unique_ids.
    await coordinator.async_restore_state()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Create / handle Lovelace dashboard
    if entry.data.get("create_dashboard", False):
        await _async_handle_dashboard_setup(hass, entry)


    _register_services(hass)

    _LOGGER.debug("[%s] Setup complete for entry %s", DOMAIN, entry.entry_id)
    return True


async def _async_handle_dashboard_setup(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Create dashboard on first run; if user_controlled, notify instead of overwriting."""
    from .dashboard import async_dashboard_exists

    user_controlled: bool = entry.data.get(CONF_DASHBOARD_USER_CONTROLLED, False)
    dashboard_exists: bool = await async_dashboard_exists(hass, entry)
    skipped_version: int | None = entry.options.get(CONF_DASHBOARD_SKIPPED_VERSION)

    if not user_controlled:
        # Legacy behaviour: always regenerate
        await async_create_dashboard(hass, entry)
        return

    if not dashboard_exists:
        # First time: generate even in user_controlled mode
        await async_create_dashboard(hass, entry)
        return

    # Dashboard exists and user is in control.
    # Show notification only if version is outdated and not already skipped.
    if skipped_version == DASHBOARD_VERSION:
        _LOGGER.debug("[%s] Dashboard update skipped (version %s)", DOMAIN, DASHBOARD_VERSION)
        return

    # Dashboard outdated: post confirmation notification
    instance = entry.data.get("instance_name", DOMAIN)
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "notification_id": NOTIF_ID_REGEN_CONFIRM,
            "title": "PowerControl — Aggiornamento dashboard disponibile",
            "message": (
                f"È disponibile una nuova versione della dashboard **{instance}** "
                f"(versione {DASHBOARD_VERSION}).\n\n"
                "⚠️ **Rigenerando la dashboard perderai tutte le personalizzazioni.** "
                "Vuoi procedere?\n\n"
                f"[✅ Aggiorna dashboard](/api/power_control/regen_confirm/{entry.entry_id}/confirm)  "
                f"[⏭️ Salta](/api/power_control/regen_confirm/{entry.entry_id}/cancel)"
            ),
        },
    )
    _LOGGER.debug("[%s] Dashboard outdated notification created (v%s)", DOMAIN, DASHBOARD_VERSION)


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
        # Save power reading before turning off
        ps = hass.states.get(load.power_sensor)
        power = 0.0
        if ps and ps.state not in ("unavailable", "unknown"):
            try:
                power = float(ps.state)
            except ValueError:
                pass
        load.suspended_power = max(power, 1.0)  # at least 1 W so it's marked suspended
        if not await coord._call_switch("turn_off", load.switch):
            load.suspended_power = 0.0  # rollback on failure
            return
        notify_entity: str = coord._get_conf(CONF_NOTIFY_ENTITY, "")
        lang = coord._get_conf(CONF_DASHBOARD_LANGUAGE, "en")
        await async_notify(
            hass, notify_entity,
            title=translate(lang, "notify_manual_shed_title"),
            message=translate(lang, "notify_manual_shed_message", load_name=load.name),
        )
        hass.bus.async_fire(
            f"{DOMAIN}_load_shed",
            {
                "load_name": load.name,
                "load_index": index,
                "switch": load.switch,
                "suspended_power_w": load.suspended_power,
            },
        )
        coord._record_shed_and_check_flap(load)
        coord.publish_current_state()
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
        load.shed_timestamps.clear()  # reset anti-flap counter on manual restart
        if not await coord._call_switch("turn_on", load.switch):
            return
        notify_entity: str = coord.config_entry.data.get(CONF_NOTIFY_ENTITY, "")
        lang = coord.config_entry.data.get(CONF_DASHBOARD_LANGUAGE, "en")
        await async_notify(
            hass, notify_entity,
            title=translate(lang, "notify_manual_restart_title"),
            message=translate(lang, "notify_manual_restart_message", load_name=load.name),
        )
        hass.bus.async_fire(
            f"{DOMAIN}_load_restored",
            {
                "load_name": load.name,
                "load_index": index,
                "switch": load.switch,
                "restored_power_w": 0.0,  # unknown at force-start time
            },
        )
        coord.publish_current_state()
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
        await async_rebuild_dashboard(hass, coord.config_entry)
        await coord.async_request_refresh()
        _LOGGER.info("[%s] Service: moved load %d %s (now at %d)", DOMAIN, index, direction, swap)

    async def handle_set_thresholds(call: ServiceCall) -> None:
        coord = _get_coordinator(call)
        if not coord:
            return
        imm = call.data.get("immediate_threshold")
        dly = call.data.get("delayed_threshold")
        coord.set_thresholds(imm, dly)

    async def handle_regenerate_dashboard(call: ServiceCall) -> None:
        """Regenerate dashboard for the first entry (single-entry assumption)."""
        entries = hass.data.get(DOMAIN, {})
        if not entries:
            return
        entry_id = next(iter(entries))
        cfg_entry = hass.config_entries.async_get_entry(entry_id)
        if cfg_entry:
            await _async_do_regen_dashboard(hass, cfg_entry)

    hass.services.async_register(DOMAIN, "enable", handle_enable)
    hass.services.async_register(DOMAIN, "disable", handle_disable)
    hass.services.async_register(DOMAIN, "reset_load", handle_reset_load, schema=_LOAD_INDEX_SCHEMA)
    hass.services.async_register(DOMAIN, "force_stop_load", handle_force_stop_load, schema=_LOAD_INDEX_SCHEMA)
    hass.services.async_register(DOMAIN, "force_start_load", handle_force_start_load, schema=_LOAD_INDEX_SCHEMA)
    hass.services.async_register(DOMAIN, "move_load", handle_move_load, schema=_MOVE_LOAD_SCHEMA)
    hass.services.async_register(DOMAIN, "set_thresholds", handle_set_thresholds, schema=_SET_THRESHOLDS_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REGENERATE_DASHBOARD, handle_regenerate_dashboard)

    # Register HTTP views for notification action buttons (confirm / cancel)
    from homeassistant.components.http import HomeAssistantView

    class _RegenConfirmView(HomeAssistantView):
        url = "/api/power_control/regen_confirm/{entry_id}/{action}"
        name = "api:power_control:regen_confirm"
        requires_auth = True

        async def get(self, request, entry_id: str, action: str):
            cfg_entry = hass.config_entries.async_get_entry(entry_id)
            if cfg_entry is None:
                return self.json_message("Entry not found", 404)
            if action == "confirm":
                await _async_do_regen_dashboard(hass, cfg_entry)
            elif action == "cancel":
                await _async_skip_dashboard_version(hass, cfg_entry)
            # Dismiss notification in both cases
            await hass.services.async_call(
                "persistent_notification", "dismiss",
                {"notification_id": NOTIF_ID_REGEN_CONFIRM},
            )
            return self.json_message("OK")

    if hass.http is not None:
        hass.http.register_view(_RegenConfirmView())

    _LOGGER.debug("[%s] Services registered", DOMAIN)


async def _async_do_regen_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Regenerate dashboard and clear the skipped-version flag."""
    await async_rebuild_dashboard(hass, entry)
    new_options = {**entry.options}
    new_options.pop(CONF_DASHBOARD_SKIPPED_VERSION, None)
    hass.config_entries.async_update_entry(entry, options=new_options)
    _LOGGER.info("[%s] Dashboard regenerated (v%s)", DOMAIN, DASHBOARD_VERSION)


async def _async_skip_dashboard_version(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Persist the current version as skipped so notification won't reappear until next upgrade."""
    new_options = {**entry.options, CONF_DASHBOARD_SKIPPED_VERSION: DASHBOARD_VERSION}
    hass.config_entries.async_update_entry(entry, options=new_options)
    _LOGGER.debug("[%s] Dashboard update skipped at v%s", DOMAIN, DASHBOARD_VERSION)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update: rebuild load list without full reload."""
    coordinator: PowerControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.rebuild_loads()
    coordinator.setup_global_sensor_listener()
    await coordinator.async_request_refresh()
    await async_rebuild_dashboard(hass, entry)
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
        for service in ["enable", "disable", "reset_load", "force_stop_load", "force_start_load", "move_load", "set_thresholds"]:
            hass.services.async_remove(DOMAIN, service)
        _LOGGER.debug("[%s] Services unregistered", DOMAIN)
        # Remove dashboard (only once, when the last entry is gone)
        if entry.data.get("create_dashboard", False):
            await async_remove_dashboard(hass)

    _LOGGER.debug("[%s] Unloaded entry %s (ok=%s)", DOMAIN, entry.entry_id, unload_ok)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Called when the config entry is permanently deleted (not just unloaded).

    Snapshot the entry's data/options so the config flow can offer to
    restore them if the integration is set up again later.
    """
    await async_save_backup(hass, dict(entry.data), dict(entry.options))
    _LOGGER.info("[%s] Entry removed — configuration backed up for future restore", DOMAIN)
