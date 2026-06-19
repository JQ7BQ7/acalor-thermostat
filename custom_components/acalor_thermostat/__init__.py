"""The Acalor Thermostat integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_entity_registry_updated_event

from .const import CONF_COOLER, CONF_HEATER, CONF_SENSOR, PLATFORMS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Acalor Thermostat from a config entry."""

    def _track_source_entity(option_key: str) -> None:
        """Keep the config entry in sync if a referenced entity is renamed."""
        entity_id = entry.options.get(option_key)
        if not entity_id:
            return

        @callback
        def _entity_registry_updated(
            event: Event[er.EventEntityRegistryUpdatedData],
        ) -> None:
            data = event.data
            if data["action"] != "update" or "entity_id" not in data["changes"]:
                return
            hass.config_entries.async_update_entry(
                entry,
                options={**entry.options, option_key: data["entity_id"]},
            )
            hass.config_entries.async_schedule_reload(entry.entry_id)

        entry.async_on_unload(
            async_track_entity_registry_updated_event(
                hass, entity_id, _entity_registry_updated
            )
        )

    for key in (CONF_SENSOR, CONF_HEATER, CONF_COOLER):
        _track_source_entity(key)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
