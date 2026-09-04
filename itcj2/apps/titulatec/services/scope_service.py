"""Alcance por carrera de un usuario administrativo de TitulaTec.

Dos capas, con responsabilidades separadas:

- `officer_programs(db, user_id)` -> `"ALL"` o `set[int]`: alimenta el **filtro SQL**
  de los listados (`allowed_program_ids`).
- `process_in_scope` / `assert_process_in_scope` -> el **predicado por proceso** que
  usan las 13 rutas con `{process_id}`.

Es el MISMO criterio en los dos casos a proposito (invariante: lista == detalle ==
escritura). Si un proceso no sale en el listado del usuario, sus rutas de detalle y de
mutacion tienen que rechazarlo.

Diseno completo: `docs/superpowers/specs/2026-09-01-titulatec-scope-carrera-design.md`.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

READ_ALL = "titulatec.process.api.read.all"
# Llave del cubo "Sin carrera": es una cola de REPARACION de datos, y este es el
# permiso que da la capacidad de repararla. `read.all` no sirve de discriminante
# porque lo tienen dos roles (jefe y titulaciones) y la decision dice solo el jefe.
MANAGE_OFFICERS = "titulatec.officers.api.manage"
_APP_KEY = "titulatec"


def _user_perms(db: Session, user_id: int) -> set[str]:
    """UNA sola fuente de verdad de permisos: la misma que usa el gate.

    `cached_perms` envuelve `get_user_permissions_for_app` pero pasa por Redis, y de
    ahi lee `require_page_app` (`itcj2/dependencies.py:132`). Preguntarle a la BD por
    separado hacia que gate y alcance discreparan dentro del MISMO request mientras
    viviera el TTL: un `read.all` recien revocado dejaba pasar el gate (HIT stale)
    mientras el alcance ya lo habia degradado a set, y al reves.
    """
    from itcj2.core.services.authz_cache import cached_perms
    return cached_perms(db, user_id, _APP_KEY)


def _program_ids_for_user(db: Session, user_id: int) -> set[int]:
    """Carreras de los puestos VIGENTES del usuario que otorgan acceso a ESTA app.

    El ancla del alcance es el PUESTO. Un rol o permiso concedido DIRECTAMENTE al
    usuario (`core_user_app_roles` / `core_user_app_perms`) no tiene puesto y por
    tanto no tiene `ProgramPosition`: queda sin ancla -> fail-closed.

    Tres cosas que la query anterior no hacia (y su docstring afirmaba):

    - **Filtrar por app.** El join era `ProgramPosition ⋈ UserPosition` a secas.
      `core_program_positions` es tabla CORE, compartida por el organigrama: *cualquier*
      puesto del usuario con carreras ahi ampliaba su alcance en TitulaTec.
    - **Filtrar por vigencia.** Usaba `UserPosition.is_active` en vez de
      `_active_position_filter()`, la clausula canonica que ademas exige
      `start_date <= hoy` y (`end_date` NULL o >= hoy). Un puesto vencido seguia
      aportando carreras aunque el gate ya no lo dejara entrar.
    - **Mirar `Position.is_active`.** Un puesto desactivado seguia aportando.

    Se aceptan las dos vias que tienen puesto (`PositionAppRole` y `PositionAppPerm`
    con `allow`) porque son las dos que acepta `has_any_assignment`, el criterio del
    gate: el alcance debe ser el GEMELO del gate, no un subconjunto arbitrario. Si el
    gate deja entrar por una via que el alcance ignora, el usuario entra a la app y ve
    todo vacio sin explicacion.
    """
    from itcj2.core.models.position import (
        Position, PositionAppPerm, PositionAppRole, ProgramPosition, UserPosition,
    )
    from itcj2.core.services.authz_service import _active_position_filter, get_or_404_app

    app = get_or_404_app(db, _APP_KEY)

    base = (
        db.query(ProgramPosition.program_id)
        .join(Position, Position.id == ProgramPosition.position_id)
        .join(UserPosition, UserPosition.position_id == ProgramPosition.position_id)
        .filter(
            UserPosition.user_id == user_id,
            _active_position_filter(),
            Position.is_active.is_(True),
        )
    )
    via_role = (
        base.join(PositionAppRole,
                  PositionAppRole.position_id == ProgramPosition.position_id)
        .filter(PositionAppRole.app_id == app.id)
    )
    via_perm = (
        base.join(PositionAppPerm,
                  PositionAppPerm.position_id == ProgramPosition.position_id)
        .filter(PositionAppPerm.app_id == app.id, PositionAppPerm.allow.is_(True))
    )
    rows = via_role.distinct().all() + via_perm.distinct().all()
    return {r[0] for r in rows}


def officer_programs(db: Session, user_id: int):
    """Devuelve 'ALL' o un set[int] de program_id que el usuario puede ver.

    Set vacio = no ve nada hasta que el jefe le asigne carreras (fail-closed).
    """
    if READ_ALL in _user_perms(db, user_id):
        return "ALL"
    return _program_ids_for_user(db, user_id)


def can_see_unmapped(db: Session, user_id: int) -> bool:
    """¿Puede ver los procesos SIN carrera (`program_id IS NULL`)?

    Son procesos que el CSV no supo mapear (`import_service`) o que se dieron de alta
    sin carrera: nadie los tiene en su alcance, asi que serian invisibles para siempre.
    El cubo "Sin carrera" es la cola de reparacion, y la abre quien puede repararla.
    """
    return MANAGE_OFFICERS in _user_perms(db, user_id)


def process_in_scope(db: Session, user_id: int, process_id: int):
    """Devuelve el `TitulationProcess` si el usuario puede verlo/tocarlo; None si no.

    Predicado PURO: no lanza, no habla HTTP, no depende de `Request`. Es el unico
    lugar donde se decide "este proceso cae en mi alcance".

    `program_id IS NULL` se resuelve ANTES de mirar el set: en SQL `IN` con NULL da
    UNKNOWN y la fila cae sola, pero en Python `None in {None}` seria True. La regla
    va explicita para no depender de esa asimetria.
    """
    from itcj2.apps.titulatec.models import TitulationProcess

    proc = db.get(TitulationProcess, process_id)
    if proc is None:
        return None
    if proc.program_id is None:
        return proc if can_see_unmapped(db, user_id) else None
    scope = officer_programs(db, user_id)
    if scope == "ALL":
        return proc
    return proc if proc.program_id in scope else None


def assert_process_in_scope(db: Session, user_id: int, process_id: int):
    """Igual, pero para rutas: 404 uniforme cuando el proceso no es alcanzable.

    404 y no 403 porque `titulatec_processes.id` es un entero secuencial: un 403
    confirmaria que el id existe y convertiria cualquier ruta en un contador del
    padron. Por lo mismo el 404 va SIN detalle distintivo y SIN header `X-Tt-Error`:
    ese header seria el oraculo que el 404 acaba de cerrar. En la UI queda el toast
    generico de `admin/base_admin.html`, que es el comportamiento correcto.

    Devuelve el proceso ya cargado para que la ruta NO repita el `db.get`: que el
    guard sea el camino mas corto al objeto es parte del control — olvidarlo cuesta
    mas codigo, no menos.
    """
    from fastapi import HTTPException

    proc = process_in_scope(db, user_id, process_id)
    if proc is None:
        raise HTTPException(status_code=404)
    return proc
