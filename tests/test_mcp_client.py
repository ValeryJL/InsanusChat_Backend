"""
Integration tests for MCP client and LangChain integration.
"""
import pytest
import asyncio
from services.mcp_client import MCPClient


@pytest.mark.asyncio
async def test_mcp_client_context_manager():
    """Test that MCPClient can be used as an async context manager."""
    async with MCPClient() as client:
        assert client is not None
        assert not client.is_connected  # Not connected yet


@pytest.mark.asyncio
async def test_mcp_client_close():
    """Test that MCPClient closes properly."""
    client = MCPClient()
    await client.close()
    assert not client.is_connected


# Note: These tests require a running MCP server to be meaningful
# For now, they just test the basic client structure
