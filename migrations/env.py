import logging
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Alembic config ────────────────────────────────────────────────────────────
config = context.config
fileConfig(config.config_file_name)
logger = logging.getLogger("alembic.env")

# DATABASE_URL desde variable de entorno (anula alembic.ini si está definida)
database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

# ── Importar todos los modelos de itcj2 para autogenerate ───────────────────
from itcj2.models.base import Base  # noqa: E402

import itcj2.core.models  # noqa: F401, E402
import itcj2.apps.helpdesk.models  # noqa: F401, E402
import itcj2.apps.agendatec.models  # noqa: F401, E402
import itcj2.apps.vistetec.models  # noqa: F401, E402

target_metadata = Base.metadata


# ── Migrations ────────────────────────────────────────────────────────────────

def run_migrations_offline():
    """Run migrations in 'offline' mode (sin conexión activa)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode (con conexión activa)."""

    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, "autogenerate", False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info("No changes in schema detected.")

    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            process_revision_directives=process_revision_directives,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
