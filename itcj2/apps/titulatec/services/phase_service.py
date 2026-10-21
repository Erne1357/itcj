"""Motor de avance de fases del proceso de titulación."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session
from itcj2.core.utils.timezone import db_now


class PhaseService:
    @staticmethod
    def get_phases(db: Session, process_id: int) -> list:
        from itcj2.apps.titulatec.models import ProcessPhase
        return (
            db.query(ProcessPhase)
            .filter_by(process_id=process_id)
            .order_by(ProcessPhase.phase_number)
            .all()
        )

    @staticmethod
    def _skips(process) -> set[int]:
        """Fases que la modalidad del proceso salta (JSON)."""
        mod = process.modality
        if mod and mod.skips_phases:
            try:
                return {int(x) for x in mod.skips_phases}
            except (TypeError, ValueError):
                return set()
        return set()

    @staticmethod
    def phase_numbers(db: Session) -> list[int]:
        """Números de fase del catálogo, ordenados.

        Fuente ÚNICA del dominio de fases. Antes estaba escrito a mano en dos
        sitios (`while n <= 8` aquí y `range(9)` en `import_service`), que podían
        desincronizarse del catálogo sin que nada avisara.
        """
        from itcj2.apps.titulatec.models import PhaseDefinition
        return [
            int(n) for (n,) in
            db.query(PhaseDefinition.number).order_by(PhaseDefinition.number).all()
        ]

    @staticmethod
    def phase_range(db: Session) -> tuple[int, int]:
        """(primera, última) fase del catálogo. Sin catálogo no hay fase válida."""
        nums = PhaseService.phase_numbers(db)
        if not nums:
            raise ValueError("No hay fases dadas de alta en el sistema.")
        return nums[0], nums[-1]

    # ------------------------------------------------------------------
    # Corte a T-soft (spec 2026-09-21, Tarea 2 del plan de deslinde)
    # ------------------------------------------------------------------
    # A partir de `_handoff_phase()` el proceso ya NO se opera en esta app: lo
    # atiende el Departamento de Titulación en su propio sistema (T-soft). Vive
    # aquí, no repetido, porque lo usan las DOS guardas de abajo: la del admin
    # (`_transition_error`, dictamen) y la del alumno (`_student_action_error`,
    # ejecución).
    HANDOFF_MSG = ("Esta fase continua en el Departamento de Titulacion (sistema T-soft). "
                   "Te contactaran por correo para darte tu usuario.")

    @staticmethod
    def _handoff_phase() -> int:
        """`get_settings()` está cacheado; el import va local (gotcha 2 del
        CLAUDE.md raíz), mismo molde que `SelfBookingService._settings()`."""
        from itcj2.config import get_settings
        return get_settings().TITULATEC_HANDOFF_PHASE

    @staticmethod
    def _transition_error(process, phase_number, first: int, last: int) -> str | None:
        """Motivo por el que `phase_number` NO puede aprobarse/rechazarse, o None.

        Las tres reglas de `docs/flows/00_state_machine.md`: la fase existe, el
        proceso está vivo, y solo se actúa sobre la fase actual (ni saltar hacia
        adelante ni retroceder a una ya cerrada). Más una cuarta (spec
        2026-09-21): ninguna fase desde `_handoff_phase()` en adelante se
        dictamina aquí -- `approve_phase(2)` (la liberación hacia T-soft) sigue
        intacta porque pasa con `phase_number=2`, por debajo del corte.

        Los mensajes van SIN acentos a propósito, no por descuido: viajan al toast
        por el header `X-Tt-Error`, y ahí Starlette es asimétrico — escribe la
        respuesta con `value.encode("latin-1")` (`datastructures.py:515`) pero su
        TestClient la lee con `value.decode()`, o sea UTF-8
        (`testclient.py:333`). Un solo byte >127 hace que el request entero
        reviente en cualquier test de ruta que caiga en este camino. En el
        navegador funcionaría; en la suite, no.
        """
        # `bool` es subclase de `int`: True colaría como fase 1.
        if isinstance(phase_number, bool) or not isinstance(phase_number, int):
            return f"Fase no reconocida: se espera un entero entre {first} y {last}."
        if not (first <= phase_number <= last):
            return (f"Fase {phase_number} fuera de rango: el proceso solo tiene "
                    f"las fases {first} a {last}.")
        if process.status != "active":
            return f"El proceso ya no admite cambios de fase (estado: {process.status})."
        # Corte a T-soft: ninguna fase >= `_handoff_phase()` se dictamina aquí,
        # ni siquiera la propia fase actual del proceso.
        if phase_number >= PhaseService._handoff_phase():
            return PhaseService.HANDOFF_MSG
        if phase_number != process.current_phase:
            return (f"Solo puedes actuar sobre la fase en curso "
                    f"(fase {process.current_phase:02d}, no la {phase_number:02d}).")
        return None

    @staticmethod
    def can_transition(db: Session, process, phase_number: int) -> bool:
        """¿Se puede aprobar/rechazar esa fase? Para quien prefiere preguntar a atrapar.

        Lo usa el auto-avance del dictamen de documentos (`pages/documents.py`)
        para decidir si llamar a `approve_phase`. Es un filtro SIN bloqueo, no
        la garantía: dos peticiones pueden pasarlo a la vez, y por eso esa ruta
        además atrapa el `ValueError` con que `approve_phase` (que sí bloquea,
        R14) despide al perdedor.
        """
        try:
            first, last = PhaseService.phase_range(db)
        except ValueError:
            return False
        return PhaseService._transition_error(process, phase_number, first, last) is None

    @staticmethod
    def assert_can_transition(db: Session, process, phase_number) -> tuple[int, int]:
        """Guarda de aprobar/rechazar. Devuelve el rango del catálogo (para reusarlo).

        Vive en el service, no en la ruta, porque `approve_phase` tiene más de un
        llamador (botón manual y auto-avance de documentos) y el siguiente que se
        agregue la hereda gratis.
        """
        first, last = PhaseService.phase_range(db)
        err = PhaseService._transition_error(process, phase_number, first, last)
        if err:
            raise ValueError(err)
        return first, last

    # ------------------------------------------------------------------
    # Guarda del ALUMNO (gemela de la de arriba, desde el otro lado)
    # ------------------------------------------------------------------
    # `assert_can_transition` protege el DICTAMEN (admin: aprobar/rechazar).
    # Esto protege la EJECUCIÓN (alumno: subir, borrar, llenar, enviar, confirmar).
    # Son las mismas tres reglas de `docs/flows/00_state_machine.md` leídas desde
    # el otro extremo, y por eso viven juntas: quien toque una ve la otra.
    #
    # Contrato con el alumno (decisión del usuario, 2026-09-02), que es también lo
    # que el acordeón del dashboard le promete literalmente:
    #   - fases SIGUIENTES → informativas ("Se habilitará cuando llegues a esta fase")
    #   - fases ANTERIORES → cerradas e INMUTABLES ("Fase cerrada · ya no requiere acción")

    @staticmethod
    def phase_number_for_code(db: Session, code: str) -> int | None:
        """Número de la fase con ese `code` en el catálogo, o None si no existe.

        Las rutas del alumno se identifican por CÓDIGO de fase (`initial_docs`,
        `review_appointment`, `format_b`) porque así están escritas ya
        `_PHASE_INFO` y `_PHASE_CTA` en `pages/student.py`. El número sale del
        catálogo y no de un literal por el mismo motivo que `phase_numbers()`:
        que agregar o renumerar una fase no exija tocar código.

        None es una respuesta legítima (código desconocido) y la guarda la trata
        como "no se puede": FALLA CERRADO. Lo mismo hace con
        `DocumentType.phase_number`, que es nullable.
        """
        from itcj2.apps.titulatec.models import PhaseDefinition
        row = (
            db.query(PhaseDefinition.number)
            .filter(PhaseDefinition.code == code)
            .first()
        )
        return int(row[0]) if row else None

    @staticmethod
    def _student_action_error(db: Session, process, phase_number) -> str | None:
        """Motivo por el que el alumno NO puede actuar en esa fase, o None.

        Mismos mensajes SIN acentos que `_transition_error` y por el mismo
        motivo: viajan al toast por el header `X-Tt-Error`, y ahí Starlette
        escribe latin-1 pero su TestClient lee UTF-8 — un byte >127 tumba el
        request entero en cualquier test de ruta que caiga aquí.

        La regla del corte a T-soft (spec 2026-09-21) va ANTES que la de "fase
        futura": sin eso, un egresado parado en la fase 3 (o pidiendo acción
        sobre ella desde antes) leería "se habilitará cuando llegues a ella",
        una promesa que el corte vuelve falsa -- esa fase ya no se habilita
        aquí, la opera T-soft.
        """
        # `bool` es subclase de `int`: True colaría como fase 1.
        if isinstance(phase_number, bool) or not isinstance(phase_number, int):
            return "Fase no reconocida: esta accion no corresponde a ninguna fase de tu proceso."
        if phase_number not in PhaseService.phase_numbers(db):
            return (f"Fase {phase_number} fuera del proceso: no existe en el "
                    f"catalogo de fases.")
        if process.status != "active":
            return f"Tu proceso ya no admite cambios (estado: {process.status})."
        if phase_number < process.current_phase:
            return (f"La fase {phase_number:02d} ya esta cerrada: no requiere "
                    f"accion y no admite cambios.")
        # Corte a T-soft: ANTES que la regla de "fase futura" (ver docstring).
        if phase_number >= PhaseService._handoff_phase():
            return PhaseService.HANDOFF_MSG
        if phase_number > process.current_phase:
            return (f"La fase {phase_number:02d} se habilitara cuando llegues a "
                    f"ella (vas en la fase {process.current_phase:02d}).")
        return None

    @staticmethod
    def can_student_act(db: Session, process, phase_number) -> bool:
        """¿Puede el alumno ejecutar esa fase? Para quien prefiere preguntar a atrapar.

        Lo usan las PÁGINAS del alumno, que en vez de un error devuelven un 302
        al acordeón del dashboard.
        """
        return PhaseService._student_action_error(db, process, phase_number) is None

    @staticmethod
    def assert_student_can_act(db: Session, process, phase_number) -> int:
        """Guarda de toda acción del alumno. Devuelve la fase validada.

        Vive en el service —no repetida en cada ruta— por lo mismo que su
        gemela: `pages/student.py` la invoca hoy desde 10 rutas y
        `FormatBService.submit` la reaplica en el punto de mutación.

        La fase RECHAZADA es un caso VÁLIDO, no una excepción a escribir aparte:
        `reject_phase` deja `process.current_phase` apuntando a la fase
        rechazada, así que mirar `current_phase` (y no el `status` de la fase) ya
        deja pasar la corrección y el reenvío del alumno.
        """
        err = PhaseService._student_action_error(db, process, phase_number)
        if err:
            raise ValueError(err)
        return phase_number

    @staticmethod
    def _next_applicable(process, after: int, last_phase: int) -> int | None:
        """Siguiente fase aplicable tras `after`, saltando las de la modalidad.

        `last_phase` es la última del catálogo (`phase_range`), no un literal.
        """
        skips = PhaseService._skips(process)
        n = after + 1
        while n <= last_phase:
            if n not in skips:
                return n
            n += 1
        return None

    @staticmethod
    def _ensure_phase(db: Session, process_id: int, n: int):
        from itcj2.apps.titulatec.models import ProcessPhase
        ph = db.query(ProcessPhase).filter_by(process_id=process_id, phase_number=n).first()
        if not ph:
            ph = ProcessPhase(process_id=process_id, phase_number=n, status="pending")
            db.add(ph)
            db.flush()
        return ph

    # Defensa de `approve_phase` (Ruling R14): la `ProcessPhase` de la fase a
    # aprobar ya está `approved`. ASCII por lo mismo que `_transition_error`.
    PHASE_ALREADY_APPROVED_MSG = "Esa fase ya fue aprobada."

    # Una sola puerta para la fase 3 (spec 2026-10-21 fase 3 §7): la fase de
    # código `format_b` solo se dictamina desde `FormatBService.approve`/
    # `.reject`, que dejan el Formato B dictaminado en la sesión antes de
    # llamar al motor. Con acentos: las rutas que lo pueden recibir (`phase/
    # {n}/approve|reject` del expediente) lo pasan por `_hdr()`.
    FORMAT_B_ONLY_MSG = "El Formato B se dictamina desde la pestaña Titulación."

    # Marca en `db.info` con la que `FormatBService.approve`/`.reject` abren la
    # puerta del motor: `(process_id, veredicto)`. La pone justo antes de
    # llamar a `approve_phase`/`reject_phase` y la quita al terminar (éxito,
    # error o rollback); `_format_b_guard` la exige y la CONSUME.
    FORMAT_B_VERDICT_KEY = "titulatec.format_b_verdict"

    @staticmethod
    def _format_b_guard(db: Session, process, phase_number: int, required: str) -> None:
        """Si `phase_number` es la fase `format_b` del catálogo, exige el dictamen
        del Formato B EN CURSO en esta sesión; si no, `FORMAT_B_ONLY_MSG`.

        «En curso» = la marca `FORMAT_B_VERDICT_KEY` de `db.info` con este
        proceso y este veredicto (`approved` para aprobar, `rejected` para
        rechazar) **y** el Formato B en ese estado. Mirar solo el estado
        guardado no basta: un Formato B `rejected` sigue así mientras el alumno
        corrige (P9), y el botón genérico «Rechazar fase» volvía a rechazar la
        fase 3 por otra puerta (evento sin observaciones, aviso y correo de
        más). La marca se consume aquí: cada dictamen abre la puerta una vez.
        Formato B `approved` ⇔ fase 3 `approved`, en una transacción (§7).
        """
        if phase_number != PhaseService.phase_number_for_code(db, "format_b"):
            return
        from itcj2.apps.titulatec.models import FormatB
        marca = db.info.pop(PhaseService.FORMAT_B_VERDICT_KEY, None)
        fb = db.get(FormatB, process.id)
        if marca != (process.id, required) or fb is None or fb.status != required:
            raise ValueError(PhaseService.FORMAT_B_ONLY_MSG)

    @staticmethod
    def _lock_process_row(db: Session, process) -> None:
        """Bloquea la fila del proceso y la relee sobre `process` (Ruling R14).

        Primera sentencia de `approve_phase` y `reject_phase`, ANTES de
        `assert_can_transition`: así la guarda valida el estado YA bloqueado y
        no el que se leyó al cargar el proceso. Sin esto dos dictámenes de la
        misma fase pasaban la guarda a la vez -- dos revisores aprobando los
        últimos documentos de la fase 1 (el auto-avance de la bandeja llamaba
        `approve_phase(1)` dos veces: eventos, avisos y correos duplicados), o
        un rechazo que regresaba el proceso a una fase que otro acababa de
        liberar. Ahora el segundo espera el commit del primero y su guarda ve
        la fase ya movida (`ValueError`).

        `FOR NO KEY UPDATE` (`key_share=True`): el mismo modo que
        `ProcessService.cancel` y `DocumentService.request_replacement` (R9, que
        hasta R14 era el único caso aquí: la liberación de la fase 2). Serializa
        dictámenes, revocaciones y pedidos de reemplazo, pero no choca con el
        `FOR KEY SHARE` de los INSERT con FK al proceso (eventos, avisos).

        `populate_existing` sobrescribe `process` -- tiene que ser un objeto de
        ESTA sesión, como lo es en todos los llamadores -- con la fila
        bloqueada. La sesión de las rutas no hace autoflush: un cambio sin
        flush sobre `process` se perdería; ningún llamador deja uno.
        """
        from itcj2.apps.titulatec.models import TitulationProcess
        (db.query(TitulationProcess).filter_by(id=process.id)
         .with_for_update(key_share=True).populate_existing().first())

    @staticmethod
    def _log(db: Session, process_id: int, actor_id: int, event_type: str, phase_number: int, payload: dict | None = None):
        from itcj2.apps.titulatec.models import ProcessEvent
        db.add(ProcessEvent(
            process_id=process_id, actor_id=actor_id,
            event_type=event_type, phase_number=phase_number, payload=payload,
        ))

    @staticmethod
    def _phase_label(db: Session, phase_number: int) -> str:
        """'Fase NN · Nombre' para copys de notificación."""
        from itcj2.apps.titulatec.models import PhaseDefinition
        pdef = db.query(PhaseDefinition).filter_by(number=phase_number).first()
        return f"Fase {phase_number:02d}" + (f" · {pdef.name}" if pdef else "")

    # La cita de cotejo es la fase 2 del catálogo. Se nombra aquí y no como
    # literal en el `if` para que grep la encuentre desde el otro lado.
    PHASE_COTEJO = 2

    # Sufijo del requisito de la encuesta de egresados en el mensaje de la
    # guarda de fase 2 (D3), por estatus de la solicitud de liberación de GTV.
    # En ASCII, SIN acentos, por la misma razón que el resto de esta guarda
    # (ver docstring de `_cotejo_gate_error`): viaja al toast por `X-Tt-Error`.
    # `approved` no aparece: si GTV liberó, el requisito ya está `fulfilled` y
    # `missing_required` ni siquiera lo trae aquí.
    _SUFIJO_ENCUESTA = {
        "missing": "sin enviar",
        "in_review": "en revision por GTV",
        "rejected": "con observaciones de GTV",
    }

    # Gemelo del de arriba para el no adeudo de biblioteca (spec 2026-10-01-
    # titulatec-biblioteca-caja-design.md §4.4.6), por su `library` de
    # `ClearanceGate.status`. Mismo ASCII, misma razón. `missing` (sin fila)
    # se dice igual que `pending`; `cleared`/`not_required` no aparecen:
    # liberado, el requisito ya está cumplido (o lo cumplió el legado a mano).
    _SUFIJO_BIBLIOTECA = {
        "missing": "en revision por Biblioteca",
        "pending": "en revision por Biblioteca",
        "awaiting_payment": "pendiente de pago en Caja",
        "observed": "con observaciones de Biblioteca",
    }

    # `auto_source` del requisito -> (llave de `ClearanceGate.status`, sufijos).
    _SUFIJOS_LIBERACION = {
        "graduate_survey": ("survey", _SUFIJO_ENCUESTA),
        "library_clearance": ("library", _SUFIJO_BIBLIOTECA),
    }

    @staticmethod
    def _requirement_label(db: Session, process, requirement) -> str:
        """Nombre de un requisito de cotejo para el mensaje de la guarda.

        Los dos que acredita una LIBERACIÓN —la encuesta de egresados
        (`auto_source == 'graduate_survey'`) y el no adeudo de biblioteca
        (`'library_clearance'`)— llevan además en qué va: sin esto, «al alumno
        le faltan requisitos (Encuesta de egresados)» no dice si ya la envió y
        está en revisión, o si ni siquiera la ha contestado — la diferencia
        entre "avisa a Escolares" y "avisa al alumno". El estado lo da
        `ClearanceGate.status` (único lector, invariante 2 de la spec
        2026-10-01-titulatec-biblioteca-caja-design.md).
        """
        llave_y_sufijos = PhaseService._SUFIJOS_LIBERACION.get(requirement.auto_source)
        if llave_y_sufijos is None:
            return requirement.label
        from itcj2.apps.titulatec.services.clearance_gate import ClearanceGate

        llave, sufijos = llave_y_sufijos
        sufijo = sufijos.get(ClearanceGate.status(db, process.id)[llave])
        return f"{requirement.label} ({sufijo})" if sufijo else requirement.label

    @staticmethod
    def _cotejo_gate_error(db: Session, process) -> str | None:
        """Motivo por el que la fase 2 NO puede liberarse, o None.

        Espejo de `DocumentService.initial_docs_all_approved`, que ya hace esto
        mismo para la fase 1: los requisitos ACTIVOS y OBLIGATORIOS de la
        convocatoria del proceso, menos los que tienen cumplimiento
        `fulfilled` o `waived`.

        Tres cosas deliberadas:

        * **Nombra lo que falta.** Un «faltan requisitos» a secas obliga al
          oficial a adivinar cuál, con el alumno enfrente.
        * **`waived` cuenta.** Es la dispensa con nota; sin ella un caso legítimo
          dejaría la fase trabada para siempre.
        * **Lee el estado ACTUAL de la convocatoria.** Un proceso creado antes de
          que se añadiera un requisito queda igualmente sujeto a él: el requisito
          es del trámite, no del momento del alta. No es un descuido.

        Nunca siembra: una convocatoria sin lista configurada no bloquea a nadie.

        **Antes que los requisitos, los reemplazos (2026-10-15, spec titulatec-
        reemplazo-cotejo §4.4, D4).** Mientras un documento de la fase 1 tenga
        un reemplazo ABIERTO (pedido en el cotejo, rechazado o subido sin
        aprobar), la fase 2 no se libera: `DocumentService.
        replacement_gate_error` lo nombra y ese mensaje sale primero.
        """
        from itcj2.apps.titulatec.services.document_service import DocumentService
        from itcj2.apps.titulatec.services.requirement_service import RequirementService

        reemplazo = DocumentService.replacement_gate_error(db, process)
        if reemplazo:
            return reemplazo

        faltantes = RequirementService.missing_required(db, process.id)
        if not faltantes:
            return None
        nombres = ", ".join(
            PhaseService._requirement_label(db, process, r) for r in faltantes)
        # Texto fijo SIN acentos, igual que `_transition_error`. Las etiquetas
        # vienen de la BD y sí los llevan, pero el único llamador que alcanza la
        # fase 2 (`pages/admin.py::phase_approve`) pasa el mensaje por `_hdr()`,
        # que hace percent-encode y deja el header en ASCII.
        return (f"No se puede liberar la fase 02: al alumno le faltan requisitos "
                f"de cotejo ({nombres}).")

    @staticmethod
    def _auto_close_cotejo_appointment(db: Session, process, actor_id: int, via: str) -> None:
        """Cierra la cita vigente de cotejo si el dictamen de la fase 02 la deja colgada.

        Hueco cerrado 2026-09-17: desde el expediente se podia aprobar O RECHAZAR
        la fase 02 con la cita vigente todavia `in_progress` (el encargado la
        atiende y se le olvida marcar "Asistio" antes de dictaminar). Esa cita no
        aparecia en ningun cubo de la cola —no es `no_show` ni `attended`— y
        bloqueaba volver a agendar por D4 (una cita ACTIVA es la unica que impide
        abrir otro intento): quedaba colgada para siempre.

        Solo toca `in_progress`: es el UNICO estado que de verdad queda "colgado"
        por el dictamen. `scheduled`/`confirmed` significan que el cotejo ni
        siquiera empezo (dictaminar ahi es otro problema, distinto de este);
        `no_show`, `attended` y "sin cita" ya estan resueltos por su cuenta y no
        se tocan.

        NO usa `AppointmentService.mark_attended`: ese metodo hace su propio
        `db.commit()`, y esto tiene que quedar en la MISMA transaccion que el
        dictamen de la fase — `approve_phase`/`reject_phase` ya hacen el suyo al
        final. `assert_transition` se llama de todas formas (aunque el `if` de
        arriba ya garantiza que el salto es legal) porque en esta app NINGUNA
        escritura de `status` se hace sin pasar por la matriz primero.
        """
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService

        appt = AppointmentService.get_for_process(db, process.id)
        if appt is None or appt.status != "in_progress":
            return
        AppointmentService.assert_transition("in_progress", "attended")
        appt.status = "attended"
        PhaseService._log(db, process.id, actor_id, "appointment_attended",
                          PhaseService.PHASE_COTEJO, {"auto": True, "via": via})

    @staticmethod
    def approve_phase(db: Session, process, phase_number: int, reviewer_id: int,
                      event_payload: dict | None = None) -> dict:
        """Aprueba una fase, activa la siguiente aplicable (o completa el proceso).

        Solo la fase ACTUAL de un proceso ACTIVO. Lanza `ValueError` si no
        (la ruta lo traduce a 400 + `X-Tt-Error`).

        **Bloquea la fila del proceso, en TODAS las fases** (Ruling R14,
        2026-10-15; hasta entonces R9 lo hacía solo con la fase de cotejo):
        `_lock_process_row` antes de validar, así que de dos dictámenes de la
        misma fase el segundo espera al primero y su guarda ve la fase ya
        movida. En la fase 2 sigue cubriendo la carrera de R9:
        `DocumentService.request_replacement` toma el mismo bloqueo, así que un
        reemplazo pedido a la vez que se libera la fase o lo ve la compuerta o
        ve la fase ya liberada -- nunca las dos cosas a medias.

        Además se niega (`PHASE_ALREADY_APPROVED_MSG`) si la `ProcessPhase` de
        esa fase ya está `approved`: defensa ante un dato incoherente, sin
        consulta extra (la fila la lee `_ensure_phase` de todas formas) y antes
        de escribir nada.

        La fase `format_b` solo pasa con el Formato B ya `approved` en la
        sesión (`_format_b_guard`, una sola puerta). `event_payload` se fusiona
        en el payload del evento `phase_approved` (así viaja la ronda del
        Formato B al timeline sin un evento duplicado).
        """
        PhaseService._lock_process_row(db, process)
        _first, last = PhaseService.assert_can_transition(db, process, phase_number)
        PhaseService._format_b_guard(db, process, phase_number, "approved")

        # D9: la encuesta de egresados (y el resto del checklist físico) BLOQUEA
        # el dictamen de la fase 2. El alumno sí puede agendar y presentarse; lo
        # que no se puede es cerrarle la fase sin haber entregado.
        #
        # Va aquí y no en `assert_can_transition` porque esa guarda la comparten
        # `reject_phase` y `can_transition`: rechazar la fase 2, o preguntar si se
        # puede actuar en ella, no dependen del checklist.
        if phase_number == PhaseService.PHASE_COTEJO:
            falta = PhaseService._cotejo_gate_error(db, process)
            if falta:
                raise ValueError(falta)

        # R14: la última negativa, ANTES de la primera escritura (el auto-cierre
        # de la cita de abajo ya escribe).
        ph = PhaseService._ensure_phase(db, process.id, phase_number)
        if ph.status == "approved":
            raise ValueError(PhaseService.PHASE_ALREADY_APPROVED_MSG)

        if phase_number == PhaseService.PHASE_COTEJO:
            # Las guardas de arriba ya pasaron: si la cita vigente quedo
            # `in_progress`, aprobar la fase 2 es la senal de que el cotejo
            # terminó. Dentro de la MISMA transaccion que el resto de este metodo
            # (antes del commit de al final).
            PhaseService._auto_close_cotejo_appointment(db, process, reviewer_id,
                                                        "phase_approved")

        ph.status = "approved"
        ph.completed_at = db_now()
        ph.reviewed_by_id = reviewer_id
        ph.rejection_reason = None

        # marca fases saltadas por modalidad como 'skipped'
        for s in PhaseService._skips(process):
            sph = PhaseService._ensure_phase(db, process.id, s)
            if sph.status not in ("approved",):
                sph.status = "skipped"

        nxt = PhaseService._next_applicable(process, phase_number, last)
        if nxt is None:
            process.status = "completed"
            process.completed_at = db_now()
            PhaseService._log(db, process.id, reviewer_id, "process_completed", phase_number)
        else:
            nph = PhaseService._ensure_phase(db, process.id, nxt)
            if nph.status in ("pending", "rejected"):
                nph.status = "in_progress"
                nph.started_at = db_now()
            process.current_phase = nxt

        PhaseService._log(db, process.id, reviewer_id, "phase_approved", phase_number,
                          dict(event_payload) if event_payload else None)

        from itcj2.apps.titulatec.services.notify import notify_student
        if nxt is None:
            notify_student(db, process.student_id, type="PROCESS_COMPLETED",
                           title="¡Proceso de titulación completado!",
                           body="Felicidades, concluiste todas las fases de tu titulación.",
                           process_id=process.id)
        else:
            notify_student(db, process.student_id, type="PHASE_APPROVED",
                           title="Avanzaste de fase",
                           body=f"{PhaseService._phase_label(db, phase_number)} fue aprobada.",
                           process_id=process.id, phase_number=nxt)

        # Correo (spec 2026-09-28 §5, #1b/#2), en esta misma transacción. La
        # fase `initial_docs` va al grupo `docs:{pid}` —sale junto con el
        # dictamen de sus documentos— y las demás solas (lo decide
        # `StudentMail`). `handoff`: la siguiente fase ya la opera T-soft.
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.phase_approved(
            db, process, phase_number=phase_number,
            phase_name=PhaseService._phase_label(db, phase_number),
            next_phase=nxt,
            next_name=(PhaseService._phase_label(db, nxt) if nxt is not None else None),
            handoff=nxt is not None and nxt >= PhaseService._handoff_phase())

        db.commit()
        return {"next_phase": nxt, "completed": nxt is None}

    @staticmethod
    def reject_phase(db: Session, process, phase_number: int, reviewer_id: int, reason: str,
                     event_payload: dict | None = None) -> None:
        """Rechaza una fase: la deja en 'rejected' con motivo y fija current_phase en ella.

        El alumno corrige y reenvía; ese reenvío la pasa a 'in_review', no a 'in_progress'.
        Misma guarda que `approve_phase`: sin ella un `n` arbitrario se escribía tal cual
        en `process.current_phase`.

        Y el mismo bloqueo previo (`_lock_process_row`, Ruling R14): sin él, un
        rechazo concurrente con la aprobación de la misma fase validaba sobre
        el `current_phase` viejo y regresaba el proceso a una fase ya liberada.

        La fase `format_b` solo pasa con el Formato B ya `rejected` en la sesión
        (`_format_b_guard`). `event_payload` se fusiona en el payload del evento
        `phase_rejected`, junto al `reason`.
        """
        PhaseService._lock_process_row(db, process)
        PhaseService.assert_can_transition(db, process, phase_number)
        PhaseService._format_b_guard(db, process, phase_number, "rejected")

        # Gemelo del cierre automático de `approve_phase`: rechazar la fase 2
        # tambien es un dictamen, y si la cita vigente quedo `in_progress` queda
        # igual de colgada que si se hubiera aprobado.
        if phase_number == PhaseService.PHASE_COTEJO:
            PhaseService._auto_close_cotejo_appointment(db, process, reviewer_id,
                                                        "phase_rejected")

        ph = PhaseService._ensure_phase(db, process.id, phase_number)
        ph.status = "rejected"
        ph.reviewed_by_id = reviewer_id
        ph.rejection_reason = reason or None
        process.current_phase = phase_number
        PhaseService._log(db, process.id, reviewer_id, "phase_rejected", phase_number,
                          {**(event_payload or {}), "reason": reason})

        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="PHASE_REJECTED",
                       title="Una fase necesita correcciones",
                       body=(reason or f"{PhaseService._phase_label(db, phase_number)} fue rechazada."),
                       process_id=process.id, phase_number=phase_number)

        # Correo (spec 2026-09-28 §5, #3): individual, con el motivo tal como
        # quedó; en esta misma transacción.
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.phase_rejected(
            db, process, phase_number=phase_number,
            phase_name=PhaseService._phase_label(db, phase_number),
            reason=reason or None)

        db.commit()


# Alias de módulo (como los mensajes de `format_b_service`): quien solo necesita
# el texto lo importa sin la clase.
FORMAT_B_ONLY_MSG = PhaseService.FORMAT_B_ONLY_MSG
