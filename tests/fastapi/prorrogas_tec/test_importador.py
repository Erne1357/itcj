from datetime import date, datetime
from decimal import Decimal as D

import pytest
from click.testing import CliRunner

from itcj2.apps.prorrogas_tec.importacion.importador import importar
from itcj2.apps.prorrogas_tec.importacion.limpio import SolicitudLimpia, escribir_limpio
from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment, ProrrogaPayment
from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest


def _sol(ref="H#2", control="99130001", carrera="Contador publico", semestre="enero – junio 2088"):
    return SolicitudLimpia(ref=ref, semestre=semestre, fecha_solicitud=date(2025, 1, 13), no_control=control,
                           nombre="Alumna Histórica", carrera=carrera,
                           parcialidades=[(1, date(2025, 2, 1), D("1000.00"), True), (2, date(2025, 3, 1), D("550.00"), False)])


def test_importa_con_recibos_solo_de_lo_pagado(db_session, make_program):
    make_program("Contador publico", "licenciatura")
    res = importar(db_session, [_sol()], dry_run=False)
    assert res["creadas"] == 1 and res["sin_semestre_core"] == 1 and res["sin_cuenta"] == 1
    assert res["por_semestre"] == {"enero – junio 2088": {"creadas": 1, "ligado": False}}  # M1
    req = db_session.query(ProrrogaRequest).filter_by(import_ref="H#2").one()
    assert (req.origin, req.status, req.total_amount, req.period_id, req.requested_terms) == \
        ("excel", "aceptada", D("1550.00"), None, None)
    assert req.created_at == req.updated_at == datetime(2025, 1, 13, 0, 0) and req.program_level == "licenciatura"
    assert req.reason is None and req.email is None
    inst = db_session.query(ProrrogaInstallment).filter_by(request_id=req.id).order_by(ProrrogaInstallment.number).all()
    assert [(i.number, i.amount, i.due_date) for i in inst] == [
        (1, D("1000.00"), date(2025, 2, 1)), (2, D("550.00"), date(2025, 3, 1))]
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
    res = importar(db_session, [_sol(ref="H#3", control="99130002", semestre=period_label(periodo))], dry_run=False)
    req = db_session.query(ProrrogaRequest).filter_by(import_ref="H#3").one()
    assert req.period_id == periodo.id and req.student_id == u.id
    assert res["por_semestre"] == {period_label(periodo): {"creadas": 1, "ligado": True}}  # M1


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


def _limpio(libro, tmp_path, monkeypatch):
    from itcj2.apps.prorrogas_tec.importacion import hojas
    from itcj2.apps.prorrogas_tec.importacion.hojas import leer_libro
    # hoja sintética: su ref (Prueba 2088#2) no puede coincidir con ningún renglón del archivo real
    monkeypatch.setitem(hojas.HOJAS, "Prueba 2088", ("enero – junio 2088", "mensual"))
    enc = ["No.", "FECHA", "No. De Control", "NOMBRE", "CARRERA", "ENERO", "IMPORTE", ""]
    ruta = libro({"Prueba 2088": [enc,
        [None, "12 de enero de 2088", 99120001, "Sintetica", "Contador publico", "16 de enero de 2088", 1000, 1]]})
    limpio = tmp_path / "limpio.xlsx"
    escribir_limpio(leer_libro(ruta), limpio)
    return limpio


def test_cli_dry_run_no_escribe(libro, tmp_path, patched_session_local, make_program, monkeypatch):
    from itcj2.cli.prorrogas import prorrogas_cli
    make_program("Contador publico", "licenciatura")
    res = CliRunner().invoke(prorrogas_cli, ["import-excel", str(_limpio(libro, tmp_path, monkeypatch)), "--dry-run"])
    assert res.exit_code == 0 and "SIMULACRO" in res.output and "Creadas: 1" in res.output, res.output
    assert "Sintetica" not in res.output and "99120001" not in res.output
    assert "  enero – junio 2088: 1 creadas, sin semestre en core" in res.output  # M1
    assert patched_session_local.query(ProrrogaRequest).filter(
        ProrrogaRequest.import_ref == "Prueba 2088#2").count() == 0


def test_cli_error_de_base_no_filtra_datos(libro, tmp_path, patched_session_local, make_program, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from itcj2.cli.prorrogas import prorrogas_cli

    def _revienta(*a, **k):
        raise IntegrityError("x", {"student_name": "SECRETO"}, None)

    monkeypatch.setattr("itcj2.apps.prorrogas_tec.importacion.importador.importar", _revienta)
    res = CliRunner().invoke(prorrogas_cli, ["import-excel", str(_limpio(libro, tmp_path, monkeypatch))])
    assert res.exit_code != 0 and "SECRETO" not in res.output and "IntegrityError" in res.output


def test_mas_de_6_y_vacias_se_saltan(db_session, make_program):
    make_program("Contador publico", "licenciatura")
    siete = _sol(ref="H#8")
    siete.parcialidades = [(i, date(2088, 2, i), D("10.00"), False) for i in range(1, 8)]
    vacia = _sol(ref="H#9")
    vacia.parcialidades = []
    res = importar(db_session, [siete, vacia, _sol(ref="H#10")], dry_run=False)
    assert res["creadas"] == 1
    assert res["con_error"] == [("H#8", "más de 6 parcialidades"), ("H#9", "parcialidades vacías")]
