"""Servidor FastAPI principal para Radar de Tendencias (30X Media)."""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from radar.api.mock_data import SEED_TRENDS
from radar.contrato import Opportunity, OpportunityUpdate, Publicacion, Trend
from radar.db.database import get_session, init_db
from radar.db.models import OpportunityDB, PublicacionDB, TrendDB


def _calcular_score_velocidad(views: int, likes: int, comments: int, published_iso: str) -> float:
    """Calcula la velocidad de engagement para priorizar contenido que apenas despega."""
    try:
        pub_dt = datetime.fromisoformat(published_iso.replace("Z", "+00:00"))
        horas = max((datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600.0, 1.0)
    except Exception:
        horas = 24.0
    # Fórmula: interacciones ponderadas sobre el paso del tiempo
    interacciones = (likes * 2) + (comments * 5)
    return float(interacciones / (horas ** 1.1 + 2.0))


def _sembrar_datos_iniciales(session: Session) -> None:
    """Puebla la base de datos con las tendencias de referencia si la tabla está vacía."""
    existentes = session.exec(select(TrendDB)).first()
    if not existentes:
        for t in SEED_TRENDS:
            score = _calcular_score_velocidad(t.views, t.likes, t.comments, t.publishedAt)
            trend_db = TrendDB(
                id=t.id,
                title=t.title,
                creator=t.creator,
                platform=t.platform,
                category=t.category,
                views=t.views,
                likes=t.likes,
                comments=t.comments,
                published_at=t.publishedAt,
                image=t.image,
                insight=t.insight,
                angle=t.angle,
                hook=t.hook,
                audience=t.audience,
                format=t.format,
                source_url=t.sourceUrl,
                engagement_score=score,
            )
            session.add(trend_db)
        session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la base de datos y carga los datos semilla en un hilo secundario sin congelar el servidor."""
    def _inicializar():
        init_db()
        with next(get_session()) as session:
            _sembrar_datos_iniciales(session)

    await run_in_threadpool(_inicializar)
    yield


app = FastAPI(
    title="30X Radar de Tendencias API",
    description="API para descubrir tendencias de contenido sobre IA en YouTube, TikTok y LinkedIn con análisis editorial para LATAM.",
    version="1.0.0",
    lifespan=lifespan,
)

# Configuración de CORS para permitir peticiones desde Next.js local y producción
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["General"])
def root():
    return {
        "sistema": "30X Radar de Tendencias",
        "version": "1.0.0",
        "estado": "operativo",
        "docs": "/docs",
        "redes_soportadas": ["YouTube", "TikTok", "LinkedIn"],
    }


@app.get("/health", tags=["General"])
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/trends", response_model=list[Trend], tags=["Tendencias"])
def get_trends(
    query: Annotated[str | None, Query(description="Término o tema a buscar (ej. Agentes IA, automatización)")] = None,
    platform: Annotated[str | None, Query(description="Filtrar por plataforma (YouTube, TikTok, LinkedIn)")] = None,
    category: Annotated[str | None, Query(description="Filtrar por categoría")] = None,
    session: Session = Depends(get_session),
):
    """Devuelve las tendencias ordenadas por velocidad de crecimiento con su análisis editorial."""
    statement = select(TrendDB)
    
    if platform and platform.lower() != "all":
        statement = statement.where(TrendDB.platform.ilike(platform))
        
    if category:
        statement = statement.where(TrendDB.category.ilike(f"%{category}%"))

    trends_db = session.exec(statement).all()
    if not trends_db and not query and not platform and not category:
        _sembrar_datos_iniciales(session)
        trends_db = session.exec(statement).all()

    # Si hay query de búsqueda, filtramos por título, categoría, gancho o insight
    if query and query.strip():
        q_lower = query.strip().lower()
        trends_db = [
            t for t in trends_db
            if (
                q_lower in t.title.lower()
                or q_lower in t.category.lower()
                or q_lower in t.insight.lower()
                or q_lower in t.angle.lower()
                or q_lower in t.hook.lower()
                or q_lower in t.audience.lower()
            )
        ]

    # Ordenar por el score de velocidad (lo que más rápido crece primero)
    trends_ordenadas = sorted(trends_db, key=lambda x: x.engagement_score, reverse=True)
    return [t.to_contract() for t in trends_ordenadas]


@app.get("/api/trends/{trend_id}", response_model=Trend, tags=["Tendencias"])
def get_trend_by_id(trend_id: str, session: Session = Depends(get_session)):
    """Obtiene los detalles y análisis editorial de una tendencia específica."""
    trend = session.get(TrendDB, trend_id)
    if not trend:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tendencia no encontrada")
    return trend.to_contract()


@app.get("/api/opportunities", response_model=list[Opportunity], tags=["Oportunidades"])
def get_opportunities(session: Session = Depends(get_session)):
    """Lista las propuestas y oportunidades editoriales guardadas."""
    oportunidades = session.exec(select(OpportunityDB)).all()
    # Si no hay ninguna en DB, proveemos estado inicial con las tendencias base
    if not oportunidades:
        trends = session.exec(select(TrendDB)).all()
        return [
            Opportunity(id=f"op-{t.id}", trendId=t.id, status="Pendiente", savedAt=t.created_at)
            for t in trends[:4]
        ]
    return [op.to_contract() for op in oportunidades]


@app.post("/api/opportunities", response_model=Opportunity, status_code=status.HTTP_201_CREATED, tags=["Oportunidades"])
def create_opportunity(opportunity: Opportunity, session: Session = Depends(get_session)):
    """Guarda o actualiza una oportunidad editorial en el pipeline."""
    existente = session.get(OpportunityDB, opportunity.id)
    if existente:
        existente.status = opportunity.status
        existente.saved_at = opportunity.savedAt
        session.add(existente)
        session.commit()
        session.refresh(existente)
        return existente.to_contract()

    op_db = OpportunityDB(
        id=opportunity.id,
        trend_id=opportunity.trendId,
        status=opportunity.status,
        saved_at=opportunity.savedAt,
    )
    session.add(op_db)
    session.commit()
    session.refresh(op_db)
    return op_db.to_contract()


@app.patch("/api/opportunities/{opportunity_id}", response_model=Opportunity, tags=["Oportunidades"])
def update_opportunity_status(
    opportunity_id: str,
    payload: OpportunityUpdate,
    session: Session = Depends(get_session),
):
    """Actualiza el estado de una oportunidad (Aprobada, Descartada, Pendiente)."""
    op = session.get(OpportunityDB, opportunity_id)
    if not op:
        # Si aún no estaba persistida pero existe el trend, la creamos al vuelo
        op = OpportunityDB(
            id=opportunity_id,
            trend_id=opportunity_id.replace("op-", ""),
            status=payload.status,
            saved_at=datetime.now(timezone.utc).isoformat(),
        )
    else:
        op.status = payload.status
        op.saved_at = datetime.now(timezone.utc).isoformat()

    session.add(op)
    session.commit()
    session.refresh(op)
    return op.to_contract()


@app.post("/api/publicaciones", status_code=status.HTTP_201_CREATED, tags=["Recolección"])
def registrar_publicaciones(
    publicaciones: list[Publicacion],
    session: Session = Depends(get_session),
):
    """Recibe un lote de publicaciones recolectadas por YouTube/TikTok/LinkedIn y las guarda en base de datos."""
    guardadas = 0
    actualizadas = 0
    for pub in publicaciones:
        existente = session.get(PublicacionDB, pub.id)
        if not existente:
            pub_db = PublicacionDB(
                id=pub.id,
                plataforma=pub.plataforma.value,
                titulo=pub.titulo,
                texto=pub.texto,
                hashtags=str(list(pub.hashtags)),
                formato=pub.formato.value,
                duracion_segundos=pub.duracion_segundos,
                idioma=pub.idioma,
                pais=pub.pais,
                tipo_autor=pub.tipo_autor.value,
                autor_hash=pub.autor_hash,
                publicada_en=pub.publicada_en.isoformat(),
                capturada_en=pub.capturada_en.isoformat(),
                origen=pub.origen.value,
                url=pub.url,
            )
            session.add(pub_db)
            guardadas += 1

            # También generamos una entrada en TrendDB preliminar para que aparezca en el buscador
            trend_existente = session.get(TrendDB, pub.id)
            if not trend_existente and pub.titulo:
                plat_nombre = "YouTube" if pub.plataforma.value == "youtube" else ("TikTok" if pub.plataforma.value == "tiktok" else "LinkedIn")
                nuevo_trend = TrendDB(
                    id=pub.id,
                    title=pub.titulo,
                    creator="Creador de " + plat_nombre,
                    platform=plat_nombre,
                    category="IA y Automatización",
                    views=1000,
                    likes=120,
                    comments=15,
                    published_at=pub.publicada_en.isoformat(),
                    source_url=pub.url,
                    insight="Publicación capturada recientemente. Pendiente de enriquecimiento profundo por IA.",
                    angle="Cómo aplicar esta tendencia en organizaciones de LATAM",
                    hook="¿Cómo impacta esto a los equipos en nuestra región?",
                    audience="Líderes y equipos en LATAM",
                    format="Video o Carrusel",
                    engagement_score=50.0,
                )
                session.add(nuevo_trend)
        else:
            existente.titulo = pub.titulo
            existente.texto = pub.texto
            existente.capturada_en = pub.capturada_en.isoformat()
            session.add(existente)
            actualizadas += 1

    session.commit()
    return {"guardadas": guardadas, "actualizadas": actualizadas, "recibidas": len(publicaciones)}


@app.post("/api/trends/{trend_id}/analizar", response_model=Trend, tags=["IA"])
def enriquecer_con_ia(
    trend_id: str,
    session: Session = Depends(get_session),
):
    """Endpoint para que el módulo de IA aplique el análisis editorial a una tendencia."""
    trend = session.get(TrendDB, trend_id)
    if not trend:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tendencia no encontrada")
    
    # Aquí es donde se conectará la rama feature/IA
    trend.insight = f"Análisis IA: El tema '{trend.title}' resuelve una necesidad operativa concreta con alta tracción."
    trend.hook = f"¿Por qué todas las empresas líderes están hablando de {trend.category} esta semana?"
    session.add(trend)
    session.commit()
    session.refresh(trend)
    return trend.to_contract()
