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
