import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Optional, Any, Dict, List
import sys

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except Exception:
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None

logger = logging.getLogger(__name__)

class MCPClient:
    """
    MCP Client for interacting with an MCP server via stdio.
    """

    def __init__(self):
        self.session: Optional[Any] = None
        self.exit_stack = AsyncExitStack()
        self._stdio_transport = None
        self.mcp_tools: Dict[str, Any] = {}

    async def connect_to_server(self, server_script_path: str, command: Optional[str] = None, args: Optional[list] = None, env: Optional[Dict[str, str]] = None):
        """Connect to an MCP server script via stdio transport."""
        if ClientSession is None or stdio_client is None or StdioServerParameters is None:
            raise RuntimeError("mcp package is not installed")

        is_python = server_script_path.endswith('.py') if server_script_path else False
        is_js = server_script_path.endswith('.js') if server_script_path else False
        
        if command is None:
            if is_python:
                command = sys.executable or 'python3'
                args = [server_script_path]
            elif is_js:
                command = 'node'
                args = [server_script_path]
            else:
                # If neither, assume it is a command itself
                command = server_script_path
                args = args or []

        server_params = StdioServerParameters(command=command, args=list(args or []), env=env)

        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self._stdio_transport = stdio_transport
        self.stdio, self.write = stdio_transport

        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
        await self.session.initialize()

        try:
            resp = await self.session.list_tools()
            tools_out = {}
            tools = getattr(resp, 'tools', None) or resp or []
            for t in tools:
                key = getattr(t, 'name', None) or (t.get('name') if isinstance(t, dict) else None)
                if key:
                    tools_out[str(key)] = t
            self.mcp_tools = tools_out
            return resp
        except Exception:
            logger.exception("MCPClient: list_tools failed")
            return None

    async def list_tools(self):
        if self.session is None:
            raise RuntimeError("Not connected")
        return await self.session.list_tools()

    async def call_tool(self, name: str, args: Optional[Dict[str, Any]] = None, timeout: int = 30):
        if self.session is None:
            raise RuntimeError("Not connected")
        
        if hasattr(self.session, 'call_tool'):
            return await self.session.call_tool(name, args or {}, timeout=timeout)
        if hasattr(self.session, 'callTool'):
            return await self.session.callTool({'name': name, 'arguments': args or {}}, timeout=timeout)
        raise RuntimeError("MCP SDK version mismatch")

    async def close(self):
        await self.exit_stack.aclose()
