"""Resolución de scope por PROCEDENCIA para autorización org-subtree.

El scope de un permiso NO es global al usuario: es la unión de los subtrees de los
DEPARTAMENTOS de los puestos que le otorgan ESE permiso. Así, alguien que es maestra
en un depto académico y secretaria en uno administrativo, y que recibe
`read.subtree` sólo por el puesto de secretaria, ve el subtree administrativo pero
NO el académico. Ver spec 2026-07-02-org-scoped-authz §2.1/§3.3.

Un grant DIRECTO al usuario (UserAppRole/UserAppPerm, sin puesto) no tiene ancla de
departamento → aporta 0 departamentos (fail-closed); para "ver todo" se usa `.all`.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, or_, func
from sqlalchemy.orm import Session

from itcj2.core.services.authz_service import get_or_404_app
from itcj2.core.services import hierarchy_service


def _active_window():
    from itcj2.core.models.position import UserPosition
    return and_(
        UserPosition.is_active == True,  # noqa: E712
        or_(UserPosition.end_date.is_(None), UserPosition.end_date >= func.current_date()),
        UserPosition.start_date <= func.current_date(),
    )


def granting_departments(db: Session, user_id: int, app_key: str, perm_code: str) -> set[int]:
    """Departamentos ANCLA (sin expandir) de los puestos vigentes del usuario que
    otorgan `perm_code` — vía perm directo del puesto o vía rol del puesto."""
    from itcj2.core.models.position import (
        UserPosition, Position, PositionAppRole, PositionAppPerm)
    from itcj2.core.models.role_permission import RolePermission
    from itcj2.core.models.permission import Permission

    app = get_or_404_app(db, app_key)

    direct = (
        db.query(Position.department_id)
        .join(UserPosition, UserPosition.position_id == Position.id)
        .join(PositionAppPerm, PositionAppPerm.position_id == Position.id)
        .join(Permission, Permission.id == PositionAppPerm.perm_id)
        .filter(
            _active_window(),
            UserPosition.user_id == user_id,
            PositionAppPerm.app_id == app.id,
            PositionAppPerm.allow == True,  # noqa: E712
            Permission.app_id == app.id,
            Permission.code == perm_code,
            Position.department_id.isnot(None),
            Position.is_active == True,  # noqa: E712
        )
    )
    via_role = (
        db.query(Position.department_id)
        .join(UserPosition, UserPosition.position_id == Position.id)
        .join(PositionAppRole, PositionAppRole.position_id == Position.id)
        .join(RolePermission, RolePermission.role_id == PositionAppRole.role_id)
        .join(Permission, Permission.id == RolePermission.perm_id)
        .filter(
            _active_window(),
            UserPosition.user_id == user_id,
            PositionAppRole.app_id == app.id,
            Permission.app_id == app.id,
            Permission.code == perm_code,
            Position.department_id.isnot(None),
            Position.is_active == True,  # noqa: E712
        )
    )
    return {r[0] for r in direct.union(via_role).all()}


def subtree_scope_for(db: Session, user_id: int, app_key: str, perm_code: str) -> set[int]:
    """Set de departamentos VISIBLES = subtree (nodo + descendientes) de cada ancla.

    Usa el mapa de descendientes cacheado (el árbol cambia rara vez) para evitar un
    CTE por ancla en el hot path.

    Las apps llaman a esta función DIRECTAMENTE (no vía ``resolve_read_scope``), así
    que aquí se comprueba que el permiso siga vigente: los grants se leen de la tabla
    de puestos, que no sabe nada de los deny explícitos (``allow=False``). Sin este
    corte, denegar el permiso apagaba el guard pero dejaba el scope intacto.
    """
    from itcj2.core.services.authz_cache import cached_perms
    if perm_code not in cached_perms(db, user_id, app_key):
        return set()

    anchors = granting_departments(db, user_id, app_key, perm_code)
    if not anchors:
        return set()
    from itcj2.core.services.authz_cache import cached_descendants_map
    dmap = cached_descendants_map(db)
    out: set[int] = set()
    for anchor in anchors:
        # El mapa solo contiene departamentos ACTIVOS; un ancla dada de baja no debe
        # reintroducirse por el default del lookup (fail-closed, §docstring del módulo).
        out |= dmap.get(anchor, set())
    return out


# ---------------------------------------------------------------------------
# Resultado de scope + resolver que consumen las apps
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ScopeResult:
    """Resultado de resolver el scope de lectura de un recurso.

    - kind="all"  → sin filtro (ve todo).
    - kind="set"  → filtrar por department_id ∈ department_ids (vacío = no ve nada).
    - kind="own"  → filtrar por propiedad (created_by/requester == user).
    - kind="none" → sin acceso (resultado vacío).
    """
    kind: str
    department_ids: frozenset | None = None


def resolve_read_scope(db: Session, user: dict, app_key: str, *, all_perm: str,
                       subtree_perm: str | None = None, dept_perm: str | None = None,
                       own_perm: str | None = None) -> ScopeResult:
    """Decide el scope de lectura de un recurso a partir de los perms efectivos.

    Precedencia: admin global / all_perm → ALL; subtree_perm → subtree por procedencia;
    dept_perm (.own_dept/.department) → depto(s) ancla exactos (SIN descendientes);
    own_perm → OWN; nada → NONE.
    """
    from itcj2.dependencies import is_global_admin
    from itcj2.core.services.authz_cache import cached_perms

    if is_global_admin(user):
        return ScopeResult("all")

    uid = int(user["sub"])
    perms = cached_perms(db, uid, app_key)

    if all_perm in perms:
        return ScopeResult("all")
    if subtree_perm and subtree_perm in perms:
        return ScopeResult("set", frozenset(subtree_scope_for(db, uid, app_key, subtree_perm)))
    if dept_perm and dept_perm in perms:
        return ScopeResult("set", frozenset(granting_departments(db, uid, app_key, dept_perm)))
    if own_perm and own_perm in perms:
        return ScopeResult("own")
    return ScopeResult("none")
