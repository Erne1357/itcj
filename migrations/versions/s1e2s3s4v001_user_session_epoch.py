"""core_users.session_epoch: fuente de verdad de la revocación de sesión

Revision ID: s1e2s3s4v001
Revises: f6feb1cdc56a
Create Date: 2026-08-20

Aditiva y con server_default: la tabla ya tiene filas y la columna es NOT NULL.

**Los usuarios existentes arrancan en 0, y eso SOLO es seguro después de correr
`python -m itcj2.cli.main core backfill-session-epoch`.** El 0 equivale a lo que
`current_version` devolvía únicamente para los usuarios que NO tenían clave en
Redis — que es justamente la población a la que el control no protege. Para
todos los demás, producción tiene hoy claves `authz:v1:sessionver:{uid}` y JWTs
vivos con `sv = N` acuñado desde ellas, así que desplegar el código nuevo sobre
esta migración sin backfill:

  - desloguea todo token con `sv >= 1` (falla `sv != 0`), y
  - REVIVE todo token ya revocado que quedara en `sv == 0` y siga dentro de sus
    12h de expiración (cuadra `0 == 0`), cuentas desactivadas incluidas.

Es decir, reproduce el incidente del 2026-08-20 entero, sus dos mitades. Orden
obligatorio: `alembic upgrade head` → `core backfill-session-epoch` → rollout
del código. Ver el runbook en
docs/superpowers/plans/2026-08-20-authz-cache-keyspace-fix.md
"""
from alembic import op
import sqlalchemy as sa

revision = "s1e2s3s4v001"
down_revision = "f6feb1cdc56a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "core_users",
        sa.Column("session_epoch", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("core_users", "session_epoch")
