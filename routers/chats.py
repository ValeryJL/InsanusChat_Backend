"""
Router de Chats (REST y WebSocket) con:
- Estandarización de `user_id` como ObjectId (HU-01)
- Creación de chat con `message` opcional + CRUD completo (`PATCH`, `DELETE` en cascada, `POST /unlock`) (HU-01)
- Protección anti-deadlock con TTL de 120s (HU-03)
- Autenticación WebSocket compatible con navegadores (`?token=...`, `Authorization` header, `Sec-WebSocket-Protocol`) (HU-04)
- Soporte de eventos de streaming token a token (`agent_stream_start`, `agent_token`, `agent_tool_start`, `agent_tool_end`) (HU-08)
"""
import asyncio
from datetime import datetime
from datetime import datetime as _dt
import json as _json
import logging
from typing import Any, Dict, List, Optional

import bson
from fastapi import APIRouter, Body, Header, HTTPException, Query, WebSocket, WebSocketDisconnect, status

import database
from models import ChatListResponse, ChatResponse, MessageResponse, MessagesResponse, PyObjectId, ResponseModel
from routers import auth
from services import messages as messages_service
from services.node_bridge import node_bridge

router = APIRouter(prefix="/api/v1/chats", tags=["Chats"])


def _user_id_query(uid: str) -> Dict[str, Any]:
    """Permite encontrar chats tanto si `user_id` se guardó como ObjectId como si se guardó como str."""
    try:
        oid = PyObjectId.parse(uid)
        return {"$in": [oid, str(uid)]}
    except Exception:
        return str(uid)


def _sanitize_chat_record(c: dict) -> dict:
    c = dict(c)
    c["_id"] = str(c["_id"])
    if c.get("user_id") is not None:
        c["user_id"] = str(c["user_id"])
    if c.get("agent_id") is not None:
        c["agent_id"] = str(c["agent_id"])
    if c.get("root_message_id") is not None:
        c["root_message_id"] = str(c["root_message_id"])
    if c.get("last_message_id") is not None:
        c["last_message_id"] = str(c["last_message_id"])
    # Reflejar el estado real del lock considerando el TTL de 120s (HU-03)
    c["locked"] = messages_service.is_chat_currently_locked(c)
    if c.get("locked_at") and hasattr(c["locked_at"], "isoformat"):
        c["locked_at"] = c["locked_at"].isoformat()
    if c.get("last_updated") and hasattr(c["last_updated"], "isoformat"):
        c["last_updated"] = c["last_updated"].isoformat()
    if c.get("created_at") and hasattr(c["created_at"], "isoformat"):
        c["created_at"] = c["created_at"].isoformat()
    if isinstance(c.get("active_tools"), list):
        c["active_tools"] = [str(t) for t in c["active_tools"]]
    c["execution_target"] = c.get("execution_target") or "cloud"
    c["node_id"] = c.get("node_id") or None
    c["workspace_path"] = c.get("workspace_path") or "."
    c["harness_mode"] = c.get("harness_mode") or "auto_edit"
    c["task_plan"] = c.get("task_plan") if isinstance(c.get("task_plan"), list) else []
    if c.get("messages") and isinstance(c.get("messages"), list):
        c["messages"] = [_sanitize_message_record(m) for m in c["messages"]]
    return c


def _sanitize_message_record(m: dict) -> dict:
    m = dict(m)
    for id_field in ("_id", "chat_id", "parent_id", "branch_anchor", "cousin_left", "cousin_right", "sender_id", "sender"):
        if m.get(id_field) is not None:
            m[id_field] = str(m[id_field])
    if isinstance(m.get("children_ids"), list):
        m["children_ids"] = [str(c) for c in m["children_ids"]]
    if isinstance(m.get("path"), list):
        m["path"] = [str(p) for p in m["path"]]
    for dt_field in ("created_at", "edited_at", "deleted_at"):
        if m.get(dt_field) is not None and hasattr(m[dt_field], "isoformat"):
            m[dt_field] = m[dt_field].isoformat()
    return m


def _sanitize_for_json(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, _dt):
        return v.isoformat()
    if isinstance(v, (PyObjectId, bson.ObjectId)):
        return str(v)
    if isinstance(v, dict):
        return {str(k): _sanitize_for_json(vv) for k, vv in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sanitize_for_json(x) for x in v]
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


@router.get("/", response_model=ChatListResponse)
async def list_chats(authorization: str = Header(..., alias="Authorization")):
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])

    chats_col = database.get_chat_collection()
    chats = []
    async for c in chats_col.find({"user_id": _user_id_query(uid)}).sort("last_updated", -1):
        chats.append(_sanitize_chat_record(c))
    return ChatListResponse(message="Chats listados", data=chats)


@router.post("/", response_model=ChatResponse)
async def create_chat(
    body: Dict[str, Any] = Body(
        default_factory=dict,
        examples={
            "with_message": {
                "summary": "Crear chat con mensaje inicial",
                "value": {"title": "Mi chat", "message": "Hola mundo", "agent_id": None},
            },
            "empty": {
                "summary": "Crear chat vacío",
                "value": {"title": "Nuevo Chat"},
            },
        },
    ),
    authorization: str = Header(..., alias="Authorization"),
):
    user = await auth.get_authenticated_user(authorization)
    user_oid = user["_id"]

    title = (body.get("title") or "").strip() or "New Chat"
    metadata = body.get("metadata") or {}
    message = body.get("message") or None
    now = datetime.utcnow()

    chats_col = database.get_chat_collection()
    raw_agent_id = body.get("agent_id")
    agent_obj = None
    if raw_agent_id:
        if not isinstance(raw_agent_id, str):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="agent_id must be a string if provided")
        try:
            agent_obj = PyObjectId.parse(raw_agent_id)
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="agent_id inválido")
    else:
        # Si el usuario tiene agentes y no especificó uno, vincular el agente activo por defecto
        user_agents = user.get("agents") or []
        default_ag = next((a for a in user_agents if a.get("active", True)), None)
        if default_ag and default_ag.get("_id"):
            agent_obj = default_ag["_id"]

    chat_doc = {
        "user_id": user_oid,
        "agent_id": agent_obj,
        "title": title,
        "metadata": metadata,
        "messages": [],
        "message_count": 0,
        "locked": False,
        "locked_at": None,
        "active_tools": [str(t) for t in (body.get("active_tools") or [])],
        "execution_target": body.get("execution_target") or "cloud",
        "node_id": body.get("node_id") or None,
        "workspace_path": body.get("workspace_path") or ".",
        "harness_mode": body.get("harness_mode") or "auto_edit",
        "task_plan": body.get("task_plan") if isinstance(body.get("task_plan"), list) else [],
        "created_at": now,
        "last_updated": now,
    }
    res = await chats_col.insert_one(chat_doc)
    chat_id = res.inserted_id
    chat_doc["_id"] = chat_id

    if message and isinstance(message, str) and message.strip():
        starter = {
            "_id": PyObjectId.new(),
            "chat_id": chat_id,
            "parent_id": None,
            "children_ids": [],
            "path": [],
            "branch_anchor": None,
            "cousin_left": None,
            "cousin_right": None,
            "sender_id": str(user_oid),
            "role": "user",
            "content": message.strip(),
            "content_type": "text",
            "status": "done",
            "tokens_used": None,
            "created_at": now,
        }
        await messages_service.process_user_message(chat_id, starter, manager=manager)

    return ChatResponse(message="Chat creado", data=_sanitize_chat_record(chat_doc))


@router.get("/{chat_id}", response_model=ChatResponse)
async def get_chat(chat_id: str, authorization: str = Header(..., alias="Authorization")):
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    try:
        chat_oid = PyObjectId.parse(chat_id)
    except Exception:
        raise HTTPException(status_code=400, detail="chat_id inválido")

    chats_col = database.get_chat_collection()
    chat = await chats_col.find_one({"_id": chat_oid, "user_id": _user_id_query(uid)})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return ChatResponse(message="Chat recuperado", data=_sanitize_chat_record(chat))


@router.patch("/{chat_id}", response_model=ChatResponse)
@router.put("/{chat_id}", response_model=ChatResponse)
async def update_chat(
    chat_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-01: Permite renombrar el chat, cambiar su agente activo o desbloquearlo."""
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    try:
        chat_oid = PyObjectId.parse(chat_id)
    except Exception:
        raise HTTPException(status_code=400, detail="chat_id inválido")

    chats_col = database.get_chat_collection()
    chat = await chats_col.find_one({"_id": chat_oid, "user_id": _user_id_query(uid)})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    update_ops: Dict[str, Any] = {"last_updated": datetime.utcnow()}
    if "title" in body and body["title"]:
        update_ops["title"] = str(body["title"]).strip()[:150]
    if "agent_id" in body:
        if body["agent_id"]:
            try:
                update_ops["agent_id"] = PyObjectId.parse(body["agent_id"])
            except Exception:
                raise HTTPException(status_code=400, detail="agent_id inválido")
        else:
            update_ops["agent_id"] = None
    if "model_selected" in body:
        update_ops["model_selected"] = str(body["model_selected"]).strip() if body["model_selected"] else None
    if "locked" in body and body["locked"] is False:
        update_ops["locked"] = False
        update_ops["locked_at"] = None
    if "metadata" in body and isinstance(body["metadata"], dict):
        update_ops["metadata"] = body["metadata"]
    if "execution_target" in body:
        update_ops["execution_target"] = str(body["execution_target"] or "cloud")
    if "node_id" in body:
        update_ops["node_id"] = str(body["node_id"]) if body["node_id"] else None
    if "workspace_path" in body:
        update_ops["workspace_path"] = str(body["workspace_path"] or ".")
    if "harness_mode" in body:
        update_ops["harness_mode"] = str(body["harness_mode"] or "auto_edit")
    if "task_plan" in body and isinstance(body["task_plan"], list):
        update_ops["task_plan"] = body["task_plan"]

    await chats_col.update_one({"_id": chat_oid}, {"$set": update_ops})
    updated = await chats_col.find_one({"_id": chat_oid})
    return ChatResponse(message="Chat actualizado", data=_sanitize_chat_record(updated))


@router.post("/{chat_id}/approve_tool", response_model=ResponseModel)
async def approve_or_reject_harness_tool(
    chat_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-22: Aprueba o rechaza una ejecución de herramienta del Harness en pausa (Human-in-the-Loop)."""
    await auth.get_authenticated_user(authorization)
    approval_id = str(body.get("approval_id") or "").strip()
    approved = bool(body.get("approved", True))
    feedback = str(body.get("feedback") or "")
    if not approval_id:
        raise HTTPException(status_code=400, detail="approval_id es obligatorio")

    resolved = node_bridge.resolve_tool_approval(chat_id, approval_id, approved, feedback)
    await manager.broadcast(
        str(chat_id),
        {
            "cmd": "agent_tool_approval_resolved",
            "message": {
                "approval_id": approval_id,
                "chat_id": str(chat_id),
                "approved": approved,
                "feedback": feedback,
            },
        },
    )
    return ResponseModel(
        message="Decisión de aprobación procesada",
        data={"resolved": resolved, "approval_id": approval_id, "approved": approved},
    )


@router.delete("/{chat_id}", response_model=ResponseModel)
async def delete_chat(chat_id: str, authorization: str = Header(..., alias="Authorization")):
    """HU-01: Elimina un chat del usuario y borra en cascada todos sus mensajes asociados."""
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    try:
        chat_oid = PyObjectId.parse(chat_id)
    except Exception:
        raise HTTPException(status_code=400, detail="chat_id inválido")

    chats_col = database.get_chat_collection()
    msgs_col = database.get_message_collection()

    chat = await chats_col.find_one({"_id": chat_oid, "user_id": _user_id_query(uid)})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    del_msgs = await msgs_col.delete_many({"chat_id": chat_oid})
    await chats_col.delete_one({"_id": chat_oid})

    return ResponseModel(
        message="Chat y mensajes eliminados",
        data={"chat_id": str(chat_oid), "deleted_messages": del_msgs.deleted_count},
    )


@router.post("/{chat_id}/unlock", response_model=ResponseModel)
async def unlock_chat(chat_id: str, authorization: str = Header(..., alias="Authorization")):
    """HU-03: Fuerza el desbloqueo inmediato de un chat y cancela cualquier tarea pendiente."""
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    try:
        chat_oid = PyObjectId.parse(chat_id)
    except Exception:
        raise HTTPException(status_code=400, detail="chat_id inválido")

    chats_col = database.get_chat_collection()
    chat = await chats_col.find_one({"_id": chat_oid, "user_id": _user_id_query(uid)})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    task = messages_service.ACTIVE_GENERATION_TASKS.get(str(chat_oid))
    if task and not task.done():
        task.cancel()
    await messages_service.release_chat_lock(chat_oid, manager=manager)

    return ResponseModel(message="Chat desbloqueado", data={"chat_id": str(chat_oid), "locked": False})


@router.get("/{chat_id}/messages", response_model=MessagesResponse)
async def list_messages(chat_id: str, authorization: str = Header(..., alias="Authorization")):
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    try:
        chat_oid = PyObjectId.parse(chat_id)
    except Exception:
        raise HTTPException(status_code=400, detail="chat_id inválido")

    chats_col = database.get_chat_collection()
    msgs_col = database.get_message_collection()
    chat = await chats_col.find_one({"_id": chat_oid, "user_id": _user_id_query(uid)})
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found or access denied")

    cursor = msgs_col.find({"chat_id": chat_oid}).sort("created_at", 1)
    msgs = []
    async for msg in cursor:
        sanitized = _sanitize_message_record(msg)
        msgs.append(_sanitize_for_json(sanitized))
    return MessagesResponse(message="Mensajes listados", data=msgs)


@router.post("/{chat_id}/messages", response_model=MessageResponse)
async def post_message(
    chat_id: str,
    body: Dict[str, Any] = Body(..., examples={"post": {"value": {"text": "Hola", "parent_id": "<message_id>"}}}),
    authorization: str = Header(..., alias="Authorization"),
):
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])

    text = body.get("text") or body.get("content")
    if not text or not isinstance(text, str):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text is required")

    try:
        chat_oid = PyObjectId.parse(chat_id)
    except Exception:
        raise HTTPException(status_code=400, detail="chat_id inválido")

    chats_col = database.get_chat_collection()
    msgs_col = database.get_message_collection()
    chat = await chats_col.find_one({"_id": chat_oid, "user_id": _user_id_query(uid)})
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found or access denied")

    if messages_service.is_chat_currently_locked(chat):
        raise HTTPException(status_code=423, detail="Chat is locked for processing")

    parent_raw = body.get("parent_id")
    parent_obj = None
    parent_id = None

    if parent_raw:
        if not isinstance(parent_raw, str):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="parent_id inválido")
        try:
            parent_id = PyObjectId.parse(parent_raw)
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="parent_id inválido")
        parent_obj = await msgs_col.find_one({"_id": parent_id, "chat_id": chat_oid})
        if parent_obj is None:
            existing_count = await msgs_col.count_documents({"chat_id": chat_oid})
            if existing_count == 0:
                parent_id = None
                parent_obj = None
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parent message not found")
        # Evitar enlaces Usuario -> Usuario: si el padre apuntado es de rol 'user', subir al mensaje de la IA superior
        if parent_obj and parent_obj.get("role") == "user":
            upper_id = parent_obj.get("parent_id")
            if upper_id:
                parent_id = upper_id
                parent_obj = await msgs_col.find_one({"_id": upper_id, "chat_id": chat_oid})
            else:
                parent_id = None
                parent_obj = None

    if parent_obj is None:
        branch_anchor = None
        cousin_left = None
        cousin_right = None
        msg_path = []
    else:
        if not parent_obj.get("children_ids"):
            branch_anchor = parent_obj.get("branch_anchor")
            cousin_left = parent_obj.get("cousin_left")
        else:
            branch_anchor = parent_id
            cousin_left = parent_obj["children_ids"][-1]
        cousin_right = parent_obj.get("cousin_right")
        msg_path = list(parent_obj.get("path", [])) + [parent_id]

    now = datetime.utcnow()
    user_msg = {
        "_id": PyObjectId.new(),
        "chat_id": chat_oid,
        "parent_id": parent_id,
        "children_ids": [],
        "path": msg_path,
        "branch_anchor": branch_anchor,
        "cousin_left": cousin_left,
        "cousin_right": cousin_right,
        "sender_id": uid,
        "role": "user",
        "content": text,
        "content_type": "text",
        "status": "done",
        "tokens_used": None,
        "created_at": now,
    }
    user_msg = await messages_service.process_user_message(chat_oid, user_msg, manager=manager)
    return MessageResponse(message="Mensaje publicado", data=_sanitize_message_record(user_msg))


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, chat_id: str, websocket: WebSocket):
        key = str(chat_id)
        try:
            await websocket.accept()
        except Exception:
            pass
        conns = self.active_connections.setdefault(key, [])
        if websocket not in conns:
            conns.append(websocket)

    def disconnect(self, chat_id: str, websocket: WebSocket):
        key = str(chat_id)
        conns = self.active_connections.get(key, [])
        if websocket in conns:
            conns.remove(websocket)
            if not conns:
                self.active_connections.pop(key, None)

    async def broadcast(self, chat_id: str, message: Dict[str, Any]):
        key = str(chat_id)
        conns = list(self.active_connections.get(key, []))
        if not conns:
            return

        safe_msg = _sanitize_for_json(message)

        if isinstance(message, dict) and message.get("cmd") and "message" in message:
            envelope = {"cmd": message.get("cmd"), "message": safe_msg.get("message")}
        else:
            role = safe_msg.get("role") if isinstance(safe_msg, dict) else None
            if role == "user":
                cmd = "user_message"
            elif role == "agent":
                cmd = "agent_message"
            elif role == "system":
                cmd = "system_message"
            elif role == "initializer":
                cmd = "initializer_message"
            else:
                cmd = "unknown_message"
            envelope = {"cmd": cmd, "message": safe_msg}

        json_text = _json.dumps(envelope, default=str, ensure_ascii=False)

        for ws in conns:
            send_ok = False
            for attempt in (1, 2):
                try:
                    await ws.send_text(json_text)
                    send_ok = True
                    break
                except Exception:
                    if attempt == 1:
                        await asyncio.sleep(0.03)
            if not send_ok:
                self.disconnect(chat_id, ws)


manager = ConnectionManager()


def _extract_ws_token(websocket: WebSocket) -> Optional[str]:
    """
    HU-04: Extrae el JWT desde:
    1) Query param `?token=<jwt>` (estándar para navegadores web `new WebSocket(url)`)
    2) Header `Authorization: Bearer <jwt>` (para clientes CLI / scripts)
    3) Header `Sec-WebSocket-Protocol: bearer, <jwt>`
    """
    qs_token = websocket.query_params.get("token")
    if qs_token:
        return qs_token.strip()

    auth_header = websocket.headers.get("authorization") or websocket.headers.get("Authorization")
    if auth_header:
        if auth_header.lower().startswith("bearer "):
            return auth_header.split(" ", 1)[1].strip()
        return auth_header.strip()

    proto = websocket.headers.get("sec-websocket-protocol")
    if proto:
        parts = [p.strip() for p in proto.split(",")]
        for p in parts:
            if p.lower() != "bearer" and len(p) > 20:
                return p

    return None


@router.websocket("/ws")
async def websocket_root(websocket: WebSocket):
    await _websocket_unified_impl(websocket, None)


@router.websocket("/ws/{chat_id_path}")
async def websocket_with_chat_id(websocket: WebSocket, chat_id_path: str):
    await _websocket_unified_impl(websocket, chat_id_path)


async def _websocket_unified_impl(websocket: WebSocket, chat_id_path: Optional[str] = None):
    """
    Manejador unificado para WebSocket (`/api/v1/chats/ws` y `/api/v1/chats/ws/{chat_id}`):
    Soporta autenticación por `?token=...` o header `Authorization: Bearer ...`.
    """
    await websocket.accept()
    token = _extract_ws_token(websocket)
    if not token:
        try:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except Exception:
            pass
        return

    try:
        decoded = auth.authenticate_token(token)
        uid = decoded.get("uid") or decoded.get("user_id")
    except Exception:
        uid = None

    if not uid:
        try:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except Exception:
            pass
        return

    chat_id_qs = chat_id_path or websocket.query_params.get("chat_id")
    if chat_id_qs:
        try:
            chat_oid = PyObjectId.parse(chat_id_qs)
        except Exception:
            try:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            except Exception:
                pass
            return

        chats_col = database.get_chat_collection()
        chat = await chats_col.find_one({"_id": chat_oid, "user_id": _user_id_query(uid)})
        if chat is None:
            try:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            except Exception:
                pass
            return

        await manager.connect(str(chat_oid), websocket)
        try:
            msgs_col = database.get_message_collection()
            last = await msgs_col.find_one({"chat_id": chat_oid, "role": {"$ne": "user"}}, sort=[("created_at", -1)])
            if not last:
                last = await msgs_col.find_one({"chat_id": chat_oid}, sort=[("created_at", -1)])

            init_payload = {
                "init": {
                    "chat": [],
                    "branch_anchor": None,
                    "last_message_id": None,
                    "locked": messages_service.is_chat_currently_locked(chat),
                }
            }
            if last:
                chat_history = await messages_service.build_history_from_message_bottom(last.get("_id"), limit=500)
                init_payload = {
                    "init": {
                        "chat": chat_history,
                        "branch_anchor": str(last.get("branch_anchor") or last.get("_id")),
                        "last_message_id": str(last.get("_id")),
                        "locked": messages_service.is_chat_currently_locked(chat),
                        "note": "history of the last used thread",
                    }
                }
            await websocket.send_text(_json.dumps(_sanitize_for_json(init_payload), ensure_ascii=False))
            await messages_service.websocket_handler(websocket, chat_oid, uid, manager)
        except WebSocketDisconnect:
            manager.disconnect(str(chat_oid), websocket)
        except Exception:
            logging.exception("websocket: error en sesión chat_id=%s", str(chat_oid))
            manager.disconnect(str(chat_oid), websocket)
        finally:
            manager.disconnect(str(chat_oid), websocket)
            try:
                await websocket.close()
            except Exception:
                pass
        return

    # Crear nuevo chat vía WebSocket
    try:
        payload = await websocket.receive_json()
    except Exception:
        try:
            await websocket.send_json({"error": "invalid or missing JSON payload"})
            await websocket.close(code=status.WS_1002_PROTOCOL_ERROR)
        except Exception:
            pass
        return

    message = payload.get("message") or None
    if not message or not isinstance(message, str):
        try:
            await websocket.send_json({"error": "message is required and must be a string"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except Exception:
            pass
        return

    title = payload.get("title") or "New Chat"
    metadata = payload.get("metadata") or {}
    raw_agent_id = payload.get("agent_id")
    agent_obj = None
    if raw_agent_id is not None:
        try:
            agent_obj = PyObjectId.parse(raw_agent_id)
        except Exception:
            try:
                await websocket.send_json({"error": "invalid agent_id"})
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            except Exception:
                pass
            return

    now = datetime.utcnow()
    user_oid = PyObjectId.parse(uid)
    chats_col = database.get_chat_collection()
    chat_doc = {
        "user_id": user_oid,
        "agent_id": agent_obj,
        "title": title,
        "metadata": metadata,
        "messages": [],
        "message_count": 0,
        "locked": False,
        "locked_at": None,
        "created_at": now,
        "last_updated": now,
    }

    res = await chats_col.insert_one(chat_doc)
    chat_id = res.inserted_id
    chat_doc["_id"] = chat_id

    starter = {
        "_id": PyObjectId.new(),
        "chat_id": chat_id,
        "parent_id": None,
        "children_ids": [],
        "path": [],
        "branch_anchor": None,
        "cousin_left": None,
        "cousin_right": None,
        "sender_id": str(uid),
        "role": "user",
        "content": message,
        "content_type": "text",
        "status": "done",
        "tokens_used": None,
        "created_at": now,
    }

    await websocket.send_json({"chat": _sanitize_chat_record(chat_doc)})
    await manager.connect(str(chat_id), websocket)
    await messages_service.process_user_message(chat_id, starter, manager=manager)

    try:
        await messages_service.websocket_handler(websocket, chat_id, uid, manager)
    except WebSocketDisconnect:
        manager.disconnect(str(chat_id), websocket)
    finally:
        manager.disconnect(str(chat_id), websocket)
        try:
            await websocket.close()
        except Exception:
            pass
