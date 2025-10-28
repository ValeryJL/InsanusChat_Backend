import os
import sys
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Excepción personalizada para errores de inicialización de la base de datos
class DatabaseNotInitializedError(Exception):
    """Raised when the database client cannot be initialized or connected."""
    pass

class DatabaseConnectionError(Exception):
    """Raised when there is a connection error with the database."""
    pass

# --- Variables Globales de Conexión ---
# Estas variables se inicializarán en la función 'connect_to_mongo'
# y serán utilizadas por el resto de la aplicación FastAPI.
# Usamos 'client' para manejar la conexión y 'db' para la base de datos específica.
# Definimos None como valor inicial para que puedan ser tipadas correctamente.
client = None
db = None

# --- Nombres de la Base de Datos y Colecciones ---
# Usamos el nombre que definiste para la base de datos
DATABASE_NAME = "insanus_chat"
# Colecciones que creaste
COLLECTION_USERS = "users"
COLLECTION_CHATS = "chats"

async def connect_to_mongo():
    """
    Función de inicialización que se ejecutará en el evento 'startup' de FastAPI.
    Establece la conexión asíncrona con MongoDB Atlas.
    """
    global client, db
    
    # 1. Obtener la URI de Conexión
    # Es crucial usar variables de entorno (Render) para credenciales
    mongo_uri = os.environ.get("MONGO_URI")

    if not mongo_uri:
        logging.error("ERROR: La variable de entorno MONGO_URI no está configurada.")
        # Salir de la aplicación si no se puede conectar (comportamiento típico de un backend)
        sys.exit(1)
        
    logging.info(f"Intentando conectar a MongoDB Atlas con URI: {mongo_uri[:20]}...")

    try:
        # 2. Crear el Cliente Asíncrono
        # Motor es la versión asíncrona de PyMongo
        client = AsyncIOMotorClient(mongo_uri)
        
        # 3. Intentar acceder a la base de datos para verificar la conexión
        # Usamos el nombre de la base de datos: 'insanus_chat'
        db = client[DATABASE_NAME]

        # Comprobar la conexión (opcional, pero útil)
        # Una simple operación de ping para verificar el acceso.
        await client.admin.command('ping')
        logging.info("Conexión con MongoDB Atlas establecida exitosamente.")
        
    except ConnectionFailure as e:
        logging.error(f"ERROR DE CONEXIÓN A MONGODB: No se pudo conectar a la base de datos. Detalle: {e}")
        raise DatabaseConnectionError("No se pudo conectar a la base de datos.")
    except Exception as e:
        logging.error(f"ERROR inesperado al conectar a MongoDB: {e}")
        raise DatabaseConnectionError("Error inesperado al conectar a la base de datos.")


def close_mongo_connection():
    """
    Función de cierre que se ejecutará en el evento 'shutdown' de FastAPI.
    Cierra la conexión con MongoDB.
    """
    global client,db
    if client:
        client.close()
        logging.info("Conexión con MongoDB Atlas cerrada.")
        client = None
        db = None

# Funciones de utilidad para obtener las colecciones (opcional, pero limpio)
def get_user_collection():
    """Devuelve la colección de usuarios."""
    if db is None:
        raise DatabaseNotInitializedError("Database client is not initialized.")
    return db[COLLECTION_USERS]

def get_chat_collection():
    """Devuelve la colección de chats."""
    if db is None:
        raise DatabaseNotInitializedError("Database client is not initialized.")
    return db[COLLECTION_CHATS]
