"""Bandeja de solicitudes (HTML): pestañas, qué ofrece cada fila y la pestaña que viaja.

Pestañas: "Por revisar" (`pending_review` y el legado `unverified`/`verified`,
por omisión), "Liga enviada" (`approved`), "Inscritas" (`converted`),
"Rechazadas" (`rejected`) y "Todas".

Lo que ofrece una fila sale de su ESTADO y de si el número de control tiene
cuenta HOY en `core_users`, que es la misma pregunta que se hace `approve()`.
Si la bandeja y el servicio se separan, la bandeja promete lo que el servicio no
hace: un NIP que nunca se aplica, o una liga que el oficial no sabía que salía.

La mecánica de aprobar, rechazar y reenviar vive en `test_enrollment_approve.py`
y `test_enrollment_resend.py`; aquí se prueba lo que ve y toca el oficial.

Los KPIs, "Por año de ingreso" y "Rechazada antes" (2026-09-17) se prueban aquí
a nivel de ruta (que el mismo alcance/convocatoria del listado llegue a
`_body_ctx` y se pinte); el cálculo en sí — agrupado por estado, personas
únicas por su solicitud más reciente, pivote de siglo — se prueba sin HTTP en
`test_enrollment_request_service.py::EnrollmentRequestService.stats`.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

URL = "/titulatec/admin/solicitudes"

LIST_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.read.all",      # -> officer_programs() == "ALL"
)
# Mismos permisos de bandeja que LIST_PERMS, pero SIN `process.api.read.all`:
# deja al actor ACOTADO por carrera (`officer_programs()` devuelve un `set`,
# no `'ALL'`) para probar el alcance de "Rechazada antes".
OFFICER_LIST_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
)

PESTANAS = ["Por revisar", "Liga enviada", "Inscritas", "Rechazadas", "Todas"]
AVISO_CON_CUENTA = ("La liga de activación irá a este correo, que escribió el "
                    "solicitante. Confirma su identidad antes de aprobar.")


def _kpi(html: str, label: str) -> int:
    m = re.search(
        rf'<div class="tt-kicker">{re.escape(label)}</div><div class="num">(\d+)</div>', html)
    assert m, f"no se encontró el KPI {label!r}"
    return int(m.group(1))


def _plano(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


@pytest.fixture()
def correo_falso(monkeypatch):
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


def _make_req(db_session, cohort, *, control, status="pending_review", kind="unknown",
              email="egresado@example.invalid", **kw):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADO", last_name="ANTIGUO", middle_name=None,
        program_id=None, program_text="Ingenieria de 2005",
        phone="6561234567", contact_email=email,
        has_efirma=False, kind=kind, status=status, verify_send_count=0,
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row


def _cuenta(db_session, control, *, password=True):
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import hash_nip

    user = User(username=control, control_number=control, first_name="YA",
                last_name="EXISTIA", password_hash=hash_nip("9999") if password else None,
                is_active=True)
    db_session.add(user)
    db_session.flush()
    return user


def _fila(html: str, req) -> str:
    """El `<tr>` de una solicitud. Los ids estables de fila son parte del contrato."""
    marca = f'id="tt-req-{req.id}"'
    assert marca in html, f"no está la fila de la solicitud {req.id}"
    return html.split(marca, 1)[1].split("</tr>", 1)[0]


def _pestana_activa(html: str) -> str:
    activa = re.search(r'<button[^>]*id="tt-req-tab-([a-z_]+)"[^>]*aria-current="true"', html)
    assert activa, "ninguna pestaña se anuncia como activa"
    return activa.group(1)


# ---------------------------------------------------------------------------
# Pestañas
# ---------------------------------------------------------------------------
def test_la_bandeja_abre_en_por_revisar_con_las_cinco_pestanas(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    por_revisar = _make_req(db_session, cohort, control="99551001")
    aprobada = _make_req(db_session, cohort, control="99551002", status="approved")

    resp = client_as(head).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    texto = _plano(resp.text)
    posiciones = [texto.index(p) for p in PESTANAS]
    assert posiciones == sorted(posiciones), "las pestañas salen en otro orden"
    assert _pestana_activa(resp.text) == "pending_review"
    assert f'id="tt-req-{por_revisar.id}"' in resp.text
    assert f'id="tt-req-{aprobada.id}"' not in resp.text


@pytest.mark.parametrize("pestana,estados", [
    ("pending_review", {"pending_review", "unverified", "verified"}),
    ("approved", {"approved"}),
    ("converted", {"converted"}),
    ("rejected", {"rejected"}),
    ("all", {"pending_review", "unverified", "verified", "approved", "converted",
             "rejected"}),
])
def test_cada_pestana_muestra_solo_sus_estados(
    client_as, db_session, make_head, make_cohort, pestana, estados,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    filas = {status: _make_req(db_session, cohort, control=f"9955{i:04d}", status=status)
             for i, status in enumerate(("pending_review", "unverified", "verified",
                                         "approved", "converted", "rejected"), start=1100)}

    resp = client_as(head).get(f"{URL}/body?status={pestana}")

    assert resp.status_code == 200
    assert _pestana_activa(resp.text) == pestana
    visibles = {s for s, req in filas.items() if f'id="tt-req-{req.id}"' in resp.text}
    assert visibles == estados


def test_una_pestana_desconocida_cae_en_por_revisar(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99551003")

    resp = client_as(head).get(f"{URL}/body?status=cualquier-cosa")

    assert resp.status_code == 200
    assert _pestana_activa(resp.text) == "pending_review"
    assert f'id="tt-req-{req.id}"' in resp.text


# ---------------------------------------------------------------------------
# Qué ofrece cada fila
# ---------------------------------------------------------------------------
def test_la_fila_por_revisar_sin_cuenta_pide_nip_para_crear_el_acceso(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99551010")

    fila = _fila(client_as(head).get(f"{URL}/body").text, req)

    assert "Sin cuenta" in fila
    assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/aprobar"' in fila
    assert 'name="nip"' in fila
    assert "Aprobar y crear acceso" in fila
    assert "Aprobar y enviar liga" not in fila
    assert AVISO_CON_CUENTA not in _plano(fila)
    assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/rechazar"' in fila
    assert 'name="note"' in fila and "required" in fila


def test_la_fila_por_revisar_con_cuenta_no_pide_nip_y_avisa_a_donde_va_la_liga(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    _cuenta(db_session, "99551011")
    req = _make_req(db_session, cohort, control="99551011", email="lo.tecleo@example.invalid")

    fila = _fila(client_as(head).get(f"{URL}/body").text, req)

    assert "Con cuenta" in fila
    assert 'name="nip"' not in fila, "a una cuenta existente no se le fija NIP"
    assert "Aprobar y enviar liga" in fila
    assert "Aprobar y crear acceso" not in fila
    assert AVISO_CON_CUENTA in _plano(fila)
    # El correo lleva un `<wbr>` antes de la «@» para partir ahí en la tabla;
    # no produce texto, así que lo que el oficial LEE es el correo entero.
    assert "lo.tecleo@example.invalid" in fila.replace("<wbr>", "")
    assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/rechazar"' in fila


def test_una_cuenta_sin_contrasena_se_marca_antes_de_intentar_aprobar(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    _cuenta(db_session, "99551012", password=False)
    req = _make_req(db_session, cohort, control="99551012")

    fila = _fila(client_as(head).get(f"{URL}/body").text, req)

    assert "Con cuenta" in fila
    assert "sin contraseña" in fila


PILDORA_DESACTIVADA = "Cuenta desactivada: se reactiva al abrir la liga"


@pytest.mark.parametrize("estado,control", [("pending_review", "99551040"),
                                            ("approved", "99551041")])
def test_una_cuenta_desactivada_se_avisa_en_la_fila(
    client_as, db_session, make_head, make_cohort, estado, control,
):
    """Abrir la liga reactiva la cuenta (excepción aprobada, 2026-09-15): el
    oficial tiene que saberlo ANTES de aprobar y mientras la liga va en camino."""
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    cuenta = _cuenta(db_session, control)
    cuenta.is_active = False
    db_session.flush()
    extra = ({"verify_send_count": 1, "verify_token_hash": "5" * 64,
              "verify_expires_at": datetime.now() + timedelta(days=1)}
             if estado == "approved" else {})
    req = _make_req(db_session, cohort, control=control, status=estado, **extra)

    fila = _fila(client_as(head).get(f"{URL}/body?status={estado}").text, req)

    assert PILDORA_DESACTIVADA in _plano(fila)


@pytest.mark.parametrize("estado,control,activa", [
    ("pending_review", "99551042", True),
    ("converted", "99551043", False),
    ("rejected", "99551044", False),
])
def test_la_pildora_de_desactivada_no_sale_si_no_aplica(
    client_as, db_session, make_head, make_cohort, estado, control, activa,
):
    """Cuenta activa, o solicitud cuya liga ya no está en camino: la píldora
    prometería una reactivación que no va a ocurrir."""
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    cuenta = _cuenta(db_session, control)
    cuenta.is_active = activa
    db_session.flush()
    req = _make_req(db_session, cohort, control=control, status=estado)

    fila = _fila(client_as(head).get(f"{URL}/body?status={estado}").text, req)

    assert PILDORA_DESACTIVADA not in _plano(fila)


def test_la_fila_legado_se_revisa_igual_que_una_nueva(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99551013", status="unverified")

    fila = _fila(client_as(head).get(f"{URL}/body").text, req)

    assert f'/solicitudes/{req.id}/aprobar' in fila
    assert f'/solicitudes/{req.id}/rechazar' in fila


def test_la_fila_con_liga_enviada_muestra_envios_y_ofrece_reenviar_y_cancelar(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    enviada = datetime(2026, 9, 14, 10, 30)
    req = _make_req(db_session, cohort, control="99551014", status="approved",
                    verify_send_count=2, verify_sent_at=enviada,
                    verify_token_hash="0" * 64,
                    verify_expires_at=datetime.now() + timedelta(days=5))

    fila = _fila(client_as(head).get(f"{URL}/body?status=approved").text, req)
    texto = _plano(fila)

    assert "Liga enviada 2 veces" in texto
    assert "última 14/09/2026 10:30" in texto
    assert "sin abrir" in texto
    assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/reenviar"' in fila
    assert "Reenviar liga" in fila
    assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/rechazar"' in fila
    assert "Cancelar solicitud" in fila
    assert f'/solicitudes/{req.id}/aprobar' not in fila
    assert 'name="nip"' not in fila


def test_la_fila_con_liga_enviada_dice_abierta_y_si_el_correo_no_salio(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99551015", status="approved",
                    verify_send_count=1, verify_sent_at=None,
                    verified_at=datetime.now() - timedelta(hours=1),
                    verify_token_hash="1" * 64,
                    verify_expires_at=datetime.now() - timedelta(hours=2))

    texto = _plano(_fila(client_as(head).get(f"{URL}/body?status=approved").text, req))

    assert "Liga enviada 1 vez" in texto
    assert "abierta" in texto and "sin abrir" not in texto
    assert "correo no enviado" in texto


def test_la_fila_inscrita_muestra_el_folio_y_la_rechazada_el_motivo(
    client_as, db_session, make_head, make_cohort, make_student, make_process,
    seed_phase_defs,
):
    seed_phase_defs()
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    proc = make_process(make_student(control_number="99551016"), cohort=cohort)
    inscrita = _make_req(db_session, cohort, control="99551016", status="converted",
                         converted_process_id=proc.id)
    rechazada = _make_req(db_session, cohort, control="99551017", status="rejected",
                          review_note="No aparece en el padrón.")
    c = client_as(head)

    fila_inscrita = _fila(c.get(f"{URL}/body?status=converted").text, inscrita)
    fila_rechazada = _fila(c.get(f"{URL}/body?status=rejected").text, rechazada)

    assert proc.folio in fila_inscrita
    assert "No aparece en el padrón." in fila_rechazada
    for fila in (fila_inscrita, fila_rechazada):
        assert "<form" not in fila


def test_la_fila_muestra_telefono_convocatoria_y_fecha(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open", name="Convocatoria Ficticia De Prueba")
    req = _make_req(db_session, cohort, control="99551018")
    db_session.refresh(req)

    fila = _fila(client_as(head).get(f"{URL}/body").text, req)

    assert "6561234567" in fila
    assert "Convocatoria Ficticia De Prueba" in fila
    assert req.created_at.strftime("%d/%m/%Y") in fila


def test_ya_no_aparecen_las_pildoras_del_flujo_anterior(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    _cuenta(db_session, "99551019")
    _make_req(db_session, cohort, control="99551019", kind="known")
    _make_req(db_session, cohort, control="99551020", status="unverified")

    html = client_as(head).get(f"{URL}/body?status=all").text.lower()

    for vieja in ("liga institucional", "correo personal verificado",
                  "correo personal sin verificar", "el nip no se aplica"):
        assert vieja not in html, vieja


# ---------------------------------------------------------------------------
# La pestaña donde estaba el oficial viaja en cada acción
# ---------------------------------------------------------------------------
def test_los_formularios_de_la_fila_llevan_la_pestana_y_la_convocatoria(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99551030", status="approved",
                    verify_send_count=1, verify_token_hash="2" * 64,
                    verify_expires_at=datetime.now() + timedelta(days=1))

    fila = _fila(client_as(head).get(
        f"{URL}/body?status=approved&cohort_id={cohort.id}").text, req)

    formularios = re.findall(r"<form.*?</form>", fila, flags=re.S)
    assert len(formularios) == 2, "reenviar y cancelar"
    for form in formularios:
        assert re.search(r'name="status"\s+value="approved"', form), form
        assert re.search(rf'name="cohort_id"\s+value="{cohort.id}"', form), form


def test_tras_aprobar_se_vuelve_a_pintar_la_pestana_donde_estaba_el_oficial(
    client_as, db_session, make_head, make_cohort, seed_phase_defs, titulatec_app,
    correo_falso,
):
    seed_phase_defs()
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99551031")
    otra = _make_req(db_session, cohort, control="99551032")
    c = client_as(head)

    resp = c.post(f"{URL}/{req.id}/aprobar",
                  data={"nip": "4917", "program_id": "", "status": "pending_review",
                        "cohort_id": ""})

    assert resp.status_code == 200, resp.headers.get("X-Tt-Error")
    assert _pestana_activa(resp.text) == "pending_review"
    assert f'id="tt-req-{req.id}"' not in resp.text, "la inscrita ya no está por revisar"
    assert f'id="tt-req-{otra.id}"' in resp.text


def test_tras_rechazar_y_reenviar_se_queda_en_liga_enviada(
    client_as, db_session, make_head, make_cohort, correo_falso,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        _token_cache_put, _sha256,
    )

    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    _token_cache_put("claro-de-prueba-inbox")
    a_reenviar = _make_req(db_session, cohort, control="99551033", status="approved",
                           verify_send_count=1,
                           verify_token_hash=_sha256("claro-de-prueba-inbox"),
                           verify_expires_at=datetime.now() + timedelta(days=1))
    a_cancelar = _make_req(db_session, cohort, control="99551034", status="approved",
                           verify_send_count=1, verify_token_hash="3" * 64,
                           verify_expires_at=datetime.now() + timedelta(days=1))
    c = client_as(head)

    reenvio = c.post(f"{URL}/{a_reenviar.id}/reenviar", data={"status": "approved"})
    cancelacion = c.post(f"{URL}/{a_cancelar.id}/rechazar",
                         data={"note": "La persona pidió cancelar.", "status": "approved"})

    assert reenvio.status_code == cancelacion.status_code == 200
    assert _pestana_activa(reenvio.text) == "approved"
    assert _pestana_activa(cancelacion.text) == "approved"
    assert f'id="tt-req-{a_reenviar.id}"' in cancelacion.text
    assert f'id="tt-req-{a_cancelar.id}"' not in cancelacion.text


# ---------------------------------------------------------------------------
# Página y reglas del frontend
# ---------------------------------------------------------------------------
def test_la_pagina_explica_los_dos_caminos(client_as, db_session, make_head):
    head = make_head(perm_codes=LIST_PERMS)

    texto = _plano(client_as(head).get(URL).text)

    assert "no tiene cuenta" in texto and "NIP de 4 dígitos" in texto
    assert "ya tiene cuenta" in texto and "liga de activación" in texto


def test_la_bandeja_no_usa_hx_confirm_ni_js_ni_css_inline():
    """`confirm()`/`hx-confirm` están prohibidos (no hay puente) y los estáticos
    viven en archivos externos."""
    import itcj2

    raiz = Path(itcj2.__file__).resolve().parent / "apps" / "titulatec" / "templates" / "titulatec"
    for ruta in (raiz / "admin" / "requests.html",
                 raiz / "admin" / "partials" / "requests_body.html"):
        sin_comentarios = re.sub(r"\{#.*?#\}", "", ruta.read_text(encoding="utf-8"), flags=re.S)
        for prohibido in ("hx-confirm", "<script", " style=", "onclick="):
            assert prohibido not in sin_comentarios, f"{ruta.name}: {prohibido}"


# ---------------------------------------------------------------------------
# KPIs (2026-09-17): mismo alcance y convocatoria que el listado, sin pestaña
# ---------------------------------------------------------------------------
def test_los_kpis_cuentan_solicitudes_sin_filtro_de_pestana_ni_limite(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99601001", status="pending_review")
    _make_req(db_session, cohort, control="99601002", status="unverified")
    _make_req(db_session, cohort, control="99601003", status="approved")
    _make_req(db_session, cohort, control="99601004", status="converted")
    _make_req(db_session, cohort, control="99601005", status="rejected")

    # Pide la pestaña "Inscritas" y acota a ESTA convocatoria: los KPIs no
    # deben filtrarse por pestaña, pero SÍ por `cohort_id` — sin acotar, la BD
    # de dev trae solicitudes reales de otras convocatorias que contaminarían
    # el conteo (no son parte de este test).
    html = client_as(head).get(f"{URL}/body?status=converted&cohort_id={cohort.id}").text

    assert _kpi(html, "Total") == 5
    assert _kpi(html, "Por revisar") == 2       # pending_review + unverified
    assert _kpi(html, "Liga enviada") == 1
    assert _kpi(html, "Inscritas") == 1
    assert _kpi(html, "Rechazadas") == 1


def test_los_kpis_respetan_la_convocatoria_filtrada(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    c1 = make_cohort(status="open")
    c2 = make_cohort(status="open")
    _make_req(db_session, c1, control="99602001")
    _make_req(db_session, c2, control="99602002")

    html = client_as(head).get(f"{URL}/body?cohort_id={c1.id}").text

    assert _kpi(html, "Total") == 1


def test_sin_alcance_la_bandeja_no_muestra_kpis(
    client_as, db_session, make_officer,
):
    officer, _pos = make_officer([], perm_codes=OFFICER_LIST_PERMS)

    html = client_as(officer).get(f"{URL}/body").text

    assert "Sin alcance" in html
    assert "tt-kpis" not in html
    assert "Por año de ingreso" not in html


# ---------------------------------------------------------------------------
# «Por año de ingreso» (2026-09-17)
# ---------------------------------------------------------------------------
def test_el_bloque_por_ano_muestra_personas_unicas_y_su_desglose(
    client_as, db_session, make_head, make_cohort,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import entry_year

    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    # DOS solicitudes del MISMO control: cuenta una sola persona, con el estado
    # de su solicitud MÁS RECIENTE (converted).
    _make_req(db_session, cohort, control="21100001", status="rejected")
    mas_reciente = _make_req(db_session, cohort, control="21100001", status="converted")
    _make_req(db_session, cohort, control="21100002", status="pending_review")
    esperado = entry_year("21100001")
    assert mas_reciente.control_number == "21100001"

    # Acotado a ESTA convocatoria: sin `cohort_id`, la BD de dev puede traer
    # otro control real que también empiece con "21" y sume una persona más.
    html = client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text

    assert "Por año de ingreso" in html
    assert f'id="tt-req-year-{esperado}"' in html
    assert "2 personas" in _plano(html)
    # Único año en juego -> su total ES el máximo: min="0" max="2" value="2".
    assert 'max="2" value="2"' in html


def test_el_bloque_por_ano_es_plegable_cerrado_y_recordado(
    client_as, db_session, make_head, make_cohort,
):
    """Con la carga real (20+ generaciones) el bloque abierto en filas medía
    2,651 px y tapaba la lista: nace CERRADO (el servidor nunca manda `open`),
    se recuerda por `data-tt-remember` y el `<summary>` basta para decidir si
    abrirlo."""
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="18100001")
    _make_req(db_session, cohort, control="21100001")
    _make_req(db_session, cohort, control="21100002")

    html = client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text

    inicio = html.index('<details class="tt-card tt-years')
    apertura = html[inicio:html.index(">", inicio)]
    assert "open" not in apertura.split("data-tt-remember")[0], (
        "el bloque por año tiene que nacer cerrado")
    assert 'data-tt-remember="tt-req-years"' in apertura
    resumen = _plano(html[inicio:html.index("</summary>", inicio)])
    assert "3 personas" in resumen
    assert "2 generaciones" in resumen
    assert "más: 2021 (2)" in resumen


def test_el_bloque_por_ano_no_sale_si_no_hay_solicitudes(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    # Convocatoria propia, sin ninguna solicitud: acotar a su `cohort_id` es lo
    # que garantiza "cero de verdad" (sin acotar, la BD de dev sí tiene
    # solicitudes reales de otras convocatorias).
    cohort = make_cohort(status="open")

    html = client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text

    assert "Por año de ingreso" not in html


# ---------------------------------------------------------------------------
# «Correo no enviado» en una rechazada (2026-09-17)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tab", ["rejected", "all"])
def test_una_rechazada_sin_rejection_sent_at_muestra_la_pildora(
    client_as, db_session, make_head, make_cohort, tab,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99603001", status="rejected",
                    review_note="No aparece en el padrón.")

    fila = _fila(client_as(head).get(f"{URL}/body?status={tab}").text, req)

    assert "correo no enviado" in fila


def test_una_rechazada_con_rejection_sent_at_no_muestra_la_pildora(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99603002", status="rejected",
                    review_note="No aparece en el padrón.",
                    rejection_sent_at=datetime(2026, 9, 17, 9, 0))

    fila = _fila(client_as(head).get(f"{URL}/body?status=rejected").text, req)

    assert "correo no enviado" not in fila


# ---------------------------------------------------------------------------
# «Rechazada antes» (2026-09-17)
# ---------------------------------------------------------------------------
def test_rechazada_antes_muestra_fecha_y_motivo_de_la_mas_reciente(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    vieja = _make_req(db_session, cohort, control="99604001", status="rejected",
                      review_note="Documentos incompletos.")
    db_session.refresh(vieja)
    nueva = _make_req(db_session, cohort, control="99604001", status="pending_review")
    assert nueva.id > vieja.id

    fila = _fila(client_as(head).get(f"{URL}/body").text, nueva)
    texto = _plano(fila)

    assert "Rechazada antes" in texto
    assert "Documentos incompletos." in texto
    assert vieja.created_at.strftime("%d/%m/%Y") in texto


def test_rechazada_antes_toma_la_mas_reciente_anterior_a_la_fila_no_la_global(
    client_as, db_session, make_head, make_cohort,
):
    """Dos rechazos del mismo control (id 1 y 2): visto desde el MÁS RECIENTE
    (id 2, que es la propia fila), su antecedente es el id 1 — no debe
    autoexcluirse ni desaparecer por ser también el rechazo "más reciente"."""
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    primera = _make_req(db_session, cohort, control="99604004", status="rejected",
                        review_note="Primer motivo.")
    segunda = _make_req(db_session, cohort, control="99604004", status="rejected",
                        review_note="Segundo motivo.")
    assert segunda.id > primera.id

    fila = _fila(client_as(head).get(f"{URL}/body?status=rejected").text, segunda)
    texto = _plano(fila)

    assert "Rechazada antes" in texto
    assert "Primer motivo." in texto
    assert "Segundo motivo." in texto      # su propio motivo de rechazo, aparte


def test_rechazada_antes_no_aparece_para_una_solicitud_sin_antecedente(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99604005")

    fila = _fila(client_as(head).get(f"{URL}/body").text, req)

    assert "Rechazada antes" not in fila


def test_rechazada_antes_respeta_el_alcance_por_carrera(
    client_as, db_session, make_officer, make_program, make_cohort,
):
    """Riesgo de fuga entre carreras: un rechazo de una carrera FUERA del
    alcance del encargado no debe delatarse como antecedente."""
    prog_propia = make_program("Carrera del encargado acotado")
    prog_ajena = make_program("Carrera ajena al encargado acotado")
    officer, _pos = make_officer([prog_propia], perm_codes=OFFICER_LIST_PERMS)
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99604002", status="rejected",
             program_id=prog_ajena.id, review_note="Nota de otra carrera.")
    nueva = _make_req(db_session, cohort, control="99604002", status="pending_review",
                      program_id=prog_propia.id)

    fila = _fila(client_as(officer).get(f"{URL}/body").text, nueva)

    assert "Rechazada antes" not in fila


def test_rechazada_antes_si_aparece_cuando_esta_dentro_del_alcance(
    client_as, db_session, make_officer, make_program, make_cohort,
):
    prog = make_program("Carrera del encargado acotado 2")
    officer, _pos = make_officer([prog], perm_codes=OFFICER_LIST_PERMS)
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99604003", status="rejected",
             program_id=prog.id, review_note="Motivo dentro de alcance.")
    nueva = _make_req(db_session, cohort, control="99604003", status="pending_review",
                      program_id=prog.id)

    fila = _fila(client_as(officer).get(f"{URL}/body").text, nueva)
    texto = _plano(fila)

    assert "Rechazada antes" in texto
    assert "Motivo dentro de alcance." in texto


# ---------------------------------------------------------------------------
# La tabla cabe en el ancho del admin (2026-09-17)
# ---------------------------------------------------------------------------
# Con 8 columnas y `table-layout: auto` medía 1,337 px como mínimo contra
# 977-1,192 px útiles: se desplazaba en horizontal con la barra al final de
# cientos de filas y las acciones se veían cortadas. El ancho real se midió en
# navegador (0 celdas desbordadas en 6 anchos x 4 pestañas); estos tests fijan
# las piezas que lo hacen posible, que es lo que un cambio futuro rompería.
_CSS = (Path(__file__).resolve().parents[3]
        / "itcj2/apps/titulatec/static/css/titulatec.css")


def test_la_tabla_tiene_cinco_columnas_y_agrupa_por_fila(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open", name="Convocatoria De La Tabla")
    req = _make_req(db_session, cohort, control="21100077",
                    email="nombre.apellido@example.invalid")

    html = client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text

    tabla = html.split('<table class="table table-sm tt-req-table">', 1)
    assert len(tabla) == 2, "la tabla perdió la clase que le da el layout fijo"
    encabezado = tabla[1].split("</thead>", 1)[0]
    assert encabezado.count("<th>") == 5
    assert encabezado.count("<col ") == 5
    fila = _fila(html, req)
    celdas = fila.split("<td")[1:]
    assert len(celdas) == 5
    # Control, nombre y cuenta en la MISMA celda; convocatoria bajo la carrera.
    assert "21100077" in celdas[0] and "EGRESADO" in _plano(celdas[0])
    assert "Sin cuenta" in celdas[0]
    assert "Convocatoria De La Tabla" in celdas[1]
    # El correo parte en la «@», no letra por letra.
    assert "nombre.apellido<wbr>@example.invalid" in celdas[2]
    # Las acciones siguen completas en la última celda.
    assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/aprobar"' in celdas[4]
    assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/rechazar"' in celdas[4]


def test_el_correo_con_marcado_se_escapa_aunque_se_parta_en_la_arroba(
    client_as, db_session, make_head, make_cohort,
):
    """El `<wbr>` se arma en la plantilla con `partition`, no con `|safe`: el
    correo lo teclea un anónimo y tiene que seguir escapado."""
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="21100078",
                    email='<script>x</script>@example.invalid')

    fila = _fila(client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text, req)

    assert "<script>x</script>" not in fila
    assert "&lt;script&gt;x&lt;/script&gt;<wbr>@example.invalid" in fila


def test_el_css_de_la_tabla_no_vuelve_a_desbordar():
    css = _CSS.read_text(encoding="utf-8")
    sin_comentarios = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    regla = re.search(r"\.tt-req-table\s*\{([^}]*)\}", sin_comentarios)
    assert regla and "table-layout: fixed" in regla.group(1)
    assert re.search(r"min-width:\s*\d+px", regla.group(1)), (
        "sin ancho mínimo, en móvil las celdas se aplastan en vez de desplazarse")

    antecedente = re.search(r"\.tt-prior-reject\s*\{([^}]*)\}", sin_comentarios)
    assert antecedente and "nowrap" not in antecedente.group(1), (
        "«Rechazada antes» en una sola línea ensanchaba la columna a 268 px")

    # El `.visually-hidden` del encabezado es `position: absolute`: sin un
    # ancestro posicionado dentro del scroll, estiraba la PÁGINA en móvil.
    assert re.search(r"#tt-requests-body \.table-responsive\s*\{[^}]*position:\s*relative",
                     sin_comentarios)


# ---------------------------------------------------------------------------
# FIFO (2026-09-24): «Por revisar» se atiende en orden de llegada
# ---------------------------------------------------------------------------
# En los dos tests de abajo el id va al REVÉS del `created_at`: la fila que se
# crea PRIMERO (id más chico) es la MÁS NUEVA. Así solo pasan si el orden sale
# de `created_at`; si saliera del desempate por `id`, se caerían.
def test_por_revisar_ordena_de_la_mas_antigua_a_la_mas_nueva(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    mas_nueva = _make_req(db_session, cohort, control="99610001",
                          created_at=datetime(2001, 1, 2, 9, 0))
    mas_antigua = _make_req(db_session, cohort, control="99610002",
                            created_at=datetime(2001, 1, 1, 9, 0))
    assert mas_antigua.id > mas_nueva.id, "el id debe ir al revés del created_at"

    html = client_as(head).get(
        f"{URL}/body?status=pending_review&cohort_id={cohort.id}").text

    pos_antigua = html.index(f'id="tt-req-{mas_antigua.id}"')
    pos_nueva = html.index(f'id="tt-req-{mas_nueva.id}"')
    assert pos_antigua < pos_nueva, (
        "«Por revisar» debe salir de la solicitud más antigua a la más nueva (FIFO)")


@pytest.mark.parametrize("pestana", ["rejected", "all"])
def test_una_pestana_de_historial_sigue_de_la_mas_nueva_a_la_mas_antigua(
    client_as, db_session, make_head, make_cohort, pestana,
):
    """Las pestañas de historial (todo lo que no es «Por revisar») no cambian:
    son un archivo, no una cola de trabajo, y se siguen leyendo empezando por
    lo último que pasó."""
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    mas_nueva = _make_req(db_session, cohort, control="99610003", status="rejected",
                          created_at=datetime(2001, 1, 2, 9, 0))
    mas_antigua = _make_req(db_session, cohort, control="99610004", status="rejected",
                            created_at=datetime(2001, 1, 1, 9, 0))
    assert mas_antigua.id > mas_nueva.id, "el id debe ir al revés del created_at"

    html = client_as(head).get(
        f"{URL}/body?status={pestana}&cohort_id={cohort.id}").text

    pos_nueva = html.index(f'id="tt-req-{mas_nueva.id}"')
    pos_antigua = html.index(f'id="tt-req-{mas_antigua.id}"')
    assert pos_nueva < pos_antigua, (
        f"«{pestana}» debe seguir mostrando lo más nuevo primero")
