import os
import logging
import asyncio
import certifi
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure
from pymongo.server_api import ServerApi

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
    Inicializa AsyncIOMotorClient. Si usas autenticación X.509, coloca la ruta
    al PEM (certificado+clave) en la variable de entorno MONGO_X509_CERT_PATH.
    """
    global client, db

    mongo_uri = os.environ.get("MONGO_URI")
    if not mongo_uri:
        logging.error("ERROR: La variable de entorno MONGO_URI no está configurada.")
        raise DatabaseNotInitializedError("MONGO_URI not configured")

    # Soporte X.509: ruta al archivo PEM que contiene certificado y clave del cliente
    cert_path = os.environ.get("MONGO_X509_CERT_PATH")  # set this in your .env
    if not cert_path:
        logging.error("ERROR: La variable de entorno MONGO_X509_CERT_PATH no está configurada.")
        raise DatabaseNotInitializedError("MONGO_X509_CERT_PATH not configured")
    
    
    logging.info(f"Intentando conectar a MongoDB Atlas con URI: {mongo_uri[:40]}...")
    try:
        client = AsyncIOMotorClient(mongo_uri, tls=True,tlsCertificateKeyFile=cert_path,server_api=ServerApi('1'))
        db = client[DATABASE_NAME]

        # Bound the ping to avoid indefinite waits
        await asyncio.wait_for(client.admin.command("ping"), timeout=5000)
        logging.info("Conexión con MongoDB Atlas establecida exitosamente.")
    except asyncio.TimeoutError:
        logging.error(f"Ping a MongoDB excedió el tiempo límite (5000s).")
        raise DatabaseConnectionError("Ping timeout")
    except ConnectionFailure as e:
        logging.error(f"ERROR DE CONEXIÓN A MONGODB: {e}")
        raise DatabaseConnectionError("No se pudo conectar a la base de datos.") from e
    except Exception as e:
        logging.exception(f"ERROR inesperado al conectar a MongoDB: {e}")
        raise DatabaseConnectionError("Error inesperado al conectar a la base de datos.") from e


async def close_mongo_connection():
    """
    Cierra la conexión con MongoDB sin bloquear el loop (close() es síncrono).
    """
    global client, db
    if not client:
        return

    try:
        # AsyncIOMotorClient.close() es sincrónico: ejecutarlo en un hilo evita bloquear el loop.
        await asyncio.to_thread(client.close)
        logging.info("Conexión con MongoDB Atlas cerrada.")
    except Exception as e:
        logging.exception(f"Error cerrando la conexión a MongoDB: {e}")
        raise DatabaseConnectionError("Error al cerrar la conexión con la base de datos.") from e
    finally:
        client = None
        db = None


# Funciones de utilidad para obtener las colecciones
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
