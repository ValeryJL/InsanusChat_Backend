from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr
from bson import ObjectId

# 1. Definición del tipo para MongoDB ObjectId
class PyObjectId(ObjectId):
    """Clase personalizada para manejar el tipo ObjectId de MongoDB en Pydantic."""
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError('Invalid objectid')
        return ObjectId(v)

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(type='string')


# 2. Modelo de Usuario (Colección 'users')
class UserModel(BaseModel):
    """
    Representa un documento de usuario en la colección 'users'.
    El campo 'firebase_id' se usa como el ID principal del usuario,
    vinculándolo directamente con Firebase Auth.
    """
    # Usaremos el ID de Firebase como el identificador principal
    firebase_id: str = Field(..., description="ID único del usuario proporcionado por Firebase Auth.")
    email: EmailStr = Field(..., description="Correo electrónico del usuario.")
    display_name: str = Field(..., max_length=100, description="Nombre visible del usuario.")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Fecha y hora de creación del usuario.")
    last_login: datetime = Field(default_factory=datetime.utcnow, description="Fecha y hora del último inicio de sesión.")

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {
            PyObjectId: str,
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "firebase_id": "firebase_uid_12345",
                "email": "usuario@ejemplo.com",
                "display_name": "Valeria Developer",
            }
        }


# 3. Modelo de Mensaje para la conversación (Usado en la colección 'chats')
class MessageModel(BaseModel):
    """
    Representa un mensaje individual dentro de una conversación.
    Cumple con la estructura de Árbol de la H2.3 (padre/hijo).
    """
    message_id: PyObjectId = Field(default_factory=PyObjectId, alias="_id", description="ID único del mensaje.")
    parent_id: Optional[PyObjectId] = Field(None, description="ID del mensaje padre, nulo si es el primer mensaje del hilo.")
    children_ids: List[PyObjectId] = Field([], description="IDs de los mensajes hijos que responden a este.")
    sender_id: str = Field(..., description="ID del remitente (ID de Firebase para el usuario, 'AI' o 'SYSTEM').")
    content: str = Field(..., description="Contenido del texto del mensaje.")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Marca de tiempo del mensaje.")
    is_deleted: bool = Field(False, description="Indica si el mensaje ha sido borrado.")

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {
            PyObjectId: str,
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "parent_id": None,
                "children_ids":[],
                "sender_id": "firebase_uid_12345",
                "content": "¿Cómo puedo empezar a programar con FastAPI?",
            }
        }

# 4. Modelo de Chat/Conversación (Colección 'chats')
class ChatModel(BaseModel):
    """
    Representa una conversación completa, que contendrá todos los mensajes.
    """
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id", description="ID de la conversación de MongoDB.")
    user_id: str = Field(..., description="ID del usuario propietario de la conversación (ID de Firebase).")
    title: str = Field(..., max_length=150, description="Título generado para la conversación.")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Fecha y hora de inicio de la conversación.")
    # Los mensajes se almacenan como sub-documentos en la misma colección (colección 'chats')
    messages: List[MessageModel] = Field([], description="Lista de todos los mensajes en el hilo principal y sus ramificaciones.")

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {
            PyObjectId: str, 
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "user_id": "firebase_uid_12345",
                "title": "Introducción a FastAPI y MongoDB",
                "messages": [],
            }
        }

# Modelo de Respuesta (para API)
class ResponseModel(BaseModel):
    """Modelo básico para respuestas HTTP."""
    message: str = "Operación exitosa"