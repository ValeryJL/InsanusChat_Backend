#!/usr/bin/env python3
"""
Create a default mock agent in the database.

This script creates a system-wide default agent that provides mock responses.
All users can use this agent when they don't have their own agents configured.

Usage:
    python scripts/create_default_agent.py
"""

import asyncio
import sys
import os

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from models import PyObjectId
from datetime import datetime


DEFAULT_AGENT_CONFIG = {
    "name": "MockBot",
    "description": "Default mock agent - provides simple automated responses",
    "system_prompt": """You are a helpful AI assistant. You provide clear, concise, and friendly responses.
You acknowledge user messages and provide thoughtful replies. If you don't know something, you say so.""",
    "model": "mock",  # Special marker for mock responses
    "temperature": 0.7,
    "max_tokens": 500,
    "is_system_default": True,  # Special flag to mark this as system default
    "created_at": datetime.utcnow(),
}


MOCK_RESPONSES = [
    "Hello! I'm the default mock agent. How can I help you today?",
    "I understand. Could you tell me more about that?",
    "That's an interesting point. Let me think about that...",
    "I see what you mean. Here's what I think...",
    "Thank you for sharing that with me!",
    "I'm here to help! What would you like to know?",
    "Interesting question! While I'm a mock agent with limited capabilities, I'll do my best to respond.",
    "I appreciate you reaching out. As a default agent, I provide simple responses while you set up your preferred AI models.",
]


async def create_default_agent():
    """Create or update the default mock agent in the database."""
    
    print("🤖 Creating default mock agent...")
    
    try:
        # Get agents collection
        agents_col = database.get_agent_collection()
        
        # Check if default agent already exists
        existing = await agents_col.find_one({"is_system_default": True})
        
        if existing:
            print(f"✓ Default agent already exists: {existing.get('name')} (ID: {existing.get('_id')})")
            
            # Update it to ensure it has latest config
            await agents_col.update_one(
                {"_id": existing["_id"]},
                {"$set": DEFAULT_AGENT_CONFIG}
            )
            print("✓ Updated default agent configuration")
            return str(existing["_id"])
        else:
            # Create new default agent
            agent_doc = DEFAULT_AGENT_CONFIG.copy()
            agent_doc["_id"] = PyObjectId.new()
            
            result = await agents_col.insert_one(agent_doc)
            agent_id = str(result.inserted_id)
            
            print(f"✓ Created default mock agent!")
            print(f"  Name: {agent_doc['name']}")
            print(f"  Description: {agent_doc['description']}")
            print(f"  ID: {agent_id}")
            
            return agent_id
            
    except Exception as e:
        print(f"✗ Error creating default agent: {e}")
        raise


async def main():
    """Main function."""
    print("=" * 70)
    print("Default Agent Setup".center(70))
    print("=" * 70)
    print()
    
    try:
        agent_id = await create_default_agent()
        
        print()
        print("=" * 70)
        print("✓ Setup Complete!".center(70))
        print("=" * 70)
        print()
        print(f"The default mock agent is now available with ID: {agent_id}")
        print()
        print("Users can now:")
        print("  1. Create chats and select this agent")
        print("  2. Send messages that will receive mock responses")
        print("  3. Use this as a fallback while setting up their own agents")
        print()
        
    except Exception as e:
        print(f"\n✗ Setup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
