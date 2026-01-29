"""
LangChain tool wrappers for MCP servers and code snippets.

This module provides LangChain-compatible tool wrappers for:
- MCP (Model Context Protocol) servers
- Code snippets (Python/JavaScript)

These wrappers allow seamless integration with LangChain's agent framework.
"""
import asyncio
import json
import logging
from typing import Any, Dict, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from services.mcp_client import MCPClient
from services.snippets import execute_snippet

logger = logging.getLogger(__name__)


class MCPToolInput(BaseModel):
    """Input schema for MCP tools - dynamically generated based on tool schema."""
    pass


class MCPTool(BaseTool):
    """LangChain tool wrapper for MCP server tools."""
    
    name: str
    description: str
    mcp_tool_name: str
    connect_params: Dict[str, Any]
    args_schema: Type[BaseModel] = MCPToolInput
    
    class Config:
        arbitrary_types_allowed = True
    
    def _run(self, **kwargs: Any) -> str:
        """Synchronous execution not supported for MCP tools."""
        raise NotImplementedError("MCP tools only support async execution")
    
    async def _arun(self, **kwargs: Any) -> str:
        """Execute the MCP tool asynchronously."""
        try:
            async with MCPClient() as client:
                await client.connect_to_server(**self.connect_params)
                result = await client.call_tool(self.mcp_tool_name, kwargs)
                
                # Extract content from MCP response
                if hasattr(result, 'content'):
                    content = result.content
                    if isinstance(content, list):
                        # Join multiple content items
                        return '\n'.join(str(item) for item in content)
                    return str(content)
                return str(result)
        except Exception as e:
            logger.error(f"Error executing MCP tool {self.mcp_tool_name}: {e}")
            return f"Error: {str(e)}"


class SnippetToolInput(BaseModel):
    """Input schema for snippet tools."""
    input_data: Optional[str] = Field(None, description="Input data for the snippet (JSON string)")


class SnippetTool(BaseTool):
    """LangChain tool wrapper for code snippets."""
    
    name: str
    description: str
    snippet_id: str
    language: str
    code: str
    args_schema: Type[BaseModel] = SnippetToolInput
    
    class Config:
        arbitrary_types_allowed = True
    
    def _run(self, input_data: Optional[str] = None) -> str:
        """Synchronous execution not supported."""
        raise NotImplementedError("Snippet tools only support async execution")
    
    async def _arun(self, input_data: Optional[str] = None) -> str:
        """Execute the code snippet asynchronously."""
        try:
            snippet_dict = {
                "language": self.language,
                "code": self.code
            }
            
            # Parse input_data if provided
            parsed_input = None
            if input_data:
                try:
                    parsed_input = json.loads(input_data)
                except json.JSONDecodeError:
                    parsed_input = input_data
            
            result = await execute_snippet(snippet_dict, input_data=parsed_input)
            
            if result.get("success"):
                output = result.get("stdout") or result.get("result") or "Success (no output)"
                return str(output)
            else:
                error_msg = result.get("error") or "Unknown error"
                stderr = result.get("stderr", "")
                return f"Error: {error_msg}\n{stderr}".strip()
        except Exception as e:
            logger.error(f"Error executing snippet {self.snippet_id}: {e}")
            return f"Error: {str(e)}"


async def create_mcp_tools(user_doc: Dict[str, Any], agent_obj: Dict[str, Any]) -> list[BaseTool]:
    """
    Create LangChain tools from MCP servers configured for an agent.
    
    Args:
        user_doc: User document containing MCP configurations
        agent_obj: Agent document containing MCP IDs to use
        
    Returns:
        List of LangChain-compatible MCP tools
    """
    tools = []
    
    if not (user_doc and agent_obj):
        return tools
    
    from services.mcp_helpers import validate_mcp_entry, build_connect_params
    
    mcps_map = {str(m.get("_id")): m for m in user_doc.get("mcps", []) or []}
    
    for mcp_id in agent_obj.get("mcp_ids", []) or []:
        mcp_id_str = str(mcp_id)
        if mcp_id_str not in mcps_map:
            continue
        
        try:
            mcp_entry = validate_mcp_entry(mcps_map[mcp_id_str])
            connect_params = build_connect_params(mcp_entry)
            
            # Get tools from MCP server
            async with MCPClient() as client:
                await client.connect_to_server(**connect_params)
                server_tools = await client.get_tools()
                
                for server_tool in server_tools:
                    tool_name = f"mcp_{mcp_id_str}_{server_tool.name}"
                    description = server_tool.description or f"MCP tool: {server_tool.name}"
                    
                    # Create dynamic input schema if available
                    input_schema = getattr(server_tool, 'inputSchema', None)
                    
                    tool = MCPTool(
                        name=tool_name,
                        description=description,
                        mcp_tool_name=server_tool.name,
                        connect_params=connect_params
                    )
                    tools.append(tool)
                    logger.info(f"Created MCP tool: {tool_name}")
        except Exception as e:
            logger.warning(f"Error loading MCP tools for {mcp_id_str}: {e}")
    
    return tools


async def create_snippet_tools(user_doc: Dict[str, Any], agent_obj: Dict[str, Any]) -> list[BaseTool]:
    """
    Create LangChain tools from code snippets configured for an agent.
    
    Args:
        user_doc: User document containing snippet configurations
        agent_obj: Agent document containing snippet IDs to use
        
    Returns:
        List of LangChain-compatible snippet tools
    """
    tools = []
    
    if not (user_doc and agent_obj):
        return tools
    
    snippets_map = {str(s.get("_id")): s for s in user_doc.get("code_snippets", []) or user_doc.get("snippets", []) or []}
    
    for snippet_id in agent_obj.get("snippet_ids", []) or []:
        snippet_id_str = str(snippet_id)
        if snippet_id_str not in snippets_map:
            continue
        
        snippet = snippets_map[snippet_id_str]
        tool_name = f"snippet_{snippet_id_str}"
        description = snippet.get("description") or f"Execute {snippet.get('language')} snippet: {snippet.get('name')}"
        
        tool = SnippetTool(
            name=tool_name,
            description=description,
            snippet_id=snippet_id_str,
            language=snippet.get("language", "javascript"),
            code=snippet.get("code", "")
        )
        tools.append(tool)
        logger.info(f"Created snippet tool: {tool_name}")
    
    return tools
