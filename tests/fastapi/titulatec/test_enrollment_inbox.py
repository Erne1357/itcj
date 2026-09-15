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

PESTANAS = ["Por revisar", "Liga enviada", "Inscritas", "Rechazadas", "Todas"]
AVISO_CON_CUENTA = ("La liga de activación irá a este correo, que escribió el "
                    "solicitante. Confirma su identidad antes de aprobar.")


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
    assert "lo.tecleo@example.invalid" in fila
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
