"""Número de control, correo institucional y folio."""
from __future__ import annotations

import re

from itcj2.apps.prorrogas_tec.services.formatting import MESES
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


def folio(req) -> str:
    """``PR-20263-05133``: código del semestre en el SII (año + 1 Ene-Jun, 2 verano, 3 Ago-Dic) y el id."""
    codigo = req.period.code if req.period_id else _codigo_de_etiqueta(req.period_label)
    return f"PR-{codigo}-{req.id:05d}"


def nombre_corto(first_name: str | None, last_name: str | None) -> str:
    """Primer apellido y primer nombre: ``PÉREZ`` + ``JUAN CARLOS`` → ``Pérez Juan`` (cabe en la barra del celular)."""
    return " ".join([(last_name or "").strip().title()] + (first_name or "").split()[:1]).title().strip()


def _codigo_de_etiqueta(etiqueta: str) -> str:
    """Históricas sin semestre de core: ``agosto – diciembre 2024`` → ``20243``."""
    p = etiqueta.split()
    mes = MESES.index(p[0]) + 1
    anio = p[1] if p[1].isdigit() else p[-1]  # ``agosto 2026 – enero 2027`` lleva el año junto al mes
    return f"{anio}{1 if mes < 6 else 2 if mes < 8 else 3}"
