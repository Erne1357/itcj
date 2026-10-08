"""Recuperación de decisiones previas a la bitácora (2026-10-08).

Antes del despliegue de la bitácora (2026-10-07), aprobar, rechazar, devolver o
reabrir una solicitud de inscripción NO dejaba evento: solo columnas de
`titulatec_enrollment_requests` (`reviewed_*`, `returned_*`, `reopened_*`), que
además se pisan entre sí (queda solo la última de cada tipo). Este servicio
vuelve a escribir esas decisiones como filas `source='action'` con la fecha
ORIGINAL de la columna, para que «Ver bitácora» de un alumno diga quién le
aprobó la solicitud.

Por qué NO usa `AuditService.record`: esa API fecha la fila con el reloj de la
base («ahora») y aquí hace falta la fecha original. Se construye el modelo
directo, pero el saneo (`AuditService.safe`) y el vocabulario (`AUDIT_ACTIONS`)
son los mismos de siempre.

Reglas (una fila por decisión que las columnas todavía conservan):

- `enrollment.approved`: `reviewed_by_id` y estado en {approved,
  awaiting_access, converted}.
- `enrollment.rejected`: `reviewed_by_id` y estado `rejected`.
- `access.returned`: `returned_by_id` (motivo = `return_note`).
- `enrollment.reopened`: `reopened_by_id` (motivo = `reopen_note`).
- NO se recupera el acceso de Centro de Cómputo (`access_granted_*`): ya lo
  cubre el `enrollment_self_service` del proceso.

Reabrir y devolver dejan `reviewed_*` con la revisión ANTERIOR, así que el
estado actual no basta para saber qué fue esa revisión:

- Solo se reabre una `rejected`. Si `reopened_at` existe y
  `reviewed_at < reopened_at`, la revisión guardada es el rechazo que se
  deshizo: se registra como `enrollment.rejected` aunque el estado sea otro. Si
  `reviewed_at >= reopened_at` hubo una revisión posterior a la reapertura y
  manda el estado actual.
- Solo se devuelve una `awaiting_access`, estado al que se llega aprobando. Si
  el estado actual no es decisivo (p. ej. `pending_review`) y
  `returned_at` existe con `reviewed_at <= returned_at`, la revisión fue la
  aprobación que se devolvió: se registra como `enrollment.approved`.
- Cualquier otro caso con estado no decisivo no se inventa: sin fila.

Solo lo ANTERIOR a la bitácora (corte): `cutoff` = el `occurred_at` más viejo
de una fila `action`/`data` que NO sea recuperada (`payload.backfilled`); sin
filas vivas, «ahora». Toda decisión cuya propia fecha (`reviewed_at`,
`returned_at`, `reopened_at`) sea >= corte ya tiene su fila en vivo (acción
explícita o el espejo `enrollment_self_service` de las aprobaciones que crean
cuenta) y NO se recupera. Una decisión con `*_by_id` pero sin fecha se salta y
se cuenta en `skipped_no_date`: nunca se fecha con «ahora» (sería permanente y
falso).

Idempotente: se salta toda `(action, entity_id)` que ya exista como fila
RECUPERADA por este servicio (`payload.recovered_from`). NO se compara contra
filas en vivo: con el corte, una fila en vivo nunca representa una decisión
previa (p. ej. la aprobación de Centro de Cómputo no debe tapar la de Servicios
Escolares anterior al despliegue). Tres SELECT en total (corte, solicitudes y
recuperadas), sin N+1, y un único INSERT por lote. No hace commit.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, or_

logger = logging.getLogger(__name__)

ACCIONES = ("enrollment.approved", "enrollment.rejected",
            "access.returned", "enrollment.reopened")

_APROBADA = frozenset({"approved", "awaiting_access", "converted"})
_ENTITY = "enrollment_request"


def _clasifica_revision(r) -> str | None:
    """`enrollment.approved` / `enrollment.rejected` / `None` para la revisión
    guardada en `reviewed_*` (ver las reglas en el docstring del módulo)."""
    if r.reviewed_by_id is None:
        return None
    if r.status == "rejected":
        return "enrollment.rejected"
    if r.reopened_at is not None and r.reviewed_at is not None \
            and r.reviewed_at < r.reopened_at:
        return "enrollment.rejected"
    if r.status in _APROBADA:
        return "enrollment.approved"
    if r.returned_at is not None and r.reviewed_at is not None \
            and r.reviewed_at <= r.returned_at:
        return "enrollment.approved"
    return None


class AuditBackfillService:
    """Rellena la bitácora con lo que las columnas de negocio todavía saben."""

    @staticmethod
    def cutoff(db):
        """Instante desde el que la bitácora ya registra en vivo (ver módulo)."""
        from itcj2.apps.titulatec.models import TitulatecAuditLog
        from itcj2.core.utils.timezone import db_now

        L = TitulatecAuditLog
        primero = (db.query(func.min(L.occurred_at))
                   .filter(L.source.in_(("action", "data")),
                           func.coalesce(L.payload["backfilled"].as_string(), "") != "true")
                   .scalar())
        return primero if primero is not None else db_now()

    @staticmethod
    def enrollment_decisions(db, *, dry_run: bool) -> dict[str, int]:
        """Recupera las decisiones de solicitudes. Devuelve el conteo por acción.

        Con `dry_run=True` cuenta lo mismo que insertaría, sin escribir. No hace
        commit (ni flush en dry-run). La llave extra `skipped_no_date` cuenta las
        decisiones sin fecha que se saltaron.
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest, TitulatecAuditLog
        from itcj2.apps.titulatec.services.audit_actions import AUDIT_ACTIONS
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.enrollment_request_service import _audit_subject

        R = EnrollmentRequest
        solicitudes = (
            db.query(R.id, R.status, R.control_number, R.first_name, R.middle_name,
                     R.last_name, R.converted_process_id,
                     R.reviewed_by_id, R.reviewed_at, R.review_note,
                     R.returned_by_id, R.returned_at, R.return_note,
                     R.reopened_by_id, R.reopened_at, R.reopen_note)
            .filter(or_(R.reviewed_by_id.isnot(None), R.returned_by_id.isnot(None),
                        R.reopened_by_id.isnot(None)))
            .order_by(R.id).all())

        # Lo que la bitácora ya trae (en vivo o de una corrida previa): un SELECT.
        corte = AuditBackfillService.cutoff(db)
        existentes = {
            (a, e) for a, e in db.query(TitulatecAuditLog.action, TitulatecAuditLog.entity_id)
            .filter(TitulatecAuditLog.entity_type == _ENTITY,
                    TitulatecAuditLog.action.in_(ACCIONES),
                    TitulatecAuditLog.payload["recovered_from"].as_string() == _ENTITY)}

        conteo = {a: 0 for a in ACCIONES}
        conteo["skipped_no_date"] = 0
        filas: list = []

        def _agrega(r, action, actor_id, cuando, motivo):
            if cuando is None:
                conteo["skipped_no_date"] += 1
                return
            if cuando >= corte or (action, r.id) in existentes:
                return
            existentes.add((action, r.id))
            conteo[action] += 1
            cols = dict(
                occurred_at=cuando,  # fecha ORIGINAL de la columna
                source="action", action=action, module=AUDIT_ACTIONS[action][0],
                actor_id=actor_id, actor_kind="user",
                entity_type=_ENTITY, entity_id=r.id,
                process_id=r.converted_process_id,
                subject_label=_audit_subject(r)[:160],
                reason=(AuditService.safe(motivo) or None) if motivo else None,
                payload=AuditService.safe({
                    "backfilled": True, "request_id": r.id,
                    "recovered_from": _ENTITY, "status_at_backfill": r.status}),
            )
            filas.append(TitulatecAuditLog(**cols))

        for r in solicitudes:
            revision = _clasifica_revision(r)
            if revision is not None:
                motivo = r.review_note if revision == "enrollment.rejected" else None
                _agrega(r, revision, r.reviewed_by_id, r.reviewed_at, motivo)
            if r.returned_by_id is not None:
                _agrega(r, "access.returned", r.returned_by_id, r.returned_at, r.return_note)
            if r.reopened_by_id is not None:
                _agrega(r, "enrollment.reopened", r.reopened_by_id, r.reopened_at,
                        r.reopen_note)

        if filas and not dry_run:
            db.add_all(filas)
            db.flush()
        logger.info("bitácora: decisiones de solicitudes %s: %s",
                    "(dry-run)" if dry_run else "recuperadas", conteo)
        return conteo
