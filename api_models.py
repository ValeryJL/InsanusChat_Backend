"""
Standardized API Request/Response Models for InsanusChat Backend.

This module provides consistent DTO (Data Transfer Objects) models for all API endpoints,
with comprehensive validation, examples, and OpenAPI documentation.
"""
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr, field_validator
from models import PyObjectId


# ==================== Base Response Models ====================

class APIResponse(BaseModel):
    """Standard API response wrapper."""
    success: bool = Field(True, description="Indicates if the request was successful")
    message: str = Field(..., description="Human-readable message describing the result")
    data: Optional[Any] = Field(None, description="Response data payload")
    errors: Optional[List[str]] = Field(None, description="List of error messages if any")
    meta: Optional[Dict[str, Any]] = Field(None, description="Additional metadata (pagination, etc.)")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "success": True,
                "message": "Operation completed successfully",
                "data": {"id": "507f1f77bcf86cd799439011"},
                "errors": None,
                "meta": {"timestamp": "2026-01-29T12:00:00Z"}
            }]
        }
    }


class ErrorResponse(BaseModel):
    """Standard error response."""
    success: bool = Field(False, description="Always false for errors")
    message: str = Field(..., description="Error message")
    errors: List[str] = Field(default_factory=list, description="Detailed error messages")
    code: Optional[str] = Field(None, description="Error code for programmatic handling")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "success": False,
                "message": "Validation failed",
                "errors": ["Field 'name' is required", "Field 'email' must be valid"],
                "code": "VALIDATION_ERROR"
            }]
        }
    }


# ==================== Authentication Models ====================

class RegisterRequest(BaseModel):
    """Request model for user registration."""
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="User password (min 8 characters)")
    display_name: str = Field(..., min_length=2, max_length=50, description="Display name")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "email": "user@example.com",
                "password": "securepassword123",
                "display_name": "John Doe"
            }]
        }
    }


class LoginRequest(BaseModel):
    """Request model for user login."""
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "email": "user@example.com",
                "password": "securepassword123"
            }]
        }
    }


class AuthTokenResponse(BaseModel):
    """Response model for authentication tokens."""
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field("bearer", description="Token type (always 'bearer')")
    expires_in: Optional[int] = Field(None, description="Token expiration time in seconds")
    user_id: str = Field(..., description="User ID")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 3600,
                "user_id": "507f1f77bcf86cd799439011"
            }]
        }
    }


class UserProfileResponse(BaseModel):
    """Response model for user profile."""
    id: str = Field(..., description="User ID")
    email: EmailStr = Field(..., description="User email")
    display_name: Optional[str] = Field(None, description="Display name")
    created_at: datetime = Field(..., description="Account creation timestamp")
    last_login: Optional[datetime] = Field(None, description="Last login timestamp")
    roles: List[str] = Field(default_factory=list, description="User roles")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "507f1f77bcf86cd799439011",
                "email": "user@example.com",
                "display_name": "John Doe",
                "created_at": "2026-01-15T10:30:00Z",
                "last_login": "2026-01-29T08:00:00Z",
                "roles": ["user"]
            }]
        }
    }


# ==================== Agent Models ====================

class CreateAgentRequest(BaseModel):
    """Request model for creating an agent."""
    name: str = Field(..., min_length=1, max_length=100, description="Agent name")
    description: Optional[str] = Field(None, max_length=500, description="Agent description")
    system_prompt: List[str] = Field(default_factory=list, description="System prompt segments")
    model_selected: Optional[str] = Field("gemini-1.5-flash", description="LLM model to use")
    temperature: Optional[float] = Field(0.7, ge=0.0, le=2.0, description="Model temperature")
    mcp_ids: List[str] = Field(default_factory=list, description="List of MCP server IDs to enable")
    snippet_ids: List[str] = Field(default_factory=list, description="List of snippet IDs to enable")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "name": "Customer Support Agent",
                "description": "Helps customers with product questions",
                "system_prompt": ["You are a helpful customer support agent.", "Be polite and professional."],
                "model_selected": "gemini-1.5-flash",
                "temperature": 0.7,
                "mcp_ids": [],
                "snippet_ids": []
            }]
        }
    }


class UpdateAgentRequest(BaseModel):
    """Request model for updating an agent."""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Agent name")
    description: Optional[str] = Field(None, max_length=500, description="Agent description")
    system_prompt: Optional[List[str]] = Field(None, description="System prompt segments")
    model_selected: Optional[str] = Field(None, description="LLM model to use")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Model temperature")
    mcp_ids: Optional[List[str]] = Field(None, description="List of MCP server IDs")
    snippet_ids: Optional[List[str]] = Field(None, description="List of snippet IDs")
    active: Optional[bool] = Field(None, description="Whether agent is active")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "name": "Updated Agent Name",
                "temperature": 0.8,
                "active": True
            }]
        }
    }


class AgentResponse(BaseModel):
    """Response model for agent data."""
    id: str = Field(..., description="Agent ID")
    name: str = Field(..., description="Agent name")
    description: Optional[str] = Field(None, description="Agent description")
    system_prompt: List[str] = Field(default_factory=list, description="System prompt")
    model_selected: str = Field(..., description="Selected LLM model")
    temperature: float = Field(..., description="Model temperature")
    created_at: datetime = Field(..., description="Creation timestamp")
    active: bool = Field(..., description="Active status")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "507f1f77bcf86cd799439011",
                "name": "Customer Support Agent",
                "description": "Helps customers",
                "system_prompt": ["You are helpful."],
                "model_selected": "gemini-1.5-flash",
                "temperature": 0.7,
                "created_at": "2026-01-29T10:00:00Z",
                "active": True
            }]
        }
    }


# ==================== API Key Models ====================

class CreateAPIKeyRequest(BaseModel):
    """Request model for creating an API key."""
    provider: str = Field(..., description="Provider name (openai, gemini, anthropic, etc.)")
    encrypted_key: str = Field(..., description="Encrypted API key")
    label: Optional[str] = Field(None, max_length=100, description="Optional label")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "provider": "openai",
                "encrypted_key": "<encrypted-key-here>",
                "label": "My OpenAI Key"
            }]
        }
    }


class UpdateAPIKeyRequest(BaseModel):
    """Request model for updating an API key."""
    label: Optional[str] = Field(None, max_length=100, description="Updated label")
    encrypted_key: Optional[str] = Field(None, description="Updated encrypted key")
    active: Optional[bool] = Field(None, description="Active status")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "label": "Updated Label",
                "active": True
            }]
        }
    }


class APIKeyResponse(BaseModel):
    """Response model for API key data."""
    id: str = Field(..., description="API key ID")
    provider: str = Field(..., description="Provider name")
    label: Optional[str] = Field(None, description="Key label")
    created_at: datetime = Field(..., description="Creation timestamp")
    last_used: Optional[datetime] = Field(None, description="Last usage timestamp")
    active: bool = Field(..., description="Active status")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "507f1f77bcf86cd799439011",
                "provider": "openai",
                "label": "My OpenAI Key",
                "created_at": "2026-01-29T10:00:00Z",
                "last_used": "2026-01-29T11:30:00Z",
                "active": True
            }]
        }
    }


# ==================== MCP Models ====================

class CreateMCPRequest(BaseModel):
    """Request model for creating an MCP server configuration."""
    name: str = Field(..., min_length=1, max_length=100, description="MCP server name")
    transport: Literal["stdio", "sse", "http", "websocket"] = Field("stdio", description="Transport type")
    local_script_path: Optional[str] = Field(None, description="Path to local script (for stdio)")
    endpoint: Optional[str] = Field(None, description="HTTP endpoint (for network transports)")
    command: Optional[str] = Field(None, description="Command to run (for stdio)")
    args: List[str] = Field(default_factory=list, description="Command arguments")
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    working_dir: Optional[str] = Field(None, description="Working directory")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "name": "Calculator Server",
                "transport": "stdio",
                "local_script_path": "/path/to/calculator.py",
                "command": "python3",
                "args": ["/path/to/calculator.py"],
                "env": {},
                "working_dir": None
            }]
        }
    }


class UpdateMCPRequest(BaseModel):
    """Request model for updating an MCP server configuration."""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="MCP server name")
    endpoint: Optional[str] = Field(None, description="HTTP endpoint")
    active: Optional[bool] = Field(None, description="Active status")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "name": "Updated Calculator",
                "active": True
            }]
        }
    }


class MCPResponse(BaseModel):
    """Response model for MCP server data."""
    id: str = Field(..., description="MCP server ID")
    name: str = Field(..., description="MCP server name")
    transport: str = Field(..., description="Transport type")
    endpoint: Optional[str] = Field(None, description="Endpoint URL")
    registered_at: datetime = Field(..., description="Registration timestamp")
    active: bool = Field(..., description="Active status")
    status: str = Field(..., description="Connection status")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "507f1f77bcf86cd799439011",
                "name": "Calculator Server",
                "transport": "stdio",
                "endpoint": None,
                "registered_at": "2026-01-29T10:00:00Z",
                "active": True,
                "status": "available"
            }]
        }
    }


# ==================== Snippet Models ====================

class CreateSnippetRequest(BaseModel):
    """Request model for creating a code snippet."""
    name: str = Field(..., min_length=1, max_length=100, description="Snippet name")
    language: Literal["python", "javascript"] = Field(..., description="Programming language")
    code: str = Field(..., min_length=1, description="Snippet code")
    description: Optional[str] = Field(None, max_length=500, description="Description")
    public: bool = Field(False, description="Whether snippet is public")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "name": "Hello World",
                "language": "python",
                "code": "print('Hello, World!')",
                "description": "Simple hello world example",
                "public": False
            }]
        }
    }


class UpdateSnippetRequest(BaseModel):
    """Request model for updating a code snippet."""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Snippet name")
    code: Optional[str] = Field(None, min_length=1, description="Snippet code")
    description: Optional[str] = Field(None, max_length=500, description="Description")
    public: Optional[bool] = Field(None, description="Public status")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "name": "Updated Snippet",
                "code": "print('Updated!')"
            }]
        }
    }


class SnippetResponse(BaseModel):
    """Response model for snippet data."""
    id: str = Field(..., description="Snippet ID")
    name: str = Field(..., description="Snippet name")
    language: str = Field(..., description="Programming language")
    code: str = Field(..., description="Snippet code")
    description: Optional[str] = Field(None, description="Description")
    created_at: datetime = Field(..., description="Creation timestamp")
    public: bool = Field(..., description="Public status")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "507f1f77bcf86cd799439011",
                "name": "Hello World",
                "language": "python",
                "code": "print('Hello, World!')",
                "description": "Simple example",
                "created_at": "2026-01-29T10:00:00Z",
                "public": False
            }]
        }
    }


# ==================== Chat Models ====================

class CreateChatRequest(BaseModel):
    """Request model for creating a chat."""
    title: Optional[str] = Field(None, max_length=150, description="Chat title")
    agent_id: Optional[str] = Field(None, description="Agent ID to use for this chat")
    initial_message: Optional[str] = Field(None, description="Initial message content")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "title": "Customer Support Session",
                "agent_id": "507f1f77bcf86cd799439011",
                "initial_message": "Hello, I need help with my order"
            }]
        }
    }


class SendMessageRequest(BaseModel):
    """Request model for sending a message."""
    content: str = Field(..., min_length=1, description="Message content")
    parent_id: Optional[str] = Field(None, description="Parent message ID for threading")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "content": "What is the weather today?",
                "parent_id": None
            }]
        }
    }


class MessageResponse(BaseModel):
    """Response model for message data."""
    id: str = Field(..., description="Message ID")
    chat_id: str = Field(..., description="Chat ID")
    content: str = Field(..., description="Message content")
    role: str = Field(..., description="Message role (user/agent/system)")
    sender_id: str = Field(..., description="Sender ID")
    created_at: datetime = Field(..., description="Creation timestamp")
    status: str = Field(..., description="Message status")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "507f1f77bcf86cd799439011",
                "chat_id": "507f1f77bcf86cd799439012",
                "content": "Hello, how can I help?",
                "role": "agent",
                "sender_id": "507f1f77bcf86cd799439013",
                "created_at": "2026-01-29T10:00:00Z",
                "status": "done"
            }]
        }
    }


class ChatResponse(BaseModel):
    """Response model for chat data."""
    id: str = Field(..., description="Chat ID")
    user_id: str = Field(..., description="Owner user ID")
    title: Optional[str] = Field(None, description="Chat title")
    agent_id: Optional[str] = Field(None, description="Associated agent ID")
    message_count: int = Field(0, description="Total message count")
    created_at: datetime = Field(..., description="Creation timestamp")
    last_updated: Optional[datetime] = Field(None, description="Last update timestamp")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "507f1f77bcf86cd799439011",
                "user_id": "507f1f77bcf86cd799439012",
                "title": "Support Chat",
                "agent_id": "507f1f77bcf86cd799439013",
                "message_count": 5,
                "created_at": "2026-01-29T10:00:00Z",
                "last_updated": "2026-01-29T11:00:00Z"
            }]
        }
    }


# ==================== List Response Models ====================

class PaginationMeta(BaseModel):
    """Pagination metadata."""
    page: int = Field(1, ge=1, description="Current page number")
    per_page: int = Field(30, ge=1, le=100, description="Items per page")
    total: int = Field(0, ge=0, description="Total item count")
    pages: int = Field(0, ge=0, description="Total page count")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "page": 1,
                "per_page": 30,
                "total": 100,
                "pages": 4
            }]
        }
    }


class AgentListResponse(APIResponse):
    """Response model for list of agents."""
    data: List[AgentResponse] = Field(default_factory=list)
    meta: Optional[PaginationMeta] = None


class APIKeyListResponse(APIResponse):
    """Response model for list of API keys."""
    data: List[APIKeyResponse] = Field(default_factory=list)
    meta: Optional[PaginationMeta] = None


class MCPListResponse(APIResponse):
    """Response model for list of MCP servers."""
    data: List[MCPResponse] = Field(default_factory=list)
    meta: Optional[PaginationMeta] = None


class SnippetListResponse(APIResponse):
    """Response model for list of snippets."""
    data: List[SnippetResponse] = Field(default_factory=list)
    meta: Optional[PaginationMeta] = None


class ChatListResponse(APIResponse):
    """Response model for list of chats."""
    data: List[ChatResponse] = Field(default_factory=list)
    meta: Optional[PaginationMeta] = None


class MessageListResponse(APIResponse):
    """Response model for list of messages."""
    data: List[MessageResponse] = Field(default_factory=list)
    meta: Optional[PaginationMeta] = None
