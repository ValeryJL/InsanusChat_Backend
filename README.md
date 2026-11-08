# InsanusChat — Backend Central & Orquestador de Agent Harness (FastAPI + LangGraph + MongoDB)

Backend asíncrono para la plataforma **InsanusChat**: conversaciones ramificadas en **Árbol 2D**, motor de **Agentes de IA Multi-Proveedor (LangChain v1.5 & LangGraph)**, **Agent Harness distribuido** con soporte para **Equipos de Ejecución Locales (`Workstations`)**, **Editor de Código VS Code integrado**, **Servidores MCP (`stdio`, `sse`, `http`)**, **Sandbox de Code Snippets**, cifrado **Fernet (AES)** en reposo y **Panel de Administración & Gobernanza**.

---

## Arquitectura & Características Principales

### 1. Árbol de Conversaciones Ramificadas (`/api/v1/chats` & WebSocket `/api/v1/chats/ws`)
- **Topología DAG/Árbol (`HU-01`, `HU-02`)**: Cada mensaje almacena `parent_id`, `children_ids`, `path`, `branch_anchor`, `cousin_left` y `cousin_right`.
- **Aislamiento Estricto por Rama**: `_build_branch_history` camina exclusivamente por la cadena de ancestros de la rama activa y recorta de forma segura con `trim_messages`.
- **Prevención de Deadlocks (`HU-03`)**: Bloqueo por chat con TTL de 120 segundos y liberación garantizada en bloques `finally`.
- **Streaming Token a Token y Eventos de Harness (`HU-08`, `HU-22`)**:
  - `agent_stream_start`, `agent_token`, `agent_tool_start`, `agent_tool_end`, `agent_message`.
  - `agent_plan_updated`: Sincronización en vivo del checklist de tareas del agente (`harness_update_plan`).
  - `agent_tool_approval_needed` / `agent_tool_approval_resolved`: Pausa y confirmación *Human-in-the-Loop* en tiempo real antes de editar archivos o correr comandos.

### 2. Agent Harness & Hub de Equipos de Ejecución (`/api/v1/nodes`)
- **Dos Modos de Entorno por Conversación (`HU-20`, `HU-29`)**:
  - `☁️ Cloud (Nube)`: Chat estándar ejecutado 100% en el servidor central con MCPs y Snippets en contenedor.
  - `💻 Workstation (Equipo Local)`: Vincula el chat a una PC de desarrollo (`node_id`) y una carpeta de proyecto (`workspace_path`).
- **Control Plane SSOT en MongoDB (`workstations` — `HU-33`, `HU-34`, `HU-35`)**:
  - `POST /api/v1/nodes/register-device`: Registro persistente de equipos Workstation Desktop (Windows/Linux) con estado `online`, `private_local_only`, `offline` o `revoked`.
  - `GET /api/v1/nodes/{node_id}/sync`: Devuelve la política autoritativa (`desired_policy`, `config_version`) y el manifiesto `synced_extensions` de VS Code.
  - `PATCH /api/v1/nodes/{node_id}/policy`: Incrementa `config_version`, persiste cambios en MongoDB, empuja `policy_sync` por WebSocket en vivo y aplica Kill-Switch remoto (`expose_to_cloud: false`) cerrando sesiones PTY activas (sin permitir nunca encender Control Remoto remotamente si el equipo está aislado).
  - `DELETE /api/v1/nodes/{node_id}`: Revoca un equipo y cierra inmediatamente su túnel WebSocket.
  - Variable `ENABLE_BUILTIN_HOST_NODE`: permite ocultar el contenedor Docker como nodo de ejecución cuando se opera únicamente con Host PCs reales (`HU-36`).
- **Túnel WebSocket Bidireccional (`/api/v1/nodes/ws`)**:
  - La aplicación Desktop **InsanusChat Workstation** (compilada desde `InsanusChat_Frontend` con Tauri v2 + sidecar local) se conecta hacia el backend central únicamente cuando el usuario activa **`🌐 Control Remoto`**.
- **Suite de Herramientas del Harness (`services/harness_tools.py` — `HU-21`, `HU-25`, `HU-26`)**:
  - `workspace_list_files`, `workspace_read_file` (con numeración de líneas), `workspace_write_file`, `workspace_edit_file` (reemplazo quirúrgico con generación de **Unified Diff**), `workspace_grep_search`, `workspace_run_command`, `workspace_git_checkpoint` y `harness_update_plan`.
- **Ingeniería de Contexto Automática (`HU-23`)**:
  - Inyección automática del árbol inicial del proyecto y descubrimiento de reglas `AGENTS.md` / `CLAUDE.md` con loop de recursión de hasta **50 pasos** en LangGraph.
- **API de Archivos y Terminal para la Vista de Editor VS Code (`HU-27`, `HU-30`)**:
  - `GET /api/v1/nodes/{node_id}/files/tree`
  - `GET /api/v1/nodes/{node_id}/files/read`
  - `POST /api/v1/nodes/{node_id}/files/write`
  - `POST /api/v1/nodes/{node_id}/files/edit`
  - `POST /api/v1/nodes/{node_id}/terminal/exec`
  - `GET /api/v1/nodes/{node_id}/git/status`

### 3. Seguridad, Criptografía y Gobernanza (`/api/v1/admin`)
- **Cifrado Fernet en Reposo (`HU-05`)**: Las API Keys se cifran con `AES-128-CBC + HMAC` antes de persistirse en MongoDB y siempre se devuelven enmascaradas (`AIza...9876`).
- **Sandbox de Subprocesos (`HU-06`)**: Ejecución aislada de snippets Python/JS limpiando secretos del entorno (`env`).
- **Gobernanza Global (`HU-07`)**: Control administrativo de registro público, permisos `stdio`, políticas de snippets y auditoría/desbloqueo de chats.

---

## Ejecución de Tests E2E

```bash
pytest -v
```
