"""Programmatic Lovelace dashboard creation for Power Control."""
from __future__ import annotations

import logging

from homeassistant.components.lovelace import (
    CONF_ICON,
    CONF_REQUIRE_ADMIN,
    CONF_SHOW_IN_SIDEBAR,
    CONF_TITLE,
    DOMAIN as LOVELACE_DOMAIN,
)
from homeassistant.components.lovelace.const import CONF_URL_PATH, CONF_ALLOW_SINGLE_WORD
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_INSTANCE_NAME, CONF_THRESHOLD_DELAYED, CONF_LOADS, LOAD_NAME

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL_PATH = "power-control"


def _build_dashboard_config(entry: ConfigEntry) -> dict:
    """Build the full Lovelace dashboard config dict for this entry."""
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

        priority_label = "Alta priorità" if i == 0 else (
            "Bassa priorità" if i == len(loads) - 1 else f"Priorità {i + 1}"
        )

        card: dict = {
            "type": "entities",
            "title": f"{name} — {priority_label}",
            "show_header_toggle": False,
            "entities": [
                {"type": "section", "label": "Stato"},
            ],
        }

        if switch_entity:
            card["entities"].append({
                "entity": switch_entity,
                "name": "Interruttore",
                "icon": "mdi:power-socket-it",
            })

        card["entities"].append({
            "entity": suspended_sensor,
            "name": "Potenza sospesa",
            "icon": "mdi:pause-circle-outline",
        })

        card["entities"].extend([
            {"type": "section", "label": "Controllo"},
            {
                "type": "button",
                "name": "Forza distacco",
                "icon": "mdi:power-off",
                "tap_action": {
                    "action": "call-service",
                    "service": f"{DOMAIN}.force_stop_load",
                    "data": {"load_index": i},
                },
            },
            {
                "type": "button",
                "name": "Forza riattivazione",
                "icon": "mdi:power-on",
                "tap_action": {
                    "action": "call-service",
                    "service": f"{DOMAIN}.force_start_load",
                    "data": {"load_index": i},
                },
            },
        ])

        load_cards.append(card)

    # ── Suspended power sensors for history graph ─────────────────────────────
    history_entities = [
        {"entity": "sensor.power_control_potenza_attuale", "name": "Potenza attuale"},
        {"entity": "sensor.power_control_potenza_sospesa", "name": "Potenza sospesa"},
        {"entity": "sensor.power_control_soglia_distacco_immediato", "name": "Soglia immediata"},
        {"entity": "sensor.power_control_soglia_distacco_ritardato", "name": "Soglia ritardata"},
    ]

    # ── Full dashboard config ─────────────────────────────────────────────────
    return {
        "views": [
            {
                "title": "Panoramica",
                "path": "panoramica",
                "icon": "mdi:lightning-bolt-circle",
                "cards": [
                    # Row 1: master switch + live tiles
                    {
                        "type": "vertical-stack",
                        "cards": [
                            {
                                "type": "horizontal-stack",
                                "cards": [
                                    {
                                        "type": "tile",
                                        "entity": "switch.power_control_attivo",
                                        "name": "Power Control",
                                        "icon": "mdi:car-cruise-control",
                                        "color": "green",
                                    },
                                    {
                                        "type": "tile",
                                        "entity": "sensor.power_control_potenza_attuale",
                                        "name": "Potenza attuale",
                                        "icon": "mdi:lightning-bolt",
                                    },
                                    {
                                        "type": "tile",
                                        "entity": "sensor.power_control_potenza_sospesa",
                                        "name": "Potenza sospesa",
                                        "icon": "mdi:pause-circle-outline",
                                        "color": "orange",
                                    },
                                ],
                            },
                            # Gauge
                            {
                                "type": "gauge",
                                "entity": "sensor.power_control_potenza_attuale",
                                "name": "Carico impianto",
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
                            # Threshold badges
                            {
                                "type": "entities",
                                "title": "Soglie configurate",
                                "show_header_toggle": False,
                                "entities": [
                                    {
                                        "entity": "sensor.power_control_soglia_distacco_immediato",
                                        "name": "Soglia immediata",
                                        "icon": "mdi:flash-alert",
                                    },
                                    {
                                        "entity": "sensor.power_control_soglia_distacco_ritardato",
                                        "name": "Soglia ritardata",
                                        "icon": "mdi:flash-outline",
                                    },
                                ],
                            },
                        ],
                    },
                    # History graph
                    {
                        "type": "history-graph",
                        "title": "Andamento potenza (ultima ora)",
                        "hours_to_show": 1,
                        "refresh_interval": 30,
                        "entities": history_entities,
                    },
                    # Per-load cards
                    {
                        "type": "vertical-stack",
                        "title": "Carichi gestiti",
                        "cards": load_cards,
                    },
                    # Quick actions
                    {
                        "type": "entities",
                        "title": "Azioni rapide",
                        "show_header_toggle": False,
                        "entities": [
                            {
                                "type": "button",
                                "name": "Abilita Power Control",
                                "icon": "mdi:check-circle-outline",
                                "tap_action": {
                                    "action": "call-service",
                                    "service": f"{DOMAIN}.enable",
                                },
                            },
                            {
                                "type": "button",
                                "name": "Disabilita Power Control",
                                "icon": "mdi:close-circle-outline",
                                "tap_action": {
                                    "action": "call-service",
                                    "service": f"{DOMAIN}.disable",
                                },
                            },
                        ],
                    },
                ],
            }
        ]
    }


async def async_create_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Create (or overwrite) the Power Control Lovelace dashboard.

    Returns True on success, False if lovelace is not available or
    the dashboard could not be created.
    """
    lovelace_data = hass.data.get(LOVELACE_DOMAIN)
    if not lovelace_data:
        _LOGGER.warning(
            "[%s] Lovelace not available — dashboard not created", DOMAIN
        )
        return False

    dashboards_collection = lovelace_data.get("dashboards_collection")
    if not dashboards_collection:
        _LOGGER.warning(
            "[%s] Lovelace dashboards_collection not available", DOMAIN
        )
        return False

    title = entry.data.get(CONF_INSTANCE_NAME, "Power Control")

    # Create the dashboard container if it doesn't exist yet
    existing = lovelace_data.get("dashboards", {})
    if DASHBOARD_URL_PATH not in existing:
        try:
            await dashboards_collection.async_create_item(
                {
                    CONF_ALLOW_SINGLE_WORD: True,
                    CONF_ICON: "mdi:lightning-bolt-circle",
                    CONF_TITLE: title,
                    CONF_URL_PATH: DASHBOARD_URL_PATH,
                    CONF_SHOW_IN_SIDEBAR: True,
                    CONF_REQUIRE_ADMIN: False,
                }
            )
            _LOGGER.info("[%s] Dashboard container created at /%s", DOMAIN, DASHBOARD_URL_PATH)
        except Exception as err:
            _LOGGER.error("[%s] Could not create dashboard container: %s", DOMAIN, err)
            return False
    else:
        _LOGGER.debug(
            "[%s] Dashboard /%s already exists — overwriting content",
            DOMAIN, DASHBOARD_URL_PATH,
        )

    # Write the dashboard content
    dashboard_store = lovelace_data.get("dashboards", {}).get(DASHBOARD_URL_PATH)
    if not dashboard_store:
        _LOGGER.error(
            "[%s] Dashboard store for /%s not found after creation",
            DOMAIN, DASHBOARD_URL_PATH,
        )
        return False

    config = _build_dashboard_config(entry)
    await dashboard_store.async_save(config)
    _LOGGER.info(
        "[%s] Dashboard saved at /%s (%d load cards)",
        DOMAIN, DASHBOARD_URL_PATH, len(entry.data.get(CONF_LOADS, [])),
    )
    return True
