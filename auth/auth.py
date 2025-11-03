from datetime import datetime, timedelta
from passlib.context import CryptContext
from typing import Optional
from dotenv import load_dotenv
import hashlib
import logging
from jose import jwt
import os

load_dotenv()

# Añadir pbkdf2_sha256 como fallback si bcrypt no funciona en el entorno
pwd_ctx = CryptContext(schemes=["bcrypt_sha256", "pbkdf2_sha256"], deprecated="auto")

SECRET = os.getenv("LOCAL_AUTH_SECRET")
ALGORITHM = os.getenv("LOCAL_AUTH_ALG") or "HS256"
ACCESS_EXPIRE_MIN = int(os.getenv("LOCAL_AUTH_EXPIRE_MIN", "60"))

def _prehash_sha256(password: str) -> str:
    """Pre-hash con SHA256 y devolver hex string (compatibilidad)."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def get_password_hash(password: str) -> str:
    """
    Devuelve el hash seguro de la contraseña.
    Intentamos usar bcrypt_sha256 explícito; si falla por el backend
    (p. ej. ValueError '72 bytes' o backend ausente) aplicamos pbkdf2_sha256.
    """
    if password is None:
        raise ValueError("password is required")
    try:
        # forzar scheme explícito a bcrypt_sha256 (mejor cuando está disponible)
        return pwd_ctx.hash(password, scheme="bcrypt_sha256")
    except Exception as e:
        logging.warning("bcrypt_sha256 not available or failed (%s), falling back to pbkdf2_sha256", e)
        # pbkdf2_sha256 no tiene el límite de 72 bytes
        try:
            return pwd_ctx.hash(password, scheme="pbkdf2_sha256")
        except Exception as e2:
            logging.exception("Fallback hashing failed")
            # como último recurso pre-hash y usar pbkdf2
            pre = _prehash_sha256(password)
            return pwd_ctx.hash(pre, scheme="pbkdf2_sha256")

def verify_password(plain: str, hashed: str) -> bool:
    """
    Verifica una contraseña en texto plano contra su hash.
    Soporta hashes hechos con bcrypt_sha256, pbkdf2_sha256 y hashes generados con pre-hash SHA256.
    """
    if plain is None or hashed is None:
        return False
    try:
        # intento normal (passlib detecta el esquema desde el hash)
        return pwd_ctx.verify(plain, hashed)
    except Exception as e:
        logging.warning("pwd_ctx.verify failed (%s), trying pre-hash fallback", e)
        try:
            pre = _prehash_sha256(plain)
            return pwd_ctx.verify(pre, hashed)
        except Exception as e2:
            logging.debug("pre-hash verify also failed: %s", e2)
            return False
    
def create_access_token(subject: str, expires_minutes: Optional[int] = None) -> str:
    """
    Crea un JWT con claim 'sub' = subject. Usa SECRET y ALGORITHM del entorno.
    """
    if SECRET is None:
        raise RuntimeError("LOCAL_AUTH_SECRET no definido en el entorno")
    expire = datetime.utcnow() + timedelta(minutes=(expires_minutes or ACCESS_EXPIRE_MIN))
    payload = {
        "sub": str(subject),
        "iat": datetime.utcnow(),
        "exp": expire
    }
    token = jwt.encode(payload, SECRET, algorithm=ALGORITHM)
    return token

def decode_access_token(token: str) -> dict:
    """
    Decodifica y valida un JWT local. Lanza excepción si inválido/expirado.
    """
    if SECRET is None:
        raise RuntimeError("LOCAL_AUTH_SECRET no definido en el entorno")
    return jwt.decode(token, SECRET, algorithms=[ALGORITHM])