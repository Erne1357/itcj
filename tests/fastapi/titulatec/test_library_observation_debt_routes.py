"""Observación CON ADEUDO en las bandejas: rutas y HTML de Biblioteca y Caja.

Spec `docs/superpowers/specs/2026-10-07-titulatec-liberados-biblioteca-helpdesk-
design.md` §2 (D3/D4). La máquina de estados la cubre
`test_library_observation_debt.py`; aquí la RUTA (`/observar` con `kind` y
`debt_amount`, 400 legibles, `/rehabilitar` en sus ramas) y lo que pinta cada
bandeja: el formulario «Observar con adeudo» (atajo «Entregar libro», adeudo
precargado), la fila «Con observaciones» (tipo, monto, pago, qué hará
«Activar»), «Por cobrar» de Caja con la observación con adeudo (y sin la
normal), el cobro retenido con su aviso, la búsqueda «Pagado — retenido por
Biblioteca» con «Revertir pago…» y el corte del día.

DATOS. La BD de dev es COMPARTIDA: las listas y contadores se aíslan con un
token único en el apellido (`q`), nunca por absolutos.
"""
from __future__ import annotations

import html as html_lib
import re
import uuid
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

# Escenarios de las vistas (registrarlos aquí sin duplicar el armado): `esc`
# del gate (egresado en una convocatoria con candado + encargado) y `caso` de
# las vistas de SE (con su cita atendida para el panel de atender).
from tests.fastapi.titulatec.test_clearance_gate import esc  # noqa: F401
from tests.fastapi.titulatec.test_se_library_views import caso  # noqa: F401

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
MOTIVO = "Entregar libro: «Cálculo» de Stewart"


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
def biblioteca(make_user, make_role, grant_user_role):
    user = make_user(first_name="BIBLIOTECA", last_name="ADEUDO")
    grant_user_role(user, make_role("tt_test_library_debt", LIBRARY_PERMS))
    return user


@pytest.fixture()
def cajera(make_user, make_role, grant_user_role):
    user = make_user(first_name="CAJA", last_name="ADEUDO")
    grant_user_role(user, make_role("tt_test_cashier_debt", CASHIER_PERMS))
    return user


@pytest.fixture()
def token():
    return "DBR" + uuid.uuid4().hex[:10].upper()


@pytest.fixture()
def nuevo(db_session, make_student, make_process, make_cohort, make_library_clearance):
    """Egresado + proceso + su fila de no adeudo en `status` (convocatoria con
    donación $800 y el requisito automático de no adeudo)."""
    from itcj2.apps.titulatec.models import CotejoRequirement

    def _build(*, status="pending", last_name="FICTICIO", donation=DONACION, **cols):
        cohort = make_cohort(book_donation_amount=donation)
        db_session.add(CotejoRequirement(
            cohort_id=cohort.id, label="Constancia de no adeudo de biblioteca", icon="book",
            code="library_clearance", auto_source="library_clearance",
            is_required=True, is_active=True, order_index=0))
        db_session.flush()
        student = make_student(last_name=last_name)
        process = make_process(student, cohort=cohort, current_phase=2,
                               library_clearance=None)
        if status in ("awaiting_payment", "observed") and "total_amount" not in cols:
            cols = {"debt_amount": ADEUDO, "donation_amount": DONACION,
                    "total_amount": TOTAL, **cols}
        clearance = make_library_clearance(process, status=status, **cols)
        return SimpleNamespace(process=process, student=student, clearance=clearance)

    return _build


def _observar(db, esc, actor, *, kind="with_debt", debt=ADEUDO, reason=MOTIVO):
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    return LibraryClearanceService.observe(db, esc.clearance.id, reason=reason,
                                           actor_id=actor.id, kind=kind, debt_amount=debt)


def _pagar(db, esc, cajera, **kw):
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    return LibraryClearanceService.register_payment(db, esc.clearance.id, cajera.id, **kw)


def _fila(html, marca):
    """La fila y, si la trae, su `<tr id="…-panel">` de dictamen."""
    assert marca in html, "falta la fila sembrada"
    resto = html.split(marca, 1)[1]
    fila, resto = resto.split("</tr>", 1)
    m = re.match(r'\s*<tr id="%s-panel"' % re.escape(marca[4:-1]), resto)
    if m:
        fila += resto.split("</tr>", 1)[0]
    return fila


def _tr(html, tr_id):
    m = re.search(r'<tr id="%s"[^>]*>.*?</tr>' % re.escape(tr_id), html, re.S)
    assert m, f"falta <tr id={tr_id}>"
    return m.group(0)


def _tab_span(html, tab_id):
    m = re.search(r'id="%s".*?</button>' % re.escape(tab_id), html, re.S)
    return m.group(0) if m else ""


def _visible(fragmento):
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", fragmento)).split())


def _form(fragmento, i, key):
    m = re.search(r'<form id="lib-%d-form-%s"[^>]*>.*?</form>' % (i, key), fragmento, re.S)
    assert m, f"falta el formulario {key}"
    return m.group(0)


def _opciones(panel, i):
    return [k for k, _ in re.findall(
        r'<label class="tt-vis-opt" for="lib-%d-opt-(\w+)">(.*?)</label>' % i, panel, re.S)]


# ---------------------------------------------------------------------------
# Biblioteca: ruta /observar con adeudo
# ---------------------------------------------------------------------------
def test_observar_con_adeudo_por_la_ruta(client_as, db_session, biblioteca, nuevo, token):
    esc = nuevo(last_name=token)

    resp = client_as(biblioteca).post(
        f"{LIB}/{esc.clearance.id}/observar",
        data={"status": "pending", "q": token, "page": "1", "kind": "with_debt",
              "reason": f"  {MOTIVO} ", "debt_amount": "$300"})

    assert resp.status_code == 200, resp.text[:500]
    assert ">1</span>" in _tab_span(resp.text, "tt-lib-tab-observed")
    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "observed"
    assert esc.clearance.observation_kind == "with_debt"
    assert esc.clearance.total_amount == TOTAL
    assert esc.clearance.observation_reason == MOTIVO


@pytest.mark.parametrize("data, patron", [
    ({"kind": "with_debt", "debt_amount": ""}, "monto"),
    ({"kind": "with_debt", "debt_amount": "abc"}, "Monto no válido"),
    ({"kind": "otra"}, "observación"),
])
def test_observar_con_adeudo_errores_400(client_as, db_session, biblioteca, nuevo, token,
                                         data, patron):
    esc = nuevo(last_name=token)

    resp = client_as(biblioteca).post(
        f"{LIB}/{esc.clearance.id}/observar",
        data={"status": "pending", "q": token, "page": "1", "reason": MOTIVO, **data})

    assert resp.status_code == 400, resp.text[:300]
    assert patron in unquote(resp.headers["X-Tt-Error"])
    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "pending"


def test_total_cero_responde_usa_la_observacion_normal(client_as, db_session, biblioteca,
                                                       nuevo, token):
    esc = nuevo(last_name=token, donation=Decimal("0.00"))

    resp = client_as(biblioteca).post(
        f"{LIB}/{esc.clearance.id}/observar",
        data={"status": "pending", "q": token, "page": "1", "kind": "with_debt",
              "reason": MOTIVO, "debt_amount": "0"})

    assert resp.status_code == 400
    assert "observación normal" in unquote(resp.headers["X-Tt-Error"])


def test_observar_sin_kind_sigue_siendo_la_normal(client_as, db_session, biblioteca, nuevo,
                                                  token):
    esc = nuevo(status="awaiting_payment", last_name=token)

    resp = client_as(biblioteca).post(
        f"{LIB}/{esc.clearance.id}/observar",
        data={"status": "awaiting_payment", "q": token, "page": "1", "reason": MOTIVO})

    assert resp.status_code == 200, resp.text[:300]
    db_session.refresh(esc.clearance)
    assert esc.clearance.observation_kind == "blocking"


# ---------------------------------------------------------------------------
# Biblioteca: formularios del panel
# ---------------------------------------------------------------------------
def test_por_revisar_ofrece_observar_con_adeudo_con_atajo(client_as, biblioteca, nuevo, token):
    esc = nuevo(last_name=token)
    i = esc.clearance.id
    html = client_as(biblioteca).get(f"{LIB}/body", params={"status": "pending",
                                                            "q": token}).text
    panel = _tr(html, f"lib-{i}-panel")

    assert _opciones(panel, i) == ["debt", "prior", "observe", "obsdebt"]
    f = _form(panel, i, "obsdebt")
    abre = re.match(r"<form[^>]*>", f).group(0)
    assert f'hx-post="/titulatec/admin/biblioteca/{i}/observar"' in abre
    assert 'data-tt-confirm-ok="Observar"' in abre
    assert 'hx-confirm="Observar con adeudo|' in abre
    assert 'name="kind" value="with_debt"' in f
    ta = re.search(r'<textarea[^>]*name="reason"[^>]*required[^>]*maxlength="1000"[^>]*>(.*?)'
                   r"</textarea>", f, re.S)
    assert ta and ta.group(1) == "Entregar libro", "atajo del motivo, editable"
    assert re.search(r'name="debt_amount"[^>]*required', f)
    assert 'name="status" value="pending"' in f
    assert _visible(re.search(r'<button type="submit"[^>]*>.*?</button>', f, re.S)
                    .group(0)) == "Registrar observación con adeudo"


def test_en_caja_precarga_el_adeudo_vigente(client_as, biblioteca, nuevo, token):
    esc = nuevo(status="awaiting_payment", last_name=token)
    i = esc.clearance.id
    html = client_as(biblioteca).get(f"{LIB}/body", params={"status": "awaiting_payment",
                                                            "q": token}).text
    panel = _tr(html, f"lib-{i}-panel")

    assert _opciones(panel, i) == ["fix", "observe", "obsdebt"]
    f = _form(panel, i, "obsdebt")
    assert re.search(r'name="debt_amount"[^>]*required\s+value="300.00"', f)


def test_fila_observada_con_adeudo_sin_pago(client_as, db_session, biblioteca, nuevo, token):
    esc = nuevo(last_name=token)
    _observar(db_session, esc, biblioteca)
    i = esc.clearance.id
    html = client_as(biblioteca).get(f"{LIB}/body", params={"status": "observed",
                                                            "q": token}).text
    fila = _fila(html, f'id="lib-{i}"')
    texto = _visible(fila)

    assert "Con adeudo" in texto and "$1,100.00" in texto and "Sin pagar" in texto
    assert "Al activar: pasa a Caja a pagar $1,100.00." in texto
    conf = html_lib.unescape(re.search(
        r'hx-post="/titulatec/admin/biblioteca/%d/rehabilitar"[^>]*hx-confirm="([^"]*)"' % i,
        fila).group(1))
    assert conf.startswith("Activar|") and "pasa a Caja" in conf
    panel = _tr(html, f"lib-{i}-panel")
    assert _opciones(panel, i) == ["obsdebt", "toblock"]
    f = _form(panel, i, "obsdebt")
    ta = re.search(r"<textarea[^>]*>(.*?)</textarea>", f, re.S)
    assert html_lib.unescape(ta.group(1)) == MOTIVO
    assert re.search(r'name="debt_amount"[^>]*required\s+value="300.00"', f)
    t = _form(panel, i, "toblock")
    assert 'name="kind" value="blocking"' in t


def test_fila_observada_con_pago_retenido(client_as, db_session, biblioteca, cajera, nuevo,
                                          token):
    esc = nuevo(last_name=token)
    _observar(db_session, esc, biblioteca)
    _pagar(db_session, esc, cajera, receipt_number="R-44")
    i = esc.clearance.id
    html = client_as(biblioteca).get(f"{LIB}/body", params={"status": "observed",
                                                            "q": token}).text
    fila = _fila(html, f'id="lib-{i}"')
    texto = _visible(fila)

    assert "Con adeudo · pagado" in texto and "Recibo R-44" in texto
    assert "Al activar: se libera su Constancia de no adeudo (folio)." in texto
    panel = _tr(html, f"lib-{i}-panel")
    assert "tt-lib-pick" not in panel, "con pago retenido, solo el motivo"
    f = _form(panel, i, "update")
    assert 'name="kind" value="with_debt"' in f and 'name="debt_amount"' not in f
    assert "Caja debe revertir el pago" in _visible(panel)


def test_fila_observada_normal_ofrece_cambiar_a_con_adeudo(client_as, db_session, biblioteca,
                                                           nuevo, token):
    esc = nuevo(last_name=token)
    _observar(db_session, esc, biblioteca, kind="blocking", debt=None)
    i = esc.clearance.id
    html = client_as(biblioteca).get(f"{LIB}/body", params={"status": "observed",
                                                            "q": token}).text
    fila = _fila(html, f'id="lib-{i}"')

    assert "Al activar: vuelve a Por revisar." in _visible(fila)
    panel = _tr(html, f"lib-{i}-panel")
    assert _opciones(panel, i) == ["update", "obsdebt"]


# ---------------------------------------------------------------------------
# Biblioteca: Activar en sus tres ramas, por la ruta
# ---------------------------------------------------------------------------
def test_activar_con_pago_retenido_libera_con_folio(client_as, db_session, biblioteca, cajera,
                                                    nuevo, token):
    esc = nuevo(last_name=token)
    _observar(db_session, esc, biblioteca)
    _pagar(db_session, esc, cajera)

    resp = client_as(biblioteca).post(f"{LIB}/{esc.clearance.id}/rehabilitar",
                                      data={"status": "observed", "q": token, "page": "1"})

    assert resp.status_code == 200, resp.text[:300]
    assert ">1</span>" in _tab_span(resp.text, "tt-lib-tab-cleared")
    db_session.refresh(esc.clearance)
    assert (esc.clearance.status, esc.clearance.cleared_via) == ("cleared", "payment")


def test_activar_con_adeudo_sin_pago_pasa_a_en_caja(client_as, db_session, biblioteca, nuevo,
                                                    token):
    esc = nuevo(last_name=token)
    _observar(db_session, esc, biblioteca)

    resp = client_as(biblioteca).post(f"{LIB}/{esc.clearance.id}/rehabilitar",
                                      data={"status": "observed", "q": token, "page": "1"})

    assert resp.status_code == 200, resp.text[:300]
    assert ">1</span>" in _tab_span(resp.text, "tt-lib-tab-awaiting_payment")
    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "awaiting_payment"


# ---------------------------------------------------------------------------
# Caja: «Por cobrar», cobro retenido, búsqueda y reversa
# ---------------------------------------------------------------------------
def test_por_cobrar_lista_con_adeudo_y_no_la_normal(client_as, db_session, biblioteca, cajera,
                                                    nuevo, token):
    c = client_as(cajera)
    n_antes = int(re.search(r">(\d+)</span>", _tab_span(
        c.get(f"{CAJA}/body").text, "tt-cashier-tab-por_cobrar")).group(1))
    con_adeudo = nuevo(last_name=token)
    normal = nuevo(status="awaiting_payment", last_name=token)
    _observar(db_session, con_adeudo, biblioteca)
    _observar(db_session, normal, biblioteca, kind="blocking", debt=None)

    html = c.get(f"{CAJA}/body").text

    n = int(re.search(r">(\d+)</span>", _tab_span(html, "tt-cashier-tab-por_cobrar")).group(1))
    assert n == n_antes + 1, "la con adeudo entra; la normal sale"
    assert f'id="caja-{normal.clearance.id}"' not in html
    fila = _fila(html, f'id="caja-{con_adeudo.clearance.id}"')
    texto = _visible(fila)
    assert "Por cobrar $1,100.00" in texto
    assert "Con observación de Biblioteca" in texto and "Stewart" in texto
    assert ("el pago no libera la Constancia de no adeudo hasta que Biblioteca la active"
            in texto)
    form = re.search(r"<form[^>]*/pagar\"[^>]*>.*?</form>", fila, re.S).group(0)
    assert 'name="expected_status" value="observed"' in form
    assert 'name="expected_total" value="1100.00"' in form
    conf = html_lib.unescape(re.search(r'hx-confirm="([^"]*)"', form).group(1))
    assert "no libera" in conf


def test_cobrar_con_adeudo_avisa_que_queda_retenido(client_as, db_session, biblioteca, cajera,
                                                    nuevo, token):
    esc = nuevo(last_name=token)
    _observar(db_session, esc, biblioteca)

    resp = client_as(cajera).post(
        f"{CAJA}/{esc.clearance.id}/pagar",
        data={"tab": "por_cobrar", "q": "", "dia": "", "page": "1", "recibo": "R-1",
              "expected_status": "observed", "expected_total": "1100.00"})

    assert resp.status_code == 200, resp.text[:300]
    aviso = unquote(resp.headers.get("X-Tt-Notice") or "")
    assert "Pago registrado" in aviso and "Biblioteca la active" in aviso
    assert resp.headers.get("X-Tt-Notice-Kind") == "warning"
    assert f'id="caja-{esc.clearance.id}"' not in resp.text, "ya no está por cobrar"
    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "observed" and esc.clearance.paid_at is not None
    assert esc.clearance.receipt_number == "R-1"


def test_pantalla_vieja_de_por_cobrar_re_pinta_sin_cobrar(client_as, db_session, biblioteca,
                                                          cajera, nuevo, token):
    """La cajera tenía un «Por cobrar» normal; Biblioteca lo observó con
    adeudo mientras tanto: re-pinta con la observación a la vista, no cobra."""
    esc = nuevo(status="awaiting_payment", last_name=token)
    _observar(db_session, esc, biblioteca)

    resp = client_as(cajera).post(
        f"{CAJA}/{esc.clearance.id}/pagar",
        data={"tab": "por_cobrar", "q": token, "dia": "", "page": "1",
              "expected_status": "awaiting_payment", "expected_total": "1100.00"})

    assert resp.status_code == 200, resp.text[:300]
    assert "Con observaciones" in unquote(resp.headers.get("X-Tt-Notice") or "")
    assert resp.headers.get("X-Tt-Notice-Kind") == "warning"
    fila = _fila(resp.text, f'id="caja-{esc.clearance.id}"')
    assert "Con observación de Biblioteca" in _visible(fila)
    db_session.refresh(esc.clearance)
    assert esc.clearance.paid_at is None


def test_la_normal_sigue_sin_cobrarse_aunque_mande_observed(client_as, db_session, biblioteca,
                                                            cajera, nuevo, token):
    esc = nuevo(status="awaiting_payment", last_name=token)
    _observar(db_session, esc, biblioteca, kind="blocking", debt=None)

    resp = client_as(cajera).post(
        f"{CAJA}/{esc.clearance.id}/pagar",
        data={"tab": "por_cobrar", "q": token, "dia": "", "page": "1",
              "expected_status": "observed", "expected_total": "1100.00"})

    assert resp.status_code == 200
    assert "No se registró ningún pago" in unquote(resp.headers.get("X-Tt-Notice") or "")
    db_session.refresh(esc.clearance)
    assert esc.clearance.paid_at is None


def test_busqueda_pinta_pagado_retenido_y_deja_revertir(client_as, db_session, biblioteca,
                                                        cajera, nuevo, token):
    esc = nuevo(last_name=token)
    _observar(db_session, esc, biblioteca)
    _pagar(db_session, esc, cajera, receipt_number="R-7")
    c = client_as(cajera)

    html = c.get(f"{CAJA}/body", params={"q": token}).text
    fila = _fila(html, f'id="caja-{esc.clearance.id}"')
    texto = _visible(fila)
    assert "Pagado — retenido por Biblioteca" in texto
    assert "Recibo R-7" in texto
    assert f'hx-post="/titulatec/admin/caja/{esc.clearance.id}/revertir"' in fila
    assert "/pagar" not in fila

    resp = c.post(f"{CAJA}/{esc.clearance.id}/revertir",
                  data={"tab": "por_cobrar", "q": token, "dia": "", "page": "1",
                        "reason": "Se cobró a otra persona"})

    assert resp.status_code == 200, resp.text[:300]
    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "observed" and esc.clearance.paid_at is None
    fila = _fila(resp.text, f'id="caja-{esc.clearance.id}"')
    assert "/pagar" in fila, "vuelve a estar por cobrar"


def test_corte_del_dia_marca_el_cobro_retenido_y_lo_revierte(client_as, db_session,
                                                             biblioteca, cajera, nuevo, token):
    from datetime import datetime

    from itcj2.apps.titulatec.models import ProcessEvent

    esc = nuevo(last_name=token)
    _observar(db_session, esc, biblioteca)
    _pagar(db_session, esc, cajera)
    evento = (db_session.query(ProcessEvent)
              .filter_by(process_id=esc.process.id, event_type="library_payment_registered")
              .one())
    evento.created_at = datetime(2091, 4, 2, 10, 0)
    db_session.flush()

    html = client_as(cajera).get(f"{CAJA}/body", params={"tab": "pagados",
                                                         "dia": "2091-04-02"}).text
    fila = _tr(html, f"caja-mov-{evento.id}")

    assert "Con observación de Biblioteca" in _visible(fila)
    assert "$1,100.00" in _visible(fila)
    assert f'hx-post="/titulatec/admin/caja/{esc.clearance.id}/revertir"' in fila


# ---------------------------------------------------------------------------
# Vistas que muestran el estado: tablero y «Mi cita» del egresado, atender
# cotejo y expediente de SE (spec 2026-10-07 §2: tipo, monto y si ya pagó)
# ---------------------------------------------------------------------------

CON_ADEUDO = {"observation_reason": MOTIVO, "observation_kind": "with_debt",
              "debt_amount": ADEUDO, "donation_amount": DONACION, "total_amount": TOTAL}


def _texto(html):
    import lxml.html
    return " ".join(lxml.html.fromstring(html).text_content().split())


def test_tablero_del_egresado_con_adeudo_sin_pagar(client_as, esc):
    import lxml.html

    proc = esc["nuevo"](biblioteca="observed", fase=1, **CON_ADEUDO)

    resp = client_as(proc.student).get("/titulatec/student/dashboard")
    assert resp.status_code == 200, resp.text[:400]
    (fase,) = lxml.html.fromstring(resp.text).xpath('//*[@data-tt-phase="2"]')
    texto = " ".join(fase.text_content().split())

    assert "Con observaciones" in texto
    assert "observación con adeudo" in texto and "$1,100.00" in texto
    assert "en la misma visita" in texto
    assert "se libera cuando Biblioteca registre la entrega" in texto
    assert MOTIVO in texto


def test_tablero_del_egresado_con_pago_retenido(client_as, esc):
    import lxml.html
    from datetime import datetime

    proc = esc["nuevo"](biblioteca="observed", fase=1, paid_at=datetime(2026, 10, 7, 9, 0),
                        **CON_ADEUDO)

    resp = client_as(proc.student).get("/titulatec/student/dashboard")
    (fase,) = lxml.html.fromstring(resp.text).xpath('//*[@data-tt-phase="2"]')
    texto = " ".join(fase.text_content().split())

    assert "Ya pagaste $1,100.00 en Caja" in texto
    assert "se libera cuando Biblioteca registre la entrega" in texto


def test_mi_cita_dice_el_adeudo(client_as, esc):
    proc = esc["nuevo"](biblioteca="observed", **CON_ADEUDO)

    resp = client_as(proc.student).get("/titulatec/student/cita")

    assert resp.status_code == 200, resp.text[:400]
    texto = _texto(resp.text)
    assert "con adeudo de $1,100.00" in texto and "misma visita" in texto


def test_expediente_de_se_dice_tipo_monto_y_pago(client_as, db_session, esc):
    from datetime import datetime

    proc = esc["nuevo"](biblioteca="observed", paid_at=datetime(2026, 10, 7, 9, 0),
                        **CON_ADEUDO)

    resp = client_as(esc["off"]).get(f"/titulatec/admin/processes/{proc.id}")

    assert resp.status_code == 200, resp.text[:400]
    texto = _texto(resp.text)
    assert MOTIVO in texto
    assert "con adeudo de $1,100.00: pagado en Caja el 07/10/2026" in texto


def test_atender_cotejo_dice_tipo_monto_y_pago(client_as, db_session, caso):
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )

    fila = LibraryClearanceService.get_for_process(db_session, caso["proc"].id)
    for col, valor in {"status": "observed", **CON_ADEUDO}.items():
        setattr(fila, col, valor)
    db_session.flush()

    resp = client_as(caso["officer"]).get(
        f"/titulatec/admin/appointments/body?v=atender&selected={caso['proc'].id}")

    assert resp.status_code == 200, resp.text[:300]
    texto = _texto(resp.text)
    assert "Con observaciones" in texto and MOTIVO in texto
    assert "con adeudo de $1,100.00: sin pagar" in texto
