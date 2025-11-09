import asyncio
from datetime import datetime
from typing import Any, Dict, List

import logging

from models import PyObjectId
from database import get_message_collection, get_chat_collection, get_user_collection
from services.mcp_helpers import validate_mcp_entry, build_connect_and_run_params
from services.mcp_client import MCPClient
from services.snippets import execute_snippet

logger = logging.getLogger(__name__)

async def _minify_msg_for_history(msg: dict) -> dict:
    """Return only the minimal fields for agent history and make them JSON-serializable.

    Fields kept: role, parent_id, children_ids, content, content_type.
    ObjectIds and datetimes are converted to strings when possible.
    """
    if not msg:
        return {}
    def _conv(v):
        if v is None:
            return None
        try:
            # datetime
            if hasattr(v, "isoformat") and not isinstance(v, str):
                try:
                    return v.isoformat()
                except Exception:
                    pass
            # ObjectId or other id-like
            try:
                return str(v)
            except Exception:
                return v
        except Exception:
            return v

    return {
        "role": msg.get("role"),
        "parent_id": _conv(msg.get("parent_id")),
        "children_ids": [_conv(c) for c in (msg.get("children_ids") or [])],
        "content": msg.get("content") or msg.get("text"),
        "content_type": msg.get("content_type"),
    }


async def build_history_for_agent(
    chat_oid,
    anchor_msg_id=None,
    max_messages: int = 30,
    direction: str = "both",  # "ancestors", "descendants", "both", "last"
) -> List[dict]:
    """Build a minimal history for the agent.

    - If anchor_msg_id is None returns the last `max_messages` messages of the chat.
    - If anchor provided, returns ancestors + anchor + descendants according to `direction`.
    """
    msgs_col = get_message_collection()

    async def _get(mid):
        try:
            return await msgs_col.find_one({"_id": mid})
        except Exception:
            return None

    # Fallback: last N messages by created_at
    if anchor_msg_id is None:
        cursor = msgs_col.find({"chat_id": chat_oid}).sort("created_at", -1).limit(max_messages)
        docs = [d async for d in cursor]
        docs.reverse()
        return [await _minify_msg_for_history(d) for d in docs]

    # With anchor
    anchor = await _get(anchor_msg_id)
    if not anchor:
        return []

    anc = []
    desc = []

    if direction in ("ancestors", "both"):
        cur = anchor
        max_anc = max_messages // 2 if direction == "both" else max_messages
        while cur and len(anc) < max_anc:
            parent_id = cur.get("parent_id")
            if not parent_id:
                break
            parent = await _get(parent_id)
            if not parent:
                break
            anc.insert(0, parent)
            cur = parent

    if direction in ("descendants", "both"):
        queue = [anchor]
        max_desc = max_messages - len(anc) - 1
        while queue and len(desc) < max_desc:
            node = queue.pop(0)
            for cid in node.get("children_ids", []) or []:
                child = await _get(cid)
                if child:
                    desc.append(child)
                    queue.append(child)
                    if len(desc) >= max_desc:
                        break

    ordered = anc + [anchor] + desc
    if len(ordered) > max_messages:
        ordered = ordered[-max_messages:]
    return [await _minify_msg_for_history(d) for d in ordered]

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
    owner_id = None
    user_doc = None
    agent_id = None
    try:
        tools_ids = chat_doc.get("active_tools", []) or []
        # cargar una vez el documento del owner (si existe) para resolver embedded tools/agents
        owner_id = chat_doc.get("owner_id")
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
            resolved = None
            # direct match against embedded lists
            if tid_s in mcps_map:
                resolved = mcps_map[tid_s]
                # validate and build connect params
                try:
                    mcp_valid = validate_mcp_entry(resolved)
                    connect_info = build_connect_and_run_params(mcp_valid)
                    tools.append({"type": "mcp", "id": tid_s, "name": mcp_valid.name, "raw": resolved, "connect": connect_info})
                    continue
                except Exception as e:
                    logger.warning("MCP entry %s validation failed: %s", tid_s, e)
                    tools.append({"type": "mcp", "id": tid_s, "name": resolved.get("name"), "raw": resolved, "connect": None, "error": str(e)})
                    continue
            if tid_s in code_map:
                snippet = code_map[tid_s]
                # minimal validation: language and code
                lang = snippet.get("language")
                code = snippet.get("code")
                if not lang or not code:
                    logger.warning("Snippet %s missing language/code", tid_s)
                    tools.append({"type": "snippet", "id": tid_s, "raw": snippet, "valid": False})
                else:
                    tools.append({"type": "snippet", "id": tid_s, "name": snippet.get("name"), "language": lang, "code": code, "raw": snippet, "valid": True})
                continue

            # intentar forma ObjectId
            try:
                pid = PyObjectId.parse(tid)
                pid_s = str(pid)
            except Exception:
                pid = None
                pid_s = None
            if pid_s and pid_s in mcps_map:
                try:
                    mcp_valid = validate_mcp_entry(mcps_map[pid_s])
                    connect_info = build_connect_and_run_params(mcp_valid)
                    tools.append({"type": "mcp", "id": pid_s, "name": mcp_valid.name, "raw": mcps_map[pid_s], "connect": connect_info})
                    continue
                except Exception as e:
                    logger.warning("MCP entry %s validation failed: %s", pid_s, e)
                    tools.append({"type": "mcp", "id": pid_s, "raw": mcps_map[pid_s], "connect": None, "error": str(e)})
                    continue
            if pid_s and pid_s in code_map:
                snippet = code_map[pid_s]
                lang = snippet.get("language")
                code = snippet.get("code")
                if not lang or not code:
                    logger.warning("Snippet %s missing language/code", pid_s)
                    tools.append({"type": "snippet", "id": pid_s, "raw": snippet, "valid": False})
                else:
                    tools.append({"type": "snippet", "id": pid_s, "name": snippet.get("name"), "language": lang, "code": code, "raw": snippet, "valid": True})
                continue

            # si no se resolvió, loguear y continuar (no romper toda la ejecución)
            logger.warning("Tool %s not found in embedded lists", tid)
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
                if owner_doc:
                    for a in owner_doc.get("agents", []) or []:
                        if str(a.get("_id")) == str(agent_id):
                            agent_obj = a
                            break
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

        

        user_text = message_doc.get("content") or message_doc.get("text") or ""
        # build minimal history for the agent (anchor at incoming message)
        try:
            history = await build_history_for_agent(chat_oid, anchor_msg_id=message_doc["_id"], max_messages=20, direction="ancestors")
        except Exception:
            history = []

        # produce a short history preview for the simulated response (for debugging)
        try:
            history_preview = " | ".join(f"{h.get('role')}: {(h.get('content') or '')[:80]}" for h in history)
        except Exception:
            history_preview = ""

        # 1) Enrich MCP tools by connecting to the MCP servers and calling `list_tools()`
        async def enrich_tools_with_server_info(tools_list: List[dict]):
            for t in tools_list:
                if t.get("type") != "mcp":
                    continue
                connect = t.get("connect")
                if not connect:
                    t["server_tools"] = []
                    continue
                # attempt to connect to the MCP server; be defensive if SDK not installed
                client = MCPClient()
                try:
                    # build params
                    server_script = connect.get("server_script_path") or ""
                    cmd = connect.get("command")
                    args = connect.get("args")
                    env = connect.get("env")
                    # try to connect (may raise if mcp package not present)
                    await client.connect_to_server(server_script, command=cmd, args=args, env=env)
                    try:
                        resp = await client.list_tools()
                        # normalize tools from resp when possible
                        server_tools = []
                        tools_attr = getattr(resp, 'tools', None) or resp or []
                        for st in tools_attr:
                            name = getattr(st, 'name', None) or (st.get('name') if isinstance(st, dict) else None)
                            desc = getattr(st, 'description', None) or (st.get('description') if isinstance(st, dict) else None)
                            input_schema = getattr(st, 'inputSchema', None) or (st.get('inputSchema') if isinstance(st, dict) else None)
                            server_tools.append({"name": name, "description": desc, "input_schema": input_schema})
                        t["server_tools"] = server_tools
                    except Exception:
                        t["server_tools"] = []
                except Exception as e:
                    logger.warning("Could not connect to MCP server for tool %s: %s", t.get("id"), e)
                    t["server_tools"] = []
                finally:
                    try:
                        await client.close()
                    except Exception:
                        pass

        await enrich_tools_with_server_info(tools)

        # 2) Mocked LLM loop: simple deterministic mock that decides to call a tool or return final text.
        # The mock looks for keywords and available server tools/snippets. In a real implementation
        # this would call Anthropic/Claude and handle tool_use content blocks.
        def mock_llm_decide(user_text: str, available_tools: List[dict], messages: List[dict]):
            # if any server tool name contains 'weather' and user asks about weather -> call it
            lower = (user_text or "").lower()
            for t in available_tools:
                if t.get("type") == "mcp":
                    for st in t.get("server_tools", []) or []:
                        nm = (st.get("name") or "").lower()
                        if "weather" in nm and ("weather" in lower or "temperature" in lower):
                            return {"type": "tool_use", "name": st.get("name"), "tool_owner": t, "input": {"location": "Buenos Aires"}}
                if t.get("type") == "snippet":
                    # if user asks to 'run' or 'execute' and snippet name appears
                    nm = (t.get("name") or "").lower()
                    if nm and nm in lower and ("run" in lower or "execute" in lower or "use" in lower):
                        return {"type": "tool_use", "name": t.get("id"), "snippet": t, "input": {}}
            # default: return a final text echoing intent
            return {"type": "text", "text": f"(mock) Respuesta final para: {user_text[:200]}"}

        # conversation messages (we keep them minimal for the mock)
        convo_messages = []
        convo_messages.extend(history)

        final_text = None
        loop_count = 0
        while True:
            loop_count += 1
            if loop_count > 6:
                final_text = "(mock) Aborting after too many iterations"
                break
            decision = mock_llm_decide(user_text, tools, convo_messages)
            if decision.get("type") == "text":
                final_text = decision.get("text")
                break
            if decision.get("type") == "tool_use":
                # execute the requested tool
                if decision.get("snippet"):
                    sn = decision.get("snippet")
                    # run snippet via services.snippets
                    if isinstance(sn, dict):
                        try:
                            res = await execute_snippet({"language": sn.get("language"), "code": sn.get("code")}, input_data=decision.get("input"), timeout=10)
                            result_content = res
                        except Exception as e:
                            result_content = {"success": False, "error": str(e)}
                    else:
                        result_content = {"success": False, "error": "invalid_snippet"}
                else:
                    # mcp tool invocation: find owner and call via MCPClient
                    owner_tool = decision.get("tool_owner")
                    # owner_tool might be a dict with 'connect' or a plain string/id; guard attribute access
                    if isinstance(owner_tool, dict):
                        connect = owner_tool.get("connect")
                    else:
                        connect = None
                    if not connect:
                        result_content = {"success": False, "error": "no_connect_info"}
                    else:
                        client = MCPClient()
                        try:
                            await client.connect_to_server(connect.get("server_script_path") or "", command=connect.get("command"), args=connect.get("args"), env=connect.get("env"))
                            # call tool on server; this uses MCPClient.call_tool which adapts to SDK
                            try:
                                tool_name = decision.get("name")
                                # ensure name is a str for call_tool
                                if tool_name is None:
                                    raise ValueError("missing tool name")
                                if not isinstance(tool_name, str):
                                    tool_name = str(tool_name)
                                # normalize input to a dict or None because call_tool expects Dict[str, Any] | None
                                raw_input = decision.get("input")
                                if raw_input is None:
                                    call_args = None
                                elif isinstance(raw_input, dict):
                                    call_args = raw_input
                                else:
                                    # wrap non-dict input into a dict under a generic key
                                    call_args = {"input": raw_input}
                                call_resp = await client.call_tool(tool_name, call_args)
                                result_content = {"success": True, "result": call_resp}
                            except Exception as e:
                                result_content = {"success": False, "error": str(e)}
                        except Exception as e:
                            logger.warning("MCP connect failed for tool %s: %s", decision.get("name"), e)
                            result_content = {"success": False, "error": str(e)}
                        finally:
                            try:
                                await client.close()
                            except Exception:
                                pass

                # inject tool result into convo and continue loop
                convo_messages.append({"role": "tool", "content": result_content})
                # continue to allow LLM to produce final text
                continue
        
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
            "content": final_text,
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