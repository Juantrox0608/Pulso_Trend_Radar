import asyncio
import json

import httpx

from app.errors import ServiceError
from app.schemas import AnalyzeRequest, AnalyzeResponse
from pydantic import ValidationError


async def request_json(http, url, payload, timeout, service, headers=None, max_bytes=2 * 1024 * 1024):
    try:
        async with asyncio.timeout(timeout):
            async with http.stream("POST", str(url), json=payload, headers=headers, timeout=timeout) as response:
                if not response.is_success:
                    if response.status_code == 429:
                        raise ServiceError(503, f"{service}_rate_limited", f"{service}: límite de uso alcanzado.")
                    if response.status_code in {401, 403}:
                        raise ServiceError(503, f"{service}_authentication", f"Revisa las credenciales de {service}.")
                    if response.status_code in {503, 504}:
                        raise ServiceError(response.status_code, f"{service}_unavailable", f"{service} no está disponible o agotó su plazo.")
                    raise ServiceError(502, f"{service}_error", f"{service} rechazó la solicitud.")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise ServiceError(502, f"{service}_response_too_large", f"Respuesta de {service} demasiado grande.")
                return json.loads(body)
    except (TimeoutError, httpx.TimeoutException):
        raise ServiceError(504, f"{service}_timeout", f"Tiempo de espera agotado: {service}.") from None
    except httpx.RequestError:
        raise ServiceError(503, f"{service}_unavailable", f"No fue posible conectar con {service}.") from None
    except (ValueError, UnicodeError):
        raise ServiceError(502, f"{service}_invalid_json", f"{service} no devolvió JSON válido.") from None


class CollectorClient:
    def __init__(self, settings, http):
        self.settings, self.http = settings, http

    async def collect(self, filters):
        if self.settings.collector_mode == "mock":
            # Synthetic records created per request, filtered by the actual input.
            rows = [{
                "id": f"yt:mock-{index}", "plataforma": "youtube",
                "titulo": f"[FICTICIO] {title}", "texto": "Datos simulados para probar integración de 30X; no son evidencia real.",
                "autor_hash": "mock-hash", "url": f"https://www.youtube.com/watch?v=mock-{index}",
                "publicada_en": "2026-10-10T12:00:00Z", "idioma": "es", "pais": "CO",
            } for index, title in enumerate([
                "IA para automatizar reportes", "IA: evaluar herramientas en equipos", "IA y reuniones de trabajo",
                "IA: riesgos y revisión humana",
            ], 1)]
            stats = {"capturada_en": "2026-10-17T06:00:00Z", "stats": {
                f"yt:mock-{i}": {"viewCount": views, "likeCount": 0 if i == 3 else None, "commentCount": None}
                for i, views in enumerate([12000, 12000, 0, None], 1)
            }}
            return {"metadata": rows, "statistics": stats}
        if self.settings.collector_url is None:
            raise ServiceError(503, "collector_configuration", "Configura COLLECTOR_URL para usar el recolector real.")
        token = self.settings.collector_token.get_secret_value().strip()
        return await request_json(
            self.http, self.settings.collector_url,
            {"filters": filters.model_dump(mode="json", exclude_none=True)},
            self.settings.collector_timeout_seconds, "collector",
            headers={"Authorization": f"Bearer {token}"} if token else None,
        )


class AIClient:
    def __init__(self, settings, http):
        self.settings, self.http = settings, http

    async def analyze(self, request: AnalyzeRequest):
        body = request.model_dump(mode="json")
        if len(json.dumps(body, ensure_ascii=False).encode("utf-8")) > 256 * 1024:
            raise ServiceError(422, "analysis_body_too_large", "Reduce el tamaño de la muestra.")
        data = await request_json(self.http, self.settings.ai_analyze_url, body,
                                  self.settings.ai_timeout_seconds, "ai", max_bytes=512 * 1024)
        try:
            return AnalyzeResponse.model_validate(data)
        except ValidationError:
            raise ServiceError(502, "ai_invalid_response", "La respuesta de IA no cumple el contrato.") from None
