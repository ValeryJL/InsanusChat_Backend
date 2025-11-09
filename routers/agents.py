from fastapi import APIRouter, HTTPException, Header, Body, Query
from routers import auth
import database
from models import PyObjectId
from datetime import datetime
from typing import List
 


def _sanitize_value(v):
    """Recursively make a value JSON-serializable without importing bson.

    Strategy:
    - datetimes -> ISO strings
    - basic scalars -> kept as-is
    - dicts/lists -> recurse
    - any other object -> fallback to str(obj)

    This avoids importing or relying on `bson.ObjectId` here; `ObjectId`
    instances will be converted to their string form by `str(obj)`.
    """
    # primitives that are already serializable
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _sanitize_value(vv) for k, vv in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sanitize_value(x) for x in v]

    # fallback: convert unknown/non-serializable objects to string
    try:
        return str(v)
    except Exception:
        # As a last resort, return a placeholder
        return "<unserializable>"

router = APIRouter(
    prefix="/api/v1/agents",
    tags=["Agentes"],
)


@router.get("/")
async def list_agents(authorization: str | None = Header(None)):
    """Listar agentes del usuario autenticado."""
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
    user = await coll.find_one({"_id": user_oid}, {"agents": 1})
    agents = user.get("agents", []) if user else []
    # serializar ObjectId/datetime recursivamente
    out = [_sanitize_value(a) for a in agents]
    return {"message": "Agentes listados", "data": out}


@router.post("/")
async def create_agent(authorization: str | None = Header(None), payload: dict = Body(...)):
    """Crear un agente para el usuario (inserta en `users.agents`).

    Payload ejemplo:
    {
      "name": "Mi Agent",
      "description": "...",
      "system_prompt": ["You are a bot.", "SNIPPET:<id>"] ,
      "snippets": [{"name":"now","language":"javascript","code":"return Date.now()"}],
      "model_selected": "gpt-4o"
    }
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

    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="name es requerido")

    # preparar snippets con ids si se entregan
    raw_snippets: List[dict] = payload.get("snippets", []) or []
    snippets = []
    for s in raw_snippets:
        s_doc = dict(s)
        s_doc["_id"] = PyObjectId.new()
        s_doc.setdefault("created_at", datetime.utcnow())
        snippets.append(s_doc)

    agent_doc = {
        "_id": PyObjectId.new(),
        "name": name,
        "description": payload.get("description"),
        "system_prompt": payload.get("system_prompt", []),
        "snippets": snippets,
        "active_tools": payload.get("active_tools", []),
        "active_mcps": payload.get("active_mcps", []),
        "model_selected": payload.get("model_selected"),
        "model_fallback": payload.get("model_fallback"),
        "metadata": payload.get("metadata", {}),
        "created_at": datetime.utcnow(),
        "active": True,
    }

    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$push": {"agents": agent_doc}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    agent_doc_out = _sanitize_value(agent_doc)
    return {"message": "Agente creado", "data": agent_doc_out}


@router.put("/")
async def update_agent(agent_id: str | None = Query(None,alias="agent_id"), authorization: str | None = Header(None), payload: dict | None = Body(None)):
    """Actualizar campos permitidos del agente embebido.

    Campos permitidos: name, description, system_prompt (lista), active_tools, active_mcps, model_selected, model_fallback, metadata, active
    Para actualizar snippets usa PUT específico o reemplaza la lista completa en `snippets`.
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

    try:
        oid = PyObjectId.parse(agent_id)
    except Exception:
        raise HTTPException(status_code=400, detail="agent_id inválido")

    allowed = {"name", "description", "system_prompt", "active_tools", "active_mcps", "model_selected", "model_fallback", "metadata", "active", "snippets"}
    update_fields = {}
    if payload:
        for k, v in payload.items():
            if k in allowed:
                update_fields[k] = v

    if not update_fields:
        raise HTTPException(status_code=400, detail="Nada para actualizar")

    # Si se provee snippets, normalizarlas (asegurar _id)
    if "snippets" in update_fields:
        norm = []
        for s in update_fields["snippets"]:
            sdoc = dict(s)
            if not sdoc.get("_id"):
                sdoc["_id"] = PyObjectId.new()
            else:
                try:
                    sdoc["_id"] = PyObjectId.parse(sdoc["_id"])
                except Exception:
                    # dejar tal cual si no convertible
                    pass
            sdoc.setdefault("created_at", datetime.utcnow())
            norm.append(sdoc)
        update_fields["snippets"] = norm

    # Preparar $set con paths agents.$[a].field
    set_ops = {}
    for k, v in update_fields.items():
        set_ops[f"agents.$[a].{k}"] = v

    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$set": set_ops}, array_filters=[{"a._id": oid}])
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Agente no encontrado o no pertenece al usuario")

    # Recuperar el agente actualizado
    user = await coll.find_one({"_id": user_oid}, {"agents": 1})
    agent = None
    agents = user.get("agents", []) if user else []
    for a in agents:
        if str(a.get("_id")) == str(oid):
            agent = a
            break
    if not agent:
        raise HTTPException(status_code=404, detail="Agente no encontrado tras actualización")
    # serializar ids y fechas recursivamente
    agent_out = _sanitize_value(agent)
    return {"message": "Agente actualizado", "data": agent_out}


@router.delete("/")
async def delete_agent(agent_id: str | None = Query(None, alias="agent_id"), authorization: str | None = Header(None)):
    """Eliminar (pull) un agente del usuario."""
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
        oid = PyObjectId.parse(agent_id)
    except Exception:
        raise HTTPException(status_code=400, detail="agent_id inválido")

    coll = database.get_user_collection()
    agent = await coll.find_one({"_id": user_oid, "agents._id": oid}, {"agents.$": 1})
    if not agent:
        raise HTTPException(status_code=404, detail="Agente no encontrado o no pertenece al usuario")
    res = await coll.update_one({"_id": user_oid}, {"$pull": {"agents": {"_id": oid}}})
    if res.modified_count == 0:
        raise HTTPException(status_code=404, detail="Agente no encontrado")
    return {"message": "Agente eliminado", "data": {"id": auth._serialize_doc(agent)}}