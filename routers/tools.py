"""
Router de Recursos: MCP Servers y Code Snippets con:
- Gobernanza de transporte `stdio` y protección Anti-SSRF (HU-07)
- Endpoint de Test de Conexión y descubrimiento de Tools MCP (`POST /api/v1/resources/mcps/{mcp_id}/test`) (HU-10)
- Endpoint de Ejecución de prueba de Code Snippets (`POST /api/v1/resources/snippets/execute`) (HU-06, HU-16)
"""
from datetime import datetime
import time
from typing import Any, Dict
from fastapi import APIRouter, Body, Header, HTTPException, Query

import database
from models import PyObjectId, ResponseModel
from routers import auth
from services.mcp_client import MCPClient
from services.mcp_helpers import build_connect_params, validate_endpoint_url, validate_mcp_entry
from services.snippets import execute_snippet

router = APIRouter(
    prefix="/api/v1/resources",
    tags=["Resources"],
)


def _ser_mcp(m: dict) -> dict:
    mm = dict(m)
    if mm.get("_id") is not None:
        mm["_id"] = str(mm["_id"])
    if mm.get("registered_at") and hasattr(mm["registered_at"], "isoformat"):
        mm["registered_at"] = mm["registered_at"].isoformat()
    if mm.get("last_connected_at") and hasattr(mm["last_connected_at"], "isoformat"):
        mm["last_connected_at"] = mm["last_connected_at"].isoformat()
    return mm


def _ser_snip(s: dict) -> dict:
    ss = dict(s)
    if ss.get("_id") is not None:
        ss["_id"] = str(ss["_id"])
    if ss.get("created_at") and hasattr(ss["created_at"], "isoformat"):
        ss["created_at"] = ss["created_at"].isoformat()
    return ss


@router.get("/", response_model=ResponseModel)
async def list_tools(authorization: str | None = Header(None)):
    user = await auth.get_authenticated_user(authorization)
    mcps = [_ser_mcp(m) for m in (user.get("mcps") or [])]
    snippets = [_ser_snip(s) for s in (user.get("code_snippets") or [])]
    return ResponseModel(message="Resources listados", data={"mcps": mcps, "code_snippets": snippets})


## ---------------- MCPs CRUD & Test ----------------


@router.post("/mcps", response_model=ResponseModel)
async def create_mcp(
    authorization: str | None = Header(None),
    body: dict = Body(
        ...,
        examples={
            "basic": {
                "summary": "Crear MCP Server",
                "value": {
                    "name": "MCP-Local",
                    "transport": "http",
                    "endpoint": "http://localhost:9000",
                    "spec": {},
                },
            }
        },
    ),
):
    user = await auth.get_authenticated_user(authorization)
    user_oid = user["_id"]

    if not body or not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="payload inválido")

    sys_settings = await database.ensure_system_settings()
    is_admin = "admin" in (user.get("roles") or [])

    name = (body.get("name") or "").strip()
    transport = (body.get("transport") or ("stdio" if body.get("local_script_path") or body.get("command") else "http")).lower()
    endpoint = body.get("endpoint")
    local_script_path = body.get("local_script_path")
    command = body.get("command")
    args = body.get("args") or []
    env = body.get("env") or {}

    if not name:
        raise HTTPException(status_code=400, detail="name es requerido")

    # Si enviaron un script .py/.js como endpoint, inferir transporte stdio
    if endpoint and (str(endpoint).endswith(".py") or str(endpoint).endswith(".js")) and not local_script_path:
        transport = "stdio"
        local_script_path = endpoint

    # HU-07: Gobernanza de stdio y Anti-SSRF
    if transport == "stdio":
        if not sys_settings.get("allow_stdio_mcp", True) and not is_admin:
            raise HTTPException(
                status_code=403,
                detail="El transporte 'stdio' está restringido a administradores por política de seguridad.",
            )
        if not local_script_path and not command and not endpoint:
            raise HTTPException(status_code=400, detail="Para transporte stdio se requiere local_script_path o command")
    elif transport in ("http", "sse", "websocket"):
        if not endpoint:
            raise HTTPException(status_code=400, detail="name y endpoint son requeridos")
        try:
            allow_local = bool(sys_settings.get("allow_local_mcp_endpoints", True)) or is_admin
            endpoint = validate_endpoint_url(endpoint, allow_local=allow_local)
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))
    else:
        raise HTTPException(status_code=400, detail=f"Transporte no soportado: {transport}")

    mcp_doc = {
        "_id": PyObjectId.new(),
        "name": name,
        "transport": transport,
        "endpoint": endpoint,
        "local_script_path": local_script_path,
        "command": command,
        "args": args if isinstance(args, list) else [str(args)],
        "env": env if isinstance(env, dict) else {},
        "working_dir": body.get("working_dir"),
        "spec": body.get("spec", {}) or {},
        "auth": body.get("auth", None),
        "metadata": body.get("metadata", {}) or {},
        "registered_at": datetime.utcnow(),
        "active": bool(body.get("active", True)),
        "status": "unknown",
        "timeout_seconds": int(body.get("timeout_seconds") or 30),
        "last_connected_at": None,
    }

    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$push": {"mcps": mcp_doc}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return ResponseModel(message="MCP creado", data=_ser_mcp(mcp_doc))


@router.put("/mcps", response_model=ResponseModel)
async def update_mcp(
    mcp_id: str | None = Query(None, alias="mcp_id"),
    authorization: str | None = Header(None),
    body: dict = Body(..., examples={"update": {"value": {"name": "Nuevo nombre"}}}),
):
    user = await auth.get_authenticated_user(authorization)
    user_oid = user["_id"]

    try:
        mid = PyObjectId.parse(mcp_id)
    except Exception:
        raise HTTPException(status_code=400, detail="mcp_id inválido")

    if not body or not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="payload inválido")

    allowed = {
        "name",
        "transport",
        "endpoint",
        "local_script_path",
        "command",
        "args",
        "env",
        "working_dir",
        "spec",
        "auth",
        "metadata",
        "active",
        "timeout_seconds",
    }
    set_ops = {f"mcps.$[m].{k}": v for k, v in body.items() if k in allowed}
    if not set_ops:
        raise HTTPException(status_code=400, detail="Nada para actualizar")

    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$set": set_ops}, array_filters=[{"m._id": mid}])
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    user_after = await coll.find_one({"_id": user_oid}, {"mcps": 1})
    updated = next((m for m in (user_after.get("mcps") or []) if str(m.get("_id")) == str(mid)), None)
    if not updated:
        raise HTTPException(status_code=404, detail="MCP no encontrado")

    return ResponseModel(message="MCP actualizado", data=_ser_mcp(updated))


@router.delete("/mcps", response_model=ResponseModel)
async def delete_mcp(
    mcp_id: str | None = Query(None, alias="mcp_id"),
    authorization: str | None = Header(None),
):
    user = await auth.get_authenticated_user(authorization)
    user_oid = user["_id"]

    try:
        mid = PyObjectId.parse(mcp_id)
    except Exception:
        raise HTTPException(status_code=400, detail="mcp_id inválido")

    existing = next((m for m in (user.get("mcps") or []) if str(m.get("_id")) == str(mid)), None)
    if not existing:
        raise HTTPException(status_code=404, detail="MCP no encontrado")

    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$pull": {"mcps": {"_id": mid}}})
    if res.modified_count == 0:
        raise HTTPException(status_code=404, detail="MCP no encontrado")

    return ResponseModel(message="MCP eliminado", data={"id": auth._serialize_doc(existing)})


@router.post("/mcps/{mcp_id}/test", response_model=ResponseModel)
async def test_mcp_connection(
    mcp_id: str,
    authorization: str | None = Header(None),
):
    """
    HU-10: Prueba la conexión con un servidor MCP registrado, descubre las herramientas
    que expone y actualiza su estado (`available` / `unreachable`) en la base de datos.
    """
    user = await auth.get_authenticated_user(authorization)
    user_oid = user["_id"]

    try:
        mid = PyObjectId.parse(mcp_id)
    except Exception:
        raise HTTPException(status_code=400, detail="mcp_id inválido")

    mcp_doc = next((m for m in (user.get("mcps") or []) if str(m.get("_id")) == str(mid)), None)
    if not mcp_doc:
        raise HTTPException(status_code=404, detail="MCP no encontrado")

    sys_settings = await database.ensure_system_settings()
    allow_local = bool(sys_settings.get("allow_local_mcp_endpoints", True)) or ("admin" in (user.get("roles") or []))

    start = time.perf_counter()
    now = datetime.utcnow()
    discovered_tools = []
    status_str = "unreachable"
    error_msg = None

    try:
        mentry = validate_mcp_entry(mcp_doc)
        cparams = build_connect_params(mentry, allow_local=allow_local)
        async with MCPClient() as client:
            await client.connect_to_server(**cparams)
            tools_raw = await client.get_tools()
            for t in tools_raw:
                t_name = getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else "unknown")
                t_desc = getattr(t, "description", None) or (t.get("description") if isinstance(t, dict) else "")
                t_schema = getattr(t, "inputSchema", None) or (t.get("inputSchema") if isinstance(t, dict) else {})
                discovered_tools.append({"name": t_name, "description": t_desc, "inputSchema": t_schema})
            status_str = "available"
    except Exception as e:
        error_msg = str(e)
        status_str = "unreachable"

    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    coll = database.get_user_collection()
    spec_updated = dict(mcp_doc.get("spec") or {})
    if discovered_tools:
        spec_updated["tools"] = discovered_tools

    await coll.update_one(
        {"_id": user_oid},
        {
            "$set": {
                "mcps.$[m].status": status_str,
                "mcps.$[m].last_connected_at": now,
                "mcps.$[m].spec": spec_updated,
            }
        },
        array_filters=[{"m._id": mid}],
    )

    return ResponseModel(
        message="Conexión MCP exitosa" if status_str == "available" else f"Fallo al conectar MCP: {error_msg}",
        data={
            "mcp_id": str(mid),
            "status": status_str,
            "latency_ms": latency_ms,
            "tools": discovered_tools,
            "tools_count": len(discovered_tools),
            "error": error_msg,
        },
    )


## ---------------- Snippets CRUD & Execute ----------------


@router.post("/snippets", response_model=ResponseModel)
async def create_snippet(
    authorization: str | None = Header(None),
    body: dict = Body(
        ...,
        examples={
            "example": {
                "value": {
                    "name": "parse_csv",
                    "language": "python",
                    "type": "runtime",
                    "code": "return {'lines': len(str(inp or '').splitlines())}",
                }
            }
        },
    ),
):
    user = await auth.get_authenticated_user(authorization)
    user_oid = user["_id"]

    sys_settings = await database.ensure_system_settings()
    if not sys_settings.get("allow_code_snippets", True):
        raise HTTPException(
            status_code=403,
            detail="La creación y ejecución de Code Snippets está deshabilitada globalmente en las políticas del servidor.",
        )

    if not body or not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="payload inválido")
    name = (body.get("name") or "").strip()
    language = (body.get("language") or "python").lower()
    code = body.get("code")
    description = body.get("description") or ""
    snip_type = body.get("type") or ("template" if language == "text" else "runtime")
    public = bool(body.get("public", False))
    active = bool(body.get("active", True))

    if not name or not language or not code:
        raise HTTPException(status_code=400, detail="name, language y code son requeridos")

    snip = {
        "_id": PyObjectId.new(),
        "name": name,
        "description": description,
        "language": language,
        "type": snip_type,
        "code": code,
        "created_at": datetime.utcnow(),
        "public": public,
        "active": active,
    }
    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$push": {"code_snippets": snip}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return ResponseModel(message="Snippet creado", data=_ser_snip(snip))


@router.put("/snippets", response_model=ResponseModel)
async def update_snippet(
    snippet_id: str | None = Query(None, alias="snippet_id"),
    authorization: str | None = Header(None),
    body: dict = Body(..., examples={"update": {"value": {"name": "nuevo", "code": "return 42"}}}),
):
    user = await auth.get_authenticated_user(authorization)
    user_oid = user["_id"]

    try:
        sid = PyObjectId.parse(snippet_id)
    except Exception:
        raise HTTPException(status_code=400, detail="snippet_id inválido")

    if not body or not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="payload inválido")

    allowed = {"name", "description", "code", "language", "type", "public", "active"}
    set_ops = {f"code_snippets.$[s].{k}": v for k, v in body.items() if k in allowed}
    if not set_ops:
        raise HTTPException(status_code=400, detail="Nada para actualizar")

    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$set": set_ops}, array_filters=[{"s._id": sid}])
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    user_after = await coll.find_one({"_id": user_oid}, {"code_snippets": 1})
    updated = next((s for s in (user_after.get("code_snippets") or []) if str(s.get("_id")) == str(sid)), None)
    if not updated:
        raise HTTPException(status_code=404, detail="Snippet no encontrado")

    return ResponseModel(message="Snippet actualizado", data=_ser_snip(updated))


@router.delete("/snippets", response_model=ResponseModel)
async def delete_snippet(
    snippet_id: str | None = Query(None, alias="snippet_id"),
    authorization: str | None = Header(None),
):
    user = await auth.get_authenticated_user(authorization)
    user_oid = user["_id"]

    try:
        sid = PyObjectId.parse(snippet_id)
    except Exception:
        raise HTTPException(status_code=400, detail="snippet_id inválido")

    existing = next((s for s in (user.get("code_snippets") or []) if str(s.get("_id")) == str(sid)), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Snippet no encontrado")

    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$pull": {"code_snippets": {"_id": sid}}})
    if res.modified_count == 0:
        raise HTTPException(status_code=404, detail="Snippet no encontrado")

    return ResponseModel(message="Snippet eliminado", data={"id": auth._serialize_doc(existing)})


@router.post("/snippets/execute", response_model=ResponseModel)
async def test_execute_snippet(
    authorization: str | None = Header(None),
    body: Dict[str, Any] = Body(
        ...,
        examples={
            "run": {
                "summary": "Probar ejecución de un snippet en sandbox aislado",
                "value": {
                    "language": "python",
                    "code": "return {'echo': inp, 'doble': 21 * 2}",
                    "input_data": "Hola desde Studio",
                },
            }
        },
    ),
):
    """
    HU-06 / HU-16: Ejecuta un snippet en el sandbox aislado con `input_data` de prueba
    y devuelve el resultado, stdout, stderr y tiempo de ejecución.
    """
    await auth.get_authenticated_user(authorization)
    sys_settings = await database.ensure_system_settings()
    if not sys_settings.get("allow_code_snippets", True):
        raise HTTPException(
            status_code=403,
            detail="La ejecución de Code Snippets está deshabilitada globalmente por el administrador.",
        )
    language = body.get("language") or "python"
    code = body.get("code") or ""
    input_data = body.get("input_data")

    if not code.strip():
        raise HTTPException(status_code=400, detail="El código del snippet es requerido")

    result = await execute_snippet({"language": language, "code": code}, input_data=input_data)
    return ResponseModel(
        message="Snippet ejecutado" if result.get("success") else "Error en ejecución de snippet",
        data=result,
    )
