"""Programmatic Lovelace dashboard creation for Power Control."""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

from homeassistant.components import frontend
from homeassistant.components.lovelace import DOMAIN as LOVELACE_DOMAIN
from homeassistant.components.lovelace import dashboard as lv_dashboard
from homeassistant.components.lovelace.const import (
    MODE_STORAGE,
    CONF_URL_PATH,
    CONF_ICON,
    CONF_TITLE,
    CONF_SHOW_IN_SIDEBAR,
    CONF_REQUIRE_ADMIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, CoreState, callback
from homeassistant.util import slugify

from .const import (
    DOMAIN,
    CONF_INSTANCE_NAME,
    CONF_GLOBAL_POWER_SENSOR,
    CONF_THRESHOLD_IMMEDIATE,
    CONF_THRESHOLD_DELAYED,
    CONF_DELAY_IMMEDIATE_SEC,
    CONF_DELAY_DELAYED_MIN,
    CONF_WAIT_BETWEEN_STOPS_SEC,
    CONF_WAIT_BETWEEN_STARTS_MIN,
    CONF_WAIT_BEFORE_START_MIN,
    CONF_NOTIFY_ENTITY,
    CONF_LOADS,
    CONF_DASHBOARD_LANGUAGE,
    CONF_DASHBOARD_REQUIRE_ADMIN,
    LOAD_NAME,
)

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL_PATH = "power-control"
def _manifest_version_int() -> int:
    """Convert manifest version string to a comparable integer.

    "4.1.2" → 4_01_02 → 40102. This means every integration version bump
    automatically triggers a dashboard rebuild on next HA start.
    """
    import json as _json
    import pathlib as _pathlib
    try:
        manifest = _json.loads(
            (_pathlib.Path(__file__).parent / "manifest.json").read_text()
        )
        parts = manifest.get("version", "0.0.0").split(".")
        major, minor, patch = (int(p) for p in (parts + ["0", "0"])[:3])
        return major * 10000 + minor * 100 + patch
    except Exception:
        return 0


DASHBOARD_VERSION = _manifest_version_int()

_TRANSLATIONS_DIR = pathlib.Path(__file__).parent / "translations"

# Cache: lang code → dashboard strings dict
_STRINGS_CACHE: dict[str, dict[str, str]] = {}


def _load_strings(lang: str) -> dict[str, str]:
    """Load dashboard strings for *lang* from the translation JSON, falling back to English."""
    if lang not in _STRINGS_CACHE:
        path = _TRANSLATIONS_DIR / f"{lang}.json"
        if not path.exists():
            path = _TRANSLATIONS_DIR / "en.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            strings = data.get("dashboard", {})
            if strings:
                _STRINGS_CACHE[lang] = strings
            else:
                _LOGGER.warning(
                    "[%s] Translation file %s has no 'dashboard' section", DOMAIN, path
                )
                return _load_strings("en") if lang != "en" else {}
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("[%s] Could not load translations for '%s': %s", DOMAIN, lang, err)
            return _load_strings("en") if lang != "en" else {}

    return _STRINGS_CACHE.get(lang, {})



def _t(lang: str, key: str, **kwargs: Any) -> str:
    """Return translated string for key, falling back to English."""
    strings = _load_strings(lang)
    en_strings = _load_strings("en")
    text = strings.get(key) or en_strings.get(key, key)
    return text.format(**kwargs) if kwargs else text


def _priority_label(lang: str, index: int, total: int) -> str:
    if index == 0:
        return _t(lang, "priority_high")
    if index == total - 1:
        return _t(lang, "priority_low")
    return _t(lang, "priority_n", n=index + 1)


# ── Panel helpers ──────────────────────────────────────────────────────────────

def _register_dashboard_panel(
    hass: HomeAssistant, title: str, icon: str, require_admin: bool = True, update: bool = False
) -> None:
    """Register (or update) the sidebar panel for our dashboard."""
    frontend.async_register_built_in_panel(
        hass,
        "lovelace",
        sidebar_title=title,
        sidebar_icon=icon,
        frontend_url_path=DASHBOARD_URL_PATH,
        config={"mode": MODE_STORAGE},
        require_admin=require_admin,
        update=update,
    )


def _get_lovelace_dashboards(hass: HomeAssistant) -> dict | None:
    """Return the lovelace dashboards dict regardless of HA version."""
    lovelace_data = hass.data.get(LOVELACE_DOMAIN)
    if lovelace_data is None:
        return None
    if isinstance(lovelace_data, dict):
        return lovelace_data.get("dashboards")
    return getattr(lovelace_data, "dashboards", None)


def _fmt_remaining(lang: str, remaining_sec: int | None) -> str:
    """Format remaining seconds as a human-readable string."""
    if remaining_sec is None:
        return _t(lang, "timer_idle")
    if remaining_sec >= 60:
        m, s = divmod(remaining_sec, 60)
        return _t(lang, "timer_min_remaining", m=m, s=s)
    return _t(lang, "timer_sec_remaining", s=remaining_sec)


def _timer_row(label: str, icon: str, attr_remaining: str, idle_text: str) -> str:
    """Return a single Jinja2 text line for a timer row."""
    entity = "sensor.power_control_current_power"
    return (
        f"{{% set rem = state_attr('{entity}','{attr_remaining}') %}}"
        f"\n{icon} {label}: "
        f"{{% if rem is none %}}{idle_text}"
        f"{{% elif rem >= 60 %}}"
        f"{{% set m = (rem // 60)|int %}}"
        f"{{% set s = (rem % 60)|int %}}"
        f"{{{{ m }}}}m {{{{ s }}}}s"
        f"{{% else %}}{{{{ rem }}}}s"
        f"{{% endif %}}\n"
    )


def _build_timer_card(lang: str) -> dict:
    """Build the timers card using a markdown card with plain Jinja2 text rows."""
    idle = _t(lang, "timer_idle")
    rows = [
        _timer_row(_t(lang, "timer_over_immediate"),  "⚡", "over_immediate_remaining_sec", idle),
        _timer_row(_t(lang, "timer_over_delayed"),    "🕐", "over_delayed_remaining_sec",   idle),
        _timer_row(_t(lang, "timer_stop_cooldown"),   "⏸", "stop_cooldown_remaining_sec",   idle),
        _timer_row(_t(lang, "timer_under_threshold"), "🔄", "under_threshold_remaining_sec", idle),
        _timer_row(_t(lang, "timer_start_cooldown"),  "⏱", "start_cooldown_remaining_sec",  idle),
    ]

    return {
        "type": "markdown",
        "title": _t(lang, "timers_title"),
        "content": "\n".join(rows),
    }



def _build_reorder_card(lang: str, loads: list[dict]) -> dict:
    """Build a grid card with up/down buttons to reorder loads."""
    cards = []
    n = len(loads)
    for i, load in enumerate(loads):
        name = load.get(LOAD_NAME, f"Load {i + 1}")
        priority = _priority_label(lang, i, n)

        # Label button (non-interactive, shows name + priority)
        cards.append({
            "type": "button",
            "name": name,
            "show_state": False,
            "show_icon": False,
            "tap_action": {"action": "none"},
            "icon": "",
        })

        # ▲ Move up (disabled for first load)
        up_action: dict = (
            {"action": "none"}
            if i == 0
            else {
                "action": "perform-action",
                "perform_action": "power_control.move_load",
                "data": {"load_index": i, "direction": "up"},
            }
        )
        cards.append({
            "type": "button",
            "name": " ",
            "show_state": False,
            "icon": "mdi:chevron-up",
            "tap_action": up_action,
        })

        # ▼ Move down (disabled for last load)
        down_action: dict = (
            {"action": "none"}
            if i == n - 1
            else {
                "action": "perform-action",
                "perform_action": "power_control.move_load",
                "data": {"load_index": i, "direction": "down"},
            }
        )
        cards.append({
            "type": "button",
            "name": " ",
            "show_state": False,
            "icon": "mdi:chevron-down",
            "tap_action": down_action,
        })

    return {
        "type": "grid",
        "title": _t(lang, "reorder_title"),
        "columns": 3,
        "square": False,
        "cards": cards,
    }


# ── Dashboard content builder ──────────────────────────────────────────────────

def _build_shed_history_card(lang: str, load_slugs: list[tuple[str, str]]) -> dict:
    """Build a history-graph card tracking suspended_power for each load.

    Args:
        load_slugs: list of (name, suspended_sensor_entity_id) tuples.
    """
    entities = [
        {"entity": entity_id, "name": name}
        for name, entity_id in load_slugs
    ]
    return {
        "type": "history-graph",
        "title": _t(lang, "shed_history_title"),
        "hours_to_show": 3,
        "refresh_interval": 30,
        "entities": entities,
    }



def _build_dashboard_config(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """Build the full Lovelace dashboard config dict for this entry."""
    # Invalidate strings cache on each rebuild so language changes are picked up
    _STRINGS_CACHE.clear()
    # Resolve language: use HA language, fall back to "en"
    # Resolve language from entry config (set by user during setup),
    # falling back to HA system language and then "en".
    raw_lang = (
        entry.data.get(CONF_DASHBOARD_LANGUAGE)
        or getattr(hass.config, "language", "en")
        or "en"
    )
    lang = raw_lang.split("-")[0].lower()
    if not (_TRANSLATIONS_DIR / f"{lang}.json").exists():
        lang = "en"
    _LOGGER.debug(
        "[%s] Building dashboard with lang=%s, gauge_title=%r",
        DOMAIN, lang, _t(lang, "gauge_title"),
    )

    data = entry.data
    loads: list[dict] = data.get(CONF_LOADS, [])
    threshold_delayed = data.get(CONF_THRESHOLD_DELAYED, 3000)
    threshold_immediate = data.get(CONF_THRESHOLD_IMMEDIATE, 3300)
    gauge_max = int(threshold_immediate * 1.15)

    global_sensor: str = data.get(CONF_GLOBAL_POWER_SENSOR, "")
    delay_imm_sec: int = int(data.get(CONF_DELAY_IMMEDIATE_SEC, 10))
    delay_del_min: int = int(data.get(CONF_DELAY_DELAYED_MIN, 3))
    wait_stops_sec: int = int(data.get(CONF_WAIT_BETWEEN_STOPS_SEC, 10))
    wait_starts_min: int = int(data.get(CONF_WAIT_BETWEEN_STARTS_MIN, 5))
    wait_before_min: int = int(data.get(CONF_WAIT_BEFORE_START_MIN, 5))
    notify_entity: str = data.get(CONF_NOTIFY_ENTITY, "")

    # ── Per-load cards ────────────────────────────────────────────────────────
    load_cards = []
    load_slugs: list[tuple[str, str]] = []  # (name, suspended_sensor_entity_id)
    for i, load in enumerate(loads):
        name = load.get(LOAD_NAME, f"Load {i + 1}")
        name_slug = slugify(f"power_control {name} suspended power")
        load_slugs.append((name, f"sensor.{name_slug}"))
        switch_entity = load.get("switch", "")
        power_sensor = load.get("power_sensor", "")
        auto_restart = load.get("auto_restart", True)
        suspended_sensor = f"sensor.{name_slug}"
        priority = _priority_label(lang, i, len(loads))

        entities: list[dict] = [{"type": "section", "label": _t(lang, "section_status")}]
        if switch_entity:
            entities.append({
                "entity": switch_entity,
                "name": _t(lang, "switch_label"),
                "icon": "mdi:power-socket-it",
            })
        if power_sensor:
            entities.append({
                "entity": power_sensor,
                "name": _t(lang, "current_power"),
                "icon": "mdi:lightning-bolt",
            })
        entities.append({
            "entity": suspended_sensor,
            "name": _t(lang, "suspended_label"),
            "icon": "mdi:pause-circle-outline",
        })
        entities.append({
            "type": "attribute",
            "entity": suspended_sensor,
            "attribute": "auto_restart",
            "name": _t(lang, "auto_restart_label"),
            "icon": "mdi:restart",
        })

        load_cards.append({
            "type": "entities",
            "title": f"{name} — {priority}",
            "show_header_toggle": False,
            "entities": entities,
        })

    # ── Settings card ─────────────────────────────────────────────────────────
    settings_card: dict = {
        "type": "entities",
        "title": _t(lang, "settings_title"),
        "show_header_toggle": False,
        "entities": [
            # ── Power sensor ───────────────────────────────────────────────
            {"type": "section", "label": _t(lang, "power_sensor_label")},
            {
                "entity": global_sensor if global_sensor else "sensor.power_control_current_power",
                "name": _t(lang, "power_sensor_label"),
                "icon": "mdi:meter-electric" if global_sensor else "mdi:sigma",
            },
            # ── Thresholds ─────────────────────────────────────────────────
            {"type": "section", "label": _t(lang, "thresholds_title")},
            {
                "entity": "sensor.power_control_immediate_threshold",
                "name": _t(lang, "threshold_immediate"),
                "icon": "mdi:flash-alert",
            },
            {
                "entity": "sensor.power_control_delayed_threshold",
                "name": _t(lang, "threshold_delayed"),
                "icon": "mdi:flash-outline",
            },
            # ── Timing ─────────────────────────────────────────────────────
            {"type": "section", "label": _t(lang, "timing_section")},
            {
                "type": "attribute",
                "entity": "sensor.power_control_current_power",
                "attribute": "cfg_delay_immediate_sec",
                "name": _t(lang, "delay_immediate_label"),
                "icon": "mdi:timer-outline",
                "secondary_info": "none",
                "suffix": _t(lang, "unit_seconds"),
            },
            {
                "type": "attribute",
                "entity": "sensor.power_control_current_power",
                "attribute": "cfg_delay_delayed_min",
                "name": _t(lang, "delay_delayed_label"),
                "icon": "mdi:timer-sand",
                "secondary_info": "none",
                "suffix": _t(lang, "unit_minutes"),
            },
            {
                "type": "attribute",
                "entity": "sensor.power_control_current_power",
                "attribute": "cfg_wait_between_stops_sec",
                "name": _t(lang, "wait_stops_label"),
                "icon": "mdi:pause",
                "secondary_info": "none",
                "suffix": _t(lang, "unit_seconds"),
            },
            {
                "type": "attribute",
                "entity": "sensor.power_control_current_power",
                "attribute": "cfg_wait_before_start_min",
                "name": _t(lang, "wait_before_start_label"),
                "icon": "mdi:clock-start",
                "secondary_info": "none",
                "suffix": _t(lang, "unit_minutes"),
            },
            {
                "type": "attribute",
                "entity": "sensor.power_control_current_power",
                "attribute": "cfg_wait_between_starts_min",
                "name": _t(lang, "wait_starts_label"),
                "icon": "mdi:play-circle-outline",
                "secondary_info": "none",
                "suffix": _t(lang, "unit_minutes"),
            },
            # ── Notification ───────────────────────────────────────────────
            {"type": "section", "label": _t(lang, "notify_label")},
            {
                "type": "attribute",
                "entity": "sensor.power_control_current_power",
                "attribute": "cfg_notify_entity",
                "name": _t(lang, "notify_label"),
                "icon": "mdi:bell-outline",
                "secondary_info": "none",
                "suffix": "",
            },
        ],
    }

    return {
        "views": [{
            "title": _t(lang, "view_title"),
            "path": "panoramica",
            "icon": "mdi:lightning-bolt-circle",
            "cards": [
                # ── Status row + gauge ────────────────────────────────────────
                {
                    "type": "vertical-stack",
                    "cards": [
                        {
                            "type": "horizontal-stack",
                            "cards": [
                                {
                                    "type": "tile",
                                    "entity": "switch.power_control_attivo",
                                    "name": _t(lang, "system_status"),
                                    "icon": "mdi:car-cruise-control",
                                    "color": "green",
                                },
                                {
                                    "type": "tile",
                                    "entity": "sensor.power_control_current_power",
                                    "name": _t(lang, "current_power"),
                                    "icon": "mdi:lightning-bolt",
                                },
                                {
                                    "type": "tile",
                                    "entity": "sensor.power_control_suspended_power",
                                    "name": _t(lang, "suspended_power"),
                                    "icon": "mdi:pause-circle-outline",
                                    "color": "orange",
                                },
                            ],
                        },
                        {
                            "type": "gauge",
                            "entity": "sensor.power_control_current_power",
                            "name": _t(lang, "gauge_title"),
                            "unit": "W",
                            "min": 0,
                            "max": gauge_max,
                            "needle": True,
                            "segments": [
                                {"from": 0, "color": "#28a745"},
                                {"from": int(threshold_delayed), "color": "#ffc107"},
                                {"from": int(threshold_immediate), "color": "#dc3545"},
                            ],
                        },
                        # ── Timer card ────────────────────────────────────────
                        _build_timer_card(lang),
                    ],
                },
                # ── History graph ─────────────────────────────────────────────
                {
                    "type": "history-graph",
                    "title": _t(lang, "history_title"),
                    "hours_to_show": 1,
                    "refresh_interval": 30,
                    "entities": [
                        {
                            "entity": "sensor.power_control_current_power",
                            "name": _t(lang, "current_power"),
                        },
                        {
                            "entity": "sensor.power_control_suspended_power",
                            "name": _t(lang, "suspended_power"),
                        },
                        {
                            "entity": "sensor.power_control_immediate_threshold",
                            "name": _t(lang, "threshold_immediate"),
                        },
                        {
                            "entity": "sensor.power_control_delayed_threshold",
                            "name": _t(lang, "threshold_delayed"),
                        },
                    ],
                },
                # ── Shed history card ─────────────────────────────────────────
                _build_shed_history_card(lang, load_slugs),
                # ── Configuration card ────────────────────────────────────────
                settings_card,
                # ── Reorder card ──────────────────────────────────────────────
                _build_reorder_card(lang, loads),
                # ── Per-load cards ────────────────────────────────────────────
                {
                    "type": "vertical-stack",
                    "title": _t(lang, "loads_title"),
                    "cards": load_cards,
                },
            ],
        }]
    }


# ── Creation logic ─────────────────────────────────────────────────────────────

async def _do_create_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Create or overwrite the Power Control Lovelace dashboard."""
    dashboards = _get_lovelace_dashboards(hass)
    if dashboards is None:
        _LOGGER.error("[%s] Lovelace not available — dashboard not created", DOMAIN)
        return False

    title = entry.data.get(CONF_INSTANCE_NAME, "Power Control")
    require_admin = entry.data.get(CONF_DASHBOARD_REQUIRE_ADMIN, False)

    # Check stored version: if outdated, force regeneration
    existing_store = dashboards.get(DASHBOARD_URL_PATH) if dashboards else None
    if existing_store is not None:
        try:
            stored_config = await existing_store.async_load()
            stored_version = (stored_config or {}).get("version", 0)
        except Exception:  # noqa: BLE001
            stored_version = 0
        if stored_version < DASHBOARD_VERSION:
            _LOGGER.info(
                "[%s] Dashboard version %s < %s — regenerating",
                DOMAIN, stored_version, DASHBOARD_VERSION,
            )
            # Remove from dashboards dict so the creation branch runs
            dashboards.pop(DASHBOARD_URL_PATH, None)
            dashboards = _get_lovelace_dashboards(hass)

    if DASHBOARD_URL_PATH not in (dashboards or {}):
        # Inject LovelaceStorage directly — never use DashboardsCollection.async_create_item
        # because its internal CHANGE_ADDED listener calls _register_panel immediately,
        # before we have a chance to write the dashboard content. This causes the
        # frontend to see an empty "New section" dashboard on first load.
        item_config = {
            "id": DASHBOARD_URL_PATH,
            CONF_URL_PATH: DASHBOARD_URL_PATH,
            CONF_TITLE: title,
            CONF_ICON: "mdi:lightning-bolt-circle",
            CONF_SHOW_IN_SIDEBAR: True,
            CONF_REQUIRE_ADMIN: require_admin,
        }
        dashboards[DASHBOARD_URL_PATH] = lv_dashboard.LovelaceStorage(hass, item_config)
        _LOGGER.debug("[%s] LovelaceStorage injected for /%s", DOMAIN, DASHBOARD_URL_PATH)
    else:
        _LOGGER.debug("[%s] Dashboard /%s exists — overwriting content", DOMAIN, DASHBOARD_URL_PATH)

    dashboards = _get_lovelace_dashboards(hass)
    dashboard_store = dashboards.get(DASHBOARD_URL_PATH) if dashboards else None
    if dashboard_store is None:
        _LOGGER.error("[%s] Dashboard store not found — cannot save content", DOMAIN)
        return False

    config = _build_dashboard_config(hass, entry)
    config["version"] = DASHBOARD_VERSION
    await dashboard_store.async_save(config)
    # async_save already populates _data internally — no need to call async_load.

    # Register (or update) the panel only after content is in memory,
    # so the frontend never sees an empty dashboard on first load.
    _register_dashboard_panel(
        hass, title, "mdi:lightning-bolt-circle",
        require_admin=require_admin,
        update=DASHBOARD_URL_PATH in (_get_lovelace_dashboards(hass) or {}),
    )

    _LOGGER.info(
        "[%s] Dashboard saved at /%s (%d load cards)",
        DOMAIN, DASHBOARD_URL_PATH, len(entry.data.get(CONF_LOADS, [])),
    )
    return True


async def async_rebuild_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rebuild and save the dashboard immediately (e.g. after a reorder)."""
    await _do_create_dashboard(hass, entry)


async def async_create_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Schedule dashboard creation after HA has fully started."""
    if hass.state == CoreState.running:
        hass.async_create_task(_do_create_dashboard(hass, entry))
    else:
        @callback
        def _on_ha_started(event) -> None:  # type: ignore[type-arg]
            hass.async_create_task(_do_create_dashboard(hass, entry))

        hass.bus.async_listen_once("homeassistant_started", _on_ha_started)
        _LOGGER.debug("[%s] Dashboard creation deferred to homeassistant_started", DOMAIN)


async def async_dashboard_exists(hass: HomeAssistant, entry: ConfigEntry) -> bool:  # noqa: ARG001
    """Return True if the Power Control dashboard is already present in lovelace."""
    dashboards = _get_lovelace_dashboards(hass)
    return bool(dashboards and DASHBOARD_URL_PATH in dashboards)


async def async_remove_dashboard(hass: HomeAssistant) -> None:
    """Remove the Power Control Lovelace dashboard and its sidebar panel."""
    # Remove sidebar panel
    try:
        frontend.async_remove_panel(hass, DASHBOARD_URL_PATH)
        _LOGGER.debug("[%s] Sidebar panel '%s' removed", DOMAIN, DASHBOARD_URL_PATH)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("[%s] Could not remove panel (non-fatal): %s", DOMAIN, err)

    # Remove dashboard from lovelace dashboards dict
    dashboards = _get_lovelace_dashboards(hass)
    if dashboards and DASHBOARD_URL_PATH in dashboards:
        dashboards.pop(DASHBOARD_URL_PATH)
        _LOGGER.debug("[%s] Dashboard '%s' removed from lovelace", DOMAIN, DASHBOARD_URL_PATH)
    else:
        _LOGGER.debug("[%s] Dashboard '%s' not found in lovelace — nothing to remove", DOMAIN, DASHBOARD_URL_PATH)
