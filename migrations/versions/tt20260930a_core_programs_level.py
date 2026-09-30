"""core: nivel academico de una carrera (core_programs.level)

Agrega `core_programs.level` (spec 2026-09-30-titulatec-posgrado-design.md
§4.1, decision D1 del usuario: "el nivel vive en el core: core_programs.level
= licenciatura | maestria | doctorado"). El core solo declara el nivel
academico de la carrera; TitulaTec construye ENCIMA su perfil de titulacion
"posgrado" (maestria o doctorado) via `TrackService.for_level` (tarea aparte)
-- ningun otro modulo debe leer `level` directamente ni comparar nombres de
carrera.

- `level`: String(20) NOT NULL, `server_default='licenciatura'`. Las 25
  carreras de dev y del respaldo del 2026-09-17 son todas de licenciatura, asi
  que el default no cambia el significado de ninguna fila existente.
- CheckConstraint `ck_core_programs_level` con el mismo dominio que
  `itcj2/core/models/program.py::PROGRAM_LEVELS`, para que el `create_all` de
  CI y esta migracion nunca diverjan.
- La clasificacion real de las 4 carreras de posgrado que ya existen en prod
  (localizadas POR NOMBRE normalizado, nunca por id ni por "las ultimas
  cuatro") es un DML aparte (`database/DML/titulatec/posgrado_2026_10/`,
  tarea 7 del plan): esta migracion solo abre el espacio en el esquema, no
  clasifica ninguna carrera.

Compatibilidad blue/green: el codigo viejo (anterior a este deploy) no lista
`level` en sus SELECT ni en sus INSERT explicitos de `core_programs` -- el
`server_default` la llena sola --, asi que una version vieja del backend
sigue funcionando sin cambios contra la tabla ya migrada. Esa version vieja
jamas escribe un valor fuera del dominio porque nunca escribe la columna.

Downgrade: quita el CheckConstraint y despues la columna (un constraint vivo
impide tirar la columna). Sin perdida de informacion mas alla del propio
nivel: en esta rama nada mas depende todavia de esta columna.

Revisión ID: tt20260930a
Revises: tt20260929a
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20260930a"
down_revision = "tt20260929a"
branch_labels = None
depends_on = None

_TABLE = "core_programs"
_CHECK = "ck_core_programs_level"
_DOMAIN = "level IN ('licenciatura','maestria','doctorado')"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            "level", sa.String(length=20), nullable=False,
            server_default="licenciatura",
            comment="Nivel academico de la carrera: licenciatura | maestria | doctorado",
        ),
    )
    op.create_check_constraint(_CHECK, _TABLE, _DOMAIN)


def downgrade() -> None:
    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.drop_column(_TABLE, "level")
