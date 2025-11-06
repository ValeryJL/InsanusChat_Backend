# Documentación API REST y WebSocket — InsanusChat Backend

Breve referencia (ejemplos mínimos) para usar las APIs REST y WebSocket del backend.

## Comprobación de API
- Consulta: GET /
  ```bash
  curl -X GET "http://127.0.0.1:8000/" \
    -H "Content-Type: application/json"
  ```
  - Respuesta 200 con JSON ```{"message":"InsanusChat Backend is running!"}```

## Autenticación
- Registrar: POST /api/v1/auth/register
  ```json
  Body: {
          "email": "user@example.com", 
          "password": "secret", 
          "username": "opcional"
  }
  ```
  - Ejemplo curl
  ```bash
  curl -X POST "http://127.0.0.1:8000/api/v1/auth/register" \
    -H "Content-Type: application/json" \
    -d '{"email":"user@example.com","password":"secret","username":"user123"}'
  ```
  - Respuesta 200 OK si se creó.
  ___
- Login: POST /api/v1/auth/login
  ```json
  Body: {
    "email": "user@example.com",
    "password": "secret"
  }
  ```
  - Ejemplo curl
  ```bash
  curl -X POST "http://127.0.0.1:8000/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"email":"user@example.com","password":"secret"}'
  ```
  - Respuesta: JSON con `access_token` (Bearer JWT), p. ej.
  ```json
  {
    "access_token": "ey...",
    "token_type": "bearer"
  }
  ```
  - Guarda el token: `TOKEN=ey...` y úsalo en el header `Authorization: Bearer $TOKEN`.
  ___
- Obtener perfil: GET /api/v1/auth
  ```http
  Header: {
    "Authorization": "Bearer $TOKEN"
  }
  ```
  - Ejemplo curl
  ```bash
  curl -X GET "http://127.0.0.1:8000/api/v1/auth" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json"
  ```
  - Respuesta: JSON con datos del usuario y configuración de perfil.
  ___
- Modificar perfil: PUT /api/v1/auth
  ```json
  Header: {
    "Authorization": "Bearer $TOKEN",
    "Content-Type": "application/json"
  }

  Body: {
    "email": "nuevo@example.com",
    "username": "nuevo_nombre",
    "other_field": "valor"
  }
  ```
  - Ejemplo curl
  ```bash
  curl -X PUT "http://127.0.0.1:8000/api/v1/auth" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"email":"nuevo@example.com","username":"nuevo_nombre"}'
  ```
  - Respuesta: JSON con los datos de usuario actualizados y la configuración de perfil.


## Endpoints Agents
- Listar agentes: GET /api/v1/agents
  - Header: Authorization: Bearer <token>
  - Respuesta: {"message":"Agentes listados","data":[...]} donde cada agente ya está serializado (ids->string).

- Crear agente: POST /api/v1/agents
  - Header: Authorization
  - Body ejemplo:
    ```json
    {
      "name": "Mi Agent",
      "description": "...",
      "system_prompt": ["You are a bot."],
      "snippets": [{"name":"now","language":"javascript","code":"return Date.now()"}],
      "active_tools": [],
      "active_mcps": [],
      "model_selected": "gpt-4o"
    }
    ```
  - Respuesta: {"message":"Agente creado","data":{...}}

- Update: PUT /api/v1/agents/{agent_id}
    - Acepta los mismos parametros que la creacion, pero aca ninguno es necesario
- Delete: DELETE /api/v1/agents/{agent_id}

## Chats (REST)
Todos los endpoints de chats requieren header: `Authorization: Bearer <token>`.

- Listar chats: GET /api/v1/chats/
  - Respuesta: lista de chats del usuario (cada chat con ids sanitizados).

- Crear chat (REST): POST /api/v1/chats/
  - Body mínimo requerido: {"message": "Texto inicial", "agent_id": "<agent_id>", "title": "opcional"}
  - Respuesta: chat creado (objeto `chat` con `_id`)
  - Nota: el backend también inicia el saludo del agente y lo transmite a los clientes WS cuando aplica.

Ejemplo curl (crear chat):

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/chats/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Hola","agent_id":"<AGENT_ID>", "title":"Chat WS"}'
```

- Listar mensajes de un chat: GET /api/v1/chats/{chat_id}/messages
  - Respuesta: lista lineal de mensajes (IDs ya en string).

- Publicar mensaje (REST): POST /api/v1/chats/{chat_id}/messages
  - Body: {"text": "...", "parent_id": "<message_id>"}
  - Reglas: `parent_id` es obligatorio (las respuestas deben indicar el padre). El servidor valida pertenencia y lock.

Ejemplo curl (post message):

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/chats/<CHAT_ID>/messages" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"Hola agente","parent_id":"<PARENT_MSG_ID>"}'
```

## API Keys y Herramientas (MCPs / Snippets)

- API Keys (user-scoped)
  - Listar: GET /api/v1/apikeys/
    - Header: Authorization: Bearer <token>
    - Respuesta: {"message":"API keys listadas","data":[{_id,provider,label,created_at,...}]}
  - Crear: POST /api/v1/apikeys/
    - Body: {"provider":"openai","encrypted_key":"<enc>","label":"mi key"}
  - Actualizar: PUT /api/v1/apikeys/{key_id} (fields: label, active, encrypted_key)
  - Eliminar: DELETE /api/v1/apikeys/{key_id}

  Ejemplo curl (crear):

  ```bash
  curl -X POST "http://127.0.0.1:8000/api/v1/apikeys/" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"provider":"openai","encrypted_key":"...","label":"test"}'
  ```

- Herramientas / Recursos (MCPs y Code Snippets)
  - Base: prefix `/api/v1/resources`
  - Listar recursos: GET /api/v1/resources/ -> devuelve `mcps` y `code_snippets` del usuario.

  MCPs (endpoints externos):
  - Crear MCP: POST /api/v1/resources/mcps
    - Body ejemplo: {"name":"MCP1","endpoint":"https://...","spec":{},"auth":{},"metadata":{}}
  - Actualizar: PUT /api/v1/resources/mcps/{mcp_id}
  - Eliminar: DELETE /api/v1/resources/mcps/{mcp_id}

  Code Snippets:
  - Crear: POST /api/v1/resources/snippets
    - Body: {"name":"now","language":"javascript","code":"return Date.now()"}
  - Actualizar: PUT /api/v1/resources/snippets/{snippet_id}
  - Eliminar: DELETE /api/v1/resources/snippets/{snippet_id}

  Ejemplo curl (crear snippet):

  ```bash
  curl -X POST "http://127.0.0.1:8000/api/v1/resources/snippets" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"name":"now","language":"javascript","code":"return Date.now()"}'
  ```

---
Archivo generado automáticamente por asistentes. Si querés, lo ajusto con más ejemplos (Python ws client, JSON pretty-print de history, o Postman collection).

## WebSocket
Hay dos endpoints WS relacionados:

1) Crear chat vía WebSocket (no requiere `chat_id`):
   - URL: `ws://HOST/api/v1/chats/ws`
   - Handshake: header `Authorization: Bearer <token>` obligatorio
   - Flujo: el cliente envía como primer mensaje JSON la solicitud de creación:
     ```json
     {"message": "Texto inicial", "agent_id": "<AGENT_ID>", "title": "opcional"}
     ```
   - Respuesta inmediata: el servidor devuelve `{ "chat": <chat_obj> }` o `{ "chat_id": "..." }` y luego delega a `websocket_handler` para mantener el socket abierto y enviar `init` y mensajes posteriores.

2) Conectar a un chat existente por WS:
   - URL: `ws://HOST/api/v1/chats/ws/{chat_id}`
   - Handshake: header `Authorization: Bearer <token>` obligatorio
   - Al conectar el servidor envía `init` con contexto y `last_message_id`:
     ```json
     { "init": { "chat": <tree|history>, "branch_anchor": "<id>", "last_message_id": "<id>", "recent": [...] } }
     ```

### Formato de comandos entrantes (cliente -> servidor)
El `websocket_handler` acepta sobres JSON con el campo `cmd`:

- Enviar mensaje (crear reply):
  ```json
  {"cmd": "send", "text": "Hola", "parent_id": "<message_id>"}
  ```
  - `parent_id` **requerido**.

- Fetch from top (descendientes / ventana):
  ```json
  {"cmd": "fetch_from_top", "id": "<message_id>", "limit": 16, "direction": "left|right"}
  ```

- Fetch from bottom (ancestros):
  ```json
  {"cmd": "fetch_from_bottom", "id": "<message_id>", "limit": 16}
  ```

- Get single message:
  ```json
  {"cmd": "get", "id": "<message_id>"}
  ```

- Ping:
  ```json
  {"cmd": "ping"}
  ```

### Formato de sobres salientes (servidor -> cliente)
El servidor envía sobres JSON textuales (siempre `send_text` con JSON string):

- Acknowledgement al crear mensaje enviado por WS:
  ```json
  {"cmd": "ack", "message": {"_id": "<inserted_id>"}}
  ```

- Envío de un mensaje (broadcast):
  ```json
  {"cmd": "user_message"|"agent_message"|"system_message", "message": {...}}
  ```
  - `message` contiene campos sanitizados (ids como strings, `created_at` isoformat)

- Historia/ventana de mensajes:
  ```json
  {"cmd": "history", "history": {"Result": [ ... ]}}
  ```
  - La estructura `history` depende de la función llamada (top/bottom); los ids ya vienen como strings.

- Bloqueo/liberación de chat:
  ```json
  {"cmd": "chat_locked", "message": {"locked": True/False}}
  ```

- Error:
  ```json
  {"cmd": "error", "error": "mensaje"}
  ```

### Ejemplo mínimo con websocat (crear chat + recibir saludo)
```bash
# crear chat via WS
websocat -H "Authorization: Bearer $TOKEN" ws://127.0.0.1:8000/api/v1/chats/ws
# enviar (primer mensaje JSON esperado por el endpoint):
# {"message":"Hola desde websocat","agent_id":"<AGENT_ID>","title":"Test"}
```

### Ejemplo mínimo cliente (usar `scripts/ws_client.py` incluido)
- El script `scripts/ws_client.py` ya implementa:
  - Login/registro interactivo
  - Conexión a `/api/v1/chats/ws` (creación) si no das `--chat-id`
  - Envío de mensajes con `{cmd: 'send', text: ..., parent_id: ...}`
  - Comandos interactivos: `/status`, `/reconnect`, `/wait`, `/quit`

## Notas y recomendaciones
- `parent_id` es obligatorio cuando se publica una respuesta. El modelo de mensajes es un árbol; siempre especifica el padre.
- El servidor sanitiza ObjectId / datetimes antes de enviarlos por WS/REST (ids como strings).
- Si ves errores 500 al llamar `/api/v1/chats/{chat_id}/messages`, revisa que `chat_id` no sea `None` y que el `Authorization` sea válido.
- Para debug rápido, usa `scripts/ws_client.py --token "$TOKEN" --agent-id "<AGENT_ID>"`.