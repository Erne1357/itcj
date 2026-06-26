"""Requisitos de cotejo (qué llevar a la cita) — configurables por convocatoria.

La jefa de Servicios Escolares define la lista por cohorte. Si una convocatoria
no tiene requisitos aún, se siembra con DEFAULTS al consultarlos.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

# Lista por defecto (la que estaba hardcodeada en la vista del alumno).
DEFAULTS = [
    ("file-earmark-text", "Actas de nacimiento", "Original + copias."),
    ("card-text", "CURP certificada", "Impresión certificada (no la simple)."),
    ("shield-check", "e.Firma (SAT)", "Constancia de situación fiscal con e.Firma vigente."),
    ("clipboard-check", "Encuesta de egresados", "Comprobante de haberla contestado."),
    ("book", "No-adeudo de biblioteca", "Constancia de no adeudo vigente."),
    ("camera", "12 fotografías", "Tamaño credencial, ovaladas, B/N, fondo blanco, papel mate."),
    ("heart-pulse", "Vigencia de derechos IMSS", "Documento que acredite vigencia."),
    ("cash-coin", "$1,900 en efectivo", "Pago del proceso de titulación (efectivo)."),
]


class CotejoRequirementService:
    @staticmethod
    def list(db: Session, cohort_id: int, *, active_only: bool = True) -> list:
        from itcj2.apps.titulatec.models import CotejoRequirement
        q = db.query(CotejoRequirement).filter_by(cohort_id=cohort_id)
        if active_only:
            q = q.filter_by(is_active=True)
        return q.order_by(CotejoRequirement.order_index, CotejoRequirement.id).all()

    @staticmethod
    def seed_defaults(db: Session, cohort_id: int) -> int:
        """Crea los requisitos por defecto si la convocatoria no tiene ninguno."""
        from itcj2.apps.titulatec.models import CotejoRequirement
        exists = db.query(CotejoRequirement).filter_by(cohort_id=cohort_id).first()
        if exists:
            return 0
        for i, (icon, label, hint) in enumerate(DEFAULTS):
            db.add(CotejoRequirement(cohort_id=cohort_id, icon=icon, label=label,
                                     hint=hint, order_index=i))
        db.commit()
        return len(DEFAULTS)

    @staticmethod
    def list_or_seed(db: Session, cohort_id: int, *, active_only: bool = True) -> list:
        """Lista los requisitos; si no hay ninguno, siembra los defaults primero."""
        items = CotejoRequirementService.list(db, cohort_id, active_only=active_only)
        if not items:
            CotejoRequirementService.seed_defaults(db, cohort_id)
            items = CotejoRequirementService.list(db, cohort_id, active_only=active_only)
        return items

    @staticmethod
    def create(db: Session, cohort_id: int, *, label: str, hint: str | None,
               icon: str | None, is_required: bool = True):
        from itcj2.apps.titulatec.models import CotejoRequirement
        last = (db.query(CotejoRequirement).filter_by(cohort_id=cohort_id)
                .order_by(CotejoRequirement.order_index.desc()).first())
        item = CotejoRequirement(
            cohort_id=cohort_id, label=label.strip(), hint=(hint or None),
            icon=(icon or "check2-square"), is_required=is_required,
            order_index=(last.order_index + 1 if last else 0),
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    @staticmethod
    def update(db: Session, req_id: int, cohort_id: int, **fields):
        from itcj2.apps.titulatec.models import CotejoRequirement
        item = db.query(CotejoRequirement).filter_by(id=req_id, cohort_id=cohort_id).first()
        if not item:
            return None
        for k in ("label", "hint", "icon", "is_required", "is_active", "order_index"):
            if k in fields and fields[k] is not None:
                setattr(item, k, fields[k])
        db.commit()
        db.refresh(item)
        return item

    @staticmethod
    def delete(db: Session, req_id: int, cohort_id: int) -> bool:
        from itcj2.apps.titulatec.models import CotejoRequirement
        item = db.query(CotejoRequirement).filter_by(id=req_id, cohort_id=cohort_id).first()
        if not item:
            return False
        db.delete(item)
        db.commit()
        return True
