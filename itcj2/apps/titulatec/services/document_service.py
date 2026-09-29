"""Lógica de documentos del proceso de titulación."""
from __future__ import annotations

from sqlalchemy.orm import Session


class DocumentService:
    INITIAL_DOC_TYPES = ["birth_certificate", "high_school_cert", "curp"]

    # ----------------------------------------------------------------- bitacora
    @staticmethod
    def _log(db: Session, process_id: int, actor_id: int | None, event_type: str,
             phase_number: int | None, payload: dict | None = None) -> None:
        """Escribe un `ProcessEvent`. Gemelo del de `appointment_service`.

        **No commitea**: se llama dentro de los metodos que ya son duenos de su
        transaccion, justo antes de su `commit()`.

        Existe porque de un documento no quedaba ABSOLUTAMENTE NADA de lo
        anterior: `save()` pisa la fila y `storage.save_document` pisa el archivo
        (nombre fijo `{control}_{ETIQUETA}.{ext}`), y `review()` pisa `review_note`. Un
        acta rechazada por falta de sello y vuelta a subir no dejaba ni el motivo
        ni la fecha ni quien la rechazo.
        """
        from itcj2.apps.titulatec.models import ProcessEvent
        db.add(ProcessEvent(
            process_id=process_id, actor_id=actor_id,
            event_type=event_type, phase_number=phase_number, payload=payload,
        ))

    @staticmethod
    def initial_docs_all_approved(db, process_id: int) -> bool:
        """True si los 3 documentos iniciales están en review_status='approved'."""
        for code in DocumentService.INITIAL_DOC_TYPES:
            doc = DocumentService.get_document(db, process_id, code)
            if not doc or doc.review_status != "approved":
                return False
        return True

    @staticmethod
    def initial_docs_summary(db, process_id: int) -> dict:
        """Resumen de los 3 documentos iniciales en **dos** consultas fijas.

        Lo consume el acordeón del dashboard del alumno, que se pinta 9 veces por
        carga: `initial_docs_all_approved` haría una consulta por código (y no
        distingue rechazado de faltante), así que ahí sería un N+1 en la pantalla
        más visitada de la app.

        `status` por documento: ``approved|rejected|pending|missing`` — ``missing``
        es el pseudo-estado de la UI cuando no hay fila (mismo criterio que
        `pages/documents.py:31`), no un valor de `Document.review_status`.
        """
        from itcj2.apps.titulatec.models import Document, DocumentType

        codes = DocumentService.INITIAL_DOC_TYPES
        docs = {
            d.type_code: d for d in
            db.query(Document)
            .filter(Document.process_id == process_id, Document.type_code.in_(codes))
            .all()
        }
        # Sin `is_active`: si un tipo se desactiva, el documento ya subido debe
        # seguir mostrándose con su nombre, no con el código crudo.
        names = {
            t.code: t.name for t in
            db.query(DocumentType).filter(DocumentType.code.in_(codes)).all()
        }

        items, counts = [], {"approved": 0, "rejected": 0, "pending": 0, "missing": 0}
        for code in codes:
            doc = docs.get(code)
            status = doc.review_status if doc else "missing"
            if status not in counts:          # valor inesperado en BD: no lo perdemos
                counts[status] = 0
            counts[status] += 1
            items.append({
                "code": code,
                "name": names.get(code, code),
                "status": status,
                "note": (doc.review_note if doc else None),
            })
        return {
            "total": len(codes),
            "uploaded": len(codes) - counts["missing"],
            "counts": counts,
            "items": items,
        }

    @staticmethod
    def sync_initial_phase(db: Session, process) -> str | None:
        """Sincroniza `ProcessPhase(1)` según cuántos de los 3 documentos
        iniciales están presentes. Reemplaza al antiguo
        `POST /student/phase/1/submit` (Tarea 1, 2026-09-28, plan
        titulatec-correos-notificaciones): la fase 1 ya no se "envía" a mano,
        se sincroniza sola en cada `save()`/`delete()` de un documento de esa
        fase.

        Contrato (falla CERRADO, misma política que el resto de esta guarda):

        - El número de fase sale del catálogo
          (`PhaseService.phase_number_for_code(db, "initial_docs")`). Sin
          catálogo, no toca nada.
        - Solo actúa si `process.status == "active"` **y**
          `process.current_phase` es justo esa fase: una fase ya pasada,
          todavía futura, o un proceso en pausa/cerrado no se tocan.
        - 3 presentes -> `"in_review"`, pero SOLO si estaba en
          `pending|in_progress|rejected` (crea la fila `ProcessPhase` si
          falta, como hacía la ruta vieja).
        - Falta alguno -> `"in_progress"`, pero SOLO si estaba `"in_review"`.
        - NUNCA toca `approved` ni `skipped`.

        Esto NO es una guarda de acceso (no lanza `ValueError`): es un efecto
        secundario de guardar/borrar un documento, así que ante cualquier caso
        fuera de su alcance simplemente no hace nada.

        Devuelve el estado nuevo ESCRITO, o `None` si no tocó nada. **No hace
        commit ni flush propio** -- quien la llama (`save`/`delete`) ya tiene
        su propia transacción abierta y decide cuándo confirmar; si el
        llamador acaba de borrar una fila, tiene que `flush()` ANTES de llamar
        aquí (ver `delete()`) para que la cuenta de abajo no incluya lo que se
        está borrando.
        """
        from itcj2.apps.titulatec.models import Document, ProcessPhase
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        n = PhaseService.phase_number_for_code(db, "initial_docs")
        if n is None:
            return None
        if process.status != "active" or process.current_phase != n:
            return None

        count = (
            db.query(Document)
            .filter(Document.process_id == process.id,
                    Document.type_code.in_(DocumentService.INITIAL_DOC_TYPES))
            .count()
        )
        complete = count >= len(DocumentService.INITIAL_DOC_TYPES)

        phase = db.query(ProcessPhase).filter_by(process_id=process.id, phase_number=n).first()
        current_status = phase.status if phase else "pending"

        if complete:
            if current_status not in ("pending", "in_progress", "rejected"):
                return None
            new_status = "in_review"
        else:
            if current_status != "in_review":
                return None
            new_status = "in_progress"

        if not phase:
            phase = ProcessPhase(process_id=process.id, phase_number=n)
            db.add(phase)
        phase.status = new_status
        return new_status

    @staticmethod
    def last_uploads(db: Session, process_ids: list[int],
                     codes: list[str] | None = None) -> dict:
        """Ultima llegada de cada (proceso, tipo) segun la bitacora, en UN lote.

        Extraido de `pages/documents.py::_last_uploads` (Tarea 2, 2026-09-28,
        plan titulatec-correos-notificaciones): la bandeja del personal (FIFO
        de "Por evaluar") y la vista del alumno (`pages/student.py::
        _docs_status_ctx`, linea "Enviado el ...") necesitan la MISMA fuente de
        verdad de "cuando llego de verdad cada documento" -- `Document` no
        sirve sola porque una resubida NO resetea `created_at`
        (`DocumentService.save` actualiza la fila en su lugar, solo sube
        `version`) y `updated_at` no tiene `onupdate` ni la escribe nadie. Cada
        subida real SI deja un `ProcessEvent(document_uploaded)` en la MISMA
        transaccion (ver `save()` arriba), con `type_code` en el payload. Se
        toma el MAXIMO por (proceso, tipo): un documento rechazado y vuelto a
        subir cuenta desde la resubida, no desde el primer intento -- es una
        llegada NUEVA.

        `codes` (opcional): filtra el TIPO ademas del proceso -- la vista del
        alumno solo necesita uno a la vez; `None` (por omision) considera
        cualquier tipo, el comportamiento de siempre para la bandeja
        (`pages/documents.py::_last_uploads`, que delega aqui y no lo pasa).
        Filtra DESPUES de traer las filas (no en SQL): mismo numero y forma de
        consulta que antes, asi que `_order_pending_by_wait` sigue costando
        UNA consulta por lote (`test_documents_fifo.py::
        test_la_pestana_pendiente_no_escala_con_las_filas`).
        """
        from itcj2.apps.titulatec.models import ProcessEvent

        if not process_ids:
            return {}
        ultimas = {}
        filas = (db.query(ProcessEvent.process_id, ProcessEvent.payload, ProcessEvent.created_at)
                 .filter(ProcessEvent.process_id.in_(process_ids),
                         ProcessEvent.event_type == "document_uploaded")
                 .all())
        for process_id, payload, subido_en in filas:
            type_code = (payload or {}).get("type_code")
            if not type_code or (codes is not None and type_code not in codes):
                continue
            clave = (process_id, type_code)
            if clave not in ultimas or subido_en > ultimas[clave]:
                ultimas[clave] = subido_en
        return ultimas

    @staticmethod
    def get_active_process(db: Session, student_id: int):
        """Proceso activo más reciente del alumno (o None)."""
        from itcj2.apps.titulatec.models import TitulationProcess
        return (
            db.query(TitulationProcess)
            .filter_by(student_id=student_id)
            .order_by(TitulationProcess.created_at.desc())
            .first()
        )

    @staticmethod
    def _storage_keys(db: Session, process) -> tuple[str, str]:
        """Devuelve (period_code, control_number) para las rutas de archivo."""
        from itcj2.core.models.user import User
        period_code = process.cohort.period_code if process.cohort else "sin_periodo"
        student = db.get(User, process.student_id)
        control = (student.control_number if student else None) or str(process.student_id)
        return str(period_code), str(control)

    @staticmethod
    def get_document(db: Session, process_id: int, type_code: str):
        from itcj2.apps.titulatec.models import Document
        return (
            db.query(Document)
            .filter_by(process_id=process_id, type_code=type_code)
            .first()
        )

    @staticmethod
    def list_phase_document_types(db: Session, phase_number: int) -> list:
        from itcj2.apps.titulatec.models import DocumentType
        return (
            db.query(DocumentType)
            .filter_by(phase_number=phase_number, is_active=True)
            .order_by(DocumentType.id)
            .all()
        )

    @staticmethod
    def save(
        db: Session,
        process,
        type_code: str,
        *,
        raw: bytes,
        original_name: str,
        content_type: str | None,
        uploaded_by_id: int,
        prepared=None,
    ):
        """Guarda/sobreescribe el documento de un tipo. Solo última versión.

        ``prepared`` (opcional, revisión 2026-09-28 m1): lo que devolvió
        ``storage.prepare_document`` — validado y comprimido — calculado FUERA
        de cualquier transacción. La ruta del alumno lo pasa así para que la
        conexión no quede «idle in transaction» los segundos que tarda comprimir
        un PDF; entonces aquí solo se escribe el archivo y la fila. Sin él, se
        valida y comprime aquí mismo (``storage.save_document``), como siempre.
        """
        from itcj2.apps.titulatec.models import Document, DocumentType
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        from itcj2.apps.titulatec.utils import storage

        dtype = db.query(DocumentType).filter_by(code=type_code, is_active=True).first()
        if not dtype:
            raise ValueError(f"Tipo de documento desconocido: {type_code}")

        period_code, control = DocumentService._storage_keys(db, process)
        if prepared is None:
            meta = storage.save_document(
                raw=raw,
                original_name=original_name,
                content_type=content_type,
                period_code=period_code,
                control_number=control,
                type_code=type_code,
                file_kind=dtype.file_kind,
            )
        else:
            # Se preparó con las reglas de OTRO tipo de archivo: no se escribe.
            if prepared.file_kind != dtype.file_kind:
                raise ValueError("El archivo no corresponde al tipo de documento.")
            meta = storage.write_document(
                prepared,
                period_code=period_code,
                control_number=control,
                type_code=type_code,
            )

        doc = DocumentService.get_document(db, process.id, type_code)
        if doc:
            doc.file_path = meta["file_path"]
            doc.original_name = meta["original_name"]
            doc.mime_type = meta["mime_type"]
            doc.size_bytes = meta["size_bytes"]
            doc.version = (doc.version or 1) + 1
            doc.review_status = "pending"
            doc.review_note = None
            doc.uploaded_by_id = uploaded_by_id
        else:
            doc = Document(
                process_id=process.id,
                phase_number=dtype.phase_number or 0,
                type_code=type_code,
                file_path=meta["file_path"],
                original_name=meta["original_name"],
                mime_type=meta["mime_type"],
                size_bytes=meta["size_bytes"],
                version=1,
                review_status="pending",
                uploaded_by_id=uploaded_by_id,
            )
            db.add(doc)

        db.flush()
        DocumentService._log(
            db, process.id, uploaded_by_id, "document_uploaded",
            dtype.phase_number,
            {"type_code": type_code, "original_name": doc.original_name,
             "version": doc.version},
        )
        # Tarea 1 (2026-09-28): la fase 1 ya no se "envía" a mano -- se
        # sincroniza sola en cuanto el TIPO subido es uno de los iniciales.
        # Antes de su commit, como el resto de esta transacción.
        if dtype.phase_number == PhaseService.phase_number_for_code(db, "initial_docs"):
            DocumentService.sync_initial_phase(db, process)
        db.commit()
        db.refresh(doc)
        return doc

    @staticmethod
    def review(db: Session, process_id: int, type_code: str, *, status: str, note: str | None, reviewer_id: int) -> bool:
        """Aprueba o rechaza un documento (status 'approved'|'rejected').

        **Guarda angosta a propósito -- NO es la gemela de
        `FormatBService.review`.** Esa usa `PhaseService.assert_can_transition`,
        que exige `phase_number == process.current_phase`: aquí eso ROMPERÍA un
        flujo legítimo que hoy funciona y es el uso normal de esta ruta, no una
        excepción -- el dictamen TARDÍO. Revisar hoy un acta de la fase 1 con el
        proceso ya en la fase 2 (o más adelante) es el caso de uso real de
        "Documentos" (bandeja de rezagados); `DocumentService.save` ya trata la
        fase del documento como la del TIPO (`dtype.phase_number`), no la del
        proceso, y esta guarda respeta la misma idea.

        Lo único que el corte a T-soft (spec 2026-09-21,
        `PhaseService._handoff_phase`) tiene que impedir es dictaminar un
        documento cuyo TIPO pertenece a una fase ya congelada
        (`dtype.phase_number >= _handoff_phase()`): las fases 1 y 2 se siguen
        dictaminando sin condición, tarde o no, mientras el corte no las
        alcance -- por debajo del corte el comportamiento de hoy no cambia ni
        un ápice. `dtype.phase_number` es nullable; un tipo CON fila pero SIN
        fase (`dtype is not None and dtype.phase_number is None`) sigue exento
        del corte a propósito -- no hay corte que aplicarle.

        Arreglo A4 (revision final 2026-09-21): si el TIPO ya no existe en el
        catálogo (`dtype is None` -- borrado o nunca sembrado), el respaldo es
        `doc.phase_number` (columna real de la fila, `nullable=False`: SIEMPRE
        está a mano). Antes, `dtype is None` dejaba pasar el dictamen SIN
        mirar nada más -- falla ABIERTO justo donde el propio repo fija
        "FALLA CERRADO" para el mismo tipo de ausencia
        (`phase_service.py:158-161`, `phase_number_for_code`).
        """
        from itcj2.apps.titulatec.models import DocumentType
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        doc = DocumentService.get_document(db, process_id, type_code)
        if not doc:
            return False

        dtype = db.query(DocumentType).filter_by(code=type_code).first()
        fase_para_el_corte = dtype.phase_number if dtype is not None else doc.phase_number
        if (fase_para_el_corte is not None
                and fase_para_el_corte >= PhaseService._handoff_phase()):
            raise ValueError(PhaseService.HANDOFF_MSG)

        doc.review_status = status
        doc.review_note = note or None
        doc.reviewed_by_id = reviewer_id

        # El evento guarda el motivo porque `review_note` es un solo hueco: la
        # siguiente revision lo pisa y el «por que» del rechazo anterior se va.
        DocumentService._log(
            db, process_id, reviewer_id,
            "document_approved" if status == "approved" else "document_rejected",
            doc.phase_number,
            {"type_code": type_code, "note": note or None},
        )

        from itcj2.apps.titulatec.models import TitulationProcess
        proc = db.get(TitulationProcess, process_id)

        if status == "rejected" and proc:
            from itcj2.apps.titulatec.services.notify import notify_student
            notify_student(db, proc.student_id, type="DOCUMENT_REJECTED",
                           title="Un documento necesita correcciones",
                           body=(note or "Revisa el documento rechazado y vuelve a subirlo."),
                           process_id=process_id, phase_number=1)

        # Correo (spec 2026-09-28 §5, #1): aprobado Y rechazado, al grupo
        # `docs:{pid}` -- sale en UN correo con los demás dictámenes (y con el
        # avance de la fase 1) cuando el grupo lleva la espera sin movimiento
        # (D7). El motivo va congelado en el payload por lo mismo que en el
        # evento. En esta transacción: si el commit falla, la fila se va con el
        # dictamen. Nombre del catálogo; si el tipo ya no está, su código.
        if proc:
            from itcj2.apps.titulatec.services.student_mail import StudentMail
            StudentMail.doc_reviewed(
                db, proc, type_code=type_code,
                doc_name=getattr(dtype, "name", None) or type_code,
                status=status, note=note or None)

        db.commit()
        return True

    @staticmethod
    def delete(db: Session, process_id: int, type_code: str,
               *, actor_id: int | None = None) -> bool:
        """Borra la fila Y el archivo. Deja evento: un hueco sin explicacion en el
        expediente se lee como «nunca lo subio».

        Tarea 1 (2026-09-28): si el tipo borrado es de la fase `initial_docs`,
        sincroniza esa fase (`sync_initial_phase`) -- perder uno de los 3 puede
        devolverla de `in_review` a `in_progress`.
        """
        from itcj2.apps.titulatec.models import TitulationProcess
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        from itcj2.apps.titulatec.utils import storage

        doc = DocumentService.get_document(db, process_id, type_code)
        if not doc:
            return False
        phase_number = doc.phase_number
        storage.delete_document_file(doc.file_path)
        db.delete(doc)
        DocumentService._log(db, process_id, actor_id, "document_deleted",
                             phase_number, {"type_code": type_code})
        if phase_number == PhaseService.phase_number_for_code(db, "initial_docs"):
            # `SessionLocal` de producción es autoflush=False
            # (`itcj2/database.py`): sin este flush, el DELETE de `doc` no
            # habría llegado a la BD todavía y `sync_initial_phase` contaría
            # el documento que se acaba de borrar.
            db.flush()
            process = db.get(TitulationProcess, process_id)
            if process:
                DocumentService.sync_initial_phase(db, process)
        db.commit()
        return True
