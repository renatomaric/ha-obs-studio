"""OBS Studio integration: switch scenes and toggle sources over obs-websocket v5."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import OBSConfigEntry, OBSCoordinator

PLATFORMS = [Platform.SELECT, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: OBSConfigEntry) -> bool:
    coordinator = OBSCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await coordinator.client.disconnect()
        raise

    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.async_shutdown)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OBSConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
