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
import os as _os

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
            curl += f" -d '{body}'"
        except Exception:
            # fallback: include a placeholder
            curl += " -d '{\"example\":true}'"
    return curl


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)

    # Add a bearer auth security scheme so Swagger UI shows the Authorize button
    components = openapi_schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes.setdefault("bearerAuth", {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    })

    # Apply a global security requirement so operations include the Authorization header by default
    openapi_schema.setdefault("security", [])
    if {"bearerAuth": []} not in openapi_schema["security"]:
        openapi_schema["security"].append({"bearerAuth": []})

    # Build server_url used by curl generator (fallbacks)
    server_url = _os.environ.get("API_SERVER_URL") or _os.environ.get("SERVER_URL") or "http://localhost:8000"

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

    # Documentar rutas WebSocket en OpenAPI para que aparezcan en Swagger UI
    try:
        # FastAPI/Starlette pueden exponer WebSocketRoute en distintos módulos según la versión.
        ws_classes = []
        try:
            from fastapi.routing import WebSocketRoute as FastAPIWebSocketRoute
            ws_classes.append(FastAPIWebSocketRoute)
        except Exception:
            pass
        try:
            from starlette.routing import WebSocketRoute as StarletteWebSocketRoute
            ws_classes.append(StarletteWebSocketRoute)
        except Exception:
            pass

        if ws_classes:
            # Añadir tag 'WebSockets' si no existe
            for route in app.routes:
                try:
                    if any(isinstance(route, cls) for cls in ws_classes):
                        ws_path = getattr(route, 'path', None) or getattr(route, 'path_format', None) or getattr(route, 'name', None)
                        if not ws_path:
                            continue
                        paths = openapi_schema.setdefault("paths", {})
                        path_item = paths.setdefault(ws_path, {})
                        # Operación documental — usamos GET como 'placeholder' y añadimos x-websocket
                        op = {
                            "summary": f"WebSocket (documentación): {getattr(route, 'name', ws_path)}",
                            "description": "Endpoint WebSocket. Documentación solamente: conectar usando un cliente WebSocket (p. ej. websocket client, wscat).",
                            # Mostrar esta operación bajo la etiqueta 'Chats' para agruparla con los endpoints REST relacionados
                            "tags": ["Chats"],
                            "responses": {
                                "101": {"description": "Switching Protocols (WebSocket)"},
                                "200": {"description": "Documentación: respuesta simulada"}
                            },
                            "x-websocket": True,
                            "parameters": [],
                        }
                        # Solo añadir si no existe una operación real con el mismo método
                        if "get" not in path_item:
                            path_item["get"] = op
                except Exception:
                    logging.exception("Error documentando ruta WebSocket: %s", getattr(route, 'path', str(route)))
    except Exception:
        # No fallar el generador OpenAPI por errores en la documentación WS
        logging.debug("Error generando documentación WebSocket: %s", exc_info=True)

    app.openapi_schema = openapi_schema
    return app.openapi_schema


# Sobrescribir la función openapi de FastAPI
app.openapi = custom_openapi
