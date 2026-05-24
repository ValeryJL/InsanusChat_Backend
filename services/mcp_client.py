"""
Cliente MCP Multi-Transporte (stdio, sse, streamable http) con soporte de Context Manager asíncrono (HU-10).
"""
import asyncio
import logging
import sys
from contextlib import AsyncExitStack
from typing import Optional, Any, Dict, List
import httpx

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except Exception:
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None

try:
    from mcp.client.sse import sse_client
except Exception:
    sse_client = None

try:
    from mcp.client.streamable_http import streamablehttp_client
except Exception:
    streamablehttp_client = None

logger = logging.getLogger(__name__)


class MCPClient:
    """
    Cliente MCP compatible con `async with MCPClient() as client:`
    Soporta transporte `stdio`, `sse` y `http` (Streamable HTTP o JSON-RPC directo).
    """

    def __init__(self):
        self.session: Optional[Any] = None
        self.exit_stack = AsyncExitStack()
        self._transport_type: str = "stdio"
        self._http_endpoint: Optional[str] = None
        self.mcp_tools: Dict[str, Any] = {}
        self._connected: bool = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    async def connect_to_server(
        self,
        server_script_path: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[list] = None,
        env: Optional[Dict[str, str]] = None,
        transport: str = "stdio",
        endpoint: Optional[str] = None,
        **kwargs,
    ):
        """Conecta a un servidor MCP por stdio, sse o http e inicializa la sesión."""
        self._transport_type = (transport or "stdio").lower()
        target_url = endpoint or server_script_path

        if self._transport_type == "stdio":
            if ClientSession is None or stdio_client is None or StdioServerParameters is None:
                raise RuntimeError("El paquete 'mcp' no está instalado en el entorno Python")

            is_python = server_script_path.endswith(".py") if server_script_path else False
            is_js = server_script_path.endswith(".js") if server_script_path else False

            if command is None:
                if is_python:
                    command = sys.executable or "python"
                    args = [server_script_path] + list(args or [])
                elif is_js:
                    command = "node"
                    args = [server_script_path] + list(args or [])
                else:
                    command = server_script_path
                    args = list(args or [])
            else:
                if server_script_path and server_script_path not in (args or []):
                    args = [server_script_path] + list(args or [])

            # Combinar env del sistema con env custom del MCP para que encuentre python/node/PATH
            import os
            merged_env = dict(os.environ)
            if env:
                merged_env.update({k: str(v) for k, v in env.items()})

            server_params = StdioServerParameters(command=command, args=list(args or []), env=merged_env)
            stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
            read_stream, write_stream = stdio_transport
            self.session = await self.exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
            await self.session.initialize()
            self._connected = True

        elif self._transport_type == "sse":
            if not target_url:
                raise ValueError("Se requiere endpoint URL para transporte SSE")
            if sse_client is None or ClientSession is None:
                raise RuntimeError("El cliente SSE de MCP no está disponible")
            sse_transport = await self.exit_stack.enter_async_context(sse_client(target_url))
            read_stream, write_stream = sse_transport
            self.session = await self.exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
            await self.session.initialize()
            self._connected = True

        elif self._transport_type == "http":
            if not target_url:
                raise ValueError("Se requiere endpoint URL para transporte HTTP")
            self._http_endpoint = target_url
            if streamablehttp_client is not None and ClientSession is not None:
                try:
                    http_transport = await self.exit_stack.enter_async_context(streamablehttp_client(target_url))
                    read_stream, write_stream = http_transport[0], http_transport[1]
                    self.session = await self.exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
                    await self.session.initialize()
                    self._connected = True
                except Exception as e:
                    logger.debug("Fallback a cliente JSON-RPC HTTP directo para %s: %s", target_url, e)
                    self.session = None
                    self._connected = True
            else:
                self._connected = True
        else:
            raise ValueError(f"Transporte MCP no soportado: {self._transport_type}")

        await self._refresh_tools_cache()
        return self.mcp_tools

    async def _refresh_tools_cache(self):
        try:
            tools_list = await self.get_tools()
            tools_out = {}
            for t in tools_list:
                key = getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else None)
                if key:
                    tools_out[str(key)] = t
            self.mcp_tools = tools_out
        except Exception as e:
            logger.warning("MCPClient: no se pudieron listar las tools al conectar: %s", e)

    async def list_tools(self):
        """Devuelve la respuesta cruda de list_tools de la sesión MCP."""
        if self.session is not None:
            return await self.session.list_tools()
        if self._transport_type == "http" and self._http_endpoint:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    self._http_endpoint,
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                )
                r.raise_for_status()
                data = r.json()
                return data.get("result", {}).get("tools", [])
        raise RuntimeError("No conectado a ningún servidor MCP")

    async def get_tools(self) -> List[Any]:
        """Devuelve siempre una lista normalizada de objetos/dicts Tool."""
        resp = await self.list_tools()
        if hasattr(resp, "tools"):
            return list(resp.tools)
        if isinstance(resp, dict) and "tools" in resp:
            return list(resp["tools"])
        if isinstance(resp, list):
            return resp
        return []

    async def call_tool(self, name: str, args: Optional[Dict[str, Any]] = None, timeout: int = 30):
        if self.session is not None:
            if hasattr(self.session, "call_tool"):
                return await asyncio.wait_for(self.session.call_tool(name, args or {}), timeout=timeout)
            if hasattr(self.session, "callTool"):
                return await asyncio.wait_for(
                    self.session.callTool({"name": name, "arguments": args or {}}),
                    timeout=timeout,
                )
        if self._transport_type == "http" and self._http_endpoint:
            async with httpx.AsyncClient(timeout=float(timeout)) as client:
                r = await client.post(
                    self._http_endpoint,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": args or {}},
                    },
                )
                r.raise_for_status()
                return r.json().get("result", {})
        raise RuntimeError("No conectado a un servidor MCP")

    async def close(self):
        try:
            await self.exit_stack.aclose()
        except Exception as e:
            logger.debug("Error cerrando MCPClient: %s", e)
        finally:
            self._connected = False
            self.session = None
