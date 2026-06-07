"""
Validación, normalización y protección Anti-SSRF para servidores MCP (HU-07, HU-10).
"""
import ipaddress
import os
import socket
from typing import Any, Dict, Optional, Union
from urllib.parse import urlparse

from pydantic import ValidationError
from models import MCPEntryModel

BLOCKED_METADATA_IPS = {"169.254.169.254", "100.100.100.200", "fd00:ec2::254"}


def validate_endpoint_url(endpoint: str, allow_local: bool = True) -> str:
    """
    Valida que un endpoint HTTP/SSE/WS de MCP tenga un esquema válido y
    protege contra ataques SSRF a endpoints de metadata cloud o redes internas.
    """
    if not endpoint or not isinstance(endpoint, str):
        raise ValueError("El endpoint del servidor MCP es requerido")

    parsed = urlparse(endpoint.strip())
    if parsed.scheme not in ("http", "https", "ws", "wss"):
        raise ValueError(f"Esquema de URL no soportado en endpoint MCP: {parsed.scheme}")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("El endpoint MCP debe incluir un hostname válido")

    if hostname in BLOCKED_METADATA_IPS or hostname.endswith(".internal"):
        raise ValueError("Endpoint bloqueado por política de seguridad Anti-SSRF (Cloud Metadata)")

    # Verificar si es IP literal o resuelve a IP privada/loopback
    try:
        ip_obj = ipaddress.ip_address(hostname)
        if str(ip_obj) in BLOCKED_METADATA_IPS or ip_obj.is_link_local:
            raise ValueError("Endpoint bloqueado por política Anti-SSRF (Link-Local / Metadata)")
        if not allow_local and (ip_obj.is_loopback or ip_obj.is_private):
            raise ValueError("Endpoints MCP hacia redes locales/privadas están deshabilitados por el administrador")
    except ValueError as ve:
        if "Anti-SSRF" in str(ve) or "deshabilitados" in str(ve):
            raise
        # No es una IP literal, es un dominio
        if not allow_local and hostname in ("localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal"):
            raise ValueError("Endpoints MCP hacia localhost están deshabilitados por el administrador")

    return endpoint.strip()


def validate_mcp_entry(data: Union[Dict[str, Any], MCPEntryModel]) -> MCPEntryModel:
    if isinstance(data, MCPEntryModel):
        return data
    return MCPEntryModel.model_validate(data)


def build_connect_params(mcp_entry: Union[Dict[str, Any], MCPEntryModel], allow_local: bool = True) -> Dict[str, Any]:
    """Construye los parámetros de conexión para MCPClient.connect_to_server."""
    m = validate_mcp_entry(mcp_entry)

    command = None
    args = None
    env = dict(m.env or {})
    workdir = m.working_dir

    if m.transport == "stdio":
        if m.local_script_path:
            server_script_path = m.local_script_path
            command = m.command
            args = m.args or None
        elif m.command:
            server_script_path = ""
            command = m.command
            args = m.args or []
        elif m.endpoint and (m.endpoint.endswith(".py") or m.endpoint.endswith(".js")):
            # Fallback amigable si el usuario puso la ruta del script en 'endpoint'
            server_script_path = m.endpoint
            command = m.command
            args = m.args or None
        else:
            raise ValueError("El transporte 'stdio' requiere 'local_script_path' o 'command' + 'args'")

    elif m.transport in ("http", "sse", "websocket"):
        if not m.endpoint:
            raise ValueError(f"El transporte '{m.transport}' requiere un campo 'endpoint' con la URL")
        validate_endpoint_url(m.endpoint, allow_local=allow_local)
        server_script_path = m.endpoint
        command = None
        args = None
    else:
        raise ValueError(f"Transporte MCP no soportado: {m.transport}")

    return {
        "server_script_path": server_script_path,
        "command": command,
        "args": args,
        "env": env,
        "workdir": workdir,
        "timeout_seconds": m.timeout_seconds,
        "transport": m.transport,
        "endpoint": m.endpoint,
        "ssl": m.ssl,
        "status": m.status,
        "last_connected_at": m.last_connected_at,
    }
