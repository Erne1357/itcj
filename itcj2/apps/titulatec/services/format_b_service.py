"""Lógica del Formato B (multi-step, reemplaza el Tsoft)."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

# Campos por paso (nombres = columnas del modelo FormatB / names del form).
STEP_FIELDS = {
    1: ["first_name", "last_name", "middle_name", "gender", "age",
        "mobile_phone", "phone", "postal_code", "neighborhood", "street",
        "ext_number", "int_number"],
    2: ["program_id", "study_plan", "titulation_type", "admission_date", "graduation_date"],
    3: ["project_name"],
}
_INT_FIELDS = {"age", "program_id"}
_MONTH_FIELDS = {"admission_date", "graduation_date"}


def _to_month_str(d) -> str:
    """Date → 'YYYY-MM' para <input type=month>."""
    return d.strftime("%Y-%m") if d else ""


def _parse_month(value: str):
    """'YYYY-MM' → date(primer día del mes). None si vacío/ inválido."""
    if not value:
        return None
    try:
        y, m = value.split("-")[:2]
        return date(int(y), int(m), 1)
    except (ValueError, TypeError):
        return None


class FormatBService:
    @staticmethod
    def get_or_create(db: Session, process):
        """Devuelve el FormatB del proceso, precargando datos del alumno/proceso."""
        from itcj2.apps.titulatec.models import FormatB
        from itcj2.core.models.user import User

        fb = db.get(FormatB, process.id)
        if fb:
            return fb

        user = db.get(User, process.student_id)
        modality = process.modality
        fb = FormatB(
            process_id=process.id,
            first_name=user.first_name if user else None,
            last_name=user.last_name if user else None,
            middle_name=user.middle_name if user else None,
            control_number=(user.control_number if user else None),
            program_id=process.program_id,
            titulation_type=(modality.name if modality else None),
            status="draft",
        )
        db.add(fb)
        db.commit()
        db.refresh(fb)
        return fb

    @staticmethod
    def save_step(db: Session, fb, step: int, form: dict) -> None:
        """Guarda los campos del paso indicado (parcial, status sigue 'draft')."""
        for field in STEP_FIELDS.get(step, []):
            if field not in form:
                continue
            raw = form.get(field)
            if field in _MONTH_FIELDS:
                setattr(fb, field, _parse_month(raw))
            elif field in _INT_FIELDS:
                setattr(fb, field, int(raw) if str(raw).strip() else None)
            else:
                setattr(fb, field, (raw.strip() or None) if isinstance(raw, str) else raw)
        if fb.status == "rejected":
            fb.status = "draft"
        db.commit()

    @staticmethod
    def submit(db: Session, fb) -> None:
        """Envía el Formato B a revisión y marca la fase 3 in_review."""
        from itcj2.apps.titulatec.models import ProcessPhase
        fb.status = "submitted"
        phase = db.query(ProcessPhase).filter_by(process_id=fb.process_id, phase_number=3).first()
        if not phase:
            phase = ProcessPhase(process_id=fb.process_id, phase_number=3)
            db.add(phase)
        phase.status = "in_review"
        db.commit()

    @staticmethod
    def review(db: Session, fb, *, status: str, note: str | None, reviewer_id: int) -> None:
        """Aprueba o rechaza el Formato B (status 'approved'|'rejected')."""
        from datetime import datetime
        fb.status = status
        if status == "approved":
            fb.approved_by_id = reviewer_id
            fb.approved_at = datetime.utcnow()
            fb.rejection_reason = None
        else:
            fb.rejection_reason = note or None
        db.commit()

    @staticmethod
    def to_ctx(fb) -> dict:
        """Datos del FormatB para los templates (con meses formateados)."""
        return {
            "first_name": fb.first_name or "", "last_name": fb.last_name or "",
            "middle_name": fb.middle_name or "", "gender": fb.gender or "",
            "age": fb.age or "", "mobile_phone": fb.mobile_phone or "", "phone": fb.phone or "",
            "postal_code": fb.postal_code or "", "neighborhood": fb.neighborhood or "",
            "street": fb.street or "", "ext_number": fb.ext_number or "", "int_number": fb.int_number or "",
            "control_number": fb.control_number or "", "program_id": fb.program_id,
            "study_plan": fb.study_plan or "", "titulation_type": fb.titulation_type or "",
            "admission_date": _to_month_str(fb.admission_date),
            "graduation_date": _to_month_str(fb.graduation_date),
            "project_name": fb.project_name or "", "status": fb.status,
        }
