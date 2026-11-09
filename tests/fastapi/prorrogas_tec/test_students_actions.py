from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import load_workbook

from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.students_service import StudentsService

AHORA = datetime(2026, 11, 2, 10, 0)


def test_recordar_una_vez_al_dia(db_session, aceptada, secretaria, con_plan, avisos):
    con_plan(aceptada, [("1000.00", date(2020, 1, 1))])
    StudentsService.remind(db_session, aceptada.id, secretaria.id, now=AHORA)
    assert [a[0] for a in avisos.calls] == ["recordatorio"]
    with pytest.raises(ServiceError) as e:
        StudentsService.remind(db_session, aceptada.id, secretaria.id, now=AHORA + timedelta(hours=23))
    assert e.value.code == "ya_recordado"
    StudentsService.remind(db_session, aceptada.id, secretaria.id, now=AHORA + timedelta(hours=25))


def test_no_se_recuerda_sin_plan_ni_saldo(db_session, aceptada, make_aceptada, secretaria, con_plan, avisos):
    pagada = con_plan(make_aceptada(), [("10.00", date(2020, 1, 1))], pagos=["10.00"])
    db_session.commit()  # el rollback del servicio al fallar descartaría lo que solo está en flush
    with pytest.raises(ServiceError) as e:
        StudentsService.remind(db_session, aceptada.id, secretaria.id, now=AHORA)
    assert e.value.code == "sin_plan"
    with pytest.raises(ServiceError) as e:
        StudentsService.remind(db_session, pagada.id, secretaria.id, now=AHORA)
    assert e.value.code == "sin_saldo"


def test_excel_de_adeudos_se_explica_solo(db_session, aceptada, make_aceptada, secretaria, con_plan, periodo):
    con_plan(aceptada, [("1000.00", date(2020, 1, 1)), ("500.00", date(2091, 5, 1))], pagos=["200.00"])
    al_dia = con_plan(make_aceptada(), [("500.00", date(2091, 5, 1))])
    data, nombre = StudentsService.export_adeudos(db_session, periodo.id, secretaria.id, now=AHORA)
    ws = load_workbook(BytesIO(data)).active
    assert ws["A1"].value == "Lista de adeudos de prórrogas" and "02/11/2026" in ws["A3"].value
    assert "parcialidad vencida y no cubierta" in ws["A4"].value and ws.freeze_panes == "A8" and ws.auto_filter.ref
    assert [c.value for c in ws[7]] == ["No. de control", "Nombre", "Carrera", "Monto debido"]
    fila = next(r for r in ws.iter_rows(min_row=8, values_only=True) if r[0] == aceptada.control_number)
    assert float(fila[3]) == 1300.0  # saldo total
    controles = [r[0].value for r in ws.iter_rows(min_row=8)]
    assert aceptada.control_number in controles and al_dia.control_number not in controles
    assert nombre.startswith("adeudos-prorrogas-") and nombre.endswith(".xlsx")
    primera = aceptada.block_exported_at
    StudentsService.export_adeudos(db_session, periodo.id, secretaria.id, now=AHORA + timedelta(days=3))
    db_session.refresh(aceptada)
    assert primera is not None and aceptada.block_exported_at == primera


def test_avisar_desbloqueo_solo_si_aplica(db_session, aceptada, secretaria, con_plan, periodo):
    con_plan(aceptada, [("1000.00", date(2020, 1, 1))])
    StudentsService.export_adeudos(db_session, periodo.id, secretaria.id, now=AHORA)
    with pytest.raises(ServiceError) as e:
        StudentsService.mark_unblock(db_session, aceptada.id, secretaria.id, now=AHORA)
    assert e.value.code == "no_aplica"                       # exportada pero aún debe
    from itcj2.apps.prorrogas_tec.models.plan import ProrrogaPayment
    db_session.add(ProrrogaPayment(request_id=aceptada.id, folio="Z-1", paid_on=date(2026, 11, 1),
                                   amount=1000))
    db_session.flush()
    StudentsService.mark_unblock(db_session, aceptada.id, secretaria.id, now=AHORA)
    assert aceptada.unblock_notified_at is not None


def test_api_exportar(client_as, secretaria, estudiante, periodo):
    r = client_as(secretaria).post("/api/prorrogas/v2/estudiantes/adeudos.xlsx", json={"period_id": periodo.id})
    assert r.status_code == 200 and r.content[:2] == b"PK" and "attachment" in r.headers["content-disposition"]
    assert client_as(estudiante).post("/api/prorrogas/v2/estudiantes/adeudos.xlsx",
                                      json={"period_id": periodo.id}).status_code == 403


def test_reexportar_tras_avisar_desbloqueo_reinicia_el_ciclo(db_session, aceptada, secretaria, con_plan, periodo):  # I1
    from itcj2.apps.prorrogas_tec.models.event import ProrrogaEvent
    from itcj2.apps.prorrogas_tec.services.payment_service import PaymentService

    def pagar(folio):
        return PaymentService.record(db_session, aceptada.id, secretaria.id, folio=folio,
                                     paid_on=aceptada.created_at.date(), amount=Decimal("1000"),
                                     now=aceptada.created_at)

    con_plan(aceptada, [("1000.00", date(2020, 1, 1))])
    StudentsService.export_adeudos(db_session, periodo.id, secretaria.id, now=AHORA)
    pago = pagar(f"I1-{aceptada.id}-a")
    StudentsService.mark_unblock(db_session, aceptada.id, secretaria.id, now=AHORA)
    PaymentService.void(db_session, pago.id, secretaria.id, motivo="Recibo de otro alumno", now=AHORA)
    segunda = AHORA + timedelta(days=3)
    StudentsService.export_adeudos(db_session, periodo.id, secretaria.id, now=segunda)
    db_session.refresh(aceptada)
    assert aceptada.unblock_notified_at is None and aceptada.block_exported_at == segunda
    ev = (db_session.query(ProrrogaEvent).filter_by(event_type="lista_bloqueo_exportada")
          .order_by(ProrrogaEvent.id.desc()).first())
    assert ev.payload["solicitudes"] == [aceptada.id] and ev.payload["estudiantes"] == 1
    pagar(f"I1-{aceptada.id}-b")
    assert StudentsService.expediente(db_session, aceptada.id, segunda.date())["bloqueo"]["avisar_desbloqueo"] is True


def test_excel_no_convierte_texto_en_formula(db_session, aceptada, secretaria, con_plan, periodo):  # T7
    aceptada.student_name = "=1+1"
    con_plan(aceptada, [("1000.00", date(2020, 1, 1))])
    data, _ = StudentsService.export_adeudos(db_session, periodo.id, secretaria.id, now=AHORA)
    ws = load_workbook(BytesIO(data)).active
    fila = next(r for r in ws.iter_rows(min_row=8) if r[0].value == aceptada.control_number)
    assert fila[1].value == "=1+1" and fila[1].data_type == "s"


def test_recordatorio_dice_si_el_pago_ya_vencio(db_session, aceptada, make_aceptada, secretaria, con_plan,
                                                enviar_correo):  # M9
    from itcj2.core.models.notification import Notification
    from itcj2.templates import templates

    con_plan(aceptada, [("1000.00", date(2020, 1, 1))])
    al_dia = con_plan(make_aceptada(), [("500.00", date(2091, 5, 1))])
    for req in (aceptada, al_dia):
        StudentsService.remind(db_session, req.id, secretaria.id, now=AHORA)
    cuerpos = [db_session.query(Notification).filter_by(user_id=r.student_id, type="prorroga_recordatorio").one().body
               for r in (aceptada, al_dia)]
    assert cuerpos == ["Saldo $1,000.00. Tienes un pago vencido desde el 01 de enero de 2020 por $1,000.00.",
                       "Saldo $500.00. Próximo pago: 01 de mayo de 2091 por $500.00."]
    plantilla = templates.env.get_template("prorrogas_tec/email/recordatorio.html")
    vencido, proximo = (plantilla.render(**c["context"]) for c in enviar_correo.calls)
    assert "pago vencido desde el 01 de enero de 2020 por $1,000.00" in vencido and "próximo pago" not in vencido
    assert "Tu próximo pago es el 01 de mayo de 2091 por $500.00" in proximo and "vencido" not in proximo


def test_no_se_recuerda_sin_cuenta_ni_correo(db_session, make_historica, secretaria, avisos):  # M4
    req = make_historica()  # importada: sin cuenta, sin correo y con saldo vencido
    db_session.commit()  # el rollback del servicio al fallar descartaría lo que solo está en flush
    assert StudentsService.expediente(db_session, req.id, AHORA.date())["recordatorio"]["puede"] is False
    with pytest.raises(ServiceError) as e:
        StudentsService.remind(db_session, req.id, secretaria.id, now=AHORA)
    assert (e.value.code, e.value.status) == ("sin_destinatario", 409) and avisos.calls == []


def test_recordatorio_que_no_sale_no_bloquea_24h(db_session, aceptada, secretaria, con_plan, monkeypatch):  # Review Focus 2
    from itcj2.apps.prorrogas_tec.services import notify
    con_plan(aceptada, [("1000.00", date(2091, 5, 1))])
    monkeypatch.setattr(notify, "send_email", lambda **k: False)
    with pytest.raises(ServiceError) as e:
        StudentsService.remind(db_session, aceptada.id, secretaria.id, now=AHORA)
    assert e.value.code == "correo_no_salio" and e.value.status == 502
    db_session.refresh(aceptada)
    assert aceptada.last_reminded_at is None
    monkeypatch.setattr(notify, "send_email", lambda **k: True)
    StudentsService.remind(db_session, aceptada.id, secretaria.id, now=AHORA)
    assert aceptada.last_reminded_at is not None


API = "/api/prorrogas/v2/estudiantes"


def _carta(db, req, firmada=False):
    from itcj2.apps.prorrogas_tec.models.document import ProrrogaDocument
    d = ProrrogaDocument(request_id=req.id, doc_type="carta_compromiso_1", version=1, context={}, file_path="x.pdf",
                         sha256="0" * 64, signed_at=AHORA if firmada else None)
    db.add(d)
    db.flush()
    return d


def test_filtro_y_marca_de_firma_pendiente(client_as, secretaria, db_session, periodo, aceptada, make_aceptada):
    _carta(db_session, aceptada)
    _carta(db_session, make_aceptada(), firmada=True)
    d = client_as(secretaria).get(f"{API}?period_id={periodo.id}&filtro=por_firmar&per_page=100").json()
    assert [i["id"] for i in d["items"]] == [aceptada.id] and d["items"][0]["por_firmar"] is True
    assert d["conteos"]["por_firmar"] == 1


def test_recordar_firma_una_vez_al_dia(db_session, aceptada, secretaria, avisos):
    _carta(db_session, aceptada)
    StudentsService.remind_pending(db_session, aceptada.id, secretaria.id, "firma", now=AHORA)
    assert avisos.calls[0][0] == "firma_pendiente"
    with pytest.raises(ServiceError) as e:
        StudentsService.remind_pending(db_session, aceptada.id, secretaria.id, "firma", now=AHORA + timedelta(hours=23))
    assert e.value.code == "ya_recordado"
    StudentsService.remind_pending(db_session, aceptada.id, secretaria.id, "firma", now=AHORA + timedelta(hours=25))
    assert len(avisos.calls) == 2


def test_no_recuerda_si_ya_firmo(db_session, aceptada, secretaria, avisos):
    _carta(db_session, aceptada, firmada=True)
    with pytest.raises(ServiceError) as e:
        StudentsService.remind_pending(db_session, aceptada.id, secretaria.id, "firma", now=AHORA)
    assert e.value.code == "no_aplica"


def test_secretaria_abre_la_referencia(client_as, secretaria, db_session, aceptada):
    from itcj2.apps.prorrogas_tec.services.reference_service import ReferenceService
    url = f"{API}/{aceptada.id}/referencia.pdf"
    assert client_as(secretaria).get(url).status_code == 404
    assert client_as(secretaria).get(f"{API}/{aceptada.id}").json()["solicitud"]["referencia"] is None
    ReferenceService.save(db_session, aceptada, b"%PDF-1.4 x", aceptada.student_id)
    assert client_as(secretaria).get(url).content == b"%PDF-1.4 x"
    assert client_as(secretaria).get(f"{API}/{aceptada.id}").json()["solicitud"]["referencia"]


def test_referencia_con_archivo_borrado_es_404(client_as, secretaria, db_session, aceptada):
    aceptada.reference_path = "referencias/0/no-existe.pdf"
    db_session.flush()
    assert client_as(secretaria).get(f"{API}/{aceptada.id}/referencia.pdf").status_code == 404


def test_recordar_referencia_solo_si_falta(db_session, aceptada, secretaria, avisos):
    from itcj2.apps.prorrogas_tec.services.reference_service import ReferenceService
    StudentsService.remind_pending(db_session, aceptada.id, secretaria.id, "referencia", now=AHORA)
    assert avisos.calls[0][0] == "referencia_pendiente"
    ReferenceService.save(db_session, aceptada, b"%PDF-1.4 x", aceptada.student_id)
    with pytest.raises(ServiceError) as e:
        StudentsService.remind_pending(db_session, aceptada.id, secretaria.id, "referencia", now=AHORA + timedelta(days=2))
    assert e.value.code == "no_aplica"


MOTIVO_CIERRE = "No trajo su referencia a tiempo."


def test_cerrar_sin_plan(db_session, aceptada, secretaria):
    from itcj2.apps.prorrogas_tec.models.event import ProrrogaEvent
    req = StudentsService.close_without_plan(db_session, aceptada.id, secretaria.id, MOTIVO_CIERRE, now=date(2091, 6, 21))
    assert req.status == "cerrada_sin_plan"
    ev = db_session.query(ProrrogaEvent).filter_by(request_id=aceptada.id, event_type="cerrada_sin_plan").one()
    assert ev.payload == {"motivo": MOTIVO_CIERRE}


@pytest.mark.parametrize("motivo, dia, code", [
    ("corto", date(2091, 6, 21), "motivo_invalido"),
    (MOTIVO_CIERRE, date(2091, 6, 20), "semestre_en_curso"),
])
def test_cierre_invalido(db_session, aceptada, secretaria, motivo, dia, code):
    with pytest.raises(ServiceError) as e:
        StudentsService.close_without_plan(db_session, aceptada.id, secretaria.id, motivo, now=dia)
    assert e.value.code == code


def test_con_plan_no_se_cierra(db_session, aceptada, secretaria, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 5, 1))])
    with pytest.raises(ServiceError) as e:
        StudentsService.close_without_plan(db_session, aceptada.id, secretaria.id, MOTIVO_CIERRE, now=date(2091, 6, 21))
    assert e.value.code == "con_plan"


def test_lista_marca_pendientes_de_cierre(db_session, periodo, aceptada):
    ver = lambda dia: StudentsService.listar(db_session, periodo.id, filtro="pendiente_cierre", today=dia)  # noqa: E731
    d = ver(date(2091, 6, 21))
    assert [i["id"] for i in d["items"]] == [aceptada.id] and d["conteos"]["pendiente_cierre"] == 1
    assert ver(date(2091, 6, 20))["items"] == []


def test_cerrada_ya_no_sale_en_estudiantes(db_session, periodo, aceptada, secretaria):
    StudentsService.close_without_plan(db_session, aceptada.id, secretaria.id, MOTIVO_CIERRE, now=date(2091, 6, 21))
    assert StudentsService.listar(db_session, periodo.id, today=date(2091, 6, 21))["items"] == []
    with pytest.raises(ServiceError) as e:
        StudentsService.expediente(db_session, aceptada.id, date(2091, 6, 21))
    assert e.value.code == "no_encontrada"


def test_no_se_recuerda_referencia_con_plan_ni_sin_semestre(db_session, aceptada, make_aceptada, secretaria, con_plan, avisos):  # I1
    con_plan(aceptada, [("1000.00", date(2091, 5, 1))])
    sin_semestre = make_aceptada()
    sin_semestre.period_id = None
    db_session.commit()  # el rollback del servicio al fallar descartaría lo que solo está en flush
    for rid in (aceptada.id, sin_semestre.id):
        with pytest.raises(ServiceError) as e:
            StudentsService.remind_pending(db_session, rid, secretaria.id, "referencia", now=AHORA)
        assert e.value.code == "no_aplica"


def test_listar_con_semestre_inexistente_es_404(db_session):  # T14
    with pytest.raises(ServiceError) as e:
        StudentsService.listar(db_session, 0, today=date(2091, 6, 21))
    assert e.value.code == "periodo_no_encontrado" and e.value.status == 404


def test_leer_referencia_sin_archivo_es_404(db_session, aceptada):  # T12-a
    from itcj2.apps.prorrogas_tec.services.reference_service import ReferenceService
    aceptada.reference_path = "referencias/0/no-existe.pdf"
    with pytest.raises(ServiceError) as e:
        ReferenceService.read(aceptada)
    assert e.value.code == "no_encontrada" and e.value.status == 404


MOTIVO_AVISO = "El folio no coincide con el de Caja."


def _con_recibo(db, req):
    from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment
    from itcj2.apps.prorrogas_tec.services import storage
    i = db.query(ProrrogaInstallment).filter_by(request_id=req.id, number=1).one()
    i.receipt_path, i.receipt_uploaded_at = f"recibos/0/{req.id}-1-abc.pdf", datetime(2091, 3, 1, 9, 0)
    storage.write_atomic(i.receipt_path, b"%PDF-1.4 x")
    db.flush()


def test_la_secretaria_ve_y_abre_el_recibo(client_as, secretaria, db_session, aceptada, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 5, 1))])
    c = client_as(secretaria)
    assert c.get(f"{API}/{aceptada.id}/parcialidades/1/recibo.pdf").status_code == 404
    _con_recibo(db_session, aceptada)
    assert c.get(f"{API}/{aceptada.id}").json()["cuenta"]["parcialidades"][0]["recibo_subido"] == "2091-03-01T09:00:00"
    assert c.get(f"{API}/{aceptada.id}/parcialidades/1/recibo.pdf").content == b"%PDF-1.4 x"


def test_avisar_inconsistencia(db_session, aceptada, secretaria, con_plan, enviar_correo):
    from itcj2.apps.prorrogas_tec.models.event import ProrrogaEvent
    from itcj2.core.models.notification import Notification
    from itcj2.templates import templates
    con_plan(aceptada, [("1000.00", date(2091, 5, 1))])
    _con_recibo(db_session, aceptada)
    StudentsService.report_receipt_issue(db_session, aceptada.id, secretaria.id, 1, f"  {MOTIVO_AVISO}  ")
    ev = db_session.query(ProrrogaEvent).filter_by(request_id=aceptada.id, event_type="recibo_inconsistente").one()
    assert ev.payload == {"numero": 1, "motivo": MOTIVO_AVISO} and ev.actor_id == secretaria.id
    n = db_session.query(Notification).filter_by(user_id=aceptada.student_id, type="prorroga_recibo_inconsistente").one()
    assert n.title == "Revisa el recibo que subiste" and n.body == f"Pago 1: {MOTIVO_AVISO}"
    envio = enviar_correo.calls[0]
    assert envio["subject"] == n.title
    html = templates.env.get_template("prorrogas_tec/email/recibo_inconsistente.html").render(**envio["context"])
    assert MOTIVO_AVISO in html


@pytest.mark.parametrize("motivo", ["muy corto", "x" * 501])
def test_motivo_del_aviso_invalido(db_session, aceptada, secretaria, motivo):
    with pytest.raises(ServiceError) as e:
        StudentsService.report_receipt_issue(db_session, aceptada.id, secretaria.id, 1, motivo)
    assert (e.value.code, e.value.status) == ("motivo_invalido", 400)


def test_sin_recibo_no_se_avisa(db_session, aceptada, secretaria, con_plan, enviar_correo):
    con_plan(aceptada, [("1000.00", date(2091, 5, 1))])
    with pytest.raises(ServiceError) as e:
        StudentsService.report_receipt_issue(db_session, aceptada.id, secretaria.id, 1, MOTIVO_AVISO)
    assert (e.value.code, e.value.status) == ("no_aplica", 409) and enviar_correo.calls == []


def test_aviso_cuyo_correo_no_sale_se_guarda_y_lo_dice(client_as, secretaria, db_session, aceptada, con_plan, monkeypatch):
    from itcj2.apps.prorrogas_tec.services import notify
    monkeypatch.setattr(notify, "send_email", lambda **k: False)
    con_plan(aceptada, [("1000.00", date(2091, 5, 1))])
    _con_recibo(db_session, aceptada)
    r = client_as(secretaria).post(f"{API}/{aceptada.id}/parcialidades/1/avisar-inconsistencia", json={"motivo": MOTIVO_AVISO})
    assert r.status_code == 200 and r.json()["correo_enviado"] is False
