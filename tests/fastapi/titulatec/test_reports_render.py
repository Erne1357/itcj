"""Capa visual del Tablero de la jefa de Servicios Escolares (Task 7a).

Spec `docs/superpowers/specs/2026-10-14-titulatec-tablero-design.md` §5
(pestañas) y §7 (visualización). Se fija sobre el HTML REAL de las rutas
(`/titulatec/admin/tablero` y `/body`), con un escenario propio:

* Panorama y Ritmo pintan los conteos del escenario (KPI, barras por etapa y
  por pelota, alertas, líneas, calendario, liberados por carrera, lista del día).
* Cada `<svg>` lleva `role="img"` + `aria-label`; cada marca (`.tt-rep-mark`)
  lleva `data-tt-tip`, y las de SVG además su `<title>` (respaldo nativo).
* Cada tarjeta de gráfica trae su tabla gemela («Ver tabla», `<details>`).
* Sin `<script>` en el parcial y sin `style=` salvo una sola declaración de
  geometría ya calculada por el servidor (`width: 42.50%`, `left: …%`, …).
* Toda liga interna cumple `hx-select` == `hx-target` ⇒ `morph:outerHTML` y
  empuja la URL de la PÁGINA, nunca la de `/body`.
* Fila de filtros (rango primero, convocatoria, carreras con chips-enlace,
  Imprimir), cabecera de impresión, estados vacíos y los estáticos cargados
  UNA vez por `base_admin.html`.

«Hoy» = `db_now().date()` (el runner de CI está en UTC). Lo que depende del día
hábil se fecha con `last_business_days`, así que la prueba no depende del día
de la semana en que corre. Toda consulta va acotada a la convocatoria del
escenario (`cohort=<id>`): la base de dev es compartida.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from itertools import count
from pathlib import Path
from types import SimpleNamespace

import lxml.html
import pytest

import itcj2.apps.titulatec as _tt_pkg

APP = Path(_tt_pkg.__file__).resolve().parent
REPORTS_TPL = APP / "templates" / "titulatec" / "admin" / "partials" / "reports"
CSS = APP / "static" / "css" / "admin" / "reports.css"
JS = APP / "static" / "js" / "admin" / "reports.js"

URL = "/titulatec/admin/tablero"
BODY = f"{URL}/body"
PERM = "titulatec.reports.page.view"
_SEQ = count(1)

# Única forma de `style=` permitida: UNA declaración de geometría que ya viene
# calculada del servidor (porcentaje o píxeles), p. ej. `width: 42.50%`.
_STYLE_OK = re.compile(r"^\s*(width|left|top)\s*:\s*\d+(\.\d+)?(%|px)\s*;?\s*$")
_OUTER = "outerHTML"


# ---------------------------------------------------------------------------
# Escenario
# ---------------------------------------------------------------------------
@pytest.fixture()
def jefa(make_head):
    from tests.fastapi.titulatec.conftest import HEAD_PERMS
    return make_head(perm_codes=HEAD_PERMS + (PERM,))


@pytest.fixture()
def esc(db_session, seed_phase_defs, seed_document_types, make_program, make_cohort,
        make_student, make_process, make_document, make_survey_review):
    """Convocatoria propia con requisitos de cotejo y dos carreras.

    | item | carrera | etapa | pelota | días |
    |---|---|---|---|---|
    | solicitud vieja | A | req_review | Escolares | 15 (crit) |
    | solicitud nueva | B | req_review | Escolares | 0 |
    | solicitud en Cómputo | A | req_access | Cómputo | 2 |
    | expediente | A | docs (1 doc por dictaminar) | Escolares | 10 (warn) |
    | listo | B | requisitos (listo para agendar) | Alumno | 0 |
    | doble | A | requisitos (pago + encuesta en GTV) | Alumno + GTV | 0 |
    | liberado | B | liberado (b0) | — | — |

    En el rango por omisión (14 días): 2 solicitudes nuevas (la vieja queda
    fuera) y 1 liberado. Inscritos acumulados al final: 4 procesos.
    """
    from itcj2.apps.titulatec.models import EnrollmentRequest, ProcessPhase
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )
    from itcj2.apps.titulatec.utils.business_days import last_business_days
    from itcj2.core.utils.timezone import db_now

    seed_phase_defs()
    seed_document_types()
    hoy = db_now().date()
    b0 = last_business_days(hoy, 1)[0]                 # hoy o el último día hábil
    pa = make_program("Ingenieria Visual Tablero A")
    pb = make_program("Ingenieria Visual Tablero B")
    c = make_cohort()
    CotejoRequirementService.seed_defaults(db_session, c.id, commit=False)

    def hace(dias, h=8):
        return datetime.combine(hoy - timedelta(days=dias), time(h, 0))

    def solicitud(status, program, creada, revisada=None):
        n = next(_SEQ)
        db_session.add(EnrollmentRequest(
            cohort_id=c.id, control_number=f"97{n:06d}", first_name="SOLICITANTE",
            last_name="VISUAL", program_id=program.id, phone="6560000000",
            contact_email=f"tt7.{n}@example.invalid", has_efirma=False, kind="unknown",
            status=status, verify_send_count=0, created_at=creada, reviewed_at=revisada))
        db_session.flush()

    solicitud("pending_review", pa, hace(15))
    solicitud("pending_review", pb, hace(0, h=0))
    solicitud("awaiting_access", pa, hace(3), revisada=hace(2))

    docs = make_process(make_student(), cohort=c, program=pa, current_phase=1)
    make_document(docs, review_status="pending")
    docs.created_at = hace(10)
    listo = make_process(make_student(), cohort=c, program=pb, current_phase=2)
    make_survey_review(listo, status="approved")
    doble = make_process(make_student(), cohort=c, program=pa, current_phase=2,
                         library_clearance="awaiting_payment")
    make_survey_review(doble, status="in_review")
    alumno_lib = make_student()
    lib = make_process(alumno_lib, cohort=c, program=pb, current_phase=3)
    f2 = db_session.query(ProcessPhase).filter_by(process_id=lib.id, phase_number=2).one()
    f2.completed_at = datetime.combine(b0, time(13))
    db_session.flush()
    return SimpleNamespace(c=c, pa=pa, pb=pb, hoy=hoy, b0=b0, lib=lib,
                           alumno_lib=alumno_lib, make_cohort=make_cohort)


def _get(client, url, **params):
    r = client.get(url, params=params)
    assert r.status_code == 200, r.text[:800]
    return r.text


def _doc(html):
    return lxml.html.fromstring(html)


def _by_id(doc, id_):
    found = doc.xpath('//*[@id="%s"]' % id_)
    assert len(found) == 1, "%s: %d nodos" % (id_, len(found))
    return found[0]


def _txt(el):
    return " ".join(el.text_content().split())


def _cls(el, name):
    return el.xpath('.//*[contains(concat(" ", normalize-space(@class), " "), " %s ")]' % name)


def _hval(doc, id_):
    """Valor de la punta de una barra horizontal (`.tt-rep-hval`)."""
    vals = _cls(_by_id(doc, id_), "tt-rep-hval")
    assert len(vals) == 1, id_
    return _txt(vals[0])


@pytest.fixture()
def panorama(client_as, jefa, esc):
    html = _get(client_as(jefa), BODY, tab="panorama", cohort=esc.c.id)
    return SimpleNamespace(html=html, doc=_doc(html))


@pytest.fixture()
def ritmo(client_as, jefa, esc):
    html = _get(client_as(jefa), BODY, tab="ritmo", cohort=esc.c.id)
    return SimpleNamespace(html=html, doc=_doc(html))


# ---------------------------------------------------------------------------
# Panorama: los números del escenario
# ---------------------------------------------------------------------------
def test_panorama_barras_por_etapa_con_los_conteos(panorama, esc):
    doc = panorama.doc
    esperado = {"req_review": "2", "req_access": "1", "req_approved": "0", "docs": "1",
                "requisitos": "2", "cita": "0", "liberado": "1"}
    for code, n in esperado.items():
        assert _hval(doc, f"tt-rep-stage-{code}") == n, code
    # La etapa legada (`unverified`) en cero no ocupa renglón; la tabla sí la lista.
    assert not doc.xpath('//*[@id="tt-rep-stage-req_unverified"]')
    tabla = _txt(_by_id(doc, "tt-rep-stages-table"))
    assert "Solicitud anterior (por revisar)" in tabla and "Solicitud por revisar 2" in tabla
    # Cada barra liga a Atorados filtrado por su etapa (página y parcial).
    liga = _by_id(doc, "tt-rep-stage-docs").xpath(".//a")[0]
    assert liga.get("href") == f"{URL}?tab=atorados&cohort={esc.c.id}&level=all&stage=docs"
    assert liga.get("hx-get") == f"{BODY}?tab=atorados&cohort={esc.c.id}&level=all&stage=docs"


def test_panorama_pelota_por_actor_con_sub_conteo_de_atorados(panorama, esc):
    doc = panorama.doc
    esperado = {"escolares": "3", "alumno": "2", "gtv": "1", "biblioteca": "0",
                "computo": "1"}
    for code, n in esperado.items():
        assert _hval(doc, f"tt-rep-ball-{code}") == n, code
    # Escolares: 2 lentos o atorados (la solicitud vieja y el expediente), liga ≥ WARN.
    sub = _by_id(doc, "tt-rep-ball-escolares-stuck")
    assert "2" in _txt(sub)
    assert sub.get("hx-get") == f"{BODY}?tab=atorados&cohort={esc.c.id}&ball=escolares"
    assert not doc.xpath('//*[@id="tt-rep-ball-alumno-stuck"]')     # 0: sin liga
    # Color de identidad por clase (sigue a la entidad), etiqueta directa visible.
    barra = _cls(_by_id(doc, "tt-rep-ball-gtv"), "tt-rep-bar")[0]
    assert "tt-rep-c--a-gtv" in barra.get("class")
    assert "GTV" in _txt(_by_id(doc, "tt-rep-ball-gtv"))
    # «N pendientes esperan a dos áreas» (el doble cuenta una vez por actor).
    assert "1 pendiente espera a dos áreas" in _txt(_by_id(doc, "tt-rep-balls"))


def test_panorama_kpis(panorama):
    doc = panorama.doc
    assert _txt(_cls(_by_id(doc, "tt-rep-kpi-liberated"), "num")[0]).startswith("1")
    assert "1 en los últimos 14 días" in _txt(_by_id(doc, "tt-rep-kpi-liberated"))
    req = _by_id(doc, "tt-rep-kpi-requests")
    assert _txt(_cls(req, "num")[0]) == "2"
    assert "15 días" in _txt(req)
    stuck = _by_id(doc, "tt-rep-kpi-stuck")
    assert _txt(_cls(stuck, "num")[0]).startswith("1")
    assert "1 lento" in _txt(stuck)
    pace = _by_id(doc, "tt-rep-kpi-pace")
    assert "a este ritmo, sin contar feriados ni nuevas solicitudes" in _txt(pace)
    # Estado SIEMPRE con icono + texto (nunca solo color).
    assert stuck.xpath('.//i[contains(@class, "bi-exclamation-octagon-fill")]')
    assert stuck.xpath('.//i[contains(@class, "bi-hourglass-split")]')


def test_panorama_alertas_con_liga(panorama, esc):
    doc = panorama.doc
    alerta = _by_id(doc, "tt-rep-alert-requests_crit")
    assert "1 solicitud por revisar lleva 14 días o más esperando" in _txt(alerta)
    liga = alerta if alerta.tag == "a" else alerta.xpath(".//a")[0]
    assert liga.get("hx-get") == (f"{BODY}?tab=atorados&cohort={esc.c.id}&level=crit"
                                  "&stage=req_review")
    assert alerta.xpath('.//i[contains(@class, "bi-exclamation-octagon-fill")]')
    assert doc.xpath('//*[@id="tt-rep-alert-docs_warn"]')
    assert doc.xpath('//*[@id="tt-rep-alert-inflow"]')              # entran 2, sale 1


def test_la_alerta_de_capacidad_sale_del_tablero_por_el_menu(client_as, jefa, esc,
                                                             monkeypatch):
    """La liga de capacidad va a Citas de cotejo: navega como el menú lateral
    (`#tt-admin-content`), no dentro del tablero."""
    from itcj2.apps.titulatec.services import report_officers as ro
    monkeypatch.setattr(ro, "capacity", lambda db, *, today, days=5: {0: (0, 0)})
    doc = _doc(_get(client_as(jefa), BODY, tab="panorama", cohort=esc.c.id))
    alerta = _by_id(doc, "tt-rep-alert-capacity")
    liga = alerta if alerta.tag == "a" else alerta.xpath(".//a")[0]
    assert liga.get("href") == "/titulatec/admin/appointments"
    assert liga.get("hx-target") == "#tt-admin-content"
    assert liga.get("hx-select") == "#tt-admin-content"
    assert liga.get("hx-swap").split(" ")[0] == "morph:outerHTML"


# ---------------------------------------------------------------------------
# Ritmo
# ---------------------------------------------------------------------------
def test_ritmo_lineas_de_un_eje_con_crosshair(ritmo):
    doc = ritmo.doc
    daily = _by_id(doc, "tt-rep-daily")
    svg = daily.xpath(".//svg")
    assert len(svg) == 1
    lineas = _cls(daily, "tt-rep-line")
    assert len(lineas) == 2
    assert {lin.get("data-tt-series") for lin in lineas} == {"requests_new", "liberated"}
    # Una columna de crosshair por día del rango (14) con su lectura completa.
    dias = daily.xpath('.//*[@data-tt-day]')
    assert len(dias) == 14
    assert all(d.get("data-tt-x") and d.get("data-tt-ys") and d.get("data-tt-vals")
               for d in dias)
    plot = daily.xpath('.//*[@data-tt-xhair]')
    assert len(plot) == 1 and plot[0].get("tabindex") == "0"
    # Leyenda con la suma del periodo (etiqueta directa en la leyenda).
    leyenda = _by_id(doc, "tt-rep-daily-legend")
    assert "Solicitudes nuevas 2" in _txt(leyenda)
    assert "Liberados 1" in _txt(leyenda)
    # Un solo eje: un solo juego de marcas Y.
    assert len(daily.xpath('.//*[contains(@class, "tt-rep-yaxis")]')) == 1


def test_ritmo_acumulado_calendario_y_carreras(ritmo, esc):
    doc = ritmo.doc
    assert "Inscritos 4" in _txt(_by_id(doc, "tt-rep-cumulative-legend"))
    assert "Liberados 1" in _txt(_by_id(doc, "tt-rep-cumulative-legend"))
    celda = _by_id(doc, f"tt-rep-cal-{esc.b0.isoformat()}")
    assert celda.get("data-tt-tip").endswith(": 1 liberado")
    assert "tt-rep-bin-5" in celda.get("class")                       # 1 de máx. 1
    assert celda.get("hx-get") == f"{BODY}?tab=ritmo&cohort={esc.c.id}&day={esc.b0.isoformat()}"
    assert _hval(doc, f"tt-rep-bp-{esc.pb.id}") == "1"
    assert not doc.xpath(f'//*[@id="tt-rep-bp-{esc.pa.id}"]')
    # Leyenda de la escala del calendario visible.
    assert _cls(_by_id(doc, "tt-rep-calendar"), "tt-rep-scale")


def test_ritmo_lista_del_dia_seleccionado(client_as, jefa, esc):
    doc = _doc(_get(client_as(jefa), BODY, tab="ritmo", cohort=esc.c.id,
                    day=esc.b0.isoformat()))
    dia = _by_id(doc, "tt-rep-day")
    filas = dia.xpath(".//li")
    assert len(filas) == 1
    assert esc.alumno_lib.control_number in _txt(filas[0])
    assert esc.pb.name in _txt(filas[0])
    liga = filas[0].xpath(".//a")[0]                     # expediente, como el menú
    assert liga.get("href") == f"/titulatec/admin/processes/{esc.lib.id}"
    assert liga.get("hx-target") == liga.get("hx-select") == "#tt-admin-content"
    cerrar = _by_id(doc, "tt-rep-day-close")
    assert cerrar.get("hx-get") == f"{BODY}?tab=ritmo&cohort={esc.c.id}"
    celda = _by_id(doc, f"tt-rep-cal-{esc.b0.isoformat()}")
    assert celda.get("aria-current") == "date"


# ---------------------------------------------------------------------------
# Contrato de marcas, accesibilidad y swaps
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("vista", ["panorama", "ritmo"])
def test_cada_svg_y_cada_marca_son_accesibles(request, vista):
    v = request.getfixturevalue(vista)
    svgs = v.doc.xpath("//svg")
    assert svgs, "la vista no trae ni un <svg>"
    for svg in svgs:
        assert svg.get("role") == "img"
        assert (svg.get("aria-label") or "").strip(), lxml.html.tostring(svg)[:200]
    marcas = _cls(v.doc, "tt-rep-mark")
    assert len(marcas) >= 5
    for m in marcas:
        assert (m.get("data-tt-tip") or "").strip(), lxml.html.tostring(m)[:200]
        if m.tag in ("polyline", "rect", "circle", "path"):
            assert m.xpath("./title"), "marca SVG sin <title>: %s" % m.get("data-tt-tip")


@pytest.mark.parametrize("vista", ["panorama", "ritmo"])
def test_cada_grafica_tiene_su_tabla_gemela(request, vista):
    v = request.getfixturevalue(vista)
    tarjetas = _cls(v.doc, "tt-rep-chart")
    assert len(tarjetas) >= 2
    for t in tarjetas:
        gemela = t.xpath('.//details[contains(@class, "tt-rep-table")]')
        assert len(gemela) == 1, t.get("id")
        assert "Ver tabla" in _txt(gemela[0].xpath("./summary")[0])
        assert gemela[0].xpath(".//table/tbody/tr"), t.get("id")
        assert gemela[0].get("id") and gemela[0].get("data-tt-keep") is not None


@pytest.mark.parametrize("vista", ["panorama", "ritmo"])
def test_sin_script_ni_estilos_inline_salvo_geometria(request, vista):
    v = request.getfixturevalue(vista)
    assert "<script" not in v.html
    assert "onclick" not in v.html.lower()
    for el in v.doc.xpath("//*[@style]"):
        assert _STYLE_OK.match(el.get("style")), el.get("style")


@pytest.mark.parametrize("vista", ["panorama", "ritmo"])
def test_ligas_internas_morph_outer_y_url_de_pagina(request, vista):
    v = request.getfixturevalue(vista)
    revisadas = 0
    for el in v.doc.xpath("//*[@hx-get]"):
        sel, tgt = el.get("hx-select"), el.get("hx-target")
        if sel and sel == tgt:
            fam = (el.get("hx-swap") or "innerHTML").split(" ")[0].split(":")[-1]
            assert fam == _OUTER, lxml.html.tostring(el)[:200]
        if "/tablero/body" in el.get("hx-get"):
            revisadas += 1
            assert tgt == sel == "#tt-report-body"
            push = el.get("hx-push-url") or ""
            assert push.startswith(URL + "?") and "/body" not in push
            assert el.get("href") == push if el.tag == "a" else True
    assert revisadas >= 10


def test_fila_de_filtros_rango_primero_y_chips_enlace(panorama, esc):
    doc, html = panorama.doc, panorama.html
    filtros = _by_id(doc, "tt-rep-filters")
    ids = [el.get("id") for el in filtros.iter() if el.get("id")]
    orden = [ids.index(i) for i in ("tt-rep-range", "tt-rep-cohort", "tt-rep-programs",
                                     "tt-rep-print")]
    assert orden == sorted(orden)
    # La barra de pestañas va DEBAJO de los filtros.
    assert html.index('id="tt-rep-filters"') < html.index('id="tt-report-tabs"')
    activo = _by_id(doc, "tt-rep-range-14")
    assert activo.get("aria-current") == "true"
    assert _by_id(doc, "tt-rep-range-30").get("hx-get") == (
        f"{BODY}?tab=panorama&cohort={esc.c.id}&range=30")
    conv = _by_id(doc, f"tt-rep-cohort-{esc.c.id}")
    assert conv.get("aria-current") == "true"
    carreras = _by_id(doc, "tt-rep-programs")
    assert carreras.tag == "details" and carreras.get("data-tt-keep") is not None
    assert "Carreras" in _txt(carreras.xpath("./summary")[0])
    chip = _by_id(doc, f"tt-rep-prog-{esc.pa.id}")
    assert chip.tag == "a"
    assert chip.get("hx-get") == f"{BODY}?tab=panorama&cohort={esc.c.id}&px={esc.pa.id}"
    assert chip.get("aria-pressed") == "true"                       # visible
    boton = _by_id(doc, "tt-rep-print")
    assert boton.tag == "button" and boton.get("data-tt-print") is not None
    assert boton.get("type") == "button"


def test_carrera_oculta_cuenta_en_el_resumen_y_se_destapa(client_as, jefa, esc):
    doc = _doc(_get(client_as(jefa), BODY, tab="panorama", cohort=esc.c.id,
                    px=str(esc.pa.id)))
    assert "1 oculta" in _txt(_by_id(doc, "tt-rep-programs").xpath("./summary")[0])
    chip = _by_id(doc, f"tt-rep-prog-{esc.pa.id}")
    assert chip.get("aria-pressed") == "false"
    assert chip.get("hx-get") == f"{BODY}?tab=panorama&cohort={esc.c.id}"


def test_todas_ocultas_avisa_con_mostrar_todas(client_as, jefa, esc):
    doc = _doc(_get(client_as(jefa), BODY, tab="panorama", cohort=esc.c.id,
                    px=f"{esc.pa.id},{esc.pb.id}"))
    aviso = _by_id(doc, "tt-rep-all-hidden")
    liga = aviso.xpath(".//a")[0]
    assert "Mostrar todas" in _txt(liga)
    assert liga.get("hx-get") == f"{BODY}?tab=panorama&cohort={esc.c.id}"


def test_cabecera_de_impresion(client_as, jefa, esc):
    doc = _doc(_get(client_as(jefa), BODY, tab="ritmo", cohort=esc.c.id, range="30"))
    cab = _txt(_by_id(doc, "tt-rep-print-head"))
    assert "Pestaña: Ritmo" in cab and "Rango: Últimos 30 días" in cab
    assert esc.c.name in cab
    assert re.search(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}", cab)


def test_las_pestanas_conservan_los_filtros(client_as, jefa, esc):
    doc = _doc(_get(client_as(jefa), BODY, tab="ritmo", cohort=esc.c.id, range="7"))
    tab = _by_id(doc, "tt-report-tab-panorama")
    assert tab.get("hx-get") == f"{BODY}?tab=panorama&cohort={esc.c.id}&range=7"
    assert tab.get("href") == f"{URL}?tab=panorama&cohort={esc.c.id}&range=7"
    assert "is-active" in _by_id(doc, "tt-report-tab-ritmo").get("class")
    assert _by_id(doc, "tt-report-tab-ritmo").get("aria-current") == "page"


# ---------------------------------------------------------------------------
# Bordes: sin convocatorias, convocatoria vacía
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tab", ["panorama", "ritmo"])
def test_sin_convocatorias(client_as, jefa, monkeypatch, tab):
    from itcj2.apps.titulatec.services import report_service as rsv
    monkeypatch.setattr(rsv, "_load_cohorts", lambda db: [])
    doc = _doc(_get(client_as(jefa), BODY, tab=tab))
    vacio = _by_id(doc, "tt-rep-no-cohorts")
    assert "Aún no hay convocatorias" in _txt(vacio)
    assert not _cls(doc, "tt-rep-chart")


@pytest.mark.parametrize("tab", ["panorama", "ritmo"])
def test_convocatoria_vacia(client_as, jefa, esc, tab, monkeypatch):
    from itcj2.apps.titulatec.services import report_officers as ro
    monkeypatch.setattr(ro, "capacity", lambda db, *, today, days=5: {0: (0, 100)})
    vacia = esc.make_cohort()
    html = _get(client_as(jefa), BODY, tab=tab, cohort=vacia.id)
    doc = _doc(html)
    if tab == "panorama":
        assert "Sin alertas" in _txt(_by_id(doc, "tt-rep-alerts"))
        assert _cls(_by_id(doc, "tt-rep-stages"), "tt-rep-empty")
        assert _cls(_by_id(doc, "tt-rep-balls"), "tt-rep-empty")
    else:
        # Sin pendientes no hay nada que pronosticar (`_pace_ctx`): «sin pendientes».
        assert "sin pendientes" in _txt(_by_id(doc, "tt-rep-pace"))
        assert "0 por día hábil" in _txt(_by_id(doc, "tt-rep-pace"))
        assert _cls(_by_id(doc, "tt-rep-by-program"), "tt-rep-empty")


# ---------------------------------------------------------------------------
# Página completa: estáticos UNA vez desde base_admin
# ---------------------------------------------------------------------------
def test_los_estaticos_se_cargan_una_vez_en_la_base(client_as, jefa, esc):
    c = client_as(jefa)
    pagina = _get(c, URL, tab="panorama", cohort=esc.c.id)
    assert pagina.count("/static/titulatec/css/admin/reports.css?v=") == 1
    assert pagina.count("/static/titulatec/js/admin/reports.js?v=") == 1
    parcial = _get(c, BODY, tab="panorama", cohort=esc.c.id)
    assert "reports.css" not in parcial and "reports.js" not in parcial
    # Las demás vistas admin también lo traen (la navegación morph no trae <head>).
    otra = _get(c, "/titulatec/admin/")
    assert otra.count("/static/titulatec/js/admin/reports.js?v=") == 1


def test_el_parcial_y_la_pagina_traen_el_mismo_cuerpo(client_as, jefa, esc):
    c = client_as(jefa)
    for url in (URL, BODY):
        doc = _doc(_get(c, url, tab="ritmo", cohort=esc.c.id))
        assert len(doc.xpath('//*[@id="tt-report-body"]')) == 1
        assert doc.xpath('//*[@id="tt-rep-daily"]')


# ---------------------------------------------------------------------------
# Macros sueltas: barra apilada (la usa Carreras en la Task 7b)
# ---------------------------------------------------------------------------
def test_macro_stacked_bar():
    from itcj2.apps.titulatec.pages.nav import titulatec_templates
    tpl = titulatec_templates.env.from_string(
        '{% from "titulatec/admin/partials/reports/_charts.html" import stacked_bar %}'
        '{{ stacked_bar("tt-x", segs, "Carrera X por etapa") }}')
    segs = [{"key": "docs", "label": "Documentos iniciales", "group": "documentos",
             "value": 3, "x_pct": 0.0, "w_pct": 75.0, "tip": "Documentos iniciales: 3"},
            {"key": "liberado", "label": "Liberado a Titulación", "group": "liberado",
             "value": 1, "x_pct": 75.0, "w_pct": 25.0, "tip": "Liberado a Titulación: 1"}]
    doc = _doc("<div>" + tpl.render(segs=segs) + "</div>")
    raiz = _by_id(doc, "tt-x")
    assert raiz.get("role") == "img" and raiz.get("aria-label")
    partes = _cls(raiz, "tt-rep-mark")
    assert [p.get("style") for p in partes] == ["width: 75.00%", "width: 25.00%"]
    assert [p.get("data-tt-tip") for p in partes] == ["Documentos iniciales: 3",
                                                      "Liberado a Titulación: 1"]
    assert "tt-rep-c--g-documentos" in partes[0].get("class")
    vacio = _doc("<div>" + tpl.render(segs=[]) + "</div>")
    assert _cls(vacio, "tt-rep-stack-empty")


def test_las_macros_del_brief_existen():
    fuente = (REPORTS_TPL / "_charts.html").read_text(encoding="utf-8")
    for nombre in ("stat_tile", "hbars", "stacked_bar", "line_chart", "sparkline",
                   "calendar_heat", "legend", "table_twin"):
        assert re.search(r"\{%-?\s*macro\s+" + nombre + r"\(", fuente), nombre


# ---------------------------------------------------------------------------
# Estáticos: CSS y JS
# ---------------------------------------------------------------------------
def test_css_de_reportes():
    css = CSS.read_text(encoding="utf-8")
    assert "@media print" in css
    assert "print-color-adjust: exact" in css
    assert "break-inside: avoid" in css
    # Texto nunca con `--tt-mute` (2.56:1).
    assert not re.search(r"(?<![-\w])color\s*:\s*var\(--tt-mute\)", css)
    # Identidad por actor y por grupo de etapa como variables (spec §7).
    for v in ("--tt-rep-a-escolares: #2a78d6", "--tt-rep-a-alumno: #eb6834",
              "--tt-rep-a-gtv: #1baf7a", "--tt-rep-a-biblioteca: #eda100",
              "--tt-rep-a-computo: #e87ba4", "--tt-rep-g-solicitud: #86b6ef",
              "--tt-rep-g-documentos: #3987e5", "--tt-rep-g-requisitos: #256abf",
              "--tt-rep-g-cita: #184f95", "--tt-rep-g-liberado: #0d366b"):
        assert v in css, v


def test_js_de_reportes_morph_safe_y_sin_innerhtml():
    js = JS.read_text(encoding="utf-8")
    assert js.lstrip().startswith("/*") and "(function" in js
    assert "innerHTML" not in js
    assert "textContent" in js
    assert "document.body.appendChild" in js                # tooltip hijo de <body>
    for evento in ("htmx:beforeRequest", "htmx:afterSettle", "DOMContentLoaded"):
        assert evento in js, evento
    assert "data-tt-print" in js and "window.print()" in js
    assert "data-tt-bound" in js
    assert not re.search(r"(?<![\w.])(confirm|alert|prompt)\(", js)
    assert "\r\n" not in js
