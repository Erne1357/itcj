"""Motor compartido de constancias (no adeudo de biblioteca y liberación de
encuesta de egresados). Spec `2026-10-01-titulatec-biblioteca-caja-design.md`
§4.5, D7/D8/D15/D21/D22, §5 invariante 5.

`CertificateService` es el ÚNICO escritor de `titulatec_certificates` /
`titulatec_certificate_batches` / `titulatec_certificate_counters` (igual que
`SurveyReviewService` lo es de `titulatec_survey_reviews`). Una fila nunca se
borra: se ANULA (`void`) y el folio nunca se reutiliza, aunque se vuelva a
emitir (`issue`) para el mismo `source_ref` — eso saca un folio NUEVO. El PDF
no vive aquí: `utils/certificate_pdf.py::render_certificates_pdf` lo arma a
partir de los datos ya CONGELADOS en cada fila, siempre que haga falta.

Folio por SEMESTRE desde `2026-10-05-titulatec-folios-design.md` §3.1
(migración `tt20261005c`): `{PREFIJO}-{AAAA}{A|B}-{NNNN}` (`BIB-2026B-0001`,
`GTV-2026A-0001`), consecutivo por tipo + semestre. `A` = enero-junio, `B` =
julio-diciembre (`semester_key`). Una liberación normal folia en el semestre
de la EMISIÓN (`semester=None` → `semester_key(db_now())`); las previas y el
legado pasan el semestre ANTERIOR a su registro (`previous_semester_key`).

Desde la Tarea 2 de `2026-10-02-titulatec-constancias-y-pendientes-design.md`
(§3.2, E1/E6/E7, §5 invariante 4) también es el ÚNICO lugar que calcula el
ESTADO DE IMPRESIÓN: `print_status_map` (por `source_ref`, hasta 2 consultas
por llamada — lo consumen las bandejas de Biblioteca/GTV, UNA llamada por
página, y las dos vistas de SE, UNA llamada por vista para encuesta y no
adeudo juntos, Ruling R14) y `voided_after_print` (por `kind`, para la página
de Constancias). Las dos son de solo lectura y no tocan `TitulationProcess` ni
ninguna tabla de liberación — eso lo cuidan `LibraryClearanceService`/
`SurveyReviewService`/`ClearanceGate`. En todo el servicio, las únicas
CONSULTAS a `TitulationProcess` son dos `EXISTS` de «proceso revocado»:
`_pending_criteria` (el `NOT EXISTS` de «Por imprimir»: `pending`,
`pending_count` y `create_batch`, Ruling R26) y la bandera `revoked` de
`list_folios` (D8, abajo); `print_status_map` y `voided_after_print` no las
usan. `issue()`, además, lee la instancia de proceso que le pasa el dueño
(alumno, convocatoria y su periodo, carrera) para congelar sus datos en la
constancia.

`list_folios` (spec folios 2026-10-05 §3.6) es la lectura de la pestaña «Folios»
(`pages/certificates_admin.py`): por `kind`, con búsqueda por folio / control /
nombre, filtro de estado (`FOLIO_ESTADOS`) y paginación; lee `titulatec_
certificates` y, solo para la bandera `revoked` por fila (D8: el folio de una
inscripción revocada se MARCA, no se anula), un `EXISTS` al estado del proceso
dentro del mismo SELECT.

Reglas fijas, iguales a `SurveyReviewService`:

* Métodos `@staticmethod`, `db: Session` primero, imports de modelos y de
  otros services SIEMPRE locales dentro de cada método (ciclos).
* `issue`/`void` NO commitean — son parte de la transacción del llamador
  (el gancho de GTV en `survey_review_service.py`, y `LibraryClearanceService`
  en la Tarea 4). `create_batch` SÍ commitea: imprimir un lote es su propia
  operación, sin nada más pendiente en la misma transacción.
* `ValueError` = regla de negocio, mensaje en español ya listo para el
  usuario.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.utils.paging import PAGE_SIZE, Page
from itcj2.core.utils.timezone import db_now

# Semestre del folio: año de 4 cifras + `A` (enero-junio) o `B`
# (julio-diciembre). `re.ASCII` para que `\d` no acepte dígitos Unicode, y se
# usa con `fullmatch` (un `$` con `match` dejaría pasar un «\n» final).
SEMESTER_RE = re.compile(r"^\d{4}[AB]$", re.ASCII)

# Filtro de estado de la pestaña «Folios» (`list_folios`, spec folios
# 2026-10-05 §3.6), en el orden en que la página pinta sus chips. Cualquier
# otro valor cae en `vigentes`.
FOLIO_ESTADOS = ("vigentes", "anulados", "todos")


def semester_key(when: date | datetime) -> str:
    """Semestre del folio para una fecha: mes 1-6 da `A`, mes 7-12 da `B`
    (`2026-06-30` → `2026A`, `2026-07-01` → `2026B`). Acepta `date` o
    `datetime` (solo lee año y mes)."""
    return f"{when.year}{'A' if when.month <= 6 else 'B'}"


def previous_semester_key(when: date | datetime) -> str:
    """Semestre ANTERIOR al de `when` (previas y legado, decisión D5/D6 del
    spec 2026-10-05): `A` de Y da `(Y-1)B`; `B` de Y da `YA`
    (`2026-10-05` → `2026A`, `2027-02-10` → `2026B`)."""
    if when.month <= 6:
        return f"{when.year - 1}B"
    return f"{when.year}A"


def printing_enabled() -> bool:
    """¿Está encendida la impresión de constancias? (spec folios 2026-10-05
    §3.5). Lee `TITULATEC_CERTIFICATE_PRINTING` de `get_settings()` en CADA
    llamada, sin guardarlo en una constante de módulo: así los tests parchean
    el atributo del singleton (`printing_on` del conftest) y un reinicio del
    proceso es lo único que hace falta en producción.

    Apagado (el default), los lotes y su PDF responden 404
    (`pages/certificates_admin.py`) y la celda de constancias
    (`certificate_cell`, `_macros.html`) pinta solo el folio. El código de los
    lotes, el PDF y `print_status_map` NO se borra ni cambia (spec D2). Se
    registra como global de Jinja `tt_certificate_printing`
    (`pages/nav.py`) porque los globales sí llegan a las macros importadas sin
    contexto, y las variables de contexto no."""
    from itcj2.config import get_settings

    return bool(get_settings().TITULATEC_CERTIFICATE_PRINTING)


# Prefijo, título del documento, departamento que lo firma y la frase que
# completa "se hace constar que FULANO ...". Textos VERBATIM del spec §4.5 —
# no se parafrasean: son lo que se imprime y se entrega a SE.
CERT_KINDS: dict[str, dict] = {
    "library_clearance": {
        "prefix": "BIB",
        "title": "CONSTANCIA DE NO ADEUDO",
        "department": "Centro de Información",
        "phrase": (
            "no tiene adeudo con el Centro de Información (biblioteca) del "
            "Instituto Tecnológico de Ciudad Juárez"
        ),
    },
    "survey_release": {
        "prefix": "GTV",
        "title": "CONSTANCIA DE LIBERACIÓN DE ENCUESTA DE EGRESADOS",
        "department": "Gestión Tecnológica y Vinculación",
        "phrase": "contestó la encuesta de egresados y le fue liberada",
    },
}

# Sufijo del código de periodo (AAAAS, 5 caracteres) -> mitad de año (spec
# §4.5). Los códigos SINTÉTICOS de prueba (`conftest._period_code`) miden 6
# caracteres a propósito, para NUNCA calzar aquí y ejercer el respaldo
# (`period.name`) sin pisar un periodo real por accidente.
_SEMESTER_LABELS = {"1": "Enero-Junio", "2": "Verano", "3": "Agosto-Diciembre"}

# Tope de columna de `Certificate.period_label` (String(40), Tarea 1 fix
# round 1). `issue()` recorta a esto SIEMPRE, aunque `period_label()` por sí
# sola devuelva algo más largo (el respaldo `period.name` es String(100)).
_PERIOD_LABEL_MAX = 40


class CertificateService:
    """Único dueño de `titulatec_certificates` / `_certificate_batches` /
    `_certificate_counters`. Emite el folio por tipo + semestre
    (`BIB-2026B-0001`, `issue`/`_next_number`, spec 2026-10-05 §3.1). También
    expone el estado de impresión de solo lectura (`print_status_map`,
    `voided_after_print`) para que otras vistas lo lean sin tocar la tabla
    directo (Tarea 2 de
    `2026-10-02-titulatec-constancias-y-pendientes-design.md`)."""

    # ------------------------------------------------------------- emisión
    @staticmethod
    def issue(db: Session, *, kind: str, process, source_ref: str,
              actor_id: int | None, semester: str | None = None) -> Certificate:
        """Emite una constancia NUEVA con folio propio y datos CONGELADOS del
        proceso en este momento (D7/D21/D22). No consulta antes si
        `source_ref` ya tiene una vigente: «a lo más UNA vigente por
        `source_ref`» (§5 invariante 5) la cuida primero el LLAMADOR, que
        conoce su propia máquina de estados (p. ej.
        `SurveyReviewService.approve` solo emite desde `in_review`/`rejected`,
        nunca dos veces sobre una ya `approved`), y la respalda la base con el
        UNIQUE parcial `uq_titulatec_certificates_live_source` (Ruling R29): un
        llamador que se equivocara truena con `IntegrityError` en el `flush()`
        de aquí, nunca deja dos vigentes. Sin commit — la transacción del
        llamador decide.

        `semester` (spec 2026-10-05 §3.1): `None` folia en el semestre de la
        emisión (`semester_key(db_now())`); las previas y el legado pasan el
        suyo (`previous_semester_key(...)`). Un valor que no cumpla
        `SEMESTER_RE` truena con `ValueError` ANTES de tocar el contador.
        `actor_id=None` es válido (importaciones y CLI): `issued_by_id` queda
        NULL. `issued_at` es SIEMPRE la hora real de emisión, aunque el folio
        caiga en un semestre anterior.
        """
        from itcj2.apps.titulatec.models.certificate import Certificate
        from itcj2.core.models.program import Program

        if kind not in CERT_KINDS:
            raise ValueError(f"Tipo de constancia desconocido: {kind!r}.")
        if semester is not None and not (isinstance(semester, str)
                                         and SEMESTER_RE.fullmatch(semester)):
            raise ValueError(
                f"Semestre de folio inválido: {semester!r} (se espera el año "
                f"y A o B, p. ej. 2026A o 2026B).")

        student = process.student
        period = process.cohort.academic_period if process.cohort else None
        program = db.get(Program, process.program_id) if process.program_id else None

        ahora = db_now()
        semestre = semester if semester is not None else semester_key(ahora)
        numero = CertificateService._next_number(db, kind, semestre)
        etiqueta = CertificateService.period_label(period)[:_PERIOD_LABEL_MAX]

        cert = Certificate(
            kind=kind,
            number=numero,
            process_id=process.id,
            source_ref=source_ref,
            control_number=(student.control_number or "")[:20],
            student_name=(student.full_name or "")[:200],
            program_name=(program.name if program else "")[:200],
            period_label=etiqueta,
            issued_at=ahora,
            issued_by_id=actor_id,
        )
        db.add(cert)
        db.flush()          # el llamador puede necesitar cert.id/number de inmediato
        return cert

    @staticmethod
    def _next_number(db: Session, kind: str, semester: str) -> str:
        """Folio atómico: `INSERT … ON CONFLICT (kind, semester) DO UPDATE
        SET last_value = last_value + 1 RETURNING last_value`, UNA sola
        sentencia (segura con PgBouncer, spec §4.5). Nace en 1 la primera vez
        que se emite ese (`kind`, `semester`); anular una constancia NUNCA
        libera su número, y volver a emitir para el mismo origen saca el
        SIGUIENTE. Devuelve `{PREFIJO}-{semester}-{NNNN}` (`BIB-2026B-0001`).
        No valida `semester`: lo hace `issue` antes de llamar aquí."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from itcj2.apps.titulatec.models.certificate import CertificateCounter

        tabla = CertificateCounter.__table__
        stmt = (
            pg_insert(tabla)
            .values(kind=kind, semester=semester, last_value=1)
            .on_conflict_do_update(
                index_elements=["kind", "semester"],
                set_={"last_value": tabla.c.last_value + 1},
            )
            .returning(tabla.c.last_value)
        )
        n = db.execute(stmt).scalar_one()
        prefix = CERT_KINDS[kind]["prefix"]
        return f"{prefix}-{semester}-{n:04d}"

    @staticmethod
    def void(db: Session, *, source_ref: str, actor_id: int,
             reason: str | None) -> Certificate | None:
        """Anula la constancia VIGENTE de `source_ref`, si la hay. `None` si
        no hay ninguna que anular — NO es un error: desde 2026-10-05 las
        previas y el legado también llevan folio (`register_prior` o el
        backfill de `FolioBackfillService`), pero una registrada ANTES y que
        el backfill aún no folia no tiene nada que anular. Nunca borra ni
        libera el folio: volver a `issue()` después saca uno nuevo. Sin commit.
        """
        from itcj2.apps.titulatec.models.certificate import Certificate

        cert = (
            db.query(Certificate)
            .filter_by(source_ref=source_ref, voided_at=None)
            .with_for_update()
            .first()
        )
        if cert is None:
            return None
        cert.voided_at = db_now()
        cert.voided_by_id = actor_id
        cert.void_reason = (reason or "").strip() or None
        return cert

    # --------------------------------------------------------------- lectura
    @staticmethod
    def _pending_criteria(kind: str) -> tuple:
        """«Por imprimir» de `kind`, UNA sola definición para `pending`,
        `pending_count` y `create_batch` (antes copiada en los tres):

        * suelta (sin lote) y vigente (sin anular) — mismo predicado que el
          índice parcial `ix_titulatec_certificates_pending_print`;
        * y su proceso NO está revocado (Ruling R26, M3 de la revisión
          final): `ProcessService.cancel` no anula las constancias, y SE no
          debe recibir papeles de una inscripción dada de baja. `NOT EXISTS`
          y no un JOIN: el `FOR UPDATE SKIP LOCKED` de `create_batch` bloquea
          solo las constancias, nunca el proceso.
        """
        from sqlalchemy import exists

        from itcj2.apps.titulatec.models import TitulationProcess
        from itcj2.apps.titulatec.models.certificate import Certificate

        revocado = (exists()
                    .where(TitulationProcess.id == Certificate.process_id,
                           TitulationProcess.status == "cancelled")
                    .correlate(Certificate))
        return (Certificate.kind == kind,
                Certificate.batch_id.is_(None),
                Certificate.voided_at.is_(None),
                ~revocado)

    @staticmethod
    def pending(db: Session, kind: str) -> list[Certificate]:
        """«Por imprimir»: constancias de `kind` sueltas (sin lote),
        vigentes (sin anular) y de un proceso no revocado, FIFO por
        `issued_at` (`_pending_criteria`)."""
        from itcj2.apps.titulatec.models.certificate import Certificate

        return (
            db.query(Certificate)
            .filter(*CertificateService._pending_criteria(kind))
            .order_by(Certificate.issued_at.asc(), Certificate.id.asc())
            .all()
        )

    @staticmethod
    def pending_count(db: Session, kind: str) -> int:
        """`len(pending(...))` sin traer las filas — para quien solo
        necesite el número, sin pagar el costo de traer las filas completas.
        La página de Constancias YA trae `pending()` para listar «Quiénes»
        (Tarea 2/E7, `pages/certificates_admin.py::_body_ctx`) y deriva su
        badge «Por imprimir (N)» de `len(pending_rows)` en vez de llamar
        este método aparte — así evita una segunda consulta con el MISMO
        predicado (`_pending_criteria`) que `pending()` ya resolvió."""
        from itcj2.apps.titulatec.models.certificate import Certificate

        total = (
            db.query(func.count(Certificate.id))
            .filter(*CertificateService._pending_criteria(kind))
            .scalar()
        )
        return total or 0

    @staticmethod
    def list_folios(db: Session, *, kind: str, q: str | None = None,
                    estado: str = "vigentes", per_page: int = PAGE_SIZE,
                    page: int = 1) -> Page:
        """Página de folios de `kind` para la pestaña «Folios» (spec folios
        2026-10-05 §3.6): `issued_at DESC, id DESC`, paginada con
        `utils/paging.paginate_query` (una página fuera de rango cae en la
        última válida). Los datos del egresado salen de lo CONGELADO al emitir
        (invariante 4: ni las tablas de liberación ni el proceso, salvo la
        bandera `revoked` de D8, abajo).

        `estado`: `vigentes` (sin anular), `anulados` o `todos`; cualquier
        otro valor (incluido `None`) cae en `vigentes`. `q` se normaliza aquí
        con `normalize_q` (`strip()`, 100 caracteres, vacío o solo espacios =
        sin filtro) y busca en `number` y `control_number` (también en
        MAYÚSCULA, la forma de `CONTROL_NUMBER_RE`) con la búsqueda ENTERA, y en
        `student_name` palabra por palabra: cada palabra de `q` tiene que estar
        en el nombre, en cualquier orden (AND de un `ILIKE` por palabra), así
        «Juan Pérez» encuentra «PÉREZ GÓMEZ JUAN» (el nombre se congela
        apellidos primero). Todo `ILIKE` lleva la diagonal invertida, `%` y `_`
        escapados (`like_pattern`).

        Los items son dicts, no filas del ORM: `number`, `student_name`,
        `control_number`, `program_name`, `issued_at`, `voided_at`,
        `void_reason` y `revoked` (formatear fechas es tarea de quien pinte).
        Un `kind` fuera de `CERT_KINDS` da `ValueError`.

        `revoked` (D8, spec folios 2026-10-05): `True` si el proceso del folio
        está `cancelled` (inscripción revocada). Se MARCA, no se anula: el folio
        sigue vigente, y si el proceso se reactiva la bandera se apaga sola.
        Sale de UN `EXISTS` correlacionado en la lista de columnas del mismo
        SELECT (sin `JOIN` y sin consultas por fila): la invariante 4 solo se
        relaja para esto -- las tablas de liberación siguen sin leerse.
        """
        from dataclasses import replace

        from sqlalchemy import and_, exists, or_

        from itcj2.apps.titulatec.models import TitulationProcess
        from itcj2.apps.titulatec.models.certificate import Certificate
        from itcj2.apps.titulatec.utils.paging import like_pattern, normalize_q, paginate_query

        if kind not in CERT_KINDS:
            raise ValueError(f"Tipo de constancia desconocido: {kind!r}.")

        revocado = (exists()
                    .where(TitulationProcess.id == Certificate.process_id,
                           TitulationProcess.status == "cancelled")
                    .correlate(Certificate))
        query = (
            db.query(Certificate.number, Certificate.student_name,
                     Certificate.control_number, Certificate.program_name,
                     Certificate.issued_at, Certificate.voided_at,
                     Certificate.void_reason, revocado.label("revoked"))
            .filter(Certificate.kind == kind)
        )
        if estado == "anulados":
            query = query.filter(Certificate.voided_at.isnot(None))
        elif estado != "todos":
            query = query.filter(Certificate.voided_at.is_(None))

        q = normalize_q(q)
        if q is not None:
            patron = like_pattern(q)
            por_nombre = and_(*(Certificate.student_name.ilike(like_pattern(palabra),
                                                               escape="\\")
                                for palabra in q.split()))
            query = query.filter(or_(
                Certificate.number.ilike(patron, escape="\\"),
                Certificate.control_number.ilike(patron, escape="\\"),
                Certificate.control_number == q.upper(),
                por_nombre,
            ))

        # Desempate por `id` (§18 regla 1): `issued_at` empata dentro de una
        # misma transacción (`NOW()`) y entre lotes de una importación.
        query = query.order_by(Certificate.issued_at.desc(), Certificate.id.desc())
        pagina = paginate_query(query, page, per_page)
        return replace(pagina, items=[fila._asdict() for fila in pagina.items])

    # ------------------------------------------------------- estado de impresión
    @staticmethod
    def print_status_map(db: Session, source_refs: list[str]) -> dict[str, dict | None]:
        """Estado de impresión de cada `source_ref`, para que las bandejas de
        Biblioteca/GTV y las vistas de SE pinten la celda «Constancia» con UNA
        sola llamada por página (spec §3.2/§4.5, invariante 2) — a lo más 2
        consultas por llamada, sin importar cuántos `source_refs` traiga
        (lista vacía -> `{}` sin tocar la base). `source_refs` repetidos se
        de-duplican solos: el resultado es un dict, una llave por ref único.

        Cada llave del resultado trae SIEMPRE uno de estos dos valores:

        * si `source_ref` tiene una constancia VIGENTE (`voided_at IS NULL`,
          a lo más una por origen — índice parcial
          `uq_titulatec_certificates_live_source`): `number`/`issued_at`/
          `batch_id` de esa constancia, `batch_at` = `CertificateBatch.
          created_at` del lote (`None` si sigue suelta), `printed = batch_id
          is not None` y `voided_printed = None` — SIEMPRE, aunque una
          constancia anulada anterior del mismo origen sí se haya impreso: la
          vigente manda; esa anulada impresa aparece aparte en
          `voided_after_print`, nunca aquí.
        * si NO hay vigente pero sí una anulada que alcanzó a entrar a un
          lote: `number=None`, `issued_at=None`, `printed=False`,
          `batch_id=None`, `batch_at=None` y `voided_printed` con los datos
          de la anulada CON lote más reciente (`number`, `batch_id`,
          `batch_at`, `voided_at`, `void_reason`) — si existe una anulada
          todavía más reciente pero SIN lote, se ignora para este cálculo
          (nunca se imprimió, no hay papel que retirar).

        `None` (no un dict) cuando `source_ref` no tiene vigente NI ninguna
        anulada con lote — nunca tuvo constancia, o las que tuvo se anularon
        sin haberse impreso nunca.

        Invariante 4: no lee `TitulationProcess` ni ninguna tabla de
        liberación — solo `titulatec_certificates` / `_certificate_batches`.
        """
        from itcj2.apps.titulatec.models.certificate import Certificate, CertificateBatch

        refs = list(dict.fromkeys(source_refs))
        if not refs:
            return {}

        vigentes = (
            db.query(Certificate, CertificateBatch)
            .outerjoin(CertificateBatch, CertificateBatch.id == Certificate.batch_id)
            .filter(Certificate.source_ref.in_(refs), Certificate.voided_at.is_(None))
            .all()
        )
        vigentes_by_ref = {cert.source_ref: (cert, batch) for cert, batch in vigentes}

        # Segunda consulta SOLO si hace falta: refs sin vigente, buscando su
        # anulada-con-lote más reciente (nunca una por fila).
        refs_sin_vigente = [r for r in refs if r not in vigentes_by_ref]
        anuladas_by_ref: dict[str, tuple] = {}
        if refs_sin_vigente:
            anuladas = (
                db.query(Certificate, CertificateBatch)
                .join(CertificateBatch, CertificateBatch.id == Certificate.batch_id)
                .filter(Certificate.source_ref.in_(refs_sin_vigente),
                        Certificate.voided_at.isnot(None))
                .order_by(Certificate.voided_at.desc(), Certificate.id.desc())
                .all()
            )
            for cert, batch in anuladas:
                anuladas_by_ref.setdefault(cert.source_ref, (cert, batch))   # la primera = la más reciente

        out: dict[str, dict | None] = {}
        for ref in refs:
            if ref in vigentes_by_ref:
                cert, batch = vigentes_by_ref[ref]
                out[ref] = {
                    "number": cert.number,
                    "issued_at": cert.issued_at,
                    "printed": cert.batch_id is not None,
                    "batch_id": cert.batch_id,
                    "batch_at": batch.created_at if batch else None,
                    "voided_printed": None,
                }
            elif ref in anuladas_by_ref:
                cert, batch = anuladas_by_ref[ref]
                out[ref] = {
                    "number": None,
                    "issued_at": None,
                    "printed": False,
                    "batch_id": None,
                    "batch_at": None,
                    "voided_printed": {
                        "number": cert.number,
                        "batch_id": cert.batch_id,
                        "batch_at": batch.created_at,
                        "voided_at": cert.voided_at,
                        "void_reason": cert.void_reason,
                    },
                }
            else:
                out[ref] = None
        return out

    @staticmethod
    def voided_after_print(db: Session, kind: str, *, days: int = 30) -> list[dict]:
        """Constancias de `kind` ANULADAS que alcanzaron a entrar a un lote
        (`batch_id IS NOT NULL`) y se anularon en los últimos `days` días
        (`voided_at >= db_now() - days`), de la más reciente a la más vieja
        (spec §3.2/E6) — para que la página de Constancias avise que hay que
        retirar ese papel; antes de esto SE no se enteraba cuando se anulaba
        una constancia ya impresa.

        Incluye las de un proceso YA revocado después (a diferencia de
        `pending`/`_pending_criteria`, Ruling R26): el papel sigue circulando
        y hay que recuperarlo igual, revocar la inscripción después no lo
        deshace. No lee `TitulationProcess` en absoluto — invariante 4.
        """
        from itcj2.apps.titulatec.models.certificate import Certificate, CertificateBatch

        corte = db_now() - timedelta(days=days)
        filas = (
            db.query(Certificate, CertificateBatch)
            .join(CertificateBatch, CertificateBatch.id == Certificate.batch_id)
            .filter(Certificate.kind == kind,
                    Certificate.voided_at.isnot(None),
                    Certificate.batch_id.isnot(None),
                    Certificate.voided_at >= corte)
            .order_by(Certificate.voided_at.desc(), Certificate.id.desc())
            .all()
        )
        return [
            {
                "number": cert.number,
                "student_name": cert.student_name,
                "control_number": cert.control_number,
                "batch_id": cert.batch_id,
                "batch_at": batch.created_at,
                "voided_at": cert.voided_at,
                "void_reason": cert.void_reason,
            }
            for cert, batch in filas
        ]

    @staticmethod
    def certificates_of(db: Session, batch_id: int) -> list[Certificate]:
        """Las constancias de un lote, anuladas incluidas (el PDF del lote se
        regenera con todas; una anulada sale marcada «ANULADA», nunca
        desaparece del lote que ya se imprimió)."""
        from itcj2.apps.titulatec.models.certificate import Certificate

        return (
            db.query(Certificate)
            .filter_by(batch_id=batch_id)
            .order_by(Certificate.issued_at.asc(), Certificate.id.asc())
            .all()
        )

    @staticmethod
    def list_batches(db: Session, *, kind: str, page: int = 1,
                     per_page: int = 30) -> tuple[list[dict], bool]:
        """Página de lotes de `kind`, más recientes primero. Cada dict trae
        `id, kind, created_at (datetime), created_by_id, created_by (nombre o
        None), count, voided_count` — `voided_count` en una sola consulta
        agrupada (nunca una por fila). Formatear fechas es tarea de quien
        pinte la página, no de este service."""
        from itcj2.apps.titulatec.models.certificate import Certificate, CertificateBatch
        from itcj2.core.models.user import User

        page = max(1, page)
        per_page = max(1, per_page)

        query = (
            db.query(CertificateBatch, User)
            .outerjoin(User, User.id == CertificateBatch.created_by_id)
            .filter(CertificateBatch.kind == kind)
            .order_by(CertificateBatch.created_at.desc(), CertificateBatch.id.desc())
        )
        filas = query.offset((page - 1) * per_page).limit(per_page + 1).all()
        has_more = len(filas) > per_page
        filas = filas[:per_page]

        batch_ids = [batch.id for batch, _ in filas]
        anuladas = dict(
            db.query(Certificate.batch_id, func.count(Certificate.id))
            .filter(Certificate.batch_id.in_(batch_ids), Certificate.voided_at.isnot(None))
            .group_by(Certificate.batch_id)
            .all()
        ) if batch_ids else {}

        out = []
        for batch, creator in filas:
            out.append({
                "id": batch.id,
                "kind": batch.kind,
                "created_at": batch.created_at,
                "created_by_id": batch.created_by_id,
                "created_by": creator.full_name if creator else None,
                "count": batch.count,
                "voided_count": anuladas.get(batch.id, 0),
            })
        return out, has_more

    # ------------------------------------------------------------------ lote
    @staticmethod
    def create_batch(db: Session, *, kind: str, actor_id: int) -> CertificateBatch:
        """Toma TODAS las pendientes de `kind` (`_pending_criteria`: las de
        un proceso revocado no entran) con `FOR UPDATE SKIP LOCKED` (si
        alguien más las está imprimiendo en otra transacción ahora mismo,
        esta llamada simplemente no las ve, en vez de bloquearse), arma el
        lote y les pone `batch_id`. Commit PROPIO: imprimir es su propia
        operación. 0 pendientes → `ValueError` legible, nada se crea."""
        from itcj2.apps.titulatec.models.certificate import Certificate, CertificateBatch

        if kind not in CERT_KINDS:
            raise ValueError(f"Tipo de constancia desconocido: {kind!r}.")

        filas = (
            db.query(Certificate)
            .filter(*CertificateService._pending_criteria(kind))
            .order_by(Certificate.issued_at.asc(), Certificate.id.asc())
            .with_for_update(skip_locked=True)
            .all()
        )
        if not filas:
            raise ValueError("No hay constancias por imprimir.")

        batch = CertificateBatch(kind=kind, created_by_id=actor_id, count=len(filas))
        db.add(batch)
        db.flush()
        for cert in filas:
            cert.batch_id = batch.id
        db.commit()
        return batch

    # --------------------------------------------------------------- periodo
    @staticmethod
    def period_label(period) -> str:
        """«Agosto-Diciembre 2026» a partir del sufijo del código del periodo
        (`AAAAS`, 5 caracteres: 1 Enero-Junio, 2 Verano, 3 Agosto-Diciembre).
        Si el código no trae ese formato — longitud distinta de 5, prefijo no
        numérico o sufijo fuera de 1/2/3 — respaldo: `period.name` tal cual
        (sin recortar: quien necesite acotarlo a una columna lo hace en el
        punto de guardar, como `issue()`). `None` → cadena vacía.
        """
        if period is None:
            return ""
        code = (period.code or "").strip()
        if len(code) == 5 and code[:4].isdigit() and code[4] in _SEMESTER_LABELS:
            return f"{_SEMESTER_LABELS[code[4]]} {code[:4]}"
        return period.name or ""
