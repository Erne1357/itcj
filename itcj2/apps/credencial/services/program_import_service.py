"""Carrera de cada alumno desde los CSV del padrón (§5.5 del spec).

Los CSV traen NIP y CURP: `StudentRow` no los tiene, se descartan al leer.
"""
import csv
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from itcj2.apps.credencial.services.display import norm_key

logger = logging.getLogger(__name__)

DEFAULT_CSVS = (
    "database/CSV/Activos.csv",
    "database/CSV/Alumnos.csv",
    "database/CSV/Alumnos Activos 2026.csv",
    "database/CSV/Alumnos_Activos_20263.csv",
    "database/CSV/Alumnos_Aspirantes_20263.csv",
)
HEADERLESS_COLUMNS = (
    "no_de_control", "carrera", "reticula", "nombre_carrera", "estatus_alumno",
    "apellido_paterno", "apellido_materno", "nombre_alumno", "curp_alumno", "nip",
    "tipo alumno", "campus",
)
BATCH = 500

# nombre_carrera del CSV -> nombre base en core_programs (se compara sin acentos ni espacios)
PROGRAM_BASE_MAP: dict[str, str] = {
    "INGENIERIA EN SISTEMAS COMPUTACIONALES": "Ing. Sistemas computacionales",
    "INGENIERIA EN TECNOLOGIAS DE LA INFORMACION Y COMUNICACIONES": "Ing. Tics",
    "INGENIERIA EN CIBERSEGURIDAD": "Ciberseguridad",
    "INGENIERIA EN GESTION EMPRESARIAL": "Ing. Gestión Empresarial",
    "CONTADOR PUBLICO": "Contador publico",
    "LICENCIATURA EN ADMINISTRACION": "Lic. Administracion",
    "INGENIERIA ELECTROMECANICA": "Electromecánica",
    "INGENIERIA MECANICA": "Mecánica",
    "INGENIERIA EN SEMICONDUCTORES": "Semiconductores",
    "INGENIERIA EN LOGISTICA": "Ing. Logistica",
    "INGENIERIA INDUSTRIAL": "Ing. Industrial",
    "INGENIERIA INDUSTRIAL MODALIDAD MIXTA": "Ing. Industrial",
    "INGENIERIA ELECTRICA": "Eléctrica",
    "INGENIERIA ELECTRONICA": "Electrónica",
    "INGENIERIA MECATRONICA": "Mecatrónica",
    "MAESTRIA EN INGENIERIA INDUSTRIAL": "Maestría en Ingeniería Industrial",
    "MAESTRIA EN ADMINISTRACION DE NEGOCIOS INTERNACIONALES": "Maestría en Administración de Negocios Internacionales",
    "MAESTRIA EN INGENIERIA ADMINISTRATIVA": "Maestría en Ingeniería Administrativa",
    "DOCTORADO EN CIENCIAS DE LA INGENIERIA": "Doctorado en Ciencias de la Ingeniería",
}
_MAP_BY_KEY = {norm_key(k): v for k, v in PROGRAM_BASE_MAP.items()}


@dataclass
class StudentRow:
    control: str
    nombre_carrera: str
    reticula: str
    estatus: str
    tipo: str
    campus: str


@dataclass
class ProgramImportReport:
    updated: int = 0
    created: int = 0
    no_user: int = 0
    unmapped: Counter = field(default_factory=Counter)


def _clean(v: str) -> str:
    v = (v or "").strip()
    if len(v) >= 2 and v[0] == v[-1] == "'":
        v = v[1:-1]
    return v.strip()


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:  # los exportes de 20263 vienen en Windows-1252
        return raw.decode("cp1252", errors="replace")


def read_student_rows(paths: list[Path]) -> dict[str, StudentRow]:
    """Une los CSV por nº de control; el archivo más reciente (mtime) pisa a los viejos."""
    out: dict[str, StudentRow] = {}
    for path in sorted((Path(p) for p in paths), key=lambda p: p.stat().st_mtime):
        lines = [ln for ln in _read_text(path).splitlines() if ln.strip()]
        if not lines:
            continue
        delim = ";" if lines[0].count(";") > lines[0].count(",") else ","
        rows = list(csv.reader(lines, delimiter=delim))
        if _clean(rows[0][0]).lower() == "no_de_control":
            cols = [_clean(c).lower() for c in rows[0]]
            rows = rows[1:]
        else:
            cols = list(HEADERLESS_COLUMNS)
        for r in rows:
            d = {c: _clean(v) for c, v in zip(cols, r)}
            control = d.get("no_de_control", "")
            if not control:
                continue
            out[control] = StudentRow(
                control=control,
                nombre_carrera=d.get("nombre_carrera", ""),
                reticula=d.get("reticula", ""),
                estatus=d.get("estatus_alumno", ""),
                tipo=d.get("tipo alumno", ""),
                campus=d.get("campus", ""),
            )
    return out


def resolve_program_id(programs_by_name: dict[str, int], row: StudentRow) -> int | None:
    base = _MAP_BY_KEY.get(norm_key(row.nombre_carrera))
    if base is None:
        return None
    suffix = " EAD" if row.tipo.upper() == "EAD" else " CAMPUS II" if row.campus == "2" else ""
    return programs_by_name.get(base + suffix, programs_by_name.get(base))


class ProgramImportService:

    @staticmethod
    def apply(db: Session, rows: dict[str, StudentRow], *, overwrite: bool = False,
              dry_run: bool = False) -> ProgramImportReport:
        from itcj2.core.models.program import Program
        from itcj2.core.models.student_profile import StudentProfile
        from itcj2.core.models.user import User

        report = ProgramImportReport()
        programs = {name: pid for pid, name in db.query(Program.id, Program.name)}
        controls = list(rows)
        for i in range(0, len(controls), BATCH):
            chunk = controls[i:i + BATCH]
            users = dict(
                db.query(User.control_number, User.id).filter(User.control_number.in_(chunk)).all()
            )
            for control in chunk:
                row = rows[control]
                uid = users.get(control)
                if uid is None:
                    report.no_user += 1
                    continue
                pid = resolve_program_id(programs, row)
                if pid is None:
                    report.unmapped[row.nombre_carrera] += 1
                values = {
                    "program_id": pid, "program_text": row.nombre_carrera or None,
                    "reticula": row.reticula or None, "estatus_alumno": row.estatus or None,
                    "campus": row.campus or None,
                }
                profile = db.get(StudentProfile, uid)
                is_new = profile is None
                if is_new:
                    profile = StudentProfile(user_id=uid)
                    db.add(profile)
                changed = False
                for col, val in values.items():
                    cur = getattr(profile, col)
                    if val is not None and cur != val and (overwrite or cur is None):
                        setattr(profile, col, val)
                        changed = True
                if is_new:
                    report.created += 1
                elif changed:
                    report.updated += 1
            if dry_run:
                db.rollback()
            else:
                db.commit()
        return report
