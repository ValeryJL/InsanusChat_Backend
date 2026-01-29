"""
Tests for snippet execution.
"""
import pytest
from services.snippets import execute_snippet


@pytest.mark.asyncio
async def test_execute_python_snippet():
    """Test executing a simple Python snippet."""
    snippet = {
        "language": "python",
        "code": "return 'Hello from Python!'"
    }
    result = await execute_snippet(snippet)
    assert result["success"]
    assert "Hello from Python!" in result.get("stdout", "")


@pytest.mark.asyncio
async def test_execute_javascript_snippet():
    """Test executing a simple JavaScript snippet."""
    snippet = {
        "language": "javascript",
        "code": "return 'Hello from JavaScript!'"
    }
    result = await execute_snippet(snippet)
    assert result["success"]


@pytest.mark.asyncio
async def test_execute_empty_snippet():
    """Test that empty code returns an error."""
    snippet = {
        "language": "python",
        "code": ""
    }
    result = await execute_snippet(snippet)
    assert not result["success"]
    assert result["error"] == "empty_code"


@pytest.mark.asyncio
async def test_execute_snippet_with_input():
    """Test executing snippet with input data."""
    snippet = {
        "language": "python",
        "code": """
if inp:
    return f"Received: {inp.get('message', 'nothing')}"
return "No input"
"""
    }
    result = await execute_snippet(snippet, input_data={"message": "test"})
    assert result["success"]
    assert "test" in result.get("stdout", "")


@pytest.mark.asyncio
async def test_snippet_timeout():
    """Test that snippets timeout appropriately."""
    snippet = {
        "language": "python",
        "code": "import time; time.sleep(20); return 'done'"
    }
    result = await execute_snippet(snippet, timeout=2)
    assert not result["success"]
    assert result["error"] == "timeout"
