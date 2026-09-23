"""`student_email(user)`: el buzón real de un alumno, no un alias inventado.

El importador de TitulaTec crea alumnos con `username == control_number`
(el número de control repetido, dígitos puros, sin la "L" del buzón real).
La regla vieja `username existe -> username@dominio` los mandaba a
`90200034@...` en vez de `L90200034@...` (36 usuarios en dev). Los 8,195
alumnos del SII no tienen `username` y ya salían bien por la otra rama.

Sin BD: `student_email` solo lee atributos, así que un `SimpleNamespace`
basta (mismo patrón que `test_eligibility.py`).
"""
from types import SimpleNamespace

from itcj2.core.utils.email_tools import MAIL_STUDENT_DOMAIN, student_email


def _user(username=None, control_number=None):
    return SimpleNamespace(username=username, control_number=control_number)


def test_username_igual_al_control_en_digitos_usa_la_forma_l():
    """El caso del importador de TitulaTec: 36 usuarios en dev."""
    user = _user(username="90200034", control_number="90200034")

    assert student_email(user) == f"L90200034@{MAIL_STUDENT_DOMAIN}"


def test_username_l_mas_control_no_duplica_la_l():
    user = _user(username="L90200034", control_number="90200034")

    assert student_email(user) == f"L90200034@{MAIL_STUDENT_DOMAIN}"


def test_sin_username_usa_l_mas_control_sin_cambios():
    """Los 8,195 alumnos del SII: sin username, ya salían bien."""
    user = _user(username=None, control_number="90200035")

    assert student_email(user) == f"L90200035@{MAIL_STUDENT_DOMAIN}"


def test_control_que_ya_empieza_con_l_no_se_duplica():
    user = _user(username=None, control_number="L1234567")

    assert student_email(user) == f"L1234567@{MAIL_STUDENT_DOMAIN}"


def test_personal_con_username_normal_no_se_toca():
    """`mmartinez` no es el número de control repetido: es un usuario real."""
    user = _user(username="mmartinez", control_number=None)

    assert student_email(user) == f"mmartinez@{MAIL_STUDENT_DOMAIN}"


def test_sin_username_ni_control_devuelve_cadena_vacia():
    """El llamador decide si salta (docstring de `student_email`)."""
    user = _user(username=None, control_number=None)

    assert student_email(user) == ""
