"""`OfficialAverageService` (spec 2026-10-13-titulatec-promedios-design.md §4.1, §5):
promedio oficial por número de control, guardado aunque no haya proceso y aplicado
a `final_average` cuando lo hay (o cuando el proceso se crea en `import_rows`)."""
from __future__ import annotations

from decimal import Decimal

import pytest

import itcj2.models  # noqa: F401
from itcj2.apps.titulatec.services.import_service import ImportService
from itcj2.apps.titulatec.services.official_average_service import OfficialAverageService as Svc

pytestmark = pytest.mark.usefixtures("audit_mark")

D = Decimal
ACCION = "average.final_set"  # `process.*` es de la escucha: el contrato lo prohíbe en AUDIT_ACTIONS


@pytest.mark.parametrize("raw,esperado", [
    ("85", D("85.00")), ("85.5", D("85.50")), ("85,5", D("85.50")),
    ("  92.25 ", D("92.25")), ("85.125", D("85.13")), ("85.124", D("85.12")),
    ("85,125", D("85.13")), ("100", D("100.00")),
    ("", None), ("   ", None), (None, None), ("abc", None), ("85.5.1", None),
    ("1,000.5", None), ("1.000,5", None), ("85,5,1", None), ("-80", None),
    ("NaN", None), ("inf", None), ("8 5", None),
])
def test_parse_average(raw, esperado):
    assert Svc.parse_average(raw) == esperado


@pytest.mark.parametrize("valor,ok", [
    (D("69.99"), False), (D("70"), True), (D("100"), True),
    (D("100.01"), False), (D("9.5"), False), (D("85.5"), True),
])
def test_in_range(valor, ok):
    assert Svc.in_range(valor) is ok


def _fila(db, control):
    from itcj2.apps.titulatec.models import OfficialAverage
    return db.get(OfficialAverage, control)


def _auditadas(db):
    from tests.fastapi.titulatec.conftest import audit_query
    db.flush()
    return audit_query(db).filter_by(action=ACCION).all()


def test_upsert_created_updated_same(db_session, make_user):
    actor = make_user()
    assert Svc.upsert(db_session, "99700001", D("85.5"), actor_id=actor.id) == "created"
    assert _fila(db_session, "99700001").average == D("85.50")
    assert _fila(db_session, "99700001").loaded_by_id == actor.id
    assert Svc.upsert(db_session, "99700001", D("85.50"), actor_id=actor.id) == "same"
    assert Svc.upsert(db_session, "99700001", D("90"), actor_id=actor.id) == "updated"
    assert _fila(db_session, "99700001").average == D("90.00")


def test_upsert_normaliza_el_control(db_session):
    assert Svc.upsert(db_session, " l99700002 ", D("80"), actor_id=None) == "created"
    assert _fila(db_session, "99700002") is not None


def test_apply_to_processes_escribe_y_audita(db_session, make_student, make_process, make_cohort):
    alumno = make_student(control_number="99700003")
    p1 = make_process(alumno, cohort=make_cohort())
    p2 = make_process(alumno, cohort=make_cohort(), status="cancelled")
    otro = make_process(make_student(control_number="99700004"), cohort=make_cohort())

    assert Svc.apply_to_processes(db_session, "99700003", D("88.5")) == 1
    db_session.refresh(p1)
    db_session.refresh(p2)
    db_session.refresh(otro)
    assert p1.final_average == D("88.50")
    assert p2.final_average is None  # cancelado: no se toca
    assert otro.final_average is None

    (fila,) = _auditadas(db_session)
    assert fila.process_id == p1.id
    assert fila.before == {"final_average": None}
    assert fila.after == {"final_average": "88.50"}


def test_apply_to_processes_mismo_valor_no_cuenta_ni_audita(db_session, make_student,
                                                            make_process, make_cohort):
    proc = make_process(make_student(control_number="99700005"), cohort=make_cohort())
    proc.final_average = D("80.00")
    db_session.flush()
    assert Svc.apply_to_processes(db_session, "99700005", D("80")) == 0
    assert _auditadas(db_session) == []
    # recarga con otro valor: sí cambia
    assert Svc.apply_to_processes(db_session, "99700005", D("81")) == 1
    db_session.refresh(proc)
    assert proc.final_average == D("81.00")
    (fila,) = _auditadas(db_session)
    assert fila.before == {"final_average": "80.00"}


def test_apply_to_processes_sin_alumno_devuelve_cero(db_session):
    assert Svc.apply_to_processes(db_session, "99799999", D("80")) == 0


def test_apply_pending_llena_solo_si_esta_vacio(db_session, make_student, make_process, make_cohort):
    proc = make_process(make_student(control_number="99700006"), cohort=make_cohort())
    assert Svc.apply_pending(db_session, proc, "99700006") is False  # sin fila guardada
    Svc.upsert(db_session, "99700006", D("91"), actor_id=None)
    assert Svc.apply_pending(db_session, proc, "99700006") is True
    assert proc.final_average == D("91.00")
    # ya tenía valor: no se pisa
    Svc.upsert(db_session, "99700006", D("75"), actor_id=None)
    assert Svc.apply_pending(db_session, proc, "99700006") is False
    assert proc.final_average == D("91.00")


def test_apply_pending_audita_el_origen(db_session, make_student, make_process, make_cohort):
    proc = make_process(make_student(control_number="99700007"), cohort=make_cohort())
    Svc.upsert(db_session, "99700007", D("77"), actor_id=None)
    Svc.apply_pending(db_session, proc, "99700007")
    (fila,) = _auditadas(db_session)
    assert fila.process_id == proc.id
    assert fila.before == {"final_average": None}


def _row(control):
    return {"control_number": control, "full_name": "ALUMNA INVENTADA", "email": None,
            "program_id": None, "modality_id": None}


def _proceso_de(db, control):
    from itcj2.apps.titulatec.models import TitulationProcess
    return (db.query(TitulationProcess).join(TitulationProcess.student)
            .filter_by(control_number=control).one())


def test_import_rows_aplica_el_promedio_guardado(db_session, titulatec_app, make_cohort):
    Svc.upsert(db_session, "99700008", D("93.5"), actor_id=None)
    ImportService.import_rows(db_session, make_cohort(), [_row("99700008")])
    assert _proceso_de(db_session, "99700008").final_average == D("93.50")


def test_import_rows_sin_promedio_guardado_lo_deja_nulo(db_session, titulatec_app, make_cohort):
    ImportService.import_rows(db_session, make_cohort(), [_row("99700009")])
    assert _proceso_de(db_session, "99700009").final_average is None
