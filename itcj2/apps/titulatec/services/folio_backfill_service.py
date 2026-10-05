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
    def candidates(db: Session) -> list[dict]:
        """Liberaciones VIGENTES sin folio vigente, de un proceso que no está
        `cancelled`, listas para foliarse. Solo lectura.

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
        from sqlalchemy import String, cast, exists

        from itcj2.apps.titulatec.models import (
            Certificate, LibraryClearance, SurveyReview, TitulationProcess,
        )
        from itcj2.apps.titulatec.services.certificate_service import (
            previous_semester_key,
        )
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )
        from itcj2.apps.titulatec.services.survey_review_service import (
            SurveyReviewService,
        )

        def _sin_folio_vigente(kind: str, modelo):
            return ~exists().where(
                Certificate.voided_at.is_(None),
                Certificate.source_ref == _REF_PREFIX[kind] + cast(modelo.id, String),
            )

        ahora = db_now()
        filas: list[tuple] = []     # (ancla, kind, id, process_id, source_ref)

        encuestas = (
            db.query(SurveyReview.id, SurveyReview.process_id, SurveyReview.reviewed_at)
            .join(TitulationProcess, TitulationProcess.id == SurveyReview.process_id)
            .filter(
                SurveyReview.status == "approved",
                SurveyReview.origin == "prior",
                TitulationProcess.status != "cancelled",
                _sin_folio_vigente("survey_release", SurveyReview),
            )
        )
        for fila_id, process_id, ancla in encuestas:
            filas.append((ancla or ahora, "survey_release", fila_id, process_id,
                          SurveyReviewService.certificate_ref(fila_id)))

        bibliotecas = (
            db.query(LibraryClearance.id, LibraryClearance.process_id,
                     LibraryClearance.updated_at)
            .join(TitulationProcess, TitulationProcess.id == LibraryClearance.process_id)
            .filter(
                LibraryClearance.status == "cleared",
                LibraryClearance.cleared_via.in_(("prior", "legacy")),
                TitulationProcess.status != "cancelled",
                _sin_folio_vigente("library_clearance", LibraryClearance),
            )
        )
        for fila_id, process_id, ancla in bibliotecas:
            filas.append((ancla or ahora, "library_clearance", fila_id, process_id,
                          LibraryClearanceService.certificate_ref(fila_id)))

        filas.sort(key=lambda f: (f[0], f[1], f[2]))
        return [
            {"kind": kind, "source_ref": ref, "process_id": process_id,
             "anchor": ancla, "semester": previous_semester_key(ancla)}
            for ancla, kind, _id, process_id, ref in filas
        ]

    @staticmethod
    def run(db: Session, *, dry_run: bool) -> dict[tuple[str, str], int]:
        """Folia los `candidates` y devuelve el conteo por `(kind, semester)`
        (ordenado). Corrida real: `CertificateService.issue(actor_id=None,
        semester=…)` por candidato, en el orden de `candidates` -así la
        numeración de cada semestre sigue el orden del ancla- y UN solo commit
        al final: si una emisión falla no se commitea ninguna. `dry_run=True`
        solo cuenta, sin escribir ni commitear nada. Idempotente: la segunda
        corrida da un conteo vacío."""
        from itcj2.apps.titulatec.models import TitulationProcess
        from itcj2.apps.titulatec.services.certificate_service import CertificateService

        conteo: dict[tuple[str, str], int] = {}
        for c in FolioBackfillService.candidates(db):
            if not dry_run:
                CertificateService.issue(
                    db, kind=c["kind"], process=db.get(TitulationProcess, c["process_id"]),
                    source_ref=c["source_ref"], actor_id=None, semester=c["semester"])
            clave = (c["kind"], c["semester"])
            conteo[clave] = conteo.get(clave, 0) + 1

        if not dry_run:
            db.commit()
        return dict(sorted(conteo.items()))
