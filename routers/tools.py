from fastapi import APIRouter, HTTPException, Header
from routers import auth

router = APIRouter(
    prefix="/api/v1/tools",  # Todas las rutas aquí comenzarán con /api/v1/tools
    tags=["Tools"],       # Etiqueta para agrupar en la documentación
)

@router.get("/")
async def list_tools(authorization: str | None = Header(None)):
    """
    Endpoint de ejemplo para listar herramientas.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    uid = auth.authenticate_token(token)
    # Aquí iría la lógica para listar las herramientas del usuario con uid
    return {"message": f"Listando herramientas para el usuario {uid}"}

@router.post("/run")
async def run_tool(authorization: str | None = Header(None)):
    """
    Endpoint de ejemplo para ejecutar una herramienta.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no provisto")
    token = authorization.split(" ", 1)[1]
    uid = auth.authenticate_token(token)
    # Aquí iría la lógica para ejecutar una herramienta para el usuario con uid
    return {"message": f"Ejecutando herramienta para el usuario {uid}"}
