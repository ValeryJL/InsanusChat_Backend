"""
Utilities for fetching and managing AI model information.

This module provides functionality to dynamically fetch available models
from Google's Generative AI API, with fallback to hardcoded models.
"""

import os
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

# Fallback models if API fetch fails
FALLBACK_MODELS = [
    ("gemini-1.5-flash", "Gemini 1.5 Flash - Fast and efficient (recommended)"),
    ("gemini-1.5-pro", "Gemini 1.5 Pro - High capability"),
    ("gemini-1.5-flash-8b", "Gemini 1.5 Flash 8B - Lightweight and fast"),
]


def get_available_gemini_models(api_key: Optional[str] = None) -> List[Tuple[str, str]]:
    """
    Fetch available Gemini models from Google API.
    
    Args:
        api_key: Google API key. If None, tries to get from environment.
    
    Returns:
        List of tuples (model_name, description) for available models.
        Falls back to hardcoded list if API call fails.
    
    Examples:
        >>> models = get_available_gemini_models("your-api-key")
        >>> for name, desc in models:
        ...     print(f"{name}: {desc}")
    """
    # Get API key from parameter or environment
    key = api_key or os.environ.get("GOOGLE_API_KEY")
    
    if not key:
        logger.info("No Google API key available, using fallback models")
        return FALLBACK_MODELS
    
    try:
        # Import here to avoid requiring google-generativeai if not used
        import google.generativeai as genai
        
        # Configure the API
        genai.configure(api_key=key)
        
        # Fetch available models
        models = []
        for model in genai.list_models():
            # Only include models that support generateContent
            if 'generateContent' in model.supported_generation_methods:
                model_name = model.name.replace('models/', '')
                
                # Only include Gemini models
                if model_name.startswith('gemini'):
                    # Create description from model metadata
                    description = model.display_name or model_name
                    
                    # Add additional context based on model name
                    if 'flash' in model_name.lower():
                        if '8b' in model_name.lower():
                            description += " - Lightweight and fast"
                        else:
                            description += " - Fast and efficient"
                    elif 'pro' in model_name.lower():
                        description += " - High capability"
                    
                    models.append((model_name, description))
        
        if models:
            logger.info(f"Successfully fetched {len(models)} Gemini models from API")
            # Sort models: newest first (assuming higher version numbers are newer)
            # Put recommended models (flash) first
            models.sort(key=lambda x: (
                '1.5-flash' not in x[0],  # Flash models first
                'flash-8b' in x[0],  # 8b models last
                x[0]
            ))
            return models
        else:
            logger.warning("No Gemini models found in API response, using fallback")
            return FALLBACK_MODELS
            
    except ImportError:
        logger.warning("google-generativeai not installed, using fallback models")
        return FALLBACK_MODELS
    except Exception as e:
        logger.warning(f"Error fetching models from Google API: {e}, using fallback")
        return FALLBACK_MODELS


def get_model_description(model_name: str) -> str:
    """
    Get a human-readable description for a model name.
    
    Args:
        model_name: The model identifier (e.g., 'gemini-1.5-flash')
    
    Returns:
        A description of the model
    """
    # Try to fetch from API first
    models = get_available_gemini_models()
    for name, desc in models:
        if name == model_name:
            return desc
    
    # Fallback to basic description
    if 'flash' in model_name.lower():
        if '8b' in model_name.lower():
            return f"{model_name} - Lightweight and fast"
        else:
            return f"{model_name} - Fast and efficient"
    elif 'pro' in model_name.lower():
        return f"{model_name} - High capability"
    else:
        return model_name
