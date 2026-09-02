"""Asignación delegada de rol con scope por carrera (genérico).

Un manager da de alta a un subordinado = usuario + rol + carreras, dentro de su
departamento. Reutiliza core/services/positions_service. "Encargado" = un Position
del depto (etiqueta UI), con rol asignado (PositionAppRole) y carreras (ProgramPosition).
Reusable en Etapa 2 (vinculación, sinodales) cambiando assigned_role/department.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from itcj2.core.services import positions_service


class OfficerService:
    @staticmethod
    def department_user_ids(db: Session, department_id: int) -> set[int]:
        """user_id con UserPosition activa en un Position del departamento."""
        from itcj2.core.models.position import Position, UserPosition
        rows = (
            db.query(UserPosition.user_id)
            .join(Position, Position.id == UserPosition.position_id)
            .filter(Position.department_id == department_id, UserPosition.is_active.is_(True))
            .distinct().all()
        )
        return {r[0] for r in rows}

    @staticmethod
    def list_officers(db: Session, department_id: int, *, code_prefix: str = "se_officer_") -> list[dict]:
        """Encargados (Positions del depto creados por esta app) con usuarios y carreras."""
        from itcj2.core.models.position import Position, UserPosition, ProgramPosition
        from itcj2.core.models.user import User
        from itcj2.core.models.program import Program
        out = []
        positions = (
            db.query(Position)
            .filter(Position.department_id == department_id,
                    Position.code.like(f"{code_prefix}%"), Position.is_active.is_(True))
            .all()
        )
        for pos in positions:
            users = (
                db.query(User).join(UserPosition, UserPosition.user_id == User.id)
                .filter(UserPosition.position_id == pos.id, UserPosition.is_active.is_(True)).all()
            )
            progs = (
                db.query(Program).join(ProgramPosition, ProgramPosition.program_id == Program.id)
                .filter(ProgramPosition.position_id == pos.id).all()
            )
            out.append({
                "id": pos.id, "name": pos.title,
                "users": [{"id": u.id, "name": u.full_name} for u in users],
                "programs": [{"id": p.id, "name": p.name} for p in progs],
            })
        return out

    @staticmethod
    def get_manageable_position(db: Session, position_id: int, department_id: int | None,
                                *, app_key: str = "titulatec"):
        """Conjunto A (administrable): puesto del depto, activo y con rol en la app.

        Devuelve el `Position` o None; nunca lanza. `core_positions` es el
        organigrama COMPARTIDO: sin este filtro un `position_id` cualquiera del
        path acaba en `set_users`, y ocupar un puesto arrastra sus
        `PositionAppRole` en todas las apps. Sin departamento gestionado no hay
        nada administrable (fail-closed).
        """
        if department_id is None:
            return None
        from itcj2.core.models.app import App
        from itcj2.core.models.position import Position, PositionAppRole
        return (
            db.query(Position)
            .join(PositionAppRole, PositionAppRole.position_id == Position.id)
            .join(App, App.id == PositionAppRole.app_id)
            .filter(Position.id == position_id,
                    Position.department_id == department_id,
                    Position.is_active.is_(True),
                    App.key == app_key)
            .first()
        )

    @staticmethod
    def get_deletable_position(db: Session, position_id: int, department_id: int | None,
                               *, code_prefix: str = "se_officer_", app_key: str = "titulatec"):
        """Conjunto B (destruible) = A ∩ (code LIKE prefix%). None si no procede.

        Más estrecho que A a propósito: `deactivate_position` apaga el puesto y
        cierra todas sus `UserPosition`. El prefijo que pone `create_officer` es
        la marca de propiedad — esta app solo destruye lo que ella creó.
        """
        pos = OfficerService.get_manageable_position(
            db, position_id, department_id, app_key=app_key)
        if pos is None or not (pos.code or "").startswith(code_prefix):
            return None
        return pos

    @staticmethod
    def set_programs(db: Session, position_id: int, program_ids: set[int]) -> None:
        """Sincroniza ProgramPosition del puesto = program_ids."""
        from itcj2.core.models.position import ProgramPosition
        current = {pp.program_id for pp in
                   db.query(ProgramPosition).filter_by(position_id=position_id).all()}
        for pid in current - set(program_ids):
            db.query(ProgramPosition).filter_by(position_id=position_id, program_id=pid).delete()
        for pid in set(program_ids) - current:
            db.add(ProgramPosition(position_id=position_id, program_id=pid))
        db.commit()

    @staticmethod
    def set_users(db: Session, position_id: int, user_ids: set[int], *, department_id: int,
                  assigned_role: str) -> None:
        """Sincroniza los usuarios del puesto (solo usuarios del depto).

        El `| set(user_ids)` que había aquí metía a los propios candidatos en el
        conjunto permitido: `bad` era vacío por álgebra de conjuntos y el control
        no existía. Las bajas no dependen de esto — salen de
        `current - user_ids`, más abajo — así que a alguien que ya salió del
        departamento se le puede seguir quitando el puesto.
        """
        if department_id is None:
            raise ValueError("Sin departamento gestionado")
        allowed = OfficerService.department_user_ids(db, department_id)
        bad = set(user_ids) - allowed
        if bad:
            raise ValueError(f"Usuarios fuera del departamento: {sorted(bad)}")
        from itcj2.core.models.position import UserPosition
        current = {up.user_id for up in
                   db.query(UserPosition).filter_by(position_id=position_id, is_active=True).all()}
        for uid in current - set(user_ids):
            positions_service.remove_user_from_position(db, uid, position_id)
        for uid in set(user_ids) - current:
            positions_service.assign_user_to_position(db, uid, position_id)

    @staticmethod
    def create_officer(db: Session, *, department_id: int, assigned_role: str,
                       name: str, program_ids: set[int], user_ids: set[int]) -> int:
        """Crea un 'Encargado' = Position + rol + usuarios + carreras. Devuelve position_id."""
        if department_id is None:
            raise ValueError("Sin departamento gestionado")
        allowed = OfficerService.department_user_ids(db, department_id)
        bad = set(user_ids) - allowed
        if bad:
            raise ValueError(f"Usuarios fuera del departamento: {bad}")
        code = f"se_officer_{uuid.uuid4().hex[:8]}"
        pos = positions_service.create_position(
            db, code=code, title=name, department_id=department_id, allows_multiple=True)
        positions_service.assign_role_to_position(db, pos.id, "titulatec", assigned_role)
        for uid in user_ids:
            positions_service.assign_user_to_position(db, uid, pos.id)
        OfficerService.set_programs(db, pos.id, program_ids)
        return pos.id

    @staticmethod
    def deactivate_officer(db: Session, position_id: int) -> None:
        positions_service.deactivate_position(db, position_id)
        db.commit()
