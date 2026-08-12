"""Replica el paso "Preparar esquema de BD de test" del pipeline.

Sirve para reproducir en local una BD como la de CI —vacia, construida con
create_all y sin nada de database/DML/— y cazar ahi los tests que solo pasan
porque la BD de desarrollo trae catalogos y usuarios sembrados.

    docker exec -w /app -e PYTHONPATH=/app \
      -e MIGRATE_DATABASE_URL=postgresql+psycopg2://postgres:password@postgres:5432/itcj_ci_check \
      itcj-backend-1 python scripts/ci_schema_check.py
"""
import os

import itcj2.models  # noqa: F401  core + apps
import itcj2.apps.titulatec.models  # noqa: F401
import itcj2.apps.directory.models  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import ENUM as PGEnum

from itcj2.models.base import Base

engine = create_engine(os.environ["MIGRATE_DATABASE_URL"], future=True)

# Los modelos declaran los ENUM con create_type=False (los crea la migracion),
# asi que create_all no emite el CREATE TYPE: hay que crearlos antes.
enums = {}
for tabla in Base.metadata.tables.values():
    for col in tabla.columns:
        if isinstance(col.type, PGEnum):
            enums.setdefault(col.type.name, col.type)

with engine.begin() as conn:
    for enum in enums.values():
        enum.create(conn, checkfirst=True)

Base.metadata.create_all(engine, checkfirst=True)
print(f"esquema listo: {len(Base.metadata.tables)} tablas; enums: {sorted(enums)}")
