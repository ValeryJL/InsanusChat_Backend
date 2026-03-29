"""
Router de Gestión de API Keys con cifrado simétrico Fernet en reposo y enmascaramiento (HU-05).
"""
from datetime import datetime
import logging
from fastapi import APIRouter, Body, Header, HTTPException, Query

from auth.crypto import encrypt_api_key, mask_api_key
import database
from models import APIKeyListResponse, APIKeyResponse, PyObjectId
from routers import auth
from utils.model_utils import normalize_provider

router = APIRouter(
    prefix="/api/v1/apikeys",
    tags=["API Keys"],
)

logger = logging.getLogger(__name__)


def _serialize_api_key_safe(k: dict) -> dict:
    """
    Serializa un documento de API Key para respuesta HTTP:
    NUNCA expone la clave en claro ni el token Fernet crudo; devuelve siempre el valor enmascarado.
    """
    kop = dict(k)
    if kop.get("_id") is not None:
        kop["_id"] = str(kop["_id"])
    raw_stored = kop.get("encrypted_key") or ""
    masked = kop.get("masked_key") or mask_api_key(raw_stored)
    kop["masked_key"] = masked
    # Por seguridad (HU-05), el campo encrypted_key en las respuestas HTTP también muestra la versión enmascarada
    kop["encrypted_key"] = masked
    if kop.get("created_at") is not None and hasattr(kop["created_at"], "isoformat"):
        kop["created_at"] = kop["created_at"].isoformat()
    if kop.get("last_used") is not None and hasattr(kop["last_used"], "isoformat"):
        kop["last_used"] = kop["last_used"].isoformat()
    return kop


@router.get("/", response_model=APIKeyListResponse)
async def list_api_keys(authorization: str | None = Header(None)):
    user = await auth.get_authenticated_user(authorization)
    api_keys = user.get("api_keys", [])
    out = [_serialize_api_key_safe(k) for k in api_keys]
    return APIKeyListResponse(message="API keys listadas", data=out)


@router.post("/", response_model=APIKeyResponse)
async def create_api_key(
    authorization: str | None = Header(None),
    body: dict = Body(
        ...,
        examples={
            "example": {
                "summary": "Crear API Key (se cifra automáticamente con Fernet)",
                "value": {"provider": "gemini", "api_key": "AIzaSyYourRealKeyHere", "label": "Mi Gemini Pro"},
            }
        },
    ),
):
    user = await auth.get_authenticated_user(authorization)
    user_oid = user["_id"]

    if not body or not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="payload inválido")

    provider = normalize_provider(body.get("provider"))
    # Aceptamos tanto 'api_key' como 'encrypted_key' o 'key' en el body por retrocompatibilidad
    raw_key = (body.get("api_key") or body.get("encrypted_key") or body.get("key") or "").strip()
    label = body.get("label") or f"Clave {provider.capitalize()}"
    base_url = body.get("base_url")

    if not body.get("provider") or not raw_key:
        raise HTTPException(status_code=400, detail="provider y api_key (o encrypted_key) son requeridos")

    cipher_text = encrypt_api_key(raw_key)
    masked = mask_api_key(raw_key)

    api_key_doc = {
        "_id": PyObjectId.new(),
        "provider": provider,
        "label": label,
        "encrypted_key": cipher_text,
        "masked_key": masked,
        "base_url": base_url,
        "created_at": datetime.utcnow(),
        "last_used": None,
        "active": True,
    }

    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$push": {"api_keys": api_key_doc}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return APIKeyResponse(message="API key creada y cifrada correctamente", data=_serialize_api_key_safe(api_key_doc))


@router.put("/", response_model=APIKeyResponse)
async def update_api_key(
    api_key_id: str | None = Query(None, alias="api_key_id"),
    authorization: str | None = Header(None),
    body: dict = Body(..., examples={"update": {"value": {"label": "Nuevo label", "active": True}}}),
):
    user = await auth.get_authenticated_user(authorization)
    user_oid = user["_id"]

    if not api_key_id:
        raise HTTPException(status_code=400, detail="api_key_id (query) es requerido")
    try:
        key_oid = PyObjectId.parse(api_key_id)
    except Exception:
        raise HTTPException(status_code=400, detail="api_key_id inválido")

    if not body or not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="payload inválido")

    set_ops = {}
    if "label" in body:
        set_ops["api_keys.$[k].label"] = body["label"]
    if "active" in body:
        set_ops["api_keys.$[k].active"] = bool(body["active"])
    if "provider" in body and body["provider"]:
        set_ops["api_keys.$[k].provider"] = normalize_provider(body["provider"])
    if "base_url" in body:
        set_ops["api_keys.$[k].base_url"] = body["base_url"]

    new_raw_key = body.get("api_key") or body.get("encrypted_key")
    if new_raw_key and isinstance(new_raw_key, str) and "..." not in new_raw_key:
        set_ops["api_keys.$[k].encrypted_key"] = encrypt_api_key(new_raw_key.strip())
        set_ops["api_keys.$[k].masked_key"] = mask_api_key(new_raw_key.strip())

    if not set_ops:
        raise HTTPException(status_code=400, detail="Nada para actualizar")

    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$set": set_ops}, array_filters=[{"k._id": key_oid}])
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    user_after = await coll.find_one({"_id": user_oid}, {"api_keys": 1})
    updated = next((k for k in (user_after.get("api_keys") or []) if str(k.get("_id")) == str(key_oid)), None)
    if not updated:
        raise HTTPException(status_code=404, detail="API key no encontrada")

    return APIKeyResponse(message="API key actualizada", data=_serialize_api_key_safe(updated))


@router.delete("/", response_model=APIKeyResponse)
async def delete_api_key(
    api_key_id: str | None = Query(None, alias="api_key_id"),
    authorization: str | None = Header(None),
):
    user = await auth.get_authenticated_user(authorization)
    user_oid = user["_id"]

    if not api_key_id:
        raise HTTPException(status_code=400, detail="api_key_id (query) es requerido")
    try:
        key_oid = PyObjectId.parse(api_key_id)
    except Exception:
        raise HTTPException(status_code=400, detail="api_key_id inválido")

    existing = next((k for k in (user.get("api_keys") or []) if str(k.get("_id")) == str(key_oid)), None)
    if not existing:
        raise HTTPException(status_code=404, detail="API key no encontrada")

    kop = _serialize_api_key_safe(existing)
    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$pull": {"api_keys": {"_id": key_oid}}})
    if res.modified_count == 0:
        raise HTTPException(status_code=404, detail="API key no encontrada o no eliminada")

    return APIKeyResponse(message="API key eliminada", data={"deleted": kop})
