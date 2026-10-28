"""Ajustes del Directorio (tabla singleton directory_settings)."""
import json
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def visible_unofficial(db: Session) -> set[int]:
    """Ids de los departamentos NO oficiales que el directorio muestra.

    Lectura PURA: nunca inserta. La fila 1 la siembra la migración, pero en CI el
    esquema se crea con create_all y la tabla nace vacía; ahí no se muestra ninguno,
    que es el comportamiento previo a esta feature.
    """
    row = db.execute(
        text("SELECT visible_unofficial_department_ids FROM directory_settings WHERE id = 1")
    ).scalar()
    return {int(i) for i in (row or [])}


def set_unofficial_visible(db: Session, department_id: int, visible: bool, *,
                           by_user_id: int | None) -> set[int]:
    """Muestra u oculta UN departamento no oficial. Devuelve el conjunto guardado.

    Estado deseado explícito (idempotente). La fila 1 se bloquea antes de leer la
    lista: dos admins marcando departamentos distintos a la vez no se pisan.
    updated_by_id/updated_at van a mano porque por SQL crudo el `onupdate` de
    SQLAlchemy no se dispara.
    """
    ok = db.execute(
        text("SELECT 1 FROM core_departments "
             "WHERE id = :d AND is_active AND NOT is_official"),
        {"d": department_id},
    ).scalar()
    if not ok:
        raise ValueError("El departamento no existe, está inactivo o es oficial")

    db.execute(text("INSERT INTO directory_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING"))
    current = db.execute(text(
        "SELECT visible_unofficial_department_ids FROM directory_settings WHERE id = 1 FOR UPDATE"
    )).scalar()
    ids = {int(i) for i in (current or [])}
    if visible:
        ids.add(department_id)
    else:
        ids.discard(department_id)
    db.execute(
        text(
            "UPDATE directory_settings "
            "SET visible_unofficial_department_ids = CAST(:v AS json), "
            "    updated_by_id = :u, updated_at = now() "
            "WHERE id = 1"
        ),
        {"v": json.dumps(sorted(ids)), "u": by_user_id},
    )
    db.commit()
    return ids


def unofficial_departments(db: Session) -> list[dict]:
    """Departamentos no oficiales activos para el panel, con su conteo de extensiones.

    Sin el conteo, mostrar un departamento sin extensiones no cambia nada visible
    y parece roto. El predicado es el MISMO que usa list_directory (puesto activo
    con extensión, entrada activa); si divergiera, el número prometería filas que
    la lista no pinta.
    """
    rows = db.execute(
        text(
            """
            SELECT d.id, d.name, p.name AS parent,
                   (SELECT count(*) FROM core_positions ps
                     WHERE ps.department_id = d.id AND ps.is_active
                       AND ps.phone_extension IS NOT NULL)
                 + (SELECT count(*) FROM directory_entries e
                     WHERE e.department_id = d.id AND e.is_active) AS extensions
              FROM core_departments d
              LEFT JOIN core_departments p ON p.id = d.parent_id
             WHERE d.is_active AND NOT d.is_official
             ORDER BY d.name
            """
        )
    ).mappings().all()
    return [dict(r) for r in rows]
