from fastapi import APIRouter, HTTPException, Header
from routers import auth
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
    uid= auth.authenticate_token(token)
    # Aquí iría la lógica para listar las API Keys del usuario con uid
    return {"message": f"Listando API Keys para el usuario {uid}"}

@router.post("/")
async def create_api_key(authorization: str | None = Header(None)):
    """
    Endpoint de ejemplo para crear una nueva API Key.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    uid= auth.authenticate_token(token)
    # Aquí iría la lógica para crear una nueva API Key para el usuario con uid
    return {"message": f"Creando nueva API Key para el usuario {uid}"}

@router.put("/{key_id}")
async def update_api_key(key_id: str, authorization: str | None = Header(None)):
    """
    Endpoint de ejemplo para actualizar una API Key.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    uid= auth.authenticate_token(token)
    # Aquí iría la lógica para actualizar la API Key con key_id para el usuario con uid
    return {"message": f"Actualizando API Key {key_id} para el usuario {uid}"}

@router.delete("/{key_id}")
async def delete_api_key(key_id: str, authorization: str | None = Header(None)):
    """
    Endpoint de ejemplo para eliminar una API Key.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    uid= auth.authenticate_token(token)
    # Aquí iría la lógica para eliminar la API Key con key_id para el usuario con uid
    return {"message": f"Eliminando API Key {key_id} para el usuario {uid}"}