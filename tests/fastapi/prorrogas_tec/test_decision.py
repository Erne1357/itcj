import pytest

from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.request_service import RequestService
from itcj2.apps.prorrogas_tec.services.document_service import DocumentService

pytestmark = pytest.mark.usefixtures("pdf_falso")


def test_aceptar_genera_la_carta_y_avisa(db_session, solicitud, secretaria, avisos):
    req = RequestService.decide(db_session, solicitud.id, secretaria.id, aceptar=True, comentario="")
    assert req.status == "aceptada" and req.decided_by_id == secretaria.id
    assert [d.doc_type for d in DocumentService.current(db_session, req)] == ["carta_aceptacion"]
    assert avisos.calls == [("aceptada", req.id, "/prorrogas/estudiante")]


def test_rechazar_requiere_motivo_y_lo_pone_en_la_carta(db_session, solicitud, secretaria, avisos):
    with pytest.raises(ServiceError) as e:
        RequestService.decide(db_session, solicitud.id, secretaria.id, aceptar=False, comentario="  ")
    assert e.value.code == "motivo_requerido"
    req = RequestService.decide(db_session, solicitud.id, secretaria.id, aceptar=False, comentario="Falta el comprobante.")
    carta = DocumentService.current(db_session, req)[0]
    assert carta.doc_type == "carta_rechazo" and carta.context["motivo_rechazo"] == "Falta el comprobante."


def test_no_se_resuelve_dos_veces(db_session, solicitud, secretaria, avisos):  # Review Focus 4
    RequestService.decide(db_session, solicitud.id, secretaria.id, aceptar=True, comentario="")
    with pytest.raises(ServiceError) as e:
        RequestService.decide(db_session, solicitud.id, secretaria.id, aceptar=False, comentario="otra")
    assert e.value.code == "ya_resuelta" and e.value.status == 409
    assert len(DocumentService.current(db_session, solicitud)) == 1 and len(avisos.calls) == 1


def test_api_lista_pendientes_y_decide(client_as, secretaria, solicitud, avisos):
    c = client_as(secretaria)
    ids = [i["id"] for i in c.get("/api/prorrogas/v2/solicitudes").json()["items"]]
    assert solicitud.id in ids
    r = c.post(f"/api/prorrogas/v2/solicitudes/{solicitud.id}/decision", json={"aceptar": True, "comentario": ""})
    assert r.status_code == 200 and r.json()["estado"] == "aceptada"
    assert c.post(f"/api/prorrogas/v2/solicitudes/{solicitud.id}/decision",
                  json={"aceptar": True, "comentario": ""}).status_code == 409


def test_api_el_estudiante_no_decide(client_as, estudiante, solicitud):
    assert client_as(estudiante).post(f"/api/prorrogas/v2/solicitudes/{solicitud.id}/decision",
                                      json={"aceptar": True, "comentario": ""}).status_code == 403


def test_la_notificacion_queda_guardada(db_session, solicitud, secretaria, enviar_correo):
    from itcj2.core.models.notification import Notification

    from itcj2.config import get_settings

    RequestService.decide(db_session, solicitud.id, secretaria.id, aceptar=True, comentario="")
    db_session.rollback()  # descarta lo que la sesión no commiteó: sin el 2.º commit la fila se pierde
    assert enviar_correo.calls[0]["context"]["link"] == f"{get_settings().DOMAIN}/prorrogas/estudiante"
    notas = db_session.query(Notification).filter_by(
        user_id=solicitud.student_id, app_name="prorrogas_tec", type="prorroga_aceptada").all()
    assert len(notas) == 1 and len(enviar_correo.calls) == 1


def test_comentario_muy_largo_y_pendientes(db_session, solicitud, secretaria):
    with pytest.raises(ServiceError) as e:
        RequestService.decide(db_session, solicitud.id, secretaria.id, aceptar=True, comentario="x" * 1001)
    assert e.value.code == "comentario_muy_largo"
    assert solicitud.id in [r.id for r in RequestService.pending(db_session)]


def test_pdf_no_disponible_deja_la_solicitud_pendiente(db_session, solicitud, secretaria, avisos, monkeypatch):
    from itcj2.core.utils import docx_pdf

    def roto(data, *, kind):
        raise docx_pdf.PdfConversionError("sin libreoffice")

    monkeypatch.setattr(docx_pdf, "docx_to_pdf", roto)
    db_session.commit()  # el rollback de decide no debe llevarse la solicitud del fixture
    with pytest.raises(ServiceError) as e:
        RequestService.decide(db_session, solicitud.id, secretaria.id, aceptar=True, comentario="")
    assert e.value.code == "pdf_no_disponible" and e.value.status == 503
    db_session.refresh(solicitud)
    assert solicitud.status == "pendiente" and solicitud.decided_by_id is None
    assert DocumentService.current(db_session, solicitud) == [] and avisos.calls == []
