"""
Tests unitarios e integración de Épica 9 (Control Plane SSOT de Workstations: HU-33, HU-34, HU-35, HU-36).
Corre de forma autocontenida con una colección MongoDB en memoria (sin requerir Docker levantado).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.node_bridge import NodeBridgeManager


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, field, direction=1):
        self._docs.sort(key=lambda d: str(d.get(field) or ""), reverse=(direction < 0))
        return self

    def __aiter__(self):
        self._idx = 0
        return self

    async def __anext__(self):
        if self._idx >= len(self._docs):
            raise StopAsyncIteration
        item = self._docs[self._idx]
        self._idx += 1
        return item


class FakeWorkstationCollection:
    def __init__(self):
        self.rows = {}

    async def find_one(self, query):
        key = (query.get("user_id"), query.get("node_id"))
        doc = self.rows.get(key)
        return dict(doc) if doc else None

    async def update_one(self, query, update, upsert=False):
        key = (query.get("user_id"), query.get("node_id"))
        doc = dict(self.rows.get(key) or {})
        if not doc and not upsert:
            return
        if not doc and "$setOnInsert" in update:
            doc.update(update["$setOnInsert"])
        for k, v in (update.get("$set") or {}).items():
            if "." in k:
                head, tail = k.split(".", 1)
                doc.setdefault(head, {})[tail] = v
            else:
                doc[k] = v
        self.rows[key] = doc

    def find(self, query):
        out = []
        for doc in self.rows.values():
            if doc.get("user_id") != query.get("user_id"):
                continue
            rev_filter = query.get("revoked")
            if isinstance(rev_filter, dict) and "$ne" in rev_filter:
                if doc.get("revoked") == rev_filter["$ne"]:
                    continue
            out.append(dict(doc))
        return FakeCursor(out)


class FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code=1000):
        self.closed = True


@pytest.mark.asyncio
async def test_workstation_ssot_lifecycle_policy_killswitch_and_extensions():
    mgr = NodeBridgeManager()
    mgr.enable_builtin_host_node = False
    fake_col = FakeWorkstationCollection()
    mgr._get_ws_col = lambda: fake_col

    uid = "user-valeria-1"
    nid = "ws-pc-win-01"

    # 1. Registro persistente SSOT (HU-33) -> arranca en private_local_only
    dev = await mgr.register_device_record(
        uid,
        {
            "node_id": nid,
            "name": "PC-Valeria",
            "os": "windows",
            "arch": "x86_64",
            "shell": "powershell",
            "app_version": "1.4.0",
            "root_dir": "C:/Proyectos",
            "workspaces": [{"name": "InsanusChat", "path": "InsanusChat", "is_git": True}],
            "reported_editors": [{"id": "code", "name": "VS Code", "path": "code.cmd"}],
        },
    )
    assert dev["status"] == "private_local_only"
    assert dev["desired_policy"]["expose_to_cloud"] is False
    assert dev["config_version"] == 1

    # 2. Seguridad física (HU-34): imposible encender Control Remoto desde la web mientras está aislado
    with pytest.raises(PermissionError):
        await mgr.update_device_policy(uid, nid, {"expose_to_cloud": True}, from_device=False)

    # 3. Activación desde la app Desktop (from_device=True) incrementa config_version
    updated = await mgr.update_device_policy(
        uid,
        nid,
        {"expose_to_cloud": True, "allow_remote_agent_tools": False, "default_harness_mode": "auto_edit"},
        from_device=True,
    )
    assert updated["config_version"] == 2
    assert updated["desired_policy"]["allow_remote_agent_tools"] is False

    # 4. Conexión real del túnel WS + enforce de allow_remote_agent_tools=False
    ws = FakeWebSocket()
    sync_ack = await mgr.register_remote_ws(uid, nid, ws, {"name": "PC-Valeria", "os": "windows"})
    assert sync_ack["policy"]["allow_remote_agent_tools"] is False

    with pytest.raises(PermissionError):
        await mgr.execute_on_node(nid, "read_file", {"workspace": "InsanusChat", "path": "README.md"}, user_id=uid)

    # 5. Kill-Switch remoto desde Web/Móvil (from_device=False, expose_to_cloud=False SÍ permitido)
    killed = await mgr.update_device_policy(uid, nid, {"expose_to_cloud": False}, from_device=False)
    assert killed["config_version"] == 3
    assert killed["desired_policy"]["expose_to_cloud"] is False
    assert any(msg.get("cmd") == "policy_sync" and msg["policy"]["expose_to_cloud"] is False for msg in ws.sent)

    # 6. Sincronización de extensiones VS Code en MongoDB (HU-35)
    exts = await mgr.record_synced_extension(uid, nid, "install", ext_record={"id": "ms-python.python", "display_name": "Python"})
    assert len(exts) == 1
    assert exts[0]["id"] == "ms-python.python"

    # 7. Revocación total cierra WS y oculta equipo de list_nodes_for_user_ssot (HU-33, HU-34)
    rev = await mgr.revoke_device(uid, nid)
    assert rev["revoked"] is True
    assert ws.closed is True
    listed = await mgr.list_nodes_for_user_ssot(uid)
    assert listed == []
