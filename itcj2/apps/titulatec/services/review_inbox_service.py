"""Bandeja «Mis revisiones» del docente (fase 5, spec 2026-10-22 §8.2).

Solo LECTURA. Las conversaciones del docente salen de sus asignaciones de
sinodal VIGENTES (`SynodalAssignment.is_active`): un sustituido deja de ver el
proceso en cuanto lo sustituyen (§12). Tres pestañas:

- **Por revisar** (`por_revisar`): conversación abierta -proceso `active`,
  fase 5 `in_progress`, sin `closed_at`-, con versión vigente, su voto CUENTA
  según la regla de firma y todavía no votó ESA versión (D4: el voto de una
  versión anterior no cuenta). FIFO por la fecha de la versión VIGENTE (la de
  mayor `number`), desempate por `process_id`.
- **En curso** (`en_curso`): lo demás que no terminó: esperando la primera
  versión, ya votó la vigente, su voto no cuenta (solo comenta), regla
  desconocida o el proceso en pausa (un `on_hold` nunca entra a «Por revisar»,
  §6.5). Mismo orden FIFO; lo que no tiene versión va al final.
- **Completados** (`completados`): conversación cerrada (liberada), fase 5
  aprobada o inscripción revocada (`cancelled`, píldora «Revocada», §6.4). Del
  cierre más reciente al más viejo.

Quién vota sale SOLO de `ReviewService.counting_roles(ReviewService.rule_for(
process))` (§6.1): este módulo nunca lee la regla de la modalidad por su
cuenta. Una regla desconocida falla cerrado: su voto no cuenta y la fila lo
dice («Regla de firma desconocida»).

Dos pasadas, como Documentos y Procesos (CLAUDE.md de la app §18): el universo
del docente (una consulta, con búsqueda y alcance en SQL) se clasifica, se
cuenta y se ordena en Python -son sus asignaciones: decenas, no miles-; la
segunda pasada solo presenta la página: «N nuevos» (`unread_counts`, una
consulta) y el plazo con el calendario de días inhábiles (una consulta, solo
si alguna fila de la página lo necesita). Número FIJO de consultas: no crece
con los procesos.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased, contains_eager

from itcj2.apps.titulatec.utils.paging import PAGE_SIZE
from itcj2.core.utils.timezone import db_now

PHASE_CODE = "synodal_review"            # fase 5

TABS = ("por_revisar", "en_curso", "completados")

# Lo que dice la fila de «En curso» (por qué no está en «Por revisar»).
LABEL_PAUSED = "En pausa"
LABEL_INACTIVE = "Sin actividad"
LABEL_RULE_UNKNOWN = "Regla de firma desconocida"
LABEL_ONLY_COMMENTS = "Solo comentas"
LABEL_NO_VERSION = "Esperando la primera versión"
LABEL_APPROVED = "Aprobaste la versión {numero}"
LABEL_CHANGES = "Pediste cambios en la versión {numero}"

# Sin fecha (sin versión o sin cierre) va al final del orden.
_MAX = datetime.max
_MIN = datetime.min


def _nombre_lista(first, last, middle) -> str:
    """«PATERNO MATERNO, NOMBRE» (como las otras bandejas)."""
    apellidos = " ".join(p for p in (last, middle) if p)
    return f"{apellidos}, {first}" if first else apellidos


class ReviewInboxService:
    """Consultas de la bandeja «Mis revisiones»."""

    TABS = TABS
    PHASE_CODE = PHASE_CODE

    # ------------------------------------------------------------------
    # Pasada 1: el universo del docente
    # ------------------------------------------------------------------
    @staticmethod
    def _universe(db: Session, user_id: int, *, q) -> list:
        """Una fila por asignación VIGENTE del docente, con todo lo que la
        clasifica: el proceso (con su modalidad, para la regla), la
        conversación, el estado de la fase 5, la versión vigente y SU voto en
        ella, más los datos de pantalla del alumno. UNA consulta (más la del
        número de la fase en el catálogo)."""
        from itcj2.apps.titulatec.models import (
            Modality,
            ProcessChat,
            ProcessPhase,
            ReviewVersion,
            ReviewVote,
        )
        from itcj2.apps.titulatec.models import (
            SynodalAssignment as SA,
        )
        from itcj2.apps.titulatec.models import (
            TitulationProcess as TP,
        )
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        from itcj2.apps.titulatec.services.process_service import process_search
        from itcj2.core.models.program import Program
        from itcj2.core.models.user import User

        n5 = PhaseService.phase_number_for_code(db, PHASE_CODE)
        mis_procesos = select(SA.process_id).where(SA.user_id == user_id,
                                                   SA.is_active.is_(True))
        # Número de la versión vigente por proceso (solo los del docente).
        vigente = (db.query(ReviewVersion.process_id.label("process_id"),
                            func.max(ReviewVersion.number).label("number"))
                   .filter(ReviewVersion.process_id.in_(mis_procesos))
                   .group_by(ReviewVersion.process_id)
                   .subquery())
        ver = aliased(ReviewVersion)
        fase5 = aliased(ProcessPhase)

        query = (
            db.query(TP, ver,
                     SA.id.label("assignment_id"), SA.role,
                     ProcessChat.id.label("chat_id"), ProcessChat.closed_at,
                     fase5.status.label("phase5_status"),
                     ReviewVote.verdict.label("my_verdict"),
                     User.first_name, User.last_name, User.middle_name,
                     User.control_number, Program.name.label("program_name"))
            .select_from(SA)
            .join(TP, TP.id == SA.process_id)
            .outerjoin(Modality, Modality.id == TP.modality_id)
            .options(contains_eager(TP.modality))
            .outerjoin(User, User.id == TP.student_id)
            .outerjoin(Program, Program.id == TP.program_id)
            .outerjoin(ProcessChat, ProcessChat.process_id == TP.id)
            .outerjoin(fase5, and_(fase5.process_id == TP.id,
                                   fase5.phase_number == (n5 if n5 is not None else -1)))
            .outerjoin(vigente, vigente.c.process_id == TP.id)
            .outerjoin(ver, and_(ver.process_id == TP.id, ver.number == vigente.c.number))
            .outerjoin(ReviewVote, and_(ReviewVote.version_id == ver.id,
                                        ReviewVote.assignment_id == SA.id))
            .filter(SA.user_id == user_id, SA.is_active.is_(True))
        )
        busqueda = process_search(q)
        if busqueda is not None:
            query = query.filter(busqueda)
        return query.all()

    @staticmethod
    def _classify(row) -> dict:
        """Pestaña, regla y etiqueta de una fila del universo (puro)."""
        from itcj2.apps.titulatec.services.review_service import ReviewService
        from itcj2.apps.titulatec.services.synodal_service import ROLE_LABELS

        proc, version = row[0], row[1]
        try:
            counts = row.role in ReviewService.counting_roles(ReviewService.rule_for(proc))
            rule_error = False
        except ValueError:
            counts, rule_error = False, True

        revoked = proc.status == "cancelled"
        closed = (revoked or row.closed_at is not None
                  or row.phase5_status == "approved")
        open_ = (not closed and proc.status == "active"
                 and row.phase5_status == "in_progress")
        numero = version.number if version is not None else None

        if closed:
            tab, label = "completados", ("Revocada" if revoked else "Liberado")
        elif open_ and counts and numero is not None and row.my_verdict is None:
            tab, label = "por_revisar", "Por revisar"
        else:
            tab = "en_curso"
            if proc.status == "on_hold":
                label = LABEL_PAUSED
            elif not open_:
                label = LABEL_INACTIVE
            elif rule_error:
                label = LABEL_RULE_UNKNOWN
            elif not counts:
                label = LABEL_ONLY_COMMENTS
            elif numero is None:
                label = LABEL_NO_VERSION
            elif row.my_verdict == "approved":
                label = LABEL_APPROVED.format(numero=numero)
            else:
                label = LABEL_CHANGES.format(numero=numero)

        return {
            "tab": tab,
            "process_id": proc.id,
            "folio": proc.folio,
            "process_status": proc.status,
            "student_name": _nombre_lista(row.first_name, row.last_name, row.middle_name),
            "control_number": row.control_number,
            "program_name": row.program_name,
            "modality_name": proc.modality.name if proc.modality is not None else None,
            "role": row.role,
            "role_label": ROLE_LABELS.get(row.role, row.role),
            "counts": counts,
            "rule_error": rule_error,
            "chat_id": row.chat_id,
            "closed_at": row.closed_at,
            "version": numero,
            "version_at": version.uploaded_at if version is not None else None,
            "my_verdict": row.my_verdict,
            "state_label": label,
            "released": closed and not revoked,
            "revoked": revoked,
            # Segunda pasada (solo la página):
            "unread": 0, "due": None, "due_label": "", "semaphore": None,
            "version_label": "", "closed_label": "",
        }

    @staticmethod
    def _sort(rows: list, tab: str) -> list:
        """Orden de la pestaña; todo termina en `process_id` (regla de la
        paginación: sin desempate, las filas saltan entre páginas)."""
        if tab == "completados":
            # Del cierre más reciente al más viejo; sin fecha de cierre (una
            # revocada con la conversación abierta), al final.
            return sorted(rows, reverse=True,
                          key=lambda r: (r["closed_at"] is not None,
                                         r["closed_at"] or _MIN, r["process_id"]))
        # FIFO por la fecha de la versión vigente; sin versión, al final.
        return sorted(rows, key=lambda r: (r["version_at"] or _MAX, r["process_id"]))

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    @staticmethod
    def list(db: Session, user_id: int, *, tab: str, q: str | None = None,
             page: int | str = 1, per_page: int = PAGE_SIZE) -> dict:
        """Una página de la bandeja + los contadores de las 3 pestañas.

        Devuelve `{"page": Page, "counts": {"por_revisar", "en_curso",
        "completados"}, "tab": tab}`. Cada fila de `page.items` es un dict:
        `process_id, folio, process_status, student_name, control_number,
        program_name, modality_name, role, role_label, counts, rule_error,
        chat_id, version, version_at, version_label, my_verdict, state_label,
        released, revoked, closed_at, closed_label, unread` («N nuevos») y,
        solo en «Por revisar», `due`, `due_label`, `semaphore` (`ok|warn|late`,
        plazo de §9.3 con el calendario de días inhábiles). `counts` respeta la
        búsqueda (no la pestaña ni la página). Pestaña desconocida ->
        `por_revisar`; página fuera de rango -> la última.
        """
        from itcj2.apps.titulatec.utils.paging import (
            normalize_q,
            paginate_list,
            parse_page,
        )

        cls = ReviewInboxService
        tab = tab if tab in TABS else "por_revisar"
        per_page = per_page or PAGE_SIZE
        filas = [cls._classify(r) for r in cls._universe(db, user_id, q=normalize_q(q))]

        counts = {t: 0 for t in TABS}
        for f in filas:
            counts[f["tab"]] += 1
        elegidas = cls._sort([f for f in filas if f["tab"] == tab], tab)
        pg = paginate_list(elegidas, parse_page(page), per_page)
        cls._present(db, user_id, pg.items, tab=tab)
        return {"page": pg, "counts": counts, "tab": tab}

    # ------------------------------------------------------------------
    # Pasada 2: solo la página
    # ------------------------------------------------------------------
    @staticmethod
    def _present(db: Session, user_id: int, rows: list, *, tab: str) -> None:
        """«N nuevos», fechas legibles y, en «Por revisar», el plazo con su
        semáforo. A lo más 2 consultas, sin importar cuántas filas."""
        from itcj2.apps.titulatec.services.review_service import ReviewService
        from itcj2.apps.titulatec.utils.dates_es import dia_largo

        if not rows:
            return
        nuevos = ReviewService.unread_counts(db, user_id,
                                             [r["chat_id"] for r in rows if r["chat_id"]])
        con_plazo = [r for r in rows if tab == "por_revisar" and r["version_at"] is not None]
        feriados = frozenset()
        if con_plazo:
            from itcj2.apps.titulatec.services.non_working_day_service import (
                NonWorkingDayService,
            )
            feriados = NonWorkingDayService.holidays(db)
        hoy = db_now().date()
        for r in rows:
            r["unread"] = int(nuevos.get(r["chat_id"], 0)) if r["chat_id"] else 0
            if r["version_at"] is not None:
                r["version_label"] = dia_largo(r["version_at"])
            if r["closed_at"] is not None:
                r["closed_label"] = dia_largo(r["closed_at"])
        for r in con_plazo:
            # `due_date` lee solo `uploaded_at` de la versión: el plazo NO se
            # guarda, se calcula con el calendario de hoy (§5, §9.3).
            due = ReviewService.due_date(SimpleNamespace(uploaded_at=r["version_at"]),
                                         holidays=feriados)
            r["due"] = due
            r["due_label"] = dia_largo(due)
            r["semaphore"] = ReviewService.semaphore(due, today=hoy, holidays=feriados)
