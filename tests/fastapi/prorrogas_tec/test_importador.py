from datetime import date
from decimal import Decimal as D

import pytest
from click.testing import CliRunner

from itcj2.database import SessionLocal
from itcj2.apps.prorrogas_tec.importacion.importador import importar
from itcj2.apps.prorrogas_tec.importacion.limpio import SolicitudLimpia, escribir_limpio
from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment, ProrrogaPayment
from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest


def _sol(ref="H#2", control="99130001", carrera="Contador publico", semestre="enero – junio 2025"):
    return SolicitudLimpia(ref=ref, semestre=semestre, fecha_solicitud=date(2025, 1, 13), no_control=control,
                           nombre="Alumna Histórica", carrera=carrera,
                           parcialidades=[(1, date(2025, 2, 1), D("1000.00"), True), (2, date(2025, 3, 1), D("550.00"), False)])


def test_importa_con_recibos_solo_de_lo_pagado(db_session, make_program):
    make_program("Contador publico", "licenciatura")
    res = importar(db_session, [_sol()], dry_run=False)
    assert res["creadas"] == 1 and res["sin_semestre_core"] == 1 and res["sin_cuenta"] == 1
    req = db_session.query(ProrrogaRequest).filter_by(import_ref="H#2").one()
    assert (req.origin, req.status, req.total_amount, req.period_id, req.requested_terms) == \
        ("excel", "aceptada", D("1550.00"), None, None)
    assert req.created_at.date() == date(2025, 1, 13) and req.program_level == "licenciatura"
    assert db_session.query(ProrrogaInstallment).filter_by(request_id=req.id).count() == 2
    pagos = db_session.query(ProrrogaPayment).filter_by(request_id=req.id).all()
    assert [(p.origin, p.folio, p.paid_on, p.amount) for p in pagos] == [("excel", None, date(2025, 2, 1), D("1000.00"))]


def test_importar_dos_veces_no_duplica(db_session, make_program):  # Review Focus 1
    make_program("Contador publico", "licenciatura")
    importar(db_session, [_sol()], dry_run=False)
    res = importar(db_session, [_sol()], dry_run=False)
    assert res["creadas"] == 0 and res["ya_existian"] == 1
    assert db_session.query(ProrrogaRequest).filter_by(import_ref="H#2").count() == 1


def test_liga_semestre_y_cuenta(db_session, make_program, make_user, periodo):
    from itcj2.apps.prorrogas_tec.services.periods import period_label
    make_program("Contador publico", "licenciatura")
    u = make_user(control_number="99130002")
    importar(db_session, [_sol(ref="H#3", control="99130002", semestre=period_label(periodo))], dry_run=False)
    req = db_session.query(ProrrogaRequest).filter_by(import_ref="H#3").one()
    assert req.period_id == periodo.id and req.student_id == u.id


def test_ref_con_problema_no_se_importa_y_dry_run_no_escribe(db_session, make_program):  # Review Focus 2
    make_program("Contador publico", "licenciatura")
    res = importar(db_session, [_sol(ref="H#4", carrera="Carrera Fantasma"), _sol(ref="H#5")], dry_run=True)
    assert res["creadas"] == 1 and res["con_error"] == [("H#4", "carrera no existe en core")]
    assert db_session.query(ProrrogaRequest).filter(ProrrogaRequest.import_ref.in_(["H#4", "H#5"])).count() == 0


def test_ref_repetido_en_el_archivo(db_session, make_program):
    make_program("Contador publico", "licenciatura")
    res = importar(db_session, [_sol(), _sol()], dry_run=False)
    assert res["creadas"] == 1 and res["con_error"] == [("H#2", "ref repetido en el archivo")]


def test_excepcion_inesperada_no_deja_nada(db_session, make_program, monkeypatch):
    make_program("Contador publico", "licenciatura")
    from itcj2.apps.prorrogas_tec.importacion import importador
    orig = importador.ProrrogaInstallment
    n = {"i": 0}

    def _falla(**kw):
        n["i"] += 1
        if n["i"] > 2:  # primera solicitud (2 parcialidades) pasa; la segunda revienta
            raise RuntimeError("boom")
        return orig(**kw)

    monkeypatch.setattr(importador, "ProrrogaInstallment", _falla)
    with pytest.raises(RuntimeError):
        importar(db_session, [_sol(ref="H#6"), _sol(ref="H#7")], dry_run=False)
    assert db_session.query(ProrrogaRequest).filter(ProrrogaRequest.import_ref.in_(["H#6", "H#7"])).count() == 0


def test_cli_dry_run_no_escribe(libro, tmp_path):
    from itcj2.apps.prorrogas_tec.importacion.hojas import leer_libro
    from itcj2.cli.prorrogas import prorrogas_cli
    enc = ["No.", "FECHA", "No. De Control", "NOMBRE", "CARRERA", "ENERO", "IMPORTE", ""]
    ruta = libro({"Inscripción Enero - Junio 2026": [enc,
        [None, "12 de enero de 2026", 99120001, "Sintetica", "Contador Público", "16 de enero de 2026", 1000, 1]]})
    limpio = tmp_path / "limpio.xlsx"
    escribir_limpio(leer_libro(ruta), limpio)
    res = CliRunner().invoke(prorrogas_cli, ["import-excel", str(limpio), "--dry-run"])
    assert "SIMULACRO" in res.output and "Sintetica" not in res.output and "99120001" not in res.output, res.output
    with SessionLocal() as db:
        assert db.query(ProrrogaRequest).filter_by(import_ref="Inscripción Enero - Junio 2026#2").count() == 0
