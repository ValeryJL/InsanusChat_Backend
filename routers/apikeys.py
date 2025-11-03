from fastapi import APIRouter, HTTPException, Header, Body
from routers import auth
import database
from models import PyObjectId, UserAPIKeyModel
from datetime import datetime
router = APIRouter(
    prefix="/api/v1/apikeys",  # Todas las rutas aquí comenzarán con /api/v1/apikeys
    tags=["API Keys"],       # Etiqueta para agrupar en la documentación
)

@router.get("/")
async def list_api_keys(authorization: str | None = Header(None)):
    """
    Endpoint de ejemplo para listar API Keys.
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
    user = await coll.find_one({"_id": user_oid}, {"api_keys": 1})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    api_keys = user.get("api_keys", [])
    # serializar _id y fechas
    out = []
    for k in api_keys:
        kop = dict(k)
        if kop.get("_id") is not None:
            kop["_id"] = str(kop["_id"])
        if kop.get("created_at") is not None:
            kop["created_at"] = kop["created_at"].isoformat()
        if kop.get("last_used") is not None:
            kop["last_used"] = kop["last_used"].isoformat()
        out.append(kop)
    return {"message": "API keys listadas", "data": out}

@router.post("/")
async def create_api_key(authorization: str | None = Header(None), body: dict = Body(...)):
    """
    Endpoint de ejemplo para crear una nueva API Key.
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

    # validar payload mínimo
    if not body or not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="payload inválido")
    provider = body.get("provider")
    encrypted_key = body.get("encrypted_key")
    label = body.get("label")
    if not provider or not encrypted_key:
        raise HTTPException(status_code=400, detail="provider y encrypted_key son requeridos")

    api_key_doc = {
        "_id": PyObjectId.new(),
        "provider": provider,
        "label": label,
        "encrypted_key": encrypted_key,
        "created_at": datetime.utcnow(),
        "last_used": None,
        "active": True,
    }

    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$push": {"api_keys": api_key_doc}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # serializar respuesta
    out = dict(api_key_doc)
    out["_id"] = str(out["_id"])
    out["created_at"] = out["created_at"].isoformat()
    return {"message": "API key creada", "data": out}

@router.put("/{key_id}")
async def update_api_key(key_id: str, authorization: str | None = Header(None), body: dict = Body(...)):
    """
    Endpoint de ejemplo para actualizar una API Key.
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
        key_oid = PyObjectId.parse(key_id)
    except Exception:
        raise HTTPException(status_code=400, detail="key_id inválido")

    if not body or not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="payload inválido")

    # permitimos actualizar label, active y encrypted_key
    allowed = {"label", "active", "encrypted_key"}
    set_ops = {}
    for k, v in body.items():
        if k in allowed:
            set_ops[f"api_keys.$[k].{k}"] = v

    if not set_ops:
        raise HTTPException(status_code=400, detail="Nada para actualizar")

    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$set": set_ops}, array_filters=[{"k._id": key_oid}])
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if res.modified_count == 0:
        raise HTTPException(status_code=404, detail="API key no encontrada o sin cambios")

    # recuperar la key actualizada
    user = await coll.find_one({"_id": user_oid}, {"api_keys": 1})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    updated = None
    for k in user.get("api_keys", []):
        if str(k.get("_id")) == str(key_oid):
            updated = k
            break
    if not updated:
        raise HTTPException(status_code=404, detail="API key no encontrada tras actualización")

    kop = dict(updated)
    kop["_id"] = str(kop["_id"])
    if kop.get("created_at"):
        kop["created_at"] = kop["created_at"].isoformat()
    if kop.get("last_used"):
        kop["last_used"] = kop["last_used"].isoformat()
    return {"message": "API key actualizada", "data": kop}

@router.delete("/{key_id}")
async def delete_api_key(key_id: str, authorization: str | None = Header(None)):
    """
    Endpoint de ejemplo para eliminar una API Key.
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
        key_oid = PyObjectId.parse(key_id)
    except Exception:
        raise HTTPException(status_code=400, detail="key_id inválido")

    coll = database.get_user_collection()
    res = await coll.update_one({"_id": user_oid}, {"$pull": {"api_keys": {"_id": key_oid}}})
    if res.modified_count == 0:
        raise HTTPException(status_code=404, detail="API key no encontrada")
    return {"message": "API key eliminada", "data": {"id": str(key_id)}}