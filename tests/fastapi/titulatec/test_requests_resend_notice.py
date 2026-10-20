"""«Reenviar aviso» de acceso en Inscritas (spec 2026-09-27 D12, Tarea 7).

Una cuenta que nació con el NIP DEL SII (`nip_source='sii'`) y cuyo correo de
acceso no salió (`access_sent_at` nulo) lleva en «Inscritas» la píldora ámbar
«correo no enviado» y el formulario «Reenviar aviso». El correo no lleva NIP
(el alumno ya sabe el suyo del SII), así que reenviarlo no expone nada.

`POST /titulatec/admin/solicitudes/{id}/reenviar-aviso` →
`EnrollmentRequestService.resend_access_notice`. Contrato que fija este archivo:

- UN código en `perms`: `titulatec.enrollment_request.api.approve`.
- Corte del modo alterno ANTES de abrir sesión (`_alternate_mode_block`).
- Alcance por carrera: fuera de alcance o inexistente = 404 liso.
- Solo `converted` + `nip_source='sii'` + `access_sent_at` nulo + la cuenta
  del control dueña del proceso en que se convirtió: si no, 400 «Esa solicitud
  no tiene un aviso de acceso pendiente.» sin correo.
- Correo SIN NIP (`nip=None`, `nip_source='sii'`), después del commit; sella
  `access_sent_at` si sale. Si no sale, 400 «El correo no salió; intenta más
  tarde.» y la fila sigue marcada.
- Nunca toca credenciales: ni `hash_nip`, ni `password_hash`, ni
  `must_change_password`.
"""
from __future__ import annotations

import inspect
import re
from datetime import datetime
from urllib.parse import unquote

import pytest

from tests.fastapi.titulatec.conftest import OFFICER_PERMS

URL = "/titulatec/admin/solicitudes"

LIST_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.read.all",
)

MSG_NO_APLICA = "Esa solicitud no tiene un aviso de acceso pendiente."
MSG_NO_SALIO = "El correo no salió; intenta más tarde."
PILDORA = "correo no enviado"
BOTON = "Reenviar aviso"


# ---------------------------------------------------------------------------
# Fixtures y ayudantes
# ---------------------------------------------------------------------------
@pytest.fixture()
def correo(monkeypatch):
    """Espía del correo de acceso: registra cada envío y dice si «salió»."""
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    estado = {"sale": True, "envios": []}

    def _send(db, req, user, *, nip, reassigned=False, nip_source="manual"):
        estado["envios"].append({"req": req.id, "user": user.id, "nip": nip,
                                 "reassigned": reassigned, "nip_source": nip_source})
        return estado["sale"]

    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        staticmethod(_send))
    return estado


@pytest.fixture()
def hash_nip_espia(monkeypatch):
    """Cualquier `hash_nip` durante la prueba queda registrado (import local o no).

    El armado de la prueba también lo llama (`_cuenta`): cada prueba vacía la
    lista justo antes de la acción que mide."""
    llamadas = []
    monkeypatch.setattr("itcj2.core.utils.security.hash_nip",
                        lambda nip: llamadas.append("hash_nip") or "no-debe-usarse")
    return llamadas


def _cuenta(db_session, control):
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import hash_nip

    user = User(username=control, control_number=control, first_name="EGRESADA",
                last_name="DEL SII", password_hash=hash_nip("1357"),
                must_change_password=False, is_active=True)
    db_session.add(user)
    db_session.flush()
    return user


def _inscrita(db_session, make_process, cohort, *, control, nip_source="sii",
              access_sent_at=None, status="converted", program=None, con_cuenta=True):
    """Solicitud que se convirtió con la cuenta de su control (la que creó).

    `con_cuenta=False`: el proceso es de OTRA cuenta y el control no tiene
    ninguna (lo que `_create_account` nunca deja, pero la guarda lo exige).
    """
    from itcj2.apps.titulatec.models import EnrollmentRequest

    if con_cuenta:
        user = _cuenta(db_session, control)
        dueno = user
    else:
        user = None
        dueno = _cuenta(db_session, f"{control[:-1]}9")
    proc = make_process(dueno, cohort=cohort, program=program)
    req = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADA", last_name="DEL SII", middle_name=None,
        program_id=getattr(program, "id", program), program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email="aviso@example.invalid",
        has_efirma=True, kind="unknown", status=status, verify_send_count=0,
        converted_process_id=proc.id, nip_source=nip_source,
        access_granted_at=datetime.now(), access_sent_at=access_sent_at,
        reviewed_at=datetime.now(),
    )
    db_session.add(req)
    db_session.flush()
    return req, user


def _post(c, req, *, status="converted", cohort_id=""):
    return c.post(f"{URL}/{req.id}/reenviar-aviso",
                  data={"status": status, "cohort_id": cohort_id},
                  follow_redirects=False)


def _fila(html: str, req) -> str:
    marca = f'id="tt-req-{req.id}"'
    assert marca in html, f"no está la fila de la solicitud {req.id}"
    return html.split(marca, 1)[1].split("</tr>", 1)[0]


def _plano(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def _marcada(fila: str, req) -> bool:
    """¿La fila ofrece reenviar el aviso? (formulario + píldora)."""
    return f'hx-post="{URL}/{req.id}/reenviar-aviso"' in fila


# ---------------------------------------------------------------------------
# Camino feliz: la píldora aparece, se reenvía y desaparece
# ---------------------------------------------------------------------------
def test_reenviar_aviso_manda_el_correo_sin_nip_sella_y_quita_la_pildora(
    client_as, db_session, make_head, make_cohort, make_process, modo_sii, correo,
    hash_nip_espia,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req, user = _inscrita(db_session, make_process, cohort, control="99670001")
    clave_antes = user.password_hash
    c = client_as(head)

    antes = _fila(c.get(f"{URL}/body?status=converted&cohort_id={cohort.id}").text, req)
    assert PILDORA in _plano(antes)
    assert _marcada(antes, req)
    assert BOTON in _plano(antes)
    hash_nip_espia.clear()

    resp = _post(c, req, cohort_id=str(cohort.id))

    assert resp.status_code == 200, unquote(resp.headers.get("X-Tt-Error", ""))
    assert unquote(resp.headers["X-Tt-Notice"]) == "Aviso reenviado."
    assert resp.headers["X-Tt-Notice-Kind"] == "success"
    assert 'id="tt-requests-body"' in resp.text
    # El correo: el de acceso del SII, SIN NIP, a la cuenta que creó la solicitud.
    assert correo["envios"] == [{"req": req.id, "user": user.id, "nip": None,
                                 "reassigned": False, "nip_source": "sii"}]
    db_session.refresh(req)
    db_session.refresh(user)
    assert req.access_sent_at is not None
    # Nunca toca credenciales.
    assert hash_nip_espia == []
    assert user.password_hash == clave_antes
    assert user.must_change_password is False
    # La bandeja devuelta ya no la marca, y sigue en «Inscritas».
    despues = _fila(resp.text, req)
    assert PILDORA not in _plano(despues)
    assert not _marcada(despues, req)
    activa = re.search(r'id="tt-req-tab-([a-z_]+)"[^>]*aria-current="true"', resp.text)
    assert activa and activa.group(1) == "converted"


def test_en_todas_la_fila_inscrita_tambien_ofrece_reenviar(
    client_as, db_session, make_head, make_cohort, make_process, modo_sii, correo,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req, _user = _inscrita(db_session, make_process, cohort, control="99670002")

    fila = _fila(client_as(head).get(f"{URL}/body?status=all&cohort_id={cohort.id}").text,
                 req)

    assert PILDORA in _plano(fila)
    assert _marcada(fila, req)


# ---------------------------------------------------------------------------
# Cuándo NO aplica: sin píldora en la bandeja y 400 en la ruta
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("caso", [
    "ya_salio", "nip_center", "nip_form", "nip_nulo", "liga_enviada", "por_revisar",
    "rechazada", "sin_cuenta",
])
def test_si_no_hay_aviso_pendiente_no_se_ofrece_y_la_ruta_da_400(
    client_as, db_session, make_head, make_cohort, make_process, modo_sii, correo, caso,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    kw = {
        "ya_salio": dict(access_sent_at=datetime(2026, 9, 1, 10, 0)),
        "nip_center": dict(nip_source="center"),
        "nip_form": dict(nip_source="form"),
        "nip_nulo": dict(nip_source=None),
        "liga_enviada": dict(status="approved"),
        "por_revisar": dict(status="pending_review"),
        "rechazada": dict(status="rejected"),
        "sin_cuenta": dict(con_cuenta=False),
    }[caso]
    req, _user = _inscrita(db_session, make_process, cohort, control="99670010", **kw)
    enviado_antes = req.access_sent_at
    c = client_as(head)

    if caso != "sin_cuenta":
        # La bandeja no la marca (con `sin_cuenta` sí: la píldora solo lee la
        # solicitud; la ruta es la que no encuentra a quién avisar).
        fila = _fila(c.get(f"{URL}/body?status=all&cohort_id={cohort.id}").text, req)
        assert not _marcada(fila, req)
        assert BOTON not in _plano(fila)
    resp = _post(c, req)

    assert resp.status_code == 400
    assert unquote(resp.headers["X-Tt-Error"]) == MSG_NO_APLICA
    assert "X-Tt-Notice" not in resp.headers
    assert correo["envios"] == []
    db_session.refresh(req)
    assert req.access_sent_at == enviado_antes


def test_si_el_correo_no_sale_da_400_y_la_fila_sigue_marcada(
    client_as, db_session, make_head, make_cohort, make_process, modo_sii, correo,
    hash_nip_espia,
):
    correo["sale"] = False
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req, _user = _inscrita(db_session, make_process, cohort, control="99670003")
    c = client_as(head)
    hash_nip_espia.clear()

    resp = _post(c, req)

    assert resp.status_code == 400
    assert unquote(resp.headers["X-Tt-Error"]) == MSG_NO_SALIO
    assert len(correo["envios"]) == 1
    db_session.refresh(req)
    assert req.access_sent_at is None
    assert hash_nip_espia == []
    fila = _fila(c.get(f"{URL}/body?status=converted&cohort_id={cohort.id}").text, req)
    assert PILDORA in _plano(fila) and _marcada(fila, req)


# ---------------------------------------------------------------------------
# Autorización, alcance y modo
# ---------------------------------------------------------------------------
def test_fuera_de_alcance_o_inexistente_da_404_y_dentro_si_reenvia(
    client_as, db_session, make_officer, make_program, make_cohort, make_process,
    modo_sii, correo,
):
    mia, ajena = make_program("Ing. Aviso Mia"), make_program("Ing. Aviso Ajena")
    encargado, _pos = make_officer([mia], perm_codes=OFFICER_PERMS + LIST_PERMS[:3])
    cohort = make_cohort(status="open")
    req_ajena, _ = _inscrita(db_session, make_process, cohort, control="99670004",
                             program=ajena)
    req_mia, _ = _inscrita(db_session, make_process, cohort, control="99670005",
                           program=mia)
    c = client_as(encargado)

    r_ajena = _post(c, req_ajena)
    r_inexistente = c.post(f"{URL}/999999999/reenviar-aviso", data={},
                           follow_redirects=False)
    r_mia = _post(c, req_mia)

    for r in (r_ajena, r_inexistente):
        assert r.status_code == 404
        assert "X-Tt-Error" not in r.headers
    assert r_mia.status_code == 200
    assert [e["req"] for e in correo["envios"]] == [req_mia.id]
    db_session.refresh(req_ajena)
    assert req_ajena.access_sent_at is None


def test_sin_el_permiso_de_aprobar_no_pasa(
    client_as, db_session, make_app_user_without_perms, make_cohort, make_process,
    modo_sii, correo,
):
    solo_ve = make_app_user_without_perms(perm_codes=(
        "titulatec.enrollment_request.page.list", "titulatec.process.api.read.all"))
    cohort = make_cohort(status="open")
    req, _ = _inscrita(db_session, make_process, cohort, control="99670006")

    resp = _post(client_as(solo_ve), req)

    assert resp.status_code == 403
    assert correo["envios"] == []


def test_la_ruta_pide_exactamente_el_permiso_de_aprobar():
    """UN código en `perms`: la lista es OR y uno de más abre la ruta."""
    from itcj2.apps.titulatec.pages import requests_admin

    fuente = inspect.getsource(requests_admin.resend_notice)
    assert "perms=_APPROVE)" in fuente
    assert requests_admin._APPROVE == ["titulatec.enrollment_request.api.approve"]


def test_la_ruta_tiene_su_nombre():
    from itcj2.apps.titulatec.pages.requests_admin import router

    rutas = {r.name: r for r in router.routes}
    ruta = rutas["titulatec.pages.requests.resend_notice"]
    assert ruta.path.endswith("/{req_id}/reenviar-aviso")
    assert ruta.methods == {"POST"}


def test_en_modo_alterno_la_ruta_da_400_y_la_bandeja_solo_informa(
    client_as, db_session, make_head, make_cohort, make_process, modo_alterno, correo,
):
    """Solo lectura (spec 2026-09-24 §8.1): la píldora informa, pero no hay
    formulario, y un POST directo se corta antes de abrir sesión (una
    inexistente también da 400, no 404)."""
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req, _ = _inscrita(db_session, make_process, cohort, control="99670007")
    c = client_as(head)

    fila = _fila(c.get(f"{URL}/body?status=converted&cohort_id={cohort.id}").text, req)
    resp = _post(c, req)
    inexistente = c.post(f"{URL}/999999999/reenviar-aviso", data={},
                         follow_redirects=False)

    assert PILDORA in _plano(fila)
    assert not _marcada(fila, req)
    for r in (resp, inexistente):
        assert r.status_code == 400
        assert unquote(r.headers["X-Tt-Error"]) == (
            "En este modo la revisión la hace Centro de Cómputo.")
    assert correo["envios"] == []


# ---------------------------------------------------------------------------
# Servicio: invariantes de orden
# ---------------------------------------------------------------------------
def _cuerpo(fn) -> str:
    src = inspect.getsource(fn)
    _, _, cuerpo = src.partition('"""')
    _, _, cuerpo = cuerpo.partition('"""')
    return cuerpo


def test_el_servicio_toma_lock_y_refresca_antes_de_leer_el_estado():
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cuerpo = _cuerpo(EnrollmentRequestService.resend_access_notice)
    lock_pos = cuerpo.index("pg_advisory_xact_lock")
    refresh_pos = cuerpo.index("db.refresh(req)")
    assert lock_pos < refresh_pos < cuerpo.index("req.status")


def test_el_correo_sale_despues_del_commit_y_sin_nip():
    """Correo después del commit (suelta el lock; un `requests.post` dentro de
    la transacción lo retendría) y el NIP en `None`: no hay credencial que
    mandar, la cuenta ya tiene el NIP del SII."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cuerpo = _cuerpo(EnrollmentRequestService.resend_access_notice)
    assert cuerpo.index("db.commit()") < cuerpo.index("_mail_access(")
    assert re.search(r"_mail_access\(\s*db,\s*req,\s*user,\s*None,\s*nip_source=\"sii\"\)",
                     cuerpo)
    assert "hash_nip" not in cuerpo and "password_hash" not in cuerpo


def test_el_servicio_devuelve_el_motivo_sin_ruta(
    db_session, make_cohort, make_process, modo_sii, correo,
):
    """El contrato `(ok, detalle)` del servicio, sin HTTP."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort(status="open")
    req, _ = _inscrita(db_session, make_process, cohort, control="99670008")
    otra, _ = _inscrita(db_session, make_process, cohort, control="99670009",
                        nip_source="center")

    assert EnrollmentRequestService.resend_access_notice(db_session, req.id) == (True, "")
    assert EnrollmentRequestService.resend_access_notice(db_session, req.id) == (
        False, MSG_NO_APLICA), "ya salió: no se reenvía dos veces"
    assert EnrollmentRequestService.resend_access_notice(db_session, otra.id) == (
        False, MSG_NO_APLICA)
    assert len(correo["envios"]) == 1
