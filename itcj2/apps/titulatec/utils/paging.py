"""Nucleo de paginacion compartido de las bandejas admin de TitulaTec.

Existe para que todas las bandejas (solicitudes, documentos, cotejo, ...)
paginen igual: mismo tamano (`PAGE_SIZE`), misma pagina fuera de rango (cae a
la ultima valida) y misma busqueda segura (spec 2026-10-04 §3.1).

Regla de desempate: todo `ORDER BY` paginado debe terminar en `id`. Sin ese
desempate dos filas con la misma clave pueden saltar o repetirse entre
paginas. Lo cumple quien arma la consulta; este modulo no puede imponerlo.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

PAGE_SIZE: int = 50
MAX_Q_LEN = 100


@dataclass(frozen=True)
class Page:
    items: list
    total: int
    page: int
    per_page: int

    @property
    def pages(self) -> int:
        return max(1, math.ceil(self.total / self.per_page))

    @property
    def start(self) -> int:
        return 0 if self.total == 0 else (self.page - 1) * self.per_page + 1

    @property
    def end(self) -> int:
        return 0 if self.total == 0 else min(self.page * self.per_page, self.total)

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages


def parse_page(raw: Any) -> int:
    """Entero >= 1, o 1 ante None, vacio, basura, negativos o decimales."""
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 1
    return n if n >= 1 else 1


def clamp_page(page: int, total: int, per_page: int) -> int:
    """Pagina entre 1 y la ultima (1 si no hay filas)."""
    last = max(1, math.ceil(total / per_page))
    return min(max(1, page), last)


def paginate_query(q, page: int, per_page: int = PAGE_SIZE) -> Page:
    """Pagina una `Query` ya ordenada (con desempate por `id`).

    Total: `q.order_by(None).count()`. Quita el ORDER BY (inutil al contar) y
    envuelve la consulta en un subquery, de modo que tambien cuenta bien
    consultas con joins o varias entidades y DISTINCT, sin reescribir
    `with_entities(func.count())`.
    """
    total = q.order_by(None).count()
    page = clamp_page(page, total, per_page)
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return Page(items=items, total=total, page=page, per_page=per_page)


def paginate_list(seq: Sequence, page: int, per_page: int = PAGE_SIZE) -> Page:
    """Mismo contrato que `paginate_query` sobre una lista ya ordenada."""
    total = len(seq)
    page = clamp_page(page, total, per_page)
    items = list(seq[(page - 1) * per_page: page * per_page])
    return Page(items=items, total=total, page=page, per_page=per_page)


def normalize_q(raw: Any) -> str | None:
    """`strip()`, recorte a 100 caracteres; vacio => None."""
    if raw is None:
        return None
    s = str(raw).strip()[:MAX_Q_LEN]
    return s or None


def like_pattern(q: str) -> str:
    r"""Patron `%q%` con `\`, `%` y `_` escapados con `\`.

    Usar con `col.ilike(like_pattern(q), escape="\\")`.
    """
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"
