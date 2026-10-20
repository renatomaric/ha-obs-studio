from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import OBSConfigEntry, OBSCoordinator, SceneItem
from .entity import OBSEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OBSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    known: set[tuple[str, int]] = set()

    @callback
    def add_new_items() -> None:
        if coordinator.data is None:
            return
        new = [
            OBSSourceSwitch(coordinator, scene, item.id)
            for scene, items in coordinator.data.items.items()
            for item in items
            if (scene, item.id) not in known
        ]
        known.update((e.scene, e.item_id) for e in new)
        if new:
            async_add_entities(new)

    add_new_items()
    entry.async_on_unload(coordinator.async_add_listener(add_new_items))


class OBSSourceSwitch(OBSEntity, SwitchEntity):
    """Visibility of one source inside one scene (the eye icon in OBS)."""

    def __init__(self, coordinator: OBSCoordinator, scene: str, item_id: int) -> None:
        super().__init__(coordinator)
        self.scene = scene
        self.item_id = item_id
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{scene}_{item_id}"

    @property
    def _item(self) -> SceneItem | None:
        for item in self.coordinator.data.items.get(self.scene, []):
            if item.id == self.item_id:
                return item
        return None

    @property
    def name(self) -> str:
        item = self._item
        return f"{self.scene} / {item.source if item else self.item_id}"

    @property
    def available(self) -> bool:
        return super().available and self._item is not None

    @property
    def is_on(self) -> bool | None:
        item = self._item
        return item.enabled if item else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.set_item_enabled(self.scene, self.item_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_item_enabled(self.scene, self.item_id, False)
