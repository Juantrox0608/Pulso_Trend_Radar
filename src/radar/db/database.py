"""Conexión y sesiones de base de datos con soporte para Neon PostgreSQL y fallback a SQLite."""

import os
from collections.abc import Generator
from dotenv import load_dotenv
from sqlmodel import Session, SQLModel, create_engine

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# Neon / Heroku / Supabase a veces proveen postgres:// en lugar de postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Si no hay DATABASE_URL configurada, usar SQLite local para desarrollo y pruebas offline
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./radar.db"

# Argumentos del motor según el motor de base de datos
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args=connect_args,
    pool_pre_ping=True if "postgresql" in DATABASE_URL else False,
)


def init_db() -> None:
    """Crea las tablas en la base de datos si aún no existen."""
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """Generador de sesiones para inyección de dependencias en FastAPI."""
    with Session(engine) as session:
        yield session
