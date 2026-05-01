"""Alembic environment — autotax modelleriyle baglantili online/offline migration runner.

DATABASE_URL ortam degiskeninden okunur. Postgres icin 'postgres://' onekini
SQLAlchemy 2.x sentaksina uyacak sekilde 'postgresql://' olarak duzeltir.
target_metadata = autotax.models.Base.metadata — autogenerate tum tablolari gorur.
"""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Repo kokunu sys.path'e ekle ki 'autotax' import edilebilsin
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autotax.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///autotax.db")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def run_migrations_offline() -> None:
    """Sadece SQL uretir, DB'ye baglanmaz."""
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Canli DB'ye karsi migration calistirir."""
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
