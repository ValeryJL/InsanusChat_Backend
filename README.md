# InsanusChat_Backend
Backend FastAPI de mi proyecto de chat para crear agentes ia, con acceso a herramientas, mcp servers, y un chat bifurcado visual
## Instalación

Requisitos previos
- Python 3.12.1 instalado
- pip, git

Pasos rápidos (entorno virtual)
1. Clonar el repo:
    ```
    git clone <REPO_URL>
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
5. Ejecutar la aplicación en modo desarrollo (ajustar el import si tu app principal no es `main:app`):
    ```
    uvicorn main:app --reload --host 0.0.0.0 --port $PORT
    ```

## Variables de entorno recomendadas

Crea un archivo `.env` en la raíz con las variables necesarias. Ejemplo mínimo:

```
# Entorno
PORT=8000

# Seguridad / Aplicación
FIREBASE_SERVICE_ACCOUNT_PATH="./secrets/firebase-service-account.json"

# Base de datos
MONGO_URI="cadena de coneccion a mongoDB"

```

Sugerencias
- Usa gestores de secretos (Vault, AWS Secrets Manager, GitHub Secrets) en producción en lugar de `.env`.
- Genera SECRET_KEY con un generador seguro y cambia valores por defecto antes de desplegar.
- Documenta cualquier variable adicional específica de tus módulos (por ejemplo, rutas de herramientas, claves de terceros) en este archivo README.

Si necesitas un ejemplo adaptado al framework/migraciones que usas (Alembic, Django, Tortoise, etc.), indícame cuál para incluir comandos específicos.