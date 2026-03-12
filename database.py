import os
import time
import logging
from datetime import datetime
from typing import Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure
from pymongo.server_api import ServerApi


class DatabaseNotInitializedError(Exception):
    pass


class DatabaseConnectionError(Exception):
    pass


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

client = None
db = None

DATABASE_NAME = os.environ.get("MONGO_DB_NAME", "insanus_chat")
COLLECTION_USERS = "users"
COLLECTION_CHATS = "chats"
COLLECTION_MESSAGES = "messages"
COLLECTION_SETTINGS = "system_settings"
COLLECTION_WORKSTATIONS = "workstations"

DEFAULT_SYSTEM_SETTINGS: Dict[str, Any] = {
    "_id": "global_settings",
    "allow_registration": True,
    "allow_stdio_mcp": True,
    "allow_local_mcp_endpoints": True,
    "allow_code_snippets": True,
    "default_provider": "gemini",
    "default_model": "gemini-2.5-flash",
    "rate_limit_login_per_min": 30,
    "maintenance_mode": False,
    "updated_at": datetime.utcnow(),
}


async def ensure_indexes():
    """Crea índices en MongoDB para garantizar rendimiento y unicidad (HU-04)."""
    if db is None:
        return
    try:
        users_col = db[COLLECTION_USERS]
        chats_col = db[COLLECTION_CHATS]
        msgs_col = db[COLLECTION_MESSAGES]
        ws_col = db[COLLECTION_WORKSTATIONS]

        await users_col.create_index("email", unique=True, background=True)
        await users_col.create_index("display_name", background=True)
        await chats_col.create_index([("user_id", 1), ("last_updated", -1)], background=True)
        await msgs_col.create_index([("chat_id", 1), ("created_at", 1)], background=True)
        await msgs_col.create_index("parent_id", background=True)
        await ws_col.create_index([("user_id", 1), ("node_id", 1)], unique=True, background=True)
        await ws_col.create_index([("user_id", 1), ("last_seen", -1)], background=True)
        logging.info("Índices de MongoDB verificados/creados correctamente.")
    except Exception as e:
        logging.warning("No se pudieron crear algunos índices en MongoDB: %s", e)


async def ensure_system_settings() -> Dict[str, Any]:
    """Asegura que exista el documento de configuración global del sistema."""
    if db is None:
        return dict(DEFAULT_SYSTEM_SETTINGS)
    try:
        settings_col = db[COLLECTION_SETTINGS]
        doc = await settings_col.find_one({"_id": "global_settings"})
        if not doc:
            doc = dict(DEFAULT_SYSTEM_SETTINGS)
            doc["updated_at"] = datetime.utcnow()
            await settings_col.insert_one(doc)
        return doc
    except Exception as e:
        logging.warning("No se pudo inicializar system_settings: %s", e)
        return dict(DEFAULT_SYSTEM_SETTINGS)


async def connect_to_mongo():
    """
    Inicializa la conexión asíncrona con MongoDB (local o Atlas),
    verifica conectividad con ping y crea índices.
    """
    global client, db

    mongo_uri = os.environ.get("MONGO_URI")
    if not mongo_uri:
        logging.error("MONGO_URI no está configurado en el entorno.")
        raise DatabaseConnectionError("MONGO_URI no configurado")

    cert_path = os.environ.get("MONGO_X509_CERT_PATH")
    logging.info("Intentando conectar a MongoDB...")

    try:
        if cert_path and os.path.exists(cert_path):
            logging.info("Usando autenticación X.509 con cert_path=%s", cert_path)
            client = AsyncIOMotorClient(
                mongo_uri,
                tls=True,
                tlsCertificateKeyFile=cert_path,
                server_api=ServerApi("1"),
            )
        else:
            if cert_path:
                logging.warning(
                    "MONGO_X509_CERT_PATH definido pero el archivo no existe: %s. Conectando con URI estándar.",
                    cert_path,
                )
            client = AsyncIOMotorClient(mongo_uri)

        db = client[DATABASE_NAME]
        await client.admin.command("ping")
        logging.info("Conexión con MongoDB (%s) establecida exitosamente.", DATABASE_NAME)

        await ensure_indexes()
        await ensure_system_settings()

    except ConnectionFailure as e:
        logging.error(f"ERROR DE CONEXIÓN A MONGODB: {e}")
        raise DatabaseConnectionError(str(e))
    except Exception as e:
        logging.exception("ERROR inesperado al conectar a MongoDB")
        raise DatabaseConnectionError(str(e))


async def close_mongo_connection():
    """Cierra la conexión con MongoDB."""
    global client
    if client:
        client.close()
        logging.info("Conexión con MongoDB cerrada.")


async def ping_db() -> Dict[str, Any]:
    """Comprueba la salud y latencia de MongoDB (HU-19)."""
    if client is None or db is None:
        return {"ok": False, "error": "Database client is not initialized", "latency_ms": None}
    start = time.perf_counter()
    try:
        await client.admin.command("ping")
        latency = round((time.perf_counter() - start) * 1000, 2)
        return {"ok": True, "latency_ms": latency, "database": DATABASE_NAME}
    except Exception as e:
        latency = round((time.perf_counter() - start) * 1000, 2)
        return {"ok": False, "error": str(e), "latency_ms": latency}


def get_user_collection():
    if db is None:
        raise DatabaseNotInitializedError("Database client is not initialized")
    return db[COLLECTION_USERS]


def get_chat_collection():
    if db is None:
        raise DatabaseNotInitializedError("Database client is not initialized")
    return db[COLLECTION_CHATS]


def get_message_collection():
    if db is None:
        raise DatabaseNotInitializedError("Database client is not initialized")
    return db[COLLECTION_MESSAGES]


def get_settings_collection():
    if db is None:
        raise DatabaseNotInitializedError("Database client is not initialized")
    return db[COLLECTION_SETTINGS]
