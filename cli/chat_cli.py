#!/usr/bin/env python3
"""
InsanusChat CLI - Interactive Chat Management Tool
==================================================

An interactive command-line interface for managing chats, agents, and messages
in the InsanusChat Backend.

Features:
- User authentication (login/register)
- Chat management (create, list, select)
- Message operations (send, view history)
- Agent management (create, list, delete)
- Colorful interactive prompts
- Real-time API interaction

Usage:
    python cli/chat_cli.py [--url BASE_URL]
    
Commands:
    help              - Show available commands
    register          - Register a new user
    login             - Login with credentials
    logout            - Logout current user
    profile           - View current user profile
    
    chats             - List all chats
    chat new          - Create a new chat
    chat select <id>  - Select a chat
    chat delete <id>  - Delete a chat
    
    send <message>    - Send message to current chat
    history           - View chat history
    
    agents            - List all agents
    agent new         - Create a new agent
    agent delete <id> - Delete an agent
    
    clear             - Clear screen
    quit/exit         - Exit the CLI

Author: InsanusTech Team
License: GPL 3.0
"""

import asyncio
import json
import sys
import argparse
from typing import Optional, Dict, Any, List
from datetime import datetime
import httpx

# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    GRAY = '\033[90m'


class ChatCLI:
    """Interactive CLI for InsanusChat Backend"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.token: Optional[str] = None
        self.user_id: Optional[str] = None
        self.email: Optional[str] = None
        self.current_chat_id: Optional[str] = None
        self.current_chat_title: Optional[str] = None
        self.client = httpx.AsyncClient(timeout=30.0)
        
    def print_header(self, text: str):
        """Print a colored header"""
        print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}{text:^70}{Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.ENDC}\n")
        
    def print_success(self, text: str):
        """Print success message"""
        print(f"{Colors.OKGREEN}✓ {text}{Colors.ENDC}")
        
    def print_error(self, text: str):
        """Print error message"""
        print(f"{Colors.FAIL}✗ {text}{Colors.ENDC}")
        
    def print_info(self, text: str):
        """Print info message"""
        print(f"{Colors.OKCYAN}ℹ {text}{Colors.ENDC}")
        
    def print_warning(self, text: str):
        """Print warning message"""
        print(f"{Colors.WARNING}⚠ {text}{Colors.ENDC}")
        
    def print_message(self, role: str, content: str, timestamp: str = None):
        """Print a chat message with formatting"""
        role_colors = {
            "user": Colors.OKGREEN,
            "agent": Colors.OKBLUE,
            "system": Colors.GRAY,
        }
        color = role_colors.get(role, Colors.ENDC)
        time_str = f" [{timestamp}]" if timestamp else ""
        print(f"{color}{role.upper()}{time_str}:{Colors.ENDC} {content}")
        
    def get_headers(self) -> Dict[str, str]:
        """Get headers with authorization token"""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
    
    def get_status_line(self) -> str:
        """Get the status line for prompt"""
        user_str = f"{Colors.OKGREEN}{self.email}{Colors.ENDC}" if self.email else f"{Colors.FAIL}not logged in{Colors.ENDC}"
        chat_str = f"{Colors.OKCYAN}{self.current_chat_title or 'none'}{Colors.ENDC}" if self.current_chat_id else f"{Colors.GRAY}no chat selected{Colors.ENDC}"
        return f"[User: {user_str} | Chat: {chat_str}]"
    
    async def register(self):
        """Register a new user"""
        self.print_header("Register New User")
        
        email = input(f"{Colors.OKCYAN}Email: {Colors.ENDC}").strip()
        password = input(f"{Colors.OKCYAN}Password: {Colors.ENDC}").strip()
        display_name = input(f"{Colors.OKCYAN}Display Name (optional): {Colors.ENDC}").strip()
        
        payload = {"email": email, "password": password}
        if display_name:
            payload["display_name"] = display_name
        
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/auth/register",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                data = response.json()
                self.print_success("Registration successful!")
                self.print_info(f"User ID: {data.get('data', {}).get('user_id', 'N/A')}")
                return True
            else:
                self.print_error(f"Registration failed: {response.text}")
                return False
        except Exception as e:
            self.print_error(f"Error during registration: {e}")
            return False
    
    async def login(self):
        """Login user"""
        self.print_header("Login")
        
        email = input(f"{Colors.OKCYAN}Email: {Colors.ENDC}").strip()
        password = input(f"{Colors.OKCYAN}Password: {Colors.ENDC}").strip()
        
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/auth/login",
                json={"email": email, "password": password},
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                data = response.json().get("data", {})
                self.token = data.get("access_token")
                self.user_id = data.get("user_id")
                self.email = email
                self.print_success(f"Login successful! Welcome, {email}")
                return True
            else:
                self.print_error(f"Login failed: {response.text}")
                return False
        except Exception as e:
            self.print_error(f"Error during login: {e}")
            return False
    
    async def logout(self):
        """Logout user"""
        self.token = None
        self.user_id = None
        self.email = None
        self.current_chat_id = None
        self.current_chat_title = None
        self.print_success("Logged out successfully")
    
    async def get_profile(self):
        """Get user profile"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/auth/",
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                data = response.json().get("data", {})
                self.print_header("User Profile")
                print(f"{Colors.OKBLUE}Email:{Colors.ENDC} {data.get('email')}")
                print(f"{Colors.OKBLUE}Display Name:{Colors.ENDC} {data.get('display_name', 'N/A')}")
                print(f"{Colors.OKBLUE}User ID:{Colors.ENDC} {data.get('_id')}")
                print(f"{Colors.OKBLUE}Created:{Colors.ENDC} {data.get('created_at')}")
                print(f"{Colors.OKBLUE}Agents:{Colors.ENDC} {len(data.get('agents', []))}")
                print(f"{Colors.OKBLUE}API Keys:{Colors.ENDC} {len(data.get('api_keys', []))}")
            else:
                self.print_error(f"Failed to get profile: {response.text}")
        except Exception as e:
            self.print_error(f"Error getting profile: {e}")
    
    async def list_chats(self):
        """List all user chats"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/chats/",
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                chats = response.json().get("data", [])
                self.print_header(f"Your Chats ({len(chats)})")
                
                if not chats:
                    self.print_info("No chats found. Create one with 'chat new'")
                    return
                
                for chat in chats:
                    chat_id = chat.get("_id", "N/A")
                    title = chat.get("title") or "Untitled Chat"
                    msg_count = chat.get("message_count", 0)
                    created = chat.get("created_at", "N/A")
                    
                    selected = " ← SELECTED" if chat_id == self.current_chat_id else ""
                    print(f"{Colors.OKBLUE}ID:{Colors.ENDC} {chat_id}")
                    print(f"  {Colors.OKCYAN}Title:{Colors.ENDC} {title}{Colors.OKGREEN}{selected}{Colors.ENDC}")
                    print(f"  {Colors.GRAY}Messages: {msg_count} | Created: {created}{Colors.ENDC}")
                    print()
            else:
                self.print_error(f"Failed to list chats: {response.text}")
        except Exception as e:
            self.print_error(f"Error listing chats: {e}")
    
    async def create_chat(self):
        """Create a new chat with optional agent and initial message"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        self.print_header("Create New Chat")
        title = input(f"{Colors.OKCYAN}Chat Title (optional): {Colors.ENDC}").strip()
        
        # Get available agents
        agent_id = None
        try:
            agents_response = await self.client.get(
                f"{self.base_url}/api/v1/agents/",
                headers=self.get_headers()
            )
            
            if agents_response.status_code == 200:
                agents = agents_response.json().get("data", [])
                if agents:
                    print(f"\n{Colors.OKBLUE}Available Agents:{Colors.ENDC}")
                    for i, agent in enumerate(agents, 1):
                        agent_name = agent.get("name", "Unnamed")
                        agent_desc = agent.get("description", "No description")
                        print(f"  {i}. {Colors.OKCYAN}{agent_name}{Colors.ENDC} - {agent_desc}")
                    
                    agent_choice = input(f"\n{Colors.OKCYAN}Select agent number (or press Enter to skip): {Colors.ENDC}").strip()
                    if agent_choice.isdigit():
                        idx = int(agent_choice) - 1
                        if 0 <= idx < len(agents):
                            agent_id = agents[idx].get("_id")
                            self.print_info(f"Selected agent: {agents[idx].get('name')}")
                else:
                    self.print_warning("No agents found. Create one with 'agent new'")
        except Exception as e:
            self.print_warning(f"Could not fetch agents: {e}")
        
        # Ask for initial message
        initial_message = input(f"\n{Colors.OKCYAN}Initial message (optional, press Enter to skip): {Colors.ENDC}").strip()
        
        payload = {}
        if title:
            payload["title"] = title
        if agent_id:
            payload["agent_id"] = agent_id
        if initial_message:
            payload["message"] = initial_message
        
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/chats/",
                json=payload,
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                data = response.json().get("data", {})
                chat_id = data.get("_id")
                chat_title = data.get("title", "Untitled Chat")
                self.print_success(f"Chat created: {chat_title}")
                self.print_info(f"Chat ID: {chat_id}")
                
                # Auto-select the new chat
                self.current_chat_id = chat_id
                self.current_chat_title = chat_title
                
                if initial_message:
                    self.print_success("Initial message sent! Waiting for agent response...")
                else:
                    self.print_info("Chat created. Send first message with 'send <message>'")
            else:
                self.print_error(f"Failed to create chat: {response.text}")
        except Exception as e:
            self.print_error(f"Error creating chat: {e}")
    
    async def select_chat(self, chat_id: str):
        """Select a chat"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        # Just set it as current chat - no need to fetch from API
        self.current_chat_id = chat_id
        self.current_chat_title = f"Chat {chat_id[:8]}..."
        self.print_success(f"Selected chat: {chat_id}")
    
    async def delete_chat(self, chat_id: str):
        """Delete a chat"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        confirm = input(f"{Colors.WARNING}Delete chat {chat_id}? (yes/no): {Colors.ENDC}").strip().lower()
        if confirm != "yes":
            self.print_info("Deletion cancelled")
            return
        
        try:
            response = await self.client.delete(
                f"{self.base_url}/api/v1/chats/{chat_id}",
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                self.print_success("Chat deleted")
                if self.current_chat_id == chat_id:
                    self.current_chat_id = None
                    self.current_chat_title = None
            else:
                self.print_error(f"Failed to delete chat: {response.text}")
        except Exception as e:
            self.print_error(f"Error deleting chat: {e}")
    
    async def send_message(self, content: str):
        """Send a message to the current chat"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        if not self.current_chat_id:
            self.print_error("No chat selected. Use 'chat select <id>' or 'chat new'")
            return
        
        try:
            # First, get the last message to use as parent_id
            history_response = await self.client.get(
                f"{self.base_url}/api/v1/chats/{self.current_chat_id}/messages",
                headers=self.get_headers()
            )
            
            parent_id = None
            if history_response.status_code == 200:
                messages = history_response.json().get("data", [])
                if messages:
                    # Get the last message ID
                    parent_id = messages[-1].get("_id")
            
            if not parent_id:
                self.print_error("Cannot send message: No parent message found. Chat might be empty.")
                self.print_info("Try creating a new chat with an initial message using 'chat new'")
                return
            
            # Send the message with proper payload
            response = await self.client.post(
                f"{self.base_url}/api/v1/chats/{self.current_chat_id}/messages",
                json={"text": content, "parent_id": parent_id},
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                data = response.json().get("data", {})
                self.print_success("Message sent")
                # Display the message
                self.print_message("user", content, data.get("created_at"))
            else:
                self.print_error(f"Failed to send message: {response.text}")
        except Exception as e:
            self.print_error(f"Error sending message: {e}")
    
    async def view_history(self):
        """View chat history"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        if not self.current_chat_id:
            self.print_error("No chat selected")
            return
        
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/chats/{self.current_chat_id}/messages",
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                messages = response.json().get("data", [])
                self.print_header(f"Chat History - {self.current_chat_title}")
                
                if not messages:
                    self.print_info("No messages yet. Send one with 'send <message>'")
                    return
                
                for msg in messages:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    timestamp = msg.get("created_at", "")
                    self.print_message(role, content, timestamp)
            else:
                self.print_error(f"Failed to get history: {response.text}")
        except Exception as e:
            self.print_error(f"Error getting history: {e}")
    
    async def list_agents(self):
        """List all agents"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/agents/",
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                agents = response.json().get("data", [])
                self.print_header(f"Your Agents ({len(agents)})")
                
                if not agents:
                    self.print_info("No agents found. Create one with 'agent new'")
                    return
                
                for agent in agents:
                    agent_id = agent.get("_id", "N/A")
                    name = agent.get("name", "Unnamed")
                    description = agent.get("description", "No description")
                    active = agent.get("active", False)
                    
                    status = f"{Colors.OKGREEN}ACTIVE{Colors.ENDC}" if active else f"{Colors.GRAY}INACTIVE{Colors.ENDC}"
                    print(f"{Colors.OKBLUE}ID:{Colors.ENDC} {agent_id} [{status}]")
                    print(f"  {Colors.OKCYAN}Name:{Colors.ENDC} {name}")
                    print(f"  {Colors.GRAY}Description: {description}{Colors.ENDC}")
                    print()
            else:
                self.print_error(f"Failed to list agents: {response.text}")
        except Exception as e:
            self.print_error(f"Error listing agents: {e}")
    
    async def create_agent(self):
        """Create a new agent"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        self.print_header("Create New Agent")
        name = input(f"{Colors.OKCYAN}Agent Name: {Colors.ENDC}").strip()
        description = input(f"{Colors.OKCYAN}Description (optional): {Colors.ENDC}").strip()
        system_prompt = input(f"{Colors.OKCYAN}System Prompt (optional): {Colors.ENDC}").strip()
        model = input(f"{Colors.OKCYAN}Model (default: gemini-2.0-flash-exp): {Colors.ENDC}").strip()
        
        if not name:
            self.print_error("Agent name is required")
            return
        
        payload = {"name": name}
        if description:
            payload["description"] = description
        if system_prompt:
            payload["system_prompt"] = [system_prompt]
        # Always set model_selected to avoid None values
        payload["model_selected"] = model if model else "gemini-2.0-flash-exp"
        
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/agents/",
                json=payload,
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                data = response.json().get("data", {})
                self.print_success(f"Agent created: {name}")
                self.print_info(f"Agent ID: {data.get('_id')}")
            else:
                self.print_error(f"Failed to create agent: {response.text}")
        except Exception as e:
            self.print_error(f"Error creating agent: {e}")
    
    async def delete_agent(self, agent_id: str):
        """Delete an agent"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        confirm = input(f"{Colors.WARNING}Delete agent {agent_id}? (yes/no): {Colors.ENDC}").strip().lower()
        if confirm != "yes":
            self.print_info("Deletion cancelled")
            return
        
        try:
            response = await self.client.delete(
                f"{self.base_url}/api/v1/agents/?agent_id={agent_id}",
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                self.print_success("Agent deleted")
            else:
                self.print_error(f"Failed to delete agent: {response.text}")
        except Exception as e:
            self.print_error(f"Error deleting agent: {e}")
    
    async def list_apikeys(self):
        """List all API keys"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/apikeys/",
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                data = response.json().get("data", [])
                if not data:
                    self.print_info("No API keys found")
                else:
                    self.print_header(f"API Keys ({len(data)})")
                    for key in data:
                        key_id = key.get("_id", "N/A")
                        provider = key.get("provider", "Unknown")
                        label = key.get("label", "No label")
                        print(f"  {Colors.OKBLUE}ID:{Colors.ENDC} {key_id}")
                        print(f"  {Colors.OKCYAN}Provider:{Colors.ENDC} {provider}")
                        print(f"  {Colors.OKCYAN}Label:{Colors.ENDC} {label}")
                        print()
            else:
                self.print_error(f"Failed to list API keys: {response.text}")
        except Exception as e:
            self.print_error(f"Error listing API keys: {e}")
    
    async def add_apikey(self):
        """Add a new API key"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        self.print_header("Add New API Key")
        provider = input(f"{Colors.OKCYAN}Provider (e.g., openai, anthropic, google): {Colors.ENDC}").strip()
        key = input(f"{Colors.OKCYAN}API Key: {Colors.ENDC}").strip()
        label = input(f"{Colors.OKCYAN}Label (optional): {Colors.ENDC}").strip()
        
        if not provider or not key:
            self.print_error("Provider and API key are required")
            return
        
        payload = {
            "provider": provider,
            "encrypted_key": key,  # Backend will handle encryption
        }
        if label:
            payload["label"] = label
        
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/apikeys/",
                json=payload,
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                data = response.json().get("data", {})
                self.print_success("API key added successfully!")
                self.print_info(f"ID: {data.get('_id', 'N/A')}")
            else:
                self.print_error(f"Failed to add API key: {response.text}")
        except Exception as e:
            self.print_error(f"Error adding API key: {e}")
    
    async def delete_apikey(self, key_id: str):
        """Delete an API key"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        confirm = input(f"{Colors.WARNING}Delete API key {key_id}? (yes/no): {Colors.ENDC}").strip().lower()
        if confirm != "yes":
            self.print_info("Deletion cancelled")
            return
        
        try:
            response = await self.client.delete(
                f"{self.base_url}/api/v1/apikeys/?api_key_id={key_id}",
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                self.print_success("API key deleted")
            else:
                self.print_error(f"Failed to delete API key: {response.text}")
        except Exception as e:
            self.print_error(f"Error deleting API key: {e}")
    
    async def list_resources(self):
        """List all tools (MCPs and snippets)"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/resources/",
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                data = response.json().get("data", {})
                mcps = data.get("mcps", [])
                snippets = data.get("snippets", [])
                
                self.print_header(f"MCP Servers ({len(mcps)})")
                if not mcps:
                    print(f"  {Colors.GRAY}No MCP servers found{Colors.ENDC}")
                else:
                    for mcp in mcps:
                        mcp_id = mcp.get("_id", "N/A")
                        name = mcp.get("name", "Unnamed")
                        transport = mcp.get("transport_type", "Unknown")
                        print(f"  {Colors.OKBLUE}ID:{Colors.ENDC} {mcp_id}")
                        print(f"  {Colors.OKCYAN}Name:{Colors.ENDC} {name}")
                        print(f"  {Colors.OKCYAN}Transport:{Colors.ENDC} {transport}")
                        print()
                
                self.print_header(f"Code Snippets ({len(snippets)})")
                if not snippets:
                    print(f"  {Colors.GRAY}No code snippets found{Colors.ENDC}")
                else:
                    for snippet in snippets:
                        snippet_id = snippet.get("_id", "N/A")
                        name = snippet.get("name", "Unnamed")
                        lang = snippet.get("language", "Unknown")
                        print(f"  {Colors.OKBLUE}ID:{Colors.ENDC} {snippet_id}")
                        print(f"  {Colors.OKCYAN}Name:{Colors.ENDC} {name}")
                        print(f"  {Colors.OKCYAN}Language:{Colors.ENDC} {lang}")
                        print()
            else:
                self.print_error(f"Failed to list resources: {response.text}")
        except Exception as e:
            self.print_error(f"Error listing resources: {e}")
    
    async def add_mcp(self):
        """Add a new MCP server"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        self.print_header("Add New MCP Server")
        name = input(f"{Colors.OKCYAN}MCP Name: {Colors.ENDC}").strip()
        transport = input(f"{Colors.OKCYAN}Transport Type (stdio/http/sse/websocket) [stdio]: {Colors.ENDC}").strip() or "stdio"
        
        if not name:
            self.print_error("MCP name is required")
            return
        
        payload = {
            "name": name,
            "transport_type": transport,
        }
        
        # Get transport-specific details
        if transport == "stdio":
            script_path = input(f"{Colors.OKCYAN}Script Path: {Colors.ENDC}").strip()
            if script_path:
                payload["script_path"] = script_path
        elif transport in ["http", "sse", "websocket"]:
            url = input(f"{Colors.OKCYAN}URL: {Colors.ENDC}").strip()
            if url:
                payload["url"] = url
        
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/resources/mcps",
                json=payload,
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                self.print_success("MCP server added successfully!")
            else:
                self.print_error(f"Failed to add MCP: {response.text}")
        except Exception as e:
            self.print_error(f"Error adding MCP: {e}")
    
    async def delete_mcp(self, mcp_id: str):
        """Delete an MCP server"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        confirm = input(f"{Colors.WARNING}Delete MCP server {mcp_id}? (yes/no): {Colors.ENDC}").strip().lower()
        if confirm != "yes":
            self.print_info("Deletion cancelled")
            return
        
        try:
            response = await self.client.delete(
                f"{self.base_url}/api/v1/resources/mcps?mcp_id={mcp_id}",
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                self.print_success("MCP server deleted")
            else:
                self.print_error(f"Failed to delete MCP: {response.text}")
        except Exception as e:
            self.print_error(f"Error deleting MCP: {e}")
    
    async def add_snippet(self):
        """Add a new code snippet"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        self.print_header("Add New Code Snippet")
        name = input(f"{Colors.OKCYAN}Snippet Name: {Colors.ENDC}").strip()
        language = input(f"{Colors.OKCYAN}Language (python/javascript) [python]: {Colors.ENDC}").strip() or "python"
        description = input(f"{Colors.OKCYAN}Description (optional): {Colors.ENDC}").strip()
        
        print(f"{Colors.OKCYAN}Enter code (press Ctrl+D or Ctrl+Z when done):{Colors.ENDC}")
        code_lines = []
        try:
            while True:
                line = input()
                code_lines.append(line)
        except EOFError:
            pass
        
        code = "\n".join(code_lines)
        
        if not name or not code:
            self.print_error("Snippet name and code are required")
            return
        
        payload = {
            "name": name,
            "language": language,
            "code": code,
        }
        if description:
            payload["description"] = description
        
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/resources/snippets",
                json=payload,
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                self.print_success("Code snippet added successfully!")
            else:
                self.print_error(f"Failed to add snippet: {response.text}")
        except Exception as e:
            self.print_error(f"Error adding snippet: {e}")
    
    async def delete_snippet(self, snippet_id: str):
        """Delete a code snippet"""
        if not self.token:
            self.print_error("Please login first")
            return
        
        confirm = input(f"{Colors.WARNING}Delete snippet {snippet_id}? (yes/no): {Colors.ENDC}").strip().lower()
        if confirm != "yes":
            self.print_info("Deletion cancelled")
            return
        
        try:
            response = await self.client.delete(
                f"{self.base_url}/api/v1/resources/snippets?snippet_id={snippet_id}",
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                self.print_success("Code snippet deleted")
            else:
                self.print_error(f"Failed to delete snippet: {response.text}")
        except Exception as e:
            self.print_error(f"Error deleting snippet: {e}")
    
    def show_help(self):
        """Show help message"""
        self.print_header("InsanusChat CLI - Help")
        print(f"{Colors.BOLD}Authentication:{Colors.ENDC}")
        print(f"  {Colors.OKCYAN}register{Colors.ENDC}          - Register a new user")
        print(f"  {Colors.OKCYAN}login{Colors.ENDC}             - Login with credentials")
        print(f"  {Colors.OKCYAN}logout{Colors.ENDC}            - Logout current user")
        print(f"  {Colors.OKCYAN}profile{Colors.ENDC}           - View your profile")
        print()
        print(f"{Colors.BOLD}Chat Management:{Colors.ENDC}")
        print(f"  {Colors.OKCYAN}chats{Colors.ENDC}             - List all chats")
        print(f"  {Colors.OKCYAN}chat new{Colors.ENDC}          - Create a new chat")
        print(f"  {Colors.OKCYAN}chat select <id>{Colors.ENDC}  - Select a chat")
        print(f"  {Colors.OKCYAN}chat delete <id>{Colors.ENDC}  - Delete a chat")
        print()
        print(f"{Colors.BOLD}Messages:{Colors.ENDC}")
        print(f"  {Colors.OKCYAN}send <message>{Colors.ENDC}    - Send message to current chat")
        print(f"  {Colors.OKCYAN}history{Colors.ENDC}           - View chat history")
        print()
        print(f"{Colors.BOLD}Agents:{Colors.ENDC}")
        print(f"  {Colors.OKCYAN}agents{Colors.ENDC}            - List all agents")
        print(f"  {Colors.OKCYAN}agent new{Colors.ENDC}         - Create a new agent")
        print(f"  {Colors.OKCYAN}agent delete <id>{Colors.ENDC} - Delete an agent")
        print()
        print(f"{Colors.BOLD}API Keys:{Colors.ENDC}")
        print(f"  {Colors.OKCYAN}apikeys{Colors.ENDC}           - List all API keys")
        print(f"  {Colors.OKCYAN}apikey add{Colors.ENDC}        - Add a new API key")
        print(f"  {Colors.OKCYAN}apikey delete <id>{Colors.ENDC} - Delete an API key")
        print()
        print(f"{Colors.BOLD}Tools/Resources:{Colors.ENDC}")
        print(f"  {Colors.OKCYAN}resources{Colors.ENDC}         - List all MCPs and snippets")
        print(f"  {Colors.OKCYAN}mcp add{Colors.ENDC}           - Add a new MCP server")
        print(f"  {Colors.OKCYAN}mcp delete <id>{Colors.ENDC}   - Delete an MCP server")
        print(f"  {Colors.OKCYAN}snippet add{Colors.ENDC}       - Add a new code snippet")
        print(f"  {Colors.OKCYAN}snippet delete <id>{Colors.ENDC} - Delete a code snippet")
        print()
        print(f"{Colors.BOLD}Other:{Colors.ENDC}")
        print(f"  {Colors.OKCYAN}clear{Colors.ENDC}             - Clear screen")
        print(f"  {Colors.OKCYAN}help{Colors.ENDC}              - Show this help")
        print(f"  {Colors.OKCYAN}quit/exit{Colors.ENDC}         - Exit the CLI")
        print()
    
    async def run(self):
        """Main CLI loop"""
        self.print_header("InsanusChat CLI")
        self.print_info(f"Connected to: {self.base_url}")
        self.print_info("Type 'help' for available commands")
        
        while True:
            try:
                # Print status and prompt
                print(f"\n{self.get_status_line()}")
                command = input(f"{Colors.BOLD}> {Colors.ENDC}").strip()
                
                if not command:
                    continue
                
                parts = command.split(maxsplit=2)
                cmd = parts[0].lower()
                
                # Authentication commands
                if cmd == "register":
                    await self.register()
                elif cmd == "login":
                    await self.login()
                elif cmd == "logout":
                    await self.logout()
                elif cmd == "profile":
                    await self.get_profile()
                
                # Chat commands
                elif cmd == "chats":
                    await self.list_chats()
                elif cmd == "chat":
                    if len(parts) < 2:
                        self.print_error("Usage: chat <new|select|delete> [id]")
                    elif parts[1] == "new":
                        await self.create_chat()
                    elif parts[1] == "select" and len(parts) >= 3:
                        await self.select_chat(parts[2])
                    elif parts[1] == "delete" and len(parts) >= 3:
                        await self.delete_chat(parts[2])
                    else:
                        self.print_error("Usage: chat <new|select|delete> [id]")
                
                # Message commands
                elif cmd == "send":
                    if len(parts) < 2:
                        self.print_error("Usage: send <message>")
                    else:
                        message = command[5:].strip()  # Get everything after "send "
                        await self.send_message(message)
                elif cmd == "history":
                    await self.view_history()
                
                # Agent commands
                elif cmd == "agents":
                    await self.list_agents()
                elif cmd == "agent":
                    if len(parts) < 2:
                        self.print_error("Usage: agent <new|delete> [id]")
                    elif parts[1] == "new":
                        await self.create_agent()
                    elif parts[1] == "delete" and len(parts) >= 3:
                        await self.delete_agent(parts[2])
                    else:
                        self.print_error("Usage: agent <new|delete> [id]")
                
                # API Key commands
                elif cmd == "apikeys":
                    await self.list_apikeys()
                elif cmd == "apikey":
                    if len(parts) < 2:
                        self.print_error("Usage: apikey <add|delete> [id]")
                    elif parts[1] == "add":
                        await self.add_apikey()
                    elif parts[1] == "delete" and len(parts) >= 3:
                        await self.delete_apikey(parts[2])
                    else:
                        self.print_error("Usage: apikey <add|delete> [id]")
                
                # Resource/Tools commands
                elif cmd == "resources":
                    await self.list_resources()
                elif cmd == "mcp":
                    if len(parts) < 2:
                        self.print_error("Usage: mcp <add|delete> [id]")
                    elif parts[1] == "add":
                        await self.add_mcp()
                    elif parts[1] == "delete" and len(parts) >= 3:
                        await self.delete_mcp(parts[2])
                    else:
                        self.print_error("Usage: mcp <add|delete> [id]")
                elif cmd == "snippet":
                    if len(parts) < 2:
                        self.print_error("Usage: snippet <add|delete> [id]")
                    elif parts[1] == "add":
                        await self.add_snippet()
                    elif parts[1] == "delete" and len(parts) >= 3:
                        await self.delete_snippet(parts[2])
                    else:
                        self.print_error("Usage: snippet <add|delete> [id]")
                
                # Utility commands
                elif cmd == "clear":
                    print("\033[2J\033[H", end="")  # Clear screen
                elif cmd == "help":
                    self.show_help()
                elif cmd in ["quit", "exit"]:
                    self.print_info("Goodbye!")
                    break
                else:
                    self.print_error(f"Unknown command: {cmd}. Type 'help' for available commands")
                    
            except KeyboardInterrupt:
                print()
                self.print_warning("Use 'quit' or 'exit' to exit")
            except Exception as e:
                self.print_error(f"Unexpected error: {e}")
        
        await self.client.aclose()


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="InsanusChat Interactive CLI")
    parser.add_argument("--url", default="http://localhost:8000", help="Backend API URL")
    args = parser.parse_args()
    
    cli = ChatCLI(base_url=args.url)
    await cli.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nExiting...")
        sys.exit(0)
