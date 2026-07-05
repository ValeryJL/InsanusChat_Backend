"""
Motor de Agentes Basado en Primitivas Nativas de LangChain v1.5 & LangGraph:
1. `init_chat_model` (`langchain.chat_models`) — Inicialización unificada multi-proveedor (`google_genai`, `openai`, `anthropic`).
2. `create_agent` (`langchain.agents`) — Grafo de estado ReAct compilado (`CompiledStateGraph`) que orquesta llamadas a herramientas MCP y Snippets (`StructuredTool`), memoria de turno y reintentos.
3. `.astream_events(..., version="v2")` — Streaming asíncrono nativo de eventos (`on_chat_model_stream`, `on_tool_start`, `on_tool_end`) conectados en vivo al WebSocket del chat.
4. `UsageMetadataCallbackHandler` (`langchain_core.callbacks`) — Contabilidad exacta de tokens (`input_tokens`, `output_tokens`, `reasoning`, `total_tokens`) a través de todos los pasos del agente.
5. `trim_messages` (`langchain_core.messages`) — Recorte seguro de ventana de contexto sobre la rama activa del árbol (`_build_branch_history`).
6. `.with_fallbacks([...])` (`RunnableWithFallbacks`) & cadenas LCEL (`ChatPromptTemplate | model | StrOutputParser`) — Respaldo automático ante errores `429 Quota Exceeded` y autogeneración de títulos de conversación.
"""
import asyncio
from datetime import datetime
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage, trim_messages
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from auth.crypto import decrypt_api_key
from database import ensure_system_settings, get_chat_collection, get_message_collection, get_user_collection
from models import PyObjectId
from services.harness_tools import build_harness_langchain_tools, build_workspace_context_prompt
from services.langchain_tools import load_mcp_tools, load_snippet_tools
from services.snippets import expand_system_prompt_snippets
from utils.model_utils import infer_provider_from_model, normalize_provider

logger = logging.getLogger(__name__)


async def _build_branch_history(chat_oid: Any, message_id: Any, max_messages: int = 30) -> List[Dict[str, Any]]:
    """
    HU-02: Reconstruye el historial de conversación caminando EXCLUSIVAMENTE
    por la cadena de ancestros (`parent_id`) de la rama activa hasta `message_id`.
    Nunca mezcla mensajes de ramas hermanas o primas.
    """
    msgs_col = get_message_collection()
    chain: List[Dict[str, Any]] = []

    curr_id = message_id
    visited = set()

    for _ in range(max_messages):
        if not curr_id:
            break
        try:
            oid = PyObjectId.parse(curr_id) if isinstance(curr_id, str) else curr_id
        except Exception:
            oid = curr_id

        str_id = str(oid)
        if str_id in visited:
            break
        visited.add(str_id)

        doc = await msgs_col.find_one({"_id": oid})
        if not doc:
            break

        chain.append(
            {
                "_id": str(doc.get("_id")),
                "role": doc.get("role") or "user",
                "content": doc.get("content") or doc.get("text") or "",
                "parent_id": str(doc.get("parent_id")) if doc.get("parent_id") else None,
            }
        )
        curr_id = doc.get("parent_id")

    chain.reverse()
    return chain


def _resolve_provider_and_key(
    user_doc: Optional[Dict[str, Any]],
    agent_obj: Optional[Dict[str, Any]],
    chat_doc: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str, Optional[str], Optional[str]]:
    """
    Determina (provider, model_name, plain_api_key, base_url) para el agente.
    Descifra la API key en memoria usando `decrypt_api_key`.
    """
    chat_model = chat_doc.get("model_selected") if chat_doc else None
    model_name = chat_model or (agent_obj.get("model_selected") if agent_obj else None) or "gemini-2.5-flash"
    if model_name in ("gemini-pro", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-flash-latest") or "-tts" in model_name.lower():
        model_name = "gemini-2.5-flash"

    provider = normalize_provider(
        infer_provider_from_model(model_name)
        if chat_model
        else ((agent_obj.get("provider") if agent_obj else None) or infer_provider_from_model(model_name))
    )
    api_keys = (user_doc.get("api_keys") or []) if user_doc else []

    preferred_key_id = str(agent_obj.get("api_key_id")) if (agent_obj and agent_obj.get("api_key_id")) else None
    if preferred_key_id:
        for k in api_keys:
            if isinstance(k, dict) and str(k.get("_id")) == preferred_key_id and k.get("active", True):
                raw_enc = k.get("encrypted_key") or ""
                plain = decrypt_api_key(raw_enc)
                k_prov = normalize_provider(k.get("provider") or provider)
                return k_prov, model_name, plain, k.get("base_url")

    for k in api_keys:
        if not isinstance(k, dict) or not k.get("active", True):
            continue
        k_prov = normalize_provider(k.get("provider"))
        if k_prov == provider:
            plain = decrypt_api_key(k.get("encrypted_key") or "")
            if plain:
                return provider, model_name, plain, k.get("base_url")

    env_map = {
        "gemini": os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"),
        "openai": os.environ.get("OPENAI_API_KEY"),
        "anthropic": os.environ.get("ANTHROPIC_API_KEY"),
        "openrouter": os.environ.get("OPENROUTER_API_KEY"),
        "ollama": os.environ.get("OLLAMA_API_KEY") or "",
    }
    return provider, model_name, env_map.get(provider), os.environ.get("OLLAMA_BASE_URL")


def _init_langchain_chat_model(
    provider: str,
    model_name: str,
    api_key: str,
    temperature: float = 0.7,
    base_url: Optional[str] = None,
):
    """
    Inicializa un `BaseChatModel` usando la fábrica oficial `init_chat_model` de LangChain.
    Configura timeouts y `max_retries=1` para no bloquear el chat ante errores 429.
    """
    lc_provider_map = {
        "gemini": "google_genai",
        "openai": "openai",
        "anthropic": "anthropic",
        "openrouter": "openai",
        "ollama": "openai",
    }
    lc_provider = lc_provider_map.get(provider, "google_genai")

    # Reducir timeout en modelos experimentales (3.8, 3.7, 4-*) cuyos endpoints en Google a veces quedan colgados
    is_experimental = any(tag in model_name.lower() for tag in ("3.8", "3.7", "4-", "preview", "exp"))
    req_timeout = 10 if is_experimental else 25

    kwargs: Dict[str, Any] = {
        "model_provider": lc_provider,
        "api_key": api_key or ("ollama" if provider == "ollama" else ""),
        "temperature": temperature,
        "max_retries": 0 if is_experimental else 1,
        "timeout": req_timeout,
    }
    if provider == "openrouter":
        kwargs["base_url"] = base_url or "https://openrouter.ai/api/v1"
    elif provider == "ollama":
        kwargs["base_url"] = base_url or "http://host.docker.internal:11434/v1"
    elif base_url:
        kwargs["base_url"] = base_url

    return init_chat_model(model_name, **kwargs)


def _build_trimmed_langchain_messages(
    branch_history: List[Dict[str, Any]],
    user_text: str,
) -> List[BaseMessage]:
    """
    Convierte el historial de la rama activa en objetos `BaseMessage` de LangChain
    y utiliza `trim_messages` de `langchain_core.messages` para garantizar que la
    ventana de contexto empiece siempre en un `HumanMessage` y no exceda el límite.
    """
    raw_messages: List[BaseMessage] = []
    for h in branch_history:
        r = (h.get("role") or "user").lower()
        c = h.get("content") or ""
        if r in ("assistant", "agent"):
            raw_messages.append(AIMessage(content=c))
        elif r == "system":
            raw_messages.append(SystemMessage(content=c))
        else:
            raw_messages.append(HumanMessage(content=c))

    if not raw_messages or raw_messages[-1].content != user_text:
        raw_messages.append(HumanMessage(content=user_text))

    try:
        trimmed = trim_messages(
            raw_messages,
            max_tokens=24,
            strategy="last",
            token_counter=len,  # Cuenta por número de mensajes (últimos 24 turnos de la rama)
            start_on="human",
            include_system=True,
            allow_partial=False,
        )
        return list(trimmed) if trimmed else [HumanMessage(content=user_text)]
    except Exception:
        return raw_messages[-24:]


def _extract_text_from_chunk_content(content: Any) -> str:
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(p.get("text", ""))
            elif isinstance(p, str):
                parts.append(p)
        return "".join(parts)
    return str(content)


def _extract_total_tokens_from_callback(usage_cb: UsageMetadataCallbackHandler, fallback_in: str, fallback_out: str) -> int:
    """Extrae el conteo exacto de tokens reportado por `UsageMetadataCallbackHandler`."""
    total = 0
    for _, meta in (usage_cb.usage_metadata or {}).items():
        if isinstance(meta, dict):
            total += int(meta.get("total_tokens") or 0)
    if total > 0:
        return total
    return max(1, (len(fallback_in or "") + len(fallback_out or "")) // 4)


async def _broadcast_ws(manager: Any, chat_key: str, payload: Dict[str, Any]):
    if manager is not None:
        try:
            await manager.broadcast(chat_key, payload)
        except Exception as e:
            logger.debug("Error broadcasting WS event: %s", e)


async def _execute_Compiled_agent_stream(
    chat_model: Any,
    all_tools: List[Any],
    system_prompt_str: str,
    lc_messages: List[BaseMessage],
    manager: Any,
    chat_key: str,
    stream_msg_id: str,
    parent_id_str: str,
) -> Tuple[str, List[Dict[str, Any]], int]:
    """
    Ejecuta el grafo de agente oficial `create_agent` de LangChain v1.5 con `.astream_events(version="v2")`
    y `UsageMetadataCallbackHandler`, emitiendo cada token y cada ejecución de herramienta por WebSocket.
    """
    usage_cb = UsageMetadataCallbackHandler()
    agent_graph = create_agent(
        model=chat_model,
        tools=all_tools if all_tools else None,
        system_prompt=system_prompt_str if system_prompt_str else None,
    )

    streamed_tokens: List[str] = []
    tool_traces: List[Dict[str, Any]] = []
    pending_tool_inputs: Dict[str, Any] = {}
    final_ai_content = ""

    async for event in agent_graph.astream_events(
        {"messages": lc_messages},
        config={"callbacks": [usage_cb], "recursion_limit": 50},
        version="v2",
    ):
        kind = event.get("event")

        if kind == "on_chat_model_stream":
            chunk = (event.get("data") or {}).get("chunk")
            delta_text = _extract_text_from_chunk_content(getattr(chunk, "content", None))
            if delta_text:
                streamed_tokens.append(delta_text)
                await _broadcast_ws(
                    manager,
                    chat_key,
                    {
                        "cmd": "agent_token",
                        "message": {
                            "message_id": stream_msg_id,
                            "parent_id": parent_id_str,
                            "delta": delta_text,
                        },
                    },
                )

        elif kind == "on_tool_start":
            tname = event.get("name") or "tool"
            tinput = (event.get("data") or {}).get("input") or {}
            run_id = event.get("run_id") or tname
            pending_tool_inputs[run_id] = tinput
            await _broadcast_ws(
                manager,
                chat_key,
                {
                    "cmd": "agent_tool_start",
                    "message": {"message_id": stream_msg_id, "tool": tname, "args": tinput},
                },
            )

        elif kind == "on_tool_end":
            tname = event.get("name") or "tool"
            run_id = event.get("run_id") or tname
            data = event.get("data") or {}
            raw_output = data.get("output")
            if isinstance(raw_output, ToolMessage):
                out_str = _extract_text_from_chunk_content(raw_output.content)
            else:
                out_str = str(raw_output or "")
            tinput = data.get("input") or pending_tool_inputs.pop(run_id, {})
            tool_traces.append({"tool": tname, "args": tinput, "result": out_str})
            await _broadcast_ws(
                manager,
                chat_key,
                {
                    "cmd": "agent_tool_end",
                    "message": {
                        "message_id": stream_msg_id,
                        "tool": tname,
                        "result": out_str[:3200],
                    },
                },
            )

        elif kind == "on_chain_end" and event.get("name") == "LangGraph":
            output_state = (event.get("data") or {}).get("output")
            if isinstance(output_state, dict) and output_state.get("messages"):
                last_msg = output_state["messages"][-1]
                if isinstance(last_msg, AIMessage):
                    final_ai_content = _extract_text_from_chunk_content(last_msg.content)

    final_text = "".join(streamed_tokens).strip() or final_ai_content.strip()
    if final_text and not streamed_tokens:
        await _broadcast_ws(
            manager,
            chat_key,
            {
                "cmd": "agent_token",
                "message": {
                    "message_id": stream_msg_id,
                    "parent_id": parent_id_str,
                    "delta": final_text,
                },
            },
        )

    total_tokens = _extract_total_tokens_from_callback(usage_cb, system_prompt_str, final_text)
    return final_text, tool_traces, total_tokens


async def _run_local_smart_assistant(
    user_text: str,
    branch_history: List[Dict[str, Any]],
    agent_obj: Optional[Dict[str, Any]],
    system_prompt_str: str,
    all_tools: List[Any],
    manager: Any,
    chat_key: str,
    stream_msg_id: str,
    parent_id_str: str,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Asistente Local Inteligente de InsanusChat (activo cuando el usuario no configuró API Key externa).
    Soporta invocación real de `StructuredTool`s (MCP Calculadora y Code Snippets) y streaming token a token.
    """
    tool_traces: List[Dict[str, Any]] = []
    agent_name = (agent_obj.get("name") if agent_obj else None) or "Insanus Assistant"

    for tool in all_tools:
        meta = getattr(tool, "metadata", None) or {}
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", user_text)]
        txt_low = user_text.lower()

        should_call = False
        call_args: Dict[str, Any] = {}

        mtool = (meta.get("mcp_tool_name") or getattr(tool, "mcp_tool_name", "") or "").lower()
        sname = (meta.get("snippet_name") or getattr(tool, "snippet_name", "") or "").lower()
        htool = (meta.get("harness_tool") or "").lower()

        if htool:
            if htool == "workspace_list_files" and any(w in txt_low for w in ("archivos", "listar", "estructura", "files", "tree", "carpeta", "proyecto")):
                should_call = True
                call_args = {"directory": ".", "max_depth": 2}
            elif htool == "workspace_git_checkpoint" and any(w in txt_low for w in ("git", "rama", "checkpoint", "commit", "status")):
                should_call = True
                call_args = {"label": user_text[:40]}
            elif htool == "harness_update_plan" and any(w in txt_low for w in ("plan", "pasos", "tareas", "crear", "app", "implementa")):
                should_call = True
                call_args = {
                    "steps": [
                        {"title": "Analizar estructura del workspace local", "status": "completed"},
                        {"title": "Ejecutar herramientas del Agent Harness", "status": "completed"},
                        {"title": "Sincronizar con Vista de Editor VS Code y Árbol 2D", "status": "completed"},
                    ]
                }
        elif mtool:
            if len(nums) >= 2:
                if mtool == "add" and any(w in txt_low for w in ("suma", "sumar", "mas", "más", "+", "add")):
                    should_call = True
                    call_args = {"a": nums[0], "b": nums[1]}
                elif mtool == "subtract" and any(w in txt_low for w in ("resta", "restar", "menos", "-", "subtract")):
                    should_call = True
                    call_args = {"a": nums[0], "b": nums[1]}
                elif mtool == "multiply" and any(w in txt_low for w in ("multiplica", "multiplicar", "por", "*", "x", "multiply")):
                    should_call = True
                    call_args = {"a": nums[0], "b": nums[1]}
                elif mtool == "divide" and any(w in txt_low for w in ("divide", "dividir", "dividido", "/", "divide")):
                    should_call = True
                    call_args = {"a": nums[0], "b": nums[1]}
            elif len(nums) >= 1 and mtool == "power_and_sqrt" and any(w in txt_low for w in ("raiz", "raíz", "potencia", "sqrt", "cuadrado")):
                should_call = True
                call_args = {"x": nums[0], "exponent": nums[1] if len(nums) > 1 else 2}
        elif sname:
            if sname in txt_low or "snippet" in txt_low or "ejecuta" in txt_low or "run" in txt_low:
                should_call = True
                call_args = {"input_data": user_text}

        if should_call:
            await _broadcast_ws(
                manager,
                chat_key,
                {
                    "cmd": "agent_tool_start",
                    "message": {"message_id": stream_msg_id, "tool": tool.name, "args": call_args},
                },
            )
            try:
                res_str = await tool.ainvoke(call_args)
            except Exception as e:
                res_str = f"Error: {e}"
            trace = {"tool": tool.name, "args": call_args, "result": str(res_str)}
            tool_traces.append(trace)
            await _broadcast_ws(
                manager,
                chat_key,
                {
                    "cmd": "agent_tool_end",
                    "message": {"message_id": stream_msg_id, "tool": tool.name, "result": str(res_str)[:300]},
                },
            )

    prev_user_msgs = [m["content"] for m in branch_history[:-1] if m.get("role") == "user"]
    depth = len(branch_history)

    lines = [
        f"### 🤖 {agent_name} *(Modo Local Activo)*",
        "",
        f"He procesado tu mensaje en la **profundidad #{depth}** de esta rama del árbol de conversación.",
    ]

    if system_prompt_str:
        lines.append(f"\n> **System Prompt activo:** `{system_prompt_str[:180]}{'...' if len(system_prompt_str) > 180 else ''}`")

    if tool_traces:
        lines.append("\n#### 🛠️ Herramientas ejecutadas en este turno:")
        for tr in tool_traces:
            lines.append(f"- **`{tr['tool']}`** con `{json.dumps(tr['args'])}` → **`{tr['result']}`**")

    if prev_user_msgs:
        last_prev = prev_user_msgs[-1][:80]
        lines.append(
            f"\n- **Contexto aislado de la rama (HU-02):** Esta rama tiene **{len(prev_user_msgs)}** mensaje(s) previo(s) del usuario (último ancestro: *\"{last_prev}\"*)."
        )
    else:
        lines.append("\n- **Nodo Raíz:** Este es el inicio de una nueva conversación o rama raíz.")

    lines.append(f"\n**Respuesta a tu consulta** (*\"{user_text[:100]}\"*):")
    if tool_traces:
        lines.append(f"El resultado devuelto por la herramienta es: **{tool_traces[-1]['result']}**.")
    else:
        lines.append(
            "Podés ramificar esta conversación desde cualquier mensaje usando el botón **Ramificar**, alternar a la **Vista de Árbol 2D**, o vincular una **API Key** (Gemini 2.5, OpenAI, Anthropic u Ollama) desde el **Agent & Tool Studio** para usar modelos LLM en la nube."
        )

    full_response = "\n".join(lines)

    words = full_response.split(" ")
    chunk_size = 3
    for i in range(0, len(words), chunk_size):
        delta = " ".join(words[i : i + chunk_size])
        if i + chunk_size < len(words):
            delta += " "
        await _broadcast_ws(
            manager,
            chat_key,
            {
                "cmd": "agent_token",
                "message": {"message_id": stream_msg_id, "parent_id": parent_id_str, "delta": delta},
            },
        )
        await asyncio.sleep(0.02)

    return full_response, tool_traces


async def _auto_generate_chat_title(
    chat_oid: Any,
    user_text: str,
    agent_text: str,
    provider: str = "gemini",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    manager: Any = None,
):
    """
    HU-11: Genera automáticamente un título conciso usando una cadena LCEL de LangChain
    (`ChatPromptTemplate | llm.with_fallbacks(...) | StrOutputParser()`) si hay API Key,
    o síntesis directa si está en modo local.
    """
    try:
        chats_col = get_chat_collection()
        chat_doc = await chats_col.find_one({"_id": chat_oid})
        if not chat_doc:
            return
        current_title = (chat_doc.get("title") or "").strip()
        if current_title and current_title.lower() not in ("new chat", "nuevo chat", "chat sin título", "untitled"):
            return

        new_title = ""
        if api_key and provider == "gemini":
            try:
                fast_llm = _init_langchain_chat_model("gemini", "gemini-2.5-flash-lite", api_key, temperature=0.3).with_fallbacks(
                    [_init_langchain_chat_model("gemini", "gemini-2.5-flash", api_key, temperature=0.3)]
                )
                prompt = ChatPromptTemplate.from_messages(
                    [
                        ("system", "Genera un título de 3 a 5 palabras en español (sin comillas ni puntos finales) que resuma la consulta."),
                        ("human", "{query}"),
                    ]
                )
                chain = prompt | fast_llm | StrOutputParser()
                gen = await chain.ainvoke({"query": user_text[:200]})
                new_title = (gen or "").strip().strip('"').strip("'")[:60]
            except Exception:
                new_title = ""

        if not new_title:
            clean = re.sub(r"[^\w\sáéíóúÁÉÍÓÚñÑ¿?¡!-]", "", user_text).strip()
            words = clean.split()
            new_title = " ".join(words[:6])
            if len(words) > 6:
                new_title += "..."
        if not new_title:
            new_title = "Conversación con Agente"

        await chats_col.update_one(
            {"_id": chat_oid},
            {"$set": {"title": new_title, "last_updated": datetime.utcnow()}},
        )
        if manager is not None:
            await _broadcast_ws(
                manager,
                str(chat_oid),
                {"cmd": "chat_updated", "message": {"chat_id": str(chat_oid), "title": new_title}},
            )
    except Exception as e:
        logger.debug("No se pudo autogenerar el título del chat: %s", e)


async def run_agent(chat_oid: Any, message_id: Any, manager: Any = None) -> Optional[Dict[str, Any]]:
    """
    Ejecuta el agente asociado al chat sobre el mensaje `message_id` usando el stack
    completo de LangChain (`init_chat_model`, `StructuredTool`, `create_agent`, `astream_events`,
    `UsageMetadataCallbackHandler`, `trim_messages` y fallbacks automáticos).
    """
    msgs_col = get_message_collection()
    chats_col = get_chat_collection()
    users_col = get_user_collection()

    try:
        chat_doc = await chats_col.find_one({"_id": chat_oid})
        message_doc = await msgs_col.find_one({"_id": message_id})
        if not chat_doc or not message_doc:
            return None
    except Exception as e:
        logger.error("Error cargando chat/mensaje en run_agent: %s", e)
        return None

    sys_settings = await ensure_system_settings()
    allow_local_mcp = bool(sys_settings.get("allow_local_mcp_endpoints", True))
    allow_code_snippets = bool(sys_settings.get("allow_code_snippets", True))

    owner_id = chat_doc.get("owner_id") or chat_doc.get("user_id")
    user_doc = None
    agent_obj = None

    if owner_id:
        try:
            owner_oid = PyObjectId.parse(owner_id) if isinstance(owner_id, str) else owner_id
            user_doc = await users_col.find_one({"_id": owner_oid})
        except Exception:
            pass

    if user_doc:
        raw_agent_id = chat_doc.get("agent_id")
        agents_list = user_doc.get("agents") or []
        if raw_agent_id:
            for a in agents_list:
                if str(a.get("_id")) == str(raw_agent_id):
                    agent_obj = a
                    break
        elif agents_list:
            for a in agents_list:
                if a.get("active", True):
                    agent_obj = a
                    break

    provider, model_name, api_key, base_url = _resolve_provider_and_key(user_doc, agent_obj, chat_doc)
    user_text = message_doc.get("content") or message_doc.get("text") or ""
    chat_key = str(chat_oid)
    response_msg_oid = PyObjectId.new()
    stream_msg_id = str(response_msg_oid)
    parent_id_str = str(message_doc["_id"])

    await _broadcast_ws(
        manager,
        chat_key,
        {
            "cmd": "agent_stream_start",
            "message": {
                "message_id": stream_msg_id,
                "parent_id": parent_id_str,
                "provider": provider,
                "model": model_name,
            },
        },
    )

    # 1. Cargar herramientas MCP y Code Snippets como `StructuredTool`s de LangChain
    all_tools = []
    if user_doc:
        mcp_ids = []
        snippet_ids = []
        if agent_obj:
            mcp_ids = agent_obj.get("active_mcps") or agent_obj.get("mcp_ids") or []
            snippet_ids = (
                agent_obj.get("active_tools")
                or agent_obj.get("allowed_tools")
                or agent_obj.get("snippet_ids")
                or []
            )
        if chat_doc.get("active_tools"):
            snippet_ids = list(set(list(snippet_ids) + [str(t) for t in chat_doc.get("active_tools", [])]))

        mcp_tools = await load_mcp_tools(user_doc, mcp_ids, allow_local=allow_local_mcp)
        all_tools.extend(mcp_tools)
        if allow_code_snippets:
            snippet_tools = load_snippet_tools(user_doc, agent_obj or {}, snippet_ids)
            all_tools.extend(snippet_tools)

    # 1.b Si el chat está vinculado a un Equipo de Ejecución (Workstation Harness), inyectar las tools del Harness (HU-21)
    execution_target = (chat_doc.get("execution_target") or "cloud").lower()
    node_id = chat_doc.get("node_id") or "local-workstation-host"
    workspace_path = chat_doc.get("workspace_path") or "."
    harness_mode = chat_doc.get("harness_mode") or "auto_edit"

    if execution_target == "workstation":
        harness_tools = build_harness_langchain_tools(
            chat_oid=chat_oid,
            node_id=node_id,
            workspace_path=workspace_path,
            harness_mode=harness_mode,
            ws_manager=manager,
            current_message_id=parent_id_str,
        )
        all_tools.extend(harness_tools)

    # 2. Construir System Prompt con expansión real de Snippets (si están habilitados) (HU-06) y Contexto de Workspace (HU-23)
    system_prompt_str = ""
    if agent_obj and agent_obj.get("system_prompt"):
        active_user_snips = [
            s for s in ((user_doc.get("code_snippets") if user_doc else None) or []) if s.get("active", True) is not False
        ] if allow_code_snippets else []
        active_agent_snips = [
            s for s in (agent_obj.get("snippets") or []) if s.get("active", True) is not False
        ] if allow_code_snippets else []
        system_prompt_str = await expand_system_prompt_snippets(
            agent_obj.get("system_prompt"),
            agent_snippets=active_agent_snips,
            user_snippets=active_user_snips,
        )

    if execution_target == "workstation":
        ws_ctx = await build_workspace_context_prompt(node_id, workspace_path, harness_mode)
        system_prompt_str = f"{system_prompt_str}\n{ws_ctx}".strip()

    # 3. Reconstruir historial EXCLUSIVAMENTE de la rama activa (HU-02) y recortar con `trim_messages`
    branch_history = await _build_branch_history(chat_oid, message_doc["_id"], max_messages=30)
    lc_messages = _build_trimmed_langchain_messages(branch_history, user_text)

    final_text = ""
    tool_traces: List[Dict[str, Any]] = []
    tokens_used: Optional[int] = None

    # 4. Ejecutar con `create_agent` y `astream_events(version="v2")` de LangChain v1.5
    if api_key or (provider == "ollama" and base_url):
        temp = float(agent_obj.get("temperature", 0.7)) if agent_obj else 0.7
        try:
            chat_model = _init_langchain_chat_model(provider, model_name, api_key or "ollama", temperature=temp, base_url=base_url)
            final_text, tool_traces, tokens_used = await _execute_Compiled_agent_stream(
                chat_model=chat_model,
                all_tools=all_tools,
                system_prompt_str=system_prompt_str,
                lc_messages=lc_messages,
                manager=manager,
                chat_key=chat_key,
                stream_msg_id=stream_msg_id,
                parent_id_str=parent_id_str,
            )
        except asyncio.CancelledError:
            raise
        except Exception as primary_err:
            err_msg = str(primary_err).strip() or f"{type(primary_err).__name__} (Endpoint del modelo no respondió a tiempo / Timeout)"
            err_low = err_msg.lower()

            # Caso A: El modelo existe y tiene cuota, pero no soporta Function Calling (tools).
            # Reintentar automáticamente `create_agent` con `tools=None`.
            if all_tools and any(
                kw in err_low for kw in ("function calling", "tool", "not enabled", "not supported", "invalid_argument")
            ):
                try:
                    logger.info("Modelo %s no soporta Function Calling; reintentando create_agent sin tools", model_name)
                    chat_model = _init_langchain_chat_model(provider, model_name, api_key or "ollama", temperature=temp, base_url=base_url)
                    final_text, tool_traces, tokens_used = await _execute_Compiled_agent_stream(
                        chat_model=chat_model,
                        all_tools=[],
                        system_prompt_str=system_prompt_str,
                        lc_messages=lc_messages,
                        manager=manager,
                        chat_key=chat_key,
                        stream_msg_id=stream_msg_id,
                        parent_id_str=parent_id_str,
                    )
                except Exception as retry_err:
                    err_msg = str(retry_err)

            # Caso B: Cuota agotada (429 ResourceExhausted) o modelo experimental no disponible ->
            # Ejecutar cadena de modelos de respaldo (`model_fallback` -> `gemini-2.5-flash` -> `gemini-2.5-flash-lite`)
            if not final_text and provider == "gemini" and api_key:
                fallback_candidates = []
                if agent_obj and agent_obj.get("model_fallback"):
                    fallback_candidates.append(agent_obj["model_fallback"])
                for fb_m in ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.5-flash"):
                    if fb_m != model_name and fb_m not in fallback_candidates:
                        fallback_candidates.append(fb_m)

                for fb_model_name in fallback_candidates:
                    try:
                        logger.info("Ejecutando modelo fallback de LangChain %s tras fallo en %s", fb_model_name, model_name)
                        fb_chat_model = _init_langchain_chat_model("gemini", fb_model_name, api_key, temperature=temp)
                        final_text, tool_traces, tokens_used = await _execute_Compiled_agent_stream(
                            chat_model=fb_chat_model,
                            all_tools=all_tools,
                            system_prompt_str=system_prompt_str,
                            lc_messages=lc_messages,
                            manager=manager,
                            chat_key=chat_key,
                            stream_msg_id=stream_msg_id,
                            parent_id_str=parent_id_str,
                        )
                        if final_text:
                            reason_short = "Cuota 429 agotada en tu plan para ese modelo" if "429" in err_msg else err_msg[:90]
                            note = f"\n\n---\n*(Nota: `{model_name}` reportó `{reason_short}`; respondido automáticamente mediante fallback de LangChain con `{fb_model_name}`)*"
                            final_text += note
                            await _broadcast_ws(
                                manager,
                                chat_key,
                                {
                                    "cmd": "agent_token",
                                    "message": {"message_id": stream_msg_id, "parent_id": parent_id_str, "delta": note},
                                },
                            )
                            model_name = f"{fb_model_name} (fallback)"
                            break
                    except Exception:
                        continue

            if not final_text:
                logger.warning("Todos los intentos del proveedor %s fallaron; activando asistente local: %s", provider, err_msg)
                final_text, fallback_traces = await _run_local_smart_assistant(
                    user_text=user_text,
                    branch_history=branch_history,
                    agent_obj=agent_obj,
                    system_prompt_str=system_prompt_str,
                    all_tools=all_tools,
                    manager=manager,
                    chat_key=chat_key,
                    stream_msg_id=stream_msg_id,
                    parent_id_str=parent_id_str,
                )
                final_text += f"\n\n*(Nota: El proveedor `{provider}/{model_name}` reportó: `{err_msg[:220]}`)*"
                tool_traces.extend(fallback_traces)

        # Actualizar timestamp last_used de la API key
        if user_doc and api_key:
            try:
                await users_col.update_one(
                    {"_id": user_doc["_id"], "api_keys.provider": provider},
                    {"$set": {"api_keys.$.last_used": datetime.utcnow()}},
                )
            except Exception:
                pass
    else:
        # 5. Ejecutar Asistente Local Inteligente (sin API Key externa)
        final_text, tool_traces = await _run_local_smart_assistant(
            user_text=user_text,
            branch_history=branch_history,
            agent_obj=agent_obj,
            system_prompt_str=system_prompt_str,
            all_tools=all_tools,
            manager=manager,
            chat_key=chat_key,
            stream_msg_id=stream_msg_id,
            parent_id_str=parent_id_str,
        )

    if not final_text:
        final_text = "No se pudo obtener una respuesta del agente."

    if tokens_used is None:
        tokens_used = max(1, (len(user_text) + len(final_text)) // 4)

    response_doc = {
        "_id": response_msg_oid,
        "chat_id": chat_oid,
        "parent_id": message_doc["_id"],
        "children_ids": [],
        "path": list(message_doc.get("path", [])) + [message_doc["_id"]],
        "branch_anchor": message_doc.get("branch_anchor"),
        "cousin_left": message_doc.get("cousin_left"),
        "cousin_right": message_doc.get("cousin_right"),
        "sender_id": str(agent_obj["_id"]) if (agent_obj and agent_obj.get("_id")) else "INSANUS_AGENT",
        "role": "agent",
        "content": final_text,
        "content_type": "markdown",
        "status": "done",
        "tokens_used": tokens_used,
        "tool_calls": tool_traces,
        "provider": provider,
        "model": model_name,
        "created_at": datetime.utcnow(),
    }

    asyncio.create_task(
        _auto_generate_chat_title(
            chat_oid,
            user_text,
            final_text,
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            manager=manager,
        )
    )

    return response_doc
