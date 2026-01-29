#!/usr/bin/env python3
"""
Script to fix agents using invalid/deprecated model names.

This script updates agents in the database that are using deprecated or
invalid model names (like gemini-1.5-pro, gemini-pro, gemini-1.5-flash-8b)
to use the valid gemini-1.5-flash model.

Usage:
    python scripts/fix_invalid_models.py
"""

import os
import sys
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.schemas import PyObjectId

# Invalid model names that need to be updated
INVALID_MODELS = [
    "gemini-pro",
    "gemini-1.5-pro", 
    "gemini-1.5-flash-8b",
    "gemini-2.0-flash-exp",
    "gemini-2.0-flash-thinking-exp",
]

# Valid model to use as replacement
VALID_MODEL = "gemini-1.5-flash"


async def fix_invalid_models():
    """Update all agents with invalid models to use valid model."""
    
    # Get MongoDB connection string
    mongo_uri = os.environ.get("MONGO_URI")
    if not mongo_uri:
        print("❌ Error: MONGO_URI environment variable not set")
        print("Please set MONGO_URI and try again")
        return 1
    
    try:
        # Connect to MongoDB
        print(f"Connecting to MongoDB...")
        client = AsyncIOMotorClient(mongo_uri)
        db = client.get_default_database()
        agents_collection = db["agents"]
        
        # Find agents with invalid models
        print(f"\nSearching for agents with invalid models...")
        query = {"model_selected": {"$in": INVALID_MODELS}}
        
        agents = await agents_collection.find(query).to_list(None)
        
        if not agents:
            print("✓ No agents found with invalid models")
            return 0
        
        print(f"\nFound {len(agents)} agent(s) with invalid models:")
        for agent in agents:
            print(f"  - {agent.get('name', 'Unnamed')} (ID: {agent['_id']}) using model: {agent.get('model_selected')}")
        
        # Ask for confirmation
        response = input(f"\nUpdate all {len(agents)} agent(s) to use '{VALID_MODEL}'? (y/n): ")
        if response.lower() != 'y':
            print("Operation cancelled")
            return 0
        
        # Update agents
        print(f"\nUpdating agents...")
        result = await agents_collection.update_many(
            query,
            {"$set": {"model_selected": VALID_MODEL}}
        )
        
        print(f"✓ Updated {result.modified_count} agent(s) successfully")
        
        # Show updated agents
        print(f"\nVerifying updates...")
        updated_agents = await agents_collection.find(
            {"_id": {"$in": [agent["_id"] for agent in agents]}}
        ).to_list(None)
        
        for agent in updated_agents:
            print(f"  ✓ {agent.get('name', 'Unnamed')} now using: {agent.get('model_selected')}")
        
        return 0
        
    except PyMongoError as e:
        print(f"❌ Database error: {e}")
        return 1
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1
    finally:
        if 'client' in locals():
            client.close()


def main():
    """Main entry point."""
    print("=" * 70)
    print("Fix Invalid Agent Models")
    print("=" * 70)
    print(f"\nThis script will update agents using invalid models:")
    for model in INVALID_MODELS:
        print(f"  - {model}")
    print(f"\nThey will be updated to use: {VALID_MODEL}")
    print()
    
    # Run async function
    exit_code = asyncio.run(fix_invalid_models())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
