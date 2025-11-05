# InsanusChat_Backend
Backend FastAPI de mi proyecto de chat para crear agentes ia, con acceso a herramientas, mcp servers, y un chat bifurcado visual
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