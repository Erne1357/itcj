"""Caja: orden de columnas y tarjetas en pantallas chicas (spec
`docs/superpowers/specs/2026-10-15-titulatec-reemplazo-cotejo-design.md` §11).

Lo que fija este archivo (sin navegador; el comportamiento visual se midió en
Chromium y está documentado en `static/css/admin/cashier.css`):

- C1. La Carrera va AL FINAL del renglón, tras la acción, en las dos tablas:
  búsqueda/«Por cobrar» = Egresado · Control · Estado · Monto · acción ·
  Carrera; «Corte del día» = el orden de siempre con la Carrera al final.
- C2. Cada celda lleva su clase `tt-cash-*` (su lugar en la tarjeta) y, la
  que tiene encabezado, un `data-label` IGUAL a ese encabezado: la tarjeta no
  inventa textos.
- La hoja `css/admin/cashier.css` se carga UNA vez desde `base_admin.html` (la
  navegación admin solo morphea `#tt-admin-content`), nunca desde el parcial;
  el parcial no trae `style=` ni `<script>`.
- La hoja tiene sus comentarios bien cerrados (el gotcha de `*/` pegado a un
  token rompe la regla siguiente sin avisar) y sus dos consultas de
  contenedor sobre `#tt-cashier-body`.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import lxml.html
import pytest

URL = "/titulatec/admin/caja"
APP = Path(__file__).resolve().parents[3] / "itcj2" / "apps" / "titulatec"
PARCIAL = APP / "templates" / "titulatec" / "admin" / "partials" / "cashier_body.html"
CSS = APP / "static" / "css" / "admin" / "cashier.css"
CSS_HREF = "/static/titulatec/css/admin/cashier.css?v="

SVC_DB_NOW = "itcj2.apps.titulatec.services.library_clearance_service.db_now"

CASHIER_PERMS = (
    "titulatec.library_payment.page.list",
    "titulatec.library_payment.api.register",
    "titulatec.library_payment.api.revert",
)

ORDEN_FILAS = ["Egresado", "Control", "Estado", "Monto", "", "Carrera"]
CLASES_FILAS = ["tt-cash-student", "tt-cash-control", "tt-cash-status",
                "tt-cash-amount", "tt-cash-action", "tt-cash-program"]
ORDEN_CORTE = ["Hora", "Egresado", "Control", "Movimiento", "Monto", "Recibo", "Quién",
               "Motivo", "Cobro original", "", "Carrera"]
CLASES_CORTE = ["tt-cash-time", "tt-cash-student", "tt-cash-control", "tt-cash-status",
                "tt-cash-amount", "tt-cash-receipt", "tt-cash-actor", "tt-cash-reason",
                "tt-cash-original", "tt-cash-action", "tt-cash-program"]


@pytest.fixture()
def cajera(make_user, make_role, grant_user_role):
    """Actor sintético de Caja: rol DIRECTO con los permisos de la bandeja."""
    user = make_user(first_name="CAJA", last_name="DISEÑO")
    grant_user_role(user, make_role("tt_test_cashier_layout", CASHIER_PERMS))
    return user


def _por_cobrar(db_session, staff, make_student, make_cohort, make_process):
    """Un egresado «Por cobrar» ($100 de adeudo + $50 de donación)."""
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    cohort = make_cohort(book_donation_amount=Decimal("50.00"))
    student = make_student(first_name="EGRESADA", last_name="ORDENCAJA")
    proc = make_process(student, cohort=cohort, current_phase=1, library_clearance="pending")
    clearance = LibraryClearanceService.get_for_process(db_session, proc.id)
    LibraryClearanceService.register(db_session, clearance.id, staff.id, debt_amount=Decimal("100"))
    db_session.refresh(clearance)
    assert clearance.status == "awaiting_payment"
    return student, proc, clearance


def _tabla(html, table_id):
    doc = lxml.html.fromstring(html)
    (tabla,) = doc.xpath(f'//table[@id="{table_id}"]')
    return tabla


def _encabezados(tabla):
    return [th.text_content().strip() for th in tabla.xpath("./thead/tr/th")]


def _celdas(tabla, tr_id):
    (tr,) = tabla.xpath(f'./tbody/tr[@id="{tr_id}"]')
    return tr.xpath("./td")


def _clase_cash(td):
    """La clase que dice el LUGAR de la celda en la tarjeta (`tt-cash-meta`
    solo agrupa los datos secundarios del corte)."""
    return next(c for c in td.get("class", "").split()
                if c.startswith("tt-cash-") and c != "tt-cash-meta")


def _assert_data_labels(encabezados, celdas):
    """Cada td con encabezado lleva `data-label` == ese encabezado; la acción
    (encabezado vacío) no lleva etiqueta."""
    for th, td in zip(encabezados, celdas):
        if th:
            assert td.get("data-label") == th, (th, td.get("data-label"))
        else:
            assert td.get("data-label") is None, td.get("data-label")


# ---------------------------------------------------------------------------
# C1 + C2: orden de columnas, clases y data-label
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ruta", [URL, f"{URL}/body"])
def test_busqueda_carrera_al_final_tras_la_accion(
    ruta, client_as, db_session, cajera, make_student, make_cohort, make_process,
):
    student, _proc, clearance = _por_cobrar(
        db_session, cajera, make_student, make_cohort, make_process)

    # Búsqueda por control: sin paginar, la fila sale aunque «Por cobrar»
    # tenga cientos de casos reales en la BD de dev.
    resp = client_as(cajera).get(ruta, params={"q": student.control_number})

    assert resp.status_code == 200, resp.text[:500]
    tabla = _tabla(resp.text, "tt-cashier-table")
    encabezados = _encabezados(tabla)
    assert encabezados == ORDEN_FILAS
    celdas = _celdas(tabla, f"caja-{clearance.id}")
    assert [_clase_cash(td) for td in celdas] == CLASES_FILAS
    _assert_data_labels(encabezados, celdas)
    # Contenido en su columna: estado, monto, acción y carrera.
    assert "Por cobrar $150.00" in celdas[2].text_content()
    assert "$150.00" in celdas[3].text_content()
    assert celdas[4].xpath(f'.//form[@hx-post="/titulatec/admin/caja/{clearance.id}/pagar"]')
    assert not celdas[5].xpath(".//form|.//button"), "la Carrera no trae acciones"


def test_por_cobrar_usa_el_mismo_orden(
    client_as, db_session, cajera, make_student, make_cohort, make_process,
):
    """La pestaña «Por cobrar» (sin buscar) pinta la MISMA tabla."""
    _por_cobrar(db_session, cajera, make_student, make_cohort, make_process)

    resp = client_as(cajera).get(f"{URL}/body", params={"tab": "por_cobrar"})

    assert resp.status_code == 200, resp.text[:500]
    tabla = _tabla(resp.text, "tt-cashier-table")
    assert _encabezados(tabla) == ORDEN_FILAS
    for tr in tabla.xpath("./tbody/tr"):
        assert [_clase_cash(td) for td in tr.xpath("./td")] == CLASES_FILAS, tr.get("id")


def test_corte_del_dia_carrera_al_final_tras_la_accion(
    client_as, db_session, cajera, make_student, make_cohort, make_process, monkeypatch,
):
    """El corte lee `ProcessEvent.created_at`: se fija a mano en un día
    sintético de 2031 que ninguna otra prueba usa (patrón de
    `test_cashier_inbox.py::test_pagados_corte_del_dia_respeta_el_selector_y_total`)."""
    from itcj2.apps.titulatec.models import ProcessEvent
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    _student, proc, clearance = _por_cobrar(
        db_session, cajera, make_student, make_cohort, make_process)
    cuando = datetime(2031, 5, 13, 10, 30, 0)
    monkeypatch.setattr(SVC_DB_NOW, lambda: cuando)
    LibraryClearanceService.register_payment(db_session, clearance.id, cajera.id,
                                             receipt_number="R-ORDEN")
    evento = (db_session.query(ProcessEvent)
              .filter_by(event_type="library_payment_registered", process_id=proc.id)
              .order_by(ProcessEvent.id.desc()).first())
    evento.created_at = cuando
    db_session.flush()

    resp = client_as(cajera).get(f"{URL}/body", params={"tab": "pagados", "dia": "2031-05-13"})

    assert resp.status_code == 200, resp.text[:500]
    tabla = _tabla(resp.text, "tt-cashier-cut")
    encabezados = _encabezados(tabla)
    assert encabezados == ORDEN_CORTE
    celdas = _celdas(tabla, f"caja-mov-{evento.id}")
    assert [_clase_cash(td) for td in celdas] == CLASES_CORTE
    _assert_data_labels(encabezados, celdas)
    assert celdas[0].text_content().strip() == "10:30"
    assert "Cobro" in celdas[3].text_content()
    assert celdas[4].text_content().strip() == "$150.00"
    assert celdas[5].text_content().strip() == "R-ORDEN"
    assert celdas[9].xpath(
        f'.//form[@hx-post="/titulatec/admin/caja/{clearance.id}/revertir"]')
    assert not celdas[10].xpath(".//form|.//button")


# ---------------------------------------------------------------------------
# Estáticos: la hoja se carga una vez desde la base; el parcial, limpio
# ---------------------------------------------------------------------------
def test_pagina_completa_carga_cashier_css_una_vez_y_el_parcial_no(client_as, cajera):
    c = client_as(cajera)

    pagina = c.get(URL)
    parcial = c.get(f"{URL}/body")

    assert pagina.status_code == 200 and parcial.status_code == 200
    assert pagina.text.count(CSS_HREF) == 1
    m = re.search(r'<link rel="stylesheet" href="%s([^"]+)">' % re.escape(CSS_HREF), pagina.text)
    assert m and m.group(1), "falta el ?v= de sv() en el <link> de cashier.css"
    assert "cashier.css" not in parcial.text


def test_la_hoja_se_carga_desde_base_admin_y_no_desde_la_pagina():
    base = (APP / "templates" / "titulatec" / "admin" / "base_admin.html").read_text(encoding="utf-8")
    pagina = (APP / "templates" / "titulatec" / "admin" / "cashier.html").read_text(encoding="utf-8")

    assert "sv('css/admin/cashier.css')" in base
    assert "cashier.css" not in pagina


def test_el_parcial_no_trae_style_ni_script_inline():
    fuente = PARCIAL.read_text(encoding="utf-8")
    sin_comentarios = re.sub(r"\{#.*?#\}", "", fuente, flags=re.S)

    assert "<script" not in sin_comentarios
    assert re.search(r"\sstyle=", sin_comentarios) is None


# ---------------------------------------------------------------------------
# La hoja: comentarios cerrados y consultas de contenedor
# ---------------------------------------------------------------------------
def test_cashier_css_comentarios_bien_cerrados_y_llaves_balanceadas():
    css = CSS.read_text(encoding="utf-8")
    sin_comentarios = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    # Un `*/` de más (p. ej. una ruta con comodín dentro del comentario)
    # deja texto suelto que el navegador traga junto con la regla siguiente.
    assert "*/" not in sin_comentarios and "/*" not in sin_comentarios
    assert sin_comentarios.count("{") == sin_comentarios.count("}")


def test_cashier_css_tarjetas_por_consulta_de_contenedor():
    css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)

    assert re.search(r"#tt-cashier-body\s*\{\s*container:\s*tt-cashier\s*/\s*inline-size;", css)
    bloques = re.findall(r"@container tt-cashier \(max-width: [\d.]+px\)\s*\{", css)
    assert bloques, "las tarjetas deben colgar de una consulta de contenedor"
    for tabla in ("tt-cash-table--rows", "tt-cash-table--cut"):
        assert re.search(r"\.%s > thead \{ display: none; \}" % tabla, css), tabla
    # La Carrera (última columna) ya no se ancla como si fuera la acción.
    assert re.search(r"td:last-child \{ position: static; \}", css)
    # Sin @media: el umbral depende del ancho de la bandeja, no del viewport.
    assert "@media" not in css
