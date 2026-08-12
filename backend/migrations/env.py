from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import URL, engine_from_config, pool

from backend.app.cloud.models import Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def migration_url() -> str:
    explicit = os.getenv("WORKBENCH_MIGRATION_DATABASE_URL", "").strip()
    if explicit:
        return explicit
    password = os.getenv("POSTGRES_PASSWORD", "").strip()
    if not password:
        raise RuntimeError("数据库迁移缺少 POSTGRES_PASSWORD 或 WORKBENCH_MIGRATION_DATABASE_URL")
    return URL.create(
        "postgresql+psycopg",
        username=os.getenv("POSTGRES_USER", "workbench_owner"),
        password=password,
        host=os.getenv("WORKBENCH_DB_HOST", "postgres"),
        port=int(os.getenv("WORKBENCH_DB_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "workbench"),
    ).render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    context.configure(
        url=migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = migration_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
