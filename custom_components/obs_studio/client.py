"""Minimal obs-websocket v5 client (no Home Assistant imports, so it can be tested on its own)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import uuid
from collections.abc import Callable
from typing import Any

import aiohttp

OP_HELLO = 0
OP_IDENTIFY = 1
OP_IDENTIFIED = 2
OP_EVENT = 5
OP_REQUEST = 6
OP_REQUEST_RESPONSE = 7

# Scenes | Inputs | SceneItems
EVENT_SUBSCRIPTIONS = (1 << 2) | (1 << 3) | (1 << 7)

CLOSE_AUTHENTICATION_FAILED = 4009

REQUEST_TIMEOUT = 10


class OBSError(Exception):
    """Base error."""


class OBSConnectionError(OBSError):
    """OBS is unreachable or the connection dropped."""


class OBSAuthError(OBSError):
    """Wrong or missing password."""


class OBSRequestError(OBSError):
    """OBS answered a request with a failure status."""


def auth_response(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


class OBSClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        password: str | None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
    ) -> None:
        self._session = session
        self._url = f"ws://{host}:{port}"
        self._password = password or ""
        self._on_event = on_event
        self._on_disconnect = on_disconnect
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reader: asyncio.Task | None = None
        self._pending: dict[str, asyncio.Future] = {}

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    async def connect(self) -> None:
        try:
            self._ws = await self._session.ws_connect(
                self._url,
                protocols=("obswebsocket.json",),
                heartbeat=30,
                timeout=aiohttp.ClientWSTimeout(ws_close=REQUEST_TIMEOUT),
            )
            hello = await self._receive(OP_HELLO)
            identify: dict[str, Any] = {
                "rpcVersion": 1,
                "eventSubscriptions": EVENT_SUBSCRIPTIONS,
            }
            if auth := hello.get("authentication"):
                if not self._password:
                    raise OBSAuthError("OBS requires a password")
                identify["authentication"] = auth_response(
                    self._password, auth["salt"], auth["challenge"]
                )
            await self._ws.send_json({"op": OP_IDENTIFY, "d": identify})
            await self._receive(OP_IDENTIFIED)
        except OBSError:
            await self._close_ws()
            raise
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            await self._close_ws()
            raise OBSConnectionError(str(err)) from err

        self._reader = asyncio.create_task(self._read_loop())

    async def disconnect(self) -> None:
        self._on_disconnect = None
        if self._reader:
            self._reader.cancel()
            self._reader = None
        await self._close_ws()
        self._fail_pending()

    async def call(self, request_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.connected:
            raise OBSConnectionError("Not connected")

        request_id = uuid.uuid4().hex
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        payload: dict[str, Any] = {"requestType": request_type, "requestId": request_id}
        if data:
            payload["requestData"] = data

        try:
            await self._ws.send_json({"op": OP_REQUEST, "d": payload})
            response = await asyncio.wait_for(future, REQUEST_TIMEOUT)
        except TimeoutError as err:
            raise OBSConnectionError(f"{request_type} timed out") from err
        finally:
            self._pending.pop(request_id, None)

        status = response["requestStatus"]
        if not status["result"]:
            raise OBSRequestError(
                f"{request_type} failed ({status['code']}): {status.get('comment', '')}"
            )
        return response.get("responseData") or {}

    async def _receive(self, expected_op: int) -> dict[str, Any]:
        msg = await self._ws.receive(timeout=REQUEST_TIMEOUT)
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = msg.json()
            if data["op"] != expected_op:
                raise OBSConnectionError(f"Expected op {expected_op}, got {data['op']}")
            return data["d"]
        if self._ws.close_code == CLOSE_AUTHENTICATION_FAILED:
            raise OBSAuthError("Authentication failed")
        raise OBSConnectionError(f"Connection closed during handshake ({self._ws.close_code})")

    async def _read_loop(self) -> None:
        try:
            async for msg in self._ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                data = msg.json()
                if data["op"] == OP_REQUEST_RESPONSE:
                    future = self._pending.get(data["d"]["requestId"])
                    if future and not future.done():
                        future.set_result(data["d"])
                elif data["op"] == OP_EVENT and self._on_event:
                    self._on_event(data["d"]["eventType"], data["d"].get("eventData") or {})
        finally:
            self._fail_pending()
            if self._on_disconnect:
                self._on_disconnect()

    def _fail_pending(self) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(OBSConnectionError("Connection lost"))
        self._pending.clear()

    async def _close_ws(self) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
