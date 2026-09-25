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


@pytest.fixture()
def modo_alterno(monkeypatch):
    """Centro de Cómputo revisa todo: se parchea `reviewer_mode`, nunca `get_settings`."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    monkeypatch.setattr(EnrollmentRequestService, "reviewer_mode",
                        staticmethod(lambda: "computer_center"))


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
    assert "Convocatoria Accesos Fila" in texto and "21/09/2026" in texto
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
    assert DESACTIVADA not in _plano(fila)
    assert DESACTIVADA in _plano(_fila(html, inactiva))
    assert "sin contraseña" in _plano(_fila(html, sin_contra))


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
    # D8 / spec §8.2 «Reasignar NIP (si aplica D8)»: el botón es el remedio del
    # correo que NO salió. Aquí salió, así que no se ofrece aunque la cuenta siga
    # elegible (`can_reassign_nip`: creada por la solicitud, sin entrar aún).
    assert "/reasignar-nip" not in fila
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


def test_un_error_de_dar_acceso_viaja_en_x_tt_error_sin_el_nip(
    client_as, db_session, make_cc, make_cohort,
):
    cc = make_cc()
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99710070")

    resp = client_as(cc).post(f"{URL}/{req.id}/dar-acceso", data={"nip": "48a6"})

    assert resp.status_code == 400
    assert _error(resp) == "El NIP debe ser exactamente 4 dígitos."
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

    # Aun con el correo sin salir: si la persona ya entró y cambió su contraseña,
    # no se reasigna (D8: «solo mientras `must_change_password` siga activo»).
    from itcj2.core.models.user import User
    cuenta = db_session.query(User).filter_by(control_number="99710110").one()
    cuenta.must_change_password = False
    db_session.flush()
    fila = _fila(c.get(f"{URL}/body?status=granted&cohort_id={cohort.id}").text, req)
    assert "correo no enviado" in fila
    assert "/reasignar-nip" not in fila
    cuenta.must_change_password = True
    db_session.flush()

    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved", envio_real)
    resp = c.post(f"{URL}/{req.id}/reasignar-nip",
                  data={"nip": NIP, "status": "granted", "cohort_id": str(cohort.id)})

    assert resp.status_code == 200, _error(resp)
    _sin_nip(resp)
    assert _pestana_activa(resp.text) == "granted"
    fila = _fila(resp.text, req)
    assert "correo no enviado" not in fila
    # El correo del NIP nuevo salió: D8 ya no aplica y el botón se va.
    assert "/reasignar-nip" not in fila
    (_asunto, _dest, correo), = correo_falso
    assert NIP in correo


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
    assert f'hx-post="{URL}/{sobrante.id}/dar-acceso"' in _fila(resp.text, sobrante)


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
    assert "La revisión la hace Centro de Cómputo" in alterno


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
