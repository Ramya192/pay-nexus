"""
PostgreSQL connection — SQLAlchemy engine, session factory, declarative Base,
and the `get_db` FastAPI dependency. ORM models live in db/models.py; this
file only wires the connection, per PROJECT_CONTEXT.md §12 (DATABASE_URL).

This is also the same DATABASE_URL the pgvector collection lives on
(backend/rag/build_index.py) — one Postgres instance, two uses.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import config


class Base(DeclarativeBase):
    pass


engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create tables that don't exist yet — create_all, not a migration tool.

    Superseded by Alembic (alembic/) as the real setup path: run
    `alembic upgrade head` once before starting the server. NOT called
    automatically from api/main.py's startup anymore — the two don't mix
    safely. If create_all silently bootstraps a fresh database first,
    Alembic never gets a chance to stamp it with a revision, and the next
    `alembic upgrade head` fails trying to CREATE TABLE on tables that
    already exist.

    Kept around for quick, throwaway scripts (a one-off Python REPL against
    a scratch database) where pulling in Alembic is overkill — not for
    anything that also runs migrations against the same database.
    """
    from db import models  # noqa: F401 — import so Base.metadata knows about them

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: `db: Session = Depends(get_db)`."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
