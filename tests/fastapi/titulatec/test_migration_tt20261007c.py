"""Contrato de `tt20261007c`: índice parcial de prefijo sobre `subject_label`.

Se lee el fuente de la migración y el índice del modelo (el harness arma el
esquema con `create_all`, así que además se consulta el catálogo de la base de la
prueba: el CI también lo debe tener).
"""
from pathlib import Path

import itcj2
from sqlalchemy import text

_MIGRACION = (Path(itcj2.__file__).resolve().parent.parent / "migrations" / "versions"
              / "tt20261007c_titulatec_audit_log_subject_index.py")
_NOMBRE = "ix_titulatec_audit_log_subject_label_prefix"


def test_revisiones_y_sql_de_la_migracion():
    src = _MIGRACION.read_text(encoding="utf-8")
    assert 'revision = "tt20261007c"' in src
    assert 'down_revision = "tt20261007b"' in src
    assert "(subject_label text_pattern_ops) WHERE process_id IS NULL" in src
    assert "DROP INDEX IF EXISTS" in src


def test_el_modelo_declara_el_mismo_indice():
    from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog

    idx = {i.name: i for i in TitulatecAuditLog.__table__.indexes}[_NOMBRE]
    assert idx.dialect_options["postgresql"]["ops"] == {"subject_label": "text_pattern_ops"}
    assert "process_id IS NULL" in str(idx.dialect_options["postgresql"]["where"])


def test_la_base_tiene_el_indice_con_opclass_y_predicado(db_session):
    fila = db_session.execute(text(
        "select indexdef from pg_indexes where indexname = :n"), {"n": _NOMBRE}).scalar()
    assert fila, "falta el índice en la base de la prueba"
    assert "text_pattern_ops" in fila and "process_id IS NULL" in fila
