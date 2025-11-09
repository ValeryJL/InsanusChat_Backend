from fastapi import APIRouter, HTTPException, Header, Body, Query
from routers import auth
import database
from models import PyObjectId
from datetime import datetime

router = APIRouter(
    prefix="/api/v1/resources",  # Todas las rutas aquí comenzarán con /api/v1/resources
    tags=["Resources"],       # Etiqueta para agrupar en la documentación
)


@router.get("/")
async def list_tools(authorization: str | None = Header(None)):
    """
    Listar herramientas asociadas al usuario.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    decoded = auth.authenticate_token(token)
    uid = decoded.get("uid") or decoded.get("user_id")
    try:
        user_oid = PyObjectId.parse(uid)
    except Exception:
        raise HTTPException(status_code=400, detail="user id inválido")

    coll = database.get_user_collection()
    # traer herramientas, mcps y code_snippets del usuario
    user = await coll.find_one({"_id": user_oid}, {"mcps": 1, "code_snippets": 1})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    mcps = user.get("mcps", [])
    snippets = user.get("code_snippets", [])

    # serializar mcps y snippets para evitar ObjectId/datetime no serializables
    def _ser_mcp(m):
        mm = dict(m)
        if mm.get("_id") is not None:
            mm["_id"] = str(mm["_id"])
        if mm.get("registered_at"):
            mm["registered_at"] = mm["registered_at"].isoformat()
        return mm

    def _ser_snip(s):
        ss = dict(s)
        if ss.get("_id") is not None:
            ss["_id"] = str(ss["_id"])
        if ss.get("created_at"):
            ss["created_at"] = ss["created_at"].isoformat()
        return ss

    mcps_out = [_ser_mcp(m) for m in mcps]
    snippets_out = [_ser_snip(s) for s in snippets]

    return {"message": "Resources listados", "data": {"mcps": mcps_out, "code_snippets": snippets_out}}


## ---------------- MCPs CRUD ----------------


@router.post("/mcps")
async def create_mcp(authorization: str | None = Header(None), body: dict = Body(...)):
    """Crear un MCP entry para el usuario.
    body esperado: {"name":..., "endpoint":..., "spec":{...}, "auth":{...}, "metadata":{...}}
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    decoded = auth.authenticate_token(token)
    uid = decoded.get("uid") or decoded.get("user_id")
    try:
        user_oid = PyObjectId.parse(uid)
    except Exception:
        raise HTTPException(status_code=400, detail="user id inválido")

    if not body or not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="payload inválido")
    name = body.get("name")
    endpoint = body.get("endpoint")
    spec = body.get("spec", {}) or {}
    auth_conf = body.get("auth", None)
    metadata = body.get("metadata", {}) or {}
    if not name or not endpoint:
        raise HTTPException(status_code=400, detail="name y endpoint son requeridos")

    mcp_doc = {
        "_id": PyObjectId.new(),
        "name": name,
        "endpoint": endpoint,
        "spec": spec,
        "auth": auth_conf,
        "metadata": metadata,
        "registered_at": datetime.utcnow(),
        "active": True,
    }

    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$push": {"mcps": mcp_doc}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    out = dict(mcp_doc)
    out["_id"] = str(out["_id"])
    out["registered_at"] = out["registered_at"].isoformat()
    return {"message": "MCP creado", "data": out}


@router.put("/mcps")
async def update_mcp(mcp_id: str | None = Query(None, alias="mcp_id"), authorization: str | None = Header(None), body: dict = Body(...)):
    """Actualizar MCP del usuario. Campos permitidos: name, endpoint, spec, auth, metadata, active"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    decoded = auth.authenticate_token(token)
    uid = decoded.get("uid") or decoded.get("user_id")
    try:
        user_oid = PyObjectId.parse(uid)
    except Exception:
        raise HTTPException(status_code=400, detail="user id inválido")

    try:
        mid = PyObjectId.parse(mcp_id)
    except Exception:
        raise HTTPException(status_code=400, detail="mcp_id inválido")

    if not body or not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="payload inválido")

    allowed = {"name", "endpoint", "spec", "auth", "metadata", "active"}
    set_ops = {}
    for k, v in body.items():
        if k in allowed:
            set_ops[f"mcps.$[m].{k}"] = v

    if not set_ops:
        raise HTTPException(status_code=400, detail="Nada para actualizar")

    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$set": set_ops}, array_filters=[{"m._id": mid}])
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if res.modified_count == 0:
        raise HTTPException(status_code=404, detail="MCP no encontrado o sin cambios")

    user = await coll.find_one({"_id": user_oid}, {"mcps": 1})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    updated = None
    for m in user.get("mcps", []):
        if str(m.get("_id")) == str(mid):
            updated = m
            break
    if not updated:
        raise HTTPException(status_code=404, detail="MCP no encontrado tras actualización")

    mop = dict(updated)
    mop["_id"] = str(mop["_id"])
    if mop.get("registered_at"):
        mop["registered_at"] = mop["registered_at"].isoformat()
    return {"message": "MCP actualizado", "data": mop}


@router.delete("/mcps")
async def delete_mcp(mcp_id: str | None = Query(None, alias="mcp_id"), authorization: str | None = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    decoded = auth.authenticate_token(token)
    uid = decoded.get("uid") or decoded.get("user_id")
    try:
        user_oid = PyObjectId.parse(uid)
    except Exception:
        raise HTTPException(status_code=400, detail="user id inválido")

    try:
        mid = PyObjectId.parse(mcp_id)
    except Exception:
        raise HTTPException(status_code=400, detail="mcp_id inválido")
    coll = database.get_user_collection()
    data = await coll.find_one({"_id": user_oid}, {"mcps": 1})
    mcp = None
    if data:
        for m in data.get("mcps", []):
            if str(m.get("_id")) == str(mid):
                mcp = m
                break
    if not mcp:
        raise HTTPException(status_code=404, detail="MCP no encontrado")
    res = await coll.update_one({"_id": user_oid}, {"$pull": {"mcps": {"_id": mid}}})
    if res.modified_count == 0:
        raise HTTPException(status_code=404, detail="MCP no encontrado")
    return {"message": "MCP eliminado", "data": {"id": auth._serialize_doc(mcp)}}

## ---------------- Snippets CRUD ----------------


@router.post("/snippets")
async def create_snippet(authorization: str | None = Header(None), body: dict = Body(...)):
    """Crear un code snippet para el usuario.
    body: {name, language, code, description?, public?}
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    decoded = auth.authenticate_token(token)
    uid = decoded.get("uid") or decoded.get("user_id")
    try:
        user_oid = PyObjectId.parse(uid)
    except Exception:
        raise HTTPException(status_code=400, detail="user id inválido")

    if not body or not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="payload inválido")
    name = body.get("name")
    language = body.get("language")
    code = body.get("code")
    description = body.get("description")
    public = bool(body.get("public", False))
    if not name or not language or not code:
        raise HTTPException(status_code=400, detail="name, language y code son requeridos")

    snip = {
        "_id": PyObjectId.new(),
        "name": name,
        "description": description,
        "language": language,
        "code": code,
        "created_at": datetime.utcnow(),
        "public": public,
    }
    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$push": {"code_snippets": snip}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    out = dict(snip)
    out["_id"] = str(out["_id"])
    out["created_at"] = out["created_at"].isoformat()
    return {"message": "Snippet creado", "data": out}


@router.put("/snippets")
async def update_snippet(snippet_id: str | None = Query(None, alias="snippet_id"), authorization: str | None = Header(None), body: dict = Body(...)):
    """Actualizar snippet: name, description, code, language, public"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    decoded = auth.authenticate_token(token)
    uid = decoded.get("uid") or decoded.get("user_id")
    try:
        user_oid = PyObjectId.parse(uid)
    except Exception:
        raise HTTPException(status_code=400, detail="user id inválido")

    try:
        sid = PyObjectId.parse(snippet_id)
    except Exception:
        raise HTTPException(status_code=400, detail="snippet_id inválido")

    if not body or not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="payload inválido")

    allowed = {"name", "description", "code", "language", "public"}
    set_ops = {}
    for k, v in body.items():
        if k in allowed:
            set_ops[f"code_snippets.$[s].{k}"] = v

    if not set_ops:
        raise HTTPException(status_code=400, detail="Nada para actualizar")

    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$set": set_ops}, array_filters=[{"s._id": sid}])
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if res.modified_count == 0:
        raise HTTPException(status_code=404, detail="Snippet no encontrado o sin cambios")

    user = await coll.find_one({"_id": user_oid}, {"code_snippets": 1})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    updated = None
    for s in user.get("code_snippets", []):
        if str(s.get("_id")) == str(sid):
            updated = s
            break
    if not updated:
        raise HTTPException(status_code=404, detail="Snippet no encontrado tras actualización")

    sop = dict(updated)
    sop["_id"] = str(sop["_id"])
    if sop.get("created_at"):
        sop["created_at"] = sop["created_at"].isoformat()
    return {"message": "Snippet actualizado", "data": sop}


@router.delete("/snippets")
async def delete_snippet(snippet_id: str | None = Query(None, alias="snippet_id"), authorization: str | None = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    decoded = auth.authenticate_token(token)
    uid = decoded.get("uid") or decoded.get("user_id")
    try:
        user_oid = PyObjectId.parse(uid)
    except Exception:
        raise HTTPException(status_code=400, detail="user id inválido")

    try:
        sid = PyObjectId.parse(snippet_id)
    except Exception:
        raise HTTPException(status_code=400, detail="snippet_id inválido")
    coll = database.get_user_collection()
    data = await coll.find_one({"_id": user_oid}, {"code_snippets": 1})
    snippet = None
    if data:
        for s in data.get("code_snippets", []):
            if str(s.get("_id")) == str(sid):
                snippet = s
                break
    if not snippet:
        raise HTTPException(status_code=404, detail="Snippet no encontrado")
    res = await coll.update_one({"_id": user_oid}, {"$pull": {"code_snippets": {"_id": sid}}})
    if res.modified_count == 0:
        raise HTTPException(status_code=404, detail="Snippet no encontrado")
    return {"message": "Snippet eliminado", "data": {"id": auth._serialize_doc(snippet)}}
