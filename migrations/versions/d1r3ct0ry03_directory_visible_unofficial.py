"""directory: visibilidad de departamentos no oficiales uno por uno

Añade directory_settings.visible_unofficial_department_ids (lista JSON). Si el
interruptor global estaba encendido, se conservan visibles TODOS los no oficiales
activos, para que el despliegue no esconda nada. La columna vieja se queda (el
código anterior la sigue leyendo mientras se despliega).

Revision ID: d1r3ct0ry03
Revises: hd20261028a
"""
import sqlalchemy as sa
from alembic import op

revision = "d1r3ct0ry03"
down_revision = "hd20261028a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "directory_settings",
        sa.Column("visible_unofficial_department_ids", sa.JSON(), nullable=False,
                  server_default=sa.text("'[]'")),
    )
    op.execute(
        """
        UPDATE directory_settings
           SET visible_unofficial_department_ids = COALESCE(
                 (SELECT json_agg(d.id ORDER BY d.id) FROM core_departments d
                   WHERE d.is_active AND NOT d.is_official),
                 '[]'::json)
         WHERE id = 1 AND show_unofficial_departments
        """
    )


def downgrade() -> None:
    op.drop_column("directory_settings", "visible_unofficial_department_ids")
