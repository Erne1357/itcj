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
    assert "Elige una opción" in _visible(panel)
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
                    "Registrar observación", False),
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


# ---------------------------------------------------------------------------
# Tarea 2: «En caja», «Con observaciones» y «Liberados»
# ---------------------------------------------------------------------------
@pytest.fixture()
def nuevo_en(make_student, make_process, make_cohort, make_library_clearance):
    def _build(last_name, status, phase=1, **cols):
        cohort = make_cohort(book_donation_amount=Decimal("800.00"))
        student = make_student(last_name=last_name)
        process = make_process(student, cohort=cohort, current_phase=phase, library_clearance=None)
        if status in ("awaiting_payment", "observed") and "total_amount" not in cols:
            cols = {"debt_amount": Decimal("120.00"), "donation_amount": Decimal("800.00"),
                    "total_amount": Decimal("920.00"), **cols}
        clearance = make_library_clearance(process, status=status, **cols)
        return SimpleNamespace(student=student, clearance=clearance, process=process)

    return _build


def _body_tab(client_as, staff, token, tab):
    resp = client_as(staff).get(f"{LIB}/body", params={"status": tab, "q": token})
    assert resp.status_code == 200, resp.text[:500]
    return resp.text


def _toggle(celda):
    return re.search(r'<button[^>]*data-tt-toggle=[^>]*>.*?</button>', celda, re.S)


def test_aria_label_del_toggle_nombra_al_egresado(client_as, staff, nuevo, token):
    esc = nuevo(token)
    celda = _ultima_celda(_tr(_body(client_as, staff, token), f"lib-{esc.clearance.id}"))
    abre = re.search(r"<button[^>]*data-tt-toggle[^>]*>", celda).group(0)
    label = html_lib.unescape(re.search(r'aria-label="([^"]*)"', abre).group(1))
    assert label.startswith("Dictaminar a ") and esc.student.last_name in label


def test_observar_boton_dice_registrar_observacion(client_as, staff, nuevo, token):
    esc = nuevo(token)
    i = esc.clearance.id
    panel = _tr(_body(client_as, staff, token), f"lib-{i}-panel")
    boton = re.search(r'<button type="submit"[^>]*>.*?</button>', _form(panel, i, "observe"), re.S)
    assert _visible(boton.group(0)) == "Registrar observación"


def test_en_caja_sin_accion_rapida_y_dos_opciones(client_as, staff, nuevo_en, token):
    esc = nuevo_en(token, "awaiting_payment")
    i = esc.clearance.id
    html = _body_tab(client_as, staff, token, "awaiting_payment")
    celda = _ultima_celda(_tr(html, f"lib-{i}"))

    botones = re.findall(r"<button[^>]*>(.*?)</button>", celda, re.S)
    assert [_visible(b) for b in botones] == ["Opciones…"]
    assert "<form" not in celda and "<textarea" not in celda

    panel = _tr(html, f"lib-{i}-panel")
    assert 'colspan="9"' in panel and "d-none" in panel
    opciones = re.findall(r'<label class="tt-vis-opt" for="lib-%d-opt-(\w+)">(.*?)</label>' % i,
                          panel, re.S)
    assert [k for k, _ in opciones] == ["fix", "observe"]
    assert "Corregir monto" in _visible(opciones[0][1])
    assert "Cambia el adeudo; se vuelve a calcular el total con la donación vigente." \
        in _visible(opciones[0][1])
    assert "Sale de Por cobrar" in _visible(opciones[1][1])

    fix = _form(panel, i, "fix")
    abre = re.match(r"<form[^>]*>", fix).group(0)
    assert f'hx-post="/titulatec/admin/biblioteca/{i}/registrar"' in abre
    assert 'data-tt-confirm-ok="Corregir"' in abre and 'hx-confirm="Corregir monto|' in abre
    assert 'name="expected_status" value="awaiting_payment"' in fix
    assert 'name="expected_total" value="920.00"' in fix
    assert re.search(r'name="debt_amount"[^>]*required[^>]*value="120.00"', fix)
    assert re.search(r'name="note"', fix)
    assert _visible(re.search(r"<button type=\"submit\".*?</button>", fix, re.S).group(0)) \
        == "Corregir monto"

    obs = _form(panel, i, "observe")
    assert f'hx-post="/titulatec/admin/biblioteca/{i}/observar"' in obs
    assert 'data-tt-confirm-ok="Observar"' in obs
    assert re.search(r'name="reason"[^>]*required', obs)
    assert _visible(re.search(r"<button type=\"submit\".*?</button>", obs, re.S).group(0)) \
        == "Registrar observación"
    assert "style=" not in panel and "<fieldset" in panel


def test_observadas_rehabilitar_visible_y_actualizar_en_panel(client_as, staff, nuevo_en, token):
    motivo = 'Debe <b>"libro"</b> & más'
    esc = nuevo_en(token, "observed", observation_reason=motivo)
    i = esc.clearance.id
    html = _body_tab(client_as, staff, token, "observed")
    celda = _ultima_celda(_tr(html, f"lib-{i}"))

    botones = re.findall(r"<button[^>]*>(.*?)</button>", celda, re.S)
    assert [_visible(b) for b in botones] == ["Rehabilitar", "Actualizar…"]
    assert f'hx-post="/titulatec/admin/biblioteca/{i}/rehabilitar"' in celda
    assert 'hx-confirm="Rehabilitar|' in celda

    panel = _tr(html, f"lib-{i}-panel")
    assert 'colspan="9"' in panel and "d-none" in panel
    assert "<fieldset" not in panel and "tt-lib-pick" not in panel, "opción única: sin selector"
    upd = _form(panel, i, "update")
    assert f'hx-post="/titulatec/admin/biblioteca/{i}/observar"' in upd
    assert 'data-tt-confirm-ok="Actualizar"' in upd
    assert 'hx-confirm="Actualizar observación|' in upd
    ta = re.search(r"<textarea[^>]*>(.*?)</textarea>", upd, re.S)
    assert html_lib.unescape(ta.group(1)) == motivo
    assert "<b>" not in ta.group(1)
    assert re.search(r'<label class="tt-label" for="lib-%d-update-reason">' % i, upd)
    assert _visible(re.search(r"<button type=\"submit\".*?</button>", upd, re.S).group(0)) \
        == "Actualizar observación"


def test_liberados_revertir_o_deshacer_en_panel(client_as, staff, nuevo_en, token):
    sin = nuevo_en(token, "cleared", cleared_via="no_charge")
    previa = nuevo_en(token, "cleared", cleared_via="prior", prior_issued_on=None)
    html = _body_tab(client_as, staff, token, "cleared")

    casos = ((sin, "revert", "revertir", "Revertir", "Vuelve a Por revisar; se anula la constancia, si la hay."),
             (previa, "undo", "deshacer-previa", "Deshacer", "Vuelve a Por revisar."))
    for esc, key, accion, ok, explica in casos:
        i = esc.clearance.id
        celda = _ultima_celda(_tr(html, f"lib-{i}"))
        assert [_visible(b) for b in re.findall(r"<button[^>]*>(.*?)</button>", celda, re.S)] \
            == ["Opciones…"]
        panel = _tr(html, f"lib-{i}-panel")
        assert 'colspan="9"' in panel and "<fieldset" not in panel
        f = _form(panel, i, key)
        abre = re.match(r"<form[^>]*>", f).group(0)
        assert f'hx-post="/titulatec/admin/biblioteca/{i}/{accion}"' in abre
        assert f'data-tt-confirm-ok="{ok}"' in abre
        assert re.search(r'name="reason"[^>]*required', f)
        assert re.search(r'<label class="tt-label" for="lib-%d-%s-reason">' % (i, key), f)
        assert explica in _visible(panel)


def test_liberados_sin_accion_no_muestra_despliegue(client_as, staff, nuevo_en, token):
    pago = nuevo_en(token, "cleared", cleared_via="payment")
    fase2 = nuevo_en(token, "cleared", cleared_via="no_charge", phase=3)
    html = _body_tab(client_as, staff, token, "cleared")

    for esc, texto in ((pago, "Se revierte desde Caja"), (fase2, "Fase 2 liberada")):
        i = esc.clearance.id
        celda = _ultima_celda(_tr(html, f"lib-{i}"))
        assert texto in _visible(celda)
        assert "<button" not in celda and "data-tt-toggle" not in celda
        assert f'id="lib-{i}-panel"' not in html


@pytest.mark.parametrize("tab,kw", [
    ("pending", {}),
    ("awaiting_payment", {}),
    ("observed", {}),
    ("cleared", {"cleared_via": "no_charge"}),
])
def test_revocada_sin_botones(client_as, staff, nuevo_en, token, db_session, tab, kw):
    esc = nuevo_en(token, tab, **kw)
    esc.process.status = "cancelled"
    db_session.flush()
    html = _body_tab(client_as, staff, token, tab)
    i = esc.clearance.id
    if tab in ("pending", "observed"):
        # El servicio no lista revocados en las pestañas de trabajo: no hay
        # fila, luego tampoco despliegue ni panel.
        assert f'id="lib-{i}"' not in html
        assert f'id="lib-{i}-panel"' not in html and "data-tt-toggle" not in html
        return
    celda = _ultima_celda(_tr(html, f"lib-{i}"))
    assert "Revocada" in _visible(celda)
    assert "<button" not in celda and "<form" not in celda
    assert "data-tt-toggle" not in celda
    assert f'id="lib-{i}-panel"' not in html


@pytest.mark.parametrize("tab,kw,prefijo", [
    ("pending", {}, "Dictaminar a "),
    ("awaiting_payment", {}, "Opciones de "),
    ("observed", {}, "Actualizar la observación de "),
    ("cleared", {"cleared_via": "no_charge"}, "Opciones de "),
])
def test_toggle_aria_natural_por_pestana(client_as, staff, nuevo_en, token, tab, kw, prefijo):
    esc = nuevo_en(token, tab, **kw)
    i = esc.clearance.id
    celda = _ultima_celda(_tr(_body_tab(client_as, staff, token, tab), f"lib-{i}"))
    abre = re.search(r"<button[^>]*data-tt-toggle[^>]*>", celda).group(0)
    label = html_lib.unescape(re.search(r'aria-label="([^"]*)"', abre).group(1))
    assert label.startswith(prefijo) and esc.student.last_name in label
    assert 'aria-expanded="false"' in abre
    assert f'aria-controls="lib-{i}-panel"' in abre
