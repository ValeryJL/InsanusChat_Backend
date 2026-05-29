#!/usr/bin/env python3
"""
Servidor MCP Local de Ejemplo — Calculadora y Utilidades de Sistema (InsanusChat).
Puede conectarse mediante transporte stdio para verificar llamadas a herramientas MCP.
"""
import asyncio
import datetime
import math
import sys
from typing import Any

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("Error: paquete 'mcp' no instalado. Ejecute: pip install mcp", file=sys.stderr)
    sys.exit(1)

app = Server("insanus-calculator")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="add",
            description="Suma dos números (a + b)",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "Primer número"},
                    "b": {"type": "number", "description": "Segundo número"},
                },
                "required": ["a", "b"],
            },
        ),
        Tool(
            name="subtract",
            description="Resta dos números (a - b)",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "Minuendo"},
                    "b": {"type": "number", "description": "Sustraendo"},
                },
                "required": ["a", "b"],
            },
        ),
        Tool(
            name="multiply",
            description="Multiplica dos números (a * b)",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "Primer factor"},
                    "b": {"type": "number", "description": "Segundo factor"},
                },
                "required": ["a", "b"],
            },
        ),
        Tool(
            name="divide",
            description="Divide dos números (a / b)",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "Numerador"},
                    "b": {"type": "number", "description": "Denominador"},
                },
                "required": ["a", "b"],
            },
        ),
        Tool(
            name="power_and_sqrt",
            description="Calcula potencia y raíz cuadrada de un número",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "number", "description": "Número base"},
                    "exponent": {"type": "number", "description": "Exponente (por defecto 2)"},
                },
                "required": ["x"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name in ("add", "subtract", "multiply", "divide"):
        a = float(arguments.get("a", 0))
        b = float(arguments.get("b", 0))
        if name == "add":
            return [TextContent(type="text", text=f"Result: {a + b}")]
        if name == "subtract":
            return [TextContent(type="text", text=f"Result: {a - b}")]
        if name == "multiply":
            return [TextContent(type="text", text=f"Result: {a * b}")]
        if name == "divide":
            if b == 0:
                return [TextContent(type="text", text="Error: Division by zero")]
            return [TextContent(type="text", text=f"Result: {a / b}")]

    if name == "power_and_sqrt":
        x = float(arguments.get("x", 0))
        exp = float(arguments.get("exponent", 2))
        sq = math.sqrt(x) if x >= 0 else "NaN (negative)"
        return [TextContent(type="text", text=f"Result: {x}^{exp} = {math.pow(x, exp)}, sqrt({x}) = {sq}")]

    return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
