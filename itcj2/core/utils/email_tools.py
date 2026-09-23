import os

MAIL_STUDENT_DOMAIN = os.getenv("EMAIL_DOMAIN", "cdjuarez.tecnm.mx")

def _norm_control(value: str) -> str:
    """Normaliza para comparar: strip, mayúsculas, sin una "L" inicial."""
    v = (value or "").strip().upper()
    if v.startswith("L"):
        v = v[1:]
    return v


def student_email(user) -> str:
    """
    Regla: si user.username existe → username@dominio
           si no → L{control_number}@dominio

    Excepción: el importador de TitulaTec crea alumnos con
    `username == control_number` (el número de control repetido, dígitos
    puros — NO es un usuario real, así que no lleva la "L" del buzón
    verdadero). Cuando el username normalizado coincide con el
    control_number normalizado igual, se trata como "sin username" y se
    aplica la forma `L{control}` — si no, esos alumnos salían con
    `90200034@...` en vez de `L90200034@...` (36 casos en dev; los 8,195
    del SII no tienen username y ya salían bien).
    """
    uname = (getattr(user, "username", None) or "").strip()
    cn = (getattr(user, "control_number", None) or "").strip()
    if uname and cn and _norm_control(uname) == _norm_control(cn):
        uname = ""
    if uname:
        return f"{uname}@{MAIL_STUDENT_DOMAIN}"
    if not cn:
        return ""  # caller decide si salta
    if cn.upper().startswith("L"):
        return f"{cn}@{MAIL_STUDENT_DOMAIN}"
    return f"L{cn}@{MAIL_STUDENT_DOMAIN}"


# ── Validación de correo institucional ───────────────────────────────────────
# El repo no tenía NINGÚN validador de email y `email-validator` no está en
# requirements: esta es la regex conservadora compartida, sin dependencia nueva.
#
# NO se lowercasea: el índice UNIQUE de core_positions.email es case-sensitive y
# ningún otro escritor lowercasea; hacerlo solo aquí crearía duplicados
# semánticos invisibles. El pre-check de unicidad sí compara sin distinguir caja.
import re  # noqa: E402

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")

MAX_EMAIL_LENGTH = 150


def normalize_email(value):
    """`strip()`; cadena vacía -> None. Nunca cambia la caja."""
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def is_valid_email(value) -> bool:
    if not value:
        return False
    text = str(value)
    if len(text) > MAX_EMAIL_LENGTH:
        return False
    return bool(_EMAIL_RE.match(text))
