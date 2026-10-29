from datetime import date, datetime
from decimal import Decimal as D

import pytest
from sqlalchemy.exc import IntegrityError

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment, ProrrogaPayment
from itcj2.apps.prorrogas_tec.services.events import EVENT_TYPES


def test_una_sola_parcialidad_vigente_por_numero(db_session, aceptada):
    db_session.add(ProrrogaInstallment(request_id=aceptada.id, number=1, amount=D("100.00"), due_date=date(2091, 2, 1)))
    db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(ProrrogaInstallment(request_id=aceptada.id, number=1, amount=D("5.00"),
                                               due_date=date(2091, 3, 1)))
            db_session.flush()


def test_folio_unico_entre_vigentes(db_session, aceptada, make_aceptada):
    otra = make_aceptada()
    p = ProrrogaPayment(request_id=aceptada.id, folio="C-1", paid_on=date(2091, 2, 1), amount=D("10.00"))
    db_session.add(p)
    db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(ProrrogaPayment(request_id=otra.id, folio="C-1", paid_on=date(2091, 2, 1), amount=D("10.00")))
            db_session.flush()
    p.voided_at = datetime(2091, 2, 2)
    db_session.flush()
    db_session.add(ProrrogaPayment(request_id=otra.id, folio="C-1", paid_on=date(2091, 2, 1), amount=D("10.00")))
    db_session.flush()


def test_eventos_del_plan_3():
    assert {"plan_confirmado", "recibo_registrado", "recibo_anulado", "documento_firmado",
            "recordatorio_enviado", "lista_bloqueo_exportada", "desbloqueo_avisado"} <= EVENT_TYPES
