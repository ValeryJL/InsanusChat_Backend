# InsanusChat Backend - Refactoring Documentation

## Recent Improvements (2026-01)

### LangChain Integration

The agent execution system has been refactored to leverage LangChain more extensively:

#### New Features

1. **LangChain-based Tool System** (`services/langchain_tools.py`)
   - MCP servers are now wrapped as LangChain `BaseTool` instances
   - Code snippets are wrapped as LangChain tools
   - Better integration with LangChain's agent framework
   - Improved error handling and logging

2. **Improved Agent Execution** (`services/agents.py`)
   - Uses LangChain's message history system
   - Better tool calling loop with LangChain's built-in patterns
   - System prompt builder with template support
   - Cleaner separation of concerns

3. **Enhanced MCP Client** (`services/mcp_client.py`)
   - Better async context manager support
   - Connection state tracking
   - Improved error messages and logging
   - `get_tools()` convenience method

4. **Snippet Execution Improvements** (`services/snippets.py`)
   - Enhanced security documentation
   - Empty code validation
   - Better timeout handling

### Testing

New test suite added in `tests/`:
- `test_snippets.py` - Tests for code snippet execution
- `test_langchain_tools.py` - Tests for LangChain tool wrappers
- `test_mcp_client.py` - Tests for MCP client

Run tests with:
```bash
python3 -m pytest tests/ -v
```

### Setup Instructions

#### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

Key new dependencies:
- `langchain>=0.3.0` - LangChain framework
- `langchain-core>=0.3.0` - LangChain core components
- `langchain-google-genai>=2.0.0` - Gemini integration

#### 2. Set Up Local MongoDB

Use the provided setup script:
```bash
./setup_local_mongodb.sh
```

Or manually with Docker:
```bash
docker run -d \
  --name insanuschat-mongodb \
  -p 27017:27017 \
  -v $(pwd)/mongodb_data:/data/db \
  -e MONGO_INITDB_ROOT_USERNAME=admin \
  -e MONGO_INITDB_ROOT_PASSWORD=insanus_admin_pass \
  mongo:7.0
```

Then add to your `.env`:
```
MONGO_URI="mongodb://admin:insanus_admin_pass@localhost:27017/insanus_chat?authSource=admin"
```

#### 3. Generate X.509 Certificate

```bash
cd secrets
./create-cert.sh
```

This creates:
- `mongodb-cert.pem` - Client certificate (for MongoDB authentication)
- `mongodb-ca.pem` - Certificate Authority
- `mongodb-key.pem` - Private key

Add to `.env`:
```
MONGO_X509_CERT_PATH="./secrets/mongodb-cert.pem"
```

### Architecture Overview

#### Agent Execution Flow

1. **Load Context**
   - Retrieve chat, message, user, and agent documents from MongoDB
   - Find user's API keys (Gemini, etc.)

2. **Build Tools**
   - `create_mcp_tools()` - Wraps MCP servers as LangChain tools
   - `create_snippet_tools()` - Wraps code snippets as LangChain tools

3. **Initialize Model**
   - Create `ChatGoogleGenerativeAI` instance
   - Bind tools to model

4. **Build Message History**
   - Convert database messages to LangChain format
   - Add system prompt
   - Add user message

5. **Execute Agent Loop**
   - Invoke model with messages
   - If tool calls requested, execute them
   - Add tool results to messages
   - Repeat until completion or max iterations

6. **Save Response**
   - Store agent's final response in database

#### Tool Execution

**MCP Tools:**
```python
async with MCPClient() as client:
    await client.connect_to_server(server_script_path="server.py")
    result = await client.call_tool("tool_name", {"arg": "value"})
```

**Snippet Tools:**
```python
snippet = {
    "language": "python",
    "code": "return 'Hello, World!'"
}
result = await execute_snippet(snippet, input_data={"key": "value"})
```

### Security Considerations

#### Code Snippet Execution

Code snippets run in subprocesses with timeouts. For production:
- Consider sandboxed execution (Docker, gVisor, Firecracker)
- Implement resource limits (CPU, memory, disk)
- Add network isolation
- Validate and sanitize inputs

#### Certificate Management

- Never commit certificates to version control
- Use environment-specific certificates
- Rotate certificates regularly
- Store production certificates in secure vault (AWS Secrets Manager, HashiCorp Vault)

### Migration Notes

If you have existing code using the old agent system:

1. The tool execution loop now uses LangChain's `BaseTool` pattern
2. MCP tools are created via `create_mcp_tools()` instead of manual binding
3. Snippet tools are created via `create_snippet_tools()`
4. Message history uses LangChain message types (`HumanMessage`, `AIMessage`, etc.)

### Troubleshooting

**Import Errors:**
```bash
pip install --upgrade langchain langchain-core langchain-google-genai
```

**MongoDB Connection Issues:**
- Verify `MONGO_URI` in `.env`
- Check MongoDB is running: `docker ps` or `systemctl status mongod`
- Test connection: `mongosh "$MONGO_URI"`

**MCP Server Connection:**
- Verify server script path exists
- Check server script has execute permissions
- Review logs in `services/mcp_client.py`

**Snippet Execution Timeouts:**
- Increase timeout parameter in `execute_snippet()`
- Check system resources (CPU, memory)
- Verify Python/Node.js are installed

### Contributing

When adding new features:
1. Add tests in `tests/`
2. Update this documentation
3. Follow existing code patterns
4. Use LangChain tools where possible
5. Add comprehensive error handling and logging

### Future Improvements

- [ ] Connection pooling for MCP clients
- [ ] Caching for frequently used tools
- [ ] Rate limiting for snippet execution
- [ ] Streaming responses for long-running agents
- [ ] Support for additional LLM providers (Anthropic, OpenAI)
- [ ] Enhanced security sandbox for snippet execution
- [ ] Metrics and observability (OpenTelemetry)
