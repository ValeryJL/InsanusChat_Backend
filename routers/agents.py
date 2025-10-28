from fastapi import APIRouter, HTTPException, Header
from routers import auth 

router = APIRouter(
    prefix="/api/v1/agents",  # Todas las rutas aquí comenzarán con /api/v1/agents
    tags=["Agentes"],       # Etiqueta para agrupar en la documentación
)

@router.get("/")
async def list_agents(authorization: str | None = Header(None)):
    """
    Endpoint de ejemplo para listar agentes.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    uid= auth.authenticate_token(token)
    # Aquí iría la lógica para listar los agentes del usuario con uid
    return {"message": f"Listando agentes para el usuario {uid}"}   

@router.post("/")
async def create_agent(authorization: str | None = Header(None)):
    """
    Endpoint de ejemplo para crear un nuevo agente.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    uid= auth.authenticate_token(token)
    # Aquí iría la lógica para crear un nuevo agente para el usuario con uid
    return {"message": f"Creando nuevo agente para el usuario {uid}"}

@router.put("/{agent_id}")
async def update_agent(agent_id: str, authorization: str | None = Header(None)):
    """
    Endpoint de ejemplo para actualizar un agente.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    uid= auth.authenticate_token(token)
    # Aquí iría la lógica para actualizar el agente con agent_id para el usuario con uid
    return {"message": f"Actualizando agente {agent_id} para el usuario {uid}"}

@router.delete("/{agent_id}")
async def delete_agent(agent_id: str, authorization: str | None = Header(None)):
    """
    Endpoint de ejemplo para eliminar un agente.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    uid= auth.authenticate_token(token)
    # Aquí iría la lógica para eliminar el agente con agent_id para el usuario con uid
    return {"message": f"Eliminando agente {agent_id} para el usuario {uid}"}