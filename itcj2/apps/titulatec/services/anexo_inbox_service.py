"""Bandeja del Anexo III (vista «Anexo III» de la pestaña Titulación, spec fase 6 §9.2).

Solo LECTURA: arma las 4 pestañas (por revisar en FIFO, con observaciones,
aprobados, sin enviar), sus contadores y el siguiente de la cola. El dictamen
vive en `AnexoService`.

Gemelo de `FormatBInboxService` (mismo contrato `rows/page/counts/tab`): los
predicados salen de la `ProcessPhase` de la fase 6 (resuelta por CÓDIGO), la
clave FIFO es `ProcessPhase.updated_at` (cada subida del escaneo la escribe,
`AnexoService.sync_phase`), alcance por carrera (`officer_programs`) ANTES de
contar y paginar, desempate por `process_id` y un número FIJO de consultas por
página.
"""
from __future__ import annotations

import dataclasses
from typing import Iterable

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.non_working_day_service import NonWorkingDayService
from itcj2.apps.titulatec.utils.business_days import business_days_between
from itcj2.core.utils.timezone import db_now


class AnexoInboxService:
    """Consultas de la bandeja del Anexo III."""

    TABS = ("pending", "observed", "approved", "unsent")
    WAIT_WARN_DAYS = 3   # ámbar desde aquí (días hábiles)
    WAIT_LATE_DAYS = 5   # rojo desde aquí

    @staticmethod
    def _wait_level(days: int) -> str:
        if days >= AnexoInboxService.WAIT_LATE_DAYS:
            return "late"
        if days >= AnexoInboxService.WAIT_WARN_DAYS:
            return "warn"
        return "ok"

    @staticmethod
    def _predicates():
        """Predicado SQL de cada pestaña (mismo para la lista y los contadores)."""
        from itcj2.apps.titulatec.models import ProcessPhase as PP, TitulationProcess as TP

        return {
            "pending": and_(PP.status == "in_review", TP.status == "active"),
            "observed": and_(PP.status == "rejected", TP.status != "cancelled"),
            "approved": and_(PP.status == "approved", TP.status != "cancelled"),
            "unsent": and_(PP.status == "in_progress", TP.status == "active"),
        }

    @staticmethod
    def _base(db: Session, user_id: int, *, q, program_id):
        """Query de procesos en alcance + fase 6 + búsqueda + carrera, o `None`.

        `None` si la fase no está en el catálogo o el alcance no deja ver nada.
        `program_id IS NULL` queda fuera siempre.
        """
        from itcj2.apps.titulatec.models import ProcessPhase as PP, TitulationProcess as TP
        from itcj2.apps.titulatec.services.anexo_service import AnexoService
        from itcj2.apps.titulatec.services.process_service import process_search
        from itcj2.apps.titulatec.services.scope_service import officer_programs
        from itcj2.core.models.user import User

        n = AnexoService.phase_number(db)
        if n is None:
            return None
        scope = officer_programs(db, user_id)
        if scope != "ALL" and not scope:
            return None
        query = (
            db.query(TP)
            .join(PP, and_(PP.process_id == TP.id, PP.phase_number == n))
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

    @staticmethod
    def list(db: Session, user_id: int, *, tab: str, q: str = "",
             program_id: int | None = None, page: str | int = "",
             per_page: int | None = None) -> dict:
        """Una página de la bandeja + contadores de las 4 pestañas.

        `counts` respeta `q` y carrera (no la pestaña ni la página). Una
        pestaña desconocida cae en `pending`.
        """
        from itcj2.apps.titulatec.models import (
            Anexo, Modality, ProcessPhase as PP, TitulationProcess as TP,
        )
        from itcj2.apps.titulatec.utils.paging import (
            PAGE_SIZE, Page, normalize_q, paginate_query, parse_page,
        )
        from itcj2.core.models.program import Program
        from itcj2.core.models.user import User

        cls = AnexoInboxService
        per_page = per_page or PAGE_SIZE
        tab = tab if tab in cls.TABS else "pending"
        q = normalize_q(q)
        page_n = parse_page(page)

        vacio = {"rows": [], "page": Page(items=[], total=0, page=1, per_page=per_page),
                 "counts": {t: 0 for t in cls.TABS}, "tab": tab}
        base = cls._base(db, user_id, q=q, program_id=program_id)
        if base is None:
            return vacio
        preds = cls._predicates()

        # Contadores: UNA consulta con un COUNT FILTER por pestaña.
        agregados = [func.count(TP.id).filter(preds[t]) for t in cls.TABS]
        fila = base.order_by(None).with_entities(*agregados).one()
        counts = {t: int(c or 0) for t, c in zip(cls.TABS, fila)}

        cols = (
            TP.id.label("process_id"), TP.folio, User.first_name, User.middle_name,
            User.last_name, User.control_number, Program.name.label("program_name"),
            Modality.name.label("modality_name"), PP.updated_at.label("sent_at"),
            Anexo.folio.label("anexo_folio"),
        )
        lista = (
            base.with_entities(*cols)
            .outerjoin(Program, Program.id == TP.program_id)
            .outerjoin(Modality, Modality.id == TP.modality_id)
            .outerjoin(Anexo, Anexo.process_id == TP.id)
            .filter(preds[tab])
        )
        if tab == "pending":
            lista = lista.order_by(PP.updated_at.asc(), TP.id.asc())
        else:
            lista = lista.order_by(PP.updated_at.desc(), TP.id.desc())

        pg = paginate_query(lista, page_n, per_page)
        hoy = db_now().date()
        feriados = (NonWorkingDayService.holidays(db) if tab == "pending"
                    else frozenset())
        first = (pg.page - 1) * pg.per_page
        rows = []
        for i, r in enumerate(pg.items):
            nombre = " ".join(p for p in (r.last_name, r.middle_name) if p)
            nombre = f"{nombre}, {r.first_name}" if r.first_name else nombre
            days = level = pos = None
            if tab == "pending":
                pos = first + i + 1
                if r.sent_at is not None:
                    days = business_days_between(r.sent_at.date(), hoy, holidays=feriados)
                    level = cls._wait_level(days)
            rows.append({
                "process_id": r.process_id, "folio": r.folio,
                "student_name": nombre, "control_number": r.control_number,
                "program_name": r.program_name, "modality_name": r.modality_name,
                "anexo_folio": r.anexo_folio, "sent_at": r.sent_at,
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

        cls = AnexoInboxService
        base = cls._base(db, user_id, q=normalize_q(q), program_id=program_id)
        if base is None or tab not in cls.TABS:
            return False
        return (base.filter(cls._predicates()[tab], TP.id == int(process_id))
                .with_entities(TP.id).first()) is not None

    @staticmethod
    def next_pending(db: Session, user_id: int, *,
                     exclude_ids: Iterable[int] = (), q: str = "",
                     program_id: int | None = None) -> int | None:
        """`process_id` del siguiente «Por revisar» en la cola FIFO, o None.

        Salta `exclude_ids`; mismo alcance y orden que la pestaña.
        """
        from itcj2.apps.titulatec.models import ProcessPhase as PP, TitulationProcess as TP
        from itcj2.apps.titulatec.utils.paging import normalize_q

        cls = AnexoInboxService
        base = cls._base(db, user_id, q=normalize_q(q), program_id=program_id)
        if base is None:
            return None
        excl = [int(i) for i in exclude_ids]
        query = base.filter(cls._predicates()["pending"])
        if excl:
            query = query.filter(TP.id.notin_(excl))
        row = (query.with_entities(TP.id)
               .order_by(PP.updated_at.asc(), TP.id.asc()).first())
        return int(row[0]) if row else None
