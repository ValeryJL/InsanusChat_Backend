import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth
from fastapi import APIRouter, HTTPException, Header
from models import UserModel, ResponseModel
from pydantic import BaseModel, EmailStr
import logging

load_dotenv()

# 1. Crear una instancia de APIRouter
router = APIRouter(
    prefix="/api/v1/users",  # Todas las rutas aquí comenzarán con /api/v1/users
    tags=["Usuarios"],       # Etiqueta para agrupar en la documentación
)

service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
if not service_account_path:
    # en dev lanzar error temprano para que lo configures
    raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_PATH no está definido en .env")

if not firebase_admin._apps:
    cred = credentials.Certificate(service_account_path)
    firebase_admin.initialize_app(cred)

# Nuevo DTO para creación (no requiere firebase_id)
class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str | None = None
    display_name: str | None = None

# 2. Definir una nueva ruta (endpoint)
@router.post("/", response_model=ResponseModel)
async def create_new_user(user_data: CreateUserRequest):
    """
    Crea un nuevo usuario en Firebase Authentication usando Admin SDK.
    Espera email y opcionales password y display_name.
    """
    try:
        password = user_data.password
        created = firebase_auth.create_user(
            email=user_data.email,
            password=password,
            display_name=user_data.display_name,
        )
        return ResponseModel(message="Usuario creado en Firebase", data={"uid": created.uid, "email": created.email})
    except Exception as e:
        msg = str(e)
        # detectar error de email ya existente y devolver 400
        if "email" in msg and "already exists" in msg:
            raise HTTPException(status_code=400, detail="El email ya existe")
        logging.exception("Error creando usuario en Firebase")
        raise HTTPException(status_code=500, detail=msg)

@router.get("/me", response_model=UserModel)
async def get_my_profile(authorization: str | None = Header(None)):
    """
    Devuelve el perfil del usuario autenticado por ID token (Authorization: Bearer <token>).
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    try:
        decoded = firebase_auth.verify_id_token(token)
        uid = decoded.get("uid")
        if not uid:
            raise HTTPException(status_code=401, detail="Token inválido")
        u = firebase_auth.get_user(uid)
        return ResponseModel(message="Perfil recuperado", data={"firebase_id": u.uid, "email": u.email, "display_name": u.display_name})
    except firebase_auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="ID token inválido")
    except Exception as e:
        logging.exception("Error verificando token o recuperando usuario")
        raise HTTPException(status_code=401, detail=str(e))


