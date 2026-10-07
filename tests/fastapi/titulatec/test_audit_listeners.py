"""Escucha `after_flush` de la bitácora (spec 2026-10-07 §4.4, §8, Review Focus 2-4).

Qué fija
--------
1. **Espejo**: cada `ProcessEvent` nuevo deja una fila `source='process_event'`,
   `action='process.<tipo>'`, con el módulo por prefijo, el motivo sacado de
   `payload.reason`/`payload.note` y el payload copiado.
2. **Red ORM**: alta/cambio/baja en cualquier tabla `titulatec_*` no excluida
   deja una fila `source='data'` con el diff por columna; un cambio que solo
   toca `updated_at`, o un «cambio» al mismo valor, no deja nada. Las columnas
   con `hash`/`token`/`nip` salen como `"***"` (D9, Review Focus 3).
3. **Costo**: todo el flush en UNA sentencia extra contra `titulatec_audit_log`,
   también con 50+ filas (Review Focus 4); una lectura o un flush sin cambios
   en tablas titulatec, CERO.
4. Las tablas de D14 (`titulatec_audit_log`, `titulatec_process_events`,
   `titulatec_email_outbox`) y las de otras apps no pasan por la red.

Las filas se buscan por `entity_id`/`process_id` de lo que crea cada prueba:
la BD de dev es compartida y la bitácora ya trae historia.
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import date, timedelta

import pytest
from sqlalchemy import event


def _contar(db_session, fn, filtro="titulatec_audit_log") -> int:
    """Sentencias que emite `fn()` y mencionan `filtro` (None = todas)."""
    sentencias: list[str] = []

    def _ver(_conn, _cursor, statement, *_a):
        sentencias.append(statement)

    conn = db_session.connection()
    event.listen(conn, "before_cursor_execute", _ver)
    try:
        fn()
    finally:
        event.remove(conn, "before_cursor_execute", _ver)
    if filtro is None:
        return len(sentencias)
    return sum(1 for s in sentencias if filtro in s)


def _filas(db_session, **filtros):
    from itcj2.apps.titulatec.models import TitulatecAuditLog
    return (db_session.query(TitulatecAuditLog).filter_by(**filtros)
            .order_by(TitulatecAuditLog.id).all())


def test_la_escucha_esta_instalada_al_cargar_los_modelos():
    import itcj2.apps.titulatec.models  # noqa: F401
    from sqlalchemy.orm import Session
    from itcj2.apps.titulatec.services import audit_listeners

    assert audit_listeners.is_installed()
    assert event.contains(Session, "after_flush", audit_listeners._after_flush)
    audit_listeners.install()                     # idempotente
    audit_listeners.install()
    assert audit_listeners.is_installed()


# ---------------------------------------------------------------------------
# 1. Espejo de ProcessEvent
# ---------------------------------------------------------------------------
def test_process_event_nuevo_se_espeja(db_session, make_student, make_process, make_user):
    from itcj2.apps.titulatec.models import ProcessEvent

    proc = make_process(make_student())
    oficial = make_user()
    db_session.add(ProcessEvent(process_id=proc.id, actor_id=oficial.id,
                                event_type="phase_rejected", phase_number=1,
                                payload={"reason": "Falta la CURP", "doc": "curp"}))
    db_session.add(ProcessEvent(process_id=proc.id, actor_id=None,
                                event_type="library_payment_registered",
                                payload={"note": "recibo 77", "total": "850.00"}))
    db_session.add(ProcessEvent(process_id=proc.id, event_type="document_uploaded",
                                payload=None))
    db_session.flush()

    filas = _filas(db_session, process_id=proc.id, source="process_event")
    por_accion = {f.action: f for f in filas}
    assert set(por_accion) == {"process.phase_rejected",
                               "process.library_payment_registered",
                               "process.document_uploaded"}

    rechazo = por_accion["process.phase_rejected"]
    assert rechazo.module == "processes"
    assert rechazo.reason == "Falta la CURP"
    # Payload copiado + la fase, que el evento guarda en su propia columna.
    assert rechazo.payload == {"reason": "Falta la CURP", "doc": "curp", "phase_number": 1}
    assert (rechazo.actor_id, rechazo.actor_kind) == (oficial.id, "user")

    pago = por_accion["process.library_payment_registered"]
    assert pago.module == "cashier" and pago.reason == "recibo 77"
    assert (pago.actor_id, pago.actor_kind) == (None, "system")

    subida = por_accion["process.document_uploaded"]
    assert subida.module == "documents" and subida.reason is None and subida.payload is None

    # La tabla de eventos está espejada: la red no la duplica como `data.*`.
    assert _filas(db_session, entity_type="titulatec_process_events") == []


@contextmanager
def _peticion(user_id=None, ip="203.0.113.40", request_id="cd" * 16):
    """Liga a mano el contexto de observabilidad de una petición HTTP."""
    from itcj2.observability.context import bind, reset
    scope = {"type": "http", "path": "/titulatec/admin/algo/1",
             "headers": [(b"x-real-ip", ip.encode())], "client": ("10.0.0.1", 1),
             "state": {}}
    if user_id is not None:
        scope["state"]["current_user"] = {"sub": str(user_id), "role": ""}
    tokens = bind(scope=scope, request_id=request_id)
    try:
        yield
    finally:
        reset(tokens)


def test_evento_sin_actor_en_peticion_ajena_es_del_sistema(db_session, make_student,
                                                          make_process, make_user):
    """Un evento con `actor_id` NULL lo hizo el sistema aunque haya corrido
    dentro de la petición de alguien (p. ej. una previa aplicada al aprobar):
    NO se le acredita al usuario de la petición — igual que el backfill. La
    petición sigue a la vista por `request_id`/`ip`/`route`."""
    from itcj2.apps.titulatec.models import ProcessEvent

    proc = make_process(make_student())
    oficial = make_user()
    with _peticion(user_id=oficial.id, request_id="ab" * 16):
        db_session.add(ProcessEvent(process_id=proc.id, actor_id=None,
                                    event_type="survey_review_prior"))
        db_session.add(ProcessEvent(process_id=proc.id, actor_id=oficial.id,
                                    event_type="phase_approved", phase_number=2))
        db_session.flush()

    filas = {f.action: f for f in _filas(db_session, process_id=proc.id,
                                         source="process_event")}
    sistema = filas["process.survey_review_prior"]
    assert (sistema.actor_id, sistema.actor_kind, sistema.actor_label) == (None, "system", None)
    assert sistema.request_id == "ab" * 16
    assert sistema.ip == "203.0.113.40" and sistema.route == "/titulatec/admin/algo/1"

    con_persona = filas["process.phase_approved"]
    assert (con_persona.actor_id, con_persona.actor_kind) == (oficial.id, "user")
    assert con_persona.request_id == "ab" * 16


@pytest.mark.parametrize("canal", ["public", "cli", "celery"])
def test_evento_sin_actor_conserva_el_canal(db_session, make_student, make_process, canal):
    """Sin persona, el tipo dice POR DÓNDE entró: la petición pública, el
    comando o la tarea. Solo una petición CON usuario cae en `system`."""
    from itcj2.apps.titulatec.models import ProcessEvent
    from itcj2.apps.titulatec.services.audit_context import audit_context

    proc = make_process(make_student())

    def _escribir():
        db_session.add(ProcessEvent(process_id=proc.id, actor_id=None,
                                    event_type="enrollment_self_service"))
        db_session.flush()

    if canal == "public":
        with _peticion(user_id=None):
            _escribir()
        etiqueta = None
    else:
        with audit_context(canal, label=f"{canal}: prueba"):
            _escribir()
        etiqueta = f"{canal}: prueba"
    (fila,) = _filas(db_session, process_id=proc.id, source="process_event")
    assert (fila.actor_id, fila.actor_kind, fila.actor_label) == (None, canal, etiqueta)


def test_la_red_si_va_a_nombre_de_quien_opera(db_session, make_cohort, make_user):
    """A diferencia del espejo, un cambio de datos lo hizo quien hace la petición."""
    from itcj2.apps.titulatec.models import CohortReviewDay
    cohort = make_cohort()
    oficial = make_user()
    with _peticion(user_id=oficial.id):
        dia = CohortReviewDay(cohort_id=cohort.id, date=date(2094, 1, 5))
        db_session.add(dia)
        db_session.flush()
    (fila,) = _filas(db_session, entity_type="titulatec_cohort_review_days", entity_id=dia.id)
    assert (fila.actor_id, fila.actor_kind) == (oficial.id, "user")


def test_el_motivo_que_no_es_texto_sale_como_json_enmascarado(db_session, make_student,
                                                             make_process):
    from itcj2.apps.titulatec.models import ProcessEvent
    proc = make_process(make_student())
    db_session.add(ProcessEvent(process_id=proc.id, event_type="phase_rejected",
                                payload={"reason": {"nip": "1234", "texto": "falta"}}))
    db_session.flush()
    (fila,) = _filas(db_session, process_id=proc.id, source="process_event")
    assert "1234" not in fila.reason
    assert json.loads(fila.reason) == {"nip": "***", "texto": "falta"}


def test_el_espejo_enmascara_el_payload(db_session, make_student, make_process):
    from itcj2.apps.titulatec.models import ProcessEvent
    proc = make_process(make_student())
    db_session.add(ProcessEvent(process_id=proc.id, event_type="enrollment_access_reset",
                                payload={"nip": "4321", "by": "cc"}))
    db_session.flush()
    (fila,) = _filas(db_session, process_id=proc.id, source="process_event")
    assert fila.payload == {"nip": "***", "by": "cc"}
    assert fila.module == "access"


# ---------------------------------------------------------------------------
# 2. Red ORM: alta, cambio, baja
# ---------------------------------------------------------------------------
def test_alta_cambio_y_baja_con_diff(db_session, make_cohort):
    from itcj2.apps.titulatec.models import CohortReviewDay

    cohort = make_cohort()
    dia = CohortReviewDay(cohort_id=cohort.id, date=date(2091, 3, 2), capacity=20,
                          location="Sala A")
    db_session.add(dia)
    db_session.flush()
    (alta,) = _filas(db_session, entity_type="titulatec_cohort_review_days", entity_id=dia.id)
    assert (alta.source, alta.action, alta.module) == ("data", "data.insert", "cohorts")
    assert alta.before is None
    assert alta.after["date"] == "2091-03-02"
    assert alta.after["capacity"] == 20 and alta.after["location"] == "Sala A"
    assert alta.after["id"] == dia.id and alta.after["cohort_id"] == cohort.id
    # El reloj de la fila es redundante con `occurred_at` en un alta.
    assert "created_at" not in alta.after

    dia.capacity = 25
    dia.location = "Sala A"                       # mismo valor: no es cambio
    db_session.flush()
    cambios = _filas(db_session, entity_type="titulatec_cohort_review_days",
                     entity_id=dia.id, action="data.update")
    assert len(cambios) == 1
    assert cambios[0].before == {"capacity": 20}
    assert cambios[0].after == {"capacity": 25}

    db_session.delete(dia)
    db_session.flush()
    (baja,) = _filas(db_session, entity_type="titulatec_cohort_review_days",
                     entity_id=dia.id, action="data.delete")
    assert baja.after is None
    assert baja.before["capacity"] == 25 and baja.before["date"] == "2091-03-02"


def test_un_huerfano_de_delete_orphan_tambien_es_baja(db_session, make_student, make_process):
    """Quitar una fase de `proc.phases` la borra en el flush SIN pasar por
    `session.delete()` (no está en `session.deleted`): la red la ve igual, como
    baja y no como cambio."""
    proc = make_process(make_student(), library_clearance=None)
    fase = next(f for f in proc.phases if f.phase_number == 8)
    fase_id = fase.id
    proc.phases.remove(fase)
    assert fase not in db_session.deleted        # solo el flush sabe que es baja
    db_session.flush()
    filas = _filas(db_session, entity_type="titulatec_process_phases", entity_id=fase_id)
    assert [f.action for f in filas] == ["data.insert", "data.delete"]
    assert filas[1].before["phase_number"] == 8
    assert filas[1].process_id == proc.id


def test_el_proceso_liga_su_process_id(db_session, make_student, make_process):
    proc = make_process(make_student(), phases=False, library_clearance=None)
    (alta,) = _filas(db_session, entity_type="titulatec_processes", entity_id=proc.id)
    assert alta.process_id == proc.id and alta.module == "processes"
    proc.current_phase = 2
    db_session.flush()
    (cambio,) = _filas(db_session, entity_type="titulatec_processes", entity_id=proc.id,
                       action="data.update")
    assert cambio.before == {"current_phase": 1} and cambio.after == {"current_phase": 2}
    assert cambio.process_id == proc.id


def test_solo_updated_at_o_sin_cambio_neto_no_deja_fila(db_session, make_cohort):
    from itcj2.core.utils.timezone import db_now

    cohort = make_cohort()
    nombre = cohort.name

    def _sin_cambio_real():
        cohort.updated_at = db_now()
        cohort.name = nombre
        db_session.flush()

    assert _contar(db_session, _sin_cambio_real) == 0
    assert _filas(db_session, entity_type="titulatec_cohorts", entity_id=cohort.id,
                  action="data.update") == []


def test_columnas_sensibles_salen_enmascaradas(db_session, make_cohort):
    """Review Focus 3: `*_hash`, `*token*` y `nip*` nunca llegan en claro."""
    from itcj2.apps.titulatec.models import EnrollmentRequest

    req = EnrollmentRequest(
        cohort_id=make_cohort().id, control_number=f"99{uuid.uuid4().int % 10**6:06d}",
        first_name="ANA", last_name="FICTICIA", phone="6560000000",
        contact_email="ana@example.invalid", has_efirma=False, kind="known",
        status="pending_review", verify_token_hash="a" * 64, created_ip_hash="b" * 64,
        nip_source="center",
    )
    db_session.add(req)
    db_session.flush()
    (alta,) = _filas(db_session, entity_type="titulatec_enrollment_requests", entity_id=req.id)
    assert alta.after["verify_token_hash"] == "***"
    assert alta.after["created_ip_hash"] == "***"
    assert alta.after["nip_source"] == "***"
    assert alta.after["first_name"] == "ANA"
    assert "a" * 64 not in str(alta.after) and "b" * 64 not in str(alta.after)

    req.verify_token_hash = "c" * 64
    db_session.flush()
    (cambio,) = _filas(db_session, entity_type="titulatec_enrollment_requests",
                       entity_id=req.id, action="data.update")
    assert cambio.before == {"verify_token_hash": "***"}
    assert cambio.after == {"verify_token_hash": "***"}


# ---------------------------------------------------------------------------
# 3. Costo: una sentencia por flush, cero en lecturas
# ---------------------------------------------------------------------------
def test_lote_de_50_mas_eventos_es_una_sola_sentencia(db_session, make_cohort,
                                                      make_student, make_process):
    """Review Focus 4: un import grande no cuesta N viajes."""
    from itcj2.apps.titulatec.models import CohortReviewDay, ProcessEvent

    cohort = make_cohort()
    proc = make_process(make_student(), cohort=cohort, phases=False, library_clearance=None)
    dias = [CohortReviewDay(cohort_id=cohort.id, date=date(2092, 1, 1) + timedelta(days=i))
            for i in range(50)]
    eventos = [ProcessEvent(process_id=proc.id, event_type="process_paused")
               for _ in range(3)]

    def _flush():
        db_session.add_all(dias + eventos)
        db_session.flush()

    assert _contar(db_session, _flush) == 1
    ids = {d.id for d in dias}
    filas = [f for f in _filas(db_session, entity_type="titulatec_cohort_review_days",
                               action="data.insert") if f.entity_id in ids]
    assert len(filas) == 50
    assert len(_filas(db_session, process_id=proc.id, source="process_event")) == 3


def test_flush_mixto_record_red_y_espejo_son_dos_sentencias(db_session, make_cohort,
                                                            make_student, make_process):
    """El costo completo de un flush que lo trae todo: las filas de
    `AuditService.record` (con y sin before/after/payload, con y sin actor) van
    en UN INSERT del ORM, y la red + el espejo en UN INSERT de Core. Nunca una
    sentencia por fila."""
    from itcj2.apps.titulatec.models import CohortReviewDay, ProcessEvent
    from itcj2.apps.titulatec.services.audit_service import AuditService

    cohort = make_cohort()
    proc = make_process(make_student(), cohort=cohort, phases=False, library_clearance=None)
    marca = f"mixto {uuid.uuid4().hex}"
    sentencias: list[str] = []

    def _ver(_conn, _cursor, statement, *_a):
        if "titulatec_audit_log" in statement:
            sentencias.append(statement)

    conn = db_session.connection()
    event.listen(conn, "before_cursor_execute", _ver)
    try:
        AuditService.record(db_session, "cohort.created", reason=marca)
        AuditService.record(db_session, "cohort.window_changed", reason=marca,
                            before={"closes_at": "a"}, after={"closes_at": "b"})
        AuditService.record(db_session, "cohort.donation_changed", reason=marca,
                            payload={"filas": 2}, actor_id=7)
        db_session.add_all(
            [CohortReviewDay(cohort_id=cohort.id, date=date(2095, 2, 1) + timedelta(days=i))
             for i in range(5)]
            + [ProcessEvent(process_id=proc.id, event_type="process_paused"),
               ProcessEvent(process_id=proc.id, event_type="process_resumed")])
        proc.current_phase = 2
        db_session.flush()
    finally:
        event.remove(conn, "before_cursor_execute", _ver)

    assert len(sentencias) == 2, sentencias
    orm = [s for s in sentencias if "RETURNING" in s.upper()]
    assert len(orm) == 1, "las filas de record van en UN INSERT del ORM"
    assert len(_filas(db_session, reason=marca)) == 3
    assert len(_filas(db_session, process_id=proc.id, source="process_event")) == 2
    assert len(_filas(db_session, entity_type="titulatec_processes", entity_id=proc.id,
                      action="data.update")) == 1


def test_un_nombre_de_tabla_largo_se_recorta_a_la_columna(db_session, make_cohort):
    """`entity_type` es String(48): una tabla futura de nombre largo no puede
    tumbar cada flush que la toque."""
    from itcj2.apps.titulatec.models import CohortReviewDay
    from itcj2.apps.titulatec.services import audit_listeners
    from itcj2.apps.titulatec.services.audit_context import current_audit_context
    from sqlalchemy import inspect as sa_inspect

    dia = CohortReviewDay(cohort_id=make_cohort().id, date=date(2095, 3, 1))
    db_session.add(dia)
    db_session.flush()
    fila = audit_listeners._data_row(sa_inspect(dia), "titulatec_" + "x" * 60, "delete",
                                     current_audit_context())
    assert len(fila["entity_type"]) == 48


def test_lectura_pura_no_emite_nada_contra_la_bitacora(db_session, make_cohort):
    from itcj2.apps.titulatec.models import Cohort

    cohort = make_cohort()

    def _leer():
        db_session.expire_all()
        db_session.query(Cohort).filter_by(id=cohort.id).all()
        db_session.get(Cohort, cohort.id).name
        db_session.flush()

    assert _contar(db_session, _leer) == 0


def test_flush_solo_de_record_no_se_audita_a_si_mismo(db_session):
    """Las filas de `AuditService.record` llegan a `session.new` como
    `TitulatecAuditLog`: la escucha las ignora (tabla excluida)."""
    from itcj2.apps.titulatec.services.audit_service import AuditService
    marca = f"solo record {uuid.uuid4().hex}"

    def _flush():
        AuditService.record(db_session, "cohort.created", reason=marca)
        db_session.flush()

    # La única sentencia es el INSERT del ORM de la propia fila de `record`.
    assert _contar(db_session, _flush) == 1
    assert len(_filas(db_session, reason=marca)) == 1
    assert _filas(db_session, entity_type="titulatec_audit_log") == []


# ---------------------------------------------------------------------------
# 4. Exclusiones: D14 y otras apps
# ---------------------------------------------------------------------------
def test_la_bandeja_de_correos_no_pasa_por_la_red(db_session, make_student, make_process):
    from itcj2.apps.titulatec.models import EmailOutbox
    student = make_student()
    proc = make_process(student, phases=False, library_clearance=None)

    def _encolar():
        db_session.add(EmailOutbox(kind="phase_approved", process_id=proc.id,
                                   user_id=student.id, payload={"phase": 1}))
        db_session.flush()

    assert _contar(db_session, _encolar) == 0
    assert _filas(db_session, entity_type="titulatec_email_outbox", process_id=proc.id) == []


def test_tablas_de_otras_apps_no_se_auditan(db_session, make_department):
    def _otra_app():
        make_department(name="Depto de la bitácora")

    assert _contar(db_session, _otra_app) == 0


# ---------------------------------------------------------------------------
# Contexto que lleva la red: el de la petición HTTP en curso
# ---------------------------------------------------------------------------
def test_la_red_lleva_quien_ip_y_ruta_de_la_peticion(client, make_user, make_cohort,
                                                     client_as, db_session):
    from itcj2.apps.titulatec.models import CohortReviewDay

    cohort = make_cohort()

    def _sonda(n: int):
        from itcj2.database import SessionLocal
        db = SessionLocal()
        try:
            dia = CohortReviewDay(cohort_id=cohort.id, date=date(2093, 5, n))
            db.add(dia)
            db.flush()
            return {"id": dia.id}
        finally:
            db.close()

    client.app.add_api_route("/titulatec/__sonda_red/{n}", _sonda, methods=["POST"])
    usuario = make_user()
    resp = client_as(usuario).post("/titulatec/__sonda_red/4",
                                   headers={"X-Real-IP": "203.0.113.77"})
    assert resp.status_code == 200, resp.text
    (fila,) = _filas(db_session, entity_type="titulatec_cohort_review_days",
                     entity_id=resp.json()["id"])
    assert (fila.actor_id, fila.actor_kind) == (usuario.id, "user")
    assert fila.ip == "203.0.113.77"
    assert fila.route == "/titulatec/__sonda_red/{n}"
    assert fila.request_id == resp.headers["x-request-id"]


def test_en_cli_la_red_lleva_el_contexto_del_comando(db_session, make_cohort):
    from itcj2.apps.titulatec.models import CohortReviewDay
    from itcj2.apps.titulatec.services.audit_context import audit_context

    cohort = make_cohort()
    with audit_context("cli", label="cli: prueba (root)") as ctx:
        dia = CohortReviewDay(cohort_id=cohort.id, date=date(2093, 6, 1))
        db_session.add(dia)
        db_session.flush()
    (fila,) = _filas(db_session, entity_type="titulatec_cohort_review_days", entity_id=dia.id)
    assert fila.actor_kind == "cli" and fila.actor_label == "cli: prueba (root)"
    assert fila.request_id == ctx.request_id


def test_un_error_al_armar_una_fila_no_rompe_el_flush(db_session, make_cohort, monkeypatch,
                                                      caplog):
    """Spec §4.4.4: un bug de Python al construir UNA fila se loguea y esa fila
    se omite; la operación de negocio sigue."""
    from itcj2.apps.titulatec.models import CohortReviewDay
    from itcj2.apps.titulatec.services import audit_listeners

    def _revienta(*_a, **_k):
        raise RuntimeError("bug simulado")

    monkeypatch.setattr(audit_listeners, "_data_row", _revienta)
    cohort = make_cohort()
    dia = CohortReviewDay(cohort_id=cohort.id, date=date(2093, 7, 1))
    db_session.add(dia)
    db_session.flush()                            # no truena
    assert dia.id is not None
    assert _filas(db_session, entity_type="titulatec_cohort_review_days", entity_id=dia.id) == []
    assert "bug simulado" in caplog.text
