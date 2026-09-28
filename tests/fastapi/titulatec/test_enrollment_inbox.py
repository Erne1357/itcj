"""Bandeja de solicitudes (HTML): pestañas, qué ofrece cada fila y la pestaña que viaja.

Pestañas: "Por revisar" (`pending_review` y el legado `unverified`/`verified`,
por omisión), "En Cómputo" (`awaiting_access`, 2026-09-24), "Liga enviada"
(`approved`), "Inscritas" (`converted`), "Rechazadas" (`rejected`) y "Todas".

Modo (`EnrollmentRequestService.reviewer_mode()`, 2026-09-24): en el OFICIAL
Servicios Escolares aprueba sin NIP y la solicitud sin cuenta pasa a Centro de
Cómputo; en el ALTERNO la bandeja es de SOLO LECTURA (ni un formulario) y las
rutas POST responden 400 — eso último vive en `test_enrollment_approve.py`.

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

PESTANAS = ["Por revisar", "En Cómputo", "Liga enviada", "Inscritas", "Rechazadas", "Todas"]
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


# `modo_alterno` vive en conftest.py (C7/I-1 de la revision final: una sola
# copia compartida en vez de 4 duplicadas por archivo).


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
def test_la_bandeja_abre_en_por_revisar_con_las_seis_pestanas(
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
    ("awaiting_access", {"awaiting_access"}),
    ("approved", {"approved"}),
    ("converted", {"converted"}),
    ("rejected", {"rejected"}),
    ("all", {"pending_review", "unverified", "verified", "awaiting_access", "approved",
             "converted", "rejected"}),
])
def test_cada_pestana_muestra_solo_sus_estados(
    client_as, db_session, make_head, make_cohort, pestana, estados,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    filas = {status: _make_req(db_session, cohort, control=f"9955{i:04d}", status=status)
             for i, status in enumerate(("pending_review", "unverified", "verified",
                                         "awaiting_access", "approved", "converted",
                                         "rejected"), start=1100)}

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
def test_la_fila_por_revisar_sin_cuenta_se_aprueba_sin_nip_y_pasa_a_computo(
    client_as, db_session, make_head, make_cohort,
):
    """Modo oficial (2026-09-24): el NIP lo da Centro de Cómputo, no SE."""
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99551010")

    fila = _fila(client_as(head).get(f"{URL}/body").text, req)

    assert "Sin cuenta" in fila
    assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/aprobar"' in fila
    assert 'name="nip"' not in fila, "SE ya no captura el NIP"
    assert "Aprobar y pasar a Cómputo" in fila
    assert "Aprobar y crear acceso" not in fila
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
    assert f'id="tt-req-{req.id}"' not in resp.text, "la aprobada ya no está por revisar"
    assert f'id="tt-req-{otra.id}"' in resp.text
    # D10 oficial: aprobar sin cuenta pasa a Cómputo, y CC es quien crea la
    # cuenta con `dar-acceso`. El `nip` que llegó en el POST debe IGNORARSE
    # aquí; antes nada comprobaba que no se hubiera creado un usuario con él.
    from itcj2.core.models.user import User
    assert db_session.query(User).filter_by(control_number="99551031").first() is None


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
def test_la_pagina_explica_los_dos_caminos(client_as, db_session, make_head, monkeypatch):
    """Los días de la liga salen de `_link_ttl_hours()`, no de un literal: se
    parchea a 10 días para que un «21» escrito a mano en la plantilla se caiga."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    monkeypatch.setattr(EnrollmentRequestService, "_link_ttl_hours",
                        staticmethod(lambda: 10 * 24))
    head = make_head(perm_codes=LIST_PERMS)

    texto = _plano(client_as(head).get(URL).text)

    assert "no tiene cuenta" in texto and "Centro de Cómputo" in texto
    assert "NIP de 4 dígitos" in texto
    assert "ya tiene cuenta" in texto and "liga de activación de 10 días" in texto
    assert "7 días" not in texto and "21 días" not in texto
    # Premisa falsa (nada obliga a un egresado a cambiar el NIP): no se anuncia.
    assert "contraseña obligatorio" not in texto


def test_la_bandeja_solo_confirma_al_aprobar_y_sin_js_ni_css_inline():
    """`hx-confirm` SOLO en el formulario de aprobar (spec 2026-09-27 D7) y
    siempre con `data-tt-confirm-ok`, que es lo que lee el puente
    `htmx:confirm` → `TitulaTecUtils.confirmDialog`; sin él el modal diría
    «Confirmar» en el botón. Los estáticos viven en archivos externos."""
    import itcj2

    raiz = Path(itcj2.__file__).resolve().parent / "apps" / "titulatec" / "templates" / "titulatec"
    for ruta in (raiz / "admin" / "requests.html",
                 raiz / "admin" / "partials" / "requests_body.html"):
        sin_comentarios = re.sub(r"\{#.*?#\}", "", ruta.read_text(encoding="utf-8"), flags=re.S)
        for prohibido in ("<script", " style=", "onclick="):
            assert prohibido not in sin_comentarios, f"{ruta.name}: {prohibido}"
        etiquetas = re.findall(r"<[a-zA-Z][^>]*hx-confirm[^>]*>", sin_comentarios)
        assert sin_comentarios.count("hx-confirm") == len(etiquetas), (
            f"{ruta.name}: hx-confirm fuera de una etiqueta")
        for etiqueta in etiquetas:
            assert etiqueta.startswith("<form"), f"{ruta.name}: {etiqueta}"
            assert '/aprobar"' in etiqueta, f"{ruta.name}: hx-confirm fuera de aprobar"
            assert 'data-tt-confirm-ok="' in etiqueta, f"{ruta.name}: {etiqueta}"


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
    # La misma tabla la reusa Accesos (`#tt-access-body`, medido en navegador:
    # `scrollWidth` de 690 px en 360/390 antes del arreglo).
    assert re.search(r"#tt-requests-body \.table-responsive\s*\{[^}]*position:\s*relative",
                     sin_comentarios)
    assert re.search(r"#tt-access-body \.table-responsive\s*\{[^}]*position:\s*relative",
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


# ---------------------------------------------------------------------------
# «En Cómputo» (2026-09-24): SE aprobó una solicitud sin cuenta y Centro de
# Cómputo tiene que darle el NIP
# ---------------------------------------------------------------------------
def test_la_fila_en_computo_dice_desde_cuando_y_solo_ofrece_cancelar(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99620001", status="awaiting_access",
                    reviewed_at=datetime(2026, 9, 20, 11, 45))

    html = client_as(head).get(f"{URL}/body?status=awaiting_access").text
    fila = _fila(html, req)
    texto = _plano(fila)

    assert _pestana_activa(html) == "awaiting_access"
    assert "En Centro de Cómputo desde 20/09/2026" in texto
    assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/rechazar"' in fila
    assert "Cancelar solicitud" in fila
    assert 'name="note"' in fila and "required" in fila
    assert f'/solicitudes/{req.id}/aprobar' not in fila
    assert f'/solicitudes/{req.id}/reenviar' not in fila
    assert 'name="nip"' not in fila


def test_la_fila_en_computo_sin_fecha_de_aprobacion_no_dice_desde_vacio(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99620007", status="awaiting_access",
                    reviewed_at=None)

    texto = _plano(_fila(client_as(head).get(f"{URL}/body?status=awaiting_access").text, req))

    assert "En Centro de Cómputo" in texto
    assert "desde" not in texto


def test_en_todas_la_fila_en_computo_lleva_su_etiqueta(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99620002", status="awaiting_access",
                    reviewed_at=datetime(2026, 9, 20, 11, 45))

    fila = _fila(client_as(head).get(f"{URL}/body?status=all").text, req)

    assert "En Cómputo" in _plano(fila)


def test_aprobar_sin_cuenta_deja_la_fila_en_la_pestana_en_computo(
    client_as, db_session, make_head, make_cohort, seed_phase_defs, titulatec_app,
    correo_falso,
):
    seed_phase_defs()
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99620003")
    c = client_as(head)

    resp = c.post(f"{URL}/{req.id}/aprobar",
                  data={"program_id": "", "status": "pending_review", "cohort_id": ""})
    assert resp.status_code == 200, resp.headers.get("X-Tt-Error")

    en_computo = c.get(f"{URL}/body?status=awaiting_access&cohort_id={cohort.id}").text
    fila = _fila(en_computo, req)
    assert "En Centro de Cómputo desde" in _plano(fila)
    assert _kpi(en_computo, "En Cómputo") == 1
    assert _kpi(en_computo, "Por revisar") == 0
    # D10 oficial sin cuenta: pasa a Cómputo sin usuario ni correo (§9 del
    # spec). El fixture estaba pedido pero nunca se comprobaba.
    assert correo_falso == []


def test_cancelar_desde_en_computo_la_manda_a_rechazadas(
    client_as, db_session, make_head, make_cohort, correo_falso,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99620004", status="awaiting_access",
                    reviewed_at=datetime(2026, 9, 20, 11, 45))
    c = client_as(head)

    resp = c.post(f"{URL}/{req.id}/rechazar",
                  data={"note": "La persona pidió cancelar.", "status": "awaiting_access",
                        "cohort_id": str(cohort.id)})

    assert resp.status_code == 200, resp.headers.get("X-Tt-Error")
    assert _pestana_activa(resp.text) == "awaiting_access"
    assert f'id="tt-req-{req.id}"' not in resp.text
    rechazadas = c.get(f"{URL}/body?status=rejected&cohort_id={cohort.id}").text
    assert "La persona pidió cancelar." in _fila(rechazadas, req)
    db_session.refresh(req)
    assert req.status == "rejected"


def test_una_solicitud_devuelta_por_computo_lo_dice_con_su_nota(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    devuelta = _make_req(db_session, cohort, control="99620005",
                         returned_at=datetime(2026, 9, 21, 9, 0),
                         return_note="El número de control no coincide con el padrón.")
    normal = _make_req(db_session, cohort, control="99620006")

    html = client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text

    assert ("Devuelta por Centro de Cómputo: El número de control no coincide con el "
            "padrón.") in _plano(_fila(html, devuelta))
    assert "Devuelta por Centro de Cómputo" not in _fila(html, normal)
    # Y una píldora junto al nombre: la nota va en la columna de acciones, que
    # se lee después; la pestaña «Por revisar» tiene que delatarla de un vistazo.
    assert re.search(r'<span class="tt-pill[^"]*">Devuelta por Cómputo</span>',
                     _fila(html, devuelta))
    assert "Devuelta por Cómputo" not in _fila(html, normal)
    # Devuelta vuelve a ser trabajo de SE: se aprueba o rechaza igual.
    assert f'/solicitudes/{devuelta.id}/aprobar' in _fila(html, devuelta)


def test_el_kpi_y_el_bloque_por_ano_cuentan_las_de_computo(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="21620001", status="awaiting_access")
    _make_req(db_session, cohort, control="21620002", status="awaiting_access")
    _make_req(db_session, cohort, control="21620003", status="pending_review")

    html = client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text

    assert _kpi(html, "Total") == 3
    assert _kpi(html, "En Cómputo") == 2
    assert _kpi(html, "Por revisar") == 1
    texto = _plano(html)
    # La leyenda de `requests_body.html:91` pinta «En Cómputo» SIEMPRE que
    # `by_year` no esté vacío, aunque el conteo real sea 0: comprobar solo que
    # la palabra aparece después de «Por año de ingreso» es una aserción
    # vacía, cierta sin importar los datos. Lo que sí depende del conteo real
    # es la cifra («2 en Cómputo», de `y.access` en la ficha del año), y debe
    # estar DENTRO del bloque del desglose, no en cualquier parte de la página.
    bloque_anio = texto.split("Por año de ingreso", 1)[1]
    assert "2 en Cómputo" in bloque_anio


# ---------------------------------------------------------------------------
# Modo alterno (2026-09-24): Centro de Cómputo revisa y SE solo consulta
# ---------------------------------------------------------------------------
def test_en_modo_alterno_la_bandeja_es_de_solo_lectura(
    client_as, db_session, make_head, make_cohort, modo_alterno,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    filas = [
        _make_req(db_session, cohort, control="99621001"),
        _make_req(db_session, cohort, control="99621002", status="awaiting_access"),
        _make_req(db_session, cohort, control="99621003", status="approved",
                  verify_send_count=1, verify_token_hash="7" * 64,
                  verify_expires_at=datetime.now() + timedelta(days=1)),
    ]
    c = client_as(head)

    for pestana in ("pending_review", "awaiting_access", "approved", "all"):
        html = c.get(f"{URL}/body?status={pestana}&cohort_id={cohort.id}").text
        assert "<form" not in html, pestana
        assert "La revisión la hace Centro de Cómputo" in _plano(html), pestana
    todas = c.get(f"{URL}/body?status=all&cohort_id={cohort.id}").text
    for req in filas:
        _fila(todas, req)          # se siguen viendo: solo lectura, no oculta
    # KPIs, pestañas y año de ingreso siguen ahí.
    assert _kpi(todas, "Total") == 3
    assert 'id="tt-req-tab-awaiting_access"' in todas
    assert "Por año de ingreso" in todas


def test_en_modo_alterno_la_pagina_lo_explica(
    client_as, db_session, make_head, modo_alterno,
):
    head = make_head(perm_codes=LIST_PERMS)

    texto = _plano(client_as(head).get(URL).text)

    assert "La revisión la hace Centro de Cómputo" in texto
    assert "NIP de 4 dígitos" not in texto, "SE ya no aprueba en este modo"
    # Dicho UNA vez: la cabecera y el aviso de solo lectura lo repetían.
    assert texto.count("La revisión la hace Centro de Cómputo") == 1
    assert texto.count("aprueba, rechaza y da el acceso") == 1


def test_con_una_liga_de_un_dia_la_cabecera_dice_dia_en_singular(
    client_as, db_session, make_head, monkeypatch,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    monkeypatch.setattr(EnrollmentRequestService, "_link_ttl_hours",
                        staticmethod(lambda: 24))
    head = make_head(perm_codes=LIST_PERMS)

    texto = _plano(client_as(head).get(URL).text)

    assert "liga de activación de 1 día" in texto
    assert "1 días" not in texto


# ---------------------------------------------------------------------------
# Modo `sii` (spec 2026-09-25 §3.5 y 2026-09-27): SE actúa como en el oficial
# —aprueba siempre: nada se aprueba solo— y cada fila «Por revisar» muestra el
# veredicto VIGENTE del SII con sus motivos.
#
# Las consultas se siembran aquí a mano (`_consulta`): lo que se prueba es qué
# pinta la bandeja de una `EligibilityCheck`. Que el NIP del SII no llegue al
# HTML con una consulta REAL al SII falso vive en `test_requests_reconsultar.py`.
# ---------------------------------------------------------------------------
# `modo_sii` vive en conftest.py (Tarea 1: una sola copia compartida en vez de
# 6 duplicadas por archivo).


@pytest.fixture()
def tope_de_intentos(monkeypatch):
    """Tope de 5 intentos, aunque el `.env` diga otra cosa."""
    from itcj2.apps.titulatec.services.eligibility_service import EligibilityService

    monkeypatch.setattr(EligibilityService, "max_attempts", staticmethod(lambda: 5))


@pytest.fixture(autouse=True)
def _sii_configurado(monkeypatch):
    """Un backend que no es `disabled` (el del contenedor lo es): con el SII sin
    configurar la bandeja no ofrece «Reintentar consulta» ni pide confirmación
    (D11). La prueba de ese caso lo vuelve a parchear a `disabled`."""
    from itcj2.apps.titulatec.services.sii.client import SiiConfig

    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: "fake"))


REGLAS_NO_APTA = [
    {"rule": "existe", "ok": True, "message": "Cumple."},
    {"rule": "creditos", "ok": False, "message": "Le faltan créditos: 200 de 260."},
    {"rule": "sin_adeudos", "ok": False, "message": "Tiene adeudos en el SII (p. ej. BIBLIOTECA)."},
]
REGLAS_APTA = [
    {"rule": "existe", "ok": True, "message": "Cumple."},
    {"rule": "creditos", "ok": True, "message": "Créditos completos (260)."},
]


_COMPARADA: dict = {}


def _consulta(db_session, req, *, status, attempt=1, results=None, error=None,
              identity_mismatch=_COMPARADA, started_at=None, finished_at=None,
              retryable=True, nip_status=None):
    """Consulta del SII ya hecha (o en curso) y apuntada como la VIGENTE. Por
    omisión el nombre se comparó con el SII y coincide (`{}`); `None` = no se
    comparó (revisión final C3). `nip_status` = lo que vio del NIP (NULL = no
    se revisó)."""
    from itcj2.apps.titulatec.models import EligibilityCheck

    now = datetime.now()
    chk = EligibilityCheck(
        request_id=req.id, status=status, attempt=attempt, rules_version="test-1",
        results=results, error=error, nip_status=nip_status,
        identity_mismatch=(dict(identity_mismatch) if identity_mismatch is not None
                           else None),
        retryable=(retryable if status == "error" else None),
        started_at=started_at or now,
        finished_at=None if status == "pending" else (finished_at or now))
    db_session.add(chk)
    db_session.flush()
    req.last_check_id = chk.id
    db_session.flush()
    return chk


def _bloque_sii(fila: str, req) -> str:
    marca = f'id="tt-req-sii-{req.id}"'
    assert marca in fila, f"la fila {req.id} no trae el bloque del SII"
    return fila.split(marca, 1)[1]


@pytest.mark.parametrize("modo", ["school_services", "computer_center"])
def test_fuera_del_modo_sii_la_fila_no_habla_del_sii(
    client_as, db_session, make_head, make_cohort, monkeypatch, modo,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    monkeypatch.setattr(EnrollmentRequestService, "reviewer_mode",
                        staticmethod(lambda: modo))
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99640001")
    # Una consulta vieja (p. ej. de antes de cambiar de modo) no se anuncia.
    _consulta(db_session, req, status="not_apt", results=REGLAS_NO_APTA)

    fila = _fila(client_as(head).get(f"{URL}/body").text, req)

    assert f'id="tt-req-sii-{req.id}"' not in fila
    assert "/reconsultar" not in fila
    assert "Le faltan créditos" not in fila


def test_en_modo_sii_se_actua_como_en_el_oficial(
    client_as, db_session, make_head, make_cohort, modo_sii, tope_de_intentos,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    sin_cuenta = _make_req(db_session, cohort, control="99640002")
    _cuenta(db_session, "99640003")
    con_cuenta = _make_req(db_session, cohort, control="99640003")

    html = client_as(head).get(f"{URL}/body").text
    fila_sin, fila_con = _fila(html, sin_cuenta), _fila(html, con_cuenta)

    assert "Solo lectura" not in html
    for req, fila in ((sin_cuenta, fila_sin), (con_cuenta, fila_con)):
        assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/aprobar"' in fila
        assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/rechazar"' in fila
        assert 'name="nip"' not in fila, "el NIP sale del SII, no de SE"
    # Sin cuenta y sin consulta (NIP sin revisar) se ofrece Accesos, nunca
    # «pasar a Cómputo» (el texto del modo oficial).
    assert "pasar a cómputo" not in fila_sin.lower()
    assert "Aprobar y pasar a Accesos" in fila_sin
    assert "Aprobar y enviar liga" in fila_con


def test_en_modo_sii_la_pagina_explica_quien_decide(
    client_as, db_session, make_head, modo_sii, tope_de_intentos,
):
    head = make_head(perm_codes=LIST_PERMS)

    texto = _plano(client_as(head).get(URL).text)

    assert "El SII revisa cada solicitud y Servicios Escolares decide" in texto
    assert "se aprueban solas" not in texto, "nada se aprueba solo (spec 2026-09-27)"
    assert "NIP del SII" in texto
    # Sin NIP en el SII, el respaldo es Accesos (D1).
    assert "Accesos" in texto
    # El texto del modo oficial (Cómputo da el NIP) no aplica aquí.
    assert "NIP de 4 dígitos" not in texto


def test_la_bandeja_no_promete_aprobacion_sola(
    client_as, db_session, make_head, make_cohort, modo_sii, tope_de_intentos,
):
    """Spec 2026-09-27 §A3 (D2): ninguna solicitud se aprueba sola, así que la
    bandeja no lo promete («se aprobará sola…»), no explica por qué no pasó
    («No se aprobó sola: …») ni marca a nadie como «Aprobada automáticamente».
    Una apta es trabajo de Servicios Escolares como cualquier otra, y su nota
    vuelve a leerse como «Nota: …»."""
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    apta = _make_req(db_session, cohort, control="99640060")
    _consulta(db_session, apta, status="apt", results=REGLAS_APTA)
    con_nota = _make_req(db_session, cohort, control="99640061",
                         review_note="El SII no devolvió NIP.")
    _consulta(db_session, con_nota, status="apt", results=REGLAS_APTA)
    # Lo que antes la bandeja marcaba «Aprobada automáticamente (SII)».
    sin_revisor = _make_req(db_session, cohort, control="99640062", status="approved",
                            reviewed_at=datetime.now(), reviewed_by_id=None)
    _consulta(db_session, sin_revisor, status="apt", results=REGLAS_APTA)
    c = client_as(head)

    for pestana in ("pending_review", "approved", "all"):
        texto = _plano(c.get(f"{URL}/body?status={pestana}&cohort_id={cohort.id}").text)
        for promesa in ("se aprobará sola", "no se aprobó sola", "aprobada automáticamente"):
            assert promesa not in texto.lower(), (pestana, promesa)

    html = c.get(f"{URL}/body?cohort_id={cohort.id}").text
    assert "Apta" in _plano(_bloque_sii(_fila(html, apta), apta))
    assert _plano(_fila(html, con_nota)).count("Nota: El SII no devolvió NIP.") == 1


def test_no_apta_muestra_cada_regla_que_fallo_con_su_motivo(
    client_as, db_session, make_head, make_cohort, modo_sii, tope_de_intentos,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99640004")
    _consulta(db_session, req, status="not_apt", attempt=2, results=REGLAS_NO_APTA)

    bloque = _plano(_bloque_sii(_fila(client_as(head).get(f"{URL}/body").text, req), req))

    assert "No apta" in bloque
    assert "Le faltan créditos: 200 de 260." in bloque
    assert "Tiene adeudos en el SII (p. ej. BIBLIOTECA)." in bloque
    assert "intento 2 de 5" in bloque
    assert "Reintentar consulta" in bloque


def test_error_muestra_el_motivo_y_ofrece_reintentar(
    client_as, db_session, make_head, make_cohort, modo_sii, tope_de_intentos,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99640008")
    _consulta(db_session, req, status="error", attempt=3,
              error="El SII no respondió a tiempo.")

    bloque = _bloque_sii(_fila(client_as(head).get(f"{URL}/body").text, req), req)
    texto = _plano(bloque)

    assert "Error" in texto
    assert "El SII no respondió a tiempo." in texto
    assert "intento 3 de 5" in texto
    assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/reconsultar"' in bloque
    # Revisión final: un error reintentable bajo el tope se reintenta solo.
    assert "Se reintenta sola (intento 4 de 5)." in texto


@pytest.mark.parametrize("attempt,retryable", [(5, True), (1, False)])
def test_un_error_que_ya_no_se_reintenta_solo_no_lo_promete(
    client_as, db_session, make_head, make_cohort, modo_sii, tope_de_intentos,
    attempt, retryable,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99640042")
    _consulta(db_session, req, status="error", attempt=attempt, retryable=retryable,
              error="Falla.")

    texto = _plano(_bloque_sii(_fila(client_as(head).get(f"{URL}/body").text, req), req))

    assert "Se reintenta sola" not in texto


def test_consultando_no_ofrece_reintentar_hasta_que_la_consulta_se_cuelga(
    client_as, db_session, make_head, make_cohort, modo_sii, tope_de_intentos,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    en_curso = _make_req(db_session, cohort, control="99640009")
    _consulta(db_session, en_curso, status="pending")
    colgada = _make_req(db_session, cohort, control="99640010")
    _consulta(db_session, colgada, status="pending",
              started_at=datetime.now() - timedelta(hours=1))

    html = client_as(head).get(f"{URL}/body").text
    b_curso = _bloque_sii(_fila(html, en_curso), en_curso)
    b_colgada = _bloque_sii(_fila(html, colgada), colgada)

    assert "Consultando…" in _plano(b_curso)
    assert "/reconsultar" not in b_curso, "reintentar ahora duplicaría la consulta en curso"
    assert "sin respuesta" in _plano(b_colgada)
    assert f"/solicitudes/{colgada.id}/reconsultar" in b_colgada


def test_sin_consulta_todavia_se_puede_pedir(
    client_as, db_session, make_head, make_cohort, modo_sii, tope_de_intentos,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99640011")

    bloque = _bloque_sii(_fila(client_as(head).get(f"{URL}/body").text, req), req)

    assert "Sin consultar" in _plano(bloque)
    assert f"/solicitudes/{req.id}/reconsultar" in bloque
    assert "Consultar al SII" in bloque


def test_las_diferencias_con_el_sii_se_muestran(
    client_as, db_session, make_head, make_cohort, modo_sii, tope_de_intentos,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99640012")
    _consulta(db_session, req, status="apt", results=REGLAS_APTA, identity_mismatch={
        "first_name": {"form": "EGRESADO", "sii": "OTRA PERSONA"},
        "program": {"form": "Ingenieria de 2005", "sii": "ING. SISTEMAS (PLAN 2010)"},
    })

    texto = _plano(_bloque_sii(_fila(client_as(head).get(f"{URL}/body").text, req), req))

    assert "Diferencias con el SII" in texto
    assert "Nombre: «EGRESADO» en el formulario, «OTRA PERSONA» en el SII" in texto
    assert ("Carrera: «Ingenieria de 2005» en el formulario, "
            "«ING. SISTEMAS (PLAN 2010)» en el SII") in texto


def test_lo_que_viene_del_sii_se_escapa(
    client_as, db_session, make_head, make_cohort, modo_sii, tope_de_intentos,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99640013")
    _consulta(db_session, req, status="not_apt", results=[
        {"rule": "x", "ok": False, "message": "<img src=x onerror=alert(1)>"}],
        identity_mismatch={"last_name": {"form": "A", "sii": "<b>B</b>"}})

    fila = _fila(client_as(head).get(f"{URL}/body").text, req)

    assert "<img src=x" not in fila and "<b>B</b>" not in fila
    assert "&lt;img src=x onerror=alert(1)&gt;" in fila


def test_en_modo_sii_kpis_pestanas_y_ano_de_ingreso_siguen_intactos(
    client_as, db_session, make_head, make_cohort, modo_sii, tope_de_intentos,
):
    """S9: la bandeja sigue con TODO, contestadas incluidas."""
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99640017")
    _make_req(db_session, cohort, control="99640018", status="approved",
              reviewed_at=datetime.now())
    _make_req(db_session, cohort, control="99640019", status="rejected",
              review_note="No apta.")

    html = client_as(head).get(f"{URL}/body?status=all&cohort_id={cohort.id}").text

    assert _kpi(html, "Total") == 3
    assert "Por año de ingreso" in html
    texto = _plano(html)
    for p in PESTANAS:
        assert p in texto


@pytest.mark.parametrize("pestana", ["pending_review", "all"])
def test_la_consulta_vigente_se_carga_sin_n_mas_1(
    client_as, db_session, make_head, make_cohort, modo_sii, tope_de_intentos, pestana,
):
    """Una consulta por lote a `titulatec_eligibility_checks`, no una por fila,
    también con la columna del SII en el historial (Tarea 6)."""
    from sqlalchemy import event

    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    for i, estado in enumerate(("pending_review", "pending_review", "approved",
                                "converted", "rejected", "awaiting_access")):
        req = _make_req(db_session, cohort, control=f"996400{30 + i}", status=estado)
        _consulta(db_session, req, status="not_apt", results=REGLAS_NO_APTA)

    consultas = []
    engine = db_session.get_bind()

    def _cuenta_checks(conn, cursor, statement, *a):
        if "FROM titulatec_eligibility_checks" in statement:
            consultas.append(statement)

    event.listen(engine, "before_cursor_execute", _cuenta_checks)
    try:
        resp = client_as(head).get(f"{URL}/body?status={pestana}&cohort_id={cohort.id}")
    finally:
        event.remove(engine, "before_cursor_execute", _cuenta_checks)

    assert resp.status_code == 200
    assert len(consultas) == 1, consultas


@pytest.mark.parametrize("selector", [".tt-sii-line", ".tt-sii-rules li span"])
def test_los_textos_largos_del_bloque_sii_se_cortan(selector):
    """Revisión final (F2): un error del driver o un nombre largo sin espacios
    (ruta, cadena ODBC saneada, correo) desbordaba la celda de acciones."""
    css = re.sub(r"/\*.*?\*/", "", _CSS.read_text(encoding="utf-8"), flags=re.S)
    reglas = re.findall(r"(?m)^([^{}]+)\{([^}]*)\}", css)
    cuerpos = [cuerpo for sel, cuerpo in reglas
               if selector in [s.strip() for s in sel.split(",")]]
    assert cuerpos, f"no hay regla para {selector}"
    assert any(re.search(r"overflow-wrap:\s*anywhere", c) for c in cuerpos), cuerpos


# ---------------------------------------------------------------------------
# Columna «SII», botón según el NIP y confirmación (spec 2026-09-27 §A5, D7,
# D10, D11; Tarea 6). La columna va entre «Recibida» y las acciones en TODAS
# las pestañas: completa en lo pendiente, compacta en el historial. El botón de
# aprobar sale de `EnrollmentRequestService.approval_path` (Ruling R8) y la
# confirmación, del veredicto vigente y de `identity_block`.
# ---------------------------------------------------------------------------
CONFIRMA = "¿Aprobar de todos modos?"
AVISO_DAR_ACCESO = "La cuenta nace con su NIP del SII; el correo no lo lleva."
AVISO_ACCESOS = "Centro de Cómputo le captura el NIP en Accesos; el correo sale entonces."
AVISO_SII_OFF = ("El SII no está configurado: las solicitudes sin cuenta se aprueban "
                 "pasándolas a Accesos.")


def _form_aprobar(fila: str, req) -> str:
    """El `<form>` de aprobar de la fila, entero (apertura y campos)."""
    m = re.search(rf'<form[^>]*/solicitudes/{req.id}/aprobar".*?</form>', fila, flags=re.S)
    assert m, f"la fila {req.id} no ofrece aprobar"
    return m.group(0)


def _apertura(form: str) -> str:
    return form[:form.index(">") + 1]


def _encabezado(html: str) -> str:
    return html.split("<colgroup>", 1)[1].split("</thead>", 1)[0]


class TestColumnaSii:

    @pytest.fixture(autouse=True)
    def _modo(self, modo_sii, tope_de_intentos):
        pass

    @pytest.mark.parametrize("pestana,estado", [
        ("pending_review", "pending_review"),
        ("awaiting_access", "awaiting_access"),
        ("approved", "approved"),
        ("converted", "converted"),
        ("rejected", "rejected"),
        ("all", "pending_review"),
        ("all", "rejected"),
    ])
    def test_la_columna_sii_aparece_en_todas_las_pestanas(
        self, client_as, db_session, make_head, make_cohort, pestana, estado,
    ):
        head = make_head(perm_codes=LIST_PERMS)
        cohort = make_cohort(status="open")
        req = _make_req(db_session, cohort, control="99660001", status=estado)
        _consulta(db_session, req, status="not_apt", results=REGLAS_NO_APTA)

        html = client_as(head).get(f"{URL}/body?status={pestana}&cohort_id={cohort.id}").text
        fila = _fila(html, req)

        encabezado = _encabezado(html)
        assert encabezado.count("<col ") == 6 and encabezado.count("<th>") == 6
        assert "<th>SII</th>" in encabezado
        # Entre «Recibida» y las acciones.
        assert encabezado.index("Recibida") < encabezado.index("<th>SII</th>")
        celdas = fila.split("<td")[1:]
        assert len(celdas) == 6
        assert f'id="tt-req-sii-{req.id}"' in celdas[4]
        assert "No apta" in _plano(celdas[4])

    @pytest.mark.parametrize("estado", ["approved", "converted", "rejected"])
    def test_en_historial_la_celda_es_compacta(
        self, client_as, db_session, make_head, make_cohort, estado,
    ):
        """Píldora + nº de reglas incumplidas con sus mensajes plegados; nada
        de reintentar, NIP ni reglas cumplidas (la solicitud ya se resolvió)."""
        head = make_head(perm_codes=LIST_PERMS)
        cohort = make_cohort(status="open")
        req = _make_req(db_session, cohort, control="99660002", status=estado)
        _consulta(db_session, req, status="not_apt", results=REGLAS_NO_APTA,
                  nip_status="missing")

        html = client_as(head).get(f"{URL}/body?status=all&cohort_id={cohort.id}").text
        bloque = _bloque_sii(_fila(html, req), req).split("</td>", 1)[0]

        assert "tt-sii--compact" in _fila(html, req)
        assert "No apta" in _plano(bloque)
        plegado = bloque.split("<details", 1)
        assert len(plegado) == 2, "las reglas incumplidas van plegadas"
        assert "2 reglas incumplidas" in _plano(plegado[1])
        assert "Le faltan créditos: 200 de 260." in _plano(plegado[1])
        assert "Le faltan créditos" not in _plano(plegado[0])
        assert "/reconsultar" not in bloque
        assert "NIP" not in _plano(bloque)
        assert "reglas cumplidas" not in _plano(bloque)

    def test_por_revisar_muestra_reglas_fallidas_y_nip(
        self, client_as, db_session, make_head, make_cohort,
    ):
        head = make_head(perm_codes=LIST_PERMS)
        cohort = make_cohort(status="open")
        sin_cuenta = _make_req(db_session, cohort, control="99660003")
        _consulta(db_session, sin_cuenta, status="not_apt", results=REGLAS_NO_APTA,
                  nip_status="missing")
        _cuenta(db_session, "99660004")
        con_cuenta = _make_req(db_session, cohort, control="99660004")
        _consulta(db_session, con_cuenta, status="not_apt", results=REGLAS_NO_APTA,
                  nip_status="not_needed")

        html = client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text
        bloque = _bloque_sii(_fila(html, sin_cuenta), sin_cuenta).split("</td>", 1)[0]
        abierto = bloque.split("<details", 1)[0]

        # Las incumplidas, visibles (fuera del `<details>` de las cumplidas).
        assert "Le faltan créditos: 200 de 260." in _plano(abierto)
        assert "Tiene adeudos en el SII (p. ej. BIBLIOTECA)." in _plano(abierto)
        assert "1 regla cumplida" in _plano(bloque)
        assert "El SII no tiene NIP" in _plano(bloque)
        # Con cuenta el NIP del SII no importa: no se anuncia.
        bloque_con = _bloque_sii(_fila(html, con_cuenta), con_cuenta).split("</td>", 1)[0]
        assert "NIP" not in _plano(bloque_con)

    @pytest.mark.parametrize("nip_status,pildora,boton,a_accesos,aviso", [
        ("available", "NIP en el SII: disponible", "Aprobar y dar acceso", False,
         AVISO_DAR_ACCESO),
        ("missing", "El SII no tiene NIP", "Aprobar y pasar a Accesos", True, AVISO_ACCESOS),
        ("invalid", "NIP del SII con formato inválido", "Aprobar y pasar a Accesos", True,
         AVISO_ACCESOS),
        ("unavailable", "No se pudo leer el NIP (SII sin respuesta)",
         "Aprobar y pasar a Accesos", True, AVISO_ACCESOS),
        ("error", "No se pudo leer el NIP (configuración)", "Aprobar y pasar a Accesos",
         True, AVISO_ACCESOS),
        (None, "NIP sin revisar", "Aprobar y pasar a Accesos", True, AVISO_ACCESOS),
        ("not_needed", "NIP sin revisar", "Aprobar y pasar a Accesos", True, AVISO_ACCESOS),
    ])
    def test_boton_segun_estado_del_nip(
        self, client_as, db_session, make_head, make_cohort, nip_status, pildora, boton,
        a_accesos, aviso,
    ):
        head = make_head(perm_codes=LIST_PERMS)
        cohort = make_cohort(status="open")
        req = _make_req(db_session, cohort, control="99660005")
        _consulta(db_session, req, status="apt", results=REGLAS_APTA, nip_status=nip_status)

        fila = _fila(client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text, req)
        form = _form_aprobar(fila, req)

        assert pildora in _plano(_bloque_sii(fila, req).split("</td>", 1)[0])
        assert re.search(rf"<button[^>]*>\s*{re.escape(boton)}\s*</button>", form), form
        assert ('<input type="hidden" name="to_access" value="1">' in form) is a_accesos
        assert fila.count('name="to_access"') == (1 if a_accesos else 0)
        assert aviso in _plano(fila)
        otro = AVISO_DAR_ACCESO if a_accesos else AVISO_ACCESOS
        assert otro not in _plano(fila)
        assert AVISO_CON_CUENTA not in _plano(fila)
        assert "Aprobar y crear cuenta" not in fila and "pasar a Cómputo" not in fila

    def test_con_cuenta_el_boton_es_enviar_liga_sin_importar_el_nip(
        self, client_as, db_session, make_head, make_cohort,
    ):
        head = make_head(perm_codes=LIST_PERMS)
        cohort = make_cohort(status="open")
        _cuenta(db_session, "99660006")
        req = _make_req(db_session, cohort, control="99660006")
        _consulta(db_session, req, status="apt", results=REGLAS_APTA, nip_status="missing")

        fila = _fila(client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text, req)
        form = _form_aprobar(fila, req)

        assert "Aprobar y enviar liga" in form
        assert 'name="to_access"' not in fila
        assert AVISO_CON_CUENTA in _plano(fila)
        assert AVISO_DAR_ACCESO not in _plano(fila) and AVISO_ACCESOS not in _plano(fila)

    @pytest.mark.parametrize("caso", ["sin_consulta", "error", "sin_configurar"])
    def test_consulta_en_error_o_sin_consulta_sigue_aprobable_via_accesos(
        self, client_as, db_session, make_head, make_cohort, monkeypatch, caso,
    ):
        """Review Focus 1: con la consulta vigente en `error` (reglas no
        montadas en el worker: de configuración, no se reintenta), sin consulta
        o con el SII sin configurar, la fila sin cuenta nunca queda sin botón."""
        from itcj2.apps.titulatec.services.sii.client import SiiConfig

        head = make_head(perm_codes=LIST_PERMS)
        cohort = make_cohort(status="open")
        req = _make_req(db_session, cohort, control="99660007")
        if caso == "error":
            _consulta(db_session, req, status="error", retryable=False,
                      error="No se encontraron las reglas del SII.")
        if caso == "sin_configurar":
            monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: "disabled"))

        fila = _fila(client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text, req)
        form = _form_aprobar(fila, req)

        assert "Aprobar y pasar a Accesos" in form
        assert '<input type="hidden" name="to_access" value="1">' in form
        assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/rechazar"' in fila

    @pytest.mark.parametrize("status", ["unverified", "verified"])
    def test_fila_legado_ofrece_pasar_a_accesos(
        self, client_as, db_session, make_head, make_cohort, status,
    ):
        """Review Focus 4: el legado no tiene consulta posible (`check` no lo
        consulta): «Sin consultar», sin «Consultar al SII», y se aprueba
        pasándolo a Accesos (`approve(to_access=True)` lo acepta)."""
        head = make_head(perm_codes=LIST_PERMS)
        cohort = make_cohort(status="open")
        req = _make_req(db_session, cohort, control="99660008", status=status)

        fila = _fila(client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text, req)
        form = _form_aprobar(fila, req)

        bloque = _bloque_sii(fila, req).split("</td>", 1)[0]
        assert "Sin consultar" in _plano(bloque)
        assert "/reconsultar" not in fila
        assert "Aprobar y pasar a Accesos" in form
        assert '<input type="hidden" name="to_access" value="1">' in form

    @pytest.mark.parametrize("caso,confirmacion", [
        ("sin_consulta", f"No se ha consultado al SII. {CONFIRMA}"),
        ("no_apta", "El SII dijo «No apta»: Le faltan créditos: 200 de 260; Tiene adeudos "
                    f"en el SII (p. ej. BIBLIOTECA). {CONFIRMA}"),
        ("error", f"La consulta al SII terminó en error. {CONFIRMA}"),
        ("consultando", f"La consulta al SII sigue en curso. {CONFIRMA}"),
        ("nombre_distinto", "El nombre del formulario no coincide con el del SII (nombre); "
                            "confirma que la solicitud sea de esa persona antes de "
                            f"aprobarla. {CONFIRMA}"),
        ("nombre_sin_comparar", f"No se pudo comparar el nombre con el SII. {CONFIRMA}"),
        ("nombre_sin_comparar_parcial", f"No se pudo comparar el nombre con el SII. {CONFIRMA}"),
        ("apta", None),
        ("apta_carrera_distinta", None),
    ])
    def test_confirmacion_si_no_apta_o_nombre_distinto(
        self, client_as, db_session, make_head, make_cohort, caso, confirmacion,
    ):
        """D7: el formulario de aprobar pide confirmación cuando el SII no dijo
        «Apta», no hay veredicto, o el nombre no coincide / no se pudo
        comparar; el texto dice el motivo. La carrera del SII llega como clave
        (siempre «diferente»): no pide confirmación (spec §11)."""
        import html as html_mod

        head = make_head(perm_codes=LIST_PERMS)
        cohort = make_cohort(status="open")
        req = _make_req(db_session, cohort, control="99660009")
        consultas = {
            "no_apta": dict(status="not_apt", results=REGLAS_NO_APTA),
            "error": dict(status="error", error="Falla."),
            "consultando": dict(status="pending"),
            "nombre_distinto": dict(status="apt", results=REGLAS_APTA, identity_mismatch={
                "first_name": {"form": "EGRESADO", "sii": "OTRA PERSONA"}}),
            "nombre_sin_comparar": dict(status="apt", results=REGLAS_APTA,
                                        identity_mismatch=None),
            "nombre_sin_comparar_parcial": dict(status="apt", results=REGLAS_APTA,
                                                identity_mismatch={"_unverified": ["last_name"]}),
            "apta": dict(status="apt", results=REGLAS_APTA),
            "apta_carrera_distinta": dict(status="apt", results=REGLAS_APTA, identity_mismatch={
                "program": {"form": "Ingenieria de 2005", "sii": "ISC-2010"}}),
        }
        if caso in consultas:
            _consulta(db_session, req, **consultas[caso])

        fila = _fila(client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text, req)
        apertura = _apertura(_form_aprobar(fila, req))

        if confirmacion is None:
            assert "hx-confirm" not in fila and "data-tt-confirm-ok" not in fila
            return
        m = re.search(r'hx-confirm="([^"]*)"', apertura)
        assert m, apertura
        titulo, _, cuerpo = html_mod.unescape(m.group(1)).partition("|")
        assert titulo == "Aprobar solicitud"
        assert cuerpo == confirmacion
        assert 'data-tt-confirm-ok="Aprobar"' in apertura
        # Solo el formulario de aprobar confirma; rechazar no.
        assert fila.count("hx-confirm") == 1

    def test_sii_no_configurado_muestra_aviso_y_no_pide_confirmacion(
        self, client_as, db_session, make_head, make_cohort, monkeypatch,
    ):
        """D11: aviso de página, «Sin consultar», sin «Reintentar consulta» (la
        ruta daría 400) y sin confirmación: no hay veredicto que discutir, se
        aprueba pasando a Accesos."""
        from itcj2.apps.titulatec.services.sii.client import SiiConfig

        monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: "disabled"))
        head = make_head(perm_codes=LIST_PERMS)
        cohort = make_cohort(status="open")
        nueva = _make_req(db_session, cohort, control="99660010")
        # Una consulta de cuando SÍ estaba configurado: se sigue leyendo.
        vieja = _make_req(db_session, cohort, control="99660011")
        _consulta(db_session, vieja, status="not_apt", results=REGLAS_NO_APTA)

        html = client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text

        aviso = html.split('id="tt-req-sii-off"', 1)
        assert len(aviso) == 2, "falta el aviso de página"
        assert AVISO_SII_OFF in _plano(aviso[1].split("</div>", 1)[0])
        assert html.index('id="tt-req-sii-off"') < html.index("<table")
        assert "Sin consultar" in _plano(_bloque_sii(_fila(html, nueva), nueva))
        assert "No apta" in _plano(_bloque_sii(_fila(html, vieja), vieja))
        for texto in ("/reconsultar", "Reintentar consulta", "Consultar al SII",
                      "hx-confirm", "data-tt-confirm-ok"):
            assert texto not in html, texto
        assert "Aprobar y pasar a Accesos" in _form_aprobar(_fila(html, nueva), nueva)

    def test_con_sii_configurado_no_hay_aviso(
        self, client_as, db_session, make_head, make_cohort,
    ):
        head = make_head(perm_codes=LIST_PERMS)
        _make_req(db_session, make_cohort(status="open"), control="99660012")

        assert 'id="tt-req-sii-off"' not in client_as(head).get(f"{URL}/body").text


@pytest.mark.parametrize("modo", ["school_services", "sii"])
def test_en_computo_es_fifo_por_reviewed_at(
    client_as, db_session, make_head, make_cohort, monkeypatch, modo,
):
    """D10 (Ruling R4: en todos los modos, es la misma cola): «En Cómputo» se
    atiende en el orden en que SE la mandó (`reviewed_at`), no en el de llegada.
    El `created_at` y el `id` van al REVÉS a propósito: la que se mandó
    primero es la más vieja por `created_at` y la de `id` mayor, así que con el
    orden de antes (`created_at` DESC) o por `id` saldría al final."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    monkeypatch.setattr(EnrollmentRequestService, "reviewer_mode", staticmethod(lambda: modo))
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    mandada_despues = _make_req(db_session, cohort, control="99661001",
                                status="awaiting_access",
                                created_at=datetime(2001, 1, 2, 9, 0),
                                reviewed_at=datetime(2001, 2, 2, 9, 0))
    mandada_antes = _make_req(db_session, cohort, control="99661002",
                              status="awaiting_access",
                              created_at=datetime(2001, 1, 1, 9, 0),
                              reviewed_at=datetime(2001, 2, 1, 9, 0))
    assert mandada_antes.id > mandada_despues.id, "el id debe ir al revés del reviewed_at"

    html = client_as(head).get(
        f"{URL}/body?status=awaiting_access&cohort_id={cohort.id}").text

    assert (html.index(f'id="tt-req-{mandada_antes.id}"')
            < html.index(f'id="tt-req-{mandada_despues.id}"')), (
        "«En Cómputo» debe salir de la que SE mandó primero a la última (FIFO)")


def test_modo_oficial_sin_columna_sii(
    client_as, db_session, make_head, make_cohort, monkeypatch,
):
    """Modo oficial (`school_services`, el del autouse): las 5 columnas y el
    botón de hoy, sin `to_access`, sin confirmación y sin el aviso del SII,
    aunque el SII no esté configurado."""
    from itcj2.apps.titulatec.services.sii.client import SiiConfig

    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: "disabled"))
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99661003")
    _consulta(db_session, req, status="not_apt", results=REGLAS_NO_APTA)

    html = client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text
    fila = _fila(html, req)

    encabezado = _encabezado(html)
    assert encabezado.count("<col ") == 5 and encabezado.count("<th>") == 5
    assert "<th>SII</th>" not in encabezado
    assert len(fila.split("<td")[1:]) == 5
    assert "tt-req-sii" not in html
    assert "Aprobar y pasar a Cómputo" in _form_aprobar(fila, req)
    for texto in ("to_access", "hx-confirm", "Accesos", "NIP"):
        assert texto not in fila, texto


def test_el_css_reparte_seis_columnas_en_modo_sii():
    """Las 6 columnas del modo `sii` suman 100 % y la tabla conserva un mínimo
    (bajo él se desplaza DENTRO de `.table-responsive`); las píldoras largas
    del SII («No se pudo leer el NIP (SII sin respuesta)») parten renglón en
    vez de desbordar la columna."""
    css = re.sub(r"/\*.*?\*/", "", _CSS.read_text(encoding="utf-8"), flags=re.S)

    base = re.search(r"\.tt-req-table--sii\s*\{([^}]*)\}", css)
    assert base and re.search(r"min-width:\s*\d+px", base.group(1))
    anchos = {}
    for col in ("who", "prog", "contact", "date", "sii", "acc"):
        m = re.search(rf"\.tt-req-table--sii \.tt-req-col-{col}\s*\{{\s*width:\s*(\d+)%",
                      css)
        assert m, col
        anchos[col] = int(m.group(1))
    assert sum(anchos.values()) == 100, anchos
    pildora = re.search(r"\.tt-sii \.tt-pill\s*\{([^}]*)\}", css)
    assert pildora and "white-space: normal" in pildora.group(1)
