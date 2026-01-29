"""
Models package for InsanusChat Backend.

This package contains all Pydantic models used in the application:
- schemas: Domain models for database entities
- responses: API response models
"""
from models.schemas import (
    PyObjectId,
    UserAPIKeyModel,
    CodeSnippetModel,
    MCPEntryModel,
    AgentSnippetModel,
    AgentModel,
    MessageModel,
    ChatModel,
    UserModel,
)
from models.responses import (
    ResponseModel,
    AuthTokenResponse,
    UserResponse,
    AgentListResponse,
    AgentResponse,
    APIKeyListResponse,
    APIKeyResponse,
    ChatListResponse,
    ChatResponse,
    MessagesResponse,
    MessageResponse,
    SnippetResponse,
    MCPResponse,
)

__all__ = [
    # Domain models
    "PyObjectId",
    "UserAPIKeyModel",
    "CodeSnippetModel",
    "MCPEntryModel",
    "AgentSnippetModel",
    "AgentModel",
    "MessageModel",
    "ChatModel",
    "UserModel",
    # Response models
    "ResponseModel",
    "AuthTokenResponse",
    "UserResponse",
    "AgentListResponse",
    "AgentResponse",
    "APIKeyListResponse",
    "APIKeyResponse",
    "ChatListResponse",
    "ChatResponse",
    "MessagesResponse",
    "MessageResponse",
    "SnippetResponse",
    "MCPResponse",
]
