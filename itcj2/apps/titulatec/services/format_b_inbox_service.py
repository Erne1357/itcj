"""Bandeja del Formato B (pestaña «Titulación», spec fase 3 §8.2).

Solo LECTURA: arma las 4 pestañas (por revisar en FIFO, con observaciones,
aprobados, sin enviar), sus contadores y la siguiente de la cola. El dictamen
vive en `FormatBService`.

Mismo patrón que la bandeja de Documentos: alcance por carrera
(`officer_programs`) ANTES de contar y paginar, búsqueda con `process_search`,
desempate por `process_id` en todo orden paginado, y un número FIJO de
consultas por página (nombres, carrera y modalidad salen del mismo SELECT).
"""
from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from typing import Iterable

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from itcj2.core.utils.timezone import db_now


class FormatBInboxService:
    """Consultas de la bandeja del Formato B."""

    TABS = ("pending", "observed", "approved", "unsent")
    WAIT_WARN_DAYS = 3   # ámbar desde aquí (días hábiles)
    WAIT_LATE_DAYS = 5   # rojo desde aquí

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _business_days_since(start: date, today: date) -> int:
        """Días hábiles (lun-vie) ESTRICTAMENTE posteriores a `start` hasta `today`."""
        n, d = 0, start
        while d < today:
            d += timedelta(days=1)
            if d.weekday() < 5:
                n += 1
        return n

    @staticmethod
    def _wait_level(days: int) -> str:
        if days >= FormatBInboxService.WAIT_LATE_DAYS:
            return "late"
        if days >= FormatBInboxService.WAIT_WARN_DAYS:
            return "warn"
        return "ok"

    @staticmethod
    def _tab_predicates(db: Session):
        """Predicado SQL de cada pestaña (mismo para la lista y los contadores)."""
        from itcj2.apps.titulatec.models import FormatB, TitulationProcess as TP
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        n = PhaseService.phase_number_for_code(db, "format_b")
        unsent = (and_(
            TP.status == "active", TP.current_phase == n,
            or_(FormatB.process_id.is_(None), FormatB.status == "draft"),
        ) if n is not None else and_(TP.id.is_(None)))  # sin catálogo: vacía
        return {
            "pending": and_(FormatB.status == "submitted", TP.status == "active"),
            "observed": and_(FormatB.status == "rejected", TP.status != "cancelled"),
            "approved": and_(FormatB.status == "approved", TP.status != "cancelled"),
            "unsent": unsent,
        }, n

    @staticmethod
    def _base(db: Session, user_id: int, *, q, program_id):
        """Query de procesos en alcance + búsqueda + carrera, o `None`.

        `program_id IS NULL` queda fuera siempre. Devuelve `None` si el alcance
        no deja ver nada.
        """
        from itcj2.apps.titulatec.models import FormatB, TitulationProcess as TP
        from itcj2.apps.titulatec.services.process_service import process_search
        from itcj2.apps.titulatec.services.scope_service import officer_programs
        from itcj2.core.models.user import User

        scope = officer_programs(db, user_id)
        if scope != "ALL" and not scope:
            return None
        query = (
            db.query(TP)
            .outerjoin(FormatB, FormatB.process_id == TP.id)
            .outerjoin(User, User.id == TP.student_id)
            .filter(TP.program_id.isnot(None))
        )
        if scope != "ALL":
            query = query.filter(TP.program_id.in_(scope))
        if program_id is not None:
            query = query.filter(TP.program_id == program_id)
        search = process_search(q)
        if search is not None:
            query = query.filter(search)
        return query

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    @staticmethod
    def list(db: Session, user_id: int, *, tab: str, q: str = "",
             program_id: int | None = None, page: str | int = "",
             per_page: int | None = None) -> dict:
        """Una página de la bandeja + contadores de las 4 pestañas.

        `counts` respeta `q` y carrera (no la pestaña ni la página). Una
        pestaña desconocida cae en `pending`.
        """
        from itcj2.apps.titulatec.models import (
            FormatB, Modality, ProcessPhase, TitulationProcess as TP,
        )
        from itcj2.apps.titulatec.utils.paging import (
            PAGE_SIZE, Page, normalize_q, paginate_query, parse_page,
        )
        from itcj2.core.models.program import Program
        from itcj2.core.models.user import User

        cls = FormatBInboxService
        per_page = per_page or PAGE_SIZE
        tab = tab if tab in cls.TABS else "pending"
        q = normalize_q(q)
        page_n = parse_page(page)

        vacio = {"rows": [], "page": Page(items=[], total=0, page=1, per_page=per_page),
                 "counts": {t: 0 for t in cls.TABS}, "tab": tab}
        base = cls._base(db, user_id, q=q, program_id=program_id)
        if base is None:
            return vacio
        preds, phase_n = cls._tab_predicates(db)

        # Contadores: UNA consulta con un COUNT FILTER por pestaña.
        agregados = [func.count(TP.id).filter(preds[t]) for t in cls.TABS]
        fila = base.order_by(None).with_entities(*agregados).one()
        counts = {t: int(c or 0) for t, c in zip(cls.TABS, fila)}

        cols = (
            TP.id.label("process_id"), TP.folio, User.first_name, User.middle_name,
            User.last_name, User.control_number, Program.name.label("program_name"),
            Modality.name.label("modality_name"), FormatB.submitted_at,
            FormatB.submission_count, FormatB.reviewed_at, FormatB.approved_at,
        )
        lista = (
            base.with_entities(*cols)
            .outerjoin(Program, Program.id == TP.program_id)
            .outerjoin(Modality, Modality.id == func.coalesce(FormatB.modality_id,
                                                              TP.modality_id))
            .filter(preds[tab])
        )
        if tab == "pending":
            lista = lista.order_by(FormatB.submitted_at.asc(), TP.id.asc())
        elif tab == "observed":
            lista = lista.order_by(FormatB.reviewed_at.desc(), TP.id.desc())
        elif tab == "approved":
            lista = lista.order_by(FormatB.approved_at.desc(), TP.id.desc())
        else:
            lista = (lista
                     .outerjoin(ProcessPhase, and_(ProcessPhase.process_id == TP.id,
                                                   ProcessPhase.phase_number == phase_n))
                     .order_by(ProcessPhase.started_at.asc().nulls_last(), TP.id.asc()))

        pg = paginate_query(lista, page_n, per_page)
        hoy = db_now().date()
        first = (pg.page - 1) * pg.per_page
        rows = []
        for i, r in enumerate(pg.items):
            nombre = " ".join(p for p in (r.last_name, r.middle_name) if p)
            nombre = f"{nombre}, {r.first_name}" if r.first_name else nombre
            days = level = pos = None
            if tab == "pending":
                pos = first + i + 1
                if r.submitted_at is not None:
                    days = cls._business_days_since(r.submitted_at.date(), hoy)
                    level = cls._wait_level(days)
            rows.append({
                "process_id": r.process_id, "folio": r.folio,
                "student_name": nombre, "control_number": r.control_number,
                "program_name": r.program_name, "modality_name": r.modality_name,
                "submitted_at": r.submitted_at, "round": int(r.submission_count or 0),
                "waited_days": days, "wait_level": level, "position": pos,
            })
        return {"rows": rows, "page": dataclasses.replace(pg, items=rows),
                "counts": counts, "tab": tab}

    @staticmethod
    def contains(db: Session, user_id: int, process_id: int, *, tab: str,
                 q: str = "", program_id: int | None = None) -> bool:
        """¿`process_id` está en la pestaña, con la búsqueda, carrera y alcance
        dados? Mismo `_base` y mismo predicado que la lista; una consulta."""
        from itcj2.apps.titulatec.models import TitulationProcess as TP
        from itcj2.apps.titulatec.utils.paging import normalize_q

        cls = FormatBInboxService
        base = cls._base(db, user_id, q=normalize_q(q), program_id=program_id)
        if base is None or tab not in cls.TABS:
            return False
        preds, _n = cls._tab_predicates(db)
        return (base.filter(preds[tab], TP.id == int(process_id))
                .with_entities(TP.id).first()) is not None

    @staticmethod
    def next_pending(db: Session, user_id: int, *,
                     exclude_ids: Iterable[int] = (), q: str = "",
                     program_id: int | None = None) -> int | None:
        """`process_id` del siguiente «Por revisar» en la cola FIFO, o None.

        Salta `exclude_ids` (p. ej. el recién dictaminado y los que otra
        persona tiene abierto). Mismo alcance y orden que la pestaña; con `q` y
        `program_id` es el siguiente del conjunto FILTRADO.
        """
        from itcj2.apps.titulatec.models import FormatB, TitulationProcess as TP
        from itcj2.apps.titulatec.utils.paging import normalize_q

        cls = FormatBInboxService
        base = cls._base(db, user_id, q=normalize_q(q), program_id=program_id)
        if base is None:
            return None
        excl = [int(i) for i in exclude_ids]
        query = base.filter(FormatB.status == "submitted", TP.status == "active")
        if excl:
            query = query.filter(TP.id.notin_(excl))
        row = (query.with_entities(TP.id)
               .order_by(FormatB.submitted_at.asc(), TP.id.asc()).first())
        return int(row[0]) if row else None
