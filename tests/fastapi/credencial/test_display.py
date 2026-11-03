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
from itcj2.apps.credencial.services.display import (  # noqa: E402
    _HEADROOM, _LINE_EM, FIT_FLOOR, FIT_MIN, _line_em, fit_class,
)

WORST_NAME = "Daniel Arturo Amador Gordillo Amador Gordillo / 21111182"           # máximo real en dev
WORST_PROGRAM = "Maestría en Administración de Negocios Internacionales / Egresado"  # 65 caracteres


def _scale(cls: str) -> int:
    return int(cls.split("cc-fit-")[1].split()[0]) if "cc-fit-" in cls else 100


def test_fit_class_short_lines_keep_base_size():
    assert fit_class("Ernesto Villarreal Ibarra / 21111182") == ""
    assert fit_class("Ing. Sistemas Computacionales / Estudiante") == ""
    assert fit_class("Instituto Tecnológico de Ciudad Juárez") == ""


def test_fit_class_worst_real_name_shrinks_with_headroom():
    cls = fit_class(WORST_NAME)
    assert cls and "cc-wrap" not in cls and _scale(cls) >= FIT_MIN
    assert _line_em(WORST_NAME) * _HEADROOM * _scale(cls) / 100 <= _LINE_EM


def test_fit_class_never_single_line_below_80():
    """Matriz T7: a 360 px una línea de 71 caracteres quedaba en ~6 px; ahora se parte antes."""
    for line in (WORST_PROGRAM, "María Guadalupe Alejandra Hernández Villaseñor de la Garza / 99000002"):
        cls = fit_class(line)
        assert cls == f" cc-fit-{FIT_MIN} cc-wrap", line
        # dos renglones a 80% alcanzan
        assert _line_em(line) * _HEADROOM * FIT_MIN / 100 <= 2 * _LINE_EM * 0.85, line


def test_fit_class_every_single_line_fits_with_headroom():
    for n in range(10, 120):
        line = ("Nombre Apellido " * 10)[:n] + " / 21111182"
        cls = fit_class(line)
        if "cc-wrap" not in cls:
            assert _scale(cls) >= FIT_MIN, line
            assert _line_em(line) * _HEADROOM * _scale(cls) / 100 <= _LINE_EM, line


def test_fit_class_absurd_length_wraps_at_floor():
    cls = fit_class("Nombre " * 20 + "/ 21111182")
    assert cls == f" cc-fit-{FIT_FLOOR} cc-wrap"


def test_fit_class_counts_accents_and_unknown_glyphs():
    assert _line_em("ÁÉÍÓÚÑ") == _line_em("AEIOUN")
    assert _line_em("😀") > _line_em("n")
