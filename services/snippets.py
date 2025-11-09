import asyncio
import json
import tempfile
import os
import sys
from typing import Any, Dict, Optional

import logging

from asyncio.subprocess import PIPE, create_subprocess_exec

DEFAULT_SNIPPET_TIMEOUT = 8


async def _run_subprocess_capture(cmd: list[str], stdin_bytes: Optional[bytes], timeout: int) -> Dict[str, Any]:
    try:
        proc = await create_subprocess_exec(*cmd, stdin=PIPE if stdin_bytes is not None else None, stdout=PIPE, stderr=PIPE)
    except FileNotFoundError as e:
        return {"success": False, "error": f"executable_not_found: {e}", "stdout": "", "stderr": ""}
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(stdin_bytes), timeout=timeout)
        stdout_s = stdout.decode(errors="ignore") if stdout else ""
        stderr_s = stderr.decode(errors="ignore") if stderr else ""
        return {"success": True, "returncode": proc.returncode, "stdout": stdout_s, "stderr": stderr_s}
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return {"success": False, "error": "timeout", "stdout": "", "stderr": ""}
    except Exception as e:
        try:
            proc.kill()
        except Exception:
            pass
        return {"success": False, "error": f"exec_error: {e}", "stdout": "", "stderr": ""}


async def execute_snippet(
    snippet: Dict[str, Any],
    input_data: Optional[Any] = None,
    timeout: int = DEFAULT_SNIPPET_TIMEOUT,
    workdir: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a code snippet in a subprocess with timeout and capture.

    snippet: {"language": "python"|"javascript", "code": "..."}
    Returns a dict with success/result/stdout/stderr or error.
    Security note: this runs arbitrary code in a subprocess. For production use a sandbox/container.
    """
    lang = (snippet.get("language") or "javascript").lower()
    code = snippet.get("code") or ""
    stdin_bytes = None
    if input_data is not None:
        try:
            stdin_bytes = json.dumps(input_data).encode()
        except Exception:
            stdin_bytes = str(input_data).encode()

    tmp_dir = workdir or tempfile.gettempdir()
    if lang in ("javascript", "js"):
        fd, path = tempfile.mkstemp(suffix=".js", dir=tmp_dir, text=True)
        os.close(fd)
        wrapper = f"""
const fs = require('fs');
let input = null;
try {{
  const raw = fs.readFileSync(0, 'utf8') || '';
  input = raw ? JSON.parse(raw) : null;
}} catch(e) {{
  input = null;
}}
        (async function(input){{
            try {{
                const inp = input;
                // execute user's code inside an inner async IIFE so `return` works
                const __ret = await (async function(inp){{
                    {code}
                }})(input);
                if (typeof __ret !== 'undefined') {{
                    console.log(JSON.stringify({{success:true,result: __ret}}));
                }}
            }} catch (e) {{
                console.error(JSON.stringify({{success:false,error: String(e)}}));
                process.exit(1);
            }}
        }})(input);
"""
        with open(path, "w", encoding="utf8") as f:
            f.write(wrapper)
        cmd = ["node", path]
        res = await _run_subprocess_capture(cmd, stdin_bytes, timeout)
        if res.get("success") and res.get("stdout"):
            try:
                parsed = json.loads(res["stdout"].strip().splitlines()[-1])
                return {"success": True, "result": parsed.get("result"), "stdout": res["stdout"], "stderr": res["stderr"], "returncode": res.get("returncode")}
            except Exception:
                return {"success": True, "result": res["stdout"], "stdout": res["stdout"], "stderr": res["stderr"], "returncode": res.get("returncode")}
        return {"success": False, "error": res.get("error") or "execution_failed", "stdout": res.get("stdout"), "stderr": res.get("stderr")}

    elif lang in ("python", "py"):
        fd, path = tempfile.mkstemp(suffix=".py", dir=tmp_dir, text=True)
        os.close(fd)
        # indent code inside a function
        indented = "\n".join(("    " + l) for l in code.splitlines()) if code else "    pass"
        wrapper = f"""import sys, json
try:
    raw = sys.stdin.read()
    inp = json.loads(raw) if raw else None
except Exception:
    inp = None

def __snippet_main(inp):
{indented}

try:
    result = __snippet_main(inp)
    try:
        print(json.dumps({{"success":True,"result": result}}))
    except Exception:
        print(json.dumps({{"success":True,"result": str(result)}}))
except Exception as e:
    print(json.dumps({{"success":False,"error": str(e)}}))
    sys.exit(1)
"""
        with open(path, "w", encoding="utf8") as f:
            f.write(wrapper)
        python_exe = sys.executable or "python3"
        cmd = [python_exe, path]
        res = await _run_subprocess_capture(cmd, stdin_bytes, timeout)
        if res.get("success") and res.get("stdout"):
            try:
                parsed = json.loads(res["stdout"].strip().splitlines()[-1])
                return {"success": parsed.get("success", False), "result": parsed.get("result"), "stdout": res["stdout"], "stderr": res["stderr"], "returncode": res.get("returncode")}
            except Exception:
                return {"success": True, "result": res["stdout"], "stdout": res["stdout"], "stderr": res["stderr"], "returncode": res.get("returncode")}
        return {"success": False, "error": res.get("error") or "execution_failed", "stdout": res.get("stdout"), "stderr": res.get("stderr")}
    else:
        return {"success": False, "error": f"unsupported_language: {lang}"}
