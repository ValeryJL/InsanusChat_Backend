import uvicorn
import os
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from routers import auth, apikeys, agents, chats, tools
import database
from fastapi.openapi.utils import get_openapi
import json

# Cargar .env automáticamente (si existe) para poblar os.environ
load_dotenv()

# --- 1. CONTEXT MANAGER PARA EL CICLO DE VIDA ---
# FastAPI (versión > 0.100.0) recomienda usar context managers
# en lugar de @app.on_event("startup") y @app.on_event("shutdown").
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Función que maneja los eventos de inicio (startup) y cierre (shutdown)
    de la aplicación FastAPI.
    """
    # Lógica de Inicio (Startup)
    logging.info("--- 🚀 Iniciando FastAPI y conectando a MongoDB... ---")
    # Dejar que `connect_to_mongo` lance las excepciones específicas.
    # Si falla en startup, es deseable que uvicorn/FastAPI detengan el arranque
    # y muestren la traza completa para debugging.
    await database.connect_to_mongo()
    
    # El 'yield' pausa la función y permite que la aplicación inicie
    yield
    
    # Lógica de Cierre (Shutdown)
    logging.info("--- 🛑 Cerrando FastAPI y desconectando de MongoDB... ---")
    # Dejar que la función de cierre gestione y lance excepciones si ocurren.
    # El handler global (registrado en la app) convertirá errores de DB en respuestas 503
    await database.close_mongo_connection()

# --- 2. INSTANCIA DE LA APLICACIÓN FASTAPI ---
# La variable 'app' debe coincidir con el Start Command de Render: uvicorn backend:app
tags_metadata = [
    {"name": "Health Check", "description": "Endpoints para comprobar salud de la API."},
    {"name": "Usuarios", "description": "Autenticación, perfil y gestión de usuario."},
    {"name": "Agentes", "description": "CRUD y gestión de agentes del usuario."},
    {"name": "API Keys", "description": "Gestión de claves de proveedor integradas por el usuario."},
    {"name": "Resources", "description": "MCPs, snippets y recursos asociados al usuario."},
    {"name": "Chats", "description": "Operaciones de chat y mensajería (REST y WebSocket)."},
]

app = FastAPI(
    title="InsanusChat Backend",
    description=(
        "Backend asíncrono para chat con ramificaciones (threads) usando FastAPI y MongoDB."
        "\n\nEn la documentación encontrarás ejemplos de request/response, códigos de error y ejemplos"
        " para cuerpos de petición en los endpoints principales."
    ),
    version="0.1.0",
    lifespan=lifespan,  # Aplicamos el context manager
    openapi_tags=tags_metadata,
    contact={"name": "InsanusTech Team", "email": os.environ.get("MAINTAINER_EMAIL", "valejlorda@insanustech.com.ar")},
    license_info={"name": "GPL 3.0"},
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# Handler global: convertir DatabaseNotInitializedError -> HTTP 503
@app.exception_handler(database.DatabaseNotInitializedError)
async def db_not_initialized_exception_handler(request: Request, exc: database.DatabaseNotInitializedError):
    logging.warning(f"Database not initialized: {exc}")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Database not ready, try again later"},
    )


# Handler global: convertir DatabaseConnectionError -> HTTP 503
@app.exception_handler(database.DatabaseConnectionError)
async def db_connection_exception_handler(request: Request, exc: database.DatabaseConnectionError):
    logging.warning(f"Database connection error: {exc}")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Database connection error, try again later"},
    )

# --- 3. RUTAS PRINCIPALES Y DE SALUD ---

@app.get("/", tags=["Health Check"])
async def root():
    """Endpoint simple para verificar que la API está funcionando."""
    return {"message": "InsanusChat Backend is running!"}


app.include_router(auth.router)
app.include_router(apikeys.router)
app.include_router(agents.router)
app.include_router(tools.router)    
app.include_router(chats.router)

# app.include_router(chats.router)

# --- 4. INICIO DEL SERVIDOR (Solo para desarrollo local) ---
# Esta sección es útil para ejecutar el backend.py directamente durante el desarrollo.
if __name__ == "__main__":
    # Nota: Render usará el 'Start Command' (uvicorn backend:app...)
    # Por lo tanto, esta sección no se ejecuta en el despliegue de Render, solo localmente.
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=True)


# Custom OpenAPI: inyecta servers y un ejemplo de curl en cada operación como extensión x-curl.
def _build_curl_for_operation(path: str, method: str, operation: dict, server_url: str) -> str:
    """Construye un comando curl sencillo para una operación OpenAPI.
    Usa el primer ejemplo disponible en requestBody (application/json) si existe.
    """
    method_upper = method.upper()
    url = server_url.rstrip("/") + path

    # Cabeceras por defecto
    headers = [
        '"Content-Type: application/json"',
        '"Authorization: Bearer <TOKEN>"'
    ]

    # Intentar extraer ejemplo de requestBody
    data_payload = None
    rb = operation.get("requestBody") or {}
    if rb:
        content = rb.get("content", {}).get("application/json", {})
        if content:
            # ejemplos: preferir content.examples -> first example value
            examples = content.get("examples")
            if examples and isinstance(examples, dict):
                first = next(iter(examples.values()))
                data_payload = first.get("value")
            elif "example" in content:
                data_payload = content.get("example")

    curl = f'curl -X {method_upper} "{url}"'
    for h in headers:
        curl += f' -H {h}'
    if data_payload is not None:
        try:
            body = json.dumps(data_payload, ensure_ascii=False)
            # escape single quotes for safe shell usage
            body_escaped = body.replace("'", "'\"'\"'")
            curl += f" -d '{body_escaped}'"
        except Exception:
            # fallback: include a placeholder
            curl += " -d '{\"example\":true}'"
    return curl


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)

    # Inyectar servers
    server_url = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
    openapi_schema["servers"] = [{"url": server_url, "description": "Default server"}]

    # Añadir x-curl a cada operación
    paths = openapi_schema.get("paths", {})
    for path, methods in paths.items():
        for method, operation in list(methods.items()):
            if method.lower() not in ("get", "post", "put", "delete", "patch", "options", "head"):
                continue
            try:
                curl = _build_curl_for_operation(path, method, operation, server_url)
                operation["x-curl"] = curl
            except Exception:
                logging.exception("Failed to build curl for %s %s", method, path)

    app.openapi_schema = openapi_schema
    return app.openapi_schema


# Sobrescribir la función openapi de FastAPI
app.openapi = custom_openapi
