# Quick Start Guide - API Testing Script

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install httpx websockets
```

### 2. Start the Backend Server

```bash
# In a separate terminal
uvicorn backend:app --reload
```

### 3. Run the Testing Script

```bash
# Interactive mode
python test_api_comprehensive.py

# Or run all tests at once
python test_api_comprehensive.py --command all
```

## 📋 Common Workflows

### First Time Setup & Full Test

```bash
# Start in interactive mode
python test_api_comprehensive.py

# Then run these commands in order:
> register    # Creates a test user and logs in
> agents      # Tests agent CRUD
> apikeys     # Tests API key CRUD
> mcps        # Tests MCP CRUD
> snippets    # Tests snippet CRUD
> chats       # Tests chat operations
> websocket   # Tests real-time WebSocket
> quit
```

### Quick Full Test

```bash
# Run all tests automatically
python test_api_comprehensive.py --command all
```

### Test Specific Feature

```bash
# Test agents only
python test_api_comprehensive.py --command agents

# Test WebSocket only
python test_api_comprehensive.py --command websocket
```

### Test Against Remote Server

```bash
python test_api_comprehensive.py --url https://your-api-server.com
```

## 🎯 Interactive Commands Cheat Sheet

| Command | What it does |
|---------|--------------|
| `help` | Show all commands |
| `status` | Check authentication status |
| `register` | Create new test user |
| `login` | Login with credentials |
| `profile` | Get user info |
| `agents` | Test agents (C.R.U.D) |
| `apikeys` | Test API keys (C.R.U.D) |
| `mcps` | Test MCPs (C.R.U.D) |
| `snippets` | Test snippets (C.R.U.D) |
| `chats` | Test chats |
| `websocket` | Test WebSocket |
| `all` | Run all tests |
| `quit` | Exit |

## 🎨 Output Color Guide

- 🟢 **Green** = Success
- 🔴 **Red** = Error
- 🟡 **Yellow** = Warning
- 🔵 **Blue** = Info/Data

## 🔧 Troubleshooting

### "Connection refused"
```bash
# Make sure backend is running:
uvicorn backend:app --reload
```

### "Not authenticated"
```bash
# In interactive mode, run:
> register
# or
> login
```

### "ModuleNotFoundError: websockets"
```bash
pip install websockets
```

## 📝 Example Session

```
$ python test_api_comprehensive.py

> register
✓ User registered successfully!
✓ Token saved: eyJhbGc...

> agents
✓ Agent created!
✓ Agents listed! Count: 1
✓ Agent updated!
✓ Agent deleted!

> chats
✓ Chat created!
✓ Chats listed! Count: 1
✓ Messages retrieved! Count: 2

> websocket
✓ WebSocket connected!
✓ Received initial message:
✓ Message sent!
✓ WebSocket test completed!

> quit
ℹ Goodbye! 👋
```

## 📚 Full Documentation

See [TEST_API_README.md](TEST_API_README.md) for complete documentation.
