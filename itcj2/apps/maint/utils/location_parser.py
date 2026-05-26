"""
Utilidades de parsing de ubicación para mantenimiento.

Extrae el identificador de edificio/área a partir del campo libre `location`
de un ticket para agrupar heatmaps por edificio.
"""
import re

# Patrón para extraer el token de edificio.
# Reconoce: Edificio X, Lab X, Aula X, Sala X, Taller X, Salón X,
#           Biblioteca, Oficina X.
_BUILDING_PATTERN = re.compile(
    r"^(edif(?:icio)?\s*\w+|lab\s*\w+|aula\s*\w+|sala\s*\w+|"
    r"taller\s*\w+|sal[oó]n\s*\w+|biblioteca|oficina\s*\w+)",
    re.IGNORECASE,
)

_NO_BUILDING = "Sin clasificar"


def parse_building(location: str | None) -> str:
    """Extrae el token de edificio de una cadena de ubicación libre.

    Aplica `_BUILDING_PATTERN` al inicio del string (ignorando espacios
    iniciales). Si no hay coincidencia devuelve ``"Sin clasificar"``.

    Ejemplos:
        "Edificio A, Aula 12"   → "Edificio A"
        "Lab Redes piso 2"      → "Lab Redes"
        "Biblioteca Central"    → "Biblioteca"
        "Estacionamiento sur"   → "Sin clasificar"
        None                    → "Sin clasificar"
    """
    if not location:
        return _NO_BUILDING
    m = _BUILDING_PATTERN.match(location.strip())
    if not m:
        return _NO_BUILDING
    return m.group(1).title()
