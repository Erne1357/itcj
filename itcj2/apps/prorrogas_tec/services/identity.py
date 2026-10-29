"""Número de control, correo institucional y folio."""
from __future__ import annotations

import re

from itcj2.core.utils.email_tools import MAIL_STUDENT_DOMAIN

_CONTROL = re.compile(r"[A-Z]?\d{8}")
# Prefijos con buzón institucional; los demás (D, B...) no tienen correo.
_CON_CORREO = ("L", "M")


def normalize_control(raw: str) -> str:
    c = (raw or "").strip().upper()
    if not _CONTROL.fullmatch(c):
        raise ValueError("Número de control inválido")
    return c


def institutional_email(control: str) -> str | None:
    c = normalize_control(control)
    if c[0].isdigit():
        c = f"L{c}"
    return f"{c}@{MAIL_STUDENT_DOMAIN}" if c[0] in _CON_CORREO else None


def folio(request_id: int) -> str:
    return f"PR-{request_id:05d}"
