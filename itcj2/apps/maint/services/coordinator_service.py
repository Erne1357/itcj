"""
Servicio para la gestión de coordinadores de mantenimiento.

Roles reconocidos:
- maint_general_coordinator: identificado por rol en la app, puede asignar cualquier técnico.
- maint_area_coordinator: mapeo en maint_coordinator_areas, solo puede asignar técnicos
  cuyas áreas intersecten con las propias.

El admin global (user["role"] == "admin") siempre tiene acceso irrestricto; esta lógica
se evalúa en can_assign_technician a través del parámetro assigner_roles o la señal
de admin global.
"""
import logging
from sqlalchemy.orm import Session

from itcj2.apps.maint.utils.catalog_cache import get_area_codes

logger = logging.getLogger(__name__)


class CoordinatorService:
    """Lógica de negocio para coordinadores de mantenimiento."""

    @staticmethod
    def get_coordinator_areas(db: Session, user_id: int) -> list[str]:
        """
        Retorna los códigos de área asignados al coordinador de área.
        Para coordinadores generales (identificados por rol) esta lista puede
        estar vacía — el chequeo de rol se hace aparte.
        """
        from itcj2.apps.maint.models.coordinator_area import MaintCoordinatorArea

        rows = (
            db.query(MaintCoordinatorArea)
            .filter_by(user_id=user_id)
            .all()
        )
        return [r.area_code for r in rows]

    @staticmethod
    def set_coordinator_areas(
        db: Session,
        user_id: int,
        area_codes: list[str],
        performed_by_id: int,
    ) -> list[str]:
        """
        Reemplaza completamente el set de áreas del coordinador.
        Elimina las filas existentes y crea las nuevas dentro de la misma transacción.
        Retorna la lista de area_codes final.
        """
        from itcj2.apps.maint.models.coordinator_area import MaintCoordinatorArea
        from itcj2.core.models.user import User

        # Validar que el usuario existe
        user = db.get(User, user_id)
        if not user:
            raise ValueError(f"Usuario {user_id} no encontrado")

        # Validar área codes contra catálogo
        valid_areas = get_area_codes(db) or {
            "TRANSPORT", "GENERAL", "ELECTRICAL", "CARPENTRY", "AC", "GARDENING", "PAINTING",
        }
        invalid = [c for c in area_codes if c not in valid_areas]
        if invalid:
            raise ValueError(
                f"Áreas inválidas: {', '.join(invalid)}. "
                f"Válidas: {', '.join(sorted(valid_areas))}"
            )

        # Eliminar filas existentes
        db.query(MaintCoordinatorArea).filter_by(user_id=user_id).delete(
            synchronize_session=False
        )

        # Crear nuevas (sin duplicados en area_codes)
        seen: set[str] = set()
        for code in area_codes:
            if code in seen:
                continue
            seen.add(code)
            db.add(
                MaintCoordinatorArea(
                    user_id=user_id,
                    area_code=code,
                    created_by_id=performed_by_id,
                )
            )

        db.commit()
        logger.info(
            "Coordinador %s: áreas actualizadas a %s por %s",
            user_id,
            area_codes,
            performed_by_id,
        )
        return list(seen)

    @staticmethod
    def is_general_coordinator(db: Session, user_id: int) -> bool:
        """
        True si el usuario tiene el rol maint_general_coordinator en la app maint.
        """
        from itcj2.core.services.authz_service import user_roles_in_app

        roles = user_roles_in_app(db, user_id, "maint")
        return "maint_general_coordinator" in roles

    @staticmethod
    def is_area_coordinator(db: Session, user_id: int) -> bool:
        """
        True si el usuario tiene el rol maint_area_coordinator en la app maint.
        """
        from itcj2.core.services.authz_service import user_roles_in_app

        roles = user_roles_in_app(db, user_id, "maint")
        return "maint_area_coordinator" in roles

    @staticmethod
    def is_coordinator(db: Session, user_id: int) -> bool:
        """
        True si el usuario es coordinador general O de área.
        """
        from itcj2.core.services.authz_service import user_roles_in_app

        roles = set(user_roles_in_app(db, user_id, "maint"))
        return bool(roles & {"maint_general_coordinator", "maint_area_coordinator"})

    @staticmethod
    def list_general_coordinators(db: Session) -> list[dict]:
        """
        Retorna los coordinadores generales (rol maint_general_coordinator).
        """
        from itcj2.core.services.authz_service import _get_users_with_roles_in_app
        from itcj2.core.models.user import User

        general_ids = _get_users_with_roles_in_app(db, "maint", ["maint_general_coordinator"])
        result = []
        for uid in general_ids:
            user = db.get(User, uid)
            if not user:
                continue
            result.append({"user_id": uid, "name": user.full_name})
        return result

    @staticmethod
    def list_area_coordinators(db: Session) -> list[dict]:
        """
        Retorna los coordinadores de área (los que NO son generales pero tienen áreas asignadas).
        """
        from itcj2.core.services.authz_service import _get_users_with_roles_in_app
        from itcj2.core.models.user import User
        from itcj2.apps.maint.models.coordinator_area import MaintCoordinatorArea

        general_ids = set(_get_users_with_roles_in_app(db, "maint", ["maint_general_coordinator"]))

        result: dict[int, dict] = {}
        area_rows = db.query(MaintCoordinatorArea).order_by(MaintCoordinatorArea.user_id).all()
        for row in area_rows:
            uid = row.user_id
            if uid in general_ids:
                continue
            if uid not in result:
                user = db.get(User, uid)
                if not user:
                    continue
                result[uid] = {"user_id": uid, "name": user.full_name, "areas": []}
            result[uid]["areas"].append(row.area_code)

        return list(result.values())

    @staticmethod
    def list_coordinators(db: Session) -> list[dict]:
        """
        Retorna todos los coordinadores conocidos:
        - Coordinadores generales (rol maint_general_coordinator)
        - Coordinadores de área (filas en maint_coordinator_areas)
        La unión es disjunta en la mayoría de casos, pero se maneja sin duplicados.
        """
        from itcj2.core.services.authz_service import _get_users_with_roles_in_app
        from itcj2.core.models.user import User
        from itcj2.apps.maint.models.coordinator_area import MaintCoordinatorArea

        result: dict[int, dict] = {}

        # 1. Coordinadores generales por rol
        general_ids = _get_users_with_roles_in_app(
            db, "maint", ["maint_general_coordinator"]
        )
        for uid in general_ids:
            user = db.get(User, uid)
            if not user:
                continue
            result[uid] = {
                "user_id": uid,
                "name": user.full_name,
                "areas": [],
                "is_general": True,
            }

        # 2. Coordinadores de área con sus áreas
        area_rows = db.query(MaintCoordinatorArea).order_by(MaintCoordinatorArea.user_id).all()
        for row in area_rows:
            uid = row.user_id
            if uid not in result:
                user = db.get(User, uid)
                if not user:
                    continue
                result[uid] = {
                    "user_id": uid,
                    "name": user.full_name,
                    "areas": [],
                    "is_general": False,
                }
            result[uid]["areas"].append(row.area_code)

        return list(result.values())

    @staticmethod
    def can_assign_technician(
        db: Session,
        assigner_id: int,
        assigner_roles: set | list,
        technician_id: int,
        is_global_admin: bool = False,
    ) -> bool:
        """
        Determina si assigner puede asignar a technician_id según la regla de área.

        Reglas (por prioridad):
        1. Admin global (is_global_admin=True o "admin" en assigner_roles) → True
        2. Rol maint_general_coordinator en app maint → True
        3. Rol maint_area_coordinator → True solo si intersección de áreas no vacía
        4. Cualquier otro rol → False

        Parámetros:
            assigner_roles: conjunto de roles del asignador en la app maint (strings).
            is_global_admin: True si user["role"] == "admin" (del JWT).
        """
        roles = set(assigner_roles)

        # 1. Admin global
        if is_global_admin or "admin" in roles:
            return True

        # 2. Coordinador general
        if "maint_general_coordinator" in roles:
            return True

        # 3. Coordinador de área
        if "maint_area_coordinator" in roles:
            coordinator_areas = set(
                CoordinatorService.get_coordinator_areas(db, assigner_id)
            )
            if not coordinator_areas:
                # Sin áreas configuradas → no puede asignar a nadie
                logger.warning(
                    "Coordinador de área %s no tiene áreas configuradas; "
                    "asignación rechazada para técnico %s",
                    assigner_id,
                    technician_id,
                )
                return False

            # Áreas del técnico destino
            from itcj2.apps.maint.models.technician_area import MaintTechnicianArea

            tech_area_rows = (
                db.query(MaintTechnicianArea)
                .filter_by(user_id=technician_id)
                .all()
            )
            tech_areas = {r.area_code for r in tech_area_rows}

            if coordinator_areas & tech_areas:
                return True

            logger.info(
                "Coordinador de área %s (áreas: %s) intentó asignar a técnico %s "
                "(áreas: %s) — sin intersección",
                assigner_id,
                sorted(coordinator_areas),
                technician_id,
                sorted(tech_areas),
            )
            return False

        # 4. Ningún rol de coordinación
        return False
