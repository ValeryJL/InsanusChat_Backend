import os
from typing import Any, Optional, List, Dict 
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth
from fastapi import APIRouter, HTTPException, Header
from models import PyObjectId, UserModel, ResponseModel
from pydantic import BaseModel, EmailStr, Field
import logging
from dotenv import load_dotenv, find_dotenv
import database
from datetime import datetime
from bson import ObjectId
from pymongo import ReturnDocument

# Cargar variables de entorno desde .env (busca en el proyecto)
load_dotenv(find_dotenv())

# Avisar en dev si no se cargó la variable esperada
if not os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH"):
    logging.warning(
        "FIREBASE_SERVICE_ACCOUNT_PATH no encontrado en el entorno. "
        "Asegúrate de tener un .env con esa variable o exportarla."
    )

# 1. Crear una instancia de APIRouter
router = APIRouter(
    prefix="/api/v1/auth",  # Todas las rutas aquí comenzarán con /api/v1/users
    tags=["Usuarios"],       # Etiqueta para agrupar en la documentación
)

service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
if not service_account_path:
    # en dev lanzar error temprano para que lo configures
    raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_PATH no está definido en .env")

if not firebase_admin._apps:
    cred = credentials.Certificate(service_account_path)
    firebase_admin.initialize_app(cred)

def authenticate_token(token: str):
    """Verifica el ID token con Firebase y devuelve el payload decodificado.
    Lanzará HTTPException(401) si el token no es válido.
    """
    try:
        decoded = firebase_auth.verify_id_token(token)
        return decoded
    except firebase_auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="ID token inválido")
    except Exception as e:
        logging.exception("Error verificando token")
        raise HTTPException(status_code=401, detail=str(e))


def _serialize_doc(doc: dict) -> dict:
    if not doc:
        return doc
    out = dict(doc)
    if "_id" in out and isinstance(out["_id"], ObjectId):
        out["_id"] = str(out["_id"])
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = v.isoformat()
    return out

class AuthUserModel(BaseModel):
    """
    Versión ligera del usuario usada por endpoints de autenticación (no incluye mcps, chats, api_keys, agents).
    """
    firebase_id: str
    email: EmailStr
    display_name: Optional[str] = None
    created_at: datetime
    last_login: Optional[datetime] = None
    roles: List[str] = Field(default_factory=list)
    settings: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": { PyObjectId: str, datetime: lambda v: v.isoformat() }
    }

# Nota: usamos `AuthUserModel` para respuestas y validación de DB.
# Para las actualizaciones aceptamos un payload parcial (dict) con campos permitidos.

@router.post("/verify", response_model=ResponseModel)
async def verify_token(authorization: Optional[str] = Header(None)):
    """
    Verifica un ID token de Firebase (Authorization: Bearer <token>).
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    try:
        decoded = firebase_auth.verify_id_token(token)
        return ResponseModel(message="Token verificado", data=decoded)
    except firebase_auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="ID token inválido")
    except Exception as e:
        logging.exception("Error verificando token")
        raise HTTPException(status_code=401, detail=str(e))
    
@router.get("/profile", response_model=ResponseModel)
async def get_user_profile(uid: str | None = None, authorization: str | None = Header(None)):
    """
    Devuelve el perfil del usuario. Si se pasa `uid` devuelve ese usuario.
    Si no se pasa `uid`, requiere Authorization y devuelve el perfil del usuario autenticado.
    """
    try:
        coll = database.get_user_collection()
        if uid:
            user_doc = await coll.find_one({"firebase_id": uid})
        else:
            if not authorization or not authorization.startswith("Bearer "):
                raise HTTPException(status_code=401, detail="Token no provisto")
            token = authorization.split(" ", 1)[1]
            decoded = authenticate_token(token)
            uid = decoded.get("uid")
            user_doc = await coll.find_one({"firebase_id": uid})

            if not user_doc:
                raise HTTPException(status_code=404, detail="Usuario no encontrado")

            # Limitar la respuesta a los campos de AuthUserModel
            auth_user = AuthUserModel.model_validate(_serialize_doc(user_doc))
            return ResponseModel(message="Perfil recuperado", data=auth_user.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error recuperando usuario")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/profile", response_model=ResponseModel)
async def update_user_profile(authorization: str | None = Header(None), payload: dict | None = None):
    """
    Actualiza (o crea) el perfil del usuario autenticado usando datos en la base de datos.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    decoded = authenticate_token(token)
    uid = decoded.get("uid")

    # Construir campos a actualizar desde payload y desde token
    update_fields = {}
    if payload:
        # aceptamos un dict parcial con campos permitidos
        allowed = {"email", "display_name", "roles", "settings", "metadata"}
        for k, v in payload.items():
            if k in allowed:
                update_fields[k] = v

    # Usar email proveniente de Firebase siempre que exista (garantizar identidad)
    if decoded.get("email"):
        update_fields["email"] = decoded.get("email")

    # Preferir display_name del payload, si no usar el del token
    if "display_name" not in update_fields and decoded.get("name"):
        update_fields["display_name"] = decoded.get("name")

    update_fields["last_login"] = datetime.utcnow()

    try:
        coll = database.get_user_collection()
        set_on_insert = {
            "firebase_id": uid,
            "created_at": datetime.utcnow(),
            "mcps": [],
            "code_snippets": [],
            "api_keys": [],
            "roles": [],
            "settings": {},
            "metadata": {},
        }

        # Evitar conflicto MongoDB: si update_fields contiene alguna clave,
        # no incluirla también en $setOnInsert (Mongo no permite la misma ruta en dos operadores).
        for k in list(set_on_insert.keys()):
            if k in update_fields:
                del set_on_insert[k]

        update_op = {"$set": update_fields}
        if set_on_insert:
            update_op["$setOnInsert"] = set_on_insert

        updated = await coll.find_one_and_update(
            {"firebase_id": uid},
            update_op,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except Exception as e:
        logging.exception("Error actualizando/creando usuario en DB")
        raise HTTPException(status_code=500, detail=str(e))

    # Validar/limitar la respuesta con AuthUserModel
    auth_user = AuthUserModel.model_validate(_serialize_doc(updated))
    return ResponseModel(message="Usuario actualizado", data=auth_user.model_dump())