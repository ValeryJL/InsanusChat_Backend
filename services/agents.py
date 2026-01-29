import asyncio
import logging
import os
import json
import httpx
from datetime import datetime
from typing import List, Optional, Any, Dict

from models import PyObjectId
from database import get_message_collection, get_chat_collection, get_user_collection
from services.mcp_helpers import validate_mcp_entry, build_connect_params
from services.mcp_client import MCPClient
from services.snippets import execute_snippet

logger = logging.getLogger(__name__)

async def _build_history(chat_oid, max_messages: int = 15) -> List[dict]:
    msgs_col = get_message_collection()
    cursor = msgs_col.find({"chat_id": chat_oid}).sort("created_at", -1).limit(max_messages)
    docs = [d async for d in cursor]
    docs.reverse()
    out = []
    for d in docs:
        out.append({
            "role": d.get("role") or "user",
            "content": d.get("content") or d.get("text") or "",
        })
    return out

async def run_agent(chat_oid, message_id):
    """
    Master Runner for agents.
    Integrates Gemini (LangChain), MCP Tools and Code Snippets.
    """
    msgs_col = get_message_collection()
    chats_col = get_chat_collection()
    users_col = get_user_collection()

    try:
        chat_doc = await chats_col.find_one({"_id": chat_oid})
        message_doc = await msgs_col.find_one({"_id": message_id})
        if not chat_doc or not message_doc: return None
    except Exception as e:
        logger.error(f"Error loading docs: {e}")
        return None

    owner_id = chat_doc.get("owner_id") or chat_doc.get("user_id")
    user_doc = None
    agent_obj = None
    
    if owner_id:
        try:
            if isinstance(owner_id, str): owner_id = PyObjectId.parse(owner_id)
            user_doc = await users_col.find_one({"_id": owner_id})
        except Exception: pass

    if user_doc:
        raw_agent = chat_doc.get("agent_id")
        for a in user_doc.get("agents", []) or []:
            if str(a.get("_id")) == str(raw_agent):
                agent_obj = a
                break

    def _find_api_key(provider_name: str) -> Optional[str]:
        keys = user_doc.get("api_keys", []) if user_doc else []
        for k in keys:
            if not isinstance(k, dict): continue
            p = str(k.get("provider", "")).lower()
            if p in (provider_name.lower(), "google", "gemini"):
                return k.get("encrypted_key")
        return os.environ.get("GOOGLE_API_KEY")

    gemini_key = _find_api_key("gemini")
    user_text = message_doc.get("content") or ""
    
    # 1. Resolve Tools
    tools_to_bind = []
    mcp_tool_map = {} # tool_name -> (mcp_id, connect_params, real_tool_name)
    snippet_tool_map = {} # tool_name -> (snippet_id, language, code)

    if agent_obj and user_doc:
        # MCP tools
        mcps_map = {str(m.get("_id")): m for m in user_doc.get("mcps", []) or []}
        for m_id in agent_obj.get("mcp_ids", []) or []:
            m_id_s = str(m_id)
            if m_id_s in mcps_map:
                try:
                    mentry = validate_mcp_entry(mcps_map[m_id_s])
                    cparams = build_connect_params(mentry)
                    async with MCPClient() as client:
                        await client.connect_to_server(**cparams)
                        server_tools = await client.get_tools()
                        for st in server_tools:
                            tname = f"mcp_{m_id_s}_{st.name}"
                            mcp_tool_map[tname] = (m_id_s, cparams, st.name)
                            tools_to_bind.append({
                                "name": tname,
                                "description": st.description or f"MCP tool {st.name}",
                                "parameters": st.inputSchema
                            })
                except Exception as e:
                    logger.warning(f"Error loading MCP tools for {m_id_s}: {e}")

        # Snippet tools
        snippets_map = {str(s.get("_id")): s for s in user_doc.get("snippets", []) or []}
        for s_id in agent_obj.get("snippet_ids", []) or []:
            s_id_s = str(s_id)
            if s_id_s in snippets_map:
                s = snippets_map[s_id_s]
                tname = f"snippet_{s_id_s}"
                snippet_tool_map[tname] = (s_id_s, s.get("language"), s.get("code"))
                tools_to_bind.append({
                    "name": tname,
                    "description": f"Execute Python/JS snippet: {s.get('name') or s_id_s}",
                    "parameters": {"type": "object", "properties": {"input_data": {"type": "string"}}}
                })

    # 2. Setup Gemini
    final_text = ""
    if gemini_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
            
            model_name = agent_obj.get("model_selected") or "gemini-flash-latest" if agent_obj else "gemini-flash-latest"
            model = ChatGoogleGenerativeAI(google_api_key=gemini_key, model=model_name, temperature=0.7)
            if tools_to_bind:
                model = model.bind_tools(tools_to_bind)

            history = await _build_history(chat_oid)
            messages = []
            if agent_obj and agent_obj.get("system_prompt"):
                messages.append(SystemMessage(content=str(agent_obj["system_prompt"])))
            
            for h in history:
                r = h["role"].lower()
                c = h["content"] or ""
                if r in ("assistant", "agent"): messages.append(AIMessage(content=c))
                elif r == "system": messages.append(SystemMessage(content=c))
                else: messages.append(HumanMessage(content=c))
            
            if not messages or (messages[-1].content != user_text):
                messages.append(HumanMessage(content=user_text))

            # 3. Execution Loop
            for _ in range(5):
                res = await asyncio.to_thread(model.invoke, messages)
                messages.append(res)
                
                if not getattr(res, "tool_calls", None):
                    final_text = res.content
                    break
                
                for tc in res.tool_calls:
                    tname = tc["name"]
                    targs = tc["args"]
                    tcall_id = tc["id"]
                    
                    result_content = "Tool not found"
                    if tname in mcp_tool_map:
                        mid, cp, real_tname = mcp_tool_map[tname]
                        try:
                            async with MCPClient() as client:
                                await client.connect_to_server(**cp)
                                mcp_res = await client.call_tool(real_tname, targs)
                                result_content = str(mcp_res.content)
                        except Exception as e:
                            result_content = f"Error calling MCP tool: {e}"
                    elif tname in snippet_tool_map:
                        sid, lang, code = snippet_tool_map[tname]
                        try:
                            py_res = await execute_snippet(lang, code, payload=json.dumps(targs))
                            result_content = py_res.get("stdout") or py_res.get("stderr") or "Success (No output)"
                        except Exception as e:
                            result_content = f"Error executing snippet: {e}"
                    
                    messages.append(ToolMessage(content=result_content, tool_call_id=tcall_id))
            
        except Exception as e:
            logger.error(f"Gemini Execution Error: {e}")
            final_text = f"Error en la ejecución: {str(e)}"

    if not final_text:
        final_text = "No se pudo obtener una respuesta de Gemini."

    # 4. Save Response
    response_doc = {
        "_id": PyObjectId.new(),
        "chat_id": chat_oid,
        "parent_id": message_doc["_id"],
        "children_ids": [],
        "path": list(message_doc.get("path", [])) + [message_doc["_id"]],
        "sender_id": PyObjectId.parse(agent_obj["_id"]) if agent_obj else None,
        "role": "agent",
        "content": final_text,
        "content_type": "text",
        "status": "done",
        "created_at": datetime.utcnow(),
    }
    return response_doc
