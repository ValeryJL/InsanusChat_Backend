"""
Router de Autenticación, Perfil, Bootstrap de Administrador y Rate Limiting (HU-01, HU-04, HU-07).
"""
import logging
import os
import re
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from dotenv import find_dotenv, load_dotenv
from fastapi import APIRouter, Body, Header, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

import database
from auth.auth import create_access_token, decode_access_token, get_password_hash, verify_password
from models import AuthTokenResponse, PyObjectId, ResponseModel, UserResponse

load_dotenv(find_dotenv())

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Usuarios"],
)

# Rate Limiter en memoria por IP (HU-07)
_RATE_LIMIT_BUCKETS: Dict[str, List[float]] = defaultdict(list)


def check_rate_limit(client_ip: str, max_requests: int = 30, window_seconds: int = 60):
    now = time.time()
    bucket = _RATE_LIMIT_BUCKETS[client_ip]
    _RATE_LIMIT_BUCKETS[client_ip] = [t for t in bucket if now - t < window_seconds]
    if len(_RATE_LIMIT_BUCKETS[client_ip]) >= max_requests:
        raise HTTPException(
            status_code=429,
            detail=f"Demasiados intentos desde esta IP. Intente nuevamente en {window_seconds} segundos.",
        )
    _RATE_LIMIT_BUCKETS[client_ip].append(now)


def authenticate_token(token: str) -> Dict[str, Any]:
    """Verifica un token local JWT y devuelve un dict normalizado."""
    if not token:
        raise HTTPException(status_code=401, detail="Token no provisto")
    try:
        if isinstance(token, str) and token.lower().startswith("bearer "):
            token = token.split(" ", 1)[1].strip()
        payload = decode_access_token(token)
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Token inválido: sin 'sub'")
        return {"auth_type": "local", "user_id": str(sub), "uid": str(sub), "payload": payload}
    except HTTPException:
        raise
    except Exception as e:
        logging.debug("Error verificando token local: %s", e)
        raise HTTPException(status_code=401, detail=f"Token inválido o expirado: {str(e)}")


async def get_authenticated_user(authorization: Optional[str]) -> Dict[str, Any]:
    """Valida el header Authorization y recupera el documento completo del usuario en MongoDB."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Token no provisto")
    decoded = authenticate_token(authorization)
    uid = decoded.get("user_id")
    try:
        oid = PyObjectId.parse(uid)
    except Exception:
        raise HTTPException(status_code=400, detail="user id inválido")
    coll = database.get_user_collection()
    user_doc = await coll.find_one({"_id": oid})
    if not user_doc:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if not user_doc.get("active", True):
        raise HTTPException(status_code=403, detail="Cuenta de usuario suspendida por el administrador")
    return user_doc


async def require_admin_user(authorization: Optional[str]) -> Dict[str, Any]:
    """Verifica que el usuario esté autenticado y posea el rol 'admin'."""
    user_doc = await get_authenticated_user(authorization)
    roles = user_doc.get("roles") or []
    if "admin" not in roles:
        raise HTTPException(
            status_code=403,
            detail="Acceso denegado: se requieren privilegios de Administrador (rol 'admin').",
        )
    return user_doc


def _serialize_doc(doc: Any) -> Any:
    """Convierte recursivamente bson.ObjectId -> str y datetime -> ISO."""
    def convert(obj: Any) -> Any:
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        if isinstance(obj, (ObjectId, PyObjectId)):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: convert(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [convert(v) for v in obj]
        return obj

    return convert(doc)


class AuthUserModel(BaseModel):
    id: PyObjectId = Field(alias="_id")
    email: str
    display_name: Optional[str] = None
    created_at: datetime
    last_login: Optional[datetime] = None
    active: bool = True
    roles: List[str] = Field(default_factory=list)
    settings: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {PyObjectId: str, ObjectId: str, datetime: lambda v: v.isoformat()},
    }


@router.post("/", response_model=AuthTokenResponse)
async def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Token no provisto")
    decoded = authenticate_token(authorization)
    data = dict(decoded)
    if "uid" not in data and "user_id" in data:
        data["uid"] = data["user_id"]
    return AuthTokenResponse(message="Token verificado", data=data)


@router.get("/", response_model=UserResponse)
async def get_user_profile(authorization: str | None = Header(None)):
    user_doc = await get_authenticated_user(authorization)
    safe_doc = _serialize_doc(user_doc)
    auth_user = AuthUserModel.model_validate(safe_doc)
    serialized = _serialize_doc(auth_user.model_dump(by_alias=True))
    return UserResponse(message="Perfil recuperado", data=serialized)


@router.put("/", response_model=UserResponse)
async def update_user_profile(
    authorization: str | None = Header(None),
    payload: dict | None = Body(
        None,
        examples={
            "update_profile": {
                "summary": "Actualizar perfil parcial",
                "value": {"display_name": "Nuevo Nombre", "settings": {"theme": "dark"}},
            }
        },
    ),
):
    user_doc = await get_authenticated_user(authorization)
    oid = user_doc["_id"]

    update_fields: Dict[str, Any] = {}
    if payload:
        # Solo un admin puede modificar sus propios roles desde aquí
        is_admin = "admin" in (user_doc.get("roles") or [])
        allowed = {"email", "display_name", "settings", "metadata"}
        if is_admin:
            allowed.add("roles")
        for k, v in payload.items():
            if k in allowed:
                update_fields[k] = v
        if "username" in payload and "display_name" not in update_fields:
            update_fields["display_name"] = payload["username"]
        if "password" in payload and payload.get("password"):
            update_fields["password_hash"] = get_password_hash(payload["password"])

    update_fields["last_login"] = datetime.utcnow()
    coll = database.get_user_collection()
    updated = await coll.find_one_and_update(
        {"_id": oid},
        {"$set": update_fields},
        upsert=False,
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    auth_user = AuthUserModel.model_validate(_serialize_doc(updated))
    return UserResponse(message="Usuario actualizado", data=_serialize_doc(auth_user.model_dump(by_alias=True)))


@router.post("/login", response_model=AuthTokenResponse)
async def local_login(
    request: Request,
    payload: dict = Body(
        ...,
        examples={"default": {"summary": "Login local", "value": {"email": "user@example.com", "password": "secret"}}},
    ),
):
    sys_settings = await database.ensure_system_settings()
    limit_per_min = int(sys_settings.get("rate_limit_login_per_min") or 30)
    client_ip = request.client.host if request.client else "127.0.0.1"
    check_rate_limit(f"login:{client_ip}", max_requests=limit_per_min)

    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password")
    if not email or not password:
        raise HTTPException(status_code=400, detail="email y password requeridos")

    coll = database.get_user_collection()
    user_doc = await coll.find_one({"email": email})
    if not user_doc:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    if not user_doc.get("active", True):
        raise HTTPException(status_code=403, detail="Esta cuenta se encuentra suspendida")

    pw_hash = user_doc.get("password_hash")
    if not pw_hash or not verify_password(password, pw_hash):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    await coll.update_one({"_id": user_doc["_id"]}, {"$set": {"last_login": datetime.utcnow()}})

    subject = str(user_doc.get("_id"))
    token = create_access_token(subject)
    roles = user_doc.get("roles") or ["user"]

    return AuthTokenResponse(
        message="Login OK",
        data={
            "access_token": token,
            "token_type": "bearer",
            "user_id": subject,
            "display_name": user_doc.get("display_name") or email,
            "email": user_doc.get("email"),
            "roles": roles,
        },
    )


@router.post("/register", response_model=ResponseModel)
async def register(
    request: Request,
    payload: dict = Body(
        ...,
        examples={
            "default": {
                "summary": "Registro local",
                "value": {"email": "user@example.com", "password": "secret", "display_name": "Usuario Demo"},
            }
        },
    ),
):
    """
    Registra un nuevo usuario local.
    Bootstrap de Admin: si es el primer usuario registrado en la base de datos
    (o su email coincide con ADMIN_EMAIL), recibe automáticamente el rol 'admin'.
    Además, se le preconfigura un Agente por defecto y el servidor MCP Calculadora de ejemplo.
    """
    sys_settings = await database.ensure_system_settings()
    client_ip = request.client.host if request.client else "127.0.0.1"
    check_rate_limit(f"register:{client_ip}", max_requests=20)

    email = payload.get("email")
    password = payload.get("password")
    display_name = payload.get("display_name") or payload.get("username") or payload.get("name")
    if not email or not password:
        raise HTTPException(status_code=400, detail="email y password requeridos")
    if not display_name or not str(display_name).strip():
        raise HTTPException(status_code=400, detail="Nombre de usuario (display_name) requerido")

    email_normalized = str(email).strip().lower()
    display_name_check = str(display_name).strip()

    coll = database.get_user_collection()
    total_users = await coll.count_documents({})

    # Si el registro público está cerrado y ya existe al menos un usuario, rechazar
    if total_users > 0 and not sys_settings.get("allow_registration", True):
        raise HTTPException(status_code=403, detail="El registro de nuevos usuarios está deshabilitado por el administrador")

    existing_email = await coll.find_one({"email": email_normalized})
    if existing_email:
        raise HTTPException(status_code=400, detail="Correo electrónico ya registrado")

    regex = {"$regex": f"^{re.escape(display_name_check)}$", "$options": "i"}
    existing_name = await coll.find_one({"display_name": regex})
    if existing_name:
        raise HTTPException(status_code=400, detail="Nombre de usuario ya en uso")

    # Determinar roles: primer usuario o ADMIN_EMAIL es admin automáticamente
    admin_env_email = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    is_first_or_admin = (total_users == 0) or (admin_env_email and email_normalized == admin_env_email)
    roles = ["admin", "user"] if is_first_or_admin else ["user"]

    now = datetime.utcnow()

    # Crear recursos iniciales de ejemplo (MCP Calculadora + Snippet Python + Agente Principal)
    calc_mcp_id = PyObjectId.new()
    calc_script = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "examples", "mcp_servers", "calculator_server.py")
    )
    default_mcps = []
    if os.path.exists(calc_script):
        default_mcps.append(
            {
                "_id": calc_mcp_id,
                "name": "Calculadora-MCP",
                "endpoint": calc_script,
                "transport": "stdio",
                "local_script_path": calc_script,
                "command": None,
                "args": [],
                "env": {},
                "spec": {"capabilities": ["tools"], "description": "Servidor MCP local con operaciones matemáticas"},
                "metadata": {"builtin": True},
                "registered_at": now,
                "active": True,
                "status": "available",
                "timeout_seconds": 30,
            }
        )

    default_snippet_id = PyObjectId.new()
    default_snippets = [
        {
            "_id": default_snippet_id,
            "name": "analizar_texto",
            "description": "Cuenta palabras, caracteres y fecha UTC actual en Python",
            "language": "python",
            "type": "runtime",
            "code": "import datetime\ntexto = str(inp or '')\nreturn {'palabras': len(texto.split()), 'caracteres': len(texto), 'utc_now': datetime.datetime.utcnow().isoformat()}",
            "created_at": now,
            "public": False,
        }
    ]

    default_agent_id = PyObjectId.new()
    default_agents = [
        {
            "_id": default_agent_id,
            "name": "Insanus Generalista + MCP",
            "description": "Agente principal con acceso al servidor MCP de Calculadora y análisis en Python.",
            "system_prompt": [
                "Eres Insanus Assistant, un agente experto en programación, arquitectura de software y análisis.",
                "Responde siempre en español claro y bien estructurado en Markdown.",
            ],
            "snippets": [],
            "active_tools": [str(default_snippet_id)],
            "active_mcps": [str(calc_mcp_id)] if default_mcps else [],
            "active_models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
            "provider": "gemini",
            "model_selected": "gemini-2.5-flash",
            "temperature": 0.7,
            "metadata": {"default": True},
            "created_at": now,
            "active": True,
        }
    ]

    user_doc = {
        "_id": PyObjectId.new(),
        "email": email_normalized,
        "display_name": display_name_check,
        "password_hash": get_password_hash(password),
        "created_at": now,
        "last_login": now,
        "active": True,
        "agents": default_agents,
        "mcps": default_mcps,
        "code_snippets": default_snippets,
        "api_keys": [],
        "roles": roles,
        "settings": {"theme": "dark"},
        "metadata": {},
    }

    await coll.insert_one(user_doc)
    uid_str = str(user_doc["_id"])
    token = create_access_token(uid_str)

    return ResponseModel(
        message="Usuario creado",
        data={
            "user_id": uid_str,
            "access_token": token,
            "token_type": "bearer",
            "roles": roles,
            "display_name": display_name_check,
            "email": email_normalized,
        },
    )
