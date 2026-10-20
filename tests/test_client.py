"""Tests for the obs-websocket client against a fake OBS server."""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web

spec = importlib.util.spec_from_file_location(
    "obs_client", Path(__file__).parents[1] / "custom_components/obs_studio/client.py"
)
client_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client_module)

OBSClient = client_module.OBSClient
OBSAuthError = client_module.OBSAuthError
OBSRequestError = client_module.OBSRequestError
auth_response = client_module.auth_response

PASSWORD = "secret"
SALT = "lM1GncleQOaCu9lT1yeUZhFYnqhsLLP1G5lAGo3ixaI="
CHALLENGE = "+IxH4CnCiqpX1rM9scsNynZzbOe4KhDeYcTNS3PDaeY="


class FakeOBS:
    def __init__(self, password: str | None = PASSWORD) -> None:
        self.password = password
        self.requests: list[dict] = []
        self.ws: web.WebSocketResponse | None = None

    async def handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(protocols=("obswebsocket.json",))
        await ws.prepare(request)
        self.ws = ws
        hello = {"obsWebSocketVersion": "5.7.4", "rpcVersion": 1}
        if self.password:
            hello["authentication"] = {"salt": SALT, "challenge": CHALLENGE}
        await ws.send_json({"op": 0, "d": hello})

        identify = await ws.receive_json()
        if self.password and identify["d"].get("authentication") != auth_response(
            self.password, SALT, CHALLENGE
        ):
            await ws.close(code=4009)
            return ws
        await ws.send_json({"op": 2, "d": {"negotiatedRpcVersion": 1}})

        async for msg in ws:
            data = msg.json()["d"]
            self.requests.append(data)
            ok = data["requestType"] != "Broken"
            await ws.send_json(
                {
                    "op": 7,
                    "d": {
                        "requestType": data["requestType"],
                        "requestId": data["requestId"],
                        "requestStatus": {"result": ok, "code": 100 if ok else 600},
                        "responseData": {"echo": data.get("requestData")},
                    },
                }
            )
        return ws


@pytest.fixture
async def server():
    async def start(fake: FakeOBS):
        app = web.Application()
        app.router.add_get("/", fake.handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        runners.append(runner)
        return site._server.sockets[0].getsockname()[1]

    runners: list[web.AppRunner] = []
    yield start
    for runner in runners:
        await runner.cleanup()


async def test_auth_and_request(server):
    fake = FakeOBS()
    port = await server(fake)
    async with aiohttp.ClientSession() as session:
        client = OBSClient(session, "127.0.0.1", port, PASSWORD)
        await client.connect()
        result = await client.call("SetCurrentProgramScene", {"sceneName": "Kamera"})
        await client.disconnect()

    assert result == {"echo": {"sceneName": "Kamera"}}
    assert fake.requests[0]["requestType"] == "SetCurrentProgramScene"


async def test_wrong_password(server):
    port = await server(FakeOBS())
    async with aiohttp.ClientSession() as session:
        client = OBSClient(session, "127.0.0.1", port, "wrong")
        with pytest.raises(OBSAuthError):
            await client.connect()


async def test_missing_password(server):
    port = await server(FakeOBS())
    async with aiohttp.ClientSession() as session:
        client = OBSClient(session, "127.0.0.1", port, None)
        with pytest.raises(OBSAuthError):
            await client.connect()


async def test_no_auth_server(server):
    port = await server(FakeOBS(password=None))
    async with aiohttp.ClientSession() as session:
        client = OBSClient(session, "127.0.0.1", port, None)
        await client.connect()
        assert await client.call("GetVersion") == {"echo": None}
        await client.disconnect()


async def test_failed_request_raises(server):
    port = await server(FakeOBS())
    async with aiohttp.ClientSession() as session:
        client = OBSClient(session, "127.0.0.1", port, PASSWORD)
        await client.connect()
        with pytest.raises(OBSRequestError):
            await client.call("Broken")
        await client.disconnect()


async def test_events_and_disconnect_callback(server):
    fake = FakeOBS()
    port = await server(fake)
    events: list[tuple[str, dict]] = []
    disconnected = asyncio.Event()
    async with aiohttp.ClientSession() as session:
        client = OBSClient(
            session,
            "127.0.0.1",
            port,
            PASSWORD,
            on_event=lambda t, d: events.append((t, d)),
            on_disconnect=disconnected.set,
        )
        await client.connect()
        await fake.ws.send_json(
            {
                "op": 5,
                "d": {"eventType": "CurrentProgramSceneChanged", "eventData": {"sceneName": "B"}},
            }
        )
        await fake.ws.close()
        await asyncio.wait_for(disconnected.wait(), 5)

    assert events == [("CurrentProgramSceneChanged", {"sceneName": "B"})]
    assert not client.connected
