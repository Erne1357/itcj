"""CLI `titulatec import-survey-xlsx` (Tarea 2, spec `2026-10-05-titulatec-
import-encuesta-xlsx-design.md` R1/§4.3): lee el `.xlsx` de Forms y delega TODO
a `SurveyImportService` (probado en `test_survey_import_service.py`). Aquí solo
la plomería: impresión de los 7 botes, `--dry-run`, `--hoja` inexistente y
encabezado desconocido. Archivo SINTÉTICO en `tmp_path`.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from itcj2.cli.titulatec import import_survey_xlsx_command
from tests.fastapi.titulatec._survey_xlsx import (
    HEADERS, build_xlsx, fila, make_egresados_form,
)

NOTIFY = "itcj2.apps.titulatec.services.notify.notify_student"
HOY_FIJO = datetime(2026, 10, 1, 10, 0, 0)


@pytest.fixture(autouse=True)
def reloj(monkeypatch):
    for modulo in ("itcj2.apps.titulatec.services.library_clearance_service",
                  "itcj2.apps.titulatec.services.survey_review_service",
                  "itcj2.apps.titulatec.services.prior_clearance_service"):
        monkeypatch.setattr(f"{modulo}.db_now", lambda: HOY_FIJO)


@pytest.fixture()
def form(make_survey_form):
    return make_egresados_form(make_survey_form)


def _archivo(tmp_path, filas, **kw):
    ruta = tmp_path / "egresados.xlsx"
    ruta.write_bytes(build_xlsx(filas, **kw))
    return ruta


def _invoke(args):
    with patch(NOTIFY):
        return CliRunner().invoke(import_survey_xlsx_command, args)


def _respuestas(db, form):
    from itcj2.apps.titulatec.models import SurveyResponse
    return db.query(SurveyResponse).filter_by(form_id=form.id).count()


def test_imprime_los_botes(tmp_path, db_session, patched_session_local, form):
    ruta = _archivo(tmp_path, [fila(1, control="99600201"), fila(2, control="")])
    res = _invoke([str(ruta)])
    assert res.exit_code == 0, res.output
    for etiqueta in ("Guardadas y liberadas: 0", "Guardadas, liberación diferida: 1",
                     "Guardadas (ya liberadas): 0", "Guardadas (conflicto): 0",
                     "Guardadas sin liberar: 1", "Duplicadas (no guardadas): 0",
                     "Ya importadas: 0", "Inválidas (no guardadas): 0"):
        assert etiqueta in res.output
    assert "99600201" in res.output
    assert _respuestas(db_session, form) == 2


def test_dry_run_no_escribe(tmp_path, db_session, patched_session_local, form):
    ruta = _archivo(tmp_path, [fila(1, control="99600202")])
    res = _invoke([str(ruta), "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "Guardadas, liberación diferida: 1" in res.output
    assert "no se escribió nada" in res.output
    assert "ocultas con valor real (guardadas; informativo): 0" in res.output
    assert "con valor original (raw): " in res.output
    assert _respuestas(db_session, form) == 0


def test_hoja_inexistente_lista_las_hojas(tmp_path, db_session, patched_session_local,
                                          form):
    ruta = _archivo(tmp_path, [fila(1)])
    res = _invoke([str(ruta), "--hoja", "Hoja9"])
    assert res.exit_code != 0
    assert "Sheet1" in res.output and "carta de liberacion" in res.output


def test_archivo_que_no_es_xlsx_da_error_claro(tmp_path, db_session,
                                               patched_session_local, form):
    ruta = tmp_path / "egresados.xlsx"
    ruta.write_bytes(b"Id,Nombre\n1,X\n")
    res = _invoke([str(ruta)])
    assert res.exit_code != 0
    assert "no es un libro .xlsx" in res.output
    assert "Traceback" not in res.output


def test_integrity_error_da_error_claro(tmp_path, db_session, patched_session_local,
                                        form):
    from sqlalchemy.exc import IntegrityError

    ruta = _archivo(tmp_path, [fila(1, control="99600204")])
    with patch("itcj2.apps.titulatec.services.survey_import_service."
               "SurveyImportService.import_rows",
               side_effect=IntegrityError("INSERT", {}, Exception("dup"))):
        res = _invoke([str(ruta)])
    assert res.exit_code != 0
    assert "Ya importadas" in res.output
    assert "Traceback" not in res.output


def test_encabezado_desconocido_aborta_sin_escribir(tmp_path, db_session,
                                                    patched_session_local, form):
    headers = list(HEADERS)
    headers[30] = "Columna nueva de Forms"
    ruta = _archivo(tmp_path, [fila(1, control="99600203")], headers=headers)
    res = _invoke([str(ruta)])
    assert res.exit_code != 0
    assert "Columna nueva de Forms" in res.output
    assert _respuestas(db_session, form) == 0
