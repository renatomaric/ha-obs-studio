"""Config flow and entity tests with a fake OBS client."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obs_studio.client import OBSAuthError
from custom_components.obs_studio.const import DOMAIN

DATA = {CONF_HOST: "192.168.0.25", CONF_PORT: 4455, CONF_PASSWORD: "secret"}

SCENES = {
    "currentProgramSceneName": "Kamera",
    "scenes": [
        {"sceneName": "Pauza", "sceneIndex": 0},
        {"sceneName": "Kamera", "sceneIndex": 1},
    ],
}
ITEMS = {
    "Kamera": [
        {"sceneItemId": 1, "sourceName": "Webcam", "sceneItemEnabled": True, "sceneItemIndex": 0},
        {"sceneItemId": 2, "sourceName": "Logo", "sceneItemEnabled": False, "sceneItemIndex": 1},
    ],
    "Pauza": [],
}


class FakeClient:
    instances: list["FakeClient"] = []
    fail_auth = False

    def __init__(self, session, host, port, password, on_event=None, on_disconnect=None):
        self.on_event = on_event
        self.calls: list[tuple[str, dict | None]] = []
        FakeClient.instances.append(self)

    async def connect(self):
        if FakeClient.fail_auth:
            raise OBSAuthError("bad")

    async def disconnect(self):
        pass

    async def call(self, request_type, data=None):
        self.calls.append((request_type, data))
        if request_type == "GetVersion":
            return {"platformDescription": "macOS"}
        if request_type == "GetSceneList":
            return SCENES
        if request_type == "GetSceneItemList":
            return {"sceneItems": ITEMS[data["sceneName"]]}
        return {}


@pytest.fixture(autouse=True)
def fake_client():
    FakeClient.instances = []
    FakeClient.fail_auth = False
    with (
        patch("custom_components.obs_studio.config_flow.OBSClient", FakeClient),
        patch("custom_components.obs_studio.coordinator.OBSClient", FakeClient),
    ):
        yield


async def test_config_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATA)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "OBS"
    assert result["data"] == DATA


async def test_config_flow_wrong_password(hass: HomeAssistant) -> None:
    FakeClient.fail_auth = True
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATA)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def setup_entry(hass: HomeAssistant) -> FakeClient:
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, title="OBS")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return FakeClient.instances[-1]


async def test_scene_select(hass: HomeAssistant) -> None:
    client = await setup_entry(hass)

    state = hass.states.get("select.obs_scene")
    assert state.state == "Kamera"
    assert state.attributes["options"] == ["Kamera", "Pauza"]

    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.obs_scene", "option": "Pauza"}, blocking=True
    )
    assert ("SetCurrentProgramScene", {"sceneName": "Pauza"}) in client.calls

    client.on_event("CurrentProgramSceneChanged", {"sceneName": "Pauza"})
    await hass.async_block_till_done()
    assert hass.states.get("select.obs_scene").state == "Pauza"


async def test_source_switches(hass: HomeAssistant) -> None:
    client = await setup_entry(hass)

    assert hass.states.get("switch.obs_kamera_webcam").state == "on"
    assert hass.states.get("switch.obs_kamera_logo").state == "off"

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.obs_kamera_logo"}, blocking=True
    )
    assert (
        "SetSceneItemEnabled",
        {"sceneName": "Kamera", "sceneItemId": 2, "sceneItemEnabled": True},
    ) in client.calls

    client.on_event(
        "SceneItemEnableStateChanged",
        {"sceneName": "Kamera", "sceneItemId": 2, "sceneItemEnabled": True},
    )
    await hass.async_block_till_done()
    assert hass.states.get("switch.obs_kamera_logo").state == "on"


async def test_new_source_adds_switch(hass: HomeAssistant) -> None:
    client = await setup_entry(hass)

    ITEMS["Pauza"] = [
        {"sceneItemId": 5, "sourceName": "Slika", "sceneItemEnabled": True, "sceneItemIndex": 0}
    ]
    try:
        client.on_event("SceneItemCreated", {"sceneName": "Pauza"})
        await hass.async_block_till_done()
        assert hass.states.get("switch.obs_pauza_slika").state == "on"
    finally:
        ITEMS["Pauza"] = []
