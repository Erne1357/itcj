"""Asignación de sinodales (fase 4): la ÚNICA puerta que mueve la fase 4.

Spec 2026-10-21-titulatec-fase4-sinodales §10 (motor), §11 (avisos) y §16b R-D
(quién opera qué departamento). El departamento académico de la carrera
registra a los 4 sinodales de un egresado en fase 4 y, en la MISMA
transacción, el motor aprueba la fase 4 y el proceso pasa a la 5 (D6). Del lado
del motor, `approve_phase`/`reject_phase` de la fase `synodal_assignment`
exigen la marca que abre `assign` (`PhaseService.open_door`); sin ella dan
`PhaseService.SYNODAL_ONLY_MSG`. La fase 4 no tiene rechazo.

Reglas que este servicio garantiza (las rutas solo deciden quién y qué proceso):

- **Candado + relectura** (patrón de `FormatBService._lock`): las
  verificaciones corren primero SIN candado sobre lo cargado (lo común falla
  barato y sin deshacer nada) y se REPITEN bajo el bloqueo del proceso sobre lo
  releído. Desde el candado hasta el commit, cualquier error hace
  `db.rollback()` antes de re-lanzar. Jefe y coordinador asignando el mismo
  proceso a la vez: el segundo recibe «ya tiene sinodales» sin escribir (RF3).
- **Alcance (R-D)**: `can_operate`. La carrera se mapea a su departamento al
  vuelo: remapearla mueve quién la opera (RF4).
- **Los 4**: personas distintas, docentes VIGENTES del departamento de la
  carrera (bajo el candado con `TeacherService.is_teacher_of(lock=True)`, que
  serializa con quitar al docente del catálogo, RF2) y con perfil completo
  (grado y cédula), sin sinodales vigentes todavía. Ninguna otra regla (D9).
- **Sustituir** (D8) solo con la fase 4 aprobada, la 5 sin aprobar y el proceso
  `active`, con motivo. La fila vieja queda `is_active = false` con
  `replaced_at`, `replaced_by_id` (QUIÉN sustituyó, como `assigned_by_id`) y
  `replacement_reason`: es el historial (`history`).
- **Avisos** (§11): aviso in-app y correo a cada sinodal DESPUÉS del commit,
  con sesión propia y best-effort (`send_assignment_notices`); una falla queda
  en el log y en la bitácora (`synodal.mail_failed`) y nunca revierte nada.
- **R-G**: con el corte a T-soft en la fase 4 o antes no se asigna, no se
  sustituye y no sale ningún aviso (`INERT_MSG`).
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from itcj2.core.utils.timezone import db_now

logger = logging.getLogger(__name__)

PHASE_CODE = "synodal_assignment"           # fase 4 del catálogo
REVIEW_PHASE_CODE = "synodal_review"        # fase 5: mientras no se apruebe, se sustituye

# Orden del oficio y de toda lista (D1).
ROLES = ("president", "secretary", "vocal", "alternate")
ROLE_LABELS = {
    "president": "Presidente",
    "secretary": "Secretario",
    "vocal": "Vocal",
    "alternate": "Vocal Suplente",
}

# Avisos a los sinodales (§11): `kind` -> (tipo de la notificación, título, asunto).
NOTICE_KINDS = ("assigned", "replaced_in", "replaced_out")
_NOTICES = {
    "assigned": ("SYNODAL_ASSIGNED", "Te asignaron como sinodal",
                 "[TitulaTec ITCJ] Asignación como sinodal"),
    "replaced_in": ("SYNODAL_ASSIGNED", "Te asignaron como sinodal (sustitución)",
                    "[TitulaTec ITCJ] Asignación como sinodal"),
    "replaced_out": ("SYNODAL_RELEASED", "Ya no eres sinodal de un proceso",
                     "[TitulaTec ITCJ] Sustitución como sinodal"),
}
NOTICE_TEMPLATE = "synodal_assigned.html"   # relativa a `titulatec/email/`
_NOTICE_PATH = "/titulatec/"                # el landing resuelve la vista por rol
_REVIEWS_PATH = "/titulatec/admin/revisiones"   # «Mis revisiones» (fase 5)

_MAX_REASON = 500

# --- Mensajes (español, para `X-Tt-Error` vía `_hdr`) ------------------------
INERT_MSG = ("La asignación de sinodales todavía no se opera en esta app "
             "(sigue fuera de la plataforma).")
NO_PHASE_MSG = "El catálogo no tiene la fase de asignación de sinodales."
NOT_MAPPED_MSG = ("La carrera del proceso no tiene departamento académico: "
                  "corrígelo en «Carreras por departamento».")
OUT_OF_SCOPE_MSG = "La carrera de este proceso no es de tu departamento académico."
MISSING_MSG = "Elige a los 4 sinodales: Presidente, Secretario, Vocal y Vocal Suplente."
REPEATED_MSG = "Los 4 sinodales deben ser personas distintas."
NOT_TEACHER_MSG = "{posicion}: {nombre} no es docente vigente del departamento de la carrera."
NO_PROFILE_MSG = ("{posicion}: {nombre} no tiene grado académico y cédula registrados; "
                  "complétalos en «Docentes».")
INACTIVE_TEACHER_MSG = ("{posicion}: la cuenta de {nombre} está desactivada; elige a otra "
                        "persona o pide a un administrador que la reactive.")
ALREADY_ASSIGNED_MSG = "Este proceso ya tiene sinodales asignados."
ROLE_MSG = "Posición de sinodal no reconocida."
NEW_USER_MSG = "Elige al docente que entra."
REASON_MSG = "Escribe el motivo de la sustitución (hasta 500 caracteres)."
REPLACE_WINDOW_MSG = ("Solo se sustituye a un sinodal con la fase 04 aprobada y la "
                      "revisión de sinodales sin terminar.")
NOT_ACTIVE_MSG = "El proceso ya no admite cambios (estado: {estado})."
NO_HOLDER_MSG = "Nadie ocupa la posición de {posicion}: no hay a quién sustituir."
SAME_PERSON_MSG = "{nombre} ya ocupa la posición de {posicion}: elige a otra persona."
IN_OTHER_ROLE_MSG = "{nombre} ya es sinodal de este proceso como {posicion}."
CONFLICT_MSG = ("Alguien más cambió a los sinodales de este proceso al mismo tiempo. "
                "Intenta de nuevo.")
_SOMEONE = "la persona elegida"

# Qué decir cuando un proceso no tiene sinodales vigentes (expediente y pestaña
# Titulación, hallazgo 8): «no aplica» si la modalidad salta la fase 4 (EGEL),
# «no está en la app» con el corte a T-soft en ella o antes, y si no, pendiente.
NOT_APPLICABLE_LABEL = "No aplica para esta modalidad."
NOT_IN_APP_LABEL = "Esta fase todavía no está en la app."
PENDING_LABEL = "Todavía no se asignan los sinodales."


def _name(user) -> str:
    """Nombre en orden natural (nombre(s), paterno, materno), como el oficio."""
    if user is None:
        return ""
    return " ".join(p for p in (user.first_name, user.last_name, user.middle_name) if p)


def _clean(raw) -> str:
    """strip() + colapsar espacios internos."""
    return " ".join(str(raw or "").split())


def _pairs(asignados: dict) -> list[dict]:
    """`{posición: user_id}` -> `[{"role", "user_id"}]` en el orden del oficio.

    Así viaja la posición en el evento y en la bitácora: como VALOR, nunca como
    llave. La bitácora enmascara toda llave que contenga «secret» (D9,
    `audit_actions.SENSITIVE_KEY_PARTS`), y `{"secretary": 12}` saldría
    `{"secretary": "***"}` en el espejo del evento y en `synodal.assigned`.
    """
    return [{"role": role, "user_id": asignados[role]} for role in ROLES if role in asignados]


def _to_id(raw) -> int | None:
    """Id de usuario de un formulario o de código; None si no es un entero > 0."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        valor = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return valor if valor > 0 else None


class SynodalService:
    """Sinodales de un proceso: asignar, sustituir, leer y avisar."""

    ROLES = ROLES
    ROLE_LABELS = ROLE_LABELS

    # ------------------------------------------------------------------
    # Corte y alcance
    # ------------------------------------------------------------------
    @staticmethod
    def operable(db: Session) -> bool:
        """¿La fase 4 se opera en esta app? (R-G). Falla cerrado: sin la fase en
        el catálogo, o con el corte a T-soft en ella o antes, no."""
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        n = PhaseService.phase_number_for_code(db, PHASE_CODE)
        return n is not None and PhaseService._handoff_phase() > n

    @staticmethod
    def _assert_operable(db: Session) -> None:
        if not SynodalService.operable(db):
            raise ValueError(INERT_MSG)

    @staticmethod
    def _phase_number(db: Session) -> int:
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        n = PhaseService.phase_number_for_code(db, PHASE_CODE)
        if n is None:
            raise ValueError(NO_PHASE_MSG)
        return n

    @staticmethod
    def _operates_department(db: Session, user_id: int, department_id: int) -> bool:
        """R-D: con `process.api.read.all` (admin, jefatura de la DEP) cualquier
        departamento mapeado; si no, solo los de `academic_departments`."""
        from itcj2.apps.titulatec.services.scope_service import (
            READ_ALL, academic_departments,
        )
        from itcj2.core.services.authz_cache import cached_perms

        if READ_ALL in cached_perms(db, user_id, "titulatec"):
            return True
        return department_id in academic_departments(db, user_id)

    @staticmethod
    def _department_of(db: Session, program_id, *, fresh: bool = False) -> int | None:
        """Departamento académico de la carrera. `fresh=True` (bajo el candado)
        lo lee de la BD y no del mapa de identidad: un remapeo que otro
        commiteó mientras tanto cuenta (RF4)."""
        from itcj2.apps.titulatec.models import ProgramDepartment
        from itcj2.apps.titulatec.services.scope_service import department_of_program

        if program_id is None:
            return None
        if not fresh:
            return department_of_program(db, program_id)
        return (db.query(ProgramDepartment.department_id)
                .filter(ProgramDepartment.program_id == program_id).scalar())

    @staticmethod
    def can_operate(db: Session, user_id: int, process) -> bool:
        """¿`user_id` puede asignar o sustituir los sinodales de `process`? (R-D)

        La carrera tiene que estar mapeada a un departamento académico; quien
        tenga `process.api.read.all` opera cualquiera, los demás solo las de los
        departamentos que dirigen o coordinan (`academic_departments`). El
        permiso de la ACCIÓN lo exige la ruta. Se calcula al vuelo: remapear la
        carrera cambia quién la opera (RF4).
        """
        if process is None:
            return False
        dept = SynodalService._department_of(db, process.program_id)
        return dept is not None and SynodalService._operates_department(db, user_id, dept)

    @staticmethod
    def _department(db: Session, process, actor_id: int, *, fresh: bool) -> int:
        """El departamento de la carrera del proceso, con el alcance del actor."""
        dept = SynodalService._department_of(db, process.program_id, fresh=fresh)
        if dept is None:
            raise ValueError(NOT_MAPPED_MSG)
        if not SynodalService._operates_department(db, actor_id, dept):
            raise ValueError(OUT_OF_SCOPE_MSG)
        return dept

    # ------------------------------------------------------------------
    # Lo cargado y lo releído
    # ------------------------------------------------------------------
    @staticmethod
    def _loaded_active(process) -> list:
        """Sinodales vigentes TAL COMO se cargaron con el proceso (sin candado)."""
        return [a for a in process.synodal_assignments if a.is_active]

    @staticmethod
    def _fresh_active(db: Session, process_id: int) -> list:
        """Sinodales vigentes releídos de la BD (bajo el candado)."""
        from itcj2.apps.titulatec.models import SynodalAssignment

        return (db.query(SynodalAssignment)
                .filter(SynodalAssignment.process_id == process_id,
                        SynodalAssignment.is_active.is_(True))
                .order_by(SynodalAssignment.id)
                .populate_existing()
                .all())

    @staticmethod
    def _users(db: Session, user_ids) -> dict:
        from itcj2.core.models.user import User

        ids = sorted({int(u) for u in user_ids if u is not None})
        if not ids:
            return {}
        return {u.id: u for u in db.query(User).filter(User.id.in_(ids)).all()}

    @staticmethod
    def _assert_teachers(db: Session, elegidos: dict, dept: int, users: dict, *,
                         locked: bool) -> None:
        """Cada `{posición: user_id}` es docente vigente del departamento, con la
        cuenta ACTIVA (un sinodal entra a la app en la fase 5; hallazgo 3) y
        perfil completo (grado y cédula no vacíos)."""
        from itcj2.apps.titulatec.models import TeacherProfile
        from itcj2.apps.titulatec.services.teacher_service import TeacherService
        from itcj2.core.models.user import User

        for role, uid in elegidos.items():
            if not TeacherService.is_teacher_of(db, uid, dept, lock=locked):
                raise ValueError(NOT_TEACHER_MSG.format(
                    posicion=ROLE_LABELS[role], nombre=_name(users.get(uid)) or _SOMEONE))
        # Columnas, no entidades: siempre lo que hay en la BD (bajo el candado
        # también), aunque la identidad cargada traiga un `is_active` viejo.
        activos = {uid for (uid,) in db.query(User.id).filter(
            User.id.in_(list(elegidos.values())), User.is_active.is_(True)).all()}
        for role, uid in elegidos.items():
            if uid not in activos:
                raise ValueError(INACTIVE_TEACHER_MSG.format(
                    posicion=ROLE_LABELS[role], nombre=_name(users.get(uid)) or _SOMEONE))
        q = db.query(TeacherProfile).filter(TeacherProfile.user_id.in_(list(elegidos.values())))
        if locked:
            q = q.populate_existing()
        perfiles = {p.user_id: p for p in q.all()}
        for role, uid in elegidos.items():
            perfil = perfiles.get(uid)
            completo = (perfil is not None and _clean(perfil.academic_degree)
                        and _clean(perfil.professional_license))
            if not completo:
                raise ValueError(NO_PROFILE_MSG.format(
                    posicion=ROLE_LABELS[role], nombre=_name(users.get(uid)) or _SOMEONE))

    @staticmethod
    def _already_assigned_msg(db: Session, vigentes) -> str:
        """«ya tiene sinodales» + quién y cuándo los registró, si se sabe."""
        from itcj2.apps.titulatec.utils.dates_es import dia_mes_hora

        primera = min(vigentes, key=lambda a: a.id)
        quien = _name(SynodalService._users(db, [primera.assigned_by_id])
                      .get(primera.assigned_by_id))
        detalle = " por " + quien if quien else ""
        if primera.created_at:
            detalle += " el " + dia_mes_hora(primera.created_at)
        if not detalle:
            return ALREADY_ASSIGNED_MSG
        return f"{ALREADY_ASSIGNED_MSG.rstrip('.')}: los registró{detalle}."

    # ------------------------------------------------------------------
    # Asignar los 4 (aprueba la fase 4)
    # ------------------------------------------------------------------
    @staticmethod
    def _check_assign(db: Session, process, actor_id: int, elegidos: dict, n: int, *,
                      locked: bool) -> None:
        """Todas las verificaciones de `assign`, sin escribir. Corre DOS veces:
        sin candado sobre lo cargado y bajo el candado sobre lo releído.

        «Ya tiene sinodales» va ANTES de la guarda del motor: quien llegó
        segundo encuentra la fase ya movida, y el motivo útil es el primero.
        """
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        dept = SynodalService._department(db, process, actor_id, fresh=locked)
        vigentes = (SynodalService._fresh_active(db, process.id) if locked
                    else SynodalService._loaded_active(process))
        if vigentes:
            raise ValueError(SynodalService._already_assigned_msg(db, vigentes))
        PhaseService.assert_can_transition(db, process, n)
        users = SynodalService._users(db, elegidos.values())
        SynodalService._assert_teachers(db, elegidos, dept, users, locked=locked)

    @staticmethod
    def assign(db: Session, process, actor_id: int, *, president_id, secretary_id,
               vocal_id, alternate_id) -> dict:
        """Registra a los 4 sinodales y aprueba la fase 4 en UNA transacción.

        `process` tiene que ser un objeto de ESTA sesión (el candado lo relee
        con `populate_existing`). Los ids pueden llegar como texto del
        formulario. Crea las 4 filas vigentes, el evento `synodals_assigned`
        (`{"synodals": [{"role", "user_id"}]}`, ver `_pairs`) y la bitácora
        `synodal.assigned`; abre la conversación de la revisión
        (`ReviewService.open_chat`, fase 5), la puerta del motor y `approve_phase` aprueba
        la fase 4, activa la 5, avisa al alumno, le encola el correo «Avanzaste
        a …» y commitea. Ya commiteado, avisa a los 4
        (`send_assignment_notices`, best-effort).

        Devuelve lo de `approve_phase` más `synodals` = `{posición: user_id}`.
        `ValueError` con el motivo (ver los `*_MSG`) sin escribir nada.
        """
        from itcj2.apps.titulatec.models import SynodalAssignment
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        elegidos = {"president": _to_id(president_id), "secretary": _to_id(secretary_id),
                    "vocal": _to_id(vocal_id), "alternate": _to_id(alternate_id)}
        if any(uid is None for uid in elegidos.values()):
            raise ValueError(MISSING_MSG)
        if len(set(elegidos.values())) != len(ROLES):
            raise ValueError(REPEATED_MSG)
        SynodalService._assert_operable(db)
        n = SynodalService._phase_number(db)

        SynodalService._check_assign(db, process, actor_id, elegidos, n, locked=False)
        try:
            PhaseService._lock_process_row(db, process)
            SynodalService._check_assign(db, process, actor_id, elegidos, n, locked=True)
            ahora = db_now()
            for role in ROLES:
                db.add(SynodalAssignment(process=process, user_id=elegidos[role], role=role,
                                         assigned_by_id=actor_id, created_at=ahora,
                                         is_active=True))
            asignados = {role: elegidos[role] for role in ROLES}
            PhaseService._log(db, process.id, actor_id, "synodals_assigned", n,
                              {"synodals": _pairs(asignados)})
            AuditService.record(
                db, "synodal.assigned",
                entity_type="process", entity_id=process.id,
                process_id=process.id, subject=process.folio,
                payload={"phase_number": n, "synodals": _pairs(asignados)},
                actor_id=actor_id,
            )
            db.flush()
            # Fase 5 (spec 2026-10-22 §6.2): la conversación de revisión nace aquí,
            # en esta misma transacción (si la aprobación falla, se revierte).
            from itcj2.apps.titulatec.services.review_service import ReviewService
            # Con el corte a T-soft en la fase 5 o antes la revisión no es de la app.
            if ReviewService.operable(db):
                ReviewService.open_chat(db, process)
            PhaseService.open_door(db, PHASE_CODE, process.id, "approved")
            resultado = PhaseService.approve_phase(db, process, n, actor_id)
        except IntegrityError:
            db.rollback()
            raise ValueError(CONFLICT_MSG) from None
        except Exception:
            db.rollback()
            raise
        finally:
            PhaseService.close_door(db)
        SynodalService.send_assignment_notices(process.id, list(asignados.values()),
                                               kind="assigned")
        return {**resultado, "synodals": asignados}

    # ------------------------------------------------------------------
    # Sustituir a uno (D8)
    # ------------------------------------------------------------------
    @staticmethod
    def _check_replace(db: Session, process, actor_id: int, role: str, nuevo: int,
                       n4: int, n5: int | None, *, locked: bool):
        """Verificaciones de `replace`, sin escribir; devuelve `(fila saliente,
        usuarios)`. Corre sin candado y otra vez bajo el candado."""
        from itcj2.apps.titulatec.models import ProcessPhase

        if process.status != "active":
            raise ValueError(NOT_ACTIVE_MSG.format(estado=process.status))
        # Columnas, no entidades: siempre lo que hay en la BD.
        estados = dict(db.query(ProcessPhase.phase_number, ProcessPhase.status)
                       .filter(ProcessPhase.process_id == process.id,
                               ProcessPhase.phase_number.in_([n4, n5]))
                       .all()) if n5 is not None else {}
        if n5 is None or estados.get(n4) != "approved" or estados.get(n5) == "approved":
            raise ValueError(REPLACE_WINDOW_MSG)
        dept = SynodalService._department(db, process, actor_id, fresh=locked)
        vigentes = (SynodalService._fresh_active(db, process.id) if locked
                    else SynodalService._loaded_active(process))
        users = SynodalService._users(db, [nuevo] + [a.user_id for a in vigentes])
        saliente = next((a for a in vigentes if a.role == role), None)
        if saliente is None:
            raise ValueError(NO_HOLDER_MSG.format(posicion=ROLE_LABELS[role]))
        nombre = _name(users.get(nuevo)) or _SOMEONE
        if saliente.user_id == nuevo:
            raise ValueError(SAME_PERSON_MSG.format(nombre=nombre, posicion=ROLE_LABELS[role]))
        otra = next((a for a in vigentes if a.user_id == nuevo), None)
        if otra is not None:
            raise ValueError(IN_OTHER_ROLE_MSG.format(
                nombre=nombre, posicion=ROLE_LABELS.get(otra.role, otra.role)))
        SynodalService._assert_teachers(db, {role: nuevo}, dept, users, locked=locked)
        return saliente, users

    @staticmethod
    def replace(db: Session, process, actor_id: int, *, role, new_user_id, reason) -> None:
        """Sustituye al sinodal vigente de `role` por `new_user_id`, con motivo.

        Solo con la fase 4 aprobada, la 5 sin aprobar y el proceso `active`;
        mismas reglas de alcance, docente vigente y perfil que al asignar, y el
        nuevo no puede ser ya sinodal vigente del proceso. Bajo el candado
        desactiva la fila vigente (`replaced_*`) y crea la nueva; evento
        `synodal_replaced`, bitácora `synodal.replaced`, aviso in-app al
        alumno y el mensaje de la sustitución en la conversación de revisión
        (`ReviewService.on_replaced`), todo en una transacción. Ya commiteado avisa al entrante
        (`replaced_in`) y al saliente (`replaced_out`, pierde el acceso).
        """
        from itcj2.apps.titulatec.models import SynodalAssignment
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.notify import notify_student
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        if role not in ROLES:
            raise ValueError(ROLE_MSG)
        motivo = _clean(reason)
        if not motivo or len(motivo) > _MAX_REASON:
            raise ValueError(REASON_MSG)
        nuevo = _to_id(new_user_id)
        if nuevo is None:
            raise ValueError(NEW_USER_MSG)
        SynodalService._assert_operable(db)
        n4 = SynodalService._phase_number(db)
        n5 = PhaseService.phase_number_for_code(db, REVIEW_PHASE_CODE)

        SynodalService._check_replace(db, process, actor_id, role, nuevo, n4, n5, locked=False)
        try:
            PhaseService._lock_process_row(db, process)
            saliente, users = SynodalService._check_replace(db, process, actor_id, role,
                                                            nuevo, n4, n5, locked=True)
            anterior = saliente.user_id
            ahora = db_now()
            saliente.is_active = False
            saliente.replaced_at = ahora
            saliente.replaced_by_id = actor_id
            saliente.replacement_reason = motivo
            db.flush()          # libera los índices únicos parciales antes de la nueva
            db.add(SynodalAssignment(process=process, user_id=nuevo, role=role,
                                     assigned_by_id=actor_id, created_at=ahora,
                                     is_active=True))
            PhaseService._log(db, process.id, actor_id, "synodal_replaced", n4,
                              {"role": role, "previous_user_id": anterior,
                               "user_id": nuevo, "reason": motivo})
            AuditService.record(
                db, "synodal.replaced",
                entity_type="process", entity_id=process.id,
                process_id=process.id, subject=process.folio, reason=motivo,
                before={"user_id": anterior}, after={"user_id": nuevo},
                payload={"role": role},
                actor_id=actor_id,
            )
            notify_student(
                db, process.student_id, type="SYNODAL_REPLACED",
                title="Cambió uno de tus sinodales",
                body=(f"{ROLE_LABELS[role]}: tu departamento académico sustituyó a "
                      f"{_name(users.get(anterior)) or 'tu sinodal'} por "
                      f"{_name(users.get(nuevo)) or 'otro docente'}."),
                process_id=process.id, phase_number=process.current_phase)
            # Fase 5 (spec 2026-10-22 §6.3): «X sustituye a Y como …» en la
            # conversación, si ya existe. El voto de la fila desactivada deja de
            # contar solo (cuentan las asignaciones vigentes).
            from itcj2.apps.titulatec.services.review_service import ReviewService
            ReviewService.on_replaced(db, process, role=role, old_user_id=anterior,
                                      new_user_id=nuevo)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise ValueError(CONFLICT_MSG) from None
        except Exception:
            db.rollback()
            raise
        SynodalService.send_assignment_notices(process.id, [nuevo], kind="replaced_in")
        SynodalService.send_assignment_notices(process.id, [anterior], kind="replaced_out")

    # ------------------------------------------------------------------
    # Lecturas (bandeja, oficio, expediente, alumno)
    # ------------------------------------------------------------------
    @staticmethod
    def empty_label(db: Session, process) -> str:
        """Leyenda para un proceso SIN sinodales vigentes (hallazgo 8).

        - La modalidad salta la fase 4 (`skips_phases`, p. ej. EGEL) o su
          `ProcessPhase` ya está `skipped` → `NOT_APPLICABLE_LABEL`. Gana sobre
          el corte: es un hecho de la modalidad.
        - La fase 4 no se opera en esta app (corte a T-soft en ella o antes, o
          sin la fase en el catálogo) → `NOT_IN_APP_LABEL`.
        - Si no, `PENDING_LABEL`.
        Dos consultas a lo más (número de fase y estado de su `ProcessPhase`).
        """
        from itcj2.apps.titulatec.models import ProcessPhase
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        n = PhaseService.phase_number_for_code(db, PHASE_CODE)
        if n is not None and process is not None:
            if n in PhaseService._skips(process):
                return NOT_APPLICABLE_LABEL
            estado = (db.query(ProcessPhase.status)
                      .filter(ProcessPhase.process_id == process.id,
                              ProcessPhase.phase_number == n).scalar())
            if estado == "skipped":
                return NOT_APPLICABLE_LABEL
        if n is None or PhaseService._handoff_phase() <= n:
            return NOT_IN_APP_LABEL
        return PENDING_LABEL

    @staticmethod
    def active_for_process(db: Session, process_id: int) -> list[dict]:
        """Los sinodales vigentes en el orden Presidente, Secretario, Vocal y
        Vocal Suplente: `role, role_label, user_id, name, academic_degree,
        professional_license, assigned_at` (grado y cédula del perfil VIGENTE:
        si se corrige, el oficio sale corregido). Una consulta."""
        from itcj2.apps.titulatec.models import SynodalAssignment, TeacherProfile
        from itcj2.core.models.user import User

        filas = (db.query(SynodalAssignment.role, SynodalAssignment.user_id,
                          SynodalAssignment.created_at, User.first_name, User.last_name,
                          User.middle_name, TeacherProfile.academic_degree,
                          TeacherProfile.professional_license)
                 .join(User, User.id == SynodalAssignment.user_id)
                 .outerjoin(TeacherProfile, TeacherProfile.user_id == SynodalAssignment.user_id)
                 .filter(SynodalAssignment.process_id == process_id,
                         SynodalAssignment.is_active.is_(True))
                 .all())
        orden = {r: i for i, r in enumerate(ROLES)}
        filas = sorted(filas, key=lambda f: (orden.get(f.role, len(ROLES)), f.user_id))
        return [{
            "role": f.role,
            "role_label": ROLE_LABELS.get(f.role, f.role),
            "user_id": f.user_id,
            "name": " ".join(p for p in (f.first_name, f.last_name, f.middle_name) if p),
            "academic_degree": f.academic_degree,
            "professional_license": f.professional_license,
            "assigned_at": f.created_at,
        } for f in filas]

    @staticmethod
    def history(db: Session, process_id: int) -> list[dict]:
        """Las sustituciones, de la más vieja a la más nueva: `role, role_label,
        user_id, name` (quien salió), `assigned_at`, `replaced_at`,
        `replaced_by_id`, `replaced_by_name` (quién lo sustituyó), `reason`,
        `replacement_user_id`, `replacement_name` (quien entró: la siguiente
        fila de esa posición). Dos consultas."""
        from itcj2.apps.titulatec.models import SynodalAssignment

        filas = (db.query(SynodalAssignment.id, SynodalAssignment.role,
                          SynodalAssignment.user_id, SynodalAssignment.is_active,
                          SynodalAssignment.created_at, SynodalAssignment.replaced_at,
                          SynodalAssignment.replaced_by_id,
                          SynodalAssignment.replacement_reason)
                 .filter(SynodalAssignment.process_id == process_id)
                 .order_by(SynodalAssignment.id)
                 .all())
        sustituidas = [f for f in filas if not f.is_active]
        if not sustituidas:
            return []
        users = SynodalService._users(
            db, {f.user_id for f in filas} | {f.replaced_by_id for f in sustituidas})
        salida = []
        for f in sustituidas:
            sucesora = next((s for s in filas if s.role == f.role and s.id > f.id), None)
            salida.append({
                "role": f.role,
                "role_label": ROLE_LABELS.get(f.role, f.role),
                "user_id": f.user_id,
                "name": _name(users.get(f.user_id)),
                "assigned_at": f.created_at,
                "replaced_at": f.replaced_at,
                "replaced_by_id": f.replaced_by_id,
                "replaced_by_name": _name(users.get(f.replaced_by_id)),
                "reason": f.replacement_reason,
                "replacement_user_id": sucesora.user_id if sucesora else None,
                "replacement_name": _name(users.get(sucesora.user_id)) if sucesora else "",
            })
        salida.sort(key=lambda h: (h["replaced_at"] or datetime.min,))
        return salida

    @staticmethod
    def last_change_at(db: Session, process_id: int) -> datetime | None:
        """Fecha del registro o de la última sustitución (la del oficio); None
        sin sinodales."""
        from itcj2.apps.titulatec.models import SynodalAssignment

        creado, sustituido = (db.query(func.max(SynodalAssignment.created_at),
                                       func.max(SynodalAssignment.replaced_at))
                              .filter(SynodalAssignment.process_id == process_id)
                              .one())
        fechas = [f for f in (creado, sustituido) if f is not None]
        return max(fechas) if fechas else None

    # ------------------------------------------------------------------
    # Avisos (§11): después del commit, best-effort
    # ------------------------------------------------------------------
    @staticmethod
    def _notice_base(db: Session, process) -> dict:
        """Datos del proceso para el aviso y el correo: alumno, control,
        carrera (nombre oficial, R-C), opción (`option_label`, si no el nombre
        de la modalidad) y título del trabajo (Formato B)."""
        from itcj2.apps.titulatec.models import FormatB, Modality, ProgramDepartment
        from itcj2.core.models.program import Program
        from itcj2.core.models.user import User

        alumno = db.get(User, process.student_id)
        carrera = None
        if process.program_id is not None:
            mapeo = db.get(ProgramDepartment, process.program_id)
            programa = db.get(Program, process.program_id)
            carrera = (mapeo.official_name if mapeo and mapeo.official_name
                       else programa.name if programa else None)
        fb = db.get(FormatB, process.id)
        modalidad = db.get(Modality, process.modality_id) if process.modality_id else None
        opcion = ((modalidad.option_label or modalidad.name) if modalidad
                  else (fb.titulation_type if fb else None))
        return {
            "alumno": _name(alumno),
            "control": alumno.control_number if alumno else None,
            "carrera": carrera,
            "opcion": opcion,
            "titulo": fb.project_name if fb else None,
        }

    @staticmethod
    def _roles_for_notice(db: Session, process_id: int, user_ids, kind: str) -> dict:
        """`{user_id: posición}`: la vigente al asignar o entrar; la última que
        dejó (la sustituida más reciente) al salir."""
        from itcj2.apps.titulatec.models import SynodalAssignment

        filas = (db.query(SynodalAssignment.user_id, SynodalAssignment.role,
                          SynodalAssignment.is_active)
                 .filter(SynodalAssignment.process_id == process_id,
                         SynodalAssignment.user_id.in_(list(user_ids)))
                 .order_by(SynodalAssignment.id)
                 .all())
        quiere_vigente = kind != "replaced_out"
        roles: dict[int, str] = {}
        for uid, role, activa in filas:       # la última que cumple gana
            if bool(activa) is quiere_vigente:
                roles[uid] = role
        return roles

    @staticmethod
    def send_assignment_notices(process_id: int, user_ids, *, kind: str) -> None:
        """Aviso in-app y correo «Asignación como sinodal» a cada uno (§11).

        Se llama DESPUÉS del commit de la asignación o la sustitución y abre su
        PROPIA sesión. Best-effort: nunca lanza ni deshace nada (un `kind`
        desconocido sí es `ValueError`: es un error de programación). Con el
        corte en la fase 4 o antes no sale nada. Las notificaciones se commitean
        antes de tocar el correo; cada correo que no sale queda en el log y en
        la bitácora (`synodal.mail_failed`).

        `kind`: `assigned` (al registrar a los 4), `replaced_in` (entra por una
        sustitución) o `replaced_out` (sale: pierde el acceso al proceso).
        """
        if kind not in NOTICE_KINDS:
            raise ValueError(f"Aviso de sinodal no reconocido: {kind!r}.")
        ids = list(dict.fromkeys(int(u) for u in (user_ids or ()) if u is not None))
        if not ids:
            return
        from itcj2.apps.titulatec.services import email_helper

        tipo, titulo, asunto = _NOTICES[kind]
        envios, folio = [], None
        try:
            from itcj2.apps.titulatec.models import TitulationProcess
            from itcj2.apps.titulatec.services.student_mail import StudentMail
            from itcj2.core.services.notification_service import NotificationService
            from itcj2.database import SessionLocal

            db = SessionLocal()
            try:
                if not SynodalService.operable(db):
                    return
                process = db.get(TitulationProcess, process_id)
                if process is None:
                    return
                folio = process.folio
                base = SynodalService._notice_base(db, process)
                roles = SynodalService._roles_for_notice(db, process_id, ids, kind)
                users = SynodalService._users(db, ids)
                liga = StudentMail.link(_NOTICE_PATH)
                # Fase 5 operable: el correo invita a «Mis revisiones» (spec 2026-10-22 §10).
                from itcj2.apps.titulatec.services.review_service import ReviewService
                revision = ReviewService.operable(db)
                liga_revision = StudentMail.link(_REVIEWS_PATH) if revision else None
                for uid in ids:
                    user, role = users.get(uid), roles.get(uid)
                    if user is None or role is None:
                        logger.warning("Sinodales: sin aviso %s para el usuario %s del "
                                       "proceso %s (no se encontró su posición)",
                                       kind, uid, process_id)
                        continue
                    posicion = ROLE_LABELS.get(role, role)
                    cuerpo = (f"Ya no eres {posicion} en la titulación de {base['alumno']}."
                              if kind == "replaced_out" else
                              f"{posicion} en la titulación de {base['alumno']}"
                              + (f" ({base['carrera']})." if base["carrera"] else "."))
                    NotificationService.create(
                        db, user_id=uid, app_name="titulatec", type=tipo, title=titulo,
                        body=cuerpo, data={"url": _NOTICE_PATH, "process_id": process_id})
                    envios.append((uid, (user.email or "").strip() or None,
                                   {**base, "kind": kind, "nombre": _name(user),
                                    "posicion": posicion, "link": liga,
                                    "revision": revision, "review_link": liga_revision}))
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Sinodales: no se crearon los avisos %s del proceso %s",
                                 kind, process_id)
            finally:
                db.close()
        except Exception:
            logger.exception("Sinodales: error inesperado al preparar los avisos %s del "
                             "proceso %s", kind, process_id)
            return

        fallas = []
        for uid, destino, contexto in envios:
            try:
                ok, motivo = email_helper.deliver_detailed(
                    template=NOTICE_TEMPLATE, context=contexto, subject=asunto,
                    to=destino, que=f"synodal_{kind}")
            except Exception:
                logger.exception("Sinodales: error al enviar el correo %s al usuario %s",
                                 kind, uid)
                ok, motivo = False, "error"
            if not ok:
                logger.warning("Sinodales: no salió el correo %s al usuario %s del "
                               "proceso %s (%s)", kind, uid, process_id, motivo)
                fallas.append((uid, motivo))
        if fallas:
            SynodalService._record_mail_failures(process_id, folio, kind, fallas)

    @staticmethod
    def _record_mail_failures(process_id: int, folio, kind: str, fallas) -> None:
        """Cada correo que no salió, a la bitácora (§11). Su propia sesión y su
        propio commit; si esto también falla, ya quedó en el log."""
        try:
            from itcj2.apps.titulatec.services.audit_service import AuditService
            from itcj2.database import SessionLocal

            db = SessionLocal()
            try:
                for uid, motivo in fallas:
                    AuditService.record(
                        db, "synodal.mail_failed",
                        entity_type="user", entity_id=uid,
                        process_id=process_id, subject=folio,
                        payload={"kind": kind, "error": motivo},
                    )
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
        except Exception:
            logger.exception("Sinodales: no se registraron en la bitácora los correos "
                             "fallidos del proceso %s", process_id)
