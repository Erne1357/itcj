from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy.exc import IntegrityError

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment, ProrrogaPayment
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.payment_service import PaymentService
from itcj2.apps.prorrogas_tec.services.plan_service import PlanService
from itcj2.apps.prorrogas_tec.services.students_service import StudentsService


def test_excel_permite_hasta_seis_parcialidades(db_session, make_historica):
    req = make_historica(parcialidades=[("100.00", date(2025, 1, i + 1)) for i in range(6)])
    assert db_session.query(ProrrogaInstallment).filter_by(request_id=req.id).count() == 6
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(ProrrogaInstallment(request_id=req.id, number=7, amount=D("1"), due_date=date(2025, 7, 1)))
            db_session.flush()


def test_historica_sin_semestre_es_de_solo_lectura(db_session, make_historica, secretaria):  # Review Focus 4
    req = make_historica(pagadas=(0,))
    e = StudentsService.expediente(db_session, req.id, date(2026, 11, 1))
    assert e["plan"]["puede_replantear"] is False and e["plan"]["fecha_limite"] is None
    assert e["cuenta"]["situacion"] == "liquidada" and e["solo_lectura"] is True
    with pytest.raises(ServiceError) as err:
        PlanService.confirm(db_session, req.id, secretaria.id, total=D("1000"),
                            parcialidades=[(D("1000"), date(2026, 12, 1))], now=date(2026, 11, 1))
    assert err.value.code == "sin_semestre" and err.value.status == 409


def test_api_expediente_historica_no_da_500(client_as, secretaria, make_historica):
    req = make_historica()
    assert client_as(secretaria).get(f"/api/prorrogas/v2/estudiantes/{req.id}").status_code == 200


def test_historica_sin_semestre_no_acepta_recibos(db_session, make_historica, periodo, secretaria):
    req = make_historica()
    hoy = date(2026, 11, 1)
    assert StudentsService.expediente(db_session, make_historica(periodo=periodo).id, hoy)["solo_lectura"] is False
    with pytest.raises(ServiceError) as err:
        PaymentService.record(db_session, req.id, secretaria.id, folio="C-H1", paid_on=date(2026, 10, 1),
                              amount=D("100"), now=hoy)
    assert (err.value.code, err.value.status) == ("sin_semestre", 409)


def test_historica_sin_semestre_no_anula_recibos(db_session, make_historica, secretaria):
    req = make_historica(pagadas=(0,))
    pago = db_session.query(ProrrogaPayment).filter_by(request_id=req.id).one()
    with pytest.raises(ServiceError) as err:
        PaymentService.void(db_session, pago.id, secretaria.id, motivo="Prueba de anulación", now=date(2026, 11, 1))
    assert (err.value.code, err.value.status) == ("sin_semestre", 409)
