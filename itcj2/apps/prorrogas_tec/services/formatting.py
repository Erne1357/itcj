"""Formato de los valores que se imprimen en las cartas de prórroga.

Los formatos salen de las cartas reales de la Subdirección (Antecedentes):
fecha corta ``13/enero/2026``, fecha larga ``26 de febrero de 2026``, montos
``$3,150.00`` y nombre en mayúsculas con los apellidos primero.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

MESES: tuple[str, ...] = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

MAX_PAGOS = 3


def fecha_corta(d: date) -> str:
    """``13/enero/2026`` (la fecha de emisión de las cartas)."""
    return f"{d.day:02d}/{MESES[d.month - 1]}/{d.year}"


def fecha_larga(d: date) -> str:
    """``26 de febrero de 2026`` (las fechas de pago)."""
    return f"{d.day:02d} de {MESES[d.month - 1]} de {d.year}"


def pesos(amount: Decimal) -> str:
    """``$3,150.00``."""
    return f"${Decimal(amount):,.2f}"


def nombre_oficial(first_name: str, last_name: str, middle_name: str | None) -> str:
    """Apellido paterno, materno y nombre(s), en mayúsculas.

    En ``core_users`` ``last_name`` es el apellido paterno y ``middle_name`` el
    materno (ver ``core/api/users_admin.py::create_user``).
    """
    partes = (last_name, middle_name, first_name)
    return " ".join(" ".join(p.split()) for p in partes if p and p.strip()).upper()


def semestre_label(start: date, end: date) -> str:
    """``enero – junio 2026``; si cruza de año, ``agosto 2026 – enero 2027``."""
    m1, m2 = MESES[start.month - 1], MESES[end.month - 1]
    if start.year == end.year:
        return f"{m1} – {m2} {end.year}"
    return f"{m1} {start.year} – {m2} {end.year}"


def split_amount(total: Decimal, n: int) -> list[Decimal]:
    """Reparte ``total`` en ``n`` pagos de pesos enteros.

    El sobrante de pesos va a los primeros pagos y los centavos al último:
    $3,650 en 3 → $1,217 · $1,217 · $1,216, como en la carta real de 3 pagos.
    """
    total = Decimal(total)
    if not 1 <= n <= MAX_PAGOS:
        raise ValueError(f"El número de pagos debe estar entre 1 y {MAX_PAGOS}.")
    if total <= 0:
        raise ValueError("El monto debe ser mayor que cero.")
    enteros = int(total)
    centavos = total - enteros
    base, sobrante = divmod(enteros, n)
    partes = [Decimal(base + 1 if i < sobrante else base) for i in range(n)]
    partes[-1] += centavos
    return partes
