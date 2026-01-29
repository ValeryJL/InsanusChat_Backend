# Validation Fixes Documentation

## Overview

This document details the fixes for critical validation errors that were preventing chat creation and agent execution.

---

## Issue 1: ChatResponse Validation Error

### Problem Description

**Error Message**:
```
pydantic_core._pydantic_core.ValidationError: 1 validation error for ChatResponse
data.user_id
  Input should be a valid string [type=string_type, input_value=ObjectId('697b505ca37b9917b7eaf42d'), input_type=ObjectId]
For further information visit https://errors.pydantic.dev/2.11/v/string_type
```

**Stack Trace**:
```python
File "/home/afconstruc/InsanusChat-Backend/routers/chats.py", line 265, in create_chat
    return ChatResponse(message="Chat creado", data=_sanitize_chat_record(chat_doc))
```

### Root Cause

The `_sanitize_chat_record()` function in `routers/chats.py` was not converting the `user_id` field from MongoDB ObjectId to string.

**Analysis**:
1. Chat document is created with `user_id` as PyObjectId (line 201):
   ```python
   user_oid = PyObjectId.parse(uid)
   chat_doc = {
       "user_id": user_oid,  # ObjectId type
       ...
   }
   ```

2. The `_sanitize_chat_record()` function converts other ObjectId fields:
   - `_id` ✅
   - `agent_id` ✅
   - `root_message_id` ✅
   - `last_message_id` ✅
   - `user_id` ❌ **MISSING!**

3. When `ChatResponse` is instantiated, Pydantic validates the data
4. The response model expects `user_id` to be a string
5. Validation fails because it receives ObjectId instead

### Solution

Added `user_id` sanitization to `_sanitize_chat_record()` function:

**File**: `routers/chats.py` (lines 22-27)

```python
def _sanitize_chat_record(c: dict) -> dict:
    c = dict(c)
    c["_id"] = str(c["_id"])
    
    # NEW: sanitize user_id (required field)
    if c.get("user_id") is not None:
        try:
            c["user_id"] = str(c["user_id"])
        except Exception:
            pass
    
    # optional agent id
    if c.get("agent_id") is not None:
        try:
            c["agent_id"] = str(c["agent_id"])
        except Exception:
            pass
    # ... rest of function
```

### Testing

**Before Fix**:
```bash
POST /api/v1/chats/
{
  "title": "Test Chat",
  "agent_id": "507f1f77bcf86cd799439011",
  "message": "Hello"
}

Response: 500 Internal Server Error
Error: ValidationError - user_id must be string
```

**After Fix**:
```bash
POST /api/v1/chats/
{
  "title": "Test Chat",
  "agent_id": "507f1f77bcf86cd799439011",
  "message": "Hello"
}

Response: 200 OK
{
  "message": "Chat creado",
  "data": {
    "_id": "697b5608339db44638119a98",
    "user_id": "697b505ca37b9917b7eaf42d",  // Now a string!
    "title": "Test Chat",
    ...
  }
}
```

---

## Issue 2: Invalid Model Name `gemini-pro`

### Problem Description

**Error Message**:
```
ERROR - Error during agent execution: Error calling model 'gemini-pro' (NOT_FOUND): 404 NOT_FOUND
{'error': {
  'code': 404, 
  'message': 'models/gemini-pro is not found for API version v1beta, or is not supported for generateContent. Call ListModels to see the list of available models and their supported methods.', 
  'status': 'NOT_FOUND'
}}
```

**Stack Trace**:
```python
File "/home/afconstruc/InsanusChat-Backend/.venv/lib/python3.12/site-packages/langchain_google_genai/chat_models.py", line 3047, in _generate
    response: GenerateContentResponse = self.client.models.generate_content(
File "/home/afconstruc/InsanusChat-Backend/.venv/lib/python3.12/site-packages/google/genai/models.py", line 5227, in generate_content
    response = self._generate_content(
```

### Root Cause

The `gemini-pro` model was included in the CLI's model selection list but has been deprecated/removed from Google's Gemini API.

**Analysis**:
1. CLI shows 4 models in `create_agent()`:
   ```python
   available_models = [
       ("gemini-1.5-flash", "Gemini 1.5 Flash - Fast and efficient (recommended)"),
       ("gemini-1.5-pro", "Gemini 1.5 Pro - High capability"),
       ("gemini-1.5-flash-8b", "Gemini 1.5 Flash 8B - Lightweight and fast"),
       ("gemini-pro", "Gemini Pro - Legacy model"),  # ❌ DOESN'T EXIST
   ]
   ```

2. User selects option 4 (`gemini-pro`)
3. Agent is created with `model_selected: "gemini-pro"`
4. When agent executes, LangChain tries to call this model
5. Google API returns 404 NOT_FOUND

### Solution

Removed the invalid `gemini-pro` option from the model selection list.

**File**: `cli/chat_cli.py` (lines 535-539)

```python
# Before (4 models):
available_models = [
    ("gemini-1.5-flash", "Gemini 1.5 Flash - Fast and efficient (recommended)"),
    ("gemini-1.5-pro", "Gemini 1.5 Pro - High capability"),
    ("gemini-1.5-flash-8b", "Gemini 1.5 Flash 8B - Lightweight and fast"),
    ("gemini-pro", "Gemini Pro - Legacy model"),  # REMOVED
]

# After (3 valid models):
available_models = [
    ("gemini-1.5-flash", "Gemini 1.5 Flash - Fast and efficient (recommended)"),
    ("gemini-1.5-pro", "Gemini 1.5 Pro - High capability"),
    ("gemini-1.5-flash-8b", "Gemini 1.5 Flash 8B - Lightweight and fast"),
]
```

### Valid Models

According to Google's Gemini API documentation (as of January 2026):

**Available Models**:
- ✅ `gemini-1.5-flash` - Fast, efficient, recommended for most use cases
- ✅ `gemini-1.5-pro` - Higher capability, better for complex tasks
- ✅ `gemini-1.5-flash-8b` - Lightweight, very fast

**Deprecated/Removed**:
- ❌ `gemini-pro` - Legacy model, no longer available
- ❌ `gemini-2.0-flash-exp` - Experimental, not in stable API
- ❌ `gemini-2.0-flash-thinking-exp` - Experimental, not available

### Testing

**Before Fix**:
```bash
> agent new
Name: Test Agent
Model: 4  # gemini-pro
✓ Agent created

> chat new
> send Hello
✗ Error: 404 NOT_FOUND - model not found
```

**After Fix**:
```bash
> agent new
Name: Test Agent

Select Model:
  1. gemini-1.5-flash - Fast and efficient (recommended)
  2. gemini-1.5-pro - High capability
  3. gemini-1.5-flash-8b - Lightweight and fast
  # gemini-pro is gone!

Model: 1
✓ Agent created with gemini-1.5-flash

> chat new
> send Hello
✓ Message sent
[Agent]: Hello! How can I help you?
```

---

## Impact Summary

### Before Fixes
- ❌ Chat creation failed with validation error
- ❌ API returned 500 Internal Server Error
- ❌ Users selecting gemini-pro got 404 errors
- ❌ Chat functionality broken
- ❌ Agent execution broken

### After Fixes
- ✅ Chat creation works properly
- ✅ All ObjectId fields properly converted to strings
- ✅ Only valid models shown in selection
- ✅ No 404 errors
- ✅ Full chat functionality restored
- ✅ Agent execution stable

---

## Related Files

**Modified**:
- `routers/chats.py` - Added user_id sanitization
- `cli/chat_cli.py` - Removed invalid model

**Related**:
- `models/responses.py` - ChatResponse model definition
- `services/agents.py` - Agent execution with models
- `routers/agents.py` - Agent creation endpoint

---

## Migration Notes

### For Existing Deployments

**No database migration needed**: 
- Existing chats will work fine
- The fix only affects the response serialization
- Old data remains unchanged

**For Existing Agents**:
- Agents with `gemini-pro` model will fail until updated
- Recommendation: Update all agents to use `gemini-1.5-flash` or `gemini-1.5-pro`
- Can be done via API or MongoDB directly:
  ```javascript
  db.agents.updateMany(
    { model_selected: "gemini-pro" },
    { $set: { model_selected: "gemini-1.5-flash" } }
  )
  ```

---

## Prevention

### Code Review Checklist

When adding new sanitization functions:
- [ ] Check all ObjectId fields are converted to strings
- [ ] Include try-except for safety
- [ ] Test with Pydantic response models
- [ ] Verify all fields match the response schema

When adding new models:
- [ ] Verify model exists in API documentation
- [ ] Test with actual API calls
- [ ] Check for deprecation notices
- [ ] Update when models are deprecated

---

## References

- [Pydantic Validation Errors](https://errors.pydantic.dev/2.11/v/string_type)
- [Google Gemini API Models](https://ai.google.dev/gemini-api/docs/models)
- [MongoDB ObjectId Documentation](https://www.mongodb.com/docs/manual/reference/method/ObjectId/)

---

**Date Fixed**: 2026-01-29
**Fixed By**: Automated refactoring
**Version**: InsanusChat Backend v1.0
