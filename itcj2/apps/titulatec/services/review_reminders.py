"""Recordatorios del plazo de la revisión de sinodales (fase 5).

Spec 2026-10-22-titulatec-fase5-revision-sinodales §10 y D9. Lo corre la tarea
Celery `titulatec.review_reminders` (diaria, 9:15; la programa solo el DML de la
fase 2). Por cada versión VIGENTE de una conversación abierta de un proceso
`active`, y por cada asignación VIGENTE cuyo voto cuenta (`counting_roles`) y que
todavía no votó esa versión:

- `due_soon`: faltan 2 o menos días hábiles y la versión aún no vence (si el
  barrido de ese día no corrió, sale el primero que corra);
- `due_today`: hoy es el vencimiento o ya pasó (el primer barrido después).

El plazo es `ReviewService.due_date` (con el calendario de días inhábiles, que se
lee UNA vez): un festivo recorre el vencimiento y con él los dos avisos. Dedupe
por `INSERT … ON CONFLICT DO NOTHING RETURNING` en `titulatec_review_reminders`
(PK versión + asignación + tipo): solo quien insertó recibe el aviso. Un barrido
en lote: 4 consultas fijas más las del envío, ninguna por proceso.

Orden: el INSERT, el aviso in-app y el commit van juntos (si algo falla, el
recordatorio no queda marcado y el barrido siguiente lo reintenta); el correo
sale DESPUÉS del commit, best-effort (`ReviewNotices.deliver`).
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

REMINDER_TEMPLATE = "review_reminder.html"       # relativa a `titulatec/email/`
SUBJECTS = {
    "due_soon": "[TitulaTec ITCJ] Tu revisión está por vencer",
    "due_today": "[TitulaTec ITCJ] Hoy vence tu revisión",
}
TITLES = {
    "due_soon": "Tu revisión está por vencer",
    "due_today": "Hoy vence tu revisión",
}


class ReviewReminders:
    """El barrido diario de recordatorios de revisión."""

    @staticmethod
    def _batch(db: Session) -> list:
        """Versiones vigentes de conversaciones abiertas de procesos `active`
        con la fase 5 en curso: `(version, process)`. Dos consultas."""
        from sqlalchemy import func
        from sqlalchemy.orm import selectinload

        from itcj2.apps.titulatec.models import (
            ProcessChat, ProcessPhase, ReviewVersion, TitulationProcess,
        )
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        from itcj2.apps.titulatec.services.review_service import PHASE_CODE

        n5 = PhaseService.phase_number_for_code(db, PHASE_CODE)
        if n5 is None:
            return []
        rv2 = ReviewVersion.__table__.alias("rv2")
        ultima = (db.query(func.max(rv2.c.number))
                  .filter(rv2.c.process_id == ReviewVersion.process_id)
                  .correlate(ReviewVersion).scalar_subquery())
        versiones = (db.query(ReviewVersion)
                     .join(ProcessChat, ProcessChat.process_id == ReviewVersion.process_id)
                     .join(TitulationProcess, TitulationProcess.id == ReviewVersion.process_id)
                     .join(ProcessPhase, (ProcessPhase.process_id == ReviewVersion.process_id)
                           & (ProcessPhase.phase_number == n5))
                     .filter(ProcessChat.closed_at.is_(None),
                             TitulationProcess.status == "active",
                             ProcessPhase.status == "in_progress",
                             ReviewVersion.number == ultima)
                     .all())
        if not versiones:
            return []
        procesos = {p.id: p for p in (
            db.query(TitulationProcess)
            .options(selectinload(TitulationProcess.modality))
            .filter(TitulationProcess.id.in_({v.process_id for v in versiones})).all())}
        return [(v, procesos[v.process_id]) for v in versiones if v.process_id in procesos]

    @staticmethod
    def _pending_voters(db: Session, version_ids) -> dict[int, list]:
        """`{version_id: [(assignment_id, user_id, role)]}`: asignaciones
        vigentes SIN voto en esa versión. Una consulta."""
        from sqlalchemy import and_

        from itcj2.apps.titulatec.models import ReviewVersion, ReviewVote, SynodalAssignment

        filas = (db.query(ReviewVersion.id, SynodalAssignment.id, SynodalAssignment.user_id,
                          SynodalAssignment.role)
                 .join(SynodalAssignment, SynodalAssignment.process_id == ReviewVersion.process_id)
                 .outerjoin(ReviewVote, and_(ReviewVote.assignment_id == SynodalAssignment.id,
                                             ReviewVote.version_id == ReviewVersion.id))
                 .filter(ReviewVersion.id.in_(list(version_ids)),
                         SynodalAssignment.is_active.is_(True),
                         ReviewVote.id.is_(None))
                 .order_by(SynodalAssignment.id).all())
        salida: dict[int, list] = {}
        for vid, aid, uid, role in filas:
            salida.setdefault(vid, []).append((aid, uid, role))
        return salida

    @staticmethod
    def _claim(db: Session, version_id: int, assignment_id: int, kind: str) -> bool:
        """`INSERT … ON CONFLICT DO NOTHING RETURNING`: ¿este barrido lo marcó?"""
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from itcj2.apps.titulatec.models import ReviewReminder

        tabla = ReviewReminder.__table__
        stmt = (pg_insert(tabla)
                .values(version_id=version_id, assignment_id=assignment_id, kind=kind)
                .on_conflict_do_nothing()
                .returning(tabla.c.version_id))
        return db.execute(stmt).first() is not None

    @staticmethod
    def run(db: Session, *, today: date | None = None) -> dict:
        """El barrido. `{"due_soon": n, "due_today": n}` (avisos NUEVOS de cada
        tipo) o `{"disabled": True}` con la fase 5 fuera de la app. `today`
        por omisión es `db_now().date()`."""
        from itcj2.apps.titulatec.services.non_working_day_service import NonWorkingDayService
        from itcj2.apps.titulatec.services.review_notices import REMINDER_TYPE, ReviewNotices
        from itcj2.apps.titulatec.services.review_service import (
            WARN_BUSINESS_DAYS, ReviewService,
        )
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        from itcj2.apps.titulatec.services.synodal_service import SynodalService
        from itcj2.apps.titulatec.utils.business_days import business_days_between
        from itcj2.apps.titulatec.utils.dates_es import dia_largo
        from itcj2.core.models.user import User
        from itcj2.core.utils.timezone import db_now

        if not ReviewService.operable(db):
            return {"disabled": True}
        hoy = today if today is not None else db_now().date()
        cuenta = {"due_soon": 0, "due_today": 0}
        lote = ReviewReminders._batch(db)
        if not lote:
            return cuenta
        feriados = NonWorkingDayService.holidays(db)
        faltan = ReviewReminders._pending_voters(db, [v.id for v, _p in lote])

        # Por proceso: qué tipo toca (según el plazo) y a quién.
        por_enviar = []            # (proceso, versión, vence, kind, [(aid, uid)])
        for version, process in lote:
            try:
                roles = ReviewService.counting_roles(ReviewService.rule_for(process))
            except ValueError:
                continue                       # regla desconocida: nada que recordar
            vence = ReviewService.due_date(version, holidays=feriados)
            if hoy >= vence:
                kind = "due_today"
            elif business_days_between(hoy, vence, holidays=feriados) <= WARN_BUSINESS_DAYS:
                kind = "due_soon"
            else:
                continue
            quienes = [(aid, uid) for aid, uid, role in faltan.get(version.id, [])
                       if role in roles]
            if quienes:
                por_enviar.append((process, version, vence, kind, quienes))
        if not por_enviar:
            return cuenta

        envios_por_proceso = []    # (process_id, folio, kind, [(uid, destino, contexto)])
        try:
            usuarios = {u.id: u for u in db.query(User).filter(User.id.in_(
                {uid for *_x, quienes in por_enviar for _a, uid in quienes})).all()}
            for process, version, vence, kind, quienes in por_enviar:
                nuevos = []
                base = None
                for aid, uid in quienes:
                    if not ReviewReminders._claim(db, version.id, aid, kind):
                        continue
                    cuenta[kind] += 1
                    if base is None:
                        base = SynodalService._notice_base(db, process)
                    ReviewNotices._notify(
                        db, uid, type_=REMINDER_TYPE, title=TITLES[kind],
                        body=(f"Versión {version.number} del proyecto de {base['alumno']}: "
                              f"vence el {dia_largo(vence)}."),
                        url=ReviewNotices.synodal_url(process.id), process_id=process.id)
                    user = usuarios.get(uid)
                    if user is not None:
                        nuevos.append((uid, (user.email or "").strip() or None, {
                            **base, "kind": kind, "version": version.number,
                            "nombre": " ".join(p for p in (user.first_name, user.last_name,
                                                           user.middle_name) if p),
                            "vence": dia_largo(vence),
                            "link": StudentMail.link(ReviewNotices.synodal_url(process.id))}))
                if nuevos:
                    envios_por_proceso.append((process.id, process.folio, kind, nuevos))
            db.commit()
        except Exception:
            db.rollback()
            raise

        # Después del commit, best-effort: nunca revierte lo marcado.
        for process_id, folio, kind, envios in envios_por_proceso:
            ReviewNotices.deliver(envios, template=REMINDER_TEMPLATE, subject=SUBJECTS[kind],
                                  que=f"review_{kind}", process_id=process_id, folio=folio)
        logger.info("Revisión: recordatorios nuevos — %s", cuenta)
        return cuenta
