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
    """Return the lovelace dashboards dict regardless of HA version.

    Older HA: hass.data["lovelace"] is a plain dict with key "dashboards".
    Newer HA: hass.data["lovelace"] is a LovelaceData dataclass with .dashboards attr.
    """
    lovelace_data = hass.data.get(LOVELACE_DOMAIN)
    if lovelace_data is None:
        return None
    if isinstance(lovelace_data, dict):
        return lovelace_data.get("dashboards")
    return getattr(lovelace_data, "dashboards", None)


def _build_dashboard_config(entry: ConfigEntry) -> dict:
    """Build the full Lovelace dashboard config dict for this entry."""
    loads: list[dict] = entry.data.get(CONF_LOADS, [])
    threshold_delayed = entry.data.get(CONF_THRESHOLD_DELAYED, 3000)
    gauge_max = max(int(threshold_delayed * 1.5), 6000)

    load_cards = []
    for i, load in enumerate(loads):
        name = load.get(LOAD_NAME, f"Carico {i + 1}")
        name_slug = name.lower().replace(" ", "_")
        switch_entity = load.get("switch", "")
        suspended_sensor = f"sensor.power_control_{name_slug}_potenza_sospesa"
        priority_label = (
            "Alta priorità" if i == 0
            else "Bassa priorità" if i == len(loads) - 1
            else f"Priorità {i + 1}"
        )
        card: dict = {
            "type": "entities",
            "title": f"{name} — {priority_label}",
            "show_header_toggle": False,
            "entities": [{"type": "section", "label": "Stato"}],
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

        load_cards.append(card)

    return {
        "views": [{
            "title": "Panoramica",
            "path": "panoramica",
            "icon": "mdi:lightning-bolt-circle",
            "cards": [
                {
                    "type": "vertical-stack",
                    "cards": [
                        {
                            "type": "horizontal-stack",
                            "cards": [
                                {"type": "tile", "entity": "switch.power_control_attivo",
                                 "name": "Power Control", "icon": "mdi:car-cruise-control", "color": "green"},
                                {"type": "tile", "entity": "sensor.power_control_potenza_attuale",
                                 "name": "Potenza attuale", "icon": "mdi:lightning-bolt"},
                                {"type": "tile", "entity": "sensor.power_control_potenza_sospesa",
                                 "name": "Potenza sospesa", "icon": "mdi:pause-circle-outline", "color": "orange"},
                            ],
                        },
                        {
                            "type": "gauge",
                            "entity": "sensor.power_control_potenza_attuale",
                            "name": "Carico impianto", "unit": "W", "min": 0, "max": gauge_max, "needle": True,
                            "segments": [
                                {"from": 0, "color": "#28a745"},
                                {"from": int(threshold_delayed * 0.8), "color": "#ffc107"},
                                {"from": threshold_delayed, "color": "#dc3545"},
                            ],
                        },
                        {
                            "type": "entities", "title": "Soglie configurate", "show_header_toggle": False,
                            "entities": [
                                {"entity": "sensor.power_control_soglia_distacco_immediato",
                                 "name": "Soglia immediata", "icon": "mdi:flash-alert"},
                                {"entity": "sensor.power_control_soglia_distacco_ritardato",
                                 "name": "Soglia ritardata", "icon": "mdi:flash-outline"},
                            ],
                        },
                    ],
                },
                {
                    "type": "history-graph",
                    "title": "Andamento potenza (ultima ora)",
                    "hours_to_show": 1, "refresh_interval": 30,
                    "entities": [
                        {"entity": "sensor.power_control_potenza_attuale", "name": "Potenza attuale"},
                        {"entity": "sensor.power_control_potenza_sospesa", "name": "Potenza sospesa"},
                        {"entity": "sensor.power_control_soglia_distacco_immediato", "name": "Soglia immediata"},
                        {"entity": "sensor.power_control_soglia_distacco_ritardato", "name": "Soglia ritardata"},
                    ],
                },
                {"type": "vertical-stack", "title": "Carichi gestiti", "cards": load_cards},
            ],
        }]
    }


async def _do_create_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Create or overwrite the Power Control Lovelace dashboard.

    Works on both old HA (dict-based lovelace data) and new HA (LovelaceData
    dataclass). Instead of relying on a pre-existing dashboards_collection in
    hass.data, we instantiate DashboardsCollection directly — the same way HA
    does internally — and wire a one-shot listener so the newly created
    dashboard gets added to the dashboards dict and saved to storage.
    """
    dashboards = _get_lovelace_dashboards(hass)
    if dashboards is None:
        _LOGGER.error("[%s] Lovelace not available — dashboard not created", DOMAIN)
        return False

    title = entry.data.get(CONF_INSTANCE_NAME, "Power Control")

    if DASHBOARD_URL_PATH not in dashboards:
        # Create a fresh DashboardsCollection, load existing storage data, then
        # create our dashboard entry.  The collection fires a CHANGE_ADDED event
        # which HA's own storage_dashboard_changed listener (registered during
        # lovelace setup) will handle — adding the LovelaceStorage object to
        # hass.data[lovelace]["dashboards"] and registering the frontend panel.
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
            _LOGGER.info("[%s] Dashboard container created at /%s", DOMAIN, DASHBOARD_URL_PATH)
            _register_dashboard_panel(hass, title, "mdi:lightning-bolt-circle")
        except Exception as err:
            _LOGGER.error("[%s] Could not create dashboard container: %s", DOMAIN, err)
            return False

        # Re-fetch dashboards after creation (the listener may have added it)
        dashboards = _get_lovelace_dashboards(hass)
        if dashboards is None or DASHBOARD_URL_PATH not in dashboards:
            # Fallback: create LovelaceStorage directly and inject it
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
        # Re-register panel in case HA restarted and lost the sidebar entry
        _register_dashboard_panel(hass, title, "mdi:lightning-bolt-circle", update=True)

    # Write the dashboard content
    dashboards = _get_lovelace_dashboards(hass)
    dashboard_store = dashboards.get(DASHBOARD_URL_PATH) if dashboards else None
    if dashboard_store is None:
        _LOGGER.error("[%s] Dashboard store not found — cannot save content", DOMAIN)
        return False

    config = _build_dashboard_config(entry)
    await dashboard_store.async_save(config)
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
