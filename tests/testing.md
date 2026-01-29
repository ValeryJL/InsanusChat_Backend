# Testing Guide for InsanusChat Backend

This document provides comprehensive information about testing the InsanusChat Backend API.

## Testing Tools

### 1. Comprehensive Test Script (`test_api_comprehensive.py`)

An interactive testing script that covers all API endpoints.

**Location:** `tests/test_api_comprehensive.py`

**Features:**
- Interactive command-line interface
- Tests all endpoints (auth, agents, API keys, MCPs, snippets, chats, WebSocket)
- Color-coded output for better readability
- Session management with token persistence
- Detailed response logging

**Usage:**
```bash
# Run with default URL (localhost:8000)
python tests/test_api_comprehensive.py

# Run with custom URL
python tests/test_api_comprehensive.py --url https://api.example.com
```

**Available Commands:**
- `register` - Register a new user
- `login` - Login with credentials
- `profile` - Get current user profile
- `agents` - Test all agent operations (create, list, update, delete)
- `apikeys` - Test all API key operations
- `mcps` - Test all MCP operations
- `snippets` - Test all snippet operations
- `chats` - Test all chat operations
- `websocket` - Test WebSocket connection
- `all` - Run all tests sequentially
- `quit/exit` - Exit the script

### 2. Interactive Chat CLI (`cli/chat_cli.py`)

A user-friendly CLI for managing chats and agents in production or development.

**Location:** `cli/chat_cli.py`

**Features:**
- User authentication
- Chat management (create, list, select, delete)
- Message sending and history viewing
- Agent management (create, list, delete)
- Colorful interactive interface
- Real-time API interaction

**Usage:**
```bash
# Run with default URL
python cli/chat_cli.py

# Run with custom URL
python cli/chat_cli.py --url https://api.example.com
```

**Quick Start:**
```bash
> register          # Create an account
> login             # Login
> chat new          # Create a chat
> send Hello!       # Send a message
> history           # View chat history
> agents            # List agents
> agent new         # Create an agent
```

### 3. Unit Tests

**Location:** `tests/`

**Available Tests:**
- `test_langchain_tools.py` - Tests for LangChain tool integration
- `test_mcp_client.py` - Tests for MCP client functionality
- `test_snippets.py` - Tests for code snippet operations

**Running Unit Tests:**
```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_snippets.py

# Run with verbose output
pytest -v tests/

# Run with coverage
pytest --cov=. tests/
```

## Test Scenarios

### Authentication Flow
1. Register a new user with email and password
2. Login to obtain JWT token
3. Access protected endpoints with token
4. Get user profile information

### Chat Operations
1. Create a new chat
2. List all user chats
3. Select a chat
4. Send messages to the chat
5. View chat history
6. Delete a chat

### Agent Management
1. Create an agent with name and description
2. Configure agent system prompt
3. List all user agents
4. Update agent configuration
5. Delete an agent

### API Key Management
1. Add API keys for AI providers (OpenAI, Gemini, Anthropic)
2. List all API keys
3. Update API key labels
4. Delete API keys

### MCP Operations
1. Register MCP servers
2. Configure MCP transport (stdio, http, sse, websocket)
3. Test MCP connectivity
4. List and manage MCP entries

### Code Snippets
1. Create code snippets (Python/JavaScript)
2. List user snippets
3. Update snippet code
4. Delete snippets

## Development Workflow

### 1. Local Testing
```bash
# Start the backend server
python backend.py

# In another terminal, run the test script
python tests/test_api_comprehensive.py

# Or use the interactive CLI
python cli/chat_cli.py
```

### 2. Automated Testing
```bash
# Run all unit tests
pytest tests/

# Run tests with coverage report
pytest --cov=. --cov-report=html tests/

# View coverage report
open htmlcov/index.html
```

### 3. Integration Testing
```bash
# Test complete user workflows
python tests/test_api_comprehensive.py
# Then use the 'all' command to run full test suite
```

## API Endpoints Reference

### Authentication
- `POST /auth/register` - Register new user
- `POST /auth/login` - Login and get JWT token
- `GET /auth/profile` - Get current user profile

### Chats
- `GET /chats` - List all user chats
- `POST /chats` - Create a new chat
- `GET /chats/{chat_id}` - Get specific chat
- `DELETE /chats/{chat_id}` - Delete a chat
- `GET /chats/{chat_id}/messages` - Get chat messages
- `POST /chats/{chat_id}/messages` - Send a message

### Agents
- `GET /agents` - List all user agents
- `POST /agents` - Create a new agent
- `GET /agents/{agent_id}` - Get specific agent
- `PUT /agents/{agent_id}` - Update an agent
- `DELETE /agents/{agent_id}` - Delete an agent

### API Keys
- `GET /api-keys` - List all API keys
- `POST /api-keys` - Add a new API key
- `PUT /api-keys/{key_id}` - Update an API key
- `DELETE /api-keys/{key_id}` - Delete an API key

### MCPs
- `GET /mcps` - List all MCP entries
- `POST /mcps` - Register a new MCP
- `GET /mcps/{mcp_id}` - Get specific MCP
- `PUT /mcps/{mcp_id}` - Update an MCP
- `DELETE /mcps/{mcp_id}` - Delete an MCP

### Code Snippets
- `GET /snippets` - List all snippets
- `POST /snippets` - Create a new snippet
- `GET /snippets/{snippet_id}` - Get specific snippet
- `PUT /snippets/{snippet_id}` - Update a snippet
- `DELETE /snippets/{snippet_id}` - Delete a snippet

### WebSocket
- `WS /ws/chat/{chat_id}` - WebSocket connection for real-time chat

## Troubleshooting

### Common Issues

**1. Connection Refused**
- Ensure the backend server is running
- Check the URL and port (default: http://localhost:8000)
- Verify firewall settings

**2. Authentication Errors**
- Ensure you're logged in before accessing protected endpoints
- Check that the JWT token is valid and not expired
- Verify email and password are correct

**3. Database Errors**
- Ensure MongoDB is running
- Check database connection string in configuration
- Verify user has proper permissions

**4. WebSocket Connection Issues**
- Ensure WebSocket endpoint is correct
- Check for proxy or firewall blocking WebSocket connections
- Verify JWT token is included in connection

## Best Practices

1. **Always test authentication first** - Most endpoints require authentication
2. **Use meaningful test data** - Create descriptive names for chats, agents, etc.
3. **Clean up after testing** - Delete test data to avoid database clutter
4. **Test error cases** - Try invalid inputs to ensure proper error handling
5. **Monitor logs** - Check backend logs for detailed error messages
6. **Use version control** - Track changes to test scripts and configurations

## Contributing

When adding new features:
1. Add corresponding tests to `tests/`
2. Update this documentation with new test scenarios
3. Add new commands to interactive scripts if applicable
4. Ensure all existing tests still pass

## Resources

- **API Documentation:** See `docs/API.md`
- **WebSocket Documentation:** See `docs/WEBSOCKET.md`
- **Project Summary:** See `PROJECT_SUMMARY.md`
- **Quick Start Guide:** See `QUICKSTART_TESTING.md`
