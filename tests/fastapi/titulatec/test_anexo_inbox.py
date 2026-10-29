"""Fase 6, tarea 5: bandeja del Anexo III (`AnexoInboxService`, spec §9.2).

Predicados por pestaña sobre la `ProcessPhase` de la fase 6, FIFO por
`ProcessPhase.updated_at`, alcance por carrera y consultas fijas por página.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from itcj2.apps.titulatec.models import ProcessPhase
from itcj2.apps.titulatec.services.anexo_inbox_service import AnexoInboxService
from itcj2.apps.titulatec.services.phase_service import PhaseService
from itcj2.core.utils.timezone import db_now

PAGE_PERM = "titulatec.titulacion.page.list"
REVIEW_PERM = "titulatec.anexo_iii.api.review"
ROLE = f"tt_test_anexo_inbox_{os.getpid()}"


@pytest.fixture()
def esc(db_session, monkeypatch, make_anexo_case, make_user, make_role, make_position,
        bind_position_role, link_programs, assign_position):
    monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: 9))
    casos = []

    def caso(estado, *, dias=0, proceso=None):
        c = make_anexo_case(phase_status="in_progress")
        fase = (db_session.query(ProcessPhase)
                .filter_by(process_id=c.process.id, phase_number=c.anexo_phase).one())
        fase.status = estado
        fase.updated_at = db_now() - timedelta(days=dias)
        if proceso:
            c.process.status = proceso
        db_session.flush()
        casos.append(c)
        return c

    def revisor(*cs):
        user = make_user(first_name="TERE", last_name="TITULACION")
        pos = make_position(title="Titulacion anexo")
        bind_position_role(pos, make_role(ROLE, (PAGE_PERM, REVIEW_PERM)))
        link_programs(pos, [c.process.program_id for c in cs])
        assign_position(user, pos)
        return user

    return SimpleNamespace(caso=caso, revisor=revisor)


def _ids(data):
    return [r["process_id"] for r in data["rows"]]


def test_cada_pestana_con_su_predicado(db_session, esc):
    p = esc.caso("in_review")
    o = esc.caso("rejected")
    a = esc.caso("approved")
    u = esc.caso("in_progress")
    v = esc.revisor(p, o, a, u)
    for tab, c in (("pending", p), ("observed", o), ("approved", a), ("unsent", u)):
        data = AnexoInboxService.list(db_session, v.id, tab=tab)
        assert _ids(data) == [c.process.id], tab
    assert AnexoInboxService.list(db_session, v.id, tab="pending")["counts"] == {
        "pending": 1, "observed": 1, "approved": 1, "unsent": 1}


def test_pending_es_fifo_por_updated_at_y_calcula_posicion(db_session, esc):
    nuevo = esc.caso("in_review", dias=0)
    viejo = esc.caso("in_review", dias=9)
    medio = esc.caso("in_review", dias=4)
    v = esc.revisor(nuevo, viejo, medio)
    data = AnexoInboxService.list(db_session, v.id, tab="pending")
    assert _ids(data) == [viejo.process.id, medio.process.id, nuevo.process.id]
    assert [r["position"] for r in data["rows"]] == [1, 2, 3]
    assert data["rows"][0]["wait_level"] in ("warn", "late")
    assert AnexoInboxService.next_pending(db_session, v.id) == viejo.process.id
    assert AnexoInboxService.next_pending(
        db_session, v.id, exclude_ids=[viejo.process.id]) == medio.process.id


def test_on_hold_y_cancelled_fuera_de_pending(db_session, esc):
    ok = esc.caso("in_review")
    pausado = esc.caso("in_review", proceso="on_hold")
    cancelado = esc.caso("in_review", proceso="cancelled")
    obs_cancelado = esc.caso("rejected", proceso="cancelled")
    v = esc.revisor(ok, pausado, cancelado, obs_cancelado)
    assert _ids(AnexoInboxService.list(db_session, v.id, tab="pending")) == [ok.process.id]
    assert _ids(AnexoInboxService.list(db_session, v.id, tab="observed")) == []


def test_alcance_por_carrera(db_session, esc):
    mio = esc.caso("in_review")
    ajeno = esc.caso("in_review")
    v = esc.revisor(mio)
    assert _ids(AnexoInboxService.list(db_session, v.id, tab="pending")) == [mio.process.id]
    assert AnexoInboxService.contains(db_session, v.id, mio.process.id, tab="pending")
    assert not AnexoInboxService.contains(db_session, v.id, ajeno.process.id, tab="pending")
    assert AnexoInboxService.next_pending(
        db_session, v.id, exclude_ids=[mio.process.id]) is None


def test_contains_respeta_pestana(db_session, esc):
    c = esc.caso("rejected")
    v = esc.revisor(c)
    assert AnexoInboxService.contains(db_session, v.id, c.process.id, tab="observed")
    assert not AnexoInboxService.contains(db_session, v.id, c.process.id, tab="pending")


def test_numero_fijo_de_consultas(db_session, esc):
    from sqlalchemy import event
    cs = [esc.caso("in_review", dias=i) for i in range(5)]
    v = esc.revisor(*cs)

    def contar(per_page):
        n = []
        conn = db_session.connection()

        def f(*a):
            n.append(1)
        event.listen(conn, "before_cursor_execute", f)
        try:
            data = AnexoInboxService.list(db_session, v.id, tab="pending", per_page=per_page)
        finally:
            event.remove(conn, "before_cursor_execute", f)
        assert len(data["rows"]) == per_page
        return len(n)

    contar(5)  # calienta cachés (authz, catálogo)
    assert contar(2) == contar(5)


def test_sin_enviar_lleva_la_etapa_de_cada_fila(db_session, esc):
    from itcj2.apps.titulatec.models import Anexo
    prep = esc.caso("in_progress")
    rep = esc.caso("in_progress")
    listo = esc.caso("in_progress")
    for c, kw in ((prep, {}), (rep, {"reprint_requested_at": datetime(2026, 3, 2)}),
                  (listo, {"ready_at": datetime(2026, 3, 1, 9, 0)})):
        db_session.add(Anexo(process_id=c.process.id, folio=f"AIII-T-{c.process.id}", semester="2026A",
                         released_at=datetime(2026, 2, 1), **kw))
    db_session.flush()
    v = esc.revisor(prep, rep, listo)
    filas = {r["process_id"]: r for r in
             AnexoInboxService.list(db_session, v.id, tab="unsent")["rows"]}
    assert filas[prep.process.id]["stage"] == "preparing"
    assert filas[prep.process.id]["stage_label"] == "En preparación"
    assert filas[rep.process.id]["stage"] == "reprint"
    assert filas[listo.process.id]["stage"] == "ready"
    assert filas[listo.process.id]["ready_label"]
    assert filas[prep.process.id]["ready_label"] is None
    # Las demás pestañas no calculan etapa.
    otra = esc.caso("in_review")
    v2 = esc.revisor(otra)
    assert AnexoInboxService.list(db_session, v2.id, tab="pending")["rows"][0]["stage"] is None


def test_con_observaciones_solo_marca_la_reimpresion(db_session, esc):
    from itcj2.apps.titulatec.models import Anexo
    normal = esc.caso("rejected")
    rep = esc.caso("rejected")
    for c, kw in ((normal, {"ready_at": datetime(2026, 3, 1, 9, 0)}),
                  (rep, {"reprint_requested_at": datetime(2026, 3, 2)})):
        db_session.add(Anexo(process_id=c.process.id, folio=f"AIII-T-{c.process.id}",
                             semester="2026A", released_at=datetime(2026, 2, 1), **kw))
    db_session.flush()
    v = esc.revisor(normal, rep)
    filas = {r["process_id"]: r for r in
             AnexoInboxService.list(db_session, v.id, tab="observed")["rows"]}
    assert filas[rep.process.id]["stage"] == "reprint"
    assert filas[normal.process.id]["stage"] == "observed"
