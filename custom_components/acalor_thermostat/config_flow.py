"""Config flow for the Acalor Thermostat integration."""

from collections.abc import Mapping
from datetime import timedelta
from typing import Any, cast

import voluptuous as vol

from homeassistant.components import switch
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.const import CONF_NAME, DEGREE
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaConfigFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
)

from .const import (
    CONF_COOL_OFF_TOLERANCE,
    CONF_COOL_ON_TOLERANCE,
    CONF_COOLER,
    CONF_DDZ,
    CONF_HEAT_OFF_TOLERANCE,
    CONF_HEAT_ON_TOLERANCE,
    CONF_HEATER,
    CONF_KEEP_ALIVE,
    CONF_MAX_DUR,
    CONF_MAX_TEMP,
    CONF_MIN_DUR_COOL,
    CONF_MIN_DUR_HEAT,
    CONF_MIN_TEMP,
    CONF_RESOLUTION,
    CONF_SENSOR,
    CONF_START_DELAY,
    CONF_TARGET_TEMP_COOL,
    CONF_TARGET_TEMP_HEAT,
    DOMAIN,
    DEFAULT_DDZ,
    DEFAULT_RESOLUTION,
    DEFAULT_START_DELAY,
    DEFAULT_TOLERANCE,
    RESOLUTIONS,
)


def _temp_selector() -> selector.NumberSelector:
    """Number input for a temperature value."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=DEGREE,
            step=0.1,
        )
    )


def _duration_selector() -> selector.DurationSelector:
    """Non-negative duration input."""
    return selector.DurationSelector(
        selector.DurationSelectorConfig(allow_negative=False)
    )


OPTIONS_SCHEMA = {
    # --- Ein-/Ausgänge ---
    vol.Required(CONF_SENSOR): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=SENSOR_DOMAIN, device_class=SensorDeviceClass.TEMPERATURE
        )
    ),
    vol.Required(CONF_HEATER): selector.EntitySelector(
        selector.EntitySelectorConfig(domain=switch.DOMAIN)
    ),
    vol.Required(CONF_COOLER): selector.EntitySelector(
        selector.EntitySelectorConfig(domain=switch.DOMAIN)
    ),
    # --- Dynamic Dead Zone + Toleranzen ---
    vol.Required(CONF_DDZ, default=DEFAULT_DDZ): _temp_selector(),
    vol.Required(CONF_HEAT_ON_TOLERANCE, default=DEFAULT_TOLERANCE): _temp_selector(),
    vol.Required(CONF_HEAT_OFF_TOLERANCE, default=DEFAULT_TOLERANCE): _temp_selector(),
    vol.Required(CONF_COOL_ON_TOLERANCE, default=DEFAULT_TOLERANCE): _temp_selector(),
    vol.Required(CONF_COOL_OFF_TOLERANCE, default=DEFAULT_TOLERANCE): _temp_selector(),
    # --- Auflösung ---
    vol.Required(CONF_RESOLUTION, default=DEFAULT_RESOLUTION): selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value=value, label=f"{value} °C")
                for value in RESOLUTIONS
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    ),
    # --- Laufzeiten / Startverzögerung (optional) ---
    vol.Optional(
        CONF_START_DELAY, default={"seconds": DEFAULT_START_DELAY}
    ): _duration_selector(),
    vol.Optional(CONF_MIN_DUR_HEAT): _duration_selector(),
    vol.Optional(CONF_MIN_DUR_COOL): _duration_selector(),
    vol.Optional(CONF_MAX_DUR): _duration_selector(),
    vol.Optional(CONF_KEEP_ALIVE): _duration_selector(),
    # --- Sollwert-Grenzen / Startwerte (optional) ---
    vol.Optional(CONF_MIN_TEMP): _temp_selector(),
    vol.Optional(CONF_MAX_TEMP): _temp_selector(),
    vol.Optional(CONF_TARGET_TEMP_HEAT): _temp_selector(),
    vol.Optional(CONF_TARGET_TEMP_COOL): _temp_selector(),
}

CONFIG_SCHEMA = {
    vol.Required(CONF_NAME): selector.TextSelector(),
    **OPTIONS_SCHEMA,
}


async def _validate(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate the user input."""
    # Heiz- und Kühlschalter müssen unterschiedlich sein.
    if user_input[CONF_HEATER] == user_input[CONF_COOLER]:
        raise SchemaFlowError("same_switch")

    # Mindestlaufzeit muss kleiner als die Höchstlaufzeit sein.
    if CONF_MAX_DUR in user_input:
        max_dur = timedelta(**user_input[CONF_MAX_DUR])
        for min_key in (CONF_MIN_DUR_HEAT, CONF_MIN_DUR_COOL):
            if min_key in user_input and timedelta(**user_input[min_key]) >= max_dur:
                raise SchemaFlowError("min_max_runtime")

    return user_input


CONFIG_FLOW = {
    "user": SchemaFlowFormStep(
        vol.Schema(CONFIG_SCHEMA),
        validate_user_input=_validate,
    ),
}

OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(
        vol.Schema(OPTIONS_SCHEMA),
        validate_user_input=_validate,
    ),
}


class ConfigFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    """Handle a config or options flow for Acalor Thermostat."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW
    options_flow_reloads = True

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title."""
        return cast(str, options[CONF_NAME])
