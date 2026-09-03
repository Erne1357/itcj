"""El acordeon de fases del dashboard del alumno y el redirect de `/fase/{n}`.

Contexto: hasta 2026-09-02 el alumno tocaba una fase y caia en
`/titulatec/student/fase/{n}`, una PANTALLA APARTE con la descripcion y un boton
que llevaba al modulo real. Ahora la descripcion se despliega en la propia lista
del dashboard y la fase ACTUAL no se despliega: sale en grande en la tarjeta "Tu
proceso" con su CTA.

Casi todo se prueba sobre `_phases_ctx` y no sobre el HTML A PROPOSITO: el
markup del acordeon lo escribe el frontend y va a cambiar; el contrato de datos
(que fase se puede desplegar, quien tiene CTA, que dice el sub-progreso) es lo
que no debe erosionarse. Del HTTP solo se asserta lo que es contrato de red:
codigo de estado y Location.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from itcj2.apps.titulatec.pages.student import _parse_open_phase, _phases_ctx

DASHBOARD = "/titulatec/student/dashboard"


def _card(ctx, number):
    return next(c for c in ctx["phases"] if c["number"] == number)


# ---------------------------------------------------------------------------
# `/fase/{n}` — compat: ya no renderiza, redirige
# ---------------------------------------------------------------------------
def test_fase_redirige_al_dashboard_con_la_fase_abierta(
    client_as, make_student, make_process, seed_phase_defs,
):
    """302 a `?fase=N`. Es la URL que llevan TODAS las notificaciones ya emitidas.

    `services/notify.py:31-33` escribio `data['url'] = /titulatec/student/fase/{n}`
    en filas de `core_notifications` que siguen en BD: si esta ruta muere, mueren
    esos avisos.
    """
    seed_phase_defs()
    student = make_student()
    make_process(student, current_phase=2)

    resp = client_as(student).get("/titulatec/student/fase/3", follow_redirects=False)

    assert resp.status_code == 302, resp.text[:300]
    assert resp.headers["location"] == f"{DASHBOARD}?fase=3"


def test_fase_no_es_redirect_permanente(
    client_as, make_student, make_process, seed_phase_defs,
):
    """301/308 lo cachearia el navegador para siempre y nunca volveria a preguntar.

    El destino puede cambiar (otro mecanismo de deep-link, o que la fase recupere
    pantalla propia); con un permanente, quien ya lo tenga cacheado no se enteraria.
    """
    seed_phase_defs()
    student = make_student()
    make_process(student)

    resp = client_as(student).get("/titulatec/student/fase/1", follow_redirects=False)

    assert resp.status_code not in (301, 308)


def test_fase_fuera_de_rango_sigue_dando_404(
    client_as, make_student, make_process, seed_phase_defs,
):
    seed_phase_defs()
    student = make_student()
    make_process(student)
    cli = client_as(student)

    assert cli.get("/titulatec/student/fase/9", follow_redirects=False).status_code == 404
    assert cli.get("/titulatec/student/fase/-1", follow_redirects=False).status_code == 404


def test_fase_sin_proceso_sigue_dando_404(client_as, make_student, seed_phase_defs):
    """El alumno sin proceso no tiene fases: 404, no un redirect a un acordeon vacio."""
    seed_phase_defs()

    resp = client_as(make_student()).get("/titulatec/student/fase/2", follow_redirects=False)

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Dashboard — la pantalla responde
# ---------------------------------------------------------------------------
def test_dashboard_200_con_proceso(
    client_as, make_student, make_process, seed_phase_defs, seed_document_types,
):
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    make_process(student, current_phase=1)

    resp = client_as(student).get(DASHBOARD)

    assert resp.status_code == 200, resp.text[:500]


def test_dashboard_200_sin_proceso(client_as, make_student, seed_phase_defs):
    """El alumno recien creado sin proceso no revienta la pantalla principal."""
    seed_phase_defs()

    resp = client_as(make_student()).get(DASHBOARD)

    assert resp.status_code == 200, resp.text[:500]


def test_dashboard_con_fase_basura_no_revienta(
    client_as, make_student, make_process, seed_phase_defs, seed_document_types,
):
    """`?fase=abc` degrada a "sin acordeon abierto", NO a un 422.

    Por eso `fase` se declara `str | None` y se parsea a mano: la URL viaja en
    notificaciones viejas y no puede tumbar el dashboard.
    """
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    make_process(student)

    assert client_as(student).get(f"{DASHBOARD}?fase=abc").status_code == 200
    assert client_as(student).get(f"{DASHBOARD}?fase=").status_code == 200
    assert client_as(student).get(f"{DASHBOARD}?fase=99").status_code == 200


def test_parse_open_phase():
    assert _parse_open_phase("3") == 3
    assert _parse_open_phase(" 3 ") == 3
    assert _parse_open_phase("abc") is None
    assert _parse_open_phase("") is None
    assert _parse_open_phase(None) is None


# ---------------------------------------------------------------------------
# Contrato del acordeon
# ---------------------------------------------------------------------------
def test_la_fase_actual_no_se_despliega_y_es_la_unica_con_cta(
    db_session, make_student, make_process, seed_phase_defs, seed_document_types,
):
    """Decisiones 2 y 3: la actual va grande en la columna A; el resto se despliega.

    Y solo la actual acciona: las anteriores estan cerradas (inmutables) y las
    siguientes son informativas — el alumno se prepara ahi, no ejecuta.
    """
    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=2)

    ctx = _phases_ctx(db_session, proc)

    actual = _card(ctx, 2)
    assert actual["is_current"] and actual["can_expand"] is False
    assert all(c["can_expand"] for c in ctx["phases"] if not c["is_current"])

    # La fase 1 (anterior) y la 3 (siguiente) TIENEN entrada en `_PHASE_CTA`...
    assert _card(ctx, 1)["cta"] is None
    assert _card(ctx, 3)["cta"] is None
    # ...y aun asi solo la actual la expone.
    assert [c["number"] for c in ctx["phases"] if c["cta"]] == [2]
    assert ctx["current"]["cta"]["url"] == "/titulatec/student/cita"


def test_la_card_grande_es_la_misma_de_la_fase_actual(
    db_session, make_student, make_process, seed_phase_defs, seed_document_types,
):
    """`current` no es una copia divergente: es la card de la lista."""
    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=3)

    ctx = _phases_ctx(db_session, proc)

    assert ctx["current"] is _card(ctx, 3)
    assert ctx["current"]["desc"]           # descripcion para la tarjeta grande
    assert ctx["current"]["needs"]          # "que vas a necesitar"


def test_clasifica_anterior_actual_y_siguiente(
    db_session, make_student, make_process, seed_phase_defs, seed_document_types,
):
    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=4)

    ctx = _phases_ctx(db_session, proc)

    assert [c["rel"] for c in ctx["phases"]] == (
        ["past"] * 4 + ["current"] + ["future"] * 4
    )


def test_deep_link_abre_solo_esa_fase(
    db_session, make_student, make_process, seed_phase_defs, seed_document_types,
):
    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=2)

    ctx = _phases_ctx(db_session, proc, open_phase=5)

    assert [c["number"] for c in ctx["phases"] if c["is_open"]] == [5]


def test_deep_link_a_la_fase_actual_no_abre_ningun_acordeon(
    db_session, make_student, make_process, seed_phase_defs, seed_document_types,
):
    """La actual no tiene acordeon que abrir: su info ya sale entera en la columna A."""
    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=2)

    ctx = _phases_ctx(db_session, proc, open_phase=2)

    assert not any(c["is_open"] for c in ctx["phases"])
    # ...pero SI se resalta: `is_target` es lo que el template usa para eso.
    assert [c["number"] for c in ctx["phases"] if c["is_target"]] == [2]
    assert ctx["open_phase"] == 2


def test_deep_link_inexistente_no_abre_nada(
    db_session, make_student, make_process, seed_phase_defs, seed_document_types,
):
    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=1)

    ctx = _phases_ctx(db_session, proc, open_phase=42)

    assert not any(c["is_open"] for c in ctx["phases"])


def test_sin_proceso_no_hay_fase_actual_ni_cta(
    db_session, seed_phase_defs, seed_document_types,
):
    seed_phase_defs()
    seed_document_types()

    ctx = _phases_ctx(db_session, None)

    assert ctx["has_process"] is False
    assert ctx["current"] is None
    assert ctx["current_phase"] == 0 and ctx["progress_pct"] == 0
    assert len(ctx["phases"]) == 9
    assert all(c["can_expand"] and c["cta"] is None for c in ctx["phases"])


# ---------------------------------------------------------------------------
# Sub-progreso (decision 4)
# ---------------------------------------------------------------------------
def test_subprogreso_fase_1_cuenta_aprobados_rechazados_y_faltantes(
    db_session, make_student, make_process, make_document,
    seed_phase_defs, seed_document_types,
):
    """3 documentos: uno aprobado, uno rechazado, uno sin subir.

    `missing` es el pseudo-estado de la UI (no hay fila), distinto de `pending`:
    "no lo has subido" y "lo subiste y falta que lo revisen" no son lo mismo.
    """
    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=1)
    make_document(proc, type_code="birth_certificate", review_status="approved")
    make_document(proc, type_code="high_school_cert", review_status="rejected",
                  note="Se ve borrosa")

    prog = _card(_phases_ctx(db_session, proc), 1)["progress"]

    assert prog["kind"] == "documents"
    assert prog["counts"] == {"approved": 1, "rejected": 1, "pending": 0, "missing": 1}
    assert prog["uploaded"] == 2 and prog["total"] == 3
    assert prog["tone"] == "danger"            # hay algo que corregir: manda eso
    assert {i["code"]: i["status"] for i in prog["items"]} == {
        "birth_certificate": "approved",
        "high_school_cert": "rejected",
        "curp": "missing",
    }


def test_subprogreso_fase_1_todo_aprobado(
    db_session, make_student, make_process, make_document,
    seed_phase_defs, seed_document_types,
):
    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=2)
    for code in ("birth_certificate", "high_school_cert", "curp"):
        make_document(proc, type_code=code, review_status="approved")

    prog = _card(_phases_ctx(db_session, proc), 1)["progress"]

    assert prog["counts"]["approved"] == 3
    assert prog["tone"] == "success"


def test_subprogreso_fase_2_habla_en_lenguaje_del_alumno(
    db_session, make_student, make_process, make_appointment,
    seed_phase_defs, seed_document_types,
):
    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=2)
    make_appointment(proc, status="confirmed", location="Edificio A")

    prog = _card(_phases_ctx(db_session, proc), 2)["progress"]

    assert prog["kind"] == "appointment"
    assert prog["label"] == "Confirmaste tu asistencia"
    assert prog["location"] == "Edificio A"
    assert prog["scheduled_label"] and prog["scheduled_label"] != "—"


def test_subprogreso_fase_2_sin_cita(
    db_session, make_student, make_process, seed_phase_defs, seed_document_types,
):
    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=2)

    prog = _card(_phases_ctx(db_session, proc), 2)["progress"]

    assert prog["started"] is False
    assert prog["label"] == "Aún no te asignan fecha y hora"


def test_subprogreso_fase_2_solicitud_de_cambio_manda_sobre_el_estado(
    db_session, make_student, make_process, make_appointment,
    seed_phase_defs, seed_document_types,
):
    """`scheduled` + solicitud de cambio = el alumno pidio otro dia."""
    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=2)
    appt = make_appointment(proc, status="scheduled")
    appt.change_request = "Trabajo ese dia"
    db_session.flush()

    prog = _card(_phases_ctx(db_session, proc), 2)["progress"]

    assert prog["change_requested"] is True
    assert prog["label"] == "Solicitaste un cambio de fecha"


def test_subprogreso_fase_3_cuenta_los_pasos_del_formato_b(
    db_session, make_student, make_process, seed_phase_defs, seed_document_types,
):
    """El paso se deriva de datos PROPIOS del alumno, no de los precargados.

    `FormatBService.get_or_create` precarga nombre, control, carrera y modalidad:
    si contaran, el paso 2 se veria completo desde el minuto cero.
    """
    from itcj2.apps.titulatec.models import FormatB

    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=3)
    db_session.add(FormatB(process_id=proc.id, status="draft",
                           first_name="ALUMNO", last_name="FICTICIO",   # precargado
                           program_id=None, titulation_type="Residencia",  # precargado
                           gender="female", age=23))                    # paso 1, propio
    db_session.flush()

    prog = _card(_phases_ctx(db_session, proc), 3)["progress"]

    assert prog["kind"] == "format_b"
    assert prog["step"] == 2 and prog["total_steps"] == 3
    assert prog["submitted"] is False
    assert [s["done"] for s in prog["steps"]] == [True, False, False]
    assert prog["label"] == "Paso 2 de 3"


def test_subprogreso_fase_3_enviado(
    db_session, make_student, make_process, seed_phase_defs, seed_document_types,
):
    from itcj2.apps.titulatec.models import FormatB

    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=3)
    db_session.add(FormatB(process_id=proc.id, status="submitted",
                           gender="male", study_plan="IIND-2010", project_name="Un proyecto"))
    db_session.flush()

    prog = _card(_phases_ctx(db_session, proc), 3)["progress"]

    assert prog["submitted"] is True
    assert prog["tone"] == "amber"
    assert "revisión" in prog["label"]


def test_fase_futura_intacta_no_muestra_subprogreso_vacio(
    db_session, make_student, make_process, seed_phase_defs, seed_document_types,
):
    """Anunciarle "Aun no lo empiezas" de la fase 3 al que va en la 1 es ruido."""
    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=1)

    ctx = _phases_ctx(db_session, proc)

    assert _card(ctx, 3)["progress"] is None
    assert _card(ctx, 1)["progress"] is not None   # la actual si, aunque este a cero


# ---------------------------------------------------------------------------
# Historial dentro del acordeon (decision 6)
# ---------------------------------------------------------------------------
def test_el_historial_se_reparte_por_fase(
    db_session, make_student, make_process, seed_phase_defs, seed_document_types,
):
    from itcj2.apps.titulatec.models import ProcessEvent

    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=2)
    base = datetime(2026, 3, 2, 10, 0)
    db_session.add_all([
        ProcessEvent(process_id=proc.id, event_type="phase_approved",
                     phase_number=1, created_at=base),
        ProcessEvent(process_id=proc.id, event_type="appointment_scheduled",
                     phase_number=2, created_at=base + timedelta(hours=1)),
        ProcessEvent(process_id=proc.id, event_type="appointment_confirmed",
                     phase_number=2, created_at=base + timedelta(hours=2)),
        # Sin fase: no se cuelga de un acordeon arbitrario.
        ProcessEvent(process_id=proc.id, event_type="phase_approved",
                     phase_number=None, created_at=base + timedelta(hours=3)),
    ])
    db_session.flush()

    ctx = _phases_ctx(db_session, proc)

    assert [e["label"] for e in _card(ctx, 1)["events"]] == ["Fase aprobada"]
    assert [e["label"] for e in _card(ctx, 2)["events"]] == [
        "Cita agendada", "Confirmaste tu asistencia",
    ]
    assert _card(ctx, 0)["events"] == []
    assert sum(len(c["events"]) for c in ctx["phases"]) == 3
    assert _card(ctx, 2)["events"][0]["when"] == "02 mar 2026 · 11:00"


# ---------------------------------------------------------------------------
# El N+1 que esta pantalla no se puede permitir
# ---------------------------------------------------------------------------
def test_el_contexto_no_hace_una_consulta_por_fase(
    db_session, make_student, make_process, make_document, make_appointment,
    seed_phase_defs, seed_document_types,
):
    """9 fases con datos completos y el numero de SELECT sigue siendo constante.

    Es la pantalla mas visitada del alumno: una consulta por fase (o tres, como
    hace `initial_docs_all_approved`) la multiplicaria por 9 en cada carga.
    """
    from sqlalchemy import event

    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=3)
    for code in ("birth_certificate", "high_school_cert", "curp"):
        make_document(proc, type_code=code, review_status="approved")
    make_appointment(proc, status="attended")

    selects = []

    def _count(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", _count)
    try:
        ctx = _phases_ctx(db_session, proc)
    finally:
        event.remove(bind, "before_cursor_execute", _count)

    assert len(ctx["phases"]) == 9
    # Presupuesto: fases + process_phases + events + documents + document_types
    # + cita + formato B = 7. El margen absorbe algun lazy load, no un N+1.
    assert len(selects) <= 10, "\n".join(selects)
