"""
Base declarativa de SQLAlchemy para itcj2 (sin Flask-SQLAlchemy).

Todos los modelos de itcj2/ heredan de ``Base`` en lugar de ``db.Model``.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base para todos los modelos SQLAlchemy de itcj2."""
    pass


class Pagination:
    """Objeto de paginación compatible con Flask-SQLAlchemy para templates Jinja2."""

    def __init__(self, items, total, page, per_page, pages):
        self.items = items
        self.total = total
        self.page = page
        self.per_page = per_page
        self.pages = pages
        self.has_next = page < pages
        self.has_prev = page > 1
        self.next_num = page + 1 if page < pages else None
        self.prev_num = page - 1 if page > 1 else None

    def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
        """Genera números de página para la navegación (compatible con Flask-SQLAlchemy).

        Yields ``None`` para los saltos (mostrados como "...").
        """
        last = 0
        for num in range(1, self.pages + 1):
            if (
                num <= left_edge
                or (self.page - left_current - 1 < num < self.page + right_current)
                or num > self.pages - right_edge
            ):
                if last + 1 != num:
                    yield None
                yield num
                last = num


def paginate(query, page: int, per_page: int, error_out: bool = False) -> Pagination:
    """Reemplaza Flask-SQLAlchemy ``query.paginate()``.

    Retorna un objeto compatible con la interfaz de paginación de Flask-SQLAlchemy::

        result = paginate(db.query(Ticket).filter(...), page=1, per_page=20)
        result.items    # list[Ticket]
        result.total    # int
        result.pages    # int
        result.has_next # bool
        result.iter_pages(...)  # generator de números de página
    """
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    pages = max(1, (total + per_page - 1) // per_page)
    return Pagination(items=items, total=total, page=page, per_page=per_page, pages=pages)
