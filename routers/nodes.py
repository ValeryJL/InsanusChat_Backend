"""
Router de Equipos de Ejecución (Workstation Nodes), Túnel RPC WebSocket y API de Archivos/Terminal
para el Editor de Código VS Code (HU-20, HU-24, HU-27).
"""
import asyncio
import base64
import hashlib
import hmac
import logging
import os
import platform
from typing import Any, Dict, Optional
from urllib.parse import quote
import uuid

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse, RedirectResponse
import httpx

from models import ResponseModel, WorkstationPolicyPatchRequest, WorkstationRegisterRequest
from routers import auth
from services.node_bridge import node_bridge
from services.pty_manager import InteractivePtySession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/nodes", tags=["Equipos de Ejecución (Harness Nodes)"])
ide_proxy_router = APIRouter(tags=["VS Code Remoto Embebido"])

IDE_COOKIE_NAME = "insanus_remote_ide"


def _ide_signing_key() -> bytes:
    return (os.environ.get("LOCAL_AUTH_SECRET") or "insanuschat-local-dev-jwt-secret-key-2026-secure").encode("utf-8")


def _sign_ide_cookie(user_id: str, node_id: str, session_secret: str) -> str:
    payload = f"{user_id}|{node_id}|{session_secret}"
    sig = hmac.new(_ide_signing_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}|{sig}"


def _verify_ide_cookie(cookie_val: Optional[str], expected_secret: str) -> Optional[Dict[str, str]]:
    if not cookie_val:
        return None
    parts = cookie_val.split("|")
    if len(parts) != 4:
        return None
    uid, nid, sec, sig = parts
    if sec != expected_secret:
        return None
    expected_sig = hmac.new(_ide_signing_key(), f"{uid}|{nid}|{sec}".encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    return {"user_id": uid, "node_id": nid, "session_secret": sec}


@router.get("/", response_model=ResponseModel)
async def list_execution_nodes(authorization: str = Header(..., alias="Authorization")):
    """HU-20 / HU-33: Lista los equipos de ejecución (MongoDB SSOT + túneles live WS) asociados al usuario."""
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    nodes = await node_bridge.list_nodes_for_user_ssot(uid)
    return ResponseModel(message="Equipos de ejecución listados", data={"nodes": nodes})


@router.post("/register-device", response_model=ResponseModel)
async def register_workstation_device(
    body: WorkstationRegisterRequest,
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-33 / HU-35: Registra o actualiza un Workstation Desktop en MongoDB y devuelve su política oficial SSOT."""
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    try:
        device = await node_bridge.register_device_record(uid, body.model_dump())
        return ResponseModel(message="Dispositivo Workstation sincronizado con el servidor", data=device)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{node_id}/sync", response_model=ResponseModel)
async def get_workstation_sync_state(
    node_id: str,
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-34: Devuelve la política autoritativa (desired_policy, config_version) y extensiones sincronizadas."""
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    try:
        device = await node_bridge.get_device_sync_state(uid, node_id)
        return ResponseModel(message="Estado autoritativo del Workstation obtenido", data=device)
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fnf))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{node_id}/policy", response_model=ResponseModel)
async def update_workstation_policy(
    node_id: str,
    body: WorkstationPolicyPatchRequest,
    authorization: str = Header(..., alias="Authorization"),
    x_workstation_origin: Optional[str] = Header(None, alias="X-Workstation-Origin"),
):
    """
    HU-34: Actualiza la política oficial de un Workstation en MongoDB (config_version += 1)
    y empuja `policy_sync` por WebSocket si está online (incluyendo Kill-Switch remoto).
    """
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    from_device = bool(body.from_device or (x_workstation_origin or "").lower() == "desktop")
    patch_data = body.model_dump(exclude_unset=True)
    patch_data.pop("from_device", None)
    try:
        device = await node_bridge.update_device_policy(uid, node_id, patch_data, from_device=from_device)
        return ResponseModel(message="Política del Workstation actualizada y sincronizada", data=device)
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fnf))
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{node_id}", response_model=ResponseModel)
async def revoke_workstation_device(
    node_id: str,
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-33 / HU-34: Revoca un dispositivo Workstation y cierra su túnel WebSocket inmediatamente."""
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    res = await node_bridge.revoke_device(uid, node_id)
    return ResponseModel(message="Dispositivo Workstation revocado y desconectado", data=res)


@router.patch("/local/privacy", response_model=ResponseModel)
async def update_local_node_privacy(
    body: Dict[str, Any] = Body(...),
    authorization: str = Header(..., alias="Authorization"),
):
    """
    HU-24: Controla el switch '🔒 Solo Local' vs '🌐 Exponer a la Nube', la lista blanca
    de carpetas de proyectos y la URL de OpenVSCode Server.
    """
    await auth.get_authenticated_user(authorization)
    expose = bool(body.get("expose_to_cloud", True))
    allow_term = body.get("allow_remote_terminal")
    allowed_ws = body.get("allowed_workspaces")
    vscode_url = body.get("vscode_server_url")
    info = node_bridge.set_local_privacy(
        expose_to_cloud=expose,
        allow_remote_terminal=bool(allow_term) if allow_term is not None else None,
        allowed_workspaces=allowed_ws if isinstance(allowed_ws, list) else None,
        vscode_server_url=vscode_url if isinstance(vscode_url, str) else None,
    )
    return ResponseModel(
        message="Configuración de privacidad del equipo actualizada",
        data=info,
    )


@router.get("/{node_id}/workspaces", response_model=ResponseModel)
async def list_node_workspaces(
    node_id: str,
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-20: Lista las carpetas de proyectos disponibles en el equipo de ejecución."""
    await auth.get_authenticated_user(authorization)
    try:
        workspaces = await node_bridge.execute_on_node(node_id, "list_workspaces", {})
        return ResponseModel(message="Proyectos del equipo listados", data={"workspaces": workspaces})
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{node_id}/workspaces", response_model=ResponseModel)
async def create_node_workspace(
    node_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-20: Crea una nueva carpeta de proyecto en el equipo de ejecución seleccionado."""
    await auth.get_authenticated_user(authorization)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="El nombre del proyecto es obligatorio")
    try:
        ws = await node_bridge.execute_on_node(
            node_id,
            "create_workspace",
            {"name": name, "description": body.get("description") or ""},
        )
        return ResponseModel(message="Proyecto creado en el equipo", data=ws)
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{node_id}/files/tree", response_model=ResponseModel)
async def get_workspace_file_tree(
    node_id: str,
    workspace: str = Query(".", description="Nombre del proyecto/workspace"),
    directory: str = Query(".", description="Subdirectorio relativo"),
    max_depth: int = Query(4, ge=1, le=8),
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-27: Devuelve el árbol de archivos del proyecto para el Explorador de VS Code."""
    await auth.get_authenticated_user(authorization)
    try:
        tree = await node_bridge.execute_on_node(
            node_id,
            "file_tree",
            {"workspace": workspace, "directory": directory, "max_depth": max_depth},
        )
        return ResponseModel(message="Árbol de archivos obtenido", data={"tree": tree, "workspace": workspace})
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{node_id}/files/search", response_model=ResponseModel)
async def search_workspace_files(
    node_id: str,
    workspace: str = Query(".", description="Nombre del proyecto/workspace"),
    query: str = Query(..., min_length=1, description="Texto o expresión regular a buscar"),
    directory: str = Query(".", description="Subdirectorio relativo"),
    max_results: int = Query(50, ge=1, le=200),
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-27: Búsqueda grep en tiempo real para el panel Search (Ctrl+Shift+F) del Workbench VS Code."""
    user = await auth.get_authenticated_user(authorization)
    try:
        matches = await node_bridge.execute_on_node(
            node_id,
            "grep_search",
            {"workspace": workspace, "query": query, "directory": directory, "max_results": max_results},
            user_id=str(user["_id"]),
        )
        return ResponseModel(message="Búsqueda completada", data={"query": query, "matches": matches})
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{node_id}/files/read", response_model=ResponseModel)
async def read_workspace_file(
    node_id: str,
    workspace: str = Query(".", description="Nombre del proyecto/workspace"),
    path: str = Query(..., description="Ruta relativa del archivo"),
    start_line: Optional[int] = Query(None),
    end_line: Optional[int] = Query(None),
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-27: Lee el contenido de un archivo para el Editor de Código VS Code."""
    await auth.get_authenticated_user(authorization)
    try:
        data = await node_bridge.execute_on_node(
            node_id,
            "read_file",
            {
                "workspace": workspace,
                "path": path,
                "start_line": start_line,
                "end_line": end_line,
                "with_line_numbers": False,
            },
        )
        return ResponseModel(message="Archivo leído", data=data)
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fnf))
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{node_id}/files/write", response_model=ResponseModel)
async def write_workspace_file(
    node_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-27: Guarda o crea un archivo desde el Editor VS Code (Ctrl+S) devolviendo el Unified Diff."""
    await auth.get_authenticated_user(authorization)
    workspace = body.get("workspace") or "."
    path = (body.get("path") or "").strip()
    content = body.get("content") if body.get("content") is not None else ""
    if not path:
        raise HTTPException(status_code=400, detail="path es obligatorio")
    try:
        res = await node_bridge.execute_on_node(
            node_id,
            "write_file",
            {"workspace": workspace, "path": path, "content": str(content), "overwrite": True},
        )
        return ResponseModel(message="Archivo guardado correctamente", data=res)
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{node_id}/files/edit", response_model=ResponseModel)
async def edit_workspace_file(
    node_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-25: Aplica una edición quirúrgica target -> replacement y devuelve el Unified Diff."""
    await auth.get_authenticated_user(authorization)
    workspace = body.get("workspace") or "."
    path = (body.get("path") or "").strip()
    target = body.get("target") or ""
    replacement = body.get("replacement") if body.get("replacement") is not None else ""
    if not path or not target:
        raise HTTPException(status_code=400, detail="path y target son obligatorios")
    try:
        res = await node_bridge.execute_on_node(
            node_id,
            "edit_file",
            {"workspace": workspace, "path": path, "target": target, "replacement": replacement},
        )
        return ResponseModel(message="Archivo editado con diff", data=res)
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{node_id}/files", response_model=ResponseModel)
async def delete_workspace_file(
    node_id: str,
    workspace: str = Query("."),
    path: str = Query(...),
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-27: Elimina un archivo o directorio vacío del proyecto."""
    await auth.get_authenticated_user(authorization)
    try:
        res = await node_bridge.execute_on_node(
            node_id,
            "delete_file",
            {"workspace": workspace, "path": path},
        )
        return ResponseModel(message="Archivo eliminado", data=res)
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{node_id}/terminal/exec", response_model=ResponseModel)
async def execute_workspace_command(
    node_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-26: Ejecuta un comando seguro en la terminal remota o local del proyecto."""
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    workspace = body.get("workspace") or "."
    command_line = (body.get("command") or body.get("command_line") or "").strip()
    timeout_seconds = int(body.get("timeout_seconds") or 30)
    if not command_line:
        raise HTTPException(status_code=400, detail="command es obligatorio")
    try:
        res = await node_bridge.execute_on_node(
            node_id,
            "run_command",
            {"workspace": workspace, "command_line": command_line, "timeout_seconds": timeout_seconds},
            timeout=float(timeout_seconds) + 10.0,
            user_id=uid,
        )
        return ResponseModel(message="Comando ejecutado", data=res)
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{node_id}/terminal/processes", response_model=ResponseModel)
async def list_workspace_processes(
    node_id: str,
    workspace: str = Query("."),
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-26: Lista los procesos en segundo plano activos en la terminal remota/local."""
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    try:
        res = await node_bridge.execute_on_node(
            node_id,
            "list_bg_processes",
            {"workspace": workspace},
            user_id=uid,
        )
        return ResponseModel(message="Procesos listados", data={"processes": res})
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{node_id}/terminal/processes", response_model=ResponseModel)
async def start_workspace_process(
    node_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-26: Inicia un proceso en background (ej: servidor de desarrollo) en el equipo remoto/local."""
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    workspace = body.get("workspace") or "."
    command_line = (body.get("command") or body.get("command_line") or "").strip()
    label = (body.get("label") or "").strip()
    if not command_line:
        raise HTTPException(status_code=400, detail="command es obligatorio")
    try:
        res = await node_bridge.execute_on_node(
            node_id,
            "start_bg_process",
            {"workspace": workspace, "command_line": command_line, "label": label},
            user_id=uid,
        )
        return ResponseModel(message="Proceso iniciado", data=res)
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{node_id}/terminal/processes/{proc_id}", response_model=ResponseModel)
async def stop_workspace_process(
    node_id: str,
    proc_id: str,
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-26: Detiene un proceso en background en el equipo remoto/local."""
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    try:
        res = await node_bridge.execute_on_node(
            node_id,
            "stop_bg_process",
            {"proc_id": proc_id},
            user_id=uid,
        )
        return ResponseModel(message="Proceso detenido", data=res)
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.websocket("/{node_id}/terminal/ws")
async def remote_terminal_interactive_ws(websocket: WebSocket, node_id: str):
    """
    HU-26: Sesión PTY Real Interactiva por WebSocket (bash/sh en Linux, PowerShell/cmd ConPTY en Windows).
    Conecta el emulador xterm.js directamente al shell real del sistema operativo (local o vía túnel Workstation).
    """
    await websocket.accept()
    token = websocket.query_params.get("token")
    workspace = websocket.query_params.get("workspace") or "."
    requested_shell = (websocket.query_params.get("shell") or "").strip() or None
    cols = int(websocket.query_params.get("cols") or 100)
    rows = int(websocket.query_params.get("rows") or 24)

    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        decoded = auth.authenticate_token(token)
        uid = str(decoded.get("uid") or decoded.get("user_id") or "")
    except Exception:
        uid = ""
    if not uid:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    is_local_host = (not node_id) or (node_id == node_bridge.local_node_id)
    local_pty: Optional[InteractivePtySession] = None
    remote_session_id: Optional[str] = None
    output_queue: Optional[asyncio.Queue] = None

    try:
        if is_local_host:
            if not node_bridge.local_executor.expose_to_cloud:
                await websocket.send_json(
                    {
                        "cmd": "pty_error",
                        "message": "El nodo local está en modo 'Solo Local'. Activá 'Acceso desde la Nube' para abrir la terminal.",
                    }
                )
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            if not node_bridge.local_executor.allow_remote_terminal:
                await websocket.send_json(
                    {"cmd": "pty_error", "message": "La terminal remota está deshabilitada en este equipo."}
                )
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            ws_dir = node_bridge.local_executor.resolve_workspace_dir(workspace)
            local_pty = InteractivePtySession(
                cwd=ws_dir,
                cols=cols,
                rows=rows,
                requested_shell=requested_shell,
            )
            local_pty.start(asyncio.get_running_loop())
            output_queue = local_pty.output_queue
            await websocket.send_json(
                {
                    "cmd": "terminal_ready",
                    "node_id": node_id,
                    "workspace": workspace,
                    "shell": local_pty.shell_name,
                    "os": platform.system().lower(),
                }
            )
        else:
            remote_session_id = uuid.uuid4().hex
            entry = node_bridge.remote_nodes.get(node_id) or {}
            info = entry.get("info") or {}
            output_queue = await node_bridge.open_remote_pty(
                node_id=node_id,
                user_id=uid,
                session_id=remote_session_id,
                workspace=workspace,
                cols=cols,
                rows=rows,
                requested_shell=requested_shell,
            )
            await websocket.send_json(
                {
                    "cmd": "terminal_ready",
                    "node_id": node_id,
                    "workspace": workspace,
                    "shell": requested_shell or info.get("shell") or "powershell",
                    "os": info.get("os") or "windows",
                }
            )
    except Exception as start_err:
        try:
            await websocket.send_json({"cmd": "pty_error", "message": str(start_err)})
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            pass
        return

    async def forward_pty_to_ws():
        assert output_queue is not None
        try:
            while True:
                ev = await output_queue.get()
                ev_cmd = ev.get("cmd")
                if ev_cmd == "pty_output":
                    await websocket.send_json({"cmd": "pty_output", "data": ev.get("data", "")})
                elif ev_cmd == "pty_exit":
                    await websocket.send_json(
                        {"cmd": "pty_exit", "exit_code": ev.get("exit_code", 0)}
                    )
                    break
        except Exception:
            pass

    reader_task = asyncio.create_task(forward_pty_to_ws())

    try:
        while True:
            payload = await websocket.receive_json()
            cmd = payload.get("cmd")
            if cmd == "input":
                data = payload.get("data") or ""
                if local_pty:
                    local_pty.write(data)
                elif remote_session_id:
                    await node_bridge.send_remote_pty_input(node_id, remote_session_id, data)
            elif cmd == "resize":
                new_cols = int(payload.get("cols") or cols)
                new_rows = int(payload.get("rows") or rows)
                if local_pty:
                    local_pty.resize(new_cols, new_rows)
                elif remote_session_id:
                    await node_bridge.resize_remote_pty(node_id, remote_session_id, new_cols, new_rows)
            elif cmd == "exec":
                # Compatibilidad retroactiva: escribir el comando directamente en el PTY real
                command_line = (payload.get("command") or "").strip()
                if command_line:
                    line = command_line + ("\r\n" if platform.system().lower().startswith("win") else "\n")
                    if local_pty:
                        local_pty.write(line)
                    elif remote_session_id:
                        await node_bridge.send_remote_pty_input(node_id, remote_session_id, command_line + "\r\n")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        reader_task.cancel()
        if local_pty:
            local_pty.close()
        if remote_session_id:
            await node_bridge.close_remote_pty(node_id, remote_session_id)


@router.get("/{node_id}/git/status", response_model=ResponseModel)
async def get_workspace_git_status(
    node_id: str,
    workspace: str = Query("."),
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-26: Obtiene rama actual, git status y resumen de diffs del proyecto."""
    await auth.get_authenticated_user(authorization)
    try:
        res = await node_bridge.execute_on_node(node_id, "git_status", {"workspace": workspace})
        return ResponseModel(message="Estado Git obtenido", data=res)
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ---------------------------------------------------------------------------
# Menú Oficial de Complementos / Extensiones de VS Code (Visual Studio Marketplace + OpenVSX) (HU-31)
# ---------------------------------------------------------------------------
async def _query_official_vscode_marketplace(query: str, page_size: int = 20) -> list:
    """Consulta la API oficial del Visual Studio Code Marketplace (con respaldo OpenVSX)."""
    results = []
    # 1. API oficial del Visual Studio Marketplace
    try:
        criteria = [{"filterType": 8, "value": "Microsoft.VisualStudio.Code"}]
        if query.strip():
            criteria.append({"filterType": 10, "value": query.strip()})
        payload = {
            "filters": [
                {
                    "criteria": criteria,
                    "pageNumber": 1,
                    "pageSize": page_size,
                    "sortBy": 4 if not query.strip() else 0,  # 4 = InstallCount (Populares), 0 = Relevancia
                    "sortOrder": 0,
                }
            ],
            "assetTypes": ["Microsoft.VisualStudio.Services.Icons.Default", "Microsoft.VisualStudio.Services.Icons.Small"],
            "flags": 914,
        }
        headers = {
            "Accept": "application/json;api-version=3.0-preview.1",
            "Content-Type": "application/json",
            "User-Agent": "VSCode/1.95.0 (InsanusChat Workbench)",
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery",
                json=payload,
                headers=headers,
            )
            if resp.status_code == 200:
                exts = ((resp.json().get("results") or [{}])[0]).get("extensions") or []
                for e in exts:
                    pub = (e.get("publisher") or {}).get("publisherName") or ""
                    pub_disp = (e.get("publisher") or {}).get("displayName") or pub
                    verified = bool((e.get("publisher") or {}).get("isDomainVerified"))
                    ext_name = e.get("extensionName") or ""
                    ext_id = f"{pub}.{ext_name}"
                    versions = e.get("versions") or []
                    latest_v = versions[0] if versions else {}
                    version_str = latest_v.get("version") or "latest"
                    icon_url = None
                    for f in latest_v.get("files") or []:
                        if f.get("assetType") in (
                            "Microsoft.VisualStudio.Services.Icons.Small",
                            "Microsoft.VisualStudio.Services.Icons.Default",
                        ):
                            icon_url = f.get("source")
                            break
                    stats = {s.get("statisticName"): s.get("value") for s in (e.get("statistics") or [])}
                    installs = int(stats.get("install", 0) or 0)
                    rating = round(float(stats.get("averagerating", 0) or 0), 1)
                    results.append(
                        {
                            "id": ext_id,
                            "display_name": e.get("displayName") or ext_name,
                            "publisher": pub_disp,
                            "publisher_id": pub,
                            "verified": verified,
                            "version": version_str,
                            "description": e.get("shortDescription") or "",
                            "icon_url": icon_url,
                            "install_count": installs,
                            "rating": rating,
                            "categories": e.get("categories") or [],
                            "marketplace_url": f"https://marketplace.visualstudio.com/items?itemName={ext_id}",
                            "source": "vscode-marketplace",
                        }
                    )
    except Exception as e:
        logger.debug("VS Marketplace fallback a OpenVSX: %s", e)

    if results:
        return results

    # 2. Fallback: OpenVSX Registry oficial
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                "https://open-vsx.org/api/-/search",
                params={"query": query.strip() or "", "size": page_size, "sortBy": "downloadCount"},
            )
            if r.status_code == 200:
                for e in r.json().get("extensions") or []:
                    ns = e.get("namespace") or ""
                    name = e.get("name") or ""
                    ext_id = f"{ns}.{name}"
                    results.append(
                        {
                            "id": ext_id,
                            "display_name": e.get("displayName") or name,
                            "publisher": ns,
                            "publisher_id": ns,
                            "verified": bool(e.get("verified")),
                            "version": e.get("version") or "latest",
                            "description": e.get("description") or "",
                            "icon_url": (e.get("files") or {}).get("icon"),
                            "install_count": int(e.get("downloadCount") or 0),
                            "rating": round(float(e.get("averageRating") or 0), 1),
                            "categories": [],
                            "marketplace_url": f"https://open-vsx.org/extension/{ns}/{name}",
                            "source": "open-vsx",
                        }
                    )
    except Exception as e:
        logger.debug("Error consultando OpenVSX: %s", e)
    return results


@router.get("/{node_id}/vscode/extensions/search", response_model=ResponseModel)
async def search_official_vscode_extensions(
    node_id: str,
    query: str = Query("", description="Buscar complementos en el Marketplace Oficial de VS Code"),
    page_size: int = Query(20, ge=1, le=50),
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-31: Busca complementos en vivo en el Visual Studio Code Marketplace oficial (+ OpenVSX)."""
    await auth.get_authenticated_user(authorization)
    extensions = await _query_official_vscode_marketplace(query, page_size=page_size)
    return ResponseModel(message="Extensiones del Marketplace VS Code obtenidas", data={"extensions": extensions})


@router.get("/{node_id}/vscode/extensions/installed", response_model=ResponseModel)
async def list_node_vscode_extensions(
    node_id: str,
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-31: Lista las extensiones de VS Code instaladas en el equipo de ejecución."""
    user = await auth.get_authenticated_user(authorization)
    try:
        items = await node_bridge.execute_on_node(node_id, "list_extensions", {}, user_id=str(user["_id"]))
        return ResponseModel(message="Extensiones instaladas listadas", data={"extensions": items})
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{node_id}/vscode/extensions/install", response_model=ResponseModel)
async def install_node_vscode_extension(
    node_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-31 / HU-35: Instala una extensión oficial de VS Code en el equipo y la sincroniza en MongoDB."""
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    try:
        res = await node_bridge.execute_on_node(
            node_id,
            "install_extension",
            {"extension": body},
            user_id=uid,
        )
        ext_rec = res.get("extension") if isinstance(res, dict) and isinstance(res.get("extension"), dict) else body
        await node_bridge.record_synced_extension(uid, node_id, "install", ext_record=ext_rec)
        return ResponseModel(message="Extensión instalada", data=res)
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{node_id}/vscode/extensions/{ext_id}", response_model=ResponseModel)
async def uninstall_node_vscode_extension(
    node_id: str,
    ext_id: str,
    authorization: str = Header(..., alias="Authorization"),
):
    """HU-31 / HU-35: Desinstala una extensión de VS Code del equipo y actualiza el manifiesto en MongoDB."""
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    try:
        res = await node_bridge.execute_on_node(
            node_id,
            "uninstall_extension",
            {"ext_id": ext_id},
            user_id=uid,
        )
        await node_bridge.record_synced_extension(uid, node_id, "uninstall", ext_id=ext_id)
        return ResponseModel(message="Extensión desinstalada", data=res)
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.websocket("/ws")
async def workstation_node_tunnel_ws(websocket: WebSocket):
    """
    HU-20 / HU-34: Túnel WebSocket saliente desde `InsanusChat_Workstation` hacia `InsanusChat_Backend`.
    Solo se conecta cuando el usuario activa '🌐 Control Remoto' en su aplicación local.
    Sincroniza con MongoDB SSOT en `node_register` y `heartbeat`.
    """
    await websocket.accept()
    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization") or websocket.headers.get("Authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()

    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        decoded = auth.authenticate_token(token)
        uid = str(decoded.get("uid") or decoded.get("user_id") or "")
    except Exception:
        uid = ""

    if not uid:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    node_id = websocket.query_params.get("node_id") or f"workstation-{uuid.uuid4().hex[:8]}"

    try:
        while True:
            payload = await websocket.receive_json()
            cmd = payload.get("cmd")
            if cmd == "node_register":
                node_id = payload.get("node_id") or node_id
                try:
                    sync_data = await node_bridge.register_remote_ws(uid, node_id, websocket, payload)
                except PermissionError as pe:
                    await websocket.send_json({"cmd": "device_revoked", "node_id": node_id, "detail": str(pe)})
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    return
                await websocket.send_json(
                    {
                        "cmd": "node_registered",
                        "node_id": node_id,
                        "policy": sync_data.get("policy"),
                        "synced_extensions": sync_data.get("synced_extensions") or [],
                    }
                )
            elif cmd == "rpc_response":
                node_bridge.handle_remote_rpc_response(node_id, payload)
            elif cmd in ("pty_output", "pty_exit"):
                node_bridge.handle_remote_pty_event(node_id, payload)
            elif cmd in ("ide_http_res", "ide_http_head", "ide_http_chunk", "ide_http_end"):
                node_bridge.handle_remote_ide_http_res(node_id, payload)
            elif cmd in ("ide_ws_opened", "ide_ws_frame", "ide_ws_close"):
                node_bridge.handle_remote_ide_ws_event(node_id, payload)
            elif cmd == "heartbeat":
                if node_id in node_bridge.remote_nodes:
                    info = node_bridge.remote_nodes[node_id]["info"]
                    if "workspaces" in payload:
                        info["workspaces"] = payload["workspaces"]
                    if "reported_editors" in payload:
                        info["reported_editors"] = payload["reported_editors"]
                    if "allow_remote_terminal" in payload:
                        info["allow_remote_terminal"] = bool(payload["allow_remote_terminal"])
                    if "allow_remote_agent_tools" in payload:
                        info["allow_remote_agent_tools"] = bool(payload["allow_remote_agent_tools"])
                await websocket.send_json({"cmd": "heartbeat_ack"})
    except WebSocketDisconnect:
        node_bridge.unregister_remote_ws(node_id)
    except Exception as e:
        logger.debug("Desconexión en túnel de nodo %s: %s", node_id, e)
        node_bridge.unregister_remote_ws(node_id)


# ---------------------------------------------------------------------------
# v1.5.0: Sesión y Reverse Proxy Multiplexado para VS Code Real Remoto (/ide/*)
# ---------------------------------------------------------------------------
@router.post("/{node_id}/ide/session", response_model=ResponseModel)
async def create_remote_ide_session(
    node_id: str,
    response: Response,
    body: Dict[str, Any] = Body(default_factory=dict),
    authorization: str = Header(..., alias="Authorization"),
):
    """Inicia el motor VS Code en el Workstation remoto y emite cookie HttpOnly firmada para /ide/{secret}/*."""
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    workspace = str(body.get("workspace") or ".")

    entry = node_bridge.remote_nodes.get(node_id)
    if not entry or not entry.get("ws"):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="El Workstation remoto no está conectado.")
    if str(entry.get("user_id")) != uid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenés permiso para acceder a este equipo.")
    if (entry.get("info") or {}).get("expose_to_cloud") is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El Control Remoto está apagado (Solo Local) en este Workstation.",
        )

    try:
        res = await node_bridge.execute_on_node(
            node_id,
            "ide_ensure_started",
            {"workspace": workspace},
            timeout=30.0,
            user_id=uid,
        )
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    session_secret = str((res or {}).get("session_secret") or "")
    folder_path = str((res or {}).get("folder_path") or "")
    if not session_secret:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="El Workstation no devolvió session_secret del IDE.")

    node_bridge.register_ide_session(session_secret, node_id, uid)
    signed = _sign_ide_cookie(uid, node_id, session_secret)
    response.set_cookie(
        key=IDE_COOKIE_NAME,
        value=signed,
        path="/ide",
        httponly=True,
        samesite="lax",
    )
    ide_url = f"/ide/{session_secret}/?folder={quote(folder_path, safe='/:')}&insanus_embedded=1"
    return ResponseModel(
        message="Sesión IDE remota lista",
        data={
            "ide_url": ide_url,
            "engine": (res or {}).get("engine"),
            "folder_path": folder_path,
            "session_secret": session_secret,
        },
    )


@router.post("/{node_id}/ide/open-file", response_model=ResponseModel)
async def open_file_in_remote_ide(
    node_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: str = Header(..., alias="Authorization"),
):
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    try:
        res = await node_bridge.execute_on_node(
            node_id,
            "ide_open_file",
            {
                "workspace": body.get("workspace") or ".",
                "path": body.get("path") or "",
                "line": body.get("line"),
            },
            user_id=uid,
        )
        return ResponseModel(message="Comando enviado al IDE", data=res)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{node_id}/ide/diagnostics", response_model=ResponseModel)
async def get_remote_ide_diagnostics(
    node_id: str,
    workspace: str = Query("."),
    path: Optional[str] = Query(None),
    authorization: str = Header(..., alias="Authorization"),
):
    user = await auth.get_authenticated_user(authorization)
    uid = str(user["_id"])
    try:
        res = await node_bridge.execute_on_node(
            node_id,
            "get_ide_diagnostics",
            {"workspace": workspace, "path": path},
            user_id=uid,
        )
        return ResponseModel(message="Diagnósticos LSP obtenidos", data=res)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@ide_proxy_router.api_route(
    "/ide/{session_secret}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def remote_ide_proxy_root(request: Request, session_secret: str):
    if not request.url.path.endswith("/"):
        qs = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(url=f"/ide/{session_secret}/{qs}", status_code=307)
    return await _proxy_remote_ide_http(request, session_secret, "")


@ide_proxy_router.api_route(
    "/ide/{session_secret}/{subpath:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def remote_ide_proxy_subpath(request: Request, session_secret: str, subpath: str):
    return await _proxy_remote_ide_http(request, session_secret, subpath)


async def _proxy_remote_ide_http(request: Request, session_secret: str, subpath: str) -> Response:
    verified = _verify_ide_cookie(request.cookies.get(IDE_COOKIE_NAME), session_secret)
    meta = node_bridge.resolve_ide_session(session_secret)
    if not verified or not meta or verified["node_id"] != meta["node_id"] or verified["user_id"] != meta["user_id"]:
        return JSONResponse(status_code=401, content={"detail": "Sesión IDE remota no autorizada o revocada"})

    try:
        body = await request.body()
        res = await node_bridge.proxy_ide_http(
            node_id=meta["node_id"],
            user_id=meta["user_id"],
            method=request.method,
            session_secret=session_secret,
            subpath=subpath,
            query=request.url.query,
            headers=dict(request.headers),
            body=body,
        )
        out = Response(content=res["body"], status_code=res["status"], headers=res["headers"])
        for ck in res.get("set_cookies") or []:
            out.headers.append("set-cookie", ck)
        return out
    except PermissionError as pe:
        return JSONResponse(status_code=403, content={"detail": str(pe)})
    except Exception as e:
        return JSONResponse(status_code=502, content={"detail": f"Error en túnel IDE remoto: {e}"})


@ide_proxy_router.websocket("/ide/{session_secret}")
async def remote_ide_proxy_ws_root(websocket: WebSocket, session_secret: str):
    await _proxy_remote_ide_ws(websocket, session_secret, "")


@ide_proxy_router.websocket("/ide/{session_secret}/{subpath:path}")
async def remote_ide_proxy_ws_subpath(websocket: WebSocket, session_secret: str, subpath: str):
    await _proxy_remote_ide_ws(websocket, session_secret, subpath)


async def _proxy_remote_ide_ws(websocket: WebSocket, session_secret: str, subpath: str) -> None:
    verified = _verify_ide_cookie(websocket.cookies.get(IDE_COOKIE_NAME), session_secret)
    meta = node_bridge.resolve_ide_session(session_secret)
    if not verified or not meta or verified["node_id"] != meta["node_id"] or verified["user_id"] != meta["user_id"]:
        await websocket.close(code=1008)
        return

    node_id = meta["node_id"]
    uid = meta["user_id"]
    stream_id = uuid.uuid4().hex
    subprotocols_hdr = websocket.headers.get("sec-websocket-protocol")
    subprotocols = [s.strip() for s in subprotocols_hdr.split(",") if s.strip()] if subprotocols_hdr else []

    try:
        q = await node_bridge.open_remote_ide_ws(
            node_id=node_id,
            user_id=uid,
            stream_id=stream_id,
            session_secret=session_secret,
            subpath=subpath,
            query=websocket.url.query,
            subprotocols=subprotocols,
        )
        first = await asyncio.wait_for(q.get(), timeout=15.0)
        if first.get("cmd") != "ide_ws_opened":
            await websocket.close(code=1011)
            return
        await websocket.accept(subprotocol=first.get("subprotocol"))

        async def browser_to_node():
            try:
                while True:
                    msg = await websocket.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if msg.get("text") is not None:
                        await node_bridge.send_remote_ide_ws_frame(node_id, stream_id, msg["text"], False)
                    elif msg.get("bytes") is not None:
                        await node_bridge.send_remote_ide_ws_frame(node_id, stream_id, msg["bytes"], True)
            except (WebSocketDisconnect, Exception):
                pass

        async def node_to_browser():
            try:
                while True:
                    ev = await q.get()
                    c = ev.get("cmd")
                    if c == "ide_ws_close":
                        break
                    if c == "ide_ws_frame":
                        if ev.get("is_binary"):
                            await websocket.send_bytes(base64.b64decode(ev.get("data") or ""))
                        else:
                            await websocket.send_text(str(ev.get("data") or ""))
            except Exception:
                pass

        t1 = asyncio.create_task(browser_to_node())
        t2 = asyncio.create_task(node_to_browser())
        _, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for p in pending:
            p.cancel()
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        await node_bridge.close_remote_ide_ws(node_id, stream_id)
