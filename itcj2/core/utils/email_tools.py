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
