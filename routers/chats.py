from fastapi import APIRouter, HTTPException, Header
from routers import auth

router = APIRouter(
    prefix="/api/v1/chats",  # Todas las rutas aquí comenzarán con /api/v1/chats
    tags=["Chats"],       # Etiqueta para agrupar en la documentación
)

@router.get("/")
async def list_chats(authorization: str | None = Header(None)):
    """
    Endpoint de ejemplo para listar chats.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    decoded = auth.authenticate_token(token)
    uid = decoded.get("uid") or decoded.get("user_id")
    # Aquí iría la lógica para listar los chats del usuario con uid
    return {"message": f"Listando chats para el usuario {uid}"}

@router.post("/")
async def create_chat(authorization: str | None = Header(None)):
    """
    Endpoint de ejemplo para crear un nuevo chat.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    decoded = auth.authenticate_token(token)
    uid = decoded.get("uid") or decoded.get("user_id")
    # Aquí iría la lógica para crear un nuevo chat para el usuario con uid
    return {"message": f"Creando nuevo chat para el usuario {uid}"}

@router.post("/{chat_id}")
async def send_message(chat_id: str, authorization: str | None = Header(None)):
    """
    Endpoint de ejemplo para enviar un mensaje en un chat.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    decoded = auth.authenticate_token(token)
    uid = decoded.get("uid") or decoded.get("user_id")
    # Aquí iría la lógica para enviar un mensaje en el chat con chat_id para el usuario con uid
    return {"message": f"Enviando mensaje en el chat {chat_id} para el usuario {uid}"}

@router.delete("/{chat_id}")
async def delete_chat(chat_id: str, authorization: str | None = Header(None)):
    """
    Endpoint de ejemplo para eliminar un chat.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    decoded = auth.authenticate_token(token)
    uid = decoded.get("uid") or decoded.get("user_id")
    # Aquí iría la lógica para eliminar el chat con chat_id para el usuario con uid
    return {"message": f"Eliminando chat {chat_id} para el usuario {uid}"}