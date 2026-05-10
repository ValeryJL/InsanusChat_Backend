"""
Servicio de Árbol de Mensajes y Manejador WebSocket (HU-02, HU-03, HU-08).
- Gestiona inserción de mensajes en árbol (`parent_id`, `children_ids`, `path`, `branch_anchor`, `cousin_left`, `cousin_right`).
- Previene deadlocks del lock de chat con TTL de 120 segundos y liberación garantizada en `finally` (HU-03).
- Permite cancelar la generación en curso con `{"cmd": "stop_generation"}` (HU-08).
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from database import get_chat_collection, get_message_collection
from models import PyObjectId
from services import agents as agents_service
from services.node_bridge import node_bridge

logger = logging.getLogger(__name__)

DEFAULT_WS_IDLE_TIMEOUT = 600  # 10 minutos
CHAT_LOCK_TTL_SECONDS = 120    # TTL de 120s para evitar chats bloqueados permanentemente (HU-03)

LEFT = "left"
RIGHT = "right"

# Registro en memoria de tareas de generación activas por chat_id (str) para soportar stop_generation
ACTIVE_GENERATION_TASKS: Dict[str, asyncio.Task] = {}


def is_chat_currently_locked(chat_doc: Optional[Dict[str, Any]]) -> bool:
    """
    HU-03: Comprueba si un chat está bloqueado respetando el TTL de 120 segundos.
    Si `locked` es True pero `locked_at` expiró (o no existe y `last_updated` expiró), devuelve False.
    """
    if not chat_doc or not chat_doc.get("locked"):
        return False
    locked_at = chat_doc.get("locked_at") or chat_doc.get("last_updated")
    if isinstance(locked_at, datetime):
        if datetime.utcnow() - locked_at > timedelta(seconds=CHAT_LOCK_TTL_SECONDS):
            return False
    return True


async def acquire_chat_lock(chat_oid: Any, manager: Any = None) -> bool:
    """Adquiere el lock del chat con timestamp `locked_at` y lo anuncia por WebSocket."""
    chats = get_chat_collection()
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=CHAT_LOCK_TTL_SECONDS)
    try:
        chat_doc = await chats.find_one({"_id": chat_oid})
        if is_chat_currently_locked(chat_doc):
            return False
        await chats.update_one(
            {"_id": chat_oid},
            {"$set": {"locked": True, "locked_at": now, "last_updated": now}},
        )
        if manager is not None:
            await manager.broadcast(str(chat_oid), {"cmd": "chat_locked", "message": {"locked": True}})
        return True
    except Exception as e:
        logger.warning("Error adquiriendo lock de chat %s: %s", chat_oid, e)
        return True


async def release_chat_lock(chat_oid: Any, manager: Any = None):
    """Libera siempre el lock del chat y anuncia `chat_unlocked` por WebSocket."""
    chats = get_chat_collection()
    try:
        await chats.update_one(
            {"_id": chat_oid},
            {"$set": {"locked": False, "locked_at": None, "last_updated": datetime.utcnow()}},
        )
    except Exception as e:
        logger.warning("Error liberando lock en DB para chat %s: %s", chat_oid, e)
    if manager is not None:
        try:
            await manager.broadcast(str(chat_oid), {"cmd": "chat_unlocked", "message": {"locked": False}})
        except Exception:
            pass


async def send_message(message_doc: Dict[str, Any], chat_oid: Any, manager: Any = None):
    """Inserta `message_doc` en la colección `messages`, actualiza `children_ids` del padre y emite por WS."""
    if not message_doc:
        return None
    msgs = get_message_collection()
    chats = get_chat_collection()

    if isinstance(message_doc.get("_id"), str):
        try:
            message_doc["_id"] = PyObjectId.parse(message_doc["_id"])
        except Exception:
            message_doc["_id"] = PyObjectId.new()
    elif message_doc.get("_id") is None:
        message_doc["_id"] = PyObjectId.new()

    parent_id = message_doc.get("parent_id")
    if isinstance(parent_id, str):
        try:
            message_doc["parent_id"] = PyObjectId.parse(parent_id)
        except Exception:
            pass

    res = await msgs.insert_one(message_doc)
    msg_id = res.inserted_id
    message_doc["_id"] = msg_id

    # Actualizar contador y timestamp del chat
    try:
        await chats.update_one(
            {"_id": chat_oid},
            {"$inc": {"message_count": 1}, "$set": {"last_updated": datetime.utcnow()}},
        )
    except Exception:
        pass

    # Si tiene padre, actualizar children_ids y punteros de ramas laterales
    if message_doc.get("parent_id") is not None:
        try:
            parent = await msgs.find_one({"_id": message_doc.get("parent_id")})
        except Exception:
            parent = None

        if parent and len(parent.get("children_ids", [])) > 0:
            try:
                asyncio.create_task(update_rightmost_branch(parent, msg_id))
            except Exception:
                pass

        try:
            await msgs.update_one(
                {"_id": message_doc.get("parent_id")},
                {"$push": {"children_ids": msg_id}},
            )
        except Exception:
            pass

    if manager is not None:
        try:
            chat_key = str(chat_oid)
            ack_envelope = {"cmd": "ack", "message": {"_id": str(msg_id)}}
            await manager.broadcast(chat_key, ack_envelope)
            await manager.broadcast(chat_key, message_doc)
        except Exception:
            logger.exception("send_message: fallo al hacer broadcast de mensaje o ack")

    return msg_id


async def process_user_message(chat_oid: Any, message: Dict[str, Any], manager: Any = None) -> Dict[str, Any]:
    """
    Inserta el mensaje del usuario, adquiere el lock con TTL, lanza la ejecución del agente
    en background y garantiza en un bloque `finally` que el chat siempre se desbloquee (HU-03).
    """
    await acquire_chat_lock(chat_oid, manager=manager)

    try:
        message_id = await send_message(message, chat_oid, manager=manager)
        message["_id"] = message_id
    except Exception:
        await release_chat_lock(chat_oid, manager=manager)
        raise

    chat_key = str(chat_oid)

    async def _run_agent_with_guaranteed_unlock():
        try:
            response = await agents_service.run_agent(chat_oid, message_id, manager=manager)
            if response:
                await send_message(response, chat_oid, manager=manager)
        except asyncio.CancelledError:
            logger.info("Generación cancelada por el usuario para el chat %s", chat_key)
            cancel_doc = {
                "_id": PyObjectId.new(),
                "chat_id": chat_oid,
                "parent_id": message_id,
                "children_ids": [],
                "path": list(message.get("path", [])) + [message_id],
                "branch_anchor": message.get("branch_anchor"),
                "cousin_left": message.get("cousin_left"),
                "cousin_right": message.get("cousin_right"),
                "sender_id": "SYSTEM",
                "role": "agent",
                "content": "*(Generación detenida por el usuario)*",
                "content_type": "markdown",
                "status": "stopped",
                "tokens_used": 0,
                "created_at": datetime.utcnow(),
            }
            await send_message(cancel_doc, chat_oid, manager=manager)
        except Exception as e:
            logger.exception("Error ejecutando agente en chat %s: %s", chat_key, e)
        finally:
            ACTIVE_GENERATION_TASKS.pop(chat_key, None)
            await release_chat_lock(chat_oid, manager=manager)

    task = asyncio.create_task(_run_agent_with_guaranteed_unlock())
    ACTIVE_GENERATION_TASKS[chat_key] = task
    return message


async def update_rightmost_branch(parent: Dict[str, Any], new_msg_oid: Any):
    msgs_col = get_message_collection()
    anchor_to_set = parent.get("_id")
    curr = None

    children = parent.get("children_ids") or []
    for cid in children:
        try:
            child_key = PyObjectId.parse(cid) if isinstance(cid, str) else cid
            child_doc = await msgs_col.find_one({"_id": child_key})
        except Exception:
            child_doc = None
        if not child_doc:
            continue

        curr = child_doc
        original_anchor = child_doc.get("branch_anchor")
        stack = [child_doc]
        while stack:
            node = stack.pop()
            if not node:
                continue
            if str(child_doc.get("_id")) == str(new_msg_oid):
                break
            node_anchor = node.get("branch_anchor")
            if node_anchor == original_anchor:
                try:
                    await msgs_col.update_one(
                        {"_id": node["_id"]},
                        {"$set": {"branch_anchor": anchor_to_set}},
                    )
                except Exception:
                    pass
                for cid2 in node.get("children_ids") or []:
                    try:
                        c2_oid = PyObjectId.parse(cid2) if isinstance(cid2, str) else cid2
                        child_doc2 = await msgs_col.find_one({"_id": c2_oid})
                        if child_doc2:
                            stack.append(child_doc2)
                    except Exception:
                        pass

    right_curr = curr
    while right_curr:
        try:
            await msgs_col.update_one(
                {"_id": right_curr["_id"]},
                {"$set": {"cousin_right": new_msg_oid}},
            )
        except Exception:
            pass
        children = right_curr.get("children_ids") or []
        if not children:
            break
        next_id = children[-1]
        try:
            n_oid = PyObjectId.parse(next_id) if isinstance(next_id, str) else next_id
            right_curr = await msgs_col.find_one({"_id": n_oid})
        except Exception:
            right_curr = None


async def websocket_handler(websocket: Any, chat_oid: Any, uid: Any, manager: Any):
    """
    Manejador WebSocket para sesión de chat activa.
    Comandos soportados:
      - {"cmd": "send", "text": "...", "parent_id": "<id opcional si el chat está vacío>"}
      - {"cmd": "stop_generation"}
      - {"cmd": "unlock"}
      - {"cmd": "fetch_from_top", "id": "<message_id>", "limit": 16, "direction": "left|right"}
      - {"cmd": "fetch_from_bottom", "id": "<message_id>", "limit": 16}
      - {"cmd": "get", "id": "<message_id>"}
      - {"cmd": "ping"}
      - {"cmd": "close" | "disconnect"}
    """
    msgs_col = get_message_collection()
    chats_col = get_chat_collection()

    def _sanitize_msg_for_out(m: dict) -> dict:
        if not m:
            return {}
        out = dict(m)
        for id_field in ("_id", "chat_id", "parent_id", "branch_anchor", "cousin_left", "cousin_right", "sender_id"):
            if out.get(id_field) is not None:
                out[id_field] = str(out[id_field])
        if isinstance(out.get("children_ids"), list):
            out["children_ids"] = [str(c) for c in out["children_ids"]]
        if isinstance(out.get("path"), list):
            out["path"] = [str(p) for p in out["path"]]
        if out.get("created_at") is not None and hasattr(out["created_at"], "isoformat"):
            out["created_at"] = out["created_at"].isoformat()
        return out

    async def send_error(ws, msg: str):
        env = {"cmd": "error", "error": str(msg)}
        try:
            await ws.send_text(json.dumps(env, default=str, ensure_ascii=False))
        except Exception:
            pass

    while True:
        data = None
        try:
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=DEFAULT_WS_IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_text(json.dumps({"cmd": "error", "error": "idle_timeout"}, ensure_ascii=False))
                    await websocket.close()
                except Exception:
                    pass
                if manager is not None:
                    manager.disconnect(chat_oid, websocket)
                return
            except RuntimeError:
                # Socket cerrado por el cliente
                return
            except Exception as exc:
                if "disconnect" in str(exc).lower() or "closed" in str(exc).lower():
                    return
                try:
                    raw = await asyncio.wait_for(websocket.receive_text(), timeout=1)
                    data = json.loads(raw)
                except Exception:
                    return
        except Exception:
            return

        if not isinstance(data, dict):
            await send_error(websocket, "payload must be a JSON object")
            continue

        cmd = data.get("cmd")

        if cmd == "ping":
            try:
                await websocket.send_text(json.dumps({"cmd": "pong"}, ensure_ascii=False))
            except Exception:
                pass
            continue

        if cmd == "stop_generation":
            chat_key = str(chat_oid)
            running_task = ACTIVE_GENERATION_TASKS.get(chat_key)
            if running_task and not running_task.done():
                running_task.cancel()
            else:
                await release_chat_lock(chat_oid, manager=manager)
            continue

        if cmd == "unlock":
            await release_chat_lock(chat_oid, manager=manager)
            continue

        if cmd == "tool_approval":
            approval_id = str(data.get("approval_id") or "")
            approved = bool(data.get("approved", True))
            feedback = str(data.get("feedback") or "")
            if approval_id:
                node_bridge.resolve_tool_approval(str(chat_oid), approval_id, approved, feedback)
                if manager is not None:
                    await manager.broadcast(
                        str(chat_oid),
                        {
                            "cmd": "agent_tool_approval_resolved",
                            "message": {
                                "approval_id": approval_id,
                                "chat_id": str(chat_oid),
                                "approved": approved,
                                "feedback": feedback,
                            },
                        },
                    )
            continue

        if cmd in ("send", "send_message"):
            text = data.get("text") or data.get("content")
            parent_id = data.get("parent_id")
            if not text or not isinstance(text, str):
                await send_error(websocket, "text is required")
                continue

            # HU-03: Validar parent_id ANTES de adquirir el lock para jamás dejar el chat bloqueado en caso de error
            parent_obj = None
            if parent_id:
                try:
                    parent_oid = PyObjectId.parse(parent_id) if isinstance(parent_id, str) else parent_id
                    parent_obj = await msgs_col.find_one({"_id": parent_oid, "chat_id": chat_oid})
                except Exception:
                    parent_obj = None
                if not parent_obj:
                    await send_error(websocket, "parent_id not found")
                    continue
                # Si por error se apuntó a un mensaje de rol 'user', subir al padre ('agent' o raíz None)
                # para que jamás quede un mensaje de usuario como hijo directo de otro mensaje de usuario
                if parent_obj.get("role") == "user":
                    upper_parent_id = parent_obj.get("parent_id")
                    if upper_parent_id:
                        parent_obj = await msgs_col.find_one({"_id": upper_parent_id, "chat_id": chat_oid})
                    else:
                        parent_obj = None

            # Comprobar lock con TTL de 120s
            chat_doc = await chats_col.find_one({"_id": chat_oid})
            if is_chat_currently_locked(chat_doc):
                await send_error(websocket, "Chat is locked for processing")
                continue

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
                    branch_anchor = parent_obj.get("_id")
                    cousin_left = parent_obj["children_ids"][-1]
                cousin_right = parent_obj.get("cousin_right")
                msg_path = list(parent_obj.get("path", [])) + [parent_obj.get("_id")]

            user_msg = {
                "_id": PyObjectId.new(),
                "chat_id": chat_oid,
                "parent_id": parent_obj.get("_id") if parent_obj else None,
                "children_ids": [],
                "path": msg_path,
                "branch_anchor": branch_anchor,
                "cousin_left": cousin_left,
                "cousin_right": cousin_right,
                "sender_id": str(uid),
                "role": "user",
                "content": text,
                "content_type": "text",
                "status": "done",
                "tokens_used": None,
                "created_at": datetime.utcnow(),
            }

            try:
                await process_user_message(chat_oid, user_msg, manager=manager)
            except Exception as e:
                logger.exception("websocket_handler: error procesando mensaje")
                await release_chat_lock(chat_oid, manager=manager)
                await send_error(websocket, str(e))
            continue

        if cmd in ("close", "disconnect"):
            try:
                await websocket.send_text(json.dumps({"cmd": "closing", "reason": "client_requested"}, ensure_ascii=False))
            except Exception:
                pass
            if manager is not None:
                manager.disconnect(chat_oid, websocket)
            try:
                await websocket.close()
            except Exception:
                pass
            return

        if cmd == "fetch_from_top":
            mid = data.get("id")
            limit = int(data.get("limit") or 16)
            direction = data.get("direction") or RIGHT
            if not mid:
                await send_error(websocket, "id is required")
                continue
            try:
                hist = await build_history_from_message_top(mid, limit=limit, direction=direction)
                await websocket.send_text(json.dumps({"cmd": "history", "history": hist}, default=str, ensure_ascii=False))
            except Exception as e:
                await send_error(websocket, str(e))
            continue

        if cmd == "fetch_from_bottom":
            mid = data.get("id")
            limit = int(data.get("limit") or 16)
            if not mid:
                await send_error(websocket, "id is required")
                continue
            try:
                hist = await build_history_from_message_bottom(mid, limit=limit)
                await websocket.send_text(json.dumps({"cmd": "history", "history": hist}, default=str, ensure_ascii=False))
            except Exception as e:
                await send_error(websocket, str(e))
            continue

        if cmd == "get":
            mid = data.get("id")
            if not mid:
                await send_error(websocket, "id is required")
                continue
            try:
                doc = await msgs_col.find_one({"_id": PyObjectId.parse(mid)})
                if not doc:
                    await send_error(websocket, "message not found")
                    continue
                out = _sanitize_msg_for_out(doc)
                await websocket.send_text(json.dumps({"cmd": "message", "message": out}, default=str, ensure_ascii=False))
            except Exception:
                await send_error(websocket, "failed to get message")
            continue

        await send_error(websocket, f"unknown cmd: {cmd}")


def _parse_msg_node(m: Dict[str, Any]) -> Dict[str, Any]:
    parsed = dict(m)
    for id_field in ("_id", "chat_id", "parent_id", "branch_anchor", "cousin_left", "cousin_right", "sender_id"):
        if parsed.get(id_field) is not None:
            parsed[id_field] = str(parsed[id_field])
    if isinstance(parsed.get("children_ids"), list):
        parsed["children_ids"] = [str(c) for c in parsed["children_ids"]]
    if isinstance(parsed.get("path"), list):
        parsed["path"] = [str(p) for p in parsed["path"]]
    ca = parsed.get("created_at")
    if ca and hasattr(ca, "isoformat"):
        parsed["created_at"] = ca.isoformat()
    return parsed


async def build_history_from_message_top(first_msg_id: Any, limit: int = 16, direction: str = RIGHT) -> Dict[str, Any]:
    msgs_col = get_message_collection()
    try:
        key = PyObjectId.parse(first_msg_id) if isinstance(first_msg_id, str) else first_msg_id
    except Exception:
        key = first_msg_id

    target_msg = await msgs_col.find_one({"_id": key})
    if not target_msg:
        raise ValueError("Message not found")

    descendents = []
    current = target_msg
    for _ in range(limit):
        if not current or not current.get("children_ids"):
            break
        child_id = current["children_ids"][0] if direction == LEFT else current["children_ids"][-1]
        try:
            child_key = PyObjectId.parse(child_id) if isinstance(child_id, str) else child_id
            child = await msgs_col.find_one({"_id": child_key})
            if not child:
                break
            descendents.append(child)
            current = child
        except Exception:
            break

    chain = [target_msg] + descendents
    return {"Result": [_parse_msg_node(m) for m in chain]}


async def build_history_from_message_bottom(last_msg_id: Any, limit: int = 16) -> Dict[str, Any]:
    msgs_col = get_message_collection()
    try:
        key = PyObjectId.parse(last_msg_id) if isinstance(last_msg_id, str) else last_msg_id
    except Exception:
        key = last_msg_id

    target_msg = await msgs_col.find_one({"_id": key})
    if not target_msg:
        raise ValueError("Message not found")

    ancestors = []
    current = target_msg
    for _ in range(limit):
        if not current.get("parent_id"):
            break
        try:
            parent_key = PyObjectId.parse(current["parent_id"]) if isinstance(current["parent_id"], str) else current["parent_id"]
            parent = await msgs_col.find_one({"_id": parent_key})
        except Exception:
            parent = None
        if not parent:
            break
        ancestors.append(parent)
        current = parent
    ancestors.reverse()

    chain = ancestors + [target_msg]
    return {"Result": [_parse_msg_node(m) for m in chain]}
