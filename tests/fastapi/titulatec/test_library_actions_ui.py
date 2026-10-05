"""Bandeja de Biblioteca, pestaña «Por revisar»: acciones de fila en un panel
bajo la fila (spec `docs/superpowers/specs/2026-10-05-titulatec-biblioteca-
acciones-design.md` §3.1-§3.3, Tarea 1).

En la celda de acciones quedan DOS controles («Sin adeudo» y el despliegue
«Dictaminar…»); el resto vive en una segunda `<tr id="lib-{id}-panel">`
oculta (`d-none`) que abre el `data-tt-toggle` global. Dentro, tarjetas de
resultado con rótulo + qué pasa, y un `<form>` por opción con los MISMOS
endpoints, ocultos y confirmaciones de antes. Aquí solo el HTML; las rutas
las cubren `test_library_inbox.py` y `test_library_observations_routes.py`.

DATOS. BD de dev COMPARTIDA: cada prueba aísla sus filas con un token único en
el apellido (`q`).
"""
from __future__ import annotations

import html as html_lib
import re
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

LIB = "/titulatec/admin/biblioteca"
PARTIAL = (Path(__file__).resolve().parents[3] / "itcj2" / "apps" / "titulatec" / "templates"
           / "titulatec" / "admin" / "partials" / "library_body.html")

LIBRARY_PERMS = (
    "titulatec.library_clearance.page.list",
    "titulatec.library_clearance.api.register",
    "titulatec.library_clearance.api.prior",
    "titulatec.library_clearance.api.revert",
)

EXPLICA = {
    "debt": ("Con adeudo", "Pasa a Caja a pagar el adeudo más la donación."),
    "prior": ("Constancia previa",
              "Ya pagó antes y trae su constancia: queda liberado sin pasar por Caja."),
    "observe": ("Observar", "Lo detiene hasta que Biblioteca lo rehabilite; no podrá agendar."),
}


@pytest.fixture()
def staff(make_user, make_role, grant_user_role):
    user = make_user(first_name="BIBLIOTECA", last_name="PANEL")
    grant_user_role(user, make_role("tt_test_library_panel", LIBRARY_PERMS))
    return user


@pytest.fixture()
def token():
    return "PNL" + uuid.uuid4().hex[:10].upper()


@pytest.fixture()
def nuevo(make_student, make_process, make_cohort, make_library_clearance):
    def _build(last_name):
        cohort = make_cohort(book_donation_amount=Decimal("800.00"))
        student = make_student(last_name=last_name)
        process = make_process(student, cohort=cohort, current_phase=1, library_clearance=None)
        clearance = make_library_clearance(process, status="pending")
        return SimpleNamespace(student=student, clearance=clearance)

    return _build


def _body(client_as, staff, token):
    resp = client_as(staff).get(f"{LIB}/body", params={"status": "pending", "q": token})
    assert resp.status_code == 200, resp.text[:500]
    return resp.text


def _tr(html, tr_id):
    """La `<tr>` con ese id, completa (de su `<tr` a su `</tr>`)."""
    m = re.search(r'<tr id="%s"[^>]*>.*?</tr>' % re.escape(tr_id), html, re.S)
    assert m, f"falta <tr id={tr_id}>"
    return m.group(0)


def _ultima_celda(fila):
    celdas = re.findall(r"<td[^>]*>(.*?)</td>", fila, re.S)
    return celdas[-1]


def _visible(fragmento):
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", fragmento)).split())


def test_por_revisar_fila_tiene_dos_controles(client_as, staff, nuevo, token):
    esc = nuevo(token)
    fila = _tr(_body(client_as, staff, token), f"lib-{esc.clearance.id}")
    celda = _ultima_celda(fila)

    botones = re.findall(r"<button[^>]*>(.*?)</button>", celda, re.S)
    assert [_visible(b) for b in botones] == ["Sin adeudo", "Dictaminar…"]
    # En la fila ya no hay campos tecleables: todo eso vive en el panel.
    assert "<textarea" not in celda and 'type="date"' not in celda
    assert 'name="debt_amount" required' not in celda


def test_panel_oculto_con_toggle_accesible(client_as, staff, nuevo, token):
    esc = nuevo(token)
    i = esc.clearance.id
    html = _body(client_as, staff, token)
    panel = _tr(html, f"lib-{i}-panel")

    assert re.match(r'<tr id="lib-%d-panel" class="[^"]*\bd-none\b' % i, panel)
    celda = _ultima_celda(_tr(html, f"lib-{i}"))
    toggle = re.search(r'<button[^>]*data-tt-toggle="lib-%d-panel"[^>]*>' % i, celda)
    assert toggle, "falta el despliegue"
    assert f'aria-controls="lib-{i}-panel"' in toggle.group(0)
    assert 'aria-expanded="false"' in toggle.group(0)
    assert 'type="button"' in toggle.group(0)
    # El panel va INMEDIATAMENTE debajo de su fila.
    assert html.index(f'<tr id="lib-{i}-panel"') > html.index(f'<tr id="lib-{i}"')
    entre = html.split(f'<tr id="lib-{i}"', 1)[1].split(f'<tr id="lib-{i}-panel"', 1)[0]
    assert entre.count("<tr") == 0


def test_panel_colspan_igual_a_columnas(client_as, staff, nuevo, token):
    esc = nuevo(token)
    html = _body(client_as, staff, token)
    thead = re.search(r"<thead>(.*?)</thead>", html, re.S).group(1)
    n = len(re.findall(r"<th\b", thead))
    panel = _tr(html, f"lib-{esc.clearance.id}-panel")

    tds = re.findall(r"<td\b[^>]*>", panel)
    assert len(tds) == 1
    assert f'colspan="{n}"' in tds[0]
    assert n == 10, "casilla de lote + 9 columnas en «Por revisar»"


def test_tres_opciones_con_rotulo_y_explicacion(client_as, staff, nuevo, token):
    esc = nuevo(token)
    i = esc.clearance.id
    panel = _tr(_body(client_as, staff, token), f"lib-{i}-panel")

    fs = re.search(r"<fieldset[^>]*>(.*?)</fieldset>", panel, re.S)
    assert fs, "el selector es un fieldset"
    assert "<legend" in fs.group(1)
    assert esc.student.last_name in _visible(re.search(r"<legend.*?</legend>", fs.group(1),
                                                       re.S).group(0))
    opciones = re.findall(r'<label class="tt-vis-opt" for="lib-%d-opt-(\w+)">(.*?)</label>' % i,
                          fs.group(1), re.S)
    assert [k for k, _ in opciones] == ["debt", "prior", "observe"]
    for key, cuerpo in opciones:
        rotulo, explica = EXPLICA[key]
        assert re.search(r'<span class="rotulo[^"]*">%s</span>' % re.escape(rotulo), cuerpo)
        assert explica in _visible(re.search(r'<span class="derivada[^"]*">.*?</span>',
                                             cuerpo, re.S).group(0))
        radio = re.search(r"<input[^>]*>", cuerpo).group(0)
        assert 'type="radio"' in radio and f'id="lib-{i}-opt-{key}"' in radio
        assert f'value="{key}"' in radio
        assert "checked" not in radio, "ninguna opción preseleccionada"
    assert "Elige un resultado" in _visible(panel)
    assert "—" not in _visible(panel), "sin guion largo en el panel"


def _form(panel, i, key):
    m = re.search(r'<form id="lib-%d-form-%s"[^>]*>.*?</form>' % (i, key), panel, re.S)
    assert m, f"falta el formulario {key}"
    return m.group(0)


def test_formularios_conservan_endpoints_y_confirm(client_as, staff, nuevo, token):
    esc = nuevo(token)
    i = esc.clearance.id
    nombre = esc.student.last_name
    html = _body(client_as, staff, token)
    panel = _tr(html, f"lib-{i}-panel")

    esperado = {
        "debt": ("registrar", "Registrar", "Con adeudo|¿Registrar este adeudo para",
                 "Registrar adeudo", True),
        "prior": ("previa", "Registrar", "Constancia previa|¿Registrar que",
                  "Registrar constancia previa", False),
        "observe": ("observar", "Observar", "Observar|¿Registrar observaciones a",
                    "Observar", False),
    }
    for key, (accion, ok, confirm, boton, expected) in esperado.items():
        f = _form(panel, i, key)
        abre = re.match(r"<form[^>]*>", f).group(0)
        assert f'class="tt-lib-form tt-lib-form--{key}"' in abre
        assert f'hx-post="/titulatec/admin/biblioteca/{i}/{accion}"' in abre
        assert 'hx-target="#tt-library-body"' in abre and 'hx-swap="outerHTML"' in abre
        assert f'data-tt-confirm-ok="{ok}"' in abre
        conf = html_lib.unescape(re.search(r'hx-confirm="([^"]*)"', abre).group(1))
        assert conf.startswith(confirm) and nombre in conf
        assert 'name="status" value="pending"' in f
        assert f'name="q" value="{token}"' in f and 'name="page" value="1"' in f
        assert ('name="expected_status" value="pending"' in f) is expected
        assert _visible(re.search(r'<button type="submit"[^>]*>.*?</button>', f, re.S)
                        .group(0)) == boton
    # «Sin adeudo» de la fila: intacto.
    celda = _ultima_celda(_tr(html, f"lib-{i}"))
    sin = re.search(r"<form[^>]*>.*?</form>", celda, re.S).group(0)
    assert f'hx-post="/titulatec/admin/biblioteca/{i}/registrar"' in sin
    assert 'data-tt-confirm-ok="Sin adeudo"' in sin and 'hx-confirm="Sin adeudo|' in sin
    assert 'name="debt_amount" value="0"' in sin
    assert 'name="expected_status" value="pending"' in sin


def test_campos_con_label_visible(client_as, staff, nuevo, token):
    esc = nuevo(token)
    i = esc.clearance.id
    panel = _tr(_body(client_as, staff, token), f"lib-{i}-panel")
    campos = re.findall(r"<(?:input|textarea)\b(?![^>]*type=\"(?:hidden|radio)\")[^>]*>", panel)

    assert len(campos) == 5, campos  # monto+nota, fecha+nota, motivo
    for c in campos:
        cid = re.search(r'id="([^"]+)"', c)
        assert cid, f"campo sin id: {c}"
        lab = re.search(r'<label class="tt-label" for="%s">(.*?)</label>'
                        % re.escape(cid.group(1)), panel, re.S)
        assert lab and _visible(lab.group(1)), f"sin <label for> visible: {c}"
    for nombre in ("debt_amount", "issued_on", "reason"):
        assert re.search(r'name="%s"[^>]*required' % nombre, panel), nombre


def test_sin_style_inline_en_el_partial():
    assert "style=" not in PARTIAL.read_text(encoding="utf-8")


def test_radios_por_fila(client_as, staff, nuevo, token):
    a = nuevo(token)
    b = nuevo(token)
    html = _body(client_as, staff, token)

    for esc in (a, b):
        i = esc.clearance.id
        panel = _tr(html, f"lib-{i}-panel")
        radios = re.findall(r'<input[^>]*type="radio"[^>]*>', panel)
        assert len(radios) == 3
        assert all(f'name="lib-{i}-op"' in r for r in radios)
        # Fuera de cualquier <form>: el selector no viaja en el POST.
        fs = re.search(r"<fieldset.*?</fieldset>", panel, re.S).group(0)
        assert "<form" not in fs
