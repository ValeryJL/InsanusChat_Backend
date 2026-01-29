# InsanusChat_Backend
Backend FastAPI de mi proyecto de chat para crear agentes ia, con acceso a herramientas, mcp servers, y un chat bifurcado visual

## Recientes Mejoras (2026-01)

Este backend ha sido refactorizado para aprovechar mejor **LangChain** en la ejecución de agentes, con mejoras significativas en:
- Integración de MCP (Model Context Protocol) servers como herramientas LangChain
- Ejecución de snippets de código (Python/JavaScript) como herramientas
- Mejor manejo de errores y logging
- Tests automatizados

Ver [REFACTORING.md](REFACTORING.md) para detalles completos de la refactorización.

## Instalación

Requisitos previos
- Python 3.12.1 instalado
- pip, git

Pasos rápidos (entorno virtual)
1. Clonar el repo:
    ```
    git clone https://github.com/ValeryJL/InsanusChat_Backend.git
    cd InsanusChat_Backend
    ```
2. Crear y activar entorno virtual:
    ```
    python -m venv .venv
    source .venv/bin/activate
    ```
3. Instalar dependencias:
    ```
    pip install -r requirements.txt
    ```
4. Configurar variables de entorno (ver sección siguiente).
5. Ejecutar la aplicación en modo desarrollo (ajustar el import si tu app principal no es `backend:app`, `backend.py`, `Class app`):
    ```
    uvicorn backend:app --reload --host 0.0.0.0 --port PORT
    ```

## Variables de entorno recomendadas

Crea un archivo `.env` en la raíz con las variables necesarias. Ejemplo mínimo:

```
# Entorno
PORT=8000

# Seguridad / Aplicación
LOCAL_AUTH_SECRET="secreto de JWT"
LOCAL_AUTH_ALG="algoritmo de encriptación"
LOCAL_AUTH_EXPIRE_MIN="tiempo de expiracion del token JWT"

# Base de datos
MONGO_URI="cadena de coneccion a mongoDB"
MONGO_X509_CERT_PATH="./secrets/mongodb-cert.pem"
```

Sugerencias
- Usa gestores de secretos (Vault, AWS Secrets Manager, GitHub Secrets) en producción en lugar de `.env`.
- Genera LOCAL_AUTH_SECRET con un generador seguro y cambia valores por defecto antes de desplegar.

## Configuración Local para Desarrollo

### MongoDB Local

Para configurar MongoDB localmente para pruebas:

```bash
./setup_local_mongodb.sh
```

O manualmente con Docker:
```bash
docker run -d \
  --name insanuschat-mongodb \
  -p 27017:27017 \
  -v $(pwd)/mongodb_data:/data/db \
  -e MONGO_INITDB_ROOT_USERNAME=admin \
  -e MONGO_INITDB_ROOT_PASSWORD=insanus_admin_pass \
  mongo:7.0
```

Luego agrega a `.env`:
```
MONGO_URI="mongodb://admin:insanus_admin_pass@localhost:27017/insanus_chat?authSource=admin"
```

### Certificado X.509

Para generar certificados de prueba:

```bash
cd secrets
./create-cert.sh
```

Esto crea los certificados necesarios en `secrets/mongodb-cert.pem`.

## Testing

Ejecutar tests:
```bash
python3 -m pytest tests/ -v
```

Tests específicos:
```bash
# Tests de snippets
python3 -m pytest tests/test_snippets.py -v

# Tests de LangChain tools
python3 -m pytest tests/test_langchain_tools.py -v

# Tests de MCP client
python3 -m pytest tests/test_mcp_client.py -v
```

## Ejemplos

### Servidor MCP de Ejemplo

Ver `examples/mcp_servers/calculator_server.py` para un ejemplo completo de servidor MCP.

Ejecutar:
```bash
python3 examples/mcp_servers/calculator_server.py
```

## Arquitectura

- **Backend FastAPI**: API REST y WebSocket para chat
- **MongoDB**: Base de datos para usuarios, chats, mensajes, agentes
- **LangChain**: Framework para agentes y herramientas
- **MCP Servers**: Servidores de herramientas externos
- **Code Snippets**: Ejecución de código Python/JavaScript

Para más detalles, ver [REFACTORING.md](REFACTORING.md).