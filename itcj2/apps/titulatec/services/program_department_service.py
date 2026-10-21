"""Carreras por departamento (fase 4, spec 2026-10-21 §13, D10 y R-C/R-F/R-G).

Dos bloques de la misma pantalla, solo `admin`:

- **Mapeo carrera -> departamento académico** (`titulatec_program_departments`) y
  el nombre oficial de la carrera que usa el oficio (R-C; NULL = `Program.name`).
- **Ajustes del oficio por departamento** (`titulatec_department_settings`, R-F):
  encabezado y códigos de puesto del destinatario y del «Atn.».

Reglas:
- El catálogo de departamentos son los hijos de `sub_academic` más
  `coord_campus_2` y `ead` (más los que YA estén mapeados, para que una fila
  existente nunca quede sin su valor en el select).
- Los servicios hacen `commit`; cada cambio deja una fila de bitácora
  (`program_department.changed` / `department_settings.changed`) en la MISMA
  transacción. Sin cambios reales no se escribe nada.
- Cambiar el departamento de una carrera con procesos en fase 4 o 5 está
  permitido (el alcance se recalcula al vuelo): la bitácora cuenta cuántos.
- **R-G**: con el corte a T-soft en la fase 4 o antes la pantalla es informativa
  y nada se escribe (`INERT_MSG`).
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from itcj2.core.utils.timezone import db_now

logger = logging.getLogger(__name__)

# Padre y departamentos sueltos del catálogo (spec §13).
ACADEMIC_PARENT_CODE = "sub_academic"
EXTRA_DEPARTMENT_CODES = ("coord_campus_2", "ead")

MAX_OFFICIAL_NAME = 200
MAX_HEADER = 200

INERT_MSG = ("Los departamentos de las carreras se editan cuando la asignación de "
             "sinodales se opera en esta app (hoy sigue fuera de la plataforma).")
PROGRAM_NOT_FOUND_MSG = "La carrera no existe."
DEPARTMENT_NOT_ACADEMIC_MSG = "El departamento no es un departamento académico del catálogo."
NAME_TOO_LONG_MSG = f"El nombre oficial no puede pasar de {MAX_OFFICIAL_NAME} caracteres."
HEADER_REQUIRED_MSG = "El encabezado del oficio es obligatorio."
HEADER_TOO_LONG_MSG = f"El encabezado no puede pasar de {MAX_HEADER} caracteres."
ADDRESSEE_REQUIRED_MSG = "El puesto del destinatario es obligatorio."
POSITION_NOT_FOUND_MSG = "No existe un puesto con el código «{code}»."

_PROGRAM_FIELDS = ("department_id", "official_name")
_SETTINGS_FIELDS = ("oficio_header", "addressee_position_code", "attn_position_code")


def _clean(value) -> str | None:
    """Texto recortado y con espacios colapsados; vacío -> None."""
    text = " ".join(str(value or "").split())
    return text or None


class ProgramDepartmentService:
    # ------------------------------------------------------------------ estado
    @staticmethod
    def operable(db: Session) -> bool:
        """¿La fase 4 se opera en esta app? Misma puerta que Sinodales y Docentes (R-G)."""
        from itcj2.apps.titulatec.services.synodal_service import SynodalService

        return SynodalService.operable(db)

    @staticmethod
    def _assert_operable(db: Session) -> None:
        if not ProgramDepartmentService.operable(db):
            raise ValueError(INERT_MSG)

    # ---------------------------------------------------------------- catálogo
    @staticmethod
    def academic_departments_catalog(db: Session) -> list[dict]:
        """Departamentos que pueden recibir carreras: `[{"id","code","name"}]` por nombre."""
        from sqlalchemy import or_

        from itcj2.apps.titulatec.models import ProgramDepartment
        from itcj2.core.models.department import Department

        parent_id = (db.query(Department.id)
                     .filter(Department.code == ACADEMIC_PARENT_CODE).scalar())
        mapped = db.query(ProgramDepartment.department_id).distinct()
        conds = [Department.code.in_(EXTRA_DEPARTMENT_CODES),
                 Department.id.in_(mapped.scalar_subquery())]
        if parent_id is not None:
            conds.append(Department.parent_id == parent_id)
        rows = (db.query(Department.id, Department.code, Department.name)
                .filter(Department.is_active.is_(True), or_(*conds))
                .order_by(Department.name).all())
        return [{"id": r.id, "code": r.code, "name": r.name} for r in rows]

    # ------------------------------------------------------------------ mapeo
    @staticmethod
    def list_mapping(db: Session) -> list[dict]:
        """Todas las carreras con su departamento y nombre oficial (sin mapear: `None`)."""
        from itcj2.apps.titulatec.models import ProgramDepartment
        from itcj2.core.models.department import Department
        from itcj2.core.models.program import Program

        rows = (db.query(Program, ProgramDepartment, Department)
                .outerjoin(ProgramDepartment, ProgramDepartment.program_id == Program.id)
                .outerjoin(Department, Department.id == ProgramDepartment.department_id)
                .order_by(Program.name).all())
        return [{
            "program_id": p.id,
            "name": p.name,
            "level": getattr(p, "level", None),
            "department_id": pd.department_id if pd else None,
            "department_name": d.name if d else None,
            "official_name": pd.official_name if pd else None,
        } for p, pd, d in rows]

    @staticmethod
    def set_department(db: Session, actor_id: int, program_id: int,
                       department_id: int, official_name=None) -> bool:
        """Mapea la carrera a un departamento del catálogo y fija su nombre oficial.

        Devuelve `False` si nada cambió (sin bitácora). `ValueError` con mensaje
        listo para `X-Tt-Error`; los errores no dejan nada escrito.
        """
        from itcj2.apps.titulatec.models import ProgramDepartment, TitulationProcess
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.core.models.program import Program

        ProgramDepartmentService._assert_operable(db)
        program = db.get(Program, program_id)
        if program is None:
            raise ValueError(PROGRAM_NOT_FOUND_MSG)
        name = _clean(official_name)
        if name is not None and len(name) > MAX_OFFICIAL_NAME:
            raise ValueError(NAME_TOO_LONG_MSG)
        catalog = {d["id"] for d in ProgramDepartmentService.academic_departments_catalog(db)}
        if department_id not in catalog:
            raise ValueError(DEPARTMENT_NOT_ACADEMIC_MSG)

        row = db.get(ProgramDepartment, program_id)
        before = (AuditService.snapshot(row, _PROGRAM_FIELDS) if row is not None
                  else {"department_id": None, "official_name": None})
        after = {"department_id": department_id, "official_name": name}
        if before == after:
            return False

        # Procesos en fase 4 o 5: el alcance se recalcula al vuelo (spec §13).
        moved = 0
        if before["department_id"] != department_id:
            moved = (db.query(TitulationProcess)
                     .filter(TitulationProcess.program_id == program_id,
                             TitulationProcess.current_phase.in_((4, 5))).count())
        if row is None:
            row = ProgramDepartment(program_id=program_id)
            db.add(row)
        row.department_id = department_id
        row.official_name = name
        row.updated_at = db_now()
        row.updated_by_id = actor_id

        b, a = AuditService.changes(before, after)
        AuditService.record(
            db, "program_department.changed", entity_type="program",
            entity_id=program_id, subject=program.name, before=b, after=a,
            payload={"processes_in_phase_4_5": moved} if moved else None,
            actor_id=actor_id)
        db.commit()
        return True

    # ----------------------------------------------------------------- ajustes
    @staticmethod
    def list_settings(db: Session) -> list[dict]:
        """Un renglón por departamento del catálogo; sin ajustes, campos vacíos."""
        from itcj2.apps.titulatec.models import DepartmentSettings

        out = []
        for d in ProgramDepartmentService.academic_departments_catalog(db):
            s = db.get(DepartmentSettings, d["id"])
            out.append({
                "department_id": d["id"], "code": d["code"], "name": d["name"],
                "oficio_header": s.oficio_header if s else "",
                "addressee_position_code": s.addressee_position_code if s else "",
                "attn_position_code": (s.attn_position_code if s else "") or "",
                "configured": s is not None,
            })
        return out

    @staticmethod
    def update_settings(db: Session, actor_id: int, department_id: int, *,
                        oficio_header, addressee_position_code, attn_position_code=None) -> bool:
        """Crea o edita los ajustes del oficio de un departamento (R-F).

        Los códigos de puesto deben existir en `core_positions` (el oficio los
        resuelve a la persona que lo ocupa al generarse). Devuelve `False` sin
        cambios.
        """
        from itcj2.apps.titulatec.models import DepartmentSettings
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.core.models.department import Department
        from itcj2.core.models.position import Position

        ProgramDepartmentService._assert_operable(db)
        dept = db.get(Department, department_id)
        catalog = {d["id"] for d in ProgramDepartmentService.academic_departments_catalog(db)}
        if dept is None or department_id not in catalog:
            raise ValueError(DEPARTMENT_NOT_ACADEMIC_MSG)
        header = _clean(oficio_header)
        if header is None:
            raise ValueError(HEADER_REQUIRED_MSG)
        if len(header) > MAX_HEADER:
            raise ValueError(HEADER_TOO_LONG_MSG)
        addressee = _clean(addressee_position_code)
        if addressee is None:
            raise ValueError(ADDRESSEE_REQUIRED_MSG)
        attn = _clean(attn_position_code)
        for code in (addressee, attn):
            if code is None:
                continue
            exists = db.query(Position.id).filter(Position.code == code).first()
            if exists is None:
                raise ValueError(POSITION_NOT_FOUND_MSG.format(code=code))

        row = db.get(DepartmentSettings, department_id)
        before = (AuditService.snapshot(row, _SETTINGS_FIELDS) if row is not None
                  else {k: None for k in _SETTINGS_FIELDS})
        after = {"oficio_header": header, "addressee_position_code": addressee,
                 "attn_position_code": attn}
        if before == after:
            return False
        if row is None:
            row = DepartmentSettings(department_id=department_id)
            db.add(row)
        row.oficio_header = header
        row.addressee_position_code = addressee
        row.attn_position_code = attn
        row.updated_at = db_now()
        row.updated_by_id = actor_id

        b, a = AuditService.changes(before, after)
        AuditService.record(
            db, "department_settings.changed", entity_type="department",
            entity_id=department_id, subject=dept.name, before=b, after=a,
            actor_id=actor_id)
        db.commit()
        return True
