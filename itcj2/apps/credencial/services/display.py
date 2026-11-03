"""Etiqueta de despliegue de la carrera en la credencial."""
import re
import unicodedata

_SUFFIX = re.compile(r"\s+(EAD|CAMPUS II)\s*$", re.IGNORECASE)

# nombre base en core_programs -> forma con mayúsculas y acentos para la tarjeta
DISPLAY_NAMES: dict[str, str] = {
    "Ing. Sistemas computacionales": "Ing. Sistemas Computacionales",
    "Ing. Tics": "Ing. TICs",
    "Ciberseguridad": "Ing. en Ciberseguridad",
    "Ing. Gestión Empresarial": "Ing. Gestión Empresarial",
    "Contador publico": "Contador Público",
    "Lic. Administracion": "Lic. Administración",
    "Electromecánica": "Ing. Electromecánica",
    "Mecánica": "Ing. Mecánica",
    "Semiconductores": "Ing. en Semiconductores",
    "Ing. Logistica": "Ing. Logística",
    "Ing. Industrial": "Ing. Industrial",
    "Eléctrica": "Ing. Eléctrica",
    "Electrónica": "Ing. Electrónica",
    "Mecatrónica": "Ing. Mecatrónica",
    "Maestría en Ingeniería Industrial": "Maestría en Ingeniería Industrial",
    "Maestría en Administración de Negocios Internacionales": "Maestría en Administración de Negocios Internacionales",
    "Maestría en Ingeniería Administrativa": "Maestría en Ingeniería Administrativa",
    "Doctorado en Ciencias de la Ingeniería": "Doctorado en Ciencias de la Ingeniería",
}


def norm_key(text: str) -> str:
    """Mayúsculas, sin acentos ni espacios/puntuación: tolera 'LAINGENIERIA' y 'Lic. Administración'."""
    t = unicodedata.normalize("NFKD", text or "")
    return re.sub(r"[^A-Z0-9]", "", "".join(c for c in t if not unicodedata.combining(c)).upper())


_DISPLAY_BY_KEY = {norm_key(k): v for k, v in DISPLAY_NAMES.items()}


def program_display_name(program_name: str | None) -> str | None:
    if not program_name or not program_name.strip():
        return None
    base = _SUFFIX.sub("", program_name.strip())
    return _DISPLAY_BY_KEY.get(norm_key(base), base)
