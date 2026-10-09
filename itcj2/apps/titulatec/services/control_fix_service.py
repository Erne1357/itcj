"""Corrección de solicitudes inscritas con la «L» de licenciatura (2026-10-09).

La «L» inicial es el prefijo del correo institucional (L21111134@…), no parte
del número de control: las cuentas de licenciatura son los 8 dígitos. Hasta que
`import_service.normalize_control` empezó a quitarla, quien escribió
«L21111134» en el formulario quedaba como «sin cuenta» aunque la tuviera, y si
Centro de Cómputo le daba acceso nacía una SEGUNDA cuenta «L21111134».

`ControlFixService.plan` clasifica cada solicitud con L (solo lectura) y `apply`
corrige una por una, cada una en su propia transacción:

  corregir         Solicitud sin resolver y sin duplicado: se le quita la L. Con
                   cuenta queda «con cuenta» y sigue el camino normal (liga).
  liga             En Accesos (SE ya aprobó) pero SÍ tiene cuenta: no pasa por
                   Centro de Cómputo; se le quita la L y se emite la liga de
                   activación, conservando quién y cuándo aprobó SE.
  liga_en_otra     Igual, pero la persona ya tenía OTRA solicitud correcta sin
                   resolver: esa hereda la aprobación de SE y recibe la liga; la
                   de la L se rechaza (sin correo).
  accesos_en_otra  Lo mismo sin cuenta: la correcta hereda la aprobación y pasa a
                   Accesos; la de la L se rechaza.
  rechazar_dup     Duplicada de una solicitud correcta ya inscrita o en curso: se
                   rechaza con nota (sin correo).
  unificar         Ya inscrita y Centro de Cómputo le creó la cuenta «L…» aunque
                   tenía la suya: proceso, documentos (también en disco),
                   encuesta, eventos, correos, avisos y perfil pasan a su cuenta;
                   la «L…» se borra; queda como egresada en su cuenta. Su NIP es
                   el de su cuenta (el del SII). Aviso por correo.
  renombrar        Ya inscrita SIN otra cuenta: la cuenta «L…» pasa a llamarse
                   con su número (y sus archivos). Aviso por correo.
  revisar          Algo no encaja (otro proceso, cuenta sin proceso…): no se toca.

Las solicitudes rechazadas y las demás ya resueltas sin cuenta «L» se omiten.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

_L_RE = re.compile(r"^L(\d{8})$")
_SIN_DECIDIR = ("unverified", "verified", "pending_review")
_VIVAS = _SIN_DECIDIR + ("approved", "awaiting_access")
# Las referencias a la cuenta «L…» que se mueven a mano; las demás abortan.
_SE_VAN_CON_LA_CUENTA = {"core_user_app_roles", "core_user_app_perms"}


@dataclass
class Accion:
    request_id: int
    control: str
    plain: str
    status: str
    tipo: str
    detalle: str
    otra_id: int | None = None
    resultado: str = ""
    correo: str = ""
    movidos: list = field(default_factory=list)


def _nombre(req) -> str:
    return " ".join(x for x in (req.last_name, req.middle_name, req.first_name) if x).strip()


def _nota_dup(control: str, otra_id: int, motivo: str) -> str:
    return (f"Número de control escrito con la «L» del correo institucional ({control}). "
            f"{motivo} (solicitud #{otra_id}). Corrección del "
            f"{datetime.now():%d/%m/%Y}; no se envió correo.")


class ControlFixService:
    """Única dueña de la corrección de la «L». Ver el docstring del módulo."""

    # ------------------------------------------------------------------ plan
    @staticmethod
    def plan(db) -> list[Accion]:
        """Qué haría `apply` con cada solicitud con L. Solo lectura."""
        from sqlalchemy import func

        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.models import EnrollmentRequest as ER
        from itcj2.apps.titulatec.models import TitulationProcess
        from itcj2.apps.titulatec.services.process_service import ProcessService

        acciones: list[Accion] = []
        reqs = (db.query(ER).filter(func.upper(ER.control_number).op("~")(r"^L[0-9]{8}$"))
                .order_by(ER.id).all())
        for r in reqs:
            control = (r.control_number or "").strip()
            plain = _L_RE.fullmatch(control.upper()).group(1)
            u_plain = db.query(User).filter_by(control_number=plain).first()
            u_l = db.query(User).filter_by(control_number=control).first()
            otras = (db.query(ER).filter(ER.cohort_id == r.cohort_id, ER.control_number == plain,
                                         ER.id != r.id).order_by(ER.id.desc()).all())
            viva = next((o for o in otras if o.status in _VIVAS), None)
            inscrita = next((o for o in otras if o.status == "converted"), None)

            def _a(tipo, detalle, otra=None):
                acciones.append(Accion(r.id, control, plain, r.status, tipo, detalle,
                                       otra.id if otra is not None else None))

            if r.status == "converted":
                if u_l is None:
                    _a("revisar", "inscrita pero no hay cuenta con la L")
                    continue
                proc_l = db.query(TitulationProcess).filter_by(student_id=u_l.id).all()
                if len(proc_l) != 1:
                    _a("revisar", f"la cuenta {control} tiene {len(proc_l)} procesos")
                    continue
                if u_plain is None:
                    _a("renombrar", f"la cuenta {control} pasa a llamarse {plain}", viva)
                    continue
                if db.query(TitulationProcess.id).filter_by(student_id=u_plain.id).first():
                    _a("revisar", f"la cuenta {plain} ya tiene su propio proceso")
                    continue
                _a("unificar", f"proceso {proc_l[0].folio} de la cuenta {control} a la {plain}",
                   viva)
            elif r.status in _VIVAS:
                if inscrita is not None:
                    _a("rechazar_dup", "ya está inscrita con su número correcto", inscrita)
                elif viva is not None and viva.status in _SIN_DECIDIR and r.status == "awaiting_access":
                    if u_plain is not None:
                        _a("liga_en_otra", "la correcta hereda la aprobación de SE y recibe la liga",
                           viva)
                    else:
                        _a("accesos_en_otra", "la correcta hereda la aprobación de SE y pasa a Accesos",
                           viva)
                elif viva is not None:
                    _a("rechazar_dup", f"tiene otra solicitud con su número ({viva.status})", viva)
                elif r.status == "awaiting_access" and u_plain is not None:
                    _a("liga", "tiene cuenta: no pasa por Accesos, se le envía la liga")
                elif r.status == "approved":
                    _a("revisar", "aprobada con L: revisar a mano")
                else:
                    _a("corregir", "se le quita la L" + (" (tiene cuenta)" if u_plain else ""))
            # rechazadas y demás ya resueltas: nada que hacer

        # Constancias previas (encuesta de Forms, CSV) guardadas con la L: nunca
        # se aplicaban al inscribirse, porque `apply_pending` busca por el número
        # de la cuenta. `request_id` aquí es el id de la PREVIA.
        from itcj2.apps.titulatec.models import PriorClearance as PC
        for pc in (db.query(PC).filter(func.upper(PC.control_number).op("~")(r"^L[0-9]{8}$"))
                   .order_by(PC.id).all()):
            plain = _L_RE.fullmatch(pc.control_number.strip().upper()).group(1)
            if db.query(PC.id).filter_by(kind=pc.kind, control_number=plain).first():
                acciones.append(Accion(pc.id, pc.control_number, plain, f"previa {pc.kind}",
                                       "revisar", "ya hay otra previa con su número"))
                continue
            u = db.query(User).filter_by(control_number=plain).first()
            proc = (ProcessService.creditable_process(db, u.id) if u is not None
                    and pc.applied_process_id is None else None)
            detalle = ("se le quita la L y se APLICA a su proceso " + proc.folio if proc is not None
                       else "se le quita la L (se aplicará cuando se inscriba)")
            acciones.append(Accion(pc.id, pc.control_number, plain, f"previa {pc.kind}",
                                   "previa", detalle))
        return acciones

    # ----------------------------------------------------------------- apply
    @staticmethod
    def apply(db, accion: Accion, *, send_mail: bool = True) -> Accion:
        """Aplica UNA acción en su propia transacción (commit o rollback aquí).
        Los archivos se mueven antes del commit y se regresan si algo falla."""
        movidos: list[tuple] = []
        try:
            handler = getattr(ControlFixService, f"_{accion.tipo}", None)
            if handler is None:
                accion.resultado = "sin cambios"
                return accion
            despues = handler(db, accion, movidos) or (lambda _mail: None)
            db.commit()
        except Exception as exc:
            db.rollback()
            for nuevo, viejo in reversed(movidos):
                try:
                    os.rename(nuevo, viejo)
                except OSError:
                    logger.exception("No se pudo regresar %s", nuevo)
            accion.resultado = f"ERROR: {type(exc).__name__}: {exc}"
            return accion
        accion.movidos = [str(n) for n, _ in movidos]
        ControlFixService._limpiar_carpetas(movidos)
        accion.resultado = accion.resultado or "aplicada"
        # Caché de authz SIEMPRE tras el commit; el correo solo con `send_mail`.
        accion.correo = despues(send_mail) or ""
        return accion

    # ------------------------------------------------------- acciones simples
    @staticmethod
    def _req(db, rid):
        from itcj2.apps.titulatec.models import EnrollmentRequest
        return db.query(EnrollmentRequest).filter_by(id=rid).with_for_update().one()

    @staticmethod
    def _corregir_control(db, req, plain, *, path: str, extra: dict | None = None):
        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.services.audit_service import AuditService

        antes = req.control_number
        req.control_number = plain
        req.kind = "known" if db.query(User.id).filter_by(control_number=plain).first() else "unknown"
        req.updated_at = datetime.now()
        db.flush()
        AuditService.record(
            db, "enrollment.control_corrected",
            entity_type="enrollment_request", entity_id=req.id,
            subject=f"{plain} · {_nombre(req)}",
            before={"control_number": antes}, after={"control_number": plain},
            payload={"path": path, "cohort_id": req.cohort_id, **(extra or {})})

    @staticmethod
    def _rechazar(db, req, nota: str):
        req.status = "rejected"
        req.review_note = nota
        req.reviewed_by_id = None
        req.reviewed_at = datetime.now()
        req.updated_at = datetime.now()
        req.verify_token_hash = None
        req.verify_expires_at = None

    @staticmethod
    def _corregir(db, a, movidos):
        req = ControlFixService._req(db, a.request_id)
        ControlFixService._corregir_control(db, req, a.plain, path="corrected")

    @staticmethod
    def _rechazar_dup(db, a, movidos):
        req = ControlFixService._req(db, a.request_id)
        motivo = ("Ya está inscrita con su número correcto" if a.tipo == "rechazar_dup"
                  else "Duplicada")
        ControlFixService._rechazar(db, req, _nota_dup(a.control, a.otra_id, motivo))
        ControlFixService._corregir_control(db, req, a.plain, path="rejected_duplicate",
                                            extra={"kept_request_id": a.otra_id})

    @staticmethod
    def _emitir_liga(db, req, user):
        """`_issue_link_for_account` (D5, contraseña) + liga en Redis y correo
        DESPUÉS del commit. Devuelve el callable que manda."""
        from itcj2.apps.titulatec.services import enrollment_request_service as ers

        ok, detalle, raw = ers.EnrollmentRequestService._issue_link_for_account(db, req, user)
        if not ok:
            raise ValueError(detalle)

        def _mandar(send_mail):
            ers._token_cache_put(raw)
            if not send_mail:
                return "liga emitida SIN correo (reenviarla desde Solicitudes)"
            return ("liga enviada" if ers.EnrollmentRequestService._mail_activation(db, req, raw)
                    else "liga NO enviada (reenviarla desde Solicitudes)")
        return _mandar

    @staticmethod
    def _liga(db, a, movidos):
        from itcj2.core.models.user import User

        req = ControlFixService._req(db, a.request_id)
        ControlFixService._corregir_control(db, req, a.plain, path="link")
        user = db.query(User).filter_by(control_number=a.plain).one()
        return ControlFixService._emitir_liga(db, req, user)

    @staticmethod
    def _heredar(db, a):
        req = ControlFixService._req(db, a.request_id)
        otra = ControlFixService._req(db, a.otra_id)
        otra.reviewed_by_id = req.reviewed_by_id
        otra.reviewed_at = req.reviewed_at
        otra.program_id = otra.program_id or req.program_id
        ControlFixService._rechazar(db, req, _nota_dup(
            a.control, otra.id, "Su solicitud correcta hereda la aprobación de Servicios Escolares"))
        ControlFixService._corregir_control(db, req, a.plain, path="approval_moved",
                                            extra={"kept_request_id": otra.id})
        return otra

    @staticmethod
    def _liga_en_otra(db, a, movidos):
        from itcj2.core.models.user import User

        otra = ControlFixService._heredar(db, a)
        user = db.query(User).filter_by(control_number=a.plain).one()
        return ControlFixService._emitir_liga(db, otra, user)

    @staticmethod
    def _accesos_en_otra(db, a, movidos):
        otra = ControlFixService._heredar(db, a)
        otra.status = "awaiting_access"

    @staticmethod
    def _previa(db, a, movidos):
        """Constancia previa con L: su número (y el de su respuesta de encuesta)
        sin la L y, si el alumno ya tiene proceso vivo, se aplica ahí mismo con
        `apply_pending` -el mismo camino que al inscribirse, con su folio, aviso
        y correo de liberación-."""
        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.models import PriorClearance, SurveyResponse
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.prior_clearance_service import PriorClearanceService
        from itcj2.apps.titulatec.services.process_service import ProcessService

        pc = db.query(PriorClearance).filter_by(id=a.request_id).with_for_update().one()
        antes = pc.control_number
        pc.control_number = a.plain
        if pc.response_id:
            db.query(SurveyResponse).filter(SurveyResponse.id == pc.response_id,
                                            SurveyResponse.control_number == antes).update(
                {"control_number": a.plain}, synchronize_session=False)
        db.flush()
        aplicadas, proc = [], None
        u = db.query(User).filter_by(control_number=a.plain).first()
        if u is not None and pc.applied_process_id is None:
            proc = ProcessService.creditable_process(db, u.id)
            if proc is not None:
                aplicadas = PriorClearanceService.apply_pending(db, proc, a.plain)
        AuditService.record(
            db, "enrollment.control_corrected",
            entity_type="prior_clearance", entity_id=pc.id,
            process_id=proc.id if proc is not None else None, subject=a.plain,
            before={"control_number": antes}, after={"control_number": a.plain},
            payload={"path": "prior_clearance", "kind": pc.kind, "applied": aplicadas})
        a.resultado = ("aplicada a " + proc.folio) if aplicadas else (
            "corregida (se aplicará al inscribirse)" if proc is None else
            "corregida; NO se pudo aplicar (revisar vigencia)")

    # ------------------------------------------------ unificar / renombrar
    @staticmethod
    def _unificar(db, a, movidos):
        from itcj2.core.models.user import User

        req = ControlFixService._req(db, a.request_id)
        u_l = db.query(User).filter_by(control_number=a.control).with_for_update().one()
        u_plain = db.query(User).filter_by(control_number=a.plain).with_for_update().one()
        return ControlFixService._pasar_proceso(db, a, req, u_l, u_plain, movidos)

    @staticmethod
    def _renombrar(db, a, movidos):
        from itcj2.core.models.user import User

        req = ControlFixService._req(db, a.request_id)
        u_l = db.query(User).filter_by(control_number=a.control).with_for_update().one()
        return ControlFixService._pasar_proceso(db, a, req, u_l, None, movidos)

    @staticmethod
    def _pasar_proceso(db, a, req, u_l, u_plain, movidos):
        """`unificar` (con `u_plain`) o `renombrar` (sin él). Todo en la sesión;
        los archivos se mueven al final y `apply` los regresa si algo falla."""
        from sqlalchemy import text

        from itcj2.core.models.notification import Notification
        from itcj2.core.models.student_profile import StudentProfile
        from itcj2.apps.titulatec.models import (
            Document, EmailOutbox, ProcessEvent, SurveyDraft, SurveyResponse, TitulationProcess,
        )
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.utils import storage

        proc = db.query(TitulationProcess).filter_by(student_id=u_l.id).with_for_update().one()
        destino = u_plain or u_l
        perfil_l = db.get(StudentProfile, u_l.id)
        otra_req = ControlFixService._req(db, a.otra_id) if a.otra_id else None
        correos = list(dict.fromkeys(c for c in (
            perfil_l.contact_email if perfil_l else None, req.contact_email,
            otra_req.contact_email if otra_req is not None else None) if c))

        if u_plain is not None:
            tid = u_plain.id
            proc.student_id = tid
            db.query(Document).filter_by(uploaded_by_id=u_l.id).update(
                {"uploaded_by_id": tid}, synchronize_session=False)
            db.query(ProcessEvent).filter_by(actor_id=u_l.id).update(
                {"actor_id": tid}, synchronize_session=False)
            db.query(EmailOutbox).filter_by(user_id=u_l.id).update(
                {"user_id": tid}, synchronize_session=False)
            db.query(Notification).filter_by(user_id=u_l.id).update(
                {"user_id": tid}, synchronize_session=False)
            db.query(SurveyResponse).filter_by(user_id=u_l.id).update(
                {"user_id": tid}, synchronize_session=False)
            for borrador in db.query(SurveyDraft).filter_by(user_id=u_l.id).all():
                if db.query(SurveyDraft.id).filter_by(form_id=borrador.form_id, user_id=tid).first():
                    db.delete(borrador)
                else:
                    borrador.user_id = tid
            perfil_plain = db.get(StudentProfile, tid)
            if perfil_l is not None:
                if perfil_plain is None:
                    db.expunge(perfil_l)
                    db.execute(text("UPDATE core_student_profile SET user_id = :t WHERE user_id = :l"),
                               {"t": tid, "l": u_l.id})
                else:
                    for col in ("contact_email", "phone", "program_id", "has_efirma"):
                        if getattr(perfil_plain, col) in (None, ""):
                            setattr(perfil_plain, col, getattr(perfil_l, col))
                    db.delete(perfil_l)
            db.flush()
        else:
            u_l.control_number = a.plain
            u_l.username = a.plain

        # Encuesta: la respuesta guarda también el número de control.
        db.query(SurveyResponse).filter(SurveyResponse.process_id == proc.id,
                                        SurveyResponse.control_number == a.control).update(
            {"control_number": a.plain}, synchronize_session=False)

        # Documentos: carpeta y nombre llevan el número de control.
        planes = []
        for doc in db.query(Document).filter_by(process_id=proc.id).all():
            nuevo = (doc.file_path or "").replace(f"/{a.control}/", f"/{a.plain}/").replace(
                f"/{a.control}_", f"/{a.plain}_")
            if nuevo != doc.file_path:
                planes.append((storage.safe_abs_path(doc.file_path), storage.safe_abs_path(nuevo)))
                doc.file_path = nuevo

        # Solicitud: su número sin la L; la correcta duplicada (si había) se rechaza.
        ControlFixService._corregir_control(db, req, a.plain, path=a.tipo,
                                            extra={"process_id": proc.id})
        if otra_req is not None:
            ControlFixService._rechazar(db, otra_req, _nota_dup(
                a.control, req.id, "Duplicada de la solicitud ya inscrita"))

        tocadas = ControlFixService._egresado(db, destino)

        if u_plain is not None:
            db.flush()
            restos = ControlFixService._referencias(db, u_l.id)
            if restos:
                raise ValueError(f"la cuenta {a.control} sigue referida en {restos}")
            # SQL directo: la base borra en cascada roles y permisos directos; el
            # ORM intentaría ponerlos en NULL.
            db.expunge(u_l)
            db.execute(text("DELETE FROM core_users WHERE id = :u"), {"u": u_l.id})
        db.flush()
        AuditService.record(
            db, "enrollment.account_merged",
            entity_type="user", entity_id=destino.id, process_id=proc.id,
            subject=f"{a.plain} · {_nombre(req)}",
            before={"control_number": a.control, "user_id": u_l.id},
            after={"control_number": a.plain, "user_id": destino.id},
            payload={"path": a.tipo, "request_id": req.id, "folio": proc.folio,
                     "documents_moved": len(planes), "rejected_duplicate": a.otra_id,
                     "account_deleted": u_l.id if u_plain is not None else None})

        for viejo, nuevo in planes:
            if viejo.exists():
                if nuevo.exists():
                    raise FileExistsError(str(nuevo))
                nuevo.parent.mkdir(parents=True, exist_ok=True)
                os.rename(viejo, nuevo)
                movidos.append((nuevo, viejo))

        borrada = u_l.id if u_plain is not None else None

        def _despues(send_mail):
            from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper
            from itcj2.apps.titulatec.services.import_service import ImportService
            from itcj2.core.services.authz_cache import invalidate_user

            ImportService.invalidate_authz(tocadas)
            if borrada:
                invalidate_user(borrada)
            if not send_mail:
                return "aviso NO enviado (--sin-correo)"
            ok, motivo = TitulaTecEmailHelper.send_username_changed(
                destino, proc, old_control=a.control, personal_emails=correos)
            return "aviso enviado" if ok else f"aviso NO enviado ({motivo})"
        return _despues

    @staticmethod
    def _egresado(db, user) -> list:
        """Roles de egresado como los deja `import_rows`; reactiva la cuenta
        (misma excepción que abrir la liga). Devuelve los pares de authz tocados."""
        from itcj2.core.models.app import App
        from itcj2.core.models.role import Role
        from itcj2.apps.titulatec.services.import_service import (
            GRADUATE_APP_KEYS, GRADUATE_ROLE, LEGACY_STUDENT_ROLE, STUDENT_REVOKE_APP_KEYS,
            _sync_graduate_roles,
        )

        graduate = db.query(Role).filter_by(name=GRADUATE_ROLE).one()
        student = db.query(Role).filter_by(name=LEGACY_STUDENT_ROLE).first()
        app_ids = dict(db.query(App.key, App.id).filter(
            App.key.in_(set(GRADUATE_APP_KEYS) | set(STUDENT_REVOKE_APP_KEYS))).all())
        apps = _sync_graduate_roles(db, user, graduate_role=graduate, student_role=student,
                                    app_ids=app_ids)
        user.is_active = True
        return [(user.id, k) for k in apps]

    @staticmethod
    def _referencias(db, user_id) -> list[str]:
        """Tablas (fuera de roles/permisos directos) que aún apuntan a la cuenta."""
        from sqlalchemy import text

        fks = db.execute(text(
            "SELECT c.conrelid::regclass::text, a.attname FROM pg_constraint c "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
            "WHERE c.contype = 'f' AND c.confrelid = 'core_users'::regclass")).fetchall()
        restos = []
        for tabla, col in fks:
            if tabla in _SE_VAN_CON_LA_CUENTA:
                continue
            n = db.execute(text(f'SELECT count(*) FROM {tabla} WHERE "{col}" = :u'),
                           {"u": user_id}).scalar()
            if n:
                restos.append(f"{tabla}.{col}={n}")
        return restos

    @staticmethod
    def _limpiar_carpetas(movidos) -> None:
        """Quita las carpetas viejas que quedaron vacías (best-effort)."""
        for _, viejo in movidos:
            for carpeta in (viejo.parent, viejo.parent.parent):
                try:
                    carpeta.rmdir()
                except OSError:
                    pass
