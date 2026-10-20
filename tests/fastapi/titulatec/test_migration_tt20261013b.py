"""Contrato de la migración `tt20261013b` (`titulatec_official_averages`): la fuente
de Alembic y el modelo (que arma `create_all` en CI) describen la misma tabla,
PK, FK y CHECK. Solo se lee el archivo (patrón de `test_migration_tt20261013a.py`)."""
from pathlib import Path

import itcj2
from itcj2.apps.titulatec.models import OfficialAverage

_MIGRACION = (Path(itcj2.__file__).resolve().parent.parent / "migrations" / "versions"
              / "tt20261013b_titulatec_official_averages.py")


def _fuente() -> str:
    return _MIGRACION.read_text(encoding="utf-8")


def test_revision_y_down_revision():
    src = _fuente()
    assert 'revision = "tt20261013b"' in src
    assert 'down_revision = "tt20261013a"' in src


def test_migracion_declara_tabla_columnas_pk_fk_y_check():
    src = _fuente()
    assert "titulatec_official_averages" in src
    assert 'sa.Column("control_number", sa.String(length=20), nullable=False)' in src
    assert 'sa.Column("average", sa.Numeric(precision=5, scale=2), nullable=False)' in src
    assert 'sa.Column("loaded_by_id", sa.BigInteger(), nullable=True)' in src
    assert 'sa.Column("loaded_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False)' in src
    assert 'sa.PrimaryKeyConstraint("control_number")' in src
    assert 'sa.ForeignKeyConstraint(["loaded_by_id"], ["core_users.id"])' in src
    assert "ck_titulatec_official_averages_range" in src
    assert "average BETWEEN 0 AND 100" in src
    assert "op.drop_table" in src


def test_el_modelo_coincide_con_la_migracion():
    t = OfficialAverage.__table__
    assert t.name == "titulatec_official_averages"
    assert [c.name for c in t.primary_key.columns] == ["control_number"]
    assert not t.c.average.nullable
    assert (t.c.average.type.precision, t.c.average.type.scale) == (5, 2)
    assert not t.c.loaded_at.nullable
    assert t.c.loaded_by_id.nullable
    fks = {(fk.parent.name, fk.target_fullname) for fk in t.foreign_keys}
    assert fks == {("loaded_by_id", "core_users.id")}
    assert t.c.control_number.type.length == 20
    checks = {c.name: str(c.sqltext) for c in t.constraints
              if c.__class__.__name__ == "CheckConstraint"}
    assert checks == {"ck_titulatec_official_averages_range": "average BETWEEN 0 AND 100"}
