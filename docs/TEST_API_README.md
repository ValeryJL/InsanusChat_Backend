# InsanusChat Backend API - Comprehensive Testing Script

## Overview

`test_api_comprehensive.py` is a comprehensive, interactive testing script for the InsanusChat Backend API. It provides full coverage of all API endpoints including authentication, CRUD operations, and real-time WebSocket communication.

## Features

✅ **Authentication Testing**
- User registration
- User login
- Profile retrieval

✅ **CRUD Operations**
- **Agents**: Create, List, Update, Delete
- **API Keys**: Create, List, Update, Delete
- **MCPs**: Create, List, Update, Delete
- **Code Snippets**: Create, List, Update, Delete
- **Chats**: Create, List, Get Messages

✅ **Real-time Communication**
- WebSocket connection testing
- Message sending/receiving
- Connection management

✅ **User Experience**
- Interactive command-line interface
- Colored output for better readability
- Automatic token management
- Realistic test data generation
- Detailed error handling and logging

## Installation

### Prerequisites

Ensure you have Python 3.8+ installed and the following dependencies:

```bash
pip install httpx websockets
```

Or install all project dependencies:

```bash
pip install -r requirements.txt
```

### Make Script Executable

```bash
chmod +x test_api_comprehensive.py
```

## Usage

### Interactive Mode (Default)

Run the script to enter interactive mode:

```bash
python test_api_comprehensive.py
```

Or with a custom URL:

```bash
python test_api_comprehensive.py --url http://localhost:8000
```

### Command-Line Mode

Run a specific test and exit:

```bash
# Run all tests
python test_api_comprehensive.py --command all

# Test authentication
python test_api_comprehensive.py --command register
python test_api_comprehensive.py --command login

# Test specific operations
python test_api_comprehensive.py --command agents
python test_api_comprehensive.py --command apikeys
python test_api_comprehensive.py --command mcps
python test_api_comprehensive.py --command snippets
python test_api_comprehensive.py --command chats
python test_api_comprehensive.py --command websocket
```

## Interactive Commands

Once in interactive mode, you can use the following commands:

### Authentication Commands

| Command | Description |
|---------|-------------|
| `register` | Register a new test user |
| `login` | Login with credentials |
| `profile` | Get current user profile |

### CRUD Operations

| Command | Description |
|---------|-------------|
| `agents` | Test all agent operations |
| `apikeys` | Test all API key operations |
| `mcps` | Test all MCP operations |
| `snippets` | Test all code snippet operations |
| `chats` | Test chat operations |

### Real-time Testing

| Command | Description |
|---------|-------------|
| `websocket` | Test WebSocket connection and messaging |

### Utility Commands

| Command | Description |
|---------|-------------|
| `health` | Test API health endpoint |
| `all` | Run all tests sequentially |
| `status` | Show current authentication status |
| `help` | Show available commands |
| `quit` / `exit` | Exit the script |

## Examples

### Example Session

```bash
$ python test_api_comprehensive.py

============================================================
    InsanusChat Backend API Tester - Interactive Mode     
============================================================

ℹ Type 'help' for available commands, 'quit' to exit

============================================================
                  Testing Health Endpoint                   
============================================================

✓ API is running: {'message': 'InsanusChat Backend is running!'}

> register

============================================================
                    User Registration                       
============================================================

ℹ Registering user: test_user_20250109_143052@insanustest.com
✓ User registered successfully!
{
  "message": "Usuario registrado exitosamente",
  "data": {
    "access_token": "eyJhbGc...",
    "user_id": "678f9c3d4e5a6b7c8d9e0f1a"
  }
}
✓ Token saved: eyJhbGc...

> agents

============================================================
                 Testing Agent Operations                   
============================================================

ℹ Creating agent...
✓ Agent created!
{
  "message": "Agent created successfully",
  "data": {
    "_id": "678f9c3e4e5a6b7c8d9e0f1b",
    "name": "Test Agent 14:30:54",
    "description": "A test agent for API testing",
    ...
  }
}

ℹ Listing agents...
✓ Agents listed! Count: 1
...

> websocket

============================================================
              Testing WebSocket Connection                  
============================================================

ℹ Connecting to WebSocket: ws://localhost:8000/api/v1/chats/ws?chat_id=...
✓ WebSocket connected!
ℹ Waiting for initial history...
✓ Received initial message:
{
  "init": {
    "chat": [...],
    ...
  }
}
ℹ Sending test message...
✓ Message sent!
...

> quit
ℹ Goodbye! 👋
```

### Running All Tests

```bash
$ python test_api_comprehensive.py --command all

============================================================
                    Running All Tests                       
============================================================

ℹ Running: Health Check
...

ℹ Running: Register User
...

ℹ Running: Agents
...

============================================================
                     Test Summary                           
============================================================

✓ Health Check: PASSED
✓ Register User: PASSED
✓ User Profile: PASSED
✓ Agents: PASSED
✓ API Keys: PASSED
✓ MCPs: PASSED
✓ Snippets: PASSED
✓ Chats: PASSED
✓ WebSocket: PASSED

ℹ Total: 9/9 tests passed

✓ 🎉 All tests passed!
```

## Test Data

The script automatically generates realistic test data:

- **Email**: `test_user_<timestamp>@insanustest.com`
- **Password**: `TestPassword123!`
- **Display Name**: `Test User <time>`
- **Agent Name**: `Test Agent <time>`
- **API Key Label**: `Test OpenAI Key <time>`
- **MCP Name**: `Test MCP <time>`
- **Snippet Name**: `test_function_<timestamp>`
- **Chat Title**: `Test Chat <time>`

## Authentication

The script maintains authentication state automatically:

1. Register or login to get an access token
2. Token is stored and included in all subsequent requests
3. Use `status` command to check authentication status
4. Token persists throughout the session

## Error Handling

The script includes comprehensive error handling:

- ✓ Green: Successful operations
- ✗ Red: Failed operations
- ⚠ Yellow: Warnings
- ℹ Cyan: Information messages

All HTTP responses are displayed with status codes and JSON payloads for debugging.

## WebSocket Testing

The WebSocket test includes:

1. Connection establishment with authentication
2. Receiving initial chat history
3. Sending test messages
4. Receiving responses from the server
5. Proper connection cleanup

## Configuration

### Base URL

Default: `http://localhost:8000`

Change via command-line:
```bash
python test_api_comprehensive.py --url https://api.insanuschat.com
```

### Timeouts

HTTP requests: 30 seconds
WebSocket messages: 5 seconds (configurable in code)

## Troubleshooting

### Connection Refused

```
✗ Failed to connect to API: [Errno 111] Connection refused
```

**Solution**: Ensure the backend server is running:
```bash
uvicorn backend:app --reload
```

### Authentication Failed

```
✗ Not authenticated. Please login first.
```

**Solution**: Run `register` or `login` command first.

### WebSocket Connection Failed

```
✗ WebSocket error: [...]
```

**Solution**: 
- Verify the backend server supports WebSocket
- Check if authentication token is valid
- Ensure you have created a chat first

### Import Error: websockets

```
ModuleNotFoundError: No module named 'websockets'
```

**Solution**: Install websockets library:
```bash
pip install websockets
```

## Development

### Adding New Tests

To add a new test function:

1. Create an async method in the `APITester` class:
```python
async def test_new_feature(self):
    self.print_header("Testing New Feature")
    # Your test code here
```

2. Add it to the command map in `interactive_mode`:
```python
command_map = {
    # ...
    'newfeature': self.test_new_feature,
}
```

3. Update the help text in `print_help()`.

### Customizing Output

Modify color constants in the `Colors` class:
```python
class Colors:
    OKGREEN = '\033[92m'  # Green
    FAIL = '\033[91m'     # Red
    # ...
```

## License

GPL 3.0 - See LICENSE file for details.

## Support

For issues or questions:
- Email: valejlorda@insanustech.com.ar
- GitHub: [InsanusChat Backend Repository]

## Contributors

InsanusTech Team
