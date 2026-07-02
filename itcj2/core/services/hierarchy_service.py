"""Helpers de jerarquía de departamentos (árbol self-referencial parent_id).

El primitivo que faltaba en core: recorrer el subtree de un departamento
(descendientes) o su cadena de ancestros, con guard de ciclos. Se usa para el
scoping por sub-departamento (ver scope_service) y para serializar el organigrama
a profundidad arbitraria.

Postgres: CTEs recursivos (1 round-trip). `_MAX_DEPTH` acota por si el dato viene
corrupto (ciclo). `department_descendants_map` construye el mapa completo en Python
para cachearlo global (el árbol cambia rara vez).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

# Guard de ciclos: ninguna jerarquía real del ITCJ se acerca a esto.
_MAX_DEPTH = 32


def descendant_department_ids(db: Session, root_id: int, include_self: bool = True) -> set[int]:
    """IDs de `root_id` y todos sus descendientes activos (subtree)."""
    sql = text(
        """
        WITH RECURSIVE tree(id, depth) AS (
            SELECT id, 0 FROM core_departments WHERE id = :root AND is_active
            UNION ALL
            SELECT d.id, t.depth + 1
            FROM core_departments d
            JOIN tree t ON d.parent_id = t.id
            WHERE d.is_active AND t.depth < :maxd
        )
        SELECT id FROM tree
        """
    )
    ids = {r[0] for r in db.execute(sql, {"root": root_id, "maxd": _MAX_DEPTH})}
    if not include_self:
        ids.discard(root_id)
    return ids


def ancestor_department_ids(db: Session, dept_id: int, include_self: bool = False) -> set[int]:
    """IDs de la cadena de ancestros de `dept_id` (hacia la raíz)."""
    sql = text(
        """
        WITH RECURSIVE up(id, parent_id, depth) AS (
            SELECT id, parent_id, 0 FROM core_departments WHERE id = :d
            UNION ALL
            SELECT p.id, p.parent_id, u.depth + 1
            FROM core_departments p
            JOIN up u ON p.id = u.parent_id
            WHERE u.depth < :maxd
        )
        SELECT id FROM up
        """
    )
    ids = {r[0] for r in db.execute(sql, {"d": dept_id, "maxd": _MAX_DEPTH})}
    if not include_self:
        ids.discard(dept_id)
    return ids


def department_descendants_map(db: Session) -> dict[int, set[int]]:
    """Mapa {dept_id -> set(descendientes incl. self)} de TODOS los deptos activos.

    Pensado para cachear globalmente: una sola pasada, expansión en memoria.
    """
    rows = db.execute(
        text("SELECT id, parent_id FROM core_departments WHERE is_active")
    ).fetchall()

    children: dict[int, list[int]] = {}
    for _id, parent in rows:
        if parent is not None:
            children.setdefault(parent, []).append(_id)

    def walk(node: int, seen: set[int]) -> set[int]:
        acc = {node}
        for child in children.get(node, []):
            if child not in seen:
                seen.add(child)
                acc |= walk(child, seen)
        return acc

    out: dict[int, set[int]] = {}
    for _id, _ in rows:
        out[_id] = walk(_id, {_id})
    return out
