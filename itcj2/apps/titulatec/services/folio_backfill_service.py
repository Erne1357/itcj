"""Backfill de folios para las previas y el legado (spec
`2026-10-05-titulatec-folios-design.md` §3.4, D5/D6, invariante 3).

Desde la Tarea 2 de ese plan, `SurveyReviewService.register_prior` y
`LibraryClearanceService.register_prior` emiten su folio al registrar (y
`undo_prior`/`revoke`/`revert_clearance` lo anulan). Quedan SIN folio dos
grupos que ese código nunca ve:

* las previas registradas ANTES de la Tarea 2 (p. ej. las 372 importadas del
  Excel de Forms en dev);
* el no adeudo `cleared/legacy`, que no lo escribe ningún servicio sino el SQL
  de la migración `tt20261001a` y la promoción D17 de
  `titulatec activar-biblioteca-caja`.

`FolioBackfillService.candidates` las lista y `run` las folia con
`CertificateService.issue(actor_id=None, semester=previous_semester_key(ancla))`
(misma regla de D5/D6: el semestre ANTERIOR al de la fecha de registro). Es
idempotente: una liberación con folio VIGENTE ya no es candidata, así que una
segunda corrida da 0. Lo usa el comando `titulatec emitir-folios-previos` y el
paso «folios de previas y legado» de `activar-biblioteca-caja`.

Concurrencia: la corrida real BLOQUEA las filas fuente (`FOR UPDATE OF`) y
re-verifica cada una justo antes de emitir. Sin eso, un `revert_clearance` (o
`undo_prior`/`revoke`) que commitea entre la lista y la emisión dejaba un folio
VIVO sobre una fila ya no liberada, y la siguiente liberación legítima de esa
fila daba 500 contra `uq_titulatec_certificates_live_source`.

Este service es el ÚNICO lugar, fuera de los dos dueños y de `ClearanceGate`,
que lee `SurveyReview.status` / `LibraryClearance.status`; por eso está en la
lista de permitidos de `test_clearance_gate.py`. Es una excepción acotada y
justificada: no decide si alguien «está liberado» para un consumidor
(agendado, resúmenes, bandejas) -eso sigue siendo del gate-, solo enumera, para
repararlas, las filas que los dueños ya dejaron liberadas SIN su constancia. No
escribe estados ni eventos: su única escritura es `CertificateService.issue`,
el ÚNICO escritor de `titulatec_certificates` (invariante 1).

Reglas fijas (patrón del resto de services): `@staticmethod`, `db: Session`
primero, imports de modelos y de otros services LOCALES.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from itcj2.core.utils.timezone import db_now

# Prefijo del `source_ref` de cada tipo: el `NOT EXISTS` de `candidates` arma el
# ref en SQL (`prefijo || id`). Son los MISMOS formatos de
# `SurveyReviewService.certificate_ref` / `LibraryClearanceService.certificate_ref`
# (`test_folio_backfill.py` lo fija: si un dueño cambiara el suyo, el backfill
# emitiría duplicados en silencio).
_REF_PREFIX = {
    "survey_release": "survey_review:",
    "library_clearance": "library_clearance:",
}


class FolioBackfillService:
    """Folia las liberaciones vigentes que quedaron sin folio: previas
    (encuesta y no adeudo) y legado (no adeudo)."""

    @staticmethod
    def _consulta(db: Session, kind: str, *, lock: bool = False, row_id: int | None = None):
        """`(id, process_id, ancla)` de las filas de `kind` que necesitan folio:
        el predicado ÚNICO de candidata (lo usan `candidates` y la
        re-verificación de `run`, así que nunca divergen).

        `lock=True` agrega `FOR UPDATE OF` la tabla FUENTE (nunca la del
        proceso): mientras dure la transacción, `revert_clearance`/`undo_prior`/
        `revoke` esperan, y si uno de ellos ya commiteó, Postgres re-evalúa el
        `WHERE` contra la fila nueva y la deja fuera. Orden por id: dos corridas
        toman los candados en el mismo orden. `row_id` acota a UNA fila (la
        re-verificación)."""
        from sqlalchemy import String, cast, exists

        from itcj2.apps.titulatec.models import (
            Certificate, LibraryClearance, SurveyReview, TitulationProcess,
        )
        # El estado que LIBERA cada una sale del gate, no de un literal copiado
        # aquí: si su dominio cambiara, el backfill no se quedaría atrás.
        from itcj2.apps.titulatec.services.clearance_gate import (
            _LIBRARY_RELEASED, _SURVEY_RELEASED,
        )

        if kind == "survey_release":
            modelo, ancla = SurveyReview, SurveyReview.reviewed_at
            filtros = (SurveyReview.status == _SURVEY_RELEASED,
                       SurveyReview.origin == "prior")
        elif kind == "library_clearance":
            modelo, ancla = LibraryClearance, LibraryClearance.updated_at
            filtros = (LibraryClearance.status == _LIBRARY_RELEASED,
                       LibraryClearance.cleared_via.in_(("prior", "legacy")))
        else:
            raise ValueError(f"Tipo de folio desconocido: {kind!r}")

        q = (
            db.query(modelo.id, modelo.process_id, ancla)
            .join(TitulationProcess, TitulationProcess.id == modelo.process_id)
            .filter(
                *filtros,
                TitulationProcess.status != "cancelled",
                ~exists().where(
                    Certificate.voided_at.is_(None),
                    Certificate.source_ref == _REF_PREFIX[kind] + cast(modelo.id, String),
                ),
            )
        )
        if row_id is not None:
            q = q.filter(modelo.id == row_id)
        if lock:
            q = q.order_by(modelo.id).with_for_update(of=modelo)
        return q

    @staticmethod
    def candidates(db: Session, *, lock: bool = False) -> list[dict]:
        """Liberaciones VIGENTES sin folio vigente, de un proceso que no está
        `cancelled`, listas para foliarse. Solo lectura; con `lock=True` además
        deja BLOQUEADAS las filas fuente hasta el fin de la transacción (lo pide
        `run` en la corrida real).

        * `SurveyReview` `approved` con `origin='prior'`; ancla `reviewed_at`.
        * `LibraryClearance` `cleared` con `cleared_via` `prior` o `legacy`;
          ancla `updated_at`.
        * «Sin folio vigente» = `NOT EXISTS` en `titulatec_certificates` con el
          mismo `source_ref` y `voided_at IS NULL`: un folio ANULADO no cuenta
          (la liberación sigue vigente y necesita uno nuevo; el anulado no se
          reutiliza).
        * Ancla NULL -`reviewed_at` puede serlo- = `db_now()` (una sola lectura
          del reloj por llamada).

        Cada dict trae `kind`, `source_ref`, `process_id`, `anchor` (datetime)
        y `semester` (= `previous_semester_key(anchor)`), en el orden
        `(anchor, kind, id de la fila)`.
        """
        from itcj2.apps.titulatec.services.certificate_service import (
            previous_semester_key,
        )
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )
        from itcj2.apps.titulatec.services.survey_review_service import (
            SurveyReviewService,
        )

        ahora = db_now()
        filas: list[tuple] = []     # (ancla, kind, id, process_id, source_ref)
        # Los tipos en el MISMO orden en que `run` emite: los candados de las
        # filas fuente se toman siempre en un orden fijo (tipo, id).
        for kind, ref_de in (("library_clearance", LibraryClearanceService.certificate_ref),
                             ("survey_release", SurveyReviewService.certificate_ref)):
            for fila_id, process_id, ancla in FolioBackfillService._consulta(
                    db, kind, lock=lock):
                filas.append((ancla or ahora, kind, fila_id, process_id, ref_de(fila_id)))

        filas.sort(key=lambda f: (f[0], f[1], f[2]))
        return [
            {"kind": kind, "source_ref": ref, "process_id": process_id,
             "anchor": ancla, "semester": previous_semester_key(ancla)}
            for ancla, kind, _id, process_id, ref in filas
        ]

    @staticmethod
    def _sigue_candidata(db: Session, candidato: dict) -> bool:
        """¿La fila de `candidato` SIGUE necesitando folio AHORA? Re-lee su
        estado (bloqueándola) con el MISMO predicado de `candidates`. Si otra
        transacción la revirtió o la deshizo entre la lista y la emisión,
        foliarla dejaría un folio VIVO sobre una fila no liberada, y la
        siguiente liberación legítima de esa fila tronaría (500) contra
        `uq_titulatec_certificates_live_source`."""
        prefijo = _REF_PREFIX[candidato["kind"]]
        row_id = int(candidato["source_ref"][len(prefijo):])
        return FolioBackfillService._consulta(
            db, candidato["kind"], lock=True, row_id=row_id).first() is not None

    @staticmethod
    def run(db: Session, *, dry_run: bool) -> dict[tuple[str, str], int]:
        """Folia los `candidates` y devuelve el conteo por `(kind, semester)`
        (ordenado).

        Corrida real: lista con `lock=True` (las filas fuente quedan bloqueadas
        hasta el commit), RE-VERIFICA cada una justo antes de emitir
        (`_sigue_candidata`: la que dejó de serlo no recibe folio ni cuenta) y
        emite con `CertificateService.issue(actor_id=None, semester=…)`
        agrupado por tipo -mismo orden de candados que la lista; dentro de cada
        tipo, el orden del ancla, así que la numeración de cada semestre sigue
        al ancla (los contadores son por `(kind, semester)`)-. UN solo commit
        al final: si una emisión falla no se commitea ninguna.

        `dry_run=True` solo cuenta, sin bloquear, escribir ni commitear nada.
        Idempotente: la segunda corrida da un conteo vacío."""
        from itcj2.apps.titulatec.models import TitulationProcess
        from itcj2.apps.titulatec.services.certificate_service import CertificateService

        candidatos = FolioBackfillService.candidates(db, lock=not dry_run)
        # `sort` es estable: por tipo y, dentro del tipo, el orden de la lista.
        candidatos.sort(key=lambda c: c["kind"])

        conteo: dict[tuple[str, str], int] = {}
        for c in candidatos:
            if not dry_run:
                if not FolioBackfillService._sigue_candidata(db, c):
                    continue
                CertificateService.issue(
                    db, kind=c["kind"], process=db.get(TitulationProcess, c["process_id"]),
                    source_ref=c["source_ref"], actor_id=None, semester=c["semester"])
            clave = (c["kind"], c["semester"])
            conteo[clave] = conteo.get(clave, 0) + 1

        if not dry_run:
            if conteo:
                # Resumen de la corrida; cada folio ya quedó por `issue`.
                from itcj2.apps.titulatec.services.audit_service import AuditService
                AuditService.record(
                    db, "certificate.backfill_run",
                    entity_type="certificate",
                    payload={
                        "total": sum(conteo.values()),
                        "por_tipo_semestre": {
                            f"{k}/{sem}": n for (k, sem), n in sorted(conteo.items())
                        },
                    },
                )
            db.commit()
        return dict(sorted(conteo.items()))
