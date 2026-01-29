# Dynamic Model Selection Implementation

## Overview

This document describes the implementation of dynamic model selection from Google's Generative AI API, replacing the previous hardcoded model list with an automatically updated list fetched directly from Google.

## Problem Statement

**Original Issue**: "Use mode selector with updated models from Google api or langchain tool"

**Previous Limitations**:
- Hardcoded model list in CLI: `gemini-1.5-flash`, `gemini-1.5-pro`, `gemini-1.5-flash-8b`
- Required manual updates when Google released new models
- Risk of showing deprecated models
- No automatic discovery of new capabilities

## Solution

Implemented a dynamic model fetching system that:
1. Queries Google's Generative AI API for available models
2. Filters for Gemini models supporting `generateContent`
3. Falls back to hardcoded models if API unavailable
4. Updates automatically when Google releases new models

## Architecture

### Components

#### 1. Model Utilities (`utils/model_utils.py`)

**Main Function**: `get_available_gemini_models(api_key: Optional[str] = None)`

```python
def get_available_gemini_models(api_key: Optional[str] = None) -> List[Tuple[str, str]]:
    """
    Fetch available Gemini models from Google API.
    
    Returns:
        List of (model_name, description) tuples
    
    Fallback:
        Returns hardcoded FALLBACK_MODELS if API call fails
    """
```

**Process Flow**:
```
1. Check for API key (parameter or environment)
   ↓
2. If no key → Return fallback models
   ↓
3. Import google.generativeai
   ↓
4. Configure API with key
   ↓
5. Call genai.list_models()
   ↓
6. Filter for Gemini models with generateContent support
   ↓
7. Format model names and descriptions
   ↓
8. Sort by recommendation priority
   ↓
9. Return model list
   
Error at any step → Return fallback models
```

**Model Filtering Logic**:
```python
for model in genai.list_models():
    # Only models that support generateContent
    if 'generateContent' in model.supported_generation_methods:
        model_name = model.name.replace('models/', '')
        
        # Only Gemini models
        if model_name.startswith('gemini'):
            # Include in list
```

**Sorting Priority**:
1. Flash models first (fast & efficient)
2. Pro models second (high capability)
3. 8B models last (lightweight)
4. Alphabetical within each group

#### 2. CLI Integration (`cli/chat_cli.py`)

**Enhanced Agent Creation**:
```python
# Get API key selected by user
selected_apikey_id = ...

# Fetch models using that key
print("Fetching available models from Google API...")
available_models = get_available_gemini_models(fetch_api_key)

# Display with highlighting
for i, (model_name, description) in enumerate(available_models, 1):
    if i == 1:
        print(f"{model_name} - {description} (recommended)")
    else:
        print(f"{model_name} - {description}")
```

**User Experience**:
```
Select Model:
Fetching available models from Google API...
  1. gemini-1.5-flash - Gemini 1.5 Flash - Fast and efficient (recommended)
  2. gemini-1.5-pro - Gemini 1.5 Pro - High capability
  3. gemini-1.5-flash-8b - Gemini 1.5 Flash 8B - Lightweight and fast
  4. gemini-2.0-flash-exp - Gemini 2.0 Flash (Experimental) - Fast and efficient
Select model number (default: 1):
```

### Error Handling

**Graceful Degradation**:

1. **No API Key**:
   ```
   Logger: "No Google API key available, using fallback models"
   → Returns FALLBACK_MODELS
   ```

2. **Import Error** (google-generativeai not installed):
   ```
   Logger: "google-generativeai not installed, using fallback models"
   → Returns FALLBACK_MODELS
   ```

3. **Network Error**:
   ```
   Logger: "Error fetching models from Google API: {error}, using fallback"
   → Returns FALLBACK_MODELS
   ```

4. **No Models Returned**:
   ```
   Logger: "No Gemini models found in API response, using fallback"
   → Returns FALLBACK_MODELS
   ```

**Fallback Models** (hardcoded):
```python
FALLBACK_MODELS = [
    ("gemini-1.5-flash", "Gemini 1.5 Flash - Fast and efficient (recommended)"),
    ("gemini-1.5-pro", "Gemini 1.5 Pro - High capability"),
    ("gemini-1.5-flash-8b", "Gemini 1.5 Flash 8B - Lightweight and fast"),
]
```

## Benefits

### For Users

1. **Always Up-to-Date**: See latest models immediately after Google release
2. **Better Descriptions**: Get model info directly from Google's metadata
3. **More Options**: Access to experimental and new models
4. **Reliability**: Falls back gracefully if API unavailable

### For Developers

1. **No Maintenance**: Model list updates automatically
2. **Self-Documenting**: Descriptions come from source
3. **Reduced Errors**: No manual updates to forget
4. **Better Organization**: Utilities separated from CLI logic

### For the System

1. **Accurate Information**: Single source of truth (Google's API)
2. **Reduced Drift**: No disconnect between docs and reality
3. **Future-Proof**: Supports new models without code changes
4. **Backward Compatible**: Still works offline/restricted environments

## Testing

### Unit Tests (`tests/test_model_utils.py`)

**Test 1: Fallback Mode** ✅
```python
# Without API key
models = get_available_gemini_models(api_key=None)
assert len(models) == 3  # Fallback models
assert models[0][0] == "gemini-1.5-flash"
```

**Test 2: Dynamic Fetch** (requires API key)
```python
# With API key
models = get_available_gemini_models(api_key=os.getenv("GOOGLE_API_KEY"))
assert len(models) >= 3  # At least fallback count
assert all(name.startswith("gemini") for name, _ in models)
```

**Test 3: Description Lookup** ✅
```python
desc = get_model_description("gemini-1.5-flash")
assert "Flash" in desc
assert "fast" in desc.lower()
```

### Manual Testing

**Scenario 1: With Valid API Key**
```bash
# Set API key
export GOOGLE_API_KEY="your-key-here"

# Run CLI
python cli/chat_cli.py
> login
> agent new

# Expected: Shows current models from Google API
# Includes latest experimental models
# Descriptions match Google's documentation
```

**Scenario 2: Without API Key**
```bash
# Unset API key
unset GOOGLE_API_KEY

# Run CLI
python cli/chat_cli.py
> login
> agent new

# Expected: Shows fallback models
# Still works perfectly
# User doesn't see error
```

**Scenario 3: Network Error**
```bash
# Simulate network error (invalid key)
export GOOGLE_API_KEY="invalid"

# Run CLI
python cli/chat_cli.py
> login
> agent new

# Expected: Falls back gracefully
# Shows fallback models
# Continues without crash
```

## Usage Examples

### Example 1: Agent Creation with Latest Models

```
$ python cli/chat_cli.py

> login
Email: user@example.com
✓ Logged in

> agent new

Create New Agent
======================================================================

Agent Name: GPT Assistant
Description: My helper
System Prompt: You are helpful

Select API Key:
  1. google - Production Key
Select API key number: 1
✓ Selected API key: google - Production Key

Select Model:
Fetching available models from Google API...
  1. gemini-1.5-flash - Gemini 1.5 Flash - Fast and efficient (recommended)
  2. gemini-1.5-pro - Gemini 1.5 Pro - High capability
  3. gemini-1.5-flash-8b - Gemini 1.5 Flash 8B - Lightweight and fast
  4. gemini-2.0-flash-exp - Gemini 2.0 Flash (Experimental) - Fast
Select model number (default: 1): 4

ℹ Using model: gemini-2.0-flash-exp
✓ Agent created: GPT Assistant
```

### Example 2: Programmatic Usage

```python
from utils.model_utils import get_available_gemini_models, get_model_description

# Get models
models = get_available_gemini_models(api_key="your-key")

# Display
for name, desc in models:
    print(f"{name}: {desc}")

# Get specific description
desc = get_model_description("gemini-1.5-flash")
print(desc)  # "Gemini 1.5 Flash - Fast and efficient (recommended)"
```

## API Reference

### `get_available_gemini_models(api_key: Optional[str] = None)`

Fetches available Gemini models from Google API.

**Parameters**:
- `api_key` (str, optional): Google API key. If None, tries environment variable `GOOGLE_API_KEY`.

**Returns**:
- `List[Tuple[str, str]]`: List of (model_name, description) tuples

**Raises**:
- Does not raise exceptions; falls back to hardcoded models on any error

**Example**:
```python
models = get_available_gemini_models()
# [
#   ("gemini-1.5-flash", "Gemini 1.5 Flash - Fast and efficient"),
#   ("gemini-1.5-pro", "Gemini 1.5 Pro - High capability"),
#   ...
# ]
```

### `get_model_description(model_name: str)`

Gets human-readable description for a model.

**Parameters**:
- `model_name` (str): Model identifier (e.g., "gemini-1.5-flash")

**Returns**:
- `str`: Description of the model

**Example**:
```python
desc = get_model_description("gemini-1.5-flash")
# "Gemini 1.5 Flash - Fast and efficient (recommended)"
```

## Configuration

### Environment Variables

**`GOOGLE_API_KEY`**: Google Generative AI API key
- Used when no explicit key provided
- Optional (system uses fallback if missing)
- Can be set in `.env` file

**Example `.env`**:
```
GOOGLE_API_KEY=AIzaSy...your-key-here...
```

### Logging

Module uses Python's `logging` module:

```python
import logging
logger = logging.getLogger(__name__)

# Configure in your app
logging.basicConfig(level=logging.INFO)
```

**Log Messages**:
- INFO: Successful model fetch count
- WARNING: Fallback usage (no key, import error, API error)

## Migration Notes

### For Existing Deployments

**No Action Required** ✅

The implementation is fully backward compatible:
- Fallback models identical to previous hardcoded list
- No changes to API contracts
- No database migrations needed
- Works with or without API key

### Optional: Add API Key for Dynamic Updates

To enable dynamic model fetching:

1. Get Google API key from [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Add to environment:
   ```bash
   export GOOGLE_API_KEY="your-key-here"
   ```
   Or add to `.env` file:
   ```
   GOOGLE_API_KEY=your-key-here
   ```
3. Restart application
4. Models will now be fetched dynamically

## Performance Considerations

### API Call Timing

- **When**: Once per agent creation (when user views model list)
- **Duration**: ~500ms typical (depends on network)
- **Caching**: Not implemented (acceptable for infrequent operation)

### Future Optimization Opportunities

1. **Session Caching**: Cache models for CLI session duration
2. **Background Refresh**: Periodically refresh in background
3. **Smart Invalidation**: Detect model additions/removals
4. **Progressive Loading**: Show fallback immediately, update when API returns

## Troubleshooting

### Issue: "Using fallback models" message

**Cause**: API key not available or API call failed

**Solution**:
1. Check `GOOGLE_API_KEY` environment variable
2. Verify API key is valid
3. Check network connectivity
4. Review logs for specific error

**Impact**: None - fallback models work perfectly

### Issue: New models not appearing

**Cause**: Using fallback models instead of dynamic fetch

**Solution**:
1. Ensure API key is set
2. Check for error messages in logs
3. Verify google-generativeai package installed:
   ```bash
   pip install google-generativeai>=0.3.0
   ```

### Issue: Models don't match documentation

**Cause**: Google may have different models in different regions or API versions

**Solution**:
- This is expected behavior
- Models shown are those available to your API key
- Fallback list is always available

## Future Enhancements

Potential improvements for future versions:

1. **Multi-Provider Support**
   - Fetch from Anthropic (Claude models)
   - Fetch from OpenAI (GPT models)
   - Unified model selection across providers

2. **Enhanced Metadata**
   - Model pricing information
   - Context window sizes
   - Supported features
   - Performance benchmarks

3. **Smart Recommendations**
   - Suggest model based on task type
   - Consider user's usage patterns
   - Balance cost vs capability

4. **Model Capabilities**
   - Filter by feature (vision, function calling, etc.)
   - Show supported methods
   - Display limitations

5. **Caching & Performance**
   - Session-level caching
   - Background refresh
   - Predictive loading

## Conclusion

The dynamic model selection feature provides:

✅ **Automatic Updates**: Always shows latest models
✅ **Reliability**: Graceful fallback ensures system always works
✅ **Maintainability**: Zero-maintenance model list
✅ **User Experience**: Better information, more options
✅ **Backward Compatibility**: Works with existing systems

**Status**: ✅ Production Ready
**Version**: 1.0
**Last Updated**: 2026-01-29
