"""Tests de `CertificateService`: motor compartido de constancias (Tarea 3,
spec `2026-10-01-titulatec-biblioteca-caja-design.md` §4.5, D7/D21/D22, §5
invariante 5) y su estado de impresión (Tarea 2, spec
`2026-10-02-titulatec-constancias-y-pendientes-design.md` §3.2, invariantes
2 y 4).

Cubre: numeración atómica por tipo y semestre (`issue`, folio
`BIB-2026B-0001`, spec `2026-10-05-titulatec-folios-design.md` §3.1, con
`semester_key`/`previous_semester_key`/`SEMESTER_RE`), anulación sin borrar ni
liberar folio (`void`), lotes (`pending`/`create_batch`/`list_batches`/
`certificates_of`), estado de impresión por `source_ref`
(`print_status_map`) y por `kind` (`voided_after_print`), `period_label`, y
el gancho de GTV dentro de `SurveyReviewService.approve`/`revoke` -- desde la
perspectiva de la constancia que (no) emiten, no de la máquina de estados de
la solicitud (eso ya lo cubre `test_survey_review_service.py`, que este
archivo NO toca).

El PDF es aparte (`test_certificate_pdf.py`).
"""
from __future__ import annotations

import itertools
import threading
import time
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

import itcj2.apps.titulatec.services.certificate_service as cert_mod
from itcj2.apps.titulatec.models import Certificate
from itcj2.apps.titulatec.services.certificate_service import CERT_KINDS, CertificateService
from itcj2.core.utils.timezone import db_now

NOTIFY = "itcj2.apps.titulatec.services.notify.notify_student"

# Año SINTÉTICO para las pruebas de numeración que dejan el semestre a
# `db_now()`: la BD de dev es COMPARTIDA (CLAUDE.md) y ya trae contadores
# reales (`library_clearance`/`2026B`; el backfill de folios de previas suma
# `2026A`), así que un «-0001» con el reloj de hoy saldría «-0004». Con el
# reloj parcheado a un año sin contadores reales, el primer folio SIEMPRE es
# 0001 (el renglón del contador muere con el rollback de `db_session`).
_ANIO = 2091
_OCTUBRE = datetime(_ANIO, 10, 5, 9, 0, 0)


@pytest.fixture()
def reloj_octubre(monkeypatch):
    """`db_now()` de `certificate_service` fijo en octubre de `_ANIO`
    (semestre `B`): se parchea DONDE se importa, no en su módulo de origen."""
    monkeypatch.setattr(cert_mod, "db_now", lambda: _OCTUBRE)
    return _OCTUBRE

# Ruling R30 #1 (re-revisión de la ola final): un `source_ref` real SIEMPRE
# es `f"{namespace}:{id}"` con `id` el entero de una fila (`LibraryClearance`
# o `SurveyReview`); en cuanto la BD de dev (compartida, CLAUDE.md) tenga una
# fila VIVA `library_clearance:1` -pasará al validar esta rama fusionada:
# la 1967 es la convocatoria con candado de la activación- un literal fijo
# como `"library_clearance:1"` choca con `uq_titulatec_certificates_live_
# source` y pone roja la prueba. El sufijo de letras (`t<n>`) nunca puede
# igualar el id puramente numérico de una fila real, pase lo que pase en
# dev; el contador de MÓDULO lo hace único también entre pruebas de este
# archivo. Reusa el mismo valor (en una variable local) cuando la prueba
# necesita referirse OTRA VEZ a la misma fila (anular, re-emitir).
_ref_seq = itertools.count(1)


def _ref(namespace: str = "library_clearance") -> str:
    return f"{namespace}:t{next(_ref_seq)}"


# ---------------------------------------------------------------------------
# Escenarios
# ---------------------------------------------------------------------------
@pytest.fixture()
def escenario(db_session, make_student, make_process, make_program, make_cohort, make_period):
    """Proceso con alumno, carrera y convocatoria REALES para que `issue()`
    tenga algo completo que congelar.

    El periodo es el SINTÉTICO de `make_period()` (código de 6 caracteres,
    `conftest._period_code`) a propósito -- la BD de dev es compartida (CLAUDE.md)
    y un código "real" de 5 caracteres como `20263` puede chocar con el
    periodo/convocatoria de VERDAD del semestre en curso (hoy cae dentro de
    Agosto-Diciembre 2026). El mapeo del sufijo 1/2/3 ya se prueba aislado,
    sin convocatoria, en `TestPeriodLabel`; aquí solo importa que `issue()`
    llame a `period_label()` y congele lo que regrese, lo que sea.
    """
    periodo = make_period()
    cohort = make_cohort(period=periodo)
    programa = make_program("Ingeniería en Sistemas Computacionales")
    alumno = make_student(control_number="20261234")
    process = make_process(alumno, cohort=cohort, program=programa, current_phase=2)
    return {"process": process, "student": alumno, "cohort": cohort,
           "program": programa, "period": periodo}


@pytest.fixture()
def gtv_escenario(db_session, make_student, make_process, make_cohort, make_user):
    """Espejo de `test_survey_review_service.py::escenario`: convocatoria +
    proceso en fase 2 (cita de cotejo, para que `can_revoke` deje probar
    `revoke`) + una persona de GTV."""
    cohort = make_cohort()
    process = make_process(make_student(), cohort=cohort, current_phase=2)
    gtv = make_user(first_name="GTV", last_name="DE PRUEBA")
    return {"cohort": cohort, "process": process, "gtv": gtv}


@pytest.fixture()
def actor(make_user):
    """Usuario real para los FKs de auditoría (`issued_by_id`, `voided_by_id`,
    `created_by_id`). En CI (réplica vacía, sin DML) `actor_id=1` no existe en
    `core_users` y la escritura truena con `ForeignKeyViolation` contra
    `titulatec_certificates_issued_by_id_fkey` (o la que toque)."""
    return make_user(first_name="EMISOR", last_name="PRUEBA")


def _folio_n(numero: str) -> int:
    return int(numero.rsplit("-", 1)[1])


def _contar_selects(db_session, fn):
    """Corre `fn()` contando los SELECT que dispara contra `db_session` --
    mismo criterio que `test_student_dashboard_accordion.py:629-663`
    (listener `before_cursor_execute`), en un helper para no repetirlo en
    cada prueba de presupuesto de `print_status_map`."""
    from sqlalchemy import event

    selects = []

    def _count(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", _count)
    try:
        resultado = fn()
    finally:
        event.remove(bind, "before_cursor_execute", _count)
    return resultado, selects


# ---------------------------------------------------------------------------
# CERT_KINDS
# ---------------------------------------------------------------------------
def test_cert_kinds_trae_los_2_tipos_del_spec():
    assert set(CERT_KINDS) == {"library_clearance", "survey_release"}
    assert CERT_KINDS["library_clearance"]["prefix"] == "BIB"
    assert CERT_KINDS["survey_release"]["prefix"] == "GTV"
    for datos in CERT_KINDS.values():
        assert {"prefix", "title", "department", "phrase"} <= set(datos)


# ---------------------------------------------------------------------------
# Semestre del folio (spec 2026-10-05-titulatec-folios-design.md §3.1)
# ---------------------------------------------------------------------------
class TestSemestre:
    @pytest.mark.parametrize("cuando, esperado", [
        (date(2026, 1, 1), "2026A"),
        (date(2026, 6, 30), "2026A"),      # último día de A
        (date(2026, 7, 1), "2026B"),       # primero de B: julio ya es B
        (date(2026, 12, 31), "2026B"),
        (datetime(2026, 6, 30, 23, 59, 59), "2026A"),
        (datetime(2026, 7, 1, 0, 0, 0), "2026B"),
    ])
    def test_semester_key_acepta_date_y_datetime(self, cuando, esperado):
        assert cert_mod.semester_key(cuando) == esperado

    @pytest.mark.parametrize("cuando, esperado", [
        (date(2026, 10, 5), "2026A"),      # B de Y da A de Y
        (date(2027, 2, 10), "2026B"),      # A de Y da B de Y-1
        (date(2026, 6, 30), "2025B"),
        (date(2026, 12, 31), "2026A"),
        (date(2026, 1, 1), "2025B"),
        (datetime(2026, 7, 1, 0, 0, 0), "2026A"),
    ])
    def test_previous_semester_key(self, cuando, esperado):
        assert cert_mod.previous_semester_key(cuando) == esperado

    @pytest.mark.parametrize("valor", ["2026A", "2026B", "1901A", "2091B"])
    def test_semester_re_acepta_aaaa_mas_a_o_b(self, valor):
        assert cert_mod.SEMESTER_RE.pattern == r"^\d{4}[AB]$"
        assert cert_mod.SEMESTER_RE.fullmatch(valor)

    @pytest.mark.parametrize("valor", ["2026C", "26A", "", "2026a", "2026AB",
                                       " 2026A", "2026A\n", "20260"])
    def test_semester_re_rechaza_lo_demas(self, valor):
        assert not cert_mod.SEMESTER_RE.fullmatch(valor)


# ---------------------------------------------------------------------------
# issue — numeración (Review Focus #6)
# ---------------------------------------------------------------------------
class TestIssueNumeracion:
    def test_primer_folio_del_semestre_es_0001_y_congela_los_datos(
            self, db_session, escenario, reloj_octubre):
        proc, alumno = escenario["process"], escenario["student"]
        ref = _ref()

        cert = CertificateService.issue(
            db_session, kind="library_clearance", process=proc,
            source_ref=ref, actor_id=alumno.id)

        assert cert.id is not None
        assert cert.number == f"BIB-{_ANIO}B-0001"
        assert cert.process_id == proc.id
        assert cert.source_ref == ref
        assert cert.control_number == "20261234"
        assert cert.student_name == alumno.full_name
        assert cert.program_name == "Ingeniería en Sistemas Computacionales"
        assert cert.period_label == escenario["period"].name   # periodo sintético: cae al respaldo
        assert cert.issued_by_id == alumno.id
        assert cert.issued_at == reloj_octubre
        assert cert.voided_at is None
        assert cert.batch_id is None

    def test_sin_semestre_usa_el_de_db_now_y_es_consecutivo(
            self, db_session, escenario, reloj_octubre, actor):
        """`semester=None` = semestre de la EMISIÓN (`semester_key(db_now())`,
        decisión C1 del spec): octubre da `B`."""
        proc = escenario["process"]

        c1 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref=_ref(), actor_id=actor.id)
        c2 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref=_ref(), actor_id=actor.id)

        assert c1.number == f"BIB-{_ANIO}B-0001"
        assert c2.number == f"BIB-{_ANIO}B-0002"

    def test_semestre_explicito_tiene_su_propio_contador(
            self, db_session, escenario, reloj_octubre, actor):
        """Un `semester` explícito (previas y legado: el semestre ANTERIOR al
        registro) numera en SU contador, independiente del `B` de hoy. Año
        sintético y no `2026A`: el backfill de folios de previas llena el
        contador real de `2026A` en la BD de dev compartida."""
        proc = escenario["process"]

        bib_hoy = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                           source_ref=_ref(), actor_id=actor.id)
        gtv_a = CertificateService.issue(db_session, kind="survey_release", process=proc,
                                         source_ref=_ref("survey_review"), actor_id=actor.id,
                                         semester=f"{_ANIO}A")
        bib_a = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                         source_ref=_ref(), actor_id=actor.id,
                                         semester=f"{_ANIO}A")
        bib_hoy2 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                            source_ref=_ref(), actor_id=actor.id)

        assert bib_hoy.number == f"BIB-{_ANIO}B-0001"
        assert gtv_a.number == f"GTV-{_ANIO}A-0001"
        assert bib_a.number == f"BIB-{_ANIO}A-0001"     # no sigue al B
        assert bib_hoy2.number == f"BIB-{_ANIO}B-0002"  # el B no se enteró del A
        assert bib_a.issued_at == reloj_octubre           # se emite HOY aunque folie en A

    @pytest.mark.parametrize("semestre", ["2026C", "26A", "", "2026a", "2026A\n"])
    def test_semestre_invalido_truena_sin_tocar_el_contador(
            self, db_session, escenario, actor, semestre):
        with pytest.raises(ValueError):
            CertificateService.issue(db_session, kind="library_clearance",
                                     process=escenario["process"], source_ref=_ref(),
                                     actor_id=actor.id, semester=semestre)

        # Se valida ANTES del upsert: ningún renglón nace con ese semestre.
        cuantos = db_session.execute(
            text("SELECT COUNT(*) FROM titulatec_certificate_counters "
                 "WHERE semester = :s"), {"s": semestre}).scalar()
        assert cuantos == 0
        assert db_session.query(Certificate).filter(
            Certificate.number.like(f"%-{semestre}-%")).count() == 0

    def test_actor_none_deja_issued_by_id_nulo(self, db_session, escenario, reloj_octubre):
        """Importaciones y CLI (backfill) emiten sin usuario:
        `issued_by_id` NULLABLE desde `tt20261005c`."""
        cert = CertificateService.issue(db_session, kind="survey_release",
                                        process=escenario["process"],
                                        source_ref=_ref("survey_review"), actor_id=None,
                                        semester=f"{_ANIO}A")
        db_session.expire(cert)

        assert db_session.get(Certificate, cert.id).issued_by_id is None
        assert cert.number == f"GTV-{_ANIO}A-0001"

    def test_usa_el_periodo_real_de_la_convocatoria_del_proceso(
            self, db_session, make_student, make_process, make_cohort, make_period, actor):
        """D22 («semestre de la constancia = periodo de la convocatoria del
        proceso») con un código REAL (`AAAAS`) de verdad: fin a fin,
        `issue()` -> `period_label()` -> «Enero-Junio 2099». Año 2099 a
        propósito: no hay forma de que choque con una convocatoria real de la
        BD de dev compartida (a diferencia de un año cercano a hoy)."""
        periodo = make_period(code="20991")
        proc = make_process(make_student(), cohort=make_cohort(period=periodo))

        cert = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                        source_ref=_ref(), actor_id=actor.id)

        assert cert.period_label == "Enero-Junio 2099"

    def test_secuencia_por_tipo_y_semestre(self, db_session, escenario, actor):
        proc = escenario["process"]

        c1 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref=_ref(), actor_id=actor.id)
        c2 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref=_ref(), actor_id=actor.id)
        c3 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref=_ref(), actor_id=actor.id)

        assert [_folio_n(c.number) for c in (c1, c2, c3)] == \
            [_folio_n(c1.number), _folio_n(c1.number) + 1, _folio_n(c1.number) + 2]

    def test_tipos_distintos_no_comparten_secuencia(
            self, db_session, escenario, reloj_octubre, actor):
        proc = escenario["process"]

        bib = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                       source_ref=_ref(), actor_id=actor.id)
        gtv = CertificateService.issue(db_session, kind="survey_release", process=proc,
                                       source_ref=_ref("survey_review"), actor_id=actor.id)

        assert bib.number == f"BIB-{_ANIO}B-0001"
        assert gtv.number == f"GTV-{_ANIO}B-0001"

    def test_cambio_de_semestre_reinicia_el_contador(
            self, db_session, escenario, monkeypatch, actor):
        proc = escenario["process"]

        def _emitir_en(cuando):
            monkeypatch.setattr(cert_mod, "db_now", lambda: cuando)
            return CertificateService.issue(db_session, kind="library_clearance",
                                            process=proc, source_ref=_ref(),
                                            actor_id=actor.id).number

        # Años SINTÉTICOS (`_ANIO`, como el resto del archivo): con años reales
        # cercanos (2029/2030) un contador de verdad en la BD de dev compartida
        # movería el «-0001».
        sig = _ANIO + 1
        assert _emitir_en(datetime(_ANIO, 3, 1, 8, 0, 0)) == f"BIB-{_ANIO}A-0001"
        assert _emitir_en(datetime(_ANIO, 6, 30, 23, 0, 0)) == f"BIB-{_ANIO}A-0002"
        assert _emitir_en(datetime(_ANIO, 7, 1, 8, 0, 0)) == f"BIB-{_ANIO}B-0001"  # reinicia en julio
        assert _emitir_en(datetime(sig, 1, 15, 8, 0, 0)) == f"BIB-{sig}A-0001"     # y en enero

    def test_anular_no_libera_el_numero(self, db_session, escenario, actor):
        proc = escenario["process"]
        ref1, ref2 = _ref(), _ref()
        c1 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref=ref1, actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref1, actor_id=actor.id,
                                reason="Emitida por error.")

        c2 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref=ref2, actor_id=actor.id)

        assert _folio_n(c2.number) == _folio_n(c1.number) + 1

    def test_re_emitir_el_mismo_origen_saca_otro_folio_y_no_reabre_el_anulado(
            self, db_session, escenario, actor):
        proc = escenario["process"]
        ref = _ref()

        c1 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref=ref, actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref, actor_id=actor.id, reason="Corregido.")
        c2 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref=ref, actor_id=actor.id)

        assert c2.id != c1.id
        assert c2.number != c1.number
        recargado = db_session.get(Certificate, c1.id)
        assert recargado is not None             # nunca se borra
        assert recargado.voided_at is not None    # y sigue anulada

    def test_kind_desconocido(self, db_session, escenario):
        with pytest.raises(ValueError):
            CertificateService.issue(db_session, kind="otra_cosa", process=escenario["process"],
                                     source_ref=_ref("x"), actor_id=1)

    def test_dos_vigentes_del_mismo_origen_truenan_en_la_base(
            self, db_session, escenario, actor):
        """Ruling R29: «a lo más UNA vigente por `source_ref`» (§5 invariante
        5) ya no es solo disciplina de los llamadores -- un `issue` de más
        sobre un origen con una vigente truena en el `flush()` con el UNIQUE
        parcial, en vez de dejar dos papeles válidos del mismo trámite."""
        from sqlalchemy.exc import IntegrityError

        proc = escenario["process"]
        ref = "library_clearance:r29-servicio"
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref=ref, actor_id=actor.id)

        with pytest.raises(IntegrityError) as exc:
            with db_session.begin_nested():
                CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                         source_ref=ref, actor_id=actor.id)
        assert "uq_titulatec_certificates_live_source" in str(exc.value)

    def test_dos_conexiones_reales_simultaneas_numeran_sin_colision(self, _pg_engine):
        """Review Focus #6 («emisiones simultáneas»): DOS conexiones REALES
        a Postgres (no el `db_session` de SAVEPOINTs del resto del archivo,
        que comparte una sola conexión física y no puede modelar bloqueo
        entre transacciones) numerando el MISMO `(kind, semester)` a la vez.

        No basta con lanzar dos hilos y esperar que no truenen -- eso
        pasaría igual aunque el segundo nunca tocara el lock del primero.
        Este test CONFIRMA con `pg_stat_activity` que el hilo B de verdad
        quedó bloqueado (`wait_event_type = 'Lock'`) esperando el renglón
        que el hilo A todavía no suelta, y SOLO ENTONCES deja que A comitee
        -- así el `{1, 2}` de abajo prueba la atomicidad del
        `INSERT ... ON CONFLICT ... DO UPDATE`, no una coincidencia de
        scheduling del hilo del SO.

        Semestre `1901A` a propósito: imposible de chocar con un contador
        real de la BD de dev COMPARTIDA (CLAUDE.md). El renglón que el contador
        deja en `titulatec_certificate_counters` se borra en un ÚNICO
        `finally` que envuelve TODO el cuerpo (arrancar los hilos + los
        asserts), pase lo que pase -- un `try/finally` partido en dos (uno
        para arrancar/sondear, otro para los asserts finales) dejaba el
        DELETE sin correr si el primero tronaba (p. ej. `assert bloqueada`),
        y encima `hilo_b.join()` sobre un hilo que nunca arrancó revienta con
        `RuntimeError` y tapa el assert real (fix round 2 de la revisión).
        """
        kind = "library_clearance"
        semester = "1901A"
        Session = sessionmaker(bind=_pg_engine, future=True)

        # Limpieza previa defensiva: si una corrida anterior murió a medio
        # camino (antes de llegar a su propio `finally`), que no arrastre un
        # renglón viejo que invalidaría el {1, 2} de abajo.
        with _pg_engine.begin() as conn:
            conn.execute(text("DELETE FROM titulatec_certificate_counters "
                              "WHERE kind = :k AND semester = :s"),
                         {"k": kind, "s": semester})

        resultados: dict[str, str] = {}
        errores: list[tuple[str, Exception]] = []
        pids: dict[str, int] = {}
        a_tiene_el_renglon = threading.Event()
        seguir_con_commit_de_a = threading.Event()

        def _hilo_a():
            session = Session()
            try:
                resultados["A"] = CertificateService._next_number(session, kind, semester)
                a_tiene_el_renglon.set()
                # Sostiene la transacción (y el lock de fila) abierta A PROPÓSITO
                # hasta que el test de abajo confirme que B quedó esperando ESE
                # MISMO lock -- el timeout es solo la red de seguridad para que
                # un assert roto no cuelgue la suite.
                seguir_con_commit_de_a.wait(timeout=5)
                session.commit()
            except Exception as exc:                      # pragma: no cover - diagnóstico
                errores.append(("A", exc))
                session.rollback()
            finally:
                session.close()

        def _hilo_b():
            session = Session()
            try:
                pids["B"] = session.execute(text("SELECT pg_backend_pid()")).scalar()
                resultados["B"] = CertificateService._next_number(session, kind, semester)
                session.commit()
            except Exception as exc:                      # pragma: no cover - diagnóstico
                errores.append(("B", exc))
                session.rollback()
            finally:
                session.close()

        hilo_a = threading.Thread(target=_hilo_a)
        hilo_b = threading.Thread(target=_hilo_b)
        try:
            hilo_a.start()
            assert a_tiene_el_renglon.wait(timeout=5), "A no tomó el renglón a tiempo"

            hilo_b.start()

            # Sondea pg_stat_activity hasta ver a B esperando un lock de fila
            # -- nunca un sleep a ciegas.
            bloqueada = False
            limite = time.monotonic() + 5
            with _pg_engine.connect() as sonda:
                while time.monotonic() < limite:
                    pid_b = pids.get("B")
                    if pid_b is not None:
                        estado = sonda.execute(
                            text("SELECT wait_event_type FROM pg_stat_activity "
                                "WHERE pid = :pid"),
                            {"pid": pid_b},
                        ).scalar()
                        if estado == "Lock":
                            bloqueada = True
                            break
                    time.sleep(0.02)

            assert bloqueada, "B nunca quedó esperando el lock de fila de A"

            seguir_con_commit_de_a.set()
            hilo_a.join(timeout=5)
            hilo_b.join(timeout=5)

            assert not hilo_a.is_alive() and not hilo_b.is_alive(), "un hilo no terminó"
            assert errores == [], f"un hilo truena: {errores!r}"
            assert set(resultados) == {"A", "B"}
            numeros = {_folio_n(resultados["A"]), _folio_n(resultados["B"])}
            assert numeros == {1, 2}   # consecutivos: ni colisión ni hueco
            assert set(resultados.values()) == {"BIB-1901A-0001", "BIB-1901A-0002"}
        finally:
            # Red de seguridad ÚNICA para TODO el cuerpo de arriba: pase lo
            # que pase (cualquier assert roto, cualquier excepción), nunca se
            # cuelga un hilo vivo ni se le queda pegado a la BD compartida el
            # renglón de 1901A.
            seguir_con_commit_de_a.set()        # idempotente -- suelta a A
            vivos = []
            for nombre, hilo in (("A", hilo_a), ("B", hilo_b)):
                if hilo.ident is not None:      # solo los que sí arrancaron
                    hilo.join(timeout=5)
                    if hilo.is_alive():
                        vivos.append(nombre)
            # m08 (triage-minors.md): si un hilo SIGUE vivo después de su
            # propio join(timeout=5), su sesión probablemente sigue abierta y
            # sosteniendo el lock de fila -- borrar aquí A CIEGAS arriesga que
            # el DELETE de abajo se quede esperando ESE MISMO lock (la suite
            # se cuelga sin ninguna pista de qué pasó) o que pise una fila que
            # esa sesión todavía necesita. Se prefiere fallar RUIDOSO y dejar
            # el renglón de 1901A SIN BORRAR (semestre sintético: purgable a mano,
            # nunca puede chocar con una convocatoria real) en vez de competir
            # por su lock. Nunca pasa en una corrida sana: 5 s de margen ya es
            # generoso frente al <1 s que tarda el camino feliz completo.
            if vivos:
                pytest.fail(
                    f"hilo(s) {vivos!r} seguían vivos tras el join; no se "
                    f"borró titulatec_certificate_counters (kind={kind!r}, "
                    f"semester={semester!r}) para no competir por su lock de fila")
            with _pg_engine.begin() as conn:
                conn.execute(text("DELETE FROM titulatec_certificate_counters "
                                  "WHERE kind = :k AND semester = :s"),
                             {"k": kind, "s": semester})


# ---------------------------------------------------------------------------
# void
# ---------------------------------------------------------------------------
class TestVoid:
    def test_anula_la_vigente_sin_borrarla(self, db_session, escenario, actor, make_user):
        proc = escenario["process"]
        otro = make_user(first_name="REVISOR", last_name="PRUEBA")
        ref = _ref()
        cert = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                        source_ref=ref, actor_id=actor.id)

        anulada = CertificateService.void(db_session, source_ref=ref,
                                          actor_id=otro.id, reason="  Motivo de prueba.  ")

        assert anulada.id == cert.id
        assert anulada.voided_at is not None
        assert anulada.voided_by_id == otro.id
        assert anulada.void_reason == "Motivo de prueba."   # recortado

    def test_sin_vigente_regresa_none(self, db_session, escenario):
        resultado = CertificateService.void(db_session, source_ref=_ref("nunca_existio"),
                                            actor_id=1, reason="x")
        assert resultado is None

    def test_no_se_puede_anular_dos_veces(self, db_session, escenario, actor):
        proc = escenario["process"]
        ref = _ref()
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref=ref, actor_id=actor.id)

        primera = CertificateService.void(db_session, source_ref=ref,
                                          actor_id=actor.id, reason="uno")
        segunda = CertificateService.void(db_session, source_ref=ref,
                                          actor_id=actor.id, reason="dos")

        assert primera is not None
        assert segunda is None


# ---------------------------------------------------------------------------
# pending / create_batch / list_batches / certificates_of
# ---------------------------------------------------------------------------
# `pending`/`create_batch`/`list_batches` son GLOBALES por `kind`: la fixture
# `sin_constancias_de_dev` (conftest) quita, dentro de la transacción del test,
# los lotes y las pendientes REALES de la BD de dev compartida.
@pytest.mark.usefixtures("sin_constancias_de_dev")
class TestLotes:
    def test_pending_count_y_pending_en_orden_fifo(self, db_session, escenario, actor):
        proc = escenario["process"]
        c1 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref=_ref(), actor_id=actor.id)
        c2 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref=_ref(), actor_id=actor.id)

        assert CertificateService.pending_count(db_session, "library_clearance") == 2
        pendientes = CertificateService.pending(db_session, "library_clearance")
        assert [c.id for c in pendientes] == [c1.id, c2.id]

    def test_create_batch_sin_pendientes(self, db_session, escenario):
        with pytest.raises(ValueError):
            CertificateService.create_batch(db_session, kind="library_clearance", actor_id=1)

    def test_create_batch_toma_las_pendientes_y_las_marca(self, db_session, escenario, actor):
        proc = escenario["process"]
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref=_ref(), actor_id=actor.id)
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref=_ref(), actor_id=actor.id)

        batch = CertificateService.create_batch(db_session, kind="library_clearance",
                                                 actor_id=actor.id)

        assert batch.id is not None
        assert batch.kind == "library_clearance"
        assert batch.count == 2
        assert batch.created_by_id == actor.id
        assert CertificateService.pending_count(db_session, "library_clearance") == 0
        miembros = CertificateService.certificates_of(db_session, batch.id)
        assert len(miembros) == 2
        assert all(c.batch_id == batch.id for c in miembros)

    def test_anuladas_no_entran_al_lote(self, db_session, escenario, actor):
        proc = escenario["process"]
        ref = _ref()
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref=ref, actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref, actor_id=actor.id,
                                reason="no aplica")

        assert CertificateService.pending_count(db_session, "library_clearance") == 0
        with pytest.raises(ValueError):
            CertificateService.create_batch(db_session, kind="library_clearance", actor_id=actor.id)

    def test_el_lote_no_mezcla_tipos(self, db_session, escenario, actor):
        proc = escenario["process"]
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref=_ref(), actor_id=actor.id)
        CertificateService.issue(db_session, kind="survey_release", process=proc,
                                 source_ref=_ref("survey_review"), actor_id=actor.id)

        batch = CertificateService.create_batch(db_session, kind="library_clearance",
                                                 actor_id=actor.id)

        assert batch.count == 1
        assert CertificateService.pending_count(db_session, "survey_release") == 1

    def test_create_batch_kind_desconocido(self, db_session, escenario):
        with pytest.raises(ValueError):
            CertificateService.create_batch(db_session, kind="otra_cosa", actor_id=1)

    def test_certificates_of_incluye_las_anuladas(self, db_session, escenario, actor):
        proc = escenario["process"]
        ref = _ref()
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref=ref, actor_id=actor.id)
        batch = CertificateService.create_batch(db_session, kind="library_clearance",
                                                 actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref, actor_id=actor.id,
                                reason="se corrigió después de imprimir")

        miembros = CertificateService.certificates_of(db_session, batch.id)

        assert len(miembros) == 1
        assert miembros[0].voided_at is not None
        assert miembros[0].batch_id == batch.id   # anular no la saca del lote

    def test_list_batches_trae_autor_cuenta_y_anuladas(self, db_session, escenario, make_user):
        proc = escenario["process"]
        autor = make_user(first_name="BIBLIO", last_name="TECARIA")
        ref1, ref2 = _ref(), _ref()
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref=ref1, actor_id=autor.id)
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref=ref2, actor_id=autor.id)
        batch = CertificateService.create_batch(db_session, kind="library_clearance",
                                                actor_id=autor.id)
        CertificateService.void(db_session, source_ref=ref1, actor_id=autor.id,
                                reason="corrección")

        filas, has_more = CertificateService.list_batches(db_session, kind="library_clearance")

        assert has_more is False
        assert len(filas) == 1
        fila = filas[0]
        assert fila["id"] == batch.id
        assert fila["count"] == 2            # el conteo del lote no cambia
        assert fila["voided_count"] == 1      # pero sabe cuántas de ese lote se anularon
        assert fila["created_by"] == autor.full_name

    def test_list_batches_pagina(self, db_session, escenario, actor):
        proc = escenario["process"]
        for _ in range(3):
            CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                     source_ref=_ref(), actor_id=actor.id)
            CertificateService.create_batch(db_session, kind="library_clearance",
                                             actor_id=actor.id)

        pagina1, has_more1 = CertificateService.list_batches(
            db_session, kind="library_clearance", page=1, per_page=2)
        pagina2, has_more2 = CertificateService.list_batches(
            db_session, kind="library_clearance", page=2, per_page=2)

        assert len(pagina1) == 2
        assert has_more1 is True
        assert len(pagina2) == 1
        assert has_more2 is False
        # más reciente primero: el último lote creado es el primero de la página 1
        assert pagina1[0]["id"] > pagina1[1]["id"] > pagina2[0]["id"]

    def test_las_de_una_inscripcion_revocada_no_se_imprimen(
            self, db_session, escenario, actor, make_student, make_process):
        """Ruling R26 (M3 de la revisión final): `ProcessService.cancel` no
        anula las constancias del proceso, así que «Por imprimir», su
        contador y el lote dejan FUERA las de un proceso `cancelled` -- SE no
        debe recibir papeles de una inscripción revocada. La constancia no se
        toca (ni se anula ni entra a un lote): solo no se imprime."""
        vivo = CertificateService.issue(
            db_session, kind="library_clearance", process=escenario["process"],
            source_ref="library_clearance:m3-vivo", actor_id=actor.id)
        revocado = make_process(make_student(), cohort=escenario["cohort"],
                                current_phase=2)
        de_revocado = CertificateService.issue(
            db_session, kind="library_clearance", process=revocado,
            source_ref="library_clearance:m3-revocado", actor_id=actor.id)
        revocado.status = "cancelled"          # se revocó DESPUÉS de emitirla
        db_session.flush()

        assert CertificateService.pending_count(db_session, "library_clearance") == 1
        assert [c.id for c in CertificateService.pending(db_session, "library_clearance")] == [
            vivo.id]

        batch = CertificateService.create_batch(db_session, kind="library_clearance",
                                                actor_id=actor.id)

        assert batch.count == 1
        assert [c.id for c in CertificateService.certificates_of(db_session, batch.id)] == [
            vivo.id]
        db_session.refresh(de_revocado)
        assert de_revocado.batch_id is None and de_revocado.voided_at is None

    def test_solo_revocadas_pendientes_no_arman_lote(
            self, db_session, escenario, actor, make_student, make_process):
        revocado = make_process(make_student(), cohort=escenario["cohort"],
                                current_phase=2, status="cancelled")
        CertificateService.issue(db_session, kind="survey_release", process=revocado,
                                 source_ref="survey_review:m3-solo", actor_id=actor.id)

        assert CertificateService.pending_count(db_session, "survey_release") == 0
        with pytest.raises(ValueError):
            CertificateService.create_batch(db_session, kind="survey_release",
                                            actor_id=actor.id)

    def test_list_batches_de_otro_kind_sale_vacio(self, db_session, escenario, actor):
        proc = escenario["process"]
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref=_ref(), actor_id=actor.id)
        CertificateService.create_batch(db_session, kind="library_clearance", actor_id=actor.id)

        filas, has_more = CertificateService.list_batches(db_session, kind="survey_release")

        assert filas == []
        assert has_more is False


# ---------------------------------------------------------------------------
# print_status_map -- estado de impresión por `source_ref` (Tarea 2, spec
# 2026-10-02-titulatec-constancias-y-pendientes-design.md §3.2, invariante 2)
# ---------------------------------------------------------------------------
class TestPrintStatusMap:
    def test_vigente_sin_lote(self, db_session, escenario, actor):
        proc = escenario["process"]
        ref = _ref()
        cert = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                        source_ref=ref, actor_id=actor.id)

        mapa = CertificateService.print_status_map(db_session, [ref])

        assert mapa[ref] == {
            "number": cert.number,
            "issued_at": cert.issued_at,
            "printed": False,
            "batch_id": None,
            "batch_at": None,
            "voided_printed": None,
        }

    def test_vigente_en_lote(self, db_session, escenario, actor):
        proc = escenario["process"]
        ref = _ref()
        cert = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                        source_ref=ref, actor_id=actor.id)
        batch = CertificateService.create_batch(db_session, kind="library_clearance",
                                                 actor_id=actor.id)

        mapa = CertificateService.print_status_map(db_session, [ref])

        assert mapa[ref]["number"] == cert.number
        assert mapa[ref]["printed"] is True
        assert mapa[ref]["batch_id"] == batch.id
        assert mapa[ref]["batch_at"] == batch.created_at
        assert mapa[ref]["voided_printed"] is None

    def test_pagado_impreso_anulado_trae_voided_printed(self, db_session, escenario, actor):
        """pagado -> impreso -> revertido: sin vigente, `voided_printed`
        trae la anulada CON lote (Review Focus #1 del plan)."""
        proc = escenario["process"]
        ref = _ref()
        cert = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                        source_ref=ref, actor_id=actor.id)
        batch = CertificateService.create_batch(db_session, kind="library_clearance",
                                                 actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref, actor_id=actor.id,
                                reason="reversa de pago")

        mapa = CertificateService.print_status_map(db_session, [ref])

        assert mapa[ref]["number"] is None
        assert mapa[ref]["issued_at"] is None
        assert mapa[ref]["printed"] is False
        assert mapa[ref]["batch_id"] is None
        assert mapa[ref]["batch_at"] is None
        vp = mapa[ref]["voided_printed"]
        assert vp["number"] == cert.number
        assert vp["batch_id"] == batch.id
        assert vp["batch_at"] == batch.created_at
        assert vp["voided_at"] is not None
        assert vp["void_reason"] == "reversa de pago"
        assert set(vp) == {"number", "batch_id", "batch_at", "voided_at", "void_reason"}

    def test_anulada_sin_lote_no_cuenta_como_impresa(self, db_session, escenario, actor):
        proc = escenario["process"]
        ref = _ref()
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref=ref, actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref, actor_id=actor.id,
                                reason="nunca se imprimió")

        mapa = CertificateService.print_status_map(db_session, [ref])

        assert mapa[ref] is None

    def test_voided_printed_ignora_una_anulada_mas_nueva_pero_sin_lote(
            self, db_session, escenario, actor):
        """Dos anuladas del mismo origen, sin vigente: la vieja SÍ estuvo en
        un lote, la nueva (más reciente por `voided_at`, forzado a propósito)
        nunca se imprimió. `voided_printed` debe tomar la VIEJA -- confirma
        que el filtro es «con lote», no solo «la más reciente», aunque el
        orden temporal diga lo contrario."""
        proc = escenario["process"]
        ref = _ref()
        vieja = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                         source_ref=ref, actor_id=actor.id)
        batch_vieja = CertificateService.create_batch(db_session, kind="library_clearance",
                                                       actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref, actor_id=actor.id,
                                reason="vieja, con lote")
        vieja_voided_at = vieja.voided_at

        nueva = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                         source_ref=ref, actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref, actor_id=actor.id,
                                reason="nueva, nunca se imprimió")
        nueva.voided_at = vieja_voided_at + timedelta(hours=1)   # MÁS reciente, a propósito
        db_session.flush()

        mapa = CertificateService.print_status_map(db_session, [ref])

        vp = mapa[ref]["voided_printed"]
        assert vp is not None
        assert vp["number"] == vieja.number
        assert vp["batch_id"] == batch_vieja.id

    def test_voided_printed_con_dos_anuladas_con_lote_toma_la_mas_reciente(
            self, db_session, escenario, actor):
        """Dos anuladas del mismo origen, AMBAS con lote, sin vigente:
        `voided_printed` es la más reciente (`voided_at` forzado para que el
        orden sea inequívoco, sin depender del reloj de pared)."""
        proc = escenario["process"]
        ref = _ref()
        primera = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                           source_ref=ref, actor_id=actor.id)
        CertificateService.create_batch(db_session, kind="library_clearance", actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref, actor_id=actor.id, reason="primera")
        primera.voided_at = db_now() - timedelta(days=2)
        db_session.flush()

        segunda = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                           source_ref=ref, actor_id=actor.id)
        batch_segunda = CertificateService.create_batch(db_session, kind="library_clearance",
                                                         actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref, actor_id=actor.id, reason="segunda")
        segunda.voided_at = db_now() - timedelta(days=1)
        db_session.flush()

        mapa = CertificateService.print_status_map(db_session, [ref])

        vp = mapa[ref]["voided_printed"]
        assert vp["number"] == segunda.number
        assert vp["batch_id"] == batch_segunda.id

    def test_anulada_re_emitida_la_vigente_nueva_gana(self, db_session, escenario, actor):
        """pagado -> impreso -> revertido -> pagado otra vez: la celda debe
        mostrar la constancia NUEVA («Sin imprimir»), nunca la vieja impresa
        (Review Focus #1 del plan)."""
        proc = escenario["process"]
        ref = _ref()
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref=ref, actor_id=actor.id)
        CertificateService.create_batch(db_session, kind="library_clearance", actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref, actor_id=actor.id,
                                reason="se corrigió")
        nueva = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                         source_ref=ref, actor_id=actor.id)

        mapa = CertificateService.print_status_map(db_session, [ref])

        assert mapa[ref]["number"] == nueva.number
        assert mapa[ref]["printed"] is False
        assert mapa[ref]["batch_id"] is None
        assert mapa[ref]["voided_printed"] is None   # la vigente manda

    def test_ref_desconocido_da_none(self, db_session, escenario, actor):
        proc = escenario["process"]
        conocido = _ref()
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref=conocido, actor_id=actor.id)
        desconocido = _ref("nunca_existio")

        mapa = CertificateService.print_status_map(db_session, [conocido, desconocido])

        assert desconocido in mapa
        assert mapa[desconocido] is None
        assert mapa[conocido] is not None

    def test_lista_vacia_no_hace_consultas(self, db_session):
        mapa, selects = _contar_selects(
            db_session, lambda: CertificateService.print_status_map(db_session, []))

        assert mapa == {}
        assert selects == []

    def test_refs_duplicados_se_deduplican(self, db_session, escenario, actor):
        proc = escenario["process"]
        ref = _ref()
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref=ref, actor_id=actor.id)

        mapa = CertificateService.print_status_map(db_session, [ref, ref, ref])

        assert list(mapa.keys()) == [ref]

    @pytest.mark.parametrize("n_refs", [1, 20])
    def test_presupuesto_1_consulta_si_todas_tienen_vigente(
            self, db_session, escenario, actor, n_refs):
        proc = escenario["process"]
        refs = [_ref() for _ in range(n_refs)]
        for ref in refs:
            CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                     source_ref=ref, actor_id=actor.id)

        mapa, selects = _contar_selects(
            db_session, lambda: CertificateService.print_status_map(db_session, refs))

        assert all(mapa[r] is not None for r in refs)
        assert len(selects) == 1, "\n".join(selects)

    @pytest.mark.parametrize("n_refs", [1, 20])
    def test_presupuesto_2_consultas_si_ninguna_tiene_vigente(
            self, db_session, escenario, actor, n_refs):
        proc = escenario["process"]
        refs = [_ref() for _ in range(n_refs)]
        for ref in refs:
            CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                     source_ref=ref, actor_id=actor.id)
            CertificateService.void(db_session, source_ref=ref, actor_id=actor.id,
                                    reason="sin lote")

        mapa, selects = _contar_selects(
            db_session, lambda: CertificateService.print_status_map(db_session, refs))

        assert all(mapa[r] is None for r in refs)   # ninguna entró a un lote
        assert len(selects) == 2, "\n".join(selects)


# ---------------------------------------------------------------------------
# voided_after_print -- anuladas que SÍ se imprimieron (Tarea 2, E6)
# ---------------------------------------------------------------------------
# `voided_after_print` es GLOBAL por `kind` (y `create_batch` mete al lote toda
# pendiente): misma fixture que `TestLotes`.
@pytest.mark.usefixtures("sin_constancias_de_dev")
class TestVoidedAfterPrint:
    def test_trae_las_con_lote_mas_recientes_primero(self, db_session, escenario, actor):
        proc = escenario["process"]
        ref1, ref2 = _ref(), _ref()
        c1 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref=ref1, actor_id=actor.id)
        CertificateService.create_batch(db_session, kind="library_clearance", actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref1, actor_id=actor.id, reason="motivo 1")

        c2 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref=ref2, actor_id=actor.id)
        batch2 = CertificateService.create_batch(db_session, kind="library_clearance",
                                                  actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref2, actor_id=actor.id, reason="motivo 2")

        filas = CertificateService.voided_after_print(db_session, "library_clearance")

        assert [f["number"] for f in filas] == [c2.number, c1.number]   # más reciente primero
        assert filas[0]["batch_id"] == batch2.id
        assert filas[0]["batch_at"] == batch2.created_at
        assert filas[0]["student_name"] == c2.student_name
        assert filas[0]["control_number"] == c2.control_number
        assert filas[0]["void_reason"] == "motivo 2"
        assert filas[0]["voided_at"] is not None
        assert set(filas[0]) == {"number", "student_name", "control_number", "batch_id",
                                  "batch_at", "voided_at", "void_reason"}

    def test_excluye_anuladas_sin_lote(self, db_session, escenario, actor):
        proc = escenario["process"]
        ref = _ref()
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref=ref, actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref, actor_id=actor.id,
                                reason="nunca se imprimió")

        filas = CertificateService.voided_after_print(db_session, "library_clearance")

        assert filas == []

    def test_excluye_anuladas_de_hace_31_dias(self, db_session, escenario, actor):
        proc = escenario["process"]
        ref = _ref()
        cert = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                        source_ref=ref, actor_id=actor.id)
        CertificateService.create_batch(db_session, kind="library_clearance", actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref, actor_id=actor.id, reason="vieja")
        cert.voided_at = db_now() - timedelta(days=31)
        db_session.flush()

        filas = CertificateService.voided_after_print(db_session, "library_clearance")

        assert filas == []

    def test_incluye_dentro_de_los_30_dias(self, db_session, escenario, actor):
        proc = escenario["process"]
        ref = _ref()
        cert = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                        source_ref=ref, actor_id=actor.id)
        CertificateService.create_batch(db_session, kind="library_clearance", actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref, actor_id=actor.id, reason="reciente")
        cert.voided_at = db_now() - timedelta(days=10)
        db_session.flush()

        filas = CertificateService.voided_after_print(db_session, "library_clearance")

        assert [f["number"] for f in filas] == [cert.number]

    def test_el_limite_de_days_es_cerrado_exacto_incluye_un_segundo_antes_excluye(
            self, db_session, escenario, actor, monkeypatch):
        """`voided_at >= db_now() - timedelta(days=days)`: el límite es
        CERRADO (`>=`, no `>`). Reloj CONGELADO (no el de pared) para que la
        comparación sea exacta -- dos llamadas reales a `db_now()` (una al
        armar el dato, otra dentro del servicio al consultar) podrían diferir
        por microsegundos y volver el límite «exacto» indistinguible de «un
        poco antes», tapando justo el caso que esta prueba quiere fijar."""
        import itcj2.apps.titulatec.services.certificate_service as cert_mod

        ahora = datetime(2030, 6, 15, 12, 0, 0)
        monkeypatch.setattr(cert_mod, "db_now", lambda: ahora)

        proc = escenario["process"]
        ref_limite, ref_fuera = _ref(), _ref()

        en_el_limite = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                                source_ref=ref_limite, actor_id=actor.id)
        CertificateService.create_batch(db_session, kind="library_clearance", actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref_limite, actor_id=actor.id,
                                reason="justo en el límite")
        en_el_limite.voided_at = ahora - timedelta(days=30)   # == corte, exacto

        fuera_del_limite = CertificateService.issue(db_session, kind="library_clearance",
                                                     process=proc, source_ref=ref_fuera,
                                                     actor_id=actor.id)
        CertificateService.create_batch(db_session, kind="library_clearance", actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref_fuera, actor_id=actor.id,
                                reason="un segundo antes del límite")
        fuera_del_limite.voided_at = ahora - timedelta(days=30, seconds=1)   # 1s antes del corte
        db_session.flush()

        filas = CertificateService.voided_after_print(db_session, "library_clearance")

        numeros = [f["number"] for f in filas]
        assert en_el_limite.number in numeros
        assert fuera_del_limite.number not in numeros

    def test_respeta_el_parametro_days(self, db_session, escenario, actor):
        proc = escenario["process"]
        ref = _ref()
        cert = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                        source_ref=ref, actor_id=actor.id)
        CertificateService.create_batch(db_session, kind="library_clearance", actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref, actor_id=actor.id,
                                reason="hace 10 días")
        cert.voided_at = db_now() - timedelta(days=10)
        db_session.flush()

        con_30 = CertificateService.voided_after_print(db_session, "library_clearance")
        con_7 = CertificateService.voided_after_print(db_session, "library_clearance", days=7)

        assert [f["number"] for f in con_30] == [cert.number]
        assert con_7 == []

    def test_no_mezcla_kind(self, db_session, escenario, actor):
        proc = escenario["process"]
        ref_bib, ref_gtv = _ref(), _ref("survey_review")
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref=ref_bib, actor_id=actor.id)
        CertificateService.create_batch(db_session, kind="library_clearance", actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref_bib, actor_id=actor.id, reason="bib")

        CertificateService.issue(db_session, kind="survey_release", process=proc,
                                 source_ref=ref_gtv, actor_id=actor.id)
        CertificateService.create_batch(db_session, kind="survey_release", actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref_gtv, actor_id=actor.id, reason="gtv")

        filas_bib = CertificateService.voided_after_print(db_session, "library_clearance")

        assert len(filas_bib) == 1
        assert filas_bib[0]["number"].startswith("BIB-")

    def test_incluye_aunque_el_proceso_se_haya_revocado_despues(
            self, db_session, escenario, actor):
        """E6: el papel sigue circulando aunque la inscripción se revoque
        DESPUÉS de anular la constancia ya impresa -- a diferencia de
        `pending` (Ruling R26), esta lista NO filtra por
        `TitulationProcess.status`."""
        proc = escenario["process"]
        ref = _ref()
        cert = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                        source_ref=ref, actor_id=actor.id)
        CertificateService.create_batch(db_session, kind="library_clearance", actor_id=actor.id)
        CertificateService.void(db_session, source_ref=ref, actor_id=actor.id, reason="motivo")
        proc.status = "cancelled"
        db_session.flush()

        filas = CertificateService.voided_after_print(db_session, "library_clearance")

        assert [f["number"] for f in filas] == [cert.number]


# ---------------------------------------------------------------------------
# period_label
# ---------------------------------------------------------------------------
class TestPeriodLabel:
    @pytest.mark.parametrize("code,esperado", [
        ("20261", "Enero-Junio 2026"),
        ("20262", "Verano 2026"),
        ("20263", "Agosto-Diciembre 2026"),
    ])
    def test_sufijo_real_1_2_3(self, db_session, make_period, code, esperado):
        periodo = make_period(code=code)
        assert CertificateService.period_label(periodo) == esperado

    def test_sufijo_fuera_de_rango_usa_name(self, db_session, make_period):
        periodo = make_period(code="20264")   # "4" no es un sufijo válido
        assert CertificateService.period_label(periodo) == periodo.name

    def test_codigo_sintetico_de_prueba_usa_name(self, db_session, make_period):
        periodo = make_period()   # código de 6 caracteres (conftest._period_code)
        assert len(periodo.code) == 6
        assert CertificateService.period_label(periodo) == periodo.name

    def test_none_da_cadena_vacia(self):
        assert CertificateService.period_label(None) == ""

    def test_issue_trunca_el_respaldo_a_40_caracteres(
            self, db_session, make_student, make_process, make_cohort, make_period, actor):
        periodo = make_period()   # código sintético -> respaldo `name`, nunca choca
        periodo.name = "Periodo con un nombre deliberadamente larguísimo " * 2
        db_session.flush()
        assert len(periodo.name) > 40
        proc = make_process(make_student(), cohort=make_cohort(period=periodo))

        cert = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                        source_ref=_ref(), actor_id=actor.id)

        assert len(cert.period_label) == 40
        assert cert.period_label == periodo.name[:40]

    def test_issue_trunca_control_number_y_student_name_a_su_columna(
            self, db_session, make_user, make_process, make_cohort, actor):
        alumno = make_user(first_name="X" * 150, last_name="Y" * 150,
                           control_number="9" * 30)   # más largo que String(20)
        proc = make_process(alumno, cohort=make_cohort())

        cert = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                        source_ref=_ref(), actor_id=actor.id)

        assert len(cert.control_number) == 20
        assert cert.control_number == ("9" * 30)[:20]
        assert len(cert.student_name) <= 200

    def test_issue_trunca_program_name_a_su_columna(
            self, db_session, make_user, make_process, make_cohort, make_program, actor):
        """m06 (triage-minors.md): `Certificate.program_name` es
        `String(200)` (`models/certificate.py`:68), pero `core_programs.name`
        es `Text` sin tope -- una carrera con un nombre larguísimo SÍ puede
        llegar hasta aquí sin que la base la rechace antes."""
        carrera = make_program("Z" * 250)   # más largo que String(200)
        proc = make_process(make_user(), cohort=make_cohort(), program=carrera)

        cert = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                        source_ref=_ref(), actor_id=actor.id)

        assert len(cert.program_name) == 200
        assert cert.program_name == ("Z" * 250)[:200]


# ---------------------------------------------------------------------------
# Gancho de GTV: SurveyReviewService.approve / revoke (spec §4.5)
# ---------------------------------------------------------------------------
class TestGanchoGtv:
    def test_approve_emite_la_constancia_survey_release(
            self, db_session, gtv_escenario, make_survey_review):
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        process, gtv = gtv_escenario["process"], gtv_escenario["gtv"]
        review = make_survey_review(process, status="in_review")

        with patch(NOTIFY):
            SurveyReviewService.approve(db_session, review.id, gtv.id)

        cert = (db_session.query(Certificate)
               .filter_by(source_ref=f"survey_review:{review.id}").first())
        assert cert is not None
        assert cert.kind == "survey_release"
        assert cert.voided_at is None
        assert cert.number.startswith("GTV-")
        assert cert.issued_by_id == gtv.id

    def test_revoke_anula_la_constancia_emitida(
            self, db_session, gtv_escenario, make_survey_review):
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        process, gtv = gtv_escenario["process"], gtv_escenario["gtv"]
        review = make_survey_review(process, status="in_review")

        with patch(NOTIFY):
            SurveyReviewService.approve(db_session, review.id, gtv.id)
            SurveyReviewService.revoke(db_session, review.id, gtv.id, "Ya no aplica.")

        cert = (db_session.query(Certificate)
               .filter_by(source_ref=f"survey_review:{review.id}").first())
        assert cert is not None
        assert cert.voided_at is not None
        assert cert.void_reason == "Ya no aplica."

    def test_re_aprobar_tras_revocar_emite_otra_constancia(
            self, db_session, gtv_escenario, make_survey_review):
        """Revocar -> Observar -> Liberar de nuevo (§4.2): dos folios
        DISTINTOS para la misma solicitud, nunca se reabre el anulado."""
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        process, gtv = gtv_escenario["process"], gtv_escenario["gtv"]
        review = make_survey_review(process, status="in_review")

        with patch(NOTIFY):
            SurveyReviewService.approve(db_session, review.id, gtv.id)
            SurveyReviewService.revoke(db_session, review.id, gtv.id, "motivo")
            SurveyReviewService.approve(db_session, review.id, gtv.id)

        vigentes = (db_session.query(Certificate)
                   .filter_by(source_ref=f"survey_review:{review.id}", voided_at=None)
                   .all())
        todas = (db_session.query(Certificate)
                .filter_by(source_ref=f"survey_review:{review.id}")
                .all())
        assert len(vigentes) == 1
        assert len(todas) == 2
        assert todas[0].number != todas[1].number

    def test_origin_prior_no_emite_constancia_al_aprobar(
            self, db_session, gtv_escenario, make_survey_review):
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        process, gtv = gtv_escenario["process"], gtv_escenario["gtv"]
        review = make_survey_review(process, status="in_review")
        review.origin = "prior"
        db_session.flush()

        with patch(NOTIFY):
            resultado = SurveyReviewService.approve(db_session, review.id, gtv.id)

        assert resultado.status == "approved"   # la máquina de estados SÍ corre
        cert = (db_session.query(Certificate)
               .filter_by(source_ref=f"survey_review:{review.id}").first())
        assert cert is None                      # pero no hay constancia que emitir

    def test_revocar_una_previa_sin_constancia_no_truena(
            self, db_session, gtv_escenario, make_survey_review):
        """Una previa nunca emitió constancia: revocarla no tiene nada que
        anular (`void` -> `None`) y, desde la Ruling R22, BORRA la solicitud
        (vuelve a `missing`), así que `revoke` devuelve `None`."""
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        process, gtv = gtv_escenario["process"], gtv_escenario["gtv"]
        review = make_survey_review(process, status="in_review")
        review.origin = "prior"
        db_session.flush()
        review_id = review.id

        with patch(NOTIFY):
            SurveyReviewService.approve(db_session, review_id, gtv.id)
            resultado = SurveyReviewService.revoke(db_session, review_id, gtv.id, "motivo")

        assert resultado is None
        assert SurveyReviewService.get_for_process(db_session, process.id) is None
        assert (db_session.query(Certificate)
               .filter_by(source_ref=f"survey_review:{review_id}").first()) is None


# ---------------------------------------------------------------------------
# `list_folios`: la tabla de la pestaña «Folios» (spec folios 2026-10-05 §3.6)
#
# La BD de dev es COMPARTIDA y ya trae constancias reales: cada prueba siembra
# SUS filas con un semestre SINTÉTICO (`_SEM`, sin contadores reales) y/o un
# nombre con un marcador `ZZ…` que ningún egresado real lleva, y busca solo por
# eso. Nunca afirma sobre totales globales.
# ---------------------------------------------------------------------------
_SEM = "2091A"


@pytest.fixture()
def emitir(db_session, make_student, make_process, make_cohort, make_program, actor):
    """Fábrica de constancias para `list_folios`: UN alumno + proceso por
    llamada (los datos congelados salen del alumno), con `source_ref`
    únicos. `issued_at` y la anulación se fijan DESPUÉS de emitir, porque
    `NOW()` es constante dentro de la transacción de la prueba."""
    cohort = make_cohort()

    def _emitir(kind="library_clearance", *, control=None, first="ALUMNO",
                last="ZZFOLIO", carrera=None, issued_at=None, anular=None,
                semester=_SEM):
        alumno = make_student(control_number=control, first_name=first, last_name=last)
        programa = make_program(carrera) if carrera else None
        proc = make_process(alumno, cohort=cohort, program=programa)
        cert = CertificateService.issue(db_session, kind=kind, process=proc,
                                        source_ref=_ref(kind), actor_id=actor.id,
                                        semester=semester)
        if issued_at is not None:
            cert.issued_at = issued_at
        if anular is not None:
            CertificateService.void(db_session, source_ref=cert.source_ref,
                                    actor_id=actor.id, reason=anular)
        db_session.flush()
        return cert

    return _emitir


def _numeros(pagina):
    return [item["number"] for item in pagina.items]


class TestListFolios:
    def test_los_items_son_dicts_con_las_claves_del_contrato(
            self, db_session, emitir):
        cert = emitir(control="Z9910001", first="ANA", last="ZZCLAVES",
                      carrera="Ingeniería ZZ de prueba", anular="se corrigió")

        pagina = CertificateService.list_folios(
            db_session, kind="library_clearance", q="ZZCLAVES", estado="todos")

        (item,) = pagina.items
        assert set(item) == {"number", "student_name", "control_number",
                             "program_name", "issued_at", "voided_at", "void_reason"}
        assert item["number"] == cert.number
        assert item["student_name"] == "ZZCLAVES ANA"
        assert item["control_number"] == "Z9910001"
        assert item["program_name"] == "Ingeniería ZZ de prueba"
        assert item["issued_at"] == cert.issued_at
        assert item["voided_at"] is not None
        assert item["void_reason"] == "se corrigió"

    def test_busca_por_folio_parcial(self, db_session, emitir):
        a = emitir()
        b = emitir()
        assert a.number == f"BIB-{_SEM}-0001" and b.number == f"BIB-{_SEM}-0002"

        parcial = CertificateService.list_folios(
            db_session, kind="library_clearance", q=f"{_SEM}-0002")
        minuscula = CertificateService.list_folios(
            db_session, kind="library_clearance", q=f"bib-{_SEM.lower()}-0001")

        assert _numeros(parcial) == [b.number]
        assert _numeros(minuscula) == [a.number]

    def test_busca_por_control_tambien_en_minuscula(self, db_session, emitir):
        cert = emitir(control="Z9910002")
        otra = emitir(control="Z9910003")

        exacto = CertificateService.list_folios(
            db_session, kind="library_clearance", q="Z9910002")
        minuscula = CertificateService.list_folios(
            db_session, kind="library_clearance", q="z9910002")
        parcial = CertificateService.list_folios(
            db_session, kind="library_clearance", q="Z99100")

        assert _numeros(exacto) == [cert.number]
        assert _numeros(minuscula) == [cert.number]
        assert set(_numeros(parcial)) == {cert.number, otra.number}

    def test_busca_por_nombre(self, db_session, emitir):
        cert = emitir(first="MARIANA", last="ZZPÉREZ")
        emitir(first="OTRO", last="ZZGÓMEZ")

        por_apellido = CertificateService.list_folios(
            db_session, kind="library_clearance", q="zzpérez")
        por_nombre = CertificateService.list_folios(
            db_session, kind="library_clearance", q="ZZPÉREZ MARIANA")

        assert _numeros(por_apellido) == [cert.number]
        assert _numeros(por_nombre) == [cert.number]

    def test_el_nombre_se_busca_por_palabras_en_cualquier_orden(self, db_session, emitir):
        """Revisión final M3: el nombre se congela apellidos primero («PÉREZ
        GÓMEZ JUAN»), pero se busca como se dice («Juan Pérez»): cada palabra
        de `q` tiene que estar en el nombre, en cualquier orden y sin importar
        mayúsculas ni acentos en mayúscula."""
        cert = emitir(first="JUAN", last="ZZPÉREZ ZZGÓMEZ")
        emitir(first="PEDRO", last="ZZPÉREZ ZZLUNA")

        como_se_dice = CertificateService.list_folios(
            db_session, kind="library_clearance", q="Juan ZZPérez")
        salteado = CertificateService.list_folios(
            db_session, kind="library_clearance", q="zzgómez   juan")
        apellidos = CertificateService.list_folios(
            db_session, kind="library_clearance", q="ZZPÉREZ")

        assert _numeros(como_se_dice) == [cert.number]
        assert _numeros(salteado) == [cert.number]
        assert len(_numeros(apellidos)) == 2

    def test_las_palabras_del_nombre_van_todas_en_la_misma_fila(self, db_session, emitir):
        """AND, no OR: una palabra en una fila y la otra en otra no casan."""
        emitir(first="JUAN", last="ZZTOKA")
        emitir(first="PEDRO", last="ZZTOKB")

        pagina = CertificateService.list_folios(
            db_session, kind="library_clearance", q="ZZTOKA PEDRO")

        assert pagina.items == []

    def test_un_porcentaje_literal_no_explota_ni_comodina(self, db_session, emitir):
        con_porcentaje = emitir(first="100%", last="ZZPCT")
        emitir(first="1000", last="ZZPCT")       # casaría si `%` fuera comodín

        pagina = CertificateService.list_folios(
            db_session, kind="library_clearance", q="ZZPCT 100%")

        assert _numeros(pagina) == [con_porcentaje.number]

    def test_un_guion_bajo_y_una_diagonal_son_literales(self, db_session, emitir):
        con_guion = emitir(first="A_B", last="ZZUND")
        emitir(first="AXB", last="ZZUND")        # casaría si `_` fuera comodín
        con_diagonal = emitir(first="C\\D", last="ZZUND")

        guion = CertificateService.list_folios(
            db_session, kind="library_clearance", q="ZZUND A_B")
        diagonal = CertificateService.list_folios(
            db_session, kind="library_clearance", q="ZZUND C\\D")

        assert _numeros(guion) == [con_guion.number]
        assert _numeros(diagonal) == [con_diagonal.number]

    def test_busqueda_vacia_o_de_espacios_equivale_a_sin_filtro(self, db_session, emitir):
        cert = emitir()
        sin_filtro = CertificateService.list_folios(
            db_session, kind="library_clearance", per_page=500)

        for q in (None, "", "   ", "\t\n"):
            pagina = CertificateService.list_folios(
                db_session, kind="library_clearance", q=q, per_page=500)
            assert pagina.total == sin_filtro.total, repr(q)
        assert cert.number in _numeros(sin_filtro)

    def test_la_busqueda_quita_los_espacios_de_los_bordes(self, db_session, emitir):
        cert = emitir(last="ZZRECORTE")

        pagina = CertificateService.list_folios(
            db_session, kind="library_clearance", q="   zzrecorte   ")

        assert _numeros(pagina) == [cert.number]

    def test_aplica_los_tres_estados(self, db_session, emitir):
        vigente = emitir(last="ZZESTADO")
        anulado = emitir(last="ZZESTADO", anular="duplicado")

        def pedir(estado):
            return CertificateService.list_folios(
                db_session, kind="library_clearance", q="ZZESTADO", estado=estado)

        assert set(_numeros(pedir("vigentes"))) == {vigente.number}
        assert set(_numeros(pedir("anulados"))) == {anulado.number}
        assert set(_numeros(pedir("todos"))) == {vigente.number, anulado.number}
        # Por omisión y ante cualquier valor desconocido: vigentes.
        omision = CertificateService.list_folios(
            db_session, kind="library_clearance", q="ZZESTADO")
        assert set(_numeros(omision)) == {vigente.number}
        for raro in ("", "ANULADOS", "borrados", None, "vigentes; DROP TABLE x"):
            assert set(_numeros(pedir(raro))) == {vigente.number}, repr(raro)

    def test_un_anulado_trae_fecha_y_motivo(self, db_session, emitir):
        emitir(last="ZZMOTIVO", anular="  se capturó mal  ")

        (item,) = CertificateService.list_folios(
            db_session, kind="library_clearance", q="ZZMOTIVO",
            estado="anulados").items

        assert item["voided_at"] is not None
        assert item["void_reason"] == "se capturó mal"

    def test_no_mezcla_tipos(self, db_session, emitir):
        bib = emitir("library_clearance", last="ZZTIPO")
        gtv = emitir("survey_release", last="ZZTIPO")

        de_bib = CertificateService.list_folios(
            db_session, kind="library_clearance", q="ZZTIPO")
        de_gtv = CertificateService.list_folios(
            db_session, kind="survey_release", q="ZZTIPO")

        assert _numeros(de_bib) == [bib.number]
        assert _numeros(de_gtv) == [gtv.number]
        assert gtv.number.startswith("GTV-")

    def test_ordena_por_emision_descendente_y_desempata_por_id(self, db_session, emitir):
        viejo = emitir(last="ZZORDEN", issued_at=datetime(2091, 1, 10, 9, 0))
        medio_a = emitir(last="ZZORDEN", issued_at=datetime(2091, 3, 1, 9, 0))
        medio_b = emitir(last="ZZORDEN", issued_at=datetime(2091, 3, 1, 9, 0))   # mismo instante
        nuevo = emitir(last="ZZORDEN", issued_at=datetime(2091, 5, 20, 9, 0))

        pagina = CertificateService.list_folios(
            db_session, kind="library_clearance", q="ZZORDEN")

        # issued_at DESC, y en el empate el id mayor primero.
        assert _numeros(pagina) == [nuevo.number, medio_b.number, medio_a.number, viejo.number]

    def test_pagina_con_per_page_3(self, db_session, emitir):
        certs = [emitir(last="ZZPAGINA", issued_at=datetime(2091, 1, n, 9, 0))
                 for n in range(1, 8)]
        esperados = [c.number for c in reversed(certs)]       # el más nuevo primero

        p1 = CertificateService.list_folios(
            db_session, kind="library_clearance", q="ZZPAGINA", per_page=3, page=1)
        p2 = CertificateService.list_folios(
            db_session, kind="library_clearance", q="ZZPAGINA", per_page=3, page=2)
        p3 = CertificateService.list_folios(
            db_session, kind="library_clearance", q="ZZPAGINA", per_page=3, page=3)

        assert (p1.total, p1.pages, p1.page) == (7, 3, 1)
        assert _numeros(p1) == esperados[0:3]
        assert _numeros(p2) == esperados[3:6]
        assert _numeros(p3) == esperados[6:7]
        assert (p3.start, p3.end) == (7, 7)

    def test_una_pagina_fuera_de_rango_cae_en_la_ultima_valida(self, db_session, emitir):
        for n in range(1, 5):
            emitir(last="ZZRANGO", issued_at=datetime(2091, 1, n, 9, 0))

        pagina = CertificateService.list_folios(
            db_session, kind="library_clearance", q="ZZRANGO", per_page=3, page=99)

        assert pagina.page == 2
        assert len(pagina.items) == 1

    def test_sin_coincidencias_devuelve_una_pagina_vacia(self, db_session):
        pagina = CertificateService.list_folios(
            db_session, kind="survey_release", q="ZZNOEXISTEESTENOMBRE")

        assert (pagina.items, pagina.total, pagina.page) == ([], 0, 1)

    def test_un_kind_fuera_de_cert_kinds_truena(self, db_session):
        with pytest.raises(ValueError, match="Tipo de constancia desconocido"):
            CertificateService.list_folios(db_session, kind="no_existe")

    def test_no_lee_el_proceso_ni_las_tablas_de_liberacion(self, db_session, emitir):
        """Invariante 4 del spec: solo `titulatec_certificates`. Se mira el
        SQL que dispara (una consulta de cuenta y una de filas)."""
        emitir(last="ZZSOLOCERT")

        _, selects = _contar_selects(
            db_session,
            lambda: CertificateService.list_folios(
                db_session, kind="library_clearance", q="ZZSOLOCERT"))

        assert len(selects) == 2
        for sql in selects:
            assert "titulatec_certificates" in sql
            for ajena in ("titulatec_processes", "titulatec_survey_reviews",
                          "titulatec_library_clearances"):
                assert ajena not in sql
