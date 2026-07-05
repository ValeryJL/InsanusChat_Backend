"""
Herramientas Nativas de LangChain (`StructuredTool.from_function`) para Servidores MCP y Code Snippets (HU-08, HU-10).
Convierte dinámicamente los JSON Schemas de MCP en modelos Pydantic v2 (`args_schema`) y genera instancias
`StructuredTool` asíncronas listas para `langchain.agents.create_agent`.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Type

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, create_model

from services.mcp_client import MCPClient
from services.mcp_helpers import build_connect_params, validate_mcp_entry
from services.snippets import execute_snippet

logger = logging.getLogger(__name__)


def _sanitize_tool_name(raw_name: str) -> str:
    """Normaliza el nombre de la herramienta para cumplir con regex de Gemini/OpenAI/Anthropic ^[a-zA-Z_][a-zA-Z0-9_-]{0,63}$."""
    clean = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_name)
    if not clean or not (clean[0].isalpha() or clean[0] == "_"):
        clean = f"tool_{clean}"
    return clean[:63]


def _json_schema_to_pydantic_model(model_name: str, schema: Optional[Dict[str, Any]]) -> Type[BaseModel]:
    """Construye dinámicamente un modelo Pydantic v2 desde el inputSchema JSON de una herramienta MCP."""
    if not schema or not isinstance(schema, dict):
        return create_model(model_name)

    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    fields: Dict[str, Any] = {}

    type_map = {
        "string": str,
        "number": float,
        "integer": int,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    for prop_name, prop_spec in props.items():
        if not isinstance(prop_spec, dict):
            continue
        json_type = prop_spec.get("type", "string")
        py_type = type_map.get(json_type, Any)
        desc = prop_spec.get("description", "")
        if prop_name in required:
            fields[prop_name] = (py_type, Field(..., description=desc))
        else:
            fields[prop_name] = (Optional[py_type], Field(None, description=desc))

    if not fields:
        return create_model(model_name)

    try:
        return create_model(model_name, **fields)
    except Exception:
        return create_model(model_name)


class SnippetToolInput(BaseModel):
    input_data: Optional[str] = Field(None, description="Datos de entrada para el snippet (texto o JSON serializado)")


def build_mcp_structured_tool(
    safe_name: str,
    description: str,
    mcp_tool_name: str,
    mcp_name: str,
    connect_params: Dict[str, Any],
    args_schema: Type[BaseModel],
) -> StructuredTool:
    """Crea un `StructuredTool` nativo de LangChain con corrutina asíncrona para invocar un servidor MCP."""

    async def _invoke_mcp(**kwargs: Any) -> str:
        clean_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        try:
            async with MCPClient() as client:
                await client.connect_to_server(**connect_params)
                result = await client.call_tool(mcp_tool_name, clean_kwargs)
                if hasattr(result, "content"):
                    content = result.content
                    if isinstance(content, list):
                        parts = []
                        for item in content:
                            if hasattr(item, "text"):
                                parts.append(str(item.text))
                            else:
                                parts.append(str(item))
                        return "\n".join(parts)
                    return str(content)
                return json.dumps(result, default=str, ensure_ascii=False) if isinstance(result, dict) else str(result)
        except Exception as e:
            logger.error("Error ejecutando MCP tool %s (%s): %s", mcp_tool_name, mcp_name, e)
            return f"Error executing MCP tool {mcp_tool_name}: {str(e)}"

    tool = StructuredTool.from_function(
        coroutine=_invoke_mcp,
        name=safe_name,
        description=description,
        args_schema=args_schema,
    )
    tool.metadata = {"mcp_tool_name": mcp_tool_name, "mcp_name": mcp_name, "type": "mcp"}
    return tool


def build_snippet_structured_tool(
    safe_name: str,
    description: str,
    snippet_id: str,
    snippet_name: str,
    language: str,
    code: str,
) -> StructuredTool:
    """Crea un `StructuredTool` nativo de LangChain con corrutina asíncrona para ejecutar un Code Snippet en sandbox."""

    async def _invoke_snippet(input_data: Optional[str] = None, **kwargs: Any) -> str:
        payload = input_data if input_data is not None else (kwargs if kwargs else None)
        try:
            res = await execute_snippet(
                {"language": language, "code": code},
                input_data=payload,
            )
            if res.get("success"):
                val = res.get("result")
                if val is not None:
                    return json.dumps(val, ensure_ascii=False) if isinstance(val, (dict, list)) else str(val)
                return (res.get("stdout") or "Success (No output)").strip()
            return f"Snippet Error: {res.get('error')} | {res.get('stderr', '')}".strip()
        except Exception as e:
            logger.error("Error ejecutando snippet %s: %s", snippet_name, e)
            return f"Error executing snippet: {str(e)}"

    tool = StructuredTool.from_function(
        coroutine=_invoke_snippet,
        name=safe_name,
        description=description,
        args_schema=SnippetToolInput,
    )
    tool.metadata = {"snippet_id": snippet_id, "snippet_name": snippet_name, "language": language, "type": "snippet"}
    return tool


async def load_mcp_tools(user_doc: Dict[str, Any], mcp_ids: List[Any], allow_local: bool = True) -> List[StructuredTool]:
    """Descubre y construye `StructuredTool`s de LangChain para los servidores MCP activos del agente."""
    tools: List[StructuredTool] = []
    if not user_doc or not mcp_ids:
        return tools

    mcps_map = {str(m.get("_id")): m for m in (user_doc.get("mcps") or []) if m.get("active", True)}
    target_ids = {str(mid) for mid in mcp_ids}

    for mid_s in target_ids:
        mcp_raw = mcps_map.get(mid_s)
        if not mcp_raw:
            continue
        try:
            mentry = validate_mcp_entry(mcp_raw)
            cparams = build_connect_params(mentry, allow_local=allow_local)
            async with MCPClient() as client:
                await client.connect_to_server(**cparams)
                server_tools = await client.get_tools()
                for st in server_tools:
                    st_name = getattr(st, "name", None) or (st.get("name") if isinstance(st, dict) else "tool")
                    st_desc = getattr(st, "description", None) or (st.get("description") if isinstance(st, dict) else "")
                    st_schema = getattr(st, "inputSchema", None) or (st.get("inputSchema") if isinstance(st, dict) else None)

                    safe_name = _sanitize_tool_name(f"mcp_{mentry.name}_{st_name}")
                    pyd_schema = _json_schema_to_pydantic_model(f"Schema_{safe_name}", st_schema)
                    tools.append(
                        build_mcp_structured_tool(
                            safe_name=safe_name,
                            description=st_desc or f"Herramienta MCP '{st_name}' del servidor '{mentry.name}'",
                            mcp_tool_name=st_name,
                            mcp_name=mentry.name,
                            connect_params=cparams,
                            args_schema=pyd_schema,
                        )
                    )
        except Exception as e:
            logger.warning("No se pudieron cargar las herramientas del MCP %s: %s", mid_s, e)

    return tools


def load_snippet_tools(user_doc: Dict[str, Any], agent_obj: Dict[str, Any], snippet_ids: List[Any]) -> List[StructuredTool]:
    """Construye `StructuredTool`s de LangChain a partir de los code_snippets del usuario y del agente."""
    tools: List[StructuredTool] = []
    snippets_map: Dict[str, Dict[str, Any]] = {}

    if user_doc:
        for s in (user_doc.get("code_snippets") or user_doc.get("snippets") or []):
            if isinstance(s, dict) and s.get("_id"):
                snippets_map[str(s["_id"])] = s

    if agent_obj:
        for s in (agent_obj.get("snippets") or []):
            if isinstance(s, dict) and s.get("_id"):
                if s.get("type", "runtime") == "runtime" and s.get("language") != "text":
                    snippets_map[str(s["_id"])] = s

    target_ids = {str(sid) for sid in (snippet_ids or [])}
    if agent_obj:
        for s in (agent_obj.get("snippets") or []):
            if isinstance(s, dict) and s.get("_id") and s.get("type", "runtime") == "runtime" and s.get("language") != "text":
                target_ids.add(str(s["_id"]))

    for sid_s in target_ids:
        s = snippets_map.get(sid_s)
        if not s:
            continue
        if s.get("active", True) is False:
            continue
        if s.get("type") == "template" or s.get("language") == "text":
            continue
        sname = s.get("name") or sid_s[:8]
        safe_name = _sanitize_tool_name(f"snippet_{sname}")
        tools.append(
            build_snippet_structured_tool(
                safe_name=safe_name,
                description=s.get("description") or f"Ejecuta el snippet {s.get('language', 'python')} '{sname}'",
                snippet_id=sid_s,
                snippet_name=sname,
                language=s.get("language", "python"),
                code=s.get("code", ""),
            )
        )

    return tools
