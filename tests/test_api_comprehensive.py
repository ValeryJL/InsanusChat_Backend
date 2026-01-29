#!/usr/bin/env python3
"""
Comprehensive Testing Script for InsanusChat Backend API
=========================================================

This interactive script tests all endpoints of the InsanusChat Backend API:
- Authentication (register, login, profile)
- Agents (CRUD operations)
- API Keys (CRUD operations)
- MCPs (CRUD operations)
- Snippets (CRUD operations)
- Chats (create, list, messages)
- WebSocket chat connection

Usage:
    python test_api_comprehensive.py [--url BASE_URL]
    
Commands:
    help              - Show available commands
    register          - Register a new user
    login             - Login with credentials
    profile           - Get current user profile
    agents            - Test all agent operations
    apikeys           - Test all API key operations
    mcps              - Test all MCP operations
    snippets          - Test all snippet operations
    chats             - Test all chat operations
    websocket         - Test WebSocket connection
    all               - Run all tests sequentially
    quit/exit         - Exit the script

Author: InsanusTech Team
License: GPL 3.0
"""

import asyncio
import json
import sys
import argparse
from datetime import datetime
from typing import Optional, Dict, Any, List
import httpx
import websockets
from websockets.exceptions import WebSocketException

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


class APITester:
    """Main testing class for InsanusChat Backend API"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.token: Optional[str] = None
        self.user_id: Optional[str] = None
        self.email: Optional[str] = None
        self.test_data: Dict[str, Any] = {}
        
    def print_header(self, text: str):
        """Print a colored header"""
        print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}{text:^60}{Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}\n")
        
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
        
    def print_json(self, data: Any, indent: int = 2):
        """Print JSON data with color"""
        json_str = json.dumps(data, indent=indent, ensure_ascii=False)
        print(f"{Colors.OKBLUE}{json_str}{Colors.ENDC}")
        
    def get_headers(self) -> Dict[str, str]:
        """Get headers with authorization token"""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
    
    async def test_health(self):
        """Test the health endpoint"""
        self.print_header("Testing Health Endpoint")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{self.base_url}/")
                if response.status_code == 200:
                    self.print_success(f"API is running: {response.json()}")
                else:
                    self.print_error(f"Health check failed: {response.status_code}")
        except Exception as e:
            self.print_error(f"Failed to connect to API: {e}")
            
    async def register_user(self, email: Optional[str] = None, password: Optional[str] = None):
        """Register a new user"""
        self.print_header("User Registration")
        
        if not email:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            email = f"test_user_{timestamp}@insanustest.com"
        if not password:
            password = "TestPassword123!"
            
        payload = {
            "email": email,
            "password": password,
            "display_name": f"Test User {datetime.now().strftime('%H:%M:%S')}"
        }
        
        self.print_info(f"Registering user: {email}")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/auth/register",
                    json=payload
                )
                
                if response.status_code == 201 or response.status_code == 200:
                    data = response.json()
                    self.print_success("User registered successfully!")
                    self.print_json(data)
                    
                    # Save credentials
                    self.email = email
                    self.test_data['password'] = password
                    
                    # Extract token if present
                    if data.get('data') and data['data'].get('access_token'):
                        self.token = data['data']['access_token']
                        self.user_id = data['data'].get('user_id')
                        self.print_success(f"Token saved: {self.token[:20]}...")
                    
                    return True
                else:
                    self.print_error(f"Registration failed: {response.status_code}")
                    self.print_json(response.json())
                    return False
                    
        except Exception as e:
            self.print_error(f"Registration error: {e}")
            return False
    
    async def login_user(self, email: Optional[str] = None, password: Optional[str] = None):
        """Login with credentials"""
        self.print_header("User Login")
        
        if not email:
            email = self.email or input("Email: ")
        if not password:
            password = self.test_data.get('password') or input("Password: ")
            
        payload = {
            "email": email,
            "password": password
        }
        
        self.print_info(f"Logging in as: {email}")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/auth/login",
                    json=payload
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self.print_success("Login successful!")
                    self.print_json(data)
                    
                    # Save token
                    if data.get('data'):
                        self.token = data['data'].get('access_token')
                        self.user_id = data['data'].get('user_id')
                        self.email = email
                        self.print_success(f"Token saved: {self.token[:20]}...")
                    
                    return True
                else:
                    self.print_error(f"Login failed: {response.status_code}")
                    self.print_json(response.json())
                    return False
                    
        except Exception as e:
            self.print_error(f"Login error: {e}")
            return False
    
    async def get_profile(self):
        """Get user profile"""
        self.print_header("Get User Profile")
        
        if not self.token:
            self.print_error("Not authenticated. Please login first.")
            return False
            
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/auth/profile",
                    headers=self.get_headers()
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self.print_success("Profile retrieved successfully!")
                    self.print_json(data)
                    return True
                else:
                    self.print_error(f"Get profile failed: {response.status_code}")
                    self.print_json(response.json())
                    return False
                    
        except Exception as e:
            self.print_error(f"Get profile error: {e}")
            return False
    
    async def test_agents(self):
        """Test all agent CRUD operations"""
        self.print_header("Testing Agent Operations")
        
        if not self.token:
            self.print_error("Not authenticated. Please login first.")
            return False
        
        # Create agent
        self.print_info("Creating agent...")
        agent_payload = {
            "name": f"Test Agent {datetime.now().strftime('%H:%M:%S')}",
            "description": "A test agent for API testing",
            "system_prompt": ["You are a helpful test assistant.", "Always be polite."],
            "snippets": [],
            "allowed_tools": ["test_tool"],
            "spec": {"model": "gpt-4o"},
            "metadata": {"test": True}
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # CREATE
                response = await client.post(
                    f"{self.base_url}/api/v1/agents/",
                    headers=self.get_headers(),
                    json=agent_payload
                )
                
                if response.status_code in [200, 201]:
                    data = response.json()
                    self.print_success("Agent created!")
                    self.print_json(data)
                    agent_id = data.get('data', {}).get('_id')
                    self.test_data['agent_id'] = agent_id
                else:
                    self.print_error(f"Agent creation failed: {response.status_code}")
                    self.print_json(response.json())
                    return False
                
                # LIST
                self.print_info("Listing agents...")
                response = await client.get(
                    f"{self.base_url}/api/v1/agents/",
                    headers=self.get_headers()
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self.print_success(f"Agents listed! Count: {len(data.get('data', []))}")
                    self.print_json(data)
                else:
                    self.print_error(f"List agents failed: {response.status_code}")
                
                # UPDATE (if agent_id exists)
                if agent_id:
                    self.print_info(f"Updating agent {agent_id}...")
                    update_payload = {
                        "name": f"Updated Agent {datetime.now().strftime('%H:%M:%S')}",
                        "description": "Updated description"
                    }
                    response = await client.put(
                        f"{self.base_url}/api/v1/agents/{agent_id}",
                        headers=self.get_headers(),
                        json=update_payload
                    )
                    
                    if response.status_code == 200:
                        self.print_success("Agent updated!")
                        self.print_json(response.json())
                    else:
                        self.print_warning(f"Agent update returned: {response.status_code}")
                    
                    # DELETE
                    self.print_info(f"Deleting agent {agent_id}...")
                    response = await client.delete(
                        f"{self.base_url}/api/v1/agents/{agent_id}",
                        headers=self.get_headers()
                    )
                    
                    if response.status_code in [200, 204]:
                        self.print_success("Agent deleted!")
                    else:
                        self.print_warning(f"Agent delete returned: {response.status_code}")
                
                return True
                
        except Exception as e:
            self.print_error(f"Agent operations error: {e}")
            return False
    
    async def test_apikeys(self):
        """Test all API key CRUD operations"""
        self.print_header("Testing API Key Operations")
        
        if not self.token:
            self.print_error("Not authenticated. Please login first.")
            return False
        
        # Create API key
        self.print_info("Creating API key...")
        apikey_payload = {
            "provider": "openai",
            "encrypted_key": "sk-test-encrypted-key-12345",
            "label": f"Test OpenAI Key {datetime.now().strftime('%H:%M:%S')}",
            "active": True
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # CREATE
                response = await client.post(
                    f"{self.base_url}/api/v1/apikeys/",
                    headers=self.get_headers(),
                    json=apikey_payload
                )
                
                if response.status_code in [200, 201]:
                    data = response.json()
                    self.print_success("API key created!")
                    self.print_json(data)
                    apikey_id = data.get('data', {}).get('_id')
                    self.test_data['apikey_id'] = apikey_id
                else:
                    self.print_error(f"API key creation failed: {response.status_code}")
                    self.print_json(response.json())
                    return False
                
                # LIST
                self.print_info("Listing API keys...")
                response = await client.get(
                    f"{self.base_url}/api/v1/apikeys/",
                    headers=self.get_headers()
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self.print_success(f"API keys listed! Count: {len(data.get('data', []))}")
                    self.print_json(data)
                else:
                    self.print_error(f"List API keys failed: {response.status_code}")
                
                # UPDATE (if apikey_id exists)
                if apikey_id:
                    self.print_info(f"Updating API key {apikey_id}...")
                    update_payload = {
                        "label": f"Updated Key {datetime.now().strftime('%H:%M:%S')}",
                        "active": False
                    }
                    response = await client.put(
                        f"{self.base_url}/api/v1/apikeys/{apikey_id}",
                        headers=self.get_headers(),
                        json=update_payload
                    )
                    
                    if response.status_code == 200:
                        self.print_success("API key updated!")
                        self.print_json(response.json())
                    else:
                        self.print_warning(f"API key update returned: {response.status_code}")
                    
                    # DELETE
                    self.print_info(f"Deleting API key {apikey_id}...")
                    response = await client.delete(
                        f"{self.base_url}/api/v1/apikeys/{apikey_id}",
                        headers=self.get_headers()
                    )
                    
                    if response.status_code in [200, 204]:
                        self.print_success("API key deleted!")
                    else:
                        self.print_warning(f"API key delete returned: {response.status_code}")
                
                return True
                
        except Exception as e:
            self.print_error(f"API key operations error: {e}")
            return False
    
    async def test_mcps(self):
        """Test all MCP CRUD operations"""
        self.print_header("Testing MCP Operations")
        
        if not self.token:
            self.print_error("Not authenticated. Please login first.")
            return False
        
        # Create MCP
        self.print_info("Creating MCP...")
        mcp_payload = {
            "name": f"Test MCP {datetime.now().strftime('%H:%M:%S')}",
            "endpoint": "http://localhost:9000/mcp",
            "transport": "http",
            "spec": {"capabilities": ["tools", "prompts"]},
            "auth": {"type": "api_key"},
            "metadata": {"test": True},
            "timeout_seconds": 30,
            "status": "available"
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # CREATE
                response = await client.post(
                    f"{self.base_url}/api/v1/resources/mcps",
                    headers=self.get_headers(),
                    json=mcp_payload
                )
                
                if response.status_code in [200, 201]:
                    data = response.json()
                    self.print_success("MCP created!")
                    self.print_json(data)
                    mcp_id = data.get('data', {}).get('_id')
                    self.test_data['mcp_id'] = mcp_id
                else:
                    self.print_error(f"MCP creation failed: {response.status_code}")
                    self.print_json(response.json())
                    return False
                
                # LIST (via resources endpoint)
                self.print_info("Listing resources (includes MCPs)...")
                response = await client.get(
                    f"{self.base_url}/api/v1/resources/",
                    headers=self.get_headers()
                )
                
                if response.status_code == 200:
                    data = response.json()
                    mcps = data.get('data', {}).get('mcps', [])
                    self.print_success(f"Resources listed! MCPs count: {len(mcps)}")
                    self.print_json(data)
                else:
                    self.print_error(f"List resources failed: {response.status_code}")
                
                # UPDATE (if mcp_id exists)
                if mcp_id:
                    self.print_info(f"Updating MCP {mcp_id}...")
                    update_payload = {
                        "name": f"Updated MCP {datetime.now().strftime('%H:%M:%S')}",
                        "status": "disabled"
                    }
                    response = await client.put(
                        f"{self.base_url}/api/v1/resources/mcps/{mcp_id}",
                        headers=self.get_headers(),
                        json=update_payload
                    )
                    
                    if response.status_code == 200:
                        self.print_success("MCP updated!")
                        self.print_json(response.json())
                    else:
                        self.print_warning(f"MCP update returned: {response.status_code}")
                    
                    # DELETE
                    self.print_info(f"Deleting MCP {mcp_id}...")
                    response = await client.delete(
                        f"{self.base_url}/api/v1/resources/mcps/{mcp_id}",
                        headers=self.get_headers()
                    )
                    
                    if response.status_code in [200, 204]:
                        self.print_success("MCP deleted!")
                    else:
                        self.print_warning(f"MCP delete returned: {response.status_code}")
                
                return True
                
        except Exception as e:
            self.print_error(f"MCP operations error: {e}")
            return False
    
    async def test_snippets(self):
        """Test all snippet CRUD operations"""
        self.print_header("Testing Code Snippet Operations")
        
        if not self.token:
            self.print_error("Not authenticated. Please login first.")
            return False
        
        # Create snippet
        self.print_info("Creating code snippet...")
        snippet_payload = {
            "name": f"test_function_{datetime.now().strftime('%H%M%S')}",
            "description": "A test function for API testing",
            "language": "python",
            "code": "def test_function():\n    return 'Hello, World!'",
            "public": False
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # CREATE
                response = await client.post(
                    f"{self.base_url}/api/v1/resources/snippets",
                    headers=self.get_headers(),
                    json=snippet_payload
                )
                
                if response.status_code in [200, 201]:
                    data = response.json()
                    self.print_success("Snippet created!")
                    self.print_json(data)
                    snippet_id = data.get('data', {}).get('_id')
                    self.test_data['snippet_id'] = snippet_id
                else:
                    self.print_error(f"Snippet creation failed: {response.status_code}")
                    self.print_json(response.json())
                    return False
                
                # LIST (via resources endpoint)
                self.print_info("Listing resources (includes snippets)...")
                response = await client.get(
                    f"{self.base_url}/api/v1/resources/",
                    headers=self.get_headers()
                )
                
                if response.status_code == 200:
                    data = response.json()
                    snippets = data.get('data', {}).get('code_snippets', [])
                    self.print_success(f"Resources listed! Snippets count: {len(snippets)}")
                    self.print_json(data)
                else:
                    self.print_error(f"List resources failed: {response.status_code}")
                
                # UPDATE (if snippet_id exists)
                if snippet_id:
                    self.print_info(f"Updating snippet {snippet_id}...")
                    update_payload = {
                        "name": f"updated_function_{datetime.now().strftime('%H%M%S')}",
                        "description": "Updated test function",
                        "public": True
                    }
                    response = await client.put(
                        f"{self.base_url}/api/v1/resources/snippets/{snippet_id}",
                        headers=self.get_headers(),
                        json=update_payload
                    )
                    
                    if response.status_code == 200:
                        self.print_success("Snippet updated!")
                        self.print_json(response.json())
                    else:
                        self.print_warning(f"Snippet update returned: {response.status_code}")
                    
                    # DELETE
                    self.print_info(f"Deleting snippet {snippet_id}...")
                    response = await client.delete(
                        f"{self.base_url}/api/v1/resources/snippets/{snippet_id}",
                        headers=self.get_headers()
                    )
                    
                    if response.status_code in [200, 204]:
                        self.print_success("Snippet deleted!")
                    else:
                        self.print_warning(f"Snippet delete returned: {response.status_code}")
                
                return True
                
        except Exception as e:
            self.print_error(f"Snippet operations error: {e}")
            return False
    
    async def test_chats(self):
        """Test chat operations"""
        self.print_header("Testing Chat Operations")
        
        if not self.token:
            self.print_error("Not authenticated. Please login first.")
            return False
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # CREATE CHAT
                self.print_info("Creating chat...")
                chat_payload = {
                    "title": f"Test Chat {datetime.now().strftime('%H:%M:%S')}",
                    "message": "Hello! This is a test message.",
                    "agent_id": self.test_data.get('agent_id')
                }
                
                response = await client.post(
                    f"{self.base_url}/api/v1/chats/",
                    headers=self.get_headers(),
                    json=chat_payload
                )
                
                if response.status_code in [200, 201]:
                    data = response.json()
                    self.print_success("Chat created!")
                    self.print_json(data)
                    chat_id = data.get('data', {}).get('_id')
                    self.test_data['chat_id'] = chat_id
                else:
                    self.print_error(f"Chat creation failed: {response.status_code}")
                    self.print_json(response.json())
                    return False
                
                # LIST CHATS
                self.print_info("Listing chats...")
                response = await client.get(
                    f"{self.base_url}/api/v1/chats/",
                    headers=self.get_headers()
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self.print_success(f"Chats listed! Count: {len(data.get('data', []))}")
                    self.print_json(data)
                else:
                    self.print_error(f"List chats failed: {response.status_code}")
                
                # GET MESSAGES
                if chat_id:
                    self.print_info(f"Getting messages for chat {chat_id}...")
                    await asyncio.sleep(2)  # Wait for message processing
                    
                    response = await client.get(
                        f"{self.base_url}/api/v1/chats/{chat_id}/messages",
                        headers=self.get_headers()
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        self.print_success(f"Messages retrieved! Count: {len(data.get('data', []))}")
                        self.print_json(data)
                    else:
                        self.print_warning(f"Get messages returned: {response.status_code}")
                
                return True
                
        except Exception as e:
            self.print_error(f"Chat operations error: {e}")
            return False
    
    async def test_websocket(self):
        """Test WebSocket connection"""
        self.print_header("Testing WebSocket Connection")
        
        if not self.token:
            self.print_error("Not authenticated. Please login first.")
            return False
        
        # Get or create a chat ID
        chat_id = self.test_data.get('chat_id')
        if not chat_id:
            self.print_info("No chat ID found, creating a chat first...")
            await self.test_chats()
            chat_id = self.test_data.get('chat_id')
            if not chat_id:
                self.print_error("Failed to create chat for WebSocket test")
                return False
        
        # Construct WebSocket URL
        ws_url = self.base_url.replace('http://', 'ws://').replace('https://', 'wss://')
        ws_url = f"{ws_url}/api/v1/chats/ws?chat_id={chat_id}"
        
        self.print_info(f"Connecting to WebSocket: {ws_url}")
        self.print_info(f"Using token: {self.token[:20]}...")
        
        try:
            # WebSocket connection with authentication header
            extra_headers = {
                "Authorization": f"Bearer {self.token}"
            }
            
            async with websockets.connect(
                ws_url,
                extra_headers=extra_headers,
                ping_interval=20,
                ping_timeout=10
            ) as websocket:
                self.print_success("WebSocket connected!")
                
                # Receive initial message (history)
                self.print_info("Waiting for initial history...")
                try:
                    init_msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    self.print_success("Received initial message:")
                    self.print_json(json.loads(init_msg))
                except asyncio.TimeoutError:
                    self.print_warning("No initial message received (timeout)")
                
                # Send a test message
                test_message = {
                    "text": f"WebSocket test message at {datetime.now().isoformat()}",
                    "parent_id": None  # Will need to get from history in real scenario
                }
                
                self.print_info("Sending test message...")
                await websocket.send(json.dumps(test_message))
                self.print_success("Message sent!")
                
                # Receive responses (with timeout)
                self.print_info("Waiting for responses...")
                try:
                    for i in range(3):  # Try to receive up to 3 messages
                        response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                        response_data = json.loads(response)
                        self.print_success(f"Received message {i+1}:")
                        self.print_json(response_data)
                except asyncio.TimeoutError:
                    self.print_warning("No more messages (timeout)")
                
                self.print_success("WebSocket test completed!")
                return True
                
        except WebSocketException as e:
            self.print_error(f"WebSocket error: {e}")
            return False
        except Exception as e:
            self.print_error(f"WebSocket test error: {e}")
            return False
    
    async def run_all_tests(self):
        """Run all tests sequentially"""
        self.print_header("Running All Tests")
        
        tests = [
            ("Health Check", self.test_health),
            ("Register User", lambda: self.register_user()),
            ("User Profile", self.get_profile),
            ("Agents", self.test_agents),
            ("API Keys", self.test_apikeys),
            ("MCPs", self.test_mcps),
            ("Snippets", self.test_snippets),
            ("Chats", self.test_chats),
            ("WebSocket", self.test_websocket),
        ]
        
        results = {}
        for name, test_func in tests:
            try:
                self.print_info(f"\nRunning: {name}")
                result = await test_func()
                results[name] = result if result is not None else True
            except Exception as e:
                self.print_error(f"Test '{name}' failed with exception: {e}")
                results[name] = False
        
        # Summary
        self.print_header("Test Summary")
        passed = sum(1 for r in results.values() if r)
        total = len(results)
        
        for name, result in results.items():
            if result:
                self.print_success(f"{name}: PASSED")
            else:
                self.print_error(f"{name}: FAILED")
        
        self.print_info(f"\nTotal: {passed}/{total} tests passed")
        
        if passed == total:
            self.print_success("\n🎉 All tests passed!")
        else:
            self.print_warning(f"\n⚠ {total - passed} test(s) failed")
    
    def print_help(self):
        """Print help information"""
        help_text = f"""
{Colors.HEADER}{Colors.BOLD}Available Commands:{Colors.ENDC}

{Colors.OKGREEN}Authentication:{Colors.ENDC}
  register          - Register a new user
  login             - Login with credentials
  profile           - Get current user profile

{Colors.OKGREEN}CRUD Operations:{Colors.ENDC}
  agents            - Test all agent operations (create, list, update, delete)
  apikeys           - Test all API key operations (create, list, update, delete)
  mcps              - Test all MCP operations (create, list, update, delete)
  snippets          - Test all snippet operations (create, list, update, delete)
  chats             - Test chat operations (create, list, get messages)

{Colors.OKGREEN}Real-time:{Colors.ENDC}
  websocket         - Test WebSocket connection and messaging

{Colors.OKGREEN}Utilities:{Colors.ENDC}
  health            - Test API health endpoint
  all               - Run all tests sequentially
  status            - Show current authentication status
  help              - Show this help message
  quit/exit         - Exit the script

{Colors.OKGREEN}Current Configuration:{Colors.ENDC}
  Base URL: {self.base_url}
  Authenticated: {"Yes" if self.token else "No"}
  User ID: {self.user_id or "N/A"}
  Email: {self.email or "N/A"}
"""
        print(help_text)
    
    def print_status(self):
        """Print current status"""
        self.print_header("Current Status")
        print(f"Base URL: {Colors.OKBLUE}{self.base_url}{Colors.ENDC}")
        print(f"Authenticated: {Colors.OKGREEN if self.token else Colors.FAIL}{'Yes' if self.token else 'No'}{Colors.ENDC}")
        print(f"User ID: {Colors.OKCYAN}{self.user_id or 'N/A'}{Colors.ENDC}")
        print(f"Email: {Colors.OKCYAN}{self.email or 'N/A'}{Colors.ENDC}")
        if self.token:
            print(f"Token: {Colors.WARNING}{self.token[:30]}...{Colors.ENDC}")
        print(f"\nTest Data: {Colors.OKBLUE}{json.dumps(self.test_data, indent=2)}{Colors.ENDC}")
    
    async def interactive_mode(self):
        """Run in interactive mode"""
        self.print_header("InsanusChat Backend API Tester - Interactive Mode")
        self.print_info("Type 'help' for available commands, 'quit' to exit")
        
        # Initial health check
        await self.test_health()
        
        command_map = {
            'help': self.print_help,
            'register': lambda: self.register_user(),
            'login': lambda: self.login_user(),
            'profile': self.get_profile,
            'agents': self.test_agents,
            'apikeys': self.test_apikeys,
            'mcps': self.test_mcps,
            'snippets': self.test_snippets,
            'chats': self.test_chats,
            'websocket': self.test_websocket,
            'health': self.test_health,
            'all': self.run_all_tests,
            'status': self.print_status,
        }
        
        while True:
            try:
                print(f"\n{Colors.BOLD}>{Colors.ENDC} ", end='')
                command = input().strip().lower()
                
                if command in ['quit', 'exit', 'q']:
                    self.print_info("Goodbye! 👋")
                    break
                
                if not command:
                    continue
                
                if command in command_map:
                    func = command_map[command]
                    if asyncio.iscoroutinefunction(func):
                        await func()
                    else:
                        result = func()
                        if asyncio.iscoroutine(result):
                            await result
                else:
                    self.print_error(f"Unknown command: {command}")
                    self.print_info("Type 'help' for available commands")
                    
            except KeyboardInterrupt:
                print()
                self.print_info("Interrupted. Type 'quit' to exit.")
            except EOFError:
                print()
                break
            except Exception as e:
                self.print_error(f"Error: {e}")


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Comprehensive testing script for InsanusChat Backend API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_api_comprehensive.py
  python test_api_comprehensive.py --url http://localhost:8000
  python test_api_comprehensive.py --url https://api.insanuschat.com
        """
    )
    parser.add_argument(
        '--url',
        default='http://localhost:8000',
        help='Base URL of the API (default: http://localhost:8000)'
    )
    parser.add_argument(
        '--command',
        help='Run a specific command and exit (e.g., "all", "register", "agents")'
    )
    
    args = parser.parse_args()
    
    tester = APITester(base_url=args.url)
    
    if args.command:
        # Run specific command and exit
        command_map = {
            'all': tester.run_all_tests,
            'register': lambda: tester.register_user(),
            'login': lambda: tester.login_user(),
            'profile': tester.get_profile,
            'agents': tester.test_agents,
            'apikeys': tester.test_apikeys,
            'mcps': tester.test_mcps,
            'snippets': tester.test_snippets,
            'chats': tester.test_chats,
            'websocket': tester.test_websocket,
            'health': tester.test_health,
        }
        
        if args.command in command_map:
            func = command_map[args.command]
            await func()
        else:
            print(f"Unknown command: {args.command}")
            sys.exit(1)
    else:
        # Interactive mode
        await tester.interactive_mode()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
