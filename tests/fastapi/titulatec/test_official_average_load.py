"""`OfficialAverageService.load_rows` (spec 2026-10-13-titulatec-promedios-design.md
§4.2, §5): carga en lote por buckets. La CLI (`test_cli_promedios.py`) solo pone la
plomería encima."""
from __future__ import annotations

from decimal import Decimal

import pytest

import itcj2.models  # noqa: F401
from itcj2.apps.titulatec.services.official_average_service import OfficialAverageService as Svc

pytestmark = pytest.mark.usefixtures("audit_mark")

D = Decimal
BUCKETS = ("applied", "stored", "updated", "same", "no_request", "out_of_range",
           "invalid", "duplicate")


def _req(db, cohort, *, control, status="pending_review"):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control, first_name="EGRESADA",
        last_name="DELLOTE", middle_name=None, program_id=None,
        program_text="Ingenieria Ficticia", phone="6561234567",
        contact_email="lote@example.invalid", has_efirma=True, kind="unknown",
        status=status, verify_send_count=0)
    db.add(row)
    db.flush()
    return row


def _fila(db, control):
    from itcj2.apps.titulatec.models import OfficialAverage
    return db.get(OfficialAverage, control)


def _carga(db, rows, actor, dry_run=False):
    return Svc.load_rows(db, rows, actor_id=actor.id, dry_run=dry_run)


def _controles(res, bucket):
    return [c for c, _ in res[bucket]]


@pytest.fixture()
def actor(make_user):
    return make_user(username="tt_prom_actor")


def test_devuelve_siempre_las_ocho_llaves(db_session, actor):
    res = _carga(db_session, [], actor)
    assert tuple(res) == BUCKETS and all(v == [] for v in res.values())


def test_applied_escribe_en_el_proceso_y_en_la_tabla(
        db_session, actor, make_student, make_process, make_cohort):
    proc = make_process(make_student(control_number="99710001"), cohort=make_cohort())

    res = _carga(db_session, [("99710001", "85,5")], actor)

    assert _controles(res, "applied") == ["99710001"]
    db_session.refresh(proc)
    assert proc.final_average == D("85.50")
    assert _fila(db_session, "99710001").average == D("85.50")
    assert _fila(db_session, "99710001").loaded_by_id == actor.id


def test_stored_sin_proceso_con_solicitud(db_session, actor, make_cohort):
    _req(db_session, make_cohort(), control="99710002")

    res = _carga(db_session, [("L99710002", "90")], actor)

    assert _controles(res, "stored") == ["99710002"]
    assert _fila(db_session, "99710002").average == D("90.00")


def test_stored_solicitud_rechazada_lo_dice_el_motivo(db_session, actor, make_cohort):
    _req(db_session, make_cohort(), control="99710003", status="rejected")

    res = _carga(db_session, [("99710003", "88")], actor)

    assert _controles(res, "stored") == ["99710003"]
    assert "rechazada" in res["stored"][0][1].lower()
    assert _fila(db_session, "99710003") is not None


def test_proceso_cancelado_cuenta_como_sin_proceso(
        db_session, actor, make_student, make_process, make_cohort):
    proc = make_process(make_student(control_number="99710004"), cohort=make_cohort(),
                        status="cancelled")
    _req(db_session, make_cohort(), control="99710004")

    res = _carga(db_session, [("99710004", "80")], actor)

    assert _controles(res, "stored") == ["99710004"]
    db_session.refresh(proc)
    assert proc.final_average is None


def test_no_request_no_guarda_nada(db_session, actor):
    res = _carga(db_session, [("99710005", "80")], actor)

    assert _controles(res, "no_request") == ["99710005"]
    assert _fila(db_session, "99710005") is None


def test_updated_reporta_antes_y_despues(db_session, actor, make_cohort):
    _req(db_session, make_cohort(), control="99710006")
    _carga(db_session, [("99710006", "80")], actor)

    res = _carga(db_session, [("99710006", "90.5")], actor)

    assert _controles(res, "updated") == ["99710006"]
    assert "80.00" in res["updated"][0][1] and "90.50" in res["updated"][0][1]
    assert _fila(db_session, "99710006").average == D("90.50")


def test_updated_con_proceso_tambien_actualiza_el_proceso(
        db_session, actor, make_student, make_process, make_cohort):
    proc = make_process(make_student(control_number="99710007"), cohort=make_cohort())
    _carga(db_session, [("99710007", "80")], actor)

    res = _carga(db_session, [("99710007", "81")], actor)

    assert _controles(res, "updated") == ["99710007"]
    db_session.refresh(proc)
    assert proc.final_average == D("81.00")


def test_same_no_cambia_nada(db_session, actor, make_cohort):
    _req(db_session, make_cohort(), control="99710008")
    _carga(db_session, [("99710008", "80")], actor)

    res = _carga(db_session, [("99710008", "80.00")], actor)

    assert _controles(res, "same") == ["99710008"]


def test_proceso_sin_valor_se_aplica_aunque_la_tabla_ya_sea_igual(
        db_session, actor, make_student, make_process, make_cohort):
    Svc.upsert(db_session, "99710009", D("80"), actor_id=None)
    proc = make_process(make_student(control_number="99710009"), cohort=make_cohort())
    proc.final_average = None
    db_session.flush()

    res = _carga(db_session, [("99710009", "80")], actor)

    assert _controles(res, "applied") == ["99710009"]
    db_session.refresh(proc)
    assert proc.final_average == D("80.00")


@pytest.mark.parametrize("valor", ["69.99", "100.01", "9.5", "0"])
def test_out_of_range(db_session, actor, make_cohort, valor):
    _req(db_session, make_cohort(), control="99710010")

    res = _carga(db_session, [("99710010", valor)], actor)

    assert _controles(res, "out_of_range") == ["99710010"]
    assert _fila(db_session, "99710010") is None


@pytest.mark.parametrize("valor", ["", "abc", "85 5", "9" * 30, "-80", "NaN"])
def test_invalid_promedio(db_session, actor, make_cohort, valor):
    _req(db_session, make_cohort(), control="99710011")

    res = _carga(db_session, [("99710011", valor)], actor)

    assert _controles(res, "invalid") == ["99710011"]
    assert _fila(db_session, "99710011") is None


def test_invalid_control_vacio_o_malformado(db_session, actor):
    res = _carga(db_session, [("", "85"), ("ab cd!", "85")], actor)
    assert len(res["invalid"]) == 2


def test_duplicate_descarta_todas_las_apariciones(db_session, actor, make_cohort):
    _req(db_session, make_cohort(), control="99710012")

    res = _carga(db_session, [("99710012", "80"), ("L99710012", "90"),
                              ("99710012", "95")], actor)

    assert _controles(res, "duplicate") == ["99710012"]   # una sola línea de reporte
    assert _fila(db_session, "99710012") is None


def test_dry_run_clasifica_igual_y_no_escribe(
        db_session, actor, make_student, make_process, make_cohort):
    proc = make_process(make_student(control_number="99710013"), cohort=make_cohort())
    _req(db_session, make_cohort(), control="99710014")
    rows = [("99710013", "85"), ("99710014", "86"), ("99710015", "87")]

    seco = _carga(db_session, rows, actor, dry_run=True)
    assert _fila(db_session, "99710013") is None and _fila(db_session, "99710014") is None
    db_session.refresh(proc)
    assert proc.final_average is None

    real = _carga(db_session, rows, actor)
    assert seco == real


def test_una_fila_que_truena_va_a_invalid_y_el_lote_sigue(
        db_session, actor, make_cohort, monkeypatch):
    _req(db_session, make_cohort(), control="99710016")
    _req(db_session, make_cohort(), control="99710017")
    original = Svc.upsert

    def _truena(db, control, average, **kw):
        if control == "99710016":
            raise RuntimeError("boom 99710016")
        return original(db, control, average, **kw)

    monkeypatch.setattr(Svc, "upsert", staticmethod(_truena))

    res = _carga(db_session, [("99710016", "80"), ("99710017", "81")], actor)

    assert _controles(res, "invalid") == ["99710016"]
    assert "RuntimeError" in res["invalid"][0][1]
    assert "boom" not in res["invalid"][0][1]
    assert _controles(res, "stored") == ["99710017"]
    assert _fila(db_session, "99710016") is None
    assert _fila(db_session, "99710017") is not None


def test_usuario_guardado_con_L_se_clasifica_y_se_escribe_igual(
        db_session, actor, make_student, make_process, make_cohort):
    """R13: el bucket `applied` solo vale si el proceso de verdad recibe el valor."""
    proc = make_process(make_student(control_number="L99710030"), cohort=make_cohort())

    res = _carga(db_session, [("99710030", "84")], actor)

    assert _controles(res, "applied") == ["99710030"]
    db_session.refresh(proc)
    assert proc.final_average == D("84.00")
