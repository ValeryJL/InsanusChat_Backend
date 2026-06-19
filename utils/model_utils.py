"""
Descubrimiento dinámico en tiempo real de modelos de IA activos (HU-09).
Consulta:
1. Las APIs oficiales de cada proveedor cuando el usuario tiene una API Key configurada:
   - Google Gemini API (`https://generativelanguage.googleapis.com/v1beta/models`)
   - OpenAI API (`https://api.openai.com/v1/models`)
   - Anthropic Models API (`https://api.anthropic.com/v1/models`)
   - Ollama Local Daemon (`http://host.docker.internal:11434/api/tags` / `localhost:11434`)
2. El repositorio público en vivo de modelos (`https://openrouter.ai/api/v1/models`),
   que mantiene actualizado en tiempo real el catálogo global de Google, OpenAI, Anthropic,
   Meta Llama, Qwen, Mistral, DeepSeek, etc., sin requerir API Key previa.
3. Fallback local únicamente si el servidor se encuentra completamente sin acceso a red.
"""
from datetime import datetime, timedelta
import logging
import os
from typing import Any, Dict, List, Optional, Tuple
import httpx

logger = logging.getLogger(__name__)

OPENROUTER_PUBLIC_MODELS_URL = "https://openrouter.ai/api/v1/models"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"

# Caché en memoria con TTL de 5 minutos para el repositorio público
_PUBLIC_REPO_CACHE: Dict[str, Any] = {
    "fetched_at": None,
    "raw_models": [],
}
CACHE_TTL_SECONDS = 300

FALLBACK_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "gemini": [
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "description": "Rápido, multimodal y eficiente"},
        {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "description": "Razonamiento complejo y programación"},
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "description": "Baja latencia"},
    ],
    "openai": [
        {"id": "gpt-4o", "name": "GPT-4o", "description": "Modelo multimodal de OpenAI"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "description": "Rápido y económico"},
        {"id": "o3-mini", "name": "o3-mini", "description": "Razonamiento STEM y código"},
    ],
    "anthropic": [
        {"id": "claude-3-7-sonnet-latest", "name": "Claude 3.7 Sonnet", "description": "Razonamiento híbrido y agentes"},
        {"id": "claude-3-5-haiku-latest", "name": "Claude 3.5 Haiku", "description": "Ultra rápido"},
    ],
    "ollama": [
        {"id": "llama3.2", "name": "Llama 3.2 (Local Ollama)", "description": "Modelo local vía Ollama"},
        {"id": "qwen2.5-coder", "name": "Qwen 2.5 Coder (Local Ollama)", "description": "Optimizado para código en local"},
        {"id": "mistral", "name": "Mistral 7B (Local Ollama)", "description": "Ligero y veloz en local"},
    ],
    "openrouter": [
        {"id": "google/gemini-2.5-flash", "name": "Google: Gemini 2.5 Flash", "description": "Vía OpenRouter"},
        {"id": "anthropic/claude-3.7-sonnet", "name": "Anthropic: Claude 3.7 Sonnet", "description": "Vía OpenRouter"},
        {"id": "deepseek/deepseek-chat", "name": "DeepSeek V3", "description": "Vía OpenRouter"},
    ],
}

FALLBACK_MODELS: List[Tuple[str, str]] = [
    ("gemini-2.5-flash", "Gemini 2.5 Flash"),
    ("gemini-2.5-pro", "Gemini 2.5 Pro"),
    ("gemini-2.0-flash", "Gemini 2.0 Flash"),
]


def normalize_provider(provider: Optional[str]) -> str:
    if not provider:
        return "gemini"
    p = provider.strip().lower()
    if p in ("google", "gemini", "google-genai"):
        return "gemini"
    if p in ("openai", "gpt"):
        return "openai"
    if p in ("anthropic", "claude"):
        return "anthropic"
    if p in ("ollama", "local"):
        return "ollama"
    if p in ("openrouter",):
        return "openrouter"
    return p


def infer_provider_from_model(model_name: Optional[str]) -> str:
    if not model_name:
        return "gemini"
    m = model_name.lower()
    if "/" in m:
        return "openrouter"
    if m.startswith("gpt-") or m.startswith("o1") or m.startswith("o3") or m.startswith("o4") or m.startswith("chatgpt-"):
        return "openai"
    if m.startswith("claude-"):
        return "anthropic"
    if m.startswith("llama") or m.startswith("qwen") or m.startswith("mistral") or m.startswith("deepseek"):
        return "ollama"
    return "gemini"


async def _fetch_public_openrouter_repo(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    Consulta el repositorio público en vivo de OpenRouter (https://openrouter.ai/api/v1/models),
    que lista todos los modelos activos del mercado sin requerir API Key.
    """
    now = datetime.utcnow()
    cached_at = _PUBLIC_REPO_CACHE.get("fetched_at")
    if (
        not force_refresh
        and cached_at
        and isinstance(cached_at, datetime)
        and (now - cached_at) < timedelta(seconds=CACHE_TTL_SECONDS)
        and _PUBLIC_REPO_CACHE.get("raw_models")
    ):
        return _PUBLIC_REPO_CACHE["raw_models"]

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(OPENROUTER_PUBLIC_MODELS_URL)
            resp.raise_for_status()
            data = resp.json().get("data") or []
            if isinstance(data, list) and len(data) > 0:
                _PUBLIC_REPO_CACHE["fetched_at"] = now
                _PUBLIC_REPO_CACHE["raw_models"] = data
                logger.info("Catálogo público en vivo actualizado: %d modelos disponibles", len(data))
                return data
    except Exception as e:
        logger.warning("No se pudo consultar el repositorio público de modelos (%s): %s", OPENROUTER_PUBLIC_MODELS_URL, e)

    return _PUBLIC_REPO_CACHE.get("raw_models") or []


NON_CHAT_KEYWORDS = (
    "-tts",
    "_tts",
    "tts-",
    "tts",
    "-image",
    "image-",
    "imagen",
    "transcribe",
    "nano-banana",
    "lyria",
    "omni",
    "veo",
    "embedding",
    "aqa",
    "bisect",
    "audio",
    "whisper",
    "moderation",
    "realtime",
    "robotics",
    "image-generation",
    "computer-use",
    "antigravity-preview",
    "deep-research",
)


def _is_valid_chat_model(model_id: str) -> bool:
    low = model_id.lower()
    if any(k in low for k in NON_CHAT_KEYWORDS):
        return False
    return True


async def _fetch_google_gemini_official(api_key: str) -> List[Dict[str, Any]]:
    """Consulta directamente la API oficial de Google Gemini con la API Key del usuario (filtrando modelos TTS/Audio/Imagen)."""
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(GEMINI_MODELS_URL, params={"key": api_key, "pageSize": 100})
            resp.raise_for_status()
            models_raw = resp.json().get("models") or []
            out: List[Dict[str, Any]] = []
            for m in models_raw:
                methods = m.get("supportedGenerationMethods") or []
                if "generateContent" not in methods:
                    continue
                m_id = (m.get("name") or "").replace("models/", "")
                if not m_id.startswith("gemini") or m_id == "gemini-pro" or "1.0" in m_id:
                    continue
                if not _is_valid_chat_model(m_id):
                    continue
                out.append(
                    {
                        "id": m_id,
                        "name": m.get("displayName") or m_id,
                        "description": (m.get("description") or "Modelo oficial Google Gemini")[:140],
                        "context_length": m.get("inputTokenLimit"),
                        "source": "google_api",
                    }
                )
            # Ordenar priorizando modelos principales estables (flash / pro) sobre experimentales/lite
            out.sort(
                key=lambda x: (
                    "2.5-flash" not in x["id"] and "2.0-flash" not in x["id"],
                    "2.5-pro" not in x["id"],
                    "lite" in x["id"],
                    "exp" in x["id"] or "preview" in x["id"],
                    x["id"],
                )
            )
            return out
    except Exception as e:
        logger.debug("Fallo al consultar Google Gemini API oficial: %s", e)
        return []


async def _fetch_openai_official(api_key: str, base_url: Optional[str] = None) -> List[Dict[str, Any]]:
    """Consulta directamente el endpoint /v1/models de OpenAI (o compatible) con la API Key del usuario."""
    if not api_key:
        return []
    url = f"{base_url.rstrip('/')}/models" if base_url else OPENAI_MODELS_URL
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
            resp.raise_for_status()
            items = resp.json().get("data") or []
            out: List[Dict[str, Any]] = []
            for m in items:
                m_id = m.get("id") or ""
                if not m_id:
                    continue
                # Filtrar modelos de embeddings/audio/tts/moderation si es OpenAI oficial
                if not base_url and not any(
                    m_id.startswith(p) for p in ("gpt-", "o1", "o3", "o4", "chatgpt-")
                ):
                    continue
                if any(skip in m_id for skip in ("realtime", "audio", "tts", "whisper", "embedding", "moderation", "instruct")):
                    continue
                out.append(
                    {
                        "id": m_id,
                        "name": m_id,
                        "description": f"Modelo oficial OpenAI ({m.get('owned_by', 'openai')})",
                        "source": "openai_api",
                    }
                )
            out.sort(key=lambda x: x["id"], reverse=True)
            return out
    except Exception as e:
        logger.debug("Fallo al consultar OpenAI /v1/models: %s", e)
        return []


async def _fetch_anthropic_official(api_key: str) -> List[Dict[str, Any]]:
    """Consulta directamente el endpoint oficial GET https://api.anthropic.com/v1/models."""
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                ANTHROPIC_MODELS_URL,
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            )
            resp.raise_for_status()
            items = resp.json().get("data") or []
            out: List[Dict[str, Any]] = []
            for m in items:
                m_id = m.get("id") or ""
                if not m_id:
                    continue
                out.append(
                    {
                        "id": m_id,
                        "name": m.get("display_name") or m_id,
                        "description": "Modelo oficial Anthropic Claude",
                        "source": "anthropic_api",
                    }
                )
            return out
    except Exception as e:
        logger.debug("Fallo al consultar Anthropic /v1/models: %s", e)
        return []


async def _fetch_ollama_local(base_url: Optional[str] = None) -> List[Dict[str, Any]]:
    """Intenta descubrir modelos instalados en un servidor Ollama local o de red."""
    candidates = []
    if base_url:
        clean_base = base_url.rstrip("/").replace("/v1", "")
        candidates.append(f"{clean_base}/api/tags")
    candidates.extend(
        [
            "http://host.docker.internal:11434/api/tags",
            "http://localhost:11434/api/tags",
        ]
    )

    async with httpx.AsyncClient(timeout=2.0) as client:
        for url in candidates:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    models = resp.json().get("models") or []
                    if models:
                        return [
                            {
                                "id": m.get("name"),
                                "name": f"{m.get('name')} (Instalado en Ollama)",
                                "description": f"Tamaño: {round((m.get('size') or 0) / (1024**3), 1)} GB",
                                "source": "ollama_local_api",
                            }
                            for m in models
                            if m.get("name")
                        ]
            except Exception:
                continue
    return []


def _extract_provider_models_from_public_repo(raw_models: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Extrae y organiza los modelos activos por proveedor desde el repositorio público en vivo.
    Filtra variantes ':batch' o ':free' duplicadas para presentar una lista limpia y ordenada.
    """
    by_prov: Dict[str, List[Dict[str, Any]]] = {
        "gemini": [],
        "openai": [],
        "anthropic": [],
        "ollama": [],
        "openrouter": [],
    }
    seen: Dict[str, set] = {k: set() for k in by_prov}

    for item in raw_models:
        full_id = item.get("id") or ""
        if not full_id or ":batch" in full_id or not _is_valid_chat_model(full_id):
            continue

        name = item.get("name") or full_id
        ctx = item.get("context_length")
        ctx_label = f" · {int(ctx) // 1000}k ctx" if isinstance(ctx, int) and ctx >= 1000 else ""
        desc_raw = (item.get("description") or "").split("\n")[0][:120]
        desc = f"{desc_raw}{ctx_label}".strip(" ·")

        # 1. Todos están disponibles bajo OpenRouter con su ID completo (ej: google/gemini-4-neon)
        if full_id not in seen["openrouter"]:
            seen["openrouter"].add(full_id)
            by_prov["openrouter"].append(
                {
                    "id": full_id,
                    "name": name,
                    "description": desc or f"Modelo activo en OpenRouter{ctx_label}",
                    "context_length": ctx,
                    "source": "public_repo",
                }
            )

        # 2. Google Gemini (prefijo google/)
        if full_id.startswith("google/"):
            short_id = full_id.split("google/", 1)[1].split(":")[0]
            if short_id.startswith("gemini") and short_id not in seen["gemini"]:
                seen["gemini"].add(short_id)
                by_prov["gemini"].append(
                    {
                        "id": short_id,
                        "name": name.replace("Google: ", ""),
                        "description": desc or f"Google Gemini ({short_id}){ctx_label}",
                        "context_length": ctx,
                        "source": "public_repo",
                    }
                )

        # 3. OpenAI (prefijo openai/)
        elif full_id.startswith("openai/"):
            short_id = full_id.split("openai/", 1)[1].split(":")[0]
            if short_id not in seen["openai"]:
                seen["openai"].add(short_id)
                by_prov["openai"].append(
                    {
                        "id": short_id,
                        "name": name.replace("OpenAI: ", ""),
                        "description": desc or f"OpenAI ({short_id}){ctx_label}",
                        "context_length": ctx,
                        "source": "public_repo",
                    }
                )

        # 4. Anthropic Claude (prefijo anthropic/)
        elif full_id.startswith("anthropic/"):
            short_id = full_id.split("anthropic/", 1)[1].split(":")[0]
            if short_id not in seen["anthropic"]:
                seen["anthropic"].add(short_id)
                by_prov["anthropic"].append(
                    {
                        "id": short_id,
                        "name": name.replace("Anthropic: ", ""),
                        "description": desc or f"Anthropic Claude ({short_id}){ctx_label}",
                        "context_length": ctx,
                        "source": "public_repo",
                    }
                )

        # 5. Modelos Open-Weights populares ejecutables en Ollama (Meta Llama, Qwen, Mistral, DeepSeek, Gemma)
        if any(full_id.startswith(p) for p in ("meta-llama/", "qwen/", "mistralai/", "deepseek/")):
            short_id = full_id.split("/", 1)[1].split(":")[0]
            if short_id not in seen["ollama"] and len(by_prov["ollama"]) < 35:
                seen["ollama"].add(short_id)
                by_prov["ollama"].append(
                    {
                        "id": short_id,
                        "name": f"{name} ({short_id})",
                        "description": f"Open-Weights / Ollama{ctx_label}",
                        "context_length": ctx,
                        "source": "public_repo",
                    }
                )

    return by_prov


async def fetch_live_models_catalog(
    provider: Optional[str] = None,
    api_keys_by_provider: Optional[Dict[str, Tuple[str, Optional[str]]]] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Construye el catálogo de modelos activos combinando:
    1. Consultas en vivo a la API oficial del proveedor (si hay API Key del usuario o de entorno).
    2. Consultas en vivo al repositorio público de modelos (OpenRouter API) para todos los proveedores.
    3. Fallback local si no hubiera conectividad.
    """
    keys_map = api_keys_by_provider or {}

    # 1. Consultar repositorio público en vivo
    public_raw = await _fetch_public_openrouter_repo(force_refresh=force_refresh)
    repo_catalog = _extract_provider_models_from_public_repo(public_raw) if public_raw else {}

    final_providers: Dict[str, List[Dict[str, Any]]] = {}
    sources_info: Dict[str, str] = {}

    target_providers = [normalize_provider(provider)] if provider else ["gemini", "openai", "anthropic", "ollama", "openrouter"]

    for prov in target_providers:
        key_tuple = keys_map.get(prov)
        api_key = key_tuple[0] if key_tuple else None
        base_url = key_tuple[1] if key_tuple else None

        # Fallback a variables de entorno si el usuario no cargó key para ese proveedor
        if not api_key:
            if prov == "gemini":
                api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
            elif prov == "openai":
                api_key = os.environ.get("OPENAI_API_KEY")
            elif prov == "anthropic":
                api_key = os.environ.get("ANTHROPIC_API_KEY")

        official_models: List[Dict[str, Any]] = []
        if prov == "gemini" and api_key:
            official_models = await _fetch_google_gemini_official(api_key)
        elif prov == "openai" and api_key:
            official_models = await _fetch_openai_official(api_key, base_url=base_url)
        elif prov == "anthropic" and api_key:
            official_models = await _fetch_anthropic_official(api_key)
        elif prov == "ollama":
            official_models = await _fetch_ollama_local(base_url=base_url)

        repo_models = repo_catalog.get(prov) or []

        if official_models:
            # Si la API oficial del proveedor respondió con la API Key del usuario,
            # mostrar exactamente los modelos activos y válidos en su cuenta/API.
            final_providers[prov] = official_models
            sources_info[prov] = f"API Oficial de {prov.capitalize()} ({len(official_models)} modelos activos en tu API Key)"
        elif repo_models:
            final_providers[prov] = repo_models
            sources_info[prov] = f"Repositorio Público en Vivo ({len(repo_models)} modelos disponibles)"
        else:
            fallback = FALLBACK_CATALOG.get(prov, [])
            final_providers[prov] = fallback
            sources_info[prov] = "Catálogo Local (Fallback sin red)"

    total_count = sum(len(v) for v in final_providers.values())
    return {
        "providers": final_providers,
        "sources": sources_info,
        "total_models": total_count,
        "fetched_at": (_PUBLIC_REPO_CACHE.get("fetched_at") or datetime.utcnow()).isoformat(),
    }


def get_models_catalog(provider: Optional[str] = None, api_key: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Versión sincrónica que usa el caché del repositorio público o el fallback."""
    public_raw = _PUBLIC_REPO_CACHE.get("raw_models") or []
    if public_raw:
        extracted = _extract_provider_models_from_public_repo(public_raw)
        if provider:
            norm = normalize_provider(provider)
            return {norm: extracted.get(norm) or FALLBACK_CATALOG.get(norm, [])}
        return extracted
    if provider:
        norm = normalize_provider(provider)
        return {norm: FALLBACK_CATALOG.get(norm, [])}
    return FALLBACK_CATALOG
