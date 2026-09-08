import os

MAIL_STUDENT_DOMAIN = os.getenv("EMAIL_DOMAIN", "cdjuarez.tecnm.mx")

def student_email(user) -> str:
    """
    Regla: si user.username existe → username@dominio
           si no → L{control_number}@dominio
    """
    uname = (getattr(user, "username", None) or "").strip()
    if uname:
        return f"{uname}@{MAIL_STUDENT_DOMAIN}"
    cn = (getattr(user, "control_number", None) or "").strip()
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
