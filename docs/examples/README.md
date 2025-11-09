# Ejemplos de la API - InsanusChat Backend

Esta carpeta contiene ejemplos listos para usar: curl y una colección Postman mínima.

Archivos:
- `curls.md`: comandos curl para endpoints principales (registro, login, apikeys, agents, chats).
- `postman_collection.json`: colección Postman (export) con ejemplos de request/response.

Cómo usar:
1. Levanta la API localmente: `uvicorn backend:app --reload`
2. Rellena `<BASE_URL>` y `<TOKEN>` en `curls.md` y ejecuta los comandos.
3. Importa `postman_collection.json` en Postman para probar requests con ejemplos incluidos.
