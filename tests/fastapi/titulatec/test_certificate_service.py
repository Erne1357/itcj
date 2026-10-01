"""Tests de `CertificateService`: motor compartido de constancias (Tarea 3,
spec `2026-10-01-titulatec-biblioteca-caja-design.md` §4.5, D7/D21/D22, §5
invariante 5).

Cubre: numeración atómica por tipo y año (`issue`), anulación sin borrar ni
liberar folio (`void`), lotes (`pending`/`create_batch`/`list_batches`/
`certificates_of`), `period_label`, y el gancho de GTV dentro de
`SurveyReviewService.approve`/`revoke` -- desde la perspectiva de la
constancia que (no) emiten, no de la máquina de estados de la solicitud (eso
ya lo cubre `test_survey_review_service.py`, que este archivo NO toca).

El PDF es aparte (`test_certificate_pdf.py`).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from itcj2.apps.titulatec.models import Certificate
from itcj2.apps.titulatec.services.certificate_service import CERT_KINDS, CertificateService

NOTIFY = "itcj2.apps.titulatec.services.notify.notify_student"


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
# issue — numeración (Review Focus #6)
# ---------------------------------------------------------------------------
class TestIssueNumeracion:
    def test_primer_folio_del_anio_es_0001_y_congela_los_datos(self, db_session, escenario):
        proc, alumno = escenario["process"], escenario["student"]

        cert = CertificateService.issue(
            db_session, kind="library_clearance", process=proc,
            source_ref="library_clearance:1", actor_id=alumno.id)

        assert cert.id is not None
        assert cert.number.startswith("BIB-")
        assert cert.number.endswith("-0001")
        assert cert.process_id == proc.id
        assert cert.source_ref == "library_clearance:1"
        assert cert.control_number == "20261234"
        assert cert.student_name == alumno.full_name
        assert cert.program_name == "Ingeniería en Sistemas Computacionales"
        assert cert.period_label == escenario["period"].name   # periodo sintético: cae al respaldo
        assert cert.issued_by_id == alumno.id
        assert cert.issued_at is not None
        assert cert.voided_at is None
        assert cert.batch_id is None

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
                                        source_ref="library_clearance:1", actor_id=actor.id)

        assert cert.period_label == "Enero-Junio 2099"

    def test_secuencia_por_tipo_y_anio(self, db_session, escenario, actor):
        proc = escenario["process"]

        c1 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref="library_clearance:1", actor_id=actor.id)
        c2 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref="library_clearance:2", actor_id=actor.id)
        c3 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref="library_clearance:3", actor_id=actor.id)

        assert [_folio_n(c.number) for c in (c1, c2, c3)] == \
            [_folio_n(c1.number), _folio_n(c1.number) + 1, _folio_n(c1.number) + 2]

    def test_tipos_distintos_no_comparten_secuencia(self, db_session, escenario, actor):
        proc = escenario["process"]

        bib = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                       source_ref="library_clearance:1", actor_id=actor.id)
        gtv = CertificateService.issue(db_session, kind="survey_release", process=proc,
                                       source_ref="survey_review:1", actor_id=actor.id)

        assert bib.number.endswith("-0001")
        assert gtv.number.endswith("-0001")

    def test_cambio_de_anio_reinicia_el_contador(self, db_session, escenario, monkeypatch, actor):
        import itcj2.apps.titulatec.services.certificate_service as cert_mod

        proc = escenario["process"]
        monkeypatch.setattr(cert_mod, "db_now", lambda: datetime(2029, 3, 1, 8, 0, 0))
        c1 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref="library_clearance:1", actor_id=actor.id)
        assert c1.number == "BIB-2029-0001"

        monkeypatch.setattr(cert_mod, "db_now", lambda: datetime(2030, 1, 15, 8, 0, 0))
        c2 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref="library_clearance:2", actor_id=actor.id)
        assert c2.number == "BIB-2030-0001"   # reinicia; NO sigue en 0002

    def test_anular_no_libera_el_numero(self, db_session, escenario, actor):
        proc = escenario["process"]
        c1 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref="library_clearance:1", actor_id=actor.id)
        CertificateService.void(db_session, source_ref="library_clearance:1", actor_id=actor.id,
                                reason="Emitida por error.")

        c2 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref="library_clearance:9", actor_id=actor.id)

        assert _folio_n(c2.number) == _folio_n(c1.number) + 1

    def test_re_emitir_el_mismo_origen_saca_otro_folio_y_no_reabre_el_anulado(
            self, db_session, escenario, actor):
        proc = escenario["process"]
        ref = "library_clearance:1"

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
                                     source_ref="x:1", actor_id=1)

    def test_dos_conexiones_reales_simultaneas_numeran_sin_colision(self, _pg_engine):
        """Review Focus #6 («emisiones simultáneas»): DOS conexiones REALES
        a Postgres (no el `db_session` de SAVEPOINTs del resto del archivo,
        que comparte una sola conexión física y no puede modelar bloqueo
        entre transacciones) numerando el MISMO `(kind, year)` a la vez.

        No basta con lanzar dos hilos y esperar que no truenen -- eso
        pasaría igual aunque el segundo nunca tocara el lock del primero.
        Este test CONFIRMA con `pg_stat_activity` que el hilo B de verdad
        quedó bloqueado (`wait_event_type = 'Lock'`) esperando el renglón
        que el hilo A todavía no suelta, y SOLO ENTONCES deja que A comitee
        -- así el `{1, 2}` de abajo prueba la atomicidad del
        `INSERT ... ON CONFLICT ... DO UPDATE`, no una coincidencia de
        scheduling del hilo del SO.

        Año 1901 a propósito: imposible de chocar con una convocatoria real
        de la BD de dev COMPARTIDA (CLAUDE.md). El renglón que el contador
        deja en `titulatec_certificate_counters` se borra en un ÚNICO
        `finally` que envuelve TODO el cuerpo (arrancar los hilos + los
        asserts), pase lo que pase -- un `try/finally` partido en dos (uno
        para arrancar/sondear, otro para los asserts finales) dejaba el
        DELETE sin correr si el primero tronaba (p. ej. `assert bloqueada`),
        y encima `hilo_b.join()` sobre un hilo que nunca arrancó revienta con
        `RuntimeError` y tapa el assert real (fix round 2 de la revisión).
        """
        kind = "library_clearance"
        year = 1901
        Session = sessionmaker(bind=_pg_engine, future=True)

        # Limpieza previa defensiva: si una corrida anterior murió a medio
        # camino (antes de llegar a su propio `finally`), que no arrastre un
        # renglón viejo que invalidaría el {1, 2} de abajo.
        with _pg_engine.begin() as conn:
            conn.execute(text("DELETE FROM titulatec_certificate_counters "
                              "WHERE kind = :k AND year = :y"), {"k": kind, "y": year})

        resultados: dict[str, str] = {}
        errores: list[tuple[str, Exception]] = []
        pids: dict[str, int] = {}
        a_tiene_el_renglon = threading.Event()
        seguir_con_commit_de_a = threading.Event()

        def _hilo_a():
            session = Session()
            try:
                resultados["A"] = CertificateService._next_number(session, kind, year)
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
                resultados["B"] = CertificateService._next_number(session, kind, year)
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
        finally:
            # Red de seguridad ÚNICA para TODO el cuerpo de arriba: pase lo
            # que pase (cualquier assert roto, cualquier excepción), nunca se
            # cuelga un hilo vivo ni se le queda pegado a la BD compartida el
            # renglón de 1901.
            seguir_con_commit_de_a.set()        # idempotente -- suelta a A
            for hilo in (hilo_a, hilo_b):
                if hilo.ident is not None:      # solo los que sí arrancaron
                    hilo.join(timeout=5)
            with _pg_engine.begin() as conn:
                conn.execute(text("DELETE FROM titulatec_certificate_counters "
                                  "WHERE kind = :k AND year = :y"), {"k": kind, "y": year})


# ---------------------------------------------------------------------------
# void
# ---------------------------------------------------------------------------
class TestVoid:
    def test_anula_la_vigente_sin_borrarla(self, db_session, escenario, actor, make_user):
        proc = escenario["process"]
        otro = make_user(first_name="REVISOR", last_name="PRUEBA")
        cert = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                        source_ref="library_clearance:1", actor_id=actor.id)

        anulada = CertificateService.void(db_session, source_ref="library_clearance:1",
                                          actor_id=otro.id, reason="  Motivo de prueba.  ")

        assert anulada.id == cert.id
        assert anulada.voided_at is not None
        assert anulada.voided_by_id == otro.id
        assert anulada.void_reason == "Motivo de prueba."   # recortado

    def test_sin_vigente_regresa_none(self, db_session, escenario):
        resultado = CertificateService.void(db_session, source_ref="nunca_existio:1",
                                            actor_id=1, reason="x")
        assert resultado is None

    def test_no_se_puede_anular_dos_veces(self, db_session, escenario, actor):
        proc = escenario["process"]
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref="library_clearance:1", actor_id=actor.id)

        primera = CertificateService.void(db_session, source_ref="library_clearance:1",
                                          actor_id=actor.id, reason="uno")
        segunda = CertificateService.void(db_session, source_ref="library_clearance:1",
                                          actor_id=actor.id, reason="dos")

        assert primera is not None
        assert segunda is None


# ---------------------------------------------------------------------------
# pending / create_batch / list_batches / certificates_of
# ---------------------------------------------------------------------------
class TestLotes:
    def test_pending_count_y_pending_en_orden_fifo(self, db_session, escenario, actor):
        proc = escenario["process"]
        c1 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref="library_clearance:1", actor_id=actor.id)
        c2 = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                      source_ref="library_clearance:2", actor_id=actor.id)

        assert CertificateService.pending_count(db_session, "library_clearance") == 2
        pendientes = CertificateService.pending(db_session, "library_clearance")
        assert [c.id for c in pendientes] == [c1.id, c2.id]

    def test_create_batch_sin_pendientes(self, db_session, escenario):
        with pytest.raises(ValueError):
            CertificateService.create_batch(db_session, kind="library_clearance", actor_id=1)

    def test_create_batch_toma_las_pendientes_y_las_marca(self, db_session, escenario, actor):
        proc = escenario["process"]
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref="library_clearance:1", actor_id=actor.id)
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref="library_clearance:2", actor_id=actor.id)

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
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref="library_clearance:1", actor_id=actor.id)
        CertificateService.void(db_session, source_ref="library_clearance:1", actor_id=actor.id,
                                reason="no aplica")

        assert CertificateService.pending_count(db_session, "library_clearance") == 0
        with pytest.raises(ValueError):
            CertificateService.create_batch(db_session, kind="library_clearance", actor_id=actor.id)

    def test_el_lote_no_mezcla_tipos(self, db_session, escenario, actor):
        proc = escenario["process"]
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref="library_clearance:1", actor_id=actor.id)
        CertificateService.issue(db_session, kind="survey_release", process=proc,
                                 source_ref="survey_review:1", actor_id=actor.id)

        batch = CertificateService.create_batch(db_session, kind="library_clearance",
                                                 actor_id=actor.id)

        assert batch.count == 1
        assert CertificateService.pending_count(db_session, "survey_release") == 1

    def test_create_batch_kind_desconocido(self, db_session, escenario):
        with pytest.raises(ValueError):
            CertificateService.create_batch(db_session, kind="otra_cosa", actor_id=1)

    def test_certificates_of_incluye_las_anuladas(self, db_session, escenario, actor):
        proc = escenario["process"]
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref="library_clearance:1", actor_id=actor.id)
        batch = CertificateService.create_batch(db_session, kind="library_clearance",
                                                 actor_id=actor.id)
        CertificateService.void(db_session, source_ref="library_clearance:1", actor_id=actor.id,
                                reason="se corrigió después de imprimir")

        miembros = CertificateService.certificates_of(db_session, batch.id)

        assert len(miembros) == 1
        assert miembros[0].voided_at is not None
        assert miembros[0].batch_id == batch.id   # anular no la saca del lote

    def test_list_batches_trae_autor_cuenta_y_anuladas(self, db_session, escenario, make_user):
        proc = escenario["process"]
        autor = make_user(first_name="BIBLIO", last_name="TECARIA")
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref="library_clearance:1", actor_id=autor.id)
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref="library_clearance:2", actor_id=autor.id)
        batch = CertificateService.create_batch(db_session, kind="library_clearance",
                                                actor_id=autor.id)
        CertificateService.void(db_session, source_ref="library_clearance:1", actor_id=autor.id,
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
        for i in range(3):
            CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                     source_ref=f"library_clearance:{i}", actor_id=actor.id)
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

    def test_list_batches_de_otro_kind_sale_vacio(self, db_session, escenario, actor):
        proc = escenario["process"]
        CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                 source_ref="library_clearance:1", actor_id=actor.id)
        CertificateService.create_batch(db_session, kind="library_clearance", actor_id=actor.id)

        filas, has_more = CertificateService.list_batches(db_session, kind="survey_release")

        assert filas == []
        assert has_more is False


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
                                        source_ref="library_clearance:99", actor_id=actor.id)

        assert len(cert.period_label) == 40
        assert cert.period_label == periodo.name[:40]

    def test_issue_trunca_control_number_y_student_name_a_su_columna(
            self, db_session, make_user, make_process, make_cohort, actor):
        alumno = make_user(first_name="X" * 150, last_name="Y" * 150,
                           control_number="9" * 30)   # más largo que String(20)
        proc = make_process(alumno, cohort=make_cohort())

        cert = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                        source_ref="library_clearance:1", actor_id=actor.id)

        assert len(cert.control_number) == 20
        assert cert.control_number == ("9" * 30)[:20]
        assert len(cert.student_name) <= 200


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
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        process, gtv = gtv_escenario["process"], gtv_escenario["gtv"]
        review = make_survey_review(process, status="in_review")
        review.origin = "prior"
        db_session.flush()

        with patch(NOTIFY):
            SurveyReviewService.approve(db_session, review.id, gtv.id)
            resultado = SurveyReviewService.revoke(db_session, review.id, gtv.id, "motivo")

        assert resultado.status == "rejected"
        assert (db_session.query(Certificate)
               .filter_by(source_ref=f"survey_review:{review.id}").first()) is None
