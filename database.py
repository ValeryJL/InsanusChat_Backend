import os
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure
from pymongo.server_api import ServerApi


# Excepciones custom usadas por la app para mapear a 503 y mensajes amigables
class DatabaseNotInitializedError(Exception):
    pass


class DatabaseConnectionError(Exception):
    pass

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
        logging.error("MONGO_URI no está configurado en el entorno.")
        # En lugar de sys.exit, lanzamos una excepción que el app handler mapeará a 503
        raise DatabaseConnectionError("MONGO_URI no configurado")

    cert_path = os.environ.get("MONGO_X509_CERT_PATH")  # opcional en .env

    logging.info("Intentando conectar a MongoDB...")

    try:
        # Si se proveyó un certificado X.509 y el archivo existe, lo usamos.
        if cert_path and os.path.exists(cert_path):
            logging.info("Usando autenticación X.509 con cert_path=%s", cert_path)
            client = AsyncIOMotorClient(mongo_uri, tls=True, tlsCertificateKeyFile=cert_path, server_api=ServerApi('1'))
        else:
            if cert_path:
                logging.warning("MONGO_X509_CERT_PATH definido pero el archivo no existe: %s. Intentando conexión sin X.509.", cert_path)
            else:
                logging.info("MONGO_X509_CERT_PATH no definido, intentando conexión estándar con la URI.")
            # Intento de conexión más permisivo (sin certificado). Muchas URIs incluyen credenciales en la propia URI.
            client = AsyncIOMotorClient(mongo_uri, server_api=ServerApi('1'))

        # Base de datos por defecto
        db = client[DATABASE_NAME]

        # Ping asíncrono para comprobar la conexión (motor usa corutinas para operaciones IO)
        await client.admin.command("ping")
        logging.info("Conexión con MongoDB Atlas establecida exitosamente.")

    except ConnectionFailure as e:
        logging.error(f"ERROR DE CONEXIÓN A MONGODB: {e}")
        raise DatabaseConnectionError(str(e))
    except Exception as e:
        logging.exception("ERROR inesperado al conectar a MongoDB")
        raise DatabaseConnectionError(str(e))


async def close_mongo_connection():
    """
    Función de cierre que se ejecutará en el evento 'shutdown' de FastAPI.
    Cierra la conexión con MongoDB.
    """
    global client
    if client:
        client.close()
        logging.info("Conexión con MongoDB Atlas cerrada.")

# Funciones de utilidad para obtener las colecciones (opcional, pero limpio)
def get_user_collection():
    """Devuelve la colección de usuarios."""
    if db is None:
        raise DatabaseNotInitializedError("Database client is not initialized")
    return db[COLLECTION_USERS]

def get_chat_collection():
    """Devuelve la colección de chats."""
    if db is None:
        raise DatabaseNotInitializedError("Database client is not initialized")
    return db[COLLECTION_CHATS]
