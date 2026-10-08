"""Recuperación de las decisiones de solicitudes anteriores a la bitácora.

`AuditBackfillService.enrollment_decisions` lee las columnas `reviewed_*`,
`returned_*` y `reopened_*` de `titulatec_enrollment_requests` y escribe UNA fila
`source='action'` por decisión, con la fecha ORIGINAL. Idempotente: no duplica lo
que la bitácora ya trae (filas en vivo o una corrida previa).

La base de dev ya trae solicitudes reales con esas columnas: el servicio las
recupera TAMBIÉN en estas pruebas (todo dentro de la transacción del test, que
se revierte), así que cada aserción mira solo las filas de las solicitudes que
siembra la propia prueba (`entity_id`), nunca totales.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from click.testing import CliRunner

from itcj2.apps.titulatec.models import TitulatecAuditLog
from tests.fastapi.titulatec.conftest import audit_query

pytestmark = pytest.mark.usefixtures("audit_mark")

_ACCIONES = ("enrollment.approved", "enrollment.rejected",
             "access.returned", "enrollment.reopened")


def _svc():
    from itcj2.apps.titulatec.services.audit_backfill_service import AuditBackfillService
    return AuditBackfillService


def _make_req(db, cohort, *, control, status, **kw):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="ANA", last_name="RECUPERADA", middle_name="LUZ",
        program_text="Ingenieria Ficticia", phone="6561234567",
        contact_email="recuperada@example.invalid", has_efirma=False,
        kind="unknown", status=status, verify_send_count=0)
    for k, v in kw.items():
        setattr(row, k, v)
    db.add(row)
    db.flush()
    return row


def _filas(db, req):
    return (audit_query(db)
            .filter(TitulatecAuditLog.source == "action",
                    TitulatecAuditLog.entity_type == "enrollment_request",
                    TitulatecAuditLog.entity_id == req.id)
            .order_by(TitulatecAuditLog.id).all())


def _por_accion(db, req):
    return {f.action: f for f in _filas(db, req)}


@pytest.fixture()
def cohorte(make_cohort):
    return make_cohort(status="open")


def test_aprobada_deja_una_fila_con_actor_fecha_y_proceso(
        patched_session_local, cohorte, make_user, make_process):
    db = patched_session_local
    revisor = make_user()
    proceso = make_process(make_user(), cohorte)
    cuando = datetime(2026, 9, 1, 10, 30)
    req = _make_req(db, cohorte, control="99210001", status="converted",
                    reviewed_by_id=revisor.id, reviewed_at=cuando,
                    converted_process_id=proceso.id)

    _svc().enrollment_decisions(db, dry_run=False)

    filas = _filas(db, req)
    assert [f.action for f in filas] == ["enrollment.approved"]
    f = filas[0]
    assert f.source == "action" and f.actor_kind == "user"
    assert f.actor_id == revisor.id
    assert f.occurred_at == cuando
    assert f.module == "enrollment"
    assert f.entity_type == "enrollment_request" and f.entity_id == req.id
    assert f.process_id == proceso.id
    assert f.subject_label == "99210001 · RECUPERADA LUZ ANA"
    assert f.payload["backfilled"] is True
    assert f.payload["request_id"] == req.id
    assert f.payload["recovered_from"] == "enrollment_request"
    assert f.payload["status_at_backfill"] == "converted"


@pytest.mark.parametrize("estado", ["approved", "awaiting_access", "converted"])
def test_aprobada_en_cualquiera_de_sus_tres_estados(
        patched_session_local, cohorte, make_user, estado):
    db = patched_session_local
    req = _make_req(db, cohorte, control="99210002", status=estado,
                    reviewed_by_id=make_user().id, reviewed_at=datetime(2026, 9, 2, 8, 0))

    _svc().enrollment_decisions(db, dry_run=False)

    assert list(_por_accion(db, req)) == ["enrollment.approved"]


def test_rechazada_guarda_el_motivo(patched_session_local, cohorte, make_user):
    db = patched_session_local
    revisor = make_user()
    cuando = datetime(2026, 9, 3, 12, 0)
    req = _make_req(db, cohorte, control="99210003", status="rejected",
                    reviewed_by_id=revisor.id, reviewed_at=cuando,
                    review_note="Documento ilegible")

    _svc().enrollment_decisions(db, dry_run=False)

    f = _por_accion(db, req)["enrollment.rejected"]
    assert f.reason == "Documento ilegible"
    assert f.actor_id == revisor.id and f.occurred_at == cuando
    assert f.payload["status_at_backfill"] == "rejected"


def test_devuelta_a_revision(patched_session_local, cohorte, make_user):
    db = patched_session_local
    quien = make_user()
    cuando = datetime(2026, 9, 4, 9, 15)
    req = _make_req(db, cohorte, control="99210004", status="pending_review",
                    returned_by_id=quien.id, returned_at=cuando,
                    return_note="Faltaba aclarar el NIP")

    _svc().enrollment_decisions(db, dry_run=False)

    filas = _por_accion(db, req)
    assert list(filas) == ["access.returned"]
    f = filas["access.returned"]
    assert f.module == "access"
    assert f.reason == "Faltaba aclarar el NIP"
    assert f.actor_id == quien.id and f.occurred_at == cuando


def test_devuelta_conserva_la_aprobacion_que_la_precedio(
        patched_session_local, cohorte, make_user):
    """Devolver exige `awaiting_access`, que solo se alcanza aprobando: con
    `reviewed_at <= returned_at` y estado `pending_review`, la revisión fue una
    aprobación y no se pierde."""
    db = patched_session_local
    revisor, quien = make_user(), make_user()
    req = _make_req(db, cohorte, control="99210005", status="pending_review",
                    reviewed_by_id=revisor.id, reviewed_at=datetime(2026, 9, 4, 8, 0),
                    returned_by_id=quien.id, returned_at=datetime(2026, 9, 4, 9, 0),
                    return_note="x")

    _svc().enrollment_decisions(db, dry_run=False)

    assert set(_por_accion(db, req)) == {"enrollment.approved", "access.returned"}


def test_rechazo_y_reapertura(patched_session_local, cohorte, make_user):
    """Rechazada y luego reabierta: queda `pending_review` con `reviewed_*` del
    rechazo. `reviewed_at < reopened_at` => la revisión fue un RECHAZO."""
    db = patched_session_local
    revisor, reabre = make_user(), make_user()
    req = _make_req(db, cohorte, control="99210006", status="pending_review",
                    reviewed_by_id=revisor.id, reviewed_at=datetime(2026, 9, 5, 9, 0),
                    review_note="Datos incompletos",
                    reopened_by_id=reabre.id, reopened_at=datetime(2026, 9, 6, 9, 0),
                    reopen_note="Aclaró en ventanilla")

    _svc().enrollment_decisions(db, dry_run=False)

    filas = _por_accion(db, req)
    assert set(filas) == {"enrollment.rejected", "enrollment.reopened"}
    assert filas["enrollment.rejected"].actor_id == revisor.id
    assert filas["enrollment.rejected"].reason == "Datos incompletos"
    assert filas["enrollment.rejected"].occurred_at == datetime(2026, 9, 5, 9, 0)
    assert filas["enrollment.reopened"].actor_id == reabre.id
    assert filas["enrollment.reopened"].reason == "Aclaró en ventanilla"
    assert filas["enrollment.reopened"].occurred_at == datetime(2026, 9, 6, 9, 0)


def test_reabierta_y_luego_aprobada_se_decide_por_el_estado_actual(
        patched_session_local, cohorte, make_user):
    """`reviewed_at > reopened_at`: la revisión es la posterior a la reapertura;
    aplica la regla por estado (aprobada), y la reapertura se registra igual."""
    db = patched_session_local
    revisor, reabre = make_user(), make_user()
    req = _make_req(db, cohorte, control="99210007", status="awaiting_access",
                    reviewed_by_id=revisor.id, reviewed_at=datetime(2026, 9, 8, 9, 0),
                    reopened_by_id=reabre.id, reopened_at=datetime(2026, 9, 7, 9, 0),
                    reopen_note="ok")

    _svc().enrollment_decisions(db, dry_run=False)

    assert set(_por_accion(db, req)) == {"enrollment.approved", "enrollment.reopened"}


def test_no_registra_el_acceso_de_centro_de_computo(patched_session_local, cohorte, make_user):
    db = patched_session_local
    req = _make_req(db, cohorte, control="99210008", status="pending_review",
                    access_granted_by_id=make_user().id,
                    access_granted_at=datetime(2026, 9, 9, 9, 0))

    _svc().enrollment_decisions(db, dry_run=False)

    assert _filas(db, req) == []


def test_sin_reviewed_by_id_no_hay_fila_de_revision(patched_session_local, cohorte, make_user):
    db = patched_session_local
    a = _make_req(db, cohorte, control="99210009", status="converted",
                  reviewed_at=datetime(2026, 9, 9, 9, 0))
    b = _make_req(db, cohorte, control="99210010", status="rejected",
                  reviewed_at=datetime(2026, 9, 9, 9, 0), review_note="x")

    _svc().enrollment_decisions(db, dry_run=False)

    assert _filas(db, a) == [] and _filas(db, b) == []


def test_no_duplica_una_fila_en_vivo(patched_session_local, cohorte, make_user):
    from itcj2.apps.titulatec.services.audit_service import AuditService

    db = patched_session_local
    revisor = make_user()
    req = _make_req(db, cohorte, control="99210011", status="awaiting_access",
                    reviewed_by_id=revisor.id, reviewed_at=datetime(2026, 9, 10, 9, 0))
    AuditService.record(db, "enrollment.approved", entity_type="enrollment_request",
                        entity_id=req.id, actor_id=revisor.id)
    db.flush()

    _svc().enrollment_decisions(db, dry_run=False)

    filas = _filas(db, req)
    assert len(filas) == 1
    assert not (filas[0].payload or {}).get("backfilled")


def test_segunda_corrida_no_inserta_nada(patched_session_local, cohorte, make_user):
    db = patched_session_local
    req = _make_req(db, cohorte, control="99210012", status="converted",
                    reviewed_by_id=make_user().id, reviewed_at=datetime(2026, 9, 11, 9, 0))

    primera = _svc().enrollment_decisions(db, dry_run=False)
    db.flush()
    segunda = _svc().enrollment_decisions(db, dry_run=False)

    assert primera["enrollment.approved"] >= 1
    assert segunda == {a: 0 for a in _ACCIONES}
    assert len(_filas(db, req)) == 1


def test_dry_run_cuenta_y_no_escribe(patched_session_local, cohorte, make_user):
    db = patched_session_local
    req = _make_req(db, cohorte, control="99210013", status="converted",
                    reviewed_by_id=make_user().id, reviewed_at=datetime(2026, 9, 12, 9, 0))

    seco = _svc().enrollment_decisions(db, dry_run=True)
    db.flush()

    assert seco["enrollment.approved"] >= 1
    assert _filas(db, req) == []
    real = _svc().enrollment_decisions(db, dry_run=False)
    assert real == seco


def test_sin_n_mas_uno_las_sentencias_no_crecen_por_solicitud(
        patched_session_local, cohorte, make_user):
    from sqlalchemy import event

    db = patched_session_local
    revisor = make_user()

    def _cuenta():
        n = {"v": 0}

        def _hook(conn, cursor, statement, *a):
            if statement.lstrip().upper().startswith("SELECT"):
                n["v"] += 1
        eng = db.get_bind()
        event.listen(eng, "before_cursor_execute", _hook)
        try:
            _svc().enrollment_decisions(db, dry_run=True)
        finally:
            event.remove(eng, "before_cursor_execute", _hook)
        return n["v"]

    _make_req(db, cohorte, control="99210020", status="converted",
              reviewed_by_id=revisor.id, reviewed_at=datetime(2026, 9, 12, 9, 0))
    uno = _cuenta()
    for i in range(15):
        _make_req(db, cohorte, control=f"9921{i + 30:04d}", status="converted",
                  reviewed_by_id=revisor.id, reviewed_at=datetime(2026, 9, 12, 9, 0))
    assert _cuenta() == uno


def test_comando_cli_dry_run_y_real(patched_session_local, cohorte, make_user):
    from itcj2.cli import titulatec as cli

    db = patched_session_local
    req = _make_req(db, cohorte, control="99210014", status="rejected",
                    reviewed_by_id=make_user().id, reviewed_at=datetime(2026, 9, 13, 9, 0),
                    review_note="no")

    res = CliRunner().invoke(cli.titulatec_cli, ["audit-backfill-solicitudes", "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "[DRY-RUN]" in res.output
    assert "enrollment.rejected" in res.output
    assert _filas(db, req) == []

    res = CliRunner().invoke(cli.titulatec_cli, ["audit-backfill-solicitudes"])
    assert res.exit_code == 0, res.output
    assert [f.action for f in _filas(db, req)] == ["enrollment.rejected"]
