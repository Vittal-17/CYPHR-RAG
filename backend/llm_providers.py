import config
import os
import logging
from pydantic import BaseModel
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

class ModelDefinition(BaseModel):
    id: str
    name: str

class ProviderDefinition(BaseModel):
    id: str
    name: str
    enabled: bool
    api_key_env: str
    base_url: str
    models: list[ModelDefinition]
    default_model: str | None = None

# Note: We read enabled status from env.
PROVIDER_REGISTRY = {
        "gemini": ProviderDefinition(
        id="gemini",
        name="Gemini",
        enabled=os.getenv("LLM_GEMINI_ENABLED", "false").lower() == "true",
        api_key_env="GEMINI_API_KEY",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-1.5-flash",
        models=[
            ModelDefinition(id="gemini-1.5-flash", name="Gemini 1.5 Flash"),
            ModelDefinition(id="gemini-1.5-pro", name="Gemini 1.5 Pro"),
        ]
    ),
    "groq": ProviderDefinition(
        id="groq",
        name="Groq",
        enabled=os.getenv("LLM_GROQ_ENABLED", "false").lower() == "true",
        api_key_env="GROQ_API_KEY",
        base_url="https://api.groq.com/openai/v1",
        default_model="openai/gpt-oss-120b",
        models=[
            ModelDefinition(id="openai/gpt-oss-120b", name="GPT-OSS 120B"),
            ModelDefinition(id="openai/gpt-oss-20b", name="GPT-OSS 20B"),
        ]
    ),
    "tokenforge": ProviderDefinition(
        id="tokenforge",
        name="TokenForge",
        enabled=os.getenv("LLM_TOKENFORGE_ENABLED", "false").lower() == "true",
        api_key_env="TOKENFORGE_API_KEY",
        base_url="https://tokenforge.ai.studio/v1",
        default_model="claude-opus-5",
        models=[
            ModelDefinition(id="claude-opus-5", name="Claude Opus 5"),
        ]
    ),
    "conduit": ProviderDefinition(
        id="conduit",
        name="Conduit",
        enabled=os.getenv("LLM_CONDUIT_ENABLED", "false").lower() == "true",
        api_key_env="CONDUIT_API_KEY",
        base_url="https://conduit.ozdoev.net/v1",
        default_model="claude-haiku-4-5",
        models=[
            ModelDefinition(id="claude-haiku-4-5", name="Claude Haiku 4.5"),
        ]
    ),
    "justworker": ProviderDefinition(
        id="justworker",
        name="JustWorker",
        enabled=os.getenv("LLM_JUSTWORKER_ENABLED", "false").lower() == "true",
        api_key_env="JUSTWORKER_API_KEY",
        base_url="https://api.justwoker.icu/v1",
        default_model="claude-opus-5",
        models=[
            ModelDefinition(id="claude-opus-5", name="Claude Opus 5"),
        ]
    ),
    "tabitoken": ProviderDefinition(
        id="tabitoken",
        name="TabiToken",
        enabled=os.getenv("LLM_TABITOKEN_ENABLED", "false").lower() == "true",
        api_key_env="TABITOKEN_API_KEY",
        base_url="https://tabitoken.com/v1",
        default_model="claude-opus-5",
        models=[
            ModelDefinition(id="claude-opus-5", name="Claude Opus 5"),
            ModelDefinition(id="claude-opus-5-thinking", name="Claude Opus 5(THINKING)"),
        ]
    )
}

LLM_DEFAULT_PROVIDER = os.getenv("LLM_DEFAULT_PROVIDER", "groq")
LLM_DEFAULT_MODEL = os.getenv("LLM_DEFAULT_MODEL", "openai/gpt-oss-20b")

TITLE_PROVIDER = "groq"
TITLE_MODEL = "openai/gpt-oss-20b"


# Fail startup safely if defaults are totally invalid
if LLM_DEFAULT_PROVIDER not in PROVIDER_REGISTRY:
    raise ValueError(f"FATAL: Default LLM provider '{LLM_DEFAULT_PROVIDER}' is not registered.")
_default_provider_def = PROVIDER_REGISTRY[LLM_DEFAULT_PROVIDER]
if not any(m.id == LLM_DEFAULT_MODEL for m in _default_provider_def.models):
    raise ValueError(f"FATAL: Default LLM model '{LLM_DEFAULT_MODEL}' is not supported by default provider '{LLM_DEFAULT_PROVIDER}'.")

# Only validate missing API keys on FIRST client initialization or eagerly here.
# Existing CYPHR code initializes clients at startup. So let's validate here.
for p_id, p_def in PROVIDER_REGISTRY.items():
    if p_def.enabled:
        api_key = os.getenv(p_def.api_key_env)
        if not api_key:
            raise ValueError(f"FATAL: Provider '{p_id}' is enabled but {p_def.api_key_env} is not set!")

_client_cache = {}

def get_provider_client(provider_id: str | None = None, model_id: str | None = None) -> tuple[AsyncOpenAI, str, str]:
    """Resolves and returns the (client, provider_id, model_id) for a request."""
    if not provider_id and not model_id:
        provider_id = LLM_DEFAULT_PROVIDER
        model_id = LLM_DEFAULT_MODEL
    elif not provider_id and model_id:
        raise ValueError("Model supplied without a provider. Incomplete provider/model pair.")
    elif provider_id and not model_id:
        p_def = PROVIDER_REGISTRY.get(provider_id)
        if not p_def:
            raise ValueError(f"Provider '{provider_id}' is not supported.")
        if not p_def.default_model:
            raise ValueError(f"Provider '{provider_id}' has no default model.")
        model_id = p_def.default_model

    provider_def = PROVIDER_REGISTRY.get(provider_id)
    if not provider_def:
        raise ValueError(f"Provider '{provider_id}' is not supported.")
    if not provider_def.enabled:
        raise ValueError(f"Provider '{provider_id}' is currently disabled.")
    if not any(m.id == model_id for m in provider_def.models):
        raise ValueError(f"Model '{model_id}' is not supported by provider '{provider_id}'.")
    if provider_id in _client_cache:
        return _client_cache[provider_id], provider_id, model_id
    api_key = os.getenv(provider_def.api_key_env)
    if not api_key:
        raise ValueError(f"Provider '{provider_id}' is enabled but API key is missing.")
    client = AsyncOpenAI(api_key=api_key, base_url=provider_def.base_url)
    _client_cache[provider_id] = client
    return client, provider_id, model_id

def get_public_provider_catalog() -> dict:
    providers = []
    for p_id, p_def in PROVIDER_REGISTRY.items():
        if p_def.enabled:
            providers.append({
                "id": p_def.id,
                "name": p_def.name,
                "models": [{"id": m.id, "name": m.name} for m in p_def.models]
            })
    return {
        "providers": providers,
        "default_provider": LLM_DEFAULT_PROVIDER,
        "default_model": LLM_DEFAULT_MODEL
    }

def get_default_provider_and_model():
    return LLM_DEFAULT_PROVIDER, LLM_DEFAULT_MODEL
