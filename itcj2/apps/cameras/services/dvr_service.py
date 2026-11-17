"""Servicio de DVR: credenciales cifradas, scope por departamento y bitácora.

Commit en el service. `detail` de la bitácora solo lleva nombres de campo e ids de
departamento; jamás valores de secretos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import exists, or_
from sqlalchemy.orm import Session, selectinload

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
# username/notes son solo escritura: vacío = sin cambio; se borran con remove_*.
_WRITE_ONLY = ("username", "notes")


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
    password: str | None = field(repr=False)
    pattern: str | None = field(repr=False)
    username: str | None = field(repr=False)
    notes: str | None = field(repr=False)
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
    # Todo se valida y cifra ANTES de mutar el objeto o escribir bitácora.
    new_pattern = secrets.normalize_pattern(data.pattern) if data.pattern else None
    new_pwd_cipher = secrets.encrypt(data.password) if data.password else None
    new_pat_cipher = secrets.encrypt(new_pattern) if new_pattern else None
    dept_ids = set(data.department_ids)
    new_depts = None
    if dept_ids != {d.id for d in dvr.departments}:
        from itcj2.core.models.department import Department
        new_depts = db.query(Department).filter(Department.id.in_(dept_ids)).all() if dept_ids else []
        if len(new_depts) != len(dept_ids):
            raise ValueError("Departamento no encontrado.")

    keeps_pwd = new_pwd_cipher or (dvr.password_cipher and not data.remove_password)
    keeps_pat = new_pat_cipher or (dvr.pattern_cipher and not data.remove_pattern)
    if not (keeps_pwd or keeps_pat):
        raise ValueError("Captura al menos la contraseña o el patrón.")

    values = {}
    for f in _PLAIN_FIELDS:
        v = getattr(data, f)
        if f in _WRITE_ONLY:
            if getattr(data, f"remove_{f}"):
                v = None
            elif not v:
                continue
        if getattr(dvr, f) != v:
            values[f] = v
    for f, v in values.items():
        setattr(dvr, f, v)
    if values:
        _log(db, dvr, actor_id, "update", {"fields": list(values)})

    if new_pwd_cipher:
        dvr.password_cipher = new_pwd_cipher
        _log(db, dvr, actor_id, "password_update")
    elif data.remove_password and dvr.password_cipher:
        dvr.password_cipher = None
        _log(db, dvr, actor_id, "password_update", {"removed": True})

    if new_pat_cipher:
        dvr.pattern_cipher = new_pat_cipher
        _log(db, dvr, actor_id, "pattern_update")
    elif data.remove_pattern and dvr.pattern_cipher:
        dvr.pattern_cipher = None
        _log(db, dvr, actor_id, "pattern_update", {"removed": True})

    if new_depts is not None:
        dvr.departments = new_depts
        _log(db, dvr, actor_id, "departments_update", {"departments": sorted(dept_ids)})
    db.commit()
    db.refresh(dvr)
    return dvr


def set_password(db: Session, viewer: Viewer, dvr_id: int, password: str, actor_id: int) -> bool:
    """False (sin escribir) si el DVR no es visible o el viewer no puede cambiarla."""
    if not password:
        raise ValueError("La contraseña no puede estar vacía.")
    if not (viewer.can_update_password or viewer.can_manage):
        return False
    dvr = get_visible(db, viewer, dvr_id)
    if dvr is None:
        return False
    dvr.password_cipher = secrets.encrypt(password)
    _log(db, dvr, actor_id, "password_update")
    if not viewer.see_all:  # un jefe cambió: Soporte, admins y los demás jefes se enteran
        from itcj2.apps.cameras.services import notify_service
        notify_service.notify_password_changed(db, dvr, actor_id)
    db.commit()
    return True


def deactivate(db: Session, dvr: Dvr, actor_id: int) -> None:
    dvr.is_active = False
    _log(db, dvr, actor_id, "deactivate")
    db.commit()


def reactivate(db: Session, dvr: Dvr, actor_id: int) -> None:
    dvr.is_active = True
    _log(db, dvr, actor_id, "reactivate")
    db.commit()


def get_inactive(db: Session, dvr_id: int) -> Dvr | None:
    dvr = db.get(Dvr, dvr_id)
    return dvr if dvr is not None and not dvr.is_active else None


def list_inactive(db: Session) -> list[dict]:
    """DVR dados de baja con cuándo y quién (de la última baja en bitácora, si existe)."""
    from itcj2.core.models.user import User
    dvrs = (db.query(Dvr).options(selectinload(Dvr.departments))
            .filter(Dvr.is_active.is_(False)).order_by(Dvr.name).all())
    out = []
    for d in dvrs:
        log = (db.query(CamerasAuditLog)
               .filter(CamerasAuditLog.dvr_id == d.id, CamerasAuditLog.action == "deactivate")
               .order_by(CamerasAuditLog.id.desc()).first())
        u = db.get(User, log.actor_id) if log and log.actor_id else None
        out.append({"dvr": d, "when": log.created_at if log else None,
                    "by": u.full_name if u else None})
    return out


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
    # detail: solo qué se entregó (booleanos), nunca los valores.
    _log(db, dvr, actor_id, "reveal", {
        "pattern": pattern is not None, "password": password is not None,
        "username": bool(dvr.username), "notes": bool(dvr.notes)})
    db.commit()
    # Sin contraseña no hay "actualizada por" que mostrar.
    when = last.created_at if last and password is not None else None
    return Revealed(password, pattern, dvr.username, dvr.notes, when,
                    changed_by if password is not None else None)


EXTEND_WINDOW_MIN = 10
EXTEND_MAX = 10


def extend(db: Session, dvr: Dvr, actor_id: int) -> None:
    """Registra que se amplió el plazo del revelado (sin detalle: nada secreto).

    Solo tras un revelado reciente del mismo actor y DVR (último reveal en la
    ventana) y hasta EXTEND_MAX extensiones posteriores a ese reveal.
    """
    from sqlalchemy import func
    last_reveal = (db.query(func.max(CamerasAuditLog.id))
                   .filter(CamerasAuditLog.dvr_id == dvr.id, CamerasAuditLog.actor_id == actor_id,
                           CamerasAuditLog.action == "reveal",
                           CamerasAuditLog.created_at >= func.now() - timedelta(minutes=EXTEND_WINDOW_MIN))
                   .scalar())
    if last_reveal is None:
        raise ValueError("Vuelve a revelar el DVR.")
    used = (db.query(CamerasAuditLog)
            .filter(CamerasAuditLog.dvr_id == dvr.id, CamerasAuditLog.actor_id == actor_id,
                    CamerasAuditLog.action == "extend", CamerasAuditLog.id > last_reveal)
            .count())
    if used >= EXTEND_MAX:
        raise ValueError("Vuelve a revelar el DVR.")
    _log(db, dvr, actor_id, "extend")
    db.commit()


def audit_page(db: Session, *, page: int, per_page: int = 50, dvr_id: int | None = None,
               actor_id: int | None = None, action: str | None = None,
               desde: date | None = None, hasta: date | None = None):
    """`desde`/`hasta` inclusivos, sobre created_at tal como se muestra (sin conversión)."""
    from itcj2.core.models.user import User
    q = db.query(CamerasAuditLog)
    if dvr_id:
        q = q.filter(CamerasAuditLog.dvr_id == dvr_id)
    if actor_id:
        q = q.filter(CamerasAuditLog.actor_id == actor_id)
    if action:
        q = q.filter(CamerasAuditLog.action == action)
    if desde:
        q = q.filter(CamerasAuditLog.created_at >= datetime.combine(desde, time.min))
    if hasta:
        q = q.filter(CamerasAuditLog.created_at < datetime.combine(hasta + timedelta(days=1), time.min))
    total = q.count()
    rows = (q.order_by(CamerasAuditLog.id.desc())
            .offset(max(page - 1, 0) * per_page).limit(per_page).all())
    names = {u.id: u.full_name for u in
             db.query(User).filter(User.id.in_({r.actor_id for r in rows if r.actor_id})).all()}
    return [{"id": r.id, "dvr_id": r.dvr_id, "dvr_name": r.dvr_name, "actor_id": r.actor_id,
             "actor_name": names.get(r.actor_id), "action": r.action, "detail": r.detail,
             "created_at": r.created_at} for r in rows], total


def audit_actors(db: Session) -> list[tuple[int, str]]:
    """Personas que aparecen en la bitácora, (id, nombre completo) por nombre."""
    from itcj2.core.models.user import User
    ids = [i for (i,) in db.query(CamerasAuditLog.actor_id).distinct().all() if i]
    users = db.query(User).filter(User.id.in_(ids)).all() if ids else []
    return sorted(((u.id, u.full_name) for u in users), key=lambda t: t[1] or "")
