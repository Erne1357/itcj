"""Bandeja de solicitudes paginada (spec 2026-10-04 §3.3 y §4).

Sin el tope de 300: `_body_ctx` pagina con `paginate_query` y conserva los tres
órdenes de hoy (FIFO por `created_at` en «Por revisar», FIFO por `reviewed_at`
en «En Cómputo», historial DESC en el resto), siempre con desempate por `id`.
La búsqueda (`enrollment_request_search`, que reutiliza Accesos) y el contador
por pestaña operan sobre el MISMO alcance por carrera y la misma convocatoria;
los KPIs siguen siendo el universo sin pestaña, sin búsqueda y sin página.

Las pruebas que van directo a `_body_ctx` le pasan `per_page=3` (Ruling R2);
las de ruta parchean `requests_admin._body_ctx` con ese `per_page`, porque las
rutas la llaman sin él.
"""
from __future__ import annotations

import functools
import re
from datetime import datetime, timedelta

import pytest

from tests.fastapi.titulatec.test_enrollment_inbox import (
    LIST_PERMS, OFFICER_LIST_PERMS, URL, _cuenta, _fila, _make_req, _pestana_activa,
)


def _ctx(db, user, **kw):
    from itcj2.apps.titulatec.pages.requests_admin import _body_ctx

    kw.setdefault("status", "pending_review")
    kw.setdefault("cohort_id", None)
    return _body_ctx(db, user_id=user.id, **kw)


def _ids(ctx):
    return [r["id"] for r in ctx["rows"]]


def _todas_las_paginas(db, user, *, pages, **kw):
    vistos = []
    for p in range(1, pages + 1):
        vistos += _ids(_ctx(db, user, page=p, per_page=3, **kw))
    return vistos


@pytest.fixture()
def tres_por_pagina(monkeypatch):
    """Las rutas llaman `_body_ctx` sin `per_page`: se la fija aquí a 3."""
    from itcj2.apps.titulatec.pages import requests_admin

    monkeypatch.setattr(requests_admin, "_body_ctx",
                        functools.partial(requests_admin._body_ctx, per_page=3))


# ---------------------------------------------------------------------------
# Orden total entre páginas
# ---------------------------------------------------------------------------
def test_por_revisar_fifo_continua_entre_paginas(db_session, make_head, make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    base = datetime(2001, 1, 1, 9, 0)
    # El id va al revés del created_at (la primera creada es la más nueva) y
    # dos comparten created_at: solo el desempate por `id` las ordena.
    reqs = [_make_req(db_session, cohort, control=f"9970{i:04d}",
                      created_at=base + timedelta(days=7 - min(i, 6)))
            for i in range(7)]
    esperado = [r.id for r in sorted(reqs, key=lambda r: (r.created_at, r.id))]

    vistos = _todas_las_paginas(db_session, head, pages=3, cohort_id=cohort.id)

    assert vistos == esperado
    ctx = _ctx(db_session, head, cohort_id=cohort.id, page=3, per_page=3)
    assert (ctx["page"].total, ctx["page"].page, ctx["page"].pages) == (7, 3, 3)


def test_en_computo_fifo_por_reviewed_at_entre_paginas(db_session, make_head, make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    reqs = [_make_req(db_session, cohort, control=f"9971{i:04d}", status="awaiting_access",
                      created_at=datetime(2001, 1, 1 + i, 9, 0),
                      reviewed_at=datetime(2001, 3, 10 - i, 9, 0))
            for i in range(7)]
    esperado = [r.id for r in sorted(reqs, key=lambda r: (r.reviewed_at, r.id))]

    vistos = _todas_las_paginas(db_session, head, pages=3, status="awaiting_access",
                                cohort_id=cohort.id)

    assert vistos == esperado


def test_historial_desc_entre_paginas(db_session, make_head, make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    reqs = [_make_req(db_session, cohort, control=f"9972{i:04d}", status="rejected",
                      created_at=datetime(2001, 1, 1 + min(i, 5), 9, 0))
            for i in range(7)]
    esperado = [r.id for r in sorted(reqs, key=lambda r: (r.created_at, r.id), reverse=True)]

    vistos = _todas_las_paginas(db_session, head, pages=3, status="rejected",
                                cohort_id=cohort.id)

    assert vistos == esperado


def test_ya_no_hay_tope_de_300(db_session, make_head, make_cohort):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    db_session.add_all([
        EnrollmentRequest(cohort_id=cohort.id, control_number=f"973{i:05d}",
                          first_name="EGRESADO", last_name="MASIVO", program_text="X",
                          phone="6561234567", contact_email="m@example.invalid",
                          has_efirma=False, kind="unknown", status="pending_review",
                          verify_send_count=0)
        for i in range(301)])
    db_session.flush()

    ctx = _ctx(db_session, head, cohort_id=cohort.id, page=7)

    assert ctx["page"].per_page == 50
    assert ctx["page"].total == 301
    assert ctx["page"].page == 7
    assert len(ctx["rows"]) == 1
    assert ctx["tab_counts"]["pending_review"] == 301


# ---------------------------------------------------------------------------
# Contador por pestaña y búsqueda
# ---------------------------------------------------------------------------
def test_contador_por_pestana_respeta_alcance_y_busqueda(
    client_as, db_session, make_officer, make_program, make_cohort,
):
    propia = make_program("Carrera propia paginacion")
    ajena = make_program("Carrera ajena paginacion")
    officer, _pos = make_officer([propia], perm_codes=OFFICER_LIST_PERMS)
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99740001", program_id=propia.id,
              first_name="ZAPATERO")
    _make_req(db_session, cohort, control="99740002", program_id=propia.id,
              status="unverified")
    _make_req(db_session, cohort, control="99740003", program_id=propia.id,
              status="rejected")
    _make_req(db_session, cohort, control="99740004", program_id=ajena.id,
              first_name="ZAPATERO")
    _make_req(db_session, cohort, control="99740005", program_id=ajena.id,
              status="rejected")

    ctx = _ctx(db_session, officer, page=1, per_page=3)
    assert ctx["tab_counts"] == {"pending_review": 2, "awaiting_access": 0, "approved": 0,
                                 "converted": 0, "rejected": 1, "all": 3}
    assert ctx["page"].total == 2

    ctx = _ctx(db_session, officer, q="zapatero", per_page=3)
    assert ctx["tab_counts"]["pending_review"] == 1
    assert ctx["tab_counts"]["all"] == 1
    assert ctx["tab_counts"]["rejected"] == 0
    assert ctx["page"].total == 1

    html = client_as(officer).get(f"{URL}/body").text
    boton = re.search(r'<button id="tt-req-tab-pending_review".*?</button>', html, re.S).group(0)
    assert "(2)" in boton
    boton = re.search(r'<button id="tt-req-tab-all".*?</button>', html, re.S).group(0)
    assert "(3)" in boton


def test_busqueda_control_minuscula_y_porcentaje(db_session, make_head, make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    con_letra = _make_req(db_session, cohort, control="B20111234")
    _make_req(db_session, cohort, control="99750001")

    ctx = _ctx(db_session, head, cohort_id=cohort.id, q="  b20111234  ")
    assert _ids(ctx) == [con_letra.id]
    assert ctx["q"] == "b20111234"

    for comodin in ("%", "_", "\\"):
        ctx = _ctx(db_session, head, cohort_id=cohort.id, q=comodin)
        assert ctx["page"].total == 0, comodin
        assert ctx["tab_counts"]["all"] == 0, comodin


def test_busqueda_por_nombre_y_correo(db_session, make_head, make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99751001", first_name="ROSA",
                    last_name="PEREZ", middle_name="LUNA", email="rosa.luna@example.invalid")
    _make_req(db_session, cohort, control="99751002")

    for q in ("rosa perez", "perez luna rosa", "ROSA.LUNA@"):
        assert _ids(_ctx(db_session, head, cohort_id=cohort.id, q=q)) == [req.id], q


def test_busqueda_por_folio_de_inscrita(
    db_session, make_head, make_cohort, make_student, make_process,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    proc = make_process(make_student(control_number="99752001"), cohort=cohort,
                        folio="TT-ZQ-98765", phases=False, library_clearance=None)
    inscrita = _make_req(db_session, cohort, control="99752001", status="converted",
                         converted_process_id=proc.id)
    otro = make_process(make_student(control_number="99752002"), cohort=cohort,
                        phases=False, library_clearance=None)
    _make_req(db_session, cohort, control="99752002", status="converted",
              converted_process_id=otro.id)

    ctx = _ctx(db_session, head, status="converted", cohort_id=cohort.id, q="zq-9876")

    assert _ids(ctx) == [inscrita.id]


def test_busqueda_sin_resultados_solicitudes(client_as, db_session, make_head, make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99753001")

    html = client_as(head).get(
        f"{URL}/body", params={"cohort_id": cohort.id, "q": "<b>nadie"}).text

    assert 'Sin resultados para "&lt;b&gt;nadie"' in html
    assert "<b>nadie" not in html
    assert "tt-pager-range" not in html
    assert "Bandeja limpia" not in html


def test_kpis_no_cambian_con_pagina_ni_busqueda(db_session, make_head, make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    for i, st in enumerate(("pending_review", "pending_review", "pending_review",
                            "approved", "rejected")):
        _make_req(db_session, cohort, control=f"9976{i:04d}", status=st)

    base = _ctx(db_session, head, cohort_id=cohort.id)
    pagina = _ctx(db_session, head, cohort_id=cohort.id, page=2, per_page=2)
    busqueda = _ctx(db_session, head, cohort_id=cohort.id, q="no-existe-nadie")

    assert base["kpis"]["total"] == 5
    assert pagina["kpis"] == base["kpis"] == busqueda["kpis"]
    assert pagina["by_year"] == base["by_year"] == busqueda["by_year"]


# ---------------------------------------------------------------------------
# Rutas: la página y los filtros viajan
# ---------------------------------------------------------------------------
def test_aprobar_ultima_fila_de_ultima_pagina_repinta_pagina_valida(
    client_as, db_session, make_head, make_cohort, seed_phase_defs, titulatec_app,
    tres_por_pagina,
):
    seed_phase_defs()
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    reqs = [_make_req(db_session, cohort, control=f"9977{i:04d}",
                      created_at=datetime(2001, 1, 1 + i, 9, 0))
            for i in range(4)]
    ultima = reqs[-1]

    resp = client_as(head).post(
        f"{URL}/{ultima.id}/aprobar",
        data={"program_id": "", "status": "pending_review", "cohort_id": str(cohort.id),
              "page": "2", "q": ""})

    assert resp.status_code == 200, resp.headers.get("X-Tt-Error")
    assert _pestana_activa(resp.text) == "pending_review"
    assert f'id="tt-req-{ultima.id}"' not in resp.text
    for r in reqs[:3]:
        assert f'id="tt-req-{r.id}"' in resp.text
    assert "1–3 de 3" in resp.text
    assert "Bandeja limpia" not in resp.text


def test_get_page_2_conserva_pestana_y_cohort(
    client_as, db_session, make_head, make_cohort, tres_por_pagina,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    otra = make_cohort(status="open")
    reqs = [_make_req(db_session, cohort, control=f"9978{i:04d}", status="rejected",
                      created_at=datetime(2001, 1, 1 + i, 9, 0))
            for i in range(5)]
    _make_req(db_session, otra, control="99789999", status="rejected",
              created_at=datetime(2000, 1, 1, 9, 0))
    desc = sorted(reqs, key=lambda r: (r.created_at, r.id), reverse=True)

    html = client_as(head).get(
        f"{URL}/body?status=rejected&cohort_id={cohort.id}&page=2").text

    assert _pestana_activa(html) == "rejected"
    visibles = [int(i) for i in re.findall(r'<tr id="tt-req-(\d+)"', html)]
    assert visibles == [r.id for r in desc[3:]]
    assert "4–5 de 5" in html
    # Un <div> (no <form>: el modo alterno no lleva formularios); sus campos
    # ocultos van antes de la caja de búsqueda.
    filtros = re.search(r'<div[^>]*id="tt-req-filters".*?<div class="tt-search">',
                        html, re.S).group(0)
    assert re.search(r'name="status"\s+value="rejected"', filtros)
    assert re.search(rf'name="cohort_id"\s+value="{cohort.id}"', filtros)
    assert re.search(r'name="page"\s+value="1"', filtros)
    prev = re.search(r'<button[^>]*id="tt-req-pager-prev"[^>]*>', html, re.S).group(0)
    assert 'hx-include="#tt-req-filters"' in prev
    assert '"page": 1' in prev
    # Las acciones de fila mandan de vuelta la página.
    fila = _fila(html, desc[3])
    assert "<form" not in fila or re.search(r'name="page"\s+value="2"', fila)


def test_las_formas_de_fila_llevan_page_y_q(
    client_as, db_session, make_head, make_cohort, tres_por_pagina,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    reqs = [_make_req(db_session, cohort, control=f"9979{i:04d}", first_name="LUCERO",
                      created_at=datetime(2001, 1, 1 + i, 9, 0))
            for i in range(4)]

    html = client_as(head).get(
        f"{URL}/body", params={"cohort_id": cohort.id, "q": "lucero", "page": 2}).text

    fila = _fila(html, reqs[3])
    formularios = re.findall(r"<form.*?</form>", fila, flags=re.S)
    assert formularios
    for form in formularios:
        assert re.search(r'name="page"\s+value="2"', form), form
        assert re.search(r'name="q"\s+value="lucero"', form), form
    # Cambiar de pestaña conserva la búsqueda y vuelve a la página 1.
    tab = re.search(r'<button id="tt-req-tab-rejected"[^>]*>', html).group(0)
    assert "q=lucero" in tab
    assert "page=" not in tab


# ---------------------------------------------------------------------------
# Presupuesto de consultas y lote de revocaciones
# ---------------------------------------------------------------------------
def _sembrar(db_session, cohort, n, prefijo, make_student, make_process):
    from itcj2.apps.titulatec.models import ProcessEvent

    for i in range(n):
        control = f"{prefijo}{i:04d}"
        if i % 2:
            proc = make_process(make_student(control_number=control), cohort=cohort,
                                status="cancelled", phases=False, library_clearance=None)
            db_session.add(ProcessEvent(process_id=proc.id, event_type="process_cancelled",
                                        payload={"reason": f"motivo {i}"}))
            _make_req(db_session, cohort, control=control, status="converted",
                      converted_process_id=proc.id)
        else:
            _cuenta(db_session, control)
            _make_req(db_session, cohort, control=control, status="rejected")
    db_session.flush()


@pytest.mark.usefixtures("authz_congelada")    # un flush de Redis no mueve la cuenta
def test_consultas_fijas_con_3_y_con_40(
    client_as, db_session, make_head, make_cohort, make_student, make_process,
):
    from sqlalchemy import event

    head = make_head(perm_codes=LIST_PERMS)
    chica, grande = make_cohort(status="open"), make_cohort(status="open")
    _sembrar(db_session, chica, 3, "9980", make_student, make_process)
    _sembrar(db_session, grande, 40, "9981", make_student, make_process)
    c = client_as(head)
    engine = db_session.get_bind()

    def _medir(cohort_id):
        sentencias = []

        def _cuenta_sql(conn, cursor, statement, *a):
            sentencias.append(statement)

        event.listen(engine, "before_cursor_execute", _cuenta_sql)
        try:
            resp = c.get(f"{URL}/body?status=all&cohort_id={cohort_id}")
        finally:
            event.remove(engine, "before_cursor_execute", _cuenta_sql)
        assert resp.status_code == 200
        return resp, sentencias

    _medir(chica.id)                      # calienta cachés de authz
    resp_chica, con_3 = _medir(chica.id)
    resp_grande, con_40 = _medir(grande.id)

    assert len(re.findall(r'<tr id="tt-req-', resp_grande.text)) == 40
    assert "Inscripción" in resp_grande.text and "motivo 1" in resp_grande.text
    assert len(con_40) == len(con_3), (len(con_3), len(con_40))


def test_cancellation_info_map_equivale_a_cancellation_info(
    db_session, make_cohort, make_student, make_process,
):
    from itcj2.apps.titulatec.models import ProcessEvent
    from itcj2.apps.titulatec.services.process_service import ProcessService

    cohort = make_cohort(status="open")

    def _proc(control, status):
        return make_process(make_student(control_number=control), cohort=cohort,
                            status=status, phases=False, library_clearance=None)

    dos_eventos = _proc("99820001", "cancelled")
    sin_evento = _proc("99820002", "cancelled")
    activo_con_evento = _proc("99820003", "active")
    misma_hora = _proc("99820004", "cancelled")
    t = datetime(2001, 1, 1, 9, 0)
    db_session.add_all([
        ProcessEvent(process_id=dos_eventos.id, event_type="process_cancelled",
                     payload={"reason": "viejo"}, created_at=t),
        ProcessEvent(process_id=dos_eventos.id, event_type="process_cancelled",
                     payload={"reason": "nuevo"}, created_at=t + timedelta(days=1)),
        ProcessEvent(process_id=dos_eventos.id, event_type="phase_approved",
                     payload={"reason": "otro tipo"}, created_at=t + timedelta(days=2)),
        ProcessEvent(process_id=activo_con_evento.id, event_type="process_cancelled",
                     payload={"reason": "ya no cuenta"}, created_at=t),
        ProcessEvent(process_id=misma_hora.id, event_type="process_cancelled",
                     payload={"reason": "primero"}, created_at=t),
        ProcessEvent(process_id=misma_hora.id, event_type="process_cancelled",
                     payload=None, created_at=t),
    ])
    db_session.flush()
    procs = [dos_eventos, sin_evento, activo_con_evento, misma_hora]

    mapa = ProcessService.cancellation_info_map(db_session, procs)

    assert mapa == {p.id: ProcessService.cancellation_info(db_session, p) for p in procs}
    assert mapa[dos_eventos.id]["reason"] == "nuevo"
    assert ProcessService.cancellation_info_map(db_session, []) == {}


def test_en_modo_alterno_se_busca_sin_formularios(
    client_as, db_session, make_head, make_cohort, modo_alterno,
):
    """Solo lectura = ni un `<form>`; buscar y paginar siguen sirviendo."""
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99830001", first_name="ANSELMO")
    _make_req(db_session, cohort, control="99830002")

    html = client_as(head).get(
        f"{URL}/body", params={"cohort_id": cohort.id, "q": "anselmo"}).text

    assert "<form" not in html
    assert 'id="tt-req-q"' in html
    assert re.findall(r'<tr id="tt-req-(\d+)"', html) == [str(req.id)]


# ---------------------------------------------------------------------------
# Buscador con hx-preserve (fix Task 6, ronda 1)
# ---------------------------------------------------------------------------
def test_buscador_preservado_y_q_viaja(
    client_as, db_session, make_head, make_cohort, tres_por_pagina,
):
    from tests.fastapi.titulatec.paging_asserts import (
        assert_buscador_preservado, assert_incluye_filtros,
    )

    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    for i in range(4):
        _make_req(db_session, cohort, control=f"9976{i:04d}", first_name="LUCERO",
                  created_at=datetime(2001, 1, 1 + i, 9, 0))
    cli = client_as(head)
    for url in (URL, f"{URL}/body"):            # carga completa y parcial
        html = cli.get(url, params={"cohort_id": cohort.id, "q": "lucero"}).text
        assert_buscador_preservado(html, input_id="tt-req-q",
                                   filters_id="tt-req-filters", q="lucero")
        nxt = re.search(r'<button[^>]*id="tt-req-pager-next"[^>]*>', html, re.S).group(0)
        assert_incluye_filtros(nxt, "tt-req-filters")
        tab = re.search(r'<button id="tt-req-tab-rejected"[^>]*>', html).group(0)
        assert "q=lucero" in tab
