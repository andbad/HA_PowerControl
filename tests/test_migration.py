"""Tests for Power Control legacy package migration."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.power_control.migration import (
    detect_legacy_package,
    read_legacy_config,
)
from custom_components.power_control.const import (
    CONF_THRESHOLD_IMMEDIATE,
    CONF_THRESHOLD_DELAYED,
    CONF_DELAY_IMMEDIATE_SEC,
    CONF_DELAY_DELAYED_MIN,
    CONF_WAIT_BETWEEN_STOPS_SEC,
    CONF_WAIT_BETWEEN_STARTS_MIN,
    CONF_WAIT_BEFORE_START_MIN,
    CONF_GLOBAL_POWER_SENSOR,
    CONF_LOADS,
    CONF_NUM_LOADS,
    LOAD_NAME,
    LOAD_POWER_SENSOR,
    LOAD_SWITCH,
    LOAD_AUTO_RESTART,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_hass(states: dict[str, str]) -> MagicMock:
    """Build a mock hass with a controllable states dict."""
    hass = MagicMock()

    def get_state(entity_id: str):
        if entity_id not in states:
            return None
        s = MagicMock()
        s.state = states[entity_id]
        return s

    hass.states.get = MagicMock(side_effect=get_state)
    return hass


# Minimal states that look like a running old package with 2 loads
MINIMAL_LEGACY_STATES = {
    "input_select.carico_1_potenza": "sensor.potenza_lavatrice",
    "input_text.carico_1_potenza":   "sensor.potenza_lavatrice",
    "input_text.carico_1_switch":    "switch.lavatrice",
    "input_boolean.mantini_spento_1": "off",
    "input_text.carico_2_potenza":   "sensor.potenza_lavastoviglie",
    "input_text.carico_2_switch":    "switch.lavastoviglie",
    "input_boolean.mantini_spento_2": "off",
    "input_number.potenza_massima_immediato": "3300",
    "input_number.potenza_massima_ritardato": "3000",
    "input_number.tempo_stop_immediato":      "30",
    "input_number.tempo_stop_ritardato":      "10",
    "input_number.attesa_stop":               "10",
    "input_number.attesa_start":              "5",
    "input_number.tempo_start":               "5",
    "input_text.potenza_carichi":             "sensor.shelly_em",
}


# ── Detection tests ───────────────────────────────────────────────────────────

class TestDetectLegacyPackage:
    def test_detects_via_input_select(self):
        hass = make_hass({"input_select.carico_1_potenza": "sensor.p"})
        assert detect_legacy_package(hass) is True

    def test_detects_via_input_text(self):
        hass = make_hass({"input_text.carico_1_potenza": "sensor.p"})
        assert detect_legacy_package(hass) is True

    def test_not_detected_on_fresh_install(self):
        hass = make_hass({})
        assert detect_legacy_package(hass) is False

    def test_not_detected_with_unrelated_entities(self):
        hass = make_hass({"sensor.some_power": "1500"})
        assert detect_legacy_package(hass) is False


# ── Config reading tests ──────────────────────────────────────────────────────

class TestReadLegacyConfig:
    def test_reads_thresholds(self):
        hass = make_hass(MINIMAL_LEGACY_STATES)
        config = read_legacy_config(hass)
        assert config[CONF_THRESHOLD_IMMEDIATE] == 3300
        assert config[CONF_THRESHOLD_DELAYED] == 3000

    def test_reads_timings(self):
        hass = make_hass(MINIMAL_LEGACY_STATES)
        config = read_legacy_config(hass)
        assert config[CONF_DELAY_IMMEDIATE_SEC] == 30
        assert config[CONF_DELAY_DELAYED_MIN] == 10
        assert config[CONF_WAIT_BETWEEN_STOPS_SEC] == 10
        assert config[CONF_WAIT_BETWEEN_STARTS_MIN] == 5
        assert config[CONF_WAIT_BEFORE_START_MIN] == 5

    def test_reads_global_sensor(self):
        hass = make_hass(MINIMAL_LEGACY_STATES)
        config = read_legacy_config(hass)
        assert config[CONF_GLOBAL_POWER_SENSOR] == "sensor.shelly_em"

    def test_ignores_virtual_global_sensor(self):
        states = {**MINIMAL_LEGACY_STATES,
                  "input_text.potenza_carichi": "sensor.potenza_carichi_virtuale"}
        hass = make_hass(states)
        config = read_legacy_config(hass)
        assert config[CONF_GLOBAL_POWER_SENSOR] == ""

    def test_ignores_seleziona_global_sensor(self):
        states = {**MINIMAL_LEGACY_STATES,
                  "input_text.potenza_carichi": "Seleziona"}
        hass = make_hass(states)
        config = read_legacy_config(hass)
        assert config[CONF_GLOBAL_POWER_SENSOR] == ""

    def test_reads_two_loads(self):
        hass = make_hass(MINIMAL_LEGACY_STATES)
        config = read_legacy_config(hass)
        assert config[CONF_NUM_LOADS] == 2
        assert len(config[CONF_LOADS]) == 2

    def test_load_entities_mapped_correctly(self):
        hass = make_hass(MINIMAL_LEGACY_STATES)
        loads = read_legacy_config(hass)[CONF_LOADS]
        assert loads[0][LOAD_POWER_SENSOR] == "sensor.potenza_lavatrice"
        assert loads[0][LOAD_SWITCH] == "switch.lavatrice"
        assert loads[1][LOAD_POWER_SENSOR] == "sensor.potenza_lavastoviglie"
        assert loads[1][LOAD_SWITCH] == "switch.lavastoviglie"

    def test_auto_restart_true_when_mantieni_off(self):
        states = {**MINIMAL_LEGACY_STATES,
                  "input_boolean.mantini_spento_1": "off"}
        hass = make_hass(states)
        loads = read_legacy_config(hass)[CONF_LOADS]
        assert loads[0][LOAD_AUTO_RESTART] is True

    def test_auto_restart_false_when_mantieni_on(self):
        states = {**MINIMAL_LEGACY_STATES,
                  "input_boolean.mantini_spento_1": "on"}
        hass = make_hass(states)
        loads = read_legacy_config(hass)[CONF_LOADS]
        assert loads[0][LOAD_AUTO_RESTART] is False

    def test_skips_unconfigured_slots(self):
        """Slots with empty/Seleziona entities are not added to load list."""
        states = {
            "input_text.carico_1_potenza": "sensor.p",
            "input_text.carico_1_switch":  "switch.s",
            "input_boolean.mantini_spento_1": "off",
            # slot 2 is missing entirely — should be skipped
        }
        hass = make_hass(states)
        config = read_legacy_config(hass)
        assert len(config[CONF_LOADS]) == 1

    def test_seleziona_slots_skipped(self):
        states = {
            "input_text.carico_1_potenza": "Seleziona",
            "input_text.carico_1_switch":  "Seleziona",
        }
        hass = make_hass(states)
        config = read_legacy_config(hass)
        # Falls back to default single load placeholder
        assert len(config[CONF_LOADS]) == 1
        assert config[CONF_LOADS][0][LOAD_POWER_SENSOR] == ""

    def test_fallback_defaults_on_missing_entities(self):
        """When no old entities exist, returns safe defaults."""
        hass = make_hass({})
        config = read_legacy_config(hass)
        assert config[CONF_THRESHOLD_IMMEDIATE] == 3300
        assert config[CONF_THRESHOLD_DELAYED] == 3000
        assert isinstance(config[CONF_LOADS], list)
        assert len(config[CONF_LOADS]) >= 1

    def test_thresholds_are_integers(self):
        """Thresholds must be int, not float (NumberSelector coercion check)."""
        hass = make_hass(MINIMAL_LEGACY_STATES)
        config = read_legacy_config(hass)
        assert isinstance(config[CONF_THRESHOLD_IMMEDIATE], int)
        assert isinstance(config[CONF_THRESHOLD_DELAYED], int)

    def test_timings_are_integers(self):
        hass = make_hass(MINIMAL_LEGACY_STATES)
        config = read_legacy_config(hass)
        for key in [CONF_DELAY_IMMEDIATE_SEC, CONF_DELAY_DELAYED_MIN,
                    CONF_WAIT_BETWEEN_STOPS_SEC, CONF_WAIT_BETWEEN_STARTS_MIN,
                    CONF_WAIT_BEFORE_START_MIN]:
            assert isinstance(config[key], int), f"{key} should be int"

    def test_non_numeric_entity_falls_back_to_default(self):
        states = {**MINIMAL_LEGACY_STATES,
                  "input_number.potenza_massima_immediato": "unavailable"}
        hass = make_hass(states)
        config = read_legacy_config(hass)
        assert config[CONF_THRESHOLD_IMMEDIATE] == 3300  # default
