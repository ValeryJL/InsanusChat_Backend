# InsanusChat Backend

> A powerful FastAPI-based backend for AI chat applications with advanced agent management, MCP server integration, and visual branching conversations.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com/)
[![MongoDB](https://img.shields.io/badge/MongoDB-7.0+-green.svg)](https://www.mongodb.com/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL%203.0-blue.svg)](LICENSE)

## Overview

InsanusChat Backend is a comprehensive chat system that enables:
- **AI Agent Management**: Create and manage custom AI agents with configurable behaviors
- **MCP Integration**: Connect to Model Context Protocol servers for extended functionality
- **Code Execution**: Run Python/JavaScript snippets as tools within conversations
- **Branching Conversations**: Visual tree-based chat navigation with message history
- **Real-time Communication**: WebSocket support for live chat interactions
- **Secure Authentication**: JWT-based authentication with API key management

## Quick Start

### Prerequisites
- Python 3.12.1 or higher
- MongoDB 7.0+
- pip and git

### Installation

```bash
# Clone the repository
git clone https://github.com/ValeryJL/InsanusChat_Backend.git
cd InsanusChat_Backend

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables (see Configuration section)
cp .env.example .env  # Edit with your values

# Run the server
python backend.py
```

The server will start at `http://localhost:8000`

### Quick Test

```bash
# Use the interactive CLI
python cli/chat_cli.py

# Connect to a different server
python cli/chat_cli.py --url http://your-server:8000

# Or run comprehensive tests
python tests/test_api_comprehensive.py
```

## Interactive CLI

The CLI provides a complete management interface for the backend:

```bash
python cli/chat_cli.py
```

### All Available Commands

#### Authentication
- `register` - Register a new user
- `login` - Login with credentials
- `logout` - Logout current user
- `profile` - View your profile

#### Chat Management
- `chats` - List all chats
- `chat new` - Create a new chat (message optional!)
- `chat select <id>` - Select a chat
- `chat delete <id>` - Delete a chat

#### Messages
- `send <message>` - Send message to current chat
- `history` - View chat history

#### Agents
- `agents` - List all agents
- `agent new` - Create a new agent
- `agent delete <id>` - Delete an agent

#### API Keys ⭐ NEW
- `apikeys` - List all API keys
- `apikey add` - Add a new API key
- `apikey delete <id>` - Delete an API key

#### Tools/Resources ⭐ NEW
- `resources` - List all MCPs and snippets
- `mcp add` - Add a new MCP server
- `mcp delete <id>` - Delete an MCP server
- `snippet add` - Add a new code snippet
- `snippet delete <id>` - Delete a code snippet

#### Utilities
- `help` - Show all commands
- `clear` - Clear screen
- `quit/exit` - Exit CLI

See [CLI_DEMO.txt](CLI_DEMO.txt) for detailed examples and usage.

## Recent Improvements (2025-01)

This backend has been refactored to leverage **LangChain** for agent execution, with significant improvements in:
- ✅ MCP (Model Context Protocol) server integration as LangChain tools
- ✅ Python/JavaScript code snippet execution as tools
- ✅ Enhanced error handling and logging
- ✅ Comprehensive automated testing
- ✅ Reorganized project structure with modular models

See [docs/REFACTORING.md](docs/REFACTORING.md) for complete refactoring details.

## Configuration

Crea un archivo `.env` en la raíz con las variables necesarias. Ejemplo mínimo:

```
# Entorno
PORT=8000

# Seguridad / Aplicación
LOCAL_AUTH_SECRET="secreto de JWT"
LOCAL_AUTH_ALG="algoritmo de encriptación"
LOCAL_AUTH_EXPIRE_MIN="tiempo de expiracion del token JWT"

# Base de datos
MONGO_URI="cadena de coneccion a mongoDB"
MONGO_X509_CERT_PATH="./secrets/mongodb-cert.pem"
```

Sugerencias
- Usa gestores de secretos (Vault, AWS Secrets Manager, GitHub Secrets) en producción en lugar de `.env`.
- Genera LOCAL_AUTH_SECRET con un generador seguro y cambia valores por defecto antes de desplegar.

### Alternative: Run with Uvicorn

```bash
uvicorn backend:app --reload --host 0.0.0.0 --port 8000
```

## Development Setup

### MongoDB Local

Para configurar MongoDB localmente para pruebas:

```bash
./setup_local_mongodb.sh
```

O manualmente con Docker:
```bash
docker run -d \
  --name insanuschat-mongodb \
  -p 27017:27017 \
  -v $(pwd)/mongodb_data:/data/db \
  -e MONGO_INITDB_ROOT_USERNAME=admin \
  -e MONGO_INITDB_ROOT_PASSWORD=insanus_admin_pass \
  mongo:7.0
```

Luego agrega a `.env`:
```
MONGO_URI="mongodb://admin:insanus_admin_pass@localhost:27017/insanus_chat?authSource=admin"
```

### Certificado X.509

Para generar certificados de prueba:

```bash
cd secrets
./create-cert.sh
```

Esto crea los certificados necesarios en `secrets/mongodb-cert.pem`.

## API Endpoints

### Authentication
- `POST /auth/register` - Register a new user
- `POST /auth/login` - Login and obtain JWT token
- `GET /auth/profile` - Get current user profile

### Chats
- `GET /chats` - List all user chats
- `POST /chats` - Create a new chat
- `GET /chats/{chat_id}` - Get specific chat details
- `DELETE /chats/{chat_id}` - Delete a chat
- `GET /chats/{chat_id}/messages` - Get chat messages
- `POST /chats/{chat_id}/messages` - Send a message to chat

### Agents
- `GET /agents` - List all user agents
- `POST /agents` - Create a new agent
- `GET /agents/{agent_id}` - Get agent details
- `PUT /agents/{agent_id}` - Update agent configuration
- `DELETE /agents/{agent_id}` - Delete an agent

### API Keys
- `GET /api-keys` - List all API keys
- `POST /api-keys` - Add a new API key for AI providers
- `PUT /api-keys/{key_id}` - Update an API key
- `DELETE /api-keys/{key_id}` - Delete an API key

### MCP Servers
- `GET /mcps` - List all MCP server entries
- `POST /mcps` - Register a new MCP server
- `GET /mcps/{mcp_id}` - Get MCP server details
- `PUT /mcps/{mcp_id}` - Update MCP configuration
- `DELETE /mcps/{mcp_id}` - Delete an MCP server

### Code Snippets
- `GET /snippets` - List all code snippets
- `POST /snippets` - Create a new snippet
- `GET /snippets/{snippet_id}` - Get snippet details
- `PUT /snippets/{snippet_id}` - Update a snippet
- `DELETE /snippets/{snippet_id}` - Delete a snippet

### WebSocket
- `WS /ws/chat/{chat_id}` - WebSocket connection for real-time chat

For detailed API documentation, visit `/docs` (Swagger UI) or `/redoc` (ReDoc) when the server is running.

## Testing

### Interactive CLI
```bash
# Start the interactive chat CLI
python cli/chat_cli.py

# Connect to a specific server
python cli/chat_cli.py --url https://api.example.com
```

### Comprehensive Test Script
```bash
# Run the full test suite interactively
python tests/test_api_comprehensive.py

# Test against a specific URL
python tests/test_api_comprehensive.py --url https://api.example.com
```

### Unit Tests
```bash
# Run all tests
pytest tests/ -v

# Run specific tests
pytest tests/test_snippets.py -v
pytest tests/test_langchain_tools.py -v
pytest tests/test_mcp_client.py -v

# Run with coverage
pytest --cov=. --cov-report=html tests/
```

For detailed testing documentation, see [tests/testing.md](tests/testing.md)

## Project Structure

```
InsanusChat_Backend/
├── models/                  # Pydantic models
│   ├── schemas.py          # Domain models (User, Agent, Chat, etc.)
│   ├── responses.py        # API response models
│   └── __init__.py         # Model exports
├── routers/                # FastAPI route handlers
│   ├── auth.py            # Authentication endpoints
│   ├── chats.py           # Chat management
│   ├── agents.py          # Agent management
│   └── ...
├── services/              # Business logic layer
│   ├── agent_service.py   # Agent execution with LangChain
│   ├── mcp_client.py      # MCP server integration
│   └── snippet_runner.py  # Code snippet execution
├── cli/                   # Command-line tools
│   └── chat_cli.py        # Interactive chat CLI
├── tests/                 # Test suite
│   ├── test_api_comprehensive.py
│   ├── test_snippets.py
│   └── testing.md         # Testing documentation
├── docs/                  # Documentation
│   ├── REFACTORING.md
│   ├── PROJECT_SUMMARY.md
│   └── ...
├── examples/              # Example implementations
│   └── mcp_servers/       # Example MCP servers
├── backend.py             # Main application entry point
├── database.py            # MongoDB connection
├── models.py              # Legacy models (for backward compatibility)
└── requirements.txt       # Python dependencies
```

## Architecture

### Core Components

- **FastAPI Backend**: RESTful API and WebSocket server for real-time communication
- **MongoDB**: Document database for users, chats, messages, and agents
- **LangChain**: Framework for AI agent orchestration and tool integration
- **MCP Servers**: External tool servers following Model Context Protocol
- **Code Execution**: Sandboxed Python/JavaScript snippet runner

### Key Features

1. **Branching Conversations**: Tree-based message structure allowing multiple conversation paths
2. **Agent System**: Customizable AI agents with configurable prompts and tool access
3. **Tool Integration**: Extensible tool system via MCP servers and code snippets
4. **Security**: JWT authentication, encrypted API keys, secure credential management
5. **Real-time**: WebSocket support for live chat updates

For architectural details, see [docs/REFACTORING.md](docs/REFACTORING.md)

## Examples

### MCP Server Example

See `examples/mcp_servers/calculator_server.py` for a complete MCP server implementation.

Run the example:
```bash
python examples/mcp_servers/calculator_server.py
```

### Creating an Agent

```python
import httpx

# Login and get token
response = httpx.post("http://localhost:8000/auth/login", 
    data={"username": "user@example.com", "password": "password"})
token = response.json()["data"]["access_token"]

# Create an agent
response = httpx.post("http://localhost:8000/agents",
    json={
        "name": "Math Helper",
        "description": "Agent for mathematical calculations",
        "system_prompt": ["You are a helpful math assistant."]
    },
    headers={"Authorization": f"Bearer {token}"})

agent = response.json()["data"]
print(f"Created agent: {agent['name']}")
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Documentation

- **API Documentation**: See `docs/docs API y WEBSOCKET.md`
- **Testing Guide**: See `tests/testing.md`
- **Project Summary**: See `docs/PROJECT_SUMMARY.md`
- **Quick Start Guide**: See `docs/QUICKSTART_TESTING.md`
- **Security Advisory**: See `docs/SECURITY_ADVISORY.md`
- **Refactoring Details**: See `docs/REFACTORING.md`

## Support

For issues, questions, or contributions, please open an issue on GitHub.

## Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- Powered by [LangChain](https://python.langchain.com/)
- Database by [MongoDB](https://www.mongodb.com/)
- Inspired by the [Model Context Protocol](https://modelcontextprotocol.io/)