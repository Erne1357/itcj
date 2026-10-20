"""Observación CON ADEUDO de Biblioteca: Caja cobra, Biblioteca libera al activar.

Spec `docs/superpowers/specs/2026-10-07-titulatec-liberados-biblioteca-helpdesk-
design.md` §2 (D3/D4). `observation_kind` distingue la observación de siempre
(`blocking`: detiene todo, incluido el pago, D4) de la nueva (`with_debt`: Caja
SÍ cobra el monto congelado, pero el pago NO libera -ni folio, ni requisito, ni
cita- hasta que Biblioteca pulsa «Activar», D3).

Cubre la máquina de estados del service: observar con adeudo (montos con la
misma lógica que Registrar, total 0 -> error), cobrar retenido (sin folio, sin
requisito, el gate sigue bloqueando, el evento de cobro existe y el corte del
día lo cuenta UNA vez), revertir el pago retenido, «Activar» en sus tres ramas
(con pago -> folio + requisito, sin doble cobro en el corte), cambios de tipo
sin perder un pago, que la observación normal siga sin poder cobrarse, y los
correos de las variantes nuevas. Las bandejas (rutas/HTML) van en
`test_library_observation_debt_routes.py`.

DATOS. La BD de dev es COMPARTIDA: las listas se aíslan con un token único en
el apellido (`q`) y el corte del día con un día SINTÉTICO fijado a mano en los
eventos (patrón de `test_library_clearance_service.py`, sección del corte).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.library_clearance_service import (
    AUTO_SOURCE_LIBRARY, LIBRARY_EVENT_TYPES, ClearanceConflict, ClearanceObserved,
    LibraryClearanceService,
)

NOTIFY = "itcj2.apps.titulatec.services.notify.notify_student"

DONACION = Decimal("800.00")
ADEUDO = Decimal("300.00")
TOTAL = ADEUDO + DONACION
MOTIVO = "Entregar libro: «Cálculo» de Stewart"
# Día sintético del corte (nadie más escribe eventos en 2091).
DIA = date(2091, 3, 14)


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _correo_encendido(monkeypatch):
    from itcj2.config import get_settings

    monkeypatch.setattr(get_settings(), "TITULATEC_EMAIL_ENABLED", True)


@pytest.fixture(autouse=True)
def _graph_prohibido(monkeypatch):
    def _prohibido(*_a, **_k):
        raise AssertionError("nada aquí manda correo de verdad")

    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent", _prohibido)
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", _prohibido)


@pytest.fixture()
def actor(make_user):
    return make_user(first_name="BIBLIOTECA", last_name="ADEUDO")


@pytest.fixture()
def cajera(make_user):
    return make_user(first_name="CAJA", last_name="ADEUDO")


@pytest.fixture()
def token():
    return "DEB" + uuid.uuid4().hex[:10].upper()


@pytest.fixture()
def nuevo(db_session, make_student, make_process, make_cohort, make_library_clearance):
    """Convocatoria con donación $800 y requisito automático de no adeudo +
    egresado + proceso + su fila de no adeudo en `status`."""
    from itcj2.apps.titulatec.models import CotejoRequirement

    def _build(*, status="pending", phase=2, last_name="FICTICIO", donation=DONACION,
               **cols):
        cohort = make_cohort(book_donation_amount=donation)
        req = CotejoRequirement(
            cohort_id=cohort.id, label="Constancia de no adeudo de biblioteca", icon="book",
            code="library_clearance", auto_source=AUTO_SOURCE_LIBRARY,
            is_required=True, is_active=True, order_index=0)
        db_session.add(req)
        db_session.flush()
        student = make_student(last_name=last_name)
        process = make_process(student, cohort=cohort, current_phase=phase,
                               library_clearance=None)
        if status in ("awaiting_payment", "observed") and "total_amount" not in cols:
            cols = {"debt_amount": ADEUDO, "donation_amount": DONACION,
                    "total_amount": TOTAL, **cols}
        clearance = make_library_clearance(process, status=status, **cols)
        return SimpleNamespace(cohort=cohort, process=process, student=student,
                               clearance=clearance, requirement=req)

    return _build


def _events(db, process_id, tipo):
    from itcj2.apps.titulatec.models import ProcessEvent
    db.flush()
    return (db.query(ProcessEvent)
            .filter_by(process_id=process_id, event_type=tipo)
            .order_by(ProcessEvent.id).all())


def _outbox(db, process_id, kind=None):
    from itcj2.apps.titulatec.models import EmailOutbox
    db.flush()
    q = db.query(EmailOutbox).filter_by(process_id=process_id)
    if kind is not None:
        q = q.filter_by(kind=kind)
    return q.order_by(EmailOutbox.id).all()


def _certs(db, clearance_id):
    from itcj2.apps.titulatec.models import Certificate
    db.flush()
    return (db.query(Certificate)
            .filter_by(source_ref=f"library_clearance:{clearance_id}")
            .order_by(Certificate.id).all())


def _fulfillment(db, esc):
    from itcj2.apps.titulatec.models import RequirementFulfillment
    db.flush()
    return (db.query(RequirementFulfillment)
            .filter_by(process_id=esc.process.id, requirement_id=esc.requirement.id)
            .first())


def _observar(db, esc, actor, *, reason=MOTIVO, kind="with_debt", debt=ADEUDO):
    with patch(NOTIFY) as aviso:
        row = LibraryClearanceService.observe(db, esc.clearance.id, reason=reason,
                                              actor_id=actor.id, kind=kind,
                                              debt_amount=debt)
    return row, aviso


def _pagar(db, esc, cajera, **kw):
    with patch(NOTIFY) as aviso:
        row = LibraryClearanceService.register_payment(db, esc.clearance.id, cajera.id, **kw)
    return row, aviso


def _revertir(db, esc, cajera, reason="Se cobró a otra persona"):
    with patch(NOTIFY) as aviso:
        row = LibraryClearanceService.revert_payment(db, esc.clearance.id, cajera.id, reason)
    return row, aviso


def _activar(db, esc, actor):
    with patch(NOTIFY) as aviso:
        row = LibraryClearanceService.reenable(db, esc.clearance.id, actor_id=actor.id)
    return row, aviso


def _al_dia(db, process_id, tipo, cuando=datetime(2091, 3, 14, 10, 0)):
    """Fija el `created_at` del último evento `tipo` del proceso en el día
    sintético del corte."""
    evento = _events(db, process_id, tipo)[-1]
    evento.created_at = cuando
    db.flush()
    return evento


def _componer(db, proc, filas):
    from itcj2.apps.titulatec.services.mail_compose import MailComposer
    from itcj2.core.models.user import User

    resultado = MailComposer.compose(db, filas, proc, db.get(User, proc.student_id))
    assert not (db.new or db.dirty or db.deleted), "componer escribió en la sesión"
    return resultado


def _html(c):
    from itcj2.apps.titulatec.pages.nav import titulatec_templates
    return titulatec_templates.get_template(f"titulatec/email/{c.template}").render(
        **c.context)


def _gate(db, esc):
    from itcj2.apps.titulatec.services.clearance_gate import ClearanceGate
    return ClearanceGate.status(db, esc.process.id)["library"]


# ---------------------------------------------------------------------------
# Modelo y catálogos
# ---------------------------------------------------------------------------
def test_dominio_de_observation_kind_y_evento_nuevo():
    from itcj2.apps.titulatec.models.library_clearance import OBSERVATION_KINDS
    from itcj2.apps.titulatec.models.process_event import EVENT_TYPES

    assert OBSERVATION_KINDS == ("blocking", "with_debt")
    assert "library_cleared_after_observation" in LIBRARY_EVENT_TYPES
    assert "library_cleared_after_observation" in EVENT_TYPES
    assert all(len(e) <= 40 for e in LIBRARY_EVENT_TYPES)


def test_kind_de_correo_nuevo_registrado():
    from itcj2.apps.titulatec.models.email_outbox import OUTBOX_KINDS
    from itcj2.apps.titulatec.services.mail_compose import MailComposer
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    assert "library_payment_held" in OUTBOX_KINDS
    assert "library_payment_held" in MailComposer.REGISTRY
    assert "library_payment_held" in StudentMail.KIND_LABELS


# ---------------------------------------------------------------------------
# Observar con adeudo
# ---------------------------------------------------------------------------
def test_observar_con_adeudo_desde_por_revisar_congela_montos(db_session, nuevo, actor):
    esc = nuevo()

    row, aviso = _observar(db_session, esc, actor, reason=f"  {MOTIVO}  ")

    assert row.status == "observed"
    assert row.observation_kind == "with_debt"
    assert row.observation_reason == MOTIVO
    assert (row.debt_amount, row.donation_amount, row.total_amount) == (
        ADEUDO, DONACION, TOTAL), "misma lógica que Registrar: adeudo + donación congelada"
    assert row.library_by_id == actor.id and row.library_at is not None
    assert row.ready_at is not None, "entra a Caja: se puede cobrar"
    assert row.paid_at is None and row.cleared_via is None
    (evento,) = _events(db_session, esc.process.id, "library_observed")
    assert evento.payload["kind"] == "with_debt"
    assert evento.payload["from_status"] == "pending"
    assert evento.payload["total"] == "1100.00"
    assert aviso.call_args.kwargs["type"] == "LIBRARY_OBSERVED"
    assert MOTIVO in aviso.call_args.kwargs["body"]
    assert "$1,100.00" in aviso.call_args.kwargs["body"]
    (correo,) = _outbox(db_session, esc.process.id, "library_observed")
    assert correo.payload["kind"] == "with_debt"
    assert correo.payload["reason"] == MOTIVO
    assert _gate(db_session, esc) == "observed"


def test_observar_con_adeudo_desde_en_caja_recongela_y_conserva_la_entrada(db_session, nuevo,
                                                                         actor):
    esc = nuevo(status="awaiting_payment", ready_at=datetime(2031, 3, 1, 9, 0),
                library_note="Debe un libro")
    esc.cohort.book_donation_amount = Decimal("900.00")     # cambió la convocatoria
    db_session.flush()

    row, _ = _observar(db_session, esc, actor, debt=Decimal("100"))

    assert row.status == "observed" and row.observation_kind == "with_debt"
    assert (row.debt_amount, row.donation_amount, row.total_amount) == (
        Decimal("100.00"), Decimal("900.00"), Decimal("1000.00"))
    assert row.ready_at == datetime(2031, 3, 1, 9, 0), "ya estaba en Caja: conserva su lugar"
    assert row.library_note == "Debe un libro"


def test_total_cero_es_error_usa_la_observacion_normal(db_session, nuevo, actor):
    esc = nuevo(donation=Decimal("0.00"))

    with pytest.raises(ValueError, match="observación normal"):
        _observar(db_session, esc, actor, debt=Decimal("0"))

    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "pending"
    assert esc.clearance.observation_kind is None
    assert _events(db_session, esc.process.id, "library_observed") == []
    assert _outbox(db_session, esc.process.id) == []


def test_adeudo_cero_con_donacion_si_se_observa(db_session, nuevo, actor):
    """«Sin adeudo» con donación no es total 0 (D18): igual va a Caja."""
    esc = nuevo()
    row, _ = _observar(db_session, esc, actor, debt=Decimal("0"))
    assert row.total_amount == DONACION


@pytest.mark.parametrize("debt, patron", [(None, "monto"), (Decimal("-1"), "negativo"),
                                          (Decimal("100000.01"), "pasar de")])
def test_monto_obligatorio_y_validado(db_session, nuevo, actor, debt, patron):
    esc = nuevo()
    with pytest.raises(ValueError, match=patron):
        _observar(db_session, esc, actor, debt=debt)
    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "pending"


def test_convocatoria_sin_donacion_es_error(db_session, nuevo, actor):
    esc = nuevo(donation=None)
    with pytest.raises(ValueError, match="donación"):
        _observar(db_session, esc, actor)
    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "pending"


def test_tipo_desconocido_es_error(db_session, nuevo, actor):
    esc = nuevo()
    with pytest.raises(ValueError, match="observación"):
        _observar(db_session, esc, actor, kind="otra")
    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "pending"


def test_la_observacion_normal_marca_blocking(db_session, nuevo, actor):
    esc = nuevo(status="awaiting_payment", ready_at=datetime(2031, 3, 1, 9, 0))
    row, aviso = _observar(db_session, esc, actor, kind="blocking", debt=None)
    assert row.observation_kind == "blocking"
    assert row.ready_at is None
    assert aviso.call_args.kwargs["body"] == MOTIVO
    (correo,) = _outbox(db_session, esc.process.id, "library_observed")
    assert correo.payload["kind"] == "blocking"


# ---------------------------------------------------------------------------
# Caja cobra retenido
# ---------------------------------------------------------------------------
def test_caja_cobra_retenido_sin_folio_ni_requisito_y_el_gate_sigue_bloqueando(
        db_session, nuevo, actor, cajera):
    esc = nuevo()
    _observar(db_session, esc, actor)

    row, aviso = _pagar(db_session, esc, cajera, receipt_number=" R-77 ",
                        expected_total=TOTAL, expected_status="observed")

    assert row.status == "observed" and row.observation_kind == "with_debt"
    assert row.paid_at is not None and row.paid_by_id == cajera.id
    assert row.receipt_number == "R-77"
    assert row.cleared_via is None
    assert LibraryClearanceService.payment_held(row) is True
    assert _certs(db_session, esc.clearance.id) == [], "el pago retenido NO emite folio"
    assert _fulfillment(db_session, esc) is None, "ni cumple el requisito"
    assert _gate(db_session, esc) == "observed", "ni libera la cita"
    (evento,) = _events(db_session, esc.process.id, "library_payment_registered")
    assert evento.payload["total"] == "1100.00"
    assert evento.payload["certificate"] is None
    assert evento.payload["held"] is True
    assert evento.payload["paid_at"] == row.paid_at.isoformat()
    assert aviso.call_args.kwargs["type"] == "LIBRARY_PAYMENT_HELD"
    assert "Biblioteca" in aviso.call_args.kwargs["body"]
    assert _outbox(db_session, esc.process.id, "library_cleared") == []
    (correo,) = _outbox(db_session, esc.process.id, "library_payment_held")
    assert correo.payload == {"total": "1100.00", "receipt": "R-77"}


def test_doble_cobro_retenido_es_error(db_session, nuevo, actor, cajera):
    esc = nuevo()
    _observar(db_session, esc, actor)
    _pagar(db_session, esc, cajera)

    with pytest.raises(ValueError, match="ya está registrado"):
        _pagar(db_session, esc, cajera, expected_total=TOTAL)
    assert len(_events(db_session, esc.process.id, "library_payment_registered")) == 1


def test_cobro_con_la_pantalla_vieja_de_por_cobrar_es_choque(db_session, nuevo, actor, cajera):
    """La cajera vio un «Por cobrar» normal; Biblioteca lo observó con adeudo
    mientras tanto: re-pinta (choque), no cobra sin que vea la observación."""
    esc = nuevo(status="awaiting_payment", ready_at=datetime(2031, 3, 1, 9, 0))
    _observar(db_session, esc, actor)

    with pytest.raises(ClearanceConflict):
        _pagar(db_session, esc, cajera, expected_total=TOTAL,
               expected_status="awaiting_payment")
    db_session.refresh(esc.clearance)
    assert esc.clearance.paid_at is None


def test_la_observacion_normal_sigue_sin_poder_cobrarse(db_session, nuevo, actor, cajera):
    """D4 / Review Focus 4: la observación sin adeudo bloquea también el pago."""
    esc = nuevo(status="awaiting_payment")
    _observar(db_session, esc, actor, kind="blocking", debt=None)

    with pytest.raises(ClearanceObserved):
        _pagar(db_session, esc, cajera, expected_total=TOTAL, expected_status="observed")
    with pytest.raises(ClearanceObserved):
        _revertir(db_session, esc, cajera)
    db_session.refresh(esc.clearance)
    assert esc.clearance.paid_at is None


def test_las_demas_transiciones_siguen_bloqueadas_con_adeudo(db_session, nuevo, actor):
    esc = nuevo()
    _observar(db_session, esc, actor)
    cid = esc.clearance.id

    intentos = [
        lambda: LibraryClearanceService.register(db_session, cid, actor.id,
                                                 debt_amount=ADEUDO),
        lambda: LibraryClearanceService.revert_clearance(db_session, cid, actor.id, "x"),
        lambda: LibraryClearanceService.undo_prior(db_session, cid, actor.id, "x"),
        lambda: LibraryClearanceService.register_prior(
            db_session, cid, actor.id, issued_on=date.today(), by="library"),
    ]
    with patch(NOTIFY):
        for intento in intentos:
            with pytest.raises(ClearanceObserved):
                intento()
        out = LibraryClearanceService.register_no_debt_bulk(db_session, [cid], actor.id)
    assert out["done"] == 0
    assert LibraryClearanceService.prior_outcome(db_session, esc.process.id) == "conflict"


# ---------------------------------------------------------------------------
# Revertir el pago retenido
# ---------------------------------------------------------------------------
def test_revertir_pago_retenido(db_session, nuevo, actor, cajera):
    esc = nuevo()
    _observar(db_session, esc, actor)
    pagado, _ = _pagar(db_session, esc, cajera, receipt_number="R-1")
    paid_at = pagado.paid_at

    row, aviso = _revertir(db_session, esc, cajera, reason="  Se cobró a otra persona ")

    assert row.status == "observed" and row.observation_kind == "with_debt"
    assert row.paid_at is None and row.paid_by_id is None and row.receipt_number is None
    assert row.total_amount == TOTAL, "sigue debiéndolo"
    assert row.observation_reason == MOTIVO
    (evento,) = _events(db_session, esc.process.id, "library_payment_reverted")
    assert evento.payload["total"] == "1100.00"
    assert evento.payload["reason"] == "Se cobró a otra persona"
    assert evento.payload["certificate"] is None
    assert evento.payload["paid_at"] == paid_at.isoformat()
    assert aviso.call_args.kwargs["type"] == "LIBRARY_PAYMENT_REVERTED"
    assert _outbox(db_session, esc.process.id, "library_reverted") == [], (
        "nunca se liberó: no hay «se revirtió tu Constancia»")
    assert LibraryClearanceService.payment_held(row) is False


def test_revertir_retenido_sin_pago_es_error(db_session, nuevo, actor, cajera):
    esc = nuevo()
    _observar(db_session, esc, actor)
    with pytest.raises(ValueError, match="pago registrado"):
        _revertir(db_session, esc, cajera)


# ---------------------------------------------------------------------------
# Corte del día: el cobro retenido cuenta el día que se cobra, una sola vez
# ---------------------------------------------------------------------------
def test_corte_cuenta_el_cobro_retenido_una_vez_aunque_se_active(db_session, nuevo, actor,
                                                                 cajera):
    esc = nuevo()
    _observar(db_session, esc, actor)
    _pagar(db_session, esc, cajera, receipt_number="R-9")
    _al_dia(db_session, esc.process.id, "library_payment_registered")

    corte = LibraryClearanceService.day_cut(db_session, DIA)
    (cobro,) = [r for r in corte["rows"] if r["clearance_id"] == esc.clearance.id]
    assert cobro["kind"] == "charge" and cobro["amount"] == TOTAL
    assert cobro["certificate"] is None
    assert cobro["can_revert_here"] is True, "el retenido se revierte desde el corte"
    cobrado = corte["charged"]

    _activar(db_session, esc, actor)
    _al_dia(db_session, esc.process.id, "library_cleared_after_observation")

    despues = LibraryClearanceService.day_cut(db_session, DIA)
    mios = [r for r in despues["rows"] if r["clearance_id"] == esc.clearance.id]
    assert [r["kind"] for r in mios] == ["charge"], "activar NO es otro cobro"
    assert despues["charged"] == cobrado


def test_corte_la_reversa_del_retenido_resta(db_session, nuevo, actor, cajera):
    esc = nuevo()
    _observar(db_session, esc, actor)
    _pagar(db_session, esc, cajera)
    _al_dia(db_session, esc.process.id, "library_payment_registered")
    _revertir(db_session, esc, cajera)
    _al_dia(db_session, esc.process.id, "library_payment_reverted",
            datetime(2091, 3, 14, 11, 0))

    corte = LibraryClearanceService.day_cut(db_session, DIA)
    mios = [r for r in corte["rows"] if r["clearance_id"] == esc.clearance.id]
    assert [(r["kind"], r["amount"]) for r in mios] == [("reversal", -TOTAL),
                                                       ("charge", TOTAL)]
    assert not any(r["can_revert_here"] for r in mios), "ya no hay pago vigente"


# ---------------------------------------------------------------------------
# Activar: tres ramas
# ---------------------------------------------------------------------------
def test_activar_observacion_normal_vuelve_a_por_revisar(db_session, nuevo, actor):
    esc = nuevo(status="awaiting_payment")
    _observar(db_session, esc, actor, kind="blocking", debt=None)

    row, aviso = _activar(db_session, esc, actor)

    assert row.status == "pending"
    assert row.observation_kind is None and row.observation_reason is None
    assert row.total_amount == TOTAL, "D2: montos intactos"
    (evento,) = _events(db_session, esc.process.id, "library_reenabled")
    assert evento.payload["to_status"] == "pending"
    assert aviso.call_args.kwargs["type"] == "LIBRARY_REENABLED"
    (correo,) = _outbox(db_session, esc.process.id, "library_reenabled")
    assert correo.payload == {"to_status": "pending"}


def test_activar_con_adeudo_sin_pago_pasa_a_caja(db_session, nuevo, actor, token):
    esc = nuevo(last_name=token)
    _observar(db_session, esc, actor)
    esc.clearance.ready_at = datetime(2031, 1, 1, 9, 0)
    db_session.flush()

    row, aviso = _activar(db_session, esc, actor)

    assert row.status == "awaiting_payment"
    assert row.observation_kind is None and row.observation_reason is None
    assert row.observed_at is None and row.observed_by_id is None
    assert row.total_amount == TOTAL
    assert row.ready_at != datetime(2031, 1, 1, 9, 0), "nueva entrada a Caja: ready_at = ahora"
    (evento,) = _events(db_session, esc.process.id, "library_reenabled")
    assert evento.payload["to_status"] == "awaiting_payment"
    assert evento.payload["kind"] == "with_debt"
    assert aviso.call_args.kwargs["type"] == "LIBRARY_REENABLED"
    assert "Caja" in aviso.call_args.kwargs["body"]
    (correo,) = _outbox(db_session, esc.process.id, "library_reenabled")
    assert correo.payload == {"to_status": "awaiting_payment"}
    assert LibraryClearanceService.payment_due(db_session, esc.process.id)["total"] == TOTAL
    assert _certs(db_session, esc.clearance.id) == []
    assert _gate(db_session, esc) == "awaiting_payment"


def test_activar_con_pago_libera_con_folio_y_requisito(db_session, nuevo, actor, cajera):
    esc = nuevo()
    _observar(db_session, esc, actor)
    _pagar(db_session, esc, cajera, receipt_number="R-5")

    row, aviso = _activar(db_session, esc, actor)

    assert row.status == "cleared" and row.cleared_via == "payment"
    assert row.observation_kind is None and row.observation_reason is None
    assert row.paid_by_id == cajera.id and row.receipt_number == "R-5"
    (folio,) = _certs(db_session, esc.clearance.id)
    assert folio.number.startswith("BIB-") and folio.voided_at is None
    ful = _fulfillment(db_session, esc)
    assert ful is not None and ful.external_ref == f"library_clearance:{esc.clearance.id}"
    assert _gate(db_session, esc) == "cleared"
    (evento,) = _events(db_session, esc.process.id, "library_cleared_after_observation")
    assert evento.payload["certificate"] == folio.number
    assert evento.payload["total"] == "1100.00"
    assert evento.payload["previous_reason"] == MOTIVO
    assert len(_events(db_session, esc.process.id, "library_payment_registered")) == 1, (
        "no se repite el evento de cobro (el corte lo contaría doble)")
    assert _events(db_session, esc.process.id, "library_reenabled") == []
    assert aviso.call_args.kwargs["type"] == "LIBRARY_CLEARED"
    (correo,) = _outbox(db_session, esc.process.id, "library_cleared")
    assert correo.payload == {"via": "payment"}
    assert _outbox(db_session, esc.process.id, "library_reenabled") == []
    # Después, Caja puede revertir el pago como cualquier liberado por pago.
    assert LibraryClearanceService.can_revert(db_session, row) is True


def test_activar_con_pago_y_luego_revertir_anula_el_folio(db_session, nuevo, actor, cajera):
    esc = nuevo()
    _observar(db_session, esc, actor)
    _pagar(db_session, esc, cajera)
    _activar(db_session, esc, actor)

    row, _ = _revertir(db_session, esc, cajera)

    assert row.status == "awaiting_payment"
    (folio,) = _certs(db_session, esc.clearance.id)
    assert folio.voided_at is not None


# ---------------------------------------------------------------------------
# Re-observar y cambios de tipo (Ruling: nunca se pierde un pago registrado)
# ---------------------------------------------------------------------------
def test_re_observar_con_adeudo_sin_pago_recongela(db_session, nuevo, actor):
    esc = nuevo()
    _observar(db_session, esc, actor)
    row, _ = _observar(db_session, esc, actor, reason="Entregar dos libros",
                       debt=Decimal("500"))
    assert row.observation_reason == "Entregar dos libros"
    assert row.total_amount == Decimal("1300.00")
    eventos = _events(db_session, esc.process.id, "library_observed")
    assert eventos[-1].payload["from_status"] == "observed"
    assert eventos[-1].payload["from_kind"] == "with_debt"


def test_con_pago_solo_cambia_el_motivo(db_session, nuevo, actor, cajera):
    esc = nuevo()
    _observar(db_session, esc, actor)
    _pagar(db_session, esc, cajera, receipt_number="R-3")

    row, _ = _observar(db_session, esc, actor, reason="Entregar el libro y la credencial",
                       debt=None)
    assert row.observation_reason == "Entregar el libro y la credencial"
    assert row.total_amount == TOTAL and row.receipt_number == "R-3"
    assert row.paid_at is not None

    # El mismo adeudo (precargado) también vale; otro adeudo no.
    _observar(db_session, esc, actor, debt=ADEUDO)
    with pytest.raises(ValueError, match="revierta el pago"):
        _observar(db_session, esc, actor, debt=Decimal("10"))
    db_session.refresh(esc.clearance)
    assert esc.clearance.total_amount == TOTAL


def test_con_pago_no_se_cambia_a_observacion_normal(db_session, nuevo, actor, cajera):
    esc = nuevo()
    _observar(db_session, esc, actor)
    _pagar(db_session, esc, cajera)

    with pytest.raises(ValueError, match="revierta el pago"):
        _observar(db_session, esc, actor, kind="blocking", debt=None)
    db_session.refresh(esc.clearance)
    assert esc.clearance.observation_kind == "with_debt"
    assert esc.clearance.paid_at is not None


def test_de_normal_a_con_adeudo_y_de_regreso(db_session, nuevo, actor):
    esc = nuevo()
    _observar(db_session, esc, actor, kind="blocking", debt=None)

    row, _ = _observar(db_session, esc, actor, debt=ADEUDO)
    assert row.observation_kind == "with_debt" and row.ready_at is not None
    assert row.total_amount == TOTAL

    row, _ = _observar(db_session, esc, actor, kind="blocking", debt=None)
    assert row.observation_kind == "blocking"
    assert row.ready_at is None, "la normal sale de Caja"
    assert row.total_amount == TOTAL, "conserva los montos como historia"


# ---------------------------------------------------------------------------
# Lectores
# ---------------------------------------------------------------------------
def test_resumen_y_observacion_traen_tipo_monto_y_pago(db_session, nuevo, actor, cajera):
    esc = nuevo()
    _observar(db_session, esc, actor)

    resumen = LibraryClearanceService.summary_for_process(db_session, esc.process.id)
    assert resumen["status"] == "observed"
    assert resumen["observation_kind"] == "with_debt"
    assert resumen["total"] == TOTAL and resumen["paid_at"] is None
    obs = LibraryClearanceService.observation(db_session, esc.process.id)
    assert obs["kind"] == "with_debt" and obs["total"] == TOTAL and obs["paid_at"] is None

    _pagar(db_session, esc, cajera)
    obs = LibraryClearanceService.observation(db_session, esc.process.id)
    assert obs["paid_at"] is not None
    assert LibraryClearanceService.summary_for_process(
        db_session, esc.process.id)["paid_at"] is not None


def test_observada_sin_tipo_cuenta_como_normal(db_session, nuevo, cajera):
    """Una fila `observed` sin `observation_kind` (dato anterior a la
    migración, o una fábrica de pruebas) se trata como la de siempre: falla
    cerrado."""
    esc = nuevo(status="observed", observation_reason="x")
    assert LibraryClearanceService.summary_for_process(
        db_session, esc.process.id)["observation_kind"] == "blocking"
    with pytest.raises(ClearanceObserved):
        _pagar(db_session, esc, cajera)


def test_fuera_de_observed_no_hay_tipo(db_session, nuevo):
    esc = nuevo(status="awaiting_payment")
    assert LibraryClearanceService.summary_for_process(
        db_session, esc.process.id)["observation_kind"] is None
    assert LibraryClearanceService.observation(db_session, esc.process.id) is None


def test_por_cobrar_de_caja_lista_el_retenido_sin_pago_y_no_el_normal(db_session, nuevo,
                                                                     actor, cajera, token):
    en_caja = nuevo(status="awaiting_payment", last_name=token,
                    ready_at=datetime(2020, 1, 1, 9, 0))      # FIFO: entró antes
    con_adeudo = nuevo(last_name=token)
    normal = nuevo(status="awaiting_payment", last_name=token)
    pagado = nuevo(last_name=token)
    _observar(db_session, con_adeudo, actor)
    _observar(db_session, normal, actor, kind="blocking", debt=None)
    _observar(db_session, pagado, actor)
    _pagar(db_session, pagado, cajera)

    pagina = LibraryClearanceService.list_for_cashier(db_session, q=token)
    ids = [r["id"] for r in pagina.items]
    assert ids == [en_caja.clearance.id, con_adeudo.clearance.id]
    assert LibraryClearanceService.cashier_due_count(db_session, q=token) == 2
    fila = pagina.items[1]
    assert fila["observation_kind"] == "with_debt" and fila["held"] is False
    assert fila["observation_reason"] == MOTIVO

    # La búsqueda de Caja ve al retenido pagado como tal, revertible.
    (encontrado,) = [r for r in LibraryClearanceService.search(db_session, token)
                     if r["id"] == pagado.clearance.id]
    assert encontrado["held"] is True and encontrado["can_revert_held"] is True


def test_el_recordatorio_de_pago_no_persigue_al_retenido(db_session, nuevo, actor):
    """Ruling: `with_debt` sin pago no recibe recordatorios de pago (el correo
    de la observación ya lo dice); `payment_due` sigue siendo solo de
    `awaiting_payment`."""
    esc = nuevo()
    _observar(db_session, esc, actor)
    assert LibraryClearanceService.payment_due(db_session, esc.process.id) is None


# ---------------------------------------------------------------------------
# Correos
# ---------------------------------------------------------------------------
def test_correo_de_observacion_con_adeudo(db_session, nuevo, actor):
    from itcj2.apps.titulatec.services.mail_compose import Composed

    esc = nuevo()
    _observar(db_session, esc, actor)
    (fila,) = _outbox(db_session, esc.process.id, "library_observed")

    c = _componer(db_session, esc.process, [fila])

    assert isinstance(c, Composed), c
    assert c.context["con_adeudo"] is True and c.context["total"] == "$1,100.00"
    html = _html(c)
    assert "$1,100.00" in html
    assert "misma visita" in html
    assert "Constancia de no adeudo se libera cuando Biblioteca registre la entrega" in html


def test_correo_de_observacion_normal_no_cambia(db_session, nuevo, actor):
    from itcj2.apps.titulatec.services.mail_compose import Composed

    esc = nuevo()
    _observar(db_session, esc, actor, kind="blocking", debt=None)
    (fila,) = _outbox(db_session, esc.process.id, "library_observed")
    c = _componer(db_session, esc.process, [fila])
    assert isinstance(c, Composed) and c.context["con_adeudo"] is False
    assert "ni pagar en Caja" in _html(c)


def test_correo_de_pago_retenido_y_su_obsolescencia(db_session, nuevo, actor, cajera):
    from itcj2.apps.titulatec.services.mail_compose import Composed, Obsolete

    esc = nuevo()
    _observar(db_session, esc, actor)
    _pagar(db_session, esc, cajera, receipt_number="R-1")
    (fila,) = _outbox(db_session, esc.process.id, "library_payment_held")

    c = _componer(db_session, esc.process, [fila])
    assert isinstance(c, Composed), c
    assert c.template == "library_payment_held.html"
    html = _html(c)
    assert "$1,100.00" in html and "Biblioteca registre la entrega" in html

    _activar(db_session, esc, actor)
    assert isinstance(_componer(db_session, esc.process, [fila]), Obsolete), (
        "ya liberada: sale el «quedó liberada», no este")


def test_correo_de_pago_retenido_obsoleto_si_se_revirtio(db_session, nuevo, actor, cajera):
    from itcj2.apps.titulatec.services.mail_compose import Obsolete

    esc = nuevo()
    _observar(db_session, esc, actor)
    _pagar(db_session, esc, cajera)
    _revertir(db_session, esc, cajera)
    (fila,) = _outbox(db_session, esc.process.id, "library_payment_held")
    assert isinstance(_componer(db_session, esc.process, [fila]), Obsolete)


def test_correo_de_activar_hacia_caja(db_session, nuevo, actor, cajera):
    from itcj2.apps.titulatec.services.mail_compose import Composed, Obsolete

    esc = nuevo()
    _observar(db_session, esc, actor)
    _activar(db_session, esc, actor)
    (fila,) = _outbox(db_session, esc.process.id, "library_reenabled")

    c = _componer(db_session, esc.process, [fila])
    assert isinstance(c, Composed), c
    assert c.context["a_caja"] is True and c.context["total"] == "$1,100.00"
    assert "Caja" in _html(c)

    _pagar(db_session, esc, cajera)          # ya pagó: el aviso de Caja ya no aplica
    assert isinstance(_componer(db_session, esc.process, [fila]), Obsolete)


def test_correo_de_liberada_al_activar_con_pago(db_session, nuevo, actor, cajera):
    from itcj2.apps.titulatec.services.mail_compose import Composed

    esc = nuevo()
    _observar(db_session, esc, actor)
    _pagar(db_session, esc, cajera)
    _activar(db_session, esc, actor)
    (obs,) = _outbox(db_session, esc.process.id, "library_observed")
    (lib,) = _outbox(db_session, esc.process.id, "library_cleared")

    from itcj2.apps.titulatec.services.mail_compose import Obsolete
    assert isinstance(_componer(db_session, esc.process, [obs]), Obsolete)
    c = _componer(db_session, esc.process, [lib])
    assert isinstance(c, Composed) and c.context["pagado"] == "$1,100.00"
