from datetime import date
from decimal import Decimal as D

import pytest

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment
from itcj2.apps.prorrogas_tec.services.document_service import DocumentService
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.identity import folio
from itcj2.apps.prorrogas_tec.services.plan_service import PlanService

pytestmark = pytest.mark.usefixtures("pdf_falso")
DOS = [(D("1825"), date(2091, 2, 1)), (D("1825"), date(2091, 4, 1))]
TRES = [(D("1217"), date(2091, 2, 1)), (D("1217"), date(2091, 3, 1)), (D("1216"), date(2091, 4, 1))]


def _cartas(db, req):
    return [d for d in DocumentService.current(db, req) if d.doc_type.startswith("carta_compromiso_")]


def test_primer_plan_genera_la_carta_y_avisa(db_session, aceptada, secretaria, avisos):
    req = PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("3650"), parcialidades=DOS,
                              now=date(2026, 11, 1))
    carta, = _cartas(db_session, req)
    assert carta.doc_type == "carta_compromiso_2" and carta.context["monto_total"] == "$3,650.00"
    assert carta.context["pago2_monto"] == "$1,825.00" and carta.context["pago1_fecha"] == "01 de febrero de 2091"
    assert req.total_amount == D("3650.00") and [a[0] for a in avisos.calls] == ["carta_lista"]


def test_reparto_por_omision():
    assert PlanService.reparto("3650", 2) == [D("1825"), D("1825")]


def test_sin_pagos_el_plan_se_rehace_avisa_y_queda_en_el_historial(db_session, aceptada, secretaria, avisos):
    from itcj2.apps.prorrogas_tec.models.event import ProrrogaEvent

    PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("3650"), parcialidades=DOS,
                        now=date(2026, 11, 1))
    req = PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("3600"),
                              parcialidades=[(D("3600"), date(2091, 5, 1))], now=date(2026, 11, 1))
    vigentes = db_session.query(ProrrogaInstallment).filter_by(request_id=req.id, superseded_at=None).all()
    assert [(v.number, v.amount, v.due_date) for v in vigentes] == [(1, D("3600.00"), date(2091, 5, 1))]
    assert [d.doc_type for d in _cartas(db_session, req)] == ["carta_compromiso_1"]
    assert req.total_amount == D("3600.00") and [a[0] for a in avisos.calls] == ["carta_lista", "plan_modificado"]
    tipos = [e.event_type for e in db_session.query(ProrrogaEvent).filter_by(request_id=req.id)
             .order_by(ProrrogaEvent.id) if e.event_type.startswith("plan_")]
    assert tipos == ["plan_confirmado", "plan_modificado"]


@pytest.mark.parametrize("total, nuevas, code", [
    (D("3650"), [(D("900"), date(2091, 5, 1)), (D("900"), date(2091, 5, 2)), (D("900"), date(2091, 5, 3)),
                 (D("950"), date(2091, 5, 4))], "plazos_invalidos"),
    (D("3650"), [], "plazos_invalidos"),
    (D("3650"), [(D("2000"), date(2091, 5, 1))], "suma_no_cuadra"),
    (D("3650"), [(D("3650"), date(2026, 10, 31))], "fechas_invalidas"),            # antes de hoy
    (D("3650"), [(D("3650"), date(2091, 7, 1))], "fechas_invalidas"),              # después del fin de semestre
    (D("3650"), [(D("1825"), date(2091, 5, 2)), (D("1825"), date(2091, 5, 1))], "fechas_invalidas"),  # desordenadas
])
def test_planes_invalidos(db_session, aceptada, secretaria, avisos, total, nuevas, code):
    with pytest.raises(ServiceError) as e:
        PlanService.confirm(db_session, aceptada.id, secretaria.id, total=total, parcialidades=nuevas,
                            now=date(2026, 11, 1))
    assert e.value.code == code


def test_con_un_pago_el_plan_ya_no_se_modifica(db_session, aceptada, secretaria, avisos, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 2, 1)), ("1000.00", date(2091, 3, 1))], pagos=["1.00"])
    with pytest.raises(ServiceError) as e:
        PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("2000"),
                            parcialidades=[(D("2000"), date(2091, 4, 1))], now=date(2026, 11, 1))
    assert e.value.code == "con_pagos" and e.value.status == 409 and avisos.calls == []


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


@pytest.mark.parametrize("kind, titulo, cuerpo", [
    ("carta_lista", "Tu carta compromiso está lista para firmar", "Entra a Mi prórroga para firmarla."),
    ("plan_modificado", "Tu plan de pagos cambió",
     "Revisa tus nuevas fechas en Mi prórroga y firma tu nueva carta compromiso."),
])
def test_avisos_del_plan_con_su_plantilla(db_session, aceptada, monkeypatch, kind, titulo, cuerpo):
    from types import SimpleNamespace

    from itcj2.apps.prorrogas_tec.services import notify
    from itcj2.core.models.notification import Notification
    from itcj2.core.utils import msgraph_mail

    sent = {}
    monkeypatch.setattr(msgraph_mail, "acquire_token_silent", lambda app: "tok")
    monkeypatch.setattr(msgraph_mail, "graph_send_mail", lambda token, subject, html, to, *a, **k: (
        sent.update(subject=subject, html=html) or SimpleNamespace(status_code=202, text="")))
    notify.notify_student(db_session, aceptada, kind=kind, link="/prorrogas/estudiante")
    n = db_session.query(Notification).filter_by(user_id=aceptada.student_id, type=f"prorroga_{kind}").one()
    assert n.title == sent["subject"] == titulo
    assert n.body == cuerpo and folio(aceptada) in sent["html"]


def test_api_reparto(client_as, secretaria):
    c = client_as(secretaria)
    assert c.get("/api/prorrogas/v2/estudiantes/reparto?total=3650&n=2").json() == {
        "montos": ["1825.00", "1825.00"]}
    assert c.get("/api/prorrogas/v2/estudiantes/reparto?total=3650&n=3").json()["error"] == "plazos_invalidos"


def test_anular_el_unico_pago_vuelve_a_dejar_modificar_el_plan(db_session, aceptada, secretaria, avisos):
    from itcj2.apps.prorrogas_tec.services.account import load
    from itcj2.apps.prorrogas_tec.services.payment_service import PaymentService

    PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("2000"), now=date(2091, 1, 15),
                        parcialidades=[(D("1000"), date(2091, 2, 1)), (D("1000"), date(2091, 3, 1))])
    pago = PaymentService.record(db_session, aceptada.id, secretaria.id, folio=f"M8-{aceptada.id}",
                                 paid_on=date(2091, 1, 20), amount=D("1000"), now=date(2091, 1, 20))
    with pytest.raises(ServiceError) as e:
        PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("2000"), now=date(2091, 1, 25),
                            parcialidades=[(D("2000"), date(2091, 4, 1))])
    assert e.value.code == "con_pagos"
    PaymentService.void(db_session, pago.id, secretaria.id, motivo="Recibo equivocado", now=date(2091, 1, 30))
    PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("2000"), now=date(2091, 1, 30),
                        parcialidades=[(D("1000"), date(2091, 3, 1)), (D("1000"), date(2091, 4, 1))])
    c = load(db_session, aceptada, date(2091, 1, 30))
    assert [(p.number, p.amount, p.due_date, p.estado) for p in c.parcialidades] == [
        (1, D("1000.00"), date(2091, 3, 1), "pendiente"), (2, D("1000.00"), date(2091, 4, 1), "pendiente")]
    assert [d.doc_type for d in _cartas(db_session, aceptada)] == ["carta_compromiso_2"]


def test_plan_nuevo_no_admite_tres_pagos(db_session, aceptada, secretaria, avisos):
    with pytest.raises(ServiceError) as e:
        PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("3650"), parcialidades=TRES, now=date(2026, 11, 1))
    assert e.value.code == "plazos_invalidos"


def test_plan_con_pago_vencido_no_se_rehace(db_session, aceptada, secretaria, con_plan, avisos):
    con_plan(aceptada, [("1000.00", date(2026, 10, 1))])
    with pytest.raises(ServiceError) as e:
        PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("1000"),
                            parcialidades=[(D("1000"), date(2091, 2, 1))], now=date(2026, 11, 1))
    assert e.value.code == "con_vencidos" and e.value.status == 409


def test_el_aviso_del_plan_lleva_fechas_y_montos(db_session, aceptada, secretaria, avisos):
    PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("3650"), parcialidades=DOS, now=date(2026, 11, 1))
    kw = avisos.kw[0]
    assert "$1,825.00 el 01 de febrero de 2091" in kw["body"] and kw["context"]["total"] == "$3,650.00"
    assert [p["etiqueta"] for p in kw["context"]["pagos"]] == ["Pago 1/2", "Pago 2/2"]


@pytest.mark.parametrize("plantilla", ["carta_lista.html", "plan_modificado.html"])
def test_el_correo_del_plan_lista_los_pagos(plantilla):
    from itcj2.templates import templates
    html = templates.env.get_template(f"prorrogas_tec/email/{plantilla}").render(
        folio="PR-1", link="x", total="$10.00", pagos=[{"etiqueta": "Pago único", "fecha": "01 de mayo de 2091", "monto": "$10.00"}])
    assert "Pago único" in html and "01 de mayo de 2091" in html and "Firmar mi carta" in html
