"""Carreras por departamento (fase 4, spec 2026-10-21 §13, D10 y R-C/R-F/R-G).

Dos bloques de la misma pantalla, solo `admin`:

- **Mapeo carrera -> departamento académico** (`titulatec_program_departments`) y
  el nombre oficial de la carrera que usa el oficio (R-C; NULL = `Program.name`).
- **Ajustes del oficio por departamento** (`titulatec_department_settings`, R-F):
  encabezado, códigos de puesto del destinatario y del «Atn.» y, opcionales,
  los títulos con que el oficio los nombra (`addressee_title`/`attn_title`,
  hallazgo 17; vacío = el título del puesto en el organigrama).

Reglas:
- El catálogo de departamentos son los que pueden operar sinodales: los que
  tienen su puesto `docente_{code}` activo (hallazgo 11 de la revisión de rama;
  hoy los 8 que siembra `fase_2/02_sinodales.sql`). Uno sin docentes no se
  ofrece: nadie podría asignar los sinodales de sus carreras. Una fila ya
  mapeada a un departamento fuera del catálogo se pinta con su valor y un aviso
  (no se puede volver a guardar sin elegir uno operable).
- Las fases 4 y 5 salen del catálogo por código (`synodal_assignment`,
  `synodal_review`), nunca de números escritos a mano.
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

# Prefijo del puesto docente: un departamento con `docente_{code}` activo es
# operable (mismo prefijo que `TeacherService.POSITION_PREFIX`).
TEACHER_POSITION_PREFIX = "docente_"

MAX_OFFICIAL_NAME = 200
MAX_HEADER = 200
MAX_TITLE = 200

INERT_MSG = ("Los departamentos de las carreras se editan cuando la asignación de "
             "sinodales se opera en esta app (hoy sigue fuera de la plataforma).")
PROGRAM_NOT_FOUND_MSG = "La carrera no existe."
DEPARTMENT_NOT_ACADEMIC_MSG = "El departamento no es un departamento académico del catálogo."
NAME_TOO_LONG_MSG = f"El nombre oficial no puede pasar de {MAX_OFFICIAL_NAME} caracteres."
HEADER_REQUIRED_MSG = "El encabezado del oficio es obligatorio."
HEADER_TOO_LONG_MSG = f"El encabezado no puede pasar de {MAX_HEADER} caracteres."
ADDRESSEE_REQUIRED_MSG = "El puesto del destinatario es obligatorio."
POSITION_NOT_FOUND_MSG = "No existe un puesto con el código «{code}»."
TITLE_TOO_LONG_MSG = f"Un título del oficio no puede pasar de {MAX_TITLE} caracteres."

_PROGRAM_FIELDS = ("department_id", "official_name")
_SETTINGS_FIELDS = ("oficio_header", "addressee_position_code", "attn_position_code",
                    "addressee_title", "attn_title")


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
        """Departamentos que pueden recibir carreras: `[{"id","code","name"}]` por nombre.

        Solo los OPERABLES: activos y con su puesto `docente_{code}` activo (de
        ahí salen los sinodales). Una consulta.
        """
        from sqlalchemy import exists, func

        from itcj2.core.models.department import Department
        from itcj2.core.models.position import Position

        con_docentes = exists().where(
            Position.code == func.concat(TEACHER_POSITION_PREFIX, Department.code),
            Position.is_active.is_(True))
        rows = (db.query(Department.id, Department.code, Department.name)
                .filter(Department.is_active.is_(True), con_docentes)
                .order_by(Department.name, Department.id).all())
        return [{"id": r.id, "code": r.code, "name": r.name} for r in rows]

    @staticmethod
    def _synodal_phase_numbers(db: Session) -> list[int]:
        """Números de las fases 4 y 5 en el catálogo (por código; las que falten
        no cuentan). Una consulta."""
        from itcj2.apps.titulatec.models import PhaseDefinition
        from itcj2.apps.titulatec.services.synodal_service import PHASE_CODE, REVIEW_PHASE_CODE

        return [int(n) for (n,) in db.query(PhaseDefinition.number)
                .filter(PhaseDefinition.code.in_((PHASE_CODE, REVIEW_PHASE_CODE))).all()]

    @staticmethod
    def unassignable_in_flight(db: Session, catalog: list[dict] | None = None) -> int:
        """Procesos ACTIVOS en la fase 4 o 5 cuya carrera no tiene departamento
        operable (sin mapear o mapeada a uno fuera del catálogo): nadie puede
        asignarles ni sustituirles sinodales hasta corregir la carrera
        (hallazgo 11). Sin carrera no cuentan (no hay qué mapear).

        `catalog` (opcional) evita volver a consultarlo. Dos consultas.
        """
        from sqlalchemy import func, or_

        from itcj2.apps.titulatec.models import ProgramDepartment, TitulationProcess as TP

        fases = ProgramDepartmentService._synodal_phase_numbers(db)
        if not fases:
            return 0
        deptos = (catalog if catalog is not None
                  else ProgramDepartmentService.academic_departments_catalog(db))
        operables = [d["id"] for d in deptos]
        sin_depto = ProgramDepartment.program_id.is_(None)
        if operables:
            sin_depto = or_(sin_depto, ~ProgramDepartment.department_id.in_(operables))
        return int(db.query(func.count(TP.id))
                   .outerjoin(ProgramDepartment, ProgramDepartment.program_id == TP.program_id)
                   .filter(TP.status == "active", TP.current_phase.in_(fases),
                           TP.program_id.isnot(None), sin_depto)
                   .scalar() or 0)

    # ------------------------------------------------------------------ mapeo
    @staticmethod
    def list_mapping(db: Session) -> list[dict]:
        """Todas las carreras con su departamento y nombre oficial (sin mapear: `None`).

        `profile_label` («Maestría», «Doctorado» o None en licenciatura) lo da
        `TrackService`: este módulo no lee el nivel de la carrera (invariante 2
        del posgrado, hallazgo 10).
        """
        from itcj2.apps.titulatec.models import ProgramDepartment
        from itcj2.apps.titulatec.services.track_service import TrackService
        from itcj2.core.models.department import Department
        from itcj2.core.models.program import Program

        rows = (db.query(Program, ProgramDepartment, Department)
                .outerjoin(ProgramDepartment, ProgramDepartment.program_id == Program.id)
                .outerjoin(Department, Department.id == ProgramDepartment.department_id)
                .order_by(Program.name).all())
        perfiles = TrackService.profile_labels(db, [p.id for p, _pd, _d in rows])
        return [{
            "program_id": p.id,
            "name": p.name,
            "profile_label": perfiles.get(p.id),
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

        # Procesos en fase 4 o 5 (números del catálogo, hallazgo 9): el alcance
        # se recalcula al vuelo (spec §13).
        moved = 0
        if before["department_id"] != department_id:
            fases = ProgramDepartmentService._synodal_phase_numbers(db)
            if fases:
                moved = (db.query(TitulationProcess)
                         .filter(TitulationProcess.program_id == program_id,
                                 TitulationProcess.current_phase.in_(fases)).count())
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
    def list_settings(db: Session, catalog: list[dict] | None = None) -> list[dict]:
        """Un renglón por departamento del catálogo; sin ajustes, campos vacíos.

        `catalog` (opcional) evita volver a consultarlo si el llamador ya lo
        tiene. Los ajustes salen en UNA consulta (antes, una por departamento).
        """
        from itcj2.apps.titulatec.models import DepartmentSettings

        deptos = (catalog if catalog is not None
                  else ProgramDepartmentService.academic_departments_catalog(db))
        ids = [d["id"] for d in deptos]
        ajustes = ({s.department_id: s for s in db.query(DepartmentSettings)
                    .filter(DepartmentSettings.department_id.in_(ids)).all()} if ids else {})
        out = []
        for d in deptos:
            s = ajustes.get(d["id"])
            out.append({
                "department_id": d["id"], "code": d["code"], "name": d["name"],
                "oficio_header": s.oficio_header if s else "",
                "addressee_position_code": s.addressee_position_code if s else "",
                "attn_position_code": (s.attn_position_code if s else "") or "",
                "addressee_title": (s.addressee_title if s else "") or "",
                "attn_title": (s.attn_title if s else "") or "",
                "configured": s is not None,
            })
        return out

    @staticmethod
    def update_settings(db: Session, actor_id: int, department_id: int, *,
                        oficio_header, addressee_position_code, attn_position_code=None,
                        addressee_title=None, attn_title=None) -> bool:
        """Crea o edita los ajustes del oficio de un departamento (R-F).

        Los códigos de puesto deben existir en `core_positions` (el oficio los
        resuelve a la persona que lo ocupa al generarse). Los títulos son
        opcionales (hasta `MAX_TITLE`); vacío = el título del puesto. Devuelve
        `False` sin cambios.
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
        titulo_dest = _clean(addressee_title)
        titulo_atn = _clean(attn_title)
        for titulo in (titulo_dest, titulo_atn):
            if titulo is not None and len(titulo) > MAX_TITLE:
                raise ValueError(TITLE_TOO_LONG_MSG)
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
                 "attn_position_code": attn, "addressee_title": titulo_dest,
                 "attn_title": titulo_atn}
        if before == after:
            return False
        if row is None:
            row = DepartmentSettings(department_id=department_id)
            db.add(row)
        row.oficio_header = header
        row.addressee_position_code = addressee
        row.attn_position_code = attn
        row.addressee_title = titulo_dest
        row.attn_title = titulo_atn
        row.updated_at = db_now()
        row.updated_by_id = actor_id

        b, a = AuditService.changes(before, after)
        AuditService.record(
            db, "department_settings.changed", entity_type="department",
            entity_id=department_id, subject=dept.name, before=b, after=a,
            actor_id=actor_id)
        db.commit()
        return True
