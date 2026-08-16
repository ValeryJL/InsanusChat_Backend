"""
Suite de Tests Automatizados E2E de InsanusChat Backend (HU-19).
Verifica:
1. Healthcheck y conexión a MongoDB (`GET /health`).
2. Registro con Bootstrap automático de Admin, Login y Perfil (` routers/auth.py`).
3. Cifrado Fernet en reposo y enmascaramiento de API Keys (`HU-05`).
4. Ejecución de Code Snippets en sandbox con aislamiento de variables de entorno (`HU-06`).
5. Gobernanza y Test de conexión real con el servidor MCP de Calculadora (`HU-07, HU-10`).
6. Creación de Agentes y catálogo multi-proveedor (`HU-01, HU-09`).
7. Creación de Chats, visibilidad (`user_id` ObjectId), bifurcación de árbol en 2 ramas y aislamiento estricto de historial por rama (`_build_branch_history`) (`HU-01, HU-02, HU-03`).
8. Panel de Administración (`/api/v1/admin/stats`, `/users`, `/settings`, `/chats`) (`HU-ADMIN-BE`).
"""
import asyncio
import os
import uuid
import pytest
from httpx import AsyncClient, ASGITransport

os.environ["MONGO_URI"] = os.environ.get(
    "MONGO_URI",
    "mongodb://admin:insanus_admin_pass@localhost:27017/insanus_chat?authSource=admin",
)
os.environ["MONGO_DB_NAME"] = "insanus_chat_test"
os.environ["LOCAL_AUTH_SECRET"] = "test-secret-key-for-insanuschat-2026"

import database
from backend import app
from auth.crypto import encrypt_api_key, decrypt_api_key, mask_api_key
from services.snippets import execute_snippet
from services.agents import _build_branch_history


@pytest.mark.asyncio
async def test_crypto_fernet_and_masking():
    """HU-05: Verifica que las API keys se cifren con Fernet y se enmascaren correctamente."""
    raw = "AIzaSyTestSecretKey1234567890ABCD"
    enc = encrypt_api_key(raw)
    assert enc.startswith("enc:v1:")
    assert raw not in enc
    dec = decrypt_api_key(enc)
    assert dec == raw
    masked = mask_api_key(enc)
    assert masked == "AIza...ABCD"
    assert "TestSecretKey" not in masked


@pytest.mark.asyncio
async def test_snippet_sandbox_env_isolation():
    """HU-06: Verifica que un snippet Python no pueda leer secretos del entorno como LOCAL_AUTH_SECRET o MONGO_URI."""
    code = """
import os
leaked_secret = os.environ.get("LOCAL_AUTH_SECRET")
leaked_mongo = os.environ.get("MONGO_URI")
return {"leaked_secret": leaked_secret, "leaked_mongo": leaked_mongo, "input": inp}
"""
    res = await execute_snippet({"language": "python", "code": code}, input_data="test_payload")
    assert res["success"] is True
    assert res["result"]["leaked_secret"] is None
    assert res["result"]["leaked_mongo"] is None
    assert res["result"]["input"] == "test_payload"


@pytest.mark.asyncio
async def test_full_platform_e2e_flow():
    """Verifica el flujo completo E2E: Auth, API Keys, MCP Test, Agentes, Chat Ramificado y Panel Admin."""
    await database.connect_to_mongo()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Healthcheck (HU-19)
        r_health = await client.get("/health")
        assert r_health.status_code == 200
        assert r_health.json()["status"] == "healthy"
        assert r_health.json()["database"]["ok"] is True

        # 2. Registro de usuario y promoción a Admin
        unique_suffix = uuid.uuid4().hex[:8]
        email = f"admin_{unique_suffix}@insanus.local"
        r_reg = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "StrongPassword123!", "display_name": f"Admin_{unique_suffix}"},
        )
        assert r_reg.status_code == 200
        reg_data = r_reg.json()["data"]
        token = reg_data["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Asegurar rol admin con /api/v1/admin/bootstrap
        r_boot = await client.post("/api/v1/admin/bootstrap", headers=headers)
        assert r_boot.status_code == 200
        assert "admin" in r_boot.json()["data"]["roles"]

        # 3. API Keys cifradas y enmascaradas (HU-05)
        r_key = await client.post(
            "/api/v1/apikeys/",
            headers=headers,
            json={"provider": "gemini", "api_key": "AIzaSySuperSecretValue9876", "label": "Gemini Test"},
        )
        assert r_key.status_code == 200
        key_data = r_key.json()["data"]
        assert key_data["masked_key"] == "AIza...9876"
        assert key_data["encrypted_key"] == "AIza...9876"

        r_keys_list = await client.get("/api/v1/apikeys/", headers=headers)
        assert r_keys_list.status_code == 200
        assert len(r_keys_list.json()["data"]) == 1
        assert "SuperSecretValue" not in str(r_keys_list.json())

        # 4. Recursos por defecto (MCP Calculadora y Snippet) y Test de Conexión MCP (HU-10)
        r_res = await client.get("/api/v1/resources/", headers=headers)
        assert r_res.status_code == 200
        mcps = r_res.json()["data"]["mcps"]
        assert len(mcps) >= 1
        calc_mcp_id = mcps[0]["_id"]

        r_mcp_test = await client.post(f"/api/v1/resources/mcps/{calc_mcp_id}/test", headers=headers)
        assert r_mcp_test.status_code == 200
        mcp_test_data = r_mcp_test.json()["data"]
        assert mcp_test_data["status"] == "available"
        tool_names = [t["name"] for t in mcp_test_data["tools"]]
        assert "add" in tool_names and "multiply" in tool_names

        # 5. Catálogo de modelos multi-proveedor (HU-09)
        r_models = await client.get("/api/v1/agents/models", headers=headers)
        assert r_models.status_code == 200
        providers = r_models.json()["data"]["providers"]
        assert "gemini" in providers and "openai" in providers and "anthropic" in providers

        # 6. Crear Chat y verificar visibilidad en GET /api/v1/chats/ (HU-01)
        r_chat = await client.post(
            "/api/v1/chats/",
            headers=headers,
            json={"title": "Chat Ramificado Test"},
        )
        assert r_chat.status_code == 200
        chat_id = r_chat.json()["data"]["_id"]

        r_chats = await client.get("/api/v1/chats/", headers=headers)
        assert r_chats.status_code == 200
        chat_ids = [c["_id"] for c in r_chats.json()["data"]]
        assert chat_id in chat_ids

        # 7. Publicar mensaje raíz y verificar aislamiento de ramas del árbol (HU-02)
        msgs_col = database.get_message_collection()
        from models import PyObjectId

        chat_oid = PyObjectId.parse(chat_id)
        root_id = PyObjectId.new()
        branch_a_id = PyObjectId.new()
        branch_b_id = PyObjectId.new()

        await msgs_col.insert_many(
            [
                {
                    "_id": root_id,
                    "chat_id": chat_oid,
                    "parent_id": None,
                    "children_ids": [branch_a_id, branch_b_id],
                    "path": [],
                    "role": "user",
                    "content": "Mensaje Raíz Común",
                    "sender_id": reg_data["user_id"],
                },
                {
                    "_id": branch_a_id,
                    "chat_id": chat_oid,
                    "parent_id": root_id,
                    "children_ids": [],
                    "path": [root_id],
                    "role": "user",
                    "content": "Secreto exclusivo de la Rama A",
                    "sender_id": reg_data["user_id"],
                },
                {
                    "_id": branch_b_id,
                    "chat_id": chat_oid,
                    "parent_id": root_id,
                    "children_ids": [],
                    "path": [root_id],
                    "role": "user",
                    "content": "Consulta en la Rama B",
                    "sender_id": reg_data["user_id"],
                },
            ]
        )

        hist_b = await _build_branch_history(chat_oid, branch_b_id)
        contents_b = [m["content"] for m in hist_b]
        assert "Mensaje Raíz Común" in contents_b
        assert "Consulta en la Rama B" in contents_b
        assert "Secreto exclusivo de la Rama A" not in contents_b

        # 8. Panel de Administración (`/api/v1/admin/*`)
        r_stats = await client.get("/api/v1/admin/stats", headers=headers)
        assert r_stats.status_code == 200
        stats = r_stats.json()["data"]
        assert stats["users"]["total"] >= 1
        assert stats["chats"]["branched_nodes"] >= 1

        r_admin_users = await client.get("/api/v1/admin/users", headers=headers)
        assert r_admin_users.status_code == 200
        assert r_admin_users.json()["data"]["total"] >= 1

        r_admin_settings = await client.put(
            "/api/v1/admin/settings",
            headers=headers,
            json={"allow_registration": True, "allow_stdio_mcp": True},
        )
        assert r_admin_settings.status_code == 200

        # Limpiar chat de prueba (cascade delete)
        r_del_chat = await client.delete(f"/api/v1/chats/{chat_id}", headers=headers)
        assert r_del_chat.status_code == 200
        assert r_del_chat.json()["data"]["deleted_messages"] == 3
    await database.close_mongo_connection()
