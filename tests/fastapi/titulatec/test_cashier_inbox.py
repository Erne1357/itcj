"""Bandeja de Caja (`pages/cashier_admin.py`), cobro del no adeudo de biblioteca.

Caja (rol `titulatec_cashier`, puesto «Caja» en Recursos Financieros) busca a un
egresado por control o nombre (en CUALQUIER estado), ve el desglose adeudo +
donación voluntaria de libro = total, registra el pago (recibo opcional) y
puede revertir un cobro equivocado mientras la fase 2 no esté aprobada. Sin
citas en Caja. «Pagados» es un corte simple del día con su total. Estas
pruebas cubren la RUTA (permisos, pestañas, búsqueda, concurrencia, códigos de
error); la máquina de estados en sí ya la cubre `test_library_clearance_service.py`
(Tarea 4), incluida la Ruling R9 (predicado de admitidos en «Por cobrar» y el
`expected_total` sin tope `AMOUNT_MAX`).

Spec `docs/superpowers/specs/2026-10-01-titulatec-biblioteca-caja-design.md`
§4.8 (bandeja), §4.2 (estados/errores de pago y reversa), §4.6 (permisos/nav),
D4/D16, §5 invariante 6 (sin `{process_id}` en estas rutas).

`make_cashier_staff` es un actor sintético con rol DIRECTO (`grant_user_role`),
no por puesto: el reparto puesto -> rol de producción ya lo verifica
`test_permissions_contract.py` contra el DML de la Tarea 2. Aquí solo importa
el CONJUNTO de permisos que el gate exige.

Cada `make_process(..., library_clearance="pending")` usa un `cohort` propio
con `book_donation_amount` YA capturado: el default de `make_cohort` es `None`
("sin configurar", D19). Los adeudos de las pruebas son SIEMPRE > 0 (o la
donación lo es) para no caer en D18 (total $0 libera directo en Biblioteca,
sin pasar por Caja) cuando el objetivo de la prueba es ejercitar «Por cobrar».
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import unquote

import pytest

URL = "/titulatec/admin/caja"

CASHIER_PERMS = (
    "titulatec.library_payment.page.list",
    "titulatec.library_payment.api.register",
    "titulatec.library_payment.api.revert",
)

SVC_DB_NOW = "itcj2.apps.titulatec.services.library_clearance_service.db_now"


@pytest.fixture()
def make_cashier_staff(make_user, make_role, grant_user_role):
    """Actor sintético de Caja: rol DIRECTO con los permisos de la bandeja."""
    def _make(perm_codes=CASHIER_PERMS, first_name="CAJA", last_name="FICTICIA"):
        user = make_user(first_name=first_name, last_name=last_name)
        role = make_role("tt_test_cashier", perm_codes)
        grant_user_role(user, role)
        return user

    return _make


def _tab_span(html, tab_id):
    """Recorta el botón de una pestaña completo, para revisar SU contador
    (y no un dígito suelto en cualquier otra parte de la página)."""
    m = re.search(r'id="%s".*?</button>' % re.escape(tab_id), html, re.S)
    return m.group(0) if m else ""


def _row(html, row_id):
    """Recorta la fila `<tr id="...">...</tr>` completa (búsqueda/«Por
    cobrar» o «Corte del día»), para revisar SU contenido -nunca el texto de
    otra fila de la misma tabla."""
    m = re.search(r'<tr id="%s">.*?</tr>' % re.escape(row_id), html, re.S)
    return m.group(0) if m else ""


def _clearance(db_session, process):
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    return LibraryClearanceService.get_for_process(db_session, process.id)


# ---------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------
def test_una_jefatura_de_escolares_sin_permiso_de_caja_no_entra(client_as, make_head):
    """`require_page_app` sin el permiso de esta página -> 403 (la jefa SÍ
    tiene acceso a la app, solo le falta `library_payment.page.list`)."""
    resp = client_as(make_head()).get(URL)

    assert resp.status_code == 403, resp.text[:300]


def test_un_graduate_no_entra(client_as, make_student):
    resp = client_as(make_student()).get(URL)

    assert resp.status_code == 403, resp.text[:300]


def test_menu_solo_muestra_caja_con_el_permiso(client_as, make_head, make_cashier_staff):
    sin_permiso = client_as(make_head()).get("/titulatec/admin/documents")
    assert sin_permiso.status_code == 200, sin_permiso.text[:500]
    assert "/titulatec/admin/caja" not in sin_permiso.text

    con_permiso = client_as(make_cashier_staff()).get(URL)
    assert con_permiso.status_code == 200, con_permiso.text[:500]
    assert "/titulatec/admin/caja" in con_permiso.text
    assert "Caja" in con_permiso.text


# ---------------------------------------------------------------------------
# Bandeja: pestaña «Por cobrar», contador, filas, mismos query params
# ---------------------------------------------------------------------------
def test_ve_pestana_por_cobrar_con_contador_y_filas(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
):
    staff = make_cashier_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    student = make_student(control_number="99700091", first_name="EGRESADO", last_name="ENCAJA")
    proc = make_process(student, cohort=cohort, current_phase=1, library_clearance="pending")
    clearance = _clearance(db_session, proc)
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("100"))
    db_session.refresh(clearance)
    assert clearance.status == "awaiting_payment"

    resp = client_as(staff).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "Por cobrar" in resp.text
    assert "Corte del día" in resp.text
    counts = LibraryClearanceService.counts_by_status(db_session)
    assert counts["awaiting_payment"] >= 1
    assert f'>{counts["awaiting_payment"]}<' in _tab_span(resp.text, "tt-cashier-tab-por_cobrar")
    assert f'id="caja-{clearance.id}"' in resp.text
    assert student.control_number in resp.text


def test_pagina_y_body_aceptan_los_mismos_query_params(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
):
    staff = make_cashier_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99700081"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("300"))
    db_session.refresh(clearance)
    assert clearance.status == "awaiting_payment"
    c = client_as(staff)

    pagina = c.get(f"{URL}?tab=por_cobrar")
    cuerpo = c.get(f"{URL}/body?tab=por_cobrar")

    assert pagina.status_code == 200 and cuerpo.status_code == 200
    assert 'id="tt-cashier-body"' in cuerpo.text
    assert "99700081" in pagina.text
    assert "99700081" in cuerpo.text


# ---------------------------------------------------------------------------
# Buscador (D4): en cualquier estado, por control o por nombre
# ---------------------------------------------------------------------------
def test_busqueda_por_control_en_cualquier_estado(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
):
    staff = make_cashier_staff()
    cohort = make_cohort(book_donation_amount=Decimal("150.00"))
    p_pend = make_process(make_student(control_number="99700061", first_name="ANA",
                                       last_name="ENBIBLIOCAJA"),
                          cohort=cohort, current_phase=1, library_clearance="pending")
    p_caja = make_process(make_student(control_number="99700062", first_name="BETO",
                                       last_name="PORCOBRARCAJA"),
                          cohort=cohort, current_phase=1, library_clearance="pending")
    c_caja = _clearance(db_session, p_caja)
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    LibraryClearanceService.register(db_session, c_caja.id, staff.id, debt_amount=Decimal("100"))

    resp_pend = client_as(staff).get(f"{URL}/body?q=99700061")
    resp_caja = client_as(staff).get(f"{URL}/body?q=99700062")

    assert resp_pend.status_code == 200, resp_pend.text[:500]
    assert "99700061" in resp_pend.text
    assert resp_caja.status_code == 200, resp_caja.text[:500]
    assert "99700062" in resp_caja.text
    assert "$250.00" in resp_caja.text          # 100 adeudo + 150 donación


def test_busqueda_por_nombre(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
):
    staff = make_cashier_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    make_process(make_student(control_number="99700071", first_name="ZOE",
                              last_name="UNICANOMBRECAJA"),
                cohort=cohort, current_phase=1, library_clearance="pending")

    resp = client_as(staff).get(f"{URL}/body?q=UNICANOMBRECAJA")

    assert resp.status_code == 200, resp.text[:500]
    assert "99700071" in resp.text


# ---------------------------------------------------------------------------
# Registrar pago
# ---------------------------------------------------------------------------
def test_registrar_pago_libera_y_emite_constancia(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
):
    staff = make_cashier_staff()
    cohort = make_cohort(book_donation_amount=Decimal("200.00"))
    proc = make_process(make_student(control_number="99700011"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("800"))
    db_session.refresh(clearance)
    assert clearance.total_amount == Decimal("1000.00")

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/pagar",
        data={"tab": "por_cobrar", "q": "", "dia": "", "page": "1",
              "expected_total": "1000.00", "recibo": "R-900"})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(clearance)
    assert clearance.status == "cleared"
    assert clearance.cleared_via == "payment"
    assert clearance.receipt_number == "R-900"

    buscar = client_as(staff).get(f"{URL}/body?q=99700011")
    assert "BIB-" in buscar.text


def test_recibo_es_opcional(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
):
    staff = make_cashier_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99700012"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("300"))
    db_session.refresh(clearance)

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/pagar",
        data={"tab": "por_cobrar", "q": "", "dia": "", "page": "1",
              "expected_total": "300.00"})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(clearance)
    assert clearance.status == "cleared"
    assert clearance.receipt_number is None


def test_doble_cobro_responde_400(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
):
    staff = make_cashier_staff()
    otra = make_cashier_staff(first_name="OTRA", last_name="CAJERA")
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99700021"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("500"))
    db_session.refresh(clearance)
    LibraryClearanceService.register_payment(db_session, clearance.id, otra.id,
                                             receipt_number="R-PRIMERO")
    db_session.refresh(clearance)

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/pagar",
        data={"tab": "por_cobrar", "q": "", "dia": "", "page": "1",
              "expected_total": "500.00"})

    assert resp.status_code == 400, resp.text[:300]
    assert resp.headers.get("X-Tt-Error")
    db_session.refresh(clearance)
    assert clearance.receipt_number == "R-PRIMERO", "no se debe pisar el cobro de la otra cajera"


def test_monto_corregido_mientras_tanto_re_pinta_y_no_cobra_lo_que_la_cajera_no_vio(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
):
    """Ruling R8 + R24 (M1): el total oculto que la cajera VIO ya no coincide
    (Biblioteca lo corrigió primero) -> nunca se cobra un monto que no se
    mostró, y la ruta responde 200 con la bandeja RE-PINTADA con el monto
    vigente y el motivo en `X-Tt-Notice` (warning) -- con un 400 htmx no hacía
    swap y la fila seguía ofreciendo el monto viejo."""
    staff = make_cashier_staff()
    cohort = make_cohort(book_donation_amount=Decimal("100.00"))
    proc = make_process(make_student(control_number="99700031"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("400"))
    db_session.refresh(clearance)
    assert clearance.total_amount == Decimal("500.00")

    # Biblioteca corrige mientras la cajera tenía la pantalla abierta.
    LibraryClearanceService.register(
        db_session, clearance.id, staff.id, debt_amount=Decimal("900"),
        expected_status="awaiting_payment", expected_total=Decimal("500.00"))
    db_session.refresh(clearance)
    assert clearance.total_amount == Decimal("1000.00")

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/pagar",
        data={"tab": "por_cobrar", "q": "99700031", "dia": "", "page": "1",
              "expected_total": "500.00"})

    assert resp.status_code == 200, resp.text[:300]
    assert not resp.headers.get("X-Tt-Error")
    aviso = unquote(resp.headers.get("X-Tt-Notice") or "")
    assert "El monto cambió mientras lo revisabas: ahora es $1,000.00" in aviso
    assert resp.headers.get("X-Tt-Notice-Kind") == "warning"
    assert 'id="tt-cashier-body"' in resp.text
    assert f'id="caja-{clearance.id}"' in resp.text and "$1,000.00" in resp.text
    db_session.refresh(clearance)
    assert clearance.status == "awaiting_payment"
    assert clearance.total_amount == Decimal("1000.00"), "el monto vigente no se debe pisar"


def test_pagar_despues_de_que_biblioteca_corrigio_a_cero_re_pinta(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
):
    """Ruling R30 #3 (re-revisión de la ola final, M1 COMPLETO): la cajera
    tenía «Pagar» abierto con el total viejo cuando Biblioteca corrigió a $0
    (adeudo y donación congelada en $0) -la fila se liberó DIRECTO
    (`cleared/no_charge`), FUERA de `awaiting_payment`-. Antes del arreglo
    `register_payment` revisaba los tres `if clearance.status == …` ANTES que
    `_check_expected`, así que esto caía en el 400 plano de «ya está
    liberado; no hay nada que cobrar» sin re-pintar; ahora `_check_expected`
    ve el `expected_total` desfasado PRIMERO y re-pinta con el aviso -- nunca
    se cobra sobre una fila que ya no debe nada."""
    staff = make_cashier_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99700092"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("500"))
    db_session.refresh(clearance)
    assert clearance.total_amount == Decimal("500.00")

    # Biblioteca corrige a $0 mientras la cajera tenía «Pagar» abierto.
    LibraryClearanceService.register(
        db_session, clearance.id, staff.id, debt_amount=Decimal("0"),
        expected_status="awaiting_payment", expected_total=Decimal("500.00"))
    db_session.refresh(clearance)
    assert clearance.status == "cleared" and clearance.cleared_via == "no_charge"

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/pagar",
        data={"tab": "por_cobrar", "q": "99700092", "dia": "", "page": "1",
              "expected_total": "500.00"})

    assert resp.status_code == 200, resp.text[:300]
    assert not resp.headers.get("X-Tt-Error")
    aviso = unquote(resp.headers.get("X-Tt-Notice") or "")
    assert "El monto cambió mientras lo revisabas: ahora es $0.00" in aviso
    assert resp.headers.get("X-Tt-Notice-Kind") == "warning"
    assert 'id="tt-cashier-body"' in resp.text
    db_session.refresh(clearance)
    assert clearance.cleared_via == "no_charge", "no se debe cobrar sobre una fila ya liberada"
    assert clearance.receipt_number is None


def test_total_arriba_del_tope_de_monto_se_cobra_si_coincide(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
):
    """Ruling R9: `expected_total` solo se valida finito y >= 0 (sin el tope
    `AMOUNT_MAX`, que topa lo que SE TECLEA, no la suma de adeudo + donación)."""
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService, AMOUNT_MAX,
    )
    staff = make_cashier_staff()
    cohort = make_cohort(book_donation_amount=Decimal("5000.00"))
    proc = make_process(make_student(control_number="99700041"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=AMOUNT_MAX)
    db_session.refresh(clearance)
    total = clearance.total_amount
    assert total > AMOUNT_MAX, "la prueba debe ejercitar un total arriba del tope"

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/pagar",
        data={"tab": "por_cobrar", "q": "", "dia": "", "page": "1",
              "expected_total": str(total)})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(clearance)
    assert clearance.status == "cleared"
    assert clearance.total_amount == total


# ---------------------------------------------------------------------------
# Revertir pago
# ---------------------------------------------------------------------------
def test_revertir_pago_regresa_a_por_cobrar(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
):
    staff = make_cashier_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99700051"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("300"))
    LibraryClearanceService.register_payment(db_session, clearance.id, staff.id,
                                             receipt_number="R-1")
    db_session.refresh(clearance)
    assert clearance.status == "cleared"

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/revertir",
        data={"tab": "pagados", "q": "", "dia": "", "page": "1",
              "reason": "Cobro equivocado"})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(clearance)
    assert clearance.status == "awaiting_payment"
    assert clearance.receipt_number is None


def test_revertir_con_fase_2_aprobada_responde_400(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
):
    from itcj2.apps.titulatec.models import ProcessPhase

    staff = make_cashier_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99700052"), cohort=cohort, current_phase=2,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("300"))
    LibraryClearanceService.register_payment(db_session, clearance.id, staff.id)
    db_session.refresh(clearance)
    assert clearance.status == "cleared"
    # El cobro ocurrió con la fase 2 ABIERTA (desde la Ruling R20 Biblioteca
    # ya no registra a quien pasó su cotejo); DESPUÉS SE la aprueba.
    (db_session.query(ProcessPhase)
     .filter_by(process_id=proc.id, phase_number=2)
     .update({"status": "approved"}))
    db_session.flush()

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/revertir",
        data={"tab": "pagados", "q": "", "dia": "", "page": "1", "reason": "x"})

    assert resp.status_code == 400, resp.text[:300]
    assert resp.headers.get("X-Tt-Error")
    db_session.refresh(clearance)
    assert clearance.status == "cleared", "la fase 2 aprobada no se debe poder revertir"


# ---------------------------------------------------------------------------
# «Pagados»: corte del día y total
# ---------------------------------------------------------------------------
def test_pagados_sin_dia_usa_hoy_por_omision(client_as, make_cashier_staff):
    from itcj2.core.utils.timezone import db_now

    resp = client_as(make_cashier_staff()).get(f"{URL}/body?tab=pagados")

    assert resp.status_code == 200, resp.text[:500]
    hoy = db_now().date().isoformat()
    assert f'value="{hoy}"' in resp.text


def test_pagados_corte_del_dia_respeta_el_selector_y_total(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
    monkeypatch,
):
    """`day_cut` lee `ProcessEvent.created_at` (server-side), NO
    `LibraryClearance.paid_at`: parchar `db_now()` del service solo controla
    lo que el PYTHON de `register_payment` escribe -nunca el
    `server_default=NOW()` del evento-, así que cada pago fija el
    `created_at` de su propio evento A MANO después de registrarlo (mismo
    patrón que `TestDayCut` de test_library_clearance_service.py); nada
    depende del reloj de verdad."""
    from itcj2.apps.titulatec.models import ProcessEvent
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_cashier_staff()
    cohort = make_cohort(book_donation_amount=Decimal("100.00"))
    p1 = make_process(make_student(control_number="99700111"), cohort=cohort, current_phase=1,
                      library_clearance="pending")
    p2 = make_process(make_student(control_number="99700112"), cohort=cohort, current_phase=1,
                      library_clearance="pending")
    p3 = make_process(make_student(control_number="99700113"), cohort=cohort, current_phase=1,
                      library_clearance="pending")
    c1, c2, c3 = (_clearance(db_session, p) for p in (p1, p2, p3))
    LibraryClearanceService.register(db_session, c1.id, staff.id, debt_amount=Decimal("200"))
    LibraryClearanceService.register(db_session, c2.id, staff.id, debt_amount=Decimal("300"))
    LibraryClearanceService.register(db_session, c3.id, staff.id, debt_amount=Decimal("50"))

    def _registrar_el(cuando, clearance_id, process_id):
        monkeypatch.setattr(SVC_DB_NOW, lambda: cuando)
        LibraryClearanceService.register_payment(db_session, clearance_id, staff.id)
        evento = (db_session.query(ProcessEvent)
                 .filter_by(event_type="library_payment_registered", process_id=process_id)
                 .order_by(ProcessEvent.id.desc()).first())
        evento.created_at = cuando

    # Días sintéticos en 2031, donde nadie más de la BD compartida cobra
    # (mismo criterio que `TestDayCut` de test_library_clearance_service.py).
    _registrar_el(datetime(2031, 4, 10, 12, 0, 0), c1.id, p1.id)
    _registrar_el(datetime(2031, 4, 10, 15, 0, 0), c2.id, p2.id)
    _registrar_el(datetime(2031, 4, 11, 9, 0, 0), c3.id, p3.id)

    # 200+100 (c1) + 300+100 (c2) = $700.00; c3 cae en OTRO día.
    resp = client_as(staff).get(f"{URL}/body?tab=pagados&dia=2031-04-10")

    assert resp.status_code == 200, resp.text[:500]
    assert "99700111" in resp.text and "99700112" in resp.text
    assert "99700113" not in resp.text, "el pago de otro día no debe aparecer en este corte"
    assert "Cobrado $700.00" in resp.text
    assert "Total del día $700.00" in resp.text


def test_dia_basura_cae_en_hoy(client_as, make_cashier_staff):
    """m24: `dia=no-es-fecha` no es un valor ISO real -> cae en hoy, nunca un
    400 (`_parse_dia` es un filtro de vista)."""
    from itcj2.core.utils.timezone import db_now

    resp = client_as(make_cashier_staff()).get(f"{URL}/body?tab=pagados&dia=no-es-fecha")

    assert resp.status_code == 200, resp.text[:500]
    hoy = db_now().date().isoformat()
    assert f'value="{hoy}"' in resp.text


def test_expected_total_nan_responde_400(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
):
    """m25: `Decimal("NaN")` SÍ parsea en `_expected_total` (NaN es un
    `Decimal` válido), pero `_check_total_shape` lo ataja con `.is_finite()`
    -> 400 + `X-Tt-Error`, nunca un 500 ni un cobro."""
    staff = make_cashier_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99700115"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("300"))
    db_session.refresh(clearance)

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/pagar",
        data={"tab": "por_cobrar", "q": "", "dia": "", "page": "1",
              "expected_total": "NaN"})

    assert resp.status_code == 400, resp.text[:300]
    assert resp.headers.get("X-Tt-Error")
    db_session.refresh(clearance)
    assert clearance.status == "awaiting_payment", "NaN no debe cobrar nada"
    assert clearance.receipt_number is None


def test_pagados_dia_vacio_sin_movimientos(client_as, make_cashier_staff):
    """m26: un día sin ningún `ProcessEvent` de Caja -> «No hay movimientos
    ese día.» y los tres totales del encabezado en $0.00."""
    resp = client_as(make_cashier_staff()).get(f"{URL}/body?tab=pagados&dia=2031-04-21")

    assert resp.status_code == 200, resp.text[:500]
    assert "No hay movimientos ese día." in resp.text
    assert "Cobrado $0.00" in resp.text
    assert "Total del día $0.00" in resp.text


def test_dia_con_reversa_muestra_monto_negativo_y_totales_con_signo(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
    monkeypatch,
):
    """Un renglón `reversal` en el corte del día trae el «−» real en su
    Monto; el encabezado dice «Revertido −$Y» (Y > 0) y un «Total del día»
    NEGATIVO cuando el cobro que esa reversa anula es de OTRO día -el corte
    de hoy solo trae la reversa (E3)."""
    from itcj2.apps.titulatec.models import ProcessEvent
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_cashier_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99700132"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("300"))

    def _en(cuando, fn):
        monkeypatch.setattr(SVC_DB_NOW, lambda: cuando)
        fn()
        evento = (db_session.query(ProcessEvent)
                 .filter_by(process_id=proc.id)
                 .order_by(ProcessEvent.id.desc()).first())
        evento.created_at = cuando
        return evento

    _en(datetime(2031, 4, 27, 9, 0), lambda: LibraryClearanceService.register_payment(
        db_session, clearance.id, staff.id, receipt_number="R-1"))
    reversa = _en(datetime(2031, 4, 28, 9, 0), lambda: LibraryClearanceService.revert_payment(
        db_session, clearance.id, staff.id, "Error"))

    resp = client_as(staff).get(f"{URL}/body?tab=pagados&dia=2031-04-28")

    assert resp.status_code == 200, resp.text[:500]
    fila = _row(resp.text, f"caja-mov-{reversa.id}")
    assert fila, "no se encontró el renglón de la reversa"
    assert "−$300.00" in fila
    assert "Revertido −$300.00" in resp.text
    assert "Total del día −$300.00" in resp.text


def test_pildoras_propias_de_caja_en_busqueda(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
):
    """m27 (E11): Caja pinta su PROPIA píldora en la búsqueda -- nunca la
    compartida `library_clearance_pill` («Por pagar en Caja»/«Constancia
    previa»). Cada aserción se recorta a SU PROPIA fila (`caja-{id}`, `_row`)
    -nunca el texto de otro renglón de la misma tabla-, incluida la regla
    «Revocada» PRIMERO (manda sobre cualquier `status`, aunque el no adeudo
    siga `awaiting_payment`)."""
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_cashier_staff()
    cohort = make_cohort(book_donation_amount=Decimal("50.00"))
    p_pendiente = make_process(make_student(control_number="99700124", first_name="UNO",
                                            last_name="PILDORACAJA"),
                               cohort=cohort, current_phase=1, library_clearance="pending")
    c_pendiente = _clearance(db_session, p_pendiente)

    p_caja = make_process(make_student(control_number="99700125", first_name="DOS",
                                       last_name="PILDORACAJA"),
                          cohort=cohort, current_phase=1, library_clearance="pending")
    c_caja = _clearance(db_session, p_caja)
    LibraryClearanceService.register(db_session, c_caja.id, staff.id, debt_amount=Decimal("100"))

    p_pagado = make_process(make_student(control_number="99700126", first_name="TRES",
                                         last_name="PILDORACAJA"),
                            cohort=cohort, current_phase=1, library_clearance="pending")
    c_pagado = _clearance(db_session, p_pagado)
    LibraryClearanceService.register(db_session, c_pagado.id, staff.id, debt_amount=Decimal("100"))
    LibraryClearanceService.register_payment(db_session, c_pagado.id, staff.id)

    cohort_libre = make_cohort(book_donation_amount=Decimal("0.00"))
    p_liberado = make_process(make_student(control_number="99700127", first_name="CUATRO",
                                           last_name="PILDORACAJA"),
                              cohort=cohort_libre, current_phase=1, library_clearance="pending")
    c_liberado = _clearance(db_session, p_liberado)
    LibraryClearanceService.register(db_session, c_liberado.id, staff.id, debt_amount=Decimal("0"))
    db_session.refresh(c_liberado)
    assert c_liberado.status == "cleared" and c_liberado.cleared_via == "no_charge"

    # Revocado CON un no-adeudo todavía `awaiting_payment` (m27): «Revocada»
    # manda, nunca «Por cobrar $X» aunque el status siga diciendo eso.
    p_revocado = make_process(make_student(control_number="99700128", first_name="CINCO",
                                           last_name="PILDORACAJA"),
                              cohort=cohort, current_phase=1, library_clearance="pending")
    c_revocado = _clearance(db_session, p_revocado)
    LibraryClearanceService.register(db_session, c_revocado.id, staff.id, debt_amount=Decimal("100"))
    (db_session.query(TitulationProcess).filter_by(id=p_revocado.id)
     .update({"status": "cancelled"}))
    db_session.flush()

    resp = client_as(staff).get(f"{URL}/body?q=PILDORACAJA")

    assert resp.status_code == 200, resp.text[:500]
    assert "En Biblioteca" in _row(resp.text, f"caja-{c_pendiente.id}")

    fila_caja = _row(resp.text, f"caja-{c_caja.id}")
    assert "Por cobrar $150.00" in fila_caja          # 100 adeudo + 50 donación

    assert "Pagado" in _row(resp.text, f"caja-{c_pagado.id}")
    assert "Liberado" in _row(resp.text, f"caja-{c_liberado.id}")

    fila_revocada = _row(resp.text, f"caja-{c_revocado.id}")
    assert fila_revocada.count("Revocada") == 1, "la píldora manda; sin duplicado (m27/cosmético)"
    assert "Por cobrar" not in fila_revocada


def test_revertir_solo_aparece_en_el_cobro_vigente_del_corte(
    client_as, db_session, make_cashier_staff, make_student, make_cohort, make_process,
    monkeypatch,
):
    """Review Focus #3, a nivel de plantilla: cobro + reversa + cobro el
    mismo día -> el botón «Revertir…» del corte sale UNA sola vez (en el
    cobro vigente), aunque haya dos renglones `charge`."""
    from itcj2.apps.titulatec.models import ProcessEvent
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_cashier_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99700131"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("300"))

    def _en(cuando, fn):
        monkeypatch.setattr(SVC_DB_NOW, lambda: cuando)
        fn()
        evento = (db_session.query(ProcessEvent)
                 .filter_by(process_id=proc.id)
                 .order_by(ProcessEvent.id.desc()).first())
        evento.created_at = cuando

    _en(datetime(2031, 4, 26, 9, 0), lambda: LibraryClearanceService.register_payment(
        db_session, clearance.id, staff.id, receipt_number="R-1"))
    _en(datetime(2031, 4, 26, 10, 0), lambda: LibraryClearanceService.revert_payment(
        db_session, clearance.id, staff.id, "Error"))
    _en(datetime(2031, 4, 26, 11, 0), lambda: LibraryClearanceService.register_payment(
        db_session, clearance.id, staff.id, receipt_number="R-2"))

    resp = client_as(staff).get(f"{URL}/body?tab=pagados&dia=2031-04-26")

    assert resp.status_code == 200, resp.text[:500]
    # 3 renglones DISTINTOS (2 cobros + 1 reversa) -- no la fila ÚNICA y
    # vigente que pintaba el viejo `paid_on` para esta misma clearance.
    assert resp.text.count('id="caja-mov-') == 3
    # "R-1" también sale en el renglón de la reversa (el recibo que revirtió,
    # payload.receipt de `revert_payment`): el cobro nuevo es "R-2" y solo él
    # debe ofrecer «Revertir…».
    assert resp.text.count("R-2") == 1
    assert resp.text.count("Revertir…") == 1, "solo el cobro vigente debe ofrecer revertir"


# ---------------------------------------------------------------------------
# Errores: 404 de existencia
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sufijo,form", [
    ("pagar", {"expected_total": "0.00"}),
    ("revertir", {"reason": "x"}),
])
def test_id_inexistente_responde_404(sufijo, form, client_as, make_cashier_staff):
    base = {"tab": "por_cobrar", "q": "", "dia": "", "page": "1"}
    resp = client_as(make_cashier_staff()).post(
        f"{URL}/999999/{sufijo}", data={**base, **form})

    assert resp.status_code == 404, resp.text[:300]


# ---------------------------------------------------------------------------
# Un código por ruta: un permiso de más no debe abrir otra acción
# ---------------------------------------------------------------------------
def test_permiso_de_list_no_alcanza_para_cobrar(
    client_as, db_session, make_user, make_role, grant_user_role,
    make_student, make_cohort, make_process,
):
    user = make_user(first_name="SOLO", last_name="LECTURACAJA")
    role = make_role("tt_test_solo_lectura_caja", ("titulatec.library_payment.page.list",))
    grant_user_role(user, role)
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99700101"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    LibraryClearanceService.register(db_session, clearance.id, user.id, debt_amount=Decimal("100"))
    db_session.refresh(clearance)

    resp = client_as(user).post(
        f"{URL}/{clearance.id}/pagar",
        data={"tab": "por_cobrar", "q": "", "dia": "", "page": "1",
              "expected_total": "100.00"})

    assert resp.status_code == 403, resp.text[:300]


def test_permiso_de_cobrar_no_alcanza_para_revertir(
    client_as, db_session, make_user, make_role, grant_user_role,
    make_student, make_cohort, make_process,
):
    user = make_user(first_name="SOLO", last_name="COBRACAJA")
    role = make_role("tt_test_solo_cobra_caja", (
        "titulatec.library_payment.page.list",
        "titulatec.library_payment.api.register",
    ))
    grant_user_role(user, role)
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99700102"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    LibraryClearanceService.register(db_session, clearance.id, user.id, debt_amount=Decimal("100"))
    LibraryClearanceService.register_payment(db_session, clearance.id, user.id)
    db_session.refresh(clearance)

    resp = client_as(user).post(
        f"{URL}/{clearance.id}/revertir",
        data={"tab": "pagados", "q": "", "dia": "", "page": "1", "reason": "x"})

    assert resp.status_code == 403, resp.text[:300]


# ---------------------------------------------------------------------------
# Estructural: sin `{process_id}` en ninguna ruta de esta bandeja (§5 inv. 6)
# ---------------------------------------------------------------------------
def test_ninguna_ruta_lleva_process_id():
    from itcj2.apps.titulatec.pages.cashier_admin import router

    paths = [getattr(r, "path", "") for r in router.routes]
    assert paths, "el router de caja no tiene rutas"
    assert not any("{process_id}" in p for p in paths), paths
