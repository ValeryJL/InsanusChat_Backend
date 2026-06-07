"""
Ejecución aislada y segura de Code Snippets (Python / JavaScript / Text Templates) (HU-06).
Garantiza:
1. Limpieza de archivos temporales en disco (`finally: os.unlink`).
2. Sanitización del entorno (`env`) para no filtrar secretos del servidor (`MONGO_URI`, `LOCAL_AUTH_SECRET`, etc.).
3. Interpolación de snippets en `system_prompt` (`SNIPPET:<id>` y `{{snippet_name}}`).
"""
import asyncio
import json
import logging
import os
import re
import sys
import tempfile
import time
from asyncio.subprocess import PIPE, create_subprocess_exec
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_SNIPPET_TIMEOUT = 8

# Variables de entorno del sistema mínimas permitidas para que Python/Node funcionen en Windows/Linux
# sin filtrar ningún secreto de la aplicación (MONGO_URI, LOCAL_AUTH_SECRET, GOOGLE_API_KEY, etc.)
ALLOWED_ENV_KEYS = {
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "LANG",
    "LC_ALL",
}


def _build_isolated_env() -> Dict[str, str]:
    """Construye un entorno limpio sin secretos de la aplicación."""
    safe_env = {k: v for k, v in os.environ.items() if k.upper() in ALLOWED_ENV_KEYS}
    safe_env["PYTHONIOENCODING"] = "utf-8"
    safe_env["PYTHONDONTWRITEBYTECODE"] = "1"
    return safe_env


async def _run_subprocess_capture(cmd: list[str], stdin_bytes: Optional[bytes], timeout: int, cwd: Optional[str] = None) -> Dict[str, Any]:
    start = time.perf_counter()
    safe_env = _build_isolated_env()
    try:
        proc = await create_subprocess_exec(
            *cmd,
            stdin=PIPE if stdin_bytes is not None else None,
            stdout=PIPE,
            stderr=PIPE,
            env=safe_env,
            cwd=cwd,
        )
    except FileNotFoundError as e:
        return {
            "success": False,
            "error": f"executable_not_found: {e}",
            "stdout": "",
            "stderr": "",
            "execution_time_ms": round((time.perf_counter() - start) * 1000, 2),
        }

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(stdin_bytes), timeout=timeout)
        stdout_s = stdout.decode("utf-8", errors="ignore") if stdout else ""
        stderr_s = stderr.decode("utf-8", errors="ignore") if stderr else ""
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": stdout_s,
            "stderr": stderr_s,
            "execution_time_ms": round((time.perf_counter() - start) * 1000, 2),
        }
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return {
            "success": False,
            "error": "timeout",
            "stdout": "",
            "stderr": f"Execution exceeded timeout of {timeout}s",
            "execution_time_ms": round((time.perf_counter() - start) * 1000, 2),
        }
    except Exception as e:
        try:
            proc.kill()
        except Exception:
            pass
        return {
            "success": False,
            "error": f"exec_error: {e}",
            "stdout": "",
            "stderr": str(e),
            "execution_time_ms": round((time.perf_counter() - start) * 1000, 2),
        }


async def execute_snippet(
    snippet: Dict[str, Any],
    input_data: Optional[Any] = None,
    timeout: int = DEFAULT_SNIPPET_TIMEOUT,
    workdir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Ejecuta un snippet de código en un subproceso con entorno aislado, timeout y limpieza garantizada.
    """
    if not isinstance(snippet, dict):
        return {"success": False, "error": "invalid_snippet_object", "stdout": "", "stderr": ""}

    lang = (snippet.get("language") or "python").lower().strip()
    code = snippet.get("code") or ""

    if not code.strip():
        return {"success": False, "error": "empty_code", "stdout": "", "stderr": ""}

    if lang == "text" or snippet.get("type") == "template":
        return {"success": True, "result": code, "stdout": code, "stderr": "", "returncode": 0, "execution_time_ms": 0}

    stdin_bytes = None
    if input_data is not None:
        try:
            if isinstance(input_data, str):
                # Si ya es JSON válido, pasarlo tal cual; si no, serializar como JSON string
                try:
                    json.loads(input_data)
                    stdin_bytes = input_data.encode("utf-8")
                except Exception:
                    stdin_bytes = json.dumps(input_data).encode("utf-8")
            else:
                stdin_bytes = json.dumps(input_data).encode("utf-8")
        except Exception:
            stdin_bytes = str(input_data).encode("utf-8")

    tmp_dir = workdir or tempfile.gettempdir()
    temp_path: Optional[str] = None

    try:
        if lang in ("javascript", "js"):
            fd, temp_path = tempfile.mkstemp(suffix=".js", dir=tmp_dir, text=True)
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
        const __ret = await (async function(inp, input){{
            {code}
        }})(input, input);
        if (typeof __ret !== 'undefined') {{
            console.log(JSON.stringify({{success:true, result: __ret}}));
        }}
    }} catch (e) {{
        console.error(JSON.stringify({{success:false, error: String(e)}}));
        process.exit(1);
    }}
}})(input);
"""
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(wrapper)
            cmd = ["node", temp_path]
            res = await _run_subprocess_capture(cmd, stdin_bytes, timeout, cwd=tmp_dir)
            if res.get("stdout"):
                try:
                    last_line = res["stdout"].strip().splitlines()[-1]
                    parsed = json.loads(last_line)
                    if isinstance(parsed, dict) and "success" in parsed:
                        return {
                            "success": parsed.get("success", True),
                            "result": parsed.get("result"),
                            "stdout": res["stdout"],
                            "stderr": res["stderr"],
                            "returncode": res.get("returncode"),
                            "execution_time_ms": res.get("execution_time_ms"),
                        }
                except Exception:
                    pass
                return {
                    "success": res.get("success", True),
                    "result": res["stdout"].strip(),
                    "stdout": res["stdout"],
                    "stderr": res["stderr"],
                    "returncode": res.get("returncode"),
                    "execution_time_ms": res.get("execution_time_ms"),
                }
            return {
                "success": False,
                "error": res.get("error") or "execution_failed",
                "stdout": res.get("stdout", ""),
                "stderr": res.get("stderr", ""),
                "execution_time_ms": res.get("execution_time_ms"),
            }

        elif lang in ("python", "py"):
            fd, temp_path = tempfile.mkstemp(suffix=".py", dir=tmp_dir, text=True)
            os.close(fd)
            indented = "\n".join(("    " + l) for l in code.splitlines()) if code else "    pass"
            wrapper = f"""import sys, json
try:
    raw = sys.stdin.read()
    inp = json.loads(raw) if raw else None
except Exception:
    inp = None

input_data = inp

def __snippet_main(inp, input_data):
{indented}

try:
    result = __snippet_main(inp, input_data)
    if result is not None:
        try:
            print(json.dumps({{"success": True, "result": result}}, ensure_ascii=False))
        except Exception:
            print(json.dumps({{"success": True, "result": str(result)}}, ensure_ascii=False))
except Exception as e:
    print(json.dumps({{"success": False, "error": str(e)}}, ensure_ascii=False))
    sys.exit(1)
"""
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(wrapper)
            python_exe = sys.executable or "python3"
            cmd = [python_exe, temp_path]
            res = await _run_subprocess_capture(cmd, stdin_bytes, timeout, cwd=tmp_dir)
            if res.get("stdout"):
                lines = res["stdout"].strip().splitlines()
                try:
                    parsed = json.loads(lines[-1])
                    if isinstance(parsed, dict) and "success" in parsed:
                        user_stdout = "\n".join(lines[:-1])
                        final_result = parsed.get("result")
                        if final_result is None and user_stdout:
                            final_result = user_stdout
                        return {
                            "success": parsed.get("success", False),
                            "result": final_result,
                            "error": parsed.get("error"),
                            "stdout": res["stdout"],
                            "stderr": res["stderr"],
                            "returncode": res.get("returncode"),
                            "execution_time_ms": res.get("execution_time_ms"),
                        }
                except Exception:
                    pass
                return {
                    "success": res.get("success", True),
                    "result": res["stdout"].strip(),
                    "stdout": res["stdout"],
                    "stderr": res["stderr"],
                    "returncode": res.get("returncode"),
                    "execution_time_ms": res.get("execution_time_ms"),
                }
            return {
                "success": False,
                "error": res.get("error") or "execution_failed",
                "stdout": res.get("stdout", ""),
                "stderr": res.get("stderr", ""),
                "execution_time_ms": res.get("execution_time_ms"),
            }
        else:
            return {"success": False, "error": f"unsupported_language: {lang}", "stdout": "", "stderr": ""}
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception as e:
                logger.debug("No se pudo eliminar archivo temporal %s: %s", temp_path, e)


async def expand_system_prompt_snippets(
    system_prompt: Any,
    agent_snippets: Optional[List[Dict[str, Any]]] = None,
    user_snippets: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Construye el system_prompt final expandiendo referencias a snippets:
    - Items con formato 'SNIPPET:<id_o_nombre>'
    - Placeholders '{{nombre_snippet}}' dentro del texto
    """
    if not system_prompt:
        return ""

    items = system_prompt if isinstance(system_prompt, list) else [str(system_prompt)]

    by_id: Dict[str, Dict[str, Any]] = {}
    by_name: Dict[str, Dict[str, Any]] = {}

    for coll in (user_snippets or [], agent_snippets or []):
        for s in coll:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("_id", ""))
            sname = str(s.get("name", "")).strip()
            if sid:
                by_id[sid] = s
            if sname:
                by_name[sname] = s

    async def _resolve_snippet(s: Dict[str, Any]) -> str:
        stype = s.get("type", "runtime")
        lang = (s.get("language") or "python").lower()
        code = s.get("code") or ""
        if stype == "template" or lang == "text":
            return str(code)
        res = await execute_snippet(s, timeout=4)
        if res.get("success"):
            val = res.get("result")
            return str(val) if val is not None else (res.get("stdout") or "").strip()
        return f"[Snippet {s.get('name')} error: {res.get('error')}]"

    resolved_parts: List[str] = []
    for raw_part in items:
        part = str(raw_part).strip()
        if part.startswith("SNIPPET:"):
            ref = part.split("SNIPPET:", 1)[1].strip()
            target = by_id.get(ref) or by_name.get(ref)
            if target:
                resolved_parts.append(await _resolve_snippet(target))
            else:
                resolved_parts.append(part)
        else:
            # Reemplazar placeholders {{snippet_name}}
            matches = re.findall(r"\{\{\s*([a-zA-Z0-9_\-]+)\s*\}\}", part)
            for m in set(matches):
                target = by_name.get(m) or by_id.get(m)
                if target:
                    val = await _resolve_snippet(target)
                    part = re.sub(r"\{\{\s*" + re.escape(m) + r"\s*\}\}", val, part)
            resolved_parts.append(part)

    return "\n".join(p for p in resolved_parts if p)
