"""Constants for the Acalor Thermostat integration."""

from homeassistant.const import Platform

DOMAIN = "acalor_thermostat"

PLATFORMS = [Platform.CLIMATE]

# --- Pflichtparameter (Lastenheft 7.1) ---
CONF_SENSOR = "target_sensor"
CONF_HEATER = "heater"
CONF_COOLER = "cooler"
CONF_DDZ = "dead_zone"
CONF_HEAT_ON_TOLERANCE = "heat_on_tolerance"
CONF_HEAT_OFF_TOLERANCE = "heat_off_tolerance"
CONF_COOL_ON_TOLERANCE = "cool_on_tolerance"
CONF_COOL_OFF_TOLERANCE = "cool_off_tolerance"

# --- Erweiterbare Parameter (Lastenheft 7.2) ---
CONF_MIN_DUR_HEAT = "min_cycle_duration_heat"
CONF_MIN_DUR_COOL = "min_cycle_duration_cool"
CONF_MAX_DUR = "max_cycle_duration"
CONF_START_DELAY = "start_delay"
CONF_MODE_CHANGE_DELAY = "mode_change_delay"
CONF_KEEP_ALIVE = "keep_alive"

# --- Temperaturauflösung (Lastenheft 7.3) ---
CONF_RESOLUTION = "resolution"

# --- Externe Anforderungen / Schnittstelle (Lastenheft 6) ---
CONF_HEAT_ENABLE_ENTITY = "heat_enable_entity"
CONF_HEAT_ENABLE_INVERT = "heat_enable_invert"
CONF_COOL_ENABLE_ENTITY = "cool_enable_entity"
CONF_COOL_ENABLE_INVERT = "cool_enable_invert"
CONF_HEAT_OFFSET_ENTITY = "heat_offset_entity"
CONF_COOL_OFFSET_ENTITY = "cool_offset_entity"

# --- Sollwert-Grenzen / Startwerte ---
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"
CONF_TARGET_TEMP_HEAT = "target_temp_heat"
CONF_TARGET_TEMP_COOL = "target_temp_cool"

# --- Defaults ---
DEFAULT_TOLERANCE = 0.3
DEFAULT_DDZ = 2.0
DEFAULT_START_DELAY = 15  # Sekunden (Lastenheft 8.4)
DEFAULT_MODE_CHANGE_DELAY = 15  # Sekunden – Entprellung bei Moduswechsel/OFF
DEFAULT_RESOLUTION = "0.1"
RESOLUTIONS = ["0.1", "0.5"]
