"""Rutas del Tablero conectadas a la fachada (Task 6).

`GET /titulatec/admin/tablero` y `/body` parsean `request.query_params` con
`ReportFilters.parse`, abren su `SessionLocal()` y llaman
`ReportService.build(..., today=db_now().date())`. Aquí se fija:

* cada pestaña responde 200 con la jefa (página completa y parcial);
* params basura (`cohort=abc`, `range=-3`, `px=1,,x`, `tab=foo`, `page=0`, ...)
  se ignoran: 200, nunca 422/500;
* presupuesto de consultas por pestaña: ≤ 20 sentencias SQL en `/body` y las
  MISMAS con 4 que con 16 procesos (patrón de CLAUDE.md de la app §18: filas
  sembradas en una convocatoria propia, caché de authz tibia, nunca un total
  absoluto de la base).
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from itertools import count
from types import SimpleNamespace

import pytest
from sqlalchemy import event

URL = "/titulatec/admin/tablero"
BODY = f"{URL}/body"
PERM = "titulatec.reports.page.view"
TABS = ("panorama", "ritmo", "encargados", "carreras", "atorados")
TECHO = 20
_SEQ = count(1)


@pytest.fixture()
def jefa(make_head):
    from tests.fastapi.titulatec.conftest import HEAD_PERMS
    return make_head(perm_codes=HEAD_PERMS + (PERM,))


@pytest.fixture()
def mundo(db_session, seed_phase_defs, seed_document_types, make_program, make_cohort,
          make_student, make_process, make_document, make_survey_review,
          make_review_day, make_review_window, make_department, make_position,
          link_programs, assign_position, make_user):
    """Convocatoria propia con requisitos, dos carreras, un encargado de
    Servicios Escolares y `poblar(rondas)`: cada ronda siembra 4 procesos (uno
    por dictaminar, uno listo para agendar -Panorama consulta la capacidad-,
    uno con cita futura y un liberado) y dos solicitudes por revisar."""
    from itcj2.apps.titulatec.models import (
        EnrollmentRequest,
        ProcessEvent,
        ProcessPhase,
        ReviewAppointment,
    )
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )
    from itcj2.apps.titulatec.utils.business_days import (
        add_business_days,
        last_business_days,
    )
    from itcj2.core.utils.timezone import db_now

    seed_phase_defs()
    seed_document_types()
    hoy = db_now().date()
    b0 = last_business_days(hoy, 1)[0]
    pa = make_program("Ingenieria Rutas Tablero A")
    pb = make_program("Ingenieria Rutas Tablero B")
    oculta = make_program("Ingenieria Rutas Tablero Oculta")
    c = make_cohort()
    CotejoRequirementService.seed_defaults(db_session, c.id, commit=False)
    depto = make_department(code="school_services", name="Servicios Escolares")
    enc = make_user(first_name="ENCARGADA", last_name="RUTASTABLERO")
    pos = make_position(code=f"se_officer_tr{next(_SEQ):05d}", department=depto)
    link_programs(pos, [pa, pb])
    assign_position(enc, pos)
    dia = add_business_days(hoy, 1)
    ventana = make_review_window(make_review_day(c, day=dia), enc, start="08:00",
                                 end="14:00", slot=15, cap=1)
    franjas = (datetime.combine(dia, time(8, 0)) + timedelta(minutes=15 * i)
               for i in range(24))

    def poblar(rondas):
        for _ in range(rondas):
            for program in (pa, pb):
                n = next(_SEQ)
                db_session.add(EnrollmentRequest(
                    cohort_id=c.id, control_number=f"95{n:06d}", first_name="SOLICITANTE",
                    last_name="RUTAS", program_id=program.id, phone="6560000000",
                    contact_email=f"tr.{n}@example.invalid", has_efirma=False,
                    kind="unknown", status="pending_review", verify_send_count=0))
            docs = make_process(make_student(), cohort=c, program=pa, current_phase=1)
            make_document(docs, review_status="pending")
            listo = make_process(make_student(), cohort=c, program=pb, current_phase=2)
            make_survey_review(listo, status="approved")
            alumno = make_student()
            cita = make_process(alumno, cohort=c, program=pa, current_phase=2)
            make_survey_review(cita, status="approved")
            db_session.add(ReviewAppointment(
                process_id=cita.id, window_id=ventana.id, scheduled_at=next(franjas),
                status="confirmed", created_by_id=alumno.id))
            lib = make_process(make_student(), cohort=c, program=pb, current_phase=3)
            f2 = db_session.query(ProcessPhase).filter_by(process_id=lib.id,
                                                          phase_number=2).one()
            f2.completed_at = datetime.combine(b0, time(12))
            f2.reviewed_by_id = enc.id
            db_session.add(ProcessEvent(process_id=docs.id, actor_id=enc.id,
                                        event_type="document_rejected",
                                        created_at=datetime.combine(b0, time(10))))
            db_session.flush()

    return SimpleNamespace(c=c, pa=pa, pb=pb, oculta=oculta, enc=enc, hoy=hoy, b0=b0,
                           poblar=poblar)


def _sentencias(db_session, fn) -> list[str]:
    """Sentencias SQL de `fn` sobre la conexión del test (la de la ruta: el
    `SessionLocal()` parchado devuelve esta misma sesión)."""
    vistas: list[str] = []

    def _ver(_conn, _cursor, statement, *_a):
        if "titulatec_audit_log" not in statement:
            vistas.append(" ".join(statement.split()))

    db_session.flush()
    conn = db_session.connection()
    event.listen(conn, "before_cursor_execute", _ver)
    try:
        fn()
    finally:
        event.remove(conn, "before_cursor_execute", _ver)
    return vistas


def test_las_rutas_llaman_a_la_fachada_con_los_filtros_parseados(client_as, jefa, mundo,
                                                                  monkeypatch):
    from itcj2.apps.titulatec.services import report_service as rsv
    from itcj2.core.utils.timezone import db_now

    llamadas = []
    real = rsv.ReportService.build

    def espia(db, *, user_id, filters, today):
        llamadas.append((user_id, filters, today))
        return real(db, user_id=user_id, filters=filters, today=today)

    monkeypatch.setattr(rsv.ReportService, "build", staticmethod(espia))
    c = client_as(jefa)
    params = {"tab": "atorados", "cohort": mundo.c.id, "level": "crit", "px": "3,x"}
    for url in (URL, BODY):
        assert c.get(url, params=params).status_code == 200
    assert len(llamadas) == 2
    for uid, filtros, hoy in llamadas:
        assert uid == jefa.id
        assert filtros == rsv.ReportFilters(tab="atorados", cohort=mundo.c.id, idle_level="crit",
                                            hidden_programs=frozenset({3}))
        assert hoy == db_now().date()


@pytest.mark.parametrize("tab", TABS)
def test_cada_pestana_responde_200_con_la_jefa(client_as, jefa, mundo, tab):
    mundo.poblar(1)
    c = client_as(jefa)
    for url in (URL, BODY):
        r = c.get(url, params={"tab": tab, "cohort": mundo.c.id})
        assert r.status_code == 200, r.text[:800]
        assert 'id="tt-report-body"' in r.text
        assert f'data-tt-tab="{tab}"' in r.text


def test_sin_parametros_usa_los_defaults(client_as, jefa, mundo):
    mundo.poblar(1)
    r = client_as(jefa).get(BODY)
    assert r.status_code == 200
    assert 'data-tt-tab="panorama"' in r.text


@pytest.mark.parametrize("url", [URL, BODY])
def test_params_basura_responden_200(client_as, jefa, mundo, url):
    mundo.poblar(1)
    basura = {"tab": "foo", "cohort": "abc", "range": "-3", "px": "1,,x", "ox": "a,b",
              "ball": "nadie", "level": "zzz", "stage": "<script>", "page": "0",
              "day": "2026-13-45"}
    r = client_as(jefa).get(url, params=basura)
    assert r.status_code == 200, r.text[:800]
    assert 'data-tt-tab="panorama"' in r.text
    # Valores repetidos, vacíos (HTMX los manda) y enormes tampoco truenan.
    r = client_as(jefa).get(url + "?tab=&tab=ritmo&cohort=&page=99999999999999999999&px=,")
    assert r.status_code == 200, r.text[:800]
    assert 'data-tt-tab="ritmo"' in r.text


@pytest.mark.parametrize("tab", ["atorados", "ritmo"])
def test_la_pestana_se_normaliza(client_as, jefa, mundo, tab):
    r = client_as(jefa).get(BODY, params={"tab": f"  {tab.upper()} "})
    assert r.status_code == 200
    assert f'data-tt-tab="{tab}"' in r.text


@pytest.mark.parametrize("tab", TABS)
def test_presupuesto_de_consultas_por_pestana(client_as, jefa, mundo, db_session, tab):
    """≤ 20 sentencias y las MISMAS con 4 que con 16 procesos. Se mide el peor
    camino: una carrera oculta (`px`, carga el catálogo de carreras), un
    encargado oculto (`ox`, valida contra la lista de encargados) y, en Ritmo,
    un día seleccionado (nombres de quien liberó)."""
    c = client_as(jefa)
    params = {"tab": tab, "cohort": mundo.c.id, "px": mundo.oculta.id, "ox": mundo.enc.id}
    if tab == "ritmo":
        params["day"] = mundo.b0.isoformat()

    def medir():
        assert c.get(BODY, params=params).status_code == 200      # caché de authz tibia
        r = {}
        vistas = _sentencias(db_session, lambda: r.setdefault("r", c.get(BODY, params=params)))
        assert r["r"].status_code == 200
        return vistas

    mundo.poblar(1)                       # 4 procesos
    pocas = medir()
    mundo.poblar(3)                       # 16 procesos
    muchas = medir()
    assert len(pocas) == len(muchas), (tab, pocas, muchas)
    assert len(muchas) <= TECHO, (tab, len(muchas), muchas)
