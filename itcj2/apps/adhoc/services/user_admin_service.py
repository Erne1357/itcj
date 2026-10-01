"""Administración de la app Calidad: usuarios y configuración de correo.

Dos fachadas viven aquí, las dos pequeñas y las dos del panel de control:

* :class:`UserAdminService` — el módulo de usuarios **recortado** (decisión D8
  del plan): listar quién tiene acceso a Calidad y fijarle rol de app y áreas.
* :class:`MailConfigService` — el interruptor global de correo (singleton
  ``adhoc_mail_config`` con ``CheckConstraint(id = 1)``).

Lo que este módulo **no** hace, a propósito: dar de alta personas y cambiar
contraseñas. El legacy lo hacía desde esta misma pantalla, sin autenticación,
con ``role_id=4`` hardcodeado — que en la BD real de itcj2 es ``admin``: una
escalada de privilegios en un formulario público. El provisioning de personas
es del core (``/itcj/config``).

**La app se resuelve siempre por ``key='adhoc'``.** El legacy escribía
``app_id = 4`` a mano (``api_users.py:22``, ``api_reports.py:29``,
``pages/general.py:31``) y en itcj2 el id 4 es *warehouse*: cada una de esas
tres líneas habría dado acceso a la app equivocada.

Contrato de errores (idéntico al de ``indicator_service``, lo traduce la API):

* :class:`LookupError` — la entidad no existe → **404**.
* :class:`ValueError`  — el dato es inválido o incoherente → **400**.
"""
from __future__ import annotations

import logging
from typing import Sequence

from sqlalchemy.orm import Session

from itcj2.apps.adhoc.schemas.admin import ADHOC_APP_ROLES
from itcj2.apps.adhoc.utils.constants import APP_KEY

logger = logging.getLogger(__name__)

#: Id del singleton de ``adhoc_mail_config``. Es 1 por CheckConstraint.
MAIL_CONFIG_ID = 1


class UserAdminService:
    """Usuarios de Calidad: quién está dentro, con qué rol y en qué áreas."""

    # ======================================================================
    # App
    # ======================================================================

    @staticmethod
    def get_app(db: Session):
        """La fila de ``core_apps`` de Calidad, resuelta por ``key``.

        Raises:
            LookupError: la app no está registrada (falta correr
                ``database/DML/adhoc/init/00_insert_app.sql``).
        """
        from itcj2.core.models.app import App

        app = db.query(App).filter(App.key == APP_KEY).one_or_none()
        if app is None:
            raise LookupError(
                f"La aplicación '{APP_KEY}' no está registrada en core_apps; "
                f"ejecuta database/DML/adhoc/init/00_insert_app.sql"
            )
        return app

    # ======================================================================
    # Listado
    # ======================================================================

    @staticmethod
    def list_users(db: Session) -> list[dict]:
        """Usuarios con acceso **directo** a Calidad, con rol(es) y áreas.

        Tres consultas fijas (usuarios, roles, áreas) en vez del N+1 del legacy,
        que tocaba ``usuario.areas_asignadas`` dentro del ``{% for %}``.

        "Acceso directo" = una fila en ``core_user_app_roles``. Los accesos que
        vienen por **puesto** (``core_position_app_roles``) no se listan aquí:
        esta pantalla escribe en ``core_user_app_roles`` y no puede modificar un
        puesto, así que mostrarlos daría filas que el botón de guardar no sabría
        editar. El organigrama se administra en ``/itcj/config``.
        """
        from itcj2.apps.adhoc.models import AdhocArea, adhoc_user_areas
        from itcj2.core.models.role import Role
        from itcj2.core.models.user import User
        from itcj2.core.models.user_app_role import UserAppRole

        app = UserAdminService.get_app(db)

        users = (
            db.query(User)
            .join(UserAppRole, UserAppRole.user_id == User.id)
            .filter(UserAppRole.app_id == app.id)
            .distinct()
            .order_by(User.last_name.asc(), User.first_name.asc(), User.id.asc())
            .all()
        )
        if not users:
            return []

        user_ids = [u.id for u in users]

        roles_by_user: dict[int, list[str]] = {}
        for user_id, role_name in (
            db.query(UserAppRole.user_id, Role.name)
            .join(Role, Role.id == UserAppRole.role_id)
            .filter(UserAppRole.app_id == app.id, UserAppRole.user_id.in_(user_ids))
            .all()
        ):
            roles_by_user.setdefault(user_id, []).append(role_name)

        areas_by_user: dict[int, list[dict]] = {}
        for user_id, area in (
            db.query(adhoc_user_areas.c.user_id, AdhocArea)
            .join(AdhocArea, AdhocArea.id == adhoc_user_areas.c.area_id)
            .filter(adhoc_user_areas.c.user_id.in_(user_ids))
            .order_by(AdhocArea.name.asc())
            .all()
        ):
            areas_by_user.setdefault(user_id, []).append({
                "id": area.id,
                "name": area.name,
                "color": area.color,
                "is_active": area.is_active,
            })

        return [
            {
                "id": user.id,
                "username": user.username,
                "control_number": user.control_number,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "middle_name": user.middle_name,
                "full_name": user.full_name,
                "is_active": bool(user.is_active),
                "roles": sorted(roles_by_user.get(user.id, [])),
                "areas": areas_by_user.get(user.id, []),
            }
            for user in users
        ]

    # ======================================================================
    # Rol de app
    # ======================================================================

    @staticmethod
    def set_app_role(db: Session, user_id: int, role_name: str) -> dict:
        """Deja al usuario con **un solo** rol dentro de Calidad.

        Borra todas las filas ``(user, adhoc, *)`` y escribe la nueva. No toca
        las de otras apps y **no revoca el acceso**: quitar a alguien de Calidad
        se hace desde ``/itcj/config``, que es el dueño del provisioning.

        Raises:
            LookupError: el usuario no existe, o el rol no está en
                ``core_roles`` (falta el DML de la app).
            ValueError: el rol no pertenece al vocabulario de Calidad — asignar
                uno de fuera dejaría al usuario con acceso y cero permisos.
        """
        from itcj2.core.models.role import Role
        from itcj2.core.models.user import User
        from itcj2.core.models.user_app_role import UserAppRole

        if role_name not in ADHOC_APP_ROLES:
            raise ValueError(
                f"Rol inválido para Calidad: {role_name!r}. "
                f"Válidos: {', '.join(ADHOC_APP_ROLES)}"
            )

        user = db.get(User, user_id)
        if user is None:
            raise LookupError(f"El usuario {user_id} no existe")

        role = db.query(Role).filter(Role.name == role_name).one_or_none()
        if role is None:
            raise LookupError(
                f"El rol '{role_name}' no existe en core_roles; "
                f"ejecuta database/DML/adhoc/init/01_insert_roles.sql"
            )

        app = UserAdminService.get_app(db)

        (db.query(UserAppRole)
           .filter(UserAppRole.user_id == user_id, UserAppRole.app_id == app.id)
           .delete(synchronize_session=False))
        db.add(UserAppRole(user_id=user_id, app_id=app.id, role_id=role.id))
        db.commit()

        UserAdminService._invalidate_authz(user_id)
        logger.info("[adhoc] Usuario %s → rol '%s' en Calidad", user_id, role_name)
        return {"user_id": user_id, "role": role_name}

    # ======================================================================
    # Áreas
    # ======================================================================

    @staticmethod
    def set_areas(db: Session, user_id: int, area_ids: Sequence[int]) -> dict:
        """Reemplaza las áreas de Calidad del usuario.

        Lista vacía = quitarle todas (operación legítima). Se exige que el
        usuario tenga acceso a la app: ``adhoc_user_areas`` es dato de Calidad y
        colgárselo a alguien de fuera crea filas que ninguna pantalla muestra.

        Raises:
            LookupError: el usuario no existe.
            ValueError: alguna área no existe, o el usuario no tiene acceso a
                Calidad.
        """
        from itcj2.apps.adhoc.models import AdhocArea, adhoc_user_areas
        from itcj2.core.models.user import User
        from itcj2.core.models.user_app_role import UserAppRole

        user = db.get(User, user_id)
        if user is None:
            raise LookupError(f"El usuario {user_id} no existe")

        app = UserAdminService.get_app(db)
        has_access = (
            db.query(UserAppRole)
            .filter(UserAppRole.user_id == user_id, UserAppRole.app_id == app.id)
            .first()
            is not None
        )
        if not has_access:
            raise ValueError(
                "El usuario no tiene acceso a Calidad; asígnale primero un rol de la app"
            )

        wanted = list(dict.fromkeys(int(a) for a in (area_ids or [])))
        if wanted:
            found = {
                a_id for (a_id,) in db.query(AdhocArea.id)
                .filter(AdhocArea.id.in_(wanted)).all()
            }
            missing = [a for a in wanted if a not in found]
            if missing:
                raise ValueError(
                    f"Área(s) inexistente(s): {', '.join(str(m) for m in missing)}"
                )

        db.execute(adhoc_user_areas.delete().where(adhoc_user_areas.c.user_id == user_id))
        if wanted:
            db.execute(
                adhoc_user_areas.insert(),
                [{"user_id": user_id, "area_id": a} for a in wanted],
            )
        db.commit()

        logger.info("[adhoc] Usuario %s → %d área(s) de Calidad", user_id, len(wanted))
        return {"user_id": user_id, "area_ids": wanted}

    # ======================================================================
    # Interno
    # ======================================================================

    @staticmethod
    def _invalidate_authz(user_id: int) -> None:
        """Tira el caché de authz del usuario tras cambiarle el rol.

        Sin esto el usuario arrastra sus permisos viejos hasta que expire la
        entrada de Redis. Best-effort: si el caché no está disponible el cambio
        ya está en la BD y no se pierde nada — no se propaga el fallo.
        """
        try:
            from itcj2.core.services.authz_cache import invalidate_user
            invalidate_user(user_id)
        except Exception:   # noqa: BLE001 — fail-soft deliberado
            logger.debug("[adhoc] No se pudo invalidar el caché de authz de %s", user_id)


class MailConfigService:
    """El interruptor global de correo del SGC (``adhoc_mail_config``)."""

    @staticmethod
    def get(db: Session):
        """La fila singleton, o ``None`` si el DML no se ha corrido.

        **Nunca escribe.** El legacy hacía ``db.add()`` + ``commit()`` dentro de
        ``GET /api/mail/config``, violando la idempotencia del método seguro; el
        endpoint de lectura solo lee, y quien decide qué hacer con el ``None``
        es la capa API.
        """
        from itcj2.apps.adhoc.models import AdhocMailConfig

        return db.get(AdhocMailConfig, MAIL_CONFIG_ID)

    @staticmethod
    def set_enabled(db: Session, is_enabled: bool):
        """Prende o apaga el correo de Calidad.

        Sí puede crear la fila si falta: ``PUT`` no es un método seguro y la
        alternativa (dejar la app sin panel de correo hasta que alguien corra el
        DML) es peor. El ``id`` es fijo por ``CheckConstraint(id = 1)``.
        """
        from itcj2.apps.adhoc.models import AdhocMailConfig

        cfg = db.get(AdhocMailConfig, MAIL_CONFIG_ID)
        if cfg is None:
            cfg = AdhocMailConfig(id=MAIL_CONFIG_ID, is_enabled=bool(is_enabled))
            db.add(cfg)
        else:
            cfg.is_enabled = bool(is_enabled)

        db.commit()
        db.refresh(cfg)
        logger.info("[adhoc] Correo de Calidad %s", "habilitado" if cfg.is_enabled else "deshabilitado")
        return cfg
