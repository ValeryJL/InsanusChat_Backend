# Fix for Model 404 Errors

## Problem Statement

Agents were failing with 404 NOT_FOUND errors when executing:

```
Error calling model 'gemini-1.5-pro' (NOT_FOUND): 404 NOT_FOUND. 
{'error': {'code': 404, 'message': 'models/gemini-1.5-pro is not found for API version v1beta, or is not supported for generateContent. Call ListModels to see the list of available models and their supported methods.', 'status': 'NOT_FOUND'}}
```

## Root Cause

### Issue 1: Invalid Models in Fallback List

The `FALLBACK_MODELS` list in `utils/model_utils.py` contained models that are no longer available in Google's Generative AI API:

- `gemini-1.5-pro` - Deprecated or removed from API
- `gemini-1.5-flash-8b` - Not consistently available across all regions

**Impact**: When the dynamic model fetch failed (no API key, network error, import error), the system fell back to the hardcoded list, which contained invalid models. This caused agents to be created with invalid model names, leading to 404 errors during execution.

### Issue 2: Existing Agents with Invalid Models

Agents created before this fix may have been assigned invalid model names, either from:
- The old fallback list
- Manual selection of now-deprecated models
- Legacy model names from earlier versions

## Solution

### 1. Updated Fallback Models

**File**: `utils/model_utils.py`

**Before**:
```python
FALLBACK_MODELS = [
    ("gemini-1.5-flash", "Gemini 1.5 Flash - Fast and efficient (recommended)"),
    ("gemini-1.5-pro", "Gemini 1.5 Pro - High capability"),  # ❌ INVALID
    ("gemini-1.5-flash-8b", "Gemini 1.5 Flash 8B - Lightweight and fast"),  # ❌ INCONSISTENT
]
```

**After**:
```python
# Only includes models verified to work with Google's Generative AI API
FALLBACK_MODELS = [
    ("gemini-1.5-flash", "Gemini 1.5 Flash - Fast and efficient (recommended)"),
]
```

**Rationale**:
- Keep only the most reliable, widely available model
- If API fetch works, users get the full list of current models
- If API fetch fails, users get one guaranteed-to-work model
- Eliminates risk of 404 errors in fallback scenarios

### 2. Migration Script for Existing Agents

**File**: `scripts/fix_invalid_models.py`

A script to automatically update existing agents that use deprecated model names.

**Features**:
- Scans database for agents with invalid models
- Shows affected agents before making changes
- Requires user confirmation
- Batch updates all affected agents
- Verifies updates succeeded

**Invalid models detected**:
- `gemini-pro` (legacy)
- `gemini-1.5-pro` (deprecated)
- `gemini-1.5-flash-8b` (inconsistent)
- `gemini-2.0-flash-exp` (experimental, not available)
- `gemini-2.0-flash-thinking-exp` (experimental, not available)

## How to Fix Existing Deployments

### Step 1: Update Code

Pull the latest changes:
```bash
git pull origin copilot/refactor-agents-code-and-implement-mcps
```

### Step 2: Run Migration Script

Fix existing agents with invalid models:

```bash
# Set MongoDB connection string
export MONGO_URI="mongodb+srv://user:pass@cluster.mongodb.net/database"

# Run the migration script
python scripts/fix_invalid_models.py
```

**Example Output**:
```
======================================================================
Fix Invalid Agent Models
======================================================================

This script will update agents using invalid models:
  - gemini-pro
  - gemini-1.5-pro
  - gemini-1.5-flash-8b
  - gemini-2.0-flash-exp
  - gemini-2.0-flash-thinking-exp

They will be updated to use: gemini-1.5-flash

Connecting to MongoDB...

Searching for agents with invalid models...

Found 3 agent(s) with invalid models:
  - Gemini (ID: 697b57ed673477550d32f094) using model: gemini-1.5-pro
  - Assistant (ID: 698a1234567890abcdef1234) using model: gemini-pro
  - Helper (ID: 699b9876543210fedcba9876) using model: gemini-1.5-flash-8b

Update all 3 agent(s) to use 'gemini-1.5-flash'? (y/n): y

Updating agents...
✓ Updated 3 agent(s) successfully

Verifying updates...
  ✓ Gemini now using: gemini-1.5-flash
  ✓ Assistant now using: gemini-1.5-flash
  ✓ Helper now using: gemini-1.5-flash
```

### Step 3: Restart Backend

Restart your backend application to use the updated code:

```bash
# If using uvicorn directly
uvicorn backend:app --reload

# If using systemd
sudo systemctl restart insanuschat-backend

# If using Docker
docker-compose restart backend
```

### Step 4: Verify

Test agent execution:

```bash
# Using CLI
python cli/chat_cli.py
> login
> chat new
> send Hello
# Should work without 404 errors
```

## Prevention

### For New Agents

The system now:
1. **Tries to fetch models from Google API** (when API key available)
2. **Shows only currently available models** to users
3. **Falls back to verified model** if API unavailable
4. **Never shows invalid models** in selection list

### For Future Updates

When Google releases new models or deprecates old ones:

**With API Key** (recommended):
- System automatically fetches latest models
- Users see current available models
- No code changes needed

**Without API Key** (fallback):
- Update `FALLBACK_MODELS` in `utils/model_utils.py`
- Only include verified, working models
- Test before deployment

## Testing

### Verify Fallback Models

Test that fallback works correctly:

```python
from utils.model_utils import get_available_gemini_models

# Test without API key (should use fallback)
models = get_available_gemini_models(api_key=None)
print(models)
# Expected: [("gemini-1.5-flash", "...")]

# Test with invalid API key (should use fallback)
models = get_available_gemini_models(api_key="invalid-key")
print(models)
# Expected: [("gemini-1.5-flash", "...")]
```

### Verify Model Works

Test that the fallback model actually works:

```python
import google.generativeai as genai

genai.configure(api_key="your-valid-api-key")
model = genai.GenerativeModel("gemini-1.5-flash")
response = model.generate_content("Hello")
print(response.text)
# Should work without errors
```

## Troubleshooting

### Script Fails with "MONGO_URI not set"

**Problem**: Environment variable not configured

**Solution**:
```bash
export MONGO_URI="your-connection-string"
# Then run script again
```

### Script Finds No Agents

**Problem**: No agents exist with invalid models

**Solution**: No action needed, system is clean

### Agent Still Fails with 404

**Possible Causes**:
1. Agent not updated by script (check agent in database)
2. Different invalid model name (add to INVALID_MODELS list in script)
3. API key issue (verify API key is valid)

**Debug**:
```bash
# Check agent in database
mongosh "mongodb+srv://..."
use your_database
db.agents.find({ model_selected: "gemini-1.5-pro" })

# Manually update if needed
db.agents.updateOne(
  { _id: ObjectId("agent-id-here") },
  { $set: { model_selected: "gemini-1.5-flash" } }
)
```

## Related Documentation

- **Dynamic Model Selection**: `docs/DYNAMIC_MODEL_SELECTION.md`
- **Agent Improvements**: `docs/AGENT_IMPROVEMENTS.md`
- **Critical Fixes**: `docs/CRITICAL_FIXES.md`

## Summary

**Issue**: Agents failing with 404 errors due to invalid model names
**Root Cause**: Fallback list contained deprecated models
**Fix**: Updated fallback to single reliable model + migration script
**Action Required**: Run migration script on existing deployments
**Status**: ✅ RESOLVED

---

**Last Updated**: 2026-01-29  
**Version**: 1.0  
**Author**: AI Assistant
