"""Bandeja FIFO del Formato B (fase 3, spec §8.2): `FormatBInboxService`.

El alcance se acota con un encargado de UNA carrera propia por prueba, así los
contadores y las listas son exactos aunque la base de dev traiga datos reales.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from tests.fastapi.titulatec.test_documents_inbox import _Contador

T0 = datetime(2026, 10, 1, 9, 0)


@pytest.fixture()
def inbox(db_session, seed_phase_defs, make_program, make_cohort, make_student,
          make_process, make_format_b, make_officer, make_modality):
    """Mundo mínimo: carrera propia, encargado acotado y fábrica de procesos."""
    seed_phase_defs()
    prog = make_program("Ingenieria Bandeja FB")
    otra = make_program("Ingenieria Bandeja FB Otra")
    cohorte = make_cohort()
    modalidad = make_modality(name="Residencias de prueba")
    user, _pos = make_officer([prog, otra])

    class W:
        pass

    w = W()
    w.db, w.prog, w.otra, w.user, w.modalidad = db_session, prog, otra, user, modalidad

    def nuevo(fb="submitted", submitted_at=T0, program=Ellipsis, status="active",
              phase=3, first="ANA", last="PEREZ", middle="LOPEZ", control=None,
              count=1, **fields):
        alumno = make_student(first_name=first, last_name=last, control_number=control)
        alumno.middle_name = middle
        proc = make_process(alumno, cohort=cohorte,
                            program=prog if program is Ellipsis else program,
                            current_phase=phase, status=status, modality=modalidad)
        if fb is not None:
            make_format_b(proc, status=fb, submitted_at=submitted_at,
                          submission_count=count if fb != "draft" else 0, **fields)
        return proc

    w.nuevo = nuevo
    w.lista = lambda tab="pending", **kw: _lista(db_session, user, tab, **kw)
    return w


def _lista(db, user, tab, **kw):
    from itcj2.apps.titulatec.services.format_b_inbox_service import FormatBInboxService
    return FormatBInboxService.list(db, user.id, tab=tab, **kw)


def _ids(ctx):
    return [r["process_id"] for r in ctx["rows"]]


def test_pending_es_fifo_y_el_reenvio_queda_al_final(inbox):
    a = inbox.nuevo(submitted_at=T0)
    b = inbox.nuevo(submitted_at=T0 + timedelta(days=1))
    c = inbox.nuevo(submitted_at=T0 + timedelta(days=2))
    assert _ids(inbox.lista()) == [a.id, b.id, c.id]

    # `a` se reenvia: su submitted_at nuevo lo manda al final (ronda 2)
    a.format_b.submitted_at = T0 + timedelta(days=5)
    a.format_b.submission_count = 2
    inbox.db.flush()
    ctx = inbox.lista()
    assert _ids(ctx) == [b.id, c.id, a.id]
    assert [r["position"] for r in ctx["rows"]] == [1, 2, 3]
    assert ctx["rows"][-1]["round"] == 2


def test_empate_de_submitted_at_se_desempata_por_process_id(inbox):
    a = inbox.nuevo(submitted_at=T0)
    b = inbox.nuevo(submitted_at=T0)
    assert _ids(inbox.lista()) == sorted([a.id, b.id])


def test_fila_trae_los_campos_del_contrato(inbox):
    p = inbox.nuevo(first="ANA", last="PEREZ", middle="LOPEZ", control="99123456")
    r = inbox.lista()["rows"][0]
    assert r["process_id"] == p.id and r["folio"] == p.folio
    assert r["student_name"] == "PEREZ LOPEZ, ANA"
    assert r["control_number"] == "99123456"
    assert r["program_name"] == inbox.prog.name
    assert r["modality_name"] == "Residencias de prueba"
    assert r["submitted_at"] == T0 and r["round"] == 1


def test_counts_son_del_conjunto_filtrado_no_de_la_pagina(inbox):
    for i in range(3):
        inbox.nuevo(submitted_at=T0 + timedelta(hours=i))
    inbox.nuevo(fb="rejected", submitted_at=T0)
    inbox.nuevo(fb="approved", submitted_at=T0)
    inbox.nuevo(fb="draft", submitted_at=None)            # sin enviar
    inbox.nuevo(fb=None)                                  # sin FB, en fase 3
    ctx = inbox.lista(per_page=2)
    assert len(ctx["rows"]) == 2 and ctx["page"].total == 3
    assert ctx["counts"] == {"pending": 3, "observed": 1, "approved": 1, "unsent": 2}
    # pagina 2 con la ultima fila
    assert len(inbox.lista(per_page=2, page="2")["rows"]) == 1


def test_busqueda_por_control_y_por_nombre_y_counts_la_respetan(inbox):
    x = inbox.nuevo(first="ZULEMA", last="QUIROGA", middle="BRAVO", control="99777001")
    inbox.nuevo(first="OTRA", last="PERSONA", middle="DISTINTA", control="99777002")
    por_control = inbox.lista(q="99777001")
    assert _ids(por_control) == [x.id]
    assert por_control["counts"]["pending"] == 1
    assert _ids(inbox.lista(q="quiroga bravo zulema")) == [x.id]
    assert inbox.lista(q="NOEXISTE-XYZ")["counts"]["pending"] == 0


def test_filtro_de_carrera_y_alcance(inbox, make_officer, make_program):
    a = inbox.nuevo()
    b = inbox.nuevo(program=inbox.otra)
    assert set(_ids(inbox.lista())) == {a.id, b.id}
    solo = inbox.lista(program_id=inbox.otra.id)
    assert _ids(solo) == [b.id] and solo["counts"]["pending"] == 1

    # un encargado de OTRA carrera no ve nada de estas
    ajena = make_program("Ingenieria Bandeja FB Ajena")
    otro, _ = make_officer([ajena])
    from itcj2.apps.titulatec.services.format_b_inbox_service import FormatBInboxService
    ctx = FormatBInboxService.list(inbox.db, otro.id, tab="pending")
    assert ctx["rows"] == [] and ctx["counts"]["pending"] == 0
    # y el filtro de carrera no puede salirse de su alcance
    ctx = FormatBInboxService.list(inbox.db, otro.id, tab="pending",
                                   program_id=inbox.prog.id)
    assert ctx["rows"] == []


def test_scope_vacio_no_ve_nada(inbox, make_user):
    from itcj2.apps.titulatec.services.format_b_inbox_service import FormatBInboxService
    inbox.nuevo()
    sin = make_user()
    ctx = FormatBInboxService.list(inbox.db, sin.id, tab="pending")
    assert ctx["rows"] == [] and ctx["page"].total == 0
    assert FormatBInboxService.next_pending(inbox.db, sin.id) is None


def test_proceso_sin_carrera_nunca_sale(inbox, make_head):
    from itcj2.apps.titulatec.services.format_b_inbox_service import FormatBInboxService
    sin_carrera = inbox.nuevo(program=None)
    jefa = make_head()                                  # alcance ALL
    for tab in ("pending",):
        ctx = FormatBInboxService.list(inbox.db, jefa.id, tab=tab, per_page=500)
        assert sin_carrera.id not in _ids(ctx)
    assert FormatBInboxService.next_pending(inbox.db, jefa.id) != sin_carrera.id


@pytest.mark.parametrize("estado", ["paused", "cancelled", "on_hold"])
def test_proceso_no_activo_fuera_de_pending(inbox, estado):
    ok = inbox.nuevo()
    fuera = inbox.nuevo(status=estado)
    ctx = inbox.lista()
    assert _ids(ctx) == [ok.id] and fuera.id not in _ids(ctx)
    assert ctx["counts"]["pending"] == 1


def test_approved_excluye_cancelados_y_ordena_por_approved_at(inbox):
    a = inbox.nuevo(fb="approved", approved_at=T0)
    b = inbox.nuevo(fb="approved", approved_at=T0 + timedelta(days=1))
    inbox.nuevo(fb="approved", approved_at=T0, status="cancelled")
    assert _ids(inbox.lista("approved")) == [b.id, a.id]


def test_observed_ordena_por_reviewed_at_desc(inbox):
    a = inbox.nuevo(fb="rejected", reviewed_at=T0)
    b = inbox.nuevo(fb="rejected", reviewed_at=T0 + timedelta(days=1))
    assert _ids(inbox.lista("observed")) == [b.id, a.id]


def test_unsent_incluye_fase_3_sin_fb_o_draft_por_antiguedad(inbox):
    from itcj2.apps.titulatec.models import ProcessPhase
    sin_fb = inbox.nuevo(fb=None)
    draft = inbox.nuevo(fb="draft", submitted_at=None)
    fase4 = inbox.nuevo(fb=None, phase=4)
    enviado = inbox.nuevo(fb="submitted")
    for proc, dias in ((sin_fb, 1), (draft, 9)):
        pp = (inbox.db.query(ProcessPhase)
              .filter_by(process_id=proc.id, phase_number=3).one())
        pp.started_at = T0 + timedelta(days=dias)
    inbox.db.flush()
    ctx = inbox.lista("unsent")
    assert _ids(ctx) == [sin_fb.id, draft.id]            # el mas viejo primero
    assert fase4.id not in _ids(ctx) and enviado.id not in _ids(ctx)
    assert all(r["position"] is None and r["wait_level"] is None for r in ctx["rows"])


def test_pestana_desconocida_cae_en_pending(inbox):
    p = inbox.nuevo()
    ctx = inbox.lista("zzz")
    assert ctx["tab"] == "pending" and _ids(ctx) == [p.id]


@pytest.mark.parametrize("dias_habiles,nivel", [(2, "ok"), (3, "warn"), (5, "late")])
def test_semaforo_en_dias_habiles(inbox, monkeypatch, dias_habiles, nivel):
    from itcj2.apps.titulatec.services import format_b_inbox_service as mod
    hoy = datetime(2026, 10, 21, 12, 0)                  # miercoles
    monkeypatch.setattr(mod, "db_now", lambda: hoy)
    enviado = {2: datetime(2026, 10, 19, 10), 3: datetime(2026, 10, 16, 10),
               5: datetime(2026, 10, 14, 10)}[dias_habiles]   # fin de semana de por medio
    inbox.nuevo(submitted_at=enviado)
    r = inbox.lista()["rows"][0]
    assert r["waited_days"] == dias_habiles and r["wait_level"] == nivel


def test_next_pending_salta_exclude_ids(inbox):
    a = inbox.nuevo(submitted_at=T0)
    b = inbox.nuevo(submitted_at=T0 + timedelta(days=1))
    c = inbox.nuevo(submitted_at=T0 + timedelta(days=2))
    inbox.nuevo(fb="approved", approved_at=T0)
    from itcj2.apps.titulatec.services.format_b_inbox_service import FormatBInboxService as S
    n = lambda **kw: S.next_pending(inbox.db, inbox.user.id, **kw)
    assert n() == a.id
    assert n(exclude_ids=[a.id]) == b.id
    assert n(exclude_ids={a.id, b.id}) == c.id
    assert n(exclude_ids=[a.id, b.id, c.id]) is None


def test_la_lista_cuesta_lo_mismo_con_2_que_con_8_filas(inbox):
    for i in range(2):
        inbox.nuevo(submitted_at=T0 + timedelta(hours=i))
    inbox.lista()                      # calienta el alcance (permisos en cache)
    with _Contador(inbox.db.get_bind()) as c2:
        assert len(inbox.lista()["rows"]) == 2
    for i in range(6):
        inbox.nuevo(submitted_at=T0 + timedelta(days=1, hours=i))
    with _Contador(inbox.db.get_bind()) as c8:
        assert len(inbox.lista()["rows"]) == 8
    assert len(c2) == len(c8), "\n".join(c8.sentencias)


def test_next_pending_respeta_la_carrera_y_la_busqueda(inbox):
    """El siguiente es del conjunto FILTRADO, no de toda la cola."""
    from itcj2.apps.titulatec.services.format_b_inbox_service import FormatBInboxService as S
    ajeno = inbox.nuevo(submitted_at=T0, program=inbox.otra, first="BETO")
    propio = inbox.nuevo(submitted_at=T0 + timedelta(days=1), first="CARLA")
    n = lambda **kw: S.next_pending(inbox.db, inbox.user.id, **kw)

    assert n() == ajeno.id
    assert n(program_id=inbox.prog.id) == propio.id
    assert n(program_id=inbox.otra.id) == ajeno.id
    assert n(q="CARLA") == propio.id
    assert n(q="BETO", program_id=inbox.prog.id) is None


def test_contains_aplica_pestana_busqueda_y_carrera(inbox):
    from itcj2.apps.titulatec.services.format_b_inbox_service import FormatBInboxService as S
    enviado = inbox.nuevo(first="CARLA")
    aprobado = inbox.nuevo(fb="approved", approved_at=T0)
    c = lambda pid, **kw: S.contains(inbox.db, inbox.user.id, pid, **kw)

    assert c(enviado.id, tab="pending")
    assert not c(enviado.id, tab="approved")
    assert c(aprobado.id, tab="approved")
    assert c(enviado.id, tab="pending", q="CARLA", program_id=inbox.prog.id)
    assert not c(enviado.id, tab="pending", program_id=inbox.otra.id)
    assert not c(enviado.id, tab="pending", q="NADIE")
    assert not c(enviado.id, tab="zzz")


def test_seleccionado_en_pagina_2_sigue_en_el_universo(inbox):
    """Con `per_page=1` el segundo cae en la página 2 y `contains` lo ve igual."""
    from itcj2.apps.titulatec.services.format_b_inbox_service import FormatBInboxService as S
    uno = inbox.nuevo(submitted_at=T0)
    dos = inbox.nuevo(submitted_at=T0 + timedelta(days=1))

    pagina_1 = inbox.lista(per_page=1)

    assert _ids(pagina_1) == [uno.id]
    assert S.contains(inbox.db, inbox.user.id, dos.id, tab="pending")


def test_un_festivo_en_el_intervalo_cuenta_un_dia_menos(inbox, monkeypatch, make_non_working_day):
    """El semaforo de la bandeja descuenta los dias inhabiles del calendario."""
    from itcj2.apps.titulatec.services import format_b_inbox_service as mod
    hoy = datetime(2091, 3, 9, 12, 0)                    # viernes
    monkeypatch.setattr(mod, "db_now", lambda: hoy)
    inbox.nuevo(submitted_at=datetime(2091, 3, 5, 10))   # lunes
    assert inbox.lista()["rows"][0]["waited_days"] == 4
    make_non_working_day(datetime(2091, 3, 6).date(), "Festivo de prueba")   # martes
    assert inbox.lista()["rows"][0]["waited_days"] == 3
