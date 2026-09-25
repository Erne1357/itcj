"""Bandeja «Accesos» de Centro de Cómputo (`pages/access_admin.py`, spec 2026-09-24 §8.2).

Lo que fija este archivo es la RUTA: permisos (un código por ruta), pestañas por
modo, qué ofrece cada fila y qué acción vale en cada modo. La máquina de estados
en sí (`grant_access`, `return_to_review`, `reassign_nip`, `approve` alterno) ya
la cubre `test_enrollment_access_service.py`.

Modo (`EnrollmentRequestService.reviewer_mode()`):

- OFICIAL (`school_services`): SE aprueba; aquí CC da el NIP («Por dar acceso»,
  `awaiting_access`), ve a quién ya se lo dio («Con acceso») y lo que devolvió a
  SE («Devueltas»). Rechazar y reenviar la liga NO son suyos: 400.
- ALTERNO (`computer_center`): CC revisa todo (aprueba con NIP o liga, rechaza,
  reenvía); devolver a SE no existe: 400.

CC NO tiene alcance por carrera: ve todo sin `core_program_positions` (patrón
GTV). El actor es sintético con rol DIRECTO y los 4 permisos: en CI no hay DML,
así que `make_role` los siembra; el reparto real (rol `titulatec_computer_center`
por puesto) lo verifica `test_permissions_contract.py`.

Review Focus 3 (CC en modo oficial no aprueba ni rechaza una `pending_review`) y
4 (el NIP nunca vuelve al navegador) se prueban aquí.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

import pytest

URL = "/titulatec/admin/accesos"
SE_URL = "/titulatec/admin/solicitudes"
# Cuatro dígitos que no aparecen en el HTML de la bandeja (ni en STATIC_VERSION):
# cada prueba que lo busca verifica esa premisa antes de actuar.
NIP = "4826"

CC_PERMS = (
    "titulatec.enrollment_access.page.list",
    "titulatec.enrollment_access.api.grant",
    "titulatec.enrollment_access.api.return",
    "titulatec.enrollment_access.api.reject",
)
SE_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.read.all",
)
OFICIAL = ["Por dar acceso", "Con acceso", "Devueltas"]
ALTERNO = ["Por revisar", "Liga enviada", "Inscritas", "Rechazadas", "Todas"]
YA_TIENE_CUENTA = "Ya tiene cuenta: se enviará liga"
DESACTIVADA = "Cuenta desactivada: se reactiva al abrir la liga"
# El aviso de identidad de Solicitudes (`requests_body.html`), con el correo a la vista.
AVISO_IDENTIDAD = ("La liga de activación irá a {correo}, que escribió el solicitante. "
                   "Confirma su identidad antes de {accion}.")


# ---------------------------------------------------------------------------
# Fixtures y helpers locales (patrón de la suite: no se importan de otro archivo)
# ---------------------------------------------------------------------------
@pytest.fixture()
def make_cc(make_user, make_role, grant_user_role):
    """Actor sintético de Centro de Cómputo: rol DIRECTO con los 4 permisos."""
    def _make(perm_codes=CC_PERMS, first_name="CENTRO", last_name="COMPUTO"):
        user = make_user(first_name=first_name, last_name=last_name)
        grant_user_role(user, make_role("tt_test_computer_center", perm_codes))
        return user

    return _make


@pytest.fixture()
def correo_falso(monkeypatch):
    """Captura los envíos sin tocar Graph: `(asunto, destinatarios, html)`."""
    enviados = []

    class _Resp:
        status_code = 202
        text = ""

    def _fake_send(access_token, subject, content_html, to_list, save_to_sent=True):
        enviados.append((subject, list(to_list), content_html))
        return _Resp()

    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent",
                        lambda app_key: "token-de-prueba")
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", _fake_send)
    return enviados


# `modo_alterno` vive en conftest.py (C7/I-1 de la revision final: una sola
# copia compartida en vez de 4 duplicadas por archivo).


def _make_req(db_session, cohort, *, control, status="pending_review", program=None,
              email="acceso@example.invalid", **kw):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADA", last_name="DE COMPUTO", middle_name=None,
        program_id=getattr(program, "id", program), program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email=email,
        has_efirma=False, kind="unknown", status=status, verify_send_count=0,
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row


def _en_espera(db_session, cohort, *, control, reviewed_at=None, **kw):
    """Solicitud que SE ya aprobó y espera a Centro de Cómputo."""
    return _make_req(db_session, cohort, control=control, status="awaiting_access",
                     reviewed_at=reviewed_at or datetime.now() - timedelta(hours=2), **kw)


def _cuenta(db_session, control, *, password=True, is_active=True):
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import hash_nip

    user = User(username=control, control_number=control, first_name="YA",
                last_name="EXISTIA", password_hash=hash_nip("9999") if password else None,
                is_active=is_active)
    db_session.add(user)
    db_session.flush()
    return user


def _plano(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def _plano_correo(html: str) -> str:
    """`_plano` sin partir el correo en su `<wbr>` ni en su `<strong>`."""
    return _plano(re.sub(r"</?(wbr|strong)>", "", html))


def _fila(html: str, req) -> str:
    """El `<tr>` de una solicitud. Los ids estables de fila son parte del contrato."""
    marca = f'id="tt-acc-{req.id}"'
    assert marca in html, f"no está la fila de la solicitud {req.id}"
    return html.split(marca, 1)[1].split("</tr>", 1)[0]


def _pestana_activa(html: str) -> str:
    activa = re.search(r'<button[^>]*id="tt-acc-tab-([a-z_]+)"[^>]*aria-current="true"', html)
    assert activa, "ninguna pestaña se anuncia como activa"
    return activa.group(1)


def _error(resp) -> str:
    return unquote(resp.headers.get("X-Tt-Error", ""))


def _aviso(resp) -> tuple[str, str]:
    """`X-Tt-Notice` (percent-encoded, como `_hdr`) y su tipo."""
    return (unquote(resp.headers.get("X-Tt-Notice", "")),
            resp.headers.get("X-Tt-Notice-Kind", ""))


def _folio(db_session, req) -> str:
    from itcj2.apps.titulatec.models import TitulationProcess

    db_session.refresh(req)
    return db_session.get(TitulationProcess, req.converted_process_id).folio


def _sin_nip(resp) -> None:
    """Review Focus 4: el NIP no vuelve al navegador, ni en el cuerpo ni en cabeceras."""
    assert NIP not in resp.text
    assert NIP not in " ".join(f"{k}: {v}" for k, v in resp.headers.items())


# ---------------------------------------------------------------------------
# Acceso y menú
# ---------------------------------------------------------------------------
def test_sin_el_permiso_de_la_bandeja_no_entra(client_as, make_head):
    """La jefa de Escolares tiene la app, no `enrollment_access.page.list`."""
    resp = client_as(make_head()).get(URL)

    assert resp.status_code == 403, resp.text[:300]


def test_el_menu_muestra_accesos_solo_con_page_list(client_as, make_head, make_cc):
    sin_permiso = client_as(make_head()).get("/titulatec/admin/documents")
    assert sin_permiso.status_code == 200, sin_permiso.text[:500]
    assert f'"{URL}"' not in sin_permiso.text

    con_permiso = client_as(make_cc()).get(URL)
    assert con_permiso.status_code == 200, con_permiso.text[:500]
    assert f'hx-get="{URL}"' in con_permiso.text
    assert "Accesos" in con_permiso.text
    assert "bi-key" in con_permiso.text


def test_cada_ruta_exige_un_solo_codigo():
    """La lista de `perms=` es OR: un código de más abre la acción entera."""
    from itcj2.apps.titulatec.pages import access_admin

    assert access_admin._LIST == ["titulatec.enrollment_access.page.list"]
    assert access_admin._GRANT == ["titulatec.enrollment_access.api.grant"]
    assert access_admin._RETURN == ["titulatec.enrollment_access.api.return"]
    assert access_admin._REJECT == ["titulatec.enrollment_access.api.reject"]


# Cada POST con el ÚNICO código que debe exigir (spec §8.2 / §7). Las que emiten
# credenciales (dar-acceso, reasignar-nip) son las que no pueden caer a `page.list`.
_RUTAS_POST = [
    ("dar-acceso", "titulatec.enrollment_access.api.grant", {"nip": NIP}),
    ("devolver", "titulatec.enrollment_access.api.return", {"note": "No coincide."}),
    ("rechazar", "titulatec.enrollment_access.api.reject", {"note": "No procede."}),
    ("reenviar", "titulatec.enrollment_access.api.grant", {}),
    ("reasignar-nip", "titulatec.enrollment_access.api.grant", {"nip": NIP}),
]


@pytest.fixture()
def make_cc_parcial(make_user, make_role, grant_user_role):
    """Actor con SOLO los códigos dados, en un rol propio: `make_role` es
    aditivo por nombre, así que reusar `tt_test_computer_center` le daría los 4."""
    def _make(role_name, perm_codes):
        user = make_user(first_name="CENTRO", last_name="PARCIAL")
        grant_user_role(user, make_role(role_name, perm_codes))
        return user

    return _make


@pytest.mark.parametrize("accion,codigo,data", _RUTAS_POST,
                         ids=[r[0] for r in _RUTAS_POST])
def test_cada_post_exige_su_codigo_y_la_vista_sola_no_basta(
    client_as, db_session, make_cc_parcial, make_cohort, correo_falso,
    accion, codigo, data,
):
    """C8: `test_cada_ruta_exige_un_solo_codigo` solo compara constantes; esto ata
    cada ruta a SU código. Un `perms=_LIST` copiado en dar-acceso o
    reasignar-nip abriría la emisión de NIP a quien solo ve la bandeja."""
    from itcj2.core.models.user import User

    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710300")
    solo_vista = make_cc_parcial("tt_test_cc_solo_lista",
                                 ["titulatec.enrollment_access.page.list"])

    resp = client_as(solo_vista).post(f"{URL}/{req.id}/{accion}", data=data)

    assert resp.status_code == 403, (accion, resp.status_code)
    db_session.refresh(req)
    assert req.status == "awaiting_access"
    assert req.access_granted_at is None and req.returned_at is None
    assert db_session.query(User).filter_by(control_number="99710300").count() == 0
    assert correo_falso == []

    # Con SOLO su código pasa el gate: puede responder 400 (modo) o 404 (no
    # existe), nunca 403. Una solicitud inexistente no deja nada escrito.
    solo_su_codigo = make_cc_parcial(f"tt_test_cc_solo_{codigo.rsplit('.', 1)[1]}", [codigo])
    resp = client_as(solo_su_codigo).post(f"{URL}/987654321/{accion}", data=data)

    assert resp.status_code != 403, (accion, codigo)
    assert resp.status_code in (400, 404), (accion, resp.status_code)


def test_la_bandeja_usa_los_estados_por_revisar_del_servicio_no_una_copia():
    """Una copia de `_REVIEWABLE` se desincroniza en silencio el día que el
    servicio sume un estado revisable: la bandeja lo escondería."""
    from itcj2.apps.titulatec.pages import access_admin
    from itcj2.apps.titulatec.services import enrollment_request_service as svc

    assert access_admin._REVIEWABLE is svc._REVIEWABLE


# ---------------------------------------------------------------------------
# Modo oficial: pestañas y filas
# ---------------------------------------------------------------------------
def test_cc_ve_todas_las_carreras_sin_puestos_por_carrera(
    client_as, db_session, make_cc, make_cohort, make_program,
):
    cc = make_cc()
    cohort = make_cohort(status="open")
    a = _en_espera(db_session, cohort, control="99710001",
                   program=make_program("Ingenieria Accesos Uno"))
    b = _en_espera(db_session, cohort, control="99710002",
                   program=make_program("Ingenieria Accesos Dos"))
    sin_carrera = _en_espera(db_session, cohort, control="99710003")

    html = client_as(cc).get(f"{URL}/body?cohort_id={cohort.id}").text

    for req in (a, b, sin_carrera):
        _fila(html, req)
    assert "Ingenieria Accesos Uno" in html and "Ingenieria Accesos Dos" in html
    assert "Sin alcance" not in html


def test_la_bandeja_oficial_abre_en_por_dar_acceso_con_sus_tres_pestanas(
    client_as, db_session, make_cc, make_cohort,
):
    cc = make_cc()
    cohort = make_cohort(status="open")
    espera = _en_espera(db_session, cohort, control="99710010")
    por_revisar = _make_req(db_session, cohort, control="99710011")

    resp = client_as(cc).get(f"{URL}?cohort_id={cohort.id}")

    assert resp.status_code == 200, resp.text[:500]
    texto = _plano(resp.text)
    posiciones = [texto.index(p) for p in OFICIAL]
    assert posiciones == sorted(posiciones)
    for ajena in ("Liga enviada", "Inscritas", "Rechazadas"):
        assert f'>{ajena}<' not in resp.text
    assert _pestana_activa(resp.text) == "awaiting_access"
    assert 'id="tt-access-body"' in resp.text
    _fila(resp.text, espera)
    assert f'id="tt-acc-{por_revisar.id}"' not in resp.text, "no es trabajo de CC"


def test_por_dar_acceso_es_fifo_por_la_aprobacion_de_se(
    client_as, db_session, make_cc, make_cohort,
):
    cc = make_cc()
    cohort = make_cohort(status="open")
    nueva = _en_espera(db_session, cohort, control="99710020",
                       reviewed_at=datetime(2026, 9, 22, 10, 0))
    vieja = _en_espera(db_session, cohort, control="99710021",
                       reviewed_at=datetime(2026, 9, 20, 10, 0))

    html = client_as(cc).get(f"{URL}/body?cohort_id={cohort.id}").text

    assert html.index(f'id="tt-acc-{vieja.id}"') < html.index(f'id="tt-acc-{nueva.id}"')


def test_una_pestana_desconocida_o_del_otro_modo_cae_en_la_de_omision(
    client_as, db_session, make_cc, make_cohort,
):
    cc = make_cc()
    c = client_as(cc)

    for pedida in ("cualquier-cosa", "rejected", "all"):
        assert _pestana_activa(c.get(f"{URL}/body?status={pedida}").text) == "awaiting_access"


def test_la_fila_sin_cuenta_pide_el_nip_y_ofrece_devolver(
    client_as, db_session, make_cc, make_cohort, make_program,
):
    cc = make_cc()
    cohort = make_cohort(status="open", name="Convocatoria Accesos Fila")
    req = _en_espera(db_session, cohort, control="21710030",
                     program=make_program("Ingenieria De La Fila"),
                     reviewed_at=datetime(2026, 9, 21, 9, 30))

    fila = _fila(client_as(cc).get(f"{URL}/body?cohort_id={cohort.id}").text, req)
    texto = _plano(fila)

    # Solicitante (nombre, control, año de ingreso), carrera, contacto, convocatoria/fecha.
    assert "DE COMPUTO" in texto and "EGRESADA" in texto and "21710030" in texto
    assert "2021" in texto, "año de ingreso vía entry_year"
    assert "Ingenieria De La Fila" in texto
    assert "acceso@example.invalid" in fila.replace("<wbr>", "")
    assert "6561234567" in texto
    assert "Convocatoria Accesos Fila" in texto
    assert "Aprobada por Servicios Escolares 21/09/2026" in texto, "sin la sigla «SE»"
    # Dar acceso con NIP.
    assert f'hx-post="{URL}/{req.id}/dar-acceso"' in fila
    nip = re.search(r'<input[^>]*name="nip"[^>]*>', fila)
    assert nip, "falta el campo del NIP"
    for attr in ('inputmode="numeric"', r'pattern="\d{4}"', 'maxlength="4"',
                 'autocomplete="off"'):
        assert attr in nip.group(0), attr
    assert "value=" not in nip.group(0)
    assert YA_TIENE_CUENTA not in texto
    # Devolver con nota (<= 2000).
    assert f'hx-post="{URL}/{req.id}/devolver"' in fila
    nota = re.search(r'<textarea[^>]*name="note"[^>]*>', fila)
    assert nota and 'maxlength="2000"' in nota.group(0) and "required" in nota.group(0)
    # Lo que no es de CC en el modo oficial.
    assert "/rechazar" not in fila and "/reenviar" not in fila


def test_la_fila_con_cuenta_anuncia_la_liga_y_no_pide_nip(
    client_as, db_session, make_cc, make_cohort,
):
    cc = make_cc()
    cohort = make_cohort(status="open")
    _cuenta(db_session, "99710040")
    req = _en_espera(db_session, cohort, control="99710040")
    _cuenta(db_session, "99710041", is_active=False)
    inactiva = _en_espera(db_session, cohort, control="99710041")
    _cuenta(db_session, "99710042", password=False)
    sin_contra = _en_espera(db_session, cohort, control="99710042")

    html = client_as(cc).get(f"{URL}/body?cohort_id={cohort.id}").text
    fila = _fila(html, req)

    assert YA_TIENE_CUENTA in _plano(fila)
    assert 'name="nip"' not in fila
    assert f'hx-post="{URL}/{req.id}/dar-acceso"' in fila
    # C3: SE aprobó cuando no había cuenta y nunca vio el aviso de identidad;
    # CC es el último que puede verlo antes de que la liga salga.
    assert (AVISO_IDENTIDAD.format(correo="acceso@example.invalid", accion="enviarla")
            in _plano_correo(fila))
    assert DESACTIVADA not in _plano(fila)
    assert DESACTIVADA in _plano(_fila(html, inactiva))
    assert "sin contraseña" in _plano(_fila(html, sin_contra))


def test_d10_sin_contrasena_en_modo_oficial_no_ofrece_enviar_liga_sino_devolver(
    client_as, db_session, make_cc, make_cohort,
):
    """La liga exige contraseña (invariante 2): el botón siempre daría 400.
    Lo que CC sí puede hacer es devolverla a SE, y el formulario está ahí."""
    cc = make_cc()
    cohort = make_cohort(status="open")
    _cuenta(db_session, "99710043", password=False)
    sin_contra = _en_espera(db_session, cohort, control="99710043")

    fila = _fila(client_as(cc).get(f"{URL}/body?cohort_id={cohort.id}").text, sin_contra)

    assert f'hx-post="{URL}/{sin_contra.id}/dar-acceso"' not in fila
    assert "Enviar liga" not in fila
    assert ("La cuenta no tiene contraseña: devuélvela a Servicios Escolares"
            in _plano(fila))
    assert f'hx-post="{URL}/{sin_contra.id}/devolver"' in fila
    assert "La liga de activación irá a" not in _plano_correo(fila), "no sale ninguna liga"


# ---------------------------------------------------------------------------
# Modo oficial: acciones
# ---------------------------------------------------------------------------
def test_dar_acceso_sin_cuenta_pasa_a_con_acceso_y_el_nip_solo_va_al_correo(
    client_as, db_session, make_cc, make_cohort, seed_phase_defs, titulatec_app,
    correo_falso,
):
    from itcj2.core.models.user import User

    seed_phase_defs()
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710050")
    c = client_as(cc)
    assert NIP not in c.get(f"{URL}?cohort_id={cohort.id}").text, "premisa del test"

    resp = c.post(f"{URL}/{req.id}/dar-acceso",
                  data={"nip": NIP, "status": "awaiting_access", "cohort_id": str(cohort.id)})

    assert resp.status_code == 200, _error(resp)
    _sin_nip(resp)
    assert _pestana_activa(resp.text) == "awaiting_access"
    assert f'id="tt-acc-{req.id}"' not in resp.text
    db_session.refresh(req)
    assert req.status == "converted"
    assert req.access_granted_by_id == cc.id
    assert db_session.query(User).filter_by(control_number="99710050").count() == 1
    (_asunto, destinatarios, correo), = correo_falso
    assert destinatarios == ["acceso@example.invalid"] and NIP in correo

    con_acceso = c.get(f"{URL}/body?status=granted&cohort_id={cohort.id}")
    fila = _fila(con_acceso.text, req)
    assert "Inscrita" in _plano(fila)
    assert "correo no enviado" not in fila
    # Ruling 2026-09-25 (spec §8.2): «Reasignar NIP» sale cuando la cuenta es
    # elegible (`can_reassign_nip`: creada por la solicitud, nunca ha iniciado
    # sesión), AUNQUE el correo haya salido: un correo mal escrito también «sale».
    assert f'hx-post="{URL}/{req.id}/reasignar-nip"' in fila
    for pestana in ("awaiting_access", "granted", "returned"):
        _sin_nip(c.get(f"{URL}/body?status={pestana}&cohort_id={cohort.id}"))
    _sin_nip(c.get(f"{URL}?cohort_id={cohort.id}"))


def test_dar_acceso_si_aparecio_una_cuenta_manda_la_liga(
    client_as, db_session, make_cc, make_cohort, correo_falso,
):
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710060")
    _cuenta(db_session, "99710060")
    c = client_as(cc)

    resp = c.post(f"{URL}/{req.id}/dar-acceso",
                  data={"nip": NIP, "status": "awaiting_access", "cohort_id": str(cohort.id)})

    assert resp.status_code == 200, _error(resp)
    _sin_nip(resp)
    db_session.refresh(req)
    assert req.status == "approved"
    (_asunto, _dest, correo), = correo_falso
    assert "/inscripcion/verificar?t=" in correo and NIP not in correo
    fila = _fila(c.get(f"{URL}/body?status=granted&cohort_id={cohort.id}").text, req)
    assert "Liga enviada" in _plano(fila)
    assert "correo no enviado" not in fila
    assert "/reasignar-nip" not in fila, "la cuenta no la creó la solicitud"


def test_dar_acceso_avisa_el_folio_y_que_el_correo_salio(
    client_as, db_session, make_cc, make_cohort, seed_phase_defs, titulatec_app,
    correo_falso,
):
    """C4: la fila se va de «Por dar acceso»; sin aviso CC no sabe qué pasó."""
    seed_phase_defs()
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710051")

    resp = client_as(cc).post(f"{URL}/{req.id}/dar-acceso", data={"nip": NIP})

    assert resp.status_code == 200, _error(resp)
    assert _aviso(resp) == (f"Acceso dado · folio {_folio(db_session, req)} · correo enviado",
                            "success")
    _sin_nip(resp)


def test_dar_acceso_con_el_correo_fallido_avisa_que_dicte_o_reasigne_el_nip(
    client_as, db_session, make_cc, make_cohort, seed_phase_defs, titulatec_app,
    monkeypatch,
):
    """El mejor momento para dictar el NIP es este: CC acaba de teclearlo."""
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    seed_phase_defs()
    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        staticmethod(lambda *a, **k: False))
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710052")

    resp = client_as(cc).post(f"{URL}/{req.id}/dar-acceso", data={"nip": NIP})

    assert resp.status_code == 200, _error(resp)
    folio = _folio(db_session, req)
    assert _aviso(resp) == (f"Acceso dado (folio {folio}), pero el correo no salió: dicta el "
                            "NIP o reasígnalo en Con acceso", "warning")
    _sin_nip(resp)


def test_dar_acceso_d10_avisa_que_ya_tenia_cuenta_y_si_la_liga_salio(
    client_as, db_session, make_cc, make_cohort, correo_falso, monkeypatch,
):
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    cc = make_cc()
    cohort = make_cohort(status="open")
    salio = _en_espera(db_session, cohort, control="99710061")
    _cuenta(db_session, "99710061")
    no_salio = _en_espera(db_session, cohort, control="99710062")
    _cuenta(db_session, "99710062")
    c = client_as(cc)

    ok = c.post(f"{URL}/{salio.id}/dar-acceso", data={"nip": NIP})
    monkeypatch.setattr(TitulaTecEmailHelper, "send_verify_enrollment",
                        staticmethod(lambda *a, **k: False))
    falla = c.post(f"{URL}/{no_salio.id}/dar-acceso", data={"nip": NIP})

    assert ok.status_code == falla.status_code == 200, (_error(ok), _error(falla))
    assert _aviso(ok) == ("Ya tenía cuenta: se envió la liga", "success")
    assert _aviso(falla) == ("Ya tenía cuenta: la liga se generó, pero el correo no salió; "
                             "Servicios Escolares puede reenviarla desde Solicitudes",
                             "warning")
    _sin_nip(ok)
    _sin_nip(falla)


def test_un_error_de_dar_acceso_viaja_en_x_tt_error_sin_el_nip(
    client_as, db_session, make_cc, make_cohort,
):
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710070")

    resp = client_as(cc).post(f"{URL}/{req.id}/dar-acceso", data={"nip": "48a6"})

    assert resp.status_code == 400
    assert _error(resp) == "El NIP debe ser exactamente 4 dígitos."
    assert "X-Tt-Notice" not in resp.headers, "un 400 no anuncia éxito"
    assert "48a6" not in " ".join(resp.headers.values()) and "48a6" not in resp.text
    db_session.refresh(req)
    assert req.status == "awaiting_access"


def test_fallo_tras_import_rows_en_dar_acceso_no_deja_huerfanos(
    client_as, db_session, make_cc, make_cohort, seed_phase_defs, titulatec_app,
    correo_falso, monkeypatch,
):
    """`import_rows(commit=False)`: si algo revienta después (aquí, el perfil),
    la ruta hace `rollback()` y no queda un `User`/`TitulationProcess` a medias.
    Repuesto de `test_enrollment_approve.py` (hasta 090cf723^), ahora en la ruta
    que crea la cuenta."""
    import itcj2.core.services.student_profile_service as sps_mod
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import TitulationProcess

    def _boom(db, user_id, **fields):
        raise RuntimeError("mutación deliberada: fallo tras import_rows")

    seed_phase_defs()
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710080")
    # La ruta hace `db.rollback()`: sin este checkpoint se llevaría también los
    # datos del fixture.
    db_session.commit()
    monkeypatch.setattr(sps_mod.StudentProfileService, "set_fields", staticmethod(_boom))

    resp = client_as(cc).post(f"{URL}/{req.id}/dar-acceso", data={"nip": NIP})

    assert resp.status_code == 400
    assert _error(resp) == "No pudimos completar el acceso; intenta de nuevo."
    _sin_nip(resp)
    assert db_session.query(User).filter_by(control_number="99710080").first() is None
    assert db_session.query(TitulationProcess).filter_by(cohort_id=cohort.id).count() == 0
    db_session.refresh(req)
    assert req.status == "awaiting_access"
    assert correo_falso == []


def test_devolver_la_manda_a_devueltas_y_a_por_revisar_de_se_con_la_nota(
    client_as, db_session, make_cc, make_head, make_cohort, correo_falso,
):
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710090")
    nota = "El número de control no coincide con el padrón."
    c = client_as(cc)

    resp = c.post(f"{URL}/{req.id}/devolver",
                  data={"note": nota, "status": "awaiting_access", "cohort_id": str(cohort.id)})

    assert resp.status_code == 200, _error(resp)
    assert f'id="tt-acc-{req.id}"' not in resp.text
    db_session.refresh(req)
    assert req.status == "pending_review" and req.returned_by_id == cc.id
    assert correo_falso == [], "el alumno no se entera"
    devueltas = c.get(f"{URL}/body?status=returned&cohort_id={cohort.id}").text
    assert nota in _plano(_fila(devueltas, req))

    se = client_as(make_head(perm_codes=SE_PERMS)).get(f"{SE_URL}/body?cohort_id={cohort.id}")
    fila_se = se.text.split(f'id="tt-req-{req.id}"', 1)[1].split("</tr>", 1)[0]
    assert f"Devuelta por Centro de Cómputo: {nota}" in _plano(fila_se)


def test_devueltas_dice_que_paso_despues_de_devolverla(
    client_as, db_session, make_cc, make_cohort,
):
    """«Devuelta a Servicios Escolares» se leía como estado actual aunque SE ya
    la hubiera vuelto a aprobar. La fila dice qué hizo CC y qué pasó después."""
    cc = make_cc()
    cohort = make_cohort(status="open")
    cuando = datetime(2026, 9, 21, 9, 0)
    con_se = _make_req(db_session, cohort, control="99710092", returned_at=cuando,
                       return_note="No coincide el nombre.")
    reaprobada = _en_espera(db_session, cohort, control="99710093", returned_at=cuando,
                            return_note="Faltaba la carrera.")
    cancelada = _make_req(db_session, cohort, control="99710094", status="rejected",
                          returned_at=cuando, return_note="Duplicada.",
                          review_note="Duplicada.", rejection_sent_at=datetime.now())

    html = client_as(cc).get(f"{URL}/body?status=returned&cohort_id={cohort.id}").text

    texto = _plano(_fila(html, con_se))
    assert "La devolviste el 21/09/2026 09:00: No coincide el nombre." in texto
    assert "volvió a aprobar" not in texto
    texto = _plano(_fila(html, reaprobada))
    assert "La devolviste el 21/09/2026 09:00: Faltaba la carrera." in texto
    assert "Servicios Escolares la volvió a aprobar" in texto
    texto = _plano(_fila(html, cancelada))
    assert "Servicios Escolares la rechazó" in texto
    assert "Devuelta a Servicios Escolares" not in html


def test_devolver_sin_nota_o_con_una_larga_da_el_motivo(
    client_as, db_session, make_cc, make_cohort,
):
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710091")
    c = client_as(cc)

    vacia = c.post(f"{URL}/{req.id}/devolver", data={"note": "   "})
    larga = c.post(f"{URL}/{req.id}/devolver", data={"note": "x" * 2001})

    assert vacia.status_code == larga.status_code == 400
    assert _error(vacia) == "Escribe el motivo de la devolución."
    assert _error(larga) == "El motivo de la devolución no puede pasar de 2000 caracteres."
    db_session.refresh(req)
    assert req.status == "awaiting_access"


def test_con_acceso_excluye_una_d10_que_volvio_a_una_cola_de_trabajo(
    client_as, db_session, make_cc, make_cohort,
):
    """Una D10 que `verify()` devolvió a `pending_review` conserva
    `access_granted_*`; si SE la vuelve a aprobar sin cuenta, llega a
    `awaiting_access` con ese sello. Las dos viven en una cola de trabajo (la de
    SE o «Por dar acceso»): en «Con acceso» serían un duplicado rancio."""
    cc = make_cc()
    cohort = make_cohort(status="open")
    devuelta = _make_req(db_session, cohort, control="99710100",
                         access_granted_at=datetime.now() - timedelta(days=1))
    reaprobada = _en_espera(db_session, cohort, control="99710102",
                            access_granted_at=datetime.now() - timedelta(days=2))
    inscrita = _make_req(db_session, cohort, control="99710101", status="converted",
                         access_granted_at=datetime.now() - timedelta(days=1),
                         access_sent_at=datetime.now())

    html = client_as(cc).get(f"{URL}/body?status=granted&cohort_id={cohort.id}").text

    _fila(html, inscrita)
    assert f'id="tt-acc-{devuelta.id}"' not in html
    assert f'id="tt-acc-{reaprobada.id}"' not in html


def test_con_acceso_conserva_la_d10_que_se_cancelo(
    client_as, db_session, make_cc, make_cohort,
):
    """Spec §8.2: «Con acceso» = `access_granted_at` no nulo. Una D10 (`approved`,
    liga en camino) que SE canceló queda `rejected` con el sello de CC: es un
    estado final que en el modo oficial no sale en ninguna otra pestaña de CC,
    así que se queda aquí con su etiqueta y el motivo, sin acciones."""
    cc = make_cc()
    cohort = make_cohort(status="open")
    motivo = "Cancelada por Servicios Escolares: duplicada."
    cancelada = _make_req(db_session, cohort, control="99710103", status="rejected",
                          access_granted_at=datetime.now() - timedelta(days=1),
                          review_note=motivo, rejection_sent_at=datetime.now())
    sin_sello = _make_req(db_session, cohort, control="99710104", status="rejected",
                          review_note="No aparece en el padrón.")

    html = client_as(cc).get(f"{URL}/body?status=granted&cohort_id={cohort.id}").text

    fila = _fila(html, cancelada)
    assert "Rechazada" in _plano(fila) and motivo in _plano(fila)
    assert "correo no enviado" not in fila
    assert "hx-post" not in fila, "una rechazada no tiene acciones de CC"
    assert f'id="tt-acc-{sin_sello.id}"' not in html, "sin acceso de CC no es de esta pestaña"


def test_reasignar_solo_se_ofrece_si_es_elegible_y_reenvia_el_nip(
    client_as, db_session, make_cc, make_cohort, seed_phase_defs, titulatec_app,
    correo_falso, monkeypatch,
):
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    seed_phase_defs()
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710110")
    legado = _make_req(db_session, cohort, control="99710111", status="converted")
    c = client_as(cc)
    # El primer correo no sale: la fila queda «correo no enviado».
    envio_real = TitulaTecEmailHelper.send_enrollment_approved
    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        staticmethod(lambda *a, **k: False))
    assert c.post(f"{URL}/{req.id}/dar-acceso", data={"nip": "7391"}).status_code == 200

    html = c.get(f"{URL}/body?status=granted&cohort_id={cohort.id}").text
    fila = _fila(html, req)
    assert "correo no enviado" in fila
    assert f'hx-post="{URL}/{req.id}/reasignar-nip"' in fila
    assert re.search(r'<input[^>]*name="nip"[^>]*autocomplete="off"', fila)
    # Una convertida sin acceso de CC (legado) no está en «Con acceso» ni se reasigna.
    assert f'id="tt-acc-{legado.id}"' not in html

    # Aun con el correo sin salir: si la persona ya inició sesión no se reasigna
    # (revisión final C1: `must_change_password` nunca se limpia en un egresado,
    # la señal es `last_login`).
    from itcj2.core.models.user import User
    cuenta = db_session.query(User).filter_by(control_number="99710110").one()
    assert cuenta.must_change_password is True
    cuenta.last_login = datetime.now()
    db_session.flush()
    fila = _fila(c.get(f"{URL}/body?status=granted&cohort_id={cohort.id}").text, req)
    assert "correo no enviado" in fila
    assert "/reasignar-nip" not in fila
    cuenta.last_login = None
    db_session.flush()

    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved", envio_real)
    resp = c.post(f"{URL}/{req.id}/reasignar-nip",
                  data={"nip": NIP, "status": "granted", "cohort_id": str(cohort.id)})

    assert resp.status_code == 200, _error(resp)
    _sin_nip(resp)
    assert _pestana_activa(resp.text) == "granted"
    fila = _fila(resp.text, req)
    assert "correo no enviado" not in fila
    # El correo salió, pero la persona sigue sin iniciar sesión: el botón sigue
    # (el ruling ya no exige `access_mail_unsent`).
    assert f'hx-post="{URL}/{req.id}/reasignar-nip"' in fila
    (_asunto, _dest, correo), = correo_falso
    assert NIP in correo
    assert "Este NIP reemplaza al que te enviamos antes" in correo
    assert _aviso(resp) == ("NIP reasignado · correo enviado", "success")


def test_el_formulario_de_reasignar_dice_a_donde_va_y_permite_no_mandar_correo(
    client_as, db_session, make_cc, make_cohort, seed_phase_defs, titulatec_app,
    correo_falso,
):
    """Ruling 2026-09-25: el caso del correo mal escrito. CC ve a qué dirección
    saldría y puede reasignar SIN correo para dictarlo por teléfono."""
    seed_phase_defs()
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710112", email="mal.escrito@example.invalid")
    c = client_as(cc)
    assert c.post(f"{URL}/{req.id}/dar-acceso", data={"nip": "7392"}).status_code == 200
    correo_falso.clear()

    fila = _fila(c.get(f"{URL}/body?status=granted&cohort_id={cohort.id}").text, req)
    formulario = fila.split(f'hx-post="{URL}/{req.id}/reasignar-nip"', 1)[1].split("</form>", 1)[0]
    assert "Se enviará a mal.escrito@example.invalid" in _plano(formulario)
    assert re.search(r'<input[^>]*type="checkbox"[^>]*name="no_mail"', formulario)
    assert "No enviar correo; lo dicto por teléfono" in _plano(formulario)

    resp = c.post(f"{URL}/{req.id}/reasignar-nip",
                  data={"nip": NIP, "no_mail": "1", "status": "granted",
                        "cohort_id": str(cohort.id)})

    assert resp.status_code == 200, _error(resp)
    _sin_nip(resp)
    assert correo_falso == [], "con la casilla no sale ningún correo"
    assert _aviso(resp) == ("NIP reasignado; no se envió correo", "success")
    db_session.refresh(req)
    assert req.access_sent_at is None
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import verify_nip
    cuenta = db_session.query(User).filter_by(control_number="99710112").one()
    assert verify_nip(NIP, cuenta.password_hash)


def test_reasignar_con_el_correo_fallido_avisa_que_lo_dicte(
    client_as, db_session, make_cc, make_cohort, seed_phase_defs, titulatec_app,
    monkeypatch,
):
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    seed_phase_defs()
    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        staticmethod(lambda *a, **k: False))
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710114")
    c = client_as(cc)
    assert c.post(f"{URL}/{req.id}/dar-acceso", data={"nip": "7395"}).status_code == 200

    resp = c.post(f"{URL}/{req.id}/reasignar-nip", data={"nip": NIP})

    assert resp.status_code == 200, _error(resp)
    assert _aviso(resp) == ("NIP reasignado, pero el correo no salió: díctalo por teléfono",
                            "warning")
    _sin_nip(resp)


def test_reasignar_una_cuenta_que_ya_inicio_sesion_da_400_sin_escribir(
    client_as, db_session, make_cc, make_cohort, seed_phase_defs, titulatec_app,
    correo_falso,
):
    from itcj2.core.models.user import User

    seed_phase_defs()
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710113")
    c = client_as(cc)
    assert c.post(f"{URL}/{req.id}/dar-acceso", data={"nip": "7393"}).status_code == 200
    correo_falso.clear()
    cuenta = db_session.query(User).filter_by(control_number="99710113").one()
    cuenta.last_login = datetime.now()
    db_session.flush()
    antes, epoca = cuenta.password_hash, cuenta.session_epoch

    resp = c.post(f"{URL}/{req.id}/reasignar-nip", data={"nip": NIP})

    assert resp.status_code == 400
    assert _error(resp) == ("Solo se reasigna el NIP de una cuenta que creó esta "
                            "solicitud y que nunca ha iniciado sesión.")
    _sin_nip(resp)
    db_session.refresh(cuenta)
    assert (cuenta.password_hash, cuenta.session_epoch) == (antes, epoca)
    assert correo_falso == []


def test_un_fallo_real_de_dar_acceso_no_lleva_el_hash_del_nip_al_log(
    client_as, db_session, make_cc, make_cohort, seed_phase_defs, titulatec_app,
    correo_falso, caplog,
):
    """Revisión final (minor de seguridad): el `IntegrityError` del INSERT de
    `core_users` trae los parámetros, `password_hash` incluido, y un hash de 4
    dígitos es el NIP. La ruta registra solo el TIPO de la excepción.

    El fallo es real: otra cuenta ya ocupa el `username` (= control) sin tener
    ese `control_number`, así que D10 no la ve y el INSERT choca."""
    import logging

    from itcj2.core.models.user import User

    seed_phase_defs()
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710140")
    db_session.add(User(username="99710140", control_number=None,
                        first_name="OCUPA", last_name="EL USUARIO", is_active=True))
    db_session.commit()          # checkpoint: el rollback de la ruta no se lleva el fixture

    with caplog.at_level(logging.DEBUG):
        resp = client_as(cc).post(f"{URL}/{req.id}/dar-acceso", data={"nip": NIP})

    assert resp.status_code == 400
    assert _error(resp) == "No pudimos completar el acceso; intenta de nuevo."
    _sin_nip(resp)
    assert "IntegrityError" in caplog.text, "control positivo: la línea sí se registró"
    assert "password_hash" not in caplog.text
    assert "scrypt" not in caplog.text
    assert "Traceback" not in caplog.text
    assert NIP not in caplog.text
    db_session.refresh(req)
    assert req.status == "awaiting_access"


def test_un_fallo_de_reasignar_nip_da_400_generico_y_no_vuelca_la_traza(
    client_as, db_session, make_cc, make_cohort, seed_phase_defs, titulatec_app,
    correo_falso, caplog, monkeypatch,
):
    """Reasignar-nip va envuelto como dar-acceso: rollback + 400 genérico, y el
    log lleva el tipo de la excepción, nunca la traza con los parámetros."""
    import logging

    from itcj2.core.models.user import User
    from itcj2.core.services import session_service

    seed_phase_defs()
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710141")
    c = client_as(cc)
    assert c.post(f"{URL}/{req.id}/dar-acceso", data={"nip": "7394"}).status_code == 200
    db_session.commit()          # checkpoint
    antes = db_session.query(User).filter_by(control_number="99710141").one().password_hash
    monkeypatch.setattr(session_service, "bump_version", lambda user_id, db=None: None)

    with caplog.at_level(logging.DEBUG):
        resp = c.post(f"{URL}/{req.id}/reasignar-nip", data={"nip": NIP})

    assert resp.status_code == 400
    assert _error(resp) == "No pudimos reasignar el NIP; intenta de nuevo."
    _sin_nip(resp)
    assert "RuntimeError" in caplog.text, "control positivo: la línea sí se registró"
    assert "Traceback" not in caplog.text and "scrypt" not in caplog.text
    cuenta = db_session.query(User).filter_by(control_number="99710141").one()
    db_session.refresh(cuenta)
    assert cuenta.password_hash == antes


def test_las_rutas_que_emiten_credenciales_no_usan_logger_exception():
    """`logger.exception` vuelca la traza, y la de un `IntegrityError` trae los
    parámetros del INSERT (`password_hash`). Aplica a toda ruta que llame a
    `approve`/`grant_access`/`reassign_nip`."""
    from itcj2.apps.titulatec.pages import access_admin, requests_admin

    for mod in (access_admin, requests_admin):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "logger.exception(" not in src, mod.__name__
        assert "exc_info=" not in src, mod.__name__


def test_reasignar_una_no_elegible_responde_400_sin_escribir(
    client_as, db_session, make_cc, make_cohort,
):
    cc = make_cc()
    cohort = make_cohort(status="open")
    legado = _make_req(db_session, cohort, control="99710120", status="converted")

    resp = client_as(cc).post(f"{URL}/{legado.id}/reasignar-nip", data={"nip": NIP})

    assert resp.status_code == 400
    assert _error(resp).startswith("Solo se reasigna el NIP")
    _sin_nip(resp)


def test_en_modo_oficial_cc_no_aprueba_ni_rechaza_ni_reenvia(
    client_as, db_session, make_cc, make_cohort, correo_falso,
):
    """Review Focus 3: dar acceso sobre una `pending_review` NO la aprueba (es de
    SE), y rechazar/reenviar ni siquiera son acciones de este modo."""
    cc = make_cc()
    cohort = make_cohort(status="open")
    por_revisar = _make_req(db_session, cohort, control="99710130")
    con_liga = _make_req(db_session, cohort, control="99710131", status="approved",
                         verify_send_count=1, verify_token_hash="8" * 64,
                         verify_expires_at=datetime.now() + timedelta(days=1))
    c = client_as(cc)

    aprobar = c.post(f"{URL}/{por_revisar.id}/dar-acceso", data={"nip": NIP})
    rechazar = c.post(f"{URL}/{por_revisar.id}/rechazar", data={"note": "No procede."})
    reenviar = c.post(f"{URL}/{con_liga.id}/reenviar")

    for resp in (aprobar, rechazar, reenviar):
        assert resp.status_code == 400
        assert _error(resp)
        _sin_nip(resp)
    assert _error(aprobar) == "Esa solicitud ya no está esperando acceso."
    db_session.refresh(por_revisar)
    db_session.refresh(con_liga)
    assert por_revisar.status == "pending_review"
    assert con_liga.status == "approved" and con_liga.verify_token_hash == "8" * 64
    assert correo_falso == []


@pytest.mark.parametrize("accion,data", [
    ("dar-acceso", {"nip": NIP}),
    ("devolver", {"note": "No coincide."}),
    ("reasignar-nip", {"nip": NIP}),
])
def test_una_solicitud_inexistente_da_404_liso(client_as, make_cc, accion, data):
    resp = client_as(make_cc()).post(f"{URL}/987654321/{accion}", data=data)

    assert resp.status_code == 404
    assert "X-Tt-Error" not in resp.headers


# ---------------------------------------------------------------------------
# Modo alterno: CC revisa todo
# ---------------------------------------------------------------------------
def test_la_bandeja_alterna_tiene_las_pestanas_de_revision(
    client_as, db_session, make_cc, make_cohort, modo_alterno,
):
    cc = make_cc()
    cohort = make_cohort(status="open")
    por_revisar = _make_req(db_session, cohort, control="99710200",
                            created_at=datetime(2026, 9, 22, 8, 0))
    sobrante = _en_espera(db_session, cohort, control="99710201",
                          created_at=datetime(2026, 9, 20, 8, 0))
    inscrita = _make_req(db_session, cohort, control="99710202", status="converted")

    resp = client_as(cc).get(f"{URL}?cohort_id={cohort.id}")

    assert resp.status_code == 200, resp.text[:500]
    texto = _plano(resp.text)
    posiciones = [texto.index(p) for p in ALTERNO]
    assert posiciones == sorted(posiciones)
    assert "Por dar acceso" not in texto and "Devueltas" not in texto
    assert _pestana_activa(resp.text) == "pending_review"
    # FIFO por llegada, con las `awaiting_access` sobrantes incluidas.
    assert (resp.text.index(f'id="tt-acc-{sobrante.id}"')
            < resp.text.index(f'id="tt-acc-{por_revisar.id}"'))
    assert f'id="tt-acc-{inscrita.id}"' not in resp.text
    fila = _fila(resp.text, por_revisar)
    assert f'hx-post="{URL}/{por_revisar.id}/dar-acceso"' in fila
    assert 'name="nip"' in fila and 'name="program_id"' in fila
    assert f'hx-post="{URL}/{por_revisar.id}/rechazar"' in fila
    assert "/devolver" not in fila
    assert "La liga de activación irá a" not in _plano_correo(fila), "sin cuenta no hay liga"
    assert f'hx-post="{URL}/{sobrante.id}/dar-acceso"' in _fila(resp.text, sobrante)


def test_en_modo_alterno_la_fila_por_revisar_trae_el_contexto_que_ve_se(
    client_as, db_session, make_cc, make_cohort, modo_alterno,
):
    """C6: CC es el único revisor. Ve la nota con que `verify()` la devolvió, el
    rechazo anterior del mismo control (como Solicitudes) y, en las sobrantes
    `awaiting_access` mezcladas en «Por revisar», su estado."""
    cc = make_cc()
    cohort = make_cohort(status="open")
    anterior = _make_req(db_session, cohort, control="99710250", status="rejected",
                         review_note="No aparece en el padrón.",
                         created_at=datetime(2026, 9, 1, 8, 0))
    devuelta = _make_req(db_session, cohort, control="99710250",
                         review_note="La convocatoria ya estaba cerrada al abrir la liga.",
                         created_at=datetime(2026, 9, 10, 8, 0))
    normal = _make_req(db_session, cohort, control="99710251",
                       created_at=datetime(2026, 9, 11, 8, 0))
    sobrante = _en_espera(db_session, cohort, control="99710252",
                          created_at=datetime(2026, 9, 12, 8, 0))

    html = client_as(cc).get(f"{URL}/body?cohort_id={cohort.id}").text
    fila = _plano(_fila(html, devuelta))

    assert "Nota: La convocatoria ya estaba cerrada al abrir la liga." in fila
    assert "Rechazada antes · 01/09/2026: No aparece en el padrón." in fila
    assert f'id="tt-acc-{anterior.id}"' not in html, "una rechazada no es de «Por revisar»"
    assert "Rechazada antes" not in _fila(html, normal)
    assert "Nota:" not in _fila(html, normal)
    assert "Aprobada por Servicios Escolares" in _plano(_fila(html, sobrante))
    assert "tt-pill--neutral\">Por revisar" not in _fila(html, normal), "sin píldora redundante"


def test_en_modo_alterno_aprobar_con_cuenta_avisa_a_donde_va_la_liga(
    client_as, db_session, make_cc, make_cohort, modo_alterno,
):
    """C3 (b): en el modo alterno CC es el único revisor; sin el aviso nadie en
    la cadena confirma la identidad antes de mandar la liga a una cuenta real."""
    cc = make_cc()
    cohort = make_cohort(status="open")
    _cuenta(db_session, "99710203")
    req = _make_req(db_session, cohort, control="99710203", email="liga@example.invalid")

    fila = _fila(client_as(cc).get(f"{URL}/body?cohort_id={cohort.id}").text, req)

    assert "Aprobar y enviar liga" in fila
    assert (AVISO_IDENTIDAD.format(correo="liga@example.invalid", accion="aprobar")
            in _plano_correo(fila))


def test_en_modo_alterno_aprobar_con_nip_crea_la_cuenta(
    client_as, db_session, make_cc, make_cohort, make_program, seed_phase_defs,
    titulatec_app, correo_falso, modo_alterno,
):
    from itcj2.core.models.user import User

    seed_phase_defs()
    cc = make_cc()
    cohort = make_cohort(status="open")
    program = make_program("Ingenieria Alterna Con NIP")
    req = _make_req(db_session, cohort, control="99710210")
    c = client_as(cc)

    resp = c.post(f"{URL}/{req.id}/dar-acceso",
                  data={"nip": NIP, "program_id": str(program.id),
                        "status": "pending_review", "cohort_id": str(cohort.id)})

    assert resp.status_code == 200, _error(resp)
    _sin_nip(resp)
    db_session.refresh(req)
    assert req.status == "converted" and req.program_id == program.id
    assert req.reviewed_by_id == cc.id and req.access_granted_by_id == cc.id
    assert db_session.query(User).filter_by(control_number="99710210").count() == 1
    (_asunto, _dest, correo), = correo_falso
    assert NIP in correo
    for pestana in ("pending_review", "converted", "all"):
        _sin_nip(c.get(f"{URL}/body?status={pestana}&cohort_id={cohort.id}"))


def test_en_modo_alterno_dar_acceso_a_una_sobrante_la_convierte(
    client_as, db_session, make_cc, make_cohort, seed_phase_defs, titulatec_app,
    correo_falso, modo_alterno,
):
    seed_phase_defs()
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710220")

    resp = client_as(cc).post(f"{URL}/{req.id}/dar-acceso", data={"nip": NIP})

    assert resp.status_code == 200, _error(resp)
    db_session.refresh(req)
    assert req.status == "converted"


def test_en_modo_alterno_el_aviso_del_correo_fallido_nombra_inscritas(
    client_as, db_session, make_cc, make_cohort, seed_phase_defs, titulatec_app,
    modo_alterno, monkeypatch,
):
    """En el alterno no existe «Con acceso»: la fila convertida vive en «Inscritas»."""
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    seed_phase_defs()
    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        staticmethod(lambda *a, **k: False))
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99710221")

    resp = client_as(cc).post(f"{URL}/{req.id}/dar-acceso", data={"nip": NIP})

    assert resp.status_code == 200, _error(resp)
    folio = _folio(db_session, req)
    assert _aviso(resp) == (f"Acceso dado (folio {folio}), pero el correo no salió: dicta el "
                            "NIP o reasígnalo en Inscritas", "warning")


def test_en_modo_alterno_rechazar_y_reenviar(
    client_as, db_session, make_cc, make_cohort, correo_falso, modo_alterno,
):
    cc = make_cc()
    cohort = make_cohort(status="open")
    a_rechazar = _make_req(db_session, cohort, control="99710230")
    con_liga = _make_req(db_session, cohort, control="99710231", status="approved",
                         verify_send_count=1, verify_token_hash="9" * 64,
                         verify_expires_at=datetime.now() + timedelta(days=1))
    c = client_as(cc)

    sin_motivo = c.post(f"{URL}/{a_rechazar.id}/rechazar", data={"note": "  "})
    rechazo = c.post(f"{URL}/{a_rechazar.id}/rechazar",
                     data={"note": "No aparece en el padrón.", "status": "pending_review",
                           "cohort_id": str(cohort.id)})
    reenvio = c.post(f"{URL}/{con_liga.id}/reenviar",
                     data={"status": "approved", "cohort_id": str(cohort.id)})

    assert sin_motivo.status_code == 400 and _error(sin_motivo)
    assert rechazo.status_code == 200, _error(rechazo)
    assert reenvio.status_code == 200, _error(reenvio)
    assert _pestana_activa(reenvio.text) == "approved"
    db_session.refresh(a_rechazar)
    db_session.refresh(con_liga)
    assert a_rechazar.status == "rejected" and a_rechazar.reviewed_by_id == cc.id
    assert con_liga.verify_token_hash != "9" * 64 and con_liga.verify_send_count == 2
    fila = _fila(reenvio.text, con_liga)
    assert f'hx-post="{URL}/{con_liga.id}/reenviar"' in fila
    assert f'hx-post="{URL}/{con_liga.id}/rechazar"' in fila


@pytest.mark.parametrize("accion,data", [
    ("rechazar", {"note": "No procede."}),
    ("reenviar", {}),
    ("dar-acceso", {"nip": NIP}),
    ("reasignar-nip", {"nip": NIP}),
])
def test_en_modo_alterno_una_solicitud_inexistente_da_404_liso(
    client_as, make_cc, modo_alterno, accion, data,
):
    """En el oficial rechazar y reenviar cortan con 400 de modo antes de leer la
    solicitud; en el alterno sí llegan al 404 liso."""
    resp = client_as(make_cc()).post(f"{URL}/987654321/{accion}", data=data)

    assert resp.status_code == 404
    assert "X-Tt-Error" not in resp.headers


def test_en_modo_alterno_devolver_no_existe(
    client_as, db_session, make_cc, make_cohort, modo_alterno,
):
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710240")

    resp = client_as(cc).post(f"{URL}/{req.id}/devolver", data={"note": "No coincide."})

    assert resp.status_code == 400 and _error(resp)
    db_session.refresh(req)
    assert req.status == "awaiting_access"


def test_la_pagina_explica_cada_modo(client_as, make_cc, monkeypatch):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    monkeypatch.setattr(EnrollmentRequestService, "_link_ttl_hours",
                        staticmethod(lambda: 10 * 24))
    c = client_as(make_cc())

    oficial = _plano(c.get(URL).text)
    assert "NIP de 4 dígitos" in oficial and "liga de activación de 10 días" in oficial
    assert "Servicios Escolares" in oficial

    monkeypatch.setattr(EnrollmentRequestService, "reviewer_mode",
                        staticmethod(lambda: "computer_center"))
    alterno = _plano(c.get(URL).text)
    # A CC se le habla en segunda persona, como en el oficial.
    assert "En este modo tú revisas las solicitudes" in alterno
    assert "La revisión la hace Centro de Cómputo" not in alterno


@pytest.mark.parametrize("modo", ["school_services", "computer_center"])
def test_con_una_liga_de_un_dia_la_cabecera_dice_dia_en_singular(
    client_as, make_cc, monkeypatch, modo,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    monkeypatch.setattr(EnrollmentRequestService, "_link_ttl_hours",
                        staticmethod(lambda: 24))
    monkeypatch.setattr(EnrollmentRequestService, "reviewer_mode", staticmethod(lambda: modo))

    texto = _plano(client_as(make_cc()).get(URL).text)

    assert "liga de activación de 1 día" in texto
    assert "1 días" not in texto


def test_un_control_sin_ano_de_ingreso_no_dice_ingreso_sin_ano(
    client_as, db_session, make_cc, make_cohort,
):
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="LEGADO7")

    texto = _plano(_fila(client_as(cc).get(f"{URL}/body?cohort_id={cohort.id}").text, req))

    assert "Sin año de ingreso" in texto
    assert "Ingreso Sin año" not in texto


# ---------------------------------------------------------------------------
# Reglas del frontend
# ---------------------------------------------------------------------------
def test_la_bandeja_no_usa_hx_confirm_ni_js_ni_css_inline():
    import itcj2

    raiz = Path(itcj2.__file__).resolve().parent / "apps" / "titulatec" / "templates" / "titulatec"
    for ruta in (raiz / "admin" / "access.html",
                 raiz / "admin" / "partials" / "access_body.html"):
        texto = ruta.read_text(encoding="utf-8")
        sin_comentarios = re.sub(r"\{#.*?#\}", "", texto, flags=re.S)
        for prohibido in ("hx-confirm", "<script", " style=", "onclick=", 'id="tt-req'):
            assert prohibido not in sin_comentarios, f"{ruta.name}: {prohibido}"
    assert "{% block admin_view %}access{% endblock %}" in (
        raiz / "admin" / "access.html").read_text(encoding="utf-8")
