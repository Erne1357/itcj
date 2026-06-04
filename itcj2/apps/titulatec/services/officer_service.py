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
        """Sincroniza los usuarios del puesto (solo usuarios del depto)."""
        allowed = OfficerService.department_user_ids(db, department_id) | set(user_ids)
        bad = set(user_ids) - allowed
        if bad:
            raise ValueError(f"Usuarios fuera del departamento: {bad}")
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
