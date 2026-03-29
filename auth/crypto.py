"""
Módulo de cifrado simétrico (Fernet / AES-128-CBC + HMAC-SHA256) y enmascaramiento
para API Keys de proveedores de IA (HU-05).
"""
import base64
import hashlib
import logging
import os
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

ENC_PREFIX = "enc:v1:"


def _get_fernet() -> Fernet:
    """
    Obtiene una instancia Fernet usando ENCRYPTION_MASTER_KEY o derivando
    una clave determinista de 32 bytes en base64 url-safe desde LOCAL_AUTH_SECRET.
    """
    master_key = os.getenv("ENCRYPTION_MASTER_KEY")
    if master_key:
        try:
            # Si ya es una clave Fernet válida de 32 bytes url-safe base64
            return Fernet(master_key.encode("utf-8"))
        except Exception:
            # Derivar 32 bytes con SHA-256
            digest = hashlib.sha256(master_key.encode("utf-8")).digest()
            return Fernet(base64.urlsafe_b64encode(digest))

    secret = os.getenv("LOCAL_AUTH_SECRET") or "insanuschat-default-local-dev-secret-key"
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    derived_key = base64.urlsafe_b64encode(digest)
    return Fernet(derived_key)


def encrypt_api_key(plain_key: str) -> str:
    """
    Cifra una API key en texto plano y le añade el prefijo 'enc:v1:'.
    Si ya tiene el prefijo, la devuelve sin recifrar.
    """
    if not plain_key:
        return ""
    if plain_key.startswith(ENC_PREFIX):
        return plain_key
    f = _get_fernet()
    token = f.encrypt(plain_key.encode("utf-8")).decode("utf-8")
    return f"{ENC_PREFIX}{token}"


def decrypt_api_key(stored_key: str) -> str:
    """
    Descifra en memoria una API key almacenada con 'enc:v1:'.
    Si es una clave heredada sin prefijo, la devuelve tal cual para compatibilidad.
    """
    if not stored_key:
        return ""
    if not stored_key.startswith(ENC_PREFIX):
        return stored_key
    token = stored_key[len(ENC_PREFIX):]
    f = _get_fernet()
    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error("No se pudo descifrar la API key (InvalidToken). Verifique ENCRYPTION_MASTER_KEY / LOCAL_AUTH_SECRET.")
        return ""
    except Exception as e:
        logger.error("Error descifrando API key: %s", e)
        return ""


def mask_api_key(stored_or_plain_key: str) -> str:
    """
    Devuelve una representación enmascarada segura para mostrar en UI / respuestas GET
    (ej: 'AIza...9f2A' o 'sk-p...1234'). Nunca expone el secreto completo.
    """
    if not stored_or_plain_key:
        return "****"
    plain = decrypt_api_key(stored_or_plain_key)
    if not plain:
        plain = stored_or_plain_key
    clean = plain.strip()
    if len(clean) <= 8:
        return f"{clean[:2]}****"
    return f"{clean[:4]}...{clean[-4:]}"
