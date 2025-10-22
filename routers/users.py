from fastapi import APIRouter
from models import UserModel, ResponseModel

# 1. Crear una instancia de APIRouter
# El prefijo y las etiquetas se añaden aquí, manteniendo limpio el backend.py
router = APIRouter(
    prefix="/api/v1/users",  # Todas las rutas aquí comenzarán con /api/v1/users
    tags=["Usuarios"],       # Etiqueta para agrupar en la documentación
)

# 2. Definir una nueva ruta (endpoint)
@router.post("/", response_model=ResponseModel)
async def create_new_user(user_data: UserModel):
    """
    Registra un nuevo usuario en la base de datos de MongoDB.
    """
    # Lógica de la base de datos (se usa database.get_user_collection() aquí)
    return ResponseModel(message="Usuario creado exitosamente")

# 3. Definir otra ruta
@router.get("/{user_id}", response_model=UserModel)
async def get_user_profile(user_id: str):
    """
    Obtiene el perfil de un usuario por su ID de Firebase.
    """
    # Lógica para buscar el usuario en la DB
    return {"firebase_id": user_id, "email": "test@example.com", "display_name": "Test User"}
