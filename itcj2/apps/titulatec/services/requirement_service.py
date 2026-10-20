"""Cumplimientos de los requisitos de cotejo, por proceso.

`CotejoRequirementService` administra la LISTA de la convocatoria (qué se pide).
Este service administra la otra mitad: QUIÉN ya lo entregó. Son dos tablas y dos
services a propósito — la lista es de la convocatoria y los cumplimientos son del
proceso, y el requisito se borra con `ON DELETE RESTRICT` justamente para que
borrar la lista no destruya el crédito de quien ya cumplió.

Reglas fijas:

* **Ausencia de fila = pendiente.** No existe un estado `pending` almacenado.
* Estados: `fulfilled` (lo trajo), `waived` (dispensa con nota) y `rejected`.
  Los dos primeros cuentan como cumplido; `rejected` no.
* **Toda escritura deja `ProcessEvent`** (`requirement_fulfilled` /
  `requirement_unfulfilled`, ambos < 40 chars). El `_log` de aquí es gemelo del
  de `DocumentService` (`document_service.py:11-29`): NO commitea, lo hace el
  método dueño de la transacción justo antes de su `commit()`.
* Los métodos aceptan `commit=False` porque el envío de la encuesta escribe
  respuesta, respuestas y cumplimiento en UNA sola transacción.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from itcj2.core.utils.timezone import db_now

# La cita de cotejo es la fase 2 del catálogo (`titulatec_phase_definitions`).
# Los eventos se cuelgan de ella para que salgan en el acordeón del expediente.
PHASE_COTEJO = 2

# Un cumplimiento cuenta si está entregado o dispensado. `rejected` NO cuenta:
# es "lo trajo y no sirve", que es exactamente lo que debe seguir bloqueando.
DONE_STATUSES = ("fulfilled", "waived")


class RequirementService:
    # ----------------------------------------------------------------- bitácora
    @staticmethod
    def _log(db: Session, process_id: int, actor_id: int | None,
             event_type: str, payload: dict | None = None) -> None:
        """Escribe un `ProcessEvent`. **No commitea** (gemelo de `DocumentService._log`)."""
        from itcj2.apps.titulatec.models import ProcessEvent
        db.add(ProcessEvent(
            process_id=process_id, actor_id=actor_id, event_type=event_type,
            phase_number=PHASE_COTEJO, payload=payload,
        ))

    # ------------------------------------------------------------------ lectura
    @staticmethod
    def list_with_status(db: Session, process_id: int) -> list[dict]:
        """Requisitos ACTIVOS de su convocatoria + lo que ya tiene acreditado.

        Usa `list_or_seed` porque una convocatoria sin requisitos configurados
        dejaría al alumno con la pantalla vacía y sin nada que acreditar (§5.2
        del diseño). Los cumplimientos se traen en UNA consulta, no una por
        requisito.
        """
        from itcj2.apps.titulatec.models import RequirementFulfillment, TitulationProcess
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )

        proc = db.get(TitulationProcess, process_id)
        if proc is None:
            return []
        reqs = CotejoRequirementService.list_or_seed(db, proc.cohort_id, active_only=True)
        hechos = {
            f.requirement_id: f for f in
            db.query(RequirementFulfillment).filter_by(process_id=process_id).all()
        }
        out = []
        for r in reqs:
            f = hechos.get(r.id)
            out.append({
                "requirement": r,
                "fulfillment": f,
                "is_done": bool(f is not None and f.status in DONE_STATUSES),
            })
        return out

    @staticmethod
    def missing_required(db: Session, process_id: int) -> list:
        """Requisitos ACTIVOS y OBLIGATORIOS que ese proceso todavía no cumple.

        Deliberadamente NO siembra: es lo que lee la guarda de la fase 2
        (`PhaseService.approve_phase`) y sembrar dentro de un dictamen escribiría
        requisitos nuevos en medio de la transacción de otro. La siembra ocurre
        al crear la convocatoria y al acreditar la encuesta.
        """
        from itcj2.apps.titulatec.models import (
            CotejoRequirement, RequirementFulfillment, TitulationProcess,
        )

        proc = db.get(TitulationProcess, process_id)
        if proc is None:
            return []
        reqs = (db.query(CotejoRequirement)
                .filter_by(cohort_id=proc.cohort_id, is_active=True, is_required=True)
                .order_by(CotejoRequirement.order_index, CotejoRequirement.id)
                .all())
        if not reqs:
            return []
        ok_ids = {
            rid for (rid,) in
            db.query(RequirementFulfillment.requirement_id)
            .filter(RequirementFulfillment.process_id == process_id,
                    RequirementFulfillment.status.in_(DONE_STATUSES))
            .all()
        }
        return [r for r in reqs if r.id not in ok_ids]

    @staticmethod
    def auto_requirement(db: Session, cohort_id: int, auto_source: str):
        """Requisito ACTIVO de esa convocatoria con ese `auto_source`, o None.

        **Seed-or-list SIN commit.** Si la convocatoria no tiene lista todavía se
        siembra la de por defecto en la misma transacción del llamador: sin esto,
        un alumno en fase 1 que contesta la encuesta —el caso mayoritario, porque
        la encuesta se promueve en público— perdería el crédito en silencio.
        """
        from itcj2.apps.titulatec.models import CotejoRequirement
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )

        existe = db.query(CotejoRequirement).filter_by(cohort_id=cohort_id).first()
        if existe is None:
            CotejoRequirementService.seed_defaults(db, cohort_id, commit=False)
        return (db.query(CotejoRequirement)
                .filter_by(cohort_id=cohort_id, auto_source=auto_source, is_active=True)
                .order_by(CotejoRequirement.order_index, CotejoRequirement.id)
                .first())

    # ----------------------------------------------------------------- escritura
    @staticmethod
    def fulfill(db: Session, process_id: int, requirement_id: int, *,
                source: str, checked_by_id: int | None = None,
                external_ref: str | None = None, note: str | None = None,
                status: str = "fulfilled", commit: bool = True):
        """Marca el requisito como cumplido/dispensado. Idempotente.

        Idempotente en lo que importa: el `UNIQUE (process_id, requirement_id)`
        garantiza que nunca haya dos filas, y una llamada que no cambia NADA no
        escribe ni deja evento, para no ensuciar la bitácora. Pero repetir la
        llamada CON algo nuevo —otra nota, otro `external_ref`, otro estado— sí
        actualiza y sí deja evento: el `mark` del encargado manda la nota en cada
        envío, y tragársela en silencio (sin dato, sin evento y sin error) es
        peor que un renglón de más en la bitácora.

        `note`, `external_ref` y `checked_by_id` en `None` significan "el
        llamador no los manda", NO "bórralos": una segunda pasada sin nota no
        debe borrar la que ya estaba. Para vaciar una nota hay que `unfulfill()`
        y volver a `fulfill()`.

        `fulfilled_at` es *cuándo quedó acreditado ASÍ*: se sella al dar de alta
        y se vuelve a sellar cuando cambia el estado, porque esa fecha se le
        muestra al encargado y "dispensado el <día en que se marcó como traído>"
        sería mentira. Corregir solo la nota no la mueve.

        `label_snapshot` y `requirement_code` se copian a propósito: si mañana
        Servicios Escolares renombra el requisito, la bitácora debe seguir
        diciendo qué se acreditó.
        """
        from itcj2.apps.titulatec.models import CotejoRequirement, RequirementFulfillment

        req = db.get(CotejoRequirement, requirement_id)
        row = (db.query(RequirementFulfillment)
               .filter_by(process_id=process_id, requirement_id=requirement_id)
               .first())

        # Solo lo que el llamador mandó de verdad (ver docstring).
        opcionales = {campo: valor for campo, valor in (
            ("note", note), ("external_ref", external_ref),
            ("checked_by_id", checked_by_id)) if valor is not None}

        if row is None:
            cambia_estado = True
            row = RequirementFulfillment(process_id=process_id,
                                         requirement_id=requirement_id)
            db.add(row)
        else:
            cambia_estado = row.status != status
            if not cambia_estado and all(getattr(row, campo) == valor
                                         for campo, valor in opcionales.items()):
                return row

        row.status = status
        row.source = source
        for campo, valor in opcionales.items():
            setattr(row, campo, valor)
        row.requirement_code = getattr(req, "code", None)
        row.label_snapshot = (req.label[:120] if req is not None else None)
        if cambia_estado:
            row.fulfilled_at = db_now()
        db.flush()

        # El payload describe el estado RESULTANTE, no solo los argumentos: si la
        # encuesta acreditó y el encargado luego anota, el evento debe seguir
        # trayendo el `external_ref` de la encuesta.
        RequirementService._log(db, process_id, checked_by_id, "requirement_fulfilled", {
            "requirement_id": requirement_id,
            "code": row.requirement_code,
            "label": row.label_snapshot,
            "status": status,
            "source": source,
            "external_ref": row.external_ref,
            "note": row.note,
        })
        if commit:
            db.commit()
        return row

    @staticmethod
    def unfulfill(db: Session, process_id: int, requirement_id: int, *,
                  actor_id: int, commit: bool = True) -> bool:
        """Quita el cumplimiento. `False` si no había nada que quitar.

        Se BORRA la fila (ausencia = pendiente) y el rastro queda en el evento:
        por eso el payload lleva el estado y el origen previos, que es lo único
        que sobrevive al borrado.
        """
        from itcj2.apps.titulatec.models import RequirementFulfillment

        row = (db.query(RequirementFulfillment)
               .filter_by(process_id=process_id, requirement_id=requirement_id)
               .first())
        if row is None:
            return False
        payload = {
            "requirement_id": requirement_id,
            "code": row.requirement_code,
            "label": row.label_snapshot,
            "status_previo": row.status,
            "source_previo": row.source,
        }
        db.delete(row)
        RequirementService._log(db, process_id, actor_id, "requirement_unfulfilled", payload)
        if commit:
            db.commit()
        return True
