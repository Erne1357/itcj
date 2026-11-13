"""merge prorrogas y directorio heads

El deploy del PR #92 (2026-11-13) se detuvo en `alembic upgrade head`: Prórrogas
(pr20261109b) y el directorio (d1r3ct0ry03) salieron del mismo padre.

Revision ID: mg20261113a
Revises: d1r3ct0ry03, pr20261109b
Create Date: 2026-11-13 00:00:00

"""


# revision identifiers, used by Alembic.
revision = 'mg20261113a'
down_revision = ('d1r3ct0ry03', 'pr20261109b')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
