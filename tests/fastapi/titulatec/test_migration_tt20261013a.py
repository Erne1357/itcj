"""Contrato de la migración `tt20261013a` (`titulatec_nip_stash`): la fuente de
Alembic y el modelo (que arma `create_all` en CI) describen la misma tabla,
PK y FK. Solo se lee el archivo (patrón de `test_migration_tt20260928a.py`)."""
from pathlib import Path

import itcj2
from itcj2.apps.titulatec.models import NipStash

_MIGRACION = (Path(itcj2.__file__).resolve().parent.parent / "migrations" / "versions"
              / "tt20261013a_titulatec_nip_stash.py")


def _fuente() -> str:
    return _MIGRACION.read_text(encoding="utf-8")


def test_revision_y_down_revision():
    src = _fuente()
    assert 'revision = "tt20261013a"' in src
    assert 'down_revision = "tt20261012a"' in src


def test_migracion_declara_tabla_columnas_pk_y_fk():
    src = _fuente()
    assert "titulatec_nip_stash" in src
    assert 'sa.Column("control_number", sa.String(length=20), nullable=False)' in src
    assert 'sa.Column("nip_cipher", sa.Text(), nullable=False)' in src
    assert 'sa.Column("loaded_by_id", sa.BigInteger(), nullable=True)' in src
    assert 'sa.Column("loaded_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False)' in src
    assert 'sa.PrimaryKeyConstraint("control_number")' in src
    assert 'sa.ForeignKeyConstraint(["loaded_by_id"], ["core_users.id"])' in src
    assert "op.drop_table" in src


def test_el_modelo_coincide_con_la_migracion():
    t = NipStash.__table__
    assert t.name == "titulatec_nip_stash"
    assert [c.name for c in t.primary_key.columns] == ["control_number"]
    assert not t.c.nip_cipher.nullable
    assert not t.c.loaded_at.nullable
    assert t.c.loaded_by_id.nullable
    fks = {(fk.parent.name, fk.target_fullname) for fk in t.foreign_keys}
    assert fks == {("loaded_by_id", "core_users.id")}
    assert t.c.control_number.type.length == 20
