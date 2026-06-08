"""Programmatic Lovelace dashboard creation for Power Control."""
from __future__ import annotations

import logging
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

from .const import DOMAIN, CONF_INSTANCE_NAME, CONF_THRESHOLD_DELAYED, CONF_LOADS, LOAD_NAME

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL_PATH = "power-control"


# ── Translations ───────────────────────────────────────────────────────────────
# Keys used in the dashboard. Each language provides all keys; any missing
# language falls back to English.

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "view_title":           "Overview",
        "system_status":        "Power Control",
        "current_power":        "Current power",
        "suspended_power":      "Suspended power",
        "gauge_title":          "Grid load",
        "thresholds_title":     "Configured thresholds",
        "threshold_immediate":  "Immediate threshold",
        "threshold_delayed":    "Delayed threshold",
        "history_title":        "Power trend (last hour)",
        "loads_title":          "Managed loads",
        "section_status":       "Status",
        "switch_label":         "Switch",
        "suspended_label":      "Suspended power",
        "priority_high":        "High priority",
        "priority_low":         "Low priority",
        "priority_n":           "Priority {n}",
    },
    "it": {
        "view_title":           "Panoramica",
        "system_status":        "Power Control",
        "current_power":        "Potenza attuale",
        "suspended_power":      "Potenza sospesa",
        "gauge_title":          "Carico impianto",
        "thresholds_title":     "Soglie configurate",
        "threshold_immediate":  "Soglia immediata",
        "threshold_delayed":    "Soglia ritardata",
        "history_title":        "Andamento potenza (ultima ora)",
        "loads_title":          "Carichi gestiti",
        "section_status":       "Stato",
        "switch_label":         "Interruttore",
        "suspended_label":      "Potenza sospesa",
        "priority_high":        "Alta priorità",
        "priority_low":         "Bassa priorità",
        "priority_n":           "Priorità {n}",
    },
    "de": {
        "view_title":           "Übersicht",
        "system_status":        "Power Control",
        "current_power":        "Aktuelle Leistung",
        "suspended_power":      "Suspendierte Leistung",
        "gauge_title":          "Netzlast",
        "thresholds_title":     "Konfigurierte Schwellwerte",
        "threshold_immediate":  "Sofortschwelle",
        "threshold_delayed":    "Verzögerungsschwelle",
        "history_title":        "Leistungsverlauf (letzte Stunde)",
        "loads_title":          "Verwaltete Verbraucher",
        "section_status":       "Status",
        "switch_label":         "Schalter",
        "suspended_label":      "Suspendierte Leistung",
        "priority_high":        "Hohe Priorität",
        "priority_low":         "Niedrige Priorität",
        "priority_n":           "Priorität {n}",
    },
    "fr": {
        "view_title":           "Vue d'ensemble",
        "system_status":        "Power Control",
        "current_power":        "Puissance actuelle",
        "suspended_power":      "Puissance suspendue",
        "gauge_title":          "Charge réseau",
        "thresholds_title":     "Seuils configurés",
        "threshold_immediate":  "Seuil immédiat",
        "threshold_delayed":    "Seuil différé",
        "history_title":        "Évolution de la puissance (dernière heure)",
        "loads_title":          "Charges gérées",
        "section_status":       "État",
        "switch_label":         "Interrupteur",
        "suspended_label":      "Puissance suspendue",
        "priority_high":        "Priorité haute",
        "priority_low":         "Priorité basse",
        "priority_n":           "Priorité {n}",
    },
    "es": {
        "view_title":           "Resumen",
        "system_status":        "Power Control",
        "current_power":        "Potencia actual",
        "suspended_power":      "Potencia suspendida",
        "gauge_title":          "Carga de red",
        "thresholds_title":     "Umbrales configurados",
        "threshold_immediate":  "Umbral inmediato",
        "threshold_delayed":    "Umbral diferido",
        "history_title":        "Evolución de potencia (última hora)",
        "loads_title":          "Cargas gestionadas",
        "section_status":       "Estado",
        "switch_label":         "Interruptor",
        "suspended_label":      "Potencia suspendida",
        "priority_high":        "Alta prioridad",
        "priority_low":         "Baja prioridad",
        "priority_n":           "Prioridad {n}",
    },
}


def _t(lang: str, key: str, **kwargs: Any) -> str:
    """Return translated string for key, falling back to English."""
    strings = _STRINGS.get(lang) or _STRINGS["en"]
    # fall back to English for individual missing keys
    text = strings.get(key) or _STRINGS["en"].get(key, key)
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


# ── Dashboard content builder ──────────────────────────────────────────────────

def _build_dashboard_config(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """Build the full Lovelace dashboard config dict for this entry."""
    # Resolve language: use HA language, fall back to "en"
    raw_lang = getattr(hass.config, "language", "en") or "en"
    lang = raw_lang.split("-")[0].lower()   # "pt-BR" → "pt", use "en" if not in table
    if lang not in _STRINGS:
        lang = "en"

    loads: list[dict] = entry.data.get(CONF_LOADS, [])
    threshold_delayed = entry.data.get(CONF_THRESHOLD_DELAYED, 3000)
    gauge_max = max(int(threshold_delayed * 1.5), 6000)

    # ── Per-load cards ────────────────────────────────────────────────────────
    load_cards = []
    for i, load in enumerate(loads):
        name = load.get(LOAD_NAME, f"Carico {i + 1}")
        name_slug = name.lower().replace(" ", "_")
        switch_entity = load.get("switch", "")
        suspended_sensor = f"sensor.power_control_{name_slug}_potenza_sospesa"
        priority = _priority_label(lang, i, len(loads))

        card: dict = {
            "type": "entities",
            "title": f"{name} — {priority}",
            "show_header_toggle": False,
            "entities": [{"type": "section", "label": _t(lang, "section_status")}],
        }
        if switch_entity:
            card["entities"].append({
                "entity": switch_entity,
                "name": _t(lang, "switch_label"),
                "icon": "mdi:power-socket-it",
            })
        card["entities"].append({
            "entity": suspended_sensor,
            "name": _t(lang, "suspended_label"),
            "icon": "mdi:pause-circle-outline",
        })
        load_cards.append(card)

    return {
        "views": [{
            "title": _t(lang, "view_title"),
            "path": "panoramica",
            "icon": "mdi:lightning-bolt-circle",
            "cards": [
                # ── Status row + gauge + thresholds ──────────────────────────
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
                                {"from": int(threshold_delayed * 0.8), "color": "#ffc107"},
                                {"from": threshold_delayed, "color": "#dc3545"},
                            ],
                        },
                        {
                            "type": "entities",
                            "title": _t(lang, "thresholds_title"),
                            "show_header_toggle": False,
                            "entities": [
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
                            ],
                        },
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

    if DASHBOARD_URL_PATH not in dashboards:
        try:
            collection = lv_dashboard.DashboardsCollection(hass)
            await collection.async_load()

            create_data: dict[str, Any] = {
                CONF_URL_PATH: DASHBOARD_URL_PATH,
                CONF_TITLE: title,
                CONF_ICON: "mdi:lightning-bolt-circle",
                CONF_SHOW_IN_SIDEBAR: True,
                CONF_REQUIRE_ADMIN: False,
                "allow_single_word": True,
            }
            await collection.async_create_item(create_data)
            _register_dashboard_panel(hass, title, "mdi:lightning-bolt-circle")
            _LOGGER.info("[%s] Dashboard container created at /%s", DOMAIN, DASHBOARD_URL_PATH)
        except Exception as err:
            _LOGGER.error("[%s] Could not create dashboard container: %s", DOMAIN, err)
            return False

        dashboards = _get_lovelace_dashboards(hass)
        if dashboards is None or DASHBOARD_URL_PATH not in dashboards:
            _LOGGER.debug("[%s] Injecting LovelaceStorage directly", DOMAIN)
            item_config = {
                "id": DASHBOARD_URL_PATH,
                CONF_URL_PATH: DASHBOARD_URL_PATH,
                CONF_TITLE: title,
                CONF_ICON: "mdi:lightning-bolt-circle",
                CONF_SHOW_IN_SIDEBAR: True,
                CONF_REQUIRE_ADMIN: False,
            }
            storage_obj = lv_dashboard.LovelaceStorage(hass, item_config)
            if dashboards is not None:
                dashboards[DASHBOARD_URL_PATH] = storage_obj
                _register_dashboard_panel(hass, title, "mdi:lightning-bolt-circle")
            else:
                _LOGGER.error("[%s] Cannot inject dashboard — dashboards dict not found", DOMAIN)
                return False
    else:
        _LOGGER.debug("[%s] Dashboard /%s exists — overwriting content", DOMAIN, DASHBOARD_URL_PATH)
        _register_dashboard_panel(hass, title, "mdi:lightning-bolt-circle", update=True)

    dashboards = _get_lovelace_dashboards(hass)
    dashboard_store = dashboards.get(DASHBOARD_URL_PATH) if dashboards else None
    if dashboard_store is None:
        _LOGGER.error("[%s] Dashboard store not found — cannot save content", DOMAIN)
        return False

    config = _build_dashboard_config(hass, entry)
    await dashboard_store.async_save(config)

    # Force the dashboard store to load its own data immediately.
    # Without this, the store is created but its in-memory config is empty
    # until the next HA restart, causing the dashboard to appear blank.
    try:
        await dashboard_store.async_load()
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("[%s] Dashboard async_load after save raised (non-fatal): %s", DOMAIN, err)

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