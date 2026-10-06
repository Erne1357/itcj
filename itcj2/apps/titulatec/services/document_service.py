"""Lógica de documentos del proceso de titulación."""
from __future__ import annotations

from sqlalchemy.orm import Session


class DocumentService:
    # Fase 1 por PERFIL (spec 2026-09-30-titulatec-posgrado-design.md §4.4,
    # invariante 1: el set de fase 1 de un proceso sale SOLO de aquí). Retira
    # al antiguo `INITIAL_DOC_TYPES` -- el mismo literal de 3 códigos repetido
    # aquí y en `pages/{documents,student,appointments,admin}.py`, sin
    # distinguir perfil; esas páginas siguen con su copia hasta que las
    # Tareas 4 y 5 las hagan consumir este servicio.
    #
    # `BASE_INITIAL_DOCS`: acta, certificado y CURP -- licenciatura Y el
    # "suelo" de posgrado. `POSGRADO_EXTRA_DOCS`: los 4 que solo sube un
    # egresado de posgrado (`TrackService.TRACK_POSGRADO`) -- cédula
    # profesional, título, oficios de autorización de la DEPI y el
    # comprobante de e.firma/cita SAT. Ver `initial_doc_types`.
    BASE_INITIAL_DOCS: tuple[str, ...] = ("birth_certificate", "high_school_cert", "curp")
    POSGRADO_EXTRA_DOCS: tuple[str, ...] = (
        "professional_license", "degree_title", "postgrad_authorization", "efirma_sat",
    )

    # Ayuda por espacio (alumno), SOLO los 4 extras -- los 3 base no cambian
    # de texto por perfil (spec §4.4). D6: cédula y título son del GRADO
    # ANTERIOR (maestría los sube de licenciatura; doctorado, de maestría).
    # D5: los oficios de la DEPI van en un solo PDF.
    INITIAL_DOC_HINTS: dict[str, str] = {
        "professional_license": (
            "De tu grado anterior (licenciatura si cursaste maestría; "
            "maestría si cursaste doctorado)."
        ),
        "degree_title": (
            "De tu grado anterior (licenciatura si cursaste maestría; "
            "maestría si cursaste doctorado)."
        ),
        "postgrad_authorization": "Júntalos en un solo PDF.",
        "efirma_sat": "Comprobante de tu e.firma o de tu cita con el SAT.",
    }

    # Sin acentos a propósito: viaja en el header `X-Tt-Error` (latin-1 en
    # Starlette, UTF-8 en su TestClient), igual que los de `PhaseService`.
    PHASE_CLOSED_MSG = ("La fase de este documento ya fue aprobada: su dictamen "
                        "ya no admite rechazo ni cambios.")

    # ------------------------------------------------------------- set por perfil
    @staticmethod
    def initial_doc_types(track: str) -> tuple[str, ...]:
        """Documentos de la fase 1 para un PERFIL ya resuelto (no un proceso).

        `track` es lo que devuelve `TrackService` (invariante 2: el perfil
        sale SOLO de ahí, nadie más compara nombres de carrera ni `level`).
        Posgrado (`TrackService.TRACK_POSGRADO`): los 3 base + los 4 extras,
        EN ESE ORDEN -- el orden importa para `initial_docs_summary` y para
        la UI que itera esta tupla (los base van primero, igual que hoy).
        Cualquier otro valor -- incluido uno que no debería llegar tras pasar
        por `TrackService` -- cae a licenciatura: falla CERRADO (pide de más,
        nunca de menos).
        """
        from itcj2.apps.titulatec.services.track_service import TRACK_POSGRADO

        if track == TRACK_POSGRADO:
            return DocumentService.BASE_INITIAL_DOCS + DocumentService.POSGRADO_EXTRA_DOCS
        return DocumentService.BASE_INITIAL_DOCS

    @staticmethod
    def initial_doc_types_for(db: Session, process) -> tuple[str, ...]:
        """`initial_doc_types` del perfil de un proceso YA CARGADO."""
        from itcj2.apps.titulatec.services.track_service import TrackService

        return DocumentService.initial_doc_types(TrackService.for_process(db, process))

    @staticmethod
    def initial_doc_types_for_id(db: Session, process_id: int) -> tuple[str, ...]:
        """Igual que `initial_doc_types_for`, buscando primero el proceso por id.

        Un proceso inexistente resuelve a licenciatura, igual que
        `TrackService.for_process_id` -- nunca una excepción.
        """
        from itcj2.apps.titulatec.services.track_service import TrackService

        return DocumentService.initial_doc_types(TrackService.for_process_id(db, process_id))

    @staticmethod
    def initial_doc_types_by_process(db: Session, processes) -> dict[int, tuple[str, ...]]:
        """`initial_doc_types_for` de VARIOS procesos en UNA sola consulta.

        Para bandejas y barridos que ya trajeron la lista completa de
        procesos (p. ej. `AppointmentService.queue_candidates`,
        `MailReminders._documentos`): resolver el perfil proceso por proceso
        dispararía la consulta de `TrackService.for_process` (carrera) una
        vez por candidato. Vía `TrackService.for_processes` -- lista vacía o
        sin ningún `program_id` no consulta nada.
        """
        from itcj2.apps.titulatec.services.track_service import TrackService

        tracks = TrackService.for_processes(db, processes)
        return {pid: DocumentService.initial_doc_types(track) for pid, track in tracks.items()}

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
    def excused_initial_docs(process, present_codes,
                             *, initial_docs_phase: int | None) -> "frozenset[str]":
        """ÚNICO predicado que decide la dispensa R-G (Ruling R11, revisión final
        2026-09-30: R-G se quedaba en la elegibilidad -- `initial_docs_all_approved`
        ya la aplicaba -- pero los CONTADORES seguían contando los 4 extras
        dispensados como pendientes: la bandeja de Documentos, el resumen del
        alumno, el visor de cotejo y el expediente tenían cada uno su propia
        copia, o ninguna, de esta misma cuenta).

        Devuelve los códigos de `POSGRADO_EXTRA_DOCS` que se DISPENSAN para
        `process`: los que NO están en `present_codes` (sin fila `Document`)
        **y** cuyo proceso ya pasó la fase de `initial_docs` -- `current_phase`
        mayor que `initial_docs_phase` (el número de esa fase en el catálogo,
        `PhaseService.phase_number_for_code(db, "initial_docs")`). Sin catálogo
        (`initial_docs_phase=None`), sin proceso, o con la fase 1 todavía
        abierta o en curso (`current_phase <= initial_docs_phase`): nada se
        dispensa -- falla CERRADO, misma política que el resto de esta guarda.

        Un extra que SÍ tiene fila (está en `present_codes`) NUNCA aparece
        aquí, sea cual sea su estado (`approved`/`rejected`/`pending`): se
        evalúa como cualquier otro documento, nunca se dispensa por el simple
        hecho de tener fila. Los 3 `BASE_INITIAL_DOCS` nunca entran aquí (no
        forman parte de `POSGRADO_EXTRA_DOCS`): se exigen siempre, haya
        pasado la fase o no.

        PREDICADO PURO a propósito -- sin `db`, sin consultas: el LLAMADOR
        resuelve `initial_docs_phase` UNA SOLA VEZ (`PhaseService.
        phase_number_for_code`) y lo reparte a cada proceso, para que un lote
        de N filas (`pages/documents.py::_doc_rows`) no pague una consulta al
        catálogo de fases POR FILA -- volvería a ser el N+1 que ya se cerró
        ahí (ver su docstring).
        """
        if process is None or initial_docs_phase is None:
            return frozenset()
        current = process.current_phase
        if not isinstance(current, int) or current <= initial_docs_phase:
            return frozenset()
        return frozenset(
            code for code in DocumentService.POSGRADO_EXTRA_DOCS
            if code not in present_codes
        )

    @staticmethod
    def initial_docs_all_approved(db, process_id: int,
                                  codes: tuple[str, ...] | None = None) -> bool:
        """True si todos los documentos iniciales de `codes` están `approved`.

        `codes=None` (uso normal): el set del PROPIO proceso
        (`initial_doc_types_for_id`) -- licenciatura, 3; posgrado, 7. Quien ya
        tiene el set en mano (p. ej. un lote resuelto con
        `initial_doc_types_by_process`) lo pasa explícito para no repetir esa
        consulta por candidato.

        R-G (spec 2026-09-30-titulatec-posgrado-design.md §5, invariante 8,
        deriva de D9; predicado centralizado en `excused_initial_docs`,
        Ruling R11): un proceso de posgrado que YA PASÓ la fase de
        `initial_docs` no se regresa por los extras de posgrado que le
        falten -- esos códigos FALTANTES dejan de contar. Uno que SÍ tiene
        fila debe estar `approved`, igual que cualquier otro; los 3 base
        SIEMPRE se exigen, haya pasado la fase o no. Sin proceso o sin
        catálogo de fases, la fase 1 se trata como ABIERTA (se exige el set
        completo) -- nunca se lanza una excepción por esto.

        El número de fase de `initial_docs` se consulta SOLO si hace falta
        -- un extra ausente --; con `codes` sin extras (licenciatura) esa
        consulta ni se intenta.

        Desde la Tarea 7 (spec 2026-10-04-titulatec-paginacion-design.md §8)
        es un envoltorio de `initial_docs_approved_map` con UN proceso: la
        regla vive en un solo sitio. Un id inexistente se evalúa como un
        proceso sin carrera y sin fase (licenciatura, nada dispensado) --
        igual que antes, nunca una excepción.
        """
        from types import SimpleNamespace

        from itcj2.apps.titulatec.models import TitulationProcess

        proceso = db.get(TitulationProcess, process_id)
        if proceso is None:
            proceso = SimpleNamespace(id=process_id, program_id=None, current_phase=None)
        codes_by_process = {process_id: tuple(codes)} if codes is not None else None
        return DocumentService.initial_docs_approved_map(
            db, [proceso], codes_by_process=codes_by_process)[process_id]

    @staticmethod
    def initial_docs_approved_map(db, processes, *,
                                  codes_by_process: dict | None = None) -> dict[int, bool]:
        """`initial_docs_all_approved` de VARIOS procesos YA CARGADOS, en
        consultas FIJAS (Tarea 7, spec 2026-10-04-titulatec-paginacion-
        design.md §8): la cola de «Citas de cotejo» la pedía candidato por
        candidato y código por código (N x 3..7 consultas).

        Consultas, sin importar cuántos procesos: el perfil
        (`initial_doc_types_by_process`, a lo sumo una -- se omite para los
        que lleguen en `codes_by_process`), los documentos del set en juego
        (una, `IN` de procesos y de códigos) y el número de fase de
        `initial_docs` (una, y SOLO si algún posgrado tiene un extra sin fila
        -- igual que antes).

        MISMA regla que siempre: todos los códigos del set del proceso
        `approved`; un extra de `POSGRADO_EXTRA_DOCS` SIN fila se dispensa si
        `excused_initial_docs` lo dice (R-G, fase 1 ya cerrada); uno CON fila
        se evalúa como cualquier otro; los 3 base se exigen siempre.

        `codes_by_process` (opcional): {process_id: codes} ya resuelto por
        el llamador; un proceso que no aparezca ahí cae a su propio perfil.
        Lista vacía -> `{}` sin consultar.
        """
        from itcj2.apps.titulatec.models import Document
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        processes = [p for p in processes if p is not None]
        if not processes:
            return {}
        codes_by_process = dict(codes_by_process or {})
        sin_set = [p for p in processes if p.id not in codes_by_process]
        if sin_set:
            codes_by_process.update(DocumentService.initial_doc_types_by_process(db, sin_set))

        en_juego = set()
        for p in processes:
            en_juego.update(codes_by_process[p.id])
        estados: dict[tuple[int, str], str] = {}
        if en_juego:
            estados = {
                (pid, code): status for pid, code, status in
                db.query(Document.process_id, Document.type_code, Document.review_status)
                .filter(Document.process_id.in_({p.id for p in processes}),
                        Document.type_code.in_(en_juego))
                .all()
            }

        sin_calcular = object()
        fase_initial = sin_calcular
        salida: dict[int, bool] = {}
        for p in processes:
            ok = True
            excused = None
            for code in codes_by_process[p.id]:
                status = estados.get((p.id, code))
                if status is None and code in DocumentService.POSGRADO_EXTRA_DOCS:
                    if excused is None:
                        if fase_initial is sin_calcular:
                            fase_initial = PhaseService.phase_number_for_code(
                                db, "initial_docs")
                        # `present_codes` vacío: el predicado solo necesita
                        # saber que ESTE código no tiene fila.
                        excused = DocumentService.excused_initial_docs(
                            p, frozenset(), initial_docs_phase=fase_initial)
                    if code in excused:
                        continue
                    ok = False
                    break
                if status != "approved":
                    ok = False
                    break
            salida[p.id] = ok
        return salida

    @staticmethod
    def initial_docs_summary(db, process_id: int,
                             codes: tuple[str, ...] | None = None,
                             *, process=None) -> dict:
        """Resumen de los documentos iniciales del proceso en pocas consultas FIJAS.

        Lo consume el acordeón del dashboard del alumno, la pantalla más
        visitada de la app: `initial_docs_all_approved` haría una consulta
        por código (y no distingue rechazado de faltante), así que ahí sería
        un N+1. `codes=None` (uso normal) resuelve el set del PROPIO proceso
        (`initial_doc_types_for_id`); quien ya lo tenga en mano lo pasa
        explícito. Las consultas de documentos y nombres son SIEMPRE dos
        (más, a lo sumo, UNA de `TitulationProcess` y otra de
        `PhaseDefinition` -- ver R-G abajo -- SOLO cuando hace falta), sin
        importar cuántos códigos traiga `codes` -- solo cambia el `IN (...)`.

        `status` por documento: ``approved|rejected|pending|missing|excused``.
        ``missing`` es el pseudo-estado de la UI cuando no hay fila (mismo
        criterio que `pages/documents.py:31`), no un valor de
        `Document.review_status`.

        R-G (spec 2026-09-30-titulatec-posgrado-design.md §5, invariante 8;
        Ruling R11): un extra de `POSGRADO_EXTRA_DOCS` sin fila, dispensado
        por `excused_initial_docs` (fase 1 ya cerrada), sale con
        ``status="excused"`` -- OTRO pseudo-estado de la UI, «se entrega en
        el cotejo», nunca un valor de `Document.review_status`. `total` y
        `uploaded` cuentan SOLO lo exigible EN LÍNEA -- se excluyen los
        dispensados -- así que para licenciatura y para un posgrado que
        sigue en fase 1 el resultado es IDÉNTICO al de hoy (ahí nunca hay
        dispensados). El número de fase de `initial_docs` (y el `process`, si
        no llega ya resuelto) se calculan LA PRIMERA VEZ que hace falta --
        algún extra sin fila -- igual que en `initial_docs_all_approved`;
        `process` (opcional): el llamador que YA cargó el `TitulationProcess`
        (p. ej. `pages/student.py`) lo pasa para no repetir ese `db.get`.
        """
        from itcj2.apps.titulatec.models import Document, DocumentType, TitulationProcess
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        if codes is None:
            codes = DocumentService.initial_doc_types_for_id(db, process_id)

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

        present_codes = frozenset(docs.keys())
        excused = frozenset()
        if any(code in DocumentService.POSGRADO_EXTRA_DOCS and code not in present_codes
               for code in codes):
            if process is None:
                process = db.get(TitulationProcess, process_id)
            n = PhaseService.phase_number_for_code(db, "initial_docs")
            excused = DocumentService.excused_initial_docs(
                process, present_codes, initial_docs_phase=n)

        items, counts = [], {"approved": 0, "rejected": 0, "pending": 0, "missing": 0,
                             "excused": 0}
        for code in codes:
            doc = docs.get(code)
            if doc is None and code in excused:
                status = "excused"
            else:
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
        total = len(codes) - counts["excused"]
        return {
            "total": total,
            "uploaded": total - counts["missing"],
            "counts": counts,
            "items": items,
        }

    @staticmethod
    def sync_initial_phase(db: Session, process) -> str | None:
        """Sincroniza `ProcessPhase(1)` según cuántos documentos iniciales DEL
        PERFIL del proceso (`initial_doc_types_for`: licenciatura, 3;
        posgrado, 7) están presentes. Reemplaza al antiguo
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
        - TODOS presentes -> `"in_review"`, pero SOLO si estaba en
          `pending|in_progress|rejected` (crea la fila `ProcessPhase` si
          falta, como hacía la ruta vieja).
        - Falta alguno -> `"in_progress"`, pero SOLO si estaba `"in_review"`.
        - NUNCA toca `approved` ni `skipped` (R-G, spec §5: `init-posgrado` y
          esta misma función re-sincronizando una fase ya cerrada no pueden
          regresarla).

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

        codes = DocumentService.initial_doc_types_for(db, process)
        count = (
            db.query(Document)
            .filter(Document.process_id == process.id,
                    Document.type_code.in_(codes))
            .count()
        )
        complete = count >= len(codes)

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

        **Fase ya aprobada = dictamen congelado (2026-10-04, decisión del
        usuario).** Si el proceso ya pasó la fase del documento
        (`process.current_phase > fase del tipo`), NO se puede rechazar ni
        tocar uno ya `approved`: el alumno no puede volver a subirlo
        (`assert_student_can_act` cierra las fases anteriores) y nada regresa
        el proceso de fase, así que un rechazo tardío lo dejaba trabado — fuera
        de la cola de cotejo y sin forma de corregir. Lo único que sigue
        permitido es APROBAR uno que no lo esté (p. ej. la fase se movió con
        «Mover de fase» con documentos pendientes): eso solo destraba. Mismo
        criterio en la bandeja (`pages/documents.py::_body_ctx`, `phase_closed`).
        """
        from itcj2.apps.titulatec.models import DocumentType, TitulationProcess
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        doc = DocumentService.get_document(db, process_id, type_code)
        if not doc:
            return False

        dtype = db.query(DocumentType).filter_by(code=type_code).first()
        fase_para_el_corte = dtype.phase_number if dtype is not None else doc.phase_number
        if (fase_para_el_corte is not None
                and fase_para_el_corte >= PhaseService._handoff_phase()):
            raise ValueError(PhaseService.HANDOFF_MSG)

        proc = db.get(TitulationProcess, process_id)
        actual = getattr(proc, "current_phase", None)
        if (fase_para_el_corte is not None
                and isinstance(actual, int) and not isinstance(actual, bool)
                and actual > fase_para_el_corte
                and (status == "rejected" or doc.review_status == "approved")):
            raise ValueError(DocumentService.PHASE_CLOSED_MSG)

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
