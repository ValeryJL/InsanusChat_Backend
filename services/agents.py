import asyncio
from datetime import datetime
from typing import Any, Dict

from fastapi import logger
from models import PyObjectId
from database import get_message_collection, get_chat_collection, get_user_collection



async def run_agent(chat_oid, message_id):
    """
    Placeholder runner for an agent.

    - chat_oid: PyObjectId
    - message_id: PyObjectId del mensaje original del usuario

    This function simulates agent processing, updates the original message status,
    creates a response message from the agent returns it.
    """
    
    msgs_col = get_message_collection()
    chats_col = get_chat_collection()
    user_col = get_user_collection()
    try:
        chat_doc = await chats_col.find_one({"_id": chat_oid})
    except Exception as e:
        raise Exception("Chat not found") from e
    if not chat_doc:
        raise Exception("Chat not found")
    tools = []
    try:
        tools_ids = chat_doc.get("active_tools", []) or []
        # cargar una vez el documento del owner (si existe) para resolver embedded tools/agents
        owner_id = chat_doc.get("owner_id")
        user_doc = None
        if owner_id:
            try:
                user_doc = await user_col.find_one({"_id": owner_id}, {"mcps": 1, "code_snippets": 1, "agents": 1})
            except Exception:
                user_doc = None

        # indexar listas embebidas por id-string para lookup O(1)
        def index_by_id(lst):
            out = {}
            for it in lst or []:
                try:
                    out[str(it.get("_id"))] = it
                except Exception:
                    pass
            return out

        mcps_map = index_by_id(user_doc.get("mcps", [])) if user_doc else {}
        code_map = index_by_id(user_doc.get("code_snippets", [])) if user_doc else {}

        for tid in tools_ids:
            tid_s = str(tid)
            if tid_s in mcps_map:
                tools.append(mcps_map[tid_s]); continue
            if tid_s in code_map:
                tools.append(code_map[tid_s]); continue
            # intentar forma ObjectId
            try:
                pid = PyObjectId.parse(tid)
                pid_s = str(pid)
            except Exception:
                pid = None
                pid_s = None
            if pid_s and pid_s in mcps_map:
                tools.append(mcps_map[pid_s]); continue
            if pid_s and pid_s in code_map:
                tools.append(code_map[pid_s]); continue
            # si no se resolvió, loguear y continuar (no romper toda la ejecución)
            # (Opcional: aquí puedes añadir batch-queries a colecciones separadas si existen)
            # logger.warn(f"Tool {tid} not resolved from owner embedded lists")
            logger.warn(f"Tool {tid} not found")
    except Exception:
        pass
    # resolver agente embebido en el mismo user_doc (si existe)
    try:
        raw_agent = chat_doc.get("agent_id")
        agent_id = None
        if raw_agent is not None:
            try:
                agent_id = PyObjectId.parse(raw_agent) if isinstance(raw_agent, str) else raw_agent
            except Exception:
                agent_id = raw_agent
        agent_obj = None
        if user_doc:
            for a in user_doc.get("agents", []) or []:
                if str(a.get("_id")) == str(agent_id):
                    agent_obj = a
                    break
        # fallback: try to load agents from user_col if not embedded (best-effort)
        if not agent_obj and owner_id:
            try:
                owner_doc = await user_col.find_one({"_id": owner_id}, {"agents": 1})
                for a in owner_doc.get("agents", []) or []:
                    if str(a.get("_id")) == str(agent_id):
                        agent_obj = a; break
            except Exception:
                pass
    except Exception:
        agent_obj = None
    try:
        message_doc = await msgs_col.find_one({"_id": message_id})
    except Exception:
        raise Exception("Message not found")
    if not message_doc:
        raise Exception("Message not found")
    try:
        # mark original message as processing in messages collection
        await msgs_col.update_one({"_id": message_doc["_id"]}, {"$set": {"status": "processing"}})

        # simulate work
        await asyncio.sleep(0.1)

        user_text = message_doc.get("content") or message_doc.get("text") or ""
        # incorporate a short representation of history into the simulated response for testing
                
        # TODO: implement build history based on agents context window

        # TODO: implement real agent logic here, considering agent_obj configuration, history, tools, etc.
        
        # simulate agent output (replace with real SDK call)
        agent_text = f"[AGENT RESPONSE] Procesado por agent {agent_id or 'default'}: {user_text}"

        now = datetime.utcnow()
        response_doc = {
            "_id": PyObjectId.new(),
            "chat_id": chat_oid,
            "parent_id": message_doc["_id"],
            "children_ids": [],
            "path": list(message_doc.get("path", [])) + [message_doc["_id"]],
            "branch_anchor": message_doc.get("branch_anchor") if message_doc.get("children_ids", []) == [] else message_doc["_id"],
            "cousin_left": message_doc.get("children_ids", [])[-1] if len(message_doc.get("children_ids", [])) > 1 else message_doc.get("cousin_left"),
            "cousin_right": message_doc.get("cousin_right"),
            "sender_id": PyObjectId.parse(agent_id) if isinstance(agent_id, str) else agent_id,
            "role": "agent",
            "content": agent_text,
            "content_type": "text",
            "tokens_used": None,
            "status": "done",
            "created_at": now,
        }

        await msgs_col.update_one({"_id": message_doc["_id"]}, {"$set": {"status": "done"}})

        return response_doc
    except Exception:
        # try to mark message as failed and ensure chat unlocked
        try:
            await msgs_col.update_one({"_id": message_doc["_id"]}, {"$set": {"status": "failed"}})
        except Exception:
            pass
        try:
            await chats_col.update_one({"_id": chat_oid}, {"$set": {"locked": False}})
        except Exception:
            pass