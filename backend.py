import uvicorn
import os
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from routers import users
import database

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
    database.close_mongo_connection()

# --- 2. INSTANCIA DE LA APLICACIÓN FASTAPI ---
# La variable 'app' debe coincidir con el Start Command de Render: uvicorn backend:app
app = FastAPI(
    title="InsanusChat Backend",
    description="Backend asíncrono para chat con ramificaciones (threads) usando FastAPI y MongoDB.",
    version="0.1.0",
    lifespan=lifespan # Aplicamos el context manager
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


app.include_router(users.router)

# app.include_router(chats.router)

# --- 4. INICIO DEL SERVIDOR (Solo para desarrollo local) ---
# Esta sección es útil para ejecutar el backend.py directamente durante el desarrollo.
if __name__ == "__main__":
    # Nota: Render usará el 'Start Command' (uvicorn backend:app...)
    # Por lo tanto, esta sección no se ejecuta en el despliegue de Render, solo localmente.
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=True)
