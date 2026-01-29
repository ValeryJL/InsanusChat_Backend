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
  # Documentación API REST y WebSocket — InsanusChat Backend

  Breve referencia (ejemplos mínimos) para usar las APIs REST y WebSocket del backend.

  Nota rápida: muchas rutas requieren header Authorization: Bearer <token>. En ejemplos uso el placeholder $TOKEN.

  ## Comprobación de API
  - Consulta: GET /
    ```bash
    curl -X GET "http://127.0.0.1:8000/" \
      -H "Content-Type: application/json"
    ```
    - Respuesta 200 con JSON: {"message":"InsanusChat Backend is running!"}

  ## Autenticación
  - Registrar: POST /api/v1/auth/register
    Body mínimo:
    ```json
    {"email": "user@example.com", "password": "secret", "username": "opcional"}
    ```
    Ejemplo curl:
    ```bash
    curl -X POST "http://127.0.0.1:8000/api/v1/auth/register" \
      -H "Content-Type: application/json" \
      -d '{"email":"user@example.com","password":"secret","username":"user123"}'
    ```

  - Login: POST /api/v1/auth/login
    Body:
    ```json
    {"email": "user@example.com", "password": "secret"}
    ```
    Ejemplo curl:
    ```bash
    curl -X POST "http://127.0.0.1:8000/api/v1/auth/login" \
      -H "Content-Type: application/json" \
      -d '{"email":"user@example.com","password":"secret"}'
    ```
    Respuesta: JSON con `access_token` (Bearer JWT), p. ej:
    ```json
    {"access_token": "ey...", "token_type": "bearer"}
    ```
    Guarda el token: `TOKEN=ey...` y úsalo en el header `Authorization: Bearer $TOKEN`.

  - Obtener perfil: GET /api/v1/auth
    ```bash
    curl -X GET "http://127.0.0.1:8000/api/v1/auth" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json"
    ```

  - Modificar perfil: PUT /api/v1/auth
    Body (ejemplo):
    ```json
    {"email": "nuevo@example.com", "username": "nuevo_nombre"}
    ```

  ## Agents
  - Listar agentes: GET /api/v1/agents (Authorization required)
  - Crear agente: POST /api/v1/agents (Authorization required)
    Body ejemplo: name, description, system_prompt, snippets, active_tools, model_selected, etc.

  ## Chats (REST)
  Todos los endpoints de chats requieren header: `Authorization: Bearer <token>`.

  - Listar chats: GET /api/v1/chats/
    - Respuesta: lista de chats del usuario (cada chat con ids sanitizados).

  - Crear chat (REST): POST /api/v1/chats/
    - Body mínimo: {"message": "Texto inicial"}
    - agent_id es opcional; si se provee debe ser un string con el ObjectId del agente. Ejemplo válido:
      {"message":"Hola","agent_id":"<AGENT_ID>", "title":"Chat WS"}
    - Respuesta: el chat creado (objeto `chat` con `_id`);
    - Nota: tras crear el chat el backend iniciará (si aplica) la generación del saludo por el agente y lo transmitirá a clientes WS conectados.

  Ejemplo curl (crear chat):

  ```bash
  curl -X POST "http://127.0.0.1:8000/api/v1/chats/" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"message":"Hola","agent_id":"<AGENT_ID>", "title":"Chat WS"}'
  ```

  - Listar mensajes de un chat: GET /api/v1/chats/{chat_id}/messages
    - Respuesta: lista lineal de mensajes (IDs como strings).

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

  ## API Keys y Recursos (MCPs / Snippets)
  - API Keys (user-scoped): GET/POST/PUT/DELETE en `/api/v1/apikeys/` (Authorization required)
  - MCPs: `/api/v1/resources/mcps` (crear/actualizar/eliminar)
  - Snippets: `/api/v1/resources/snippets` (crear/actualizar/eliminar)

  ## WebSocket
  Hay dos endpoints WS relacionados:

  1) Crear chat vía WebSocket (no requiere `chat_id` en la URL):
     - URL: `ws://HOST/api/v1/chats/ws` o `wss://HOST/api/v1/chats/ws` (usar wss en producción)
     - Handshake: header `Authorization: Bearer <token>` obligatorio
     - Flujo: el cliente envía como primer mensaje JSON la solicitud de creación. `agent_id` es opcional:
       ```json
       {"message": "Texto inicial", "agent_id": "<AGENT_ID>", "title": "opcional"}
       ```
     - Respuesta inmediata: el servidor devuelve `{ "chat": <chat_obj> }` (incluye `_id`) o `{ "chat_id": "..." }` y mantiene la conexión abierta. Luego el servidor inicializará `init` y otros eventos conforme corresponda.

  2) Conectar a un chat existente por WS:
     - URL: `ws://HOST/api/v1/chats/ws/{chat_id}` o `wss://HOST/api/v1/chats/ws/{chat_id}`
     - Handshake: header `Authorization: Bearer <token>` obligatorio
     - Al conectar el servidor envía `init` con contexto y `last_message_id`:
       ```json
       { "init": { "chat": <history>, "branch_anchor": "<id>", "last_message_id": "<id>" } }
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

  - Close
    ```json
    {"cmd": "close/disconnect"}
    ```

  ### Formato de sobres salientes (servidor -> cliente)
  El servidor envía sobres JSON textuales (siempre `send_text` con JSON string). Secuencia típica al persistir un mensaje:

  - ACK (confirmación de persistencia):
    - El servicio inserta el mensaje y primero broadcastea un ACK envelope. Actualmente la forma del ACK es:
    ```json
    {"cmd": "ack", "message": {"mensaje": <message_doc_sanitized>}}
    ```
    donde `mensaje` contiene el mensaje persistido (ids como strings, fechas iso).

  - Luego se broadcastea el mensaje real (ConnectionManager envolverá el `message` con `cmd` según su `role`):
    ```json
    {"cmd": "user_message" | "agent_message" | "system_message", "message": {...}}
    ```

  - Historia/ventana de mensajes:
    ```json
    {"cmd": "history", "history": {...}}
    ```

  - Bloqueo/liberación de chat:
    ```json
    {"cmd": "chat_locked", "message": {"locked": true}}
    {"cmd": "chat_unlocked", "message": {"locked": false}}
    ```

  - Error:
    ```json
    {"cmd": "error", "error": "mensaje"}
    ```

  ### Ejemplo mínimo con websocat (crear chat + recibir saludo)
  ```bash
  # conectar (ejemplo usando ws en dev; en producción preferir wss)
  websocat -H "Authorization: Bearer $TOKEN" ws://127.0.0.1:8000/api/v1/chats/ws
  # enviar (primer mensaje JSON esperado por el endpoint):
  # {"message":"Hola desde websocat","agent_id":"<AGENT_ID>","title":"Test"}
  ```

  ### Ejemplo mínimo cliente (scripts/WS.py)
  - El archivo `scripts/WS.py` en el repositorio es un cliente sencillo que:
    - Hace login por REST para obtener token
    - Conecta a `/api/v1/chats/ws` (creación) o a `/api/v1/chats/ws/{chat_id}`
    - Mantiene un hilo receptor en background que imprime eventos entrantes
    - Permite enviar comandos JSON como `{cmd: 'send', text: ..., parent_id: ...}` desde la línea de comandos

  ## Notas y recomendaciones
  - `parent_id` es obligatorio cuando se publica una respuesta (REST o WS). El modelo de mensajes es un árbol; siempre especifica el padre.
  - `agent_id` es opcional en la creación de chats; si lo provees debe ser un string válido (ObjectId).
  - El servidor sanitiza ObjectId / datetimes antes de enviarlos por WS/REST (ids como strings, fechas en ISO).
  - Si ves errores 500 al llamar `/api/v1/chats/{chat_id}/messages`, revisa que `chat_id` no sea `None` y que el `Authorization` sea válido.

  ---
  Archivo actualizado para reflejar la implementación actual: create-vía-WS mantiene la conexión, `agent_id` es opcional, y la secuencia de broadcast es ACK (con `mensaje`) seguido del mensaje normal.