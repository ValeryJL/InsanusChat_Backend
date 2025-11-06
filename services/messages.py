from datetime import datetime
import asyncio
import logging

# tiempo por defecto (segundos) de inactividad tras el cual se cierra la conexión
DEFAULT_WS_IDLE_TIMEOUT = 300  # 5 minutos

from database import get_message_collection, get_chat_collection
from models import PyObjectId
from services import agents as agents_service

LEFT = "left"
RIGHT = "right"

async def send_message(message_doc, chat_oid, manager=None):
    """Insert message_doc into DB and broadcast via manager if provided."""
    msgs = get_message_collection()
    parent_id = message_doc.get("parent_id")
    if isinstance(parent_id, str):
        try:
            message_doc["parent_id"] = PyObjectId.parse(parent_id)
        except Exception:
            # leave as-is if cannot parse
            pass

    # perform insertion
    res = await msgs.insert_one(message_doc)
    try:
        msg_id = res.inserted_id
    except Exception:
        msg_id = None
    message_doc["_id"] = msg_id

    # If there is a parent, push this id into its children_ids and possibly update branches
    if message_doc.get("parent_id") is not None:
        try:
            parent = await msgs.find_one({"_id": message_doc.get("parent_id")})
        except Exception:
            parent = None

        # schedule branch-anchor updates if parent had more than one child before insertion
        try:
            if parent and len(parent.get("children_ids", [])) > 0:
                # previous rightmost child is at index -2
                try:
                    asyncio.create_task(update_rightmost_branch(parent, msg_id))
                except Exception:
                    pass
        except Exception:
            pass

        # push new child id into parent's children_ids for navigation
        try:
            await msgs.update_one({"_id": message_doc.get("parent_id")}, {"$push": {"children_ids": msg_id}})
        except Exception:
            pass

    # Broadcast the inserted message to websocket clients in the chat (if manager provided).
    # We first send an ACK envelope (nested under 'mensaje') and then the normal message.
    if manager is not None:
        try:
            chat_key = str(chat_oid)
            # send a minimal ACK (only the inserted id) to avoid duplicating full message content
            try:
                ack_payload = {"_id": str(msg_id)} if msg_id is not None else {"_id": None}
            except Exception:
                ack_payload = {"_id": msg_id}
            ack_envelope = {"cmd": "ack", "message": ack_payload}
            await manager.broadcast(chat_key, ack_envelope)
            # Normal message broadcast (ConnectionManager will envelope it if needed)
            await manager.broadcast(chat_key, message_doc)
        except Exception:
            try:
                logging.exception("send_message: failed to broadcast message or ack")
            except Exception:
                pass

    return msg_id

async def process_user_message(chat_oid, message, manager=None):
    """Insert user message, broadcast it, call agent to generate a response, insert and broadcast response.

    parent_id may be None (in which case we resolve to last message or create a root if none).
    This function acquires a per-chat lock to avoid concurrent agent processing for the same chat.
    """
    chats = get_chat_collection()
    
    # mark chat locked
    try:
        await chats.update_one({"_id": chat_oid}, {"$set": {"locked": True}})
    except Exception:
        pass
    # announce lock to websocket clients
    try:
        if manager is not None:
            try:
                chat_key = str(chat_oid)
                lock_env = {"cmd": "chat_locked", "message": {"locked": True}}
                await manager.broadcast(chat_key, lock_env)
            except Exception:
                try:
                    logging.exception("process_user_message: failed to broadcast chat_locked")
                except Exception:
                    pass
    except Exception:
        pass
    # insert initial system message (send_message returns the inserted _id)
    message_id = await send_message(message, chat_oid, manager=manager)
    # attach the inserted id back into the message for caller convenience
    try:
        message["_id"] = message_id
    except Exception:
        pass
    # Build a detailed system prompt for the greeting. This prompt will be passed
    # to the agent runner via agent_params so the agent knows to generate the welcome.
    # The prompt describes the agent role and the expected welcome message.

    # schedule agent run on the starter message (does insertion of agent response)
    async def _run_init():
        try:
            response = await agents_service.run_agent(chat_oid, message_id)
            await send_message(response, chat_oid, manager=manager)
            # unlock chat
            await chats.update_one({"_id": chat_oid}, {"$set": {"locked": False}})
            # announce unlock to websocket clients
            try:
                if manager is not None:
                    try:
                        chat_key = str(chat_oid)
                        unlock_env = {"cmd": "chat_unlocked", "message": {"locked": False}}
                        await manager.broadcast(chat_key, unlock_env)
                    except Exception:
                        try:
                            logging.exception("process_user_message: failed to broadcast chat_unlocked")
                        except Exception:
                            pass
            except Exception:
                pass
        except Exception:
            # best-effort: ensure chat unlocked
            try:
                await chats.update_one({"_id": chat_oid}, {"$set": {"locked": False}})
            except Exception:
                pass
            # announce unlock even if we hit exception
            try:
                if manager is not None:
                    try:
                        chat_key = str(chat_oid)
                        unlock_env = {"cmd": "chat_unlocked", "message": {"locked": False}}
                        await manager.broadcast(chat_key, unlock_env)
                    except Exception:
                        try:
                            logging.exception("process_user_message: failed to broadcast chat_unlocked after exception")
                        except Exception:
                            pass
            except Exception:
                pass

    asyncio.create_task(_run_init())
    return message

async def update_rightmost_branch(parent, new_msg_oid):
    msgs_col = get_message_collection()
    original_anchor = None
    # prepare anchor to set on affected branches (new child's branch_anchor is parent._id)
    anchor_to_set = parent.get("_id")
    curr = None

    # iterate every child of parent, update descendant branch_anchor where it equals
    # the child's original anchor. Stop early if we encounter the child that matches new_msg_oid.
    children = parent.get("children_ids") or []
    for cid in children:
        # normalize child id and fetch document
        try:
            child_key = PyObjectId.parse(cid) if isinstance(cid, str) else cid
        except Exception:
            child_key = cid
        try:
            child_doc = await msgs_col.find_one({"_id": child_key})
        except Exception:
            child_doc = None
        if not child_doc:
            continue

        # remember last processed child (used later to walk the rightmost branch)
        curr = child_doc

        original_anchor = child_doc.get("branch_anchor")
        # DFS over this child's subtree, updating branch_anchor only when it equals original_anchor
        stack = [child_doc]
        while stack:
            node = stack.pop()
            try:
                if str(child_doc.get("_id")) == str(new_msg_oid):
                    break
            except Exception:
                # on any comparison error, continue to next child
                pass
            if not node:
                continue
            try:
                node_anchor = node.get("branch_anchor")
            except Exception:
                node_anchor = None

            if node_anchor == original_anchor:
                try:
                    await msgs_col.update_one(
                        {"_id": node["_id"]},
                        {"$set": {"branch_anchor": anchor_to_set}}
                    )
                except Exception:
                    pass
                # push children to continue traversal
                for cid2 in node.get("children_ids") or []:
                    try:
                        child_doc2 = await msgs_col.find_one({"_id": PyObjectId.parse(cid2)})
                    except Exception:
                        child_doc2 = None
                    if child_doc2:
                        stack.append(child_doc2)
            # else: do not descend this branch

        # if this child is the new message, stop processing further siblings
        

    # 2) Walk the rightmost branch (always the last child) from curr and update cousin_right
    right_curr = curr
    while right_curr:
        try:
            await msgs_col.update_one(
                {"_id": right_curr["_id"]},
                {"$set": {"cousin_right": new_msg_oid}}
            )
        except Exception:
            pass

        children = right_curr.get("children_ids") or []
        if not children:
            break
        next_id = children[-1]
        try:
            right_curr = await msgs_col.find_one({"_id": PyObjectId.parse(next_id)})
        except Exception:
            right_curr = None

async def websocket_handler(websocket, chat_oid, uid, manager):
    """WebSocket handler inteligente.

    Soporta comandos JSON entrantes con la forma:
      {"cmd": "send", "text": "...", "parent_id": "<id>"}
      {"cmd": "fetch_from_top", "id": "<message_id>", "limit": 16, "direction": "left"}
      {"cmd": "fetch_from_bottom", "id": "<message_id>", "limit": 16}
      {"cmd": "get", "id": "<message_id>"}
      {"cmd": "ping"}

    Responde con envelopes JSON por websocket (usando send_text con json.dumps):
      {"cmd": "ack", "message": {"_id": "..."}}
      {"cmd": "history", "history": {...}}
      {"cmd": "message", "message": {...}}
      {"cmd": "error", "error": "..."}

    Esta función asume que la autenticación/validación del user y del chat
    ya fue hecha por el endpoint que llamó a este handler.
    """
    import json

    msgs_col = get_message_collection()
    chats_col = get_chat_collection()

    def _sanitize_msg_for_out(m: dict) -> dict:
        """Normaliza un documento de mensaje para salida JSON (ids->str, fechas->ISO)."""
        if not m:
            return {}
        try:
            out = dict(m)
        except Exception:
            return {"_raw": str(m)}
        if out.get("_id") is not None:
            out["_id"] = str(out["_id"])
        if out.get("parent_id") is not None:
            try:
                out["parent_id"] = str(out["parent_id"])
            except Exception:
                out["parent_id"] = out.get("parent_id")
        if isinstance(out.get("children_ids"), list):
            out["children_ids"] = [str(c) for c in out.get("children_ids")]
        if out.get("created_at") is not None:
            try:
                out["created_at"] = out["created_at"].isoformat()
            except Exception:
                try:
                    out["created_at"] = str(out["created_at"])
                except Exception:
                    pass
        return out

    async def send_error(ws, msg: str):
        env = {"cmd": "error", "error": str(msg)}
        try:
            await ws.send_text(json.dumps(env, default=str, ensure_ascii=False))
        except Exception:
            pass

    try:
        logging.info("websocket_handler: start for chat_oid=%s uid=%s", str(chat_oid), str(uid))
        while True:
            data = None
            idle_timeout = DEFAULT_WS_IDLE_TIMEOUT
            try:
                # try to receive a JSON payload directly, with idle timeout
                try:
                    data = await asyncio.wait_for(websocket.receive_json(), timeout=idle_timeout)
                    logging.debug("websocket_handler: received json payload: %s", data)
                except asyncio.TimeoutError:
                    # idle timeout — close connection
                    logging.info("websocket_handler: idle timeout reached (secs=%s) for chat=%s uid=%s, closing websocket", str(idle_timeout), str(chat_oid), str(uid))
                    try:
                        await websocket.send_text(json.dumps({"cmd": "error", "error": "idle_timeout"}, ensure_ascii=False))
                    except Exception:
                        pass
                    try:
                        await websocket.close()
                    except Exception:
                        pass
                    # ensure manager disconnect if provided
                    try:
                        if manager is not None:
                            manager.disconnect(chat_oid, websocket)
                    except Exception:
                        pass
                    return
                except Exception:
                    # receive_json failed (maybe not JSON). Try to get raw text and parse it.
                    try:
                        raw = await asyncio.wait_for(websocket.receive_text(), timeout=1)
                        logging.debug("websocket_handler: received raw text payload: %s", raw)
                        try:
                            data = json.loads(raw)
                        except Exception:
                            await send_error(websocket, "invalid json payload")
                            continue
                    except asyncio.TimeoutError:
                        await send_error(websocket, "failed to receive payload")
                        continue
                    except Exception:
                        await send_error(websocket, "failed to receive payload")
                        continue
            except Exception:
                await send_error(websocket, "unexpected receive error")
                continue

            if not isinstance(data, dict):
                await send_error(websocket, "payload must be a JSON object")
                continue

            cmd = data.get("cmd")

            # 1) ping
            if cmd == "ping":
                logging.debug("websocket_handler: ping received from uid=%s chat=%s", str(uid), str(chat_oid))
                try:
                    await websocket.send_text(json.dumps({"cmd": "pong"}, ensure_ascii=False))
                except Exception:
                    pass
                continue

            # 2) send message (behave like POST /messages)
            if cmd == "send" or cmd == "send_message":
                text = data.get("text") or data.get("content")
                parent_id = data.get("parent_id")
                if not text or not isinstance(text, str):
                    await send_error(websocket, "text is required")
                    continue

                # check chat lock atomically: if locked, reject the send
                try:
                    # attempt to acquire lock only if not already locked
                    acquired = await chats_col.find_one_and_update(
                        {"_id": chat_oid, "locked": False},
                        {"$set": {"locked": True}}
                    )
                    if acquired is None:
                        await send_error(websocket, "Chat is locked for processing")
                        continue
                except Exception:
                    # if we can't check the lock for any reason, proceed but log
                    try:
                        logging.exception("websocket_handler: failed to check/acquire chat lock")
                    except Exception:
                        pass

                # resolve parent if provided
                parent_obj = None
                if not parent_id:
                    await send_error(websocket, "parent_id is required")
                    continue
                if parent_id:
                    try:
                        parent_oid = PyObjectId.parse(parent_id) if isinstance(parent_id, str) else parent_id
                        parent_obj = await msgs_col.find_one({"_id": parent_oid})
                    except Exception:
                        parent_obj = None
                    if not parent_obj:
                        await send_error(websocket, "parent_id not found")
                        continue

                # determine branch anchors/cousins similar to REST flow
                if parent_obj is None:
                    branch_anchor = None
                    cousin_left = None
                    cousin_right = None
                else:
                    if parent_obj.get("children_ids") == []:
                        branch_anchor = parent_obj.get("branch_anchor")
                        cousin_left = parent_obj.get("cousin_left")
                    else:
                        branch_anchor = parent_obj.get("_id")
                        cousin_left = parent_obj.get("children_ids")[-1] if parent_obj.get("children_ids") else None
                    cousin_right = parent_obj.get("cousin_right")

                now = datetime.utcnow()
                user_msg = {
                    "_id": PyObjectId.new(),
                    "chat_id": chat_oid,
                    "parent_id": parent_obj.get("_id") if parent_obj else None,
                    "children_ids": [],
                    "path": list(parent_obj.get("path", [])) + [parent_obj.get("_id")] if parent_obj else [],
                    "branch_anchor": branch_anchor,
                    "cousin_left": cousin_left,
                    "cousin_right": cousin_right,
                    "sender_id": PyObjectId.parse(uid) if isinstance(uid, str) else uid,
                    "role": "user",
                    "content": text,
                    "content_type": "text",
                    "status": "queued",
                    "tokens_used": None,
                    "created_at": now,
                }

                try:
                    # reuse existing service to insert and broadcast
                    logging.info("websocket_handler: processing send command uid=%s chat=%s parent_id=%s text_preview=%s",
                                 str(uid), str(chat_oid), str(parent_id), (text or '')[:120])
                    msg_id = await process_user_message(chat_oid, user_msg, manager=manager)
                    logging.info("websocket_handler: processed send command uid=%s chat=%s result=%s", str(uid), str(chat_oid), str(getattr(msg_id, '_id', msg_id)))
                    # process_user_message returns the original message object in current implementation
                    # ack/broadcast is handled by send_message via the manager; do not send here
                except Exception as e:
                    logging.exception("websocket_handler: failed to process send command")
                    await send_error(websocket, str(e))
                continue

            # 2b) client-requested close/disconnect
            if cmd in ("close", "disconnect"):
                logging.info("websocket_handler: close requested by uid=%s chat=%s", str(uid), str(chat_oid))
                try:
                    # notify client we're closing
                    await websocket.send_text(json.dumps({"cmd": "closing", "reason": "client_requested"}, ensure_ascii=False))
                except Exception:
                    pass
                # ensure we remove from manager and then close
                try:
                    if manager is not None:
                        manager.disconnect(chat_oid, websocket)
                except Exception:
                    logging.exception("websocket_handler: error while disconnecting before close for chat=%s uid=%s", str(chat_oid), str(uid))
                try:
                    await websocket.close()
                except Exception:
                    logging.exception("websocket_handler: error while closing websocket after client-requested close for chat=%s uid=%s", str(chat_oid), str(uid))
                return

            # 3) fetch history from top (use build_history_from_message_top)
            if cmd == "fetch_from_top":
                mid = data.get("id")
                limit = int(data.get("limit") or 16)
                direction = data.get("direction") or RIGHT
                logging.info("websocket_handler: fetch_from_top requested id=%s limit=%s direction=%s by uid=%s", str(mid), limit, direction, str(uid))
                if not mid:
                    await send_error(websocket, "id is required")
                    continue
                try:
                    # call the existing function (it expects id object or string)
                    hist = await build_history_from_message_top(mid, limit=limit, direction=direction)
                    env = {"cmd": "history", "history": hist}
                    await websocket.send_text(json.dumps(env, default=str, ensure_ascii=False))
                except Exception as e:
                    logging.exception("websocket_handler: fetch_from_top failed")
                    await send_error(websocket, str(e))
                continue

            # 4) fetch history from bottom (ancestors)
            if cmd == "fetch_from_bottom":
                mid = data.get("id")
                limit = int(data.get("limit") or 16)
                logging.info("websocket_handler: fetch_from_bottom requested id=%s limit=%s by uid=%s", str(mid), limit, str(uid))
                if not mid:
                    await send_error(websocket, "id is required")
                    continue
                try:
                    hist = await build_history_from_message_bottom(mid, limit=limit)
                    env = {"cmd": "history", "history": hist}
                    await websocket.send_text(json.dumps(env, default=str, ensure_ascii=False))
                except Exception as e:
                    logging.exception("websocket_handler: fetch_from_bottom failed")
                    await send_error(websocket, str(e))
                continue

            # 5) get a single message
            if cmd == "get":
                mid = data.get("id")
                logging.info("websocket_handler: get requested id=%s by uid=%s", str(mid), str(uid))
                if not mid:
                    await send_error(websocket, "id is required")
                    continue
                try:
                    doc = await msgs_col.find_one({"_id": PyObjectId.parse(mid)})
                    out = _sanitize_msg_for_out(doc)
                    env = {"cmd": "message", "message": out}
                    await websocket.send_text(json.dumps(env, default=str, ensure_ascii=False))
                except Exception:
                    logging.exception("websocket_handler: get failed")
                    await send_error(websocket, "failed to get message")
                continue

            # unknown command
            logging.warning("websocket_handler: unknown cmd received: %s from uid=%s", str(cmd), str(uid))
            await send_error(websocket, f"unknown cmd: {cmd}")

    except Exception:
        logging.exception("Error in websocket_handler")
        raise

async def build_history_from_message_top(first_msg_id, limit=16, direction=RIGHT):
    """Build a message history tree centered around first_msg_id.

    Args:
        first_msg_id (str): The ID of the first message.
        limit (int): The maximum number of messages to retrieve.
        direction (tuple): The direction to build the history (LEFT, RIGHT).

    Returns:
        dict: A dictionary containing the message history.
    """
    msgs_col = get_message_collection()

    # normalize id if a string was provided
    try:
        key = PyObjectId.parse(first_msg_id) if isinstance(first_msg_id, str) else first_msg_id
    except Exception:
        key = first_msg_id

    # Fetch the target message
    target_msg = await msgs_col.find_one({"_id": key})
    if not target_msg:
        raise ValueError("Message not found")

    # Build ancestors
    descendents = []
    current = target_msg
    for _ in range(limit):
        if not current.get("children_ids") or len(current.get("children_ids")) == 0:
            break
        if direction == LEFT:
            child_id = current["children_ids"][0]
        else:
            child_id = current["children_ids"][-1]
        try:
            # normalize child id
            try:
                child_key = PyObjectId.parse(child_id) if isinstance(child_id, str) else child_id
            except Exception:
                child_key = child_id
            child = await msgs_col.find_one({"_id": child_key})
            descendents.append(child)
            current = child
        except Exception:
            break

    # Build the "tree" as a list of parsed messages (ids as strings, datetimes iso)
    def _parse_msg(m):
        parsed = dict(m)
        # Normalize id fields to strings where present
        if parsed.get("_id") is not None:
            parsed["_id"] = str(parsed["_id"])
        if parsed.get("parent_id") is not None:
            parsed["parent_id"] = str(parsed["parent_id"])
        # children_ids may be stored as ObjectIds; convert to strings
        if isinstance(parsed.get("children_ids"), list):
            parsed["children_ids"] = [str(c) for c in parsed["children_ids"]]
        # created_at -> isoformat if datetime-like
        ca = parsed.get("created_at")
        if hasattr(ca, "isoformat"):
            try:
                parsed["created_at"] = ca.isoformat()
            except Exception:
                pass
        return parsed

    chain = [target_msg] + descendents
    res = [_parse_msg(m) for m in chain]

    return {"Result": res}

async def build_history_from_message_bottom(last_msg_id, limit=16):
    """Build a message history tree centered around last_msg_id.

    This function retrieves messages from the database to construct a
    structure of messages, including ancestors up to ancestor_limit levels.
    The total number of nodes is capped at max_nodes.

    Returns a dict with 'tree' and 'recent' keys.
    """
    msgs_col = get_message_collection()

    # normalize id if a string was provided
    try:
        key = PyObjectId.parse(last_msg_id) if isinstance(last_msg_id, str) else last_msg_id
    except Exception:
        key = last_msg_id

    # Fetch the target message
    target_msg = await msgs_col.find_one({"_id": key})
    if not target_msg:
        raise ValueError("Message not found")

    # Build ancestors
    ancestors = []
    current = target_msg
    for _ in range(limit):
        if not current.get("parent_id"):
            break
        try:
            parent_key = PyObjectId.parse(current.get("parent_id")) if isinstance(current.get("parent_id"), str) else current.get("parent_id")
        except Exception:
            parent_key = current.get("parent_id")
        parent = await msgs_col.find_one({"_id": parent_key})
        if not parent:
            break
        ancestors.append(parent)
        current = parent
    ancestors.reverse()

    # Build the "tree" as a list of parsed messages (ids as strings, datetimes iso)
    def _parse_msg(m):
        parsed = dict(m)
        # Normalize id fields to strings where present
        if parsed.get("_id") is not None:
            parsed["_id"] = str(parsed["_id"])
        if parsed.get("parent_id") is not None:
            parsed["parent_id"] = str(parsed["parent_id"])
        # children_ids may be stored as ObjectIds; convert to strings
        if isinstance(parsed.get("children_ids"), list):
            parsed["children_ids"] = [str(c) for c in parsed["children_ids"]]
        # created_at -> isoformat if datetime-like
        ca = parsed.get("created_at")
        if hasattr(ca, "isoformat"):
            try:
                parsed["created_at"] = ca.isoformat()
            except Exception:
                pass
        return parsed

    chain = ancestors + [target_msg]
    res = [_parse_msg(m) for m in chain]

    return {"Result": res}