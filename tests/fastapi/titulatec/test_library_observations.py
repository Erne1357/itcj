"""«Con observaciones» del no adeudo de biblioteca: Biblioteca DETIENE a un
egresado con un motivo (`observe`) y solo Biblioteca lo REHABILITA
(`reenable`), de vuelta a «Por revisar».

Spec `docs/superpowers/specs/2026-10-05-titulatec-biblioteca-observaciones-
design.md` §2 (D1-D4), §3.1-§3.3. Análogo a «Observar» de GTV
(`SurveyReviewService.reject`).

Cubre: transiciones válidas e inválidas desde cada estado, motivo
obligatorio y recortado, `ready_at` limpio al observar desde Caja, montos
conservados al rehabilitar, guardas de proceso/fase 2, eventos, avisos,
filas de outbox y su composición (incluido el `Obsolete` del Review Focus 4),
las guardas de registrar/pagar/revertir/previa sobre una observada, y la
pestaña nueva de la bandeja.

DATOS. La BD de dev es COMPARTIDA: las listas se aíslan con un token único
en el apellido (`q`), nunca por absolutos.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.library_clearance_service import (
    AUTO_SOURCE_LIBRARY, LIBRARY_EVENT_TYPES, LibraryClearanceService,
)

NOTIFY = "itcj2.apps.titulatec.services.notify.notify_student"

DONACION = Decimal("800.00")
ADEUDO = Decimal("300.00")
TOTAL = ADEUDO + DONACION
MSG_OBSERVADO = "observaciones de Biblioteca"


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _correo_encendido(monkeypatch):
    """Encolar necesita el correo encendido (atributo del singleton, como el
    resto de la suite)."""
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
    return make_user(first_name="BIBLIOTECA", last_name="OBSERVA")


@pytest.fixture()
def token():
    return "OBS" + uuid.uuid4().hex[:10].upper()


@pytest.fixture()
def nuevo(db_session, make_student, make_process, make_cohort, make_library_clearance):
    """Convocatoria con donación $800 y requisito automático de no adeudo +
    egresado + proceso + su fila de no adeudo en `status`."""
    from itcj2.apps.titulatec.models import CotejoRequirement

    def _build(*, status="pending", process_status="active", phase=1,
               last_name="FICTICIO", cohort=None, **cols):
        if cohort is None:
            cohort = make_cohort(book_donation_amount=DONACION)
            db_session.add(CotejoRequirement(
                cohort_id=cohort.id, label="Constancia de no adeudo de biblioteca", icon="book",
                code="library_clearance", auto_source=AUTO_SOURCE_LIBRARY,
                is_required=True, is_active=True, order_index=0))
            db_session.flush()
        student = make_student(last_name=last_name)
        process = make_process(student, cohort=cohort, current_phase=phase,
                               status=process_status, library_clearance=None)
        if status in ("awaiting_payment", "observed") and "total_amount" not in cols:
            cols = {"debt_amount": ADEUDO, "donation_amount": DONACION,
                    "total_amount": TOTAL, **cols}
        clearance = make_library_clearance(process, status=status, **cols)
        return SimpleNamespace(cohort=cohort, process=process, student=student,
                               clearance=clearance)

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


def _observar(db, esc, actor, reason="Libro dañado: «Cálculo» de Stewart"):
    with patch(NOTIFY) as aviso:
        row = LibraryClearanceService.observe(db, esc.clearance.id,
                                              reason=reason, actor_id=actor.id)
    return row, aviso


def _rehabilitar(db, esc, actor):
    with patch(NOTIFY) as aviso:
        row = LibraryClearanceService.reenable(db, esc.clearance.id, actor_id=actor.id)
    return row, aviso


def _componer(db, proc, filas):
    from itcj2.apps.titulatec.services.mail_compose import MailComposer
    from itcj2.core.models.user import User

    resultado = MailComposer.compose(db, filas, proc, db.get(User, proc.student_id))
    assert not (db.new or db.dirty or db.deleted), "componer escribió en la sesión"
    return resultado


# ---------------------------------------------------------------------------
# observe
# ---------------------------------------------------------------------------
def test_observar_desde_por_revisar(db_session, nuevo, actor):
    esc = nuevo()

    row, aviso = _observar(db_session, esc, actor, reason="  Libro dañado  ")

    assert row.status == "observed"
    assert row.observation_reason == "Libro dañado"
    assert row.observed_by_id == actor.id
    assert row.observed_at is not None
    assert row.cleared_via is None
    (evento,) = _events(db_session, esc.process.id, "library_observed")
    assert evento.payload["reason"] == "Libro dañado"
    assert evento.payload["from_status"] == "pending"
    assert evento.phase_number == 2
    assert aviso.call_args.kwargs["type"] == "LIBRARY_OBSERVED"
    assert aviso.call_args.kwargs["body"] == "Libro dañado"
    (correo,) = _outbox(db_session, esc.process.id, "library_observed")
    assert correo.payload["reason"] == "Libro dañado"


def test_observar_desde_en_caja_limpia_ready_at_y_conserva_montos(db_session, nuevo,
                                                                  actor):
    from datetime import datetime
    esc = nuevo(status="awaiting_payment", ready_at=datetime(2031, 3, 1, 9, 0),
                library_note="Debe un libro")

    row, _ = _observar(db_session, esc, actor)

    assert row.status == "observed"
    assert row.ready_at is None, "sale de «Por cobrar» y de los recordatorios"
    assert (row.debt_amount, row.donation_amount, row.total_amount) == (
        ADEUDO, DONACION, TOTAL)
    assert row.library_note == "Debe un libro"
    (evento,) = _events(db_session, esc.process.id, "library_observed")
    assert evento.payload["from_status"] == "awaiting_payment"
    assert LibraryClearanceService.payment_due(db_session, esc.process.id) is None


def test_observar_desde_observado_actualiza_motivo(db_session, nuevo, actor, make_user):
    esc = nuevo()
    _observar(db_session, esc, actor, reason="Primero")
    otro = make_user(first_name="BIBLIOTECA", last_name="DOS")

    row, aviso = _observar(db_session, esc, otro, reason="Segundo")

    assert row.status == "observed"
    assert row.observation_reason == "Segundo"
    assert row.observed_by_id == otro.id
    eventos = _events(db_session, esc.process.id, "library_observed")
    assert [e.payload["reason"] for e in eventos] == ["Primero", "Segundo"]
    assert eventos[-1].payload["from_status"] == "observed"
    assert aviso.call_args.kwargs["body"] == "Segundo"


def test_no_se_observa_un_liberado(db_session, nuevo, actor):
    esc = nuevo(status="cleared", cleared_via="no_charge")

    with pytest.raises(ValueError, match="revierte"):
        _observar(db_session, esc, actor)

    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "cleared"
    assert _events(db_session, esc.process.id, "library_observed") == []


@pytest.mark.parametrize("motivo", ["", "    ", "x" * 1001, None],
                         ids=["vacio", "espacios", "1001", "none"])
def test_motivo_obligatorio_y_recortado(db_session, nuevo, actor, motivo):
    esc = nuevo()

    with pytest.raises(ValueError, match="motivo"):
        _observar(db_session, esc, actor, reason=motivo)

    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "pending"
    assert _events(db_session, esc.process.id, "library_observed") == []


def test_motivo_de_1000_caracteres_si_cabe(db_session, nuevo, actor):
    esc = nuevo()
    row, _ = _observar(db_session, esc, actor, reason="  " + "x" * 1000 + "  ")
    assert row.observation_reason == "x" * 1000


def test_fase2_aprobada_no_se_observa(db_session, nuevo, actor):
    esc = nuevo(phase=3)        # fase 2 approved (make_process)

    with pytest.raises(ValueError, match="cotejo"):
        _observar(db_session, esc, actor)

    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "pending"
    assert _events(db_session, esc.process.id, "library_observed") == []
    assert _outbox(db_session, esc.process.id) == []


@pytest.mark.parametrize("estado", ["cancelled", "completed"])
def test_proceso_no_admitido_no_se_observa(db_session, nuevo, actor, estado):
    esc = nuevo(process_status=estado)

    with pytest.raises(ValueError):
        _observar(db_session, esc, actor)

    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "pending"
    assert _events(db_session, esc.process.id, "library_observed") == []


def test_en_pausa_si_se_observa(db_session, nuevo, actor):
    esc = nuevo(process_status="on_hold")
    row, _ = _observar(db_session, esc, actor)
    assert row.status == "observed"


def test_observar_id_inexistente_es_lookup(db_session, actor):
    with pytest.raises(LookupError):
        LibraryClearanceService.observe(db_session, 2_000_000_000, reason="x",
                                        actor_id=actor.id)
    with pytest.raises(LookupError):
        LibraryClearanceService.reenable(db_session, 2_000_000_000, actor_id=actor.id)


# ---------------------------------------------------------------------------
# reenable
# ---------------------------------------------------------------------------
def test_rehabilitar_vuelve_a_por_revisar_con_montos(db_session, nuevo, actor):
    esc = nuevo(status="awaiting_payment")
    _observar(db_session, esc, actor, reason="Libro dañado")

    row, aviso = _rehabilitar(db_session, esc, actor)

    assert row.status == "pending"
    assert row.observation_reason is None
    assert row.observed_by_id is None and row.observed_at is None
    assert (row.debt_amount, row.donation_amount, row.total_amount) == (
        ADEUDO, DONACION, TOTAL), "D2: precargan el formulario de registro"
    (evento,) = _events(db_session, esc.process.id, "library_reenabled")
    assert evento.payload["previous_reason"] == "Libro dañado"
    assert aviso.call_args.kwargs["type"] == "LIBRARY_REENABLED"
    assert len(_outbox(db_session, esc.process.id, "library_reenabled")) == 1


@pytest.mark.parametrize("estado, cols", [
    ("pending", {}),
    ("awaiting_payment", {}),
    ("cleared", {"cleared_via": "no_charge"}),
])
def test_rehabilitar_solo_desde_observado(db_session, nuevo, actor, estado, cols):
    esc = nuevo(status=estado, **cols)

    with pytest.raises(ValueError):
        _rehabilitar(db_session, esc, actor)

    db_session.refresh(esc.clearance)
    assert esc.clearance.status == estado
    assert _events(db_session, esc.process.id, "library_reenabled") == []


def test_rehabilitar_con_fase2_aprobada_falla(db_session, nuevo, actor):
    esc = nuevo(status="observed", phase=3, observation_reason="x")
    with pytest.raises(ValueError):
        _rehabilitar(db_session, esc, actor)
    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "observed"


def test_rehabilitar_proceso_revocado_falla(db_session, nuevo, actor):
    esc = nuevo(status="observed", process_status="cancelled", observation_reason="x")
    with pytest.raises(ValueError):
        _rehabilitar(db_session, esc, actor)


# ---------------------------------------------------------------------------
# Guardas del resto de las transiciones
# ---------------------------------------------------------------------------
def test_registrar_pagar_revertir_previa_sobre_observado_falla_claro(db_session, nuevo,
                                                                     actor):
    esc = nuevo(status="observed", observation_reason="Libro dañado")
    cid = esc.clearance.id

    intentos = [
        lambda: LibraryClearanceService.register(db_session, cid, actor.id,
                                                 debt_amount=ADEUDO),
        lambda: LibraryClearanceService.register_payment(db_session, cid, actor.id,
                                                         receipt_number="R-1"),
        lambda: LibraryClearanceService.register_payment(db_session, cid, actor.id,
                                                         expected_total=TOTAL),
        lambda: LibraryClearanceService.revert_payment(db_session, cid, actor.id, "x"),
        lambda: LibraryClearanceService.revert_clearance(db_session, cid, actor.id, "x"),
        lambda: LibraryClearanceService.undo_prior(db_session, cid, actor.id, "x"),
        lambda: LibraryClearanceService.register_prior(
            db_session, cid, actor.id, issued_on=date.today(), by="library"),
    ]
    with patch(NOTIFY):
        for intento in intentos:
            with pytest.raises(ValueError, match=MSG_OBSERVADO):
                intento()

    db_session.refresh(esc.clearance)
    assert esc.clearance.status == "observed"


def test_lote_sin_adeudo_omite_observados(db_session, nuevo, actor):
    esc = nuevo(status="observed", observation_reason="x")
    with patch(NOTIFY):
        out = LibraryClearanceService.register_no_debt_bulk(
            db_session, [esc.clearance.id], actor.id)
    assert out["done"] == 0
    assert len(out["skipped"]) == 1


def test_previa_de_un_observado_es_conflicto(db_session, nuevo):
    """La importación de constancias previas no aplica sobre una observada
    (lo decide Biblioteca) y no truena."""
    esc = nuevo(status="observed", observation_reason="x")
    assert LibraryClearanceService.prior_outcome(db_session, esc.process.id) == "conflict"


# ---------------------------------------------------------------------------
# Eventos, avisos y dominio cerrado
# ---------------------------------------------------------------------------
def test_eventos_y_notificaciones(db_session, nuevo, actor):
    assert "library_observed" in LIBRARY_EVENT_TYPES
    assert "library_reenabled" in LIBRARY_EVENT_TYPES
    assert all(len(e) <= 40 for e in LIBRARY_EVENT_TYPES)

    esc = nuevo()
    _, aviso_obs = _observar(db_session, esc, actor, reason="Libro dañado")
    _, aviso_reh = _rehabilitar(db_session, esc, actor)

    obs = aviso_obs.call_args.kwargs
    reh = aviso_reh.call_args.kwargs
    assert (obs["type"], obs["process_id"], obs["phase_number"]) == (
        "LIBRARY_OBSERVED", esc.process.id, 2)
    assert (reh["type"], reh["process_id"], reh["phase_number"]) == (
        "LIBRARY_REENABLED", esc.process.id, 2)
    assert aviso_obs.call_args.args[1] == esc.student.id
    tipos = [e.event_type for e in _events(db_session, esc.process.id, "library_observed")
             + _events(db_session, esc.process.id, "library_reenabled")]
    assert tipos == ["library_observed", "library_reenabled"]


def test_un_solo_commit_por_transicion(db_session, nuevo, actor, monkeypatch):
    esc = nuevo()
    cuenta = []
    original = db_session.commit
    monkeypatch.setattr(db_session, "commit", lambda: (cuenta.append(1), original()))
    _observar(db_session, esc, actor)
    _rehabilitar(db_session, esc, actor)
    assert len(cuenta) == 2


def test_estado_observed_en_el_modelo_y_etiqueta():
    from itcj2.apps.titulatec.models.library_clearance import LIBRARY_STATUSES
    from itcj2.apps.titulatec.services import library_clearance_service as mod

    assert LIBRARY_STATUSES == ("pending", "awaiting_payment", "observed", "cleared")
    assert mod._STATUS_LABELS["observed"] == "Con observaciones"


# ---------------------------------------------------------------------------
# Correo
# ---------------------------------------------------------------------------
def test_outbox_kinds():
    from itcj2.apps.titulatec.models.email_outbox import OUTBOX_KINDS
    from itcj2.apps.titulatec.services.mail_compose import MailComposer
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    for kind in ("library_observed", "library_reenabled"):
        assert kind in OUTBOX_KINDS
        assert kind in MailComposer.REGISTRY
        assert kind in StudentMail.KIND_LABELS


def test_compose_observed_sale_con_el_motivo_congelado(db_session, nuevo, actor):
    from itcj2.apps.titulatec.services.mail_compose import Composed

    esc = nuevo()
    _observar(db_session, esc, actor, reason="Libro <b>dañado</b>")
    (fila,) = _outbox(db_session, esc.process.id, "library_observed")

    c = _componer(db_session, esc.process, [fila])

    assert isinstance(c, Composed), c
    assert c.template == "library_observed.html"
    assert c.context["reason"] == "Libro <b>dañado</b>"
    assert c.subject.startswith("[TitulaTec ITCJ] ")


def test_compose_observed_obsolete_si_ya_rehabilitado(db_session, nuevo, actor):
    """Review Focus 4: observado y rehabilitado antes del despacho -> el
    aviso de observación no sale."""
    from itcj2.apps.titulatec.services.mail_compose import Obsolete

    esc = nuevo()
    _observar(db_session, esc, actor)
    _rehabilitar(db_session, esc, actor)
    (fila,) = _outbox(db_session, esc.process.id, "library_observed")

    assert isinstance(_componer(db_session, esc.process, [fila]), Obsolete)


def test_compose_observed_obsolete_si_hay_una_observacion_mas_nueva(db_session, nuevo,
                                                                    actor):
    from itcj2.apps.titulatec.services.mail_compose import Composed, Obsolete

    esc = nuevo()
    _observar(db_session, esc, actor, reason="Primero")
    _observar(db_session, esc, actor, reason="Segundo")
    vieja, nueva = _outbox(db_session, esc.process.id, "library_observed")

    assert isinstance(_componer(db_session, esc.process, [vieja]), Obsolete)
    c = _componer(db_session, esc.process, [nueva])
    assert isinstance(c, Composed) and c.context["reason"] == "Segundo"


def test_compose_reenabled(db_session, nuevo, actor):
    from itcj2.apps.titulatec.services.mail_compose import Composed

    esc = nuevo()
    _observar(db_session, esc, actor)
    _rehabilitar(db_session, esc, actor)
    (fila,) = _outbox(db_session, esc.process.id, "library_reenabled")

    c = _componer(db_session, esc.process, [fila])

    assert isinstance(c, Composed), c
    assert c.template == "library_reenabled.html"


def test_compose_reenabled_obsolete_si_volvio_a_observarse(db_session, nuevo, actor):
    from itcj2.apps.titulatec.services.mail_compose import Obsolete

    esc = nuevo()
    _observar(db_session, esc, actor)
    _rehabilitar(db_session, esc, actor)
    _observar(db_session, esc, actor, reason="Otra vez")
    (fila,) = _outbox(db_session, esc.process.id, "library_reenabled")

    assert isinstance(_componer(db_session, esc.process, [fila]), Obsolete)


def test_plantillas_renderizan_y_escapan(db_session, nuevo, actor):
    from itcj2.apps.titulatec.pages.nav import titulatec_templates

    esc = nuevo()
    _observar(db_session, esc, actor, reason="Libro <script>x</script>")
    (obs,) = _outbox(db_session, esc.process.id, "library_observed")
    c = _componer(db_session, esc.process, [obs])
    html = titulatec_templates.get_template(f"titulatec/email/{c.template}").render(
        **c.context)
    assert "<script>x</script>" not in html
    assert "Biblioteca" in html

    _rehabilitar(db_session, esc, actor)
    (reh,) = _outbox(db_session, esc.process.id, "library_reenabled")
    c = _componer(db_session, esc.process, [reh])
    html = titulatec_templates.get_template(f"titulatec/email/{c.template}").render(
        **c.context)
    assert "continuar" in html


# ---------------------------------------------------------------------------
# Bandeja
# ---------------------------------------------------------------------------
def test_por_revisar_no_cuenta_observados(db_session, nuevo, actor, token):
    base = nuevo(last_name=token)
    obs = nuevo(cohort=base.cohort, last_name=token)
    _observar(db_session, obs, actor)

    counts = LibraryClearanceService.counts_by_status(db_session, q=token)
    pendientes = LibraryClearanceService.list_for_inbox(
        db_session, status="pending", q=token).items

    assert counts["pending"] == 1
    assert [f["id"] for f in pendientes] == [base.clearance.id]


def test_pestana_observed_lista_y_cuenta(db_session, nuevo, actor, token):
    primero = nuevo(last_name=token)
    segundo = nuevo(cohort=primero.cohort, last_name=token, status="awaiting_payment")
    nuevo(cohort=primero.cohort, last_name=token)
    _observar(db_session, primero, actor, reason="Primero")
    _observar(db_session, segundo, actor, reason="Segundo")
    # Orden observed_at DESC: el segundo se observó después (mismo NOW() en
    # una transacción -> desempata el id DESC; aquí van en commits distintos).
    from datetime import datetime
    primero.clearance.observed_at = datetime(2031, 1, 1, 9, 0)
    segundo.clearance.observed_at = datetime(2031, 1, 2, 9, 0)
    db_session.flush()

    counts = LibraryClearanceService.counts_by_status(db_session, q=token)
    pagina = LibraryClearanceService.list_for_inbox(
        db_session, status="observed", q=token)

    assert set(counts) == {"pending", "awaiting_payment", "observed", "cleared"}
    assert counts["observed"] == 2
    assert counts["pending"] == 1
    assert counts["awaiting_payment"] == 0
    assert [f["id"] for f in pagina.items] == [segundo.clearance.id, primero.clearance.id]
    fila = pagina.items[0]
    assert fila["status"] == "observed"
    assert fila["observation_reason"] == "Segundo"
    assert fila["observed_at"] == datetime(2031, 1, 2, 9, 0)
    assert fila["observed_by"] == actor.full_name
    assert fila["total"] == TOTAL


def test_resumen_trae_la_observacion(db_session, nuevo, actor):
    esc = nuevo()
    _observar(db_session, esc, actor, reason="Libro dañado")
    resumen = LibraryClearanceService.summary_for_process(db_session, esc.process.id)
    assert resumen["status"] == "observed"
    assert resumen["observation"] == "Libro dañado"
    assert resumen["observed_at"] is not None


def test_observada_de_proceso_revocado_ni_se_lista_ni_se_cuenta(db_session, nuevo, actor, token):
    """Mismo filtro de admitidos que las otras pestañas de trabajo: reenable lo
    exige, así que un proceso revocado no se queda en la pestaña sin acciones."""
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    nuevo(status="observed", process_status="cancelled", observation_reason="x",
          last_name=token)

    page = LibraryClearanceService.list_for_inbox(db_session, status="observed", q=token)
    assert [r["id"] for r in page.items] == []
    assert LibraryClearanceService.counts_by_status(db_session, token)["observed"] == 0
