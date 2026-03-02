"""
Base declarativa de SQLAlchemy para itcj2 (sin Flask-SQLAlchemy).

Todos los modelos de itcj2/ heredan de ``Base`` en lugar de ``db.Model``.
"""
from types import SimpleNamespace

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base para todos los modelos SQLAlchemy de itcj2."""
    pass


def paginate(query, page: int, per_page: int, error_out: bool = False):
    """Reemplaza Flask-SQLAlchemy ``query.paginate()``.

    Retorna un objeto compatible con la interfaz de paginación de Flask-SQLAlchemy::

        result = paginate(db.query(Ticket).filter(...), page=1, per_page=20)
        result.items    # list[Ticket]
        result.total    # int
        result.pages    # int
        result.has_next # bool
    """
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    pages = max(1, (total + per_page - 1) // per_page)
    return SimpleNamespace(
        items=items,
        total=total,
        pages=pages,
        page=page,
        has_next=page < pages,
        has_prev=page > 1,
        next_num=page + 1 if page < pages else None,
        prev_num=page - 1 if page > 1 else None,
    )
