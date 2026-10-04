"""Bandeja de Biblioteca (`pages/library_admin.py`), no adeudo de biblioteca.

Biblioteca (rol `titulatec_library`, puesto «Biblioteca · No adeudo») trabaja la
cola FIFO de TODA inscripción aceptada (`LibraryClearance`, Tarea 4): «Sin
adeudo» (fila y lote), «Con adeudo…» (monto + nota), «Constancia previa…»
(fecha + nota) desde «Por revisar»; «Corregir…» desde «En caja»; «Revertir…»/
«Deshacer…» desde «Liberados». Estas pruebas cubren la RUTA (permisos,
pestañas, formularios, concurrencia, códigos de error); la máquina de estados
en sí ya la cubre `test_library_clearance_service.py` (Tarea 4).

Spec `docs/superpowers/specs/2026-10-01-titulatec-biblioteca-caja-design.md`
§4.7 (bandeja), §4.2 (estados/errores), §4.6 (permisos/nav), D3/D10/D18/D19,
§5 invariante 6 (sin `{process_id}` en estas rutas).

`make_library_staff` es un actor sintético con rol DIRECTO (`grant_user_role`),
no por puesto: el reparto puesto -> rol de producción ya lo verifica
`test_permissions_contract.py` contra el DML de la Tarea 2. Aquí solo importa
el CONJUNTO de permisos que el gate exige.

Cada `make_process(..., library_clearance=...)` usa un `cohort` propio con
`book_donation_amount` YA capturado (`make_cohort(book_donation_amount=...)`):
el default de `make_cohort` es `None` ("sin configurar", D19) y CUALQUIER
`register`/lote sobre esa convocatoria por omisión daría 400 -- a propósito
para la prueba de ese caso, mortal por accidente en cualquier otra.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import unquote

import pytest

URL = "/titulatec/admin/biblioteca"

LIBRARY_PERMS = (
    "titulatec.library_clearance.page.list",
    "titulatec.library_clearance.api.register",
    "titulatec.library_clearance.api.prior",
    "titulatec.library_clearance.api.revert",
)


@pytest.fixture()
def make_library_staff(make_user, make_role, grant_user_role):
    """Actor sintético de Biblioteca: rol DIRECTO con los permisos de la bandeja."""
    def _make(perm_codes=LIBRARY_PERMS, first_name="BIBLIOTECA", last_name="FICTICIA"):
        user = make_user(first_name=first_name, last_name=last_name)
        role = make_role("tt_test_library", perm_codes)
        grant_user_role(user, role)
        return user

    return _make


def _tab_span(html, tab_id):
    """Recorta el botón de una pestaña completo, para revisar SU contador
    (y no un dígito suelto en cualquier otra parte de la página)."""
    m = re.search(r'id="%s".*?</button>' % re.escape(tab_id), html, re.S)
    return m.group(0) if m else ""


def _clearance(db_session, process):
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    return LibraryClearanceService.get_for_process(db_session, process.id)


def _certs(db_session, clearance_id):
    from itcj2.apps.titulatec.models import Certificate
    return (db_session.query(Certificate)
            .filter_by(source_ref=f"library_clearance:{clearance_id}")
            .order_by(Certificate.id).all())


def _fila(html, marca):
    """La fila completa (hasta el siguiente `</tr>`): acota los asserts a ESA
    fila y no a cualquier otra parte de la bandeja (patrón ya usado por
    `test_una_inscripcion_revocada_no_ofrece_acciones_y_se_etiqueta`)."""
    assert marca in html, "falta la fila sembrada"
    return html.split(marca, 1)[1].split("</tr>", 1)[0]


def _celda(fila, texto):
    """El ÚNICO `<td>` de `fila` que contiene `texto`, tal cual (HTML crudo):
    acota los asserts a ESA celda -la columna «Constancia»- y no a la fila."""
    celdas = [c for c in re.findall(r"<td[^>]*>(.*?)</td>", fila, re.S) if texto in c]
    assert len(celdas) == 1, celdas
    return celdas[0]


def _visible(html):
    """El texto que se lee de un pedazo de HTML: sin etiquetas, espacios juntos."""
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


# ---------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------
def test_una_jefatura_de_escolares_sin_permiso_de_biblioteca_no_entra(client_as, make_head):
    """Medido, no asumido: `require_page_app` sin el permiso de esta página
    devuelve 403 (la jefa SÍ tiene acceso a la app, solo le falta el permiso
    de `library_clearance.page.list` -> `PageForbidden(has_app_access=True)`)."""
    resp = client_as(make_head()).get(URL)

    assert resp.status_code == 403, resp.text[:300]


def test_un_graduate_no_entra(client_as, make_student):
    resp = client_as(make_student()).get(URL)

    assert resp.status_code == 403, resp.text[:300]


def test_menu_solo_muestra_biblioteca_con_el_permiso(client_as, make_head, make_library_staff):
    sin_permiso = client_as(make_head()).get("/titulatec/admin/documents")
    assert sin_permiso.status_code == 200, sin_permiso.text[:500]
    assert "/titulatec/admin/biblioteca" not in sin_permiso.text

    con_permiso = client_as(make_library_staff()).get(URL)
    assert con_permiso.status_code == 200, con_permiso.text[:500]
    assert "/titulatec/admin/biblioteca" in con_permiso.text
    assert "Biblioteca" in con_permiso.text


# ---------------------------------------------------------------------------
# Bandeja: pestañas, contadores, filas, FIFO, búsqueda
# ---------------------------------------------------------------------------
def test_ve_pestanas_con_contadores_y_filas(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    student = make_student(control_number="99600001", first_name="EGRESADA", last_name="PRUEBA")
    proc = make_process(student, cohort=cohort, current_phase=1, library_clearance="pending")

    resp = client_as(staff).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "Por revisar" in resp.text
    assert "En caja" in resp.text
    assert "Liberados" in resp.text
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    counts = LibraryClearanceService.counts_by_status(db_session)
    assert counts["pending"] >= 1, "el caso sembrado tiene que contar"
    assert f'>{counts["pending"]}<' in _tab_span(resp.text, "tt-lib-tab-pending")
    clearance = _clearance(db_session, proc)
    assert f'id="lib-{clearance.id}"' in resp.text
    assert student.control_number in resp.text


def test_body_acepta_los_mismos_query_params_que_la_pagina(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    make_process(make_student(control_number="99600002"), cohort=cohort, current_phase=1,
                library_clearance="pending")
    c = client_as(staff)

    pagina = c.get(f"{URL}?status=pending")
    cuerpo = c.get(f"{URL}/body?status=pending")

    assert pagina.status_code == 200 and cuerpo.status_code == 200
    assert 'id="tt-library-body"' in cuerpo.text
    assert "99600002" in pagina.text
    assert "99600002" in cuerpo.text


def test_fifo_por_revisar_ordena_por_fecha_de_inscripcion(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    s1 = make_student(control_number="99600011", first_name="PRIMERO", last_name="ENLLEGAR")
    s2 = make_student(control_number="99600012", first_name="SEGUNDO", last_name="ENLLEGAR")
    p1 = make_process(s1, cohort=cohort, current_phase=1, library_clearance="pending")
    p2 = make_process(s2, cohort=cohort, current_phase=1, library_clearance="pending")
    c1, c2 = _clearance(db_session, p1), _clearance(db_session, p2)

    resp = client_as(staff).get(f"{URL}/body?status=pending&q=ENLLEGAR")

    assert resp.status_code == 200, resp.text[:500]
    pos1 = resp.text.find(f'id="lib-{c1.id}"')
    pos2 = resp.text.find(f'id="lib-{c2.id}"')
    assert pos1 != -1 and pos2 != -1, "faltan filas sembradas"
    assert pos1 < pos2, "FIFO: el primero en inscribirse debe salir primero"


def test_busqueda_filtra_por_control_o_nombre(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    make_process(make_student(control_number="99600021", first_name="ANA", last_name="BUSCADA"),
                cohort=cohort, current_phase=1, library_clearance="pending")
    make_process(make_student(control_number="99600022", first_name="LUIS", last_name="OTRO"),
                cohort=cohort, current_phase=1, library_clearance="pending")

    resp = client_as(staff).get(f"{URL}/body?status=pending&q=99600021")

    assert resp.status_code == 200, resp.text[:500]
    assert "99600021" in resp.text
    assert "99600022" not in resp.text


def test_una_busqueda_de_solo_espacios_no_filtra_nada(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    make_process(make_student(control_number="99600023"), cohort=cohort, current_phase=1,
                library_clearance="pending")

    resp = client_as(staff).get(f"{URL}/body?status=pending&q=%20%20%20")

    assert resp.status_code == 200, resp.text[:500]
    assert "99600023" in resp.text


def test_pestana_sin_casos_muestra_bandeja_limpia(client_as, db_session, make_library_staff):
    """El vacío se FABRICA, no se supone (patrón `test_survey_reviews_admin_routes.py`)."""
    from itcj2.apps.titulatec.models import LibraryClearance

    db_session.query(LibraryClearance).filter_by(status="cleared").delete(
        synchronize_session=False)
    db_session.flush()

    resp = client_as(make_library_staff()).get(f"{URL}/body?status=cleared")

    assert resp.status_code == 200, resp.text[:500]
    assert "Bandeja limpia" in resp.text


def test_aviso_de_convocatoria_sin_donacion(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    """D19: convocatoria sin `book_donation_amount` -> aviso arriba de la bandeja."""
    staff = make_library_staff()
    cohort = make_cohort(name="Convocatoria sin donar")   # book_donation_amount=None
    make_process(make_student(control_number="99600031"), cohort=cohort, current_phase=1,
                library_clearance="pending")

    resp = client_as(staff).get(f"{URL}/body?status=pending")

    assert resp.status_code == 200, resp.text[:500]
    assert "donación voluntaria de libro" in resp.text
    assert "Convocatoria sin donar" in resp.text


# ---------------------------------------------------------------------------
# Registrar: Sin adeudo / Con adeudo (D18 total=0 libera directo; si no, Caja)
# ---------------------------------------------------------------------------
def test_sin_adeudo_con_donacion_cero_libera_directo_sin_pasar_por_caja(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600041"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/registrar",
        data={"status": "pending", "q": "", "page": "1", "debt_amount": "0",
              "expected_status": "pending"})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(clearance)
    assert clearance.status == "cleared"
    assert clearance.cleared_via == "no_charge"


def test_con_adeudo_y_donacion_pasa_a_caja_con_desglose(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("200.00"))
    proc = make_process(make_student(control_number="99600042"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/registrar",
        data={"status": "pending", "q": "", "page": "1", "debt_amount": "800",
              "note": "Libro perdido", "expected_status": "pending"})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(clearance)
    assert clearance.status == "awaiting_payment"
    assert clearance.debt_amount == Decimal("800.00")
    assert clearance.donation_amount == Decimal("200.00")
    assert clearance.total_amount == Decimal("1000.00")
    # El caso ya salió de «Por revisar» (la pestaña que trae el `status`
    # oculto del formulario, así que el parcial re-pintado es esa); el
    # desglose se confirma en «En caja», a donde se acaba de mover.
    en_caja = client_as(staff).get(f"{URL}/body?status=awaiting_payment&q=99600042")
    assert "$800.00" in en_caja.text
    assert "$200.00" in en_caja.text
    assert "$1,000.00" in en_caja.text
    assert "Libro perdido" in en_caja.text


def test_sin_adeudo_con_donacion_mayor_a_cero_tambien_pasa_a_caja(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    """D18: «Sin adeudo» es adeudo 0, NO total 0 -- con donación > 0 el
    egresado igual pasa a Caja."""
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("150.00"))
    proc = make_process(make_student(control_number="99600043"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/registrar",
        data={"status": "pending", "q": "", "page": "1", "debt_amount": "0",
              "expected_status": "pending"})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(clearance)
    assert clearance.status == "awaiting_payment"
    assert clearance.total_amount == Decimal("150.00")


def test_monto_invalido_responde_400_sin_escribir_nada(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600044"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/registrar",
        data={"status": "pending", "q": "", "page": "1", "debt_amount": "mucho",
              "expected_status": "pending"})

    assert resp.status_code == 400, resp.text[:300]
    assert resp.headers.get("X-Tt-Error")
    db_session.refresh(clearance)
    assert clearance.status == "pending"
    assert clearance.debt_amount is None


def test_convocatoria_sin_donacion_responde_400_al_registrar(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort = make_cohort()   # sin donación (D19)
    proc = make_process(make_student(control_number="99600045"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/registrar",
        data={"status": "pending", "q": "", "page": "1", "debt_amount": "0",
              "expected_status": "pending"})

    assert resp.status_code == 400, resp.text[:300]
    assert resp.headers.get("X-Tt-Error")


# ---------------------------------------------------------------------------
# Corregir (desde «En caja»): mismo endpoint, expected_status/expected_total
# ---------------------------------------------------------------------------
def test_corregir_en_caja_re_congela_con_la_donacion_vigente(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("200.00"))
    proc = make_process(make_student(control_number="99600051"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("500"))
    db_session.refresh(clearance)
    assert clearance.status == "awaiting_payment" and clearance.total_amount == Decimal("700.00")

    # SE sube la donación a 300 DESPUÉS de registrar: corregir debe usar la VIGENTE.
    cohort.book_donation_amount = Decimal("300.00")
    db_session.flush()

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/registrar",
        data={"status": "awaiting_payment", "q": "", "page": "1", "debt_amount": "300",
              "note": "corregido", "expected_status": "awaiting_payment",
              "expected_total": "700.00"})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(clearance)
    assert clearance.status == "awaiting_payment"
    assert clearance.debt_amount == Decimal("300.00")
    assert clearance.donation_amount == Decimal("300.00")
    assert clearance.total_amount == Decimal("600.00")


def test_corregir_con_total_esperado_desfasado_re_pinta_con_el_monto_vigente(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    """R8 + Ruling R24 (M1): el total oculto que el usuario vio ya no coincide
    (otro lo corrigió primero) -> nunca se pisa el registro ajeno, y la ruta
    responde 200 con la bandeja RE-PINTADA (el monto vigente a la vista) y el
    motivo en `X-Tt-Notice` (warning). Con un 400, htmx no hacía swap: la
    fila seguía mostrando el monto viejo y reintentar volvía a fallar."""
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("100.00"))
    proc = make_process(make_student(control_number="99600052"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("400"))
    db_session.refresh(clearance)
    assert clearance.total_amount == Decimal("500.00")

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/registrar",
        data={"status": "awaiting_payment", "q": "99600052", "page": "1",
              "debt_amount": "100", "expected_status": "awaiting_payment",
              "expected_total": "999.00"})

    assert resp.status_code == 200, resp.text[:300]
    assert not resp.headers.get("X-Tt-Error")
    aviso = unquote(resp.headers.get("X-Tt-Notice") or "")
    assert "El monto cambió mientras lo revisabas: ahora es $500.00" in aviso
    assert resp.headers.get("X-Tt-Notice-Kind") == "warning"
    assert 'id="tt-library-body"' in resp.text
    assert f'id="lib-{clearance.id}"' in resp.text and "$500.00" in resp.text
    db_session.refresh(clearance)
    assert clearance.debt_amount == Decimal("400.00"), "no se debe pisar el monto vigente"


def test_concurrencia_otro_ya_registro_la_fila_re_pinta_y_avisa(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    """Review Focus #1 (R8) + Ruling R24: dos de Biblioteca sobre la misma
    fila. El segundo ve `expected_status=pending` (lo que vio al cargar la
    pantalla), pero la fila ya se movió a `awaiting_payment` -> nunca un
    doble registro; 200 con «Por revisar» re-pintada (la fila ya no está ahí)
    y el aviso de que otra persona la movió."""
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_library_staff()
    otra = make_library_staff(first_name="OTRA", last_name="BIBLIOTECARIA")
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600053"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    # "Otra persona" ya registró mientras el segundo tenía la pantalla abierta.
    LibraryClearanceService.register(db_session, clearance.id, otra.id, debt_amount=Decimal("500"))
    db_session.refresh(clearance)
    assert clearance.status == "awaiting_payment"

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/registrar",
        data={"status": "pending", "q": "99600053", "page": "1", "debt_amount": "300",
              "expected_status": "pending"})

    assert resp.status_code == 200, resp.text[:300]
    aviso = unquote(resp.headers.get("X-Tt-Notice") or "")
    assert "Otra persona ya movió este caso: ahora está «En caja»" in aviso
    assert resp.headers.get("X-Tt-Notice-Kind") == "warning"
    assert 'id="tt-library-body"' in resp.text
    assert f'id="lib-{clearance.id}"' not in resp.text, "ya no está en «Por revisar»"
    db_session.refresh(clearance)
    assert clearance.debt_amount == Decimal("500.00"), "no se debe pisar el registro de otra persona"


def test_dos_sin_adeudo_concurrentes_sobre_la_misma_fila_re_pinta(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    """Ruling R30 #3 (re-revisión de la ola final, M1 COMPLETO): con donación
    $0, «Sin adeudo» (adeudo 0) libera DIRECTO -`cleared/no_charge`, FUERA de
    `("pending", "awaiting_payment")`-. Antes de este arreglo
    `_prepare_registration` revisaba «ya está liberado» ANTES que
    `_check_expected`, así que el segundo clic (la pantalla seguía en «Por
    revisar») caía en el 400 PLANO sin re-pintar, a diferencia de
    `test_concurrencia_otro_ya_registro_la_fila_re_pinta_y_avisa` de arriba
    -ese caso deja la fila en `awaiting_payment`, que SÍ está en la tupla, así
    que ya re-pintaba incluso antes del arreglo-. Ahora `_check_expected`
    corre primero: mismo 200 + bandeja re-pintada + aviso que cualquier otro
    choque, sin importar a qué estado se movió la fila."""
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_library_staff()
    otra = make_library_staff(first_name="OTRA", last_name="BIBLIOTECARIA")
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600111"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    # "Otra persona" ya marcó «Sin adeudo» mientras el segundo tenía la
    # pantalla de «Por revisar» abierta: con donación $0 y adeudo $0 libera
    # DIRECTO, sin pasar por `awaiting_payment`.
    LibraryClearanceService.register(db_session, clearance.id, otra.id, debt_amount=Decimal("0"))
    db_session.refresh(clearance)
    assert clearance.status == "cleared" and clearance.cleared_via == "no_charge"

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/registrar",
        data={"status": "pending", "q": "99600111", "page": "1", "debt_amount": "0",
              "expected_status": "pending"})

    assert resp.status_code == 200, resp.text[:300]
    assert not resp.headers.get("X-Tt-Error")
    aviso = unquote(resp.headers.get("X-Tt-Notice") or "")
    assert "Otra persona ya movió este caso: ahora está «Liberado»" in aviso
    assert resp.headers.get("X-Tt-Notice-Kind") == "warning"
    assert 'id="tt-library-body"' in resp.text
    db_session.refresh(clearance)
    assert clearance.cleared_via == "no_charge", "no se debe reabrir ni repisar lo ya liberado"


def test_corregir_despues_de_que_caja_cobro_re_pinta_sin_pisar_el_pago(
    client_as, db_session, make_library_staff, make_user, make_student, make_cohort,
    make_process,
):
    """Ruling R30 #3: Biblioteca tenía «Corregir…» abierto cuando Caja ya
    cobró -la fila se movió a `cleared/payment`, FUERA de `("pending",
    "awaiting_payment")`-. Antes del arreglo esto caía en el 400 plano de «ya
    está liberado» sin re-pintar; ahora `_check_expected` ve el
    `expected_status=awaiting_payment` desfasado PRIMERO y re-pinta con el
    aviso, como cualquier otro choque; el pago de Caja nunca se pisa."""
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_library_staff()
    cajera = make_user(first_name="CAJA", last_name="FICTICIA")
    cohort = make_cohort(book_donation_amount=Decimal("100.00"))
    proc = make_process(make_student(control_number="99600112"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("400"))
    db_session.refresh(clearance)
    assert clearance.total_amount == Decimal("500.00")
    # Caja ya cobró mientras Biblioteca tenía «Corregir…» abierto.
    LibraryClearanceService.register_payment(db_session, clearance.id, cajera.id)
    db_session.refresh(clearance)
    assert clearance.status == "cleared" and clearance.cleared_via == "payment"

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/registrar",
        data={"status": "awaiting_payment", "q": "99600112", "page": "1",
              "debt_amount": "100", "expected_status": "awaiting_payment",
              "expected_total": "500.00"})

    assert resp.status_code == 200, resp.text[:300]
    assert not resp.headers.get("X-Tt-Error")
    aviso = unquote(resp.headers.get("X-Tt-Notice") or "")
    assert "Otra persona ya movió este caso: ahora está «Liberado»" in aviso
    assert resp.headers.get("X-Tt-Notice-Kind") == "warning"
    db_session.refresh(clearance)
    assert clearance.cleared_via == "payment", "no se debe pisar el pago de Caja"
    assert clearance.debt_amount == Decimal("400.00")


def test_lote_con_una_fila_movida_por_otro_re_pinta_y_avisa(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    """Ruling R24 en el lote: la fila que otra persona movió se OMITE con el
    motivo del choque y la bandeja se re-pinta (200 + aviso warning)."""
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_library_staff()
    otra = make_library_staff(first_name="OTRA", last_name="BIBLIOTECARIA")
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    movida = make_process(make_student(control_number="99600054"), cohort=cohort,
                          current_phase=1, library_clearance="pending")
    libre = make_process(make_student(control_number="99600055"), cohort=cohort,
                         current_phase=1, library_clearance="pending")
    c_movida, c_libre = _clearance(db_session, movida), _clearance(db_session, libre)
    LibraryClearanceService.register(db_session, c_movida.id, otra.id,
                                     debt_amount=Decimal("500"))

    resp = client_as(staff).post(
        f"{URL}/registrar",
        data={"status": "pending", "q": "", "page": "1",
              "ids": [str(c_movida.id), str(c_libre.id)]})

    assert resp.status_code == 200, resp.text[:300]
    aviso = unquote(resp.headers.get("X-Tt-Notice") or "")
    assert "1 registrado · 1 omitido" in aviso
    assert "Otra persona ya movió este caso" in aviso
    assert resp.headers.get("X-Tt-Notice-Kind") == "warning"
    db_session.refresh(c_movida)
    db_session.refresh(c_libre)
    assert c_movida.debt_amount == Decimal("500.00")
    assert c_libre.status == "cleared"


# ---------------------------------------------------------------------------
# Lote «Sin adeudo» (D10)
# ---------------------------------------------------------------------------
def test_barra_de_lote_trae_el_gancho_de_conteo_y_badge_vacio(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    """Fix round 1 (Important, plan-mandated, spec §4.7): la barra debe leer
    «Sin adeudo (N)» con conteo EN VIVO de lo marcado. El servidor renderiza
    el badge VACÍO a propósito -nunca «(0)» fijo, que mentiría para siempre
    si el JS no llega a cargar- y cada casilla de lote lleva
    `data-tt-count-into` apuntando a él; `titulatec-utils.js` (compartido,
    cargado una sola vez por `base.html`) es quien lo llena en el navegador."""
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    make_process(make_student(control_number="99600065"), cohort=cohort, current_phase=1,
                library_clearance="pending")

    resp = client_as(staff).get(f"{URL}/body?status=pending")

    assert resp.status_code == 200, resp.text[:500]
    assert '<span id="tt-lib-bulk-count" aria-live="polite"></span>' in resp.text, (
        "el badge debe nacer vacío en el servidor (nunca un «(0)» fijo) y "
        "anunciarse por lector de pantalla (m23, triage-minors.md)")
    assert 'data-tt-count-into="#tt-lib-bulk-count"' in resp.text, (
        "la casilla de lote debe llevar el gancho genérico de conteo")
    assert "Sin adeudo (seleccionados)" not in resp.text, (
        "el label estático viejo (sin conteo en vivo) ya no debe aparecer")


def test_lote_sin_adeudo_registra_varios_en_una_sola_peticion(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    p1 = make_process(make_student(control_number="99600061"), cohort=cohort, current_phase=1,
                      library_clearance="pending")
    p2 = make_process(make_student(control_number="99600062"), cohort=cohort, current_phase=1,
                      library_clearance="pending")
    c1, c2 = _clearance(db_session, p1), _clearance(db_session, p2)

    resp = client_as(staff).post(
        f"{URL}/registrar",
        data={"status": "pending", "q": "", "page": "1",
              "ids": [str(c1.id), str(c2.id)]})

    assert resp.status_code == 200, resp.text[:500]
    aviso = unquote(resp.headers.get("X-Tt-Notice") or "")
    assert "2 registrados" in aviso
    assert "0 omitidos" in aviso
    db_session.refresh(c1)
    db_session.refresh(c2)
    assert c1.status == "cleared" and c2.status == "cleared"


def test_lote_omite_filas_que_no_pasan_la_validacion_y_dice_el_motivo(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort_ok = make_cohort(book_donation_amount=Decimal("0.00"))
    cohort_sin_donacion = make_cohort()
    p1 = make_process(make_student(control_number="99600063"), cohort=cohort_ok,
                      current_phase=1, library_clearance="pending")
    p2 = make_process(make_student(control_number="99600064"), cohort=cohort_sin_donacion,
                      current_phase=1, library_clearance="pending")
    c1, c2 = _clearance(db_session, p1), _clearance(db_session, p2)

    resp = client_as(staff).post(
        f"{URL}/registrar",
        data={"status": "pending", "q": "", "page": "1",
              "ids": [str(c1.id), str(c2.id)]})

    assert resp.status_code == 200, resp.text[:500]
    aviso = unquote(resp.headers.get("X-Tt-Notice") or "")
    assert "1 registrado" in aviso
    assert "1 omitido" in aviso
    assert "donación" in aviso
    db_session.refresh(c1)
    db_session.refresh(c2)
    assert c1.status == "cleared"
    assert c2.status == "pending"


def test_lote_sin_seleccion_responde_400(client_as, make_library_staff):
    resp = client_as(make_library_staff()).post(
        f"{URL}/registrar", data={"status": "pending", "q": "", "page": "1"})

    assert resp.status_code == 400, resp.text[:300]
    assert resp.headers.get("X-Tt-Error")


def test_lote_con_un_id_no_numerico_responde_400(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    """m19: `ids=["abc"]` (o mezclado con uno válido -el campo oculto manipulado
    a mano, o una casilla que mandara basura-) no debe llegar a `int(cid)` sin
    red: la ruta ya responde 400 limpio (`register_bulk`), pero no tenía
    prueba propia."""
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    p1 = make_process(make_student(control_number="99600301"), cohort=cohort, current_phase=1,
                      library_clearance="pending")
    c1 = _clearance(db_session, p1)

    resp = client_as(staff).post(
        f"{URL}/registrar",
        data={"status": "pending", "q": "", "page": "1",
              "ids": [str(c1.id), "abc"]})

    assert resp.status_code == 400, resp.text[:300]
    assert unquote(resp.headers.get("X-Tt-Error") or "") == "Selección inválida."
    db_session.refresh(c1)
    assert c1.status == "pending", "una seleccion invalida no debe registrar nada"


def test_lote_con_todos_ya_fuera_de_pendiente_no_registra_ninguno(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    """m20: con TODOS los ids ya fuera de «Por revisar» (alguien más los
    movió mientras la bandeja seguía abierta -mismo choque que la prueba de
    omisión PARCIAL de arriba, aquí con los DOS ids omitidos-) el lote no
    registra a nadie, pero sigue respondiendo 200 -nunca 400, Ruling R24- con
    «0 registrados · N omitidos» en warning."""
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    p1 = make_process(make_student(control_number="99600302"), cohort=cohort, current_phase=1,
                      library_clearance="pending")
    p2 = make_process(make_student(control_number="99600303"), cohort=cohort, current_phase=1,
                      library_clearance="pending")
    c1, c2 = _clearance(db_session, p1), _clearance(db_session, p2)
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    LibraryClearanceService.register(db_session, c1.id, staff.id, debt_amount=Decimal("0"))
    LibraryClearanceService.register(db_session, c2.id, staff.id, debt_amount=Decimal("0"))
    db_session.refresh(c1)
    db_session.refresh(c2)
    assert c1.status == "cleared" and c2.status == "cleared"

    resp = client_as(staff).post(
        f"{URL}/registrar",
        data={"status": "pending", "q": "", "page": "1",
              "ids": [str(c1.id), str(c2.id)]})

    assert resp.status_code == 200, resp.text[:500]
    aviso = unquote(resp.headers.get("X-Tt-Notice") or "")
    assert "0 registrados" in aviso
    assert "2 omitidos" in aviso
    assert resp.headers.get("X-Tt-Notice-Kind") == "warning"
    db_session.refresh(c1)
    db_session.refresh(c2)
    assert c1.status == "cleared" and c2.status == "cleared", (
        "nada debe mutar cuando TODOS los ids se omiten")


# ---------------------------------------------------------------------------
# Constancia previa (D9) / Deshacer
# ---------------------------------------------------------------------------
def test_constancia_previa_libera_sin_pasar_por_caja(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("150.00"))
    proc = make_process(make_student(control_number="99600071"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    fecha = (date.today() - timedelta(days=30)).isoformat()

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/previa",
        data={"status": "pending", "q": "", "page": "1", "issued_on": fecha,
              "note": "Folio 123"})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(clearance)
    assert clearance.status == "cleared"
    assert clearance.cleared_via == "prior"
    assert clearance.prior_issued_on.isoformat() == fecha


def test_constancia_previa_vencida_responde_400(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    """§4.2: `issued_on < hoy - 365 días` -> `ValueError` legible."""
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600072"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    fecha = (date.today() - timedelta(days=366)).isoformat()

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/previa",
        data={"status": "pending", "q": "", "page": "1", "issued_on": fecha})

    assert resp.status_code == 400, resp.text[:300]
    assert resp.headers.get("X-Tt-Error")
    db_session.refresh(clearance)
    assert clearance.status == "pending"


def test_constancia_previa_fecha_con_formato_invalido_responde_400(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600073"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/previa",
        data={"status": "pending", "q": "", "page": "1", "issued_on": "31/02/2026"})

    assert resp.status_code == 400, resp.text[:300]
    assert resp.headers.get("X-Tt-Error")


def test_constancia_previa_sin_fecha_responde_400(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600074"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/previa",
        data={"status": "pending", "q": "", "page": "1", "issued_on": ""})

    assert resp.status_code == 400, resp.text[:300]
    assert resp.headers.get("X-Tt-Error")


def test_deshacer_constancia_previa_regresa_a_pendiente(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("300.00"))
    proc = make_process(make_student(control_number="99600075"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register_prior(
        db_session, clearance.id, staff.id,
        issued_on=date.today() - timedelta(days=10), by="library")
    db_session.refresh(clearance)
    assert clearance.status == "cleared" and clearance.cleared_via == "prior"

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/deshacer-previa",
        data={"status": "cleared", "q": "", "page": "1", "reason": "fecha mal capturada"})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(clearance)
    assert clearance.status == "pending"


# ---------------------------------------------------------------------------
# Revertir una liberación sin cargo o legado
# ---------------------------------------------------------------------------
def test_revertir_liberacion_sin_cargo_regresa_a_pendiente(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600081"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("0"))
    db_session.refresh(clearance)
    assert clearance.status == "cleared" and clearance.cleared_via == "no_charge"

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/revertir",
        data={"status": "cleared", "q": "", "page": "1", "reason": "me equivoqué"})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(clearance)
    assert clearance.status == "pending"


def test_revertir_un_pago_no_se_hace_desde_biblioteca(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    """`cleared_via='payment'` lo revierte Caja, no Biblioteca: el service
    levanta `ValueError` y la ruta responde 400 (nunca lo hace a su manera)."""
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("100.00"))
    proc = make_process(make_student(control_number="99600082"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("0"))
    db_session.refresh(clearance)
    LibraryClearanceService.register_payment(db_session, clearance.id, staff.id)
    db_session.refresh(clearance)
    assert clearance.status == "cleared" and clearance.cleared_via == "payment"

    resp = client_as(staff).post(
        f"{URL}/{clearance.id}/revertir",
        data={"status": "cleared", "q": "", "page": "1", "reason": "x"})

    assert resp.status_code == 400, resp.text[:300]
    assert resp.headers.get("X-Tt-Error")


def test_liberados_muestra_pildora_fecha_y_numero_de_constancia(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600083"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("0"))
    db_session.refresh(clearance)

    resp = client_as(staff).get(f"{URL}/body?status=cleared&q=99600083")

    assert resp.status_code == 200, resp.text[:500]
    assert f'id="lib-{clearance.id}"' in resp.text
    assert "BIB-" in resp.text


# ---------------------------------------------------------------------------
# Columna «Constancia» (Tarea 3, 2026-10-02-titulatec-constancias-y-pendientes
# -design.md §3.3/E1/E6): folio + si ya se imprimió, a la derecha de «Estado»
# en las 3 pestañas. Reemplaza el folio suelto que antes vivía bajo «Estado».
# ---------------------------------------------------------------------------
def test_columna_constancia_vigente_sin_imprimir_muestra_folio_y_pildora_ambar(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600210"), cohort=cohort,
                        current_phase=1, library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("0"))
    cert = _certs(db_session, clearance.id)[0]

    resp = client_as(staff).get(f"{URL}/body?status=cleared&q=99600210")

    assert resp.status_code == 200, resp.text[:500]
    fila = _fila(resp.text, f'id="lib-{clearance.id}"')
    assert cert.number in fila
    assert "Sin imprimir" in fila
    assert "tt-pill--amber" in fila
    assert "Impresa" not in fila


def test_columna_constancia_impresa_muestra_pildora_verde_lote_y_fecha(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    from itcj2.apps.titulatec.services.certificate_service import CertificateService
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600211"), cohort=cohort,
                        current_phase=1, library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("0"))
    cert = _certs(db_session, clearance.id)[0]
    batch = CertificateService.create_batch(db_session, kind="library_clearance",
                                            actor_id=staff.id)

    resp = client_as(staff).get(f"{URL}/body?status=cleared&q=99600211")

    assert resp.status_code == 200, resp.text[:500]
    fila = _fila(resp.text, f'id="lib-{clearance.id}"')
    assert cert.number in fila
    assert "Impresa" in fila
    assert "tt-pill--success" in fila
    assert f"lote #{batch.id}" in fila
    assert batch.created_at.strftime("%d/%m/%Y") in fila


def test_columna_constancia_anulada_tras_imprimir_avisa_retirar_el_papel(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    """Pagado -> impreso -> revertido (Review Focus #1 del plan): la celda ya
    no trae la vigente (se anuló); avisa que hay un papel que retirar.

    M1 (revisión final): sin `prior` ni `legacy`, la celda ABRE con el aviso
    -nada de un «—» suelto ni un `<br>` arriba-: la fila SÍ tuvo constancia,
    así que «—» («nunca tuvo») contradecía al aviso de abajo."""
    from itcj2.apps.titulatec.services.certificate_service import CertificateService
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600212"), cohort=cohort,
                        current_phase=1, library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("0"))
    cert = _certs(db_session, clearance.id)[0]
    batch = CertificateService.create_batch(db_session, kind="library_clearance",
                                            actor_id=staff.id)
    LibraryClearanceService.revert_clearance(db_session, clearance.id, staff.id,
                                             "se imprimió por error")
    db_session.refresh(clearance)
    assert clearance.status == "pending"

    resp = client_as(staff).get(f"{URL}/body?status=pending&q=99600212")

    assert resp.status_code == 200, resp.text[:500]
    fila = _fila(resp.text, f'id="lib-{clearance.id}"')
    assert "Anulada tras imprimir" in fila
    assert "tt-pill--danger" in fila
    assert cert.number in fila
    assert f"lote #{batch.id} — retira ese papel" in fila
    celda = _celda(fila, "Anulada tras imprimir")
    assert not celda.lstrip().startswith(("—", "<br")), celda
    assert _visible(celda).startswith("Anulada tras imprimir"), _visible(celda)


def test_columna_constancia_en_constancia_previa_no_emite_folio(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("150.00"))
    proc = make_process(make_student(control_number="99600213"), cohort=cohort,
                        current_phase=1, library_clearance="pending")
    clearance = _clearance(db_session, proc)
    fecha = (date.today() - timedelta(days=30)).isoformat()

    resp_post = client_as(staff).post(
        f"{URL}/{clearance.id}/previa",
        data={"status": "pending", "q": "", "page": "1", "issued_on": fecha})
    assert resp_post.status_code == 200, resp_post.text[:500]

    resp = client_as(staff).get(f"{URL}/body?status=cleared&q=99600213")

    assert resp.status_code == 200, resp.text[:500]
    fila = _fila(resp.text, f'id="lib-{clearance.id}"')
    assert "Constancia previa (papel del egresado)" in fila
    assert "BIB-" not in fila


def test_columna_constancia_en_legado_no_muestra_nada(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600214"), cohort=cohort,
                        current_phase=1, library_clearance="cleared")
    clearance = _clearance(db_session, proc)
    assert clearance.cleared_via == "legacy"

    resp = client_as(staff).get(f"{URL}/body?status=cleared&q=99600214")

    assert resp.status_code == 200, resp.text[:500]
    fila = _fila(resp.text, f'id="lib-{clearance.id}"')
    assert "BIB-" not in fila
    assert "Impresa" not in fila
    assert "Sin imprimir" not in fila
    assert "Anulada tras imprimir" not in fila


def test_columna_constancia_revocada_conserva_la_celda_impresa_sin_acciones(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    """Review Focus #5: con el proceso `cancelled` una constancia YA impresa
    sigue diciendo «Impresa» -el papel existe; Ruling R13 solo cambia la
    vigente SIN lote, prueba de abajo- y la fila sigue sin acciones."""
    from itcj2.apps.titulatec.services.certificate_service import CertificateService
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600215"), cohort=cohort,
                        current_phase=1, library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("0"))
    CertificateService.create_batch(db_session, kind="library_clearance", actor_id=staff.id)
    proc.status = "cancelled"          # se revocó DESPUÉS de liberarse e imprimirse
    db_session.flush()

    resp = client_as(staff).get(f"{URL}/body?status=cleared&q=99600215")

    assert resp.status_code == 200, resp.text[:500]
    fila = _fila(resp.text, f'id="lib-{clearance.id}"')
    assert "Revocada" in re.sub(r"<[^>]+>", " ", fila).split()
    assert "hx-post" not in fila
    assert "Impresa" in fila
    assert "No se imprimirá" not in fila


def test_columna_constancia_revocada_sin_imprimir_dice_que_no_se_imprimira(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    """Ruling R13 (P4 de la revisión final): la constancia VIGENTE sin lote de
    una inscripción revocada nunca entrará a un lote (`_pending_criteria`,
    Ruling R26), así que la celda dice «No se imprimirá» en una píldora
    NEUTRA, no «Sin imprimir» ámbar -la página de Constancias tampoco la
    cuenta en «Por imprimir»-. Ruling R18: el motivo, «inscripción
    revocada», va FUERA de la píldora (que no parte renglón), en una nota
    tenue que sí puede partirse. El folio se conserva. Control positivo:
    `test_columna_constancia_vigente_sin_imprimir_...` (la misma constancia
    sin revocar sigue «Sin imprimir»)."""
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600216"), cohort=cohort,
                        current_phase=1, library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("0"))
    cert = _certs(db_session, clearance.id)[0]
    proc.status = "cancelled"          # se revocó con la constancia todavía sin imprimir
    db_session.flush()

    resp = client_as(staff).get(f"{URL}/body?status=cleared&q=99600216")

    assert resp.status_code == 200, resp.text[:500]
    celda = _celda(_fila(resp.text, f'id="lib-{clearance.id}"'), cert.number)
    pildora = re.search(r'<span class="tt-pill tt-pill--neutral">(.*?)</span>', celda, re.S)
    assert pildora and _visible(pildora.group(1)) == "No se imprimirá", celda
    assert '<span class="small text-body-secondary">inscripción revocada</span>' in celda
    assert "Sin imprimir" not in celda
    assert "tt-pill--amber" not in celda


def test_columna_constancia_no_hace_una_consulta_por_fila(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    """Invariante 2 (`2026-10-02-titulatec-constancias-y-pendientes-design.md`
    §4): `print_status_map` agrega el estado de impresión de TODA la página
    en, cuando mucho, 2 consultas -- nunca una por fila. Patrón de conteo de
    `test_enrollment_inbox.py::test_la_consulta_vigente_se_carga_sin_n_mas_1`."""
    from sqlalchemy import event

    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    engine = db_session.get_bind()
    consultas = []

    def _cuenta(conn, cursor, statement, *a):
        if "titulatec_certificates" in statement or "titulatec_certificate_batches" in statement:
            consultas.append(statement)

    make_process(make_student(control_number="99600220", last_name="CONSULTAUNO"),
                cohort=cohort, current_phase=1, library_clearance="pending")
    event.listen(engine, "before_cursor_execute", _cuenta)
    try:
        resp1 = client_as(staff).get(f"{URL}/body?status=pending&q=CONSULTAUNO")
    finally:
        event.remove(engine, "before_cursor_execute", _cuenta)
    assert resp1.status_code == 200, resp1.text[:300]
    con_una_fila = len(consultas)

    for i in range(20):
        make_process(make_student(control_number=f"996003{i:02d}", last_name="CONSULTAVEINTE"),
                    cohort=cohort, current_phase=1, library_clearance="pending")
    consultas.clear()
    event.listen(engine, "before_cursor_execute", _cuenta)
    try:
        resp2 = client_as(staff).get(f"{URL}/body?status=pending&q=CONSULTAVEINTE")
    finally:
        event.remove(engine, "before_cursor_execute", _cuenta)
    assert resp2.status_code == 200, resp2.text[:300]
    con_veinte_filas = len(consultas)

    assert "CONSULTAVEINTE" in resp2.text, "control positivo: sí se sembraron las 20"
    assert con_una_fila >= 1, "la columna debe consultar el estado de impresión"
    assert con_una_fila == con_veinte_filas, (
        f"1 fila: {con_una_fila} consultas; 20 filas: {con_veinte_filas}")


# ---------------------------------------------------------------------------
# Inscripción revocada: sin acciones, en cualquier pestaña
# ---------------------------------------------------------------------------
def test_una_inscripcion_revocada_no_ofrece_acciones_y_se_etiqueta(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    staff = make_library_staff()
    cohort = make_cohort(book_donation_amount=Decimal("100.00"))
    proc = make_process(make_student(control_number="99600091"), cohort=cohort, current_phase=2,
                        status="cancelled", library_clearance="awaiting_payment")
    clearance = _clearance(db_session, proc)

    resp = client_as(staff).get(f"{URL}/body?status=awaiting_payment&q=99600091")

    assert resp.status_code == 200, resp.text[:500]
    marca = f'id="lib-{clearance.id}"'
    assert marca in resp.text
    fila = resp.text.split(marca, 1)[1].split("</tr>", 1)[0]
    assert "Revocada" in re.sub(r"<[^>]+>", " ", fila).split()
    assert "hx-post" not in fila


# ---------------------------------------------------------------------------
# Errores: 404 de existencia
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sufijo,form", [
    ("registrar", {"debt_amount": "0", "expected_status": "pending"}),
    ("previa", {"issued_on": (date.today() - timedelta(days=1)).isoformat()}),
    ("deshacer-previa", {"reason": "x"}),
    ("revertir", {"reason": "x"}),
])
def test_id_inexistente_responde_404(sufijo, form, client_as, make_library_staff):
    base = {"status": "pending", "q": "", "page": "1"}
    resp = client_as(make_library_staff()).post(
        f"{URL}/999999/{sufijo}", data={**base, **form})

    assert resp.status_code == 404, resp.text[:300]


# ---------------------------------------------------------------------------
# Un código por ruta: un permiso de más no debe abrir otra acción
# ---------------------------------------------------------------------------
def test_permiso_de_prior_no_alcanza_para_revertir(
    client_as, db_session, make_user, make_role, grant_user_role,
    make_student, make_cohort, make_process,
):
    user = make_user(first_name="SOLO", last_name="PREVIA")
    role = make_role("tt_test_solo_previa", (
        "titulatec.library_clearance.page.list",
        "titulatec.library_clearance.api.prior",
    ))
    grant_user_role(user, role)
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600101"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register(db_session, clearance.id, user.id, debt_amount=Decimal("0"))
    db_session.refresh(clearance)

    resp = client_as(user).post(
        f"{URL}/{clearance.id}/revertir",
        data={"status": "cleared", "q": "", "page": "1", "reason": "x"})

    assert resp.status_code == 403, resp.text[:300]


def test_permiso_de_list_no_alcanza_para_registrar(
    client_as, db_session, make_user, make_role, grant_user_role,
    make_student, make_cohort, make_process,
):
    user = make_user(first_name="SOLO", last_name="LECTURA")
    role = make_role("tt_test_solo_lectura_lib", ("titulatec.library_clearance.page.list",))
    grant_user_role(user, role)
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600102"), cohort=cohort, current_phase=1,
                        library_clearance="pending")
    clearance = _clearance(db_session, proc)

    resp = client_as(user).post(
        f"{URL}/{clearance.id}/registrar",
        data={"status": "pending", "q": "", "page": "1", "debt_amount": "0",
              "expected_status": "pending"})

    assert resp.status_code == 403, resp.text[:300]


# ---------------------------------------------------------------------------
# m21: el permiso EXACTO de cada ruta (sin nada de más) ya alcanza. Los
# negativos de arriba (permisos CRUZADOS, p.ej. `api.prior` contra
# `/revertir`) ya atraparían un cableado erróneo, pero nunca ejercitan el
# camino de éxito con el permiso justo de SU PROPIA ruta -un `perms=[...]`
# vacío o apuntando a una lista equivocada pasaría esos negativos igual
# (ambos dan 403) y solo lo delata un 200 que hoy nadie pedía.
# ---------------------------------------------------------------------------
def test_permiso_exacto_de_prior_basta_para_constancia_previa(
    client_as, db_session, make_user, make_role, grant_user_role,
    make_student, make_cohort, make_process,
):
    user = make_user(first_name="SOLO", last_name="PREVIAEXACTO")
    role = make_role("tt_test_solo_previa_exacto", (
        "titulatec.library_clearance.page.list",
        "titulatec.library_clearance.api.prior",
    ))
    grant_user_role(user, role)
    cohort = make_cohort(book_donation_amount=Decimal("150.00"))
    proc = make_process(make_student(control_number="99600304"), cohort=cohort,
                        current_phase=1, library_clearance="pending")
    clearance = _clearance(db_session, proc)
    fecha = (date.today() - timedelta(days=30)).isoformat()

    resp = client_as(user).post(
        f"{URL}/{clearance.id}/previa",
        data={"status": "pending", "q": "", "page": "1", "issued_on": fecha})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(clearance)
    assert clearance.status == "cleared" and clearance.cleared_via == "prior"


def test_permiso_exacto_de_prior_basta_para_deshacer_previa(
    client_as, db_session, make_user, make_role, grant_user_role,
    make_student, make_cohort, make_process,
):
    """Mismo permiso exacto que la prueba anterior (`_PRIOR` de
    `pages/library_admin.py` cubre las DOS rutas), ejercitado en SU PROPIA
    ruta -un typo que apuntara `/deshacer-previa` a otra lista no lo
    atraparía la prueba de `/previa`."""
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    user = make_user(first_name="SOLO", last_name="DESHACEREXACTO")
    role = make_role("tt_test_solo_deshacer_exacto", (
        "titulatec.library_clearance.page.list",
        "titulatec.library_clearance.api.prior",
    ))
    grant_user_role(user, role)
    cohort = make_cohort(book_donation_amount=Decimal("150.00"))
    proc = make_process(make_student(control_number="99600305"), cohort=cohort,
                        current_phase=1, library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register_prior(
        db_session, clearance.id, user.id,
        issued_on=date.today() - timedelta(days=10), by="library")
    db_session.refresh(clearance)
    assert clearance.status == "cleared" and clearance.cleared_via == "prior"

    resp = client_as(user).post(
        f"{URL}/{clearance.id}/deshacer-previa",
        data={"status": "cleared", "q": "", "page": "1", "reason": "fecha mal capturada"})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(clearance)
    assert clearance.status == "pending"


def test_permiso_exacto_de_revert_basta_para_revertir(
    client_as, db_session, make_user, make_role, grant_user_role,
    make_student, make_cohort, make_process,
):
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    user = make_user(first_name="SOLO", last_name="REVERTEXACTO")
    role = make_role("tt_test_solo_revert_exacto", (
        "titulatec.library_clearance.page.list",
        "titulatec.library_clearance.api.revert",
    ))
    grant_user_role(user, role)
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    proc = make_process(make_student(control_number="99600306"), cohort=cohort,
                        current_phase=1, library_clearance="pending")
    clearance = _clearance(db_session, proc)
    LibraryClearanceService.register(db_session, clearance.id, user.id, debt_amount=Decimal("0"))
    db_session.refresh(clearance)
    assert clearance.status == "cleared" and clearance.cleared_via == "no_charge"

    resp = client_as(user).post(
        f"{URL}/{clearance.id}/revertir",
        data={"status": "cleared", "q": "", "page": "1", "reason": "me equivoqué"})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(clearance)
    assert clearance.status == "pending"


# ---------------------------------------------------------------------------
# Estructural: sin `{process_id}` en ninguna ruta de esta bandeja (§5 inv. 6)
# ---------------------------------------------------------------------------
def test_ninguna_ruta_lleva_process_id():
    from itcj2.apps.titulatec.pages.library_admin import router

    paths = [getattr(r, "path", "") for r in router.routes]
    assert paths, "el router de biblioteca no tiene rutas"
    assert not any("{process_id}" in p for p in paths), paths


# ---------------------------------------------------------------------------
# Pager compartido: «1–N de T»
# ---------------------------------------------------------------------------
def test_biblioteca_muestra_rango_de_total(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
    monkeypatch,
):
    import functools
    from itcj2.apps.titulatec.pages import library_admin

    monkeypatch.setattr(library_admin, "_body_ctx",
                        functools.partial(library_admin._body_ctx, per_page=2))
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    for _ in range(3):
        make_process(make_student(last_name="PAGBIBZQ"), cohort=cohort, current_phase=1,
                     library_clearance="pending")
    c = client_as(make_library_staff())

    p1 = c.get(f"{URL}/body?status=pending&q=PAGBIBZQ").text
    p2 = c.get(f"{URL}/body?status=pending&q=PAGBIBZQ&page=2").text

    assert "1–2 de 3" in p1
    assert "3–3 de 3" in p2
    prev = re.search(r'<button[^>]*id="tt-biblioteca-pager-prev"[^>]*>', p2, re.S).group(0)
    assert "status=pending" in prev and "q=PAGBIBZQ" in prev and '"page": 1' in prev


def test_buscador_preservado_y_q_viaja(
    client_as, db_session, make_library_staff, make_student, make_cohort, make_process,
):
    """hx-preserve en el buscador: id estable, q sigue viajando."""
    from tests.fastapi.titulatec.paging_asserts import assert_buscador_preservado
    cohort = make_cohort(book_donation_amount=Decimal("0.00"))
    make_process(make_student(control_number="99600091"), cohort=cohort, current_phase=1,
                library_clearance="pending")
    c = client_as(make_library_staff())
    for url in (URL, f"{URL}/body"):
        html = c.get(url, params={"status": "pending", "q": "99600091"}).text
        assert_buscador_preservado(html, input_id="tt-library-q",
                                   filters_id="tt-library-filters", q="99600091",
                                   include="closest form")
        tab = re.search(r'<button id="tt-lib-tab-[a-z_]+"[^>]*q=99600091[^>]*>', html)
        assert tab, "las pestañas deben arrastrar q"
