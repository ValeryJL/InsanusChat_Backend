"""
Aplicación Principal FastAPI — InsanusChat Backend.
Incluye:
- CORSMiddleware habilitado para clientes web y proxy inverso (HU-04)
- Healthcheck avanzado `GET /health` con ping y latencia de MongoDB (HU-19)
- Routers de Autenticación, API Keys (Fernet), Agentes (Multi-Proveedor), Recursos (MCPs/Snippets), Chats (REST + WS) y Administración (`/api/v1/admin`).
"""
from contextlib import asynccontextmanager
import json
import logging
import os
import os as _os

from dotenv import load_dotenv
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
import uvicorn

import database
from routers import admin, agents, apikeys, auth, chats, nodes, tools

load_dotenv()

# Garantizar valores seguros por defecto en entorno local si no hay archivo .env
if not os.environ.get("LOCAL_AUTH_SECRET"):
    os.environ["LOCAL_AUTH_SECRET"] = "insanuschat-local-dev-jwt-secret-key-2026-secure"
if not os.environ.get("MONGO_URI"):
    os.environ["MONGO_URI"] = "mongodb://admin:insanus_admin_pass@localhost:27017/insanus_chat?authSource=admin"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("--- 🚀 Iniciando InsanusChat Backend y conectando a MongoDB... ---")
    await database.connect_to_mongo()
    yield
    logging.info("--- 🛑 Cerrando InsanusChat Backend y desconectando de MongoDB... ---")
    await database.close_mongo_connection()


tags_metadata = [
    {"name": "Health Check", "description": "Endpoints para comprobar salud y latencia de la API y MongoDB."},
    {"name": "Usuarios", "description": "Autenticación JWT, registro, perfil y gestión de sesión."},
    {"name": "Agentes", "description": "CRUD de agentes de IA y catálogo de modelos multi-proveedor."},
    {"name": "API Keys", "description": "Gestión de claves de proveedor cifradas en reposo con Fernet (AES)."},
    {"name": "Resources", "description": "Servidores MCP (stdio/sse/http) y Code Snippets en sandbox aislado."},
    {"name": "Chats", "description": "Conversaciones ramificadas en árbol (REST y WebSocket con streaming)."},
    {"name": "Equipos de Ejecución (Harness Nodes)", "description": "Registro de Workstations, túnel WebSocket RPC, filesystem, diffs y terminal para el Editor VS Code."},
    {"name": "Administración", "description": "Panel de Administración: métricas globales, gestión de usuarios y políticas del sistema."},
]

app = FastAPI(
    title="insanus-harnes Backend",
    description=(
        "Plataforma asíncrona de Chat Ramificado en Árbol con Agentes de IA Multi-Proveedor, "
        "Agent Harness distribuido, Control Plane SSOT de Workstations, Servidores MCP y Panel Admin."
    ),
    version="1.4.1",
    lifespan=lifespan,
    openapi_tags=tags_metadata,
    contact={"name": "InsanusTech Team", "email": os.environ.get("MAINTAINER_EMAIL", "valejlorda@insanustech.com.ar")},
    license_info={"name": "GPL 3.0"},
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# HU-04: Configurar CORS para permitir conexión desde Frontend React en desarrollo y producción
raw_origins = os.environ.get("CORS_ORIGINS", "*")
allow_origins = [o.strip() for o in raw_origins.split(",") if o.strip()] if raw_origins != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(database.DatabaseNotInitializedError)
async def db_not_initialized_exception_handler(request: Request, exc: database.DatabaseNotInitializedError):
    logging.warning(f"Database not initialized: {exc}")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Database not ready, try again later"},
    )


@app.exception_handler(database.DatabaseConnectionError)
async def db_connection_exception_handler(request: Request, exc: database.DatabaseConnectionError):
    logging.warning(f"Database connection error: {exc}")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Database connection error, try again later"},
    )


@app.get("/", tags=["Health Check"])
async def root():
    return {"message": "InsanusChat Backend is running!", "version": "1.0.0"}


@app.get("/health", tags=["Health Check"])
@app.get("/api/v1/health", tags=["Health Check"])
async def health_check():
    """HU-19: Healthcheck avanzado con verificación en vivo de MongoDB y latencia."""
    db_status = await database.ping_db()
    if not db_status.get("ok"):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "database": db_status},
        )
    return {"status": "healthy", "version": "1.0.0", "database": db_status}


app.include_router(auth.router)
app.include_router(apikeys.router)
app.include_router(agents.router)
app.include_router(tools.router)
app.include_router(chats.router)
app.include_router(nodes.router)
app.include_router(admin.router)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("backend:app", host="0.0.0.0", port=port, reload=True)


def _build_curl_for_operation(path: str, method: str, operation: dict, server_url: str) -> str:
    method_upper = method.upper()
    url = server_url.rstrip("/") + path
    headers = ['"Content-Type: application/json"', '"Authorization: Bearer <TOKEN>"']
    data_payload = None
    rb = operation.get("requestBody") or {}
    if rb:
        content = rb.get("content", {}).get("application/json", {})
        if content:
            examples = content.get("examples")
            if examples and isinstance(examples, dict):
                first = next(iter(examples.values()))
                data_payload = first.get("value")
            elif "example" in content:
                data_payload = content.get("example")

    curl = f'curl -X {method_upper} "{url}"'
    for h in headers:
        curl += f" -H {h}"
    if data_payload is not None:
        try:
            body = json.dumps(data_payload, ensure_ascii=False)
            curl += f" -d '{body}'"
        except Exception:
            curl += " -d '{\"example\":true}'"
    return curl


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    components = openapi_schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes.setdefault(
        "bearerAuth",
        {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
    )
    openapi_schema.setdefault("security", [])
    if {"bearerAuth": []} not in openapi_schema["security"]:
        openapi_schema["security"].append({"bearerAuth": []})

    server_url = _os.environ.get("API_SERVER_URL") or _os.environ.get("SERVER_URL") or "http://localhost:8000"
    paths = openapi_schema.get("paths", {})
    for path, methods in paths.items():
        for method, operation in list(methods.items()):
            if method.lower() not in ("get", "post", "put", "delete", "patch", "options", "head"):
                continue
            try:
                operation["x-curl"] = _build_curl_for_operation(path, method, operation, server_url)
            except Exception:
                pass

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
