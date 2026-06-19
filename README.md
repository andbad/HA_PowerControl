# HA Power Control

<p align="center">
  <img src="logo.png" alt="HA Power Control Logo" width="200"/>
</p>

<a href="https://www.buymeacoffee.com/andthebad" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>
![GitHub Release](https://img.shields.io/github/v/release/andbad/HA_PowerControl)
![GitHub commit activity](https://img.shields.io/github/commit-activity/y/andbad/HA_PowerControl)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Home Assistant integration that prevents main power meter trips by automatically managing electrical loads based on power consumption.

---

## How It Works

When the total power consumption exceeds a configured threshold, the integration turns off loads in **reverse priority order** (from least important to most important), one at a time, until power usage drops back within the limit.

Once consumption stays below the threshold for a sufficient amount of time, the loads are **automatically reactivated** in direct priority order, ensuring that each reactivation won't trigger another overload.

### Two Shedding Modes

| Mode | Threshold | Delay |
|---|---|---|
| **Immediate** | Immediate threshold (e.g., 3300 W) | Configurable in seconds |
| **Delayed** | Delayed threshold (e.g., 3000 W) | Configurable in minutes |

---

## Requirements

- Home Assistant 2023.6 or higher
- Devices with a controllable switch (e.g., Shelly 1PM, Shelly Plug S)
- Power sensors for the managed loads (W)
- Optional: Main grid/system power sensor (e.g., Shelly EM)

---

## Installation via HACS

1. In HACS, go to **Integrations → ⋮ → Custom repositories**
2. Add `https://github.com/andbad/HA_PowerControl` with the category **Integration**
3. Search for "Power Control" and click install
4. Restart Home Assistant

### Manual Installation

Copy the `custom_components/power_control/` folder into the `custom_components/` directory of your HA installation, then restart.

---

## Configuration

1. Go to **Settings → Devices & services → Add Integration**
2. Search for **Power Control**
3. Follow the three-step setup wizard:

### Step 1 — Global Settings

| Field | Description | Default |
|---|---|---|
| Instance name | Display name in HA | Power Control |
| Main power sensor | entity_id of the main total sensor (optional) | — |
| Immediate threshold | W above which loads are shed immediately | 3000 W |
| Delayed threshold | W above which loads are shed after N minutes | 2700 W |
| Immediate shedding delay | Seconds spent above threshold | 30 s |
| Delayed shedding delay | Minutes spent above threshold | 10 min |
| Wait time between sheddings | Seconds between turning off one load and the next | 10 s |
| Wait time between reactivations | Minutes between turning on one load and the next | 5 min |
| Wait time before reactivating | Minutes below threshold before starting reactivations | 5 min |
| Notification service | e.g., `notify.mobile_app_phone` (optional) | — |

> **Note:** The immediate threshold must be greater than the delayed threshold.

### Step 2 — Number of Loads

Choose how many loads to manage (1–20). Loads are sorted by priority: **Load 1 is the most important** and will be the last one to be turned off.

### Step 3 — Load Configuration (Repeated for each load)

| Field | Description |
|---|---|
| Name | Label displayed in notifications and HA |
| Power sensor | entity_id of the sensor (e.g., `sensor.washing_machine_power`) |
| Switch | entity_id of the switch (e.g., `switch.shelly_washing_machine`) |
| Auto reactivation | If disabled, the load will never be turned back on automatically |

---

## Created Entities

All entities are grouped under a single **Power Control** device.

### Sensors

| Entity | Description |
|---|---|
| `sensor.power_control_potenza_attuale` | Real-time measured power (W) |
| `sensor.power_control_potenza_sospesa` | Total power of suspended loads (W) |
| `sensor.power_control_soglia_distacco_immediato` | Configured immediate threshold (W) |
| `sensor.power_control_soglia_distacco_ritardato` | Configured delayed threshold (W) |
| `sensor.power_control_<name>_potenza_sospesa` | Suspended power for each individual load (W) |

Per-load sensors also expose the following attributes:

- `current_power_w` — instantaneous measured power
- `switch_state` — switch state (`on` / `off` / `unavailable`)
- `auto_restart` — automatic reactivation enabled
- `keep_off` — load manually blocked
- `is_suspended` — load currently suspended

### Switches

| Entity | Description |
|---|---|
| `switch.power_control_attivo` | Enables/disables the entire system. State persists across HA restarts. |

---

## Services

| Service | Parameters | Description |
|---|---|---|
| `power_control.enable` | — | Enables load control |
| `power_control.disable` | — | Disables control and resets all suspended powers |
| `power_control.reset_load` | `load_index` (0–19) | Removes a load from the suspended list |
| `power_control.force_stop_load` | `load_index` (0–19) | Immediately sheds a specific load |
| `power_control.force_start_load` | `load_index` (0–19) | Immediate reactivation, ignoring timers |

The `load_index` corresponds to the position of the load in the wizard (0 = first position = highest priority). You can also find it as a `load_index` attribute on the load sensor.

---

## `set_thresholds` service

The `power_control.set_thresholds` service lets you override the intervention thresholds at runtime without changing the persistent configuration. This is useful when you want to adapt thresholds dynamically based on the active power source (grid, solar, solar EPS mode, time of day, etc.).

**Fields**

| Field | Required | Description |
|---|---|---|
| `immediate_threshold` | no | Immediate shedding threshold in Watts |
| `delayed_threshold` | no | Delayed shedding threshold in Watts |

Both fields are optional. Omit one to leave that threshold unchanged. Call the service with no fields to reset both thresholds to the values set in the configuration.

> **Note:** overrides are stored in memory only. They are lost when Home Assistant restarts.

**Example — switch to solar profile:**
```yaml
service: power_control.set_thresholds
data:
  immediate_threshold: 5000
  delayed_threshold: 4500
```

**Example — reset to configured values:**
```yaml
service: power_control.set_thresholds
data: {}
```

**Example — full automation based on power source:**
```yaml
automation:
  - alias: "PowerControl — adapt thresholds to power source"
    trigger:
      - platform: state
        entity_id: sensor.power_source
    action:
      - choose:
          - conditions:
              - condition: state
                entity_id: sensor.power_source
                state: "solar"
            sequence:
              - service: power_control.set_thresholds
                data:
                  immediate_threshold: 5000
                  delayed_threshold: 4500
          - conditions:
              - condition: state
                entity_id: sensor.power_source
                state: "solar_eps"
            sequence:
              - service: power_control.set_thresholds
                data:
                  immediate_threshold: 2000
                  delayed_threshold: 1800
        default:
          - service: power_control.set_thresholds
            data: {}
```

---

## Dashboard

The Lovelace dashboard is automatically created at the end of the configuration wizard if the **"Create dashboard"** option is enabled. No manual file importing is required.

The dashboard includes:
- Main load gauge with color coding (green/yellow/red)
- Real-time status of current and suspended power
- 1-hour history graph
- Configuration card showing thresholds and timing parameters
- Timer card with progress bars for internal timers
- Individual cards for each configured load with power sensor and suspension state

The dashboard is accessible in the sidebar as **Power Control** and is automatically removed when the integration is deleted.

---

## Main Power Sensor vs. Virtual Sensing

**With Main Sensor** (recommended): Configure the entity_id of a sensor that measures the entire power consumption of the system (e.g., Shelly EM). The integration will use this value directly.

**Without Main Sensor**: The system sums up the power consumption of the individual configured loads. This works, but it cannot account for unmonitored appliances — use conservative thresholds in this case.

---

## Behavior on HA Restart

- The master switch state (`active` / `inactive`) is restored.
- Suspended powers are restored by reading the last state of the sensor entities.
- If a load was suspended before the restart, it remains in the queue waiting for reactivation.

---

## Credits

Based on the original YAML package [HA_PowerControl](https://github.com/andbad/HA_PowerControl) by **andbad**, developed with the support of the [InDomus](https://indomus.it/) community.
