"""
API Response Models for InsanusChat Backend.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import logging
from models.schemas import (
    UserModel, AgentModel, UserAPIKeyModel, CodeSnippetModel,
    MCPEntryModel, ChatModel, MessageModel
)

class ResponseModel(BaseModel):
    """Modelo básico para respuestas HTTP."""
    message: str = "Operación exitosa"
    data: Optional[Dict] = None
    errors: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None
    
    def __init__(self, **data: Any):
        logger = logging.getLogger(__name__)
        try:
            logger.debug("ResponseModel.__init__ called with keys=%s types=%s",
                         list(data.keys()), {k: type(v).__name__ for k, v in data.items()})
        except Exception:
            logger.debug("ResponseModel.__init__ called (unable to pretty-print types)")
        super().__init__(**data)
    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "Operación exitosa",
                "data": {"sample": "value"},
                "meta": {"page": 1, "size": 10, "total": 0},
                "errors": None
            }
        }
    }


# -------------------- Specific Response Models --------------------
class AuthTokenResponse(ResponseModel):
    """Respuesta para endpoints de autenticación que devuelven tokens."""
    data: Optional[Dict[str, str]] = None
    model_config = {
        "json_schema_extra": {
            "example": {"message": "Login OK", "data": {"access_token": "<jwt>", "token_type": "bearer", "user_id": "650f6b9e..."}}
        }
    }


class UserResponse(ResponseModel):
    data: Optional[UserModel] = None
    model_config = {
        "json_schema_extra": {
            "example": {"message": "Perfil recuperado", "data": {"_id": "650f6b9e1c4e4a3f9b0aaaaa", "email": "user@example.com", "display_name": "Usuario Demo", "created_at": "2025-11-09T12:34:56Z"}}
        }
    }


class AgentListResponse(ResponseModel):
    data: Optional[List[AgentModel]] = None
    model_config = {
        "json_schema_extra": {
            "example": {"message": "Agentes listados", "data": [{"_id": "650f...", "name": "weather-agent", "description": "..."}]}
        }
    }


class AgentResponse(ResponseModel):
    data: Optional[AgentModel] = None


class APIKeyListResponse(ResponseModel):
    data: Optional[List[UserAPIKeyModel]] = None


class APIKeyResponse(ResponseModel):
    data: Optional[UserAPIKeyModel] = None


class ChatListResponse(ResponseModel):
    data: Optional[List[ChatModel]] = None


class ChatResponse(ResponseModel):
    data: Optional[ChatModel] = None


class MessagesResponse(ResponseModel):
    data: Optional[List[MessageModel]] = None


class MessageResponse(ResponseModel):
    data: Optional[MessageModel] = None


class SnippetResponse(ResponseModel):
    data: Optional[CodeSnippetModel] = None


class MCPResponse(ResponseModel):
    data: Optional[MCPEntryModel] = None