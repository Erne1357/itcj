"""El acordeon del dashboard del alumno, verificado SOBRE EL HTML servido.

Complemento de `test_student_dashboard_accordion.py`, que prueba el contrato de
datos (`_phases_ctx`). Aqui se prueba lo unico que el alumno toca de verdad: el
markup. La distincion no es burocracia — `_cta_for()` puede devolver `None`
perfectamente y aun asi el template puede pintar un enlace a `/student/documents`
en el panel de una fase futura, porque el enlace no tiene por que venir del
contexto: puede estar escrito a mano en el HTML. **El contexto correcto no
demuestra una pantalla correcta.**

La regresion que mas duele, y por la que empieza el archivo: **dejar accionar un
paso que no toca**. Un alumno en fase 1 que puede abrir "Formato B" desde el
acordeon manda datos a una fase que nadie ha habilitado; uno en fase 5 que puede
volver a subir documentos rompe la inmutabilidad de lo ya aprobado. Por eso el
guardia de aqui no busca "el CTA": barre el acordeon entero y **prohibe
cualquier forma de accionar** — enlace de app, `<form>`, o atributo htmx —, de
modo que tambien caza el boton que a nadie se le ocurrio llamar CTA.

Anclas estables (contrato con los E2E, no las renombres a la ligera):
`main[data-tt-page="student_dashboard"]` · `#tt-fase-actual` · `[data-tt-cta]` ·
`[data-tt-acc-root]` · `[data-tt-phase="N"]` · `#tt-acc-btn-N` · `#tt-acc-panel-N`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import lxml.html
import pytest

DASHBOARD = "/titulatec/student/dashboard"

# Los tres modulos que EJECUTAN algo del proceso. Salen de `_PHASE_CTA`
# (`pages/student.py`), que es la unica fuente de enlaces de fase.
ACTION_URLS = (
    "/titulatec/student/documents",
    "/titulatec/student/cita",
    "/titulatec/student/formato-b",
)

HTMX_ATTRS = ("hx-get", "hx-post", "hx-put", "hx-patch", "hx-delete")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _dash(cli, query: str = ""):
    """GET del dashboard -> arbol lxml. Falla con el HTML a la vista si no es 200."""
    resp = cli.get(DASHBOARD + query)
    assert resp.status_code == 200, resp.text[:600]
    return lxml.html.fromstring(resp.text)


def _acc_root(doc):
    roots = doc.xpath('//*[@data-tt-acc-root]')
    assert len(roots) == 1, "se esperaba UN acordeon, hay %d" % len(roots)
    return roots[0]


def _items(doc):
    """Los 9 items del acordeon, indexados por numero de fase."""
    root = _acc_root(doc)
    out = {int(el.get("data-tt-phase")): el for el in root.xpath('.//*[@data-tt-phase]')}
    assert sorted(out) == list(range(9)), "faltan fases en el acordeon: %s" % sorted(out)
    return out


def _panel(doc, n):
    """Panel desplegable de la fase n (None si esa fase no se despliega)."""
    got = doc.xpath('//*[@id="tt-acc-panel-%d"]' % n)
    return got[0] if got else None


def _text(el) -> str:
    return " ".join(el.text_content().split())


def _acciones(el) -> list[str]:
    """Todo lo que, dentro de `el`, permitiria ACCIONAR algo.

    Tres formas distintas de lo mismo, porque las tres existen en esta app:
    un `<a>` a un modulo, un `<form>` que postea, o un atributo htmx en
    cualquier etiqueta. Un `<a href="#...">` (la pista que remite a la tarjeta)
    no acciona: navega dentro de la propia pagina.
    """
    hits = []
    for a in el.xpath('.//a[@href]'):
        href = a.get("href")
        if not href.startswith("#"):
            hits.append("<a href=%s> %r" % (href, _text(a)[:60]))
    for f in el.xpath('.//form'):
        hits.append("<form action=%s>" % f.get("action"))
    for attr in HTMX_ATTRS:
        for node in el.xpath('.//*[@%s]' % attr):
            hits.append("%s=%s" % (attr, node.get(attr)))
    for b in el.xpath('.//button'):
        # El unico boton legitimo del acordeon es el propio toggle.
        if b.get("data-tt-acc") is None:
            hits.append("<button> %r" % _text(b)[:60])
    return hits


# ---------------------------------------------------------------------------
# LA regresion: accionar una fase que no toca
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("current_phase", list(range(9)))
def test_ninguna_fase_del_acordeon_ofrece_una_accion(
    client_as, make_student, make_process, make_document, make_appointment,
    seed_phase_defs, seed_document_types, current_phase,
):
    """En las 9 posiciones posibles del alumno, el acordeon NO acciona nada.

    Se recorren todas porque el error se cuela por los bordes: con el alumno en
    fase 2 las fases accionables (1, 2 y 3) caen en "anterior", "actual" y
    "siguiente" a la vez, pero en fase 0 las tres son futuras y en fase 8 las
    tres son pasadas. Un `{% if %}` mal puesto solo falla en una de esas
    posiciones.

    Se siembran documentos y cita a proposito: con datos, los paneles pintan su
    sub-progreso — que es justo donde es tentador colar un "corregir documento".
    """
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    proc = make_process(student, current_phase=current_phase)
    make_document(proc, type_code="birth_certificate", review_status="approved")
    make_document(proc, type_code="high_school_cert", review_status="rejected",
                  note="Se ve borrosa")
    make_appointment(proc, status="scheduled")

    doc = _dash(client_as(student))
    root = _acc_root(doc)

    fugas = _acciones(root)
    assert fugas == [], (
        "el acordeon deja accionar algo con el alumno en la fase %d:\n  %s"
        % (current_phase, "\n  ".join(fugas))
    )

    # Control anti-vacio: que el acordeon se haya pintado de verdad.
    assert len(root.xpath('.//*[@data-tt-phase]')) == 9


@pytest.mark.parametrize("current_phase,url", [
    (1, "/titulatec/student/documents"),
    (2, "/titulatec/student/cita"),
    (3, "/titulatec/student/formato-b"),
])
def test_control_la_fase_actual_si_acciona_y_lo_hace_desde_la_tarjeta(
    client_as, make_student, make_process, seed_phase_defs, seed_document_types,
    current_phase, url,
):
    """Contrapeso del test anterior: sin esto, un dashboard vacio lo pasaria.

    Comprueba las dos mitades de la decision 2: el CTA **existe** y esta
    **fuera** del acordeon, dentro de la tarjeta grande `#tt-fase-actual`.
    """
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    make_process(student, current_phase=current_phase)

    doc = _dash(client_as(student))

    ctas = doc.xpath('//a[@data-tt-cta]')
    assert len(ctas) == 1, "se esperaba UN CTA, hay %d" % len(ctas)
    assert ctas[0].get("href") == url

    # Y esta dentro de la tarjeta, no en la lista.
    assert doc.xpath('//*[@id="tt-fase-actual"]//a[@data-tt-cta]')
    assert not _acc_root(doc).xpath('.//a[@data-tt-cta]')


@pytest.mark.parametrize("current_phase", [0, 4, 5, 6, 7, 8])
def test_una_fase_actual_sin_modulo_no_inventa_un_boton(
    client_as, make_student, make_process, seed_phase_defs, seed_document_types,
    current_phase,
):
    """Fases que el alumno no ejecuta (las lleva un area): cero CTA en toda la pagina.

    La tarjeta grande explica quien la tiene, pero no ofrece boton: no hay
    ningun sitio al que mandar al alumno.
    """
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    make_process(student, current_phase=current_phase)

    doc = _dash(client_as(student))

    assert doc.xpath('//a[@data-tt-cta]') == []
    assert doc.xpath('//*[@id="tt-fase-actual"]'), "la tarjeta debe seguir ahi"


# ---------------------------------------------------------------------------
# La fase actual no se despliega (decisiones 2 y 3)
# ---------------------------------------------------------------------------
def test_la_fase_actual_no_tiene_boton_ni_panel_en_el_html(
    client_as, make_student, make_process, seed_phase_defs, seed_document_types,
):
    """No basta con no marcarla desplegable: el toggle no debe EXISTIR.

    Si la fila fuese un `<button>` con `disabled` o `aria-disabled`, seguiria en
    el orden de tabulacion o se le podria quitar el atributo desde el inspector.
    Aqui la fila actual es un `div.tt-acc-row`: no hay nada que activar.
    """
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    make_process(student, current_phase=2)

    doc = _dash(client_as(student))
    items = _items(doc)

    actual = items[2]
    assert actual.xpath('.//button[@data-tt-acc]') == []
    assert _panel(doc, 2) is None
    assert actual.xpath('.//*[contains(@class, "tt-acc-row")]'), (
        "la fase actual debe pintar su fila estatica")
    # Y remite a la tarjeta, que es donde esta su contenido.
    hint = actual.xpath('.//a[@data-tt-acc-goto]')
    assert len(hint) == 1 and hint[0].get("href") == "#tt-fase-actual"

    # Las otras 8 SI se despliegan: boton + panel, sin excepcion.
    for n, item in items.items():
        if n == 2:
            continue
        assert item.xpath('.//button[@data-tt-acc]'), "la fase %d no se despliega" % n
        assert _panel(doc, n) is not None, "la fase %d no tiene panel" % n


def test_sin_proceso_las_nueve_se_despliegan_y_ninguna_acciona(
    client_as, make_student, seed_phase_defs, seed_document_types,
):
    """El alumno recien dado de alta: 9 fases informativas, cero acciones.

    Es el estado en el que mas facil es filtrar un boton, porque no hay ninguna
    fase "actual" que lo justifique.
    """
    seed_phase_defs()
    seed_document_types()

    doc = _dash(client_as(make_student()))

    assert len(doc.xpath('//button[@data-tt-acc]')) == 9
    assert doc.xpath('//a[@data-tt-cta]') == []
    assert _acciones(_acc_root(doc)) == []


# ---------------------------------------------------------------------------
# Las 9 fases y su estado
# ---------------------------------------------------------------------------
def test_el_dashboard_pinta_las_nueve_fases_con_su_estado(
    client_as, make_student, make_process, seed_phase_defs, seed_document_types,
):
    """Nombre del catalogo + pildora de estado, en el orden del catalogo.

    Reparto que deja `make_process` (espejo del importador): < actual aprobadas,
    == actual en curso, > actual pendientes. La pildora de "Pendiente" no se
    pinta a proposito (seria ruido en 5 filas de 9), asi que se afirma su
    AUSENCIA: si un dia aparece, este test lo dice en vez de que se note en
    produccion.
    """
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    make_process(student, current_phase=4)

    doc = _dash(client_as(student))
    items = _items(doc)

    assert "Documentos iniciales" in _text(items[1])
    assert "Cita de cotejo" in _text(items[2])
    assert "Formato B" in _text(items[3])

    for n in range(0, 4):                       # anteriores -> aprobadas
        assert "Aprobado" in _text(items[n]), "fase %d" % n
    assert "Actual" in _text(items[4])          # la actual lleva su propia pildora
    for n in range(5, 9):                       # siguientes -> sin pildora
        assert "Aprobado" not in _text(items[n]) and "Pendiente" not in _text(items[n])

    # El hero cuenta el avance con el mismo numero.
    assert "4 de 9 fases" in _text(doc)


def test_la_barra_del_hero_marca_la_fase_actual(
    client_as, make_student, make_process, seed_phase_defs, seed_document_types,
):
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    make_process(student, current_phase=3)

    doc = _dash(client_as(student))
    segs = doc.xpath('//*[contains(@class,"tt-phasebar")]/div')

    assert len(segs) == 9
    assert [i for i, s in enumerate(segs) if "is-done" in (s.get("class") or "")] == [0, 1, 2]
    assert [i for i, s in enumerate(segs) if "is-current" in (s.get("class") or "")] == [3]


# ---------------------------------------------------------------------------
# Fase anterior: historial, e inmutable
# ---------------------------------------------------------------------------
def test_una_fase_anterior_expone_su_historial_dentro_del_panel(
    client_as, db_session, make_student, make_process,
    seed_phase_defs, seed_document_types,
):
    """Decision 6: el historial que vivia en la pantalla de fase vive en el panel.

    Y solo el de ESA fase: un evento de la fase 2 no se cuela en el panel de la
    1, que era el riesgo obvio al mover el timeline de una pantalla por fase a
    nueve paneles en la misma pagina.
    """
    from itcj2.apps.titulatec.models import ProcessEvent

    seed_phase_defs()
    seed_document_types()
    student = make_student()
    proc = make_process(student, current_phase=2)
    base = datetime(2026, 3, 2, 10, 0)
    db_session.add_all([
        ProcessEvent(process_id=proc.id, event_type="phase_approved",
                     phase_number=1, created_at=base),
        ProcessEvent(process_id=proc.id, event_type="appointment_scheduled",
                     phase_number=2, created_at=base + timedelta(hours=1)),
    ])
    db_session.flush()

    doc = _dash(client_as(student))
    panel = _panel(doc, 1)
    txt = _text(panel)

    assert "Historial" in txt
    assert "Fase aprobada" in txt
    assert "Cita agendada" not in txt, "el evento de la fase 2 se colo en la fase 1"
    assert panel.xpath('.//*[contains(@class,"tt-timeline-item")]')
    # Inmutable: se consulta, no se opera.
    assert "Fase cerrada" in txt
    assert _acciones(panel) == []

    # El de la fase actual no cabe en ningun panel: vive en la tarjeta grande.
    assert "Cita agendada" in _text(doc.xpath('//*[@id="tt-fase-actual"]')[0])


# ---------------------------------------------------------------------------
# Fase siguiente: informativa, sin CTA
# ---------------------------------------------------------------------------
def test_una_fase_siguiente_informa_pero_no_habilita_nada(
    client_as, make_student, make_process, seed_phase_defs, seed_document_types,
):
    """Decision 7: la frase de la fase + "que vas a necesitar", y punto.

    El texto de cierre ("se habilitara cuando llegues") es lo que evita que el
    alumno lea el panel como si ya pudiera hacer algo.
    """
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    make_process(student, current_phase=2)

    doc = _dash(client_as(student))
    panel = _panel(doc, 4)
    txt = _text(panel)

    assert "Qué vas a necesitar" in txt
    assert len(panel.xpath('.//ul[contains(@class,"tt-needs")]/li')) >= 1
    assert "Se habilitará cuando llegues a esta fase" in txt
    assert _acciones(panel) == []


def test_una_fase_futura_accionable_tampoco_ensena_su_boton(
    client_as, make_student, make_process, seed_phase_defs, seed_document_types,
):
    """El caso peligroso: el alumno va en la 1 y la 3 (Formato B) es suya... luego.

    La fase 3 tiene entrada en `_PHASE_CTA`, asi que es la candidata natural a
    filtrarse. Se comprueba por URL, no por el atributo `data-tt-cta`: un enlace
    escrito a mano en el template no llevaria ese atributo y pasaria inadvertido.
    """
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    make_process(student, current_phase=1)

    doc = _dash(client_as(student))
    panel_txt_href = [a.get("href") for a in _panel(doc, 3).xpath('.//a[@href]')]

    assert all(h not in ACTION_URLS for h in panel_txt_href), panel_txt_href
    assert "Llenar Formato B" not in _text(_panel(doc, 3))


# ---------------------------------------------------------------------------
# Sub-progreso (decision 4) en el HTML
# ---------------------------------------------------------------------------
def test_el_panel_de_la_fase_1_refleja_2_de_3_documentos_aprobados(
    client_as, make_student, make_process, make_document,
    seed_phase_defs, seed_document_types,
):
    """Dos aprobados y uno en revision: se ve el detalle documento a documento.

    Y sigue sin poderse subir nada desde ahi — el alumno ya paso de fase, esos
    documentos son historia.
    """
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    proc = make_process(student, current_phase=2)
    make_document(proc, type_code="birth_certificate", review_status="approved")
    make_document(proc, type_code="high_school_cert", review_status="approved")
    make_document(proc, type_code="curp", review_status="pending")

    doc = _dash(client_as(student))
    item, panel = _items(doc)[1], _panel(doc, 1)
    txt = _text(panel)

    # Resumen en la cabecera, sin desplegar: cuantos van y que falta.
    assert "2 de 3 aprobados · 1 en revisión" in _text(item)
    # Detalle dentro.
    assert "Cómo va" in txt
    assert "Acta de nacimiento · aprobado" in txt
    assert "Certificado de bachillerato · aprobado" in txt
    assert "CURP certificada · en revisión" in txt
    assert len(panel.xpath('.//*[contains(@class,"tt-substep")]')) == 3
    assert _acciones(panel) == []


def test_un_documento_rechazado_muestra_el_motivo_en_el_panel(
    client_as, make_student, make_process, make_document,
    seed_phase_defs, seed_document_types,
):
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    proc = make_process(student, current_phase=2)
    make_document(proc, type_code="birth_certificate", review_status="rejected",
                  note="La foto está borrosa")
    make_document(proc, type_code="high_school_cert", review_status="approved")

    txt = _text(_panel(_dash(client_as(student)), 1))

    assert "Acta de nacimiento · por corregir" in txt
    assert "La foto está borrosa" in txt
    assert "CURP certificada · sin subir" in txt      # missing != pending


def test_el_panel_de_la_cita_dice_fecha_lugar_y_si_falta_confirmar(
    client_as, make_student, make_process, make_appointment,
    seed_phase_defs, seed_document_types,
):
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    proc = make_process(student, current_phase=3)
    make_appointment(proc, status="scheduled", location="Edificio K, planta baja")

    txt = _text(_panel(_dash(client_as(student)), 2))

    assert "Edificio K, planta baja" in txt
    assert "Falta que confirmes tu asistencia" in txt
    assert _acciones(_panel(_dash(client_as(student)), 2)) == []


def test_el_panel_del_formato_b_enumera_sus_tres_pasos(
    client_as, db_session, make_student, make_process,
    seed_phase_defs, seed_document_types,
):
    seed_phase_defs()
    seed_document_types()
    from itcj2.apps.titulatec.models import FormatB

    student = make_student()
    proc = make_process(student, current_phase=5)
    db_session.add(FormatB(process_id=proc.id, status="draft",
                           gender="female", age=23))
    db_session.flush()

    panel = _panel(_dash(client_as(student)), 3)
    txt = _text(panel)

    assert len(panel.xpath('.//*[contains(@class,"tt-substep")]')) == 3
    assert "Paso 1" in txt and "listo" in txt
    assert "pendiente" in txt


# ---------------------------------------------------------------------------
# Deep-link: el servidor entrega el acordeon ya abierto (decision 5)
# ---------------------------------------------------------------------------
def test_el_deep_link_llega_abierto_en_el_html_sin_ayuda_de_js(
    client_as, make_student, make_process, seed_phase_defs, seed_document_types,
):
    """`?fase=N` abre EN EL SERVIDOR: `aria-expanded=true` y panel sin `hidden`.

    Es la razon de usar query param y no `#fase-N`: el fragmento no viaja al
    servidor, asi que el panel llegaria cerrado y solo lo abriria JS despues de
    pintar — un parpadeo, y nada para quien navegue sin JS.
    """
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    make_process(student, current_phase=2)

    doc = _dash(client_as(student), "?fase=5")

    abierto = doc.xpath('//*[@id="tt-acc-btn-5"]')[0]
    assert abierto.get("aria-expanded") == "true"
    assert _panel(doc, 5).get("hidden") is None

    otros = [b.get("id") for b in doc.xpath('//button[@data-tt-acc]')
             if b.get("aria-expanded") == "true"]
    assert otros == ["tt-acc-btn-5"], otros
    for n in (0, 1, 3, 4, 6, 7, 8):
        assert _panel(doc, n).get("hidden") is not None, "la fase %d llego abierta" % n

    assert "is-target" in _items(doc)[5].get("class")


def test_el_deep_link_a_la_fase_actual_resalta_pero_no_abre_nada(
    client_as, make_student, make_process, seed_phase_defs, seed_document_types,
):
    """La actual no tiene panel que abrir: se resalta la fila y punto.

    Su contenido ya esta entero en la tarjeta grande, que es a donde la lleva el
    JS de desplazamiento.
    """
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    make_process(student, current_phase=2)

    doc = _dash(client_as(student), "?fase=2")

    assert [b.get("id") for b in doc.xpath('//button[@data-tt-acc]')
            if b.get("aria-expanded") == "true"] == []
    assert "is-target" in _items(doc)[2].get("class")


def test_la_ruta_vieja_aterriza_en_un_dashboard_con_esa_fase_abierta(
    client_as, make_student, make_process, seed_phase_defs, seed_document_types,
):
    """De punta a punta lo que hace una notificacion ya emitida.

    `services/notify.py` escribio `/titulatec/student/fase/{n}` en filas de
    `core_notifications` que siguen en BD. El 302 solo sirve si lo que hay al
    otro lado es el acordeon abierto: esto lo comprueba SIGUIENDO el redirect,
    no solo mirando el `Location`.
    """
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    make_process(student, current_phase=2)

    resp = client_as(student).get("/titulatec/student/fase/1", follow_redirects=True)

    assert resp.status_code == 200
    doc = lxml.html.fromstring(resp.text)
    assert doc.xpath('//main[@data-tt-page="student_dashboard"]')
    assert doc.xpath('//*[@id="tt-acc-btn-1"]')[0].get("aria-expanded") == "true"
    assert _panel(doc, 1).get("hidden") is None


# ---------------------------------------------------------------------------
# Accesibilidad del acordeon (patron APG)
# ---------------------------------------------------------------------------
def test_cada_cabecera_desplegable_cumple_el_patron_apg(
    client_as, make_student, make_process, seed_phase_defs, seed_document_types,
):
    """Boton real, `aria-expanded`, y `aria-controls` que APUNTA A ALGO.

    Los tres fallos clasicos: un `<div onclick>` que el teclado no alcanza, un
    `aria-expanded` que se queda fijo en "false", y un `aria-controls` que
    referencia un id inexistente (lo mas comun al renombrar). El ultimo solo se
    ve resolviendo la referencia, que es lo que hace este test.
    """
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    make_process(student, current_phase=2)

    doc = _dash(client_as(student), "?fase=6")
    botones = doc.xpath('//button[@data-tt-acc]')

    assert len(botones) == 8, "8 desplegables (las 9 menos la actual)"
    for b in botones:
        n = b.get("data-tt-acc")
        assert b.get("type") == "button", "fase %s: sin type=button postea el form padre" % n
        assert b.get("aria-expanded") in ("true", "false"), n
        destino = doc.xpath('//*[@id="%s"]' % b.get("aria-controls"))
        assert len(destino) == 1, "fase %s: aria-controls apunta a un id que no existe" % n
        assert destino[0].get("role") == "region"
        assert destino[0].get("aria-labelledby") == b.get("id")
        # El chevron es decoracion pura (gira al abrir): fuera del arbol de
        # accesibilidad. No se exige lo mismo a los iconos de las pildoras: los
        # emite la macro `pill()`, compartida con todo el admin, y cambiarla
        # seria un cambio de diseno, no un test.
        chevrons = b.xpath('.//i[contains(@class,"tt-acc-chev")]')
        assert len(chevrons) == 1, "fase %s: se esperaba un chevron" % n
        assert chevrons[0].get("aria-hidden") == "true", n

    # El panel cerrado se cierra con `hidden`, no con altura 0: lo que no se ve
    # tampoco se tabula ni lo lee el lector.
    cerrados = [p for p in doc.xpath('//*[starts-with(@id,"tt-acc-panel-")]')
                if p.get("hidden") is None]
    assert [p.get("id") for p in cerrados] == ["tt-acc-panel-6"]


def test_toda_vista_de_alumno_lleva_su_ancla_data_tt_page(
    client_as, make_student, make_process, seed_phase_defs, seed_document_types,
    db_session,
):
    """`main[data-tt-page="clave"]`, una sola, no vacia y distinta en cada vista.

    Es el equivalente del `data-hd-page` de helpdesk: el punto al que se agarra
    un E2E para saber que la navegacion aterrizo donde debia. Sin el, un test de
    responsive no puede afirmar QUE pantalla midio. Se comprueba aqui, y no en
    el E2E que aun no existe, porque no necesita navegador: es markup.

    El fallo tipico no es que falte, sino que dos vistas repitan clave al
    copiar-pegar la plantilla — por eso se afirma que son 5 claves DISTINTAS.

    **Cada vista se pide con el proceso EN SU FASE.** Antes bastaba un unico
    `current_phase=3` para las cinco; desde la guarda de fase del alumno
    (`test_student_phase_guard.py`) las tres vistas de modulo solo responden 200
    cuando esa es la fase en curso, y fuera de ella devuelven un 302 al acordeon
    —que el TestClient sigue por defecto, asi que el fallo se veia como "la
    ancla de /documents dice student_dashboard". Mover la fase mantiene este
    test hablando de MARKUP y no de autorizacion, que es lo suyo.
    """
    from tests.fastapi.titulatec.conftest import STUDENT_PERMS

    seed_phase_defs()
    seed_document_types()
    # `formato-b` pide un permiso que el set por defecto del alumno no trae.
    student = make_student(perm_codes=tuple(STUDENT_PERMS) + ("titulatec.format_b.page.fill",))
    proc = make_process(student, current_phase=3)
    cli = client_as(student)

    # url -> (ancla esperada, fase que hay que tener en curso; None = cualquiera)
    vistas = {
        "/titulatec/student/dashboard": ("student_dashboard", None),
        "/titulatec/student/documents": ("student_documents", 1),
        "/titulatec/student/cita": ("student_cita", 2),
        "/titulatec/student/formato-b": ("student_formato_b", 3),
        "/titulatec/student/perfil": ("student_perfil", None),
    }

    vistos = []
    for url, (esperado, fase) in vistas.items():
        if fase is not None:
            proc.current_phase = fase
            db_session.flush()
        resp = cli.get(url)
        assert resp.status_code == 200, "%s -> %s\n%s" % (url, resp.status_code, resp.text[:400])
        mains = lxml.html.fromstring(resp.text).xpath('//main[@data-tt-page]')
        assert len(mains) == 1, "%s: se esperaba UN <main data-tt-page>, hay %d" % (url, len(mains))
        clave = mains[0].get("data-tt-page")
        assert clave == esperado, "%s: ancla %r, se esperaba %r" % (url, clave, esperado)
        vistos.append(clave)

    assert len(set(vistos)) == len(vistas), "hay dos vistas con la misma clave: %s" % vistos


def test_el_js_del_acordeon_se_carga_una_vez_y_versionado(
    client_as, make_student, make_process, seed_phase_defs, seed_document_types,
):
    """Un solo `<script src>` del modulo, con `?v=`, y cero `<script>` inline nuevo.

    Cargarlo desde la base (y no desde el fragmento) es lo que lo hace
    morph-safe; el `?v=` es lo que evita que el navegador sirva el JS viejo tras
    un despliegue (gotcha #9 de la app). Se afirma tambien que la vista no
    reintrodujo JS inline: la regla del proyecto es modulo externo.
    """
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    make_process(student, current_phase=2)

    resp = client_as(student).get(DASHBOARD)
    doc = lxml.html.fromstring(resp.text)

    srcs = [s.get("src") for s in doc.xpath('//script[@src]')
            if "student/dashboard.js" in (s.get("src") or "")]
    assert len(srcs) == 1, srcs
    assert "?v=" in srcs[0] and not srcs[0].endswith("?v=")
