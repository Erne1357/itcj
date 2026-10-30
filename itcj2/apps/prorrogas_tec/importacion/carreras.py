"""Equivalencias entre las carreras escritas en el Excel histórico y los nombres de ``core_programs``.

Si aparece una variante nueva, se agrega a ``_TABLA`` (una línea).
"""
from .normaliza import normalizar

# (variantes vistas en el Excel real, nombre oficial)
_TABLA: list[tuple[tuple[str, ...], str]] = [
    (("Contador Público",), "Contador publico"),
    (("Doctorado en Ciencias de la Ingeniería",), "Doctorado en Ciencias de la Ingeniería"),
    (("Ingeniería Electromecánica",), "Electromecánica"),
    (("Ingeniería Electrónica", "Ingeniería en Electrónica"), "Electrónica"),
    (("Ingeniería Eléctrica",), "Eléctrica"),
    (("Ingeniería Industrial", "Ingeniería Industrial (Curso de verano)"), "Ing. Industrial"),
    (("Ingeniería Industrial EAD",), "Ing. Industrial EAD"),
    (("Ingeniería Mecánica",), "Mecánica"),
    (("Ingeniería en Ciberseguridad",), "Ciberseguridad"),
    (("Ingeniería en Gestión Empresarial",), "Ing. Gestión Empresarial"),
    (("Ingeniería en Gestión Empresarial EAD", "Ingeniería en Gestión Empresaria EAD",
      "Ingeniería en Gestíon Empresarial EAD"), "Ing. Gestión Empresarial EAD"),
    (("Ingeniería en Logística",), "Ing. Logistica"),
    (("Ingeniería en Mecatrónica",), "Mecatrónica"),
    (("Ingeniería en Semiconductores",), "Semiconductores"),
    (("Ingeniería en Sistemas Computacionales", "Ingenierpia en Sistemas Computacionales"),
     "Ing. Sistemas computacionales"),
    (("Ingeniería en Sistemas Computacionales EAD",), "Ing. Sistemas computacionales EAD"),
    (("TIC'S", "TIC´S", "Ingeniería en TIC´S"), "Ing. Tics"),
    (("Licenciatura en Administración", "Licenciatura en Administración de Empresas"), "Lic. Administracion"),
    (("Maestría en Ingeniería Administrativa",), "Maestría en Ingeniería Administrativa"),
    (("Maestría en Ingeniería Industrial",), "Maestría en Ingeniería Industrial"),
    (("Maestría en Negocios Internacionales",), "Maestría en Administración de Negocios Internacionales"),
]

EQUIVALENCIAS: dict[str, str] = {normalizar(v): oficial for variantes, oficial in _TABLA for v in variantes}
