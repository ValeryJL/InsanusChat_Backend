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
    
    Usage:
        async with MCPClient() as client:
            await client.connect_to_server(server_script_path="server.py")
            tools = await client.list_tools()
            result = await client.call_tool("tool_name", {"arg": "value"})
    """

    def __init__(self):
        self.session: Optional[Any] = None
        self.exit_stack = AsyncExitStack()
        self._stdio_transport = None
        self.mcp_tools: Dict[str, Any] = {}
        self._connected = False

    async def connect_to_server(self, server_script_path: str, command: Optional[str] = None, args: Optional[list] = None, env: Optional[Dict[str, str]] = None):
        """Connect to an MCP server script via stdio transport.
        
        Args:
            server_script_path: Path to the server script (or command name)
            command: Optional explicit command to run (auto-detected from file extension if not provided)
            args: Optional arguments for the command
            env: Optional environment variables
            
        Raises:
            RuntimeError: If MCP package is not installed or connection fails
        """
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

        try:
            stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
            self._stdio_transport = stdio_transport
            self.stdio, self.write = stdio_transport

            self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
            await self.session.initialize()
            self._connected = True

            # List available tools
            try:
                resp = await self.session.list_tools()
                tools_out = {}
                tools = getattr(resp, 'tools', None) or resp or []
                for t in tools:
                    key = getattr(t, 'name', None) or (t.get('name') if isinstance(t, dict) else None)
                    if key:
                        tools_out[str(key)] = t
                self.mcp_tools = tools_out
                logger.info(f"MCP client connected. Found {len(tools_out)} tools.")
                return resp
            except Exception as e:
                logger.warning(f"MCP client connected but list_tools failed: {e}")
                return None
        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            self._connected = False
            raise RuntimeError(f"MCP connection failed: {e}") from e

    async def list_tools(self):
        """List available tools from the connected MCP server."""
        if self.session is None:
            raise RuntimeError("Not connected to MCP server")
        return await self.session.list_tools()

    async def get_tools(self):
        """Get tools as a list (convenience method)."""
        if not self._connected or not self.mcp_tools:
            resp = await self.list_tools()
            tools = getattr(resp, 'tools', None) or resp or []
            return list(tools)
        return list(self.mcp_tools.values())

    async def call_tool(self, name: str, args: Optional[Dict[str, Any]] = None, timeout: int = 30):
        """Call a tool on the connected MCP server.
        
        Args:
            name: Tool name to call
            args: Arguments to pass to the tool
            timeout: Timeout in seconds (default: 30)
            
        Returns:
            Tool execution result
            
        Raises:
            RuntimeError: If not connected or SDK version mismatch
        """
        if self.session is None:
            raise RuntimeError("Not connected to MCP server")
        
        try:
            if hasattr(self.session, 'call_tool'):
                return await self.session.call_tool(name, args or {}, timeout=timeout)
            if hasattr(self.session, 'callTool'):
                return await self.session.callTool({'name': name, 'arguments': args or {}}, timeout=timeout)
            raise RuntimeError("MCP SDK version mismatch - no call_tool or callTool method")
        except Exception as e:
            logger.error(f"Error calling MCP tool '{name}': {e}")
            raise

    async def close(self):
        """Close the MCP client connection."""
        try:
            await self.exit_stack.aclose()
            self._connected = False
            logger.info("MCP client closed")
        except Exception as e:
            logger.warning(f"Error closing MCP client: {e}")
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
        return False
