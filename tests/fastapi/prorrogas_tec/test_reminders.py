from datetime import date, timedelta

import pytest

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment
from itcj2.apps.prorrogas_tec.services import notify
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.reminder_service import ReminderService
from itcj2.apps.prorrogas_tec.services.students_service import StudentsService

HOY = date(2091, 5, 1)


def _plan(con_plan, req, dias, pagos=()):
    return con_plan(req, [("1000.00", HOY + timedelta(days=dias))], pagos=pagos)


@pytest.mark.parametrize("dias, sale", [(5, True), (1, True), (0, True), (3, False), (-1, False)])
def test_sale_a_5_1_y_0_dias(db_session, aceptada, con_plan, avisos, dias, sale):
    _plan(con_plan, aceptada, dias)
    assert ReminderService.run(db_session, HOY) == {"enviados": int(sale), "fallidos": 0}


def test_dos_corridas_el_mismo_dia_no_repiten(db_session, aceptada, con_plan, avisos):  # Review Focus 3
    _plan(con_plan, aceptada, 5)
    ReminderService.run(db_session, HOY)
    ReminderService.run(db_session, HOY)
    assert len(avisos.calls) == 1


def test_cada_umbral_sale_una_vez(db_session, aceptada, con_plan, avisos):
    _plan(con_plan, aceptada, 5)
    for d in range(6):
        ReminderService.run(db_session, HOY + timedelta(days=d))
    assert len(avisos.calls) == 3


def test_pago_cubierto_no_recibe(db_session, aceptada, con_plan, avisos):
    _plan(con_plan, aceptada, 1, pagos=["1000.00"])
    assert ReminderService.run(db_session, HOY)["enviados"] == 0


def test_historica_sin_semestre_queda_fuera(db_session, make_historica, avisos):
    make_historica(parcialidades=(("1000.00", HOY),))
    assert ReminderService.run(db_session, HOY)["enviados"] == 0


def test_si_el_correo_falla_no_se_marca(db_session, aceptada, con_plan, monkeypatch):
    _plan(con_plan, aceptada, 0)
    monkeypatch.setattr(notify, "notify_student", lambda *a, **k: False)
    assert ReminderService.run(db_session, HOY) == {"enviados": 0, "fallidos": 1}
    assert db_session.query(ProrrogaInstallment).filter_by(request_id=aceptada.id).one().last_reminder_days is None


def test_el_boton_manual_excluye_historicas_sin_semestre(db_session, make_historica, secretaria):
    h = make_historica(parcialidades=(("1000.00", date(2091, 5, 1)),))
    h.email = "x@example.invalid"
    with pytest.raises(ServiceError) as e:
        StudentsService.remind(db_session, h.id, secretaria.id, now=HOY)
    assert e.value.code == "sin_semestre"
