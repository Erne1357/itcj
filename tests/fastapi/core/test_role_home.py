"""`role_home` — a dónde cae quien ya tiene sesión y abre `/itcj/login`.

Desde 2026-09-15 el alumno de titulación es `graduate` (egresado) y
`ImportService.import_rows` le asigna ese rol en la app `itcj`. Sin entrada
propia, `role_home({"graduate"})` caía al final (`/itcj/dashboard`), que a su vez
lo rebota a `/itcj/m/` porque no tiene rol de escritorio
(`core/pages/dashboard.py`): un salto de más en cada login. El egresado va directo
al shell móvil, igual que `student`.
"""
from itcj2.core.utils.role_home import role_home


def test_graduate_va_al_shell_movil():
    assert role_home({"graduate"}) == "/itcj/m/"


def test_graduate_como_string_tambien():
    assert role_home("graduate") == "/itcj/m/"


def test_un_rol_de_escritorio_gana_sobre_graduate():
    """Un `staff` que se titula sigue entrando a su escritorio."""
    assert role_home({"staff", "graduate"}) == "/itcj/dashboard"


def test_student_no_cambia():
    assert role_home({"student"}) == "/itcj/m/"


def test_sin_roles_va_a_la_raiz():
    assert role_home(set()) == "/"
