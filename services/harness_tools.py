"""
Generador de Herramientas Nativas del Agent Harness (LangChain `StructuredTool`)
e Inyector de Contexto de Workspace (`AGENTS.md`, árbol del proyecto, Git y Plan de Tareas)
(HU-21, HU-22, HU-23).
"""
import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

import database
from services.node_bridge import compute_unified_diff, node_bridge

logger = logging.getLogger(__name__)


class ListFilesArgs(BaseModel):
    directory: str = Field(".", description="Directorio relativo dentro del proyecto a listar (por defecto '.')")
    max_depth: int = Field(3, description="Profundidad máxima del árbol (1 a 5)")


class ReadFileArgs(BaseModel):
    path: str = Field(..., description="Ruta relativa del archivo dentro del workspace")
    start_line: int = Field(1, description="Línea inicial a leer (1-indexed)")
    end_line: int = Field(250, description="Línea final a leer (máximo 400 líneas por lectura)")


class WriteFileArgs(BaseModel):
    path: str = Field(..., description="Ruta relativa del archivo a crear o sobrescribir")
    content: str = Field(..., description="Contenido completo a escribir en el archivo")


class EditFileArgs(BaseModel):
    path: str = Field(..., description="Ruta relativa del archivo a editar quirúrgicamente")
    target: str = Field(..., description="Bloque exacto de texto existente que se desea reemplazar")
    replacement: str = Field(..., description="Nuevo bloque de texto que reemplazará a target")


class GrepSearchArgs(BaseModel):
    query: str = Field(..., description="Texto o expresión regular a buscar en los archivos del proyecto")
    directory: str = Field(".", description="Subdirectorio relativo donde buscar")


class RunCommandArgs(BaseModel):
    command_line: str = Field(..., description="Comando de terminal a ejecutar en la carpeta del proyecto")
    timeout_seconds: int = Field(30, description="Tiempo máximo de espera en segundos (1 a 120)")


class GitCheckpointArgs(BaseModel):
    label: str = Field(..., description="Descripción breve del punto de control o rama")


class UpdatePlanArgs(BaseModel):
    steps: List[Dict[str, str]] = Field(
        ...,
        description="Lista de pasos del plan: [{'title': '...', 'status': 'pending' | 'in_progress' | 'completed'}]",
    )


async def build_workspace_context_prompt(node_id: str, workspace_path: str, harness_mode: str = "auto_edit") -> str:
    """
    HU-23: Construye el bloque de ingeniería de contexto del Workspace activo:
    incluye árbol inicial de archivos, estado Git y contenido de `AGENTS.md` si existe.
    """
    try:
        tree = await node_bridge.execute_on_node(
            node_id,
            "file_tree",
            {"workspace": workspace_path, "directory": ".", "max_depth": 2},
        )
    except Exception as e:
        return f"\n[AVISO HARNESS]: No se pudo acceder al workspace '{workspace_path}' en el nodo '{node_id}': {e}\n"

    flat_files: List[str] = []

    def _flatten(items: List[Dict[str, Any]]):
        for it in items:
            if len(flat_files) >= 60:
                return
            prefix = "📁 " if it.get("type") == "directory" else "📄 "
            flat_files.append(f"{prefix}{it.get('path')}")
            if it.get("children"):
                _flatten(it["children"])

    _flatten(tree or [])

    agents_md_content = ""
    for candidate_doc in ("AGENTS.md", "CLAUDE.md", ".insanus/rules.md"):
        try:
            doc_res = await node_bridge.execute_on_node(
                node_id,
                "read_file",
                {"workspace": workspace_path, "path": candidate_doc, "start_line": 1, "end_line": 120},
            )
            if doc_res and doc_res.get("content"):
                agents_md_content = f"\n### Reglas del Proyecto ({candidate_doc}):\n{doc_res['content'][:2500]}\n"
                break
        except Exception:
            continue

    files_summary = "\n".join(flat_files) if flat_files else "(Proyecto vacío)"

    return (
        f"\n\n=== ENTORNO DE DESARROLLO ACTIVO (INSANUS HARNESS) ===\n"
        f"- Equipo de Ejecución: `{node_id}`\n"
        f"- Proyecto / Workspace Activo: `{workspace_path}`\n"
        f"- Política de Permisos: `{harness_mode}`\n"
        f"- Estructura inicial del proyecto:\n{files_summary}\n"
        f"{agents_md_content}"
        f"Instrucciones del Harness:\n"
        f"1. Usa `harness_update_plan` para mantener actualizado tu plan de tareas paso a paso.\n"
        f"2. Antes de editar un archivo existente, léelo con `workspace_read_file` y luego usa `workspace_edit_file`.\n"
        f"3. Usa `workspace_run_command` para ejecutar tests, builds o comandos de verificación.\n"
        f"======================================================\n"
    )


def build_harness_langchain_tools(
    chat_oid: Any,
    node_id: str,
    workspace_path: str,
    harness_mode: str = "auto_edit",
    ws_manager: Any = None,
    current_message_id: Optional[str] = None,
) -> List[StructuredTool]:
    """
    HU-21 & HU-22: Crea la suite de `StructuredTool`s de LangChain conectadas al equipo
    de ejecución `node_id` y carpeta `workspace_path`, respetando la política `harness_mode`
    (`ask`, `auto_edit`, `autopilot`).
    """
    chat_id_str = str(chat_oid)
    mode = (harness_mode or "auto_edit").lower()

    async def _list_files(directory: str = ".", max_depth: int = 3) -> str:
        res = await node_bridge.execute_on_node(
            node_id,
            "file_tree",
            {"workspace": workspace_path, "directory": directory, "max_depth": max_depth},
        )
        return json.dumps({"workspace": workspace_path, "directory": directory, "tree": res}, ensure_ascii=False)

    async def _read_file(path: str, start_line: int = 1, end_line: int = 250) -> str:
        res = await node_bridge.execute_on_node(
            node_id,
            "read_file",
            {
                "workspace": workspace_path,
                "path": path,
                "start_line": start_line,
                "end_line": end_line,
                "with_line_numbers": True,
            },
        )
        return json.dumps(
            {
                "path": res.get("path"),
                "start_line": res.get("start_line"),
                "end_line": res.get("end_line"),
                "total_lines": res.get("total_lines"),
                "content": res.get("content"),
            },
            ensure_ascii=False,
        )

    async def _write_file(path: str, content: str) -> str:
        if mode == "ask":
            preview_diff = compute_unified_diff("", content, path)
            approved, feedback = await node_bridge.request_tool_approval(
                chat_id=chat_id_str,
                tool_name="workspace_write_file",
                args={"path": path},
                preview_diff=preview_diff,
                ws_manager=ws_manager,
            )
            if not approved:
                return json.dumps(
                    {"status": "rejected_by_user", "path": path, "feedback": feedback or "Acción rechazada por el usuario"},
                    ensure_ascii=False,
                )

        res = await node_bridge.execute_on_node(
            node_id,
            "write_file",
            {"workspace": workspace_path, "path": path, "content": content, "overwrite": True},
        )
        return json.dumps(res, ensure_ascii=False)

    async def _edit_file(path: str, target: str, replacement: str) -> str:
        if mode == "ask":
            preview_diff = compute_unified_diff(target, replacement, path)
            approved, feedback = await node_bridge.request_tool_approval(
                chat_id=chat_id_str,
                tool_name="workspace_edit_file",
                args={"path": path},
                preview_diff=preview_diff,
                ws_manager=ws_manager,
            )
            if not approved:
                return json.dumps(
                    {"status": "rejected_by_user", "path": path, "feedback": feedback or "Edición rechazada por el usuario"},
                    ensure_ascii=False,
                )

        res = await node_bridge.execute_on_node(
            node_id,
            "edit_file",
            {"workspace": workspace_path, "path": path, "target": target, "replacement": replacement},
        )
        return json.dumps(res, ensure_ascii=False)

    async def _grep_search(query: str, directory: str = ".") -> str:
        res = await node_bridge.execute_on_node(
            node_id,
            "grep_search",
            {"workspace": workspace_path, "query": query, "directory": directory},
        )
        return json.dumps({"query": query, "matches": res}, ensure_ascii=False)

    async def _run_command(command_line: str, timeout_seconds: int = 30) -> str:
        if mode in ("ask", "auto_edit"):
            approved, feedback = await node_bridge.request_tool_approval(
                chat_id=chat_id_str,
                tool_name="workspace_run_command",
                args={"command_line": command_line, "workspace": workspace_path},
                preview_diff=None,
                ws_manager=ws_manager,
            )
            if not approved:
                return json.dumps(
                    {
                        "status": "rejected_by_user",
                        "command": command_line,
                        "feedback": feedback or "Comando rechazado por el usuario",
                    },
                    ensure_ascii=False,
                )

        res = await node_bridge.execute_on_node(
            node_id,
            "run_command",
            {"workspace": workspace_path, "command_line": command_line, "timeout_seconds": timeout_seconds},
            timeout=float(timeout_seconds) + 10.0,
        )
        return json.dumps(res, ensure_ascii=False)

    async def _git_checkpoint(label: str) -> str:
        res = await node_bridge.execute_on_node(
            node_id,
            "git_checkpoint",
            {"workspace": workspace_path, "label": label, "node_id": current_message_id},
        )
        return json.dumps(res, ensure_ascii=False)

    async def _update_plan(steps: List[Dict[str, str]]) -> str:
        normalized: List[Dict[str, str]] = []
        for idx, s in enumerate(steps or []):
            if isinstance(s, dict):
                title = str(s.get("title") or s.get("step") or f"Paso {idx + 1}").strip()
                st = str(s.get("status") or "pending").lower()
                if st not in ("pending", "in_progress", "completed"):
                    st = "pending"
                normalized.append({"id": f"step-{idx + 1}", "title": title, "status": st})
        try:
            chats_col = database.get_chat_collection()
            await chats_col.update_one({"_id": chat_oid}, {"$set": {"task_plan": normalized}})
        except Exception as e:
            logger.debug("Error guardando task_plan en MongoDB: %s", e)

        if ws_manager is not None:
            try:
                await ws_manager.broadcast(
                    chat_id_str,
                    {
                        "cmd": "agent_plan_updated",
                        "message": {"chat_id": chat_id_str, "task_plan": normalized},
                    },
                )
            except Exception:
                pass
        return json.dumps({"status": "plan_updated", "task_plan": normalized}, ensure_ascii=False)

    tools = [
        StructuredTool.from_function(
            coroutine=_list_files,
            name="workspace_list_files",
            description="Lista archivos y carpetas del proyecto local activo en el equipo de ejecución.",
            args_schema=ListFilesArgs,
            metadata={"harness_tool": "workspace_list_files"},
        ),
        StructuredTool.from_function(
            coroutine=_read_file,
            name="workspace_read_file",
            description="Lee el contenido de un archivo del proyecto con números de línea (start_line a end_line).",
            args_schema=ReadFileArgs,
            metadata={"harness_tool": "workspace_read_file"},
        ),
        StructuredTool.from_function(
            coroutine=_write_file,
            name="workspace_write_file",
            description="Crea o sobrescribe un archivo en el proyecto activo y devuelve el Unified Diff.",
            args_schema=WriteFileArgs,
            metadata={"harness_tool": "workspace_write_file"},
        ),
        StructuredTool.from_function(
            coroutine=_edit_file,
            name="workspace_edit_file",
            description="Reemplaza quirúrgicamente un bloque exacto (target -> replacement) en un archivo y devuelve el Unified Diff.",
            args_schema=EditFileArgs,
            metadata={"harness_tool": "workspace_edit_file"},
        ),
        StructuredTool.from_function(
            coroutine=_grep_search,
            name="workspace_grep_search",
            description="Busca texto o expresiones regulares en todos los archivos del proyecto.",
            args_schema=GrepSearchArgs,
            metadata={"harness_tool": "workspace_grep_search"},
        ),
        StructuredTool.from_function(
            coroutine=_run_command,
            name="workspace_run_command",
            description="Ejecuta un comando de terminal (PowerShell/Bash) dentro de la carpeta del proyecto.",
            args_schema=RunCommandArgs,
            metadata={"harness_tool": "workspace_run_command"},
        ),
        StructuredTool.from_function(
            coroutine=_git_checkpoint,
            name="workspace_git_checkpoint",
            description="Crea un punto de control o verifica el estado Git vinculado al nodo actual del Árbol 2D.",
            args_schema=GitCheckpointArgs,
            metadata={"harness_tool": "workspace_git_checkpoint"},
        ),
        StructuredTool.from_function(
            coroutine=_update_plan,
            name="harness_update_plan",
            description="Actualiza el checklist del plan de tareas del agente en vivo para que el usuario vea el progreso.",
            args_schema=UpdatePlanArgs,
            metadata={"harness_tool": "harness_update_plan"},
        ),
    ]
    return tools
