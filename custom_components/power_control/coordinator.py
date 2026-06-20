"""Coordinator for Power Control integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .notify import async_notify
from .const import (
    DOMAIN,
    UPDATE_INTERVAL_SEC,
    MIN_ACTIVE_POWER_W,
    CONF_GLOBAL_POWER_SENSOR,
    CONF_THRESHOLD_IMMEDIATE,
    CONF_THRESHOLD_DELAYED,
    CONF_DELAY_IMMEDIATE_SEC,
    CONF_DELAY_DELAYED_MIN,
    CONF_NOTIFY_ENTITY,
    CONF_NOTIFY_SERVICE,  # alias
    CONF_WAIT_BETWEEN_STOPS_SEC,
    CONF_WAIT_BETWEEN_STARTS_MIN,
    CONF_WAIT_BEFORE_START_MIN,
    CONF_LOADS,
    LOAD_NAME,
    LOAD_POWER_SENSOR,
    LOAD_SWITCH,
    LOAD_AUTO_RESTART,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class LoadState:
    """Runtime state for a single managed load."""

    # Static config (from config_entry)
    name: str
    power_sensor: str          # entity_id or ""
    switch: str                # entity_id or ""
    auto_restart: bool

    # Runtime state
    suspended_power: float = 0.0   # W at time of shutdown; 0 = load is active/unmanaged
    keep_off: bool = False          # user-requested permanent off

    # Derived (refreshed every coordinator update)
    current_power: float = 0.0     # live W reading
    switch_state: str = "unknown"  # "on" / "off" / "unavailable" / "unknown"

    @property
    def is_configured(self) -> bool:
        """True when both sensor and switch are set."""
        return bool(self.power_sensor) and bool(self.switch)

    @property
    def is_suspended(self) -> bool:
        """True when the coordinator has shut this load down."""
        return self.suspended_power > 0


@dataclass
class PowerControlData:
    """Data snapshot exposed to HA entities after each coordinator update."""

    current_power: float = 0.0
    total_suspended_power: float = 0.0
    loads: list[LoadState] = field(default_factory=list)
    enabled: bool = True


class PowerControlCoordinator(DataUpdateCoordinator[PowerControlData]):
    """Coordinator that reads power state and drives the stop/start logic."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{config_entry.entry_id}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SEC),
        )
        self.config_entry = config_entry
        self.enabled: bool = True

        # Build initial load list from config
        self._loads: list[LoadState] = self._build_loads()

        # Listener cancel callback for the global power sensor
        self._global_sensor_unsub: object | None = None

        # Timers for threshold hysteresis (set when threshold first exceeded)
        self._over_immediate_since: datetime | None = None
        self._over_delayed_since: datetime | None = None
        # Timer for restart hysteresis (set when power returns below threshold)
        self._under_threshold_since: datetime | None = None

        # Cooldown timestamps: block next stop/start until enough time has elapsed
        self._last_stop_at: datetime | None = None
        self._last_start_at: datetime | None = None

        # Runtime threshold overrides (set via service, None = use config)
        self._threshold_override: tuple[float, float] | None = None

    # ──────────────────────────────────────────────────────────────────────────
    # Setup helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _build_loads(self) -> list[LoadState]:
        """Construct LoadState objects from config_entry data."""
        raw: list[dict[str, Any]] = self.config_entry.data.get(CONF_LOADS, [])
        return [
            LoadState(
                name=l.get(LOAD_NAME, f"Carico {i + 1}"),
                power_sensor=l.get(LOAD_POWER_SENSOR, ""),
                switch=l.get(LOAD_SWITCH, ""),
                auto_restart=l.get(LOAD_AUTO_RESTART, True),
            )
            for i, l in enumerate(raw)
        ]



    # ──────────────────────────────────────────────────────────────────────────
    # Global sensor listener
    # ──────────────────────────────────────────────────────────────────────────

    @callback
    def setup_global_sensor_listener(self) -> None:
        """Register a state-change listener on the global power sensor.

        Called once during setup and again whenever the user changes the
        global sensor in the options flow.  Always cancels the previous
        listener before registering a new one.
        """
        # Cancel previous listener if any
        if self._global_sensor_unsub is not None:
            self._global_sensor_unsub()
            self._global_sensor_unsub = None

        global_sensor: str = self.config_entry.data.get(CONF_GLOBAL_POWER_SENSOR, "")
        if not global_sensor:
            _LOGGER.debug(
                "[%s] No global sensor configured — listener not registered", DOMAIN
            )
            return

        @callback
        def _on_sensor_change(entity_id: str, old_state, new_state) -> None:  # type: ignore[type-arg]
            """Trigger a coordinator refresh when the global sensor changes."""
            if new_state is None or new_state.state in ("unavailable", "unknown"):
                return
            _LOGGER.debug(
                "[%s] Global sensor %s changed to %s W — triggering refresh",
                DOMAIN, entity_id, new_state.state,
            )
            self.hass.async_create_task(self.async_request_refresh())

        self._global_sensor_unsub = async_track_state_change(
            self.hass,
            global_sensor,
            _on_sensor_change,
        )

        _LOGGER.debug(
            "[%s] Registered state-change listener on %s", DOMAIN, global_sensor
        )

    @callback
    def async_shutdown(self) -> None:
        """Cancel the global sensor listener on integration unload."""
        if self._global_sensor_unsub is not None:
            self._global_sensor_unsub()
            self._global_sensor_unsub = None
            _LOGGER.debug("[%s] Global sensor listener cancelled", DOMAIN)

    # ──────────────────────────────────────────────────────────────────────────
    # Core update
    # ──────────────────────────────────────────────────────────────────────────

    async def _async_update_data(self) -> PowerControlData:
        """Called every UPDATE_INTERVAL_SEC by the coordinator base class."""
        try:
            await self._refresh_load_states()
            current_power = self._read_global_power()
            total_suspended = sum(l.suspended_power for l in self._loads)

            _LOGGER.debug(
                "[%s] update — current: %.0f W | suspended: %.0f W | enabled: %s",
                DOMAIN,
                current_power,
                total_suspended,
                self.enabled,
            )

            # Watchdog: if user turned a switch back on manually, clear suspended_power
            self._watchdog_manual_restart()

            # Stop logic: shed loads if power exceeds thresholds
            if self.enabled:
                await self.async_check_and_stop(current_power)

            # Start logic: restore loads when power is back under threshold
            if self.enabled:
                await self.async_check_and_start(current_power)

            return PowerControlData(
                current_power=current_power,
                total_suspended_power=total_suspended,
                loads=list(self._loads),
                enabled=self.enabled,
            )
        except Exception as err:
            raise UpdateFailed(f"Power Control update error: {err}") from err

    # ──────────────────────────────────────────────────────────────────────────
    # State reading
    # ──────────────────────────────────────────────────────────────────────────

    def _read_global_power(self) -> float:
        """Return total current power from global sensor or sum of loads."""
        global_sensor: str = self.config_entry.data.get(CONF_GLOBAL_POWER_SENSOR, "")

        if global_sensor:
            state: State | None = self.hass.states.get(global_sensor)
            if state and state.state not in ("unavailable", "unknown", ""):
                try:
                    return float(state.state)
                except ValueError:
                    _LOGGER.warning(
                        "[%s] Global power sensor '%s' returned non-numeric value: %s",
                        DOMAIN,
                        global_sensor,
                        state.state,
                    )

        # Fallback: sum active loads
        total = sum(l.current_power for l in self._loads)
        _LOGGER.debug("[%s] Using virtual power sum: %.0f W", DOMAIN, total)
        return total

    async def _refresh_load_states(self) -> None:
        """Update current_power and switch_state for every load."""
        for i, load in enumerate(self._loads):
            if not load.is_configured:
                continue

            # Power sensor
            ps: State | None = self.hass.states.get(load.power_sensor)
            if ps is None or ps.state in ("unavailable", "unknown"):
                load.current_power = 0.0
            else:
                try:
                    load.current_power = float(ps.state)
                except ValueError:
                    load.current_power = 0.0

            # Switch state
            sw: State | None = self.hass.states.get(load.switch)
            load.switch_state = sw.state if sw else "unknown"

            _LOGGER.debug(
                "[%s] Load %d '%s' — power: %.0f W | switch: %s | suspended: %.0f W",
                DOMAIN,
                i,
                load.name,
                load.current_power,
                load.switch_state,
                load.suspended_power,
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Watchdog
    # ──────────────────────────────────────────────────────────────────────────

    def _watchdog_manual_restart(self) -> None:
        """Clear suspended_power if the user manually turned a switch back on."""
        for i, load in enumerate(self._loads):
            if load.is_suspended and load.switch_state == "on":
                _LOGGER.info(
                    "[%s] Load %d '%s' was manually restarted — clearing suspended power (%.0f W)",
                    DOMAIN,
                    i,
                    load.name,
                    load.suspended_power,
                )
                load.suspended_power = 0.0

    # ──────────────────────────────────────────────────────────────────────────
    # Public API (used by stop/start logic in step 5 & 6, and by services)
    # ──────────────────────────────────────────────────────────────────────────

    @property
    def loads(self) -> list[LoadState]:
        """Return the live load list."""
        return self._loads

    @property
    def thresholds(self) -> tuple[float, float]:
        """Return (immediate_W, delayed_W).

        If a runtime override is set via set_thresholds service, use that.
        Otherwise fall back to options flow, then config entry data.
        """
        if self._threshold_override is not None:
            return self._threshold_override
        opts = self.config_entry.options
        source = opts if (opts is not None and len(opts) > 0) else self.config_entry.data
        return (
            float(source.get(CONF_THRESHOLD_IMMEDIATE, 3000)),
            float(source.get(CONF_THRESHOLD_DELAYED, 2700)),
        )

    def set_thresholds(self, immediate_w: float | None, delayed_w: float | None) -> None:
        """Override thresholds at runtime. Pass None to both to reset to config values."""
        if immediate_w is None and delayed_w is None:
            self._threshold_override = None
            _LOGGER.info("[%s] Threshold override cleared — using config values", DOMAIN)
        else:
            imm, dly = self.thresholds  # current effective values as fallback
            self._threshold_override = (
                float(immediate_w) if immediate_w is not None else imm,
                float(delayed_w) if delayed_w is not None else dly,
            )
            _LOGGER.info(
                "[%s] Threshold override set: immediate=%.0f W, delayed=%.0f W",
                DOMAIN, self._threshold_override[0], self._threshold_override[1],
            )

    def _get_conf(self, key: str, default):
        """Read config key from options first, then data (options flow override support)."""
        opts = self.config_entry.options
        source = opts if (opts is not None and len(opts) > 0) else self.config_entry.data
        return source.get(key, default)

    @property
    def timer_state(self) -> dict:
        """Return a snapshot of all internal timer states for dashboard display.

        All durations are in seconds; None means the timer is not running.
        Negative elapsed values are clamped to 0.
        """
        now = datetime.now()
        delay_imm_sec: int = int(self._get_conf(CONF_DELAY_IMMEDIATE_SEC, 10))
        delay_del_min: int = int(self._get_conf(CONF_DELAY_DELAYED_MIN, 3))
        wait_stops_sec: int = int(self._get_conf(CONF_WAIT_BETWEEN_STOPS_SEC, 10))
        wait_starts_min: int = int(self._get_conf(CONF_WAIT_BETWEEN_STARTS_MIN, 5))
        wait_before_min: int = int(self._get_conf(CONF_WAIT_BEFORE_START_MIN, 5))

        def _remaining(since: datetime | None, total_sec: int) -> int | None:
            if since is None:
                return None
            elapsed = max(0, (now - since).total_seconds())
            remaining = total_sec - elapsed
            return max(0, int(remaining))

        return {
            "over_immediate_remaining_sec": _remaining(self._over_immediate_since, delay_imm_sec),
            "over_delayed_remaining_sec":   _remaining(self._over_delayed_since, delay_del_min * 60),
            "stop_cooldown_remaining_sec":  _remaining(self._last_stop_at, wait_stops_sec),
            "under_threshold_remaining_sec": _remaining(self._under_threshold_since, wait_before_min * 60),
            "start_cooldown_remaining_sec": _remaining(self._last_start_at, wait_starts_min * 60),
        }

    def reset_all_suspended(self) -> None:
        """Reset suspended power for all loads (called on disable)."""
        for load in self._loads:
            load.suspended_power = 0.0
        self._last_stop_at = None
        self._last_start_at = None
        _LOGGER.debug("[%s] All suspended powers reset", DOMAIN)

    def reset_load_suspended(self, index: int) -> None:
        """Reset suspended power for a single load by index."""
        if 0 <= index < len(self._loads):
            self._loads[index].suspended_power = 0.0
            _LOGGER.debug(
                "[%s] Suspended power reset for load %d '%s'",
                DOMAIN,
                index,
                self._loads[index].name,
            )

    def publish_current_state(self) -> None:
        """Push current in-memory state to listeners without re-running
        _async_update_data (which would re-read switch states from HA and
        could race with a state change that hasn't propagated yet)."""
        total_suspended = sum(l.suspended_power for l in self._loads)
        self.async_set_updated_data(
            PowerControlData(
                current_power=self._read_global_power(),
                total_suspended_power=total_suspended,
                loads=list(self._loads),
                enabled=self.enabled,
            )
        )

    def rebuild_loads(self) -> None:
        """Rebuild load list after an options flow update.

        Preserves suspended_power for loads that still exist, matched by
        switch entity_id so that reordering does not lose suspended state.
        """
        old_by_switch = {l.switch: l.suspended_power for l in self._loads if l.switch}
        self._loads = self._build_loads()
        for load in self._loads:
            if load.switch and load.switch in old_by_switch:
                load.suspended_power = old_by_switch[load.switch]
        _LOGGER.debug("[%s] Load list rebuilt (%d loads)", DOMAIN, len(self._loads))

    # ──────────────────────────────────────────────────────────────────────────
    # Stop logic  (Step 5)
    # ──────────────────────────────────────────────────────────────────────────

    async def async_check_and_stop(self, current_power: float) -> None:
        """Shed loads when power exceeds either threshold.

        Two trigger modes:
        - immediate: threshold_immediate exceeded for delay_immediate_sec seconds
        - delayed:   threshold_delayed  exceeded for delay_delayed_min  minutes

        On each call we shed at most ONE load, then return. The coordinator's
        10-second poll loop will call us again if power is still too high.
        """
        if not self.enabled:
            return

        threshold_immediate, threshold_delayed = self.thresholds
        delay_imm_sec: int = int(
            self.config_entry.data.get(CONF_DELAY_IMMEDIATE_SEC, 30)
        )
        delay_del_min: int = int(
            self.config_entry.data.get(CONF_DELAY_DELAYED_MIN, 10)
        )
        now = datetime.now()

        # ── Track how long we have been over each threshold ──────────────────
        if current_power >= threshold_immediate:
            if self._over_immediate_since is None:
                self._over_immediate_since = now
                _LOGGER.debug(
                    "[%s] Immediate threshold exceeded (%.0f >= %.0f W) — timer started",
                    DOMAIN, current_power, threshold_immediate,
                )
        else:
            if self._over_immediate_since is not None:
                _LOGGER.debug("[%s] Immediate threshold cleared — timer reset", DOMAIN)
            self._over_immediate_since = None

        if current_power >= threshold_delayed:
            if self._over_delayed_since is None:
                self._over_delayed_since = now
                _LOGGER.debug(
                    "[%s] Delayed threshold exceeded (%.0f > %.0f W) — timer started",
                    DOMAIN, current_power, threshold_delayed,
                )
        else:
            if self._over_delayed_since is not None:
                _LOGGER.debug("[%s] Delayed threshold cleared — timer reset", DOMAIN)
            self._over_delayed_since = None

        # ── Decide whether to act ────────────────────────────────────────────
        trigger_immediate = (
            self._over_immediate_since is not None
            and (now - self._over_immediate_since).total_seconds() >= delay_imm_sec
        )
        trigger_delayed = (
            self._over_delayed_since is not None
            and (now - self._over_delayed_since).total_seconds() >= delay_del_min * 60
        )

        if not trigger_immediate and not trigger_delayed:
            return

        trigger_label = "immediato" if trigger_immediate else "ritardato"
        active_threshold = threshold_immediate if trigger_immediate else threshold_delayed

        _LOGGER.info(
            "[%s] STOP trigger (%s) — current: %.0f W > %.0f W",
            DOMAIN, trigger_label, current_power, active_threshold,
        )

        # ── Shed one load (lowest priority first = highest index first) ───────
        await self._shed_one_load(current_power, active_threshold)

    async def _shed_one_load(
        self, current_power: float, active_threshold: float
    ) -> None:
        """Turn off the lowest-priority active load that is actually drawing power."""
        wait_sec: int = int(
            self.config_entry.data.get(CONF_WAIT_BETWEEN_STOPS_SEC, 10)
        )

        # Cooldown: block shed if the previous one happened too recently.
        # This replaces asyncio.sleep — the coordinator keeps running normally
        # and simply skips shedding until the cooldown has elapsed.
        if self._last_stop_at is not None:
            elapsed = (datetime.now() - self._last_stop_at).total_seconds()
            if elapsed < wait_sec:
                _LOGGER.debug(
                    "[%s] Stop cooldown active — %.0f / %d s elapsed",
                    DOMAIN, elapsed, wait_sec,
                )
                return

        for i in range(len(self._loads) - 1, -1, -1):   # highest index first
            load = self._loads[i]

            if not load.is_configured:
                _LOGGER.debug("[%s] Load %d '%s': skip — not configured", DOMAIN, i, load.name)
                continue

            if load.switch_state in ("unavailable", "unknown"):
                _LOGGER.debug("[%s] Load %d '%s': skip — switch unavailable", DOMAIN, i, load.name)
                continue

            if load.current_power <= MIN_ACTIVE_POWER_W:
                _LOGGER.debug(
                    "[%s] Load %d '%s': skip — power %.0f W ≤ %d W (already off or idle)",
                    DOMAIN, i, load.name, load.current_power, MIN_ACTIVE_POWER_W,
                )
                continue

            if load.is_suspended:
                _LOGGER.debug(
                    "[%s] Load %d '%s': skip — already suspended (%.0f W)",
                    DOMAIN, i, load.name, load.suspended_power,
                )
                continue

            # Found a candidate — suspend it
            load.suspended_power = load.current_power
            _LOGGER.info(
                "[%s] Suspending load %d '%s' (%.0f W) — switch: %s",
                DOMAIN, i, load.name, load.suspended_power, load.switch,
            )

            await self.hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": load.switch},
                blocking=True,
            )

            _LOGGER.debug(
                "[%s] Load %d '%s' switched off — waiting %d s before next check",
                DOMAIN, i, load.name, wait_sec,
            )

            # Notify
            notify_entity: str = self.config_entry.data.get(CONF_NOTIFY_ENTITY, "")
            await async_notify(
                self.hass,
                notify_entity,
                title="Limite potenza superato",
                message=f"{load.name} disattivato.",
            )

            # Record the stop time — the next shed is blocked until
            # wait_between_stops_sec have elapsed (checked at the top of this method).
            # The coordinator keeps running normally in the meantime.
            self._last_stop_at = datetime.now()

            return  # one load per call — let the poll loop decide if more are needed

        _LOGGER.warning(
            "[%s] STOP requested but no sheddable load found "
            "(all loads idle, unconfigured or already suspended)",
            DOMAIN,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Start logic  (Step 6)
    # ──────────────────────────────────────────────────────────────────────────

    async def async_check_and_start(self, current_power: float) -> None:
        """Restore suspended loads when power has been under threshold long enough.

        Entry condition:
          current_power + total_suspended_power < threshold_delayed
          AND at least one load is suspended
          AND the condition has held for wait_before_start_min minutes
        """
        total_suspended = sum(
            l.suspended_power for l in self._loads if l.auto_restart
        )

        if total_suspended == 0:
            # Nothing to restore
            self._under_threshold_since = None
            return

        _, threshold_delayed = self.thresholds
        wait_before_min: int = int(
            self.config_entry.data.get(CONF_WAIT_BEFORE_START_MIN, 5)
        )
        now = datetime.now()

        # headroom_ok if at least one suspended load can be restored without exceeding threshold
        headroom_ok = any(
            (current_power + l.suspended_power) < threshold_delayed
            for l in self._loads
            if l.auto_restart and l.suspended_power > 0
        )

        if headroom_ok:
            if self._under_threshold_since is None:
                self._under_threshold_since = now
                _LOGGER.debug(
                    "[%s] Start timer started — %.0f W + %.0f W suspended < %.0f W threshold",
                    DOMAIN, current_power, total_suspended, threshold_delayed,
                )
            elapsed = (now - self._under_threshold_since).total_seconds()
            if elapsed < wait_before_min * 60:
                _LOGGER.debug(
                    "[%s] Waiting before restart: %.0f / %d s elapsed",
                    DOMAIN, elapsed, wait_before_min * 60,
                )
                return
            # Timer expired — proceed to restore one load
            _LOGGER.info(
                "[%s] START condition met (%.0f s > %d min) — attempting restore",
                DOMAIN, elapsed, wait_before_min,
            )
            await self._restore_one_load(current_power, threshold_delayed)
        else:
            if self._under_threshold_since is not None:
                _LOGGER.debug(
                    "[%s] Start timer reset — headroom gone "
                    "(%.0f + %.0f = %.0f W ≥ %.0f W)",
                    DOMAIN, current_power, total_suspended,
                    current_power + total_suspended, threshold_delayed,
                )
            self._under_threshold_since = None

    async def _restore_one_load(
        self, current_power: float, threshold_delayed: float
    ) -> None:
        """Turn on the highest-priority suspended load that fits within headroom."""
        wait_min: int = int(
            self.config_entry.data.get(CONF_WAIT_BETWEEN_STARTS_MIN, 5)
        )

        # Cooldown: block restore if the previous one happened too recently.
        if self._last_start_at is not None:
            elapsed = (datetime.now() - self._last_start_at).total_seconds()
            if elapsed < wait_min * 60:
                _LOGGER.debug(
                    "[%s] Start cooldown active — %.0f / %d s elapsed",
                    DOMAIN, elapsed, wait_min * 60,
                )
                return

        for i, load in enumerate(self._loads):   # index 0 = highest priority first
            if not load.is_suspended:
                continue

            if not load.is_configured:
                _LOGGER.debug(
                    "[%s] Load %d '%s': skip restore — not configured", DOMAIN, i, load.name
                )
                continue

            if load.keep_off:
                _LOGGER.debug(
                    "[%s] Load %d '%s': skip restore — keep_off flag set", DOMAIN, i, load.name
                )
                continue

            if not load.auto_restart:
                _LOGGER.debug(
                    "[%s] Load %d '%s': skip restore — auto_restart disabled",
                    DOMAIN, i, load.name,
                )
                continue

            # Check headroom: would re-enabling this load keep us under threshold?
            projected = current_power + load.suspended_power
            if projected >= threshold_delayed:
                _LOGGER.debug(
                    "[%s] Load %d '%s': skip restore — projected %.0f W ≥ %.0f W threshold",
                    DOMAIN, i, load.name, projected, threshold_delayed,
                )
                continue

            # Restore this load
            _LOGGER.info(
                "[%s] Restoring load %d '%s' (was %.0f W) — switch: %s",
                DOMAIN, i, load.name, load.suspended_power, load.switch,
            )
            load.suspended_power = 0.0

            await self.hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": load.switch},
                blocking=True,
            )

            # Notify
            notify_entity: str = self.config_entry.data.get(CONF_NOTIFY_ENTITY, "")
            await async_notify(
                self.hass,
                notify_entity,
                title="Limite potenza rientrato",
                message=f"{load.name} riattivato.",
            )

            # Reset the under-threshold timer so the next restore waits again
            self._under_threshold_since = None

            _LOGGER.debug(
                "[%s] Load %d '%s' restored — waiting %d min before next restore",
                DOMAIN, i, load.name, wait_min,
            )

            # Record the start time — the next restore is blocked until
            # wait_between_starts_min have elapsed.
            self._last_start_at = datetime.now()
            # Also reset the under-threshold timer: the next restore
            # must wait the full wait_before_start_min again.

            return  # one load per call

        _LOGGER.debug(
            "[%s] No restorable load found "
            "(all suspended loads have keep_off, auto_restart=False, or insufficient headroom)",
            DOMAIN,
        )
        # All suspended loads are permanently off or don't fit — clear timer
        self._under_threshold_since = None

    # ──────────────────────────────────────────────────────────────────────────
    # State restore after HA restart  (replaces the step-3 stub)
    # ──────────────────────────────────────────────────────────────────────────

    async def async_restore_state(self) -> None:
        """Restore suspended_power from the per-load sensor entities.

        The per-load sensor entities (created in step 4) persist their last
        known state in HA's state machine across restarts.  We read that value
        back here so the coordinator resumes correctly without losing track of
        which loads were suspended before the restart.
        """
        for i, load in enumerate(self._loads):
            entity_id = f"sensor.power_control_load_{i}_suspended"
            state = self.hass.states.get(entity_id)
            if state and state.state not in ("unavailable", "unknown", "None", ""):
                try:
                    load.suspended_power = float(state.state)
                    if load.suspended_power > 0:
                        _LOGGER.info(
                            "[%s] Restored suspended power for load %d '%s': %.0f W",
                            DOMAIN, i, load.name, load.suspended_power,
                        )
                except ValueError:
                    pass
