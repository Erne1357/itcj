"""CLI `titulatec import-prior-clearances` (D9, spec `2026-10-01-titulatec-
biblioteca-caja-design.md` §4.12): carga por archivo las constancias previas
del semestre anterior -encuesta (`--tipo encuesta`) o no adeudo de biblioteca
(`--tipo biblioteca`)-, delegando TODA la lógica a `PriorClearanceService.
import_rows` (ya probado contra Postgres real en
`test_prior_clearance_service.py`). Aquí solo se cubre el PLOMERÍA de la CLI:
lectura del CSV (BOM/`;`/`,`, igual que `ImportService.parse`), autodetección
de la columna de control, resolución de la fecha (columna o `--fecha` fija),
`--dry-run` y la impresión de los 6 botes.

`CliRunner` + `patched_session_local` (mismo patrón que `test_cli_biblioteca_
caja.py`): el comando abre su propia `SessionLocal()`, así que la prueba la
redirige a `db_session` (la transacción de la prueba, con rollback al final).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from itcj2.cli.titulatec import import_prior_clearances_command

NOTIFY = "itcj2.apps.titulatec.services.notify.notify_student"


def _csv(tmp_path, nombre, texto, encoding="utf-8"):
    ruta = tmp_path / nombre
    ruta.write_bytes(texto.encode(encoding))
    return ruta


@pytest.fixture()
def proceso(db_session, make_student, make_process, make_cohort):
    """Copia local de la fábrica de `test_prior_clearance_service.py`:
    convocatoria + egresado + proceso en fase 1."""
    def _make(*, control_number=None, process_status="active", current_phase=1,
              library_clearance=None, cohort=None):
        cohort = cohort or make_cohort()
        student = make_student(control_number=control_number)
        return make_process(student, cohort=cohort, current_phase=current_phase,
                            status=process_status, library_clearance=library_clearance)
    return _make


@pytest.fixture(autouse=True)
def reloj(monkeypatch):
    """Mismo reloj fijo que `test_prior_clearance_service.py`, en los tres
    módulos que lo usan para la vigencia D9."""
    from datetime import datetime
    hoy_fijo = datetime(2026, 10, 1, 10, 0, 0)
    for modulo in ("itcj2.apps.titulatec.services.library_clearance_service",
                  "itcj2.apps.titulatec.services.survey_review_service",
                  "itcj2.apps.titulatec.services.prior_clearance_service"):
        monkeypatch.setattr(f"{modulo}.db_now", lambda: hoy_fijo)


def _invoke(args, db_session, patched_session_local):
    with patch(NOTIFY):
        return CliRunner().invoke(import_prior_clearances_command, args)


# ---------------------------------------------------------------------------
# Lectura del archivo: delimitador, BOM, columnas
# ---------------------------------------------------------------------------
def test_coma_autodetecta_la_columna_de_control(tmp_path, db_session,
                                                patched_session_local, proceso):
    proceso(control_number="99800001")
    archivo = _csv(tmp_path, "previas.csv",
                   "Numero de control,Nombre\n99800001,ALUMNO UNO\n")

    res = _invoke([str(archivo), "--tipo", "encuesta", "--fecha", "2026-09-01"],
                  db_session, patched_session_local)

    assert res.exit_code == 0, res.output
    assert "Aplicadas: 1" in res.output
    assert "99800001" in res.output


def test_punto_y_coma_con_bom(tmp_path, db_session, patched_session_local, proceso):
    proceso(control_number="99800002")
    texto = "control;fecha\n99800002;2026-09-01\n"
    archivo = tmp_path / "previas.csv"
    archivo.write_bytes(b"\xef\xbb\xbf" + texto.encode("utf-8"))

    res = _invoke([str(archivo), "--tipo", "encuesta", "--columna-fecha", "fecha"],
                  db_session, patched_session_local)

    assert res.exit_code == 0, res.output
    assert "Aplicadas: 1" in res.output


def test_columna_control_explicita(tmp_path, db_session, patched_session_local, proceso):
    proceso(control_number="99800003")
    archivo = _csv(tmp_path, "previas.csv", "matricula\n99800003\n")

    res = _invoke([str(archivo), "--tipo", "biblioteca", "--fecha", "2026-09-01",
                  "--columna-control", "matricula"],
                  db_session, patched_session_local)

    assert res.exit_code == 0, res.output
    assert "Aplicadas: 1" in res.output


def test_sin_fecha_ni_columna_falla_claro(tmp_path, db_session, patched_session_local):
    archivo = _csv(tmp_path, "previas.csv", "control\n99800004\n")

    res = _invoke([str(archivo), "--tipo", "encuesta"], db_session, patched_session_local)

    assert res.exit_code != 0
    assert "fecha" in res.output.lower()


def test_archivo_inexistente(db_session, patched_session_local):
    res = _invoke(["no-existe.csv", "--tipo", "encuesta", "--fecha", "2026-09-01"],
                  db_session, patched_session_local)
    assert res.exit_code != 0


def test_tipo_invalido_lo_rechaza_click(tmp_path, db_session, patched_session_local):
    archivo = _csv(tmp_path, "previas.csv", "control\n99800005\n")
    res = _invoke([str(archivo), "--tipo", "lo-que-sea", "--fecha", "2026-09-01"],
                  db_session, patched_session_local)
    assert res.exit_code != 0


# ---------------------------------------------------------------------------
# Los 6 botes se imprimen (biblioteca, para no repetir el escenario de
# encuesta de arriba) y dry-run no escribe nada
# ---------------------------------------------------------------------------
def test_dry_run_no_escribe_nada_y_lo_anuncia(tmp_path, db_session,
                                              patched_session_local, proceso):
    from itcj2.apps.titulatec.models import PriorClearance

    proceso(control_number="99800010", library_clearance="pending")
    antes = db_session.query(PriorClearance).count()
    archivo = _csv(tmp_path, "previas.csv",
                   "control,fecha\n99800010,2026-09-01\n99800011,2026-09-01\n")

    res = _invoke([str(archivo), "--tipo", "biblioteca", "--columna-fecha", "fecha",
                  "--dry-run"], db_session, patched_session_local)

    assert res.exit_code == 0, res.output
    assert "[dry-run]" in res.output
    assert "no se escribió nada" in res.output
    assert "Aplicadas: 1" in res.output
    assert "Registradas para después: 1" in res.output
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert db_session.query(PriorClearance).count() == antes


def test_imprime_los_seis_botes_con_filas_de_cada_uno(
        tmp_path, db_session, patched_session_local, proceso, make_survey_review):
    proc_aplica = proceso(control_number="99800020")
    proc_liberado = proceso(control_number="99800021")
    make_survey_review(proc_liberado, status="approved")
    proc_conflicto = proceso(control_number="99800022")
    make_survey_review(proc_conflicto, status="in_review")

    filas = "\n".join([
        "control,fecha",
        "99800020,2026-09-01",     # aplica
        "99800023,2026-09-01",     # diferida (sin proceso)
        "99800021,2026-09-01",     # ya liberada
        "99800022,2026-09-01",     # conflicto
        "99800024,2024-01-01",     # vencida (> 365 días antes del reloj fijo)
        "bad,2026-09-01",          # control inválido
    ])
    archivo = _csv(tmp_path, "previas.csv", filas)

    res = _invoke([str(archivo), "--tipo", "encuesta", "--columna-fecha", "fecha"],
                  db_session, patched_session_local)

    assert res.exit_code == 0, res.output
    assert "Aplicadas: 1" in res.output
    assert "Registradas para después: 1" in res.output
    assert "Ya liberadas: 1" in res.output
    assert "Conflictos: 1" in res.output
    assert "Vencidas: 1" in res.output
    assert "Inválidas: 1" in res.output
    assert "99800020" in res.output and "99800023" in res.output
