"""program_display_name: etiqueta de la carrera en la tarjeta."""
from itcj2.apps.credencial.services.display import program_display_name


def test_display_name_strips_suffix_and_fixes_case():
    assert program_display_name("Ing. Sistemas computacionales") == "Ing. Sistemas Computacionales"
    assert program_display_name("Ing. Sistemas computacionales EAD") == "Ing. Sistemas Computacionales"
    assert program_display_name("Contador publico") == "Contador Público"
    assert program_display_name("Contador Público CAMPUS II") == "Contador Público"


def test_display_name_unknown_returns_name_without_suffix():
    assert program_display_name("Carrera Rara EAD") == "Carrera Rara"
    assert program_display_name(None) is None
    assert program_display_name("  ") is None


# ── fit_class: las líneas caben en la tarjeta sin JS ──────────────────────────
from itcj2.apps.credencial.services.display import FIT_FLOOR, _LINE_EM, _line_em, fit_class  # noqa: E402

WORST_NAME = "Daniel Arturo Amador Gordillo Amador Gordillo / 21111182"           # máximo real en dev
WORST_PROGRAM = "Maestría en Administración de Negocios Internacionales / Egresado"  # 65 caracteres


def _scale(cls: str) -> int:
    return int(cls.split("cc-fit-")[1].split()[0]) if "cc-fit-" in cls else 100


def test_fit_class_short_lines_keep_base_size():
    assert fit_class("Ernesto Villarreal Ibarra / 21111182") == ""
    assert fit_class("Ing. Sistemas Computacionales / Estudiante") == ""
    assert fit_class("Instituto Tecnológico de Ciudad Juárez") == ""


def test_fit_class_worst_real_cases_shrink_and_fit():
    for line in (WORST_NAME, WORST_PROGRAM):
        cls = fit_class(line)
        assert cls and "cc-wrap" not in cls, line
        assert _line_em(line) * _scale(cls) / 100 <= _LINE_EM, line


def test_fit_class_synthetic_60_char_name_fits_without_wrap():
    line = "María Guadalupe Alejandra Hernández Villaseñor de la Garza / 99000002"
    cls = fit_class(line)
    assert FIT_FLOOR <= _scale(cls) < 100 and "cc-wrap" not in cls


def test_fit_class_absurd_length_wraps_at_floor():
    cls = fit_class("Nombre " * 20 + "/ 21111182")
    assert cls == f" cc-fit-{FIT_FLOOR} cc-wrap"


def test_fit_class_counts_accents_and_unknown_glyphs():
    assert _line_em("ÁÉÍÓÚÑ") == _line_em("AEIOUN")
    assert _line_em("😀") > _line_em("n")
