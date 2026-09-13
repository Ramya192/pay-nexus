import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy import pool

from alembic import context

# alembic's own entry point doesn't put backend/ on sys.path the way running
# `python -m` or uvicorn from backend/ does — add it explicitly so the bare
# `from db.database import Base` style imports used everywhere else in this
# codebase work here too.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.database import Base  # noqa: E402
from db import models  # noqa: E402,F401 -- import so Base.metadata knows about them
from config import config as app_config  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# DATABASE_URL comes from .env (via app_config), not a duplicated, easy-to-
# drift copy hardcoded in alembic.ini. Deliberately NOT routed through
# config.set_main_option()/get_main_option() — those round-trip through
# Python's configparser, which treats a bare "%" as the start of its own
# interpolation syntax and throws on it. A password containing a URL-encoded
# character (e.g. "%24") breaks that round-trip; using app_config.DATABASE_URL
# directly when building the engine below sidesteps it entirely.

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

# pgvector's own tables (langchain_pg_collection, langchain_pg_embedding —
# created by rag/build_index.py via langchain_postgres.PGVector) live in the
# same database but aren't part of this app's SQLAlchemy models. Without
# this filter, autogenerate proposes DROPping them on every run, since it
# sees them in the live DB but not in target_metadata — which would delete
# the RAG index. Excluding by name rather than by reflected type/schema,
# since that's the actual distinguishing fact here.
_PGVECTOR_TABLES = {"langchain_pg_collection", "langchain_pg_embedding"}


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and name in _PGVECTOR_TABLES:
        return False
    if type_ == "index" and getattr(object, "table", None) is not None and object.table.name in _PGVECTOR_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=app_config.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = create_engine(app_config.DATABASE_URL, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
