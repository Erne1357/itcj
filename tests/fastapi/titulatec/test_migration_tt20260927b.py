"""Contrato de la migración `tt20260927b`: la ventana de la convocatoria pasa
de `Date` a `DateTime` NOT NULL (spec 2026-09-27 §B1, D9).

El harness arma el esquema con `create_all` (sin Alembic), así que la
migración no se "corre" aquí: se carga el módulo con `importlib` para probar
sus funciones puras (`_cohorts_without_close`, `_abort_message`) con un doble
de conexión, y se lee su fuente para fijar el ORDEN de `upgrade()` — el
aborto va antes de cualquier DDL. La base de pruebas ya tiene la columna NOT
NULL, así que no se inserta una convocatoria con cierre nulo.
"""
import importlib.util
import inspect
import re
from pathlib import Path

import itcj2

_MIGRACION = (Path(itcj2.__file__).resolve().parent.parent / "migrations" / "versions"
              / "tt20260927b_titulatec_cohort_window_datetime.py")


def _modulo():
    spec = importlib.util.spec_from_file_location("tt20260927b_mig", _MIGRACION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _ConnFalsa:
    """Registra el SQL de cada `execute` y devuelve filas fijas."""

    def __init__(self, filas):
        self.sql: list[str] = []
        self._filas = filas

    def execute(self, sql, *args, **kwargs):
        self.sql.append(str(sql))
        filas = self._filas

        class _Res:
            def fetchall(self_inner):
                return filas

        return _Res()


def test_revision_y_down_revision():
    mod = _modulo()
    assert mod.revision == "tt20260927b"
    assert mod.down_revision == "tt20260927a"


def test_el_mensaje_de_aborto_nombra_cada_convocatoria_y_dice_donde_arreglarla():
    msg = _modulo()._abort_message([(7, "Conv A"), (9, "Conv B")])

    for pedazo in ("id=7", "Conv A", "id=9", "Conv B"):
        assert pedazo in msg, msg
    assert "Ventana de inscripción" in msg
    assert "vuelve a correr la migración" in msg


def test_cohorts_without_close_devuelve_las_filas_y_filtra_cierre_nulo():
    conn = _ConnFalsa([(7, "Conv A")])

    filas = _modulo()._cohorts_without_close(conn)

    assert filas == [(7, "Conv A")]
    assert len(conn.sql) == 1
    sql = " ".join(conn.sql[0].split())
    assert "titulatec_cohorts" in sql
    assert "closes_at IS NULL" in sql


def test_upgrade_aborta_antes_de_cualquier_ddl_y_convierte_el_cierre_a_23_59_59():
    src = inspect.getsource(_modulo().upgrade)

    chequeo = src.find("_cohorts_without_close(")
    assert chequeo != -1, "upgrade() no consulta los cierres vacíos"
    ddl = [i for i in (src.find("alter_column"), src.find("ALTER TABLE"),
                       src.find("op.execute")) if i != -1]
    assert ddl, "upgrade() no altera nada"
    assert chequeo < min(ddl), "el aborto tiene que ir ANTES de tocar la tabla"
    assert "RuntimeError" in src
    assert "interval '23:59:59'" in src
    assert "created_at::date" in src, "apertura vacía = fecha de creación 00:00"
    # Por llamada: `nullable=False` dentro del MISMO `alter_column` de cada
    # columna (sin cruzar a la siguiente llamada). `\b` deja fuera
    # `existing_nullable=`.
    for columna in ("opens_at", "closes_at"):
        assert re.search(
            rf'alter_column\(\s*_COHORTS,\s*"{columna}",'
            rf'(?:(?!alter_column).)*?\bnullable=False', src, re.S,
        ), f"{columna} no queda NOT NULL"


def test_downgrade_vuelve_a_date_y_nullable():
    src = inspect.getsource(_modulo().downgrade)

    assert "nullable=True" in src
    assert "::date" in src
    assert "opens_at" in src and "closes_at" in src


def test_el_modelo_declara_datetime_not_null():
    from sqlalchemy import DateTime

    from itcj2.apps.titulatec.models import Cohort

    for nombre in ("opens_at", "closes_at"):
        col = Cohort.__table__.columns[nombre]
        assert isinstance(col.type, DateTime), nombre
        assert col.nullable is False, nombre
