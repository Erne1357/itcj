"""Requisitos de cotejo (qué llevar a la cita) — configurables por convocatoria.

La jefa de Servicios Escolares define la lista por cohorte. Si una convocatoria
no tiene requisitos aún, se siembra con DEFAULTS al consultarlos.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

# Lista por defecto (la que estaba hardcodeada en la vista del alumno).
#
# 5-tuplas: (icon, label, hint, code, auto_source).
#   * `code` da identidad ESTABLE al requisito: la etiqueta la reescribe
#     Servicios Escolares cuando quiere, el código no.
#   * `auto_source` marca los que acredita el SISTEMA. Es la única fuente de ese
#     valor: `create()` no puede fijarlo desde la UI a propósito, porque un
#     requisito automático borrado a media convocatoria dejaría a la encuesta sin
#     nada que acreditar y sin forma de restaurarlo.
DEFAULTS = [
    ("file-earmark-text", "Actas de nacimiento", "Original + copias.",
     "birth_certificates", None),
    ("card-text", "CURP certificada", "Impresión certificada (no la simple).",
     "curp", None),
    ("shield-check", "e.Firma (SAT)", "Constancia de situación fiscal con e.Firma vigente.",
     "efirma", None),
    ("clipboard-check", "Encuesta de egresados", "Comprobante de haberla contestado.",
     "graduate_survey", "graduate_survey"),
    ("book", "No-adeudo de biblioteca", "Constancia de no adeudo vigente.",
     "library_clearance", None),
    ("camera", "12 fotografías", "Tamaño credencial, ovaladas, B/N, fondo blanco, papel mate.",
     "photos", None),
    ("heart-pulse", "Vigencia de derechos IMSS", "Documento que acredite vigencia.",
     "imss", None),
    ("cash-coin", "$1,900 en efectivo", "Pago del proceso de titulación (efectivo).",
     "payment", None),
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
    def seed_defaults(db: Session, cohort_id: int, *, commit: bool = True) -> int:
        """Crea los requisitos por defecto si la convocatoria no tiene ninguno.

        `commit=False` es para los llamadores que YA son dueños de su
        transacción: `RequirementService.auto_requirement` (§4.4 del diseño exige
        un solo commit al enviar la encuesta) y `cohort_create`, que siembra en
        la misma transacción en que crea la convocatoria.

        Es la ÚNICA escritura de `code`/`auto_source`.
        """
        from itcj2.apps.titulatec.models import CotejoRequirement
        exists = db.query(CotejoRequirement).filter_by(cohort_id=cohort_id).first()
        if exists:
            return 0
        for i, (icon, label, hint, code, auto_source) in enumerate(DEFAULTS):
            db.add(CotejoRequirement(cohort_id=cohort_id, icon=icon, label=label,
                                     hint=hint, code=code, auto_source=auto_source,
                                     order_index=i))
        if commit:
            db.commit()
        else:
            db.flush()
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
        """Actualiza el requisito. Candado para el automático (D9).

        Un requisito con `auto_source` (hoy solo 'graduate_survey') es el que
        ACREDITA el sistema, y `RequirementService.missing_required` —la
        guarda que bloquea el dictamen de la fase 2— solo mira filas
        `is_active=True AND is_required=True`. Si el editor pudiera volverlo
        opcional o inactivo, esa guarda se desarmaría en silencio (pasó en
        dev: alguien corrió un UPDATE manual mientras la encuesta no existía
        y nunca se revirtió). Por eso aquí `is_required`/`is_active` se fuerzan
        a `True` para estos SIN importar lo que traiga `fields` — `label`,
        `hint`, `icon` y `order_index` sí se siguen pudiendo editar.
        """
        from itcj2.apps.titulatec.models import CotejoRequirement
        item = db.query(CotejoRequirement).filter_by(id=req_id, cohort_id=cohort_id).first()
        if not item:
            return None
        if item.auto_source:
            fields = {**fields, "is_required": True, "is_active": True}
        for k in ("label", "hint", "icon", "is_required", "is_active", "order_index"):
            if k in fields and fields[k] is not None:
                setattr(item, k, fields[k])
        db.commit()
        db.refresh(item)
        return item

    @staticmethod
    def delete(db: Session, req_id: int, cohort_id: int) -> tuple[bool, str]:
        """Borra el requisito. Devuelve `(ok, motivo)`.

        `motivo` ∈ ``"ok"`` | ``"not_found"`` | ``"fulfilled:{N}"``.

        La comprobación de cumplimientos va ANTES del `db.delete`: la FK de
        `titulatec_requirement_fulfillments.requirement_id` es `ON DELETE
        RESTRICT` (a propósito, para que borrar la lista no destruya el crédito
        de quien ya cumplió), así que sin esto Postgres contestaría con un
        `IntegrityError` crudo a mitad de un POST de la UI. La vía soportada es
        `is_active = False`, que ya existe en modelo, ruta y parcial.
        """
        from itcj2.apps.titulatec.models import CotejoRequirement, RequirementFulfillment
        item = db.query(CotejoRequirement).filter_by(id=req_id, cohort_id=cohort_id).first()
        if not item:
            return False, "not_found"
        usados = (db.query(RequirementFulfillment)
                  .filter_by(requirement_id=req_id).count())
        if usados:
            return False, f"fulfilled:{usados}"
        db.delete(item)
        db.commit()
        return True, "ok"
