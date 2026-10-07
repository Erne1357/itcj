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
        """Encargados (Positions del depto creados por esta app) con usuarios y carreras.

        Tres consultas, sin importar cuántos encargados haya (H10, spec
        2026-10-05-titulatec-rendimiento §3.5): los puestos, y de TODOS ellos de
        una vez sus usuarios y sus carreras. Antes eran dos por puesto.
        """
        from itcj2.core.models.position import Position, UserPosition, ProgramPosition
        from itcj2.core.models.user import User
        from itcj2.core.models.program import Program
        positions = (
            db.query(Position)
            .filter(Position.department_id == department_id,
                    Position.code.like(f"{code_prefix}%"), Position.is_active.is_(True))
            .all()
        )
        if not positions:
            return []
        position_ids = [pos.id for pos in positions]
        users_by_position: dict[int, dict[int, User]] = {pid: {} for pid in position_ids}
        for position_id, u in (
            db.query(UserPosition.position_id, User)
            .join(User, User.id == UserPosition.user_id)
            .filter(UserPosition.position_id.in_(position_ids),
                    UserPosition.is_active.is_(True)).all()
        ):
            users_by_position[position_id].setdefault(u.id, u)
        programs_by_position: dict[int, dict[int, Program]] = {pid: {} for pid in position_ids}
        for position_id, p in (
            db.query(ProgramPosition.position_id, Program)
            .join(Program, Program.id == ProgramPosition.program_id)
            .filter(ProgramPosition.position_id.in_(position_ids)).all()
        ):
            programs_by_position[position_id].setdefault(p.id, p)
        out = []
        for pos in positions:
            out.append({
                "id": pos.id, "name": pos.title,
                # `is_active` viaja a la vista porque una cuenta se puede
                # desactivar DESPUÉS desde la configuración del core, y entonces
                # el encargado deja de poder entrar sin que nada en esta
                # pestaña lo delatara.
                "users": [{"id": u.id, "name": u.full_name,
                           "is_active": bool(u.is_active)}
                          for u in users_by_position[pos.id].values()],
                "programs": [{"id": p.id, "name": p.name}
                             for p in programs_by_position[pos.id].values()],
            })
        return out

    @staticmethod
    def get_manageable_position(db: Session, position_id: int, department_id: int | None,
                                *, app_key: str = "titulatec"):
        """Conjunto A (amplio): puesto del depto, activo y con rol en la app.

        USO INTERNO. Es el conjunto BASE sobre el que `get_owned_position`
        estrecha, y no debe volver a guardar una ruta jamas: A contiene puestos
        COMPARTIDOS que esta app no creo ni lista (`secretary_school_services`,
        `head_school_services`, `aux_school_services`, los de division). Guardar
        `update` con A dejaba que un `position_id` escrito a mano llegara a
        `set_users` + `set_programs` sobre uno de ellos: las carreras amplian en
        silencio el alcance de su ocupante y ocupar el puesto arrastra sus
        `PositionAppRole` en TODAS las apps.

        Devuelve el `Position` o None; nunca lanza. Sin departamento gestionado
        no hay nada administrable (fail-closed).
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
    def get_owned_position(db: Session, position_id: int, department_id: int | None,
                           *, code_prefix: str = "se_officer_", app_key: str = "titulatec"):
        """Conjunto B (propio) = A ∩ (code LIKE prefix%). None si no procede.

        Es la guarda de TODA ruta que muta un puesto: `update` y `deactivate`.
        Más estrecho que A a propósito, porque ambas operaciones tocan
        `core_positions`, compartida con las demás apps del organigrama:
        `deactivate_position` apaga el puesto y cierra todas sus `UserPosition`,
        y `set_users`/`set_programs` le cambian ocupantes y carreras. El prefijo
        que pone `create_officer` es la marca de propiedad — esta app solo
        edita y destruye lo que ella creó.
        """
        pos = OfficerService.get_manageable_position(
            db, position_id, department_id, app_key=app_key)
        if pos is None or not (pos.code or "").startswith(code_prefix):
            return None
        return pos

    @staticmethod
    def activate_users(db: Session, user_ids: set[int], *, department_id: int,
                       actor_id: int | None = None) -> list[dict]:
        """Reactiva las cuentas INACTIVAS que van a ser encargados. Devuelve a quiénes tocó.

        Por qué existe (2026-09-17): nombrar encargado a una cuenta inactiva
        producía un encargado MUERTO. `auth_service.py:45` filtra
        `is_active=True` al entrar, así que la persona salía en la lista, tenía
        el rol `titulatec_school_services` y su alcance por carrera, y no podía
        iniciar sesión. En Servicios Escolares eran 9 de 11 cuentas: los
        `aux_school_services`, dados de alta en una campaña de inventario de
        helpdesk y desactivados desde entonces.

        Restablece además la contraseña a `DEFAULT_PASSWORD` (decisión del
        usuario, 2026-09-17). Esto INVALIDA la contraseña anterior, así que la
        UI lo dice antes de guardar y lo confirma después; no es un efecto
        secundario callado. Lo que evita que quede una credencial conocida es
        `core/api/users.py::password_state`: quien tenga exactamente esa
        contraseña recibe la pantalla de cambio obligatorio al entrar.

        El conjunto permitido es el MISMO que valida `create_officer` y
        `set_users`: usuarios con puesto activo en el departamento que gestiona
        el jefe. Un `user_id` escrito a mano que no esté ahí se ignora en
        silencio y NO se activa — esta función nunca es la guarda única, pero
        tampoco puede ser el agujero por el que se active a un ajeno. Es lo que
        acota el alcance de un permiso de titulatec que toca identidad del core.

        Una cuenta YA activa no se toca: ni su `is_active` ni su contraseña.
        Sin ella, editar un encargado para agregarle una carrera le habría
        reseteado la contraseña a todos sus ocupantes.
        """
        import logging

        from itcj2.core.models.user import User
        from itcj2.core.utils.security import DEFAULT_PASSWORD, hash_nip

        if department_id is None:
            raise ValueError("Sin departamento gestionado")
        permitidos = OfficerService.department_user_ids(db, department_id)
        objetivo = set(user_ids) & permitidos
        if not objetivo:
            return []

        tocados = []
        for u in db.query(User).filter(User.id.in_(objetivo),
                                       User.is_active.is_(False)).all():
            u.is_active = True
            u.password_hash = hash_nip(DEFAULT_PASSWORD)
            # Lo mismo que hace `core/api/users_admin.py::reset_password`. La
            # pantalla de cambio obligatorio la decide `password_state`
            # comparando el hash contra `DEFAULT_PASSWORD`, así que el flujo
            # funcionaría sin esta línea; se pone para no dejar la columna
            # diciendo lo contrario que el hash en la cuenta de alguien que sí
            # se había puesto contraseña propia antes de que la desactivaran.
            u.must_change_password = True
            tocados.append({"id": u.id, "name": u.full_name})
        if tocados:
            # Bitácora ANTES del commit: la fila viaja con el cambio de cuenta y
            # contraseña (si el commit revierte, el rastro también). Solo ids y el
            # hecho del restablecimiento: nunca la contraseña ni su hash.
            from itcj2.apps.titulatec.services.audit_service import AuditService
            AuditService.record(
                db, "officer.account_reactivated",
                entity_type="user",
                subject=f"{len(tocados)} cuenta(s) reactivada(s)",
                payload={
                    "user_ids": [t["id"] for t in tocados],
                    "department_id": department_id,
                    "credential_reset": True,
                    "forced_change_on_login": True,
                },
                actor_id=actor_id,
            )
            db.commit()
            logging.getLogger("itcj2.apps.titulatec.services.officer_service").info(
                "Encargados: actor %s reactivó y restableció la contraseña de %s "
                "en el departamento %s",
                actor_id, [t["id"] for t in tocados], department_id,
            )
        return tocados

    @staticmethod
    def _sync_programs(db: Session, position_id: int, program_ids: set[int]) -> tuple[list[int], list[int]]:
        """Sincroniza ProgramPosition SIN commit. Devuelve (antes, después) ordenados."""
        from itcj2.core.models.position import ProgramPosition
        current = {pp.program_id for pp in
                   db.query(ProgramPosition).filter_by(position_id=position_id).all()}
        for pid in current - set(program_ids):
            db.query(ProgramPosition).filter_by(position_id=position_id, program_id=pid).delete()
        for pid in set(program_ids) - current:
            db.add(ProgramPosition(position_id=position_id, program_id=pid))
        return sorted(current), sorted(set(program_ids))

    @staticmethod
    def _position_title(db: Session, position_id: int) -> str | None:
        """Nombre del encargado para el `subject` de la bitácora (nunca truena)."""
        from itcj2.core.models.position import Position
        pos = db.get(Position, position_id)
        title = getattr(pos, "title", None)
        return title if isinstance(title, str) else None

    @staticmethod
    def set_programs(db: Session, position_id: int, program_ids: set[int]) -> None:
        """Sincroniza ProgramPosition del puesto = program_ids."""
        from itcj2.apps.titulatec.services.audit_service import AuditService
        antes, despues = OfficerService._sync_programs(db, position_id, program_ids)
        if antes != despues:
            # `program_position` es de core: la red ORM no la ve, esta fila es el
            # único rastro de quién cambió el alcance por carrera.
            AuditService.record(
                db, "officer.programs_changed",
                entity_type="position", entity_id=position_id,
                subject=OfficerService._position_title(db, position_id),
                before={"program_ids": antes}, after={"program_ids": despues},
            )
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
        error: Exception | None = None
        try:
            for uid in current - set(user_ids):
                positions_service.remove_user_from_position(db, uid, position_id)
            for uid in set(user_ids) - current:
                positions_service.assign_user_to_position(db, uid, position_id)
        except Exception as exc:  # se registra lo que SÍ quedó y se re-lanza
            error = exc
        # `positions_service` commitea por dentro (una vez por persona): aunque una
        # asignación falle a medias, las anteriores ya persistieron. La fila se
        # escribe SIEMPRE y con lo que de verdad quedó (re-consultado), marcada
        # `partial` si hubo error; la excepción original sigue su camino.
        despues = OfficerService._active_user_ids(db, position_id)
        if current != despues:
            from itcj2.apps.titulatec.services.audit_service import AuditService
            payload = {"assigned_role": assigned_role,
                       "added": sorted(despues - current),
                       "removed": sorted(current - despues)}
            if error is not None:
                payload.update(partial=True, error=type(error).__name__,
                               requested=sorted(set(user_ids)))
            AuditService.record(
                db, "officer.users_changed",
                entity_type="position", entity_id=position_id,
                subject=OfficerService._position_title(db, position_id),
                before={"user_ids": sorted(current)},
                after={"user_ids": sorted(despues)},
                payload=payload,
            )
            db.commit()
        if error is not None:
            raise error

    @staticmethod
    def _active_user_ids(db: Session, position_id: int) -> set[int]:
        """Personas con asignación vigente al puesto, leídas de la BD."""
        from itcj2.core.models.position import UserPosition
        if not db.is_active:
            db.rollback()
        return {uid for (uid,) in db.query(UserPosition.user_id)
                .filter_by(position_id=position_id, is_active=True).all()}

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
        # El id se toma YA: si el `flush` de abajo falla, la sesión revierte y
        # `pos` queda expirado (leer `pos.id` daría `PendingRollbackError`).
        pos_id = pos.id
        error: Exception | None = None
        try:
            positions_service.assign_role_to_position(db, pos_id, "titulatec", assigned_role)
            for uid in user_ids:
                positions_service.assign_user_to_position(db, uid, pos_id)
            OfficerService._sync_programs(db, pos_id, program_ids)
            # `_sync_programs` solo hace `db.add`, y la sesión de producción NO
            # autoflushea: sin este flush la consulta de `carreras` de abajo no
            # veía las filas nuevas y la bitácora decía «sin carreras» (revisión
            # final I1). Además mete aquí, dentro del `try`, el error de una
            # carrera que no existe (FK): antes salía en el `commit` final y la
            # fila del alta se perdía con el puesto ya creado.
            db.flush()
        except Exception as exc:  # el puesto ya existe: se registra lo que quedó
            error = exc
        # Una sola fila para el alta (puesto + rol + personas + carreras), escrita
        # SIEMPRE: `positions_service` commitea por dentro, así que un fallo a
        # medias deja el puesto y a quienes ya se asignaron. `after` sale de la BD,
        # no de lo solicitado; con error lleva `partial`, la clase del error y lo
        # que se pidió (`requested`, como `set_users`).
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.core.models.position import ProgramPosition
        usuarios = OfficerService._active_user_ids(db, pos_id)
        carreras = sorted(pid for (pid,) in db.query(ProgramPosition.program_id)
                          .filter_by(position_id=pos_id).all())
        payload = {"department_id": department_id, "assigned_role": assigned_role,
                   "code": code}
        if error is not None:
            payload.update(partial=True, error=type(error).__name__,
                           requested={"user_ids": sorted(set(user_ids)),
                                      "program_ids": sorted(set(program_ids))})
        AuditService.record(
            db, "officer.created",
            entity_type="position", entity_id=pos_id, subject=name,
            after={"user_ids": sorted(usuarios), "program_ids": carreras},
            payload=payload,
        )
        db.commit()
        if error is not None:
            raise error
        return pos_id

    @staticmethod
    def deactivate_officer(db: Session, position_id: int) -> None:
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.core.models.position import UserPosition
        # Quiénes ocupaban el puesto, ANTES: `deactivate_position` cierra sus
        # UserPosition y commitea por dentro.
        ocupantes = sorted(
            uid for (uid,) in db.query(UserPosition.user_id)
            .filter_by(position_id=position_id, is_active=True).all())
        titulo = OfficerService._position_title(db, position_id)
        if positions_service.deactivate_position(db, position_id):
            AuditService.record(
                db, "officer.deactivated",
                entity_type="position", entity_id=position_id, subject=titulo,
                before={"user_ids": ocupantes}, after={"user_ids": []},
            )
        db.commit()
