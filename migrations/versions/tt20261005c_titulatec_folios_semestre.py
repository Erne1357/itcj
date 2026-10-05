"""titulatec: folio de constancias por semestre (BIB-2026B-0001)

Spec `2026-10-05-titulatec-folios-design.md` §3.1/§3.2. Escrita a mano (sin
autogenerate), junto con el modelo: el CI arma el esquema con `create_all`
(sin Alembic) y dev/prod con Alembic -- la tabla de contadores y la
nulabilidad de `issued_by_id` estan declaradas AQUI y en
`models/certificate.py`, con el mismo nombre y tipo.

Que cambia
----------
* `titulatec_certificates.issued_by_id` pasa a NULLABLE: las importaciones y
  la CLI de folios de previas emiten sin usuario (`actor_id=None`).
* Folio `{PREFIJO}-{AAAA}{A|B}-{NNNN}` (antes `{PREFIJO}-{AAAA}-{NNNN}`),
  consecutivo por tipo + semestre. `A` = mes 1-6, `B` = mes 7-12 de
  `issued_at`. Las constancias existentes se RENUMERAN con UN `UPDATE` por
  `ROW_NUMBER() OVER (PARTITION BY kind, semestre ORDER BY issued_at, id)`.
  No choca con el UNIQUE de `number`: el formato viejo y el nuevo nunca
  coinciden (el nuevo lleva la letra del semestre).
* `titulatec_certificate_counters` se RECONSTRUYE: DROP + CREATE con PK
  `(kind, semester String(5))` (antes `(kind, year Integer)`) y un INSERT con
  el `COUNT(*)` de constancias por `(kind, semestre)` -- misma expresion de
  semestre que el renumerado, asi el siguiente folio sigue al ultimo.

En produccion no hay constancias: el renumerado y el INSERT no hacen nada. En
dev, las 3 BIB del 2026-10-05 quedan `BIB-2026B-0001..0003` y el contador en
`('library_clearance', '2026B', 3)`.

Downgrade (CON PERDIDA, documentada)
-------------------------------------
1. BORRA las constancias con `issued_by_id IS NULL` (folios de importacion y
   del backfill de previas/legado): el esquema viejo no las admite. Ninguna
   tabla tiene FK hacia `titulatec_certificates`; el `count` de un lote que
   las incluyera queda como estaba.
2. Renumera las que quedan a `{PREFIJO}-{AAAA}-{NNNN}` por `(kind, anio de
   issued_at)`, mismo orden `issued_at, id`.
3. Reconstruye los contadores `(kind, year Integer)` con su `COUNT(*)`.
4. Devuelve `issued_by_id` a NOT NULL.

Los folios de previas emitidos POR UN USUARIO (captura de SE/Biblioteca/GTV)
sobreviven a la bajada: el codigo viejo los trataria como constancias por
imprimir (apareceran en «Por imprimir» de la pagina de Constancias).

ADVERTENCIA: no ejecutar este SQL a mano. Solo via `alembic upgrade head` /
`alembic downgrade`.

Revision ID: tt20261005c
Revises: tt20261005b
Create Date: 2026-10-05
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261005c"
down_revision = "tt20261005b"
branch_labels = None
depends_on = None


# Semestre de `issued_at` (`2026A`/`2026B`), gemelo de
# `certificate_service.semester_key`. UNA sola definicion para el renumerado
# y el INSERT de contadores: si difirieran, el contador no seguiria al ultimo
# folio renumerado.
_SEM_SQL = (
    "EXTRACT(YEAR FROM issued_at)::int::text || "
    "CASE WHEN EXTRACT(MONTH FROM issued_at) <= 6 THEN 'A' ELSE 'B' END"
)

_PREFIX_SQL = "(CASE kind WHEN 'library_clearance' THEN 'BIB' ELSE 'GTV' END)"

UPGRADE_RENUMBER_SQL = f"""
UPDATE titulatec_certificates c
   SET number = r.nuevo
  FROM (SELECT id,
               {_PREFIX_SQL} || '-' || sem || '-' ||
               LPAD(ROW_NUMBER() OVER (PARTITION BY kind, sem
                                       ORDER BY issued_at, id)::text, 4, '0') AS nuevo
          FROM (SELECT *, {_SEM_SQL} AS sem
                  FROM titulatec_certificates) s) r
 WHERE c.id = r.id
"""

UPGRADE_COUNTERS_SQL = f"""
INSERT INTO titulatec_certificate_counters (kind, semester, last_value)
SELECT kind, sem, COUNT(*)
  FROM (SELECT kind, {_SEM_SQL} AS sem
          FROM titulatec_certificates) s
 GROUP BY kind, sem
"""

DOWNGRADE_DELETE_SQL = """
DELETE FROM titulatec_certificates WHERE issued_by_id IS NULL
"""

DOWNGRADE_RENUMBER_SQL = f"""
UPDATE titulatec_certificates c
   SET number = r.viejo
  FROM (SELECT id,
               {_PREFIX_SQL} || '-' || anio::text || '-' ||
               LPAD(ROW_NUMBER() OVER (PARTITION BY kind, anio
                                       ORDER BY issued_at, id)::text, 4, '0') AS viejo
          FROM (SELECT *, EXTRACT(YEAR FROM issued_at)::int AS anio
                  FROM titulatec_certificates) s) r
 WHERE c.id = r.id
"""

DOWNGRADE_COUNTERS_SQL = """
INSERT INTO titulatec_certificate_counters (kind, year, last_value)
SELECT kind, EXTRACT(YEAR FROM issued_at)::int, COUNT(*)
  FROM titulatec_certificates
 GROUP BY kind, EXTRACT(YEAR FROM issued_at)::int
"""


def upgrade() -> None:
    op.alter_column("titulatec_certificates", "issued_by_id",
                    existing_type=sa.BigInteger(), nullable=True)

    op.execute(sa.text(UPGRADE_RENUMBER_SQL))

    op.drop_table("titulatec_certificate_counters")
    op.create_table(
        "titulatec_certificate_counters",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("semester", sa.String(length=5), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("kind", "semester"),
    )
    op.execute(sa.text(UPGRADE_COUNTERS_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_DELETE_SQL))

    op.execute(sa.text(DOWNGRADE_RENUMBER_SQL))

    op.drop_table("titulatec_certificate_counters")
    op.create_table(
        "titulatec_certificate_counters",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("kind", "year"),
    )
    op.execute(sa.text(DOWNGRADE_COUNTERS_SQL))

    op.alter_column("titulatec_certificates", "issued_by_id",
                    existing_type=sa.BigInteger(), nullable=False)
