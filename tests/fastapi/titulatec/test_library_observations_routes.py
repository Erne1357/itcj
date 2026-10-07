"""«Con observaciones» en las bandejas: rutas de Biblioteca (Observar /
Actualizar observación / Rehabilitar, pestaña nueva) y lo que ve Caja.

Spec `docs/superpowers/specs/2026-10-05-titulatec-biblioteca-observaciones-
design.md` §3.4 (`caja_pill`) y §3.5 (bandeja). La máquina de estados ya la
cubre `test_library_observations.py`; aquí solo la RUTA (permisos, 400/404,
re-pintado de pestaña/página/búsqueda, contador) y el HTML.

DATOS. La BD de dev es COMPARTIDA: las listas y contadores se aíslan con un
token único en el apellido (`q`), nunca por absolutos.
"""
from __future__ import annotations

import re
import uuid
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

LIB = "/titulatec/admin/biblioteca"
CAJA = "/titulatec/admin/caja"

LIBRARY_PERMS = (
    "titulatec.library_clearance.page.list",
    "titulatec.library_clearance.api.register",
    "titulatec.library_clearance.api.prior",
    "titulatec.library_clearance.api.revert",
)
CASHIER_PERMS = (
    "titulatec.library_payment.page.list",
    "titulatec.library_payment.api.register",
    "titulatec.library_payment.api.revert",
)

DONACION = Decimal("800.00")
ADEUDO = Decimal("300.00")
TOTAL = ADEUDO + DONACION
MOTIVO = "Libro dañado: «Cálculo» de Stewart"


@pytest.fixture(autouse=True)
def _correo_encendido(monkeypatch):
    from itcj2.config import get_settings

    monkeypatch.setattr(get_settings(), "TITULATEC_EMAIL_ENABLED", True)


@pytest.fixture(autouse=True)
def _graph_prohibido(monkeypatch):
    def _prohibido(*_a, **_k):
        raise AssertionError("nada aquí manda correo de verdad")

    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent", _prohibido)
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", _prohibido)


@pytest.fixture()
def staff(make_user, make_role, grant_user_role):
    def _make(perms=LIBRARY_PERMS, role="tt_test_library_obs", first_name="BIBLIOTECA",
              last_name="OBSERVA"):
        user = make_user(first_name=first_name, last_name=last_name)
        grant_user_role(user, make_role(role, perms))
        return user

    return _make


@pytest.fixture()
def cajera(make_user, make_role, grant_user_role):
    user = make_user(first_name="CAJA", last_name="OBSERVA")
    grant_user_role(user, make_role("tt_test_cashier_obs", CASHIER_PERMS))
    return user


@pytest.fixture()
def token():
    return "OBS" + uuid.uuid4().hex[:10].upper()


@pytest.fixture()
def nuevo(db_session, make_student, make_process, make_cohort, make_library_clearance):
    """Egresado + proceso + su fila de no adeudo en `status` (convocatoria con
    donación $800)."""
    def _build(*, status="pending", last_name="FICTICIO", **cols):
        cohort = make_cohort(book_donation_amount=DONACION)
        student = make_student(last_name=last_name)
        process = make_process(student, cohort=cohort, current_phase=1,
                               library_clearance=None)
        if status in ("awaiting_payment", "observed") and "total_amount" not in cols:
            cols = {"debt_amount": ADEUDO, "donation_amount": DONACION,
                    "total_amount": TOTAL, **cols}
        clearance = make_library_clearance(process, status=status, **cols)
        return SimpleNamespace(process=process, student=student, clearance=clearance)

    return _build


def _observar_svc(db, clearance_id, actor_id, reason=MOTIVO):
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    return LibraryClearanceService.observe(db, clearance_id, reason=reason, actor_id=actor_id)


def _fila(html, marca):
    """La fila y, si la trae, su `<tr id="lib-{id}-panel">` de dictamen (spec
    2026-10-05-titulatec-biblioteca-acciones §3.1): los formularios de la
    fila viven ahí desde ese rediseño."""
    assert marca in html, "falta la fila sembrada"
    resto = html.split(marca, 1)[1]
    fila, resto = resto.split("</tr>", 1)
    m = re.match(r'\s*<tr id="%s-panel"' % re.escape(marca[4:-1]), resto)
    if m:
        fila += resto.split("</tr>", 1)[0]
    return fila


def _tab_span(html, tab_id):
    m = re.search(r'id="%s".*?</button>' % re.escape(tab_id), html, re.S)
    return m.group(0) if m else ""


def _visible(html):
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


# ---------------------------------------------------------------------------
# Biblioteca: Observar / Actualizar / Rehabilitar
# ---------------------------------------------------------------------------
def test_observar_ruta_ok_y_repinta_pestana(client_as, db_session, staff, nuevo, token):
    """Observar desde «Por revisar» re-pinta la MISMA pestaña con la misma
    búsqueda; la fila sale de ahí y la pestaña «Con observaciones» la cuenta."""
    yo = staff()
    esc = nuevo(last_name=token)

    resp = client_as(yo).post(f"{LIB}/{esc.clearance.id}/observar",
                              data={"status": "pending", "q": token, "page": "1",
                                    "reason": f"  {MOTIVO}  "})

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-library-body"' in resp.text
    assert 'id="tt-lib-tab-pending" type="button"' in resp.text
    assert 'aria-current="true"' in _tab_span(resp.text, "tt-lib-tab-pending")
    assert f'id="lib-{esc.clearance.id}"' not in resp.text, "ya no está por revisar"
    assert ">1</span>" in _tab_span(resp.text, "tt-lib-tab-observed")
    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "observed"
    assert esc.clearance.observation_reason == MOTIVO
    assert esc.clearance.observed_by_id == yo.id


def test_observar_desde_en_caja(client_as, db_session, staff, nuevo, token):
    esc = nuevo(status="awaiting_payment", last_name=token)

    resp = client_as(staff()).post(f"{LIB}/{esc.clearance.id}/observar",
                                   data={"status": "awaiting_payment", "q": token,
                                         "page": "1", "reason": MOTIVO})

    assert resp.status_code == 200, resp.text[:500]
    assert 'aria-current="true"' in _tab_span(resp.text, "tt-lib-tab-awaiting_payment")
    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "observed"
    assert esc.clearance.ready_at is None


def test_observar_pagina_fuera_de_rango_se_acota(client_as, db_session, staff, nuevo, token):
    """§3.3 del spec de paginación: si la acción vacía la página en la que
    estaba, el re-pintado se acota a la última que existe (nunca 400/500)."""
    esc = nuevo(last_name=token)

    resp = client_as(staff()).post(f"{LIB}/{esc.clearance.id}/observar",
                                   data={"status": "pending", "q": token, "page": "7",
                                         "reason": MOTIVO})

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-library-body"' in resp.text


def test_observar_sin_motivo_400(client_as, db_session, staff, nuevo, token):
    esc = nuevo(last_name=token)

    for reason in ("", "   "):
        resp = client_as(staff()).post(f"{LIB}/{esc.clearance.id}/observar",
                                       data={"status": "pending", "q": token, "page": "1",
                                             "reason": reason})
        assert resp.status_code == 400, resp.text[:300]
        assert unquote(resp.headers.get("X-Tt-Error") or "")
    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "pending"


def test_observar_liberado_400_con_mensaje(client_as, db_session, staff, nuevo, token):
    esc = nuevo(status="cleared", last_name=token, cleared_via="no_charge",
                debt_amount=Decimal("0"), donation_amount=Decimal("0"),
                total_amount=Decimal("0"))

    resp = client_as(staff()).post(f"{LIB}/{esc.clearance.id}/observar",
                                   data={"status": "cleared", "q": token, "page": "1",
                                         "reason": MOTIVO})

    assert resp.status_code == 400, resp.text[:300]
    assert "primero revierte" in unquote(resp.headers["X-Tt-Error"])


def test_observar_y_rehabilitar_id_inexistente_404(client_as, staff):
    c = client_as(staff())
    assert c.post(f"{LIB}/999999999/observar",
                  data={"status": "pending", "reason": MOTIVO}).status_code == 404
    assert c.post(f"{LIB}/999999999/rehabilitar",
                  data={"status": "observed"}).status_code == 404


@pytest.mark.parametrize("sufijo", ["observar", "rehabilitar"])
def test_observar_sin_permiso_403_o_redirect(sufijo, client_as, db_session, staff, nuevo, token):
    """Solo lectura (`page.list`) o los otros permisos de Biblioteca
    (`prior`/`revert`) NO alcanzan: la ruta exige `api.register`."""
    esc = nuevo(status="observed", last_name=token, observation_reason=MOTIVO)
    sin = staff(perms=("titulatec.library_clearance.page.list",
                       "titulatec.library_clearance.api.prior",
                       "titulatec.library_clearance.api.revert"),
                role="tt_test_library_obs_sin", first_name="SIN", last_name="REGISTRO")

    resp = client_as(sin).post(f"{LIB}/{esc.clearance.id}/{sufijo}",
                               data={"status": "observed", "q": "", "page": "1",
                                     "reason": MOTIVO})

    assert resp.status_code in (302, 303, 403), resp.text[:300]
    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "observed"


@pytest.mark.parametrize("sufijo", ["observar", "rehabilitar"])
def test_permiso_exacto_de_register_basta(sufijo, client_as, db_session, staff, nuevo, token):
    esc = nuevo(status="observed", last_name=token, observation_reason=MOTIVO)
    justo = staff(perms=("titulatec.library_clearance.api.register",),
                  role="tt_test_library_obs_justo", first_name="JUSTO", last_name="REGISTRO")

    resp = client_as(justo).post(f"{LIB}/{esc.clearance.id}/{sufijo}",
                                 data={"status": "observed", "q": token, "page": "1",
                                       "reason": "Otro motivo"})

    assert resp.status_code == 200, resp.text[:300]


def test_actualizar_observacion_cambia_el_motivo(client_as, db_session, staff, nuevo, token):
    esc = nuevo(last_name=token)
    yo = staff()
    _observar_svc(db_session, esc.clearance.id, yo.id)

    resp = client_as(yo).post(f"{LIB}/{esc.clearance.id}/observar",
                              data={"status": "observed", "q": token, "page": "1",
                                    "reason": "Falta credencial"})

    assert resp.status_code == 200, resp.text[:500]
    assert 'aria-current="true"' in _tab_span(resp.text, "tt-lib-tab-observed")
    assert "Falta credencial" in _fila(resp.text, f'id="lib-{esc.clearance.id}"')
    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "observed"
    assert esc.clearance.observation_reason == "Falta credencial"


def test_rehabilitar_ruta_ok(client_as, db_session, staff, nuevo, token):
    """Rehabilitar regresa a «Por revisar» con los montos intactos y re-pinta
    «Con observaciones» (ya vacía para esa búsqueda)."""
    esc = nuevo(status="awaiting_payment", last_name=token)
    yo = staff()
    _observar_svc(db_session, esc.clearance.id, yo.id)

    resp = client_as(yo).post(f"{LIB}/{esc.clearance.id}/rehabilitar",
                              data={"status": "observed", "q": token, "page": "1"})

    assert resp.status_code == 200, resp.text[:500]
    assert 'aria-current="true"' in _tab_span(resp.text, "tt-lib-tab-observed")
    assert f'id="lib-{esc.clearance.id}"' not in resp.text
    assert ">1</span>" in _tab_span(resp.text, "tt-lib-tab-pending")
    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "pending"
    assert esc.clearance.total_amount == TOTAL
    assert esc.clearance.observation_reason is None


def test_rehabilitar_no_observado_400(client_as, db_session, staff, nuevo, token):
    esc = nuevo(last_name=token)

    resp = client_as(staff()).post(f"{LIB}/{esc.clearance.id}/rehabilitar",
                                   data={"status": "pending", "q": token, "page": "1"})

    assert resp.status_code == 400, resp.text[:300]
    assert "no tiene observaciones" in unquote(resp.headers["X-Tt-Error"])


# ---------------------------------------------------------------------------
# Biblioteca: pestaña y fila
# ---------------------------------------------------------------------------
def test_pestana_con_observaciones_y_contador(client_as, db_session, staff, nuevo, token):
    """Pestaña «Con observaciones» ENTRE «En caja» y «Liberados», con su
    contador (acotado por la búsqueda) y paginada como las demás."""
    yo = staff()
    a, b = nuevo(last_name=token), nuevo(status="awaiting_payment", last_name=token)
    nuevo(last_name=token)   # se queda en «Por revisar»
    _observar_svc(db_session, a.clearance.id, yo.id)
    _observar_svc(db_session, b.clearance.id, yo.id)

    resp = client_as(yo).get(f"{LIB}/body", params={"status": "observed", "q": token})

    assert resp.status_code == 200, resp.text[:500]
    html = resp.text
    orden = [html.index(f'id="tt-lib-tab-{k}"')
             for k in ("pending", "awaiting_payment", "observed", "cleared")]
    assert orden == sorted(orden)
    pestana = _tab_span(html, "tt-lib-tab-observed")
    assert "Con observaciones" in pestana and ">2</span>" in pestana
    assert 'aria-current="true"' in pestana
    assert ">1</span>" in _tab_span(html, "tt-lib-tab-pending")
    assert f'id="lib-{a.clearance.id}"' in html and f'id="lib-{b.clearance.id}"' in html
    assert "q=" + token in pestana


def test_fila_observada_muestra_motivo_y_acciones(client_as, db_session, staff, nuevo, token):
    yo = staff(first_name="LUCIA", last_name="REVISORA")
    esc = nuevo(last_name=token)
    _observar_svc(db_session, esc.clearance.id, yo.id)

    html = client_as(yo).get(f"{LIB}/body", params={"status": "observed", "q": token}).text
    fila = _fila(html, f'id="lib-{esc.clearance.id}"')
    texto = _visible(fila)

    assert "Con observaciones" in texto
    assert "Libro dañado" in texto and "Stewart" in texto
    assert "LUCIA" in texto and "REVISORA" in texto
    assert re.search(r"\d{2}/\d{2}/\d{4}", texto), "falta la fecha de la observación"
    # Rehabilitar: hx-confirm vía el puente, en el <form> que lleva hx-post.
    assert re.search(r'<form[^>]*hx-post="/titulatec/admin/biblioteca/%d/rehabilitar"[^>]*'
                     r'data-tt-confirm-ok="Activar"[^>]*hx-confirm="' % esc.clearance.id, fila)
    # Actualizar observación: textarea obligatoria, maxlength 1000, precargada.
    m = re.search(r'<form[^>]*hx-post="/titulatec/admin/biblioteca/%d/observar"[^>]*>(.*?)</form>'
                  % esc.clearance.id, fila, re.S)
    assert m, "falta «Actualizar observación»"
    assert "hx-confirm=" in m.group(0) and "data-tt-confirm-ok=" in m.group(0)
    assert re.search(r'<textarea[^>]*name="reason"[^>]*required[^>]*maxlength="1000"', m.group(1))
    assert "Actualizar observación" in m.group(1)
    assert 'name="status" value="observed"' in m.group(1)
    # Ninguna otra acción en una observada.
    assert "/registrar" not in fila and "/previa" not in fila and "/revertir" not in fila
    assert "confirm(" not in html and "alert(" not in html


@pytest.mark.parametrize("status", ["pending", "awaiting_payment"])
def test_filas_por_revisar_y_en_caja_ofrecen_observar(status, client_as, nuevo, staff, token):
    esc = nuevo(status=status, last_name=token)

    html = client_as(staff()).get(f"{LIB}/body", params={"status": status, "q": token}).text
    fila = _fila(html, f'id="lib-{esc.clearance.id}"')

    m = re.search(r'<form[^>]*hx-post="/titulatec/admin/biblioteca/%d/observar"[^>]*>(.*?)</form>'
                  % esc.clearance.id, fila, re.S)
    assert m, "falta «Observar»"
    assert "hx-confirm=" in m.group(0) and "data-tt-confirm-ok=" in m.group(0)
    assert re.search(r'<textarea[^>]*name="reason"[^>]*required[^>]*maxlength="1000"', m.group(1))
    assert f'name="status" value="{status}"' in m.group(1)


# ---------------------------------------------------------------------------
# Caja
# ---------------------------------------------------------------------------
def test_caja_por_cobrar_excluye_observado(client_as, db_session, staff, cajera, nuevo, token):
    """Review Focus 1: observar a uno que estaba En caja lo saca de «Por
    cobrar» (lista y contador)."""
    esc = nuevo(status="awaiting_payment", last_name=token)
    c = client_as(cajera)
    antes = c.get(f"{CAJA}/body").text
    n_antes = int(re.search(r'>(\d+)</span>', _tab_span(antes, "tt-cashier-tab-por_cobrar")).group(1))
    _observar_svc(db_session, esc.clearance.id, staff().id)
    despues = c.get(f"{CAJA}/body").text
    n_despues = int(re.search(r'>(\d+)</span>',
                              _tab_span(despues, "tt-cashier-tab-por_cobrar")).group(1))

    assert n_despues == n_antes - 1
    assert f'id="caja-{esc.clearance.id}"' not in despues


def test_caja_busqueda_pill_observado(client_as, db_session, staff, cajera, nuevo, token):
    esc = nuevo(status="awaiting_payment", last_name=token)
    _observar_svc(db_session, esc.clearance.id, staff().id)

    html = client_as(cajera).get(f"{CAJA}/body", params={"q": token}).text
    fila = _fila(html, f'id="caja-{esc.clearance.id}"')

    assert "Con observaciones (Biblioteca)" in _visible(fila)
    assert "Por cobrar" not in _visible(fila)
    assert "/pagar" not in fila
    assert "Sin acciones en Caja" in _visible(fila)


def test_caja_pagar_observado_repinta_con_aviso(client_as, db_session, staff, cajera, nuevo, token):
    """Un «Por cobrar» viejo en pantalla: Biblioteca lo observó mientras
    tanto. Nunca se cobra; la ruta re-pinta la bandeja (como el choque de
    monto, Ruling R24) con el motivo claro en `X-Tt-Notice` warning, en vez
    de un 400 sin swap que deja la fila vieja ofreciendo «Registrar pago»."""
    esc = nuevo(status="awaiting_payment", last_name=token)
    _observar_svc(db_session, esc.clearance.id, staff().id)

    resp = client_as(cajera).post(f"{CAJA}/{esc.clearance.id}/pagar",
                                  data={"tab": "por_cobrar", "q": token, "dia": "", "page": "1",
                                        "expected_total": str(TOTAL)})

    assert resp.status_code == 200, resp.text[:300]
    assert not resp.headers.get("X-Tt-Error")
    aviso = unquote(resp.headers.get("X-Tt-Notice") or "")
    assert "observaciones" in aviso and "Biblioteca" in aviso
    assert resp.headers.get("X-Tt-Notice-Kind") == "warning"
    assert 'id="tt-cashier-body"' in resp.text
    fila = _fila(resp.text, f'id="caja-{esc.clearance.id}"')
    assert "Con observaciones (Biblioteca)" in _visible(fila) and "/pagar" not in fila
    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "observed"
    assert esc.clearance.paid_at is None and esc.clearance.receipt_number is None


def test_clearance_observed_sigue_siendo_value_error():
    """Caja distingue a la observada por TIPO (`ClearanceObserved`), no
    comparando el estado fuera de los dueños (invariante 2,
    `test_clearance_gate.py`); los llamadores viejos y el lote la siguen
    tratando como cualquier regla de negocio."""
    from itcj2.apps.titulatec.services.library_clearance_service import (
        ClearanceConflict, ClearanceObserved,
    )
    assert issubclass(ClearanceObserved, ValueError)
    assert not issubclass(ClearanceObserved, ClearanceConflict)


# ---------------------------------------------------------------------------
# Biblioteca: montos precargados al rehabilitar, XSS del motivo, filtro de admitidos
# ---------------------------------------------------------------------------
def test_rehabilitado_precarga_montos_y_nota_en_por_revisar(client_as, db_session, staff,
                                                            nuevo, token):
    """observar -> rehabilitar una fila con adeudo: «Por revisar» muestra los
    montos conservados y precarga «Con adeudo…» (monto y nota), escapados."""
    yo = staff()
    esc = nuevo(status="awaiting_payment", last_name=token, library_note='Nota "x" <b>y</b>')
    _observar_svc(db_session, esc.clearance.id, yo.id)
    client_as(yo).post(f"{LIB}/{esc.clearance.id}/rehabilitar",
                       data={"status": "observed", "q": token, "page": "1"})

    html = client_as(yo).get(f"{LIB}/body", params={"status": "pending", "q": token}).text
    fila = _fila(html, f'id="lib-{esc.clearance.id}"')

    assert "Montos previos" in fila and "300.00" in fila
    m = re.search(r'<form[^>]*hx-post="[^"]*/%d/registrar"[^>]*>(?:(?!</form>).)*?'
                  r'name="debt_amount" required\s+value="([^"]*)"' % esc.clearance.id, fila, re.S)
    assert m and Decimal(m.group(1)) == ADEUDO
    assert 'value="Nota &#34;x&#34; &lt;b&gt;y&lt;/b&gt;"' in fila
    assert "<b>y</b>" not in fila


def test_pendiente_sin_montos_no_precarga(client_as, nuevo, staff, token):
    esc = nuevo(last_name=token)
    html = client_as(staff()).get(f"{LIB}/body", params={"status": "pending", "q": token}).text
    fila = _fila(html, f'id="lib-{esc.clearance.id}"')
    assert "Montos previos" not in fila
    assert 'name="debt_amount" required' in fila
    assert 'required\n                     value=' not in fila


def test_motivo_con_html_se_escapa_en_fila_y_textarea(client_as, db_session, staff, nuevo,
                                                      token):
    yo = staff()
    esc = nuevo(last_name=token)
    peligro = '<script>alert(1)</script> "comillas" \'simples\''
    _observar_svc(db_session, esc.clearance.id, yo.id, reason=peligro)

    html = client_as(yo).get(f"{LIB}/body", params={"status": "observed", "q": token}).text
    fila = _fila(html, f'id="lib-{esc.clearance.id}"')

    assert "<script>alert(1)</script>" not in fila
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in fila
    ta = re.search(r"<textarea[^>]*>(.*?)</textarea>", fila, re.S)
    assert ta and "<script>" not in ta.group(1)
    assert "&lt;script&gt;" in ta.group(1)
    assert "</textarea><" not in ta.group(1)


def test_observada_de_proceso_revocado_no_se_lista_ni_se_cuenta(client_as, db_session, staff,
                                                                nuevo, token):
    yo = staff()
    vivo, muerto = nuevo(last_name=token), nuevo(last_name=token)
    _observar_svc(db_session, vivo.clearance.id, yo.id)
    _observar_svc(db_session, muerto.clearance.id, yo.id)
    muerto.process.status = "cancelled"
    db_session.flush()

    html = client_as(yo).get(f"{LIB}/body", params={"status": "observed", "q": token}).text

    assert f'id="lib-{vivo.clearance.id}"' in html
    assert f'id="lib-{muerto.clearance.id}"' not in html
    assert ">1</span>" in _tab_span(html, "tt-lib-tab-observed")
