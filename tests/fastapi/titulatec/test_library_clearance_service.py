"""Tests de `LibraryClearanceService`: único dueño de la máquina de estados del
no adeudo de biblioteca (Biblioteca → Caja). Spec
`2026-10-01-titulatec-biblioteca-caja-design.md` §4.2, D3/D4/D5/D9/D16-D19,
§4.7/§4.8 (bandejas) y §5 (invariantes).

Cubre cada flecha de §4.2 y cada error (estado equivocado, proceso revocado o
terminado, en pausa permitido, sin donación, total 0, corregir re-congela,
lote con omitidos, constancia previa 365/366/futura, revertir con la fase 2
aprobada), `parse_amount`, el requisito cumplido/descumplido (con y SIN
requisito automático en la convocatoria: Ruling R2, los `DEFAULTS` no lo marcan
automático hasta la Tarea 5, así que cada escenario crea el suyo), la
constancia emitida/anulada, eventos y avisos, las listas de las bandejas y el
alta de la fila en `ImportService.import_rows`.

CONCURRENCIA (Review Focus #1). Se SIMULA el estado tras el lock: otra
transacción ya escribió la fila (un UPDATE crudo, por fuera del mapa de
identidad del ORM) mientras esta sesión conserva la foto vieja del objeto. La
transición tiene que releer al tomar el `FOR UPDATE` y responder con un
`ValueError` claro, sin doble cobro ni monto pisado. Que de verdad pida el
`FOR UPDATE` lo fija la captura de SQL (`TestBloqueo`).

DATOS. La BD de dev es COMPARTIDA y ya trae filas reales del backfill: las
listas se aíslan con un token único en el apellido (`q`) o se miden por delta,
nunca por absolutos; los periodos son los sintéticos de `make_period` y los
días de cobro de `day_cut` (`TestDayCut`) son de 2031, donde nadie más cobra.
Esas pruebas fijan `ProcessEvent.created_at` A MANO tras llamar al service
real (el `db_now()` parchado NO toca el `server_default=NOW()` del evento):
nunca dependen del reloj de verdad ni de una fecha de calendario fija contra
él.
"""
from __future__ import annotations

import ast
import inspect
import re
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import event, text

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.library_clearance_service import (
    AMOUNT_MAX, AUTO_SOURCE_LIBRARY, LIBRARY_EVENT_TYPES, PHASE_COTEJO,
    PRIOR_VALIDITY_DAYS, REASON_MAX, LibraryClearanceService, format_amount,
    parse_amount,
)

NOTIFY = "itcj2.apps.titulatec.services.notify.notify_student"
SVC = "itcj2.apps.titulatec.services.library_clearance_service"

DONACION = Decimal("800.00")
ADEUDO = Decimal("300.00")
HOY_FIJO = datetime(2026, 10, 1, 10, 0, 0)   # reloj fijo de las pruebas de vigencia


# ---------------------------------------------------------------------------
# Ayudantes
# ---------------------------------------------------------------------------
def _req(db, cohort, *, code, auto_source=None, label=None, is_active=True):
    """Un `CotejoRequirement` escrito a mano (patrón de test_survey_review_service)."""
    from itcj2.apps.titulatec.models import CotejoRequirement
    row = CotejoRequirement(
        cohort_id=cohort.id, label=label or f"Requisito {code}", icon="book",
        code=code, auto_source=auto_source, is_required=True,
        is_active=is_active, order_index=0,
    )
    db.add(row)
    db.flush()
    return row


def _auto_req(db, cohort):
    from itcj2.apps.titulatec.models import CotejoRequirement
    return (db.query(CotejoRequirement)
            .filter_by(cohort_id=cohort.id, auto_source=AUTO_SOURCE_LIBRARY)
            .first())


def _events(db, process_id, tipo):
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db.query(ProcessEvent)
            .filter_by(process_id=process_id, event_type=tipo)
            .order_by(ProcessEvent.id).all())


def _library_events(db, process_id):
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db.query(ProcessEvent)
            .filter(ProcessEvent.process_id == process_id,
                    ProcessEvent.event_type.in_(LIBRARY_EVENT_TYPES))
            .order_by(ProcessEvent.id).all())


def _fulfillment(db, process_id, requirement_id):
    from itcj2.apps.titulatec.models import RequirementFulfillment
    return (db.query(RequirementFulfillment)
            .filter_by(process_id=process_id, requirement_id=requirement_id).first())


def _fulfillments_of(db, process_id):
    from itcj2.apps.titulatec.models import RequirementFulfillment
    return db.query(RequirementFulfillment).filter_by(process_id=process_id).all()


def _certs(db, clearance_id):
    from itcj2.apps.titulatec.models import Certificate
    return (db.query(Certificate)
            .filter_by(source_ref=f"library_clearance:{clearance_id}")
            .order_by(Certificate.id).all())


def _vigente(db, clearance_id):
    """La constancia VIGENTE (sin anular) de la fila: debe ser exactamente una."""
    (vigente,) = [c for c in _certs(db, clearance_id) if c.voided_at is None]
    return vigente


def _fase2(db, process, status):
    from itcj2.apps.titulatec.models import ProcessPhase
    fase = (db.query(ProcessPhase)
            .filter_by(process_id=process.id, phase_number=2).first())
    fase.status = status
    db.flush()


@contextmanager
def _sql(db):
    """Captura el SQL que la sesión manda a Postgres mientras dura el bloque."""
    sentencias: list[str] = []
    conn = db.connection()

    def _antes(_conn, _cursor, statement, _params, _context, _executemany):
        sentencias.append(statement)

    event.listen(conn, "before_cursor_execute", _antes)
    try:
        yield sentencias
    finally:
        event.remove(conn, "before_cursor_execute", _antes)


def _pide_for_update(sentencias) -> bool:
    return any("titulatec_library_clearances" in s and "FOR UPDATE" in s.upper()
               for s in sentencias)


def _literales(expr) -> set[str]:
    if isinstance(expr, ast.IfExp):
        return _literales(expr.body) | _literales(expr.orelse)
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return {expr.value}
    return set()


# ---------------------------------------------------------------------------
# Escenarios
# ---------------------------------------------------------------------------
@pytest.fixture()
def actores(make_user):
    return SimpleNamespace(
        biblioteca=make_user(first_name="BIBLIOTECA", last_name="DE PRUEBA"),
        biblioteca2=make_user(first_name="BIBLIOTECA DOS", last_name="DE PRUEBA"),
        caja=make_user(first_name="CAJA", last_name="DE PRUEBA"),
        caja2=make_user(first_name="CAJA DOS", last_name="DE PRUEBA"),
        se=make_user(first_name="ESCOLARES", last_name="DE PRUEBA"),
    )


@pytest.fixture()
def nuevo(db_session, make_student, make_process, make_cohort, make_program,
          make_library_clearance):
    """Fábrica: convocatoria (donación $800 y requisito automático de no adeudo
    por omisión) + egresado + proceso en fase 1 + su fila de no adeudo.

    `requisito=False` crea OTRO requisito cualquiera: bloquea la siembra de
    `DEFAULTS` (antes y después de la Tarea 5) y deja la convocatoria SIN
    candado de biblioteca. `status=None` no crea la fila de no adeudo.
    `cohort=` reutiliza una convocatoria ya armada (las listas).
    """
    programa = make_program("Ingeniería Ficticia de Biblioteca")

    def _build(*, status="pending", donation=DONACION, requisito=True, cohort=None,
               process_status="active", phase=1, first_name="ALUMNO",
               last_name="FICTICIO", control_number=None, **cols):
        if cohort is None:
            cohort = make_cohort(book_donation_amount=donation)
            if requisito:
                _req(db_session, cohort, code="library_clearance",
                     auto_source=AUTO_SOURCE_LIBRARY, label="No-adeudo de biblioteca")
            else:
                _req(db_session, cohort, code="birth_certificates",
                     label="Actas de nacimiento")
        student = make_student(control_number=control_number,
                               first_name=first_name, last_name=last_name)
        process = make_process(student, cohort=cohort, program=programa,
                               current_phase=phase, status=process_status,
                               library_clearance=None)
        clearance = (make_library_clearance(process, status=status, **cols)
                     if status is not None else None)
        return SimpleNamespace(cohort=cohort, process=process, student=student,
                               clearance=clearance, req=_auto_req(db_session, cohort))

    return _build


@pytest.fixture()
def commits(db_session, monkeypatch):
    """Cuenta los `commit()` del service (siguen ocurriendo de verdad)."""
    cuenta: list[int] = []
    original = db_session.commit

    def _commit():
        cuenta.append(1)
        original()

    monkeypatch.setattr(db_session, "commit", _commit)
    return cuenta


@pytest.fixture()
def reloj(monkeypatch):
    """`db_now()` del service fijo en HOY_FIJO (las reglas de vigencia)."""
    monkeypatch.setattr(f"{SVC}.db_now", lambda: HOY_FIJO)
    return HOY_FIJO.date()


def _a_caja(db, esc, actor, debt=ADEUDO, note=None):
    with patch(NOTIFY):
        return LibraryClearanceService.register(
            db, esc.clearance.id, actor.id, debt_amount=debt, note=note)


def _pagar(db, esc, actor, receipt="R-100"):
    with patch(NOTIFY):
        return LibraryClearanceService.register_payment(
            db, esc.clearance.id, actor.id, receipt_number=receipt)


# ---------------------------------------------------------------------------
# Constantes y vocabulario de eventos
# ---------------------------------------------------------------------------
def test_constantes_publicas():
    assert PRIOR_VALIDITY_DAYS == 365
    assert AMOUNT_MAX == Decimal("100000.00")
    assert REASON_MAX == 1000
    assert AUTO_SOURCE_LIBRARY == "library_clearance"
    assert PHASE_COTEJO == 2


def test_los_diez_eventos_del_spec_caben_en_la_columna():
    assert LIBRARY_EVENT_TYPES == (
        "library_debt_registered", "library_no_charge", "library_amount_corrected",
        "library_payment_registered", "library_prior_registered",
        "library_payment_reverted", "library_clearance_reverted", "library_prior_undone",
        # «Con observaciones» (spec 2026-10-05 §3.2).
        "library_observed", "library_reenabled",
    )
    assert all(len(e) <= 40 for e in LIBRARY_EVENT_TYPES)   # ProcessEvent.event_type String(40)


def test_el_service_escribe_exactamente_esos_eventos():
    """La constante no es decorativa: es lo que los `_log(...)` escriben."""
    from itcj2.apps.titulatec.services import library_clearance_service as mod

    escritos: set[str] = set()
    for nodo in ast.walk(ast.parse(inspect.getsource(mod))):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr == "_log"):
            assert len(nodo.args) >= 4, "event_type va en 4.º lugar (test_mail_writers)"
            lits = _literales(nodo.args[3])
            assert lits, f"event_type no literal en la línea {nodo.lineno}"
            escritos |= lits
    assert escritos == set(LIBRARY_EVENT_TYPES)


# ---------------------------------------------------------------------------
# parse_amount / format_amount (Review Focus #3)
# ---------------------------------------------------------------------------
class TestParseAmount:
    @pytest.mark.parametrize("raw, esperado", [
        ("800", "800.00"),
        ("800.5", "800.50"),
        ("1,200.50", "1200.50"),
        ("$1,200", "1200.00"),
        ("$800", "800.00"),
        ("  $ 1,200.50  ", "1200.50"),
        ("0", "0.00"),
        ("0.99", "0.99"),
        ("1200", "1200.00"),
        ("12,345.6", "12345.60"),
        ("100000", "100000.00"),
        ("100,000.00", "100000.00"),
    ])
    def test_formatos_de_pesos_aceptados(self, raw, esperado):
        valor = parse_amount(raw)
        assert isinstance(valor, Decimal)
        assert valor == Decimal(esperado)
        assert str(valor) == esperado          # siempre a centavos

    @pytest.mark.parametrize("raw, fragmento", [
        (None, "Escribe el monto"),
        ("", "Escribe el monto"),
        ("   ", "Escribe el monto"),
        ("-5", "negativo"),
        ("-$5", "negativo"),
        ("$-5", "negativo"),
        ("800.555", "2 decimales"),
        ("1e3", "no válido"),
        ("1E3", "no válido"),
        ("abc", "no válido"),
        ("1,20", "no válido"),
        ("1.2.3", "no válido"),
        (".5", "no válido"),
        ("800.", "no válido"),
        ("$", "no válido"),
        ("NaN", "no válido"),
        ("Infinity", "no válido"),
        ("８００", "no válido"),      # dígitos de ancho completo: no son pesos
        ("100001", "$100,000.00"),
        ("100000.01", "$100,000.00"),
        ("99999999999999999999999999999999", "$100,000.00"),
    ])
    def test_rechaza_con_mensaje_legible(self, raw, fragmento):
        with pytest.raises(ValueError) as exc:
            parse_amount(raw)
        assert fragmento in str(exc.value)


def test_format_amount():
    assert format_amount(Decimal("1200.5")) == "$1,200.50"
    assert format_amount(Decimal("0")) == "$0.00"
    assert format_amount(Decimal("100000.00")) == "$100,000.00"
    assert format_amount(None) == ""


# ---------------------------------------------------------------------------
# open_for_process / lectura
# ---------------------------------------------------------------------------
class TestOpenForProcess:
    def test_abre_pending_sin_commit(self, db_session, nuevo, monkeypatch):
        esc = nuevo(status=None)
        monkeypatch.setattr(db_session, "commit",
                            lambda: pytest.fail("open_for_process no debe commitear"))

        fila = LibraryClearanceService.open_for_process(db_session, esc.process)

        assert fila.id is not None
        assert fila.process_id == esc.process.id
        assert fila.status == "pending"
        assert fila.cleared_via is None
        assert fila.total_amount is None

    def test_es_idempotente(self, db_session, nuevo):
        from itcj2.apps.titulatec.models import LibraryClearance
        esc = nuevo(status=None)

        primera = LibraryClearanceService.open_for_process(db_session, esc.process)
        segunda = LibraryClearanceService.open_for_process(db_session, esc.process)

        assert primera.id == segunda.id
        assert db_session.query(LibraryClearance).filter_by(
            process_id=esc.process.id).count() == 1

    def test_respeta_la_fila_existente(self, db_session, nuevo):
        esc = nuevo(status="cleared")
        fila = LibraryClearanceService.open_for_process(db_session, esc.process)
        assert fila.id == esc.clearance.id
        assert fila.status == "cleared"

    def test_just_created_inserta_sin_select_previo(self, db_session, nuevo):
        """La variante del importador: el proceso se acaba de insertar y no puede
        tener fila; un SELECT por alumno es costo puro en un lote de 400."""
        esc = nuevo(status=None)

        with _sql(db_session) as sentencias:
            fila = LibraryClearanceService.open_for_process(
                db_session, esc.process, just_created=True)

        assert fila.id is not None          # con id: el llamador puede usarla ya
        assert fila.status == "pending"
        tocan = [s for s in sentencias if "titulatec_library_clearances" in s]
        assert tocan, "no se capturó el INSERT: el listener no ve la conexión"
        assert not [s for s in tocan if s.lstrip().upper().startswith("SELECT")]


class TestLectura:
    def test_get_for_process(self, db_session, nuevo):
        sin = nuevo(status=None)
        con = nuevo(status="pending")
        assert LibraryClearanceService.get_for_process(db_session, sin.process.id) is None
        assert LibraryClearanceService.get_for_process(
            db_session, con.process.id).id == con.clearance.id

    @pytest.mark.parametrize("status", ["pending", "awaiting_payment", "cleared"])
    def test_release_status_es_el_estado_real(self, db_session, nuevo, status):
        cols = ({"debt_amount": ADEUDO, "donation_amount": DONACION,
                 "total_amount": ADEUDO + DONACION}
                if status == "awaiting_payment" else {})
        esc = nuevo(status=status, **cols)
        assert LibraryClearanceService.release_status(db_session, esc.process.id) == status

    def test_release_status_missing_sin_fila(self, db_session, nuevo):
        esc = nuevo(status=None)
        assert LibraryClearanceService.release_status(db_session, esc.process.id) == "missing"

    def test_release_status_map_en_una_consulta(self, db_session, nuevo):
        en_caja = nuevo(status="awaiting_payment", debt_amount=ADEUDO,
                        donation_amount=DONACION, total_amount=ADEUDO + DONACION)
        sin = nuevo(status=None)
        liberado = nuevo(status="cleared")

        with _sql(db_session) as sentencias:
            mapa = LibraryClearanceService.release_status_map(
                db_session, [en_caja.process.id, sin.process.id, liberado.process.id])

        assert mapa == {en_caja.process.id: "awaiting_payment",
                        sin.process.id: "missing",
                        liberado.process.id: "cleared"}
        assert len([s for s in sentencias if "titulatec_library_clearances" in s]) == 1

    def test_release_status_map_vacio(self, db_session):
        assert LibraryClearanceService.release_status_map(db_session, []) == {}


class TestSummary:
    # Sin `certificate` ni `certificate_number` (Rulings R14 y R17, revisión
    # final de `2026-10-02-titulatec-constancias-y-pendientes-design.md`
    # §3.4): el resumen no consulta constancias. El estado de impresión lo
    # cuelgan las dos vistas de SE con UNA llamada a `print_status_map`
    # (`test_se_library_views.py::TestUnaLecturaDeLaMarcaPorVista`), y el
    # folio suelto ya no tenía lector desde la Task 4 (Caja lee el de `_rows`).
    LLAVES = {"status", "via", "debt", "donation", "total", "note", "ready_at",
              "paid_at", "receipt",
              "prior_issued_on", "prior_note", "observation", "observed_at",
              "can_revert", "clearance_id"}

    def test_sin_fila(self, db_session, nuevo):
        esc = nuevo(status=None)
        resumen = LibraryClearanceService.summary_for_process(db_session, esc.process.id)
        assert resumen == {llave: None for llave in self.LLAVES} | {
            "status": "missing", "can_revert": False}

    def test_en_caja_trae_desglose_y_nota(self, db_session, nuevo, actores):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca, note="Debe 2 libros")

        resumen = LibraryClearanceService.summary_for_process(db_session, esc.process.id)

        assert set(resumen) == self.LLAVES
        assert resumen["status"] == "awaiting_payment"
        assert resumen["via"] is None
        assert (resumen["debt"], resumen["donation"], resumen["total"]) == (
            ADEUDO, DONACION, ADEUDO + DONACION)
        assert resumen["note"] == "Debe 2 libros"
        assert resumen["ready_at"] is not None
        assert resumen["paid_at"] is None
        assert resumen["can_revert"] is False          # no está liberado
        assert resumen["clearance_id"] == esc.clearance.id

    def test_pagado_trae_recibo_y_se_puede_revertir(self, db_session, nuevo, actores):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        _pagar(db_session, esc, actores.caja, receipt="R-777")

        resumen = LibraryClearanceService.summary_for_process(db_session, esc.process.id)

        assert resumen["status"] == "cleared"
        assert resumen["via"] == "payment"
        assert resumen["receipt"] == "R-777"
        assert resumen["paid_at"] is not None
        assert resumen["can_revert"] is True

    def test_no_consulta_constancias(self, db_session, nuevo, actores, monkeypatch):
        """Rulings R14 y R17 (revisión final): el resumen lo usan también el
        tablero del egresado y «Mi cita», que no pintan la constancia, y las
        vistas de SE, que cuelgan su `certificate` con UNA llamada por vista.
        Así que no trae ni `certificate` ni `certificate_number` y no toca
        `titulatec_certificates`/`titulatec_certificate_batches`, ni siquiera
        con la constancia vigente ya en un lote."""
        from itcj2.apps.titulatec.services.certificate_service import CertificateService

        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        _pagar(db_session, esc, actores.caja)
        CertificateService.create_batch(db_session, kind="library_clearance",
                                        actor_id=actores.caja.id)
        llamadas = []
        monkeypatch.setattr(CertificateService, "print_status_map", staticmethod(
            lambda db, refs: llamadas.append(list(refs)) or {}))

        with _sql(db_session) as sentencias:
            resumen = LibraryClearanceService.summary_for_process(db_session, esc.process.id)

        assert set(resumen) == self.LLAVES
        assert llamadas == []
        assert not [s for s in sentencias if "titulatec_certificate" in s], sentencias

    def test_certificate_ref_es_el_source_ref_de_su_constancia(self, db_session, nuevo,
                                                               actores):
        """`certificate_ref` (Ruling R14): el MISMO `source_ref` con el que se
        emite/anula la constancia BIB -con él las vistas de SE piden la marca
        de impresión-; `None` sin fila."""
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        _pagar(db_session, esc, actores.caja)

        ref = LibraryClearanceService.certificate_ref(esc.clearance.id)
        assert ref == _vigente(db_session, esc.clearance.id).source_ref
        assert LibraryClearanceService.certificate_ref(None) is None

    def test_previa_trae_fecha_y_nota(self, db_session, nuevo, actores, reloj):
        esc = nuevo()
        with patch(NOTIFY):
            LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.biblioteca.id,
                issued_on=reloj - timedelta(days=10), note="Papel de enero", by="library")

        resumen = LibraryClearanceService.summary_for_process(db_session, esc.process.id)
        assert resumen["via"] == "prior"
        assert resumen["prior_issued_on"] == reloj - timedelta(days=10)
        assert resumen["prior_note"] == "Papel de enero"

    def test_no_commitea(self, db_session, nuevo, monkeypatch):
        esc = nuevo(status="cleared")
        monkeypatch.setattr(db_session, "commit",
                            lambda: pytest.fail("summary_for_process no debe commitear"))
        LibraryClearanceService.summary_for_process(db_session, esc.process.id)


# ---------------------------------------------------------------------------
# Ya pasó su cotejo (Rulings R20/R21, I2/I3 de la revisión final): la fase 2
# aprobada sin un no adeudo liberado es `not_applicable`, no «en Biblioteca»,
# y Biblioteca/SE ya no le abren trámite.
# ---------------------------------------------------------------------------
MSG_YA_PASO = "Este egresado ya pasó su cotejo; no necesita trámite de no adeudo."


class TestCotejoYaLiberado:
    @pytest.mark.parametrize("status", [None, "pending", "awaiting_payment"])
    def test_release_status_no_aplica_con_la_fase_2_aprobada(
            self, db_session, nuevo, status):
        cols = ({"debt_amount": ADEUDO, "donation_amount": DONACION,
                 "total_amount": ADEUDO + DONACION}
                if status == "awaiting_payment" else {})
        esc = nuevo(status=status, phase=3, **cols)     # fases 0, 1 y 2 aprobadas

        assert LibraryClearanceService.release_status(
            db_session, esc.process.id) == "not_applicable"

    def test_liberado_sigue_liberado_con_la_fase_2_aprobada(self, db_session, nuevo):
        esc = nuevo(status="cleared", cleared_via="payment", phase=3)

        assert LibraryClearanceService.release_status(db_session, esc.process.id) == "cleared"

    def test_la_fase_2_rechazada_no_es_no_aplica(self, db_session, nuevo):
        """Solo `approved` cierra el trámite: con observaciones el egresado
        vuelve a agendar y el candado sigue."""
        esc = nuevo(status="pending", phase=2)
        _fase2(db_session, esc.process, "rejected")

        assert LibraryClearanceService.release_status(db_session, esc.process.id) == "pending"

    def test_el_mapa_dice_lo_mismo_en_una_consulta(self, db_session, nuevo):
        sin_fila = nuevo(status=None, phase=3)
        pendiente = nuevo(status="pending", phase=3)
        liberado = nuevo(status="cleared", phase=3)
        abierto = nuevo(status="pending")

        with _sql(db_session) as sentencias:
            mapa = LibraryClearanceService.release_status_map(
                db_session, [sin_fila.process.id, pendiente.process.id,
                             liberado.process.id, abierto.process.id, 987654321])

        assert mapa == {sin_fila.process.id: "not_applicable",
                        pendiente.process.id: "not_applicable",
                        liberado.process.id: "cleared",
                        abierto.process.id: "pending",
                        987654321: "missing"}           # inexistente: falla cerrado
        assert len([s for s in sentencias if "titulatec_library_clearances" in s]) == 1

    def test_el_resumen_dice_no_aplica_sin_revertir(self, db_session, nuevo):
        sin_fila = nuevo(status=None, phase=3)
        en_caja = nuevo(status="awaiting_payment", phase=3, debt_amount=ADEUDO,
                        donation_amount=DONACION, total_amount=ADEUDO + DONACION)

        r1 = LibraryClearanceService.summary_for_process(db_session, sin_fila.process.id)
        r2 = LibraryClearanceService.summary_for_process(db_session, en_caja.process.id)

        assert set(r1) == TestSummary.LLAVES and set(r2) == TestSummary.LLAVES
        assert r1["status"] == r2["status"] == "not_applicable"
        assert r1["clearance_id"] is None
        assert r2["clearance_id"] == en_caja.clearance.id
        assert r1["can_revert"] is r2["can_revert"] is False

    def test_registrar_lo_rechaza_sin_escribir(self, db_session, nuevo, actores):
        esc = nuevo(status="pending", phase=3)

        with pytest.raises(ValueError) as exc, patch(NOTIFY):
            LibraryClearanceService.register(
                db_session, esc.clearance.id, actores.biblioteca.id,
                debt_amount=ADEUDO, expected_status="pending")

        assert str(exc.value) == MSG_YA_PASO
        assert esc.clearance.status == "pending" and esc.clearance.debt_amount is None
        assert _library_events(db_session, esc.process.id) == []

    def test_corregir_tambien_lo_rechaza_sin_escribir(self, db_session, nuevo, actores):
        """Ruling R30 #4 (re-revisión de la ola final): R20 ya rechaza
        «Corregir…», no solo «Registrar»/«Sin adeudo» desde «Por revisar» --
        una fila `awaiting_payment` cuya fase 2 se aprobó DURANTE la
        transición (p. ej. SE marcó el requisito a mano) tampoco admite
        corregir el monto desde «En caja»."""
        esc = nuevo(status="awaiting_payment", phase=3, debt_amount=ADEUDO,
                    donation_amount=DONACION, total_amount=ADEUDO + DONACION)

        with pytest.raises(ValueError) as exc, patch(NOTIFY):
            LibraryClearanceService.register(
                db_session, esc.clearance.id, actores.biblioteca.id,
                debt_amount=Decimal("100"), expected_status="awaiting_payment")

        assert str(exc.value) == MSG_YA_PASO
        assert esc.clearance.status == "awaiting_payment"
        assert esc.clearance.debt_amount == ADEUDO            # no se pisó
        assert _library_events(db_session, esc.process.id) == []

    def test_caja_si_puede_cobrar_aunque_ya_paso_su_cotejo(self, db_session, nuevo, actores):
        """Ruling R30 #4: Caja SÍ puede seguir cobrando si el egresado se
        presenta -el adeudo EXISTE aunque el dueño ya clasifique la fila
        `NOT_APPLICABLE` para el candado y los correos (Ruling R21)-;
        `register_payment` nunca mira la fase 2."""
        esc = nuevo(status="awaiting_payment", phase=3, debt_amount=ADEUDO,
                    donation_amount=DONACION, total_amount=ADEUDO + DONACION)
        assert LibraryClearanceService.release_status(
            db_session, esc.process.id) == "not_applicable"

        with patch(NOTIFY):
            LibraryClearanceService.register_payment(
                db_session, esc.clearance.id, actores.caja.id, receipt_number="R-1")

        assert esc.clearance.status == "cleared" and esc.clearance.cleared_via == "payment"
        assert esc.clearance.receipt_number == "R-1"
        assert len(_certs(db_session, esc.clearance.id)) == 1
        assert len(_library_events(db_session, esc.process.id)) == 1

    def test_el_lote_lo_omite_con_su_motivo(self, db_session, nuevo, actores):
        abierto = nuevo()
        cerrado = nuevo(cohort=abierto.cohort, phase=3)

        with patch(NOTIFY):
            resultado = LibraryClearanceService.register_no_debt_bulk(
                db_session, [abierto.clearance.id, cerrado.clearance.id],
                actores.biblioteca.id)

        assert resultado["done"] == 1
        assert resultado["skipped"] == [(cerrado.clearance.id, MSG_YA_PASO)]
        assert cerrado.clearance.status == "pending"

    def test_la_constancia_previa_lo_rechaza(self, db_session, nuevo, actores, reloj):
        esc = nuevo(status="awaiting_payment", phase=3, debt_amount=ADEUDO,
                    donation_amount=DONACION, total_amount=ADEUDO + DONACION)

        with pytest.raises(ValueError) as exc, patch(NOTIFY):
            LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.se.id,
                issued_on=reloj - timedelta(days=5), by="school_services")

        assert str(exc.value) == MSG_YA_PASO
        assert esc.clearance.status == "awaiting_payment"
        assert _library_events(db_session, esc.process.id) == []

    def test_por_revisar_su_contador_y_el_aviso_de_donacion_lo_excluyen(
            self, db_session, nuevo, token):
        abierto = nuevo(last_name=token, donation=None)
        nuevo(cohort=abierto.cohort, last_name=token, phase=3)

        filas = LibraryClearanceService.list_for_inbox(
            db_session, status="pending", q=token).items
        counts = LibraryClearanceService.counts_by_status(db_session, q=token)
        avisos = {a["cohort_id"]: a["pending"] for a in
                  LibraryClearanceService.cohorts_missing_donation(db_session)}

        assert [f["id"] for f in filas] == [abierto.clearance.id]
        assert counts["pending"] == 1
        assert avisos[abierto.cohort.id] == 1


# ---------------------------------------------------------------------------
# Registrar (Biblioteca) desde pending
# ---------------------------------------------------------------------------
class TestRegister:
    def test_con_adeudo_pasa_a_caja_y_congela_la_donacion(
            self, db_session, nuevo, actores, commits):
        esc = nuevo()

        with patch(NOTIFY) as aviso:
            fila = LibraryClearanceService.register(
                db_session, esc.clearance.id, actores.biblioteca.id,
                debt_amount=ADEUDO, note="  Debe 2 libros  ")

        assert fila.id == esc.clearance.id
        assert fila.status == "awaiting_payment"
        assert fila.cleared_via is None
        assert fila.debt_amount == ADEUDO
        assert fila.donation_amount == DONACION       # congelada desde la convocatoria
        assert fila.total_amount == Decimal("1100.00")
        assert fila.library_note == "Debe 2 libros"
        assert fila.library_by_id == actores.biblioteca.id
        assert fila.library_at is not None
        assert fila.ready_at is not None              # ancla de recordatorios
        assert commits == [1]

        evs = _events(db_session, esc.process.id, "library_debt_registered")
        assert len(evs) == 1
        assert evs[0].phase_number == 2
        assert evs[0].actor_id == actores.biblioteca.id
        assert evs[0].payload["debt"] == "300.00"
        assert evs[0].payload["donation"] == "800.00"
        assert evs[0].payload["total"] == "1100.00"
        assert evs[0].payload["note"] == "Debe 2 libros"

        aviso.assert_called_once()
        kw = aviso.call_args.kwargs
        assert kw["type"] == "LIBRARY_READY"
        assert kw["title"] == "Ya puedes pasar a Caja"
        assert "$1,100.00" in kw["body"]
        assert kw["process_id"] == esc.process.id
        assert kw["phase_number"] == 2

        assert _certs(db_session, fila.id) == []       # todavía no se libera
        assert _fulfillment(db_session, esc.process.id, esc.req.id) is None

    def test_sin_adeudo_con_donacion_igual_pasa_a_caja(self, db_session, nuevo, actores):
        """«Sin adeudo» es adeudo 0, no total 0: la donación se paga en Caja."""
        esc = nuevo()
        fila = _a_caja(db_session, esc, actores.biblioteca, debt=Decimal("0"))

        assert fila.status == "awaiting_payment"
        assert fila.debt_amount == Decimal("0.00")
        assert fila.total_amount == DONACION
        assert len(_events(db_session, esc.process.id, "library_debt_registered")) == 1

    def test_adeudo_sin_donacion_cobra_solo_el_adeudo(self, db_session, nuevo, actores):
        esc = nuevo(donation=Decimal("0.00"))
        fila = _a_caja(db_session, esc, actores.biblioteca, debt=ADEUDO)
        assert fila.status == "awaiting_payment"
        assert fila.total_amount == ADEUDO

    def test_total_cero_libera_sin_cargo_con_constancia_y_requisito(
            self, db_session, nuevo, actores, commits):
        """D18: sin adeudo y donación $0 → se libera sin pasar por Caja."""
        esc = nuevo(donation=Decimal("0.00"))

        with patch(NOTIFY) as aviso:
            fila = LibraryClearanceService.register(
                db_session, esc.clearance.id, actores.biblioteca.id,
                debt_amount=Decimal("0"), note=None)

        assert fila.status == "cleared"
        assert fila.cleared_via == "no_charge"
        assert fila.total_amount == Decimal("0.00")
        assert fila.ready_at is None                  # nunca pasó a caja
        assert commits == [1]

        certs = _certs(db_session, fila.id)
        assert len(certs) == 1
        assert certs[0].kind == "library_clearance"
        assert certs[0].number.startswith("BIB-")
        assert certs[0].voided_at is None

        cumplido = _fulfillment(db_session, esc.process.id, esc.req.id)
        assert cumplido is not None
        assert cumplido.status == "fulfilled"
        assert cumplido.source == "system"
        assert cumplido.external_ref == f"library_clearance:{fila.id}"

        evs = _events(db_session, esc.process.id, "library_no_charge")
        assert len(evs) == 1
        assert evs[0].payload["certificate"] == certs[0].number
        assert _events(db_session, esc.process.id, "library_debt_registered") == []
        assert aviso.call_args.kwargs["type"] == "LIBRARY_CLEARED"
        assert aviso.call_args.kwargs["title"] == "Tu no adeudo de biblioteca quedó liberado"

    def test_sin_requisito_automatico_libera_igual_sin_cumplimiento(
            self, db_session, nuevo, actores):
        """Ruling R2: convocatoria sin candado de biblioteca → nada que cumplir."""
        esc = nuevo(donation=Decimal("0.00"), requisito=False)
        assert esc.req is None

        fila = _a_caja(db_session, esc, actores.biblioteca, debt=Decimal("0"))

        assert fila.status == "cleared"
        assert fila.cleared_via == "no_charge"
        assert len(_certs(db_session, fila.id)) == 1
        assert [f for f in _fulfillments_of(db_session, esc.process.id)
                if f.requirement_code == "library_clearance"] == []

    def test_convocatoria_sin_donacion(self, db_session, nuevo, actores):
        """D19: sin donación capturada no se puede pasar el caso a Caja."""
        esc = nuevo(donation=None)

        with pytest.raises(ValueError) as exc:
            LibraryClearanceService.register(
                db_session, esc.clearance.id, actores.biblioteca.id,
                debt_amount=ADEUDO, note=None)

        assert str(exc.value) == (
            f"La convocatoria {esc.cohort.name} no tiene capturada la donación "
            "voluntaria de libro; pide a Servicios Escolares que la capture.")
        assert esc.clearance.status == "pending"
        assert esc.clearance.total_amount is None
        assert _library_events(db_session, esc.process.id) == []

    def test_proceso_en_pausa_si_opera(self, db_session, nuevo, actores):
        """Review Focus #4: convocatoria en pausa → Biblioteca sí trabaja."""
        esc = nuevo(process_status="on_hold")
        fila = _a_caja(db_session, esc, actores.biblioteca)
        assert fila.status == "awaiting_payment"

    @pytest.mark.parametrize("estado, fragmento", [
        ("cancelled", "revocada"),
        ("completed", "terminó"),
    ])
    def test_proceso_revocado_o_terminado(self, db_session, nuevo, actores, estado, fragmento):
        esc = nuevo(process_status=estado)

        with pytest.raises(ValueError) as exc:
            LibraryClearanceService.register(
                db_session, esc.clearance.id, actores.biblioteca.id,
                debt_amount=ADEUDO, note=None)

        assert fragmento in str(exc.value)
        assert esc.clearance.status == "pending"
        assert _library_events(db_session, esc.process.id) == []

    def test_ya_liberado(self, db_session, nuevo, actores):
        esc = nuevo(status="cleared")
        with pytest.raises(ValueError) as exc:
            LibraryClearanceService.register(
                db_session, esc.clearance.id, actores.biblioteca.id,
                debt_amount=ADEUDO, note=None)
        assert "ya está liberado" in str(exc.value)
        assert esc.clearance.status == "cleared"

    @pytest.mark.parametrize("monto", [
        Decimal("-1"), AMOUNT_MAX + Decimal("0.01"), Decimal("1.005"),
        Decimal("NaN"), 1.5, "800", None, True,
    ])
    def test_monto_invalido_no_escribe_nada(self, db_session, nuevo, actores, monto):
        esc = nuevo()
        with pytest.raises(ValueError):
            LibraryClearanceService.register(
                db_session, esc.clearance.id, actores.biblioteca.id,
                debt_amount=monto, note=None)
        assert esc.clearance.status == "pending"
        assert esc.clearance.debt_amount is None
        assert _library_events(db_session, esc.process.id) == []

    def test_monto_entero_y_tope_exacto_se_aceptan(self, db_session, nuevo, actores):
        tope = nuevo(donation=Decimal("0.00"))
        fila = _a_caja(db_session, tope, actores.biblioteca, debt=AMOUNT_MAX)
        assert fila.total_amount == AMOUNT_MAX

        entero = nuevo()
        fila = _a_caja(db_session, entero, actores.biblioteca, debt=500)   # int: exacto
        assert fila.debt_amount == Decimal("500.00")
        assert str(fila.debt_amount) == "500.00"
        assert fila.total_amount == Decimal("1300.00")

    def test_nota_en_blanco_queda_null_y_nota_larga_se_rechaza(
            self, db_session, nuevo, actores):
        esc = nuevo()
        with pytest.raises(ValueError):
            LibraryClearanceService.register(
                db_session, esc.clearance.id, actores.biblioteca.id,
                debt_amount=ADEUDO, note="x" * (REASON_MAX + 1))
        assert esc.clearance.status == "pending"

        fila = _a_caja(db_session, esc, actores.biblioteca, note="   ")
        assert fila.library_note is None

    def test_id_inexistente(self, db_session, actores):
        with pytest.raises(LookupError):
            LibraryClearanceService.register(
                db_session, 9_999_999, actores.biblioteca.id,
                debt_amount=ADEUDO, note=None)


# ---------------------------------------------------------------------------
# Corregir (Biblioteca) desde awaiting_payment — Review Focus #2
# ---------------------------------------------------------------------------
class TestCorregir:
    def test_corrige_el_monto_y_conserva_ready_at(self, db_session, nuevo, actores, commits):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        primera_vez = esc.clearance.ready_at
        commits.clear()

        with patch(NOTIFY) as aviso:
            fila = LibraryClearanceService.register(
                db_session, esc.clearance.id, actores.biblioteca2.id,
                debt_amount=Decimal("500.00"), note="Eran 3 libros")

        assert fila.status == "awaiting_payment"
        assert fila.debt_amount == Decimal("500.00")
        assert fila.total_amount == Decimal("1300.00")
        assert fila.library_note == "Eran 3 libros"
        assert fila.library_by_id == actores.biblioteca2.id
        assert fila.ready_at == primera_vez           # corregir no es entrar a caja (R10)
        assert commits == [1]

        evs = _events(db_session, esc.process.id, "library_amount_corrected")
        assert len(evs) == 1
        assert evs[0].payload["total"] == "1300.00"
        assert evs[0].payload["previous"]["total"] == "1100.00"
        assert len(_events(db_session, esc.process.id, "library_debt_registered")) == 1
        assert aviso.call_args.kwargs["type"] == "LIBRARY_READY"
        assert "$1,300.00" in aviso.call_args.kwargs["body"]

    def test_cambiar_la_donacion_no_mueve_los_montos_congelados(
            self, db_session, nuevo, actores):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)

        esc.cohort.book_donation_amount = Decimal("950.00")    # SE la cambia
        db_session.flush()
        db_session.refresh(esc.clearance)

        assert esc.clearance.donation_amount == DONACION
        assert esc.clearance.total_amount == Decimal("1100.00")

    def test_corregir_re_congela_con_la_donacion_vigente(self, db_session, nuevo, actores):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        esc.cohort.book_donation_amount = Decimal("950.00")
        db_session.flush()

        fila = _a_caja(db_session, esc, actores.biblioteca, debt=ADEUDO)

        assert fila.donation_amount == Decimal("950.00")
        assert fila.total_amount == Decimal("1250.00")

    def test_corregir_a_total_cero_libera_sin_cargo(self, db_session, nuevo, actores):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        esc.cohort.book_donation_amount = Decimal("0.00")
        db_session.flush()

        fila = _a_caja(db_session, esc, actores.biblioteca, debt=Decimal("0"))

        assert fila.status == "cleared"
        assert fila.cleared_via == "no_charge"
        assert len(_certs(db_session, fila.id)) == 1
        assert _fulfillment(db_session, esc.process.id, esc.req.id) is not None
        assert len(_events(db_session, esc.process.id, "library_no_charge")) == 1
        assert _events(db_session, esc.process.id, "library_amount_corrected") == []

    def test_corregir_sin_donacion_vigente(self, db_session, nuevo, actores):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        esc.cohort.book_donation_amount = None
        db_session.flush()

        with pytest.raises(ValueError) as exc:
            _a_caja(db_session, esc, actores.biblioteca, debt=Decimal("100.00"))

        assert "no tiene capturada la donación" in str(exc.value)
        assert esc.clearance.total_amount == Decimal("1100.00")


# ---------------------------------------------------------------------------
# Ruling R10 (revisión de la Tarea 4): `ready_at` es la entrada VIGENTE a Caja
# y una corrección que no cambia nada es no-op
# ---------------------------------------------------------------------------
@pytest.fixture()
def correo_encendido(monkeypatch):
    """El correo encendido sin depender del `.env` del contenedor (atributo del
    singleton de `get_settings()`, como el resto de la suite)."""
    from itcj2.config import get_settings

    monkeypatch.setattr(get_settings(), "TITULATEC_EMAIL_ENABLED", True)


def _outbox(db, process_id, kind):
    from itcj2.apps.titulatec.models import EmailOutbox

    db.flush()
    return db.query(EmailOutbox).filter_by(process_id=process_id, kind=kind).count()


class TestRulingR10:
    def test_pasar_a_caja_vuelve_a_fijar_ready_at(self, db_session, nuevo, actores, reloj):
        """(a) `pending → awaiting_payment` fija `ready_at` aunque la fila traiga
        la entrada de una vuelta anterior (revertida a Biblioteca): el ancla
        del recordatorio y el FIFO de Caja miden la entrada vigente."""
        esc = nuevo(ready_at=datetime(2026, 1, 5, 9, 0))

        fila = _a_caja(db_session, esc, actores.biblioteca)

        assert fila.ready_at == HOY_FIJO

    def test_revertir_el_pago_vuelve_a_fijar_ready_at(self, db_session, nuevo, actores,
                                                      monkeypatch):
        """(a) `cleared/payment → awaiting_payment` también es entrar a Caja."""
        esc = nuevo()
        monkeypatch.setattr(f"{SVC}.db_now", lambda: datetime(2026, 3, 2, 9, 0))
        _a_caja(db_session, esc, actores.biblioteca)
        _pagar(db_session, esc, actores.caja)
        assert esc.clearance.ready_at == datetime(2026, 3, 2, 9, 0)

        monkeypatch.setattr(f"{SVC}.db_now", lambda: datetime(2026, 9, 14, 11, 30))
        with patch(NOTIFY):
            fila = LibraryClearanceService.revert_payment(
                db_session, esc.clearance.id, actores.caja.id, "Pago duplicado")

        assert fila.status == "awaiting_payment"
        assert fila.ready_at == datetime(2026, 9, 14, 11, 30)

    def test_correccion_sin_cambios_es_no_op(self, db_session, nuevo, actores, commits,
                                             correo_encendido, monkeypatch):
        """(b) Mismo adeudo, misma donación congelada, misma nota: ni evento, ni
        aviso, ni correo, ni firma nueva de Biblioteca."""
        esc = nuevo()
        monkeypatch.setattr(f"{SVC}.db_now", lambda: datetime(2026, 9, 1, 9, 0))
        _a_caja(db_session, esc, actores.biblioteca, note="Debe 2 libros")
        firma = (esc.clearance.library_by_id, esc.clearance.library_at,
                 esc.clearance.updated_at, esc.clearance.ready_at)
        eventos = len(_library_events(db_session, esc.process.id))
        correos = _outbox(db_session, esc.process.id, "library_ready")
        commits.clear()

        monkeypatch.setattr(f"{SVC}.db_now", lambda: datetime(2026, 9, 2, 9, 0))
        with patch(NOTIFY) as aviso:
            fila = LibraryClearanceService.register(
                db_session, esc.clearance.id, actores.biblioteca2.id,
                debt_amount=Decimal("300"), note="  Debe 2 libros  ",
                expected_status="awaiting_payment")

        assert correos == 1
        aviso.assert_not_called()
        assert len(_library_events(db_session, esc.process.id)) == eventos
        assert _outbox(db_session, esc.process.id, "library_ready") == correos
        assert (fila.library_by_id, fila.library_at, fila.updated_at,
                fila.ready_at) == firma
        assert fila.status == "awaiting_payment"

    @pytest.mark.parametrize("cambio", ["adeudo", "nota", "donacion"])
    def test_cualquier_cambio_si_es_correccion(self, db_session, nuevo, actores, cambio):
        """El control positivo de (b): basta UNO de los tres para corregir. La
        donación cuenta aunque la escriba SE: corregir re-congela la vigente."""
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca, note="Debe 2 libros")
        if cambio == "donacion":
            esc.cohort.book_donation_amount = Decimal("950.00")
            db_session.flush()

        _a_caja(db_session, esc, actores.biblioteca,
                debt=Decimal("500.00") if cambio == "adeudo" else ADEUDO,
                note="Eran 3 libros" if cambio == "nota" else "Debe 2 libros")

        assert len(_events(db_session, esc.process.id, "library_amount_corrected")) == 1


# ---------------------------------------------------------------------------
# Lecturas para los correos del pago (spec §4.11): la comparación de `status`
# se queda en el dueño
# ---------------------------------------------------------------------------
class TestPagoPendiente:
    def test_en_caja_trae_los_montos_congelados(self, db_session, nuevo, actores):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca, note="Debe 2 libros")

        assert LibraryClearanceService.payment_due(db_session, esc.process.id) == {
            "debt": ADEUDO, "donation": DONACION, "total": ADEUDO + DONACION,
            "note": "Debe 2 libros", "ready_at": esc.clearance.ready_at}

    def test_fuera_de_caja_o_sin_fila_es_none_y_la_clausula_dice_lo_mismo(
            self, db_session, nuevo):
        """Ruling R30 #4 (re-revisión de la ola final, ronda 2): `payment_due`
        y `awaiting_payment_clause` deciden EXACTAMENTE lo mismo -son la
        MISMA pregunta en Python y en SQL-, incluida una fase 2 YA aprobada
        (`ya_paso`, `NOT_APPLICABLE`, Ruling R21): aunque la fila SIGA
        `awaiting_payment`, ninguno de los dos la cuenta como pago pendiente."""
        from itcj2.apps.titulatec.models import LibraryClearance, TitulationProcess

        en_caja = nuevo(status="awaiting_payment", debt_amount=ADEUDO,
                        donation_amount=DONACION, total_amount=ADEUDO + DONACION)
        ya_paso = nuevo(status="awaiting_payment", phase=3, debt_amount=ADEUDO,
                        donation_amount=DONACION, total_amount=ADEUDO + DONACION)
        otros = [nuevo(status="pending"), nuevo(status="cleared")]
        sin_fila = nuevo(status=None)

        assert LibraryClearanceService.payment_due(db_session, en_caja.process.id)
        for esc in (ya_paso, *otros, sin_fila):
            assert LibraryClearanceService.payment_due(db_session, esc.process.id) is None

        ids = [esc.clearance.id for esc in (en_caja, ya_paso, *otros)]
        en_sql = {cid for (cid,) in (
            db_session.query(LibraryClearance.id)
            .join(TitulationProcess, TitulationProcess.id == LibraryClearance.process_id)
            .filter(LibraryClearance.id.in_(ids),
                    LibraryClearanceService.awaiting_payment_clause()))}
        assert en_sql == {en_caja.clearance.id}

    def test_no_commitea(self, db_session, nuevo, monkeypatch):
        esc = nuevo(status="awaiting_payment", debt_amount=Decimal("0.00"),
                    donation_amount=DONACION, total_amount=DONACION)
        monkeypatch.setattr(db_session, "commit",
                            lambda: pytest.fail("payment_due no debe commitear"))
        LibraryClearanceService.payment_due(db_session, esc.process.id)


# ---------------------------------------------------------------------------
# ¿Biblioteca todavía revisa su caso? (m40, spec 2026-10-02 §3.7): el
# predicado del dueño con el que el correo de la reversión a Biblioteca se
# vuelve obsoleto sin que `mail_compose.py` compare estados (invariante 2)
# ---------------------------------------------------------------------------
class TestRevisable:
    # La tabla de casos que parten `reviewable` (Python) y `_reviewable_clause`
    # (SQL, «Por revisar»): las DOS se prueban fila por fila contra ella.
    CASOS = pytest.mark.parametrize("process_status, phase, fase2, revisable", [
        ("active", 1, None, True),               # Biblioteca revisa desde la fase 1 (D3)
        ("active", 2, None, True),               # fase 2 en curso
        ("active", 2, "rejected", True),         # con observaciones vuelve a agendar
        ("on_hold", 2, None, True),              # en pausa Biblioteca SÍ opera
        ("active", 3, None, False),              # ya pasó su cotejo (Ruling R20)
        ("cancelled", 2, None, False),           # revocado
        ("completed", 9, None, False),           # terminó
    ], ids=["fase-1", "fase-2-en-curso", "fase-2-rechazada", "en-pausa",
            "cotejo-aprobado", "revocado", "terminado"])

    @CASOS
    def test_admitido_y_sin_la_fase_2_aprobada(self, db_session, nuevo, process_status,
                                               phase, fase2, revisable):
        """Lo mismo que «Por revisar» (`_reviewable_clause`): proceso admitido
        Y fase 2 sin aprobar. Sin mirar el estado de la fila de no adeudo."""
        esc = nuevo(status="pending", process_status=process_status, phase=phase)
        if fase2 is not None:
            _fase2(db_session, esc.process, fase2)

        assert LibraryClearanceService.reviewable(db_session, esc.process.id) is revisable

    @CASOS
    def test_la_clausula_sql_parte_los_mismos_casos(self, db_session, nuevo, process_status,
                                                    phase, fase2, revisable):
        """M5 (revisión final): la gemela SQL, `_reviewable_clause`, contra la
        MISMA tabla -antes solo `reviewable` la recorría y el docstring de la
        cláusula citaba esta clase-. Una fila sin no adeudo se cuenta igual:
        la cláusula pregunta por el proceso."""
        from itcj2.apps.titulatec.models import TitulationProcess

        esc = nuevo(status="pending", process_status=process_status, phase=phase)
        sin_fila = nuevo(status=None, process_status=process_status, phase=phase)
        ids = [esc.process.id, sin_fila.process.id]
        if fase2 is not None:
            _fase2(db_session, esc.process, fase2)
            _fase2(db_session, sin_fila.process, fase2)

        en_sql = {pid for (pid,) in (
            db_session.query(TitulationProcess.id)
            .filter(TitulationProcess.id.in_(ids),
                    LibraryClearanceService._reviewable_clause()))}

        assert en_sql == (set(ids) if revisable else set())
        assert {pid for pid in ids
                if LibraryClearanceService.reviewable(db_session, pid)} == en_sql

    def test_sin_fila_de_no_adeudo_tambien_responde(self, db_session, nuevo):
        """Pregunta por el PROCESO, no por la fila: sin fila (alta durante el
        blue/green) Biblioteca igual lo revisaría."""
        esc = nuevo(status=None, phase=2)

        assert LibraryClearanceService.reviewable(db_session, esc.process.id) is True

    def test_proceso_inexistente_falla_cerrado(self, db_session):
        assert LibraryClearanceService.reviewable(db_session, 987654321) is False

    def test_dice_lo_mismo_que_la_clausula_de_por_revisar(self, db_session, nuevo):
        """Gemela en Python de `_reviewable_clause` (la de la bandeja): parten
        los MISMOS casos, para que el correo nunca prometa «volverá a revisar
        tu caso» a quien Biblioteca no ve en «Por revisar»."""
        from itcj2.apps.titulatec.models import TitulationProcess

        casos = [nuevo(status="pending", phase=1),
                 nuevo(status="pending", phase=2, process_status="on_hold"),
                 nuevo(status="awaiting_payment", phase=3, debt_amount=ADEUDO,
                       donation_amount=DONACION, total_amount=ADEUDO + DONACION),
                 nuevo(status="cleared", phase=2, process_status="cancelled"),
                 nuevo(status="pending", phase=9, process_status="completed")]
        ids = [esc.process.id for esc in casos]

        en_python = {pid for pid in ids if LibraryClearanceService.reviewable(db_session, pid)}
        en_sql = {pid for (pid,) in (
            db_session.query(TitulationProcess.id)
            .filter(TitulationProcess.id.in_(ids),
                    LibraryClearanceService._reviewable_clause()))}

        assert en_python == en_sql == {casos[0].process.id, casos[1].process.id}

    def test_no_commitea(self, db_session, nuevo, monkeypatch):
        esc = nuevo(status="pending", phase=2)
        monkeypatch.setattr(db_session, "commit",
                            lambda: pytest.fail("reviewable no debe commitear"))
        LibraryClearanceService.reviewable(db_session, esc.process.id)


# ---------------------------------------------------------------------------
# Lote «Sin adeudo» (D10)
# ---------------------------------------------------------------------------
class TestLoteSinAdeudo:
    def test_registra_los_validos_y_omite_con_motivo_en_un_commit(
            self, db_session, nuevo, actores, commits):
        a1 = nuevo()
        a2 = nuevo(cohort=a1.cohort)
        en_caja = nuevo(cohort=a1.cohort, status="awaiting_payment", debt_amount=ADEUDO,
                        donation_amount=DONACION, total_amount=ADEUDO + DONACION)
        liberado = nuevo(cohort=a1.cohort, status="cleared")
        revocado = nuevo(cohort=a1.cohort, process_status="cancelled")
        sin_donacion = nuevo(donation=None)

        ids = [a1.clearance.id, a2.clearance.id, en_caja.clearance.id,
               liberado.clearance.id, revocado.clearance.id,
               sin_donacion.clearance.id, 9_999_999, a1.clearance.id]

        with patch(NOTIFY) as aviso:
            resultado = LibraryClearanceService.register_no_debt_bulk(
                db_session, ids, actores.biblioteca.id)

        assert resultado["done"] == 2
        assert [cid for cid, _ in resultado["skipped"]] == [
            en_caja.clearance.id, liberado.clearance.id, revocado.clearance.id,
            sin_donacion.clearance.id, 9_999_999]
        motivos = dict(resultado["skipped"])
        assert "En caja" in motivos[en_caja.clearance.id]
        # Ruling R30 #3 (M1 completo): el lote SIEMPRE manda
        # `expected_status="pending"`; sobre una fila que ya está `cleared`
        # eso es un choque -`ClearanceConflict`- como cualquier otro, no el
        # «ya está liberado» genérico de antes del reordenamiento.
        assert "Otra persona ya movió este caso: ahora está «Liberado»" in (
            motivos[liberado.clearance.id])
        assert "revocada" in motivos[revocado.clearance.id]
        assert "no tiene capturada la donación" in motivos[sin_donacion.clearance.id]
        assert "No existe" in motivos[9_999_999]
        assert commits == [1]

        for esc in (a1, a2):
            assert esc.clearance.status == "awaiting_payment"
            assert esc.clearance.debt_amount == Decimal("0.00")
            assert esc.clearance.total_amount == DONACION
            assert len(_events(db_session, esc.process.id, "library_debt_registered")) == 1
        assert aviso.call_count == 2
        # Los omitidos no se tocaron.
        assert en_caja.clearance.total_amount == ADEUDO + DONACION
        assert revocado.clearance.status == "pending"
        assert sin_donacion.clearance.status == "pending"
        assert _library_events(db_session, revocado.process.id) == []

    def test_donacion_cero_libera_sin_cargo(self, db_session, nuevo, actores):
        a1 = nuevo(donation=Decimal("0.00"))
        a2 = nuevo(cohort=a1.cohort)

        with patch(NOTIFY):
            resultado = LibraryClearanceService.register_no_debt_bulk(
                db_session, [a1.clearance.id, a2.clearance.id], actores.biblioteca.id)

        assert resultado == {"done": 2, "skipped": []}
        for esc in (a1, a2):
            assert esc.clearance.status == "cleared"
            assert esc.clearance.cleared_via == "no_charge"
            assert len(_certs(db_session, esc.clearance.id)) == 1
            assert _fulfillment(db_session, esc.process.id, esc.req.id) is not None

    def test_lista_vacia_no_hace_nada(self, db_session, actores, monkeypatch):
        monkeypatch.setattr(db_session, "commit",
                            lambda: pytest.fail("sin ids no hay nada que commitear"))
        assert LibraryClearanceService.register_no_debt_bulk(
            db_session, [], actores.biblioteca.id) == {"done": 0, "skipped": []}

    def test_todo_omitido_no_escribe_nada(self, db_session, nuevo, actores):
        liberado = nuevo(status="cleared")
        resultado = LibraryClearanceService.register_no_debt_bulk(
            db_session, [liberado.clearance.id], actores.biblioteca.id)
        assert resultado["done"] == 0
        assert len(resultado["skipped"]) == 1
        assert _library_events(db_session, liberado.process.id) == []


# ---------------------------------------------------------------------------
# Registrar pago (Caja)
# ---------------------------------------------------------------------------
class TestRegisterPayment:
    def test_cobra_libera_emite_constancia_y_cumple_el_requisito(
            self, db_session, nuevo, actores, commits):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        commits.clear()

        with patch(NOTIFY) as aviso:
            fila = LibraryClearanceService.register_payment(
                db_session, esc.clearance.id, actores.caja.id, receipt_number="  R-555  ")

        assert fila.status == "cleared"
        assert fila.cleared_via == "payment"
        assert fila.paid_by_id == actores.caja.id
        assert fila.paid_at is not None
        assert fila.receipt_number == "R-555"
        assert fila.total_amount == Decimal("1100.00")    # el monto congelado, intacto
        assert commits == [1]

        certs = _certs(db_session, fila.id)
        assert len(certs) == 1 and certs[0].voided_at is None

        cumplido = _fulfillment(db_session, esc.process.id, esc.req.id)
        assert cumplido is not None
        assert cumplido.source == "system"
        assert cumplido.external_ref == f"library_clearance:{fila.id}"
        assert cumplido.checked_by_id == actores.caja.id

        evs = _events(db_session, esc.process.id, "library_payment_registered")
        assert len(evs) == 1
        assert evs[0].actor_id == actores.caja.id
        assert evs[0].payload["total"] == "1100.00"
        assert evs[0].payload["receipt"] == "R-555"
        assert evs[0].payload["certificate"] == certs[0].number

        assert aviso.call_args.kwargs["type"] == "LIBRARY_CLEARED"
        assert aviso.call_args.kwargs["title"] == "Tu no adeudo de biblioteca quedó liberado"

    def test_recibo_es_opcional_y_tiene_tope(self, db_session, nuevo, actores):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)

        with pytest.raises(ValueError):
            _pagar(db_session, esc, actores.caja, receipt="R" * 41)
        assert esc.clearance.status == "awaiting_payment"

        fila = _pagar(db_session, esc, actores.caja, receipt="   ")
        assert fila.receipt_number is None

    def test_no_cobra_lo_que_biblioteca_no_ha_registrado(self, db_session, nuevo, actores):
        esc = nuevo()
        with pytest.raises(ValueError) as exc:
            _pagar(db_session, esc, actores.caja)
        assert "todavía no registra" in str(exc.value)
        assert esc.clearance.status == "pending"

    def test_no_cobra_dos_veces(self, db_session, nuevo, actores):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        _pagar(db_session, esc, actores.caja, receipt="R-1")

        with pytest.raises(ValueError) as exc:
            _pagar(db_session, esc, actores.caja2, receipt="R-2")

        assert str(exc.value) == "Este pago ya está registrado."
        assert esc.clearance.receipt_number == "R-1"
        assert len(_certs(db_session, esc.clearance.id)) == 1
        assert len(_events(db_session, esc.process.id, "library_payment_registered")) == 1

    def test_liberado_sin_pago_no_se_cobra(self, db_session, nuevo, actores):
        esc = nuevo(status="cleared")
        with pytest.raises(ValueError) as exc:
            _pagar(db_session, esc, actores.caja)
        assert "no hay nada que cobrar" in str(exc.value)

    def test_sin_requisito_automatico_libera_igual(self, db_session, nuevo, actores):
        esc = nuevo(requisito=False)
        _a_caja(db_session, esc, actores.biblioteca)
        fila = _pagar(db_session, esc, actores.caja)
        assert fila.status == "cleared"
        assert len(_certs(db_session, fila.id)) == 1
        assert [f for f in _fulfillments_of(db_session, esc.process.id)
                if f.requirement_code == "library_clearance"] == []

    def test_proceso_en_pausa_si_cobra(self, db_session, nuevo, actores):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        esc.process.status = "on_hold"
        db_session.flush()
        assert _pagar(db_session, esc, actores.caja).status == "cleared"

    def test_proceso_revocado_no_cobra(self, db_session, nuevo, actores):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        esc.process.status = "cancelled"
        db_session.flush()

        with pytest.raises(ValueError) as exc:
            _pagar(db_session, esc, actores.caja)

        assert "revocada" in str(exc.value)
        assert esc.clearance.status == "awaiting_payment"
        assert _certs(db_session, esc.clearance.id) == []

    def test_id_inexistente(self, db_session, actores):
        with pytest.raises(LookupError):
            LibraryClearanceService.register_payment(
                db_session, 9_999_999, actores.caja.id, receipt_number=None)

    def test_expected_total_arriba_del_tope_de_monto_se_acepta_si_coincide_ruling_r9(
            self, db_session, nuevo, actores):
        """Ruling R9 (spec §4.8): un adeudo al tope (`AMOUNT_MAX`) más la
        donación da un total legítimo arriba de ese mismo tope; antes de esta
        tarea `_check_expected` reusaba `_check_amount` (que SÍ aplica
        `AMOUNT_MAX`) y rechazaba ese `expected_total`, aunque coincidiera con
        la fila -- nunca se podía cobrar. Ahora solo exige forma mínima
        (finito y >= 0)."""
        esc = nuevo(donation=Decimal("900.00"))
        fila = _a_caja(db_session, esc, actores.biblioteca, debt=AMOUNT_MAX)
        assert fila.total_amount == AMOUNT_MAX + Decimal("900.00")
        assert fila.total_amount > AMOUNT_MAX

        with patch(NOTIFY):
            pagada = LibraryClearanceService.register_payment(
                db_session, esc.clearance.id, actores.caja.id,
                expected_total=fila.total_amount)

        assert pagada.status == "cleared"
        assert pagada.total_amount == AMOUNT_MAX + Decimal("900.00")

    @pytest.mark.parametrize("expected_total", [Decimal("-1"), Decimal("NaN")])
    def test_expected_total_sigue_exigiendo_forma_minima(
            self, db_session, nuevo, actores, expected_total):
        """R9 relaja el TOPE, no la forma: negativo o no finito sigue siendo
        `ValueError`, nunca un 500 ni un cobro silencioso."""
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)

        with pytest.raises(ValueError):
            LibraryClearanceService.register_payment(
                db_session, esc.clearance.id, actores.caja.id,
                expected_total=expected_total)
        assert esc.clearance.status == "awaiting_payment"


# ---------------------------------------------------------------------------
# Constancia previa (D9) — Review Focus #7
# ---------------------------------------------------------------------------
class TestRegisterPrior:
    def test_desde_pending_libera_y_emite_el_folio_del_semestre_anterior(
            self, db_session, nuevo, actores, reloj, commits):
        esc = nuevo()

        with patch(NOTIFY) as aviso:
            fila = LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.biblioteca.id,
                issued_on=reloj - timedelta(days=30), note="  Trae su papel  ",
                by="library")

        assert fila.status == "cleared"
        assert fila.cleared_via == "prior"
        assert fila.prior_issued_on == reloj - timedelta(days=30)
        assert fila.prior_note == "Trae su papel"
        assert fila.prior_by_id == actores.biblioteca.id
        assert commits == [1]

        # Spec folios 2026-10-05 §3.3: la previa TAMBIEN folia, en el semestre
        # anterior al del registro (HOY_FIJO = 2026-10-01 -> 2026A).
        (cert,) = _certs(db_session, fila.id)
        assert cert.kind == "library_clearance"
        assert re.fullmatch(r"BIB-2026A-\d{4}", cert.number), cert.number
        assert cert.voided_at is None
        assert cert.issued_by_id == actores.biblioteca.id
        assert cert.process_id == esc.process.id
        cumplido = _fulfillment(db_session, esc.process.id, esc.req.id)
        assert cumplido is not None
        assert cumplido.external_ref == f"library_clearance:{fila.id}"

        evs = _events(db_session, esc.process.id, "library_prior_registered")
        assert len(evs) == 1
        assert evs[0].payload["by"] == "library"
        assert evs[0].payload["issued_on"] == (reloj - timedelta(days=30)).isoformat()
        assert evs[0].payload["from_status"] == "pending"

        assert aviso.call_args.kwargs["type"] == "LIBRARY_CLEARED"
        assert "constancia" in aviso.call_args.kwargs["body"]

    def test_desde_en_caja_conserva_los_montos(self, db_session, nuevo, actores, reloj):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)

        with patch(NOTIFY):
            fila = LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.se.id,
                issued_on=reloj, note=None, by="school_services")

        assert fila.cleared_via == "prior"
        assert fila.total_amount == Decimal("1100.00")
        assert _events(db_session, esc.process.id,
                       "library_prior_registered")[0].payload["from_status"] == "awaiting_payment"

    @pytest.mark.parametrize("dias, valida", [
        (0, True),
        (PRIOR_VALIDITY_DAYS, True),           # exactamente 365 días: vigente
        (PRIOR_VALIDITY_DAYS + 1, False),      # 366: vencida
        (-1, False),                           # futura
    ])
    def test_vigencia(self, db_session, nuevo, actores, reloj, dias, valida):
        esc = nuevo()
        fecha = reloj - timedelta(days=dias)
        if valida:
            with patch(NOTIFY):
                fila = LibraryClearanceService.register_prior(
                    db_session, esc.clearance.id, actores.biblioteca.id,
                    issued_on=fecha, note=None, by="library")
            assert fila.cleared_via == "prior"
            return

        with pytest.raises(ValueError) as exc:
            LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.biblioteca.id,
                issued_on=fecha, note=None, by="library")
        if dias > 0:
            assert str(exc.value) == "La constancia venció: tiene más de un año."
        else:
            assert "futura" in str(exc.value)
        assert esc.clearance.status == "pending"
        assert _library_events(db_session, esc.process.id) == []

    def test_sin_fecha(self, db_session, nuevo, actores, reloj):
        esc = nuevo()
        with pytest.raises(ValueError):
            LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.biblioteca.id,
                issued_on=None, note=None, by="library")
        assert esc.clearance.status == "pending"

    @pytest.mark.parametrize("by", ["library", "school_services", "import"])
    def test_el_origen_va_al_payload(self, db_session, nuevo, actores, reloj, by):
        esc = nuevo()
        with patch(NOTIFY):
            LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.se.id,
                issued_on=reloj, note=None, by=by)
        assert _events(db_session, esc.process.id,
                       "library_prior_registered")[0].payload["by"] == by

    def test_origen_desconocido(self, db_session, nuevo, actores, reloj):
        esc = nuevo()
        with pytest.raises(ValueError):
            LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.se.id,
                issued_on=reloj, note=None, by="caja")
        assert esc.clearance.status == "pending"

    def test_commit_false_deja_la_transaccion_al_llamador(
            self, db_session, nuevo, reloj, monkeypatch):
        """La usa `PriorClearanceService.apply_pending` dentro de `import_rows`
        (Tarea 6): sin actor y sin commit propio."""
        esc = nuevo()
        monkeypatch.setattr(db_session, "commit",
                            lambda: pytest.fail("commit=False no debe commitear"))

        with patch(NOTIFY):
            fila = LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, None,
                issued_on=reloj, note=None, by="import", commit=False)

        assert fila.status == "cleared"
        assert fila.prior_by_id is None
        ev = _events(db_session, esc.process.id, "library_prior_registered")[0]
        assert ev.actor_id is None

    def test_ya_liberado(self, db_session, nuevo, actores, reloj):
        esc = nuevo(status="cleared")
        with pytest.raises(ValueError) as exc:
            LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.biblioteca.id,
                issued_on=reloj, note=None, by="library")
        assert "ya está liberado" in str(exc.value)

    def test_proceso_revocado(self, db_session, nuevo, actores, reloj):
        esc = nuevo(process_status="cancelled")
        with pytest.raises(ValueError):
            LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.biblioteca.id,
                issued_on=reloj, note=None, by="library")
        assert esc.clearance.status == "pending"


# ---------------------------------------------------------------------------
# Revertir pago (Caja)
# ---------------------------------------------------------------------------
class TestRevertPayment:
    def test_regresa_a_caja_anula_la_constancia_y_descumple(
            self, db_session, nuevo, actores, commits):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        _pagar(db_session, esc, actores.caja, receipt="R-9")
        commits.clear()

        with patch(NOTIFY) as aviso:
            fila = LibraryClearanceService.revert_payment(
                db_session, esc.clearance.id, actores.caja.id, "  Se cobró a otro  ")

        assert fila.status == "awaiting_payment"
        assert fila.cleared_via is None
        assert fila.paid_by_id is None and fila.paid_at is None
        assert fila.receipt_number is None
        assert fila.total_amount == Decimal("1100.00")   # sigue debiendo lo mismo
        assert commits == [1]

        cert = _certs(db_session, fila.id)[0]
        assert cert.voided_at is not None
        assert cert.void_reason == "Se cobró a otro"
        assert _fulfillment(db_session, esc.process.id, esc.req.id) is None

        ev = _events(db_session, esc.process.id, "library_payment_reverted")[0]
        assert ev.payload["reason"] == "Se cobró a otro"
        assert ev.payload["receipt"] == "R-9"
        assert ev.payload["certificate"] == cert.number

        assert aviso.call_args.kwargs["type"] == "LIBRARY_REVERTED"
        assert aviso.call_args.kwargs["body"] == "Se cobró a otro"

    def test_volver_a_cobrar_emite_otra_constancia(self, db_session, nuevo, actores):
        """§5.5: a lo más UNA vigente por origen; el folio anulado no se reabre."""
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        _pagar(db_session, esc, actores.caja)
        with patch(NOTIFY):
            LibraryClearanceService.revert_payment(
                db_session, esc.clearance.id, actores.caja.id, "Error de captura")
        _pagar(db_session, esc, actores.caja)

        certs = _certs(db_session, esc.clearance.id)
        assert len(certs) == 2
        assert certs[0].number != certs[1].number
        assert certs[0].voided_at is not None
        assert [c for c in certs if c.voided_at is None] == [certs[1]]
        assert _fulfillment(db_session, esc.process.id, esc.req.id) is not None

    def test_no_revierte_con_la_fase_2_aprobada(self, db_session, nuevo, actores):
        esc = nuevo(phase=2)
        _a_caja(db_session, esc, actores.biblioteca)
        _pagar(db_session, esc, actores.caja)
        _fase2(db_session, esc.process, "approved")

        with pytest.raises(ValueError) as exc:
            LibraryClearanceService.revert_payment(
                db_session, esc.clearance.id, actores.caja.id, "Motivo")

        assert "fase 2" in str(exc.value)
        assert esc.clearance.status == "cleared"
        assert _certs(db_session, esc.clearance.id)[0].voided_at is None

    @pytest.mark.parametrize("estado", ["pending", "cleared"])
    def test_solo_se_revierte_un_pago(self, db_session, nuevo, actores, estado):
        esc = nuevo(status=estado)          # cleared del fixture = legacy
        with pytest.raises(ValueError) as exc:
            LibraryClearanceService.revert_payment(
                db_session, esc.clearance.id, actores.caja.id, "Motivo")
        assert "pago registrado" in str(exc.value)

    @pytest.mark.parametrize("motivo", ["", "   ", None, "x" * (REASON_MAX + 1)])
    def test_motivo_invalido(self, db_session, nuevo, actores, motivo):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        _pagar(db_session, esc, actores.caja)
        with pytest.raises(ValueError):
            LibraryClearanceService.revert_payment(
                db_session, esc.clearance.id, actores.caja.id, motivo)
        assert esc.clearance.status == "cleared"

    def test_proceso_revocado(self, db_session, nuevo, actores):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        _pagar(db_session, esc, actores.caja)
        esc.process.status = "cancelled"
        db_session.flush()
        with pytest.raises(ValueError):
            LibraryClearanceService.revert_payment(
                db_session, esc.clearance.id, actores.caja.id, "Motivo")
        assert esc.clearance.status == "cleared"


# ---------------------------------------------------------------------------
# Revertir sin cargo / legado (Biblioteca)
# ---------------------------------------------------------------------------
class TestRevertClearance:
    def test_sin_cargo_vuelve_a_pending_anula_y_descumple(
            self, db_session, nuevo, actores, commits):
        esc = nuevo(donation=Decimal("0.00"))
        _a_caja(db_session, esc, actores.biblioteca, debt=Decimal("0"), note="Revisado")
        commits.clear()

        with patch(NOTIFY) as aviso:
            fila = LibraryClearanceService.revert_clearance(
                db_session, esc.clearance.id, actores.biblioteca.id, "Sí debía un libro")

        assert fila.status == "pending"
        assert fila.cleared_via is None
        # De vuelta a la forma de recién abierta: Biblioteca lo vuelve a registrar.
        assert fila.debt_amount is None and fila.total_amount is None
        assert fila.library_note is None and fila.library_by_id is None
        assert commits == [1]

        assert _certs(db_session, fila.id)[0].voided_at is not None
        assert _fulfillment(db_session, esc.process.id, esc.req.id) is None
        ev = _events(db_session, esc.process.id, "library_clearance_reverted")[0]
        assert ev.payload["via"] == "no_charge"
        assert ev.payload["reason"] == "Sí debía un libro"
        assert aviso.call_args.kwargs["type"] == "LIBRARY_REVERTED"

    def test_legado_vuelve_a_pending_y_quita_el_cumplimiento(
            self, db_session, nuevo, actores, make_user):
        """El legado ya cumplía el requisito marcado A MANO por un encargado."""
        from itcj2.apps.titulatec.services.requirement_service import RequirementService

        esc = nuevo(status="cleared")                     # legacy
        encargado = make_user(first_name="ENCARGADO")
        RequirementService.fulfill(db_session, esc.process.id, esc.req.id,
                                   source="officer", checked_by_id=encargado.id,
                                   commit=False)

        with patch(NOTIFY):
            fila = LibraryClearanceService.revert_clearance(
                db_session, esc.clearance.id, actores.biblioteca.id, "Debe libros")

        assert fila.status == "pending"
        assert _certs(db_session, fila.id) == []          # el legado nunca tuvo
        assert _fulfillment(db_session, esc.process.id, esc.req.id) is None
        assert _events(db_session, esc.process.id,
                       "library_clearance_reverted")[0].payload["via"] == "legacy"

    @pytest.mark.parametrize("via, fragmento", [
        ("payment", "Caja"),
        ("prior", "Deshacer"),
        (None, "Biblioteca"),          # anomalía: liberado sin `cleared_via`
    ])
    def test_pago_y_previa_tienen_su_propio_camino(
            self, db_session, nuevo, actores, via, fragmento):
        esc = nuevo(status="cleared", cleared_via=via)
        with pytest.raises(ValueError) as exc:
            LibraryClearanceService.revert_clearance(
                db_session, esc.clearance.id, actores.biblioteca.id, "Motivo")
        assert fragmento in str(exc.value)
        assert esc.clearance.status == "cleared"

    def test_no_revierte_con_la_fase_2_aprobada(self, db_session, nuevo, actores):
        esc = nuevo(status="cleared", phase=2)
        _fase2(db_session, esc.process, "approved")
        with pytest.raises(ValueError) as exc:
            LibraryClearanceService.revert_clearance(
                db_session, esc.clearance.id, actores.biblioteca.id, "Motivo")
        assert "fase 2" in str(exc.value)
        assert esc.clearance.status == "cleared"

    def test_nada_que_revertir(self, db_session, nuevo, actores):
        esc = nuevo()
        with pytest.raises(ValueError) as exc:
            LibraryClearanceService.revert_clearance(
                db_session, esc.clearance.id, actores.biblioteca.id, "Motivo")
        assert "no está liberado" in str(exc.value)


# ---------------------------------------------------------------------------
# Folio de la constancia previa (spec folios 2026-10-05 §3.3)
# ---------------------------------------------------------------------------
def _reloj_en(monkeypatch, cuando):
    """`db_now()` del service fijo en `cuando`. Los años sintéticos (2090+) son
    a propósito: la BD de dev es COMPARTIDA y ya trae contadores reales de 2026."""
    monkeypatch.setattr(f"{SVC}.db_now", lambda: cuando)
    return cuando.date()


class TestRegisterPriorFolio:
    @pytest.mark.parametrize("cuando, semestre", [
        (datetime(2091, 10, 5, 10, 0), "2091A"),      # B de Y -> A de Y
        (datetime(2091, 7, 1, 8, 0), "2091A"),        # primer día de B
        (datetime(2092, 2, 10, 10, 0), "2091B"),      # A de Y -> B de Y-1
        (datetime(2091, 6, 30, 23, 0), "2090B"),      # último día de A
    ])
    def test_el_semestre_es_el_anterior_al_del_registro(
            self, db_session, nuevo, actores, monkeypatch, cuando, semestre):
        hoy = _reloj_en(monkeypatch, cuando)
        esc = nuevo()

        with patch(NOTIFY):
            fila = LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.biblioteca.id,
                issued_on=hoy, note=None, by="library")

        (cert,) = _certs(db_session, fila.id)
        assert re.fullmatch(rf"BIB-{semestre}-\d{{4}}", cert.number), cert.number
        assert cert.kind == "library_clearance"
        assert cert.source_ref == f"library_clearance:{fila.id}"
        assert cert.issued_by_id == actores.biblioteca.id
        assert cert.voided_at is None

    @pytest.mark.parametrize("origen", ["pending", "awaiting_payment"])
    def test_emite_desde_pending_y_desde_en_caja(
            self, db_session, nuevo, actores, monkeypatch, origen):
        hoy = _reloj_en(monkeypatch, datetime(2091, 10, 5, 10, 0))
        esc = nuevo()
        if origen == "awaiting_payment":
            _a_caja(db_session, esc, actores.biblioteca)
        assert _certs(db_session, esc.clearance.id) == []

        with patch(NOTIFY):
            fila = LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.se.id,
                issued_on=hoy, note=None, by="school_services")

        (cert,) = _certs(db_session, fila.id)
        assert cert.number.startswith("BIB-2091A-")
        assert cert.issued_by_id == actores.se.id
        assert cert.control_number == esc.student.control_number

    def test_commit_false_tambien_emite_sin_commitear(
            self, db_session, nuevo, monkeypatch):
        """El camino de `import_rows`/`apply_pending`: sin actor y sin commit,
        pero con folio (queda en la transacción del llamador)."""
        hoy = _reloj_en(monkeypatch, datetime(2091, 10, 5, 10, 0))
        esc = nuevo()
        monkeypatch.setattr(db_session, "commit",
                            lambda: pytest.fail("commit=False no debe commitear"))

        with patch(NOTIFY):
            fila = LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, None,
                issued_on=hoy, note=None, by="import", commit=False)

        (cert,) = _certs(db_session, fila.id)
        assert cert.number.startswith("BIB-2091A-")
        assert cert.issued_by_id is None              # importación: sin emisor
        assert cert.voided_at is None

    def test_un_rechazo_no_deja_folio(self, db_session, nuevo, actores, monkeypatch):
        """Toda la validación va ANTES de emitir: una previa vencida no deja
        constancia."""
        hoy = _reloj_en(monkeypatch, datetime(2091, 10, 5, 10, 0))
        esc = nuevo()

        with pytest.raises(ValueError):
            LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.biblioteca.id,
                issued_on=hoy - timedelta(days=PRIOR_VALIDITY_DAYS + 1),
                note=None, by="library")

        assert _certs(db_session, esc.clearance.id) == []

    def test_dos_previas_consecutivas_en_el_mismo_semestre(
            self, db_session, nuevo, actores, monkeypatch):
        hoy = _reloj_en(monkeypatch, datetime(2091, 10, 5, 10, 0))
        a, b = nuevo(), nuevo()

        with patch(NOTIFY):
            for esc in (a, b):
                LibraryClearanceService.register_prior(
                    db_session, esc.clearance.id, actores.biblioteca.id,
                    issued_on=hoy, note=None, by="library")

        na = _certs(db_session, a.clearance.id)[0].number
        nb = _certs(db_session, b.clearance.id)[0].number
        assert na.startswith("BIB-2091A-") and nb.startswith("BIB-2091A-")
        assert int(nb.rsplit("-", 1)[1]) == int(na.rsplit("-", 1)[1]) + 1


# ---------------------------------------------------------------------------
# Deshacer constancia previa (Biblioteca o SE)
# ---------------------------------------------------------------------------
class TestUndoPrior:
    def test_deshace_la_previa(self, db_session, nuevo, actores, reloj, commits):
        esc = nuevo()
        with patch(NOTIFY):
            LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.se.id,
                issued_on=reloj, note="Papel", by="school_services")
        commits.clear()

        with patch(NOTIFY) as aviso:
            fila = LibraryClearanceService.undo_prior(
                db_session, esc.clearance.id, actores.se.id, "No era de este año")

        assert fila.status == "pending"
        assert fila.cleared_via is None
        assert fila.prior_issued_on is None and fila.prior_note is None
        assert fila.prior_by_id is None
        assert commits == [1]
        assert _fulfillment(db_session, esc.process.id, esc.req.id) is None
        ev = _events(db_session, esc.process.id, "library_prior_undone")[0]
        assert ev.payload["reason"] == "No era de este año"
        assert ev.payload["issued_on"] == reloj.isoformat()
        assert aviso.call_args.kwargs["type"] == "LIBRARY_REVERTED"
        assert aviso.call_args.kwargs["body"] == "No era de este año"

    def test_anula_el_folio_y_el_payload_trae_su_numero(
            self, db_session, nuevo, actores, monkeypatch):
        hoy = _reloj_en(monkeypatch, datetime(2091, 10, 5, 10, 0))
        esc = nuevo()
        with patch(NOTIFY):
            LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.biblioteca.id,
                issued_on=hoy, note=None, by="library")
        (cert,) = _certs(db_session, esc.clearance.id)
        assert cert.voided_at is None
        numero = cert.number

        with patch(NOTIFY):
            fila = LibraryClearanceService.undo_prior(
                db_session, esc.clearance.id, actores.se.id, "No era de este año")

        assert fila.status == "pending"
        (cert,) = _certs(db_session, esc.clearance.id)
        assert cert.number == numero                     # el folio no se borra
        assert cert.voided_at is not None
        assert cert.voided_by_id == actores.se.id
        assert cert.void_reason == "No era de este año"
        ev = _events(db_session, esc.process.id, "library_prior_undone")[0]
        assert ev.payload["certificate"] == numero
        assert ev.payload["reason"] == "No era de este año"

    def test_volver_a_registrar_emite_un_folio_nuevo_y_distinto(
            self, db_session, nuevo, actores, monkeypatch):
        hoy = _reloj_en(monkeypatch, datetime(2091, 10, 5, 10, 0))
        esc = nuevo()
        with patch(NOTIFY):
            LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.biblioteca.id,
                issued_on=hoy, note=None, by="library")
            LibraryClearanceService.undo_prior(
                db_session, esc.clearance.id, actores.biblioteca.id, "Error de captura")
            LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.biblioteca.id,
                issued_on=hoy, note=None, by="library")

        certs = _certs(db_session, esc.clearance.id)
        assert len(certs) == 2
        primero, segundo = certs
        assert primero.voided_at is not None
        assert segundo.voided_at is None
        assert segundo.number != primero.number          # nunca se reutiliza
        assert _vigente(db_session, esc.clearance.id).id == segundo.id

    def test_una_previa_sin_folio_se_deshace_con_certificate_none(
            self, db_session, nuevo, actores, reloj):
        """Una previa de ANTES de este código (o aún sin backfill) no trae
        folio: deshacer no truena, no anula nada y el payload lo dice."""
        esc = nuevo(status="cleared", cleared_via="prior", prior_issued_on=reloj)
        assert _certs(db_session, esc.clearance.id) == []

        with patch(NOTIFY):
            fila = LibraryClearanceService.undo_prior(
                db_session, esc.clearance.id, actores.se.id, "Motivo")

        assert fila.status == "pending"
        assert _certs(db_session, esc.clearance.id) == []
        ev = _events(db_session, esc.process.id, "library_prior_undone")[0]
        assert "certificate" in ev.payload and ev.payload["certificate"] is None

    @pytest.mark.parametrize("via", ["no_charge", "payment", "legacy"])
    def test_solo_previas(self, db_session, nuevo, actores, via):
        esc = nuevo(status="cleared", cleared_via=via)
        with pytest.raises(ValueError) as exc:
            LibraryClearanceService.undo_prior(
                db_session, esc.clearance.id, actores.se.id, "Motivo")
        assert "constancia previa" in str(exc.value)

    def test_no_con_la_fase_2_aprobada(self, db_session, nuevo, actores):
        esc = nuevo(status="cleared", cleared_via="prior", phase=2,
                    prior_issued_on=date(2026, 9, 1))
        _fase2(db_session, esc.process, "approved")
        with pytest.raises(ValueError):
            LibraryClearanceService.undo_prior(
                db_session, esc.clearance.id, actores.se.id, "Motivo")
        assert esc.clearance.status == "cleared"


# ---------------------------------------------------------------------------
# can_revert
# ---------------------------------------------------------------------------
class TestCanRevert:
    @pytest.mark.parametrize("estado", ["active", "on_hold"])
    def test_liberado_con_proceso_admitido_y_fase_2_abierta(
            self, db_session, nuevo, estado):
        esc = nuevo(status="cleared", process_status=estado)
        assert LibraryClearanceService.can_revert(db_session, esc.clearance) is True

    def test_false_con_la_fase_2_aprobada(self, db_session, nuevo):
        esc = nuevo(status="cleared", phase=2)
        _fase2(db_session, esc.process, "approved")
        assert LibraryClearanceService.can_revert(db_session, esc.clearance) is False

    @pytest.mark.parametrize("estado", ["cancelled", "completed"])
    def test_false_con_el_proceso_revocado_o_terminado(self, db_session, nuevo, estado):
        esc = nuevo(status="cleared", process_status=estado)
        assert LibraryClearanceService.can_revert(db_session, esc.clearance) is False

    def test_false_si_no_esta_liberado(self, db_session, nuevo):
        esc = nuevo()
        assert LibraryClearanceService.can_revert(db_session, esc.clearance) is False


# ---------------------------------------------------------------------------
# for_process_locked (rutas de SE, por `{process_id}`)
# ---------------------------------------------------------------------------
class TestForProcessLocked:
    def test_devuelve_la_fila_bloqueada(self, db_session, nuevo):
        esc = nuevo(status="awaiting_payment", debt_amount=ADEUDO,
                    donation_amount=DONACION, total_amount=ADEUDO + DONACION)
        with _sql(db_session) as sentencias:
            fila = LibraryClearanceService.for_process_locked(db_session, esc.process.id)
        assert fila.id == esc.clearance.id
        assert _pide_for_update(sentencias)

    def test_abre_la_fila_si_falta(self, db_session, nuevo):
        """Procesos creados en el blue/green sin fila: SE puede operar igual."""
        esc = nuevo(status=None)
        fila = LibraryClearanceService.for_process_locked(db_session, esc.process.id)
        assert fila.process_id == esc.process.id
        assert fila.status == "pending"
        assert LibraryClearanceService.for_process_locked(
            db_session, esc.process.id).id == fila.id

    def test_proceso_inexistente(self, db_session):
        with pytest.raises(LookupError):
            LibraryClearanceService.for_process_locked(db_session, 9_999_999)


# ---------------------------------------------------------------------------
# Dos personas sobre la misma fila (Review Focus #1)
# ---------------------------------------------------------------------------
def _otra_transaccion(db, clearance_id, **cols):
    """Lo que OTRA transacción ya commiteó cuando esta obtiene el lock: un UPDATE
    crudo que el mapa de identidad del ORM no ve (la foto vieja sigue en memoria)."""
    asignaciones = ", ".join(f"{col} = :{col}" for col in cols)
    db.execute(text(f"UPDATE titulatec_library_clearances SET {asignaciones} "
                    "WHERE id = :clearance_id"),
               {**cols, "clearance_id": clearance_id})


class TestBloqueo:
    @pytest.mark.parametrize("transicion", [
        "register", "register_payment", "register_prior", "revert_payment",
        "revert_clearance", "undo_prior", "register_no_debt_bulk",
    ])
    def test_cada_transicion_pide_for_update(
            self, db_session, nuevo, actores, reloj, transicion):
        esc = nuevo()
        llamadas = {
            "register": lambda: LibraryClearanceService.register(
                db_session, esc.clearance.id, actores.biblioteca.id,
                debt_amount=ADEUDO, note=None),
            "register_payment": lambda: LibraryClearanceService.register_payment(
                db_session, esc.clearance.id, actores.caja.id, receipt_number=None),
            "register_prior": lambda: LibraryClearanceService.register_prior(
                db_session, esc.clearance.id, actores.biblioteca.id,
                issued_on=reloj, note=None, by="library"),
            "revert_payment": lambda: LibraryClearanceService.revert_payment(
                db_session, esc.clearance.id, actores.caja.id, "Motivo"),
            "revert_clearance": lambda: LibraryClearanceService.revert_clearance(
                db_session, esc.clearance.id, actores.biblioteca.id, "Motivo"),
            "undo_prior": lambda: LibraryClearanceService.undo_prior(
                db_session, esc.clearance.id, actores.se.id, "Motivo"),
            "register_no_debt_bulk": lambda: LibraryClearanceService.register_no_debt_bulk(
                db_session, [esc.clearance.id], actores.biblioteca.id),
        }
        with _sql(db_session) as sentencias, patch(NOTIFY):
            try:
                llamadas[transicion]()
            except ValueError:
                pass          # el estado puede no admitirla: el lock va ANTES de validar
        assert _pide_for_update(sentencias), f"{transicion} no pidió FOR UPDATE"

    def test_dos_cobros_el_segundo_ve_el_pago_y_no_cobra_doble(
            self, db_session, nuevo, actores):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        _otra_transaccion(db_session, esc.clearance.id, status="cleared",
                          cleared_via="payment", receipt_number="R-OTRA",
                          paid_by_id=actores.caja2.id, paid_at=datetime(2026, 10, 1, 9, 0))
        assert esc.clearance.status == "awaiting_payment"    # la foto vieja

        with pytest.raises(ValueError) as exc:
            _pagar(db_session, esc, actores.caja, receipt="R-MIA")

        assert str(exc.value) == "Este pago ya está registrado."
        assert esc.clearance.receipt_number == "R-OTRA"       # releída, no pisada
        assert _certs(db_session, esc.clearance.id) == []
        assert _events(db_session, esc.process.id, "library_payment_registered") == []

    def test_caja_cobra_primero_y_biblioteca_ya_no_corrige(
            self, db_session, nuevo, actores):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        _otra_transaccion(db_session, esc.clearance.id, status="cleared",
                          cleared_via="payment", paid_by_id=actores.caja.id,
                          paid_at=datetime(2026, 10, 1, 9, 0))

        with pytest.raises(ValueError) as exc:
            _a_caja(db_session, esc, actores.biblioteca, debt=Decimal("900.00"))

        assert "ya está liberado" in str(exc.value)
        assert esc.clearance.total_amount == Decimal("1100.00")
        assert _events(db_session, esc.process.id, "library_amount_corrected") == []

    def test_biblioteca_corrige_primero_y_caja_no_cobra_el_monto_viejo(
            self, db_session, nuevo, actores):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        _otra_transaccion(db_session, esc.clearance.id, debt_amount=Decimal("500.00"),
                          total_amount=Decimal("1300.00"))

        # Caja confirmó «Registrar pago de $1,100.00»: el monto ya no es ese.
        with pytest.raises(ValueError) as exc, patch(NOTIFY):
            LibraryClearanceService.register_payment(
                db_session, esc.clearance.id, actores.caja.id, receipt_number=None,
                expected_total=Decimal("1100.00"))
        assert "$1,300.00" in str(exc.value)
        assert esc.clearance.status == "awaiting_payment"

        # Sin el monto esperado, cobra el VIGENTE (releído tras el lock), nunca el viejo.
        _pagar(db_session, esc, actores.caja)
        ev = _events(db_session, esc.process.id, "library_payment_registered")[0]
        assert ev.payload["total"] == "1300.00"

    def test_dos_de_biblioteca_registran_el_mismo_caso(self, db_session, nuevo, actores):
        """FIFO: los dos ven arriba la misma fila. El segundo no CORRIGE sin
        querer lo que el primero acaba de registrar."""
        esc = nuevo()
        _otra_transaccion(db_session, esc.clearance.id, status="awaiting_payment",
                          debt_amount=ADEUDO, donation_amount=DONACION,
                          total_amount=ADEUDO + DONACION, library_by_id=actores.biblioteca.id,
                          library_at=datetime(2026, 10, 1, 9, 0),
                          ready_at=datetime(2026, 10, 1, 9, 0))

        with pytest.raises(ValueError) as exc, patch(NOTIFY):
            LibraryClearanceService.register(
                db_session, esc.clearance.id, actores.biblioteca2.id,
                debt_amount=Decimal("0"), note=None, expected_status="pending")

        assert "En caja" in str(exc.value)
        assert esc.clearance.total_amount == ADEUDO + DONACION     # no se pisó
        assert esc.clearance.library_by_id == actores.biblioteca.id

    def test_dos_correcciones_la_segunda_ve_el_monto_nuevo(self, db_session, nuevo, actores):
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        _otra_transaccion(db_session, esc.clearance.id, debt_amount=Decimal("500.00"),
                          total_amount=Decimal("1300.00"))

        with pytest.raises(ValueError) as exc, patch(NOTIFY):
            LibraryClearanceService.register(
                db_session, esc.clearance.id, actores.biblioteca2.id,
                debt_amount=Decimal("100.00"), note=None,
                expected_status="awaiting_payment", expected_total=Decimal("1100.00"))

        assert "$1,300.00" in str(exc.value)
        assert esc.clearance.debt_amount == Decimal("500.00")

    def test_el_choque_optimista_es_clearance_conflict(self, db_session, nuevo, actores):
        """Ruling R24 (M1): el choque de `expected_status`/`expected_total` es
        una excepción PROPIA -sigue siendo `ValueError` para todo llamador
        viejo- para que Biblioteca y Caja re-pinten la bandeja (200 +
        aviso) en vez de un 400 sin swap. Un total mal formado NO es choque:
        sigue siendo un `ValueError` cualquiera (400)."""
        from itcj2.apps.titulatec.services.library_clearance_service import (
            ClearanceConflict,
        )

        assert issubclass(ClearanceConflict, ValueError)
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)

        with pytest.raises(ClearanceConflict, match="Otra persona ya movió este caso"), \
                patch(NOTIFY):
            LibraryClearanceService.register(
                db_session, esc.clearance.id, actores.biblioteca2.id,
                debt_amount=Decimal("0"), expected_status="pending")
        with pytest.raises(ClearanceConflict, match=r"ahora es \$1,100\.00"), patch(NOTIFY):
            LibraryClearanceService.register_payment(
                db_session, esc.clearance.id, actores.caja.id,
                expected_total=Decimal("999.00"))
        with pytest.raises(ValueError) as basura, patch(NOTIFY):
            LibraryClearanceService.register_payment(
                db_session, esc.clearance.id, actores.caja.id,
                expected_total=Decimal("NaN"))
        assert not isinstance(basura.value, ClearanceConflict)
        assert esc.clearance.status == "awaiting_payment"

    def test_el_lote_ve_el_estado_nuevo(self, db_session, nuevo, actores):
        esc = nuevo()
        _otra_transaccion(db_session, esc.clearance.id, status="cleared",
                          cleared_via="no_charge")
        resultado = LibraryClearanceService.register_no_debt_bulk(
            db_session, [esc.clearance.id], actores.biblioteca.id)
        assert resultado["done"] == 0
        # Ruling R30 #3 (M1 completo): `ClearanceConflict` -choque contra el
        # `expected_status="pending"` fijo del lote-, no el «ya está
        # liberado» genérico de antes del reordenamiento.
        assert "Otra persona ya movió este caso: ahora está «Liberado»" in (
            resultado["skipped"][0][1])


# ---------------------------------------------------------------------------
# Listas de las bandejas (§4.7 / §4.8)
# ---------------------------------------------------------------------------
@pytest.fixture()
def token():
    """Apellido único: aísla las filas de la prueba de las reales de dev."""
    return "BIB" + uuid.uuid4().hex[:10].upper()


class TestCounts:
    def test_las_cuatro_llaves_siempre(self, db_session):
        counts = LibraryClearanceService.counts_by_status(db_session)
        assert set(counts) == {"pending", "awaiting_payment", "observed", "cleared"}
        assert all(isinstance(v, int) and v >= 0 for v in counts.values())

    def test_con_q_cuenta_solo_lo_buscado_y_sin_revocadas_en_por_revisar(
            self, db_session, nuevo, token):
        base = nuevo(last_name=token)
        nuevo(cohort=base.cohort, last_name=token)
        nuevo(cohort=base.cohort, last_name=token, process_status="cancelled")
        nuevo(cohort=base.cohort, last_name=token, process_status="completed")
        nuevo(cohort=base.cohort, last_name=token, process_status="on_hold")
        nuevo(cohort=base.cohort, last_name=token, status="awaiting_payment",
              debt_amount=ADEUDO, donation_amount=DONACION, total_amount=ADEUDO + DONACION)
        nuevo(cohort=base.cohort, last_name=token, status="cleared")
        nuevo(cohort=base.cohort, last_name=token, status="cleared",
              process_status="cancelled")

        counts = LibraryClearanceService.counts_by_status(db_session, q=token)

        assert counts == {"pending": 3, "awaiting_payment": 1, "observed": 0, "cleared": 2}

    def test_sin_q_por_delta(self, db_session, nuevo):
        antes = LibraryClearanceService.counts_by_status(db_session)
        base = nuevo()
        nuevo(cohort=base.cohort, process_status="cancelled")
        nuevo(cohort=base.cohort, status="cleared")

        despues = LibraryClearanceService.counts_by_status(db_session)

        assert despues["pending"] - antes["pending"] == 1
        assert despues["cleared"] - antes["cleared"] == 1
        assert despues["awaiting_payment"] - antes["awaiting_payment"] == 0

    def test_por_cobrar_tambien_excluye_revocadas_y_terminadas_ruling_r9(
            self, db_session, nuevo, token):
        """Ruling R9 (spec §4.8): con `admitted_only=True` -lo que pide Caja,
        «Por cobrar»- el contador usa el MISMO filtro de admitidos que «Por
        revisar». Por omisión (`admitted_only=False`, lo que sigue pidiendo
        Biblioteca en «En caja») NO se aplica: un `awaiting_payment` con el
        proceso ya revocado sigue contando -su lista también lo sigue
        mostrando, con la píldora «Revocada» (Tarea 7)-, para que el contador
        nunca se desalinee de lo que la tabla pinta."""
        def _en_caja(cohort=None, **extra):
            return nuevo(cohort=cohort, last_name=token, status="awaiting_payment",
                         debt_amount=ADEUDO, donation_amount=DONACION,
                         total_amount=ADEUDO + DONACION, **extra)

        base = _en_caja()
        _en_caja(base.cohort, process_status="on_hold")       # admitido: sí cuenta
        revocado = _en_caja(base.cohort, process_status="cancelled")
        _en_caja(base.cohort, process_status="completed")     # terminado: NO cuenta con el flag

        sin_flag = LibraryClearanceService.counts_by_status(db_session, q=token)
        con_flag = LibraryClearanceService.counts_by_status(
            db_session, q=token, admitted_only=True)

        assert sin_flag["awaiting_payment"] == 4, "Biblioteca sigue contando TODO (default)"
        assert con_flag["awaiting_payment"] == 2, "Caja (admitted_only) descarta revocada/terminada"
        assert revocado.clearance.status == "awaiting_payment"    # no se tocó la fila


class TestListForInbox:
    def test_por_revisar_fifo_por_alta_y_sin_revocadas_ni_terminadas(
            self, db_session, nuevo, token):
        tercero = nuevo(last_name=token)
        primero = nuevo(cohort=tercero.cohort, last_name=token)
        segundo = nuevo(cohort=tercero.cohort, last_name=token, process_status="on_hold")
        nuevo(cohort=tercero.cohort, last_name=token, process_status="cancelled")
        nuevo(cohort=tercero.cohort, last_name=token, process_status="completed")
        # El orden es por la aceptación de la inscripción, no por id.
        tercero.process.created_at = datetime(2030, 1, 3, 9, 0)
        primero.process.created_at = datetime(2030, 1, 1, 9, 0)
        segundo.process.created_at = datetime(2030, 1, 2, 9, 0)
        db_session.flush()

        pagina = LibraryClearanceService.list_for_inbox(
            db_session, status="pending", q=token)
        filas = pagina.items

        assert pagina.has_next is False
        assert [f["id"] for f in filas] == [
            primero.clearance.id, segundo.clearance.id, tercero.clearance.id]

    def test_en_caja_fifo_por_ready_at(self, db_session, nuevo, token):
        def _en_caja(cohort, ready):
            return nuevo(cohort=cohort, last_name=token, status="awaiting_payment",
                         debt_amount=ADEUDO, donation_amount=DONACION,
                         total_amount=ADEUDO + DONACION, ready_at=ready)

        tarde = _en_caja(None, datetime(2030, 2, 3, 9, 0))
        temprano = _en_caja(tarde.cohort, datetime(2030, 2, 1, 9, 0))
        medio = _en_caja(tarde.cohort, datetime(2030, 2, 2, 9, 0))

        filas = LibraryClearanceService.list_for_inbox(
            db_session, status="awaiting_payment", q=token).items

        assert [f["id"] for f in filas] == [
            temprano.clearance.id, medio.clearance.id, tarde.clearance.id]
        assert filas[0]["total"] == ADEUDO + DONACION

    def test_por_cobrar_con_admitted_only_excluye_revocadas_y_terminadas(
            self, db_session, nuevo, token):
        """Ruling R9 (spec §4.8), gemela de
        `test_por_revisar_fifo_por_alta_y_sin_revocadas_ni_terminadas`: con
        `admitted_only=True` -lo que pide `pages/cashier_admin.py` («Por
        cobrar»)- un proceso revocado o terminado sale de la lista aunque su
        fila siga `awaiting_payment`; uno en pausa sigue operando (Biblioteca
        y Caja SÍ trabajan convocatorias en pausa, spec §4.2). SIN el flag
        (lo que sigue pidiendo Biblioteca en «En caja») el revocado se queda
        -se pinta «Revocada», Tarea 7- porque `admitted_only` por omisión es
        `False`."""
        def _en_caja(cohort, ready, **extra):
            return nuevo(cohort=cohort, last_name=token, status="awaiting_payment",
                         debt_amount=ADEUDO, donation_amount=DONACION,
                         total_amount=ADEUDO + DONACION, ready_at=ready, **extra)

        activo = _en_caja(None, datetime(2030, 2, 1, 9, 0))
        en_pausa = _en_caja(activo.cohort, datetime(2030, 2, 2, 9, 0),
                            process_status="on_hold")
        revocado = _en_caja(activo.cohort, datetime(2030, 2, 3, 9, 0),
                            process_status="cancelled")
        _en_caja(activo.cohort, datetime(2030, 2, 4, 9, 0), process_status="completed")

        con_flag = LibraryClearanceService.list_for_inbox(
            db_session, status="awaiting_payment", q=token, admitted_only=True).items
        sin_flag = LibraryClearanceService.list_for_inbox(
            db_session, status="awaiting_payment", q=token).items

        assert [f["id"] for f in con_flag] == [activo.clearance.id, en_pausa.clearance.id]
        assert revocado.clearance.id in {f["id"] for f in sin_flag}, (
            "Biblioteca (sin el flag) sigue mostrando el revocado, con su propia píldora")

    def test_liberados_recientes_primero_con_constancia_y_can_revert(
            self, db_session, nuevo, actores, token):
        # Fechas en el PASADO: el pago de abajo sella `updated_at` con el reloj real.
        viejo = nuevo(last_name=token, status="cleared",
                      updated_at=datetime(2020, 3, 1, 9, 0))
        revocado = nuevo(cohort=viejo.cohort, last_name=token, status="cleared",
                         process_status="cancelled", updated_at=datetime(2020, 3, 2, 9, 0))
        pagado = nuevo(cohort=viejo.cohort, last_name=token)
        _a_caja(db_session, pagado, actores.biblioteca)
        _pagar(db_session, pagado, actores.caja)             # updated_at = ahora

        filas = LibraryClearanceService.list_for_inbox(
            db_session, status="cleared", q=token).items

        assert [f["id"] for f in filas] == [
            pagado.clearance.id, revocado.clearance.id, viejo.clearance.id]
        por_id = {f["id"]: f for f in filas}
        assert por_id[pagado.clearance.id]["certificate_number"].startswith("BIB-")
        assert por_id[pagado.clearance.id]["via"] == "payment"
        assert por_id[pagado.clearance.id]["can_revert"] is True
        assert por_id[viejo.clearance.id]["certificate_number"] is None
        assert por_id[revocado.clearance.id]["revoked"] is True
        assert por_id[revocado.clearance.id]["can_revert"] is False

    def test_fila_trae_certificate_el_dict_de_print_status_map(
            self, db_session, nuevo, actores, token):
        """Tarea 3 (`2026-10-02-titulatec-constancias-y-pendientes-design.md`
        §3.3): `_rows` sustituyó su consulta propia de folio vigente por
        `CertificateService.print_status_map` -UNA llamada por página- y
        agrega la llave `certificate` con el dict completo que esa llamada
        regresa; la plantilla lo pinta con la macro `certificate_cell`.
        `certificate_number` SIGUE siendo la vigente (Caja y otras vistas ya
        la leen) y coincide con `certificate["number"]`."""
        from itcj2.apps.titulatec.services.certificate_service import CertificateService

        pagado = nuevo(last_name=token)
        _a_caja(db_session, pagado, actores.biblioteca)
        _pagar(db_session, pagado, actores.caja)
        batch = CertificateService.create_batch(db_session, kind="library_clearance",
                                                actor_id=actores.caja.id)
        sin_constancia = nuevo(cohort=pagado.cohort, last_name=token)

        filas = LibraryClearanceService.list_for_inbox(
            db_session, status="cleared", q=token).items
        por_id = {f["id"]: f for f in filas}

        pagada = por_id[pagado.clearance.id]
        assert pagada["certificate"]["printed"] is True
        assert pagada["certificate"]["batch_id"] == batch.id
        assert pagada["certificate"]["number"] == pagada["certificate_number"]
        assert pagada["certificate"]["voided_printed"] is None

        filas_pend = LibraryClearanceService.list_for_inbox(
            db_session, status="pending", q=token).items
        sin_fila = next(f for f in filas_pend if f["id"] == sin_constancia.clearance.id)
        assert sin_fila["certificate"] is None
        assert sin_fila["certificate_number"] is None

    def test_can_revert_en_lote_mira_la_fase_2(self, db_session, nuevo, token):
        abierta = nuevo(last_name=token, status="cleared", phase=2)
        cerrada = nuevo(cohort=abierta.cohort, last_name=token, status="cleared", phase=2)
        _fase2(db_session, cerrada.process, "approved")

        filas = LibraryClearanceService.list_for_inbox(
            db_session, status="cleared", q=token).items

        por_id = {f["id"]: f for f in filas}
        assert por_id[abierta.clearance.id]["can_revert"] is True
        assert por_id[cerrada.clearance.id]["can_revert"] is False

    def test_fila_trae_lo_que_pinta_la_bandeja(self, db_session, nuevo, token):
        esc = nuevo(last_name=token, donation=None)
        filas = LibraryClearanceService.list_for_inbox(
            db_session, status="pending", q=token).items

        fila = filas[0]
        assert fila["id"] == esc.clearance.id
        assert fila["process_id"] == esc.process.id
        assert fila["student"] == esc.student.full_name
        assert fila["control"] == esc.student.control_number
        assert fila["program"] == "Ingeniería Ficticia de Biblioteca"
        assert fila["cohort"] == esc.cohort.name
        assert fila["cohort_id"] == esc.cohort.id
        assert fila["status"] == "pending"
        assert fila["enrolled_at"] == esc.process.created_at
        assert fila["donation_missing"] is True
        assert fila["revoked"] is False
        assert fila["admitted"] is True
        assert {"debt", "donation", "total", "note", "ready_at", "paid_at", "receipt",
                "prior_issued_on", "via", "current_phase"} <= set(fila)

    def test_paginado(self, db_session, nuevo, token):
        base = nuevo(last_name=token)
        nuevo(cohort=base.cohort, last_name=token)
        nuevo(cohort=base.cohort, last_name=token)

        p1 = LibraryClearanceService.list_for_inbox(
            db_session, status="pending", q=token, page=1, per_page=2)
        p2 = LibraryClearanceService.list_for_inbox(
            db_session, status="pending", q=token, page=2, per_page=2)

        assert (len(p1.items), p1.has_next, len(p2.items), p2.has_next) == (2, True, 1, False)
        assert (p1.total, p2.total) == (3, 3)
        assert not {f["id"] for f in p1.items} & {f["id"] for f in p2.items}

    def test_inbox_muestra_rango_de_total(self, db_session, nuevo, token):
        base = nuevo(last_name=token)
        nuevo(cohort=base.cohort, last_name=token)
        nuevo(cohort=base.cohort, last_name=token)

        p2 = LibraryClearanceService.list_for_inbox(
            db_session, status="pending", q=token, page=2, per_page=2)
        # Fuera de rango cae a la ultima pagina valida.
        p9 = LibraryClearanceService.list_for_inbox(
            db_session, status="pending", q=token, page=9, per_page=2)

        assert (p2.start, p2.end, p2.total) == (3, 3, 3)
        assert (p9.page, p9.start, p9.end) == (2, 3, 3)

    def test_pestana_desconocida(self, db_session):
        with pytest.raises(ValueError):
            LibraryClearanceService.list_for_inbox(db_session, status="paid")


class TestCohortsMissingDonation:
    def test_solo_convocatorias_sin_donacion_con_casos_por_revisar(
            self, db_session, nuevo):
        sin = nuevo(donation=None)
        nuevo(cohort=sin.cohort)
        nuevo(cohort=sin.cohort, process_status="cancelled")      # no cuenta
        nuevo(cohort=sin.cohort, status="cleared")                # no cuenta
        con = nuevo()                                             # tiene donación
        sin_pendientes = nuevo(donation=None, status="cleared")

        avisos = {a["cohort_id"]: a for a in
                  LibraryClearanceService.cohorts_missing_donation(db_session)}

        assert avisos[sin.cohort.id] == {"cohort_id": sin.cohort.id,
                                         "name": sin.cohort.name, "pending": 2}
        assert con.cohort.id not in avisos
        assert sin_pendientes.cohort.id not in avisos


class TestSearch:
    def test_por_control_o_nombre_en_cualquier_estado(self, db_session, nuevo, token):
        pendiente = nuevo(last_name=token, first_name="ANA")
        en_caja = nuevo(cohort=pendiente.cohort, last_name=token, first_name="BETO",
                        status="awaiting_payment", debt_amount=ADEUDO,
                        donation_amount=DONACION, total_amount=ADEUDO + DONACION)
        pagado = nuevo(cohort=pendiente.cohort, last_name=token, first_name="CARLA",
                       status="cleared", cleared_via="payment")

        por_nombre = LibraryClearanceService.search(db_session, token)
        assert [r["id"] for r in por_nombre] == [
            pendiente.clearance.id, en_caja.clearance.id, pagado.clearance.id]
        assert [r["status"] for r in por_nombre] == ["pending", "awaiting_payment", "cleared"]

        por_control = LibraryClearanceService.search(
            db_session, en_caja.student.control_number)
        assert [r["id"] for r in por_control] == [en_caja.clearance.id]

        assert len(LibraryClearanceService.search(db_session, token, limit=2)) == 2

    def test_comodines_de_like_son_literales(self, db_session, nuevo, token):
        """`%` y `_` del buscador (Caja y Biblioteca comparten `_search_clause`)
        se escapan: no comodinean ni la búsqueda, ni el contador, ni la lista."""
        fila = nuevo(last_name=token)
        con_porciento = token[:5] + "%" + token[-3:]
        con_guion = token[:5] + "_" + token[6:]

        assert LibraryClearanceService.search(db_session, token)[0]["id"] == fila.clearance.id
        for q in (con_porciento, con_guion):
            assert LibraryClearanceService.search(db_session, q) == []
            assert LibraryClearanceService.counts_by_status(db_session, q)["pending"] == 0
            assert LibraryClearanceService.list_for_inbox(
                db_session, status="pending", q=q).items == []
        assert LibraryClearanceService.counts_by_status(db_session, token)["pending"] == 1

    @pytest.mark.parametrize("q", [None, "", "   "])
    def test_busqueda_vacia(self, db_session, q):
        assert LibraryClearanceService.search(db_session, q) == []

    def test_control_exacto_sale_primero_aunque_el_nombre_alfabetico_sea_antes(
            self, db_session, nuevo, token):
        """m10: el `case()` de control exacto (:990-993) manda SIEMPRE sobre
        el orden alfabético por nombre -- las pruebas de hoy nunca hacían
        competir las dos ramas."""
        por_nombre = nuevo(last_name=token, first_name="AAA_NOMBREANTES",
                           control_number=f"{token}X")
        por_control = nuevo(cohort=por_nombre.cohort, last_name=token,
                            first_name="ZZZ_NOMBREDESPUES", control_number=token)

        filas = LibraryClearanceService.search(db_session, token)

        assert [f["id"] for f in filas] == [
            por_control.clearance.id, por_nombre.clearance.id]


class TestDayCut:
    """`day_cut` (E3): corte del día FIJO desde `ProcessEvent`, nunca desde la
    fila VIGENTE. Cada prueba fija `ProcessEvent.created_at` A MANO después de
    llamar al service real -parchar `db_now()` solo controla lo que el PYTHON
    de la transición escribe (`clearance.paid_at`/`updated_at`), nunca el
    `server_default=NOW()` del evento-: así ningún caso depende del reloj de
    verdad ni de una fecha de calendario fija contra él (Review Focus #3)."""

    TOTAL = ADEUDO + DONACION   # 1100.00 ($300 adeudo + $800 donación, nuevo())

    @staticmethod
    def _en(db, monkeypatch, process_id, tipo, cuando):
        """Último evento `tipo` de `process_id` -> su `created_at` fijado a
        `cuando`. Se llama DESPUÉS de la transición real."""
        evento = _events(db, process_id, tipo)[-1]
        evento.created_at = cuando
        return evento

    def test_ayer_queda_fijo_y_hoy_trae_la_reversa_con_signo(
            self, db_session, nuevo, actores, monkeypatch):
        """Mandatorio: cobro ayer + reversa hoy -- el corte de ayer NO cambia
        (mismas filas y totales) y el de hoy trae -monto con el neto en
        negativo."""
        ayer, hoy = date(2031, 7, 10), date(2031, 7, 11)
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)

        monkeypatch.setattr(f"{SVC}.db_now", lambda: datetime(2031, 7, 10, 10, 0))
        _pagar(db_session, esc, actores.caja)
        self._en(db_session, monkeypatch, esc.process.id,
                 "library_payment_registered", datetime(2031, 7, 10, 10, 0))

        monkeypatch.setattr(f"{SVC}.db_now", lambda: datetime(2031, 7, 11, 9, 0))
        with patch(NOTIFY):
            LibraryClearanceService.revert_payment(
                db_session, esc.clearance.id, actores.caja.id, "Cobro equivocado")
        self._en(db_session, monkeypatch, esc.process.id,
                 "library_payment_reverted", datetime(2031, 7, 11, 9, 0))

        corte_ayer = LibraryClearanceService.day_cut(db_session, ayer)
        assert [r["kind"] for r in corte_ayer["rows"]] == ["charge"]
        fila_ayer = corte_ayer["rows"][0]
        assert fila_ayer["amount"] == self.TOTAL
        assert fila_ayer["clearance_id"] == esc.clearance.id
        assert fila_ayer["student"] == esc.student.full_name
        assert fila_ayer["control"] == esc.student.control_number
        assert fila_ayer["receipt"] == "R-100"            # default de `_pagar`
        assert fila_ayer["actor"] == actores.caja.full_name
        assert fila_ayer["certificate"] and fila_ayer["certificate"].startswith("BIB-")
        assert fila_ayer["reason"] is None
        assert fila_ayer["original_paid_at"] is None
        assert corte_ayer["charged"] == self.TOTAL
        assert corte_ayer["reverted"] == Decimal("0.00")
        assert corte_ayer["net"] == self.TOTAL

        corte_hoy = LibraryClearanceService.day_cut(db_session, hoy)
        assert [r["kind"] for r in corte_hoy["rows"]] == ["reversal"]
        fila_hoy = corte_hoy["rows"][0]
        assert fila_hoy["amount"] == -self.TOTAL
        assert fila_hoy["reason"] == "Cobro equivocado"
        assert fila_hoy["original_paid_at"] is not None
        assert fila_hoy["certificate"] == fila_ayer["certificate"], (
            "la reversa trae el folio del MISMO cobro que anuló")
        assert fila_hoy["can_revert_here"] is False
        assert corte_hoy["charged"] == Decimal("0.00")
        assert corte_hoy["reverted"] == self.TOTAL
        assert corte_hoy["net"] == -self.TOTAL

    def test_mismo_dia_cobro_reversa_cobro_neto_un_cobro_revertir_solo_el_ultimo(
            self, db_session, nuevo, actores, monkeypatch):
        """Mandatorio: cobro + reversa + cobro el MISMO día -- 3 renglones,
        neto = un cobro, «Revertir…» (`can_revert_here`) SOLO en el último
        cobro (el folio vigente es el de la 2.ª emisión; la 1.ª ya se anuló al
        revertir)."""
        dia = date(2031, 7, 20)
        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)

        monkeypatch.setattr(f"{SVC}.db_now", lambda: datetime(2031, 7, 20, 9, 0))
        _pagar(db_session, esc, actores.caja, receipt="R-1")
        cobro1 = self._en(db_session, monkeypatch, esc.process.id,
                          "library_payment_registered", datetime(2031, 7, 20, 9, 0))

        monkeypatch.setattr(f"{SVC}.db_now", lambda: datetime(2031, 7, 20, 10, 0))
        with patch(NOTIFY):
            LibraryClearanceService.revert_payment(
                db_session, esc.clearance.id, actores.caja.id, "Error de caja")
        reversa = self._en(db_session, monkeypatch, esc.process.id,
                           "library_payment_reverted", datetime(2031, 7, 20, 10, 0))

        monkeypatch.setattr(f"{SVC}.db_now", lambda: datetime(2031, 7, 20, 11, 0))
        _pagar(db_session, esc, actores.caja, receipt="R-2")
        cobro2 = self._en(db_session, monkeypatch, esc.process.id,
                          "library_payment_registered", datetime(2031, 7, 20, 11, 0))

        corte = LibraryClearanceService.day_cut(db_session, dia)

        assert [r["kind"] for r in corte["rows"]] == ["charge", "reversal", "charge"]
        assert [r["id"] for r in corte["rows"]] == [cobro2.id, reversa.id, cobro1.id]
        assert corte["charged"] == self.TOTAL * 2
        assert corte["reverted"] == self.TOTAL
        assert corte["net"] == self.TOTAL, "neto == un solo cobro"
        assert [r["can_revert_here"] for r in corte["rows"]] == [True, False, False], (
            "«Revertir…» solo en el cobro vigente (el último)")

    def test_dia_vacio(self, db_session):
        cero = Decimal("0.00")
        assert LibraryClearanceService.day_cut(db_session, date(2031, 7, 30)) == {
            "rows": [], "charged": cero, "reverted": cero, "net": cero}

    def test_payload_viejo_sin_total_no_truena_y_cuenta_como_cero(
            self, db_session, nuevo, actores):
        """Tolerancia a datos viejos de dev (payload sin `total`): nunca
        truena, entra a `charged` como 0 y la fila trae `amount == 0` (la
        plantilla lo pinta «—»)."""
        from itcj2.apps.titulatec.models import ProcessEvent

        esc = nuevo()
        _a_caja(db_session, esc, actores.biblioteca)
        dia = date(2031, 7, 25)
        db_session.add(ProcessEvent(
            process_id=esc.process.id, actor_id=actores.caja.id,
            event_type="library_payment_registered", phase_number=PHASE_COTEJO,
            payload={"clearance_id": esc.clearance.id, "receipt": "R-OLD"},
            created_at=datetime(2031, 7, 25, 9, 0),
        ))
        db_session.flush()

        corte = LibraryClearanceService.day_cut(db_session, dia)

        assert len(corte["rows"]) == 1
        fila = corte["rows"][0]
        assert fila["amount"] == Decimal("0.00")
        assert not fila["amount"]
        assert fila["certificate"] is None
        assert fila["can_revert_here"] is False
        assert fila["actor"] == actores.caja.full_name
        assert corte["charged"] == Decimal("0.00")
        assert corte["net"] == Decimal("0.00")


class TestEventAmount:
    """`_event_amount` (usado por `day_cut`): nunca truena, incluidos los
    valores especiales de `Decimal` que SÍ parsean sin error -- `Decimal(
    "NaN")` no lanza al construirse, pero compararlo con `>= 0`/`< 0` SÍ
    lanza `InvalidOperation`; `is_finite()` se revisa primero para que
    ninguna comparación posterior truene."""

    @pytest.mark.parametrize("raw, esperado", [
        (None, Decimal("0.00")),
        ("", Decimal("0.00")),
        ("abc", Decimal("0.00")),
        ("-5", Decimal("0.00")),
        ("NaN", Decimal("0.00")),
        ("sNaN", Decimal("0.00")),
        ("Infinity", Decimal("0.00")),
        ("-Infinity", Decimal("0.00")),
        ("800.00", Decimal("800.00")),
        ("1200.5", Decimal("1200.50")),
        (800, Decimal("800.00")),
    ])
    def test_nunca_truena(self, raw, esperado):
        assert LibraryClearanceService._event_amount(raw) == esperado


# ---------------------------------------------------------------------------
# Alta del proceso: `ImportService.import_rows` abre la fila
# ---------------------------------------------------------------------------
def _filas_import(n, base=99520000):
    return [{"control_number": str(base + i), "full_name": f"ALUMNA{i} BIBLIOTECA",
             "email": None, "program_id": None, "modality_id": None}
            for i in range(1, n + 1)]


class TestAltaDelProceso:
    def test_import_rows_abre_pending_sin_select(
            self, db_session, titulatec_app, seed_phase_defs, make_cohort):
        from itcj2.apps.titulatec.models import LibraryClearance, TitulationProcess
        from itcj2.apps.titulatec.services.import_service import ImportService

        seed_phase_defs()
        cohort = make_cohort(book_donation_amount=DONACION)

        with _sql(db_session) as sentencias:
            resumen = ImportService.import_rows(db_session, cohort, _filas_import(3))

        assert resumen["processes_created"] == 3
        pids = [p.id for p in db_session.query(TitulationProcess)
                .filter_by(cohort_id=cohort.id).all()]
        filas = (db_session.query(LibraryClearance)
                 .filter(LibraryClearance.process_id.in_(pids)).all())
        assert sorted(f.process_id for f in filas) == sorted(pids)
        assert {f.status for f in filas} == {"pending"}
        assert all(f.cleared_via is None and f.total_amount is None for f in filas)

        tocan = [s for s in sentencias if "titulatec_library_clearances" in s]
        assert tocan, "no se capturó el INSERT del no adeudo"
        assert not [s for s in tocan if s.lstrip().upper().startswith("SELECT")], (
            "el alta de un proceso NUEVO no necesita consultar la tabla")

    def test_reimportar_no_duplica(self, db_session, titulatec_app, seed_phase_defs,
                                   make_cohort):
        from itcj2.apps.titulatec.models import LibraryClearance, TitulationProcess
        from itcj2.apps.titulatec.services.import_service import ImportService

        seed_phase_defs()
        cohort = make_cohort(book_donation_amount=DONACION)
        filas = _filas_import(2, base=99520100)

        ImportService.import_rows(db_session, cohort, filas)
        segundo = ImportService.import_rows(db_session, cohort, filas)

        assert segundo["processes_created"] == 0
        pids = [p.id for p in db_session.query(TitulationProcess)
                .filter_by(cohort_id=cohort.id).all()]
        assert len(pids) == 2
        assert (db_session.query(LibraryClearance)
                .filter(LibraryClearance.process_id.in_(pids)).count()) == 2
