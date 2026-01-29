# Example MCP Servers

This directory contains example MCP servers for testing InsanusChat integrations.

## Calculator Server

A simple calculator MCP server providing basic arithmetic operations.

### Usage

```bash
python3 calculator_server.py
```

### Available Tools

- `add` - Add two numbers
- `subtract` - Subtract two numbers  
- `multiply` - Multiply two numbers
- `divide` - Divide two numbers

### Testing with InsanusChat

1. Register the MCP server in the user's MCPs:

```python
mcp_entry = {
    "name": "Calculator",
    "transport": "stdio",
    "local_script_path": "/path/to/calculator_server.py",
    "command": "python3",
    "args": ["/path/to/calculator_server.py"]
}
```

2. Add the MCP ID to an agent's `mcp_ids` list

3. The agent will automatically load and use the calculator tools
