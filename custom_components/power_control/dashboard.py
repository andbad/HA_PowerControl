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
    LOAD_NAME,
)

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL_PATH = "power-control"
DASHBOARD_VERSION = 2  # increment to force regeneration on next HA start

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
    hass: HomeAssistant, title: str, icon: str, update: bool = False
) -> None:
    """Register (or update) the sidebar panel for our dashboard."""
    frontend.async_register_built_in_panel(
        hass,
        "lovelace",
        sidebar_title=title,
        sidebar_icon=icon,
        frontend_url_path=DASHBOARD_URL_PATH,
        config={"mode": MODE_STORAGE},
        require_admin=False,
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


def _timer_bar_html(
    label: str,
    icon: str,
    attr_remaining: str,
    attr_pct: str,
    bar_color_active: str = "#3b82f6",
    bar_color_idle: str = "#374151",
) -> str:
    """Return HTML for a single timer row with progress bar.

    The Jinja2 inside markdown cards is evaluated by HA at render time,
    so we can reference state_attr() directly.
    """
    entity = "sensor.power_control_potenza_attuale"
    return (
        f"<div style='margin:6px 0'>"
        f"<div style='display:flex;align-items:center;justify-content:space-between;"
        f"font-size:0.85em;margin-bottom:3px'>"
        f"<span>{icon} {label}: </span>"
        f"{{% set rem = state_attr('{entity}','{attr_remaining}') %}}"
        f"<span style='color:var(--secondary-text-color);font-size:0.9em'>"
        f"{{% if rem is none %}}—"
        f"{{% elif rem >= 60 %}}{{% set m = (rem // 60)|int %}}{{% set s = (rem % 60)|int %}}"
        f"{{{{ m }}}}m {{{{ s }}}}s"
        f"{{% else %}}{{{{ rem }}}}s"
        f"{{% endif %}}"
        f"</span>"
        f"</div>"
        f"{{% set pct = state_attr('{entity}','{attr_pct}') or 0 %}}"
        f"{{% set active = state_attr('{entity}','{attr_remaining}') is not none %}}"
        f"<div style='background:#1f2937;border-radius:4px;height:6px;overflow:hidden'>"
        f"<div style='height:6px;border-radius:4px;transition:width 1s ease;"
        f"background:{{% if active %}}{bar_color_active}{{% else %}}{bar_color_idle}{{% endif %}};"
        f"width:{{{{ pct }}}}%'></div>"
        f"</div>"
        f"</div>"
    )


def _build_timer_card(lang: str) -> dict:
    """Build the timers card using a markdown card with inline progress bars."""
    rows = [
        _timer_bar_html(
            _t(lang, "timer_over_immediate"),
            "⚡",
            "over_immediate_remaining_sec",
            "over_immediate_pct",
            bar_color_active="#ef4444",   # red — danger
        ),
        _timer_bar_html(
            _t(lang, "timer_over_delayed"),
            "🕐",
            "over_delayed_remaining_sec",
            "over_delayed_pct",
            bar_color_active="#f97316",   # orange — warning
        ),
        _timer_bar_html(
            _t(lang, "timer_stop_cooldown"),
            "⏸",
            "stop_cooldown_remaining_sec",
            "stop_cooldown_pct",
            bar_color_active="#8b5cf6",   # purple — cooldown
        ),
        _timer_bar_html(
            _t(lang, "timer_under_threshold"),
            "🔄",
            "under_threshold_remaining_sec",
            "under_threshold_pct",
            bar_color_active="#22c55e",   # green — restart
        ),
        _timer_bar_html(
            _t(lang, "timer_start_cooldown"),
            "⏱",
            "start_cooldown_remaining_sec",
            "start_cooldown_pct",
            bar_color_active="#06b6d4",   # cyan — between restarts
        ),
    ]

    content = "\n".join(rows)

    return {
        "type": "markdown",
        "title": _t(lang, "timers_title"),
        "content": content,
    }


# ── Dashboard content builder ──────────────────────────────────────────────────

def _build_dashboard_config(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """Build the full Lovelace dashboard config dict for this entry."""
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
    for i, load in enumerate(loads):
        name = load.get(LOAD_NAME, f"Carico {i + 1}")
        name_slug = name.lower().replace(" ", "_")
        switch_entity = load.get("switch", "")
        power_sensor = load.get("power_sensor", "")
        auto_restart = load.get("auto_restart", True)
        suspended_sensor = f"sensor.power_control_{name_slug}_potenza_sospesa"
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
                "entity": global_sensor if global_sensor else "sensor.power_control_potenza_attuale",
                "name": _t(lang, "power_sensor_label"),
                "icon": "mdi:meter-electric" if global_sensor else "mdi:sigma",
            },
            # ── Thresholds ─────────────────────────────────────────────────
            {"type": "section", "label": _t(lang, "thresholds_title")},
            {
                "entity": "sensor.power_control_soglia_distacco_immediato",
                "name": _t(lang, "threshold_immediate"),
                "icon": "mdi:flash-alert",
            },
            {
                "entity": "sensor.power_control_soglia_distacco_ritardato",
                "name": _t(lang, "threshold_delayed"),
                "icon": "mdi:flash-outline",
            },
            # ── Timing ─────────────────────────────────────────────────────
            {"type": "section", "label": _t(lang, "timing_section")},
            {
                "type": "attribute",
                "entity": "sensor.power_control_soglia_distacco_immediato",
                "attribute": "unit_of_measurement",  # placeholder — real value injected via secondary_info workaround below
                "name": _t(lang, "delay_immediate_label"),
                "icon": "mdi:timer-outline",
                "secondary_info": "none",
                "suffix": f"{delay_imm_sec} {_t(lang, 'unit_seconds')}",
            },
            {
                "type": "attribute",
                "entity": "sensor.power_control_soglia_distacco_ritardato",
                "attribute": "unit_of_measurement",
                "name": _t(lang, "delay_delayed_label"),
                "icon": "mdi:timer-sand",
                "secondary_info": "none",
                "suffix": f"{delay_del_min} {_t(lang, 'unit_minutes')}",
            },
            {
                "type": "attribute",
                "entity": "sensor.power_control_soglia_distacco_immediato",
                "attribute": "unit_of_measurement",
                "name": _t(lang, "wait_stops_label"),
                "icon": "mdi:pause",
                "secondary_info": "none",
                "suffix": f"{wait_stops_sec} {_t(lang, 'unit_seconds')}",
            },
            {
                "type": "attribute",
                "entity": "sensor.power_control_soglia_distacco_ritardato",
                "attribute": "unit_of_measurement",
                "name": _t(lang, "wait_before_start_label"),
                "icon": "mdi:clock-start",
                "secondary_info": "none",
                "suffix": f"{wait_before_min} {_t(lang, 'unit_minutes')}",
            },
            {
                "type": "attribute",
                "entity": "sensor.power_control_soglia_distacco_ritardato",
                "attribute": "unit_of_measurement",
                "name": _t(lang, "wait_starts_label"),
                "icon": "mdi:play-circle-outline",
                "secondary_info": "none",
                "suffix": f"{wait_starts_min} {_t(lang, 'unit_minutes')}",
            },
            # ── Notification ───────────────────────────────────────────────
            {"type": "section", "label": _t(lang, "notify_label")},
            {
                "type": "attribute",
                "entity": "sensor.power_control_potenza_attuale",
                "attribute": "unit_of_measurement",
                "name": _t(lang, "notify_label"),
                "icon": "mdi:bell-outline",
                "secondary_info": "none",
                "suffix": notify_entity if notify_entity else _t(lang, "notify_none"),
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
                                    "entity": "sensor.power_control_potenza_attuale",
                                    "name": _t(lang, "current_power"),
                                    "icon": "mdi:lightning-bolt",
                                },
                                {
                                    "type": "tile",
                                    "entity": "sensor.power_control_potenza_sospesa",
                                    "name": _t(lang, "suspended_power"),
                                    "icon": "mdi:pause-circle-outline",
                                    "color": "orange",
                                },
                            ],
                        },
                        {
                            "type": "gauge",
                            "entity": "sensor.power_control_potenza_attuale",
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
                            "entity": "sensor.power_control_potenza_attuale",
                            "name": _t(lang, "current_power"),
                        },
                        {
                            "entity": "sensor.power_control_potenza_sospesa",
                            "name": _t(lang, "suspended_power"),
                        },
                        {
                            "entity": "sensor.power_control_soglia_distacco_immediato",
                            "name": _t(lang, "threshold_immediate"),
                        },
                        {
                            "entity": "sensor.power_control_soglia_distacco_ritardato",
                            "name": _t(lang, "threshold_delayed"),
                        },
                    ],
                },
                # ── Configuration card ────────────────────────────────────────
                settings_card,
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
            CONF_REQUIRE_ADMIN: False,
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
        update=DASHBOARD_URL_PATH in (_get_lovelace_dashboards(hass) or {}),
    )

    _LOGGER.info(
        "[%s] Dashboard saved at /%s (%d load cards)",
        DOMAIN, DASHBOARD_URL_PATH, len(entry.data.get(CONF_LOADS, [])),
    )
    return True


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
