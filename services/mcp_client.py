import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Optional, Any, Dict, List
import sys

from dotenv import load_dotenv


try:
    # modelcontextprotocol python package (official MCP SDK)
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except Exception:
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None

try:
    # anthropic SDK (optional, used in tutorial to query Claude)
    from anthropic import Anthropic
except Exception:
    Anthropic = None

class MCPClient:
    """
    MCP Client for interacting with the MCP server.
    If not installed, the methods will raise informative RuntimeError exceptions.
    """

    def __init__(self):
        self.session: Optional[Any] = None
        self.exit_stack = AsyncExitStack()
        # Load environment variables (e.g., ANTHROPIC_API_KEY) and initialize Anthropic client if available
        try:
            load_dotenv()
        except Exception:
            pass
        self.anthropic = Anthropic() if Anthropic is not None else None
        self._stdio_transport = None
        # mcp tools exposed by a connected server (dict keyed by tool name or id)
        self.mcp_tools: Dict[str, Any] = {}

    async def connect_to_server(self, server_script_path: str, command: Optional[str] = None, args: Optional[list] = None, env: Optional[Dict[str, str]] = None):
        """Connect to an MCP server script via stdio transport.

        server_script_path: local path to a server script (.py or .js) OR a command
        and args may be supplied explicitly.
        """
        if ClientSession is None or stdio_client is None or StdioServerParameters is None:
            raise RuntimeError("mcp package is not installed; install it to use MCP client features")

        is_python = server_script_path.endswith('.py') if server_script_path else False
        is_js = server_script_path.endswith('.js') if server_script_path else False
        if command is None:
            if is_python:
                command = 'python'
                args = [server_script_path]
            elif is_js:
                command = 'node'
                args = [server_script_path]
            else:
                raise ValueError("Server script must be a .py or .js file or provide explicit command/args")

        server_params = StdioServerParameters(command=command, args=list(args or []), env=env)

        # Open stdio transport using the SDK helper
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        # stdio_transport is typically a pair (readable, writable)
        self._stdio_transport = stdio_transport
        self.stdio, self.write = stdio_transport

        # Create MCP ClientSession from the stdio transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))

        # Initialize session handshake
        await self.session.initialize()

        # Populate mcp_tools cache if possible
        try:
            resp = await self.session.list_tools()
            # normalize into dict keyed by tool name when possible
            tools_out = {}
            tools = getattr(resp, 'tools', None) or resp or []
            for t in tools:
                # try common attributes
                key = None
                if hasattr(t, 'name'):
                    key = getattr(t, 'name')
                elif isinstance(t, dict) and t.get('name'):
                    key = t.get('name')
                elif hasattr(t, 'id'):
                    key = str(getattr(t, 'id'))
                elif isinstance(t, dict) and t.get('_id'):
                    key = str(t.get('_id'))
                if not key:
                    continue
                tools_out[str(key)] = t
            self.mcp_tools = tools_out
            return resp
        except Exception:
            logging.exception("MCPClient: list_tools failed after initialize")
            return None

    async def list_tools(self):
        if self.session is None:
            raise RuntimeError("Not connected to MCP server")
        return await self.session.list_tools()

    # Snippet management and local execution helpers were moved to `services.snippets`.
    # MCPClient focuses on the MCP transport/session. Use services.snippets.execute_snippet
    # when you need to execute user-provided code snippets.

    async def call_tool(self, name: str, args: Optional[Dict[str, Any]] = None, timeout: int = 30):
        if self.session is None:
            raise RuntimeError("Not connected to MCP server")
        # The exact call signature depends on the MCP SDK; quickstart shows session.call_tool / callTool
        if hasattr(self.session, 'call_tool'):
            return await self.session.call_tool(name, args or {}, timeout=timeout)
        if hasattr(self.session, 'callTool'):
            return await self.session.callTool({'name': name, 'arguments': args or {}}, timeout=timeout)
        raise RuntimeError("MCP SDK session does not expose a known call_tool API")

    async def close(self):
        await self.exit_stack.aclose()

    async def process_query(self, query: str, max_tokens: int = 1000) -> str:
        """Process a user query using Anthropic (Claude) and available MCP tools.

        This follows the tutorial pattern: send the query + tools to Anthropic, handle any
        tool_use responses by calling the MCP tool, then feed results back to Anthropic
        until a final textual response is produced.
        """
        if self.anthropic is None:
            raise RuntimeError("Anthropic client is not available; install anthropic and set ANTHROPIC_API_KEY")
        if self.session is None:
            raise RuntimeError("Not connected to MCP server")

        # Build messages list (simple form expected by the tutorial)
        messages = [{"role": "user", "content": query}]

        # Get available tools from the MCP server
        resp = await self.session.list_tools()
        tools = getattr(resp, 'tools', None) or resp or []
        available_tools = []
        for t in tools:
            try:
                available_tools.append({
                    "name": getattr(t, 'name', t.get('name') if isinstance(t, dict) else None),
                    "description": getattr(t, 'description', t.get('description') if isinstance(t, dict) else None),
                    "input_schema": getattr(t, 'inputSchema', t.get('inputSchema') if isinstance(t, dict) else None),
                })
            except Exception:
                continue

        # First call to Anthropic
        try:
            ai_resp = self.anthropic.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=max_tokens,
                messages=messages,
                tools=available_tools,
            )
        except Exception as e:
            logging.exception("Anthropic API call failed")
            raise

        final_text = []

        # Handle the response content blocks. The exact shape depends on the SDK version.
        for content in getattr(ai_resp, 'content', ai_resp.get('content', [])):
            # content may be an object with attributes or dict-like
            ctype = getattr(content, 'type', content.get('type') if isinstance(content, dict) else None)
            if ctype == 'text':
                text = getattr(content, 'text', content.get('text') if isinstance(content, dict) else None)
                final_text.append(text)
            elif ctype == 'tool_use':
                tool_name = getattr(content, 'name', content.get('name') if isinstance(content, dict) else None)
                tool_input = getattr(content, 'input', content.get('input') if isinstance(content, dict) else None)
                # Call MCP tool
                try:
                    result = await self.call_tool(tool_name, tool_input or {})
                except Exception as e:
                    result = {"error": str(e)}

                final_text.append(f"[Calling tool {tool_name} with args {tool_input}]")

                # Append tool result to messages and ask Anthropic for follow-up
                messages.append({"role": "assistant", "content": [content]})
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": getattr(content, 'id', content.get('id') if isinstance(content, dict) else None), "content": result}
                    ]
                })

                try:
                    ai_resp = self.anthropic.messages.create(
                        model="claude-3-5-sonnet-20241022",
                        max_tokens=max_tokens,
                        messages=messages,
                        tools=available_tools,
                    )
                except Exception:
                    logging.exception("Anthropic follow-up call failed")
                    continue

                # add next text segment(s)
                for content2 in getattr(ai_resp, 'content', ai_resp.get('content', [])):
                    if getattr(content2, 'type', content2.get('type') if isinstance(content2, dict) else None) == 'text':
                        final_text.append(getattr(content2, 'text', content2.get('text') if isinstance(content2, dict) else None))

        return "\n".join([t for t in final_text if t])

    async def chat_loop(self):
        print("\nMCP Client Started!\nType your queries or 'quit' to exit.")
        while True:
            try:
                query = input("\nQuery: ").strip()
                if query.lower() == 'quit':
                    break
                resp = await self.process_query(query)
                print("\n" + resp)
            except Exception as e:
                print(f"\nError: {e}")


async def main():
    if len(sys.argv) < 2:
        print("Usage: python mcp_client.py <path_to_server_script>")
        sys.exit(1)

    client = MCPClient()
    try:
        await client.connect_to_server(sys.argv[1])
        await client.chat_loop()
    finally:
        await client.close()


if __name__ == '__main__':
    asyncio.run(main())


# Optional convenience function to run a client example (non-blocking)
async def example_connect_and_list(script_path: str):
    c = MCPClient()
    try:
        res = await c.connect_to_server(script_path)
        print('tools:', getattr(res, 'tools', res))
    finally:
        await c.close()
