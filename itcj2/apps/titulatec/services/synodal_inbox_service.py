"""Bandeja «Sinodales» del departamento académico (fase 4, spec §9).

Solo LECTURA: arma las pestañas, sus contadores y el universo de
`?selected=`. Asignar y sustituir viven en `SynodalService`.

- **Por asignar** (`pending`): procesos `active` en la fase
  `synodal_assignment`, sin sinodales vigentes, en orden FIFO por
  `ProcessPhase.started_at` de la fase 4 (desempate por `process_id`), con
  posición y semáforo de días hábiles (ámbar >= 3, rojo >= 5).
- **En Anexo III** (`anexo`, fase 6 de la spec 2026-10-22): procesos `active`
  con `current_phase` en la fase `anexo_iii`; vacia si el Anexo no se opera.
- **Asignados** (`assigned`): procesos no revocados con sinodales vigentes y
  la fase 5 (`synodal_review`) sin aprobar: es la ventana en la que se
  sustituye y se descarga el oficio.

Alcance por DEPARTAMENTO, no por puesto de Servicios Escolares (spec §7 y
R-D): `manageable_departments` da los departamentos que el usuario opera
(todos los mapeados con `process.api.read.all`; si no, los que dirige o
coordina) y la bandeja lista las carreras mapeadas a ellos. Una carrera sin
departamento no sale: nadie puede asignarle sinodales hasta mapearla en
«Carreras por departamento». El mapeo se lee al vuelo (remapear mueve la
carrera de bandeja, RF4).

Mismo patrón que `FormatBInboxService`: alcance ANTES de contar y paginar,
búsqueda con `process_search`, desempate por `process_id` en todo orden
paginado y un número FIJO de consultas por página.
"""
from __future__ import annotations

import dataclasses

from sqlalchemy import and_, exists, false, func
from sqlalchemy.orm import Session, aliased

from itcj2.apps.titulatec.services.non_working_day_service import NonWorkingDayService
from itcj2.apps.titulatec.utils.business_days import business_days_between
from itcj2.core.utils.timezone import db_now

PHASE_CODE = "synodal_assignment"        # fase 4: la que se asigna aquí
REVIEW_PHASE_CODE = "synodal_review"     # fase 5: mientras no se apruebe, «Asignados»


class SynodalInboxService:
    """Consultas de la bandeja de sinodales."""

    TABS = ("pending", "assigned", "anexo")
    WAIT_WARN_DAYS = 3   # ámbar desde aquí (días hábiles)
    WAIT_LATE_DAYS = 5   # rojo desde aquí

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _wait_level(days: int) -> str:
        if days >= SynodalInboxService.WAIT_LATE_DAYS:
            return "late"
        if days >= SynodalInboxService.WAIT_WARN_DAYS:
            return "warn"
        return "ok"

    @staticmethod
    def departments(db: Session, user_id: int) -> list[dict]:
        """Departamentos que el usuario opera, `[{"id","code","name"}]` por nombre
        (`scope_service.manageable_departments`, R-D)."""
        from itcj2.apps.titulatec.services.scope_service import manageable_departments

        return manageable_departments(db, user_id)

    @staticmethod
    def _department_ids(db: Session, user_id: int, department_id) -> list[int]:
        """Ids de los departamentos del universo: los que opera, acotados al
        `department_id` del filtro si lo hay (uno ajeno deja la lista vacía)."""
        ids = {d["id"] for d in SynodalInboxService.departments(db, user_id)}
        if department_id is not None:
            ids &= {int(department_id)}
        return sorted(ids)

    @staticmethod
    def programs(db: Session, user_id: int, *, department_id=None) -> list[dict]:
        """Carreras del filtro: las mapeadas a los departamentos del universo,
        por nombre. Una consulta (más la de los departamentos)."""
        from itcj2.apps.titulatec.models import ProgramDepartment
        from itcj2.core.models.program import Program

        dept_ids = SynodalInboxService._department_ids(db, user_id, department_id)
        if not dept_ids:
            return []
        filas = (db.query(Program.id, Program.name)
                 .join(ProgramDepartment, ProgramDepartment.program_id == Program.id)
                 .filter(ProgramDepartment.department_id.in_(dept_ids))
                 .order_by(Program.name, Program.id).all())
        return [{"id": i, "name": n} for i, n in filas]

    @staticmethod
    def _phase_numbers(db: Session) -> tuple[int | None, int | None]:
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        return (PhaseService.phase_number_for_code(db, PHASE_CODE),
                PhaseService.phase_number_for_code(db, REVIEW_PHASE_CODE))

    @staticmethod
    def _anexo_number(db: Session) -> int | None:
        """Numero de la fase 6 solo si el Anexo III se opera (corte); None deja
        la pestana «En Anexo III» vacia (falla cerrado)."""
        from itcj2.apps.titulatec.services.anexo_service import AnexoService

        return AnexoService.phase_number(db) if AnexoService.operable(db) else None

    @staticmethod
    def _tab_predicates(n4: int | None, n5: int | None, n6: int | None = None) -> dict:
        """Predicado SQL de cada pestaña (mismo para la lista, los contadores y
        `contains`). Sin la fase en el catálogo, la pestaña queda vacía."""
        from itcj2.apps.titulatec.models import (
            ProcessPhase, SynodalAssignment, TitulationProcess as TP,
        )

        con_sinodales = exists().where(SynodalAssignment.process_id == TP.id,
                                       SynodalAssignment.is_active.is_(True))
        revision_terminada = (exists().where(ProcessPhase.process_id == TP.id,
                                             ProcessPhase.phase_number == n5,
                                             ProcessPhase.status == "approved")
                              if n5 is not None else false())
        pendiente = (and_(TP.status == "active", TP.current_phase == n4, ~con_sinodales)
                     if n4 is not None else false())
        return {
            "pending": pendiente,
            "assigned": and_(TP.status != "cancelled", con_sinodales, ~revision_terminada),
            "anexo": (and_(TP.status == "active", TP.current_phase == n6)
                      if n6 is not None else false()),
        }

    @staticmethod
    def _base(db: Session, user_id: int, *, q, program_id, department_id):
        """Query de procesos de carreras mapeadas a los departamentos del
        universo + búsqueda + carrera, o `None` si el alcance no deja ver nada.
        `program_id IS NULL` queda fuera solo (el join con el mapeo lo exige)."""
        from itcj2.apps.titulatec.models import ProgramDepartment, TitulationProcess as TP
        from itcj2.apps.titulatec.services.process_service import process_search
        from itcj2.core.models.user import User

        dept_ids = SynodalInboxService._department_ids(db, user_id, department_id)
        if not dept_ids:
            return None
        query = (
            db.query(TP)
            .join(ProgramDepartment, ProgramDepartment.program_id == TP.program_id)
            .outerjoin(User, User.id == TP.student_id)
            .filter(ProgramDepartment.department_id.in_(dept_ids))
        )
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
             program_id: int | None = None, department_id: int | None = None,
             page: str | int = "", per_page: int | None = None) -> dict:
        """Una página de la bandeja + contadores de las 2 pestañas.

        Filas: `process_id, folio, student_name, control_number, program_name,
        department_name, waited_days, wait_level, position` (los tres últimos
        solo en «Por asignar»; None en «Asignados») y `assigned_at` (aprobación
        de la fase 4, solo en «Asignados»). `counts` respeta búsqueda, carrera y
        departamento (no la pestaña ni la página). Una pestaña desconocida cae
        en `pending`.
        """
        from itcj2.apps.titulatec.models import ProcessPhase, TitulationProcess as TP
        from itcj2.apps.titulatec.models import ProgramDepartment
        from itcj2.apps.titulatec.utils.paging import (
            PAGE_SIZE, Page, normalize_q, paginate_query, parse_page,
        )
        from itcj2.core.models.department import Department
        from itcj2.core.models.program import Program
        from itcj2.core.models.user import User

        cls = SynodalInboxService
        per_page = per_page or PAGE_SIZE
        tab = tab if tab in cls.TABS else "pending"
        q = normalize_q(q)
        page_n = parse_page(page)

        vacio = {"rows": [], "page": Page(items=[], total=0, page=1, per_page=per_page),
                 "counts": {t: 0 for t in cls.TABS}, "tab": tab}
        base = cls._base(db, user_id, q=q, program_id=program_id, department_id=department_id)
        if base is None:
            return vacio
        n4, n5 = cls._phase_numbers(db)
        preds = cls._tab_predicates(n4, n5, cls._anexo_number(db))

        # Contadores: UNA consulta con un COUNT FILTER por pestaña.
        agregados = [func.count(TP.id).filter(preds[t]) for t in cls.TABS]
        fila = base.order_by(None).with_entities(*agregados).one()
        counts = {t: int(c or 0) for t, c in zip(cls.TABS, fila)}

        fase4 = aliased(ProcessPhase)
        cols = (
            TP.id.label("process_id"), TP.folio, User.first_name, User.middle_name,
            User.last_name, User.control_number, Program.name.label("program_name"),
            Department.name.label("department_name"),
            fase4.started_at, fase4.completed_at,
        )
        lista = (
            base.with_entities(*cols)
            .outerjoin(Program, Program.id == TP.program_id)
            .outerjoin(Department, Department.id == ProgramDepartment.department_id)
            .outerjoin(fase4, and_(fase4.process_id == TP.id, fase4.phase_number == n4))
            .filter(preds[tab])
        )
        if tab == "pending":
            lista = lista.order_by(fase4.started_at.asc().nulls_last(), TP.id.asc())
        else:
            lista = lista.order_by(fase4.completed_at.desc().nulls_last(), TP.id.desc())

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
                if r.started_at is not None:
                    days = business_days_between(r.started_at.date(), hoy,
                                                 holidays=feriados)
                    level = cls._wait_level(days)
            rows.append({
                "process_id": r.process_id, "folio": r.folio,
                "student_name": nombre, "control_number": r.control_number,
                "program_name": r.program_name, "department_name": r.department_name,
                "started_at": r.started_at,
                "assigned_at": r.completed_at if tab == "assigned" else None,
                "waited_days": days, "wait_level": level, "position": pos,
            })
        return {"rows": rows, "page": dataclasses.replace(pg, items=rows),
                "counts": counts, "tab": tab}

    @staticmethod
    def contains(db: Session, user_id: int, process_id: int, *, tab: str, q: str = "",
                 program_id: int | None = None, department_id: int | None = None) -> bool:
        """¿`process_id` está en la pestaña, con la búsqueda, carrera,
        departamento y alcance dados? Mismo `_base` y mismo predicado que la
        lista; una consulta (más las del alcance)."""
        from itcj2.apps.titulatec.models import TitulationProcess as TP
        from itcj2.apps.titulatec.utils.paging import normalize_q

        cls = SynodalInboxService
        if tab not in cls.TABS:
            return False
        base = cls._base(db, user_id, q=normalize_q(q), program_id=program_id,
                         department_id=department_id)
        if base is None:
            return False
        preds = cls._tab_predicates(*cls._phase_numbers(db), cls._anexo_number(db))
        return (base.filter(preds[tab], TP.id == int(process_id))
                .with_entities(TP.id).first()) is not None
