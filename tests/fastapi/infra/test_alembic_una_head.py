"""`deploy.sh` corre `alembic upgrade head`: con dos heads se detiene a mitad del deploy.

Pasó con el PR #92 (2026-11-13, mg20261113a) y antes con 53cfd4188f65. Aquí truena
en el CI del PR, que prueba la rama ya mezclada con main, antes de llegar al deploy.
"""
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "migrations" / "alembic.ini"


def test_migraciones_con_una_sola_head():
    heads = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_heads()
    assert len(heads) == 1, (
        f"Hay {len(heads)} heads de alembic: {sorted(heads)}. Crea una migración de merge: "
        "`alembic -c migrations/alembic.ini merge heads -m \"merge ...\"`."
    )
