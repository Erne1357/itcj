import subprocess

import pytest

from itcj2.apps.prorrogas_tec.documents.catalog import default_template_path
from itcj2.apps.prorrogas_tec.services.docx_fill import find_placeholders
from itcj2.core.utils.docx_pdf import PdfConversionError
from itcj2.core.utils.timezone import db_now

API = "/api/prorrogas/v2/templates"
RECHAZO_OK = ("{{nombre}}", "{{no_control}}", "{{motivo_rechazo}}")
ANIO = 2090  # sin plantillas reales en la BD de dev (ver test_template_service.py)


def _post(c, data, filename="rechazo.docx", doc_type="carta_rechazo", anio=ANIO):
    return c.post(API, data={"doc_type": doc_type, "anio": str(anio)}, files={"archivo": (filename, data)})


def test_anonimo_recibe_401(client):
    assert client.get(API).status_code == 401


def test_estudiante_recibe_403(client_as, estudiante):
    assert client_as(estudiante).get(API).status_code == 403


def test_lista_seis_tipos_y_el_anio_actual(client_as, secretaria):
    body = client_as(secretaria).get(API).json()
    assert [t["code"] for t in body["tipos"]][0] == "formato_solicitud" and len(body["tipos"]) == 6
    assert db_now().year in [a["anio"] for a in body["anios"]]
    for a in body["anios"]:
        assert len(a["plantillas"]) == 6
        assert {p["origen"] for p in a["plantillas"]} <= {"subida", "heredada", "sistema"}


def test_subir_la_vuelve_activa_para_su_anio(client_as, secretaria, docx_con):
    c = client_as(secretaria)
    r = _post(c, docx_con(*RECHAZO_OK))
    assert r.status_code == 201 and r.json()["placeholders"] == ["motivo_rechazo", "no_control", "nombre"]
    anio = next(a for a in c.get(API).json()["anios"] if a["anio"] == ANIO)
    rechazo = next(p for p in anio["plantillas"] if p["doc_type"] == "carta_rechazo")
    assert rechazo["origen"] == "subida" and rechazo["plantilla"]["id"] == r.json()["id"]


@pytest.mark.parametrize("lines, filename, code", [
    ((), "x.docx", "docx_invalido"),                                        # Review Focus 3 (bytes de PDF)
    (RECHAZO_OK + ("{{nombr}}",), "x.docx", "placeholders_desconocidos"),   # Review Focus 4
])
def test_subida_invalida_responde_400_con_codigo(client_as, secretaria, docx_con, lines, filename, code):
    data = b"%PDF-1.7" if not lines else docx_con(*lines)
    r = _post(client_as(secretaria), data, filename=filename)
    assert r.status_code == 400 and r.json()["error"] == code
    if code == "placeholders_desconocidos":
        assert r.json()["desconocidos"] == ["nombr"]


def test_estudiante_no_puede_subir(client_as, estudiante, docx_con):
    assert _post(client_as(estudiante), docx_con(*RECHAZO_OK)).status_code == 403


def test_descarga_subida_y_del_sistema(client_as, secretaria, docx_con):
    c = client_as(secretaria)
    data = docx_con(*RECHAZO_OK)
    tid = _post(c, data).json()["id"]
    r = c.get(f"{API}/{tid}/archivo")
    assert r.status_code == 200 and r.content == data and "wordprocessingml" in r.headers["content-type"]
    r = c.get(f"{API}/sistema/carta_rechazo/archivo")
    assert r.status_code == 200 and r.content == default_template_path("carta_rechazo").read_bytes()
    assert c.get(f"{API}/999999/archivo").status_code == 404


def test_vista_previa_devuelve_pdf_sin_marcadores(client_as, secretaria, monkeypatch):
    seen = {}

    def fake(data, *, kind):
        seen["placeholders"] = find_placeholders(data)
        seen["kind"] = kind
        return b"%PDF-1.4 fake"

    monkeypatch.setattr("itcj2.core.utils.docx_pdf.docx_to_pdf", fake)
    r = client_as(secretaria).get(f"{API}/vista-previa/carta_compromiso_3.pdf?anio={ANIO}")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert seen == {"placeholders": set(), "kind": "prorrogas_documento"}


def test_vista_previa_sin_libreoffice_responde_503(client_as, secretaria, monkeypatch):  # Review Focus 5
    def boom(data, *, kind):
        raise PdfConversionError("LibreOffice no está instalado.")

    monkeypatch.setattr("itcj2.core.utils.docx_pdf.docx_to_pdf", boom)
    r = client_as(secretaria).get(f"{API}/vista-previa/carta_rechazo.pdf?anio={ANIO}")
    assert r.status_code == 503 and r.json()["error"] == "pdf_no_disponible"


def test_vista_previa_tipo_desconocido_404(client_as, secretaria):
    r = client_as(secretaria).get(f"{API}/vista-previa/otro.pdf")
    assert r.status_code == 404 and r.json()["error"] == "tipo_invalido"


def test_marcador_mal_escrito_responde_400_con_la_lista(client_as, secretaria, docx_con):
    r = _post(client_as(secretaria), docx_con(*RECHAZO_OK, "{{Nombre}}"))
    assert r.status_code == 400 and r.json()["error"] == "marcadores_mal_escritos"
    assert r.json()["mal_escritos"] == ["{{Nombre}}"]


# Revisión final del Plan 1 (#1): LibreOffice colgado (timeout) o que no arranca
# (OSError) también es "PDF no disponible", no un 500.
@pytest.mark.parametrize("exc", [subprocess.TimeoutExpired(["soffice"], 60), OSError("soffice no arranca")])
def test_vista_previa_con_libreoffice_colgado_responde_503(client_as, secretaria, monkeypatch, exc):
    def boom(data, *, kind):
        raise exc

    monkeypatch.setattr("itcj2.core.utils.docx_pdf.docx_to_pdf", boom)
    r = client_as(secretaria).get(f"{API}/vista-previa/carta_rechazo.pdf?anio={ANIO}")
    assert r.status_code == 503 and r.json()["error"] == "pdf_no_disponible"
