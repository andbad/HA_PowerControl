"""Migration helpers for upgrading from the legacy pc.yaml package.

The old package stored configuration in HA input_* entities.
This module reads those entities (if present) and converts them
to the new config_entry data format.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CONF_GLOBAL_POWER_SENSOR,
    CONF_INSTANCE_NAME,
    CONF_THRESHOLD_IMMEDIATE,
    CONF_THRESHOLD_DELAYED,
    CONF_DELAY_IMMEDIATE_SEC,
    CONF_DELAY_DELAYED_MIN,
    CONF_WAIT_BETWEEN_STOPS_SEC,
    CONF_WAIT_BETWEEN_STARTS_MIN,
    CONF_WAIT_BEFORE_START_MIN,
    CONF_NOTIFY_SERVICE,
    CONF_NUM_LOADS,
    CONF_LOADS,
    LOAD_NAME,
    LOAD_POWER_SENSOR,
    LOAD_SWITCH,
    LOAD_AUTO_RESTART,
)

_LOGGER = logging.getLogger(__name__)

_OLD_GLOBAL_SENSOR  = "input_text.potenza_carichi"
_OLD_THRESHOLD_IMM  = "input_number.potenza_massima_immediato"
_OLD_THRESHOLD_DEL  = "input_number.potenza_massima_ritardato"
_OLD_DELAY_IMM_SEC  = "input_number.tempo_stop_immediato"
_OLD_DELAY_DEL_MIN  = "input_number.tempo_stop_ritardato"
_OLD_WAIT_STOP_SEC  = "input_number.attesa_stop"
_OLD_WAIT_START_MIN = "input_number.attesa_start"
_OLD_WAIT_BEFORE    = "input_number.tempo_start"

MAX_LEGACY_LOADS = 20


def _state_float(hass: HomeAssistant, entity_id: str, default: float) -> float:
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable", ""):
        return default
    try:
        return float(state.state)
    except ValueError:
        return default


def _state_str(hass: HomeAssistant, entity_id: str, default: str = "") -> str:
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable"):
        return default
    return state.state


def detect_legacy_package(hass: HomeAssistant) -> bool:
    """Return True if old pc.yaml package entities are present."""
    return (
        hass.states.get("input_select.carico_1_potenza") is not None
        or hass.states.get("input_text.carico_1_potenza") is not None
    )


def read_legacy_config(hass: HomeAssistant) -> dict[str, Any]:
    """Read old package entities and return a new-format config dict."""
    _LOGGER.info("Reading legacy PowerControl package configuration")

    global_sensor = _state_str(hass, _OLD_GLOBAL_SENSOR)
    if global_sensor in ("Seleziona", "sensor.potenza_carichi_virtuale", ""):
        global_sensor = ""

    config: dict[str, Any] = {
        CONF_INSTANCE_NAME:           "Power Control",
        CONF_GLOBAL_POWER_SENSOR:     global_sensor,
        CONF_THRESHOLD_IMMEDIATE:     int(_state_float(hass, _OLD_THRESHOLD_IMM, 3300)),
        CONF_THRESHOLD_DELAYED:       int(_state_float(hass, _OLD_THRESHOLD_DEL, 3000)),
        CONF_DELAY_IMMEDIATE_SEC:     int(_state_float(hass, _OLD_DELAY_IMM_SEC, 30)),
        CONF_DELAY_DELAYED_MIN:       int(_state_float(hass, _OLD_DELAY_DEL_MIN, 10)),
        CONF_WAIT_BETWEEN_STOPS_SEC:  int(_state_float(hass, _OLD_WAIT_STOP_SEC, 10)),
        CONF_WAIT_BETWEEN_STARTS_MIN: int(_state_float(hass, _OLD_WAIT_START_MIN, 5)),
        CONF_WAIT_BEFORE_START_MIN:   int(_state_float(hass, _OLD_WAIT_BEFORE, 5)),
        CONF_NOTIFY_SERVICE:          "",
    }

    loads: list[dict[str, Any]] = []
    for i in range(1, MAX_LEGACY_LOADS + 1):
        power_sensor = _state_str(hass, f"input_text.carico_{i}_potenza")
        switch       = _state_str(hass, f"input_text.carico_{i}_switch")

        if power_sensor in ("", "Seleziona") and switch in ("", "Seleziona"):
            continue

        mantieni     = _state_str(hass, f"input_boolean.mantini_spento_{i}")
        auto_restart = mantieni != "on"

        name = (
            power_sensor.replace("sensor.", "")
                        .replace("potenza_", "")
                        .replace("_", " ")
                        .title()
            if power_sensor not in ("", "Seleziona")
            else f"Carico {len(loads) + 1}"
        )

        loads.append({
            LOAD_NAME:         name,
            LOAD_POWER_SENSOR: power_sensor if power_sensor != "Seleziona" else "",
            LOAD_SWITCH:       switch       if switch       != "Seleziona" else "",
            LOAD_AUTO_RESTART: auto_restart,
        })
        _LOGGER.debug("Legacy load %d → %s | %s | %s", i, name, power_sensor, switch)

    config[CONF_NUM_LOADS] = max(len(loads), 1)
    config[CONF_LOADS] = loads or [{
        LOAD_NAME: "Carico 1", LOAD_POWER_SENSOR: "",
        LOAD_SWITCH: "", LOAD_AUTO_RESTART: True,
    }]

    _LOGGER.info(
        "Legacy config imported: %d loads, imm=%dW, del=%dW",
        len(loads), config[CONF_THRESHOLD_IMMEDIATE], config[CONF_THRESHOLD_DELAYED],
    )
    return config


# Aliases used by config_flow.py
detect_old_package = detect_legacy_package
read_old_config    = read_legacy_config
