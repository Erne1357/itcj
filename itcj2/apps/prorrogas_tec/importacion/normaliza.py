"""Normalizadores puros del Excel histórico: fechas, importes, banderas, controles y carreras."""
import math
import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal

from ..services.errors import ServiceError
from ..services.formatting import MESES as _MESES, parse_monto

MESES: dict[str, int] = {m: i for i, m in enumerate(_MESES, 1)} | {"setiembre": 9}

_EXCEL_BASE = date(1899, 12, 30)
_RE_LARGA = re.compile(r"(\d{1,2})\s+de\s+([a-záéíóú]+)(?:\s+(?:de\s+)?(\d{4}))?", re.IGNORECASE)
_RE_CORTA = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})")
_RE_TOKEN = re.compile(r"\$?\s*[0-9][0-9.,]*")


class NoInterpretable(ValueError):
    """Un dato del Excel que no se pudo interpretar; ``motivo`` es el texto del problema."""

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


def normalizar(texto) -> str:
    """Minúsculas, sin acentos, ``´`` y ``’`` iguales a ``'``, espacios colapsados."""
    # los apóstrofos se unifican ANTES de NFKD, que descompone ´ en espacio + acento
    t = str(texto).lower().replace("´", "'").replace("’", "'")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.split())


def _vacio(raw) -> bool:
    return raw is None or (isinstance(raw, str) and not raw.strip())


def parse_fechas(raw, *, anio: int) -> list[date]:
    """Una o varias fechas de una celda; ``anio`` completa las que no traen año."""
    if _vacio(raw):
        return []
    if isinstance(raw, datetime):
        return [raw.date()]
    if isinstance(raw, date):
        return [raw]
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if 20000 <= raw <= 80000:
            return [_EXCEL_BASE + timedelta(days=int(raw))]
        raise NoInterpretable("fecha ilegible")
    if not isinstance(raw, str):
        raise NoInterpretable("fecha ilegible")
    hallazgos = []  # (posición, año, mes, día)
    for m in _RE_LARGA.finditer(raw):
        mes = MESES.get(m.group(2).lower())
        if mes is None:
            raise NoInterpretable("fecha ilegible")
        hallazgos.append((m.start(), int(m.group(3) or anio), mes, int(m.group(1))))
    for m in _RE_CORTA.finditer(raw):
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        if y < 2000:
            raise NoInterpretable("fecha ilegible")
        hallazgos.append((m.start(), y, int(m.group(2)), int(m.group(1))))
    resto = _RE_CORTA.sub(" ", _RE_LARGA.sub(" ", raw))
    if not hallazgos or re.search(r"\d", resto):
        raise NoInterpretable("fecha ilegible")
    try:
        return [date(y, mes, d) for _, y, mes, d in sorted(hallazgos)]
    except ValueError:
        raise NoInterpretable("fecha ilegible") from None


def _token_a_monto(token: str) -> Decimal:
    """Último separador + 2 dígitos = decimal; + 3 dígitos = miles; otra cosa es ilegible.

    Los grupos intermedios deben ser de 3 dígitos (o vacíos: ``$3,.000.00`` es un dedazo conocido).
    Con separador de miles, el primer grupo es de 1 a 3 dígitos: ``1234,567`` no es 1,234,567.
    """
    grupos = re.split(r"[.,]", token.replace("$", "").replace(" ", ""))
    miles = len(grupos) > (2 if len(grupos[-1]) == 2 else 1)
    if len(grupos) > 1 and (len(grupos[-1]) not in (2, 3) or any(len(g) not in (0, 3) for g in grupos[1:-1])
                            or (miles and len(grupos[0]) > 3)):
        raise NoInterpretable("importe ilegible")
    if len(grupos) == 1:
        return parse_monto(grupos[0])
    if len(grupos[-1]) == 2:
        return parse_monto("".join(grupos[:-1]) + "." + grupos[-1])
    return parse_monto("".join(grupos))


def parse_importes(raw) -> list[Decimal]:
    """Uno o varios importes de una celda, siempre en ``Decimal``."""
    if _vacio(raw):
        return []
    try:
        if isinstance(raw, (int, float, Decimal)) and not isinstance(raw, bool):
            return [parse_monto(str(raw))]
        if not isinstance(raw, str):
            raise NoInterpretable("importe ilegible")
        tokens = _RE_TOKEN.findall(raw)
        if not tokens or _RE_TOKEN.sub("", raw).strip():
            raise NoInterpretable("importe ilegible")
        return [_token_a_monto(t) for t in tokens]
    except ServiceError:
        raise NoInterpretable("importe ilegible") from None


def parse_bandera(raw) -> bool:
    """Bandera de pagado: ``1`` o vacía → True, ``0`` → False, lo demás es problema."""
    if _vacio(raw):
        return True
    v = raw.strip() if isinstance(raw, str) else raw
    if v in (1, "1"):  # True == 1 y 1.0 == 1
        return True
    if v in (0, "0"):
        return False
    raise NoInterpretable("bandera ilegible")


def parse_control(raw) -> str:
    """Número de control: ``^[A-Z]?\\d{8}$`` tras ``strip().upper()``."""
    if isinstance(raw, float) and not (math.isfinite(raw) and raw == int(raw)):
        raise NoInterpretable("número de control inválido")
    s = str(int(raw)) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else str(raw or "").strip().upper()
    if not re.fullmatch(r"[A-Z]?\d{8}", s):
        raise NoInterpretable("número de control inválido")
    return s


def mapear_carrera(texto: str) -> str:
    """Nombre oficial de ``core_programs`` para una carrera escrita como viene en el Excel."""
    from .carreras import EQUIVALENCIAS  # import tardío: carreras usa normalizar de este módulo

    try:
        return EQUIVALENCIAS[normalizar(texto)]
    except KeyError:
        raise NoInterpretable("carrera sin equivalencia") from None
