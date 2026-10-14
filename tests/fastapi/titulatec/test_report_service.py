"""Fachada del Tablero de la jefa de Servicios Escolares (Task 6).

Spec `docs/superpowers/specs/2026-10-14-titulatec-tablero-design.md` §3
(parámetros de URL), §4 (definiciones), §5 (pestañas) y §8 (bordes).

1. **Puras** (sin BD): `ReportFilters.parse` con basura, `query()` estable y sin
   defaults, toggles involutivos, elección de la convocatoria por omisión.
2. **`ReportService.build` con BD** sobre un escenario propio (2 carreras + «Sin
   carrera», 2 encargados traslapados, un pendiente en cada etapa, 2 liberados):
   los números de cada pestaña, doble pelota sin inflar procesos únicos,
   ocultar carrera/encargado, convocatoria vacía, sin convocatorias y cada
   alerta disparando solo con su condición.

«Hoy» = `db_now().date()` (nunca `date.today()`: el runner de CI está en UTC).
Lo que cae en días hábiles (producción, liberaciones del calendario) se fecha en
días hábiles reales para que la prueba no dependa del día de la semana en que
corre. La base de dev es compartida: toda consulta va acotada a la convocatoria
del escenario y las aserciones sobre encargados filtran a los propios.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from itertools import count
from types import SimpleNamespace
from urllib.parse import parse_qsl

import pytest

from itcj2.apps.titulatec.services import report_officers as ro
from itcj2.apps.titulatec.services import report_service as rsv
from itcj2.apps.titulatec.services.report_service import ReportFilters, ReportService
from itcj2.apps.titulatec.utils.business_days import (
    add_business_days,
    last_business_days,
)

PERM = "titulatec.reports.page.view"
_SEQ = count(1)


# ===========================================================================
# 1. ReportFilters (puras)
# ===========================================================================
def test_parse_vacio_da_los_defaults():
    f = ReportFilters.parse({})
    assert f == ReportFilters()
    assert (f.tab, f.cohort, f.range_days, f.level, f.page) == ("panorama", None, 14, "warn", 1)
    assert f.hidden_programs == frozenset() and f.hidden_officers == frozenset()
    assert (f.ball, f.stage, f.day) == (None, None, None)


def test_parse_con_basura_nunca_levanta_y_cae_al_default():
    f = ReportFilters.parse({
        "tab": "foo", "cohort": "abc", "range": "-3", "px": "1,,x", "ox": "a,-2,7",
        "ball": "nadie", "level": "zzz", "stage": "nope", "page": "0", "day": "2026-13-45",
    })
    assert f.tab == "panorama"
    assert f.cohort is None
    assert f.range_days == 14
    assert f.hidden_programs == frozenset({1})
    assert f.hidden_officers == frozenset({7})
    assert (f.ball, f.level, f.stage, f.page, f.day) == (None, "warn", None, 1, None)


def test_parse_digitos_no_ascii_no_truenan():
    """`"²".isdigit()` es True pero `int("²")` levanta: se tratan como basura."""
    f = ReportFilters.parse({"cohort": "²", "range": "³", "px": "²,3", "ox": "١٢",
                             "page": "²"})
    assert (f.cohort, f.range_days, f.page) == (None, 14, 1)
    assert f.hidden_programs == frozenset({3}) and f.hidden_officers == frozenset()


@pytest.mark.parametrize("campo", ["cohort", "range", "px", "ox", "page"])
@pytest.mark.parametrize("largo", [19, 4301, 5000])
def test_parse_con_basura_numeros_enormes_no_truenan(campo, largo):
    """`int()` de más de 4300 dígitos levanta `ValueError` (límite de CPython):
    sin tope, `cohort=999…9` era un 500. Con más de 18 dígitos es basura."""
    f = ReportFilters.parse({campo: "9" * largo})
    assert f == ReportFilters()


def test_parse_acepta_hasta_18_digitos():
    f = ReportFilters.parse({"cohort": "9" * 18, "px": f"{'9' * 18},3", "ox": "1" * 18})
    assert f.cohort == int("9" * 18)
    assert f.hidden_programs == frozenset({int("9" * 18), 3})
    assert f.hidden_officers == frozenset({int("1" * 18)})


@pytest.mark.parametrize("raw", [None, 5, ["x"], object()])
def test_parse_tolera_mapeos_raros(raw):
    assert ReportFilters.parse(raw if raw is None else {"tab": raw}).tab == "panorama"


def test_parse_valores_validos():
    f = ReportFilters.parse({
        "tab": " Atorados ", "cohort": "12", "range": "all", "px": "3, 1,0", "ox": "9",
        "ball": "gtv", "level": "crit", "stage": "docs", "page": "3", "day": "2026-10-09",
    })
    assert f.tab == "atorados"
    assert f.cohort == 12
    assert f.range_days is None
    assert f.hidden_programs == frozenset({0, 1, 3})      # 0 = «Sin carrera»
    assert f.hidden_officers == frozenset({9})
    assert (f.ball, f.level, f.stage, f.page) == ("gtv", "crit", "docs", 3)
    assert f.day == date(2026, 10, 9)
    assert ReportFilters.parse({"cohort": "ALL"}).cohort == "all"
    assert ReportFilters.parse({"range": "30"}).range_days == 30
    assert ReportFilters.parse({"range": "15"}).range_days == 14     # fuera del menú


def test_query_estable_ordenada_y_sin_defaults():
    assert ReportFilters().query() == "tab=panorama"
    f = ReportFilters(tab="atorados", cohort=7, range_days=None,
                      hidden_programs=frozenset({5, 2}), hidden_officers=frozenset({30, 4}),
                      ball="escolares", level="all", stage="docs", page=2,
                      day=date(2026, 10, 9))
    assert f.query() == ("tab=atorados&cohort=7&range=all&px=2,5&ox=4,30&ball=escolares"
                         "&level=all&stage=docs&page=2&day=2026-10-09")
    # Los defaults se quitan aunque vengan explícitos.
    assert ReportFilters(range_days=14, level="warn", page=1).query() == "tab=panorama"
    # `changes` no muta el original.
    assert f.query(page=1, day=None, tab="ritmo").startswith("tab=ritmo&cohort=7")
    assert f.page == 2


def test_query_ida_y_vuelta():
    f = ReportFilters(tab="encargados", cohort="all", range_days=30,
                      hidden_programs=frozenset({0, 8}), hidden_officers=frozenset({4}),
                      ball="computo", level="crit", stage="req_access", page=4,
                      day=date(2026, 9, 30))
    assert ReportFilters.parse(dict(parse_qsl(f.query()))) == f


def test_urls_de_pagina_y_de_parcial():
    f = ReportFilters(tab="ritmo")
    assert f.page_url() == "/titulatec/admin/tablero?tab=ritmo"
    assert f.body_url(range_days=7) == "/titulatec/admin/tablero/body?tab=ritmo&range=7"


def test_toggles_son_involutivos_y_no_tocan_lo_demas():
    f = ReportFilters(tab="encargados", page=3, hidden_programs=frozenset({1}))
    con = f.toggle_program(2)
    assert con.hidden_programs == frozenset({1, 2}) and con.page == 3
    assert con.toggle_program(2) == f
    assert f.toggle_program(1).hidden_programs == frozenset()
    assert f.toggle_officer(9).hidden_officers == frozenset({9})
    assert f.toggle_officer(9).toggle_officer(9) == f


def test_la_convocatoria_por_omision_es_la_abierta_mas_reciente():
    def c(i, status):
        return SimpleNamespace(id=i, name=f"C{i}", status=status,
                               opens_at=datetime(2026, 1, i))
    filas = [c(9, "draft"), c(8, "closed"), c(7, "open"), c(5, "open")]   # id desc
    assert rsv._pick_cohort(filas, None) == ([7], filas[2])
    assert rsv._pick_cohort(filas, 8) == ([8], filas[1])
    assert rsv._pick_cohort(filas, 123) == ([7], filas[2])                 # inexistente
    assert rsv._pick_cohort(filas, "all") == (None, None)
    sin_abiertas = [c(4, "closed"), c(3, "draft")]
    assert rsv._pick_cohort(sin_abiertas, None) == ([4], sin_abiertas[0])
    assert rsv._pick_cohort([], None) == ([], None)


# ===========================================================================
# 2. Escenario con BD
# ===========================================================================
@pytest.fixture()
def esc(db_session, seed_phase_defs, seed_document_types, make_program, make_cohort,
        make_student, make_process, make_document, make_survey_review, make_review_day,
        make_review_window, make_department, make_position, link_programs,
        assign_position, make_user, make_head):
    """Convocatoria propia con el candado de requisitos, carreras A y B, dos
    encargados de Servicios Escolares traslapados (Ana: A+B, Beto: A) y la jefa.

    Pendientes (13 items + 1 en pausa):

    | id | carrera | etapa | pelota | días |
    |---|---|---|---|---|
    | r_a_vieja | A | req_review | Escolares | 15 (crit) |
    | r_a_nip | A | req_access | Cómputo | 2 |
    | r_b_nueva | B | req_review | Escolares | 0 |
    | r_b_liga | B | req_approved | Alumno | 1 |
    | p_a_docs | A | docs (1 doc por dictaminar) | Escolares | 10 (warn) |
    | p_b_docs | B | docs | Alumno | 0 |
    | p_sin_docs | — | docs (1 doc) | Escolares | 0 |
    | p_a_doble | A | requisitos | Alumno (pago) + GTV | 0 |
    | p_b_listo | B | requisitos (listo para agendar) | Alumno | 0 |
    | p_a_futura | A | cita futura (ventana de Ana) | — | 0 |
    | p_a_pasada | A | cita pasada sin cerrar (ventana de Ana) | Escolares | 0 |
    | p_a_lib | A | liberado (b1, por Ana) | — | — |
    | p_b_lib | B | liberado (b0, por la jefa) | — | — |
    | p_b_pausa | B | en pausa | — | — |
    """
    from itcj2.apps.titulatec.models import (
        EnrollmentRequest,
        ProcessEvent,
        ProcessPhase,
        ReviewAppointment,
    )
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )
    from itcj2.core.utils.timezone import db_now
    from tests.fastapi.titulatec.conftest import HEAD_PERMS

    seed_phase_defs()
    seed_document_types()
    hoy = db_now().date()
    b0, b1 = last_business_days(hoy, 2)[::-1]          # b0 = hoy o el último hábil
    pa = make_program("Ingenieria Fachada Tablero A")
    pb = make_program("Ingenieria Fachada Tablero B")
    c = make_cohort()
    CotejoRequirementService.seed_defaults(db_session, c.id, commit=False)

    depto = make_department(code="school_services", name="Servicios Escolares")
    ana = make_user(first_name="ANA", last_name="AAFACHADA")
    beto = make_user(first_name="BETO", last_name="BBFACHADA")
    for user, progs in ((ana, [pa, pb]), (beto, [pa])):
        pos = make_position(code=f"se_officer_tt6{next(_SEQ):05d}", department=depto)
        link_programs(pos, progs)
        assign_position(user, pos)
    jefa = make_head(perm_codes=HEAD_PERMS + (PERM,))

    sig = add_business_days(hoy, 1)
    w_fut = make_review_window(make_review_day(c, day=sig), ana, start="09:00", end="10:00",
                               slot=30, cap=1)
    w_pas = make_review_window(make_review_day(c, day=hoy - timedelta(days=1)), ana,
                               start="09:00", end="10:00", slot=30, cap=1)
    ventanas_de_hoy = []                    # se crea al primer uso: no mueve la capacidad de Ana

    def w_hoy():
        if not ventanas_de_hoy:
            ventanas_de_hoy.append(make_review_window(make_review_day(c, day=hoy), ana,
                                                      start="09:00", end="10:00", slot=30, cap=1))
        return ventanas_de_hoy[0]

    def a_las(d, h=10):
        return datetime.combine(d, time(h, 0))

    def hace(dias, h=8):
        return datetime.combine(hoy - timedelta(days=dias), time(h, 0))

    def solicitud(status, program, *, creada, revisada=None, por=None, vence=None):
        n = next(_SEQ)
        row = EnrollmentRequest(
            cohort_id=c.id, control_number=f"96{n:06d}", first_name="SOLICITANTE",
            last_name="FACHADA", program_id=getattr(program, "id", program),
            phone="6560000000", contact_email=f"tt6.{n}@example.invalid", has_efirma=False,
            kind="unknown", status=status, verify_send_count=0, created_at=creada,
            reviewed_at=revisada, reviewed_by_id=getattr(por, "id", por),
            verify_expires_at=vence)
        db_session.add(row)
        db_session.flush()
        return row

    def proceso(clase, program, *, status="active", creado_hace=0):
        alumno = make_student()
        if clase in ("docs_pend", "docs_alumno"):
            p = make_process(alumno, cohort=c, program=program, status=status, current_phase=1)
            if clase == "docs_pend":
                make_document(p, type_code="birth_certificate", review_status="pending")
            else:
                make_document(p, type_code="birth_certificate", review_status="rejected")
        elif clase == "liberado":
            p = make_process(alumno, cohort=c, program=program, status=status, current_phase=3)
        else:
            biblioteca, encuesta = {"doble": ("awaiting_payment", "in_review"),
                                    "listo": ("cleared", "approved"),
                                    "futura": ("cleared", "approved"),
                                    "pasada": ("cleared", "approved"),
                                    "en_curso_hoy": ("cleared", "approved"),
                                    "en_curso_ayer": ("cleared", "approved")}[clase]
            p = make_process(alumno, cohort=c, program=program, status=status,
                             current_phase=2, library_clearance=biblioteca)
            make_survey_review(p, status=encuesta)
            cita = {"futura": (w_fut, sig, "confirmed"),
                    "pasada": (w_pas, hoy - timedelta(days=1), "confirmed"),
                    "en_curso_hoy": (None, hoy, "in_progress"),        # «Atender ahora»
                    "en_curso_ayer": (w_pas, hoy - timedelta(days=1), "in_progress")}.get(clase)
            if cita is not None:
                w, dia, estado = cita
                w = w or w_hoy()
                db_session.add(ReviewAppointment(
                    process_id=p.id, window_id=w.id, scheduled_at=a_las(dia, 9),
                    status=estado, created_by_id=alumno.id))
        p.created_at = hace(creado_hace)
        db_session.flush()
        return p

    def liberar(p, dia, por):
        f2 = (db_session.query(ProcessPhase)
              .filter_by(process_id=p.id, phase_number=2).one())
        f2.completed_at = a_las(dia, 13)
        f2.reviewed_by_id = por.id
        db_session.add(ProcessEvent(process_id=p.id, actor_id=por.id,
                                    event_type="phase_approved", phase_number=2,
                                    created_at=a_las(dia, 13)))
        db_session.flush()

    def evento(actor, tipo, dia, proc):
        db_session.add(ProcessEvent(process_id=proc.id, actor_id=actor.id, event_type=tipo,
                                    created_at=a_las(dia, 11)))
        db_session.flush()

    t = SimpleNamespace(
        db=db_session, hoy=hoy, b0=b0, b1=b1, sig=sig, pa=pa, pb=pb, c=c,
        ana=ana, beto=beto, jefa=jefa, w_fut=w_fut, w_pas=w_pas,
        solicitud=solicitud, proceso=proceso, liberar=liberar, evento=evento,
        hace=hace, make_cohort=make_cohort, make_program=make_program)
    return t


@pytest.fixture()
def lleno(esc):
    """El escenario de la tabla de `esc`, completo."""
    t = esc
    t.r_a_vieja = t.solicitud("pending_review", t.pa, creada=t.hace(15))
    t.r_a_nip = t.solicitud("awaiting_access", t.pa, creada=t.hace(3),
                            revisada=datetime.combine(t.b1, time(9)), por=t.beto)
    t.r_b_nueva = t.solicitud("pending_review", t.pb, creada=t.hace(0, h=0))
    t.r_b_liga = t.solicitud("approved", t.pb, creada=t.hace(2),
                             revisada=datetime.combine(t.b1, time(10)), por=t.beto,
                             vence=t.hace(-10))
    t.p_a_docs = t.proceso("docs_pend", t.pa, creado_hace=10)
    t.p_b_docs = t.proceso("docs_alumno", t.pb)
    t.p_sin_docs = t.proceso("docs_pend", None)
    t.p_a_doble = t.proceso("doble", t.pa)
    t.p_b_listo = t.proceso("listo", t.pb)
    t.p_a_futura = t.proceso("futura", t.pa)
    t.p_a_pasada = t.proceso("pasada", t.pa)
    t.p_a_lib = t.proceso("liberado", t.pa)
    t.p_b_lib = t.proceso("liberado", t.pb)
    t.p_b_pausa = t.proceso("docs_pend", t.pb, status="on_hold")
    t.liberar(t.p_a_lib, t.b1, t.ana)
    t.liberar(t.p_b_lib, t.b0, t.jefa)
    # Producción en días hábiles: Ana dictamina 4 (1 rechazo); la jefa, 1. Se
    # cuelgan de los liberados para no mover los días sin movimiento de nadie.
    for tipo in ("document_approved", "document_approved", "document_approved",
                 "document_rejected"):
        t.evento(t.ana, tipo, t.b0, t.p_a_lib)
    t.evento(t.jefa, "document_approved", t.b0, t.p_b_lib)
    return t


def _build(t, tab="panorama", **kw):
    f = ReportFilters(tab=tab, cohort=kw.pop("cohort", t.c.id), **kw)
    return ReportService.build(t.db, user_id=t.jefa.id, filters=f, today=t.hoy)


def _por_codigo(lista):
    return {x["code"]: x for x in lista}


def _bdays_en_rango(hoy, dias=14):
    inicio = hoy - timedelta(days=dias - 1)
    return sum(1 for i in range(dias) if (inicio + timedelta(days=i)).weekday() < 5)


# ---------------------------------------------------------------------------
# Contexto común
# ---------------------------------------------------------------------------
def test_contexto_comun(lleno):
    t = lleno
    ctx = _build(t)
    assert ctx["filters"].cohort == t.c.id
    assert ctx["tab"] == "panorama"
    assert [x["code"] for x in ctx["tabs"]] == ["panorama", "ritmo", "encargados",
                                                "carreras", "atorados"]
    activa = [x for x in ctx["tabs"] if x["active"]]
    assert [x["code"] for x in activa] == ["panorama"]
    ritmo = _por_codigo(ctx["tabs"])["ritmo"]
    assert ritmo["url"] == f"/titulatec/admin/tablero?tab=ritmo&cohort={t.c.id}"
    assert ritmo["body_url"] == f"/titulatec/admin/tablero/body?tab=ritmo&cohort={t.c.id}"
    mia = [c for c in ctx["cohorts"] if c["id"] == t.c.id]
    assert len(mia) == 1 and mia[0]["selected"] is True
    assert ctx["cohorts"][-1]["id"] == "all"
    chips = {c["id"]: c for c in ctx["program_chips"]}
    assert set(chips) >= {t.pa.id, t.pb.id, 0}
    assert chips[0]["name"] == "Sin carrera"
    assert chips[t.pa.id]["hidden"] is False
    assert chips[t.pa.id]["toggle_url"] == (
        f"/titulatec/admin/tablero?tab=panorama&cohort={t.c.id}&px={t.pa.id}")
    assert chips[t.pa.id]["body_toggle_url"].startswith("/titulatec/admin/tablero/body?")
    rangos = [r["code"] for r in ctx["range_options"]]
    assert rangos == ["7", "14", "30", "all"]
    assert [r["code"] for r in ctx["range_options"] if r["active"]] == ["14"]
    assert ctx["today"] == t.hoy
    assert ctx["idle"] == {"warn": 7, "crit": 14}
    assert "Panorama" in ctx["print_summary"] and t.c.name in ctx["print_summary"]
    # Solo la pestaña activa se calcula.
    assert "panorama" in ctx and not ({"ritmo", "encargados", "carreras", "atorados"} & set(ctx))


def test_la_convocatoria_por_omision_en_build(lleno):
    """La del escenario es la más nueva y está abierta: la elige sola."""
    t = lleno
    f = ReportFilters()
    ctx = ReportService.build(t.db, user_id=t.jefa.id, filters=f, today=t.hoy)
    assert ctx["selected_cohort"]["id"] == t.c.id
    assert ctx["panorama"]["kpis"]["liberated"]["total"] == 2
    # Una convocatoria inexistente cae a la de omisión y no viaja en las ligas.
    ctx = _build(t, cohort=987654321)
    assert ctx["selected_cohort"]["id"] == t.c.id
    assert ctx["filters"].cohort is None


# ---------------------------------------------------------------------------
# Panorama
# ---------------------------------------------------------------------------
def test_panorama_numeros_del_escenario(lleno):
    t = lleno
    p = _build(t)["panorama"]
    etapas = {s["code"]: s["value"] for s in p["stages"]}
    assert etapas == {"req_unverified": 0, "req_review": 2, "req_access": 1,
                      "req_approved": 1, "docs": 3, "requisitos": 2, "cita": 2, "liberado": 2}
    assert [s["code"] for s in p["stages"]] == [
        "req_unverified", "req_review", "req_access", "req_approved", "docs",
        "requisitos", "cita", "liberado"]
    docs = _por_codigo(p["stages"])["docs"]
    assert docs["color"] == "#3987e5" and docs["pct"] == 100
    assert docs["url"] == f"/titulatec/admin/tablero?tab=atorados&cohort={t.c.id}&level=all&stage=docs"

    pelotas = _por_codigo(p["balls"])
    assert [b["code"] for b in p["balls"]] == ["escolares", "alumno", "gtv", "biblioteca", "computo"]
    assert {k: v["value"] for k, v in pelotas.items()} == {
        "escolares": 5, "alumno": 4, "gtv": 1, "biblioteca": 0, "computo": 1}
    assert (pelotas["escolares"]["stuck"], pelotas["escolares"]["crit"]) == (2, 1)
    assert pelotas["alumno"]["stuck"] == 0
    assert pelotas["gtv"]["url"].endswith("&ball=gtv&level=all")
    assert pelotas["escolares"]["stuck_url"].endswith("&ball=escolares")    # level=warn default

    k = p["kpis"]
    assert (k["liberated"]["total"], k["liberated"]["in_range"]) == (2, 2)
    assert k["liberated"]["spark"]                                    # puntos SVG
    assert k["requests"] == {**k["requests"], "pending": 2, "oldest_days": 15}
    assert (k["stuck"]["crit"], k["stuck"]["warn"], k["stuck"]["total"]) == (1, 1, 2)
    assert k["pace"]["per_day"] == pytest.approx(0.2)
    assert k["pace"]["pending"] == 11
    assert k["pace"]["forecast"] == add_business_days(t.hoy, 55)       # ⌈11 ÷ 0.2⌉
    assert "sin contar feriados" in k["pace"]["note"]
    assert p["on_hold"] == 1


def test_doble_pelota_no_infla_los_procesos_unicos(lleno):
    p = _build(lleno)["panorama"]
    suma = sum(b["value"] for b in p["balls"])
    assert p["pending_total"] == 11
    assert p["with_ball"] == 10                 # la cita futura no tiene pelota
    assert p["multi_ball"] == 1
    assert suma == p["with_ball"] + p["multi_ball"] == 11


def test_panorama_alertas_del_escenario(lleno, monkeypatch):
    monkeypatch.setattr(ro, "capacity", lambda db, *, today, days=5: {0: (0, 0)})
    alertas = _build(lleno)["panorama"]["alerts"]
    assert [a["code"] for a in alertas] == ["requests_crit", "docs_warn", "capacity",
                                            "inflow", "appts_unclosed"]
    assert all(a["level"] in ("warn", "crit") and a["text"] and a["url"] for a in alertas)
    por = _por_codigo(alertas)
    assert por["requests_crit"]["level"] == "crit"
    assert por["requests_crit"]["url"].endswith("&level=crit&stage=req_review")
    assert por["docs_warn"]["url"].endswith("&ball=escolares&stage=docs")
    assert "1 " in por["appts_unclosed"]["text"]


def test_ocultar_una_carrera_saca_sus_items(lleno):
    t = lleno
    ctx = _build(t, hidden_programs=frozenset({t.pb.id}))
    p = ctx["panorama"]
    etapas = {s["code"]: s["value"] for s in p["stages"]}
    assert etapas == {"req_unverified": 0, "req_review": 1, "req_access": 1,
                      "req_approved": 0, "docs": 2, "requisitos": 1, "cita": 2, "liberado": 1}
    assert p["on_hold"] == 0                     # la pausada era de B
    chips = {c["id"]: c for c in ctx["program_chips"]}
    assert chips[t.pb.id]["hidden"] is True and chips[t.pb.id]["name"] == t.pb.name
    assert chips[t.pb.id]["toggle_url"] == f"/titulatec/admin/tablero?tab=panorama&cohort={t.c.id}"
    assert ctx["hidden_programs_count"] == 1
    # Ocultar «Sin carrera» (px=0) saca el documento sin carrera.
    sin = _build(t, hidden_programs=frozenset({0}))["panorama"]
    assert {s["code"]: s["value"] for s in sin["stages"]}["docs"] == 2


def test_ocultar_todas_avisa_con_enlace_mostrar_todas(lleno):
    t = lleno
    ctx = _build(t, hidden_programs=frozenset({t.pa.id, t.pb.id, 0}))
    assert ctx["all_hidden"] is True
    assert ctx["show_all_url"] == f"/titulatec/admin/tablero?tab=panorama&cohort={t.c.id}"
    assert sum(s["value"] for s in ctx["panorama"]["stages"]) == 0


def test_ocultar_un_encargado_no_cambia_las_pelotas(lleno):
    t = lleno
    def numeros(ctx):
        return [(b["code"], b["value"], b["stuck"], b["crit"], b["pct"], b["color"])
                for b in ctx["panorama"]["balls"]]

    base = _build(t)
    sin_ana = _build(t, hidden_officers=frozenset({t.ana.id}))
    assert numeros(sin_ana) == numeros(base)
    assert sin_ana["panorama"]["pending_total"] == base["panorama"]["pending_total"]
    # Las ligas sí conservan el filtro vigente (`ox` viaja).
    assert f"ox={t.ana.id}" in sin_ana["panorama"]["balls"][0]["url"]


# ---------------------------------------------------------------------------
# Alertas: cada una solo con su condición
# ---------------------------------------------------------------------------
@pytest.fixture()
def capacidad_amplia(monkeypatch):
    monkeypatch.setattr(ro, "capacity", lambda db, *, today, days=5: {0: (0, 100)})


def _alertas(t, **kw):
    return [a["code"] for a in _build(t, **kw)["panorama"]["alerts"]]


def test_sin_pendientes_no_hay_alertas(esc, capacidad_amplia):
    assert _alertas(esc) == []


def test_alerta_solicitud_vieja(esc, capacidad_amplia):
    t = esc
    # Rango de 7 días: ninguna de las dos entra a «entradas vs salidas».
    t.solicitud("pending_review", t.pa, creada=t.hace(13))            # 13 < 14: no
    assert _alertas(t, range_days=7) == []
    t.solicitud("pending_review", t.pa, creada=t.hace(14))
    assert _alertas(t, range_days=7) == ["requests_crit"]


def test_alerta_documentos_lentos(esc, capacidad_amplia):
    t = esc
    t.proceso("docs_pend", t.pa, creado_hace=6)
    t.proceso("docs_alumno", t.pa, creado_hace=20)                    # no es de Escolares
    assert _alertas(t) == []
    t.proceso("docs_pend", t.pa, creado_hace=7)
    assert _alertas(t) == ["docs_warn"]


def test_alerta_capacidad(esc, monkeypatch):
    t = esc
    t.proceso("listo", t.pa)
    t.proceso("listo", t.pb)
    monkeypatch.setattr(ro, "capacity", lambda db, *, today, days=5: {0: (3, 5)})
    assert _alertas(t) == []                                          # 2 listos, 2 libres
    monkeypatch.setattr(ro, "capacity", lambda db, *, today, days=5: {0: (4, 5)})
    assert _alertas(t) == ["capacity"]                                # 2 listos, 1 libre


def test_alerta_entradas_mayores_que_salidas(esc, capacidad_amplia):
    t = esc
    t.solicitud("pending_review", t.pa, creada=t.hace(0, h=0))
    lib = t.proceso("liberado", t.pa)
    t.liberar(lib, t.b0, t.ana)
    assert _alertas(t) == []                                          # 1 entra, 1 sale
    t.solicitud("pending_review", t.pb, creada=t.hace(1))
    assert _alertas(t) == ["inflow"]


def test_alerta_citas_pasadas_por_motivo_no_por_nivel(esc, capacidad_amplia):
    """La cita de ayer recién creada sale «Al día» (nivel ok) y aun así alerta."""
    t = esc
    t.proceso("futura", t.pa)
    assert _alertas(t) == []
    t.proceso("pasada", t.pa)
    assert _alertas(t) == ["appts_unclosed"]


def test_cita_en_atencion_hoy_no_es_cita_sin_cerrar(esc, capacidad_amplia):
    """«Atender ahora»: la cita `in_progress` de HOY es «En atención» (Escolares),
    no «Cerrar cita», y no alerta. La `in_progress` de AYER sí quedó sin cerrar."""
    t = esc
    hoy = t.proceso("en_curso_hoy", t.pa)
    p = _build(t)["panorama"]
    assert p["alerts"] == []
    fila = next(r for r in _build(t, "atorados", level="all")["atorados"]["page"].items
                if r["id"] == hoy.id)
    assert fila["motive_text"] == "Escolares: En atención"
    ayer = t.proceso("en_curso_ayer", t.pa)
    assert _alertas(t) == ["appts_unclosed"]
    fila = next(r for r in _build(t, "atorados", level="all")["atorados"]["page"].items
                if r["id"] == ayer.id)
    assert fila["motive_text"] == "Escolares: Cerrar cita"
    assert "1 cita pasada" in _build(t)["panorama"]["alerts"][0]["text"]


def test_la_regla_de_solicitudes_es_una_sola_alerta_y_caben_las_cinco(lleno, monkeypatch):
    """Con solicitudes viejas en las dos etapas (legado incluido) la regla 1 sale
    UNA vez con el conteo sumado y la regla 5 no se cae del tope de 5."""
    t = lleno
    monkeypatch.setattr(ro, "capacity", lambda db, *, today, days=5: {0: (0, 0)})
    t.solicitud("unverified", t.pa, creada=t.hace(20))
    alertas = _build(t)["panorama"]["alerts"]
    assert [a["code"] for a in alertas] == ["requests_crit", "docs_warn", "capacity",
                                            "inflow", "appts_unclosed"]
    assert alertas[0]["text"].startswith("2 solicitudes por revisar")
    assert alertas[0]["url"].endswith("&level=crit&stage=req_review")
    # Solo legado: la liga apunta a su etapa.
    t2 = lleno
    t2.r_a_vieja.status = "rejected"
    t2.db.flush()
    solo = _build(t2)["panorama"]["alerts"][0]
    assert solo["code"] == "requests_crit" and solo["text"].startswith("1 solicitud por revisar")
    assert solo["url"].endswith("&level=crit&stage=req_unverified")


# ---------------------------------------------------------------------------
# Ritmo
# ---------------------------------------------------------------------------
def test_ritmo_series_acumulado_calendario_y_carreras(lleno):
    t = lleno
    r = _build(t, "ritmo")["ritmo"]
    series = {s["key"]: s for s in r["daily"]["series"]}
    assert set(series) == {"requests_new", "liberated"}
    assert len(r["daily"]["days"]) == 14
    assert series["requests_new"]["sum"] == 3               # la de hace 15 días queda fuera
    assert series["liberated"]["sum"] == 2
    assert r["daily"]["ticks"][0]["value"] == 0
    assert series["liberated"]["points"].count(",") == 14

    acum = {s["key"]: s for s in r["cumulative"]["series"]}
    assert acum["enrolled"]["last"] == 10                   # 9 vivos/liberados + 1 en pausa
    assert acum["liberated"]["last"] == 2
    assert r["cumulative"]["days"][0]["date"] <= t.hoy - timedelta(days=10)

    celdas = {c["date"]: c for semana in r["calendar"]["weeks"] for c in semana}
    assert celdas[t.b0]["n"] == 1 and celdas[t.b1]["n"] == 1
    assert celdas[t.b0]["bin"] == 5
    assert celdas[t.b1]["url"].endswith(f"&day={t.b1.isoformat()}")
    assert r["calendar"]["legend"][0]["bin"] == 0

    carreras = {x["id"]: x["value"] for x in r["by_program"]}
    assert carreras == {t.pa.id: 1, t.pb.id: 1}
    assert r["selected_day"] is None and r["day_list"] == []


def test_ritmo_lista_del_dia_seleccionado(lleno):
    t = lleno
    r = _build(t, "ritmo", day=t.b1)["ritmo"]
    assert r["selected_day"] == t.b1
    (fila,) = r["day_list"]
    assert fila["id"] == t.p_a_lib.id
    assert fila["program"] == t.pa.name
    assert fila["officer"] == t.ana.full_name
    assert fila["href"] == f"/titulatec/admin/processes/{t.p_a_lib.id}"
    assert r["clear_day_url"] == f"/titulatec/admin/tablero?tab=ritmo&cohort={t.c.id}"


# ---------------------------------------------------------------------------
# Encargados
# ---------------------------------------------------------------------------
def test_encargados_cola_traslapada_produccion_y_lugares(lleno):
    t = lleno
    e = _build(t, "encargados")["encargados"]
    filas = {r["user_id"]: r for r in e["rows"] if r["user_id"] in (t.ana.id, t.beto.id)}
    ana, beto = filas[t.ana.id], filas[t.beto.id]
    assert ana["queue"] == {"req_review": 2, "docs_pending": 1, "appts_to_close": 1,
                            "ready_to_book": 1, "total_escolares": 4}
    assert beto["queue"] == {"req_review": 1, "docs_pending": 1, "appts_to_close": 0,
                             "ready_to_book": 0, "total_escolares": 2}
    assert [p["name"] for p in ana["programs"]] == sorted([t.pa.name, t.pb.name])
    assert ana["prod"]["docs_approved"] == 3 and ana["prod"]["docs_rejected"] == 1
    assert ana["prod"]["liberated"] == 1
    assert ana["reject_text"] == "25%"
    assert beto["prod"]["req_reviewed"] == 2 and beto["reject_text"] == "—"
    n_bd = _bdays_en_rango(t.hoy)
    assert ana["days_to_clear"] == pytest.approx(n_bd)        # cola 4 ÷ (4 / n_bd)
    assert beto["days_to_clear"] == pytest.approx(n_bd)       # cola 2 ÷ (2 / n_bd)
    assert ana["places"] == {"occupied": 1, "capacity": 2, "free": 1}
    assert beto["places"] == {"occupied": 0, "capacity": 0, "free": 0}
    assert e["others"]["docs_approved"] == 1                   # la jefa no es encargada
    assert e["range_bdays"] == n_bd
    barras = {b["user_id"]: b for b in e["clear_bars"]["rows"]}
    assert barras[t.ana.id]["value"] == pytest.approx(n_bd)
    sparks = {s["user_id"]: s for s in e["sparks"]["series"]}
    assert sparks[t.ana.id]["total"] == 4 and sparks[t.beto.id]["total"] == 2
    assert e["sparks"]["vmax"] >= 4                           # misma escala para todos


def test_ocultar_un_encargado_quita_su_fila_sin_mover_a_los_demas(lleno):
    t = lleno
    todos = _build(t, "encargados")["encargados"]
    sin_ana = _build(t, "encargados", hidden_officers=frozenset({t.ana.id}))["encargados"]
    ids = {r["user_id"] for r in sin_ana["rows"]}
    assert t.ana.id not in ids and t.beto.id in ids
    fila = lambda e: next(r for r in e["rows"] if r["user_id"] == t.beto.id)
    assert fila(sin_ana)["queue"] == fila(todos)["queue"]
    assert fila(sin_ana)["color_index"] == fila(todos)["color_index"]
    chip = next(c for c in sin_ana["officer_chips"] if c["user_id"] == t.ana.id)
    assert chip["hidden"] is True
    assert chip["toggle_url"] == f"/titulatec/admin/tablero?tab=encargados&cohort={t.c.id}"


# ---------------------------------------------------------------------------
# Carreras
# ---------------------------------------------------------------------------
def test_carreras_filas_ordenadas_por_atorados(lleno):
    t = lleno
    filas = _build(t, "carreras")["carreras"]["rows"]
    assert [f["id"] for f in filas] == [t.pa.id, t.pb.id, None]
    a, b, sin = filas
    assert (a["enrolled"], a["liberated"], a["stuck"], a["crit"]) == (5, 1, 2, 1)
    assert a["pct_liberated"] == pytest.approx(20.0)
    assert {s["key"]: s["value"] for s in a["segments"]} == {
        "req_review": 1, "req_access": 1, "docs": 1, "requisitos": 1, "cita": 2, "liberado": 1}
    assert sum(s["w_pct"] for s in a["segments"]) == pytest.approx(100)
    assert sorted(a["officers"]) == sorted([t.ana.full_name, t.beto.full_name])
    # «Inscritos» = procesos creados no revocados, pausados incluidos (B tiene uno).
    assert (b["enrolled"], b["liberated"], b["stuck"]) == (4, 1, 0)
    assert b["pct_liberated"] == pytest.approx(25.0)
    assert b["officers"] == [t.ana.full_name]
    assert (sin["name"], sin["enrolled"], sin["liberated"], sin["officers"]) == (
        "Sin carrera", 1, 0, [])


# ---------------------------------------------------------------------------
# Atorados
# ---------------------------------------------------------------------------
def test_atorados_por_omision_lentos_o_mas_por_dias(lleno):
    t = lleno
    a = _build(t, "atorados")["atorados"]
    assert a["page"].total == 2
    assert [(r["kind"], r["id"]) for r in a["page"].items] == [
        ("request", t.r_a_vieja.id), ("process", t.p_a_docs.id)]
    fila = a["page"].items[0]
    assert (fila["days"], fila["level"], fila["level_label"]) == (15, "crit", "Atorado")
    assert fila["program"] == t.pa.name
    assert sorted(fila["officers"]) == sorted([t.ana.full_name, t.beto.full_name])
    assert fila["motive_text"] == "Escolares: Revisar solicitud"
    assert fila["href"].startswith("/titulatec/admin/solicitudes?")
    assert a["officers_by_program"][t.pb.id] == [t.ana.full_name]
    niveles = _por_codigo(a["chips"]["level"])
    assert niveles["warn"]["active"] is True and niveles["all"]["n"] == 13


def test_atorados_filtros_de_pelota_nivel_y_etapa(lleno):
    t = lleno
    alumno = _build(t, "atorados", ball="alumno", level="all")["atorados"]
    assert alumno["page"].total == 4
    cita = _build(t, "atorados", stage="cita", level="all")["atorados"]
    assert {r["id"] for r in cita["page"].items} == {t.p_a_futura.id, t.p_a_pasada.id}
    futura = next(r for r in cita["page"].items if r["id"] == t.p_a_futura.id)
    assert futura["motive_text"].startswith("Cita el ")
    crit = _build(t, "atorados", level="crit")["atorados"]
    assert [r["id"] for r in crit["page"].items] == [t.r_a_vieja.id]
    chips = _por_codigo(crit["chips"]["ball"])
    assert chips["escolares"]["url"] == (
        f"/titulatec/admin/tablero?tab=atorados&cohort={t.c.id}&ball=escolares&level=crit")
    assert (chips["escolares"]["n"], chips["alumno"]["n"]) == (1, 0)
    assert all("page=" not in c["url"] for c in crit["chips"]["stage"])


def test_atorados_pagina_fuera_de_rango_cae_en_la_ultima(lleno):
    a = _build(lleno, "atorados", page=99)["atorados"]
    assert a["page"].page == 1 and a["page"].total == 2


# ---------------------------------------------------------------------------
# Bordes: convocatoria vacía y sin convocatorias
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tab", ["panorama", "ritmo", "encargados", "carreras", "atorados"])
def test_convocatoria_vacia_no_truena(esc, tab, capacidad_amplia):
    t = esc
    vacia = t.make_cohort()
    ctx = _build(t, tab, cohort=vacia.id, range_days=None)
    assert tab in ctx
    if tab == "panorama":
        p = ctx["panorama"]
        assert p["pending_total"] == 0 and p["alerts"] == []
        assert p["kpis"]["pace"]["forecast_text"] == "sin pendientes"
    if tab == "atorados":
        assert ctx["atorados"]["page"].total == 0
    if tab == "carreras":
        assert ctx["carreras"]["rows"] == []


@pytest.mark.parametrize("tab", ["panorama", "ritmo", "encargados", "carreras", "atorados"])
def test_sin_convocatorias_no_truena(esc, tab, monkeypatch, capacidad_amplia):
    t = esc
    monkeypatch.setattr(rsv, "_load_cohorts", lambda db: [])
    ctx = ReportService.build(t.db, user_id=t.jefa.id,
                              filters=ReportFilters(tab=tab, day=t.hoy), today=t.hoy)
    assert ctx["no_cohorts"] is True
    assert ctx["cohorts"] == []
    assert tab in ctx


def test_ritmo_sin_ritmo_medible(esc, capacidad_amplia):
    t = esc
    t.proceso("docs_pend", t.pa)
    k = _build(t)["panorama"]["kpis"]["pace"]
    assert k["forecast"] is None and k["forecast_text"] == "sin ritmo medible"


def test_inscritos_es_lo_mismo_en_carreras_y_en_ritmo(lleno):
    """Una sola definición: procesos creados no revocados (con pausados)."""
    t = lleno
    carreras = _build(t, "carreras")["carreras"]["rows"]
    ritmo = _build(t, "ritmo")["ritmo"]
    acumulado = next(s for s in ritmo["cumulative"]["series"] if s["key"] == "enrolled")
    assert sum(r["enrolled"] for r in carreras) == acumulado["last"] == 10
    # Una carrera con solo un proceso en pausa también es fila (inscritos 1).
    pc = t.make_program("Ingenieria Fachada Tablero Solo Pausa")
    t.proceso("docs_pend", pc, status="on_hold")
    filas = {r["id"]: r for r in _build(t, "carreras")["carreras"]["rows"]}
    assert (filas[pc.id]["enrolled"], filas[pc.id]["total"], filas[pc.id]["name"]) == (
        1, 0, pc.name)


# ---------------------------------------------------------------------------
# Normalización de `px`/`ox` y alcance acotado
# ---------------------------------------------------------------------------
def test_px_y_ox_inexistentes_no_viajan_en_las_ligas(lleno):
    t = lleno
    ctx = _build(t, hidden_programs=frozenset({987654321, t.pb.id}),
                 hidden_officers=frozenset({987654322, t.ana.id}))
    assert ctx["filters"].hidden_programs == frozenset({t.pb.id})
    assert ctx["filters"].hidden_officers == frozenset({t.ana.id})
    assert all("987654321" not in x["url"] and "987654322" not in x["url"]
               for x in ctx["tabs"])
    assert {c["id"] for c in ctx["program_chips"] if c["hidden"]} == {t.pb.id}


@pytest.fixture()
def acotado(lleno, make_officer):
    """Usuario con el permiso del tablero pero SIN `read.all`: alcance = {A}."""
    from tests.fastapi.titulatec.conftest import OFFICER_PERMS

    user, _pos = make_officer([lleno.pa], perm_codes=OFFICER_PERMS + (PERM,))
    return user


def _build_como(t, user, tab="panorama", **kw):
    f = ReportFilters(tab=tab, cohort=kw.pop("cohort", t.c.id), **kw)
    return ReportService.build(t.db, user_id=user.id, filters=f, today=t.hoy)


@pytest.mark.parametrize("tab", ["panorama", "ritmo", "encargados", "carreras", "atorados"])
def test_usuario_acotado_no_ve_ni_nombra_carreras_fuera_de_su_alcance(lleno, acotado, tab,
                                                                       capacidad_amplia):
    t = lleno
    ctx = _build_como(t, acotado, tab, hidden_programs=frozenset({t.pb.id, 0}))
    # `px` fuera del alcance (B) y «Sin carrera» (no puede verla) se descartan.
    assert ctx["filters"].hidden_programs == frozenset()
    assert {c["id"] for c in ctx["program_chips"]} == {t.pa.id}
    assert t.pb.name not in repr(ctx)
    assert all("px=" not in x["url"] for x in ctx["tabs"])
    if tab == "panorama":
        etapas = {s["code"]: s["value"] for s in ctx["panorama"]["stages"]}
        assert etapas["liberado"] == 1 and etapas["docs"] == 1       # solo los de A
    if tab == "encargados":
        filas = {r["user_id"]: r for r in ctx["encargados"]["rows"]}
        ana = filas[t.ana.id]
        assert [p["id"] for p in ana["programs"]] == [t.pa.id]
        assert ana["programs_out_of_scope"] == 1
        assert ana["no_programs"] is False
        # La producción sigue siendo global, por actor (spec §4.7).
        assert ana["prod"]["docs_approved"] == 3
