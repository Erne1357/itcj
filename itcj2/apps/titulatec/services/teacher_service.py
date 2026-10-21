"""Catálogo de docentes por departamento y sus cuentas (fase 4, sinodales).

Spec 2026-10-21 §8 (pestaña «Docentes») y §16b R-B (reutilizar cuentas) y R-G
(inerte con el corte). Un docente es una PERSONA con UNA cuenta (D3): el puesto
`docente_{depto}` (sembrado por el DML de `init-titulatec-fase-2`) lo hace
docente de ese departamento, y su grado y cédula viven en un perfil único
(`TeacherProfile`) que comparten todos sus departamentos.

Reglas que este servicio garantiza (las rutas solo deciden quién y qué depto):

- **Nunca dos cuentas para la misma persona.** Crear se bloquea si el correo ya
  existe (sin distinguir mayúsculas) o si el usuario (parte local del correo)
  ya lo tiene otra cuenta; si solo coincide el nombre, crear exige
  `confirm_other_person`. Las cuentas de ALUMNO (`control_number`) no se
  reutilizan ni se restablecen aquí: escribirles una credencial sería tocar la
  cuenta de un egresado desde un departamento (mismo criterio que el core,
  `users_admin.reset_user_password`).
- **Contraseña temporal = `DEFAULT_PASSWORD`, con cambio obligatorio.** Solo se
  escribe en una cuenta nueva, en una reutilizada inactiva o sin primer acceso
  (`last_login IS NULL`, patrón de `OfficerService.activate_users`) y en
  «Reenviar acceso» (solo sin primer acceso). Una cuenta que ya entró no se
  toca. Restablecer revoca las sesiones vivas en la MISMA transacción
  (`session_service.bump_version(db=db)`). La contraseña JAMÁS va a log,
  bitácora, evento ni respuesta: solo viaja en el correo de acceso
  (`send_access_email`, después del commit, best-effort).
- **Una transacción por acción.** `authz_service.grant_role` y
  `positions_service.assign_user_to_position` commitean por dentro, así que
  aquí NO se usan: la fila del rol `staff` en `itcj` y la del puesto se insertan
  directo, y la bitácora viaja en la misma transacción (antes del commit,
  después de las validaciones).
- **R-G**: con el corte a T-soft en la fase `synodal_assignment` o antes, toda
  mutación responde `INERT_MSG` sin escribir y el correo no sale.
- **RF2**: quitar a un docente de un depto se bloquea mientras tenga
  asignaciones de sinodal vigentes en procesos vivos de carreras de ese depto.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from contextlib import contextmanager

from sqlalchemy import and_, case, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.audit_service import AuditService

logger = logging.getLogger(__name__)

POSITION_PREFIX = "docente_"
# La fase del catálogo que decide si «Docentes» se opera aquí (R-G).
SYNODAL_PHASE_CODE = "synodal_assignment"
STAFF_APP_KEY = "itcj"
STAFF_ROLE = "staff"
# Un proceso en estos estados todavía necesita a sus sinodales (RF2): uno
# revocado o terminado ya no bloquea quitar al docente.
LIVE_PROCESS_STATUSES = ("active", "on_hold")
ACCOUNT_STATUSES = ("active", "pending_first_login", "inactive")

ACCESS_TEMPLATE = "teacher_access.html"
ACCESS_SUBJECT = "[TitulaTec ITCJ] Tu acceso como docente"

_DEGREE_MIN, _DEGREE_MAX = 2, 150
_NAME_MAX = 100
_EMAIL_MAX = 150
_SEARCH_LIMIT_MAX = 50
_LICENSE_RE = re.compile(r"\d{5,12}")
# Parte local que puede ser usuario de la plataforma: empieza con letra o
# dígito; solo letras, dígitos, punto, guion y guion bajo. Se valida YA en
# minúsculas.
_EMAIL_RE = re.compile(r"([a-z0-9][a-z0-9._-]{0,63})@([a-z0-9][a-z0-9.-]*)")

# Plegado para comparar nombres sin acentos ni mayúsculas, igual en Python y en
# SQL (`translate` no necesita la extensión `unaccent`).
_SQL_ACCENTS = "áéíóúüñàèìòùâêîôûçÁÉÍÓÚÜÑÀÈÌÒÙÂÊÎÔÛÇ"
_SQL_PLAIN = "aeiouunaeiouaeioucaeiouunaeiouaeiouc"

# --- Mensajes (español, pensados para `X-Tt-Error`) ---------------------------
INERT_MSG = ("El catálogo de docentes todavía no se opera en esta app "
             "(la asignación de sinodales sigue fuera de la plataforma).")
DEPARTMENT_MSG = "El departamento no existe."
NO_POSITION_MSG = ("El departamento no tiene el puesto «Docente». "
                   "Hace falta correr `titulatec init-titulatec-fase-2`.")
STAFF_MISSING_MSG = "Falta el rol «staff» de la plataforma: avisa a un administrador."
USER_NOT_FOUND_MSG = "La cuenta no existe."
STUDENT_ACCOUNT_MSG = ("Esa es una cuenta de alumno: no se puede usar como docente. "
                       "Da de alta a la persona con su correo institucional.")
NO_USERNAME_MSG = ("La cuenta no tiene usuario para iniciar sesión: "
                   "pide a un administrador que se lo asigne.")
DEGREE_MSG = "El grado académico debe tener entre 2 y 150 caracteres."
LICENSE_MSG = "La cédula profesional debe tener de 5 a 12 dígitos."
FIRST_NAME_MSG = "Captura el nombre o nombres (hasta 100 caracteres)."
LAST_NAME_MSG = "Captura el apellido paterno (hasta 100 caracteres)."
MIDDLE_NAME_MSG = "El apellido materno admite hasta 100 caracteres."
EMAIL_INVALID_MSG = "Captura un correo institucional válido (usuario@dominio)."
EMAIL_DOMAIN_MSG = "El correo debe ser institucional: {dominios}."
EMAIL_REQUIRED_MSG = ("La cuenta no tiene correo: captura su correo institucional "
                      "(ahí le llegarán los avisos).")
EMAIL_TAKEN_MSG = ("Ya existe una cuenta con ese correo. "
                   "Búscala y agrégala en lugar de crear otra.")
USERNAME_TAKEN_MSG = ("El usuario «{usuario}» ya pertenece a otra cuenta. Si es la misma "
                      "persona, búscala y agrégala; si no, avisa a un administrador.")
NAME_MATCH_MSG = ("Ya hay una cuenta con ese nombre. Si es la misma persona, agrégala "
                  "desde la búsqueda; si no, marca «Es otra persona».")
ALREADY_TEACHER_MSG = "Esa persona ya es docente del departamento."
NOT_TEACHER_MSG = "Esa persona no es docente del departamento."
NOT_TEACHER_ANY_MSG = "Esa cuenta no es docente de ningún departamento."
NO_PROFILE_MSG = "Esa persona no tiene perfil docente."
HAS_ASSIGNMENTS_MSG = ("Tiene asignaciones vigentes como sinodal en procesos de este "
                       "departamento: primero sustitúyelo.")
RESET_NOT_ALLOWED_MSG = ("Solo se puede reenviar el acceso a una cuenta que nunca ha "
                         "iniciado sesión.")
RESET_INACTIVE_MSG = ("La cuenta está desactivada: pide a un administrador que la "
                      "reactive antes de reenviar el acceso.")
CONFLICT_MSG = "Alguien más modificó a esta persona al mismo tiempo. Intenta de nuevo."


class TeacherCandidatesError(ValueError):
    """`ValueError` que además trae las cuentas que lo provocaron, para que la
    pantalla ofrezca reutilizarlas (R-B). `str(error)` es el mensaje."""

    def __init__(self, message: str, candidates: list[dict]):
        super().__init__(message)
        self.candidates = candidates


class EmailTakenError(TeacherCandidatesError):
    """El correo ya es de otra cuenta (D3: nunca se crea una segunda)."""


class NameMatchError(TeacherCandidatesError):
    """Hay cuentas con el mismo nombre: crear exige `confirm_other_person`."""


# ---------------------------------------------------------------------------
# Validaciones puras
# ---------------------------------------------------------------------------
def _collapse(raw) -> str:
    return " ".join(str(raw or "").split())


def _clean_degree(raw) -> str:
    s = _collapse(raw)
    if not _DEGREE_MIN <= len(s) <= _DEGREE_MAX:
        raise ValueError(DEGREE_MSG)
    return s


def _clean_license(raw) -> str:
    s = str(raw or "").strip()
    if not _LICENSE_RE.fullmatch(s):
        raise ValueError(LICENSE_MSG)
    return s


def _clean_name(raw, message: str, *, required: bool) -> str | None:
    s = _collapse(raw)
    if not s:
        if required:
            raise ValueError(message)
        return None
    if len(s) > _NAME_MAX:
        raise ValueError(message)
    return s.upper()


def _fold(raw) -> str:
    """Minúsculas, sin acentos y con espacios colapsados (gemelo de `_fold_sql`)."""
    s = unicodedata.normalize("NFD", _collapse(raw).lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _fold_sql(col):
    return func.translate(
        func.lower(func.trim(func.regexp_replace(col, r"\s+", " ", "g"))),
        _SQL_ACCENTS, _SQL_PLAIN)


@contextmanager
def _writing(db: Session):
    """Bloque de ESCRITURAS de una acción (va después de todas las
    validaciones): cualquier error revierte la transacción entera, y un choque
    de unicidad concurrente (un autoflush o el commit) sale como `CONFLICT_MSG`
    en vez de un `IntegrityError` crudo."""
    try:
        yield
    except IntegrityError:
        db.rollback()
        raise ValueError(CONFLICT_MSG)
    except Exception:
        db.rollback()
        raise


def _vigente_today(link) -> bool:
    """¿Una `UserPosition` YA cargada es vigente hoy? (gemela en Python de
    `authz_service._active_position_filter`, para filas bloqueadas)."""
    from itcj2.core.utils.timezone import db_now

    hoy = db_now().date()
    return (bool(link.is_active)
            and (link.start_date is None or link.start_date <= hoy)
            and (link.end_date is None or link.end_date >= hoy))


class TeacherService:
    """Catálogo de docentes (puesto `docente_{depto}` + perfil) y sus cuentas."""

    # ------------------------------------------------------------------
    # Configuración y corte
    # ------------------------------------------------------------------
    @staticmethod
    def allowed_email_domains() -> tuple[str, ...]:
        """Dominios de `TITULATEC_TEACHER_EMAIL_DOMAINS`, en minúsculas y sin
        repetir. Vacío = ningún alta posible (falla cerrado). Se lee en cada
        llamada: las pruebas parchean el atributo del singleton."""
        from itcj2.config import get_settings

        raw = getattr(get_settings(), "TITULATEC_TEACHER_EMAIL_DOMAINS", "") or ""
        dominios = (d.strip().lower().lstrip("@") for d in str(raw).split(","))
        return tuple(dict.fromkeys(d for d in dominios if d))

    @staticmethod
    def operable(db: Session) -> bool:
        """¿«Docentes» se opera en esta app? (R-G). Falla cerrado: sin la fase
        `synodal_assignment` en el catálogo, o con el corte a T-soft en ella o
        antes, no. Mismo molde que `pages/titulacion_admin.py::_operable`."""
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        n = PhaseService.phase_number_for_code(db, SYNODAL_PHASE_CODE)
        return n is not None and PhaseService._handoff_phase() > n

    @staticmethod
    def _assert_operable(db: Session) -> None:
        if not TeacherService.operable(db):
            raise ValueError(INERT_MSG)

    # ------------------------------------------------------------------
    # Puesto y pertenencia
    # ------------------------------------------------------------------
    @staticmethod
    def _position_or_none(db: Session, department_id):
        from itcj2.core.models.department import Department
        from itcj2.core.models.position import Position

        dept = db.get(Department, department_id) if department_id is not None else None
        if dept is None:
            return None
        return (db.query(Position)
                .filter(Position.code == f"{POSITION_PREFIX}{dept.code}",
                        Position.department_id == dept.id,
                        Position.is_active.is_(True))
                .first())

    @staticmethod
    def position_for(db: Session, department_id: int):
        """El puesto `docente_{code}` del departamento. `ValueError` si el
        departamento no existe o si el DML de la fase 4 no lo sembró."""
        from itcj2.core.models.department import Department

        if department_id is None or db.get(Department, department_id) is None:
            raise ValueError(DEPARTMENT_MSG)
        pos = TeacherService._position_or_none(db, department_id)
        if pos is None:
            raise ValueError(NO_POSITION_MSG)
        return pos

    @staticmethod
    def is_teacher_of(db: Session, user_id: int, department_id: int, *,
                      lock: bool = False) -> bool:
        """¿`user_id` ocupa HOY el puesto docente del departamento?

        `lock=True` toma `FOR SHARE` sobre su `UserPosition`: quien asigna un
        sinodal bajo su propio candado (fase 4) y `remove_from_department` (que
        toma `FOR UPDATE` sobre la misma fila antes de contar asignaciones) se
        serializan, así que no puede quedar un sinodal recién asignado a un
        docente que se estaba quitando (RF2).
        """
        from itcj2.core.models.department import Department
        from itcj2.core.models.position import Position, UserPosition
        from itcj2.core.services.authz_service import _active_position_filter

        q = (db.query(UserPosition.id)
             .join(Position, Position.id == UserPosition.position_id)
             .join(Department, Department.id == Position.department_id)
             .filter(UserPosition.user_id == user_id,
                     Position.department_id == department_id,
                     Position.code == func.concat(POSITION_PREFIX, Department.code),
                     Position.is_active.is_(True),
                     _active_position_filter()))
        if lock:
            q = q.with_for_update(read=True, of=UserPosition)
        return q.first() is not None

    @staticmethod
    def _teacher_departments(db: Session, user_ids) -> dict[int, list[int]]:
        """`{user_id: [department_id, ...]}` donde cada quien es docente HOY
        (una consulta; todo id pedido sale, `[]` si no es docente)."""
        from itcj2.core.models.department import Department
        from itcj2.core.models.position import Position, UserPosition
        from itcj2.core.services.authz_service import _active_position_filter

        ids = sorted({int(u) for u in user_ids})
        out: dict[int, list[int]] = {u: [] for u in ids}
        if not ids:
            return out
        rows = (db.query(UserPosition.user_id, Position.department_id)
                .join(Position, Position.id == UserPosition.position_id)
                .join(Department, Department.id == Position.department_id)
                .filter(UserPosition.user_id.in_(ids),
                        Position.code == func.concat(POSITION_PREFIX, Department.code),
                        Position.is_active.is_(True),
                        _active_position_filter())
                .distinct().all())
        for uid, dept_id in rows:
            out[uid].append(dept_id)
        for lista in out.values():
            lista.sort()
        return out

    # ------------------------------------------------------------------
    # Lecturas: lista del depto y búsqueda de candidatos
    # ------------------------------------------------------------------
    @staticmethod
    def active_assignment_counts(db: Session, user_ids) -> dict[int, int]:
        """`{user_id: n}` de asignaciones de sinodal vigentes (fila activa, en un
        proceso vivo), en UNA consulta. Todo id pedido sale (0 si no tiene)."""
        from itcj2.apps.titulatec.models import SynodalAssignment, TitulationProcess

        ids = sorted({int(u) for u in user_ids})
        out = {u: 0 for u in ids}
        if not ids:
            return out
        rows = (db.query(SynodalAssignment.user_id, func.count(SynodalAssignment.id))
                .join(TitulationProcess, TitulationProcess.id == SynodalAssignment.process_id)
                .filter(SynodalAssignment.user_id.in_(ids),
                        SynodalAssignment.is_active.is_(True),
                        TitulationProcess.status.in_(LIVE_PROCESS_STATUSES))
                .group_by(SynodalAssignment.user_id).all())
        for uid, n in rows:
            out[uid] = int(n)
        return out

    @staticmethod
    def _account_status(user) -> str:
        if not user.is_active:
            return "inactive"
        if user.last_login is None:
            return "pending_first_login"
        return "active"

    @staticmethod
    def roster(db: Session, department_id: int) -> list[dict]:
        """Docentes HOY del departamento, por nombre. Sin el puesto sembrado,
        `[]` (la pantalla pinta su estado vacío; agregar sí dice por qué falla).

        Cada fila: `user_id, name, username, email, academic_degree,
        professional_license` (None sin perfil), `account_status`
        (`active` | `pending_first_login` = `last_login IS NULL` | `inactive`) y
        `active_assignments` (cuántas asignaciones de sinodal vigentes tiene,
        en cualquier departamento: dato informativo). Tres consultas fijas.
        """
        from itcj2.apps.titulatec.models import TeacherProfile
        from itcj2.core.models.position import UserPosition
        from itcj2.core.models.user import User
        from itcj2.core.services.authz_service import _active_position_filter

        pos = TeacherService._position_or_none(db, department_id)
        if pos is None:
            return []
        rows = (db.query(User, TeacherProfile)
                .join(UserPosition, UserPosition.user_id == User.id)
                .outerjoin(TeacherProfile, TeacherProfile.user_id == User.id)
                .filter(UserPosition.position_id == pos.id, _active_position_filter())
                .order_by(User.last_name, User.middle_name, User.first_name, User.id)
                .all())
        vistos: dict[int, tuple] = {}
        for user, prof in rows:
            vistos.setdefault(user.id, (user, prof))
        cuentas = TeacherService.active_assignment_counts(db, vistos)
        return [{
            "user_id": user.id,
            "name": user.full_name,
            "username": user.username,
            "email": user.email,
            "academic_degree": prof.academic_degree if prof else None,
            "professional_license": prof.professional_license if prof else None,
            "account_status": TeacherService._account_status(user),
            "active_assignments": cuentas.get(user.id, 0),
        } for user, prof in vistos.values()]

    @staticmethod
    def _candidate_dicts(db: Session, users) -> list[dict]:
        """Filas de candidato para la UI, en el orden recibido (dos consultas)."""
        from itcj2.apps.titulatec.models import TeacherProfile

        users = list(users)
        if not users:
            return []
        ids = [u.id for u in users]
        deptos = TeacherService._teacher_departments(db, ids)
        perfiles = {p.user_id: p for p in
                    db.query(TeacherProfile).filter(TeacherProfile.user_id.in_(ids)).all()}
        out = []
        for u in users:
            prof = perfiles.get(u.id)
            out.append({
                "user_id": u.id,
                "name": u.full_name,
                "username": u.username,
                "email": u.email,
                "is_active": bool(u.is_active),
                "has_logged_in": u.last_login is not None,
                "already_in": deptos.get(u.id, []),
                "academic_degree": prof.academic_degree if prof else None,
                "professional_license": prof.professional_license if prof else None,
            })
        return out

    @staticmethod
    def search_candidates(db: Session, q: str, *, limit: int = 10) -> list[dict]:
        """Cuentas de PERSONAL que casan con `q` para «Agregar docente» (R-B).

        Busca por correo (exacto o parcial), usuario (parcial) y nombre (todas
        las palabras, en cualquier orden, sin acentos ni mayúsculas). El correo
        exacto va primero; luego por nombre. Excluye cuentas de alumno
        (`control_number`); incluye las inactivas (se reactivan al agregarlas).
        Cada fila: `user_id, name, username, email, is_active, has_logged_in,
        already_in` (deptos donde ya es docente) y el perfil si lo tiene.
        """
        from itcj2.apps.titulatec.utils.paging import like_pattern, normalize_q
        from itcj2.core.models.user import User

        texto = normalize_q(q)
        if not texto:
            return []
        limit = max(1, min(int(limit or 10), _SEARCH_LIMIT_MAX))
        bajo = texto.lower()
        patron = like_pattern(bajo)
        correo = func.lower(func.trim(User.email))
        nombre = _fold_sql(func.concat_ws(" ", User.first_name, User.last_name,
                                          User.middle_name))
        palabras = _fold(texto).split()
        conds = [correo == bajo,
                 correo.like(patron, escape="\\"),
                 func.lower(User.username).like(patron, escape="\\")]
        if palabras:
            conds.append(and_(*[nombre.like(like_pattern(p), escape="\\") for p in palabras]))
        users = (db.query(User)
                 .filter(User.control_number.is_(None), or_(*conds))
                 .order_by(case((correo == bajo, 0), else_=1),
                           User.last_name, User.middle_name, User.first_name, User.id)
                 .limit(limit).all())
        return TeacherService._candidate_dicts(db, users)

    # ------------------------------------------------------------------
    # Piezas internas de las mutaciones
    # ------------------------------------------------------------------
    @staticmethod
    def _clean_email(raw) -> str:
        """Correo institucional en minúsculas, con dominio permitido."""
        s = str(raw or "").strip().lower()
        m = _EMAIL_RE.fullmatch(s) if len(s) <= _EMAIL_MAX else None
        if m is None:
            raise ValueError(EMAIL_INVALID_MSG)
        dominios = TeacherService.allowed_email_domains()
        if m.group(2) not in dominios:
            raise ValueError(EMAIL_DOMAIN_MSG.format(
                dominios=", ".join(f"@{d}" for d in dominios) or "(ninguno configurado)"))
        return s

    @staticmethod
    def _email_owners(db: Session, email: str, *, exclude_id=None) -> list:
        from itcj2.core.models.user import User

        q = db.query(User).filter(func.lower(func.trim(User.email)) == email)
        if exclude_id is not None:
            q = q.filter(User.id != exclude_id)
        return q.order_by(User.id).limit(10).all()

    @staticmethod
    def _staff_ids(db: Session) -> tuple[int, int]:
        """`(app_id, role_id)` del rol `staff` en `itcj` (D4)."""
        from itcj2.core.services.authz_service import get_app_by_key, get_role_by_name

        app = get_app_by_key(db, STAFF_APP_KEY)
        role = get_role_by_name(db, STAFF_ROLE)
        if app is None or role is None:
            raise ValueError(STAFF_MISSING_MSG)
        return app.id, role.id

    @staticmethod
    def _ensure_staff_role(db: Session, user_id: int, app_id: int, role_id: int) -> bool:
        """Inserta `staff` en `itcj` si falta, SIN commit (no `grant_role`, que
        commitea por dentro). True si lo agregó."""
        from itcj2.core.models.user_app_role import UserAppRole

        existe = db.query(UserAppRole).filter_by(
            user_id=user_id, app_id=app_id, role_id=role_id).first()
        if existe is not None:
            return False
        db.add(UserAppRole(user_id=user_id, app_id=app_id, role_id=role_id))
        return True

    @staticmethod
    def _open_position(db: Session, user_id: int, position_id: int, stale: list) -> None:
        """Da el puesto docente, SIN commit. `stale` son filas `is_active` que ya
        no son vigentes (vencidas o futuras): se cierran primero, porque el
        índice único parcial `uq_active_user_position_new` admite una sola fila
        activa por (persona, puesto). `start_date` lo pone la BD
        (`current_date`): vigente desde ya."""
        from itcj2.core.models.position import UserPosition

        if stale:
            for link in stale:
                link.is_active = False
            db.flush()
        db.add(UserPosition(user_id=user_id, position_id=position_id, is_active=True,
                            notes="Alta en el catálogo de docentes (TitulaTec)"))

    @staticmethod
    def _locked_links(db: Session, user_id: int, position_id: int) -> list:
        """Filas `is_active` de (persona, puesto) con `FOR UPDATE`."""
        from itcj2.core.models.position import UserPosition

        return (db.query(UserPosition)
                .filter(UserPosition.user_id == user_id,
                        UserPosition.position_id == position_id,
                        UserPosition.is_active.is_(True))
                .populate_existing().with_for_update().all())

    @staticmethod
    def _locked_user(db: Session, user_id: int):
        from itcj2.core.models.user import User

        return (db.query(User).filter(User.id == user_id)
                .populate_existing().with_for_update().first())

    @staticmethod
    def _reset_credentials(db: Session, user) -> None:
        """`DEFAULT_PASSWORD` + cambio obligatorio + sesiones revocadas, en la
        transacción del llamador. Nunca registra la contraseña."""
        from itcj2.core.services import session_service
        from itcj2.core.utils.security import DEFAULT_PASSWORD, hash_nip

        user.password_hash = hash_nip(DEFAULT_PASSWORD)
        user.must_change_password = True
        if session_service.bump_version(user.id, db=db) is None:
            # `bump_version` nunca lanza: un None dejaría la credencial nueva con
            # las sesiones anteriores vivas (patrón de `reassign_nip`).
            raise RuntimeError("no se pudieron revocar las sesiones de la cuenta")

    @staticmethod
    def _upsert_profile(db: Session, user_id: int, actor_id: int, degree: str,
                        license_: str) -> tuple[bool, dict, dict]:
        """Crea o actualiza el perfil único, SIN commit. -> (creado, antes, después)
        con solo lo que cambió."""
        from itcj2.apps.titulatec.models import TeacherProfile
        from itcj2.core.utils.timezone import db_now

        prof = (db.query(TeacherProfile).filter(TeacherProfile.user_id == user_id)
                .populate_existing().with_for_update().first())
        nuevo = {"academic_degree": degree, "professional_license": license_}
        if prof is None:
            db.add(TeacherProfile(user_id=user_id, academic_degree=degree,
                                  professional_license=license_, updated_by_id=actor_id))
            return True, {}, nuevo
        antes = {"academic_degree": prof.academic_degree,
                 "professional_license": prof.professional_license}
        before, after = AuditService.changes(antes, nuevo)
        if after:
            prof.academic_degree = degree
            prof.professional_license = license_
            prof.updated_at = db_now()
            prof.updated_by_id = actor_id
        return False, before, after

    @staticmethod
    def _after_commit(user_id: int, *, credentials_reset: bool) -> None:
        """Caché de authz (el puesto y el rol cambian lo que puede) y, si se
        revocaron sesiones, la época en caché. Best-effort."""
        try:
            from itcj2.core.services.authz_cache import invalidate_user
            invalidate_user(user_id)
        except Exception:  # nunca romper la acción por el caché
            logger.warning("Docentes: no se invalidó el caché de authz de %s", user_id)
        if credentials_reset:
            try:
                from itcj2.core.services import session_service
                session_service.forget_cached_version(user_id)
            except Exception:
                logger.warning("Docentes: no se olvidó la época en caché de %s", user_id)

    # ------------------------------------------------------------------
    # Mutaciones
    # ------------------------------------------------------------------
    @staticmethod
    def add_existing(db: Session, actor_id: int, department_id: int, user_id: int, *,
                     academic_degree, professional_license,
                     institutional_email=None) -> dict:
        """Hace docente del departamento a una cuenta que YA existe (R-B).

        - Inactiva o sin primer acceso (`last_login IS NULL`): se reactiva y se
          restablece `DEFAULT_PASSWORD` con cambio obligatorio (patrón de
          `OfficerService.activate_users`); hay que mandarle el correo de acceso.
        - Ya entró alguna vez y está activa: su contraseña no se toca.
        - Sin correo: se le escribe `institutional_email` (obligatorio en ese
          caso, con dominio permitido y sin dueño). Con otro correo: no se pisa.
        - Rol `staff` en `itcj` si le falta; puesto `docente_{depto}`; perfil
          creado o actualizado (es uno solo para todos sus departamentos).

        Devuelve `{"user_id", "access_email_needed"}`; el correo lo manda quien
        llama con `send_access_email`, DESPUÉS de este commit.
        """
        TeacherService._assert_operable(db)
        degree = _clean_degree(academic_degree)
        license_ = _clean_license(professional_license)
        pos = TeacherService.position_for(db, department_id)
        app_id, role_id = TeacherService._staff_ids(db)

        user = TeacherService._locked_user(db, user_id)
        if user is None:
            raise ValueError(USER_NOT_FOUND_MSG)
        if user.control_number:
            raise ValueError(STUDENT_ACCOUNT_MSG)
        if not (user.username or "").strip():
            raise ValueError(NO_USERNAME_MSG)
        nuevo_correo = None
        if not (user.email or "").strip():
            if not str(institutional_email or "").strip():
                raise ValueError(EMAIL_REQUIRED_MSG)
            nuevo_correo = TeacherService._clean_email(institutional_email)
            duenos = TeacherService._email_owners(db, nuevo_correo, exclude_id=user.id)
            if duenos:
                raise EmailTakenError(EMAIL_TAKEN_MSG,
                                      TeacherService._candidate_dicts(db, duenos))
        links = TeacherService._locked_links(db, user.id, pos.id)
        if any(_vigente_today(link) for link in links):
            raise ValueError(ALREADY_TEACHER_MSG)

        # --- desde aquí, solo escrituras (nada que valide puede lanzar) ---
        uid = user.id
        reactivada = not user.is_active
        restablecer = reactivada or user.last_login is None
        with _writing(db):
            if reactivada:
                user.is_active = True
            if restablecer:
                TeacherService._reset_credentials(db, user)
            if nuevo_correo:
                user.email = nuevo_correo
            staff_nuevo = TeacherService._ensure_staff_role(db, user.id, app_id, role_id)
            TeacherService._open_position(db, user.id, pos.id, links)
            perfil_nuevo, before, after = TeacherService._upsert_profile(
                db, user.id, actor_id, degree, license_)
            AuditService.record(
                db, "teacher.added",
                entity_type="user", entity_id=user.id, subject=user.full_name,
                before=before, after=after,
                payload={
                    "department_id": department_id,
                    "position_id": pos.id,
                    "account_reactivated": reactivada,
                    "credential_reset": restablecer,
                    "forced_change_on_login": restablecer,
                    "email_written": bool(nuevo_correo),
                    "staff_role_granted": staff_nuevo,
                    "profile_created": perfil_nuevo,
                },
                actor_id=actor_id,
            )
            db.commit()
        TeacherService._after_commit(uid, credentials_reset=restablecer)
        logger.info("Docentes: actor %s agregó al usuario %s al departamento %s "
                    "(reactivada=%s, restablecida=%s)",
                    actor_id, uid, department_id, reactivada, restablecer)
        return {"user_id": uid, "access_email_needed": restablecer}

    @staticmethod
    def create_and_add(db: Session, actor_id: int, department_id: int, *, first_name,
                       last_name, middle_name, email, academic_degree, professional_license,
                       confirm_other_person: bool = False) -> dict:
        """Crea la cuenta de un docente que NO existe y lo hace docente del depto.

        Correo institucional obligatorio con dominio permitido; si ya es de otra
        cuenta -> `EmailTakenError` (D3). `username` = parte local del correo; si
        ya existe (sin distinguir mayúsculas) -> `ValueError` claro, sin
        inventar sufijos. Si hay cuentas de personal con el mismo nombre y
        apellido paterno y no se confirmó «Es otra persona» -> `NameMatchError`
        con los candidatos. La cuenta nace activa con `DEFAULT_PASSWORD` y
        cambio obligatorio, rol `staff` (global y en `itcj`), puesto y perfil.
        Devuelve `{"user_id", "access_email_needed": True}`.
        """
        from itcj2.core.models.user import User
        from itcj2.core.utils.security import DEFAULT_PASSWORD, hash_nip

        TeacherService._assert_operable(db)
        nombre = _clean_name(first_name, FIRST_NAME_MSG, required=True)
        paterno = _clean_name(last_name, LAST_NAME_MSG, required=True)
        materno = _clean_name(middle_name, MIDDLE_NAME_MSG, required=False)
        correo = TeacherService._clean_email(email)
        degree = _clean_degree(academic_degree)
        license_ = _clean_license(professional_license)
        pos = TeacherService.position_for(db, department_id)
        app_id, role_id = TeacherService._staff_ids(db)

        duenos = TeacherService._email_owners(db, correo)
        if duenos:
            raise EmailTakenError(EMAIL_TAKEN_MSG, TeacherService._candidate_dicts(db, duenos))
        usuario = correo.split("@", 1)[0]
        if (db.query(User.id).filter(func.lower(User.username) == usuario).first()
                is not None):
            raise ValueError(USERNAME_TAKEN_MSG.format(usuario=usuario))
        homonimos = (db.query(User)
                     .filter(User.control_number.is_(None),
                             _fold_sql(User.first_name) == _fold(nombre),
                             _fold_sql(User.last_name) == _fold(paterno))
                     .order_by(User.id).limit(10).all())
        if homonimos and not confirm_other_person:
            raise NameMatchError(NAME_MATCH_MSG, TeacherService._candidate_dicts(db, homonimos))

        # --- desde aquí, solo escrituras ---
        user = User(first_name=nombre, last_name=paterno, middle_name=materno,
                    email=correo, username=usuario, control_number=None,
                    role_id=role_id, password_hash=hash_nip(DEFAULT_PASSWORD),
                    must_change_password=True, is_active=True)
        db.add(user)
        try:
            db.flush()          # el id; el mismo usuario dado de alta a la vez truena aquí
        except IntegrityError:
            db.rollback()
            raise ValueError(USERNAME_TAKEN_MSG.format(usuario=usuario))
        uid = user.id
        with _writing(db):
            TeacherService._ensure_staff_role(db, uid, app_id, role_id)
            TeacherService._open_position(db, uid, pos.id, [])
            TeacherService._upsert_profile(db, uid, actor_id, degree, license_)
            AuditService.record(
                db, "teacher.created",
                entity_type="user", entity_id=uid, subject=user.full_name,
                after={"academic_degree": degree, "professional_license": license_},
                payload={
                    "department_id": department_id,
                    "position_id": pos.id,
                    "username": usuario,
                    "email": correo,
                    "temporary_credential": True,
                    "forced_change_on_login": True,
                    "confirmed_other_person": bool(confirm_other_person and homonimos),
                    "name_matches": [h.id for h in homonimos],
                },
                actor_id=actor_id,
            )
            db.commit()
        TeacherService._after_commit(uid, credentials_reset=False)
        logger.info("Docentes: actor %s creó la cuenta %s (docente del departamento %s)",
                    actor_id, uid, department_id)
        return {"user_id": uid, "access_email_needed": True}

    @staticmethod
    def update_profile(db: Session, actor_id: int, user_id: int, *, academic_degree,
                       professional_license) -> None:
        """Corrige grado y cédula del perfil ÚNICO (se ve en todos sus deptos).
        Sin cambios, no escribe nada."""
        from itcj2.apps.titulatec.models import TeacherProfile
        from itcj2.core.models.user import User

        TeacherService._assert_operable(db)
        degree = _clean_degree(academic_degree)
        license_ = _clean_license(professional_license)
        if db.get(TeacherProfile, user_id) is None:
            raise ValueError(NO_PROFILE_MSG)
        with _writing(db):
            _, before, after = TeacherService._upsert_profile(
                db, user_id, actor_id, degree, license_)
            if not after:
                return
            user = db.get(User, user_id)
            AuditService.record(
                db, "teacher.profile_updated",
                entity_type="user", entity_id=user_id,
                subject=user.full_name if user is not None else None,
                before=before, after=after, actor_id=actor_id,
            )
            db.commit()

    @staticmethod
    def remove_from_department(db: Session, actor_id: int, department_id: int,
                               user_id: int) -> None:
        """Termina el puesto `docente_{depto}` de la persona (nunca borra la
        cuenta, el perfil ni su rol `staff`).

        RF2: se bloquea mientras tenga asignaciones de sinodal vigentes en
        procesos vivos de carreras de ese departamento. El puesto se bloquea
        (`FOR UPDATE`) ANTES de contar: quien asigna con
        `is_teacher_of(..., lock=True)` espera o deja de verlo docente.
        """
        from itcj2.apps.titulatec.models import (
            ProgramDepartment, SynodalAssignment, TitulationProcess,
        )
        from itcj2.core.models.user import User
        from itcj2.core.utils.timezone import db_now

        TeacherService._assert_operable(db)
        pos = TeacherService.position_for(db, department_id)
        links = TeacherService._locked_links(db, user_id, pos.id)
        if not any(_vigente_today(link) for link in links):
            raise ValueError(NOT_TEACHER_MSG)
        vigentes = (db.query(func.count(SynodalAssignment.id))
                    .join(TitulationProcess,
                          TitulationProcess.id == SynodalAssignment.process_id)
                    .join(ProgramDepartment,
                          ProgramDepartment.program_id == TitulationProcess.program_id)
                    .filter(SynodalAssignment.user_id == user_id,
                            SynodalAssignment.is_active.is_(True),
                            TitulationProcess.status.in_(LIVE_PROCESS_STATUSES),
                            ProgramDepartment.department_id == department_id)
                    .scalar())
        if vigentes:
            raise ValueError(HAS_ASSIGNMENTS_MSG)

        hoy = db_now().date()
        with _writing(db):
            for link in links:
                link.is_active = False
                if link.end_date is None or link.end_date > hoy:
                    link.end_date = hoy
            user = db.get(User, user_id)
            AuditService.record(
                db, "teacher.removed",
                entity_type="user", entity_id=user_id,
                subject=user.full_name if user is not None else None,
                payload={"department_id": department_id, "position_id": pos.id},
                actor_id=actor_id,
            )
            db.commit()
        TeacherService._after_commit(user_id, credentials_reset=False)
        logger.info("Docentes: actor %s quitó al usuario %s del departamento %s",
                    actor_id, user_id, department_id)

    @staticmethod
    def reset_access(db: Session, actor_id: int, user_id: int) -> None:
        """«Reenviar acceso»: SOLO a una cuenta activa que nunca ha iniciado
        sesión y que es docente de algún departamento. Restablece
        `DEFAULT_PASSWORD` con cambio obligatorio (no reactiva: una cuenta
        desactivada la reactiva un administrador). El correo lo manda quien
        llama con `send_access_email`, después de este commit."""
        TeacherService._assert_operable(db)
        user = TeacherService._locked_user(db, user_id)
        if user is None:
            raise ValueError(USER_NOT_FOUND_MSG)
        if user.control_number:
            raise ValueError(STUDENT_ACCOUNT_MSG)
        if not user.is_active:
            raise ValueError(RESET_INACTIVE_MSG)
        if user.last_login is not None:
            raise ValueError(RESET_NOT_ALLOWED_MSG)
        if not TeacherService._teacher_departments(db, [user.id])[user.id]:
            raise ValueError(NOT_TEACHER_ANY_MSG)
        uid = user.id
        with _writing(db):
            TeacherService._reset_credentials(db, user)
            AuditService.record(
                db, "teacher.access_reset",
                entity_type="user", entity_id=uid, subject=user.full_name,
                payload={"credential_reset": True, "forced_change_on_login": True},
                actor_id=actor_id,
            )
            db.commit()
        TeacherService._after_commit(uid, credentials_reset=True)
        logger.info("Docentes: actor %s restableció el acceso del usuario %s", actor_id, uid)

    # ------------------------------------------------------------------
    # Correo de acceso
    # ------------------------------------------------------------------
    @staticmethod
    def send_access_email(user_id: int) -> tuple[bool, str | None]:
        """Correo de acceso (usuario + contraseña temporal + liga) al correo de
        la cuenta. Abre su PROPIA sesión: se llama DESPUÉS del commit del alta o
        del restablecimiento. Best-effort: nunca lanza ni deshace nada.

        Solo sale si la cuenta está activa y su contraseña SIGUE siendo la
        temporal con cambio obligatorio (si la persona ya la cambió, el correo
        mentiría). `(True, None)` si salió; si no, `(False, motivo)`: los de
        `email_helper.deliver_detailed` o `inerte`, `sin_cuenta`,
        `cuenta_inactiva`, `sin_usuario`, `sin_credencial_temporal`, `error`.
        La contraseña solo viaja en el cuerpo del correo: nunca al log.
        """
        from itcj2.apps.titulatec.services import email_helper

        try:
            from itcj2.core.models.user import User
            from itcj2.core.utils.security import DEFAULT_PASSWORD, is_default_password_hash
            from itcj2.database import SessionLocal

            db = SessionLocal()
            try:
                if not TeacherService.operable(db):
                    return False, "inerte"
                user = db.get(User, user_id)
                if user is None:
                    return False, "sin_cuenta"
                if not user.is_active:
                    return False, "cuenta_inactiva"
                if not (user.username or "").strip():
                    return False, "sin_usuario"
                if not (user.must_change_password and user.password_hash
                        and is_default_password_hash(user.password_hash)):
                    return False, "sin_credencial_temporal"
                destino = (user.email or "").strip() or None
                contexto = {
                    "nombre": " ".join(p for p in (user.first_name, user.last_name,
                                                   user.middle_name) if p),
                    "usuario": user.username,
                    "contrasena": DEFAULT_PASSWORD,
                    "login_url": f"{email_helper.PUBLIC_ORIGIN}/itcj/login",
                }
            finally:
                db.close()
            ok, motivo = email_helper.deliver_detailed(
                template=ACCESS_TEMPLATE, context=contexto, subject=ACCESS_SUBJECT,
                to=destino, que="teacher_access")
        except Exception:
            logger.exception("Docentes: error inesperado al enviar el acceso del usuario %s",
                             user_id)
            return False, "error"
        if ok:
            logger.info("Docentes: correo de acceso enviado al usuario %s", user_id)
        else:
            logger.warning("Docentes: no salió el correo de acceso del usuario %s (%s)",
                           user_id, motivo)
        return ok, motivo
