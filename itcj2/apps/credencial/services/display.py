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


# ── Ajuste de las líneas impresas al ancho de la tarjeta (sin JS: sirve al hero) ──
# Avance de Montserrat SemiBold en milésimas de em, medido con canvas en el navegador;
# una letra acentuada mide lo mismo que su base. Lo desconocido cuenta como ancho.
_ADV = dict(zip(
    " !\"'(),-./0123456789:;?&"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    (276, 278, 413, 220, 347, 348, 244, 385, 244, 371,
     673, 381, 582, 582, 679, 584, 627, 608, 652, 627, 244, 244, 581, 706,
     749, 761, 718, 826, 670, 637, 772, 810, 319, 527, 729, 599, 955, 810, 842, 726,
     842, 731, 629, 602, 789, 729, 1144, 693, 661, 663,
     607, 686, 581, 687, 622, 369, 694, 685, 289, 295, 635, 289, 1053, 685, 645, 686,
     686, 420, 515, 424, 681, 578, 919, 573, 578, 532),
    strict=True,
))
_UNKNOWN_ADV = 760
_TRACKING_EM = 0.035   # letter-spacing de .cc-lines (card.css)
_LINE_EM = 31.0        # ancho útil (100% - 7.38% - 3%) / 2.8cqi, con ~3% de holgura
_HEADROOM = 1.05       # el navegador midió +2-3 px sobre la tabla (matriz T7): margen extra
FIT_MIN = 80           # una línea sola no baja de 80%: antes se parte en dos renglones
FIT_FLOOR = 60         # piso de una línea partida (solo textos absurdos)
_WRAP_FILL = 0.85      # el corte por palabras deja hueco al final del primer renglón


def _line_em(text: str) -> float:
    total = 0
    for ch in text:
        base = unicodedata.normalize("NFKD", ch)[:1] or ch
        total += _ADV.get(base, _UNKNOWN_ADV)
    return total / 1000 + len(text) * _TRACKING_EM


def fit_class(text: str) -> str:
    """Clases de card.css para que la línea quepa: '' | ' cc-fit-NN' | ' cc-fit-NN cc-wrap'.

    NN es el % del tamaño base en pasos de 4; las medidas son proporcionales a la
    tarjeta, así que la misma clase vale para el hero y la tarjeta completa. Si a
    80% no cabe, se parte en dos renglones (el nº de control va en .cc-num, nowrap)
    con la letra que haga caber dos renglones, entre 60% y 80%.
    """
    em = _line_em(text) * _HEADROOM
    if em <= _LINE_EM:
        return ""
    pct = int(100 * _LINE_EM / em) // 4 * 4
    if pct >= FIT_MIN:
        return f" cc-fit-{pct}"
    pct = int(100 * 2 * _LINE_EM * _WRAP_FILL / em) // 4 * 4
    return f" cc-fit-{max(FIT_FLOOR, min(FIT_MIN, pct))} cc-wrap"
