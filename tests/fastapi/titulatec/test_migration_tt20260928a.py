"""Contrato de la migración `tt20260928a`: crea `titulatec_email_outbox`
con sus 5 nombres exactos de índice/constraint.

Solo lee el archivo de la migración (patrón de `test_migration_tt20260927a.py`):
el harness de tests arma el esquema con `create_all` (sin Alembic), así que
no hay forma de "correr" la migración aquí -- se verifica su fuente.
"""
import re
from pathlib import Path

import itcj2

_MIGRACION = (Path(itcj2.__file__).resolve().parent.parent / "migrations" / "versions"
              / "tt20260928a_titulatec_email_outbox.py")


def _fuente() -> str:
    return _MIGRACION.read_text(encoding="utf-8")


def _cuerpo(nombre: str, src: str) -> str:
    """El cuerpo de `def {nombre}(...):` hasta la siguiente `def` a nivel de módulo."""
    m = re.search(rf"\ndef {nombre}\(.*?\).*?:\n(.*?)(?=\ndef \w|\Z)", src, re.S)
    assert m, f"no se encontro 'def {nombre}(...)' en la migracion"
    return m.group(1)


def test_revision_y_down_revision():
    src = _fuente()
    assert 'revision = "tt20260928a"' in src
    assert 'down_revision = "tt20260927b"' in src


def test_las_constantes_de_tabla_apuntan_a_las_tablas_correctas():
    src = _fuente()
    assert '_TABLE = "titulatec_email_outbox"' in src
    assert '_PROCESSES = "titulatec_processes"' in src
    assert '_USERS = "core_users"' in src


def test_upgrade_fija_lock_timeout_antes_de_cualquier_ddl():
    """Tabla nueva sin filas existentes: el tope es red de seguridad, no
    protección de un backfill. Aun así debe ir PRIMERO (mismo contrato que
    `tt20260927a`), antes de `op.create_table`."""
    upgrade = _cuerpo("upgrade", _fuente())
    sentencias = [ln.strip() for ln in upgrade.splitlines()
                  if ln.strip() and not ln.strip().startswith("#")]

    assert sentencias[0] == 'op.execute("SET LOCAL lock_timeout = \'10s\'")', sentencias[:2]
    assert upgrade.index("lock_timeout") < upgrade.index("op.create_table")


def test_upgrade_crea_la_tabla_con_las_columnas_exactas():
    upgrade = _cuerpo("upgrade", _fuente())

    assert "op.create_table(" in upgrade

    # Columnas de una sola línea (sin server_default): substring literal alcanza.
    assert 'sa.Column("id", sa.Integer(), nullable=False)' in upgrade
    assert 'sa.Column("kind", sa.String(length=40), nullable=False)' in upgrade
    assert 'sa.Column("process_id", sa.Integer(), nullable=True)' in upgrade
    assert 'sa.Column("user_id", sa.BigInteger(), nullable=False)' in upgrade
    assert 'sa.Column("group_key", sa.String(length=80), nullable=True)' in upgrade
    assert 'sa.Column("dedupe_key", sa.String(length=160), nullable=True)' in upgrade
    assert 'sa.Column("payload", sa.JSON(), nullable=False)' in upgrade
    assert 'sa.Column("subject", sa.String(length=200), nullable=True)' in upgrade
    assert 'sa.Column("sent_to", sa.String(length=150), nullable=True)' in upgrade
    assert 'sa.Column("last_error", sa.String(length=255), nullable=True)' in upgrade
    assert 'sa.Column("sent_at", sa.DateTime(), nullable=True)' in upgrade

    # Columnas con server_default parten en dos líneas en el archivo real;
    # cada mitad SÍ cabe en una sola línea, así que un substring literal
    # alcanza (evita pelearse con los paréntesis anidados de sa.text(...)
    # en un regex).
    assert 'sa.Column("status", sa.String(length=20),' in upgrade
    assert 'server_default=sa.text("\'pending\'"), nullable=False),' in upgrade

    assert 'sa.Column("attempts", sa.Integer(),' in upgrade
    assert 'server_default=sa.text("0"), nullable=False),' in upgrade

    assert 'sa.Column("not_before", sa.DateTime(),' in upgrade
    assert 'sa.Column("created_at", sa.DateTime(),' in upgrade
    # Misma línea de cierre para ambas (not_before Y created_at): confirma
    # que las DOS, no solo una, quedan NOT NULL con server_default NOW().
    assert upgrade.count('server_default=sa.text("NOW()"), nullable=False),') == 2

    # FKs a las tablas correctas + PK.
    assert 'sa.ForeignKeyConstraint(["process_id"], [f"{_PROCESSES}.id"])' in upgrade
    assert 'sa.ForeignKeyConstraint(["user_id"], [f"{_USERS}.id"])' in upgrade
    assert 'sa.PrimaryKeyConstraint("id")' in upgrade


def test_upgrade_declara_los_5_nombres_exactos_de_indice_y_constraint():
    """Estos 5 nombres son el contrato del despachador (Tarea 7) y deben
    coincidir letra por letra con los que declara el modelo -- el CI arma
    el esquema con `create_all`, dev/prod con esta migración."""
    upgrade = _cuerpo("upgrade", _fuente())

    assert ('sa.UniqueConstraint("dedupe_key", '
            'name="uq_titulatec_email_outbox_dedupe_key")') in upgrade

    idx_process = re.search(
        r'op\.create_index\(\s*"ix_titulatec_email_outbox_process_id".*?\)', upgrade, re.S,
    ).group(0)
    assert '["process_id"]' in idx_process

    idx_user = re.search(
        r'op\.create_index\(\s*"ix_titulatec_email_outbox_user_id".*?\)', upgrade, re.S,
    ).group(0)
    assert '["user_id"]' in idx_user

    idx_group = re.search(
        r'op\.create_index\(\s*"ix_titulatec_email_outbox_group_key".*?\)', upgrade, re.S,
    ).group(0)
    assert '["group_key"]' in idx_group

    idx_status = re.search(
        r'op\.create_index\(\s*"ix_titulatec_email_outbox_status_not_before".*?\]\s*,?\s*\)',
        upgrade, re.S,
    ).group(0)
    assert '["status", "not_before"]' in idx_status


def test_downgrade_borra_los_4_indices_y_la_tabla():
    downgrade = _cuerpo("downgrade", _fuente())

    assert 'op.drop_index("ix_titulatec_email_outbox_status_not_before", table_name=_TABLE)' in downgrade
    assert 'op.drop_index("ix_titulatec_email_outbox_group_key", table_name=_TABLE)' in downgrade
    assert 'op.drop_index("ix_titulatec_email_outbox_user_id", table_name=_TABLE)' in downgrade
    assert 'op.drop_index("ix_titulatec_email_outbox_process_id", table_name=_TABLE)' in downgrade
    assert "op.drop_table(_TABLE)" in downgrade

    # La tabla se borra AL FINAL, despues de sus propios indices.
    assert downgrade.index("op.drop_table(_TABLE)") > downgrade.index(
        'op.drop_index("ix_titulatec_email_outbox_status_not_before"'
    )
