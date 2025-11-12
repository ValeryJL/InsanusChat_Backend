from fastapi import APIRouter, HTTPException, Header, Query
from fastapi import WebSocket, WebSocketDisconnect, status, Body
from typing import List, Optional, Dict, Any
from datetime import datetime
import asyncio
import logging
import database
from models import PyObjectId, ResponseModel, ChatListResponse, ChatResponse, MessagesResponse, MessageResponse
from routers import auth
from services import agents as agents_service
from services import messages as messages_service
import json as _json
from datetime import datetime as _dt
import bson

router = APIRouter(prefix="/api/v1/chats", tags=["Chats"])


def _sanitize_chat_record(c: dict) -> dict:
    c = dict(c)
    c["_id"] = str(c["_id"])
    # optional agent id
    if c.get("agent_id") is not None:
        try:
            c["agent_id"] = str(c["agent_id"])
        except Exception:
            pass
    # optional root/last message ids
    if c.get("root_message_id") is not None:
        try:
            c["root_message_id"] = str(c["root_message_id"])
        except Exception:
            pass
    if c.get("last_message_id") is not None:
        try:
            c["last_message_id"] = str(c["last_message_id"])
        except Exception:
            pass
    if c.get("last_updated"):
        c["last_updated"] = c["last_updated"].isoformat()
    # also sanitize created_at if present
    if c.get("created_at"):
        try:
            c["created_at"] = c["created_at"].isoformat()
        except Exception:
            try:
                c["created_at"] = str(c["created_at"])
            except Exception:
                pass
    # sanitize embedded messages if present
    if c.get("messages") and isinstance(c.get("messages"), list):
        sanitized = []
        for m in c.get("messages"): # type: ignore
            try:
                sanitized.append(_sanitize_message_record(m))
            except Exception:
                try:
                    # fallback: stringify id
                    mm = dict(m)
                    if mm.get("_id") is not None:
                        mm["_id"] = str(mm["_id"])
                    sanitized.append(mm)
                except Exception:
                    pass
        c["messages"] = sanitized
    return c


def _sanitize_message_record(m: dict) -> dict:
    m = dict(m)
    # Embedded message: ensure id and sender are strings, format created_at
    if m.get("_id") is not None:
        m["_id"] = str(m["_id"])
    if m.get("sender") is not None:
        m["sender"] = str(m["sender"])
    if m.get("created_at") is not None:
        try:
            m["created_at"] = m["created_at"].isoformat()
        except Exception:
            m["created_at"] = str(m["created_at"])
    return m


def _sanitize_for_json(v):
    """Recursively make a value JSON-serializable: ObjectId -> str, datetimes -> iso, lists/dicts recurse."""
    # primitives
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    # datetime
    try:
        if isinstance(v, _dt):
            return v.isoformat()
    except Exception:
        pass
    # PyObjectId or bson.ObjectId
    try:
        if isinstance(v, PyObjectId):
            return str(v)
    except Exception:
        pass
    try:
        if isinstance(v, bson.ObjectId):
            return str(v)
    except Exception:
        pass
    # dict/list
    if isinstance(v, dict):
        out = {}
        for k, vv in v.items():
            try:
                kk = str(k)
            except Exception:
                kk = _json.dumps(k, default=str)
            out[kk] = _sanitize_for_json(vv)
        return out
    if isinstance(v, (list, tuple)):
        return [_sanitize_for_json(x) for x in v]
    # fallback: try isoformat then str
    try:
        if v and hasattr(v, "isoformat"):
            return v.isoformat() # type: ignore
    except Exception:
        pass
    try:
        return str(v)
    except Exception:
        return None


@router.get("/", response_model=ChatListResponse)
async def list_chats(authorization: str = Header(..., alias="Authorization")):
    """Listar chats del usuario autenticado (simple).

    Requiere header: Authorization: Bearer <token>
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    decoded = auth.authenticate_token(token)
    uid = decoded.get("uid") or decoded.get("user_id")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_oid = PyObjectId.parse(uid)
    chats_col = database.get_chat_collection()
    chats = []
    async for c in chats_col.find({"user_id": user_oid}).sort("last_updated", -1):
        chats.append(_sanitize_chat_record(c))
    return ChatListResponse(message="Chats listados", data=chats)


@router.post("/", response_model=ChatResponse)
async def create_chat(
    body: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Crear chat con mensaje inicial",
                "value": {"title": "Mi chat", "message": "Hola mundo", "agent_id": None},
            }
        },
    ),
    authorization: str = Header(..., alias="Authorization"),
):
    """Crear un chat entre miembros. Body: {"title": "optional"}
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    decoded = auth.authenticate_token(token)
    uid = decoded.get("uid") or decoded.get("user_id")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Create a chat owned by the authenticated user. Body may include optional title/metadata.
    title = body.get("title") or "New Chat"
    metadata = body.get("metadata") or {}
    message = body.get("message") or None
    if not message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="message is required to create chat")
    now = datetime.utcnow()
    chats_col = database.get_chat_collection()
    msgs_col=database.get_message_collection()
    # optional agent_id to associate an agent with this chat
    raw_agent_id = body.get("agent_id")
    agent_obj = None
    if raw_agent_id is not None:
        if not isinstance(raw_agent_id, str):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="agent_id must be a string if provided")
        try:
            agent_obj = PyObjectId.parse(raw_agent_id)
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="agent_id inválido")

    chat_doc = {
        "user_id": uid,
        "agent_id": agent_obj,
        "title": title,
        "metadata": metadata,
        "messages": [],
        "locked": False,
        "created_at": now,
        "last_updated": now,
    }
    res = await chats_col.insert_one(chat_doc)
    # use the inserted id consistently from now on
    chat_id = res.inserted_id
    chat_doc["_id"] = chat_id
    # initialize greeting generated by the agent and ensure a starter/origin message is present
    try:
        now = datetime.utcnow()
        starter_id = str(PyObjectId.new())
        starter = {
            "_id": starter_id,
            "chat_id": chat_id,
            "parent_id": None,
            "children_ids": [],
            "path": [],
            "branch_anchor": None,
            "cousin_left": None,
            "cousin_right": None,
            "sender_id": uid,
            "role": "user",
            "content": message,
            "content_type": "text",
            "status": "queued",
            "tokens_used": None,
            "created_at": now,
        }
        # pass module-level manager so WS clients can receive the greeting
        await messages_service.process_user_message(chat_id, starter, manager=manager)
    except Exception:
        init_doc = await msgs_col.find_one({"chat_id": chat_id}, sort=[("created_at", 1)])
        init = init_doc["_id"] if init_doc else None
        not_sent = {
            "_id": PyObjectId.new(),
            "chat_id": chat_id,
            "parent_id": init,
            "children_ids": [],
            "path": [],
            "branch_anchor": None,
            "cousin_left": None,
            "cousin_right": None,
            "sender_id": "SYSTEM",
            "role": "system",
            "content": "Agent isnt responding. Check your agent configuration.",
            "content_type": "text",
            "status": "done",
            "tokens_used": None,
            "created_at": now,
        }
        await messages_service.send_message(not_sent, chat_id, manager=manager)
    return ChatResponse(message="Chat creado", data=_sanitize_chat_record(chat_doc))


@router.get("/{chat_id}/messages", response_model=MessagesResponse)
async def list_messages(chat_id: str, authorization: str = Header(..., alias="Authorization")):
    """Listar mensajes de un chat si el usuario es miembro.

    Requiere header: Authorization: Bearer <token>
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    decoded = auth.authenticate_token(token)
    uid = decoded.get("uid") or decoded.get("user_id")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    chat_oid = PyObjectId.parse(chat_id)
    chats_col = database.get_chat_collection()
    msgs_col=database.get_message_collection()
    chat = await chats_col.find_one({"_id": chat_oid, "user_id": uid})
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found or access denied")
    # TODO: return messages in tree structure
    cursor = msgs_col.find({"chat_id": chat_oid}).sort("created_at", 1)
    msgs = []
    async for msg in cursor:
        try:
            sanitized = _sanitize_message_record(msg)
            sanitized = _sanitize_for_json(sanitized)
            msgs.append(sanitized)
        except Exception:
            try:
                msgs.append(_sanitize_for_json(msg))
            except Exception:
                msgs.append({"_raw": str(msg)})
    return MessagesResponse(message="Mensajes listados", data=msgs)

@router.post("/{chat_id}/messages", response_model=MessageResponse)
async def post_message(
    chat_id: str,
    body: Dict[str, Any] = Body(..., examples={"post": {"value": {"text": "Hola", "parent_id": "<message_id>"}}}),
    authorization: str = Header(..., alias="Authorization"),
):
    """Publicar un mensaje en un chat (REST). Body: {"text": "..."}"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    decoded = auth.authenticate_token(token)
    uid = decoded.get("uid") or decoded.get("user_id")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    text = body.get("text")
    if not text or not isinstance(text, str):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text is required")

    chat_oid = PyObjectId.parse(chat_id)
    chats_col = database.get_chat_collection()
    msgs_col = database.get_message_collection()
    chat = await chats_col.find_one({"_id": chat_oid, "user_id": uid})
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found or access denied")

    # parent_id is required for replies
    parent = body.get("parent_id")
    if not parent or not isinstance(parent, str):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="parent_id is required")
    try:
        parent_id = PyObjectId.parse(parent)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="parent_id inválido")

    # check chat lock
    if chat.get("locked"):
        raise HTTPException(status_code=423, detail="Chat is locked for processing")

    # process via centralized message service which will broadcast and call agents
    parent_obj = await msgs_col.find_one({"_id": parent_id})
    if parent_obj is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parent message not found")
    if parent_obj.get("children_ids", []) == []:
        branch_anchor = parent_obj.get("branch_anchor")
        cousin_left = parent_obj.get("cousin_left")
    else:
        branch_anchor = parent_id
        cousin_left = parent_obj.get("children_ids", [])[-1] if parent_obj.get("children_ids") else None
    cousin_right = parent_obj.get("cousin_right")
    now = datetime.utcnow()
    user_msg={
        "_id": PyObjectId.new(),
        "chat_id": chat_oid,
        "parent_id": parent_id,
        "children_ids": [],
        "path": [],
        "branch_anchor": branch_anchor,
        "cousin_left": cousin_left,
        "cousin_right": cousin_right,
        "sender_id": uid,
        "role": "user",
        "content": text,
        "content_type": "text",
        "status": "queued",
        "tokens_used": None,
        "created_at": now,
    }
    user_msg = await messages_service.process_user_message(chat_oid, user_msg, manager=manager)
    return MessageResponse(message="Mensaje publicado", data=_sanitize_message_record(user_msg))


class ConnectionManager:
    def __init__(self):
        # chat_id -> list[WebSocket]
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, chat_id: str, websocket: WebSocket):
        # Normalize chat key to string so callers can pass either str or ObjectId
        key = str(chat_id)
        # Accept the websocket if it hasn't been accepted yet. Some callers
        # (e.g. websocket_create_chat) accept the connection before
        # delegating to manager.connect, so ignore RuntimeError from a
        # repeated accept call.
        try:
            await websocket.accept()
        except RuntimeError:
            # already accepted (or invalid state) - ignore and continue
            pass
        except Exception:
            # any other accept error should not crash the manager; log/ignore
            pass
        conns = self.active_connections.setdefault(key, [])
        # avoid duplicate websocket entries
        if websocket not in conns:
            conns.append(websocket)
        try:
            print(f"ConnectionManager: connect chat={key} total={len(conns)}")
        except Exception:
            pass

    def disconnect(self, chat_id: str, websocket: WebSocket):
        key = str(chat_id)
        conns = self.active_connections.get(key, [])
        if websocket in conns:
            conns.remove(websocket)
            try:
                # Log detailed disconnect info (client addr + websocket repr + remaining count)
                client_info = getattr(websocket, "client", None)
                logging.info("ConnectionManager: disconnect chat=%s remaining=%s client=%s ws_id=%s",
                             key, len(conns), client_info, hex(id(websocket)))
            except Exception:
                logging.exception("ConnectionManager: failed to log disconnect details for chat=%s", key)

            # Schedule an async close and notify other participants about this disconnection.
            try:
                # create_task so disconnect can be called from sync contexts without awaiting
                asyncio.create_task(self._async_close_and_notify(key, websocket))
            except Exception:
                logging.exception("ConnectionManager: failed to schedule async close/notify for chat=%s", key)

            # If the list is now empty, remove the key to avoid growth
            if not conns:
                try:
                    del self.active_connections[key]
                except Exception:
                    pass

            return

    async def _async_close_and_notify(self, chat_id: str, websocket: WebSocket):
        """Asynchronously attempt to close the websocket and notify remaining clients.

        This is scheduled from the synchronous `disconnect` so we don't block callers.
        """
        key = str(chat_id)
        client_info = None
        try:
            client_info = getattr(websocket, "client", None)
        except Exception:
            client_info = None

        # Attempt to close the websocket if it's still open
        try:
            try:
                await websocket.close()
            except Exception:
                # Some websocket implementations raise when closing twice; log and continue
                logging.exception("ConnectionManager: error while closing websocket for chat=%s ws_id=%s", key, hex(id(websocket)))
        except Exception:
            logging.exception("ConnectionManager: unexpected error during websocket.close for chat=%s", key)

        # Notify remaining participants about the disconnection
        try:
            notice = {"cmd": "client_disconnected", "client": {"client": client_info, "ws_id": hex(id(websocket))}}
            # Use broadcast which will sanitize and send to remaining sockets
            await self.broadcast(key, notice)
        except Exception:
            logging.exception("ConnectionManager: failed to broadcast client_disconnected for chat=%s", key)

    async def broadcast(self, chat_id: str, message: Dict[str, Any]):
        key = str(chat_id)
        conns = list(self.active_connections.get(key, []))
        try:
            print(f"ConnectionManager: broadcast chat={key} targets={len(conns)}")
        except Exception:
            pass

        # --- Precompute sanitized payload + envelope + JSON once (avoid repeating per-socket) ---
        def _sanitize(obj):
            if obj is None:
                return None
            if isinstance(obj, dict):
                out = {}
                for k, v in obj.items():
                    if not isinstance(k, str):
                        k = str(k)
                    if isinstance(v, (PyObjectId,)):
                        try:
                            out[k] = str(v); continue
                        except Exception:
                            pass
                    if k in ("_id", "parent_id", "branch_anchor", "cousin_left", "cousin_right", "chat_id", "sender_id"):
                        try:
                            out[k] = str(v); continue
                        except Exception:
                            pass
                    if k in ("created_at", "last_updated"):
                        try:
                            out[k] = v.isoformat(); continue # type: ignore
                        except Exception:
                            pass
                    out[k] = _sanitize(v)
                return out
            if isinstance(obj, list):
                return [_sanitize(x) for x in obj]
            try:
                if hasattr(obj, "isoformat"):
                    return obj.isoformat()
            except Exception:
                pass
            return obj

        safe_msg = _sanitize(message)
        # ensure JSON-serializable (fallbacks)
        try:
            import json as _json
            _json.dumps(safe_msg)
        except Exception:
            try:
                import json as _json
                s = _json.dumps(message, default=str, ensure_ascii=False)
                safe_msg = _json.loads(s)
            except Exception:
                try:
                    safe_msg = {"_raw": str(message)}
                except Exception:
                    safe_msg = {"_raw": "<unserializable>"}

        # build envelope (reuse if already an envelope)
        if isinstance(message, dict) and message.get("cmd") and message.get("message"):
            inner = safe_msg.get("message") if isinstance(safe_msg, dict) and safe_msg.get("message") is not None else message.get("message", safe_msg)
            envelope = {"cmd": message.get("cmd"), "message": inner}
        else:
            role = (safe_msg.get("role") if isinstance(safe_msg, dict) else None)
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

        # build preview once and serialize to JSON once
        try:
            preview_text = ""
            mp = envelope.get("message")
            if isinstance(mp, dict):
                preview_text = (mp.get("content") or mp.get("text") or "")[:120]
            elif isinstance(mp, list):
                parts = []
                for itm in mp[:3]:
                    if isinstance(itm, dict):
                        parts.append(str(itm.get("content") or itm.get("text") or ""))
                    else:
                        parts.append(str(itm))
                preview_text = " | ".join([p for p in parts if p])[:120]
            else:
                preview_text = str(mp)[:120]
            try:
                print(f"ConnectionManager: about to send envelope preview for chat={chat_id}: {{'cmd': {envelope.get('cmd')}, 'message_preview': {preview_text}}}")
            except Exception:
                pass
            import json as _json
            json_text = _json.dumps(envelope, default=str, ensure_ascii=False)
        except Exception:
            try:
                json_text = str(envelope)
            except Exception:
                json_text = '"<unserializable>"'

        for ws in conns:
            # attempt send with one retry to handle transient write races
            send_ok = False
            for attempt in (1, 2):
                try:
                    # send raw string (text) to avoid websocket-lib internal json serialization errors
                    # use send_text which exists on Starlette WebSocket
                    await ws.send_text(json_text)
                    send_ok = True
                    try:
                        print(f"ConnectionManager: sent envelope to chat={chat_id} client (attempt={attempt})")
                    except Exception:
                        pass
                    break
                except Exception as e:
                    try:
                        print(f"ConnectionManager: send attempt={attempt} failed for chat={chat_id}: {e}")
                    except Exception:
                        pass
                    # small backoff before retry
                    if attempt == 1:
                        try:
                            await asyncio.sleep(0.05)
                        except Exception:
                            pass

            if not send_ok:
                # if send ultimately fails, remove this websocket and close it
                try:
                    self.disconnect(chat_id, ws)
                except Exception:
                    pass
                try:
                    await ws.close()
                except Exception:
                    pass
                continue


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_unified(websocket: WebSocket):
    """Manejador unificado para WebSocket:
    - Si se pasa query param `chat_id` -> unirse a chat existente (envía init history y delega a websocket_handler)
    - Si no se pasa `chat_id` -> crear chat (espera primer JSON con {message,..}), crea el chat y luego delega
    """
    await websocket.accept()
    # autenticar por Authorization header del handshake
    auth_header = websocket.headers.get("authorization") or websocket.headers.get("Authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        logging.warning("websocket: missing or invalid Authorization header")
        try:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except Exception:
            pass
        return
    token = auth_header.split(" ", 1)[1].strip()
    decoded = auth.authenticate_token(token)
    uid = decoded.get("uid") or decoded.get("user_id")
    if not uid:
        logging.warning("websocket: token decoding failed or uid missing")
        try:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except Exception:
            pass
        return

    # Determinar si el cliente quiere unirse a un chat existente
    chat_id_qs = websocket.query_params.get("chat_id")
    if chat_id_qs:
        # Unirse a chat existente
        logging.info("websocket: connection request to existing chat_id=%s uid=%s", str(chat_id_qs), str(uid))
        try:
            chat_oid = PyObjectId.parse(chat_id_qs)
        except Exception:
            try:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            except Exception:
                pass
            return

        chats_col = database.get_chat_collection()
        chat = await chats_col.find_one({"_id": chat_oid, "user_id": uid})
        if chat is None:
            try:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            except Exception:
                pass
            return

        await manager.connect(chat_id_qs, websocket)
        try:
            # Preparar y enviar payload de init (historia centrada)
            try:
                msgs_col = database.get_message_collection()
                last = await msgs_col.find_one({"chat_id": chat_oid, "role": {"$ne": "user"}}, sort=[("created_at", -1)])
                if not last:
                    last = await msgs_col.find_one({"chat_id": chat_oid}, sort=[("created_at", 1)])
                init_payload = {"init": {"chat": [], "branch_anchor": None, "last_message_id": None}}
                if last:
                    chat_history = await messages_service.build_history_from_message_bottom(last.get("_id"), limit=500)
                    init_payload = {
                        "init": {
                            "chat": chat_history,
                            "branch_anchor": str(last.get("branch_anchor") or last.get("_id")),
                            "last_message_id": str(last.get("_id")),
                            "note": "history of the last used thread"
                        }
                    }
                else:
                    init_payload = {"init": {"chat": [], "branch_anchor": None, "last_message_id": None}}

                safe_init = _sanitize_for_json(init_payload)
                await websocket.send_text(_json.dumps(safe_init, ensure_ascii=False))
            except Exception as e:
                logging.exception("websocket: failed to build/send init for chat_id=%s uid=%s", str(chat_id_qs), str(uid))
                try:
                    err_payload = {"init": {"error": "failed to load history", "details": str(e)}}
                    await websocket.send_text(_json.dumps(_sanitize_for_json(err_payload), ensure_ascii=False))
                except Exception:
                    pass

            logging.info("websocket: delegating to websocket_handler for chat_id=%s uid=%s", str(chat_id_qs), str(uid))
            await messages_service.websocket_handler(websocket, chat_oid, uid, manager)
        except WebSocketDisconnect:
            try:
                logging.info("websocket: WebSocketDisconnect for chat_id=%s uid=%s", str(chat_id_qs), str(uid))
                manager.disconnect(chat_id_qs, websocket)
            except Exception:
                logging.exception("websocket: error while handling WebSocketDisconnect for chat_id=%s uid=%s", str(chat_id_qs), str(uid))
        except Exception:
            logging.exception("websocket: unexpected exception for chat_id=%s uid=%s", str(chat_id_qs), str(uid))
            try:
                manager.disconnect(chat_id_qs, websocket)
            except Exception:
                logging.exception("websocket: error while disconnecting after exception for chat_id=%s uid=%s", str(chat_id_qs), str(uid))
        finally:
            try:
                logging.info("websocket: final cleanup for chat_id=%s uid=%s", str(chat_id_qs), str(uid))
                manager.disconnect(chat_id_qs, websocket)
            except Exception:
                logging.exception("websocket: error during manager.disconnect in finally for chat_id=%s uid=%s", str(chat_id_qs), str(uid))
            try:
                await websocket.close()
            except Exception:
                logging.exception("websocket: error while closing websocket in finally for chat_id=%s uid=%s", str(chat_id_qs), str(uid))
        return

    # Si no se pasó chat_id -> crear chat nuevo, esperamos primer mensaje JSON con datos
    try:
        payload = await websocket.receive_json()
        logging.info("websocket: received payload for chat creation: %s", payload)
    except Exception as e:
        logging.exception("websocket: failed to receive initial JSON payload for chat creation: %s", e)
        try:
            await websocket.send_json({"error": "invalid or missing JSON payload"})
        except Exception:
            pass
        try:
            await websocket.close(code=status.WS_1002_PROTOCOL_ERROR)
        except Exception:
            pass
        return

    message = payload.get("message") or None
    if not message or not isinstance(message, str):
        try:
            await websocket.send_json({"error": "message is required and must be a string"})
        except Exception:
            pass
        try:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except Exception:
            pass
        return

    title = payload.get("title") or "New Chat"
    metadata = payload.get("metadata") or {}
    raw_agent_id = payload.get("agent_id")
    agent_obj = None
    if raw_agent_id is not None:
        if not isinstance(raw_agent_id, str):
            try:
                await websocket.send_json({"error": "agent_id must be a string if provided"})
            except Exception:
                pass
            try:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            except Exception:
                pass
            return
        try:
            agent_obj = PyObjectId.parse(raw_agent_id)
        except Exception:
            try:
                await websocket.send_json({"error": "invalid agent_id"})
            except Exception:
                pass
            try:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            except Exception:
                pass
            return

    now = datetime.utcnow()
    chats_col = database.get_chat_collection()
    chat_doc = {
        "user_id": uid,
        "agent_id": agent_obj,
        "title": title,
        "metadata": metadata,
        "messages": [],
        "locked": False,
        "created_at": now,
        "last_updated": now,
    }

    try:
        res = await chats_col.insert_one(chat_doc)
        chat_id = res.inserted_id
        chat_doc["_id"] = chat_id
        # crear mensaje inicial/starter
        starter = {
            "_id": PyObjectId.new(),
            "chat_id": chat_id,
            "parent_id": None,
            "children_ids": [],
            "path": [],
            "branch_anchor": None,
            "cousin_left": None,
            "cousin_right": None,
            "sender_id": uid,
            "role": "user",
            "content": message,
            "content_type": "text",
            "status": "queued",
            "tokens_used": None,
            "created_at": now,
        }

        try:
            logging.info("websocket: sending initial chat object to client chat_id=%s", str(chat_id))
            await websocket.send_json({"chat": _sanitize_chat_record(chat_doc)})
        except Exception:
            logging.exception("websocket: failed to send sanitized chat, falling back to chat_id only")
            try:
                await websocket.send_json({"chat_id": str(chat_id)})
            except Exception:
                pass

    except Exception:
        logging.exception("websocket: failed to create chat or send initial payload for uid=%s", str(uid))
        try:
            await websocket.close()
        except Exception:
            pass
        return

    # Register and initialize
    try:
        await manager.connect(chat_id, websocket)
    except Exception:
        logging.exception("websocket: manager.connect failed for chat_id=%s", str(chat_id))

    try:
        logging.info("websocket: initializing starter message for chat_id=%s", str(chat_id))
        await messages_service.process_user_message(chat_id, starter, manager=manager)
    except Exception:
        try:
            msgs_col = database.get_message_collection()
            init_doc = await msgs_col.find_one({"chat_id": chat_id}, sort=[("created_at", 1)])
            init = init_doc["_id"] if init_doc else None
            not_sent = {
                "_id": PyObjectId.new(),
                "chat_id": chat_id,
                "parent_id": init,
                "children_ids": [],
                "path": [],
                "branch_anchor": None,
                "cousin_left": None,
                "cousin_right": None,
                "sender_id": "SYSTEM",
                "role": "system",
                "content": "Agent isnt responding. Check your agent configuration.",
                "content_type": "text",
                "status": "done",
                "tokens_used": None,
                "created_at": now,
            }
            await messages_service.send_message(not_sent, chat_id, manager=manager)
        except Exception:
            logging.exception("websocket: failed while sending fallback system message for chat_id=%s", str(chat_id))

    # Delegar a websocket_handler para manejar la sesión
    try:
        logging.info("websocket: entering websocket_handler for chat_id=%s, uid=%s", str(chat_id), str(uid))
        await messages_service.websocket_handler(websocket, chat_id, uid, manager)
    except WebSocketDisconnect:
        try:
            logging.info("websocket: websocket disconnected for chat_id=%s", str(chat_id))
            manager.disconnect(chat_id, websocket)
        except Exception:
            logging.exception("websocket: error during disconnect handling for chat_id=%s", str(chat_id))
    except Exception:
        logging.exception("websocket: unexpected exception for chat_id=%s", str(chat_id))
        try:
            manager.disconnect(chat_id, websocket)
        except Exception:
            logging.exception("websocket: error while disconnecting after exception for chat_id=%s", str(chat_id))
    finally:
        try:
            logging.info("websocket: final cleanup closing websocket for chat_id=%s", str(chat_id))
            try:
                manager.disconnect(chat_id, websocket)
            except Exception:
                logging.exception("websocket: error during manager.disconnect in finally for chat_id=%s", str(chat_id))
            await websocket.close()
        except Exception:
            logging.exception("websocket: error while closing websocket for chat_id=%s in finally", str(chat_id))