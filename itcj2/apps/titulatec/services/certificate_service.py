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

from sqlalchemy import func
from sqlalchemy.orm import Session

from itcj2.core.utils.timezone import db_now

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
    `_certificate_counters`."""

    # ------------------------------------------------------------- emisión
    @staticmethod
    def issue(db: Session, *, kind: str, process, source_ref: str,
              actor_id: int) -> Certificate:
        """Emite una constancia NUEVA con folio propio y datos CONGELADOS del
        proceso en este momento (D7/D21/D22). Incondicional: no comprueba que
        `source_ref` ya tenga una vigente — ese candado («a lo más UNA
        vigente por `source_ref`», §5 invariante 5) es responsabilidad del
        LLAMADOR, que conoce su propia máquina de estados (p. ej.
        `SurveyReviewService.approve` solo emite desde `in_review`/`rejected`,
        nunca dos veces sobre una ya `approved`). Sin commit — la transacción
        del llamador decide.
        """
        from itcj2.apps.titulatec.models.certificate import Certificate
        from itcj2.core.models.program import Program

        if kind not in CERT_KINDS:
            raise ValueError(f"Tipo de constancia desconocido: {kind!r}.")

        student = process.student
        period = process.cohort.academic_period if process.cohort else None
        program = db.get(Program, process.program_id) if process.program_id else None

        ahora = db_now()
        numero = CertificateService._next_number(db, kind, ahora.year)
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
    def _next_number(db: Session, kind: str, year: int) -> str:
        """Folio atómico: `INSERT … ON CONFLICT (kind, year) DO UPDATE SET
        last_value = last_value + 1 RETURNING last_value`, UNA sola sentencia
        (segura con PgBouncer, spec §4.5). Nace en 1 la primera vez que se
        emite ese (`kind`, `year`); anular una constancia NUNCA libera su
        número, y volver a emitir para el mismo origen saca el SIGUIENTE."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from itcj2.apps.titulatec.models.certificate import CertificateCounter

        tabla = CertificateCounter.__table__
        stmt = (
            pg_insert(tabla)
            .values(kind=kind, year=year, last_value=1)
            .on_conflict_do_update(
                index_elements=["kind", "year"],
                set_={"last_value": tabla.c.last_value + 1},
            )
            .returning(tabla.c.last_value)
        )
        n = db.execute(stmt).scalar_one()
        prefix = CERT_KINDS[kind]["prefix"]
        return f"{prefix}-{year}-{n:04d}"

    @staticmethod
    def void(db: Session, *, source_ref: str, actor_id: int,
             reason: str | None) -> Certificate | None:
        """Anula la constancia VIGENTE de `source_ref`, si la hay. `None` si
        no hay ninguna que anular — NO es un error: un review `origin='prior'`
        nunca emitió una (lo salta `issue`), así que revocarlo no tiene nada
        que anular y eso es el camino normal. Nunca borra ni libera el folio:
        volver a `issue()` después saca uno nuevo. Sin commit.
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
    def pending(db: Session, kind: str) -> list[Certificate]:
        """«Por imprimir»: constancias de `kind` sueltas (sin lote) y
        vigentes (sin anular), FIFO por `issued_at` — mismo predicado que el
        índice parcial `ix_titulatec_certificates_pending_print`."""
        from itcj2.apps.titulatec.models.certificate import Certificate

        return (
            db.query(Certificate)
            .filter_by(kind=kind, batch_id=None, voided_at=None)
            .order_by(Certificate.issued_at.asc(), Certificate.id.asc())
            .all()
        )

    @staticmethod
    def pending_count(db: Session, kind: str) -> int:
        """`len(pending(...))` sin traer las filas — para el badge «Por
        imprimir (N)» de la página de Constancias."""
        from itcj2.apps.titulatec.models.certificate import Certificate

        total = (
            db.query(func.count(Certificate.id))
            .filter_by(kind=kind, batch_id=None, voided_at=None)
            .scalar()
        )
        return total or 0

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
        """Toma TODAS las pendientes de `kind` con `FOR UPDATE SKIP LOCKED`
        (si alguien más las está imprimiendo en otra transacción ahora mismo,
        esta llamada simplemente no las ve, en vez de bloquearse), arma el
        lote y les pone `batch_id`. Commit PROPIO: imprimir es su propia
        operación. 0 pendientes → `ValueError` legible, nada se crea."""
        from itcj2.apps.titulatec.models.certificate import Certificate, CertificateBatch

        if kind not in CERT_KINDS:
            raise ValueError(f"Tipo de constancia desconocido: {kind!r}.")

        filas = (
            db.query(Certificate)
            .filter_by(kind=kind, batch_id=None, voided_at=None)
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
