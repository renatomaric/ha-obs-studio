from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OBSCoordinator


class OBSEntity(CoordinatorEntity[OBSCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: OBSCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="OBS Project",
            model="OBS Studio",
        )
