from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .config import Settings
from .errors import ServiceError
from .groq_client import GroqClient
from .routes import router

MAX_BODY_BYTES = 256 * 1024


class BodyLimitMiddleware:
    """Bound streamed bodies too; do not trust Content-Length."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        messages = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            total += len(message.get("body", b""))
            if total > MAX_BODY_BYTES:
                response = JSONResponse(status_code=413, content={"error": {
                    "code": "body_too_large", "message": "El cuerpo supera 256 KiB.", "details": [],
                }})
                return await response(scope, receive, send)
            messages.append(message)
            if not message.get("more_body", False):
                break
        iterator = iter(messages)

        async def replay():
            return next(iterator, {"type": "http.disconnect"})

        await self.app(scope, replay, send)


def create_app(provider=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        if provider is not None:
            app.state.provider = provider
            yield
        else:
            async with httpx.AsyncClient(follow_redirects=False) as client:
                try:
                    settings = Settings()
                except ValidationError:
                    # Safe startup error: Pydantic exceptions can include secret inputs.
                    raise RuntimeError("Configuración local inválida; revisa .env.example.") from None
                app.state.provider = GroqClient(settings, client)
                yield

    app = FastAPI(title="30X RADAR - IA", version="0.1.0", lifespan=lifespan)
    app.add_middleware(BodyLimitMiddleware)

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status, content={"error": {
            "code": exc.code, "message": exc.message, "details": [],
        }})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Never echo invalid input, validator context, or the request body.
        details = [{"location": list(e["loc"]), "type": e["type"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {
            "code": "invalid_input", "message": "La solicitud contiene datos inválidos.", "details": details,
        }})

    app.include_router(router)
    return app


app = create_app()
