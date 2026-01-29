import asyncio
import logging
import os
from datetime import datetime
from typing import List, Optional, Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_core.chat_history import BaseChatMessageHistory, InMemoryChatMessageHistory
from langchain_google_genai import ChatGoogleGenerativeAI

from models import PyObjectId
from database import get_message_collection, get_chat_collection, get_user_collection
from services.langchain_tools import create_mcp_tools, create_snippet_tools

logger = logging.getLogger(__name__)

async def _build_langchain_history(chat_oid, max_messages: int = 15) -> List[Any]:
    """
    Build LangChain-compatible message history from database.
    
    Returns a list of LangChain message objects (HumanMessage, AIMessage, SystemMessage).
    """
    msgs_col = get_message_collection()
    cursor = msgs_col.find({"chat_id": chat_oid}).sort("created_at", -1).limit(max_messages)
    docs = [d async for d in cursor]
    docs.reverse()
    
    messages = []
    for doc in docs:
        role = (doc.get("role") or "user").lower()
        content = doc.get("content") or doc.get("text") or ""
        
        if role in ("assistant", "agent"):
            messages.append(AIMessage(content=content))
        elif role == "system":
            messages.append(SystemMessage(content=content))
        else:  # user or any other role
            messages.append(HumanMessage(content=content))
    
    return messages

async def run_agent(chat_oid, message_id):
    """
    Master Runner for agents using LangChain framework.
    
    This function integrates:
    - Gemini LLM via LangChain
    - MCP Tools (wrapped as LangChain tools)
    - Code Snippets (wrapped as LangChain tools)
    
    The agent uses LangChain's built-in tool calling loop for better reliability.
    """
    msgs_col = get_message_collection()
    chats_col = get_chat_collection()
    users_col = get_user_collection()

    # Load documents
    try:
        chat_doc = await chats_col.find_one({"_id": chat_oid})
        message_doc = await msgs_col.find_one({"_id": message_id})
        if not chat_doc or not message_doc:
            logger.error(f"Chat or message not found: chat_id={chat_oid}, msg_id={message_id}")
            return None
    except Exception as e:
        logger.error(f"Error loading documents: {e}")
        return None

    # Get user and agent
    owner_id = chat_doc.get("owner_id") or chat_doc.get("user_id")
    user_doc = None
    agent_obj = None
    
    if owner_id:
        try:
            if isinstance(owner_id, str):
                owner_id = PyObjectId.parse(owner_id)
            user_doc = await users_col.find_one({"_id": owner_id})
        except Exception as e:
            logger.warning(f"Error loading user: {e}")

    if user_doc:
        raw_agent = chat_doc.get("agent_id")
        for agent in user_doc.get("agents", []) or []:
            if str(agent.get("_id")) == str(raw_agent):
                agent_obj = agent
                break

    # Helper to find API keys
    def _find_api_key(provider_name: str) -> Optional[str]:
        """Find API key for given provider from user's keys."""
        # First, check if agent has a specific API key configured
        if agent_obj and agent_obj.get("api_key_id"):
            agent_api_key_id = str(agent_obj.get("api_key_id"))
            keys = user_doc.get("api_keys", []) if user_doc else []
            for key_entry in keys:
                if not isinstance(key_entry, dict):
                    continue
                if str(key_entry.get("_id", "")) == agent_api_key_id:
                    logger.info(f"Using agent-specific API key: {key_entry.get('provider')}")
                    return key_entry.get("encrypted_key")
        
        # Fall back to finding by provider name
        keys = user_doc.get("api_keys", []) if user_doc else []
        for key_entry in keys:
            if not isinstance(key_entry, dict):
                continue
            provider = str(key_entry.get("provider", "")).lower()
            if provider in (provider_name.lower(), "google", "gemini"):
                return key_entry.get("encrypted_key")
        
        # Last resort: environment variable
        return os.environ.get("GOOGLE_API_KEY")

    gemini_key = _find_api_key("gemini")
    user_text = message_doc.get("content") or ""
    
    # Initialize response
    final_text = ""
    
    if not gemini_key:
        final_text = "Error: No Gemini API key configured"
        logger.error("No Gemini API key found for agent execution")
    else:
        try:
            # 1. Create LangChain tools from MCP servers and snippets
            logger.info("Creating LangChain tools...")
            mcp_tools = await create_mcp_tools(user_doc, agent_obj)
            snippet_tools = await create_snippet_tools(user_doc, agent_obj)
            all_tools = mcp_tools + snippet_tools
            
            logger.info(f"Created {len(all_tools)} tools ({len(mcp_tools)} MCP, {len(snippet_tools)} snippets)")
            
            # 2. Setup Gemini model with LangChain
            # Handle None values by using 'or' operator - dict.get() returns None if key exists with None value
            model_name = (agent_obj.get("model_selected") if agent_obj else None) or "gemini-2.0-flash-exp"
            temperature = (agent_obj.get("temperature") if agent_obj else None) or 0.7
            
            model = ChatGoogleGenerativeAI(
                google_api_key=gemini_key,
                model=model_name,
                temperature=temperature
            )
            
            # Bind tools if available
            if all_tools:
                model = model.bind_tools(all_tools)
                logger.info(f"Bound {len(all_tools)} tools to model")

            # 3. Build message history
            history = await _build_langchain_history(chat_oid, max_messages=15)
            
            # Add system prompt if configured
            messages = []
            if agent_obj and agent_obj.get("system_prompt"):
                system_content = _build_system_prompt(agent_obj)
                messages.append(SystemMessage(content=system_content))
            
            # Add history
            messages.extend(history)
            
            # Add current user message if not already in history
            if not messages or (messages[-1].content != user_text):
                messages.append(HumanMessage(content=user_text))

            # 4. Execute agent loop with tool calling
            logger.info(f"Starting agent execution loop with {len(messages)} messages")
            max_iterations = 5
            response = None  # Initialize to avoid NameError
            
            for iteration in range(max_iterations):
                logger.info(f"Agent iteration {iteration + 1}/{max_iterations}")
                
                # Invoke model
                response = await asyncio.to_thread(model.invoke, messages)
                messages.append(response)
                
                # Check if model wants to call tools
                tool_calls = getattr(response, "tool_calls", None)
                if not tool_calls:
                    # No more tool calls - extract final response
                    final_text = response.content
                    logger.info("Agent completed without tool calls")
                    break
                
                # Execute tool calls
                logger.info(f"Executing {len(tool_calls)} tool calls")
                for tool_call in tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call.get("args", {})
                    tool_call_id = tool_call.get("id", "unknown")
                    
                    logger.info(f"Calling tool: {tool_name} with args: {tool_args}")
                    
                    # Find the tool
                    tool = None
                    for t in all_tools:
                        if t.name == tool_name:
                            tool = t
                            break
                    
                    if tool:
                        try:
                            # Execute tool asynchronously
                            result = await tool._arun(**tool_args)
                            logger.info(f"Tool {tool_name} returned: {str(result)[:100]}...")
                        except Exception as e:
                            result = f"Error executing tool: {str(e)}"
                            logger.error(f"Tool execution error: {e}")
                    else:
                        result = f"Tool {tool_name} not found"
                        logger.warning(f"Tool not found: {tool_name}")
                    
                    # Add tool result to messages
                    messages.append(ToolMessage(
                        content=str(result),
                        tool_call_id=tool_call_id
                    ))
            else:
                # Max iterations reached
                final_text = response.content if (response and hasattr(response, 'content')) else "Maximum iterations reached"
                logger.warning(f"Agent reached maximum iterations ({max_iterations})")
            
        except Exception as e:
            logger.exception(f"Error during agent execution: {e}")
            final_text = f"Error en la ejecución del agente: {str(e)}"

    if not final_text:
        final_text = "No se pudo obtener una respuesta del agente."

    # 5. Save response to database
    response_doc = {
        "_id": PyObjectId.new(),
        "chat_id": chat_oid,
        "parent_id": message_doc["_id"],
        "children_ids": [],
        "path": list(message_doc.get("path", [])) + [message_doc["_id"]],
        "sender_id": PyObjectId.parse(agent_obj["_id"]) if agent_obj else None,
        "role": "agent",
        "content": final_text,
        "content_type": "text",
        "status": "done",
        "created_at": datetime.utcnow(),
    }
    
    logger.info(f"Agent execution complete. Response length: {len(final_text)} chars")
    return response_doc


def _build_system_prompt(agent_obj: Dict[str, Any]) -> str:
    """
    Build system prompt from agent configuration.
    
    Supports:
    - Simple string system prompt
    - List of strings (joined with newlines)
    - TODO: Template expansion for snippets
    """
    system_prompt = agent_obj.get("system_prompt", "")
    
    if isinstance(system_prompt, list):
        # Join list items
        return "\n".join(str(item) for item in system_prompt)
    
    return str(system_prompt)
