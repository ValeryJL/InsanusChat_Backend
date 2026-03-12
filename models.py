from typing import List, Optional, Literal, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr
from pydantic_core import PydanticCustomError, core_schema
from bson import ObjectId
import logging


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
        return ObjectId()

    @classmethod
    def parse(cls, v):
        if isinstance(v, ObjectId):
            return v
        return ObjectId(str(v))


# -------------------------------------------------
# Sub-modelos de Dominio
# -------------------------------------------------
class UserAPIKeyModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId.new, alias="_id")
    provider: str = Field(..., description="Proveedor (gemini, openai, anthropic, ollama, openrouter)")
    label: Optional[str] = Field(None, description="Etiqueta descriptiva para la key.")
    encrypted_key: str = Field(..., description="Clave encriptada o enmascarada.")
    masked_key: Optional[str] = Field(None, description="Representación enmascarada segura (ej: AIza...9f2A).")
    base_url: Optional[str] = Field(None, description="Base URL opcional (para Ollama / OpenRouter / vLLM).")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_used: Optional[datetime] = None
    active: bool = Field(default=True)

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {PyObjectId: str, ObjectId: str, datetime: lambda v: v.isoformat()},
    }


class CodeSnippetModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId.new, alias="_id")
    name: str = Field(..., description="Nombre del snippet")
    description: Optional[str] = Field(None)
    language: Literal["python", "javascript", "text"] = Field("python")
    code: str = Field(..., description="Código fuente o plantilla del snippet.")
    type: Literal["runtime", "template"] = Field("runtime", description="runtime (ejecutable como tool) o template (inyectable en prompt)")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    public: bool = Field(False)
    active: bool = Field(True)

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {PyObjectId: str, ObjectId: str, datetime: lambda v: v.isoformat()},
    }


class MCPEntryModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId.new, alias="_id")
    name: str = Field(..., description="Nombre del MCP server")
    endpoint: Optional[str] = Field(None, description="URL base del MCP server (para transportes HTTP/SSE/WS)")
    transport: Literal["stdio", "sse", "http", "websocket"] = Field("stdio", description="Tipo de transporte usado para conectar al MCP server")
    command: Optional[str] = Field(None, description="Comando/executable para lanzar el servidor stdio")
    args: List[str] = Field(default_factory=list, description="Argumentos para el comando stdio")
    env: Dict[str, str] = Field(default_factory=dict, description="Variables de entorno a pasar al proceso/transport")
    local_script_path: Optional[str] = Field(None, description="Ruta local al script del servidor")
    working_dir: Optional[str] = Field(None, description="Directorio de trabajo cuando se lanza el proceso STDIO")
    spec: Dict[str, Any] = Field(default_factory=dict)
    auth: Optional[Dict[str, Any]] = Field(None)
    ssl: Optional[Dict[str, Any]] = Field(None)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    registered_at: datetime = Field(default_factory=datetime.utcnow)
    active: bool = Field(True)
    status: Literal["unknown", "available", "unreachable", "disabled"] = Field("unknown")
    timeout_seconds: int = Field(30)
    last_connected_at: Optional[datetime] = Field(None)

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {PyObjectId: str, ObjectId: str, datetime: lambda v: v.isoformat()},
    }


class AgentSnippetModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId.new, alias="_id")
    name: str = Field(..., description="Nombre del snippet")
    language: Literal["javascript", "python", "text"] = Field("javascript")
    code: str = Field(..., description="Código o template del snippet")
    type: Literal["template", "runtime"] = Field("runtime")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {PyObjectId: str, ObjectId: str, datetime: lambda v: v.isoformat()},
    }


class AgentModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId.new, alias="_id")
    name: str = Field(..., description="Nombre del agente")
    description: Optional[str] = Field(None)
    system_prompt: List[str] = Field(default_factory=list, description="Secuencia de strings y referencias SNIPPET:<id> o {{nombre}}")
    snippets: List[AgentSnippetModel] = Field(default_factory=list)
    spec: Dict[str, Any] = Field(default_factory=dict)
    allowed_tools: List[str] = Field(default_factory=list)
    active_tools: List[str] = Field(default_factory=list, description="IDs de CodeSnippets activos como herramientas para este agente")
    active_mcps: List[str] = Field(default_factory=list, description="IDs de MCP Servers activos para este agente")
    active_models: List[str] = Field(
        default_factory=lambda: ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
        description="Lista de modelos activos habilitados en este agente",
    )
    provider: Optional[str] = Field("gemini", description="Proveedor de IA: gemini, openai, anthropic, ollama, openrouter")
    model_selected: Optional[str] = Field("gemini-2.5-flash", description="Identificador del modelo principal seleccionado entre los modelos activos")
    model_fallback: Optional[str] = Field(None, description="Modelo de respaldo")
    api_key_id: Optional[str] = Field(None, description="ID de la API key específica del usuario")
    temperature: float = Field(0.7, description="Temperatura de generación")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    active: bool = Field(True)

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {PyObjectId: str, ObjectId: str, datetime: lambda v: v.isoformat()},
    }


class MessageModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId.new, alias="_id")
    chat_id: PyObjectId = Field(..., description="ID del chat al que pertenece el mensaje")
    parent_id: Optional[PyObjectId] = Field(None, description="ID del padre directo")
    children_ids: List[PyObjectId] = Field(default_factory=list, description="IDs de hijos directos")
    path: List[PyObjectId] = Field(default_factory=list, description="Ruta ancestry [root,...,parent]")
    branch_anchor: Optional[PyObjectId] = Field(None, description="Primer ancestro con múltiples hijos")
    cousin_left: Optional[PyObjectId] = Field(None, description="Nodo primo a la izquierda")
    cousin_right: Optional[PyObjectId] = Field(None, description="Nodo primo a la derecha")

    sender_id: Optional[str] = Field("user", description="ID del remitente: uid, agent_id o SYSTEM")
    role: str = Field("user", description="user|agent|system|tool|initializer")

    content: str = Field(..., description="Contenido principal del mensaje")
    content_type: str = Field("text", description="text|json|file|markdown")

    status: str = Field("done", description="queued|processing|done|failed|stopped")
    tokens_used: Optional[int] = Field(None, description="Tokens consumidos")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Traza de herramientas invocadas en este turno")
    provider: Optional[str] = Field(None)
    model: Optional[str] = Field(None)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    edited_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    is_deleted: bool = Field(False)
    version: int = Field(1)

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {PyObjectId: str, ObjectId: str, datetime: lambda v: v.isoformat()},
    }


class ChatModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId.new, alias="_id")
    user_id: str = Field(..., description="Owner user id (string)")
    agent_id: Optional[str] = Field(None, description="Agent principal asociado al chat")
    title: Optional[str] = Field("New Chat", max_length=150)
    messages: List[Any] = Field(default_factory=list)
    message_count: int = Field(0)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    locked: bool = Field(False)
    locked_at: Optional[datetime] = Field(None)
    active_tools: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated: Optional[datetime] = None

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {PyObjectId: str, ObjectId: str, datetime: lambda v: v.isoformat()},
    }


class UserModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId.new, alias="_id")
    email: EmailStr = Field(...)
    password_hash: Optional[str] = Field(None, repr=False)
    display_name: Optional[str] = Field(None, max_length=100)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    active: bool = Field(True)

    agents: List[AgentModel] = Field(default_factory=list)
    mcps: List[MCPEntryModel] = Field(default_factory=list)
    code_snippets: List[CodeSnippetModel] = Field(default_factory=list)
    api_keys: List[UserAPIKeyModel] = Field(default_factory=list)

    roles: List[str] = Field(default_factory=lambda: ["user"])
    settings: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {PyObjectId: str, ObjectId: str, datetime: lambda v: v.isoformat()},
    }


# -------------------------------------------------
# Modelos de Respuesta (API)
# -------------------------------------------------
class ResponseModel(BaseModel):
    message: str = "Operación exitosa"
    data: Optional[Any] = None
    errors: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None


class AuthTokenResponse(ResponseModel):
    data: Optional[Dict[str, Any]] = None


class UserResponse(ResponseModel):
    data: Optional[Any] = None


class AgentListResponse(ResponseModel):
    data: Optional[List[Any]] = None


class AgentResponse(ResponseModel):
    data: Optional[Any] = None


class APIKeyListResponse(ResponseModel):
    data: Optional[List[Any]] = None


class APIKeyResponse(ResponseModel):
    data: Optional[Any] = None


class ChatListResponse(ResponseModel):
    data: Optional[List[Any]] = None


class ChatResponse(ResponseModel):
    data: Optional[Any] = None


class MessagesResponse(ResponseModel):
    data: Optional[List[Any]] = None


class MessageResponse(ResponseModel):
    data: Optional[Any] = None


class SnippetResponse(ResponseModel):
    data: Optional[Any] = None


class MCPResponse(ResponseModel):
    data: Optional[Any] = None


# -------------------------------------------------
