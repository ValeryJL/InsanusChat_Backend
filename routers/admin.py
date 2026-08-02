"""
Router de Administración de Plataforma (`/api/v1/admin/*`).
Permite administrar integralmente InsanusChat desde el Panel de Admin Web o vía API:
1. Métricas globales y salud del sistema (`GET /api/v1/admin/stats`)
2. Gestión de usuarios: listar, promover/revocar rol `admin`, suspender/activar cuenta, eliminar usuario y sus datos (`GET / PATCH / DELETE /api/v1/admin/users`)
3. Configuración de políticas globales del servidor: registro público, permiso de MCP `stdio`, endpoints locales, modelo por defecto, rate limit (`GET / PUT /api/v1/admin/settings`)
4. Auditoría y desbloqueo/limpieza de conversaciones (`GET /api/v1/admin/chats`, `POST /api/v1/admin/chats/{chat_id}/unlock`)
5. Bootstrap de Admin en entorno local (`POST /api/v1/admin/bootstrap`)
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Body, Header, HTTPException, Query

import database
from models import PyObjectId, ResponseModel
from routers import auth
from services import messages as messages_service

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["Administración"],
)


@router.post("/bootstrap", response_model=ResponseModel)
async def bootstrap_admin(
    authorization: str | None = Header(None),
):
    """
    Promueve al usuario autenticado al rol 'admin' si aún no existe ningún administrador
    en la base de datos (o en entornos de desarrollo local).
    """
    user_doc = await auth.get_authenticated_user(authorization)
    users_col = database.get_user_collection()

    admin_count = await users_col.count_documents({"roles": "admin"})
    current_roles = list(set((user_doc.get("roles") or ["user"]) + ["admin", "user"]))

    # Si no hay admins o estamos en despliegue local, permitir la promoción para poder probar el Panel Admin
    await users_col.update_one(
        {"_id": user_doc["_id"]},
        {"$set": {"roles": current_roles}},
    )
    return ResponseModel(
        message="Privilegios de Administrador otorgados correctamente",
        data={"user_id": str(user_doc["_id"]), "email": user_doc.get("email"), "roles": current_roles, "previous_admins": admin_count},
    )


@router.get("/stats", response_model=ResponseModel)
async def get_platform_stats(authorization: str | None = Header(None)):
    """Devuelve métricas globales de uso, recursos y salud de la plataforma."""
    await auth.require_admin_user(authorization)

    users_col = database.get_user_collection()
    chats_col = database.get_chat_collection()
    msgs_col = database.get_message_collection()

    total_users = await users_col.count_documents({})
    active_users = await users_col.count_documents({"active": {"$ne": False}})
    admin_users = await users_col.count_documents({"roles": "admin"})

    total_chats = await chats_col.count_documents({})
    locked_chats = await chats_col.count_documents({"locked": True})
    total_messages = await msgs_col.count_documents({})
    # Nodos bifurcados: mensajes que tienen 2 o más hijos
    branched_nodes = await msgs_col.count_documents({"children_ids.1": {"$exists": True}})

    # Agregar totales de agentes, MCPs, snippets y API keys en todos los usuarios
    total_agents = 0
    total_mcps = 0
    total_snippets = 0
    total_api_keys = 0
    async for u in users_col.find({}, {"agents": 1, "mcps": 1, "code_snippets": 1, "api_keys": 1}):
        total_agents += len(u.get("agents") or [])
        total_mcps += len(u.get("mcps") or [])
        total_snippets += len(u.get("code_snippets") or [])
        total_api_keys += len(u.get("api_keys") or [])

    # Sumar tokens consumidos en toda la plataforma
    total_tokens = 0
    pipeline = [{"$group": {"_id": None, "tokens": {"$sum": {"$ifNull": ["$tokens_used", 0]}}}}]
    async for agg in msgs_col.aggregate(pipeline):
        total_tokens = int(agg.get("tokens") or 0)

    db_health = await database.ping_db()
    sys_settings = await database.ensure_system_settings()

    return ResponseModel(
        message="Estadísticas globales recuperadas",
        data={
            "users": {
                "total": total_users,
                "active": active_users,
                "suspended": total_users - active_users,
                "admins": admin_users,
            },
            "chats": {
                "total": total_chats,
                "locked": locked_chats,
                "total_messages": total_messages,
                "branched_nodes": branched_nodes,
                "total_tokens_used": total_tokens,
            },
            "resources": {
                "agents": total_agents,
                "mcps": total_mcps,
                "code_snippets": total_snippets,
                "api_keys": total_api_keys,
            },
            "database": db_health,
            "settings": auth._serialize_doc(sys_settings),
        },
    )


@router.get("/users", response_model=ResponseModel)
async def list_all_users(
    search: Optional[str] = Query(None, description="Filtrar por email o display_name"),
    authorization: str | None = Header(None),
):
    """Lista todos los usuarios registrados con contadores de sus recursos y chats."""
    await auth.require_admin_user(authorization)

    users_col = database.get_user_collection()
    chats_col = database.get_chat_collection()

    query: Dict[str, Any] = {}
    if search and search.strip():
        q = search.strip()
        query = {
            "$or": [
                {"email": {"$regex": q, "$options": "i"}},
                {"display_name": {"$regex": q, "$options": "i"}},
            ]
        }

    users_list = []
    async for u in users_col.find(query).sort("created_at", -1):
        uid = u["_id"]
        chat_count = await chats_col.count_documents({"user_id": {"$in": [uid, str(uid)]}})
        users_list.append(
            {
                "_id": str(uid),
                "email": u.get("email"),
                "display_name": u.get("display_name"),
                "roles": u.get("roles") or ["user"],
                "active": u.get("active", True),
                "created_at": u["created_at"].isoformat() if u.get("created_at") else None,
                "last_login": u["last_login"].isoformat() if u.get("last_login") else None,
                "counts": {
                    "chats": chat_count,
                    "agents": len(u.get("agents") or []),
                    "mcps": len(u.get("mcps") or []),
                    "snippets": len(u.get("code_snippets") or []),
                    "api_keys": len(u.get("api_keys") or []),
                },
            }
        )

    return ResponseModel(message="Usuarios listados", data={"users": users_list, "total": len(users_list)})


@router.patch("/users/{user_id}", response_model=ResponseModel)
async def admin_update_user(
    user_id: str,
    body: Dict[str, Any] = Body(
        ...,
        examples={
            "promote": {
                "summary": "Modificar roles o estado activo de un usuario",
                "value": {"roles": ["admin", "user"], "active": True},
            }
        },
    ),
    authorization: str | None = Header(None),
):
    """Permite a un administrador cambiar roles ('admin'/'user'), suspender/reactivar cuentas o editar nombre."""
    admin_user = await auth.require_admin_user(authorization)

    try:
        target_oid = PyObjectId.parse(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="user_id inválido")

    users_col = database.get_user_collection()
    target = await users_col.find_one({"_id": target_oid})
    if not target:
        raise HTTPException(status_code=404, detail="Usuario objetivo no encontrado")

    update_ops: Dict[str, Any] = {}
    if "roles" in body and isinstance(body["roles"], list):
        clean_roles = [str(r).strip().lower() for r in body["roles"] if str(r).strip()]
        if "user" not in clean_roles:
            clean_roles.append("user")
        update_ops["roles"] = clean_roles
    if "active" in body:
        # Evitar que el admin actual se suspenda a sí mismo por accidente
        if str(target_oid) == str(admin_user["_id"]) and not bool(body["active"]):
            raise HTTPException(status_code=400, detail="No puedes suspender tu propia cuenta de administrador")
        update_ops["active"] = bool(body["active"])
    if "display_name" in body and body["display_name"]:
        update_ops["display_name"] = str(body["display_name"]).strip()

    if not update_ops:
        raise HTTPException(status_code=400, detail="No se especificaron campos válidos para actualizar")

    await users_col.update_one({"_id": target_oid}, {"$set": update_ops})
    updated = await users_col.find_one({"_id": target_oid})

    return ResponseModel(
        message="Usuario actualizado por el administrador",
        data={
            "_id": str(updated["_id"]),
            "email": updated.get("email"),
            "display_name": updated.get("display_name"),
            "roles": updated.get("roles") or ["user"],
            "active": updated.get("active", True),
        },
    )


@router.delete("/users/{user_id}", response_model=ResponseModel)
async def admin_delete_user(
    user_id: str,
    authorization: str | None = Header(None),
):
    """Elimina un usuario y borra en cascada todos sus chats y mensajes."""
    admin_user = await auth.require_admin_user(authorization)

    try:
        target_oid = PyObjectId.parse(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="user_id inválido")

    if str(target_oid) == str(admin_user["_id"]):
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propia cuenta de administrador activa")

    users_col = database.get_user_collection()
    chats_col = database.get_chat_collection()
    msgs_col = database.get_message_collection()

    target = await users_col.find_one({"_id": target_oid})
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    user_chats = [c["_id"] async for c in chats_col.find({"user_id": {"$in": [target_oid, str(target_oid)]}}, {"_id": 1})]
    deleted_msgs = 0
    if user_chats:
        res_m = await msgs_col.delete_many({"chat_id": {"$in": user_chats}})
        deleted_msgs = res_m.deleted_count

    res_c = await chats_col.delete_many({"user_id": {"$in": [target_oid, str(target_oid)]}})
    await users_col.delete_one({"_id": target_oid})

    return ResponseModel(
        message="Usuario y todos sus datos eliminados",
        data={
            "deleted_user_id": str(target_oid),
            "deleted_chats": res_c.deleted_count,
            "deleted_messages": deleted_msgs,
        },
    )


@router.get("/settings", response_model=ResponseModel)
async def get_system_settings(authorization: str | None = Header(None)):
    """Obtiene la configuración global de políticas del servidor."""
    await auth.require_admin_user(authorization)
    settings_doc = await database.ensure_system_settings()
    return ResponseModel(message="Configuración global del sistema", data=auth._serialize_doc(settings_doc))


@router.put("/settings", response_model=ResponseModel)
async def update_system_settings(
    body: Dict[str, Any] = Body(
        ...,
        examples={
            "settings": {
                "value": {
                    "allow_registration": True,
                    "allow_stdio_mcp": True,
                    "allow_local_mcp_endpoints": True,
                    "default_provider": "gemini",
                    "default_model": "gemini-2.5-flash",
                    "rate_limit_login_per_min": 30,
                    "maintenance_mode": False,
                }
            }
        },
    ),
    authorization: str | None = Header(None),
):
    """Actualiza las políticas globales de seguridad y operación de la plataforma."""
    await auth.require_admin_user(authorization)

    allowed = {
        "allow_registration",
        "allow_stdio_mcp",
        "allow_local_mcp_endpoints",
        "allow_code_snippets",
        "default_provider",
        "default_model",
        "rate_limit_login_per_min",
        "maintenance_mode",
    }
    update_ops = {k: v for k, v in body.items() if k in allowed}
    update_ops["updated_at"] = datetime.utcnow()

    settings_col = database.get_settings_collection()
    await settings_col.update_one(
        {"_id": "global_settings"},
        {"$set": update_ops},
        upsert=True,
    )
    updated = await database.ensure_system_settings()
    return ResponseModel(message="Políticas globales actualizadas", data=auth._serialize_doc(updated))


@router.get("/chats", response_model=ResponseModel)
async def admin_list_chats(
    limit: int = Query(50, ge=1, le=200),
    authorization: str | None = Header(None),
):
    """Lista las conversaciones recientes de toda la plataforma para supervisión y soporte."""
    await auth.require_admin_user(authorization)

    chats_col = database.get_chat_collection()
    users_col = database.get_user_collection()
    msgs_col = database.get_message_collection()

    # Cache simple de usuarios
    users_map: Dict[str, str] = {}
    async for u in users_col.find({}, {"email": 1, "display_name": 1}):
        users_map[str(u["_id"])] = f"{u.get('display_name') or ''} ({u.get('email') or ''})".strip()

    items = []
    async for c in chats_col.find({}).sort("last_updated", -1).limit(limit):
        cid = c["_id"]
        uid_str = str(c.get("user_id"))
        msg_count = await msgs_col.count_documents({"chat_id": cid})
        items.append(
            {
                "_id": str(cid),
                "title": c.get("title") or "New Chat",
                "user_id": uid_str,
                "user_label": users_map.get(uid_str, uid_str),
                "message_count": msg_count,
                "locked": messages_service.is_chat_currently_locked(c),
                "created_at": c["created_at"].isoformat() if c.get("created_at") else None,
                "last_updated": c["last_updated"].isoformat() if c.get("last_updated") else None,
            }
        )

    return ResponseModel(message="Chats de plataforma listados", data={"chats": items})
