import asyncio
import copy

import httpx

from .config import Settings
from .errors import ServiceError
from .prompts import SYSTEM_PROMPT
from .schemas import ModelAnalysis

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
VERIFIED_MODELS = {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}


def output_schema():
    """Keep provider schema structural; enforce text/list bounds locally as well."""
    schema = copy.deepcopy(ModelAnalysis.model_json_schema())

    def simplify(node):
        if isinstance(node, dict):
            for key in ("minLength", "maxLength", "minItems", "maxItems"):
                node.pop(key, None)
            for value in node.values():
                simplify(value)
        elif isinstance(node, list):
            for value in node:
                simplify(value)

    simplify(schema)
    return schema


class GroqClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    async def generate(self, context: str) -> str:
        key = self.settings.groq_api_key.get_secret_value().strip()
        if not key or self.settings.groq_model not in VERIFIED_MODELS:
            raise ServiceError(503, "provider_configuration", "Revisa la clave y el modelo configurados localmente.")
        payload = {
            "model": self.settings.groq_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
            "max_completion_tokens": self.settings.groq_max_completion_tokens,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "radar_analysis", "strict": True, "schema": output_schema(),
            }},
        }
        try:
            # Total deadline includes both attempts and backoff, not just socket reads.
            async with asyncio.timeout(self.settings.groq_timeout_seconds):
                return await self._request(payload, key)
        except (TimeoutError, httpx.TimeoutException):
            raise ServiceError(504, "provider_timeout", "Groq no respondió dentro del tiempo permitido.") from None
        except httpx.RequestError:
            raise ServiceError(503, "provider_unavailable", "No fue posible conectar con Groq.") from None

    async def _request(self, payload: dict, key: str) -> str:
        for attempt in range(2):
            try:
                response = await self.client.post(
                    GROQ_URL, json=payload, headers={"Authorization": f"Bearer {key}"},
                    timeout=self.settings.groq_timeout_seconds,
                )
            except httpx.TimeoutException:
                raise
            except httpx.RequestError:
                if attempt == 0:
                    await asyncio.sleep(0.25)
                    continue
                raise
            if response.status_code in {500, 502, 503, 504} and attempt == 0:
                await asyncio.sleep(0.25)
                continue
            if response.status_code == 429:
                # Return promptly; no immediate retries that spend more quota.
                raise ServiceError(503, "provider_rate_limited", "Groq alcanzó un límite de uso; intenta más tarde.")
            if response.status_code in {401, 403}:
                raise ServiceError(503, "provider_authentication", "Revisa las credenciales y permisos locales de Groq.")
            if response.status_code >= 500:
                raise ServiceError(503, "provider_unavailable", "Groq no está disponible temporalmente.")
            if not response.is_success:
                raise ServiceError(502, "provider_rejected_request", "Groq rechazó la solicitud; revisa modelo y presupuesto de contexto.")
            try:
                choice = response.json()["choices"][0]
                content = choice["message"]["content"]
                if choice["finish_reason"] != "stop" or not isinstance(content, str) or not content.strip():
                    raise ValueError()
                return content
            except (ValueError, KeyError, IndexError, TypeError):
                raise ServiceError(502, "invalid_provider_response", "Groq devolvió una respuesta incompleta o mal formada.") from None
        raise AssertionError("unreachable")
