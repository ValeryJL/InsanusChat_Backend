"""
Servicio de Gestión de Equipos de Ejecución (Workstation Nodes), Túnel RPC por WebSocket
y Motor de Operaciones de Workspace (Filesystem, Unified Diffs, Terminal, Git y HITL Approvals)
(HU-20, HU-22, HU-25, HU-26, HU-27).
"""
import asyncio
from datetime import datetime
import difflib
import json
import logging
import os
from pathlib import Path
import platform
import re
import subprocess
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import WebSocket

logger = logging.getLogger(__name__)

IGNORED_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".pytest_cache",
    ".mypy_cache",
    ".idea",
}

IGNORED_EXTENSIONS = {".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe", ".bin", ".lock"}

# Patrones destructivos de sistema bloqueados por el Guardrail de Terminal Remota Segura (HU-26)
BLOCKED_COMMAND_PATTERNS = [
    r"\brm\s+-rf\s+/\s*$",
    r"\brm\s+-rf\s+/\*",
    r"\bformat\s+[a-zA-Z]:",
    r"\bmkfs\.",
    r"\bshutdown\b",
    r"\breboot\b",
    r":\(\)\{\s*:\|:&\s*\};:",
]


def validate_safe_terminal_command(command_line: str) -> None:
    """HU-26: Valida que el comando remoto no contenga instrucciones destructivas de nivel sistema operativo."""
    cmd = (command_line or "").strip()
    if not cmd:
        raise ValueError("El comando no puede estar vacío")
    for pat in BLOCKED_COMMAND_PATTERNS:
        if re.search(pat, cmd, re.IGNORECASE):
            raise PermissionError(f"Comando bloqueado por política de Terminal Remota Segura: '{cmd}'")


def _default_workspaces_root() -> Path:
    env_root = os.environ.get("WORKSPACES_ROOT")
    if env_root and os.path.exists(env_root):
        return Path(env_root).resolve()
    if os.path.exists("/workspaces"):
        return Path("/workspaces").resolve()
    # Fallback: carpeta padre del backend o carpeta local ./workspaces
    parent = Path(__file__).resolve().parent.parent.parent
    if parent.exists() and any((parent / p).exists() for p in ("InsanusChat_Backend", "InsanusChat_Frontend")):
        return parent
    local_ws = Path(__file__).resolve().parent.parent / "workspaces"
    local_ws.mkdir(parents=True, exist_ok=True)
    return local_ws.resolve()


def compute_unified_diff(old_text: str, new_text: str, rel_path: str) -> str:
    """Genera un Unified Diff estándar estilo Git/VS Code entre dos versiones de un archivo."""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{rel_path}",
        tofile=f"b/{rel_path}",
        lineterm="\n",
    )
    return "".join(diff)


class LocalWorkspaceExecutor:
    """
    Ejecutor nativo de operaciones de Filesystem, Diffs, Búsqueda, Terminal y Git
    sobre el directorio de proyectos local o montado.
    """

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir: Path = (root_dir or _default_workspaces_root()).resolve()
        self.expose_to_cloud: bool = True
        self.allow_remote_terminal: bool = True
        self.allowed_workspaces: Optional[List[str]] = None
        self.vscode_server_url: Optional[str] = os.environ.get("VSCODE_SERVER_URL", None)
        self.bg_processes: Dict[str, Dict[str, Any]] = {}

    def _resolve_workspace_dir(self, workspace: str) -> Path:
        if not workspace or workspace in (".", "/"):
            return self.root_dir
        clean_name = workspace.strip().lstrip("/\\")
        candidate = (self.root_dir / clean_name).resolve()
        if not str(candidate).startswith(str(self.root_dir)):
            raise ValueError(f"Acceso denegado fuera de la raíz de proyectos: {workspace}")
        if self.allowed_workspaces is not None and clean_name not in self.allowed_workspaces:
            raise ValueError(f"El proyecto '{clean_name}' no está en la lista blanca de exposición")
        return candidate

    def resolve_workspace_dir(self, workspace: str) -> Path:
        ws_dir = self._resolve_workspace_dir(workspace)
        if not ws_dir.exists():
            ws_dir.mkdir(parents=True, exist_ok=True)
        return ws_dir

    def _resolve_file_path(self, workspace: str, rel_path: str) -> Tuple[Path, Path]:
        ws_dir = self._resolve_workspace_dir(workspace)
        clean_rel = (rel_path or ".").strip().lstrip("/\\")
        target = (ws_dir / clean_rel).resolve()
        if not str(target).startswith(str(ws_dir)):
            raise ValueError(f"Ruta inválida fuera del workspace '{workspace}': {rel_path}")
        return ws_dir, target

    def list_workspaces(self) -> List[Dict[str, Any]]:
        if not self.root_dir.exists():
            self.root_dir.mkdir(parents=True, exist_ok=True)
        items: List[Dict[str, Any]] = []
        # Incluir el propio directorio raíz como workspace seleccionable
        items.append(
            {
                "name": self.root_dir.name,
                "path": ".",
                "full_path": str(self.root_dir),
                "is_git": (self.root_dir / ".git").exists(),
                "is_root": True,
            }
        )
        try:
            for entry in sorted(self.root_dir.iterdir(), key=lambda x: x.name.lower()):
                if entry.is_dir() and not entry.name.startswith(".") and entry.name not in IGNORED_DIRS:
                    if self.allowed_workspaces is not None and entry.name not in self.allowed_workspaces:
                        continue
                    items.append(
                        {
                            "name": entry.name,
                            "path": entry.name,
                            "full_path": str(entry),
                            "is_git": (entry / ".git").exists(),
                            "is_root": False,
                        }
                    )
        except Exception as e:
            logger.warning("Error listando workspaces en %s: %s", self.root_dir, e)
        return items

    def create_workspace(self, name: str, description: str = "") -> Dict[str, Any]:
        clean = re.sub(r"[^a-zA-Z0-9_\-\.]", "-", (name or "").strip()).strip("-")
        if not clean:
            raise ValueError("Nombre de proyecto inválido")
        target = (self.root_dir / clean).resolve()
        if not str(target).startswith(str(self.root_dir)):
            raise ValueError("Ruta fuera del directorio de proyectos")
        target.mkdir(parents=True, exist_ok=True)
        readme_path = target / "README.md"
        if not readme_path.exists():
            readme_path.write_text(
                f"# {clean}\n\n{description or 'Proyecto creado con InsanusChat Agent Harness.'}\n",
                encoding="utf-8",
            )
        return {
            "name": clean,
            "path": clean,
            "full_path": str(target),
            "is_git": (target / ".git").exists(),
        }

    def get_file_tree(self, workspace: str, rel_dir: str = ".", max_depth: int = 4) -> List[Dict[str, Any]]:
        ws_dir, start_dir = self._resolve_file_path(workspace, rel_dir)
        if not start_dir.exists() or not start_dir.is_dir():
            return []

        def _walk(curr: Path, depth: int) -> List[Dict[str, Any]]:
            if depth > max_depth:
                return []
            nodes: List[Dict[str, Any]] = []
            try:
                entries = sorted(curr.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
            except Exception:
                return []
            for entry in entries:
                if entry.name in IGNORED_DIRS:
                    continue
                if entry.name.startswith(".") and entry.name not in (".env.example", ".gitignore", ".dockerignore"):
                    continue
                rel = entry.relative_to(ws_dir).as_posix()
                if entry.is_dir():
                    nodes.append(
                        {
                            "name": entry.name,
                            "path": rel,
                            "type": "directory",
                            "children": _walk(entry, depth + 1),
                        }
                    )
                else:
                    if entry.suffix.lower() in IGNORED_EXTENSIONS:
                        continue
                    try:
                        size = entry.stat().st_size
                    except Exception:
                        size = 0
                    nodes.append(
                        {
                            "name": entry.name,
                            "path": rel,
                            "type": "file",
                            "size": size,
                            "language": self._infer_language(entry.name),
                        }
                    )
            return nodes

        return _walk(start_dir, 1)

    @staticmethod
    def _infer_language(filename: str) -> str:
        ext = Path(filename).suffix.lower()
        mapping = {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".json": "json",
            ".md": "markdown",
            ".html": "html",
            ".css": "css",
            ".yml": "yaml",
            ".yaml": "yaml",
            ".sh": "shell",
            ".ps1": "powershell",
            ".sql": "sql",
            ".dockerfile": "dockerfile",
        }
        if filename.lower() == "dockerfile":
            return "dockerfile"
        return mapping.get(ext, "plaintext")

    def read_file(
        self,
        workspace: str,
        rel_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        with_line_numbers: bool = False,
    ) -> Dict[str, Any]:
        ws_dir, target = self._resolve_file_path(workspace, rel_path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"Archivo no encontrado: {rel_path}")
        raw = target.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()
        total_lines = len(lines)

        s_idx = max(1, int(start_line)) if start_line else 1
        e_idx = min(total_lines, int(end_line)) if end_line else total_lines
        selected = lines[s_idx - 1 : e_idx]

        if with_line_numbers:
            formatted = "\n".join(f"{i}: {line}" for i, line in enumerate(selected, start=s_idx))
        else:
            formatted = "\n".join(selected)

        return {
            "path": target.relative_to(ws_dir).as_posix(),
            "content": formatted if (start_line or end_line or with_line_numbers) else raw,
            "raw_content": raw,
            "total_lines": total_lines,
            "start_line": s_idx,
            "end_line": e_idx,
            "language": self._infer_language(target.name),
        }

    def write_file(self, workspace: str, rel_path: str, content: str, overwrite: bool = True) -> Dict[str, Any]:
        ws_dir, target = self._resolve_file_path(workspace, rel_path)
        existed = target.exists()
        if existed and not overwrite:
            raise FileExistsError(f"El archivo ya existe y overwrite=False: {rel_path}")
        old_text = target.read_text(encoding="utf-8", errors="replace") if existed else ""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        norm_rel = target.relative_to(ws_dir).as_posix()
        diff_str = compute_unified_diff(old_text, content, norm_rel)
        return {
            "path": norm_rel,
            "action": "updated" if existed else "created",
            "lines_count": len(content.splitlines()),
            "diff": diff_str,
        }

    def edit_file(self, workspace: str, rel_path: str, target_block: str, replacement_block: str) -> Dict[str, Any]:
        ws_dir, target = self._resolve_file_path(workspace, rel_path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"Archivo no encontrado: {rel_path}")
        old_text = target.read_text(encoding="utf-8", errors="replace")

        if target_block in old_text:
            new_text = old_text.replace(target_block, replacement_block, 1)
        else:
            # Fallback normalizando saltos de línea CRLF vs LF
            norm_old = old_text.replace("\r\n", "\n")
            norm_target = target_block.replace("\r\n", "\n")
            norm_rep = replacement_block.replace("\r\n", "\n")
            if norm_target not in norm_old:
                raise ValueError(
                    f"El bloque target no coincide exactamente en {rel_path}. "
                    "Usa workspace_read_file primero para verificar el contenido exacto."
                )
            new_text = norm_old.replace(norm_target, norm_rep, 1)

        target.write_text(new_text, encoding="utf-8")
        norm_rel = target.relative_to(ws_dir).as_posix()
        diff_str = compute_unified_diff(old_text, new_text, norm_rel)
        return {
            "path": norm_rel,
            "action": "edited",
            "diff": diff_str,
        }

    def delete_file(self, workspace: str, rel_path: str) -> Dict[str, Any]:
        ws_dir, target = self._resolve_file_path(workspace, rel_path)
        if not target.exists():
            raise FileNotFoundError(f"No existe: {rel_path}")
        if target == ws_dir:
            raise ValueError("No se puede eliminar la raíz del workspace")
        norm_rel = target.relative_to(ws_dir).as_posix()
        if target.is_dir():
            target.rmdir()
        else:
            target.unlink()
        return {"path": norm_rel, "deleted": True}

    def grep_search(self, workspace: str, query: str, rel_dir: str = ".", max_results: int = 40) -> List[Dict[str, Any]]:
        ws_dir, start_dir = self._resolve_file_path(workspace, rel_dir)
        if not start_dir.exists():
            return []
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            pattern = re.compile(re.escape(query), re.IGNORECASE)

        matches: List[Dict[str, Any]] = []
        for root, dirs, files in os.walk(start_dir):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
            for fname in files:
                if Path(fname).suffix.lower() in IGNORED_EXTENSIONS:
                    continue
                fpath = Path(root) / fname
                try:
                    if fpath.stat().st_size > 512_000:
                        continue
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                    for idx, line in enumerate(text.splitlines(), start=1):
                        if pattern.search(line):
                            matches.append(
                                {
                                    "path": fpath.relative_to(ws_dir).as_posix(),
                                    "line": idx,
                                    "content": line.strip()[:200],
                                }
                            )
                            if len(matches) >= max_results:
                                return matches
                except Exception:
                    continue
        return matches

    def run_command(self, workspace: str, command_line: str, timeout_seconds: int = 30) -> Dict[str, Any]:
        if not self.allow_remote_terminal:
            raise PermissionError("La ejecución de terminal remota está deshabilitada en las políticas de este equipo.")
        validate_safe_terminal_command(command_line)
        ws_dir = self._resolve_workspace_dir(workspace)
        if not ws_dir.exists():
            raise FileNotFoundError(f"Directorio de workspace no existe: {workspace}")

        start = time.perf_counter()
        try:
            proc = subprocess.run(
                command_line,
                cwd=str(ws_dir),
                shell=True,
                capture_output=True,
                text=True,
                timeout=max(1, min(120, int(timeout_seconds))),
            )
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            return {
                "command": command_line,
                "cwd": str(ws_dir),
                "workspace": workspace,
                "hostname": platform.node(),
                "os": platform.system().lower(),
                "exit_code": proc.returncode,
                "stdout": (proc.stdout or "")[-8000:],
                "stderr": (proc.stderr or "")[-4000:],
                "duration_ms": duration_ms,
                "ok": proc.returncode == 0,
            }
        except subprocess.TimeoutExpired as te:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            return {
                "command": command_line,
                "cwd": str(ws_dir),
                "workspace": workspace,
                "hostname": platform.node(),
                "os": platform.system().lower(),
                "exit_code": -1,
                "stdout": (te.stdout or "")[-4000:] if isinstance(te.stdout, str) else "",
                "stderr": f"Command timed out after {timeout_seconds}s",
                "duration_ms": duration_ms,
                "ok": False,
            }

    def start_background_process(self, workspace: str, command_line: str, label: str = "") -> Dict[str, Any]:
        if not self.allow_remote_terminal:
            raise PermissionError("La ejecución de terminal remota está deshabilitada en este equipo.")
        validate_safe_terminal_command(command_line)
        ws_dir = self._resolve_workspace_dir(workspace)
        proc_id = f"proc-{uuid.uuid4().hex[:8]}"
        proc = subprocess.Popen(
            command_line,
            cwd=str(ws_dir),
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.bg_processes[proc_id] = {
            "proc_id": proc_id,
            "pid": proc.pid,
            "workspace": workspace,
            "cwd": str(ws_dir),
            "command": command_line,
            "label": label or command_line[:40],
            "started_at": datetime.utcnow().isoformat(),
            "process": proc,
        }
        return self._serialize_bg_process(proc_id)

    def _serialize_bg_process(self, proc_id: str) -> Dict[str, Any]:
        info = self.bg_processes[proc_id]
        proc: subprocess.Popen = info["process"]
        code = proc.poll()
        return {
            "proc_id": proc_id,
            "pid": info["pid"],
            "workspace": info["workspace"],
            "cwd": info["cwd"],
            "command": info["command"],
            "label": info["label"],
            "started_at": info["started_at"],
            "running": code is None,
            "exit_code": code,
        }

    def list_background_processes(self, workspace: Optional[str] = None) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for pid, info in list(self.bg_processes.items()):
            if workspace and workspace != "." and info.get("workspace") != workspace:
                continue
            out.append(self._serialize_bg_process(pid))
        return out

    def stop_background_process(self, proc_id: str) -> Dict[str, Any]:
        info = self.bg_processes.get(proc_id)
        if not info:
            raise KeyError(f"Proceso no encontrado: {proc_id}")
        proc: subprocess.Popen = info["process"]
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
        serialized = self._serialize_bg_process(proc_id)
        self.bg_processes.pop(proc_id, None)
        return serialized

    def git_status(self, workspace: str) -> Dict[str, Any]:
        ws_dir = self._resolve_workspace_dir(workspace)
        res_branch = self.run_command(workspace, "git rev-parse --abbrev-ref HEAD", timeout_seconds=5)
        res_status = self.run_command(workspace, "git status --short", timeout_seconds=8)
        res_diff = self.run_command(workspace, "git diff --stat", timeout_seconds=8)
        res_full_diff = self.run_command(workspace, "git diff", timeout_seconds=8)
        return {
            "workspace": workspace,
            "path": str(ws_dir),
            "is_git": res_branch.get("ok", False),
            "branch": (res_branch.get("stdout") or "").strip() if res_branch.get("ok") else None,
            "status_short": (res_status.get("stdout") or "").strip(),
            "diff_stat": (res_diff.get("stdout") or "").strip(),
            "diff_full": (res_full_diff.get("stdout") or "").strip(),
        }

    def git_checkpoint(self, workspace: str, label: str, node_id: Optional[str] = None) -> Dict[str, Any]:
        short_node = (str(node_id)[:8] if node_id else uuid.uuid4().hex[:6])
        safe_label = re.sub(r"[^a-zA-Z0-9_\- ]", "", label or "checkpoint").strip() or "checkpoint"
        branch_name = f"harness/node-{short_node}"
        status_info = self.git_status(workspace)
        if not status_info.get("is_git"):
            return {"ok": False, "message": "El workspace no es un repositorio Git inicializado."}
        return {
            "ok": True,
            "branch_suggested": branch_name,
            "current_branch": status_info.get("branch"),
            "status_short": status_info.get("status_short"),
            "label": safe_label,
        }

    # Gestor de Complementos / Extensiones de VS Code en el Equipo (HU-31)
    def _extensions_registry_path(self) -> Path:
        return self.root_dir / ".insanus-vscode-extensions.json"

    def list_installed_extensions(self) -> List[Dict[str, Any]]:
        builtin = {
            "id": "insanustech.insanuschat-harness",
            "display_name": "InsanusChat Agent Harness & 2D Tree",
            "publisher": "insanustech",
            "version": "1.2.0",
            "description": "Integración nativa de agentes IA, diffs y árbol 2D dentro del workbench VS Code.",
            "icon_url": None,
            "builtin": True,
            "enabled": True,
        }
        reg_file = self._extensions_registry_path()
        items: List[Dict[str, Any]] = [builtin]
        if reg_file.exists():
            try:
                saved = json.loads(reg_file.read_text(encoding="utf-8"))
                if isinstance(saved, list):
                    for ext in saved:
                        if isinstance(ext, dict) and ext.get("id") and ext["id"] != builtin["id"]:
                            items.append(ext)
            except Exception:
                pass
        return items

    def install_extension(self, ext_meta: Dict[str, Any]) -> Dict[str, Any]:
        ext_id = str(ext_meta.get("id") or "").strip()
        if not ext_id or "." not in ext_id:
            raise ValueError("ID de extensión inválido (formato esperado: publisher.name)")
        items = [x for x in self.list_installed_extensions() if not x.get("builtin") and x.get("id") != ext_id]
        record = {
            "id": ext_id,
            "display_name": ext_meta.get("display_name") or ext_id,
            "publisher": ext_meta.get("publisher") or ext_id.split(".", 1)[0],
            "version": ext_meta.get("version") or "latest",
            "description": ext_meta.get("description") or "",
            "icon_url": ext_meta.get("icon_url"),
            "install_count": ext_meta.get("install_count"),
            "rating": ext_meta.get("rating"),
            "builtin": False,
            "enabled": True,
            "installed_at": datetime.utcnow().isoformat(),
        }
        # Intentar instalar también en VS Code CLI local si está disponible en el equipo
        cli_synced = False
        try:
            import shutil as _shutil
            code_bin = _shutil.which("code") or _shutil.which("codium")
            if code_bin:
                subprocess.run([code_bin, "--install-extension", ext_id], capture_output=True, timeout=25)
                cli_synced = True
        except Exception:
            cli_synced = False
        record["cli_synced"] = cli_synced
        items.insert(0, record)
        self._extensions_registry_path().write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        return record

    def uninstall_extension(self, ext_id: str) -> Dict[str, Any]:
        items = [x for x in self.list_installed_extensions() if not x.get("builtin") and x.get("id") != ext_id]
        self._extensions_registry_path().write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            import shutil as _shutil
            code_bin = _shutil.which("code") or _shutil.which("codium")
            if code_bin:
                subprocess.run([code_bin, "--uninstall-extension", ext_id], capture_output=True, timeout=20)
        except Exception:
            pass
        return {"id": ext_id, "uninstalled": True}


class NodeBridgeManager:
    """
    Registro central de Equipos de Ejecución (Workstations) conectados por WebSocket
    + Nodo Local Integrado con control de privacidad (`expose_to_cloud`).
    """

    def __init__(self):
        self.local_executor = LocalWorkspaceExecutor()
        self.local_node_id = "local-workstation-host"
        self.local_node_name = os.environ.get("LOCAL_NODE_NAME", f"Docker-Sandbox-{platform.node() or 'Server'}")
        self.enable_builtin_host_node = True
        # Conexiones WebSocket de Workstations externas (Host PCs reales): node_id -> {ws, user_id, info, pending, pty_sessions}
        self.remote_nodes: Dict[str, Dict[str, Any]] = {}
        # Aprobaciones Human-in-the-Loop pendientes por chat_id -> call_id -> {future, info}
        self.pending_approvals: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def get_local_node_info(self) -> Dict[str, Any]:
        workspaces = self.local_executor.list_workspaces() if self.local_executor.expose_to_cloud else []
        return {
            "node_id": self.local_node_id,
            "name": self.local_node_name,
            "os": platform.system().lower(),
            "shell": "powershell" if platform.system().lower().startswith("win") else "bash",
            "status": "online" if self.local_executor.expose_to_cloud else "private_local_only",
            "expose_to_cloud": self.local_executor.expose_to_cloud,
            "allow_remote_terminal": self.local_executor.allow_remote_terminal,
            "allowed_workspaces": self.local_executor.allowed_workspaces,
            "root_dir": str(self.local_executor.root_dir),
            "workspaces": workspaces,
            "vscode_server_url": self.local_executor.vscode_server_url,
            "is_builtin_host": True,
            "last_seen": datetime.utcnow().isoformat(),
        }

    def set_local_privacy(
        self,
        expose_to_cloud: bool,
        allow_remote_terminal: Optional[bool] = None,
        allowed_workspaces: Optional[List[str]] = None,
        vscode_server_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.local_executor.expose_to_cloud = bool(expose_to_cloud)
        if allow_remote_terminal is not None:
            self.local_executor.allow_remote_terminal = bool(allow_remote_terminal)
        if allowed_workspaces is not None:
            self.local_executor.allowed_workspaces = [str(w).strip() for w in allowed_workspaces if str(w).strip()]
        if vscode_server_url is not None:
            self.local_executor.vscode_server_url = vscode_server_url.strip() or None
        return self.get_local_node_info()

    def list_nodes_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        nodes: List[Dict[str, Any]] = []
        # Primero listar siempre los Equipos Host reales (Windows/macOS/Linux Workstation conectados por túnel WS)
        for nid, entry in list(self.remote_nodes.items()):
            if str(entry.get("user_id")) == str(user_id):
                info = dict(entry.get("info") or {})
                info["node_id"] = nid
                info["status"] = "online"
                info["connected"] = True
                info["is_builtin_host"] = False
                nodes.append(info)
        # Solo exponer el nodo interno del servidor si ENABLE_BUILTIN_HOST_NODE=true
        if self.enable_builtin_host_node:
            nodes.append(self.get_local_node_info())
        return nodes

    @staticmethod
    def _default_policy_dict() -> Dict[str, Any]:
        return {
            "expose_to_cloud": False,
            "allow_remote_terminal": True,
            "allow_remote_agent_tools": True,
            "default_harness_mode": "ask",
            "allowed_workspaces": None,
            "terminal_auto_approve_patterns": ["git status", "git diff", "pytest", "npm test"],
            "terminal_blocked_patterns": [],
            "preferred_editor": "auto",
            "custom_editor_path": None,
            "sync_cli_extensions": True,
            "default_shell": "auto",
            "config_version": 1,
        }

    def _get_ws_col(self):
        try:
            import database as _db

            if _db.db is not None:
                return _db.get_workstation_collection()
        except Exception:
            pass
        return None

    async def register_device_record(self, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """HU-33 / HU-35: Registra o actualiza un Workstation en MongoDB (Fuente de Verdad SSOT)."""
        node_id = str(payload.get("node_id") or "").strip()
        if not node_id:
            raise ValueError("node_id es obligatorio")

        now_iso = datetime.utcnow().isoformat()
        col = self._get_ws_col()
        existing = await col.find_one({"user_id": str(user_id), "node_id": node_id}) if col is not None else None

        policy = dict(self._default_policy_dict())
        if existing and isinstance(existing.get("desired_policy"), dict):
            policy.update(existing["desired_policy"])
        elif isinstance(payload.get("local_policy"), dict):
            lp = payload["local_policy"]
            for k in list(policy.keys()):
                if k in lp and lp[k] is not None:
                    policy[k] = lp[k]

        synced_extensions = (existing or {}).get("synced_extensions") or []
        is_connected = node_id in self.remote_nodes and str(self.remote_nodes[node_id].get("user_id")) == str(user_id)

        doc = {
            "user_id": str(user_id),
            "node_id": node_id,
            "name": payload.get("name") or (existing or {}).get("name") or f"Workstation-{node_id[:6]}",
            "os": payload.get("os") or (existing or {}).get("os") or "windows",
            "arch": payload.get("arch") or (existing or {}).get("arch") or "x86_64",
            "shell": payload.get("shell") or (existing or {}).get("shell") or "powershell",
            "app_version": payload.get("app_version") or (existing or {}).get("app_version") or "1.4.0",
            "root_dir": payload.get("root_dir") if payload.get("root_dir") is not None else (existing or {}).get("root_dir", ""),
            "workspaces": payload.get("workspaces") if payload.get("workspaces") is not None else (existing or {}).get("workspaces", []),
            "reported_editors": payload.get("reported_editors") if payload.get("reported_editors") is not None else (existing or {}).get("reported_editors", []),
            "desired_policy": policy,
            "synced_extensions": synced_extensions,
            "revoked": False,
            "last_seen": now_iso,
            "updated_at": now_iso,
        }
        if not existing:
            doc["created_at"] = now_iso

        if col is not None:
            await col.update_one(
                {"user_id": str(user_id), "node_id": node_id},
                {"$set": doc},
                upsert=True,
            )

        return self._format_device_view(doc, is_connected)

    def _format_device_view(self, doc: Dict[str, Any], is_connected: bool) -> Dict[str, Any]:
        policy = dict(self._default_policy_dict())
        if isinstance(doc.get("desired_policy"), dict):
            policy.update(doc["desired_policy"])

        live_entry = self.remote_nodes.get(doc["node_id"]) if is_connected else None
        live_info = (live_entry or {}).get("info") or {}

        expose = bool(policy.get("expose_to_cloud", False))
        if doc.get("revoked"):
            status_str = "revoked"
        elif is_connected:
            status_str = "online"
            expose = True
        elif not expose:
            status_str = "private_local_only"
        else:
            status_str = "offline"

        return {
            "node_id": doc["node_id"],
            "name": live_info.get("name") or doc.get("name") or doc["node_id"],
            "os": live_info.get("os") or doc.get("os") or "windows",
            "arch": doc.get("arch") or "x86_64",
            "shell": live_info.get("shell") or doc.get("shell") or "powershell",
            "app_version": doc.get("app_version") or "1.4.0",
            "status": status_str,
            "connected": is_connected,
            "revoked": bool(doc.get("revoked", False)),
            "expose_to_cloud": expose,
            "allow_remote_terminal": bool(policy.get("allow_remote_terminal", True)),
            "allow_remote_agent_tools": bool(policy.get("allow_remote_agent_tools", True)),
            "allowed_workspaces": policy.get("allowed_workspaces"),
            "root_dir": live_info.get("root_dir") or doc.get("root_dir") or "",
            "workspaces": live_info.get("workspaces") if is_connected and live_info.get("workspaces") is not None else (doc.get("workspaces") or []),
            "reported_editors": live_info.get("reported_editors") or doc.get("reported_editors") or [],
            "desired_policy": policy,
            "config_version": int(policy.get("config_version", 1)),
            "synced_extensions": doc.get("synced_extensions") or [],
            "is_builtin_host": False,
            "last_seen": live_info.get("last_seen") or doc.get("last_seen"),
        }

    async def list_nodes_for_user_ssot(self, user_id: str) -> List[Dict[str, Any]]:
        """HU-33: Lista Workstations combinando registro persistente en MongoDB + túneles live WS."""
        uid = str(user_id)
        seen_ids = set()
        nodes: List[Dict[str, Any]] = []

        col = self._get_ws_col()
        if col is not None:
            cursor = col.find({"user_id": uid, "revoked": {"$ne": True}}).sort("last_seen", -1)
            async for doc in cursor:
                nid = str(doc.get("node_id") or "")
                if not nid:
                    continue
                seen_ids.add(nid)
                is_conn = nid in self.remote_nodes and str(self.remote_nodes[nid].get("user_id")) == uid
                nodes.append(self._format_device_view(doc, is_conn))

        # Incluir también cualquier nodo conectado por WS que aún no haya pasado por /register-device
        for nid, entry in list(self.remote_nodes.items()):
            if str(entry.get("user_id")) == uid and nid not in seen_ids:
                info = dict(entry.get("info") or {})
                info["node_id"] = nid
                info["status"] = "online"
                info["connected"] = True
                info["is_builtin_host"] = False
                nodes.append(info)

        # Priorizar nodos online arriba de los offline/local_only
        nodes.sort(key=lambda n: (0 if n.get("connected") else 1, n.get("name", "").lower()))

        if self.enable_builtin_host_node:
            nodes.append(self.get_local_node_info())
        return nodes

    async def get_device_sync_state(self, user_id: str, node_id: str) -> Dict[str, Any]:
        """HU-34: Devuelve la política autoritativa y extensiones sincronizadas del dispositivo."""
        col = self._get_ws_col()
        doc = await col.find_one({"user_id": str(user_id), "node_id": node_id}) if col is not None else None
        if not doc:
            raise FileNotFoundError(f"El dispositivo '{node_id}' no está registrado en tu cuenta.")
        is_conn = node_id in self.remote_nodes and str(self.remote_nodes[node_id].get("user_id")) == str(user_id)
        return self._format_device_view(doc, is_conn)

    async def update_device_policy(
        self,
        user_id: str,
        node_id: str,
        patch: Dict[str, Any],
        from_device: bool = False,
    ) -> Dict[str, Any]:
        """
        HU-34: Actualiza la política oficial en MongoDB (incrementando config_version) y empuja
        `policy_sync` por WebSocket si el equipo está conectado.
        Seguridad física: nunca se puede encender `expose_to_cloud` remotamente si el equipo está aislado.
        """
        uid = str(user_id)
        if node_id == self.local_node_id:
            return self.set_local_privacy(
                expose_to_cloud=bool(patch.get("expose_to_cloud", self.local_executor.expose_to_cloud)),
                allow_remote_terminal=patch.get("allow_remote_terminal"),
                allowed_workspaces=patch.get("allowed_workspaces"),
            )

        col = self._get_ws_col()
        doc = await col.find_one({"user_id": uid, "node_id": node_id}) if col is not None else None
        live_entry = self.remote_nodes.get(node_id)
        is_connected = bool(live_entry and str(live_entry.get("user_id")) == uid)

        if not doc and not is_connected:
            raise FileNotFoundError(f"Dispositivo '{node_id}' no encontrado en tu cuenta.")

        if doc and doc.get("revoked"):
            raise PermissionError("Este dispositivo fue revocado. Re-vincúlalo desde la app Desktop.")

        policy = dict(self._default_policy_dict())
        if doc and isinstance(doc.get("desired_policy"), dict):
            policy.update(doc["desired_policy"])

        # Regla de seguridad física: no encender Control Remoto desde afuera si no hay túnel activo
        if not from_device and patch.get("expose_to_cloud") is True and not is_connected and not policy.get("expose_to_cloud"):
            raise PermissionError(
                "Por seguridad física, el Control Remoto solo puede activarse desde la aplicación Desktop en tu PC."
            )

        allowed_fields = {
            "expose_to_cloud",
            "allow_remote_terminal",
            "allow_remote_agent_tools",
            "default_harness_mode",
            "allowed_workspaces",
            "terminal_auto_approve_patterns",
            "terminal_blocked_patterns",
            "preferred_editor",
            "custom_editor_path",
            "sync_cli_extensions",
            "default_shell",
        }
        for key in allowed_fields:
            if key in patch and patch[key] is not None:
                policy[key] = patch[key]
            elif key == "allowed_workspaces" and "allowed_workspaces" in patch and patch["allowed_workspaces"] is None:
                policy["allowed_workspaces"] = None

        policy["config_version"] = int(policy.get("config_version", 1)) + 1
        now_iso = datetime.utcnow().isoformat()

        updates: Dict[str, Any] = {
            "desired_policy": policy,
            "updated_at": now_iso,
        }
        if patch.get("node_name"):
            updates["name"] = str(patch["node_name"]).strip()

        if col is not None:
            await col.update_one(
                {"user_id": uid, "node_id": node_id},
                {
                    "$set": updates,
                    "$setOnInsert": {
                        "user_id": uid,
                        "node_id": node_id,
                        "name": updates.get("name") or (live_entry or {}).get("info", {}).get("name") or node_id,
                        "os": (live_entry or {}).get("info", {}).get("os") or "windows",
                        "shell": (live_entry or {}).get("info", {}).get("shell") or "powershell",
                        "revoked": False,
                        "created_at": now_iso,
                        "last_seen": now_iso,
                    },
                },
                upsert=True,
            )
            doc = await col.find_one({"user_id": uid, "node_id": node_id})

        if is_connected and live_entry:
            live_entry["info"]["allow_remote_terminal"] = bool(policy.get("allow_remote_terminal", True))
            live_entry["info"]["allow_remote_agent_tools"] = bool(policy.get("allow_remote_agent_tools", True))
            live_entry["info"]["expose_to_cloud"] = bool(policy.get("expose_to_cloud", True))
            if updates.get("name"):
                live_entry["info"]["name"] = updates["name"]
            try:
                await live_entry["ws"].send_json(
                    {
                        "cmd": "policy_sync",
                        "policy": policy,
                        "config_version": policy["config_version"],
                        "node_name": updates.get("name"),
                    }
                )
            except Exception:
                pass

            # Kill-Switch remoto: si se apaga expose_to_cloud, cerrar sesiones PTY remotas
            if policy.get("expose_to_cloud") is False:
                for sid in list((live_entry.get("pty_sessions") or {}).keys()):
                    await self.close_remote_pty(node_id, sid)

        if doc:
            return self._format_device_view(doc, is_connected and bool(policy.get("expose_to_cloud", True)))
        return {"node_id": node_id, "desired_policy": policy, "config_version": policy["config_version"]}

    async def revoke_device(self, user_id: str, node_id: str) -> Dict[str, Any]:
        """HU-33 / HU-34: Revoca y desconecta un Workstation inmediatamente."""
        uid = str(user_id)
        col = self._get_ws_col()
        if col is not None:
            await col.update_one(
                {"user_id": uid, "node_id": node_id},
                {
                    "$set": {
                        "revoked": True,
                        "desired_policy.expose_to_cloud": False,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                },
            )
        entry = self.remote_nodes.get(node_id)
        if entry and str(entry.get("user_id")) == uid:
            try:
                await entry["ws"].send_json({"cmd": "device_revoked", "node_id": node_id})
                await entry["ws"].close(code=1008)
            except Exception:
                pass
            self.unregister_remote_ws(node_id)
        return {"node_id": node_id, "revoked": True}

    async def record_synced_extension(
        self,
        user_id: str,
        node_id: str,
        action: str,
        ext_record: Optional[Dict[str, Any]] = None,
        ext_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """HU-35: Mantiene sincronizado el manifiesto de extensiones VS Code en MongoDB."""
        col = self._get_ws_col()
        if col is None:
            return []
        doc = await col.find_one({"user_id": str(user_id), "node_id": node_id})
        items: List[Dict[str, Any]] = list((doc or {}).get("synced_extensions") or [])
        if action == "install" and ext_record and ext_record.get("id"):
            items = [i for i in items if i.get("id") != ext_record["id"]]
            items.append(ext_record)
        elif action == "uninstall" and ext_id:
            items = [i for i in items if i.get("id") != ext_id]
        if doc is not None:
            await col.update_one(
                {"user_id": str(user_id), "node_id": node_id},
                {"$set": {"synced_extensions": items, "updated_at": datetime.utcnow().isoformat()}},
            )
        return items

    async def register_remote_ws(self, user_id: str, node_id: str, websocket: WebSocket, info: Dict[str, Any]) -> Dict[str, Any]:
        uid = str(user_id)
        col = self._get_ws_col()
        existing = await col.find_one({"user_id": uid, "node_id": node_id}) if col is not None else None
        if existing and existing.get("revoked"):
            raise PermissionError("Este equipo fue revocado por el usuario.")

        policy = dict(self._default_policy_dict())
        if existing and isinstance(existing.get("desired_policy"), dict):
            policy.update(existing["desired_policy"])
        # Al conectar activamente el túnel desde la PC, la intención física local es expose_to_cloud=True
        policy["expose_to_cloud"] = True
        if "allow_remote_terminal" in info:
            policy["allow_remote_terminal"] = bool(info["allow_remote_terminal"])
        if "allow_remote_agent_tools" in info:
            policy["allow_remote_agent_tools"] = bool(info["allow_remote_agent_tools"])

        now_iso = datetime.utcnow().isoformat()
        node_info = {
            "node_id": node_id,
            "name": info.get("name") or (existing or {}).get("name") or f"Workstation-{node_id[:6]}",
            "os": info.get("os") or "windows",
            "arch": info.get("arch") or "x86_64",
            "shell": info.get("shell") or "powershell",
            "app_version": info.get("app_version") or "1.4.0",
            "root_dir": info.get("root_dir") or "",
            "workspaces": info.get("workspaces") or [],
            "reported_editors": info.get("reported_editors") or [],
            "vscode_server_url": info.get("vscode_server_url"),
            "allow_remote_terminal": bool(policy.get("allow_remote_terminal", True)),
            "allow_remote_agent_tools": bool(policy.get("allow_remote_agent_tools", True)),
            "expose_to_cloud": True,
            "desired_policy": policy,
            "last_seen": now_iso,
        }

        self.remote_nodes[node_id] = {
            "user_id": uid,
            "ws": websocket,
            "info": node_info,
            "pending": {},
            "pty_sessions": {},
        }

        if col is not None:
            await col.update_one(
                {"user_id": uid, "node_id": node_id},
                {
                    "$set": {
                        "user_id": uid,
                        "node_id": node_id,
                        "name": node_info["name"],
                        "os": node_info["os"],
                        "arch": node_info["arch"],
                        "shell": node_info["shell"],
                        "app_version": node_info["app_version"],
                        "root_dir": node_info["root_dir"],
                        "workspaces": node_info["workspaces"],
                        "reported_editors": node_info["reported_editors"],
                        "desired_policy": policy,
                        "revoked": False,
                        "last_seen": now_iso,
                        "updated_at": now_iso,
                    },
                    "$setOnInsert": {"created_at": now_iso, "synced_extensions": []},
                },
                upsert=True,
            )
        return {
            "policy": policy,
            "synced_extensions": (existing or {}).get("synced_extensions") or [],
        }

    def unregister_remote_ws(self, node_id: str):
        entry = self.remote_nodes.pop(node_id, None)
        if entry and entry.get("pending"):
            for _, fut in entry["pending"].items():
                if not fut.done():
                    fut.set_exception(RuntimeError("El equipo de ejecución se desconectó"))
        if entry and entry.get("pty_sessions"):
            for _, q in entry["pty_sessions"].items():
                try:
                    q.put_nowait({"cmd": "pty_exit", "exit_code": 1, "reason": "node_disconnected"})
                except Exception:
                    pass

    def handle_remote_pty_event(self, node_id: str, payload: Dict[str, Any]):
        entry = self.remote_nodes.get(node_id)
        if not entry:
            return
        sid = payload.get("session_id")
        q = (entry.get("pty_sessions") or {}).get(sid)
        if q is not None:
            try:
                q.put_nowait(payload)
            except Exception:
                pass

    async def open_remote_pty(
        self,
        node_id: str,
        user_id: str,
        session_id: str,
        workspace: str,
        cols: int,
        rows: int,
        requested_shell: Optional[str] = None,
    ) -> asyncio.Queue:
        entry = self.remote_nodes.get(node_id)
        if not entry or not entry.get("ws"):
            raise RuntimeError(f"El equipo de ejecución '{node_id}' no está conectado.")
        if user_id and str(entry.get("user_id")) != str(user_id):
            raise PermissionError("No tienes permiso para abrir una terminal en un equipo de otro usuario.")
        info = entry.get("info") or {}
        if info.get("allow_remote_terminal") is False:
            raise PermissionError("La Terminal Remota está deshabilitada en este Workstation.")

        q: asyncio.Queue = asyncio.Queue()
        entry.setdefault("pty_sessions", {})[session_id] = q
        await entry["ws"].send_json(
            {
                "cmd": "pty_open",
                "session_id": session_id,
                "workspace": workspace,
                "cols": cols,
                "rows": rows,
                "shell": requested_shell or "",
            }
        )
        return q

    async def send_remote_pty_input(self, node_id: str, session_id: str, data: str):
        entry = self.remote_nodes.get(node_id)
        if entry and entry.get("ws"):
            await entry["ws"].send_json({"cmd": "pty_input", "session_id": session_id, "data": data})

    async def resize_remote_pty(self, node_id: str, session_id: str, cols: int, rows: int):
        entry = self.remote_nodes.get(node_id)
        if entry and entry.get("ws"):
            await entry["ws"].send_json(
                {"cmd": "pty_resize", "session_id": session_id, "cols": cols, "rows": rows}
            )

    async def close_remote_pty(self, node_id: str, session_id: str):
        entry = self.remote_nodes.get(node_id)
        if entry:
            (entry.get("pty_sessions") or {}).pop(session_id, None)
            if entry.get("ws"):
                try:
                    await entry["ws"].send_json({"cmd": "pty_close", "session_id": session_id})
                except Exception:
                    pass

    def handle_remote_rpc_response(self, node_id: str, payload: Dict[str, Any]):
        entry = self.remote_nodes.get(node_id)
        if not entry:
            return
        call_id = payload.get("call_id")
        if call_id and call_id in entry["pending"]:
            fut: asyncio.Future = entry["pending"].pop(call_id)
            if not fut.done():
                if payload.get("error"):
                    fut.set_exception(RuntimeError(str(payload["error"])))
                else:
                    fut.set_result(payload.get("data"))

    async def execute_on_node(
        self,
        node_id: str,
        action: str,
        params: Dict[str, Any],
        timeout: float = 35.0,
        user_id: Optional[str] = None,
    ) -> Any:
        """
        Ejecuta una acción del Harness (`list_workspaces`, `create_workspace`, `file_tree`,
        `read_file`, `write_file`, `edit_file`, `delete_file`, `grep_search`, `run_command`,
        `start_bg_process`, `list_bg_processes`, `stop_bg_process`, `git_status`, `git_checkpoint`)
        ya sea en el nodo local o a través del túnel WebSocket con verificación de propietario.
        """
        if action in ("run_command", "start_bg_process"):
            validate_safe_terminal_command(params.get("command_line", ""))

        if not node_id or node_id == self.local_node_id:
            if not self.local_executor.expose_to_cloud:
                raise PermissionError(
                    "Este equipo local tiene activado el modo '🔒 Solo Local (No expuesto a la Nube)'. "
                    "Habilitá el switch 'Exponer a la Nube' para permitir operaciones remotas."
                )
            return await asyncio.to_thread(self._exec_local_sync, action, params)

        entry = self.remote_nodes.get(node_id)
        if not entry or not entry.get("ws"):
            raise RuntimeError(f"El equipo de ejecución '{node_id}' no está conectado actualmente.")
        if user_id and str(entry.get("user_id")) != str(user_id):
            raise PermissionError("No tienes permiso para ejecutar comandos en un equipo de otro usuario.")

        info = entry.get("info") or {}
        if info.get("allow_remote_terminal") is False and action in ("run_command", "start_bg_process"):
            raise PermissionError("La Terminal Remota está deshabilitada en este Workstation.")
        if info.get("allow_remote_agent_tools") is False and action not in (
            "list_workspaces",
            "set_privacy",
            "list_extensions",
        ):
            raise PermissionError(
                "Las herramientas remotas de archivos/agente están deshabilitadas en las políticas de este Workstation."
            )

        call_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        entry["pending"][call_id] = fut

        ws: WebSocket = entry["ws"]
        await ws.send_json(
            {
                "cmd": "rpc_request",
                "call_id": call_id,
                "action": action,
                "params": params,
            }
        )
        return await asyncio.wait_for(fut, timeout=timeout)

    def _exec_local_sync(self, action: str, params: Dict[str, Any]) -> Any:
        ws_name = params.get("workspace") or "."
        if action == "list_workspaces":
            return self.local_executor.list_workspaces()
        if action == "create_workspace":
            return self.local_executor.create_workspace(params.get("name", ""), params.get("description", ""))
        if action == "file_tree":
            return self.local_executor.get_file_tree(
                ws_name,
                params.get("directory", "."),
                int(params.get("max_depth", 4)),
            )
        if action == "read_file":
            return self.local_executor.read_file(
                ws_name,
                params.get("path", ""),
                params.get("start_line"),
                params.get("end_line"),
                bool(params.get("with_line_numbers", False)),
            )
        if action == "write_file":
            return self.local_executor.write_file(
                ws_name,
                params.get("path", ""),
                params.get("content", ""),
                bool(params.get("overwrite", True)),
            )
        if action == "edit_file":
            return self.local_executor.edit_file(
                ws_name,
                params.get("path", ""),
                params.get("target", ""),
                params.get("replacement", ""),
            )
        if action == "delete_file":
            return self.local_executor.delete_file(ws_name, params.get("path", ""))
        if action == "grep_search":
            return self.local_executor.grep_search(
                ws_name,
                params.get("query", ""),
                params.get("directory", "."),
                int(params.get("max_results", 40)),
            )
        if action == "run_command":
            return self.local_executor.run_command(
                ws_name,
                params.get("command_line", ""),
                int(params.get("timeout_seconds", 30)),
            )
        if action == "start_bg_process":
            return self.local_executor.start_background_process(
                ws_name,
                params.get("command_line", ""),
                params.get("label", ""),
            )
        if action == "list_bg_processes":
            return self.local_executor.list_background_processes(ws_name)
        if action == "stop_bg_process":
            return self.local_executor.stop_background_process(params.get("proc_id", ""))
        if action == "git_status":
            return self.local_executor.git_status(ws_name)
        if action == "git_checkpoint":
            return self.local_executor.git_checkpoint(
                ws_name,
                params.get("label", "checkpoint"),
                params.get("node_id"),
            )
        if action == "list_extensions":
            return self.local_executor.list_installed_extensions()
        if action == "install_extension":
            return self.local_executor.install_extension(params.get("extension") or {})
        if action == "uninstall_extension":
            return self.local_executor.uninstall_extension(params.get("ext_id", ""))
        raise ValueError(f"Acción de nodo desconocida: {action}")

    async def request_tool_approval(
        self,
        chat_id: str,
        tool_name: str,
        args: Dict[str, Any],
        preview_diff: Optional[str],
        ws_manager: Any,
        timeout: float = 90.0,
    ) -> Tuple[bool, str]:
        """
        HU-22: Pausa la ejecución de una herramienta sensible y solicita aprobación en vivo
        por WebSocket al usuario (Human-in-the-Loop).
        """
        approval_id = uuid.uuid4().hex[:10]
        loop = asyncio.get_running_loop()
        fut = loop.create_future()

        chat_map = self.pending_approvals.setdefault(str(chat_id), {})
        chat_map[approval_id] = {
            "approval_id": approval_id,
            "tool": tool_name,
            "args": args,
            "diff": preview_diff,
            "future": fut,
            "created_at": datetime.utcnow().isoformat(),
        }

        if ws_manager is not None:
            await ws_manager.broadcast(
                str(chat_id),
                {
                    "cmd": "agent_tool_approval_needed",
                    "message": {
                        "approval_id": approval_id,
                        "chat_id": str(chat_id),
                        "tool": tool_name,
                        "args": args,
                        "diff": preview_diff,
                    },
                },
            )

        try:
            decision = await asyncio.wait_for(fut, timeout=timeout)
            return bool(decision.get("approved")), str(decision.get("feedback") or "")
        except asyncio.TimeoutError:
            return False, "Tiempo de espera de aprobación agotado (90s)."
        finally:
            chat_map.pop(approval_id, None)

    def resolve_tool_approval(
        self,
        chat_id: str,
        approval_id: str,
        approved: bool,
        feedback: str = "",
    ) -> bool:
        chat_map = self.pending_approvals.get(str(chat_id)) or {}
        item = chat_map.get(approval_id)
        if not item:
            return False
        fut: asyncio.Future = item["future"]
        if not fut.done():
            fut.set_result({"approved": approved, "feedback": feedback})
        return True


node_bridge = NodeBridgeManager()
