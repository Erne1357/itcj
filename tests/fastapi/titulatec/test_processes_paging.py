"""Bandeja de Procesos paginada en DOS pasadas (spec 2026-10-04 §3.3 y §7).

Pasada 1 (`_proc_universe`): filas ligeras del universo en alcance (+ estado,
+ búsqueda) con `idle_days`/`idle_level` de la fase actual, en UNA consulta.
Sobre ellas, en Python y con la lógica de siempre: KPIs, filtro «atorados»,
fase, orden `created_at DESC, id DESC`, columnas del kanban.
Pasada 2 (`_proc_present`): alumno, carrera, modalidad y fase SOLO para las
filas visibles (la página de la tabla o las ≤N tarjetas de cada columna).

Aislamiento: la jefa ve TODA la BD de dev, así que estas pruebas usan un
encargado acotado a una carrera recién creada (`escena`). Las pruebas directas
pasan `per_page=3` (Ruling R2); las de ruta parchean `admin._proc_ctx`.
"""
from __future__ import annotations

import functools
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import itcj2.apps.titulatec as _tt_pkg
from tests.fastapi.titulatec.conftest import OFFICER_PERMS
from tests.fastapi.titulatec.test_documents_inbox import _Contador

URL = "/titulatec/admin/processes"
_APP = Path(_tt_pkg.__file__).resolve().parent


@pytest.fixture()
def escena(seed_phase_defs, make_program, make_cohort, make_student, make_process,
           make_officer, make_modality, db_session):
    """Carrera nueva + encargado acotado a ella + fábrica de procesos."""
    seed_phase_defs()
    tag = uuid.uuid4().hex[:8]
    programa = make_program(f"Paginacion Procesos {tag}")
    cohorte = make_cohort()
    modalidad = make_modality(name=f"Modalidad Paginacion {tag}")

    class _Escena:
        program = programa
        cohort = cohorte

        @staticmethod
        def officer(perm_codes=OFFICER_PERMS, programs=None):
            user, _pos = make_officer(programs or [programa], perm_codes=perm_codes)
            return user

        @staticmethod
        def proc(*, program=None, current_phase=1, status="active", control=None,
                 folio=None, first_name="ALUMNO", last_name="FICTICIO",
                 created_at=None, idle_days=None):
            """`idle_days`: cuántos días lleva la fase actual (None = recién)."""
            from itcj2.apps.titulatec.models import ProcessPhase

            alumno = make_student(control_number=control, first_name=first_name,
                                  last_name=last_name)
            proc = make_process(alumno, cohort=cohorte, program=program or programa,
                                modality=modalidad, current_phase=current_phase,
                                status=status, folio=folio)
            if created_at is not None:
                proc.created_at = created_at
            if idle_days is not None:
                fase = (db_session.query(ProcessPhase)
                        .filter_by(process_id=proc.id, phase_number=current_phase).one())
                fase.started_at = datetime.now() - timedelta(days=idle_days)
            db_session.flush()
            return proc

    return _Escena


def _ctx(db, user, **kw):
    from itcj2.apps.titulatec.pages.admin import _proc_ctx

    return _proc_ctx(db, user_id=user.id, **kw)


def _ids(ctx):
    return [r["id"] for r in ctx["rows"]]


@pytest.fixture()
def tres_por_pagina(monkeypatch):
    """La ruta llama `_proc_ctx` sin `per_page`: se fija aquí a 3."""
    from itcj2.apps.titulatec.pages import admin

    monkeypatch.setattr(admin, "_proc_ctx", functools.partial(admin._proc_ctx, per_page=3))


def _filas_html(html):
    return [int(i) for i in re.findall(r'id="proc-row-(\d+)"', html)]


def _tarjetas_html(html):
    return [int(i) for i in re.findall(r'id="proc-card-(\d+)"', html)]


# ---------------------------------------------------------------------------
# Orden total entre páginas
# ---------------------------------------------------------------------------
def test_tabla_desc_continua_entre_paginas(db_session, escena):
    oficial = escena.officer()
    base = datetime(2001, 1, 1, 9, 0)
    # Dos empates de created_at: el desempate `id DESC` decide.
    fechas = [base, base + timedelta(days=1), base + timedelta(days=1), base,
              base + timedelta(days=5), base + timedelta(days=2), base + timedelta(days=1)]
    procs = [escena.proc(created_at=f) for f in fechas]
    esperado = [p.id for p in sorted(procs, key=lambda p: (p.created_at, p.id), reverse=True)]

    vistos = []
    for page in (1, 2, 3):
        ctx = _ctx(db_session, oficial, page=page, per_page=3)
        vistos += _ids(ctx)

    assert vistos == esperado
    assert (ctx["page"].total, ctx["page"].page, ctx["page"].pages) == (7, 3, 3)
    # Fuera de rango -> la última válida.
    assert _ids(_ctx(db_session, oficial, page=99, per_page=3)) == esperado[6:]


# ---------------------------------------------------------------------------
# KPIs del universo, no de la página
# ---------------------------------------------------------------------------
def test_kpis_del_universo_no_de_la_pagina(db_session, escena):
    oficial = escena.officer()
    for _ in range(4):
        escena.proc(current_phase=1)
    escena.proc(current_phase=3, idle_days=40, folio=f"TT-KPI-{uuid.uuid4().hex[:6]}")
    escena.proc(status="completed", current_phase=8)
    escena.proc(status="cancelled")

    esperado = {"total": 6, "active": 5, "completed": 1, "on_hold": 0, "cancelled": 1,
                "pct_completed": 17, "n_stuck": 1}
    base = _ctx(db_session, oficial, page=1, per_page=3)
    assert base["kpis"] == esperado
    # Ni la página, ni la búsqueda, ni la fase, ni «atorados» mueven los KPIs.
    for kw in ({"page": 2}, {"q": "TT-KPI"}, {"phase": 3}, {"stuck": 1},
               {"view": "board"}):
        assert _ctx(db_session, oficial, per_page=3, **kw)["kpis"] == esperado, kw


def test_stuck_pagina_sobre_atorados(db_session, escena):
    oficial = escena.officer()
    atorados = [escena.proc(idle_days=30 + k) for k in range(5)]
    for _ in range(3):
        escena.proc(idle_days=1)
    # Una revocada nunca está atorada, por vieja que sea.
    escena.proc(status="cancelled", idle_days=90)

    p1 = _ctx(db_session, oficial, stuck=1, page=1, per_page=3)
    p2 = _ctx(db_session, oficial, stuck=1, page=2, per_page=3)

    assert (p1["page"].total, p1["page"].pages) == (5, 2)
    assert set(_ids(p1) + _ids(p2)) == {p.id for p in atorados}
    assert len(_ids(p2)) == 2
    assert all(r["idle_level"] == "crit" for r in p1["rows"] + p2["rows"])
    assert p1["kpis"]["n_stuck"] == 5


# ---------------------------------------------------------------------------
# Búsqueda en servidor
# ---------------------------------------------------------------------------
def test_busqueda_servidor_nombre_control_folio(db_session, escena):
    oficial = escena.officer()
    tag = uuid.uuid4().hex[:6].upper()
    control = f"B{uuid.uuid4().int % 10**8:08d}"
    por_control = escena.proc(control=control)
    por_nombre = escena.proc(first_name=f"ANDREA{tag}", last_name="SOLIS")
    por_folio = escena.proc(folio=f"TT-Q-{tag}")
    escena.proc()

    def _q(q, **kw):
        return set(_ids(_ctx(db_session, oficial, q=q, **kw)))

    assert _q(control.lower()) == {por_control.id}           # minúscula -> MAYÚSCULA
    assert _q(f"andrea{tag.lower()}") == {por_nombre.id}
    assert _q(f"SOLIS ANDREA{tag}") == {por_nombre.id}         # paterno primero
    assert _q(f"q-{tag.lower()}") == {por_folio.id}
    assert _q("%") == set()                                    # `%` no comodinea
    assert _q("_") == set()
    # La búsqueda se aplica ANTES de paginar: el total es el de los resultados.
    ctx = _ctx(db_session, oficial, q=control, per_page=3)
    assert ctx["page"].total == 1
    assert ctx["q"] == control


def test_busqueda_sin_resultados_procesos(escena, client_as):
    oficial = escena.officer()
    escena.proc()
    html = client_as(oficial).get(URL, params={"q": "<b>nadie"}).text

    assert 'Sin resultados para "&lt;b&gt;nadie"' in html
    assert 'id="tt-proc-pager' not in html
    assert _filas_html(html) == []


# ---------------------------------------------------------------------------
# Alcance parcial
# ---------------------------------------------------------------------------
def test_alcance_parcial_totales_y_kpis(db_session, escena, make_program):
    otra = make_program(f"Otra Carrera Procesos {uuid.uuid4().hex[:8]}")
    oficial = escena.officer()
    mios = [escena.proc() for _ in range(2)]
    for _ in range(4):
        escena.proc(program=otra, idle_days=60)
        escena.proc(program=otra, status="completed")

    for kw in ({}, {"view": "board"}, {"stuck": 1}, {"q": "ALUMNO"}):
        ctx = _ctx(db_session, oficial, per_page=3, **kw)
        assert ctx["kpis"]["total"] == 2, kw
        assert ctx["kpis"]["completed"] == 0 and ctx["kpis"]["n_stuck"] == 0, kw
        assert sum(c["count"] for c in ctx["columns"]) == (0 if kw.get("stuck") else 2), kw
        if kw.get("view") != "board":
            assert ctx["page"].total == (0 if kw.get("stuck") else 2), kw
            assert set(_ids(ctx)) <= {p.id for p in mios}, kw


# ---------------------------------------------------------------------------
# Ruta: la página 2 es la continuación de ESA vista
# ---------------------------------------------------------------------------
def test_get_page_2_conserva_status_stuck_q_view(db_session, escena, client_as,
                                                 tres_por_pagina):
    oficial = escena.officer()
    tag = uuid.uuid4().hex[:6].upper()
    base = datetime(2001, 1, 1, 9, 0)
    buenos = [escena.proc(first_name=f"PAGINA{tag}", idle_days=40,
                          created_at=base + timedelta(days=k)) for k in range(5)]
    # Ruido que cada filtro debe dejar fuera.
    escena.proc(first_name=f"PAGINA{tag}", idle_days=1)                     # stuck
    escena.proc(first_name=f"PAGINA{tag}", idle_days=40, status="on_hold")  # status
    escena.proc(first_name="OTRONOMBRE", idle_days=40)                      # q
    esperado = [p.id for p in sorted(buenos, key=lambda p: p.created_at, reverse=True)]

    cli = client_as(oficial)
    filtros = {"view": "table", "status": "active", "stuck": "1", "q": f"pagina{tag}"}
    p1 = cli.get(URL, params=filtros).text
    p2 = cli.get(URL, params={**filtros, "page": "2"}).text

    assert _filas_html(p1) == esperado[:3]
    assert _filas_html(p2) == esperado[3:]
    # El pager arrastra el formulario de filtros con todos sus valores...
    assert 'hx-include="#proc-filters"' in p1
    for nombre, valor in (("status", "active"), ("stuck", "1"), ("view", "table"),
                          ("q", f"pagina{tag}")):
        assert re.search(r'name="%s" value="%s"' % (nombre, re.escape(valor)), p1), nombre
    assert re.search(r'name="page" value="1"', p1)
    # ...y respeta el contrato de swap de la vista (select == target => outerHTML).
    pager = re.search(r'<button[^>]*id="tt-proc-pager-next"[^>]*>', p1, re.S).group(0)
    assert 'hx-target="#tt-admin-content"' in pager
    assert 'hx-select="#tt-admin-content"' in pager
    assert 'hx-swap="morph:outerHTML"' in pager
    assert 'hx-push-url="true"' in pager
    buscador = re.search(r'<input[^>]*name="q"[^>]*>', p1, re.S).group(0)
    assert 'hx-select="#tt-admin-content"' in buscador
    assert 'hx-target="#tt-admin-content"' in buscador
    assert 'hx-swap="morph:outerHTML"' in buscador
    assert 'hx-include="#proc-filters"' in buscador
    assert "keyup changed delay:400ms, search" in buscador


# ---------------------------------------------------------------------------
# Kanban acotado por columna
# ---------------------------------------------------------------------------
def test_kanban_columna_con_mas_de_50_muestra_50_y_cuenta_real(db_session, escena,
                                                               client_as, tres_por_pagina):
    oficial = escena.officer()
    base = datetime(2001, 1, 1, 9, 0)
    fase2 = [escena.proc(current_phase=2, created_at=base + timedelta(days=k))
             for k in range(5)]
    escena.proc(current_phase=4)

    ctx = _ctx(db_session, oficial, view="board", per_page=3)
    cols = {c["phase"]: c for c in ctx["columns"]}
    assert cols[2]["count"] == 5
    assert [r["id"] for r in cols[2]["rows"]] == [p.id for p in reversed(fase2)][:3]
    assert cols[2]["more"] is True
    assert cols[4]["count"] == 1 and cols[4]["more"] is False
    assert "view=table" in cols[2]["table_url"] and "phase=2" in cols[2]["table_url"]

    html = client_as(oficial).get(URL, params={"view": "board"}).text
    assert sorted(_tarjetas_html(html)) == sorted(
        [r["id"] for r in cols[2]["rows"]] + [r["id"] for r in cols[4]["rows"]])
    assert "Ver las 5 en tabla" in html
    assert html.count("Ver las ") == 1


def test_con_el_tope_por_defecto_la_columna_pinta_50(db_session, escena):
    from itcj2.apps.titulatec.utils.paging import PAGE_SIZE

    oficial = escena.officer()
    for _ in range(PAGE_SIZE + 1):
        escena.proc(current_phase=2)

    col = {c["phase"]: c for c in _ctx(db_session, oficial, view="board")["columns"]}[2]
    assert (col["count"], len(col["rows"]), col["more"]) == (PAGE_SIZE + 1, PAGE_SIZE, True)


def test_ver_todas_filtra_por_fase(db_session, escena, client_as, tres_por_pagina):
    oficial = escena.officer()
    fase2 = [escena.proc(current_phase=2) for _ in range(5)]
    otros = [escena.proc(current_phase=k) for k in (1, 3)]

    ctx = _ctx(db_session, oficial, view="board", stuck=0, q="ALUMNO", per_page=3)
    url = {c["phase"]: c for c in ctx["columns"]}[2]["table_url"]
    assert "q=ALUMNO" in url                      # arrastra los filtros vigentes

    cli = client_as(oficial)
    p1 = cli.get(url).text
    p2 = cli.get(url + "&page=2").text
    assert set(_filas_html(p1) + _filas_html(p2)) == {p.id for p in fase2}
    assert not set(_filas_html(p1) + _filas_html(p2)) & {p.id for p in otros}

    tabla = _ctx(db_session, oficial, phase=2, per_page=3)
    assert tabla["page"].total == 5
    assert tabla["phase"] == 2
    # La franja del funnel sigue mostrando todas las fases (el filtro es de la tabla).
    assert sum(c["count"] for c in tabla["columns"]) == 7


# ---------------------------------------------------------------------------
# Presupuesto de consultas
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("view", ["table", "board"])
@pytest.mark.usefixtures("authz_congelada")    # un flush de Redis no mueve la cuenta
def test_sin_n_mas_1_usuario_y_carrera(db_session, escena, view):
    oficial = escena.officer()
    for _ in range(3):
        escena.proc()
    _ctx(db_session, oficial, view=view)                 # calienta authz
    with _Contador(db_session.get_bind()) as pocas:
        ctx3 = _ctx(db_session, oficial, view=view)

    for k in range(37):
        escena.proc(current_phase=k % 9)
    with _Contador(db_session.get_bind()) as muchas:
        ctx40 = _ctx(db_session, oficial, view=view)

    visibles = (len(ctx3["rows"]), len(ctx40["rows"])) if view == "table" else (
        sum(len(c["rows"]) for c in ctx3["columns"]),
        sum(len(c["rows"]) for c in ctx40["columns"]))
    assert visibles == (3, 40)
    sql = "\n".join(muchas.sentencias)
    assert len(pocas) == len(muchas), sql
    # Medido: app + alcance (2) + universo + fases + alumnos + carreras +
    # modalidades = 8 (sin `q` no hay la consulta de ids que casan).
    assert len(muchas) == 8, sql
    # Pasada 2 en lote: UNA lectura de alumnos, carreras y modalidades.
    for entidad in ("core_users", "core_programs", "titulatec_modalities"):
        assert len([s for s in muchas.sentencias
                    if s.startswith("SELECT %s." % entidad)]) == 1, (entidad, sql)
    # El `started_at` de la fase actual viaja en la consulta del universo.
    assert len(muchas.tocan("titulatec_process_phases ")) == 1, sql


# ---------------------------------------------------------------------------
# El filtro de cliente ya no existe
# ---------------------------------------------------------------------------
def test_js_ya_no_filtra_en_cliente():
    js = (_APP / "static" / "js" / "admin" / "processes.js").read_text(encoding="utf-8")
    tpl = (_APP / "templates" / "titulatec" / "admin" / "processes.html").read_text(
        encoding="utf-8")

    assert "data-search" not in tpl
    assert "dataset.search" not in js and "data-search" not in js
    assert "proc-search" not in js, "el buscador ya no lo atiende el cliente"
    assert "estado.fase" not in js, "la fase la filtra el servidor (?phase=)"
    # Lo que sí sigue siendo de cliente: orden de la página y alto del kanban.
    assert "th.sortable" in js and "medirTablero" in js


# ---------------------------------------------------------------------------
# Buscador con hx-preserve y tablero sin resultados (fix ronda 1)
# ---------------------------------------------------------------------------
def test_buscador_preservado_y_q_viaja(db_session, escena, client_as, tres_por_pagina):
    from tests.fastapi.titulatec.paging_asserts import (
        assert_buscador_preservado, assert_incluye_filtros,
    )

    oficial = escena.officer()
    for _ in range(4):
        escena.proc(first_name="LUCERO")
    html = client_as(oficial).get(URL, params={"q": "lucero"}).text

    assert_buscador_preservado(html, input_id="proc-q", filters_id="proc-filters",
                               q="lucero")
    nxt = re.search(r'<button[^>]*id="tt-proc-pager-next"[^>]*>', html, re.S).group(0)
    assert_incluye_filtros(nxt, "proc-filters")
    # Los enlaces de filtro (chips, vista, funnel) llevan `q` en su URL.
    for ctl in ("proc-chip-active", "proc-view-board", "proc-seg-1"):
        tag = re.search(r'<a[^>]*id="%s"[^>]*>' % ctl, html, re.S).group(0)
        assert "q=lucero" in tag, ctl


def test_el_js_repone_el_buscador_preservado_si_no_tiene_foco():
    js = (_APP / "static" / "js" / "shared" / "titulatec-utils.js").read_text(encoding="utf-8")
    cuerpo = js.split("function _syncPreservedSearch", 1)[1].split("}\n  document", 1)[0]
    assert "data-tt-q-server" in cuerpo
    assert 'input[name="q"][hx-preserve]' in cuerpo
    assert "document.activeElement" in cuerpo
    assert "htmx:afterSettle', _syncPreservedSearch" in js
    # Sin `moveBefore` (Firefox/Safari) htmx re-inserta el nodo y pierde el foco:
    # se repone en afterSwap, antes del settle.
    foco = js.split("var _qFoco = null;", 1)[1]
    assert "htmx:beforeSwap" in foco and "htmx:afterSwap" in foco
    assert "el.focus(" in foco and "setSelectionRange" in foco


def test_busqueda_sin_resultados_en_tablero(escena, client_as):
    oficial = escena.officer()
    escena.proc(current_phase=2)
    html = client_as(oficial).get(URL, params={"view": "board", "q": "<b>nadie"}).text

    assert 'id="proc-board-no-results"' in html
    assert 'Sin resultados para "&lt;b&gt;nadie"' in html
    assert "<b>nadie" not in html
    assert 'id="proc-board"' not in html          # sin las 9 columnas de «—»

    # Con resultados el tablero sigue ahí.
    con = client_as(oficial).get(URL, params={"view": "board", "q": "ALUMNO"}).text
    assert 'id="proc-board"' in con and 'id="proc-board-no-results"' not in con
