from datetime import date
from decimal import Decimal as D

import pytest

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment
from itcj2.apps.prorrogas_tec.services.document_service import DocumentService
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.plan_service import PlanService

pytestmark = pytest.mark.usefixtures("pdf_falso")
TRES = [(D("1217"), date(2091, 2, 1)), (D("1217"), date(2091, 3, 1)), (D("1216"), date(2091, 4, 1))]


def _cartas(db, req):
    return [d for d in DocumentService.current(db, req) if d.doc_type.startswith("carta_compromiso_")]


def test_primer_plan_genera_la_carta_y_avisa(db_session, aceptada, secretaria, avisos):
    req = PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("3650"), parcialidades=TRES,
                              now=date(2026, 11, 1))
    carta, = _cartas(db_session, req)
    assert carta.doc_type == "carta_compromiso_3" and carta.context["monto_total"] == "$3,650.00"
    assert carta.context["pago3_monto"] == "$1,216.00" and carta.context["pago1_fecha"] == "01 de febrero de 2091"
    assert req.total_amount == D("3650.00") and [a[0] for a in avisos.calls] == ["carta_lista"]


def test_reparto_por_omision():
    assert PlanService.reparto("3650", 3) == [D("1217"), D("1217"), D("1216")]


def test_replantear_conserva_lo_pagado_y_reparte_lo_que_falta(db_session, aceptada, secretaria, avisos, con_plan):
    con_plan(aceptada, [("1217.00", date(2091, 2, 1)), ("1217.00", date(2091, 3, 1)), ("1216.00", date(2091, 4, 1))],
             pagos=["1500.00"])  # la 1 pagada, la 2 a medias
    req = PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("3650"),
                              parcialidades=[(D("2433"), date(2091, 5, 1))], now=date(2026, 11, 1))
    vigentes = (db_session.query(ProrrogaInstallment).filter_by(request_id=req.id, superseded_at=None)
                .order_by(ProrrogaInstallment.number).all())
    assert [(v.number, v.amount) for v in vigentes] == [(1, D("1217.00")), (2, D("2433.00"))]
    assert db_session.query(ProrrogaInstallment).filter(ProrrogaInstallment.request_id == req.id,
                                                        ProrrogaInstallment.superseded_at.isnot(None)).count() == 2
    assert [d.doc_type for d in _cartas(db_session, req)] == ["carta_compromiso_2"]


def test_replanteo_sustituye_la_carta_anterior_aunque_cambie_n(db_session, aceptada, secretaria, avisos):
    PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("3650"), parcialidades=TRES,
                        now=date(2026, 11, 1))
    req = PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("3650"),
                              parcialidades=[(D("3650"), date(2091, 5, 1))], now=date(2026, 11, 1))
    assert [d.doc_type for d in _cartas(db_session, req)] == ["carta_compromiso_1"]


@pytest.mark.parametrize("total, nuevas, code", [
    (D("1000"), [(D("1000"), date(2091, 5, 1))], "total_menor_que_pagado"),       # pagado 1500
    (D("3650"), [(D("800"), date(2091, 5, 1)), (D("800"), date(2091, 5, 2)), (D("833"), date(2091, 5, 3))],
     "plazos_invalidos"),                                                          # 1 conservada + 3 nuevas
    (D("3650"), [(D("2000"), date(2091, 5, 1))], "suma_no_cuadra"),
    (D("3650"), [(D("2433"), date(2091, 1, 15))], "fechas_invalidas"),             # antes de la conservada
    (D("3650"), [(D("2433"), date(2091, 7, 1))], "fechas_invalidas"),              # después del fin de semestre
])
def test_replanteos_invalidos(db_session, aceptada, secretaria, avisos, con_plan, total, nuevas, code):
    con_plan(aceptada, [("1217.00", date(2091, 2, 1)), ("2433.00", date(2091, 3, 1))], pagos=["1500.00"])
    with pytest.raises(ServiceError) as e:
        PlanService.confirm(db_session, aceptada.id, secretaria.id, total=total, parcialidades=nuevas,
                            now=date(2026, 11, 1))
    assert e.value.code == code


def test_conservadas_vienen_de_la_cuenta_actual(db_session, aceptada, secretaria, avisos, con_plan):  # Review Focus 2
    con_plan(aceptada, [("1000.00", date(2091, 2, 1)), ("1000.00", date(2091, 3, 1))], pagos=[])
    req = PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("2000"),
                              parcialidades=[(D("2000"), date(2091, 4, 1))], now=date(2026, 11, 1))
    assert _cartas(db_session, req)[0].doc_type == "carta_compromiso_1"


def test_liquidada_no_se_replantea(db_session, aceptada, secretaria, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 2, 1))], pagos=["1000.00"])
    with pytest.raises(ServiceError) as e:
        PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("1000"),
                            parcialidades=[(D("1000"), date(2091, 4, 1))], now=date(2026, 11, 1))
    assert e.value.code == "ya_liquidada" and e.value.status == 409


def test_api_plan_y_permiso(client_as, secretaria, estudiante, aceptada, avisos):
    body = {"total": "3650", "parcialidades": [{"monto": "3650", "fecha": "2091-05-01"}]}
    r = client_as(secretaria).post(f"/api/prorrogas/v2/estudiantes/{aceptada.id}/plan", json=body)
    assert r.status_code == 200 and r.json()["carta"]["tipo"] == "carta_compromiso_1"
    assert client_as(estudiante).post(f"/api/prorrogas/v2/estudiantes/{aceptada.id}/plan", json=body).status_code == 403


def test_pdf_no_disponible_deja_el_plan_anterior(db_session, aceptada, secretaria, avisos, con_plan, monkeypatch):
    from itcj2.core.utils import docx_pdf

    con_plan(aceptada, [("1000.00", date(2091, 2, 1)), ("1000.00", date(2091, 3, 1))])
    db_session.commit()  # el rollback de confirm no debe llevarse el plan del fixture

    def roto(data, *, kind):
        raise docx_pdf.PdfConversionError("sin libreoffice")

    monkeypatch.setattr(docx_pdf, "docx_to_pdf", roto)
    with pytest.raises(ServiceError) as e:
        PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("2000"),
                            parcialidades=[(D("2000"), date(2091, 4, 1))], now=date(2026, 11, 1))
    assert e.value.code == "pdf_no_disponible" and e.value.status == 503
    vigentes = db_session.query(ProrrogaInstallment).filter_by(request_id=aceptada.id, superseded_at=None).all()
    assert len(vigentes) == 2 and _cartas(db_session, aceptada) == [] and avisos.calls == []


def test_aviso_carta_lista_con_su_plantilla(db_session, aceptada, monkeypatch):
    from types import SimpleNamespace

    from itcj2.apps.prorrogas_tec.services import notify
    from itcj2.core.models.notification import Notification
    from itcj2.core.utils import msgraph_mail

    sent = {}
    monkeypatch.setattr(msgraph_mail, "acquire_token_silent", lambda app: "tok")
    monkeypatch.setattr(msgraph_mail, "graph_send_mail", lambda token, subject, html, to, *a, **k: (
        sent.update(subject=subject, html=html) or SimpleNamespace(status_code=202, text="")))
    notify.notify_student(db_session, aceptada, kind="carta_lista", link="/prorrogas/estudiante")
    n = db_session.query(Notification).filter_by(user_id=aceptada.student_id, type="prorroga_carta_lista").one()
    assert n.title == sent["subject"] == "Tu carta compromiso está lista para firmar"
    assert n.body == "Entra a Mi prórroga para firmarla." and f"PR-{aceptada.id:05d}" in sent["html"]


def test_api_reparto(client_as, secretaria):
    c = client_as(secretaria)
    assert c.get("/api/prorrogas/v2/estudiantes/reparto?total=3650&n=3").json() == {
        "montos": ["1217.00", "1217.00", "1216.00"]}
    assert c.get("/api/prorrogas/v2/estudiantes/reparto?total=3650&n=4").json()["error"] == "plazos_invalidos"


def test_replantear_anular_y_replantear_otra_vez(db_session, aceptada, secretaria, avisos):  # Review Focus 2, M8
    from itcj2.apps.prorrogas_tec.services.account import load
    from itcj2.apps.prorrogas_tec.services.payment_service import PaymentService

    def estado(hoy):
        c = load(db_session, aceptada, hoy)
        cartas = [d.doc_type for d in _cartas(db_session, aceptada)]
        return [(p.number, p.amount, p.due_date, p.estado) for p in c.parcialidades], c.situacion, cartas

    PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("2000"), now=date(2091, 1, 15),
                        parcialidades=[(D("1000"), date(2091, 2, 1)), (D("1000"), date(2091, 3, 1))])
    assert estado(date(2091, 1, 15)) == ([(1, D("1000.00"), date(2091, 2, 1), "pendiente"),
                                          (2, D("1000.00"), date(2091, 3, 1), "pendiente")],
                                         "al_corriente", ["carta_compromiso_2"])
    pago = PaymentService.record(db_session, aceptada.id, secretaria.id, folio=f"M8-{aceptada.id}",
                                 paid_on=date(2091, 1, 20), amount=D("1000"), now=date(2091, 1, 20))
    assert estado(date(2091, 1, 20))[0][0][3] == "pagada"
    PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("2000"), now=date(2091, 1, 25),
                        parcialidades=[(D("1000"), date(2091, 4, 1))])           # conserva la 1
    assert estado(date(2091, 1, 25)) == ([(1, D("1000.00"), date(2091, 2, 1), "pagada"),
                                          (2, D("1000.00"), date(2091, 4, 1), "pendiente")],
                                         "al_corriente", ["carta_compromiso_2"])
    PaymentService.void(db_session, pago.id, secretaria.id, motivo="Recibo equivocado", now=date(2091, 2, 10))
    assert estado(date(2091, 2, 10)) == ([(1, D("1000.00"), date(2091, 2, 1), "vencida"),
                                          (2, D("1000.00"), date(2091, 4, 1), "pendiente")],
                                         "atrasada", ["carta_compromiso_2"])
    # Ya no hay pagadas: no conserva nada, así que caben 3 nuevas (con la 1 conservada serían 4).
    PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("2000"), now=date(2091, 2, 10),
                        parcialidades=[(D("700"), date(2091, 3, 1)), (D("700"), date(2091, 4, 1)),
                                       (D("600"), date(2091, 5, 1))])
    assert estado(date(2091, 2, 10)) == ([(1, D("700.00"), date(2091, 3, 1), "pendiente"),
                                          (2, D("700.00"), date(2091, 4, 1), "pendiente"),
                                          (3, D("600.00"), date(2091, 5, 1), "pendiente")],
                                         "al_corriente", ["carta_compromiso_3"])
    assert aceptada.total_amount == D("2000.00")
    assert db_session.query(ProrrogaInstallment).filter(ProrrogaInstallment.request_id == aceptada.id,
                                                        ProrrogaInstallment.superseded_at.isnot(None)).count() == 3
