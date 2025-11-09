from typing import List, Optional, Literal, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr
from pydantic_core import PydanticCustomError, core_schema
from bson import ObjectId
import logging

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
        oid = ObjectId()
        logging.getLogger(__name__).debug("PyObjectId.new() -> %s", oid)
        return oid

    @classmethod
    def parse(cls, v):
        """Parsea una representación (str o ObjectId) a ObjectId.

        Si `v` ya es un ObjectId lo devuelve tal cual, si es str intenta
        convertirlo, y en caso de fallo propaga la excepción.
        """
        logger = logging.getLogger(__name__)
        logger.debug("PyObjectId.parse input: %s (type=%s)", v, type(v))
        if isinstance(v, ObjectId):
            logger.debug("PyObjectId.parse - input is already ObjectId: %s", v)
            return v
        parsed = ObjectId(str(v))
        logger.debug("PyObjectId.parse -> %s", parsed)
        return parsed


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
    # Endpoint usado para transportes de red (http/sse/ws). No obligatorio para STDIO transport.
    endpoint: Optional[str] = Field(None, description="URL base del MCP server (para transportes HTTP/SSE/WS)")
    # Transporte soportado por el registro: 'stdio' (arranca proceso local), 'sse', 'http', 'websocket'
    transport: Literal["stdio", "sse", "http", "websocket"] = Field("stdio", description="Tipo de transporte usado para conectar al MCP server")
    # Comando local y argumentos (útil cuando transport='stdio' y el servidor se arranca como proceso)
    command: Optional[str] = Field(None, description="Comando/executable para lanzar el servidor (ej. python/node). Si está vacío, se inferirá desde la extensión del script)")
    args: List[str] = Field(default_factory=list, description="Argumentos para el comando cuando se usa transporte STDIO")
    # Opciones de entorno (por seguridad no almacenar secretos en claro; preferir referencias a vault)
    env: Dict[str, str] = Field(default_factory=dict, description="Variables de entorno a pasar al proceso/transport")
    # Ruta local al script (útil para STDIO) y directorio de trabajo
    local_script_path: Optional[str] = Field(None, description="Ruta local al script del servidor (ej. /path/to/server.py)")
    working_dir: Optional[str] = Field(None, description="Directorio de trabajo cuando se lanza el proceso STDIO")

    spec: Dict[str, Any] = Field(default_factory=dict)
    # auth puede contener metadatos sobre el método (tipo: api_key, oauth, x509) pero evitar guardar secretos en texto
    auth: Optional[Dict[str, Any]] = Field(None, description="Método de auth (no almacenar secretos sin encriptado). Preferir referencias a credenciales seguras")
    # SSL / TLS details (paths, verify flags) cuando se usan transportes de red
    ssl: Optional[Dict[str, Any]] = Field(None, description="Opciones TLS/SSL (ej. {'verify': True, 'cert_path': '/path/to/cert.pem'})")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    registered_at: datetime = Field(default_factory=datetime.utcnow)
    active: bool = Field(True)
    # Estado de conectividad y datos operativos
    status: Literal["unknown", "available", "unreachable", "disabled"] = Field("unknown", description="Estado observado del endpoint/transport")
    timeout_seconds: int = Field(30, description="Timeout por defecto para llamadas relacionadas con este MCP (segundos)")
    last_connected_at: Optional[datetime] = Field(None, description="Última vez que se intentó/estableció conexión")

    model_config = {
        "populate_by_name": True,
        "json_encoders": { PyObjectId: str, datetime: lambda v: v.isoformat() }
    }


class AgentSnippetModel(BaseModel):
    """Snippet que puede inyectarse en el prompt del agente.

    El campo `language` permite identificar si es JS/Python/texto; el backend puede
    decidir cómo renderizar/ejecutar el snippet.
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
    # Lista de nombres o IDs de herramientas permitidas para este agente (control de permisos)
    allowed_tools: List[str] = Field(default_factory=list, description="Nombres o IDs de herramientas que este agente puede invocar")
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
    Mensaje embebido dentro de un documento `chats`.

    Este proyecto modela chats entre un usuario y un agente de IA. Cada mensaje
    puede activar al agente; por eso el mensaje contiene datos sobre qué agente
    se invoca, qué herramientas están activas y metadatos operativos.
    """
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    # referencia al chat (si usamos colección separada de mensajes)
    chat_id: PyObjectId = Field(..., description="ID del chat al que pertenece el mensaje")

    parent_id: Optional[PyObjectId] = Field(None, description="ID del padre directo")
    children_ids: List[PyObjectId] = Field(default_factory=list, description="IDs de hijos directos")
    path: List[PyObjectId] = Field(default_factory=list, description="Ruta ancestry [root,...,this]")
    # primer ancestro hacia arriba que tiene más de un hijo (anchor para 'primos')
    branch_anchor: Optional[PyObjectId] = Field(None, description="Primer ancestro con múltiples hijos (o None)")
    # referencias a nodos "primos" (izquierda/derecha) para navegación lateral rápida
    cousin_left: Optional[PyObjectId] = Field(None, description="Nodo primo a la izquierda (si existe)")
    cousin_right: Optional[PyObjectId] = Field(None, description="Nodo primo a la derecha (si existe)")

    sender_id: str = Field(..., description="ID del remitente (string): uid, agent_id, tool_id o 'SYSTEM')")
    role: str = Field("user", description="user|agent|system|tool|initializer")

    # Contenido del mensaje
    content: str = Field(..., description="Contenido principal del mensaje (texto)")
    content_type: str = Field("text", description="text|json|file|markdown|etc")

    # Estado/flujo del procesamiento por el agente
    status: str = Field("queued", description="queued|processing|done|failed")
    tokens_used: Optional[int] = Field(None, description="Estimación de tokens usados por el agente (si aplica)")

    # Timestamps
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
    Modelo de chat para la colección `chats`.

    Un `chat` pertenece a un usuario y tiene asociado un agente objetivo (agent_id).
    Los mensajes se almacenan embebidos en el campo `messages`.
    """
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    user_id: str = Field(..., description="Owner user id (string)")
    agent_id: Optional[PyObjectId] = Field(None, description="Agent principal asociado al chat")
    title: Optional[str] = Field(None, max_length=150)
    messages: List[MessageModel] = Field(default_factory=list)
    message_count: int = Field(0, description="Contador de mensajes en el chat")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # Cuando hay un agente procesando una respuesta, marcamos el chat como bloqueado
    # para evitar escrituras concurrentes que puedan crear ramas indeseadas.
    locked: bool = Field(False, description="Flag que indica si el chat está bloqueado para nuevas escrituras mientras un agente procesa")
    active_tools: List[PyObjectId] = Field(default_factory=list, description="IDs de herramientas activas para este chat")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated: Optional[datetime] = None

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
                            "transport": "stdio",
                            "local_script_path": "/opt/mcp_servers/weather_server/weather.py",
                            "command": "python3",
                            "args": ["/opt/mcp_servers/weather_server/weather.py"],
                            "working_dir": "/opt/mcp_servers/weather_server",
                            "env": {"ANTHROPIC_API_KEY": "<set-in-env-or-vault>"},
                            "spec": {"capabilities": ["tools", "files"]},
                            "metadata": {"env": "dev"},
                            "timeout_seconds": 30,
                            "status": "available"
                        }
                    ],
                "code_snippets": [
                    {"name": "parse_csv", "language": "python", "code": "def parse_csv(s): ..."}
                ],
                "api_keys": [
                    {"provider": "gemini", "label": "Mi Gemini", "encrypted_key": "<encrypted>"}
                ],
                "agents": [
                    {
                        "name": "weather-agent",
                        "description": "Agente que consulta el servidor de weather",
                        "allowed_tools": ["get_weather", "list_locations"]
                    }
                ]
            }
        }
    }
    
# Modelo de Respuesta (para API)
class ResponseModel(BaseModel):
    """Modelo básico para respuestas HTTP."""
    message: str = "Operación exitosa"
    data: Optional[Dict] = None
    
    def __init__(self, **data: Any):
        logger = logging.getLogger(__name__)
        try:
            logger.debug("ResponseModel.__init__ called with keys=%s types=%s",
                         list(data.keys()), {k: type(v).__name__ for k, v in data.items()})
        except Exception:
            logger.debug("ResponseModel.__init__ called (unable to pretty-print types)")
        super().__init__(**data)