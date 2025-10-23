import uvicorn
import os
from dotenv import load_dotenv
from fastapi import FastAPI
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
    print("--- 🚀 Iniciando FastAPI y conectando a MongoDB... ---")
    database.connect_to_mongo()
    
    # El 'yield' pausa la función y permite que la aplicación inicie
    yield
    
    # Lógica de Cierre (Shutdown)
    print("--- 🛑 Cerrando FastAPI y desconectando de MongoDB... ---")
    database.close_mongo_connection()

# --- 2. INSTANCIA DE LA APLICACIÓN FASTAPI ---
# La variable 'app' debe coincidir con el Start Command de Render: uvicorn backend:app
app = FastAPI(
    title="InsanusChat Backend",
    description="Backend asíncrono para chat con ramificaciones (threads) usando FastAPI y MongoDB.",
    version="0.1.0",
    lifespan=lifespan # Aplicamos el context manager
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
