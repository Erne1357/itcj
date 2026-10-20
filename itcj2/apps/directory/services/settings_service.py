"""Ajustes globales del Directorio (tabla singleton directory_settings)."""
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def show_unofficial(db: Session) -> bool:
    """True si el directorio debe mostrar los departamentos NO oficiales.

    Lectura PURA: nunca inserta. La fila 1 la siembra la migración, pero en CI el
    esquema se crea con create_all y la tabla nace vacía; ahí el default es False,
    que es exactamente el comportamiento previo a esta feature.
    """
    row = db.execute(
        text("SELECT show_unofficial_departments FROM directory_settings WHERE id = 1")
    ).scalar()
    return bool(row)


def set_show_unofficial(db: Session, value: bool, *, by_user_id: int | None) -> bool:
    """Persiste el ajuste. Devuelve el valor guardado.

    UPDATE y solo si no tocó nada un INSERT: un `db.add()` de fila nueva chocaría
    con el CHECK cuando la fila 1 ya existe, y dos admins simultáneos chocarían
    contra la PK. updated_by_id/updated_at se escriben a mano porque por SQL crudo
    el `onupdate` de SQLAlchemy no se dispara y la bitácora quedaría congelada.
    """
    result = db.execute(
        text(
            "UPDATE directory_settings "
            "SET show_unofficial_departments = :v, updated_by_id = :u, updated_at = now() "
            "WHERE id = 1"
        ),
        {"v": bool(value), "u": by_user_id},
    )
    if result.rowcount == 0:
        db.execute(
            text(
                "INSERT INTO directory_settings (id, show_unofficial_departments, updated_by_id) "
                "VALUES (1, :v, :u) ON CONFLICT (id) DO NOTHING"
            ),
            {"v": bool(value), "u": by_user_id},
        )
    db.commit()
    return bool(value)


def hidden_row_count(db: Session) -> int:
    """Filas que NO se verían con el ajuste apagado (puestos + entradas).

    Alimenta el contador del panel: sin él, encender el toggle con los datos
    actuales no produce ningún cambio visible y parece roto.

    El predicado es el MISMO que usa list_directory (puesto activo con extensión,
    entrada activa); si divergiera, el contador prometería filas que la lista no
    pinta.
    """
    return int(
        db.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM core_positions p
                     JOIN core_departments d ON d.id = p.department_id
                    WHERE p.is_active AND d.is_active AND NOT d.is_official
                      AND p.phone_extension IS NOT NULL)
                + (SELECT count(*) FROM directory_entries e
                     JOIN core_departments d ON d.id = e.department_id
                    WHERE e.is_active AND d.is_active AND NOT d.is_official)
                """
            )
        ).scalar()
        or 0
    )
