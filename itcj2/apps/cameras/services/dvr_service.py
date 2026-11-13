"""Servicio de DVR: credenciales cifradas, scope por departamento y bitácora.

Commit en el service. `detail` de la bitácora solo lleva nombres de campo e ids de
departamento; jamás valores de secretos.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, or_
from sqlalchemy.orm import Session

from itcj2.apps.cameras.models import CamerasAuditLog, Dvr, DvrDepartment
from itcj2.apps.cameras.schemas.dvr import DvrInput
from itcj2.apps.cameras.services import secrets

PERM_PAGE = "cameras.dvrs.page.list"
PERM_READ_ALL = "cameras.dvrs.api.read.all"
PERM_READ_DEPT = "cameras.dvrs.api.read.department"
PERM_MANAGE = "cameras.dvrs.api.manage"
PERM_PWD_DEPT = "cameras.credentials.api.update.department"
PERM_AUDIT = "cameras.audit.page.list"
APP = "cameras"

_PLAIN_FIELDS = ("name", "location", "brand", "model", "channels", "username", "notes")


@dataclass(frozen=True)
class Viewer:
    user_id: int
    see_all: bool
    dept_ids: frozenset[int]
    can_manage: bool
    can_update_password: bool
    can_audit: bool


@dataclass
class Revealed:
    password: str | None
    pattern: str | None
    username: str | None
    notes: str | None
    password_changed_at: datetime | None
    password_changed_by: str | None


def viewer_for(db: Session, user: dict) -> Viewer:
    uid = int(user["sub"])
    if user.get("role") == "admin":
        return Viewer(uid, True, frozenset(), True, True, True)
    from itcj2.core.services import authz_cache
    from itcj2.core.services.scope_service import granting_departments

    perms: set = set()
    if authz_cache.cached_has_assignment(db, uid, APP):
        perms = authz_cache.cached_perms(db, uid, APP)
    depts = (frozenset(granting_departments(db, uid, APP, PERM_READ_DEPT))
             if PERM_READ_DEPT in perms else frozenset())
    return Viewer(uid, PERM_READ_ALL in perms, depts, PERM_MANAGE in perms,
                  PERM_PWD_DEPT in perms, PERM_AUDIT in perms)


def _log(db: Session, dvr: Dvr | None, actor_id: int, action: str, detail: dict | None = None):
    db.add(CamerasAuditLog(
        dvr_id=dvr.id if dvr else None, dvr_name=dvr.name if dvr else None,
        actor_id=actor_id, action=action, detail=detail or None))


def _visible_query(db: Session, viewer: Viewer):
    q = db.query(Dvr).filter(Dvr.is_active.is_(True))
    if viewer.see_all:
        return q
    if not viewer.dept_ids:
        return q.filter(False)
    return q.filter(exists().where(
        DvrDepartment.dvr_id == Dvr.id, DvrDepartment.department_id.in_(viewer.dept_ids)))


def list_visible(db: Session, viewer: Viewer, q: str | None = None) -> list[Dvr]:
    from itcj2.core.models.department import Department
    query = _visible_query(db, viewer)
    if q and q.strip():
        like = f"%{q.strip()}%"
        dept_match = exists().where(
            DvrDepartment.dvr_id == Dvr.id, DvrDepartment.department_id == Department.id,
            Department.name.ilike(like))
        query = query.filter(or_(Dvr.name.ilike(like), Dvr.location.ilike(like), dept_match))
    return query.order_by(Dvr.location.asc().nulls_last(), Dvr.name).all()


def get_visible(db: Session, viewer: Viewer, dvr_id: int) -> Dvr | None:
    return _visible_query(db, viewer).filter(Dvr.id == dvr_id).first()


def _set_departments(db: Session, dvr: Dvr, ids: list[int]) -> bool:
    """Reemplaza los departamentos; True si cambió el conjunto."""
    from itcj2.core.models.department import Department
    wanted = set(ids)
    if wanted == {d.id for d in dvr.departments}:
        return False
    found = db.query(Department).filter(Department.id.in_(wanted)).all() if wanted else []
    if len(found) != len(wanted):
        raise ValueError("Departamento no encontrado.")
    dvr.departments = found
    return True


def create(db: Session, data: DvrInput, actor_id: int) -> Dvr:
    password = data.password or None
    pattern = secrets.normalize_pattern(data.pattern) if data.pattern else None
    if not password and not pattern:
        raise ValueError("Captura al menos la contraseña o el patrón.")
    dvr = Dvr(
        **{f: getattr(data, f) for f in _PLAIN_FIELDS},
        password_cipher=secrets.encrypt(password) if password else None,
        pattern_cipher=secrets.encrypt(pattern) if pattern else None,
        created_by_id=actor_id,
    )
    db.add(dvr)
    _set_departments(db, dvr, data.department_ids)
    db.flush()
    _log(db, dvr, actor_id, "create", {"departments": sorted(data.department_ids)})
    db.commit()
    db.refresh(dvr)
    return dvr


def update(db: Session, dvr: Dvr, data: DvrInput, actor_id: int) -> Dvr:
    changed = [f for f in _PLAIN_FIELDS if getattr(dvr, f) != getattr(data, f)]
    for f in changed:
        setattr(dvr, f, getattr(data, f))
    if changed:
        _log(db, dvr, actor_id, "update", {"fields": changed})

    if data.password:
        dvr.password_cipher = secrets.encrypt(data.password)
        _log(db, dvr, actor_id, "password_update")
    elif data.remove_password and dvr.password_cipher:
        dvr.password_cipher = None
        _log(db, dvr, actor_id, "password_update", {"removed": True})

    if data.pattern:
        dvr.pattern_cipher = secrets.encrypt(secrets.normalize_pattern(data.pattern))
        _log(db, dvr, actor_id, "pattern_update")
    elif data.remove_pattern and dvr.pattern_cipher:
        dvr.pattern_cipher = None
        _log(db, dvr, actor_id, "pattern_update", {"removed": True})

    if _set_departments(db, dvr, data.department_ids):
        _log(db, dvr, actor_id, "departments_update",
             {"departments": sorted(data.department_ids)})
    db.commit()
    db.refresh(dvr)
    return dvr


def set_password(db: Session, dvr: Dvr, password: str, actor_id: int) -> None:
    if not password:
        raise ValueError("La contraseña no puede estar vacía.")
    dvr.password_cipher = secrets.encrypt(password)
    _log(db, dvr, actor_id, "password_update")
    db.commit()


def deactivate(db: Session, dvr: Dvr, actor_id: int) -> None:
    dvr.is_active = False
    _log(db, dvr, actor_id, "deactivate")
    db.commit()


def reveal(db: Session, dvr: Dvr, actor_id: int) -> Revealed:
    from itcj2.core.models.user import User
    password = secrets.decrypt(dvr.password_cipher) if dvr.password_cipher else None
    pattern = secrets.decrypt(dvr.pattern_cipher) if dvr.pattern_cipher else None
    last = (db.query(CamerasAuditLog)
            .filter(CamerasAuditLog.dvr_id == dvr.id,
                    CamerasAuditLog.action.in_(("password_update", "create")))
            .order_by(CamerasAuditLog.id.desc()).first())
    changed_by = None
    if last and last.actor_id:
        u = db.get(User, last.actor_id)
        changed_by = u.full_name if u else None
    _log(db, dvr, actor_id, "reveal")
    db.commit()
    return Revealed(password, pattern, dvr.username, dvr.notes,
                    last.created_at if last else None, changed_by)


def audit_page(db: Session, *, page: int, per_page: int = 50, dvr_id: int | None = None,
               actor_id: int | None = None, action: str | None = None):
    from itcj2.core.models.user import User
    q = db.query(CamerasAuditLog)
    if dvr_id:
        q = q.filter(CamerasAuditLog.dvr_id == dvr_id)
    if actor_id:
        q = q.filter(CamerasAuditLog.actor_id == actor_id)
    if action:
        q = q.filter(CamerasAuditLog.action == action)
    total = q.count()
    rows = (q.order_by(CamerasAuditLog.id.desc())
            .offset(max(page - 1, 0) * per_page).limit(per_page).all())
    names = {u.id: u.full_name for u in
             db.query(User).filter(User.id.in_({r.actor_id for r in rows if r.actor_id})).all()}
    return [{"id": r.id, "dvr_id": r.dvr_id, "dvr_name": r.dvr_name, "actor_id": r.actor_id,
             "actor_name": names.get(r.actor_id), "action": r.action, "detail": r.detail,
             "created_at": r.created_at} for r in rows], total
