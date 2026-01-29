#!/usr/bin/env python3
"""
Example MCP Server - Calculator

This is a simple MCP server that provides basic calculator operations.
It can be used for testing the MCP integration in InsanusChat.

Usage:
    python3 calculator_server.py
"""
import asyncio
import sys
from typing import Any

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("Error: MCP package not installed. Install with: pip install mcp", file=sys.stderr)
    sys.exit(1)


# Create the MCP server instance
app = Server("calculator")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available calculator tools."""
    return [
        Tool(
            name="add",
            description="Add two numbers together",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"}
                },
                "required": ["a", "b"]
            }
        ),
        Tool(
            name="subtract",
            description="Subtract second number from first number",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"}
                },
                "required": ["a", "b"]
            }
        ),
        Tool(
            name="multiply",
            description="Multiply two numbers",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"}
                },
                "required": ["a", "b"]
            }
        ),
        Tool(
            name="divide",
            description="Divide first number by second number",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "Numerator"},
                    "b": {"type": "number", "description": "Denominator"}
                },
                "required": ["a", "b"]
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute a calculator tool."""
    a = float(arguments.get("a", 0))
    b = float(arguments.get("b", 0))
    
    if name == "add":
        result = a + b
        return [TextContent(type="text", text=f"Result: {result}")]
    
    elif name == "subtract":
        result = a - b
        return [TextContent(type="text", text=f"Result: {result}")]
    
    elif name == "multiply":
        result = a * b
        return [TextContent(type="text", text=f"Result: {result}")]
    
    elif name == "divide":
        if b == 0:
            return [TextContent(type="text", text="Error: Division by zero")]
        result = a / b
        return [TextContent(type="text", text=f"Result: {result}")]
    
    else:
        return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
