import base64
import struct
import zlib
from io import BytesIO

import pytest
from PIL import Image

from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.request_service import RequestService
from itcj2.apps.prorrogas_tec.services.signature import parse_signature
from tests.fastapi.prorrogas_tec.conftest import STUDENT_PERMS

pytestmark = pytest.mark.usefixtures("pdf_falso")
MOTIVO = "El pago de nómina de mis padres se retrasó este mes."


def _crear(db, alumno, prog, firma, **kw):
    datos = dict(plazos=2, motivo=MOTIVO, program_id=prog.id, firma=firma, ip="10.0.0.2", user_agent="pytest")
    datos.update(kw)
    return RequestService.create(db, alumno, **datos)


def test_crea_solicitud_con_formato_firmado(db_session, alumno_unido, make_program, firma_png):
    req = _crear(db_session, alumno_unido, make_program("Ingeniería de Prueba", "licenciatura"), firma_png)
    out = RequestService.request_out(db_session, req)
    assert out["estado"] == "pendiente" and out["documentos"][0]["tipo"] == "formato_solicitud"
    assert out["documentos"][0]["firmado"] is True and req.period_label


def test_doble_envio_solo_crea_una(db_session, alumno_unido, make_program, firma_png):  # Review Focus 1
    prog = make_program("Ingeniería de Prueba", "licenciatura")
    _crear(db_session, alumno_unido, prog, firma_png)
    with pytest.raises(ServiceError) as e:
        _crear(db_session, alumno_unido, prog, firma_png)
    assert e.value.code == "solicitud_abierta" and e.value.status == 409


def test_sin_union_no_puede_solicitar(db_session, estudiante, periodo_hoy, make_program, firma_png):
    with pytest.raises(ServiceError) as e:
        _crear(db_session, estudiante, make_program("Ingeniería de Prueba", "licenciatura"), firma_png)
    assert e.value.code == "sin_acceso"


def test_tras_cancelar_hay_que_unirse_otra_vez(db_session, alumno_unido, make_program, firma_png):
    prog = make_program("Ingeniería de Prueba", "licenciatura")
    req = _crear(db_session, alumno_unido, prog, firma_png)
    RequestService.cancel(db_session, req.id, alumno_unido.id)
    with pytest.raises(ServiceError) as e:
        _crear(db_session, alumno_unido, prog, firma_png)
    assert e.value.code == "sin_acceso"


@pytest.mark.parametrize("kw, code", [({"plazos": 4}, "plazos_invalidos"), ({"motivo": "corto"}, "motivo_invalido")])
def test_datos_invalidos(db_session, alumno_unido, make_program, firma_png, kw, code):
    with pytest.raises(ServiceError) as e:
        _crear(db_session, alumno_unido, make_program("Ingeniería de Prueba", "licenciatura"), firma_png, **kw)
    assert e.value.code == code


def _png(size, color):
    buf = BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_firma_vacia_o_enorme():  # Review Focus 3
    with pytest.raises(ServiceError) as e:
        parse_signature("data:image/png;base64," + _png((600, 180), (0, 0, 0, 0)))
    assert e.value.code == "firma_vacia"
    with pytest.raises(ServiceError) as e:
        parse_signature(_png((2500, 100), (0, 0, 0, 255)))
    assert e.value.code == "firma_muy_grande"
    with pytest.raises(ServiceError) as e:
        parse_signature("no-es-base64!!")
    assert e.value.code == "firma_invalida"


def test_api_crear_ver_y_no_ver_lo_ajeno(client_as, alumno_unido, make_user, make_program, firma_png,
                                         grant, make_role):
    prog = make_program("Ingeniería de Prueba", "licenciatura")
    c = client_as(alumno_unido)
    firma = "data:image/png;base64," + base64.b64encode(firma_png).decode()
    r = c.post("/api/prorrogas/v2/estudiante/solicitudes",
               json={"plazos": 2, "motivo": MOTIVO, "program_id": prog.id, "firma": firma})
    assert r.status_code == 201 and r.json()["folio"].startswith("PR-")
    estado = c.get("/api/prorrogas/v2/estudiante/estado").json()
    assert estado["puede_solicitar"] is False and estado["motivo"] == "solicitud_abierta"
    doc = estado["solicitudes"][0]["documentos"][0]
    assert c.get(f"/api/prorrogas/v2/estudiante/solicitudes/{r.json()['id']}/documentos/{doc['id']}.pdf").status_code == 200
    ajeno = make_user(control_number="99500009")
    grant(ajeno, make_role("student", STUDENT_PERMS))  # con permisos: llega al filtro de dueño
    ca = client_as(ajeno)
    assert ca.get(
        f"/api/prorrogas/v2/estudiante/solicitudes/{r.json()['id']}/documentos/{doc['id']}.pdf").status_code == 404
    assert ca.post(f"/api/prorrogas/v2/estudiante/solicitudes/{r.json()['id']}/cancelar").status_code == 404


def _chunk(tag, body):
    return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))


def _png_crudo(w, h, idat=b""):
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def test_firma_bomba_y_corrupta_no_dan_500():
    with pytest.raises(ServiceError) as e:
        parse_signature(base64.b64encode(_png_crudo(20000, 20000)).decode())
    assert e.value.code == "firma_muy_grande"
    buf = BytesIO()
    Image.effect_noise((100, 100), 80).convert("RGBA").save(buf, "PNG")
    bueno = buf.getvalue()
    corrupto = bueno[:len(bueno) // 2] + b"basura" + bueno[-12:]
    with pytest.raises(ServiceError) as e:
        parse_signature(base64.b64encode(corrupto).decode())
    assert e.value.code == "firma_invalida"


def test_firma_base64_enorme_y_rgb_sin_alfa():
    with pytest.raises(ServiceError) as e:
        parse_signature("A" * 300_000)
    assert e.value.code == "firma_muy_grande"
    buf = BytesIO()
    Image.new("RGB", (100, 50), (255, 255, 255)).save(buf, "PNG")
    with pytest.raises(ServiceError) as e:
        parse_signature(base64.b64encode(buf.getvalue()).decode())
    assert e.value.code == "firma_invalida"


def test_integrity_error_se_mapea_a_solicitud_abierta(db_session, alumno_unido, periodo_hoy, make_program,
                                                      firma_png, monkeypatch):
    prog = make_program("Ingeniería de Prueba", "licenciatura")
    _crear(db_session, alumno_unido, prog, firma_png)
    monkeypatch.setattr(RequestService, "access", staticmethod(lambda *a, **k: (periodo_hoy, None)))
    with pytest.raises(ServiceError) as e:
        _crear(db_session, alumno_unido, prog, firma_png)  # el índice único dispara en el flush
    assert e.value.code == "solicitud_abierta" and e.value.status == 409
