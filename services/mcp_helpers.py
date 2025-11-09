from typing import Any, Dict, Optional, Union
import os
from datetime import datetime

from pydantic import ValidationError

from models import MCPEntryModel


def validate_mcp_entry(data: Union[Dict[str, Any], MCPEntryModel]) -> MCPEntryModel:
    """Validate and normalize an MCP entry.

    Accepts a dict or MCPEntryModel and returns a validated MCPEntryModel instance.
    Raises ValueError/ValidationError on invalid data.
    """
    if isinstance(data, MCPEntryModel):
        return data

    try:
        # pydantic v2 API
        m = MCPEntryModel.model_validate(data)
    except AttributeError:
        # fallback for older pydantic versions
        try:
            m = MCPEntryModel.parse_obj(data)
        except Exception as e:
            raise ValidationError(e)
    return m


def build_connect_params(mcp_entry: Union[Dict[str, Any], MCPEntryModel]) -> Dict[str, Optional[object]]:
    """Build parameters suitable for MCPClient.connect_to_server.

    Returns a dict with keys:
      - server_script_path: str (may be empty when command+args are provided)
      - command: Optional[str]
      - args: Optional[list]
      - env: Optional[dict]
      - workdir: Optional[str]

    Raises ValueError when required fields for the chosen transport are missing.
    """
    m = validate_mcp_entry(mcp_entry)

    command = None
    args = None
    env = dict(m.env or {})
    workdir = m.working_dir

    if m.transport == 'stdio':
        # Prefer local_script_path when available (allow connect_to_server to infer command)
        if m.local_script_path:
            server_script_path = m.local_script_path
            # If command was explicitly provided, pass it through (useful to override inference)
            command = m.command
            args = m.args or None
        elif m.command:
            # No local script -> require explicit command+args
            server_script_path = ""
            command = m.command
            args = m.args or []
        else:
            raise ValueError("MCPEntry transport 'stdio' requires 'local_script_path' or explicit 'command' + 'args'")

    elif m.transport in ('http', 'sse', 'websocket'):
        if not m.endpoint:
            raise ValueError(f"MCPEntry transport '{m.transport}' requires an 'endpoint' field")
        # For network transports we pass endpoint as server_script_path so higher-level
        # callers can decide how to handle it. MCPClient.connect_to_server in this
        # repo currently expects a local script path or command; callers should
        # implement a different transport handler for network transports.
        server_script_path = m.endpoint
        command = None
        args = None
    else:
        raise ValueError(f"Unsupported transport: {m.transport}")

    # Basic sanity checks
    if server_script_path and m.transport == 'stdio' and m.local_script_path:
        # If a local path was given, optionally check existence and warn (do not raise by default)
        try:
            if not os.path.exists(m.local_script_path):
                # keep behavior non-fatal here; caller may run in different environment
                pass
        except Exception:
            pass

    return {
        "server_script_path": server_script_path,
        "command": command,
        "args": args,
        "env": env,
        "workdir": workdir,
        "timeout_seconds": m.timeout_seconds,
        "transport": m.transport,
        "ssl": m.ssl,
        "status": m.status,
        "last_connected_at": m.last_connected_at,
    }


def build_connect_and_run_params(mcp_entry: Union[Dict[str, Any], MCPEntryModel]) -> Dict[str, Any]:
    """Convenience wrapper returning only the subset commonly passed to connect_to_server.

    Returns: { 'server_script_path', 'command', 'args', 'env' }
    """
    params = build_connect_params(mcp_entry)
    return {
        "server_script_path": params.get("server_script_path"),
        "command": params.get("command"),
        "args": params.get("args"),
        "env": params.get("env"),
    }
