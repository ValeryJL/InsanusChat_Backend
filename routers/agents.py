"""
Router de Agentes del Usuario con catálogo dinámico Multi-Proveedor (HU-01, HU-09).
"""
from datetime import datetime
from typing import Any, List, Optional
from fastapi import APIRouter, Body, Header, HTTPException, Query

from auth.crypto import decrypt_api_key
import database
from models import AgentListResponse, AgentResponse, PyObjectId, ResponseModel
from routers import auth
from utils.model_utils import (
    fetch_live_models_catalog,
    get_models_catalog,
    infer_provider_from_model,
    normalize_provider,
)

router = APIRouter(
    prefix="/api/v1/agents",
    tags=["Agentes"],
)


def _sanitize_value(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _sanitize_value(vv) for k, vv in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sanitize_value(x) for x in v]
    try:
        return str(v)
    except Exception:
        return "<unserializable>"


@router.get("/models", response_model=ResponseModel)
async def list_available_models(
    provider: Optional[str] = Query(None, description="Filtrar por proveedor: gemini, openai, anthropic, ollama, openrouter"),
    api_key_id: Optional[str] = Query(None, description="ID de API key del usuario para consultar modelos dinámicos"),
    refresh: bool = Query(False, description="Forzar recarga en vivo desde las APIs y repositorio público"),
    authorization: str | None = Header(None),
):
    """
    HU-09: Consulta en vivo las APIs oficiales de los proveedores (si el usuario tiene API Key)
    y el repositorio público de modelos activos (OpenRouter API) para devolver todos los modelos disponibles.
    """
    user = await auth.get_authenticated_user(authorization)
    keys_by_provider = {}

    for k in (user.get("api_keys") or []):
        if not isinstance(k, dict) or not k.get("active", True):
            continue
        k_prov = normalize_provider(k.get("provider"))
        plain_key = decrypt_api_key(k.get("encrypted_key") or "")
        base_url = k.get("base_url")
        if api_key_id and str(k.get("_id")) == str(api_key_id):
            keys_by_provider[k_prov] = (plain_key, base_url)
            break
        if k_prov not in keys_by_provider and plain_key:
            keys_by_provider[k_prov] = (plain_key, base_url)

    live_data = await fetch_live_models_catalog(
        provider=provider,
        api_keys_by_provider=keys_by_provider,
        force_refresh=refresh,
    )
    return ResponseModel(
        message=f"Modelos disponibles consultados en vivo ({live_data['total_models']} modelos)",
        data=live_data,
    )


@router.get("/", response_model=AgentListResponse)
async def list_agents(authorization: str | None = Header(None)):
    user = await auth.get_authenticated_user(authorization)
    agents = user.get("agents", [])
    out = []
    for a in agents:
        san = _sanitize_value(a)
        if isinstance(san, dict):
            msel = san.get("model_selected") or "gemini-2.5-flash"
            amodels = san.get("active_models") or []
            if not amodels:
                prov = normalize_provider(san.get("provider") or infer_provider_from_model(msel))
                cat = get_models_catalog(provider=prov).get(prov, [])
                amodels = [m["id"] for m in cat] or [msel]
            if msel not in amodels:
                amodels = [msel] + list(amodels)
            san["active_models"] = amodels
            san["model_selected"] = msel
        out.append(san)
    return AgentListResponse(message="Agentes listados", data=out)


@router.post("/", response_model=AgentResponse)
async def create_agent(
    authorization: str | None = Header(None),
    payload: dict = Body(
        ...,
        examples={
            "normal": {
                "summary": "Crear agente multi-proveedor con MCPs y Snippets",
                "value": {
                    "name": "Mi Agente",
                    "description": "Agente con herramientas",
                    "provider": "gemini",
                    "model_selected": "gemini-2.5-flash",
                    "system_prompt": ["Eres un asistente útil."],
                    "active_tools": [],
                    "active_mcps": [],
                    "snippets": [],
                },
            }
        },
    ),
):
    user = await auth.get_authenticated_user(authorization)
    user_oid = user["_id"]

    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name es requerido")

    raw_snippets: List[dict] = payload.get("snippets", []) or []
    snippets = []
    for s in raw_snippets:
        if not isinstance(s, dict):
            continue
        s_doc = dict(s)
        s_doc["_id"] = PyObjectId.new()
        s_doc.setdefault("created_at", datetime.utcnow())
        snippets.append(s_doc)

    raw_prompt = payload.get("system_prompt", [])
    if isinstance(raw_prompt, str):
        system_prompt = [raw_prompt] if raw_prompt.strip() else []
    elif isinstance(raw_prompt, list):
        system_prompt = [str(p) for p in raw_prompt if str(p).strip()]
    else:
        system_prompt = []

    model_selected = payload.get("model_selected") or "gemini-2.5-flash"
    provider = normalize_provider(payload.get("provider") or infer_provider_from_model(model_selected))
    raw_active_models = payload.get("active_models")
    if isinstance(raw_active_models, list) and len(raw_active_models) > 0:
        active_models = [str(m) for m in raw_active_models if str(m).strip()]
    else:
        cat = get_models_catalog(provider=provider).get(provider, [])
        active_models = [m["id"] for m in cat] or [model_selected]
    if model_selected not in active_models:
        active_models = [model_selected] + active_models

    active_tools = [str(t) for t in (payload.get("active_tools") or payload.get("allowed_tools") or [])]
    active_mcps = [str(m) for m in (payload.get("active_mcps") or payload.get("mcp_ids") or [])]

    agent_doc = {
        "_id": PyObjectId.new(),
        "name": name,
        "description": payload.get("description") or "",
        "system_prompt": system_prompt,
        "snippets": snippets,
        "active_tools": active_tools,
        "allowed_tools": active_tools,
        "active_mcps": active_mcps,
        "active_models": active_models,
        "provider": provider,
        "model_selected": model_selected,
        "model_fallback": payload.get("model_fallback"),
        "api_key_id": payload.get("api_key_id"),
        "temperature": float(payload.get("temperature", 0.7)),
        "metadata": payload.get("metadata", {}) or {},
        "created_at": datetime.utcnow(),
        "active": bool(payload.get("active", True)),
    }

    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$push": {"agents": agent_doc}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return AgentResponse(message="Agente creado", data=_sanitize_value(agent_doc))


@router.put("/", response_model=AgentResponse)
async def update_agent(
    agent_id: str | None = Query(None, alias="agent_id"),
    authorization: str | None = Header(None),
    payload: dict | None = Body(
        None,
        examples={"partial": {"summary": "Actualizar nombre y descripción", "value": {"name": "Nuevo nombre"}}},
    ),
):
    user = await auth.get_authenticated_user(authorization)
    user_oid = user["_id"]

    try:
        oid = PyObjectId.parse(agent_id)
    except Exception:
        raise HTTPException(status_code=400, detail="agent_id inválido")

    allowed = {
        "name",
        "description",
        "system_prompt",
        "active_tools",
        "allowed_tools",
        "active_mcps",
        "active_models",
        "provider",
        "model_selected",
        "model_fallback",
        "api_key_id",
        "temperature",
        "metadata",
        "active",
        "snippets",
    }
    update_fields = {}
    if payload:
        for k, v in payload.items():
            if k in allowed:
                update_fields[k] = v

    if not update_fields:
        raise HTTPException(status_code=400, detail="Nada para actualizar")

    if "system_prompt" in update_fields and isinstance(update_fields["system_prompt"], str):
        update_fields["system_prompt"] = [update_fields["system_prompt"]]

    if "active_tools" in update_fields and "allowed_tools" not in update_fields:
        update_fields["allowed_tools"] = update_fields["active_tools"]
    elif "allowed_tools" in update_fields and "active_tools" not in update_fields:
        update_fields["active_tools"] = update_fields["allowed_tools"]

    if "snippets" in update_fields and isinstance(update_fields["snippets"], list):
        norm = []
        for s in update_fields["snippets"]:
            if not isinstance(s, dict):
                continue
            sdoc = dict(s)
            if not sdoc.get("_id"):
                sdoc["_id"] = PyObjectId.new()
            else:
                try:
                    sdoc["_id"] = PyObjectId.parse(sdoc["_id"])
                except Exception:
                    sdoc["_id"] = PyObjectId.new()
            sdoc.setdefault("created_at", datetime.utcnow())
            norm.append(sdoc)
        update_fields["snippets"] = norm

    set_ops = {f"agents.$[a].{k}": v for k, v in update_fields.items()}
    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$set": set_ops}, array_filters=[{"a._id": oid}])
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Agente no encontrado")

    user_after = await coll.find_one({"_id": user_oid}, {"agents": 1})
    agent = next((a for a in (user_after.get("agents") or []) if str(a.get("_id")) == str(oid)), None)
    if not agent:
        raise HTTPException(status_code=404, detail="Agente no encontrado tras actualización")

    return AgentResponse(message="Agente actualizado", data=_sanitize_value(agent))


@router.delete("/", response_model=AgentResponse)
async def delete_agent(
    agent_id: str | None = Query(None, alias="agent_id"),
    authorization: str | None = Header(None),
):
    user = await auth.get_authenticated_user(authorization)
    user_oid = user["_id"]

    try:
        oid = PyObjectId.parse(agent_id)
    except Exception:
        raise HTTPException(status_code=400, detail="agent_id inválido")

    coll = database.get_user_collection()
    existing = next((a for a in (user.get("agents") or []) if str(a.get("_id")) == str(oid)), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Agente no encontrado")

    res = await coll.update_one({"_id": user_oid}, {"$pull": {"agents": {"_id": oid}}})
    if res.modified_count == 0:
        raise HTTPException(status_code=404, detail="Agente no encontrado")

    return AgentResponse(message="Agente eliminado", data=_sanitize_value(existing))
