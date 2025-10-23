import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth
from fastapi import APIRouter, HTTPException
from models import UserModel, ResponseModel

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

# 2. Definir una nueva ruta (endpoint)
@router.post("/", response_model=ResponseModel)
async def create_new_user(user_data: UserModel):
    """
    Crea un nuevo usuario en Firebase Authentication usando Admin SDK.
    Espera que UserModel tenga al menos 'email' y opcionalmente 'password' y 'display_name'.
    """
    try:
        password = getattr(user_data, "password", None)
        created = firebase_auth.create_user(
            email=user_data.email,
            password=password,
            display_name=getattr(user_data, "display_name", None),
        )
        return ResponseModel(message="Usuario creado en Firebase", data={"uid": created.uid, "email": created.email})
    except firebase_auth.EmailAlreadyExistsError:
        raise HTTPException(status_code=400, detail="El email ya existe")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 3. Definir otra ruta
@router.get("/{user_id}", response_model=UserModel)
async def get_user_profile(user_id: str):
    """
    Obtiene el perfil de un usuario por su ID de Firebase.
    """
    try:
        u = firebase_auth.get_user(user_id)
        return {"firebase_id": u.uid, "email": u.email, "display_name": u.display_name}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
