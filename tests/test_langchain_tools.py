"""
Tests for LangChain tools integration.
"""
import pytest
from services.langchain_tools import SnippetTool, MCPTool


@pytest.mark.asyncio
async def test_snippet_tool_creation():
    """Test creating a SnippetTool."""
    tool = SnippetTool(
        name="test_snippet",
        description="Test snippet tool",
        snippet_id="123",
        language="python",
        code="return 'test'"
    )
    
    assert tool.name == "test_snippet"
    assert tool.description == "Test snippet tool"
    assert tool.language == "python"


@pytest.mark.asyncio
async def test_snippet_tool_execution():
    """Test executing a SnippetTool."""
    tool = SnippetTool(
        name="hello_world",
        description="Returns hello world",
        snippet_id="123",
        language="python",
        code="return 'Hello, World!'"
    )
    
    result = await tool._arun()
    assert "Hello, World!" in result


@pytest.mark.asyncio
async def test_snippet_tool_with_input():
    """Test executing a SnippetTool with input."""
    tool = SnippetTool(
        name="echo",
        description="Echoes input",
        snippet_id="123",
        language="python",
        code="""
import json
if inp:
    return f"Echo: {inp}"
return "No input"
"""
    )
    
    result = await tool._arun(input_data='{"test": "value"}')
    assert "test" in result or "value" in result
