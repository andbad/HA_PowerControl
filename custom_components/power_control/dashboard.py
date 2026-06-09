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
    LOAD_NAME,
)

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL_PATH = "power-control"


# ── Translations ───────────────────────────────────────────────────────────────
# Keys used in the dashboard. Each language provides all keys; any missing
# language falls back to English.

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "view_title":                   "Overview",
        "system_status":                "Power Control",
        "current_power":                "Current power",
        "suspended_power":              "Suspended power",
        "gauge_title":                  "Grid load",
        "thresholds_title":             "Configured thresholds",
        "threshold_immediate":          "Immediate threshold",
        "threshold_delayed":            "Delayed threshold",
        "history_title":                "Power trend (last hour)",
        "loads_title":                  "Managed loads",
        "section_status":               "Status",
        "switch_label":                 "Switch",
        "suspended_label":              "Suspended power",
        "priority_high":                "High priority",
        "priority_low":                 "Low priority",
        "priority_n":                   "Priority {n}",
        # Settings card
        "settings_title":               "Configuration",
        "power_sensor_label":           "Power sensor",
        "power_sensor_virtual":         "Virtual (sum of loads)",
        "delay_immediate_label":        "Immediate trip delay",
        "delay_delayed_label":          "Delayed trip delay",
        "wait_stops_label":             "Wait between stops",
        "wait_starts_label":            "Wait between restarts",
        "wait_before_start_label":      "Wait before first restart",
        "notify_label":                 "Notification entity",
        "notify_none":                  "Not configured",
        "timing_section":               "Timing",
        "auto_restart_label":           "Auto restart",
        "unit_seconds":                 "s",
        "unit_minutes":                 "min",
        # Timers card
        "timers_title":                 "Active timers",
        "timer_over_immediate":         "Immediate trip arming",
        "timer_over_delayed":           "Delayed trip arming",
        "timer_stop_cooldown":          "Cooldown between stops",
        "timer_under_threshold":        "Restart countdown",
        "timer_start_cooldown":         "Cooldown between restarts",
        "timer_idle":                   "Idle",
        "timer_sec_remaining":          "{s}s remaining",
        "timer_min_remaining":          "{m}m {s}s remaining",
    },
    "it": {
        "view_title":                   "Panoramica",
        "system_status":                "Power Control",
        "current_power":                "Potenza attuale",
        "suspended_power":              "Potenza sospesa",
        "gauge_title":                  "Carico impianto",
        "thresholds_title":             "Soglie configurate",
        "threshold_immediate":          "Soglia immediata",
        "threshold_delayed":            "Soglia ritardata",
        "history_title":                "Andamento potenza (ultima ora)",
        "loads_title":                  "Carichi gestiti",
        "section_status":               "Stato",
        "switch_label":                 "Interruttore",
        "suspended_label":              "Potenza sospesa",
        "priority_high":                "Alta priorità",
        "priority_low":                 "Bassa priorità",
        "priority_n":                   "Priorità {n}",
        # Settings card
        "settings_title":               "Configurazione",
        "power_sensor_label":           "Sensore potenza",
        "power_sensor_virtual":         "Virtuale (somma dei carichi)",
        "delay_immediate_label":        "Ritardo distacco immediato",
        "delay_delayed_label":          "Ritardo distacco ritardato",
        "wait_stops_label":             "Attesa tra i distacchi",
        "wait_starts_label":            "Attesa tra le riattivazioni",
        "wait_before_start_label":      "Attesa prima della riattivazione",
        "notify_label":                 "Entità notifica",
        "notify_none":                  "Non configurata",
        "timing_section":               "Temporizzazioni",
        "auto_restart_label":           "Riavvio automatico",
        "unit_seconds":                 "s",
        "unit_minutes":                 "min",
        # Timers card
        "timers_title":                 "Timer attivi",
        "timer_over_immediate":         "Armamento distacco immediato",
        "timer_over_delayed":           "Armamento distacco ritardato",
        "timer_stop_cooldown":          "Attesa tra i distacchi",
        "timer_under_threshold":        "Conto alla rovescia riattivazione",
        "timer_start_cooldown":         "Attesa tra le riattivazioni",
        "timer_idle":                   "Inattivo",
        "timer_sec_remaining":          "{s}s rimanenti",
        "timer_min_remaining":          "{m}m {s}s rimanenti",
    },
    "de": {
        "view_title":                   "Übersicht",
        "system_status":                "Power Control",
        "current_power":                "Aktuelle Leistung",
        "suspended_power":              "Suspendierte Leistung",
        "gauge_title":                  "Netzlast",
        "thresholds_title":             "Konfigurierte Schwellwerte",
        "threshold_immediate":          "Sofortschwelle",
        "threshold_delayed":            "Verzögerungsschwelle",
        "history_title":                "Leistungsverlauf (letzte Stunde)",
        "loads_title":                  "Verwaltete Verbraucher",
        "section_status":               "Status",
        "switch_label":                 "Schalter",
        "suspended_label":              "Suspendierte Leistung",
        "priority_high":                "Hohe Priorität",
        "priority_low":                 "Niedrige Priorität",
        "priority_n":                   "Priorität {n}",
        # Settings card
        "settings_title":               "Konfiguration",
        "power_sensor_label":           "Leistungssensor",
        "power_sensor_virtual":         "Virtuell (Summe der Lasten)",
        "delay_immediate_label":        "Sofortverzögerung",
        "delay_delayed_label":          "Verzögerung (verzögert)",
        "wait_stops_label":             "Wartezeit zwischen Abschaltungen",
        "wait_starts_label":            "Wartezeit zwischen Einschaltungen",
        "wait_before_start_label":      "Wartezeit vor erster Einschaltung",
        "notify_label":                 "Benachrichtigungsentität",
        "notify_none":                  "Nicht konfiguriert",
        "timing_section":               "Zeiteinstellungen",
        "auto_restart_label":           "Automatischer Neustart",
        "unit_seconds":                 "s",
        "unit_minutes":                 "min",
        # Timers card
        "timers_title":                 "Aktive Timer",
        "timer_over_immediate":         "Sofortauslösung aktiv",
        "timer_over_delayed":           "Verzögerungsauslösung aktiv",
        "timer_stop_cooldown":          "Wartezeit zwischen Abschaltungen",
        "timer_under_threshold":        "Countdown Wiedereinschaltung",
        "timer_start_cooldown":         "Wartezeit zwischen Einschaltungen",
        "timer_idle":                   "Inaktiv",
        "timer_sec_remaining":          "{s}s verbleibend",
        "timer_min_remaining":          "{m}m {s}s verbleibend",
    },
    "fr": {
        "view_title":                   "Vue d'ensemble",
        "system_status":                "Power Control",
        "current_power":                "Puissance actuelle",
        "suspended_power":              "Puissance suspendue",
        "gauge_title":                  "Charge réseau",
        "thresholds_title":             "Seuils configurés",
        "threshold_immediate":          "Seuil immédiat",
        "threshold_delayed":            "Seuil différé",
        "history_title":                "Évolution de la puissance (dernière heure)",
        "loads_title":                  "Charges gérées",
        "section_status":               "État",
        "switch_label":                 "Interrupteur",
        "suspended_label":              "Puissance suspendue",
        "priority_high":                "Priorité haute",
        "priority_low":                 "Priorité basse",
        "priority_n":                   "Priorité {n}",
        # Settings card
        "settings_title":               "Configuration",
        "power_sensor_label":           "Capteur de puissance",
        "power_sensor_virtual":         "Virtuel (somme des charges)",
        "delay_immediate_label":        "Délai déclenchement immédiat",
        "delay_delayed_label":          "Délai déclenchement différé",
        "wait_stops_label":             "Attente entre coupures",
        "wait_starts_label":            "Attente entre réactivations",
        "wait_before_start_label":      "Attente avant première réactivation",
        "notify_label":                 "Entité de notification",
        "notify_none":                  "Non configuré",
        "timing_section":               "Temporisation",
        "auto_restart_label":           "Redémarrage automatique",
        "unit_seconds":                 "s",
        "unit_minutes":                 "min",
        # Timers card
        "timers_title":                 "Minuteries actives",
        "timer_over_immediate":         "Armement déclenchement immédiat",
        "timer_over_delayed":           "Armement déclenchement différé",
        "timer_stop_cooldown":          "Attente entre coupures",
        "timer_under_threshold":        "Compte à rebours réactivation",
        "timer_start_cooldown":         "Attente entre réactivations",
        "timer_idle":                   "Inactif",
        "timer_sec_remaining":          "{s}s restantes",
        "timer_min_remaining":          "{m}m {s}s restantes",
    },
    "es": {
        "view_title":                   "Resumen",
        "system_status":                "Power Control",
        "current_power":                "Potencia actual",
        "suspended_power":              "Potencia suspendida",
        "gauge_title":                  "Carga de red",
        "thresholds_title":             "Umbrales configurados",
        "threshold_immediate":          "Umbral inmediato",
        "threshold_delayed":            "Umbral diferido",
        "history_title":                "Evolución de potencia (última hora)",
        "loads_title":                  "Cargas gestionadas",
        "section_status":               "Estado",
        "switch_label":                 "Interruptor",
        "suspended_label":              "Potencia suspendida",
        "priority_high":                "Alta prioridad",
        "priority_low":                 "Baja prioridad",
        "priority_n":                   "Prioridad {n}",
        # Settings card
        "settings_title":               "Configuración",
        "power_sensor_label":           "Sensor de potencia",
        "power_sensor_virtual":         "Virtual (suma de cargas)",
        "delay_immediate_label":        "Retardo disparo inmediato",
        "delay_delayed_label":          "Retardo disparo diferido",
        "wait_stops_label":             "Espera entre cortes",
        "wait_starts_label":            "Espera entre reactivaciones",
        "wait_before_start_label":      "Espera antes de primera reactivación",
        "notify_label":                 "Entidad de notificación",
        "notify_none":                  "No configurado",
        "timing_section":               "Temporización",
        "auto_restart_label":           "Reinicio automático",
        "unit_seconds":                 "s",
        "unit_minutes":                 "min",
        # Timers card
        "timers_title":                 "Temporizadores activos",
        "timer_over_immediate":         "Armado disparo inmediato",
        "timer_over_delayed":           "Armado disparo diferido",
        "timer_stop_cooldown":          "Espera entre cortes",
        "timer_under_threshold":        "Cuenta atrás reactivación",
        "timer_start_cooldown":         "Espera entre reactivaciones",
        "timer_idle":                   "Inactivo",
        "timer_sec_remaining":          "{s}s restantes",
        "timer_min_remaining":          "{m}m {s}s restantes",
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
        f"<span>{icon} {label}</span>"
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
    raw_lang = getattr(hass.config, "language", "en") or "en"
    lang = raw_lang.split("-")[0].lower()   # "pt-BR" → "pt", use "en" if not in table
    if lang not in _STRINGS:
        lang = "en"

    data = entry.data
    loads: list[dict] = data.get(CONF_LOADS, [])
    threshold_delayed = data.get(CONF_THRESHOLD_DELAYED, 3000)
    threshold_immediate = data.get(CONF_THRESHOLD_IMMEDIATE, 3300)
    gauge_max = max(int(threshold_delayed * 1.5), 6000)

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
                                {"from": int(threshold_delayed * 0.8), "color": "#ffc107"},
                                {"from": threshold_delayed, "color": "#dc3545"},
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
                # ── Configuration card ────────────────────────────────────────
                settings_card,
                # ── Timer card ────────────────────────────────────────────────
                _build_timer_card(lang),
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
