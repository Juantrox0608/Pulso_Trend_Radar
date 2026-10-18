import asyncio
import json
import re

import httpx

from app.errors import ServiceError
from app.schemas import AnalyzeRequest, AnalyzeResponse
from pydantic import ValidationError


async def request_json(http, url, payload, timeout, service, headers=None, max_bytes=2 * 1024 * 1024,
                       method="POST", expected_status=200):
    try:
        async with asyncio.timeout(timeout):
            kwargs = {"json": payload} if method == "POST" else {}
            async with http.stream(method, str(url), headers=headers, timeout=timeout, **kwargs) as response:
                if not response.is_success:
                    if service == "collector" and response.status_code == 409:
                        raise ServiceError(503, "collector_busy", "El recolector ya tiene una búsqueda en curso; espera antes de iniciar otra.")
                    if service == "collector" and response.status_code == 404:
                        raise ServiceError(502, "collector_search_lost", "La búsqueda no existe o se perdió al reiniciar el recolector.")
                    if response.status_code == 429:
                        raise ServiceError(503, f"{service}_rate_limited", f"{service}: límite de uso alcanzado.")
                    if response.status_code in {401, 403}:
                        raise ServiceError(503, f"{service}_authentication", f"Revisa las credenciales de {service}.")
                    if response.status_code in {503, 504}:
                        raise ServiceError(response.status_code, f"{service}_unavailable", f"{service} no está disponible o agotó su plazo.")
                    raise ServiceError(502, f"{service}_error", f"{service} rechazó la solicitud.")
                if response.status_code != expected_status:
                    raise ServiceError(502, f"{service}_invalid_response", f"Estado HTTP inesperado de {service}.")
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
        from .collector_contract import collector_parameters
        parameters = collector_parameters(filters, self.settings)
        search_id = None
        try:
            async with asyncio.timeout(self.settings.collector_search_timeout_seconds):
                base = str(self.settings.collector_url).rstrip("/")
                try:
                    started = await request_json(self.http, base + "/busquedas", parameters,
                        self.settings.collector_timeout_seconds, "collector", expected_status=202)
                except ServiceError as exc:
                    if exc.code in {"collector_timeout", "collector_unavailable", "collector_invalid_json",
                                    "collector_invalid_response", "collector_response_too_large"}:
                        raise ServiceError(exc.status, "collector_start_uncertain",
                            "No se pudo confirmar el inicio. No repitas automáticamente POST /busquedas: podría existir una tarea activa.") from None
                    raise
                if (not isinstance(started, dict) or started.get("estado") != "en_curso"
                        or not isinstance(started.get("id"), str) or not re.fullmatch(r"[a-f0-9]{32}", started["id"])):
                    raise ServiceError(502, "collector_start_uncertain",
                        "Inicio inválido o sin ID confirmado. No repitas automáticamente la creación.")
                search_id = started["id"]
                result = await self.wait_for_search(search_id)
                result["search_id"] = search_id
                result["request_parameters"] = parameters
                return result
        except ServiceError as exc:
            if search_id:
                exc.message += f" ID de búsqueda: {search_id}. Conserva este ID; no crees otra tarea automáticamente."
            raise
        except TimeoutError:
            suffix = f" Consulta GET /busquedas/{search_id} para recuperar el resultado." if search_id else " No repitas automáticamente el POST: el inicio pudo haber ocurrido."
            raise ServiceError(504, "collector_search_timeout", "Se agotó el plazo de recolección." + suffix) from None

    async def wait_for_search(self, search_id):
        base = str(self.settings.collector_url).rstrip("/")
        while True:
            result = await request_json(self.http, base + "/busquedas/" + search_id, None,
                self.settings.collector_timeout_seconds, "collector", method="GET")
            if not isinstance(result, dict):
                raise ServiceError(502, "collector_invalid_response", "La consulta de búsqueda no es un objeto.")
            state = result.get("estado")
            if state == "lista":
                return result
            if state == "error":
                raise ServiceError(502, "collector_search_failed", "El recolector informó una búsqueda fallida; no se consultó IA.")
            if state != "en_curso":
                raise ServiceError(502, "collector_invalid_state", "El recolector devolvió un estado desconocido.")
            await asyncio.sleep(self.settings.collector_poll_interval_seconds)


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
