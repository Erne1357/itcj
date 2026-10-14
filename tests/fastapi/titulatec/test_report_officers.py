"""Tablero de la jefa de Servicios Escolares — Encargados (Task 5).

Spec `docs/superpowers/specs/2026-10-14-titulatec-tablero-design.md` §2 (D2),
§4.6 y §4.7:

* **Puras** (sin BD, `Item`s construidos a mano): `queues` (cola con traslape:
  cada encargado carga la cola COMPLETA de sus carreras) y `days_to_clear`.
* **Con BD** (fábricas de `conftest.py`; la CI corre sobre base vacía, así que
  nada sale de datos de dev): `officers` (encargados de Servicios Escolares, una
  fila por persona), `production` (por actor, en rango) y `capacity` (lugares
  de los próximos días hábiles), más su presupuesto de consultas: el MISMO
  número de sentencias con pocos que con muchos datos.

Las fechas de `production`/`capacity` viven en 2091 (año sintético): la base de
dev es compartida y trae eventos, solicitudes y ventanas reales; en 2091 no hay
nada más que lo que siembra cada prueba.
"""
from __future__ import annotations

import itertools
from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import event

from itcj2.apps.titulatec.services import report_officers as ro
from itcj2.apps.titulatec.services import report_snapshot as rs
from itcj2.apps.titulatec.services.report_snapshot import Item

_SEQ = itertools.count(1)

# Lunes sintético: 2091-01-01 cae en lunes, pero se calcula para no depender de
# saberlo de memoria.
_BASE = date(2091, 1, 1)
LUNES = _BASE + timedelta(days=(7 - _BASE.weekday()) % 7)
assert LUNES.weekday() == 0


# ---------------------------------------------------------------------------
# Ayudantes
# ---------------------------------------------------------------------------
def _item(stage, program_id, *, kind=None, balls=(), pending_docs=0,
          ready_to_book=False, appt_owner_id=None) -> Item:
    """`Item` mínimo para las pruebas puras (lo demás no lo lee `queues`)."""
    n = next(_SEQ)
    return Item(
        kind=kind or ("request" if stage.startswith("req_") else "process"),
        id=n, cohort_id=1, program_id=program_id, stage=stage, balls=tuple(balls),
        idle_days=0, level="ok", label=f"Egresado {n} · 99{n:06d}",
        control=f"99{n:06d}", href="#", pending_docs=pending_docs,
        ready_to_book=ready_to_book, appt_owner_id=appt_owner_id,
    )


def _officer(uid, *programs, name=None) -> ro.Officer:
    return ro.Officer(user_id=uid, name=name or f"ENCARGADO {uid}",
                      program_ids=frozenset(programs))


ESC_REVIEW = ("escolares", rs.MOTIVE_REVIEW_REQUEST)
ESC_DOCS = ("escolares", rs.MOTIVE_REVIEW_DOCS)
ESC_CLOSE = ("escolares", rs.MOTIVE_CLOSE_APPT)
ESC_PHASE2 = ("escolares", rs.MOTIVE_REVIEW_PHASE2)
ALU_BOOK = ("alumno", rs.MOTIVE_BOOK)
ALU_RESCHEDULE = ("alumno", rs.MOTIVE_RESCHEDULE)


def _contar(db_session, fn) -> int:
    """Sentencias que emite `fn` sobre la conexión del test (patrón de
    `test_appt_queue_batch.py`). Ignora las de la bitácora (CLAUDE.md §20:
    un flush con escrituras titulatec suma sus INSERT)."""
    sentencias = []

    def _ver(_conn, _cursor, statement, *_a):
        if "titulatec_audit_log" not in statement:
            sentencias.append(statement)

    db_session.flush()
    conn = db_session.connection()
    event.listen(conn, "before_cursor_execute", _ver)
    try:
        fn()
    finally:
        event.remove(conn, "before_cursor_execute", _ver)
    return len(sentencias)


# ---------------------------------------------------------------------------
# 0. Contrato con el catálogo de la instantánea (T3)
# ---------------------------------------------------------------------------
def test_los_codigos_que_lee_la_cola_existen_en_el_catalogo():
    etapas = {code for code, _, _ in rs.STAGES}
    actores = {code for code, _, _ in rs.ACTORS}
    assert ro.REQUEST_REVIEW_STAGES <= etapas
    assert ro.APPT_STAGE in etapas
    assert ro.ESCOLARES in actores


# ---------------------------------------------------------------------------
# 1. queues (pura): traslape, carreras disjuntas, citas por dueño
# ---------------------------------------------------------------------------
def test_dos_encargados_con_la_misma_carrera_ven_la_misma_cola():
    a, b = _officer(10, 1), _officer(20, 1)
    items = [
        _item("req_review", 1, balls=[ESC_REVIEW]),
        _item("req_review", 1, balls=[ESC_REVIEW]),
        _item("docs", 1, balls=[ESC_DOCS], pending_docs=2),
        _item("docs", 1, balls=[ESC_DOCS], pending_docs=1),
        _item("requisitos", 1, balls=[ALU_BOOK], ready_to_book=True),
    ]
    q = ro.queues([a, b], items)
    esperado = {"req_review": 2, "docs_pending": 3, "appts_to_close": 0,
                "ready_to_book": 1, "total_escolares": 5}
    assert q[10] == esperado
    assert q[20] == esperado
    # D2: el traslape NO se reparte; cada uno carga la cola completa, así que
    # la suma por encargado rebasa los pendientes reales.
    assert q[10]["req_review"] + q[20]["req_review"] == 4


def test_ocultar_un_encargado_no_cambia_la_cola_de_los_demas():
    """Chips `ox` (spec §4.7): quitar a uno de la lista no mueve a nadie más."""
    a, b = _officer(10, 1, 2), _officer(20, 2)
    items = [
        _item("req_review", 1, balls=[ESC_REVIEW]),
        _item("docs", 2, balls=[ESC_DOCS], pending_docs=2),
        _item("cita", 2, balls=[ESC_CLOSE], appt_owner_id=10),
        _item("cita", 2, balls=[ESC_CLOSE], appt_owner_id=20),
    ]
    assert ro.queues([b], items)[20] == ro.queues([a, b], items)[20]
    assert ro.queues([a], items)[10] == ro.queues([a, b], items)[10]


def test_carreras_disjuntas_no_se_cruzan():
    a, b = _officer(10, 1), _officer(20, 2)
    items = [
        _item("req_review", 1, balls=[ESC_REVIEW]),
        _item("docs", 1, balls=[ESC_DOCS], pending_docs=4),
        _item("req_review", 2, balls=[ESC_REVIEW]),
        _item("req_review", 2, balls=[ESC_REVIEW]),
        _item("requisitos", 2, balls=[ALU_BOOK], ready_to_book=True),
    ]
    q = ro.queues([a, b], items)
    assert q[10] == {"req_review": 1, "docs_pending": 4, "appts_to_close": 0,
                     "ready_to_book": 0, "total_escolares": 5}
    assert q[20] == {"req_review": 2, "docs_pending": 0, "appts_to_close": 0,
                     "ready_to_book": 1, "total_escolares": 2}


def test_encargado_con_varias_carreras_suma_las_suyas():
    q = ro.queues([_officer(10, 1, 2), _officer(20, 2)], [
        _item("req_review", 1, balls=[ESC_REVIEW]),
        _item("req_review", 2, balls=[ESC_REVIEW]),
        _item("req_review", 3, balls=[ESC_REVIEW]),          # de nadie
    ])
    assert q[10]["req_review"] == 2
    assert q[20]["req_review"] == 1


def test_las_citas_por_cerrar_son_del_dueno_de_la_ventana_no_de_la_carrera():
    a, b = _officer(10, 1), _officer(20, 1)
    items = [
        # Pasada sin cerrar y atendida sin dictamen: Escolares, ventana de A,
        # aunque la carrera 9 no sea de A.
        _item("cita", 9, balls=[ESC_CLOSE], appt_owner_id=10),
        _item("cita", 1, balls=[ESC_PHASE2, ("gtv", rs.MOTIVE_RELEASE_SURVEY)],
              appt_owner_id=10),
        # En agenda (sin pelota) y faltó (pelota del alumno): no son de Escolares.
        _item("cita", 1, balls=[], appt_owner_id=10),
        _item("cita", 1, balls=[ALU_RESCHEDULE], appt_owner_id=10, ready_to_book=True),
        # Pelota de Escolares pero en otra etapa: no es cita.
        _item("docs", 1, balls=[ESC_DOCS], pending_docs=1, appt_owner_id=10),
        # Cita sin ventana (legado): no es de nadie.
        _item("cita", 1, balls=[ESC_CLOSE], appt_owner_id=None),
    ]
    q = ro.queues([a, b], items)
    assert q[10]["appts_to_close"] == 2
    assert q[20]["appts_to_close"] == 0
    # La reagenda del no_show sí cuenta como «listo sin cita» de la carrera.
    assert q[10]["ready_to_book"] == q[20]["ready_to_book"] == 1
    assert q[10]["total_escolares"] == 0 + 1 + 2
    assert q[20]["total_escolares"] == 0 + 1 + 0


def test_total_escolares_suma_las_tres_colas_y_no_los_listos():
    q = ro.queues([_officer(10, 1)], [
        _item("req_review", 1, balls=[ESC_REVIEW]),
        _item("docs", 1, balls=[ESC_DOCS], pending_docs=3),
        _item("cita", 1, balls=[ESC_CLOSE], appt_owner_id=10),
        _item("requisitos", 1, balls=[ALU_BOOK], ready_to_book=True),
        _item("requisitos", 1, balls=[ALU_BOOK], ready_to_book=True),
    ])[10]
    assert q == {"req_review": 1, "docs_pending": 3, "appts_to_close": 1,
                 "ready_to_book": 2, "total_escolares": 5}


def test_solicitud_anterior_cuenta_como_por_revisar():
    """`req_unverified` (legado) también es «Revisar solicitud» de Escolares
    (Ruling de T3): la bandeja la lista en «Por revisar · anterior»."""
    q = ro.queues([_officer(10, 1)], [
        _item("req_unverified", 1, balls=[ESC_REVIEW]),
        _item("req_review", 1, balls=[ESC_REVIEW]),
        # Las demás etapas de solicitud no son «por revisar».
        _item("req_access", 1, balls=[("computo", rs.MOTIVE_GIVE_NIP)]),
        _item("req_approved", 1, balls=[("escolares", rs.MOTIVE_RESEND_LINK)]),
    ])[10]
    assert q["req_review"] == 2


def test_sin_carrera_no_cae_en_ninguna_cola_y_sin_carreras_es_cero():
    a, sin = _officer(10, 1), _officer(30)
    items = [
        _item("req_review", None, balls=[ESC_REVIEW]),
        _item("docs", None, balls=[ESC_DOCS], pending_docs=5),
        _item("requisitos", None, balls=[ALU_BOOK], ready_to_book=True),
    ]
    q = ro.queues([a, sin], items)
    cero = {"req_review": 0, "docs_pending": 0, "appts_to_close": 0,
            "ready_to_book": 0, "total_escolares": 0}
    assert q[10] == cero
    assert q[30] == cero


def test_cola_vacia_y_sin_encargados():
    assert ro.queues([], [_item("req_review", 1, balls=[ESC_REVIEW])]) == {}
    assert ro.queues([_officer(10, 1)], [])[10]["total_escolares"] == 0


# ---------------------------------------------------------------------------
# 2. days_to_clear (pura)
# ---------------------------------------------------------------------------
def _semana(lunes=LUNES) -> list[date]:
    return [lunes + timedelta(days=i) for i in range(5)]


def test_days_to_clear_none_sin_produccion():
    dias = _semana()
    assert ro.days_to_clear(10, {}, dias) is None
    assert ro.days_to_clear(10, {d: 0 for d in dias}, dias) is None
    assert ro.days_to_clear(0, {}, dias) is None


def test_days_to_clear_none_sin_dias_habiles():
    assert ro.days_to_clear(10, {LUNES: 4}, []) is None


def test_days_to_clear_cola_entre_ritmo_por_dia_habil():
    dias = _semana()
    # 10 en 5 días hábiles = 2 por día; 12 pendientes = 6 días.
    prod = {dias[0]: 4, dias[2]: 6}
    assert ro.days_to_clear(12, prod, dias) == pytest.approx(6.0)
    assert ro.days_to_clear(0, prod, dias) == pytest.approx(0.0)


def test_days_to_clear_solo_cuenta_lo_producido_dentro_del_tramo():
    dias = _semana()                           # lunes a viernes
    prod = {
        LUNES: 5,
        LUNES - timedelta(days=1): 100,        # domingo anterior: fuera
        LUNES + timedelta(days=7): 100,        # lunes siguiente: fuera
    }
    # 5 en 5 días hábiles = 1 por día.
    assert ro.days_to_clear(3, prod, dias) == pytest.approx(3.0)
    # Un sábado DENTRO del tramo sí cuenta (se trabajó), y el divisor sigue
    # siendo de días hábiles.
    dos_semanas = _semana() + _semana(LUNES + timedelta(days=7))
    prod2 = {LUNES + timedelta(days=5): 10}    # sábado entre las dos semanas
    assert ro.days_to_clear(10, prod2, dos_semanas) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# 3. officers (BD)
# ---------------------------------------------------------------------------
@pytest.fixture()
def escolares(make_department):
    """El departamento real (`school_services`): en dev ya existe y
    `make_department` lo devuelve; en la CI lo crea."""
    return make_department(code="school_services", name="Servicios Escolares")


@pytest.fixture()
def puesto_encargado(make_position, link_programs, assign_position):
    """Puesto `se_officer_*` del depto, con carreras y ocupantes."""
    def _make(dept, programs, users, *, code=None, title="Encargado tablero"):
        pos = make_position(code=code or f"se_officer_tt{next(_SEQ):06d}",
                            title=title, department=dept)
        link_programs(pos, programs)
        for u in users:
            assign_position(u, pos)
        return pos
    return _make


def _mios(lista, *users) -> list[ro.Officer]:
    ids = {u.id for u in users}
    return [o for o in lista if o.user_id in ids]


def test_officers_une_los_puestos_de_una_persona_en_una_fila(
        db_session, escolares, puesto_encargado, make_user, make_program):
    pa = make_program("Ingenieria Tablero Encargados A")
    pb = make_program("Ingenieria Tablero Encargados B")
    pc = make_program("Ingenieria Tablero Encargados C")
    ana = make_user(first_name="ANA", last_name="ZZTABLERO")
    beto = make_user(first_name="BETO", last_name="AATABLERO")
    puesto_encargado(escolares, [pa, pb], [ana])
    puesto_encargado(escolares, [pb, pc], [ana, beto])

    mios = _mios(ro.officers(db_session), ana, beto)
    assert [o.user_id for o in mios] == [beto.id, ana.id]          # orden por nombre
    por_id = {o.user_id: o for o in mios}
    assert por_id[ana.id].program_ids == frozenset({pa.id, pb.id, pc.id})
    assert por_id[beto.id].program_ids == frozenset({pb.id, pc.id})
    assert por_id[ana.id].name == ana.full_name
    assert isinstance(por_id[ana.id], ro.Officer)
    # Una fila por persona en TODA la lista, no solo en las mías.
    todos = [o.user_id for o in ro.officers(db_session)]
    assert len(todos) == len(set(todos))


def test_officers_solo_encargados_de_servicios_escolares(
        db_session, escolares, puesto_encargado, make_department, make_position,
        assign_position, link_programs, make_user, make_program):
    pa = make_program("Ingenieria Tablero Encargados A")
    dentro = make_user(first_name="DENTRO", last_name="TABLERO")
    otro_depto = make_user(first_name="OTRODEPTO", last_name="TABLERO")
    otro_codigo = make_user(first_name="OTROCODIGO", last_name="TABLERO")
    puesto_encargado(escolares, [pa], [dentro])
    # Encargado de OTRO departamento: fuera.
    puesto_encargado(make_department(), [pa], [otro_depto])
    # Puesto de Escolares que no es `se_officer_*` (jefatura, secretaria): fuera.
    pos = make_position(code=f"tt_head_like_{next(_SEQ)}", department=escolares)
    link_programs(pos, [pa])
    assign_position(otro_codigo, pos)

    ids = {o.user_id for o in ro.officers(db_session)}
    assert dentro.id in ids
    assert otro_depto.id not in ids and otro_codigo.id not in ids


def test_officers_sin_carreras_es_fila_con_conjunto_vacio(
        db_session, escolares, puesto_encargado, make_user):
    sin = make_user(first_name="SINCARRERAS", last_name="TABLERO")
    puesto_encargado(escolares, [], [sin])
    (fila,) = _mios(ro.officers(db_session), sin)
    assert fila.program_ids == frozenset()


def test_officers_sin_departamento_es_lista_vacia(db_session, monkeypatch):
    monkeypatch.setattr(ro, "DEPT_CODE", "tt_no_existe_tablero")
    assert ro.officers(db_session) == []


def test_officers_consultas_fijas(db_session, escolares, puesto_encargado, make_user,
                                  make_program):
    pa = make_program("Ingenieria Tablero Encargados A")
    puesto_encargado(escolares, [pa], [make_user(), make_user()])
    db_session.expire_all()
    pocos = _contar(db_session, lambda: ro.officers(db_session))
    for _ in range(4):
        puesto_encargado(escolares, [pa], [make_user(), make_user()])
    db_session.expire_all()
    muchos = _contar(db_session, lambda: ro.officers(db_session))
    assert pocos == muchos == 4            # depto + los 3 de `list_officers`


# ---------------------------------------------------------------------------
# 4. production (BD)
# ---------------------------------------------------------------------------
@pytest.fixture()
def fabrica(db_session, make_cohort, make_program, make_process, make_student, make_user):
    """Convocatorias, procesos y fábricas de eventos/solicitudes revisadas."""
    from itcj2.apps.titulatec.models import EnrollmentRequest, ProcessEvent

    pa = make_program("Ingenieria Tablero Encargados A")
    c1, c2 = make_cohort(), make_cohort()
    p1 = make_process(make_student(), cohort=c1, program=pa)
    p2 = make_process(make_student(), cohort=c2, program=pa)

    def evento(proc, actor, tipo, cuando, phase_number=None):
        db_session.add(ProcessEvent(
            process_id=proc.id, actor_id=getattr(actor, "id", actor), event_type=tipo,
            phase_number=phase_number, created_at=cuando))

    def revisada(cohort, actor, cuando, status="pending_review"):
        n = next(_SEQ)
        db_session.add(EnrollmentRequest(
            cohort_id=cohort.id, control_number=f"97{n:06d}", first_name="SOLICITANTE",
            last_name="TABLERO", program_id=pa.id, phone="6560000000",
            contact_email=f"tt.enc.{n}@example.invalid", has_efirma=False,
            kind="unknown", status=status, verify_send_count=0,
            created_at=cuando - timedelta(days=3),
            reviewed_by_id=getattr(actor, "id", actor), reviewed_at=cuando))

    return {"c1": c1, "c2": c2, "p1": p1, "p2": p2, "evento": evento,
            "revisada": revisada, "make_user": make_user}


def _a_las(d: date, h: int = 10) -> datetime:
    return datetime.combine(d, time(h, 0))


def test_produccion_por_actor_en_rango(db_session, fabrica):
    f = fabrica
    ana, beto = f["make_user"](), f["make_user"]()
    ini, fin = LUNES, LUNES + timedelta(days=4)          # lunes a viernes
    mar, mie = LUNES + timedelta(days=1), LUNES + timedelta(days=2)
    ev, p1 = f["evento"], f["p1"]

    ev(p1, ana, "document_approved", _a_las(ini, 8))     # borde inicial: dentro
    ev(p1, ana, "document_approved", _a_las(mar))
    ev(p1, ana, "document_approved", _a_las(mar, 17))
    ev(p1, ana, "document_rejected", _a_las(mie))
    ev(p1, ana, "appointment_attended", _a_las(mie))
    ev(p1, ana, "appointment_no_show", _a_las(mie))
    ev(p1, ana, "phase_approved", _a_las(fin, 23), phase_number=2)   # borde final
    ev(p1, ana, "phase_approved", _a_las(mar), phase_number=1)       # no es liberación
    ev(p1, ana, "document_uploaded", _a_las(mar))                    # no es producción
    ev(p1, ana, "document_approved", _a_las(ini - timedelta(days=1), 23))  # antes
    ev(p1, ana, "document_approved", _a_las(fin + timedelta(days=1), 0))   # después
    ev(p1, None, "document_approved", _a_las(mar))                   # sistema: sin actor
    f["revisada"](f["c1"], ana, _a_las(mar))
    f["revisada"](f["c1"], ana, _a_las(fin), status="rejected")
    f["revisada"](f["c1"], ana, _a_las(fin + timedelta(days=1)))     # fuera de rango
    f["revisada"](f["c1"], beto, _a_las(ini))
    db_session.flush()

    prod = ro.production(db_session, start=ini, end=fin, cohort_ids=[f["c1"].id])
    assert set(prod) == {ana.id, beto.id}
    assert prod[ana.id] == {
        "req_reviewed": 2, "docs_approved": 3, "docs_rejected": 1,
        "reject_rate": pytest.approx(0.25), "attended": 1, "no_show": 1,
        "liberated": 1,
        # dictámenes de documentos + revisiones de solicitud, por día
        "by_day": {ini: 1, mar: 3, mie: 1, fin: 1},
    }
    assert prod[beto.id] == {
        "req_reviewed": 1, "docs_approved": 0, "docs_rejected": 0,
        "reject_rate": None, "attended": 0, "no_show": 0, "liberated": 0,
        "by_day": {ini: 1},
    }


def test_produccion_filtra_por_convocatoria(db_session, fabrica):
    f = fabrica
    ana = f["make_user"]()
    mar = LUNES + timedelta(days=1)
    f["evento"](f["p1"], ana, "document_rejected", _a_las(mar))
    f["evento"](f["p2"], ana, "document_rejected", _a_las(mar))      # convocatoria 2
    f["revisada"](f["c2"], ana, _a_las(mar))
    db_session.flush()
    kw = {"start": LUNES, "end": LUNES + timedelta(days=4)}

    solo_c1 = ro.production(db_session, cohort_ids=[f["c1"].id], **kw)[ana.id]
    assert (solo_c1["docs_rejected"], solo_c1["req_reviewed"]) == (1, 0)
    assert solo_c1["reject_rate"] == pytest.approx(1.0)

    ambas = ro.production(db_session, cohort_ids=[f["c1"].id, f["c2"].id], **kw)[ana.id]
    assert (ambas["docs_rejected"], ambas["req_reviewed"]) == (2, 1)
    assert ambas["by_day"] == {mar: 3}

    # `None` = todas las convocatorias (en 2091 solo hay lo sembrado aquí).
    todas = ro.production(db_session, cohort_ids=None, **kw)
    assert todas[ana.id]["docs_rejected"] == 2 and todas[ana.id]["req_reviewed"] == 1


def test_produccion_sin_convocatorias_o_rango_invertido_no_consulta(db_session, fabrica):
    kw = {"start": LUNES, "end": LUNES + timedelta(days=4)}
    assert _contar(db_session, lambda: ro.production(db_session, cohort_ids=[], **kw)) == 0
    assert ro.production(db_session, cohort_ids=[], **kw) == {}
    al_reves = {"start": LUNES + timedelta(days=4), "end": LUNES}
    assert ro.production(db_session, cohort_ids=None, **al_reves) == {}


def test_produccion_reject_rate_none_sin_dictamenes(db_session, fabrica):
    f = fabrica
    ana = f["make_user"]()
    f["evento"](f["p1"], ana, "appointment_attended", _a_las(LUNES))
    db_session.flush()
    prod = ro.production(db_session, start=LUNES, end=LUNES, cohort_ids=[f["c1"].id])
    assert prod[ana.id]["reject_rate"] is None
    assert prod[ana.id]["by_day"] == {}                # atender no es dictamen


def test_produccion_consultas_fijas(db_session, fabrica):
    f = fabrica
    kw = {"start": LUNES, "end": LUNES + timedelta(days=4),
          "cohort_ids": [f["c1"].id, f["c2"].id]}
    tipos = ("document_approved", "document_rejected", "appointment_attended",
             "appointment_no_show")

    def sembrar(n_actores):
        for _ in range(n_actores):
            u = f["make_user"]()
            for i, tipo in enumerate(tipos):
                f["evento"](f["p1"], u, tipo, _a_las(LUNES + timedelta(days=i)))
                f["evento"](f["p2"], u, tipo, _a_las(LUNES + timedelta(days=i)))
            f["evento"](f["p1"], u, "phase_approved", _a_las(LUNES), phase_number=2)
            f["revisada"](f["c1"], u, _a_las(LUNES + timedelta(days=3)))
            f["revisada"](f["c2"], u, _a_las(LUNES + timedelta(days=4)))

    sembrar(2)
    pocos = _contar(db_session, lambda: ro.production(db_session, **kw))
    assert len(ro.production(db_session, **kw)) == 2
    sembrar(6)
    muchos = _contar(db_session, lambda: ro.production(db_session, **kw))
    assert len(ro.production(db_session, **kw)) == 8
    assert pocos == muchos <= 3


# ---------------------------------------------------------------------------
# 5. capacity (BD)
# ---------------------------------------------------------------------------
@pytest.fixture()
def agenda(db_session, make_cohort, make_review_day, make_review_window, make_process,
           make_student, make_user):
    """Días de cotejo de una convocatoria propia, ventanas y citas que ocupan."""
    from itcj2.apps.titulatec.models import ReviewAppointment

    cohort = make_cohort()
    dias: dict[date, object] = {}

    def dia(d, *, closed=False):
        if d not in dias:
            dias[d] = make_review_day(cohort, day=d)
        if closed:
            dias[d].is_closed = True
            db_session.flush()
        return dias[d]

    def ventana(owner, d, **kw):
        return make_review_window(dia(d), owner, **kw)

    def cita(w, d, hhmm="09:00", status="confirmed"):
        alumno = make_student()
        proc = make_process(alumno, cohort=cohort, current_phase=2)
        h, m = (int(x) for x in hhmm.split(":"))
        db_session.add(ReviewAppointment(
            process_id=proc.id, window_id=w.id,
            scheduled_at=datetime.combine(d, time(h, m)), status=status,
            created_by_id=alumno.id))
        db_session.flush()

    return {"dia": dia, "ventana": ventana, "cita": cita, "make_user": make_user}


def test_capacidad_suma_ventanas_abiertas_en_los_proximos_dias_habiles(db_session, agenda):
    g = agenda
    ana, beto = g["make_user"](), g["make_user"]()
    lun, mie, vie = LUNES, LUNES + timedelta(days=2), LUNES + timedelta(days=4)

    # Ana, hoy (lunes): 09:00-10:00 cada 30 min x2 = 4 lugares, 1 ocupado.
    w1 = g["ventana"](ana, lun, start="09:00", end="10:00", slot=30, cap=2)
    g["cita"](w1, lun, "09:00")
    g["cita"](w1, lun, "09:30", status="cancelled")          # no ocupa
    # Ana, viernes, sin horario: 10 lugares, 2 ocupados.
    w2 = g["ventana"](ana, vie, start="09:00", end="13:00", cap=10, visibility="walkin")
    g["cita"](w2, vie, "09:00")
    g["cita"](w2, vie, "09:00", status="scheduled")
    # Beto, miércoles: 10:00-11:00 cada 20 x1 = 3 lugares.
    g["ventana"](beto, mie, start="10:00", end="11:00", slot=20, cap=1)

    # Fuera: pausada, día cerrado, sábado, y el sexto día hábil.
    g["ventana"](beto, LUNES + timedelta(days=1), status="paused")
    g["ventana"](beto, LUNES + timedelta(days=3), start="09:00", end="10:00")
    g["dia"](LUNES + timedelta(days=3), closed=True)
    g["ventana"](ana, LUNES + timedelta(days=5), start="09:00", end="10:00", cap=5)
    g["ventana"](ana, LUNES + timedelta(days=7), start="09:00", end="10:00", cap=5)

    cap = ro.capacity(db_session, today=LUNES)
    assert cap == {ana.id: (1 + 2, 4 + 10), beto.id: (0, 3), 0: (3, 17)}


def test_capacidad_desde_hoy_inclusive_y_desde_un_fin_de_semana(db_session, agenda):
    g = agenda
    ana = g["make_user"]()
    sab = LUNES + timedelta(days=5)
    lun2 = LUNES + timedelta(days=7)
    g["ventana"](ana, sab, start="09:00", end="10:00", slot=60, cap=7)     # el propio sábado
    g["ventana"](ana, lun2 + timedelta(days=4), start="09:00", end="10:00", slot=60, cap=2)
    g["ventana"](ana, lun2 + timedelta(days=7), start="09:00", end="10:00", slot=60, cap=9)

    # Hoy sábado: los 5 hábiles son lun2..vie2; el sábado no es hábil.
    assert ro.capacity(db_session, today=sab) == {ana.id: (0, 2), 0: (0, 2)}
    # `days` acota: solo el lunes siguiente (sin ventanas de Ana ese día).
    assert ro.capacity(db_session, today=sab, days=1) == {0: (0, 0)}


def test_capacidad_vacia_trae_el_total_en_cero(db_session, agenda):
    assert ro.capacity(db_session, today=LUNES) == {0: (0, 0)}
    assert _contar(db_session, lambda: ro.capacity(db_session, today=LUNES, days=0)) == 0
    assert ro.capacity(db_session, today=LUNES, days=0) == {0: (0, 0)}


def test_capacidad_consultas_fijas(db_session, agenda):
    g = agenda
    duenos = [g["make_user"]() for _ in range(3)]
    k = itertools.count()

    def sembrar(n):
        # (día, hora) distintos por ventana: UNIQUE (día, dueño, inicio).
        for i in itertools.islice(k, n):
            d, hora = LUNES + timedelta(days=i % 5), f"{8 + i // 5:02d}"
            w = g["ventana"](duenos[i % 3], d, start=f"{hora}:00", end=f"{hora}:30",
                             slot=30, cap=3)
            g["cita"](w, d, f"{hora}:00")

    sembrar(2)
    db_session.expire_all()
    pocos = _contar(db_session, lambda: ro.capacity(db_session, today=LUNES))
    sembrar(10)
    db_session.expire_all()
    muchos = _contar(db_session, lambda: ro.capacity(db_session, today=LUNES))
    assert ro.capacity(db_session, today=LUNES)[0] == (12, 36)
    assert pocos == muchos == 2            # ventanas + ocupación en lote
