from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import OBSConfigEntry, OBSCoordinator
from .entity import OBSEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OBSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([OBSSceneSelect(entry.runtime_data)])


class OBSSceneSelect(OBSEntity, SelectEntity):
    _attr_translation_key = "scene"

    def __init__(self, coordinator: OBSCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_scene"

    @property
    def options(self) -> list[str]:
        return self.coordinator.data.scenes

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.current_scene

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.set_scene(option)
