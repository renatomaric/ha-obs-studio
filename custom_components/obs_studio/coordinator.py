"""Keeps OBS scene state in sync over the websocket and reconnects when OBS goes away."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import OBSClient, OBSError
from .const import DOMAIN, RECONNECT_INTERVAL

_LOGGER = logging.getLogger(__name__)

# Events that change the scene/source structure, so the whole state is fetched again.
STRUCTURE_EVENTS = {
    "SceneCreated",
    "SceneRemoved",
    "SceneNameChanged",
    "SceneListChanged",
    "SceneItemCreated",
    "SceneItemRemoved",
    "SceneItemListReindexed",
    "InputNameChanged",
}


@dataclass
class SceneItem:
    id: int
    source: str
    enabled: bool


@dataclass
class OBSState:
    current_scene: str | None = None
    scenes: list[str] = field(default_factory=list)
    items: dict[str, list[SceneItem]] = field(default_factory=dict)


type OBSConfigEntry = ConfigEntry[OBSCoordinator]


class OBSCoordinator(DataUpdateCoordinator[OBSState]):
    config_entry: OBSConfigEntry

    def __init__(self, hass: HomeAssistant, entry: OBSConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN)
        self.client = OBSClient(
            async_get_clientsession(hass),
            entry.data[CONF_HOST],
            entry.data[CONF_PORT],
            entry.data.get(CONF_PASSWORD),
            on_event=self._handle_event,
            on_disconnect=self._handle_disconnect,
        )
        self._reconnect_task: asyncio.Task | None = None
        self._refresh_task: asyncio.Task | None = None

    async def _async_setup(self) -> None:
        try:
            await self.client.connect()
        except OBSError as err:
            raise UpdateFailed(f"Cannot connect to OBS: {err}") from err

    async def _async_update_data(self) -> OBSState:
        try:
            return await self._fetch_state()
        except OBSError as err:
            raise UpdateFailed(str(err)) from err

    async def async_shutdown(self) -> None:
        for task in (self._reconnect_task, self._refresh_task):
            if task:
                task.cancel()
        await self.client.disconnect()
        await super().async_shutdown()

    async def set_scene(self, scene: str) -> None:
        await self.client.call("SetCurrentProgramScene", {"sceneName": scene})

    async def set_item_enabled(self, scene: str, item_id: int, enabled: bool) -> None:
        await self.client.call(
            "SetSceneItemEnabled",
            {"sceneName": scene, "sceneItemId": item_id, "sceneItemEnabled": enabled},
        )

    async def _fetch_state(self) -> OBSState:
        scene_list = await self.client.call("GetSceneList")
        # OBS returns scenes bottom-up; reverse so the order matches the OBS UI.
        scenes = [
            s["sceneName"]
            for s in sorted(scene_list["scenes"], key=lambda s: s["sceneIndex"], reverse=True)
        ]
        items: dict[str, list[SceneItem]] = {}
        for scene in scenes:
            result = await self.client.call("GetSceneItemList", {"sceneName": scene})
            items[scene] = [
                SceneItem(i["sceneItemId"], i["sourceName"], i["sceneItemEnabled"])
                for i in sorted(result["sceneItems"], key=lambda i: i["sceneItemIndex"], reverse=True)
            ]
        return OBSState(scene_list["currentProgramSceneName"], scenes, items)

    @callback
    def _handle_event(self, event_type: str, data: dict[str, Any]) -> None:
        if self.data is None:
            return

        if event_type == "CurrentProgramSceneChanged":
            self.data.current_scene = data["sceneName"]
            self.async_set_updated_data(self.data)
        elif event_type == "SceneItemEnableStateChanged":
            for item in self.data.items.get(data["sceneName"], []):
                if item.id == data["sceneItemId"]:
                    item.enabled = data["sceneItemEnabled"]
            self.async_set_updated_data(self.data)
        elif event_type in STRUCTURE_EVENTS and (
            self._refresh_task is None or self._refresh_task.done()
        ):
            self._refresh_task = self.config_entry.async_create_background_task(
                self.hass, self.async_request_refresh(), "obs_studio_refresh"
            )

    @callback
    def _handle_disconnect(self) -> None:
        _LOGGER.warning("Lost connection to OBS, reconnecting every %s s", RECONNECT_INTERVAL)
        self.async_set_update_error(UpdateFailed("Disconnected from OBS"))
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = self.config_entry.async_create_background_task(
                self.hass, self._reconnect(), "obs_studio_reconnect"
            )

    async def _reconnect(self) -> None:
        while True:
            await asyncio.sleep(RECONNECT_INTERVAL)
            try:
                await self.client.connect()
            except OBSError as err:
                _LOGGER.debug("Reconnect to OBS failed: %s", err)
                continue
            _LOGGER.info("Reconnected to OBS")
            await self.async_refresh()
            return
