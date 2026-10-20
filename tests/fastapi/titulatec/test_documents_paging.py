"""Bandeja de Documentos paginada en DOS pasadas (spec 2026-10-04 §3.3 y §6).

Pasada 1 (`_doc_states`): el universo ligero -- procesos activos en alcance y
búsqueda, con sus estados de documento -- se filtra por pestaña, se ordena (FIFO
en «Por evaluar») y se cuenta en Python con las MISMAS funciones de siempre.
Pasada 2 (`_doc_present`): nombres, controles, carreras y tipos SOLO para las
filas de la página (y para el detalle seleccionado si cae fuera de ella).

Aislamiento: la jefa ve TODA la BD de dev, así que estas pruebas usan un
encargado acotado a una carrera recién creada (`escena`): su universo es solo lo
que crea el propio test. Las pruebas directas pasan `per_page=3` (Ruling R2);
las de ruta parchean `documents._body_ctx` con ese `per_page`.
"""
from __future__ import annotations

import functools
import itertools
import re
import uuid
from datetime import datetime, timedelta

import pytest

from tests.fastapi.titulatec.conftest import (
    INITIAL_DOC_TYPES, OFFICER_PERMS, POSGRADO_DOC_TYPES,
)
from tests.fastapi.titulatec.test_documents_inbox import _Contador

CODIGOS = ["birth_certificate", "high_school_cert", "curp"]
REVIEW_PERMS = ("titulatec.document.api.approve", "titulatec.document.api.reject")
URL = "/titulatec/admin/documents"
_SEQ = itertools.count(1)


@pytest.fixture()
def escena(seed_document_types, make_program, make_cohort, make_student,
           make_process, make_document, make_officer):
    """Carrera nueva + encargado acotado a ella + fábrica de procesos."""
    seed_document_types(types=INITIAL_DOC_TYPES + POSGRADO_DOC_TYPES)
    tag = uuid.uuid4().hex[:8]
    programa = make_program(f"Paginacion Docs {tag}")
    cohorte = make_cohort()

    class _Escena:
        program = programa
        cohort = cohorte

        @staticmethod
        def officer(perm_codes=OFFICER_PERMS, programs=None):
            user, _pos = make_officer(programs or [programa], perm_codes=perm_codes)
            return user

        @staticmethod
        def proc(estados=None, *, program=None, current_phase=1, control=None,
                 folio=None, first_name="ALUMNO", last_name="FICTICIO"):
            """`estados`: {codigo: review_status}; por omisión los 3 en pending."""
            alumno = make_student(control_number=control, first_name=first_name,
                                  last_name=last_name)
            proc = make_process(alumno, cohort=cohorte, program=program or programa,
                                current_phase=current_phase, folio=folio)
            for code, st in (estados or {c: "pending" for c in CODIGOS}).items():
                make_document(proc, type_code=code, review_status=st)
            return proc

    return _Escena


def _ctx(db, user, **kw):
    from itcj2.apps.titulatec.pages.documents import _body_ctx

    kw.setdefault("status_filter", None)
    kw.setdefault("selected_id", None)
    return _body_ctx(db, user_id=user.id, **kw)


def _ids(ctx):
    return [r["process_id"] for r in ctx["rows"]]


def _evento(db, proc, type_code, cuando):
    from itcj2.apps.titulatec.models import ProcessEvent

    db.add(ProcessEvent(process_id=proc.id, actor_id=None, event_type="document_uploaded",
                        phase_number=1, created_at=cuando,
                        payload={"type_code": type_code, "original_name": "d.pdf",
                                 "version": 1}))
    db.flush()


@pytest.fixture()
def tres_por_pagina(monkeypatch):
    """Las rutas llaman `_body_ctx` sin `per_page`: se fija aquí a 3."""
    from itcj2.apps.titulatec.pages import documents

    monkeypatch.setattr(documents, "_body_ctx",
                        functools.partial(documents._body_ctx, per_page=3))


def _filas_html(html):
    return [int(i) for i in re.findall(r'data-tt-docs-row="(\d+)"', html)]


# ---------------------------------------------------------------------------
# FIFO entre páginas
# ---------------------------------------------------------------------------
def test_por_evaluar_fifo_continua_entre_paginas(db_session, escena):
    oficial = escena.officer()
    base = datetime(2001, 1, 1, 9, 0)
    procs = [escena.proc({"birth_certificate": "pending"}) for _ in range(7)]
    # Llegadas en orden distinto al de creación (y al inverso): p6, p0, p5, ...
    orden_llegada = [procs[i] for i in (6, 0, 5, 1, 4, 2, 3)]
    for k, p in enumerate(orden_llegada):
        _evento(db_session, p, "birth_certificate", base + timedelta(hours=k))

    vistos = []
    for page in (1, 2, 3):
        vistos += _ids(_ctx(db_session, oficial, status_filter="pending",
                            page=page, per_page=3))

    assert vistos == [p.id for p in orden_llegada]
    ctx = _ctx(db_session, oficial, status_filter="pending", page=3, per_page=3)
    assert (ctx["page"].total, ctx["page"].page, ctx["page"].pages) == (7, 3, 3)
    assert len(ctx["rows"]) == 1


def test_resubida_va_al_final_tambien_paginado(db_session, escena):
    oficial = escena.officer()
    base = datetime(2001, 1, 1, 9, 0)
    p = [escena.proc({"birth_certificate": "pending"}) for _ in range(4)]
    for k, proc in enumerate(p):
        _evento(db_session, proc, "birth_certificate", base + timedelta(hours=k))
    # p[0] llegó primero, pero lo resubieron después de todos: su ÚLTIMA llegada manda.
    _evento(db_session, p[0], "birth_certificate", base + timedelta(days=3))

    pag1 = _ids(_ctx(db_session, oficial, status_filter="pending", page=1, per_page=3))
    pag2 = _ids(_ctx(db_session, oficial, status_filter="pending", page=2, per_page=3))

    assert pag1 == [p[1].id, p[2].id, p[3].id]
    assert pag2 == [p[0].id]


# ---------------------------------------------------------------------------
# Contadores del universo, no de la página
# ---------------------------------------------------------------------------
def test_total_pending_es_del_universo_no_de_la_pagina(db_session, escena):
    oficial = escena.officer()
    for _ in range(5):
        escena.proc()                                   # 3 pendientes cada uno
    escena.proc({c: "approved" for c in CODIGOS})       # 0 pendientes

    ctx = _ctx(db_session, oficial, page=1, per_page=3)

    assert len(ctx["rows"]) == 3
    assert ctx["page"].total == 6
    assert ctx["total_pending"] == 15


def test_alcance_parcial_no_cuenta_otra_carrera(db_session, escena, make_program):
    otra = make_program(f"Otra Carrera Docs {uuid.uuid4().hex[:8]}")
    oficial = escena.officer()
    mios = [escena.proc() for _ in range(2)]
    for _ in range(4):
        escena.proc(program=otra)

    for tab in (None, "pending"):
        ctx = _ctx(db_session, oficial, status_filter=tab, page=1, per_page=3)
        assert ctx["page"].total == 2, tab
        assert set(_ids(ctx)) == {p.id for p in mios}, tab
        assert ctx["total_pending"] == 6, tab


# ---------------------------------------------------------------------------
# ?selected= fuera de la página
# ---------------------------------------------------------------------------
def test_selected_fuera_de_la_pagina_se_pinta(db_session, escena, client_as, tres_por_pagina):
    oficial = escena.officer()
    procs = [escena.proc(folio=f"TT-SEL-{uuid.uuid4().hex[:6]}") for _ in range(5)]
    # «Todos»: created_at desc, id desc -> el primero creado cae en la página 2.
    lejano = procs[0]

    ctx = _ctx(db_session, oficial, selected_id=lejano.id, page=1, per_page=3)
    assert lejano.id not in _ids(ctx)
    assert ctx["detail"] is not None
    assert ctx["detail"]["process_id"] == lejano.id
    assert ctx["detail"]["folio"] == lejano.folio
    assert "phase_closed" in ctx["detail"]          # `_annotate_phase_lock` corrió

    html = client_as(oficial).get(f"{URL}/body", params={"selected": lejano.id}).text
    assert f'data-process="{lejano.id}"' in html
    assert lejano.folio in html
    assert lejano.id not in _filas_html(html)


def test_selected_fuera_del_universo_no_se_pinta(db_session, escena, make_program):
    otra = make_program(f"Ajena Docs {uuid.uuid4().hex[:8]}")
    oficial = escena.officer()
    escena.proc()
    completo = escena.proc({c: "approved" for c in CODIGOS})
    ajeno = escena.proc(program=otra)

    # Está en el alcance, pero no en la pestaña «Por evaluar».
    ctx = _ctx(db_session, oficial, status_filter="pending", selected_id=completo.id,
               per_page=3)
    assert ctx["detail"] is None
    # Fuera del alcance del encargado.
    ctx = _ctx(db_session, oficial, selected_id=ajeno.id, per_page=3)
    assert ctx["detail"] is None


# ---------------------------------------------------------------------------
# Búsqueda
# ---------------------------------------------------------------------------
def test_busqueda_por_control_minuscula_y_folio(db_session, escena):
    oficial = escena.officer()
    n = next(_SEQ)
    control = "B77%06d" % (uuid.uuid4().int % 1000000)
    folio = f"TT-PAGDOC-{uuid.uuid4().hex[:6].upper()}"
    buscado = escena.proc(control=control, first_name="ZACARIAS",
                          last_name=f"PAGINADO{n}")
    con_folio = escena.proc(folio=folio)
    escena.proc()

    assert _ids(_ctx(db_session, oficial, q=control.lower())) == [buscado.id]
    assert _ids(_ctx(db_session, oficial, q=f"  {control}  ")) == [buscado.id]
    assert _ids(_ctx(db_session, oficial, q=folio.lower())) == [con_folio.id]
    assert _ids(_ctx(db_session, oficial, q=f"paginado{n} zacarias")) == [buscado.id]
    assert _ids(_ctx(db_session, oficial, q=f"zacarias paginado{n}")) == [buscado.id]
    # `%` y `_` son literales, no comodines.
    ctx = _ctx(db_session, oficial, q="%")
    assert ctx["rows"] == [] and ctx["page"].total == 0
    assert _ids(_ctx(db_session, oficial, q="_")) == []
    assert _ctx(db_session, oficial, q=control.lower())["q"] == control.lower()


def test_busqueda_sin_resultados_documentos(db_session, escena, client_as):
    oficial = escena.officer()
    escena.proc()

    html = client_as(oficial).get(f"{URL}/body", params={"q": "<b>nadie"}).text

    assert 'Sin resultados para "&lt;b&gt;nadie"' in html
    assert "<b>nadie" not in html
    assert "tt-pager-range" not in html
    assert "Sin documentos por revisar" not in html


# ---------------------------------------------------------------------------
# Rutas: la acción y la página 2 conservan pestaña, página y búsqueda
# ---------------------------------------------------------------------------
def test_dictaminar_ultima_fila_ultima_pagina_repinta_valida(
        db_session, escena, client_as, seed_phase_defs, tres_por_pagina):
    seed_phase_defs()
    oficial = escena.officer(perm_codes=OFFICER_PERMS + REVIEW_PERMS)
    base = datetime(2001, 1, 1, 9, 0)
    procs = [escena.proc({"birth_certificate": "pending"}) for _ in range(3)]
    ultima = escena.proc({"birth_certificate": "approved", "high_school_cert": "approved",
                          "curp": "pending"})
    for k, p in enumerate(procs + [ultima]):
        _evento(db_session, p, "birth_certificate" if p is not ultima else "curp",
                base + timedelta(hours=k))

    resp = client_as(oficial).post(
        f"{URL}/{ultima.id}/document/review",
        data={"type_code": "curp", "action": "approve", "status": "pending",
              "page": "2", "q": ""})

    assert resp.status_code == 200, resp.headers.get("X-Tt-Error")
    assert _filas_html(resp.text) == [p.id for p in procs]
    assert "1–3 de 3" in resp.text
    assert "Sin documentos por revisar" not in resp.text
    # La fila dictaminada salió de «Por evaluar»: su detalle tampoco se pinta.
    assert f'data-process="{ultima.id}"' not in resp.text


def test_get_page_2_conserva_filtro(db_session, escena, client_as, tres_por_pagina):
    oficial = escena.officer()
    rechazados = [escena.proc({"birth_certificate": "rejected"}) for _ in range(4)]
    for _ in range(3):
        escena.proc()                                    # solo pendientes
    desc = sorted(rechazados, key=lambda p: p.id, reverse=True)

    html = client_as(oficial).get(f"{URL}/body?status=rejected&page=2").text

    assert _filas_html(html) == [desc[3].id]
    assert "4–4 de 4" in html
    filtros = re.search(r'<div[^>]*id="docs-filters".*?</div>\s*</div>', html, re.S).group(0)
    assert re.search(r'name="status"\s+value="rejected"', filtros)
    assert re.search(r'name="page"\s+value="1"', filtros)
    assert 'hx-include="#docs-filters"' in html
    # El pager pide la página 1 de ESA pestaña (el include lleva status=rejected).
    assert re.search(r'id="tt-docs-pager-prev"[^>]*hx-vals=\'\{"page": 1\}\'', html)


# ---------------------------------------------------------------------------
# Presupuesto de consultas
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("authz_congelada")    # un flush de Redis no mueve la cuenta
def test_presupuesto_de_consultas_igual_con_2_y_con_40(db_session, escena):
    oficial = escena.officer()
    for _ in range(2):
        escena.proc()
    _ctx(db_session, oficial, status_filter="pending")           # calienta authz
    with _Contador(db_session.get_bind()) as pocas:
        ctx2 = _ctx(db_session, oficial, status_filter="pending")

    for _ in range(38):
        escena.proc()
    with _Contador(db_session.get_bind()) as muchas:
        ctx40 = _ctx(db_session, oficial, status_filter="pending")

    assert len(ctx2["rows"]) == 2 and len(ctx40["rows"]) == 40
    assert len(pocas) == len(muchas), "\n".join(muchas.sentencias)
    for tabla in ("titulatec_documents ", "core_users", "titulatec_document_types",
                  "titulatec_process_events"):
        assert len(muchas.tocan(tabla)) == 1, (tabla, "\n".join(muchas.sentencias))


# ---------------------------------------------------------------------------
# R-G (posgrado) no cambia con la paginación
# ---------------------------------------------------------------------------
def test_posgrado_excused_sigue_igual_paginado(db_session, escena, make_program,
                                              seed_phase_defs):
    seed_phase_defs()
    maestria = make_program(f"Maestria Paginada {uuid.uuid4().hex[:8]}", level="maestria")
    oficial = escena.officer(programs=[escena.program, maestria])
    pasado = escena.proc({c: "approved" for c in CODIGOS}, program=maestria,
                         current_phase=3)
    en_fase = escena.proc({c: "pending" for c in CODIGOS}, program=maestria)

    completos = _ctx(db_session, oficial, status_filter="approved", per_page=1)
    assert _ids(completos) == [pasado.id]
    fila = completos["rows"][0]
    assert fila["all_approved"] is True and fila["pending"] == 0
    assert sorted(d["status"] for d in fila["docs"]).count("excused") == 4

    # «Todos» con 1 por página: en_fase (más nuevo) en la 1, pasado en la 2.
    pag1 = _ctx(db_session, oficial, page=1, per_page=1)
    pag2 = _ctx(db_session, oficial, page=2, per_page=1)
    assert _ids(pag1) == [en_fase.id] and _ids(pag2) == [pasado.id]
    # 3 subidos por evaluar + 4 extras sin subir (fase 1 en curso: no se
    # dispensan). Los sin subir esperan al alumno: no cuentan «por evaluar»
    # (2026-10-09; antes daba 7).
    assert pag1["rows"][0]["pending"] == 3
    assert pag1["rows"][0]["missing"] == 4
    assert pag1["total_pending"] == pag2["total_pending"] == 3


# ---------------------------------------------------------------------------
# Buscador con hx-preserve (fix Task 6, ronda 1)
# ---------------------------------------------------------------------------
def test_buscador_preservado_y_q_viaja(db_session, escena, client_as, tres_por_pagina):
    from tests.fastapi.titulatec.paging_asserts import (
        assert_buscador_preservado, assert_incluye_filtros,
    )

    oficial = escena.officer()
    for _ in range(4):
        escena.proc(first_name="LUCERO")
    cli = client_as(oficial)
    for url in (URL, f"{URL}/body"):
        html = cli.get(url, params={"q": "lucero"}).text
        assert_buscador_preservado(html, input_id="tt-docs-q",
                                   filters_id="docs-filters", q="lucero")
        nxt = re.search(r'<button[^>]*id="tt-docs-pager-next"[^>]*>', html, re.S).group(0)
        assert_incluye_filtros(nxt, "docs-filters")
        # Las pestañas toman `q` del mismo bloque.
        tabs = re.findall(r'<button class="btn btn-sm[^>]*hx-vals=\'\{"status"[^>]*>', html, re.S)
        assert tabs and all('hx-include="#docs-filters"' in t for t in tabs)
