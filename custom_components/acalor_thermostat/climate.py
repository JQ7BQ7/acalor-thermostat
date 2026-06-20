"""Acalor Thermostat – climate entity with separate heat/cool setpoints.

Phase 3 (Lastenheft): getrennte Heiz-/Kühl-Solltemperatur, zweiter Schalter
(Kühlschalter) mit gegenseitiger Verriegelung, vier Toleranzen, konfigurierbare
Auflösung, Startverzögerung sowie Mindest-/Höchstlaufzeit. Modi: OFF / HEAT / COOL.

Noch nicht enthalten (spätere Phasen): Dynamic Dead Zone (Phase 5),
HEAT_COOL-Dispatcher (Phase 6), Anbindung externer Anforderungen (Phase 7).
Die Einhängepunkte für externe Anforderungen sind als Seam bereits vorhanden.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta
import logging
import math
from typing import Any, Literal

from homeassistant.components.climate import (
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    EVENT_HOMEASSISTANT_START,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    DOMAIN as HOMEASSISTANT_DOMAIN,
    CoreState,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.device import async_entity_id_to_device
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_COOL_ENABLE_ENTITY,
    CONF_COOL_ENABLE_INVERT,
    CONF_COOL_OFF_TOLERANCE,
    CONF_COOL_OFFSET_ENTITY,
    CONF_COOL_ON_TOLERANCE,
    CONF_COOLER,
    CONF_DDZ,
    CONF_HEAT_ENABLE_ENTITY,
    CONF_HEAT_ENABLE_INVERT,
    CONF_HEAT_OFFSET_ENTITY,
    CONF_HEAT_OFF_TOLERANCE,
    CONF_HEAT_ON_TOLERANCE,
    CONF_HEATER,
    CONF_KEEP_ALIVE,
    CONF_MAX_DUR,
    CONF_MAX_TEMP,
    CONF_MIN_DUR_COOL,
    CONF_MIN_DUR_HEAT,
    CONF_MIN_TEMP,
    CONF_MODE_CHANGE_DELAY,
    CONF_RESOLUTION,
    CONF_SENSOR,
    CONF_START_DELAY,
    CONF_TARGET_TEMP_COOL,
    CONF_TARGET_TEMP_HEAT,
    DEFAULT_RESOLUTION,
    DEFAULT_TOLERANCE,
)

_LOGGER = logging.getLogger(__name__)

# Welche Ausgangs-Anforderung der Regler aktuell stellt.
Output = Literal["heat", "cool"]
Decision = Literal["heat", "cool", "idle"]


def _as_timedelta(value: Any) -> timedelta | None:
    """Convert a config value (duration dict / timedelta) to timedelta."""
    if value is None:
        return None
    if isinstance(value, timedelta):
        return value
    if isinstance(value, Mapping):
        return timedelta(**value)
    # Plain number of seconds.
    return timedelta(seconds=float(value))


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Initialize the config entry."""
    options = config_entry.options
    async_add_entities(
        [
            AcalorThermostat(
                hass,
                name=options[CONF_NAME],
                sensor_entity_id=options[CONF_SENSOR],
                heater_entity_id=options[CONF_HEATER],
                cooler_entity_id=options[CONF_COOLER],
                dead_zone=options[CONF_DDZ],
                heat_on_tolerance=options.get(CONF_HEAT_ON_TOLERANCE, DEFAULT_TOLERANCE),
                heat_off_tolerance=options.get(
                    CONF_HEAT_OFF_TOLERANCE, DEFAULT_TOLERANCE
                ),
                cool_on_tolerance=options.get(CONF_COOL_ON_TOLERANCE, DEFAULT_TOLERANCE),
                cool_off_tolerance=options.get(
                    CONF_COOL_OFF_TOLERANCE, DEFAULT_TOLERANCE
                ),
                resolution=options.get(CONF_RESOLUTION, DEFAULT_RESOLUTION),
                min_dur_heat=_as_timedelta(options.get(CONF_MIN_DUR_HEAT)),
                min_dur_cool=_as_timedelta(options.get(CONF_MIN_DUR_COOL)),
                max_cycle_duration=_as_timedelta(options.get(CONF_MAX_DUR)),
                start_delay=_as_timedelta(options.get(CONF_START_DELAY)),
                mode_change_delay=_as_timedelta(options.get(CONF_MODE_CHANGE_DELAY)),
                keep_alive=_as_timedelta(options.get(CONF_KEEP_ALIVE)),
                min_temp=options.get(CONF_MIN_TEMP),
                max_temp=options.get(CONF_MAX_TEMP),
                target_temp_heat=options.get(CONF_TARGET_TEMP_HEAT),
                target_temp_cool=options.get(CONF_TARGET_TEMP_COOL),
                heat_enable_entity=options.get(CONF_HEAT_ENABLE_ENTITY),
                heat_enable_invert=options.get(CONF_HEAT_ENABLE_INVERT, False),
                cool_enable_entity=options.get(CONF_COOL_ENABLE_ENTITY),
                cool_enable_invert=options.get(CONF_COOL_ENABLE_INVERT, False),
                heat_offset_entity=options.get(CONF_HEAT_OFFSET_ENTITY),
                cool_offset_entity=options.get(CONF_COOL_OFFSET_ENTITY),
                unit=hass.config.units.temperature_unit,
                unique_id=config_entry.entry_id,
            )
        ]
    )


class AcalorThermostat(ClimateEntity, RestoreEntity):
    """Thermostat with independent heat/cool setpoints and two switches."""

    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        name: str,
        sensor_entity_id: str,
        heater_entity_id: str,
        cooler_entity_id: str,
        dead_zone: float,
        heat_on_tolerance: float,
        heat_off_tolerance: float,
        cool_on_tolerance: float,
        cool_off_tolerance: float,
        resolution: str,
        min_dur_heat: timedelta | None,
        min_dur_cool: timedelta | None,
        max_cycle_duration: timedelta | None,
        start_delay: timedelta | None,
        mode_change_delay: timedelta | None,
        keep_alive: timedelta | None,
        min_temp: float | None,
        max_temp: float | None,
        target_temp_heat: float | None,
        target_temp_cool: float | None,
        heat_enable_entity: str | None,
        heat_enable_invert: bool,
        cool_enable_entity: str | None,
        cool_enable_invert: bool,
        heat_offset_entity: str | None,
        cool_offset_entity: str | None,
        unit: str,
        unique_id: str,
    ) -> None:
        """Initialize the thermostat."""
        self._attr_name = name
        self._attr_unique_id = unique_id
        self.sensor_entity_id = sensor_entity_id
        self.heater_entity_id = heater_entity_id
        self.cooler_entity_id = cooler_entity_id
        self.device_entry = async_entity_id_to_device(hass, heater_entity_id)

        # Konfiguration
        self._dead_zone = dead_zone  # Mindestabstand Kühl-/Heiz-Soll (DDZ)
        self._heat_on_tol = heat_on_tolerance
        self._heat_off_tol = heat_off_tolerance
        self._cool_on_tol = cool_on_tolerance
        self._cool_off_tol = cool_off_tolerance
        self._resolution = float(resolution)
        self._min_dur_heat = min_dur_heat or timedelta()
        self._min_dur_cool = min_dur_cool or timedelta()
        self._max_cycle_duration = max_cycle_duration
        self._start_delay = start_delay or timedelta()
        self._mode_change_delay = mode_change_delay or timedelta()
        self._keep_alive = keep_alive
        self._min_temp = min_temp
        self._max_temp = max_temp

        # Laufzeit-Zustand
        self._cur_temp: float | None = None
        self._target_temp_heat = target_temp_heat
        self._target_temp_cool = target_temp_cool
        self._hvac_mode: HVACMode = HVACMode.OFF
        self._active = False
        self._temp_lock = asyncio.Lock()

        # Welcher Ausgang ist von uns angefordert + seit wann (für Laufzeiten).
        self._active_output: Output | None = None
        self._output_started: datetime | None = None

        # Externe Anforderungen (Lastenheft 6): zugewiesene Entitäten + Polarität.
        self._heat_enable_entity = heat_enable_entity
        self._heat_enable_invert = heat_enable_invert
        self._cool_enable_entity = cool_enable_entity
        self._cool_enable_invert = cool_enable_invert
        self._heat_offset_entity = heat_offset_entity
        self._cool_offset_entity = cool_offset_entity
        # Aktuelle Werte (Defaults neutral, bis die Entitäten gelesen werden).
        self._ext_heat_enable = True
        self._ext_cool_enable = True
        self._ext_heat_offset = 0.0
        self._ext_cool_offset = 0.0

        # Timer-Handles
        self._start_delay_unsub: CALLBACK_TYPE | None = None
        self._min_runtime_unsub: CALLBACK_TYPE | None = None
        self._max_runtime_unsub: CALLBACK_TYPE | None = None
        self._mode_change_unsub: CALLBACK_TYPE | None = None
        self._pending_start_output: Output | None = None

        self._attr_temperature_unit = unit
        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.HEAT,
            HVACMode.COOL,
            HVACMode.HEAT_COOL,
        ]
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def async_added_to_hass(self) -> None:
        """Register listeners and restore state."""
        await super().async_added_to_hass()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self.sensor_entity_id], self._async_sensor_changed
            )
        )
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self.heater_entity_id, self.cooler_entity_id],
                self._async_switch_changed,
            )
        )

        external_entities = [
            entity
            for entity in (
                self._heat_enable_entity,
                self._cool_enable_entity,
                self._heat_offset_entity,
                self._cool_offset_entity,
            )
            if entity
        ]
        if external_entities:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, external_entities, self._async_external_changed
                )
            )

        self.async_on_remove(self._cancel_timers)

        if self._keep_alive:
            self.async_on_remove(
                async_track_time_interval(
                    self.hass, self._async_control_keepalive, self._keep_alive
                )
            )

        await self._async_restore_state()

        @callback
        def _async_startup(_: Event | None = None) -> None:
            sensor_state = self.hass.states.get(self.sensor_entity_id)
            if sensor_state and sensor_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                self._async_update_temp(sensor_state)
            self._update_external()
            # Tatsächlichen Ausgangszustand übernehmen + Sicherheits-Check.
            self.hass.async_create_task(self._async_startup_control(), eager_start=True)

        if self.hass.state is CoreState.running:
            _async_startup()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

    async def _async_restore_state(self) -> None:
        """Restore HVAC mode and both setpoints (Lastenheft 3.4)."""
        old_state = await self.async_get_last_state()
        if old_state is not None:
            if self._target_temp_heat is None:
                self._target_temp_heat = _to_float(
                    old_state.attributes.get(ATTR_TARGET_TEMP_LOW)
                )
            if self._target_temp_cool is None:
                self._target_temp_cool = _to_float(
                    old_state.attributes.get(ATTR_TARGET_TEMP_HIGH)
                )
            try:
                restored_mode = HVACMode(old_state.state)
            except ValueError:
                restored_mode = HVACMode.OFF
            if restored_mode in self._attr_hvac_modes:
                self._hvac_mode = restored_mode

        # Sinnvolle Defaults, falls nichts wiederhergestellt werden konnte.
        if self._target_temp_heat is None:
            self._target_temp_heat = self.min_temp
        if self._target_temp_cool is None:
            self._target_temp_cool = self.max_temp

        # DDZ auch nach Neustart erzwingen (z.B. falls DDZ-Config erhöht wurde).
        self._enforce_ddz(None)

    async def _async_startup_control(self) -> None:
        """Adopt the real switch state, enforce safety, then evaluate."""
        async with self._temp_lock:
            heater_on = self._switch_is_on(self.heater_entity_id)
            cooler_on = self._switch_is_on(self.cooler_entity_id)

            # 3.4.1 / 4.1: laufende Aktion nicht speichern, Verriegelung prüfen.
            if self._hvac_mode == HVACMode.OFF or (heater_on and cooler_on):
                # Sicherheit: in OFF oder bei Doppelschaltung alles aus.
                if heater_on or cooler_on:
                    _LOGGER.warning(
                        "Unsafe initial output state (heater=%s, cooler=%s) – "
                        "switching both off",
                        heater_on,
                        cooler_on,
                    )
                    await self._switch_set(self.heater_entity_id, False)
                    await self._switch_set(self.cooler_entity_id, False)
                self._active_output = None
                self._output_started = None
            elif heater_on:
                self._active_output = "heat"
                self._output_started = dt_util.utcnow()
            elif cooler_on:
                self._active_output = "cool"
                self._output_started = dt_util.utcnow()

        self.async_write_ha_state()
        await self._async_control()

    # ------------------------------------------------------------------ #
    # Properties
    # ------------------------------------------------------------------ #

    @property
    def precision(self) -> float:
        """Return the precision of the system."""
        return self._resolution

    @property
    def target_temperature_step(self) -> float:
        """Return the step of the target temperature."""
        return self._resolution

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._cur_temp

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current operation mode."""
        return self._hvac_mode

    @property
    def hvac_action(self) -> HVACAction:
        """Return the current running action (derived from the real outputs).

        Der reale Schalterzustand hat Vorrang: Während der OFF-Entprellung läuft
        der Ausgang noch, also wird weiterhin heating/cooling angezeigt – erst
        wenn der Schalter tatsächlich aus ist, gilt OFF.
        """
        if self._switch_is_on(self.heater_entity_id):
            return HVACAction.HEATING
        if self._switch_is_on(self.cooler_entity_id):
            return HVACAction.COOLING
        if self._hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        return HVACAction.IDLE

    @property
    def target_temperature(self) -> float | None:
        """Single setpoint shown in HEAT / COOL."""
        if self._hvac_mode == HVACMode.HEAT:
            return self._target_temp_heat
        if self._hvac_mode == HVACMode.COOL:
            return self._target_temp_cool
        return None

    @property
    def target_temperature_low(self) -> float | None:
        """Heating setpoint (used by the range display in HEAT_COOL)."""
        return self._target_temp_heat

    @property
    def target_temperature_high(self) -> float | None:
        """Cooling setpoint (used by the range display in HEAT_COOL)."""
        return self._target_temp_cool

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose DDZ, external requests and a human-readable status reason."""
        attrs: dict[str, Any] = {
            "dead_zone": self._dead_zone,
            "heat_enabled": self._ext_heat_enable,
            "cool_enabled": self._ext_cool_enable,
            "heat_offset": self._ext_heat_offset,
            "cool_offset": self._ext_cool_offset,
            "status_reason": self._status_reason(),
        }
        # Tatsächlich angefahrener Wert (Sollwert inkl. externem Offset).
        if self._target_temp_heat is not None:
            attrs["heat_setpoint_effective"] = round(
                self._target_temp_heat + self._ext_heat_offset, 2
            )
        if self._target_temp_cool is not None:
            attrs["cool_setpoint_effective"] = round(
                self._target_temp_cool + self._ext_cool_offset, 2
            )
        return attrs

    def _status_reason(self) -> str:
        """Human-readable reason for the current state (Lastenheft 5.3)."""
        if self._hvac_mode == HVACMode.OFF:
            return "Aus"
        action = self.hvac_action
        if action == HVACAction.HEATING:
            return "Heizen" + self._offset_suffix(self._ext_heat_offset)
        if action == HVACAction.COOLING:
            return "Kühlen" + self._offset_suffix(self._ext_cool_offset)
        # Leerlauf – genauer aufschlüsseln:
        if self._mode_change_unsub is not None:
            return "Moduswechsel-Verzögerung"
        if self._pending_start_output == "heat":
            return "Startverzögerung (Heizen)"
        if self._pending_start_output == "cool":
            return "Startverzögerung (Kühlen)"
        cur = self._cur_temp
        if cur is not None:
            heat_relevant = self._hvac_mode in (HVACMode.HEAT, HVACMode.HEAT_COOL)
            cool_relevant = self._hvac_mode in (HVACMode.COOL, HVACMode.HEAT_COOL)
            if (
                heat_relevant
                and not self._ext_heat_enable
                and self._target_temp_heat is not None
                and cur < self._target_temp_heat + self._ext_heat_offset
            ):
                return "Heizen extern gesperrt"
            if (
                cool_relevant
                and not self._ext_cool_enable
                and self._target_temp_cool is not None
                and cur > self._target_temp_cool + self._ext_cool_offset
            ):
                return "Kühlen extern gesperrt"
        return "Leerlauf"

    @staticmethod
    def _offset_suffix(offset: float) -> str:
        """Append an active external offset to the status text."""
        if not offset:
            return ""
        return f" (Offset {offset:+.1f} °C)".replace(".", ",")

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        if self._min_temp is not None:
            return self._min_temp
        return super().min_temp

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        if self._max_temp is not None:
            return self._max_temp
        return super().max_temp

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set a new HVAC mode (Lastenheft 8.1 / 8.2, 8.4-Entprellung)."""
        if hvac_mode not in self._attr_hvac_modes:
            _LOGGER.error("Unsupported HVAC mode: %s", hvac_mode)
            return
        self._hvac_mode = hvac_mode
        await self._handle_user_change()
        self.async_write_ha_state()

    async def _handle_user_change(self) -> None:
        """Apply a user-initiated change (mode or setpoint) with debounce.

        Ein Moduswechsel (inkl. OFF) ODER eine Sollwert-Änderung schaltet die
        Ausgänge nicht sofort. Die Anlage läuft zunächst unverändert weiter
        (Entprellung): Wird innerhalb der Moduswechsel-Verzögerung erneut
        umgeschaltet/verstellt, verfällt der Timer – es passiert nichts. Erst
        nach Ablauf erfolgt die volle Neubewertung und das Schalten. Dadurch
        gilt die Verzögerung auch fürs Ausschalten bei Sollwert-Änderungen.
        """
        # Anstehende Schalthandlungen verwerfen – die Lage ändert sich.
        self._cancel_start_delay()
        self._cancel_mode_change()

        if self._mode_change_delay > timedelta():
            _LOGGER.debug(
                "User change – debouncing for %s before acting",
                self._mode_change_delay,
            )
            self._mode_change_unsub = async_call_later(
                self.hass, self._mode_change_delay, self._async_mode_change_fired
            )
            return

        # Keine Entprellung konfiguriert: sofort bewerten und schalten.
        await self._async_control()

    async def _async_mode_change_fired(self, _now: datetime | None = None) -> None:
        """After the debounce: re-evaluate and switch."""
        self._mode_change_unsub = None
        await self._async_control()
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature(s)."""
        low = kwargs.get(ATTR_TARGET_TEMP_LOW)
        high = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        single = kwargs.get(ATTR_TEMPERATURE)

        if low is not None and high is not None:
            # Bereichseingabe (HEAT_COOL): nur den bewegten Griff als Anker nehmen,
            # damit der vom Nutzer eingestellte Wert exakt stehen bleibt und nur
            # der andere Sollwert ausweicht (kein „Zurückfedern").
            old_heat = self._target_temp_heat
            old_cool = self._target_temp_cool
            self._target_temp_heat = low
            self._target_temp_cool = high
            heat_moved = old_heat is None or self._round(low) != self._round(old_heat)
            cool_moved = old_cool is None or self._round(high) != self._round(old_cool)
            if cool_moved and not heat_moved:
                self._enforce_ddz("cool")
            elif heat_moved and not cool_moved:
                self._enforce_ddz("heat")
            else:
                self._enforce_ddz(None)
        elif single is not None:
            if self._hvac_mode == HVACMode.HEAT:
                self._target_temp_heat = single
                self._enforce_ddz("heat")
            elif self._hvac_mode == HVACMode.COOL:
                self._target_temp_cool = single
                self._enforce_ddz("cool")
            else:
                return
        else:
            return

        await self._handle_user_change()
        self.async_write_ha_state()

    # ------------------------------------------------------------------ #
    # Sensor / switch events
    # ------------------------------------------------------------------ #

    async def _async_sensor_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Handle temperature sensor updates."""
        new_state = event.data["new_state"]
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        self._async_update_temp(new_state)
        self.async_set_context(event.context)
        await self._async_control()
        self.async_write_ha_state()

    @callback
    def _async_switch_changed(self, event: Event[EventStateChangedData]) -> None:
        """Refresh state when a switch changes (no re-control, avoids loops)."""
        if event.data["new_state"] is None:
            return
        self.async_write_ha_state()

    @callback
    def _async_update_temp(self, state: State) -> None:
        """Update the current temperature from the sensor."""
        try:
            cur_temp = float(state.state)
            if not math.isfinite(cur_temp):
                raise ValueError(f"Sensor has illegal state {state.state}")  # noqa: TRY301
            self._cur_temp = cur_temp
        except ValueError as ex:
            _LOGGER.error("Unable to update from sensor: %s", ex)

    async def _async_control_keepalive(self, _now: datetime | None = None) -> None:
        """Keep-alive tick (re-assert the current output)."""
        await self._async_control(keepalive=True)

    # ------------------------------------------------------------------ #
    # Externe Anforderungen (Lastenheft 6)
    # ------------------------------------------------------------------ #

    async def _async_external_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """React to a change of an external request entity."""
        self._update_external()
        await self._async_control()
        self.async_write_ha_state()

    @callback
    def _update_external(self) -> None:
        """Read the assigned external request entities into the internal seam."""
        self._ext_heat_enable = self._read_enable(
            self._heat_enable_entity, self._heat_enable_invert
        )
        self._ext_cool_enable = self._read_enable(
            self._cool_enable_entity, self._cool_enable_invert
        )
        self._ext_heat_offset = self._read_offset(self._heat_offset_entity)
        self._ext_cool_offset = self._read_offset(self._cool_offset_entity)

    def _read_enable(self, entity_id: str | None, invert: bool) -> bool:
        """Read an enable entity (on = allowed). Fail-safe: allow if unavailable."""
        if not entity_id:
            return True
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return True
        enabled = state.state == STATE_ON
        return not enabled if invert else enabled

    def _read_offset(self, entity_id: str | None) -> float:
        """Read a numeric offset entity (°C). 0.0 if unset/invalid."""
        if not entity_id:
            return 0.0
        state = self.hass.states.get(entity_id)
        if state is None:
            return 0.0
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return 0.0
        return value if math.isfinite(value) else 0.0

    # ------------------------------------------------------------------ #
    # Regelung: Entscheidung (_evaluate) + Umsetzung (_apply)
    # ------------------------------------------------------------------ #

    async def _async_control(self, *, keepalive: bool = False) -> None:
        """Re-evaluate and apply the control decision."""
        async with self._temp_lock:
            # Während der Moduswechsel-Entprellung bleibt die Anlage eingefroren:
            # weder Sensor-Updates noch Keep-alive dürfen jetzt schalten.
            if self._mode_change_unsub is not None:
                return

            if not self._active and self._cur_temp is not None:
                self._active = True

            if self._hvac_mode == HVACMode.OFF:
                # OFF schaltet sofort ab (Lastenheft 2.1) – die Mindestlaufzeit
                # wird hier bewusst nicht abgewartet.
                self._cancel_start_delay()
                if self._active_output is not None:
                    await self._switch_off_active()
                else:
                    await self._switch_set(self.heater_entity_id, False)
                    await self._switch_set(self.cooler_entity_id, False)
                return

            if not self._active or self._cur_temp is None:
                return

            decision = self._evaluate()
            await self._apply(decision, keepalive=keepalive)

    def _evaluate(self) -> Decision:
        """Pure decision: heating / cooling / idle (Lastenheft 2 + 6).

        External enables/offsets are applied here – the single, defined point
        where external requests influence the decision.
        """
        cur = self._cur_temp
        if cur is None:
            return "idle"

        if self._hvac_mode == HVACMode.HEAT:
            return self._eval_heat(cur)
        if self._hvac_mode == HVACMode.COOL:
            return self._eval_cool(cur)
        if self._hvac_mode == HVACMode.HEAT_COOL:
            return self._eval_heat_cool(cur)
        return "idle"

    def _eval_heat(self, cur: float) -> Decision:
        """Heating hysteresis using the heat setpoint (+ external offset)."""
        if not self._ext_heat_enable or self._target_temp_heat is None:
            return "idle"
        setpoint = self._target_temp_heat + self._ext_heat_offset
        if self._active_output == "heat":
            # Läuft – erst bei Überschreiten der AUS-Schwelle stoppen.
            if cur > setpoint + self._heat_off_tol:
                return "idle"
            return "heat"
        # Steht – erst bei Unterschreiten der EIN-Schwelle starten.
        if cur < setpoint - self._heat_on_tol:
            return "heat"
        return "idle"

    def _eval_cool(self, cur: float) -> Decision:
        """Cooling hysteresis using the cool setpoint (+ external offset)."""
        if not self._ext_cool_enable or self._target_temp_cool is None:
            return "idle"
        setpoint = self._target_temp_cool + self._ext_cool_offset
        if self._active_output == "cool":
            if cur < setpoint - self._cool_off_tol:
                return "idle"
            return "cool"
        if cur > setpoint + self._cool_on_tol:
            return "cool"
        return "idle"

    def _eval_heat_cool(self, cur: float) -> Decision:
        """HEAT_COOL dispatcher (Lastenheft 2.4).

        Der Modus bleibt dauerhaft HEAT_COOL; je nach Ist-Temperatur wird die
        Heiz- oder Kühllogik (inkl. eigener Hysterese) ausgeführt, dazwischen
        (innerhalb der Dead Zone) idle.
        """
        # Laufenden Ausgang mit seiner Hysterese fortführen, solange gefordert.
        if self._active_output == "heat" and self._eval_heat(cur) == "heat":
            return "heat"
        if self._active_output == "cool" and self._eval_cool(cur) == "cool":
            return "cool"
        # Sonst neu dispatchen – auch wenn der laufende Ausgang gerade abschalten
        # soll: liegt die Ist-Temp jenseits eines Sollwerts, direkt auf die andere
        # Seite wechseln. Ohne das bliebe der Regler nach heat->idle im Leerlauf
        # „hängen", statt auf cool zu gehen (und umgekehrt).
        if (
            self._target_temp_heat is not None
            and cur < self._target_temp_heat + self._ext_heat_offset
        ):
            return self._eval_heat(cur)
        if (
            self._target_temp_cool is not None
            and cur > self._target_temp_cool + self._ext_cool_offset
        ):
            return self._eval_cool(cur)
        return "idle"

    def _output_allowed(self, output: Output) -> bool:
        """Whether an output may run in the current HVAC mode (Lastenheft 2.2/2.3)."""
        if self._hvac_mode == HVACMode.HEAT:
            return output == "heat"
        if self._hvac_mode == HVACMode.COOL:
            return output == "cool"
        if self._hvac_mode == HVACMode.HEAT_COOL:
            return True
        return False

    async def _apply(self, decision: Decision, *, keepalive: bool) -> None:
        """Apply a decision following the order from Lastenheft 8.2."""
        target: Output | None = None if decision == "idle" else decision

        # Veraltete Startverzögerung verwerfen, wenn das Ziel sich geändert hat.
        if self._pending_start_output is not None and (
            self._pending_start_output != target
        ):
            self._cancel_start_delay()

        # Kein Wechsel der Anforderung.
        if self._active_output == target:
            if keepalive and target is not None:
                await self._reassert_output(target)
            return

        # 2./3. Mindestlaufzeit + Verriegelung: laufenden Ausgang ggf. abschalten.
        if self._active_output is not None:
            # Die Mindestlaufzeit schützt nur einen im aktuellen Modus erlaubten
            # Ausgang. Ein modus-fremder Ausgang (z.B. Heizen nach Wechsel auf
            # COOL) wird sofort abgeschaltet (Lastenheft 2.2 / 2.3).
            if self._output_allowed(
                self._active_output
            ) and not self._min_runtime_elapsed(self._active_output):
                self._schedule_min_runtime_recheck(self._active_output)
                return
            await self._switch_off_active()

        if target is None:
            return

        # 4. Startverzögerung: erst nach Ablauf + erneuter Bewertung schalten.
        if self._start_delay > timedelta():
            if self._pending_start_output != target:
                self._cancel_start_delay()
                self._pending_start_output = target
                self._start_delay_unsub = async_call_later(
                    self.hass, self._start_delay, self._async_start_delay_fired
                )
                _LOGGER.debug(
                    "Start delay %s before switching on %s output",
                    self._start_delay,
                    target,
                )
            return

        # 5. Schaltentscheidung.
        await self._switch_on(target)

    async def _async_start_delay_fired(self, _now: datetime | None = None) -> None:
        """After the start delay: re-evaluate, switch on only if still demanded."""
        self._start_delay_unsub = None
        target = self._pending_start_output
        self._pending_start_output = None
        if target is None:
            return
        async with self._temp_lock:
            if self._hvac_mode == HVACMode.OFF or self._cur_temp is None:
                return
            if self._evaluate() == target and self._active_output is None:
                await self._switch_on(target)

    # ------------------------------------------------------------------ #
    # Ausgänge schalten (mit Verriegelung) + Laufzeit-Timer
    # ------------------------------------------------------------------ #

    async def _switch_on(self, output: Output) -> None:
        """Turn the requested output on after ensuring the other is off (4.1)."""
        other_entity = (
            self.cooler_entity_id if output == "heat" else self.heater_entity_id
        )
        this_entity = (
            self.heater_entity_id if output == "heat" else self.cooler_entity_id
        )
        # Verriegelung: immer zuerst den anderen Ausgang ausschalten.
        await self._switch_set(other_entity, False)
        await self._switch_set(this_entity, True)
        self._active_output = output
        self._output_started = dt_util.utcnow()
        self._cancel_min_runtime_recheck()
        self._schedule_max_runtime()
        self.async_write_ha_state()

    async def _switch_off_active(self) -> None:
        """Turn off whichever output is currently active."""
        await self._switch_set(self.heater_entity_id, False)
        await self._switch_set(self.cooler_entity_id, False)
        self._active_output = None
        self._output_started = None
        self._cancel_max_runtime()
        self.async_write_ha_state()

    async def _reassert_output(self, output: Output) -> None:
        """Keep-alive: re-send the ON command to the active output."""
        entity = self.heater_entity_id if output == "heat" else self.cooler_entity_id
        await self._switch_set(entity, True, force=True)

    async def _switch_set(
        self, entity_id: str, turn_on: bool, *, force: bool = False
    ) -> None:
        """Call switch.turn_on/off, skipping redundant calls unless forced."""
        is_on = self._switch_is_on(entity_id)
        if not force and (turn_on == is_on):
            return
        service = SERVICE_TURN_ON if turn_on else SERVICE_TURN_OFF
        await self.hass.services.async_call(
            HOMEASSISTANT_DOMAIN,
            service,
            {ATTR_ENTITY_ID: entity_id},
            context=self._context,
        )

    def _switch_is_on(self, entity_id: str) -> bool:
        """Return True if the given switch entity is on."""
        return self.hass.states.is_state(entity_id, STATE_ON)

    # --- Mindestlaufzeit (Lastenheft 8.3) ---

    def _min_runtime(self, output: Output) -> timedelta:
        return self._min_dur_heat if output == "heat" else self._min_dur_cool

    def _min_runtime_elapsed(self, output: Output) -> bool:
        min_dur = self._min_runtime(output)
        if not min_dur or self._output_started is None:
            return True
        return dt_util.utcnow() >= self._output_started + min_dur

    def _schedule_min_runtime_recheck(self, output: Output) -> None:
        if self._min_runtime_unsub is not None or self._output_started is None:
            return
        remaining = (self._output_started + self._min_runtime(output)) - dt_util.utcnow()
        if remaining <= timedelta():
            return
        _LOGGER.debug("Minimum runtime not reached, re-check in %s", remaining)
        self._min_runtime_unsub = async_call_later(
            self.hass, remaining, self._async_min_runtime_fired
        )

    async def _async_min_runtime_fired(self, _now: datetime | None = None) -> None:
        self._min_runtime_unsub = None
        await self._async_control()

    # --- Höchstlaufzeit (Lastenheft 7.2) ---

    def _schedule_max_runtime(self) -> None:
        if not self._max_cycle_duration:
            return
        self._cancel_max_runtime()
        _LOGGER.debug("Scheduling max-runtime shut-off in %s", self._max_cycle_duration)
        self._max_runtime_unsub = async_call_later(
            self.hass, self._max_cycle_duration, self._async_max_runtime_fired
        )

    async def _async_max_runtime_fired(self, _now: datetime | None = None) -> None:
        self._max_runtime_unsub = None
        async with self._temp_lock:
            if self._active_output is not None:
                _LOGGER.debug("Max runtime reached – switching output off")
                await self._switch_off_active()

    # --- Timer-Aufräumen ---

    @callback
    def _cancel_start_delay(self) -> None:
        if self._start_delay_unsub is not None:
            self._start_delay_unsub()
            self._start_delay_unsub = None
        self._pending_start_output = None

    @callback
    def _cancel_min_runtime_recheck(self) -> None:
        if self._min_runtime_unsub is not None:
            self._min_runtime_unsub()
            self._min_runtime_unsub = None

    @callback
    def _cancel_max_runtime(self) -> None:
        if self._max_runtime_unsub is not None:
            self._max_runtime_unsub()
            self._max_runtime_unsub = None

    @callback
    def _cancel_mode_change(self) -> None:
        if self._mode_change_unsub is not None:
            self._mode_change_unsub()
            self._mode_change_unsub = None

    @callback
    def _cancel_timers(self) -> None:
        self._cancel_start_delay()
        self._cancel_min_runtime_recheck()
        self._cancel_max_runtime()
        self._cancel_mode_change()

    # ------------------------------------------------------------------ #
    # Dynamic Dead Zone (Lastenheft 3.2 / 3.3)
    # ------------------------------------------------------------------ #

    def _enforce_ddz(self, anchor: Literal["heat", "cool"] | None) -> None:
        """Enforce ``cool >= heat + DDZ`` – the invariant that must never break.

        ``anchor`` ist der gerade geänderte Sollwert; der jeweils andere wird
        nachgezogen (Lastenheft 3.3). Bei ``None`` (Neustart / Bereichseingabe)
        wird symmetrisch um die Mitte aufgezogen (Lastenheft 3.2.1). Beide Werte
        werden gerundet und auf [min_temp, max_temp] begrenzt; ein durch das
        Begrenzen entstehender Verstoß wird anschließend korrigiert.
        """
        heat = self._target_temp_heat
        cool = self._target_temp_cool
        if heat is None or cool is None:
            self._target_temp_heat = self._round(heat)
            self._target_temp_cool = self._round(cool)
            return

        ddz = self._dead_zone
        if cool - heat < ddz:
            if anchor == "heat":
                cool = heat + ddz
            elif anchor == "cool":
                heat = cool - ddz
            else:
                mid = (heat + cool) / 2
                heat = mid - ddz / 2
                cool = mid + ddz / 2

        heat = self._round(heat)
        cool = self._round(cool)

        # Das Begrenzen auf min/max kann die DDZ erneut verletzen -> nachziehen
        # (setzt voraus, dass max_temp - min_temp >= DDZ; per Config-Flow geprüft).
        if cool - heat < ddz:
            if cool >= self.max_temp:
                heat = self._round(cool - ddz)
            else:
                cool = self._round(heat + ddz)

        self._target_temp_heat = heat
        self._target_temp_cool = cool

    # ------------------------------------------------------------------ #
    # Hilfsfunktionen
    # ------------------------------------------------------------------ #

    def _round(self, value: float | None) -> float | None:
        """Round to the configured resolution and clamp to min/max."""
        if value is None:
            return None
        step = self._resolution
        rounded = round(round(value / step) * step, 2)
        return min(max(rounded, self.min_temp), self.max_temp)


def _to_float(value: Any) -> float | None:
    """Best-effort float conversion for restored attributes."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
