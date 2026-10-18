import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from app.errors import ServiceError
from app.main import BodyLimitMiddleware
from app.schemas import ErrorResponse
from .clients import AIClient, CollectorClient
from .errors import DependencyError
from .config import Settings
from .schemas import ResearchRequest, ResearchResponse
from .service import research


def create_app(settings=None, collector=None, ai=None):
    try:
        config = settings or Settings()
    except ValidationError:
        raise RuntimeError("Configuración inválida; revisa main_backend/.env.example.") from None

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(follow_redirects=False) as http:
            app.state.settings = config
            app.state.collector = collector or CollectorClient(config, http)
            app.state.ai = ai or AIClient(config, http)
            yield

    app = FastAPI(title="30X RADAR - Backend principal", version="0.1.0", lifespan=lifespan)
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"], allow_credentials=False)

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status, content={"error": {
            "code": exc.code, "message": exc.message,
            "details": exc.details if isinstance(exc, DependencyError) else [],
        }})

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": {
            "code": "invalid_input", "message": "Revisa pregunta, audiencia y filtros.",
            "details": [{"location": list(e["loc"]), "type": e["type"]} for e in exc.errors()],
        }})

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "main_backend", "collector_mode": app.state.settings.collector_mode}

    @app.post("/research", response_model=ResearchResponse, responses={
        code: {"model": ErrorResponse} for code in (413, 422, 502, 503, 504)
    })
    async def research_endpoint(body: ResearchRequest):
        try:
            async with asyncio.timeout(app.state.settings.research_timeout_seconds):
                return await research(body, app.state.collector, app.state.ai, app.state.settings.collector_mode)
        except TimeoutError:
            raise ServiceError(504, "research_timeout", "Se agotó el plazo total de investigación.") from None

    return app


app = create_app()
