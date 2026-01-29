"""
Test script for dynamic model fetching.

This script tests the model_utils module to ensure it can fetch models
from Google API or fall back to hardcoded models.
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.model_utils import get_available_gemini_models, get_model_description

def test_model_fetching():
    """Test fetching models with and without API key."""
    
    print("=" * 70)
    print("Testing Dynamic Model Fetching")
    print("=" * 70)
    
    # Test 1: Without API key (should use fallback)
    print("\n1. Testing without API key (fallback mode):")
    print("-" * 70)
    models = get_available_gemini_models(api_key=None)
    print(f"Found {len(models)} models:")
    for i, (name, desc) in enumerate(models, 1):
        print(f"  {i}. {name}: {desc}")
    
    # Test 2: With API key from environment (if available)
    print("\n2. Testing with API key from environment:")
    print("-" * 70)
    api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key:
        print(f"API key found: {api_key[:10]}...")
        models = get_available_gemini_models(api_key=api_key)
        print(f"Found {len(models)} models:")
        for i, (name, desc) in enumerate(models, 1):
            print(f"  {i}. {name}: {desc}")
    else:
        print("No GOOGLE_API_KEY in environment, skipping API test")
    
    # Test 3: Model description lookup
    print("\n3. Testing model description lookup:")
    print("-" * 70)
    test_models = ["gemini-1.5-flash", "gemini-1.5-pro", "unknown-model"]
    for model in test_models:
        desc = get_model_description(model)
        print(f"  {model}: {desc}")
    
    print("\n" + "=" * 70)
    print("Testing complete!")
    print("=" * 70)

if __name__ == "__main__":
    test_model_fetching()
