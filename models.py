from typing import List, Optional, Literal, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr
from pydantic_core import PydanticCustomError, core_schema
from bson import ObjectId

# -------------------------------------------------
# Helper: PyObjectId (compatible con Pydantic v2)
# -------------------------------------------------
class PyObjectId:
    """
    Custom BSON ObjectId type for Pydantic v2.
    Validates strings/ObjectId -> returns ObjectId instance.
    Produces a JSON schema of string with 24-hex pattern.
    """
    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        def validate(v):
            if isinstance(v, ObjectId):
                return v
            if not ObjectId.is_valid(v):
                raise PydanticCustomError("value_error.invalid_objectid", "Invalid ObjectId")
            return ObjectId(v)
        return core_schema.no_info_plain_validator_function(validate)

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        return {"type": "string", "pattern": "^[0-9a-fA-F]{24}$"}

    @classmethod
    def new(cls):
        """Factory helper: devuelve un nuevo bson.ObjectId.

        Útil para crear ids desde el código que prepara documentos para la DB
        manteniendo coherencia con el tipo usado en los modelos Pydantic.
        """
        return ObjectId()

    @classmethod
    def parse(cls, v):
        """Parsea una representación (str o ObjectId) a ObjectId.

        Si `v` ya es un ObjectId lo devuelve tal cual, si es str intenta
        convertirlo, y en caso de fallo propaga la excepción.
        """
        if isinstance(v, ObjectId):
            return v
        return ObjectId(str(v))


# -------------------------------------------------
# Sub-modelos
# -------------------------------------------------
class UserAPIKeyModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    provider: str = Field(..., description="Proveedor (openai, gemini, anthropic, etc.)")
    label: Optional[str] = Field(None, description="Etiqueta descriptiva para la key.")
    encrypted_key: str = Field(..., description="Clave encriptada almacenada por el backend.")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_used: Optional[datetime] = None
    active: bool = Field(default=True)

    model_config = {
        "populate_by_name": True,
        "json_encoders": { PyObjectId: str, datetime: lambda v: v.isoformat() }
    }


class CodeSnippetModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    name: str = Field(..., description="Nombre del snippet")
    description: Optional[str] = Field(None)
    language: Literal["python", "javascript"] = Field(...)
    code: str = Field(..., description="Código fuente (texto). Considerar encriptar si contiene secretos.")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    public: bool = Field(False)

    model_config = {
        "populate_by_name": True,
        "json_encoders": { PyObjectId: str, datetime: lambda v: v.isoformat() }
    }


class MCPEntryModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    name: str = Field(..., description="Nombre del MCP server")
    endpoint: str = Field(..., description="URL base del MCP server")
    spec: Dict[str, Any] = Field(default_factory=dict)
    auth: Optional[Dict[str, Any]] = Field(None, description="Método de auth (no almacenar secretos sin encriptado)")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    registered_at: datetime = Field(default_factory=datetime.utcnow)
    active: bool = Field(True)

    model_config = {
        "populate_by_name": True,
        "json_encoders": { PyObjectId: str, datetime: lambda v: v.isoformat() }
    }


class AgentSnippetModel(BaseModel):
    """Snippet que puede inyectarse en el prompt del agente.

    El campo `language` permite identificar si es JS/Python/texto; el backend puede
    decidir cómo renderizar/ejecutar el snippet (por ahora se trata como texto).
    """
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    name: str = Field(..., description="Nombre del snippet")
    language: Literal["javascript", "python", "text"] = Field("javascript")
    code: str = Field(..., description="Código o template del snippet")
    type: Literal["template", "runtime"] = Field("runtime", description="Cómo será usado el snippet")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "populate_by_name": True,
        "json_encoders": { PyObjectId: str, datetime: lambda v: v.isoformat() }
    }

class AgentModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    name: str = Field(..., description="Nombre del agente")
    description: Optional[str] = Field(None)
    # `system_prompt` ahora es una secuencia de strings que pueden contener texto
    # o referencias a snippets en el formato "SNIPPET:<snippet_id>". Ejemplo:
    # ["You are a helpful assistant.", "SNIPPET:613f...", "Current date: {{now}}"]
    system_prompt: List[str] = Field(default_factory=list, description="Secuencia para el system prompt: texto y/o referencias a snippets")
    # snippets embebidos que pueden ser referenciados desde `system_prompt`.
    snippets: List[AgentSnippetModel] = Field(default_factory=list)
    spec: Dict[str, Any] = Field(default_factory=dict)  # configuración/plantilla adicional del agente
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    active: bool = Field(True)

    model_config = {
        "populate_by_name": True,
        "json_encoders": { PyObjectId: str, datetime: lambda v: v.isoformat() }
    }

# -------------------------------------------------
# Message & Chat models (colecciones separadas)
# -------------------------------------------------
class MessageModel(BaseModel):
    """
    Modelo de mensaje para la colección 'messages'.
    Incluye campos para soportar árbol (parent/children), path (ancestros), thread_root (root de rama), y metadatos operativos.
    """
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    chat_id: PyObjectId = Field(..., description="ID del chat al que pertenece (referencia)")
    parent_id: Optional[PyObjectId] = Field(None, description="ID del padre directo")
    children_ids: List[PyObjectId] = Field(default_factory=list, description="IDs de hijos directos")
    path: List[PyObjectId] = Field(default_factory=list, description="Ruta ancestry [root,...,this]")
    thread_root: PyObjectId = Field(..., description="ID del root de la rama/hilo (puede ser el primer mensaje del chat)")
    branch_label: Optional[str] = Field(None, description="Etiqueta opcional para la rama (p.ej. 'v2')")

    sender_id: str = Field(..., description="ID del remitente (firebase uid, 'AI', 'SYSTEM')")
    role: str = Field("user", description="user|agent|system|tool")
    content: str = Field(..., description="Contenido del mensaje")
    content_type: str = Field("text", description="text|file|json|etc")
    tools_used: List[Dict[str, Any]] = Field(default_factory=list, description="Herramientas invocadas")
    tokens_used: Optional[int] = Field(None, description="Estimación tokens usados")
    status: str = Field("done", description="queued|processing|done|failed")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    edited_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    is_deleted: bool = Field(False)
    version: int = Field(1, description="Versión para control optimista")

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": { PyObjectId: str, datetime: lambda v: v.isoformat() }
    }


class ChatModel(BaseModel):
    """
    Modelo de chat para la colección 'chats'.
    Guarda metadata y resumen de ramas/threads. Los mensajes se guardan en la colección 'messages'.
    """
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    user_id: str = Field(..., description="Owner firebase uid")
    title: str = Field(..., max_length=150)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    default_thread_root: Optional[PyObjectId] = Field(None, description="Root de thread por defecto")
    thread_roots: List[PyObjectId] = Field(default_factory=list, description="Roots de ramas principales")
    message_count: int = Field(0, description="Contador de mensajes en el chat")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": { PyObjectId: str, datetime: lambda v: v.isoformat() }
    }


# -------------------------------------------------
# Modelo principal de Usuario
# -------------------------------------------------
class UserModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id", description="Identificador MongoDB")
    email: EmailStr = Field(..., description="Correo electrónico del usuario")
    password_hash: Optional[str] = Field(None, repr=False, description="Hash bcrypt de la contraseña local (no almacenar contraseñas en texto)")
    display_name: Optional[str] = Field(None, max_length=100)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None

    agents: List[AgentModel] = Field(default_factory=list)
    mcps: List[MCPEntryModel] = Field(default_factory=list)
    code_snippets: List[CodeSnippetModel] = Field(default_factory=list)
    api_keys: List[UserAPIKeyModel] = Field(default_factory=list)

    roles: List[str] = Field(default_factory=list)
    settings: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": { PyObjectId: str, datetime: lambda v: v.isoformat() },
        "json_schema_extra": {
            "example": {
                "firebase_id": "firebase_uid_12345",
                "email": "usuario@ejemplo.com",
                "display_name": "Valeria Developer",
                "mcps": [
                    {
                        "name": "MCP-Local",
                        "endpoint": "https://mcp.example.com",
                        "spec": {"capabilities": ["tools", "files"]},
                        "metadata": {"env": "dev"}
                    }
                ],
                "code_snippets": [
                    {"name": "parse_csv", "language": "python", "code": "def parse_csv(s): ..."}
                ],
                "api_keys": [
                    {"provider": "gemini", "label": "Mi Gemini", "encrypted_key": "<encrypted>"}
                ]
            }
        }
    }
    
# Modelo de Respuesta (para API)
class ResponseModel(BaseModel):
    """Modelo básico para respuestas HTTP."""
    message: str = "Operación exitosa"
    data: Optional[Dict] = None