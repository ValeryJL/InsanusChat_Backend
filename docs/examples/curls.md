# Ejemplos curl para InsanusChat Backend

Sustituye <BASE_URL> por http://127.0.0.1:8000 y <TOKEN> por tu JWT.

## Registro (POST /api/v1/auth/register)
curl -X POST "<BASE_URL>/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"secret","display_name":"Usuario Demo"}'

## Login (POST /api/v1/auth/login)
curl -X POST "<BASE_URL>/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"secret"}'

## Obtener perfil (GET /api/v1/auth/)
curl -X GET "<BASE_URL>/api/v1/auth/" \
  -H "Authorization: Bearer <TOKEN>"

## Listar API Keys (GET /api/v1/apikeys/)
curl -X GET "<BASE_URL>/api/v1/apikeys/" \
  -H "Authorization: Bearer <TOKEN>"

## Crear API Key (POST /api/v1/apikeys/)
curl -X POST "<BASE_URL>/api/v1/apikeys/" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"provider":"openai","encrypted_key":"<encrypted>","label":"Mi OpenAI"}'

## Listar agentes (GET /api/v1/agents/)
curl -X GET "<BASE_URL>/api/v1/agents/" \
  -H "Authorization: Bearer <TOKEN>"

## Crear agente (POST /api/v1/agents/)
curl -X POST "<BASE_URL>/api/v1/agents/" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Mi Agent","description":"Agent de prueba","system_prompt":["You are a bot."],"snippets":[]}'

## Listar chats (GET /api/v1/chats/)
curl -X GET "<BASE_URL>/api/v1/chats/" \
  -H "Authorization: Bearer <TOKEN>"

## Crear chat (POST /api/v1/chats/)
curl -X POST "<BASE_URL>/api/v1/chats/" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"title":"Mi chat","message":"Hola, quiero probar el agente"}'

## Listar mensajes (GET /api/v1/chats/{chat_id}/messages)
curl -X GET "<BASE_URL>/api/v1/chats/<chat_id>/messages" \
  -H "Authorization: Bearer <TOKEN>"

## Publicar mensaje (POST /api/v1/chats/{chat_id}/messages)
curl -X POST "<BASE_URL>/api/v1/chats/<chat_id>/messages" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"text":"Hola desde curl","parent_id":"<parent_message_id>"}'
