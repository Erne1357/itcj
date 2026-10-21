"""
Validación pura del Formato B (spec fase 3 §5.1). Sin BD ni modelos: la consumen el
motor (FormatBService) y la UI del alumno. Las reglas que dependen de la modalidad
llegan por `ValidationCtx` (salen del catálogo, nunca de comparar códigos).
"""
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

EDITABLE_FIELDS: dict[int, tuple[str, ...]] = {
    1: ("gender", "age", "mobile_phone", "phone", "postal_code", "neighborhood",
        "street", "ext_number", "int_number"),
    2: ("modality_id", "study_plan", "admission_date", "graduation_date"),
    3: ("project_name",),
}

FIELD_LABELS: dict[str, str] = {
    "first_name": "Nombre(s)",
    "last_name": "Apellido paterno",
    "middle_name": "Apellido materno",
    "control_number": "Número de control",
    "program_id": "Carrera",
    "gender": "Sexo",
    "age": "Edad",
    "mobile_phone": "Celular",
    "phone": "Teléfono",
    "postal_code": "Código postal",
    "neighborhood": "Colonia",
    "street": "Calle",
    "ext_number": "Número exterior",
    "int_number": "Número interior",
    "modality_id": "Tipo de titulación",
    "titulation_type": "Tipo de titulación",
    "study_plan": "Plan de estudios",
    "admission_date": "Mes de ingreso",
    "graduation_date": "Mes de egreso",
    "project_name": "Nombre del proyecto",
}

_GENDERS = ("male", "female", "unspecified")
_MIN_ADMISSION = date(1980, 1, 1)
_MONTH_RE = re.compile(r"^(\d{4})-(\d{1,2})$")
_EXT_RE = re.compile(r"^[A-Za-z0-9 \-]+$")
_PHONE_SEPARATORS = re.compile(r"[\s\-().]")


@dataclass(frozen=True)
class ValidationCtx:
    today: date
    modality_ids: frozenset[int]
    # None = sin modalidad elegida → el proyecto se exige.
    requires_project: bool | None


class FormatBValidationError(ValueError):
    def __init__(self, errors: dict[str, str], step: int):
        self.errors = errors
        self.step = step
        super().__init__("; ".join(errors.values()) or "Formato B inválido")


def _text(raw: Any) -> str:
    """strip() + colapsar espacios internos; None → ''."""
    if raw is None:
        return ""
    return " ".join(str(raw).split())


def normalize_phone(raw: str | None) -> str | None:
    """Quita espacios, guiones, paréntesis, puntos y un '+52' inicial. None si queda vacío."""
    if raw is None:
        return None
    s = _PHONE_SEPARATORS.sub("", str(raw))
    if s.startswith("+52"):
        s = s[3:]
    return s or None


def _parse_month(raw: Any) -> date | None:
    """'YYYY-MM' (o date) → date(y, m, 1); None si no es un mes válido."""
    if isinstance(raw, date):
        return date(raw.year, raw.month, 1)
    m = _MONTH_RE.match(_text(raw))
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    if y < 1 or not 1 <= mo <= 12:
        return None
    return date(y, mo, 1)


def _validate_phone(raw: Any, label: str, required: bool, errors: dict, key: str, out: dict) -> None:
    phone = normalize_phone(_text(raw))
    if phone is None:
        if required:
            errors[key] = f"{label} es obligatorio"
        out[key] = None
        return
    if not (phone.isascii() and phone.isdigit() and len(phone) == 10):
        errors[key] = f"{label} debe tener 10 dígitos"
        return
    out[key] = phone


def _length(value: str, lo: int, hi: int, label: str, key: str, errors: dict) -> bool:
    if not value:
        errors[key] = f"{label} es obligatorio"
    elif len(value) < lo:
        errors[key] = f"{label} debe tener al menos {lo} caracteres"
    elif len(value) > hi:
        errors[key] = f"{label} no puede pasar de {hi} caracteres"
    else:
        return True
    return False


def _step1(raw: Mapping[str, Any], ctx: ValidationCtx):
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}

    gender = _text(raw.get("gender"))
    if gender in _GENDERS:
        out["gender"] = gender
    else:
        errors["gender"] = "Selecciona tu sexo" if not gender else "El sexo elegido no es válido"

    age_txt = _text(raw.get("age"))
    if not age_txt:
        errors["age"] = "La edad es obligatoria"
    elif not (age_txt.isascii() and age_txt.isdigit()) or not 18 <= int(age_txt) <= 99:
        errors["age"] = "La edad debe ser un número entre 18 y 99"
    else:
        out["age"] = int(age_txt)

    _validate_phone(raw.get("mobile_phone"), "El celular", True, errors, "mobile_phone", out)
    _validate_phone(raw.get("phone"), "El teléfono", False, errors, "phone", out)

    cp = _text(raw.get("postal_code"))
    if not cp:
        errors["postal_code"] = "El código postal es obligatorio"
    elif not (cp.isascii() and cp.isdigit() and len(cp) == 5):
        errors["postal_code"] = "El código postal debe tener 5 dígitos"
    else:
        out["postal_code"] = cp

    for key, label in (("neighborhood", "La colonia"), ("street", "La calle")):
        val = _text(raw.get(key))
        if _length(val, 2, 120, label, key, errors):
            out[key] = val

    ext = _text(raw.get("ext_number"))
    if not ext:
        errors["ext_number"] = "El número exterior es obligatorio"
    elif len(ext) > 10:
        errors["ext_number"] = "El número exterior no puede pasar de 10 caracteres"
    elif ext.upper() == "S/N" or _EXT_RE.match(ext):
        out["ext_number"] = ext.upper() if ext.upper() == "S/N" else ext
    else:
        errors["ext_number"] = "El número exterior solo admite letras, dígitos, guion o S/N"

    int_n = _text(raw.get("int_number"))
    if len(int_n) > 10:
        errors["int_number"] = "El número interior no puede pasar de 10 caracteres"
    else:
        out["int_number"] = int_n or None
    return out, errors


def _step2(raw: Mapping[str, Any], ctx: ValidationCtx):
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}

    mod_txt = _text(raw.get("modality_id"))
    if not mod_txt:
        errors["modality_id"] = "Elige el tipo de titulación"
    elif not (mod_txt.isascii() and mod_txt.isdigit()) or int(mod_txt) not in ctx.modality_ids:
        errors["modality_id"] = "El tipo de titulación elegido no es válido"
    else:
        out["modality_id"] = int(mod_txt)

    plan = _text(raw.get("study_plan")).upper()
    if _length(plan, 2, 40, "El plan de estudios", "study_plan", errors):
        out["study_plan"] = plan

    adm_raw, grad_raw = _text(raw.get("admission_date")), _text(raw.get("graduation_date"))
    adm = grad = None
    if not adm_raw:
        errors["admission_date"] = "El mes de ingreso es obligatorio"
    else:
        adm = _parse_month(raw.get("admission_date"))
        if adm is None:
            errors["admission_date"] = "El mes de ingreso no es válido"
        elif adm < _MIN_ADMISSION:
            errors["admission_date"] = "El mes de ingreso no puede ser anterior a enero de 1980"
            adm = None
    if not grad_raw:
        errors["graduation_date"] = "El mes de egreso es obligatorio"
    else:
        grad = _parse_month(raw.get("graduation_date"))
        if grad is None:
            errors["graduation_date"] = "El mes de egreso no es válido"
        elif grad > date(ctx.today.year, ctx.today.month, 1):
            errors["graduation_date"] = "El mes de egreso no puede ser posterior al mes actual"
            grad = None
    if adm and grad and adm >= grad:
        errors["graduation_date"] = "El mes de egreso debe ser posterior al de ingreso"
    if "admission_date" not in errors and adm:
        out["admission_date"] = adm
    if "graduation_date" not in errors and grad:
        out["graduation_date"] = grad
    return out, errors


def _step3(raw: Mapping[str, Any], ctx: ValidationCtx):
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}
    name = _text(raw.get("project_name"))
    if ctx.requires_project is False:
        out["project_name"] = None
    elif _length(name, 10, 500, "El nombre del proyecto", "project_name", errors):
        out["project_name"] = name
    return out, errors


_STEPS = {1: _step1, 2: _step2, 3: _step3}


def validate_step(step: int, raw: Mapping[str, Any], ctx: ValidationCtx) -> tuple[dict[str, Any], dict[str, str]]:
    """(valores normalizados SOLO de ese paso, errores por campo)."""
    if step not in _STEPS:
        raise ValueError(f"Paso inválido: {step}")
    return _STEPS[step](raw, ctx)


def _as_text(value: Any) -> Any:
    """Valor ya tipado del modelo → el texto que entiende validate_step."""
    if isinstance(value, date):
        return f"{value.year:04d}-{value.month:02d}"
    return value


def validate_all(values: Mapping[str, Any], ctx: ValidationCtx) -> None:
    """Valida los 3 pasos sobre valores ya guardados; lanza con el primer paso con errores."""
    raw = {k: _as_text(v) for k, v in values.items()}
    for step in sorted(_STEPS):
        _, errors = validate_step(step, raw, ctx)
        if errors:
            raise FormatBValidationError(errors, step)
