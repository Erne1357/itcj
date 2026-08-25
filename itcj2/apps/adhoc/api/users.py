"""API v2 de usuarios de Calidad — el módulo **recortado** (decisión D8).

Router **sin prefijo**: lo pone el padre en la fase de cableado
(``adhoc_router.include_router(users_router, prefix="/users")``).

Qué se porta y qué no, respecto de ``api_users.py`` del legacy:

===============================================  =============================
Legacy                                           Aquí
===============================================  =============================
``POST /usuarios/save`` — alta de personas       **No se porta**
``POST /usuarios/edit/<id>`` — cambia contraseña **No se porta**
``/api/usuarios/delete/`` (el JS pegaba a un 404) **No existía**
Listado en la página, sin API                    ``GET ""``
Asignación de rol dentro del alta                ``PUT /{id}/app-role``
Asignación de área dentro del alta               ``PUT /{id}/areas``
===============================================  =============================

El alta de personas y el cambio de contraseña se quedan fuera a propósito: el
endpoint del legacy era **anónimo**, creaba el ``User`` con ``role_id=4``
hardcodeado —que en la BD real de itcj2 es ``admin``— y filtraba el ``str(e)``
de un ``IntegrityError`` al cliente. Es una escalada de privilegios en un
formulario público. Ese trabajo es del core: ``/itcj/config``.

Las tres rutas exigen permiso; en el legacy las dos que existían eran anónimas.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Request

from itcj2.apps.adhoc.schemas.admin import AssignAppRoleIn, AssignAreasIn
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["adhoc-users"])
logger = logging.getLogger(__name__)

__all__ = ["router"]


@contextmanager
def _domain_errors():
    """``LookupError`` → 404 · ``ValueError`` → 400, con ``detail`` STRING.

    Mismo contrato que en ``api/indicators.py``: el handler global envuelve el
    ``detail`` como ``{"error": detail, "status": N}`` y el cliente asume texto.
    """
    try:
        yield
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def list_adhoc_users(
    request: Request,
    user: dict = require_perms("adhoc", ["adhoc.users.api.read"]),
    db: DbSession = None,
):
    """Usuarios con acceso a Calidad, con su rol de app y sus áreas.

    Tres consultas fijas, sin N+1. Solo se listan los accesos **directos**
    (``core_user_app_roles``): los que vienen por puesto se administran en
    ``/itcj/config``, que es el dueño del organigrama.
    """
    from itcj2.apps.adhoc.schemas.common import ok_list
    from itcj2.apps.adhoc.services.user_admin_service import UserAdminService

    with _domain_errors():
        rows = UserAdminService.list_users(db)
    return ok_list(rows)


@router.put("/{user_id}/app-role")
def set_adhoc_app_role(
    user_id: int,
    payload: AssignAppRoleIn,
    user: dict = require_perms("adhoc", ["adhoc.users.api.assign_role"]),
    db: DbSession = None,
):
    """Fija el rol del usuario **dentro de Calidad**.

    Reemplaza todas sus filas de ``core_user_app_roles`` para esta app por una
    sola. No revoca el acceso ni toca otras apps.

    El rol tiene que ser uno de los 5 que reconoce la matriz de permisos de
    ``database/DML/adhoc/init/03_insert_role_permission.sql``: asignar uno de
    fuera dejaría al usuario con acceso a la app y **cero permisos**, es decir
    403 en las 26 páginas.

    La app se resuelve por ``key='adhoc'``. El legacy escribía ``app_id = 4``
    hardcodeado, que en esta BD es *warehouse*.
    """
    from itcj2.apps.adhoc.schemas.common import ok_message
    from itcj2.apps.adhoc.services.user_admin_service import UserAdminService

    with _domain_errors():
        UserAdminService.set_app_role(db, user_id, payload.role)

    logger.info("[adhoc] %s asignó el rol '%s' al usuario %s",
                user.get("sub"), payload.role, user_id)
    return ok_message(f"Rol '{payload.role}' asignado correctamente")


@router.put("/{user_id}/areas")
def set_adhoc_user_areas(
    user_id: int,
    payload: AssignAreasIn,
    user: dict = require_perms("adhoc", ["adhoc.users.api.assign_areas"]),
    db: DbSession = None,
):
    """Reemplaza las áreas de Calidad del usuario.

    Lista vacía = quitarle todas. Se exige que el usuario ya tenga acceso a la
    app: ``adhoc_user_areas`` es dato de Calidad y colgárselo a alguien de fuera
    crearía filas que ninguna pantalla muestra.
    """
    from itcj2.apps.adhoc.schemas.common import ok_message
    from itcj2.apps.adhoc.services.user_admin_service import UserAdminService

    with _domain_errors():
        result = UserAdminService.set_areas(db, user_id, payload.area_ids)

    logger.info("[adhoc] %s asignó %d área(s) al usuario %s",
                user.get("sub"), len(result["area_ids"]), user_id)
    return ok_message(f"{len(result['area_ids'])} área(s) asignada(s) correctamente")
