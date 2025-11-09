import os
from typing import Any, Optional, List, Dict 
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Header, Body
from models import PyObjectId, UserModel, ResponseModel
from pydantic import BaseModel, Field
import logging
from dotenv import load_dotenv, find_dotenv
import database
from datetime import datetime
from pymongo import ReturnDocument
from auth.auth import verify_password, create_access_token, decode_access_token, get_password_hash
import re
from bson import ObjectId

# Cargar variables de entorno desde .env (busca en el proyecto)
load_dotenv(find_dotenv())

# Cargamos .env para obtener claves locales si están definidas

# 1. Crear una instancia de APIRouter
router = APIRouter(
    prefix="/api/v1/auth",  # Todas las rutas aquí comenzarán con /api/v1/users
    tags=["Usuarios"],       # Etiqueta para agrupar en la documentación
)

def authenticate_token(token: str):
    """Intentar verificar un token local (JWT) y si falla, verificar con Firebase.
    Devuelve un dict normalizado: {"auth_type": "local"|"firebase", "user_id": str, "payload": {...}}
    Lanzará HTTPException(401) si ninguno es válido.
    """
    """Verifica un token local JWT y devuelve un dict normalizado.
    Devuelve: {"auth_type": "local", "user_id": str, "uid": str, "payload": {...}}
    Lanzará HTTPException(401) si el token no es válido.
    """
    logger = logging.getLogger(__name__)
    logger.debug("authenticate_token called (preview 64): %s", (token[:64] if isinstance(token, str) else token))
    try:
        payload = decode_access_token(token)
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Token inválido: sin 'sub'")
        # Devolver 'uid' por compatibilidad con código existente
        return { "auth_type": "local", "user_id": str(sub), "uid": str(sub), "payload": payload}
    except Exception as e:
        logging.exception("Error verificando token local")
        raise HTTPException(status_code=401, detail=str(e))


def _serialize_doc(doc: Any) -> Any:
    """
    Convierte recursivamente bson.ObjectId -> str y datetime -> ISO en todo el documento.
    Devuelve una estructura nueva (dict/list/primitive) segura para Pydantic/JSON.
    """
    logger = logging.getLogger(__name__)
    logger.debug("_serialize_doc called with type=%s", type(doc))
    def convert(obj: Any) -> Any:
        # Objetos atómicos
        try:
            if isinstance(obj, (str, int, float, bool)) or obj is None:
                return obj
            # bson.ObjectId (runtime instances) o PyObjectId
            if isinstance(obj, (ObjectId, PyObjectId)):
                logger.debug("_serialize_doc.convert - converting ObjectId/PyObjectId: %s (type=%s)", obj, type(obj))
                return str(obj)
            if isinstance(obj, datetime):
                logger.debug("_serialize_doc.convert - converting datetime: %s", obj)
                return obj.isoformat()
            # Estructuras compuestas
            if isinstance(obj, dict):
                logger.debug("_serialize_doc.convert - dict with %d keys", len(obj))
                return {k: convert(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple, set)):
                logger.debug("_serialize_doc.convert - iterable of length %d (type=%s)", len(obj), type(obj))
                converted = [convert(v) for v in obj]
                if isinstance(obj, tuple):
                    return tuple(converted)
                if isinstance(obj, set):
                    return set(converted)
                return converted
        except Exception as e:
            logger.exception("_serialize_doc.convert error for obj type %s: %s", type(obj), e)
        # Otros tipos (int, str, float, bool, None, etc.)
        return obj

    return convert(doc)

class AuthUserModel(BaseModel):
    """
    Versión ligera del usuario usada por endpoints de autenticación (no incluye mcps, chats, api_keys, agents).
    """
    id: PyObjectId = Field(alias="_id")
    email: str
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

@router.post("/", response_model=ResponseModel)
async def verify_token(authorization: Optional[str] = Header(None)):
    """
    Verifica un token local (Authorization: Bearer <token>). Devuelve payload decodificado.
    """
    logger = logging.getLogger(__name__)
    logger.info("POST /api/v1/auth/ verify_token called")
    logger.debug("Authorization header: %s", authorization)
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("verify_token - token missing/invalid format")
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    try:
        decoded = authenticate_token(token)
        # asegurar compatibilidad: exponer tanto "uid" como "user_id"
        data = dict(decoded)
        if "uid" not in data and "user_id" in data:
            data["uid"] = data["user_id"]
        return ResponseModel(message="Token verificado", data=data)
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error verificando token")
        raise HTTPException(status_code=401, detail=str(e))
    
@router.get("/", response_model=ResponseModel)
async def get_user_profile(authorization: str | None = Header(None)):
    """
    Devuelve el perfil del usuario. Si se pasa `uid` devuelve ese usuario.
    Si no se pasa `uid`, requiere Authorization y devuelve el perfil del usuario autenticado.
    """
    logger = logging.getLogger(__name__)
    logger.info("GET /api/v1/auth/ - start get_user_profile")
    logger.debug("Authorization header raw: %s", authorization)
    try:
        coll = database.get_user_collection()
        if not authorization or not authorization.startswith("Bearer "):
            logger.warning("Token no provisto o formato incorrecto")
            raise HTTPException(status_code=401, detail="Token no provisto")
        token = authorization.split(" ", 1)[1]
        logger.info("Token extraido (preview 64): %s", token[:64])
        decoded = authenticate_token(token)
        logger.debug("Token decodificado: %s", decoded)

        # Token local: buscar por _id
        try:
            user_id_raw = decoded.get("user_id")
            logger.debug("user_id raw from token: %s (type=%s)", user_id_raw, type(user_id_raw))
            oid = PyObjectId.parse(user_id_raw)
            logger.info("Parsed user_id -> ObjectId: %s", oid)
        except Exception as e:
            logger.exception("Error parseando user_id desde token")
            raise HTTPException(status_code=400, detail="user id inválido")

        logger.debug("Buscando usuario en collecion por _id: %s", oid)
        user_doc = await coll.find_one({"_id": oid})
        logger.debug("Resultado find_one user_doc type=%s", type(user_doc))
        logger.debug("user_doc keys: %s", list(user_doc.keys()) if user_doc else None)
        logger.debug("user_doc preview: %s", {k: (str(v) if isinstance(v, (ObjectId, PyObjectId, datetime)) else v) for k, v in (user_doc.items() if user_doc else [])})

        if not user_doc:
            logger.warning("Usuario no encontrado para _id=%s", oid)
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        # Limitar la respuesta a los campos de AuthUserModel
        logger.info("Validando user_doc con AuthUserModel")
        safe_doc = _serialize_doc(user_doc)
        logger.debug("safe_doc type=%s keys=%s", type(safe_doc), list(safe_doc.keys()))
        auth_user = AuthUserModel.model_validate(safe_doc)
        logger.debug("AuthUserModel instance created: %s", auth_user)
        dumped = auth_user.model_dump()
        logger.debug("AuthUserModel.model_dump() keys=%s types=%s", list(dumped.keys()), {k: type(v).__name__ for k, v in dumped.items()})
        serialized = _serialize_doc(dumped)
        logger.info("User profile serialized, returning response")
        logger.debug("Response data preview: %s", serialized)

        return ResponseModel(message="Perfil recuperado", data=serialized)
    except HTTPException:
        logger.info("Raising HTTPException from get_user_profile")
        raise
    except Exception as e:
        logger.exception("Error recuperando usuario")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/", response_model=ResponseModel)
async def update_user_profile(
    authorization: str | None = Header(None),
    payload: dict | None = Body(
        None,
        examples={
            "update_profile": {
                "summary": "Actualizar perfil parcial",
                "value": {"display_name": "Nuevo Nombre", "settings": {"theme": "dark"}}
            }
        },
    ),
):
    """
    Actualiza (o crea) el perfil del usuario autenticado usando datos en la base de datos.
    """
    logger = logging.getLogger(__name__)
    logger.info("PUT /api/v1/auth/ update_user_profile called")
    logger.debug("Authorization header: %s", authorization)
    logger.debug("Payload preview: %s", payload)
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("update_user_profile - token missing/invalid format")
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    decoded = authenticate_token(token)
    # decoded es un dict normalizado: {auth_type, user_id, payload}

    # Construir campos a actualizar desde payload y desde token
    update_fields = {}
    if payload:
        # aceptamos un dict parcial con campos permitidos
        allowed = {"email", "display_name", "roles", "settings", "metadata"}
        for k, v in payload.items():
            if k in allowed:
                update_fields[k] = v

        # Si el payload incluye una contraseña en claro, guardamos su hash
        if "password" in payload:
            pw = payload.get("password")
            if pw:
                update_fields["password_hash"] = get_password_hash(pw)
            # nunca persistas la contraseña en claro
            if "password" in update_fields:
                del update_fields["password"]

    # Si el token incluye email en su payload (opcional), preferirlo
    token_payload = decoded.get("payload") or {}
    if token_payload.get("email"):
        update_fields["email"] = token_payload.get("email")

    # Preferir display_name del payload, si no usar el del token
    if "display_name" not in update_fields and decoded.get("name"):
        update_fields["display_name"] = decoded.get("name")

    update_fields["last_login"] = datetime.utcnow()

    try:
        coll = database.get_user_collection()

        # Token local: buscamos por _id (el subject del token) y actualizamos
        local_id = decoded.get("user_id")
        try:
            oid = PyObjectId.parse(local_id)
        except Exception:
            raise HTTPException(status_code=400, detail="user id inválido")

        if not update_fields:
            update_fields = {}

        update_op = {"$set": update_fields}
        updated = await coll.find_one_and_update(
            {"_id": oid},
            update_op,
            upsert=False,
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
    except Exception as e:
        logging.exception("Error actualizando/creando usuario en DB")
        raise HTTPException(status_code=500, detail=str(e))

    # Validar/limitar la respuesta con AuthUserModel
    auth_user = AuthUserModel.model_validate(_serialize_doc(updated))
    return ResponseModel(message="Usuario actualizado", data=_serialize_doc(auth_user.model_dump()))


@router.post("/login", response_model=ResponseModel)
async def local_login(
    payload: dict = Body(
        ...,
        examples={
            "default": {"summary": "Login local", "value": {"email": "user@example.com", "password": "secret"}}
        },
    )
):
    """
    Login local usando email + password (dev/registro local).
    Devuelve un JWT creado por `auth.auth.create_access_token` con subject = ObjectId del usuario.
    """
    logger = logging.getLogger(__name__)
    logger.info("POST /api/v1/auth/login called")
    logger.debug("Payload keys: %s", list(payload.keys()) if isinstance(payload, dict) else str(type(payload)))
    email = payload.get("email")
    password = payload.get("password")
    if not email or not password:
        raise HTTPException(status_code=400, detail="email y password requeridos")

    try:
        coll = database.get_user_collection()
        user_doc = await coll.find_one({"email": email})
        if not user_doc:
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

        pw_hash = user_doc.get("password_hash")
        if not pw_hash or not verify_password(password, pw_hash):
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

        # actualizar last_login
        await coll.update_one({"_id": user_doc["_id"]}, {"$set": {"last_login": datetime.utcnow()}})

        # crear token local (subject = id del documento)
        subject = str(user_doc.get("_id"))
        token = create_access_token(subject)

        return ResponseModel(message="Login OK", data={"access_token": token, "token_type": "bearer", "user_id": subject})
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error en login local")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/register", response_model=ResponseModel)
async def register(
    payload: dict = Body(
        ...,
        examples={
            "default": {"summary": "Registro local", "value": {"email": "user@example.com", "password": "secret", "display_name": "Usuario Demo"}}
        },
    )
):
    """Registrar un usuario local (email + password + display_name). Devuelve token local JWT."""

    logger = logging.getLogger(__name__)
    logger.info("POST /api/v1/auth/register called")
    logger.debug("Register payload keys: %s", list(payload.keys()) if isinstance(payload, dict) else str(type(payload)))
    email = payload.get("email")
    password = payload.get("password")
    display_name = payload.get("display_name") or payload.get("name")
    if not email or not password:
        raise HTTPException(status_code=400, detail="email y password requeridos")

    # El nombre de usuario es obligatorio
    if not display_name:
        raise HTTPException(status_code=400, detail="Nombre de usuario (display_name) requerido")

    # Normalizar email para evitar duplicados por mayúsculas/espacios
    email_normalized = email.strip().lower()

    # Normalizar display_name para comprobaciones (pero mantener el original si se guarda)
    display_name_check = display_name.strip()
    if display_name_check == "":
        raise HTTPException(status_code=400, detail="Nombre de usuario inválido")

    try:
        coll = database.get_user_collection()

        # Comprobar email existente
        existing_email = await coll.find_one({"email": email_normalized})
        if existing_email:
            raise HTTPException(status_code=400, detail="Correo electrónico ya registrado")

        # Comprobar display_name (comparación case-insensitive exacta)
        regex = {"$regex": f"^{re.escape(display_name_check)}$", "$options": "i"}
        existing_name = await coll.find_one({"display_name": regex})
        if existing_name:
            raise HTTPException(status_code=400, detail="Nombre de usuario ya en uso")

        user_doc = {
            "_id": PyObjectId.new(),
            "email": email_normalized,
            "display_name": display_name_check,
            "password_hash": get_password_hash(password),
            "created_at": datetime.utcnow(),
            "last_login": datetime.utcnow(),
            "mcps": [],
            "code_snippets": [],
            "api_keys": [],
            "roles": [],
            "settings": {},
            "metadata": {},
        }

        await coll.insert_one(user_doc)

        return ResponseModel(message="Usuario creado", data={"user_id": str(user_doc["_id"])})
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error registrando usuario local")
        raise HTTPException(status_code=500, detail=str(e))