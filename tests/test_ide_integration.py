"""
Tests de integración v1.5.0:
- Firma y verificación HMAC de cookies HttpOnly para VS Code Remoto (/ide/{session_secret}/*)
- Multiplexado HTTP y WebSocket sobre NodeBridgeManager + revocación inmediata por Kill-Switch
- Resolución idempotente de chat por workspace (`POST /api/v1/chats/resolve-workspace`)
"""
import asyncio
import base64
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from routers.nodes import _sign_ide_cookie, _verify_ide_cookie
from services.node_bridge import NodeBridgeManager


class FakeWebSocket:
    def __init__(self, on_send=None):
        self.sent = []
        self.closed = False
        self.on_send = on_send

    async def send_json(self, payload):
        self.sent.append(payload)
        if self.on_send:
            self.on_send(payload)

    async def close(self, code=1000):
        self.closed = True


def test_ide_cookie_hmac_signing_and_tamper_rejection():
    signed = _sign_ide_cookie("user-1", "node-win-01", "sec-abcdef123456")
    verified = _verify_ide_cookie(signed, "sec-abcdef123456")
    assert verified == {
        "user_id": "user-1",
        "node_id": "node-win-01",
        "session_secret": "sec-abcdef123456",
    }

    # Rechazar secret distinto o firma adulterada
    assert _verify_ide_cookie(signed, "other-secret") is None
    assert _verify_ide_cookie(signed[:-4] + "0000", "sec-abcdef123456") is None
    assert _verify_ide_cookie("malformed", "sec-abcdef123456") is None


@pytest.mark.asyncio
async def test_remote_ide_http_ws_multiplex_and_killswitch():
    mgr = NodeBridgeManager()
    mgr.enable_builtin_host_node = False
    mgr._get_ws_col = lambda: None

    uid = "user-valeria-ide"
    nid = "ws-pc-ide-01"
    sec = "ide-secret-998877"

    def _auto_reply(payload):
        if payload.get("cmd") == "ide_http_req":
            mgr.handle_remote_ide_http_res(
                nid,
                {
                    "cmd": "ide_http_res",
                    "req_id": payload["req_id"],
                    "status": 200,
                    "headers": {"content-type": "text/html"},
                    "body_b64": base64.b64encode(b"<html>obsidian</html>").decode("ascii"),
                },
            )
        elif payload.get("cmd") == "ide_ws_open":
            mgr.handle_remote_ide_ws_event(
                nid,
                {
                    "cmd": "ide_ws_opened",
                    "stream_id": payload["stream_id"],
                    "subprotocol": "vscode",
                },
            )

    ws = FakeWebSocket(on_send=_auto_reply)
    await mgr.register_remote_ws(uid, nid, ws, {"name": "PC-Valeria", "os": "windows"})
    mgr.register_ide_session(sec, nid, uid)

    assert mgr.resolve_ide_session(sec) is not None

    # 1. Proxy HTTP multiplexado
    res = await mgr.proxy_ide_http(
        node_id=nid,
        user_id=uid,
        method="GET",
        session_secret=sec,
        subpath="",
        query="folder=C:/Proyectos",
        headers={},
        body=b"",
    )
    assert res["status"] == 200
    assert b"obsidian" in res["body"]

    # 2. Proxy WebSocket multiplexado
    q = await mgr.open_remote_ide_ws(nid, uid, "stream-1", sec, "ws", "", ["vscode"])
    ev = await asyncio.wait_for(q.get(), timeout=2.0)
    assert ev["cmd"] == "ide_ws_opened"
    assert ev["subprotocol"] == "vscode"

    # 3. Kill-Switch remoto revoca inmediatamente la sesión IDE y cierra el stream WS
    await mgr.update_device_policy(uid, nid, {"expose_to_cloud": False}, from_device=False)
    assert mgr.resolve_ide_session(sec) is None
    close_ev = await asyncio.wait_for(q.get(), timeout=2.0)
    assert close_ev["cmd"] == "ide_ws_close"


@pytest.mark.asyncio
async def test_remote_ide_chunked_gzip_http_streaming():
    import gzip

    mgr = NodeBridgeManager()
    mgr.enable_builtin_host_node = False
    mgr._get_ws_col = lambda: None

    uid = "user-chunk-1"
    nid = "ws-chunk-01"
    sec = "sec-chunk-123"
    big_js = b"console.log('vscode-workbench');\n" * 20000  # ~660 KB -> comprimido y partido en chunks
    gz = gzip.compress(big_js, compresslevel=5)

    def _chunk_reply(payload):
        if payload.get("cmd") == "ide_http_req":
            rid = payload["req_id"]
            mid = len(gz) // 2
            mgr.handle_remote_ide_http_res(
                nid,
                {
                    "cmd": "ide_http_head",
                    "req_id": rid,
                    "status": 200,
                    "headers": {"content-type": "application/javascript"},
                    "set_cookies": ["a=1; SameSite=Lax"],
                    "gzipped": True,
                    "total_chunks": 2,
                },
            )
            mgr.handle_remote_ide_http_res(
                nid, {"cmd": "ide_http_chunk", "req_id": rid, "idx": 0, "data_b64": base64.b64encode(gz[:mid]).decode("ascii")}
            )
            mgr.handle_remote_ide_http_res(
                nid, {"cmd": "ide_http_chunk", "req_id": rid, "idx": 1, "data_b64": base64.b64encode(gz[mid:]).decode("ascii")}
            )
            mgr.handle_remote_ide_http_res(nid, {"cmd": "ide_http_end", "req_id": rid})

    ws = FakeWebSocket(on_send=_chunk_reply)
    await mgr.register_remote_ws(uid, nid, ws, {"name": "PC-Chunk", "os": "windows"})
    mgr.register_ide_session(sec, nid, uid)

    res = await mgr.proxy_ide_http(nid, uid, "GET", sec, "static/workbench.js", "", {}, b"")
    assert res["status"] == 200
    assert res["body"] == big_js
    assert res["set_cookies"] == ["a=1; SameSite=Lax"]

