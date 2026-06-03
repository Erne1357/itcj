"""Importación de alumnos de una convocatoria desde CSV (formato del Forms, flexible).

No hardcodea encabezados: detecta columnas por heurística y permite ajuste manual.
Flujo: parse → autodetect mapping → validate (preview) → import.
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from pathlib import Path

from sqlalchemy.orm import Session

from itcj2.config import get_settings

# Campos destino (semánticos). El admin mapea cada uno a un encabezado del CSV.
TARGET_FIELDS = ["control_number", "full_name", "email", "career", "modality"]

# Palabras clave para auto-detección por encabezado normalizado.
_FIELD_KEYWORDS = {
    "control_number": ["control", "matricula", "no control", "numero de control", "num control"],
    "full_name": ["nombre", "alumno", "estudiante"],
    "email": ["correo", "email", "e mail", "mail"],
    "career": ["carrera", "programa", "plan"],
    "modality": ["modalidad", "opcion de titulacion", "tipo de titulacion", "titulacion"],
}

_INSTITUTIONAL_DOMAIN = "@cdjuarez.tecnm.mx"


def _norm(s: str) -> str:
    """Normaliza: minúsculas, sin acentos, sin puntuación, espacios colapsados."""
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _imports_dir() -> Path:
    d = Path(get_settings().TITULATEC_UPLOAD_PATH) / "_imports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mapping_store() -> Path:
    return _imports_dir() / "_mapping.json"


class ImportService:
    # ---------- persistencia del token (CSV temporal) ----------
    @staticmethod
    def save_temp(raw: bytes, token: str) -> None:
        (_imports_dir() / f"{token}.csv").write_bytes(raw)

    @staticmethod
    def read_temp(token: str) -> bytes | None:
        p = _imports_dir() / f"{token}.csv"
        return p.read_bytes() if p.exists() else None

    @staticmethod
    def delete_temp(token: str) -> None:
        (_imports_dir() / f"{token}.csv").unlink(missing_ok=True)

    # ---------- mapeo reusable ----------
    @staticmethod
    def load_saved_mapping() -> dict:
        p = _mapping_store()
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    @staticmethod
    def save_mapping(mapping: dict) -> None:
        try:
            _mapping_store().write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    # ---------- parsing ----------
    @staticmethod
    def parse(raw: bytes) -> tuple[list[str], list[dict]]:
        """Devuelve (headers, rows). Detecta delimitador (',' o ';')."""
        text = raw.decode("utf-8-sig", errors="replace")
        sample = text[:2048]
        delim = ";" if sample.count(";") > sample.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delim)
        headers = reader.fieldnames or []
        rows = [dict(r) for r in reader]
        return headers, rows

    @staticmethod
    def autodetect_mapping(headers: list[str]) -> dict:
        """Mapea cada target field al encabezado más probable (o '')."""
        saved = ImportService.load_saved_mapping()
        mapping: dict[str, str] = {}
        norm_headers = {h: _norm(h) for h in headers}
        for field in TARGET_FIELDS:
            # 1) si el mapeo guardado apunta a un encabezado presente, úsalo
            if saved.get(field) in headers:
                mapping[field] = saved[field]
                continue
            # 2) heurística por keywords
            chosen = ""
            for h in headers:
                nh = norm_headers[h]
                if any(kw in nh for kw in _FIELD_KEYWORDS[field]):
                    chosen = h
                    break
            mapping[field] = chosen
        return mapping

    # ---------- matching de catálogos ----------
    @staticmethod
    def _match_program(db: Session, value: str):
        from itcj2.core.models.program import Program
        if not value:
            return None
        nv = _norm(value)
        programs = db.query(Program).all()
        # match exacto normalizado, luego contains
        for p in programs:
            if _norm(p.name) == nv:
                return p
        for p in programs:
            np = _norm(p.name)
            if nv and (nv in np or np in nv):
                return p
        return None

    @staticmethod
    def _match_modality(db: Session, value: str):
        from itcj2.apps.titulatec.models import Modality
        if not value:
            return None
        nv = _norm(value)
        mods = db.query(Modality).filter_by(is_active=True).all()
        for m in mods:
            if _norm(m.code) == nv or _norm(m.name) == nv:
                return m
        for m in mods:
            if nv in _norm(m.name) or any(tok in nv for tok in _norm(m.code).split("_")):
                return m
        return None

    # ---------- validación / preview ----------
    @staticmethod
    def build_preview(db: Session, rows: list[dict], mapping: dict) -> list[dict]:
        """Para cada fila devuelve datos normalizados + matches + issues + status."""
        out = []
        for i, row in enumerate(rows):
            def cell(field):
                h = mapping.get(field)
                return (row.get(h) or "").strip() if h else ""

            control = cell("control_number")
            full_name = cell("full_name")
            email = cell("email")
            career_raw = cell("career")
            modality_raw = cell("modality")

            program = ImportService._match_program(db, career_raw)
            modality = ImportService._match_modality(db, modality_raw)

            issues = []
            if not control:
                issues.append(("error", "Sin número de control"))
            if not full_name:
                issues.append(("error", "Sin nombre"))
            if email and not email.lower().endswith(_INSTITUTIONAL_DOMAIN):
                issues.append(("warning", "Correo no institucional"))
            if not email:
                issues.append(("warning", "Sin correo"))
            if career_raw and not program:
                issues.append(("warning", f"Carrera no reconocida: {career_raw}"))
            if modality_raw and not modality:
                issues.append(("warning", f"Modalidad no reconocida: {modality_raw}"))

            status = "ok"
            if any(t == "error" for t, _ in issues):
                status = "error"
            elif issues:
                status = "warning"

            out.append({
                "idx": i,
                "control_number": control,
                "full_name": full_name,
                "email": email,
                "career_raw": career_raw,
                "modality_raw": modality_raw,
                "program_id": program.id if program else None,
                "program_name": program.name if program else None,
                "modality_id": modality.id if modality else None,
                "modality_name": modality.name if modality else None,
                "issues": issues,
                "status": status,
            })
        return out

    # ---------- importación ----------
    @staticmethod
    def import_rows(db: Session, cohort, rows: list[dict]) -> dict:
        """Crea User (merge por control_number) + Process + phases + rol student.

        `rows` = lista de dicts ya resueltos (del preview/override del admin):
        {control_number, full_name, email, program_id, modality_id}.
        Devuelve summary.
        """
        from itcj2.core.models.user import User
        from itcj2.core.models.role import Role
        from itcj2.apps.titulatec.models import TitulationProcess, ProcessPhase
        from itcj2.core.services.authz_service import grant_role

        student_role = db.query(Role).filter_by(name="student").first()
        period_code = cohort.period_code or str(cohort.period_id)

        # folio: continúa la numeración del cohort
        existing = db.query(TitulationProcess).filter_by(cohort_id=cohort.id).count()
        seq = existing

        created_users = matched_users = processes_created = skipped = 0

        for r in rows:
            control = (r.get("control_number") or "").strip()
            full_name = (r.get("full_name") or "").strip()
            if not control or not full_name:
                skipped += 1
                continue

            user = db.query(User).filter_by(control_number=control).first()
            if user:
                matched_users += 1
                if r.get("email") and not user.email:
                    user.email = r["email"]
            else:
                # split simple: último token = apellido, resto = nombres
                parts = full_name.split()
                last = parts[-1] if len(parts) > 1 else full_name
                first = " ".join(parts[:-1]) if len(parts) > 1 else full_name
                user = User(
                    username=control, control_number=control,
                    first_name=first, last_name=last,
                    email=r.get("email") or None,
                    role_id=student_role.id if student_role else None,
                    is_active=True, must_change_password=True,
                )
                db.add(user)
                db.flush()
                created_users += 1

            grant_role(db, user.id, "titulatec", "student")

            proc = db.query(TitulationProcess).filter_by(student_id=user.id, cohort_id=cohort.id).first()
            if not proc:
                seq += 1
                proc = TitulationProcess(
                    folio=f"TT-{period_code}-{seq:04d}",
                    student_id=user.id, cohort_id=cohort.id,
                    program_id=r.get("program_id"), modality_id=r.get("modality_id"),
                    current_phase=1, status="active", is_app_active=True,
                )
                db.add(proc)
                db.flush()
                # fase 0 aprobada (intake), fase 1 en curso, resto pendiente
                for n in range(9):
                    st = "approved" if n == 0 else ("in_progress" if n == 1 else "pending")
                    db.add(ProcessPhase(process_id=proc.id, phase_number=n, status=st))
                processes_created += 1

                from itcj2.apps.titulatec.services.notify import notify_student
                notify_student(db, user.id, type="PROCESS_CREATED",
                               title="Tu proceso de titulación está activo",
                               body="Servicios Escolares te dio de alta. Empieza subiendo tus documentos iniciales.",
                               process_id=proc.id, phase_number=1)

        db.commit()
        return {
            "created_users": created_users,
            "matched_users": matched_users,
            "processes_created": processes_created,
            "skipped": skipped,
        }
