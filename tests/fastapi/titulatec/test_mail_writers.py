"""Barrido de escritores (spec 2026-09-28 §5): ningún escritor de dictamen, de
cita o del no adeudo de biblioteca (spec 2026-10-01 §4.11) se queda sin encolar
su correo por olvido.

Recorre por AST cada función de `itcj2/apps/titulatec/services/**/*.py` y de
`pages/*.py` (métodos de clase y funciones de módulo; lo anidado cuenta como
parte de su función) con DOS detectores:

1. EVENTOS — el contrato del plan. Si la función escribe un
   `ProcessEvent(event_type=…)` o un `<X>._log(db, pid, actor, <event_type>, …)`
   con un literal del catálogo (`EVENTO_A_CORREO`), tiene que llamar a la
   función de `StudentMail` que le toca. Se lee el ARGUMENTO `event_type`, no
   cualquier literal de la llamada: `ProcessService.cancel` lleva
   `"appointment_cancelled"` como LLAVE de su payload y no es ese evento.
   Por AST y no por regex de línea: en `AppointmentService.create` el literal
   va en su propia línea, y en `DocumentService.review` es un `if/else`.
2. ESTADOS — lo que enumeró el barrido de la tarea. Asignar `.review_status`
   (salvo el `'pending'` de la subida) o `.status` a
   approved|rejected|cancelled|no_show|attended|superseded (literal, o un
   nombre local que se asignó con uno de ellos), pasarlo como keyword a un
   constructor/`.values()`/`.update({...})`, o construir `ReviewAppointment`
   / `SurveyReview`. Sin este detector, las entradas de la lista blanca que no
   escriben ningún evento del catálogo (`SlotService._open_new_attempt`,
   `PhaseService._auto_close_cotejo_appointment`...) serían letra muerta.
   Límite conocido: un `.status = <parámetro>` no se ve (así escriben
   `FormatBService.review` o `RequirementService`, fuera del catálogo).

El registro (`MAPEO` + `LISTA_BLANCA`) es EXACTO en los dos sentidos: una
función NUEVA que escriba y no esté registrada falla, y una entrada que ya no
escribe (renombrada, borrada) también — así la lista blanca no se pudre.

La presencia de la llamada es por FUNCIÓN, no por rama: `AppointmentService.
cancel` llama a `appointment_changed` solo si el actor no es el alumno y
`notify=True`. Esas ramas sin correo las fijan pruebas de comportamiento
(`RAMAS_SIN_CORREO`), y aquí se exige que existan.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import itcj2.apps.titulatec as _app

_APP = Path(_app.__file__).resolve().parent
_ITCJ2 = _APP.parents[1]
_HOOKS_TEST = Path(__file__).with_name("test_mail_hooks.py")

# Evento del catálogo -> función de `StudentMail` que lo encola.
EVENTO_A_CORREO = {
    "document_approved": "doc_reviewed",
    "document_rejected": "doc_reviewed",
    "phase_approved": "phase_approved",
    "phase_rejected": "phase_rejected",
    "survey_review_approved": "survey_result",
    "survey_review_rejected": "survey_result",
    "survey_review_revoked": "survey_result",
    # Constancia previa (D9, Tarea 6): `register_prior` construye `SurveyReview`
    # directo en `approved` y escribe este evento; el correo es el MISMO
    # `survey_result` (con `origin="prior"` en el payload).
    "survey_review_prior": "survey_result",
    "appointment_scheduled": "appointment_changed",
    "appointment_rescheduled": "appointment_changed",
    "appointment_cancelled": "appointment_changed",
    "appointment_no_show": "appointment_no_show",
    # No adeudo de biblioteca (spec 2026-10-01-titulatec-biblioteca-caja-design.md
    # §4.11, Tarea 10): los 8 eventos de `LibraryClearanceService`, uno por
    # camino. Pasar a Caja o corregir el monto -> `library_ready`; quedar
    # liberado (sin cargo, pago o constancia previa) -> `library_cleared`;
    # revertir o deshacer -> `library_reverted`.
    "library_debt_registered": "library_ready",
    "library_amount_corrected": "library_ready",
    "library_no_charge": "library_cleared",
    "library_payment_registered": "library_cleared",
    "library_prior_registered": "library_cleared",
    "library_payment_reverted": "library_reverted",
    "library_clearance_reverted": "library_reverted",
    "library_prior_undone": "library_reverted",
}

# Escritores que SÍ encolan: función -> la de `StudentMail` que deben llamar.
MAPEO = {
    "DocumentService.review": "doc_reviewed",
    "PhaseService.approve_phase": "phase_approved",
    "PhaseService.reject_phase": "phase_rejected",
    "SurveyReviewService.approve": "survey_result",
    "SurveyReviewService.reject": "survey_result",
    "SurveyReviewService.revoke": "survey_result",
    "SurveyReviewService.register_prior": "survey_result",
    "AppointmentService.create": "appointment_changed",
    "AppointmentService.reschedule": "appointment_changed",
    "AppointmentService.cancel": "appointment_changed",
    "AppointmentService.mark_no_show": "appointment_no_show",
    # `register`/`register_no_debt_bulk` no escriben eventos: delegan en
    # `_mark_ready` (pasa a Caja / corrige) y `_clear_no_charge` (total 0).
    "LibraryClearanceService._mark_ready": "library_ready",
    "LibraryClearanceService._clear_no_charge": "library_cleared",
    "LibraryClearanceService.register_payment": "library_cleared",
    "LibraryClearanceService.register_prior": "library_cleared",
    "LibraryClearanceService.revert_payment": "library_reverted",
    "LibraryClearanceService.revert_clearance": "library_reverted",
    "LibraryClearanceService.undo_prior": "library_reverted",
}

# Escritores que NO encolan, cada uno con su motivo.
LISTA_BLANCA = {
    "AppointmentService.mark_attended":
        "«asistió» no lleva correo: lo cubre el avance de la fase 2 "
        "(spec §5, «Sin correo»).",
    "PhaseService._auto_close_cotejo_appointment":
        "cierra la cita `in_progress` dentro de approve_phase/reject_phase de "
        "la fase 2: el correo es el del dictamen, en la misma transacción.",
    "ProcessService.cancel":
        "revocación: su aviso es `send_process_cancelled` (D3) y la cita la "
        "cancela con notify=False, sin correo (spec §5, «Sin correo»).",
    "SlotService._open_new_attempt":
        "cierra la vigente (superseded) al abrir un intento nuevo; el correo "
        "lo encola quien abrió el intento (AppointmentService.create/.reschedule).",
    "SlotService.assign":
        "inserta la cita pero no conoce el evento ni commitea; el correo lo "
        "encolan sus dos llamadores, AppointmentService.create y .reschedule.",
    "SlotService.assign_batch":
        "reparto masivo SIN llamadores (test_assign_batch_sigue_sin_llamadores): "
        "quien lo vuelva a cablear tiene que encolar appointment_changed.",
    "SurveyReviewService.open_for_submission":
        "la abre el envío de la encuesta, acción del propio egresado: sin "
        "correo por sus propias acciones (spec §1.2).",
    "EnrollmentRequestService._issue_link_for_account":
        "EnrollmentRequest (inscripción), no el proceso: sus correos son los 6 "
        "de TitulaTecEmailHelper, que no se tocan (D3).",
    "EnrollmentRequestService.reject":
        "EnrollmentRequest (inscripción), no el proceso: sus correos son los 6 "
        "de TitulaTecEmailHelper, que no se tocan (D3).",
    "ImportService.import_rows":
        "alta del proceso: la fase 0 (intake) nace `approved`; no es un "
        "dictamen y el alta tiene sus propios avisos.",
}

# Ramas SIN correo dentro de funciones mapeadas: el detector solo ve que la
# llamada existe en la función. Las fijan estas pruebas de comportamiento.
RAMAS_SIN_CORREO = {
    "AppointmentService.cancel": (
        "test_alumno_cancela_no_encola",
        "test_revocar_proceso_no_encola_cancelacion_de_cita",
    ),
    # «Atender ahora» (D7, `start_now=True`): el egresado está enfrente; la
    # cita nace `in_progress` sin correo ni aviso de «agendada».
    "AppointmentService.create": ("test_atender_ahora_no_encola",),
    # Ruling R10 (b): corregir sin cambiar nada (mismo adeudo, misma donación
    # congelada, misma nota) es no-op: ni evento, ni aviso, ni correo.
    "LibraryClearanceService._mark_ready": ("test_correccion_sin_cambios_no_encola",),
}

_ESTADOS_VIGILADOS = frozenset({"approved", "rejected", "cancelled", "no_show",
                                "attended", "superseded"})
_ATRIBUTOS = frozenset({"status", "review_status"})
_MODELOS_CREADOS = frozenset({"ReviewAppointment", "SurveyReview"})


# ---------------------------------------------------------------------------
# Detectores
# ---------------------------------------------------------------------------
def _archivos():
    yield from sorted((_APP / "services").rglob("*.py"))
    yield from sorted((_APP / "pages").glob("*.py"))


def _funciones_de(arbol, stem):
    """(nombre, nodo) de las funciones de módulo y de los métodos de clase."""
    for nodo in arbol.body:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield f"{stem}.{nodo.name}", nodo
        elif isinstance(nodo, ast.ClassDef):
            for item in nodo.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield f"{nodo.name}.{item.name}", item


def _funciones():
    """{nombre: (archivo, nodo)}. Un nombre repetido fusionaría dos escritores
    en silencio: se exige único."""
    out = {}
    for path in _archivos():
        arbol = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for nombre, nodo in _funciones_de(arbol, path.stem):
            assert nombre not in out, f"nombre de función repetido: {nombre}"
            out[nombre] = (path, nodo)
    return out


def _callee(func):
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _kw(call, nombre):
    return next((k.value for k in call.keywords if k.arg == nombre), None)


def _literales(expr):
    """Literales que puede valer `event_type`: el propio, o las ramas de un
    `a if cond else b` (no la condición). Vacío = no se puede verificar."""
    if isinstance(expr, ast.IfExp):
        return _literales(expr.body) | _literales(expr.orelse)
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return {expr.value}
    return set()


def _eventos(fn):
    """(eventos escritos, líneas con un `event_type` que no es literal)."""
    eventos, opacos = set(), []
    for nodo in ast.walk(fn):
        if not isinstance(nodo, ast.Call):
            continue
        callee = _callee(nodo.func)
        if callee == "ProcessEvent":
            expr = _kw(nodo, "event_type")
        elif callee == "_log":
            # Firma de todos los `_log`: (db, process_id, actor_id, event_type, ...)
            # — la fija `test_todo_log_recibe_event_type_en_cuarto_lugar`.
            expr = _kw(nodo, "event_type") or (nodo.args[3] if len(nodo.args) > 3 else None)
        else:
            continue
        lits = _literales(expr) if expr is not None else set()
        if not lits:
            opacos.append(nodo.lineno)
        eventos |= lits
    return eventos, opacos


def _correos(fn):
    """Funciones de `StudentMail` que la función llama."""
    return {n.func.attr for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "StudentMail"}


def _consts(expr):
    return {n.value for n in ast.walk(expr)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _escrituras_de_estado(fn):
    """Descripción de cada escritura vigilada de la función (ver docstring)."""
    # Nombres locales asignados con un estado vigilado: `st = "approved" if … else …`
    locales = {t.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
               and _consts(n.value) & _ESTADOS_VIGILADOS
               for t in n.targets if isinstance(t, ast.Name)}

    def _vigilado(attr, valor):
        if attr == "review_status":
            return not (isinstance(valor, ast.Constant) and valor.value == "pending")
        nombres = {n.id for n in ast.walk(valor) if isinstance(n, ast.Name)}
        return bool(_consts(valor) & _ESTADOS_VIGILADOS or nombres & locales)

    hallazgos = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if (isinstance(t, ast.Attribute) and t.attr in _ATRIBUTOS
                        and _vigilado(t.attr, n.value)):
                    hallazgos.append(f".{t.attr} = … (línea {n.lineno})")
        elif isinstance(n, ast.Call):
            callee = _callee(n.func) or ""
            if callee in _MODELOS_CREADOS:
                hallazgos.append(f"{callee}(…) (línea {n.lineno})")
            if callee[:1].isupper() or callee == "values":
                for k in n.keywords:
                    if k.arg in _ATRIBUTOS and _vigilado(k.arg, k.value):
                        hallazgos.append(f"{callee}({k.arg}=…) (línea {n.lineno})")
            if callee == "update":
                for arg in n.args:
                    if isinstance(arg, ast.Dict):
                        for k, v in zip(arg.keys, arg.values):
                            if (isinstance(k, ast.Constant) and k.value in _ATRIBUTOS
                                    and _vigilado(k.value, v)):
                                hallazgos.append(f".update({{{k.value!r}: …}}) "
                                                 f"(línea {n.lineno})")
    return hallazgos


def _escritores():
    """{nombre: {"eventos": set, "estados": list, "correos": set, "archivo": Path}}
    de toda función que escribe algo vigilado."""
    out = {}
    for nombre, (path, fn) in _funciones().items():
        if fn.name == "_log":            # el ayudante mismo, no un escritor
            continue
        eventos, _ = _eventos(fn)
        eventos &= EVENTO_A_CORREO.keys()
        estados = _escrituras_de_estado(fn)
        if eventos or estados:
            out[nombre] = {"eventos": eventos, "estados": estados,
                           "correos": _correos(fn), "archivo": path}
    return out


# ---------------------------------------------------------------------------
# El contrato
# ---------------------------------------------------------------------------
def test_cada_evento_del_catalogo_encola_su_correo():
    faltan = []
    for nombre, info in sorted(_escritores().items()):
        if nombre in LISTA_BLANCA:
            continue
        for evento in sorted(info["eventos"]):
            esperado = EVENTO_A_CORREO[evento]
            if esperado not in info["correos"]:
                faltan.append(f"{nombre} ({info['archivo'].name}) escribe `{evento}` "
                              f"y no llama StudentMail.{esperado}")
    assert not faltan, "Eventos del catálogo sin su correo:\n  " + "\n  ".join(faltan)


def test_ningun_escritor_sin_registrar_ni_entradas_muertas():
    escritores = _escritores()
    registrados = set(MAPEO) | set(LISTA_BLANCA)
    nuevos = sorted(set(escritores) - registrados)
    muertos = sorted(registrados - set(escritores))

    assert not nuevos, (
        "Escritor NUEVO de un dictamen o de una cita sin registrar. Agrégalo a "
        "MAPEO (y encola su correo) o a LISTA_BLANCA con su motivo:\n  "
        + "\n  ".join(f"{n} ({escritores[n]['archivo'].name}): "
                      f"eventos={sorted(escritores[n]['eventos'])} "
                      f"estados={escritores[n]['estados']}" for n in nuevos))
    assert not muertos, (
        "Entradas del registro que ya no escriben nada vigilado (¿renombradas o "
        "borradas?): " + ", ".join(muertos))
    assert not set(MAPEO) & set(LISTA_BLANCA)


def test_el_mapeo_llama_lo_que_dice():
    escritores = _escritores()
    for nombre, correo in MAPEO.items():
        info = escritores[nombre]
        assert correo in info["correos"], f"{nombre} no llama StudentMail.{correo}"
        # Lo que escribe tiene que ser justo lo que ese correo cubre.
        for evento in info["eventos"]:
            assert EVENTO_A_CORREO[evento] == correo, (nombre, evento, correo)


def test_la_lista_blanca_no_encola_nada():
    """Una función de la lista blanca que empieza a encolar va al MAPEO."""
    escritores = _escritores()
    encolan = {n: sorted(escritores[n]["correos"]) for n in LISTA_BLANCA
               if escritores[n]["correos"]}
    assert not encolan, f"Estas ya encolan; muévelas a MAPEO: {encolan}"


def test_cada_evento_del_no_adeudo_tiene_su_correo():
    """Los 8 de `LIBRARY_EVENT_TYPES` están en el catálogo: un evento nuevo del
    no adeudo sin correo registrado no pasaría inadvertido (el detector solo
    vigila los eventos que ya están en `EVENTO_A_CORREO`)."""
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LIBRARY_EVENT_TYPES,
    )

    assert set(LIBRARY_EVENT_TYPES) <= set(EVENTO_A_CORREO)
    assert {EVENTO_A_CORREO[e] for e in LIBRARY_EVENT_TYPES} == {
        "library_ready", "library_cleared", "library_reverted"}


def test_ningun_event_type_opaco():
    """Un `event_type` que no es literal no se puede verificar."""
    opacos = []
    for nombre, (path, fn) in _funciones().items():
        if fn.name == "_log":
            continue
        _, lineas = _eventos(fn)
        opacos += [f"{path.name}:{ln} ({nombre})" for ln in lineas]
    assert not opacos, "event_type no literal: " + ", ".join(opacos)


def test_todo_log_recibe_event_type_en_cuarto_lugar():
    """El detector lee el 4.º argumento posicional de `_log`: que siga siéndolo."""
    firmas = {}
    for nombre, (_path, fn) in _funciones().items():
        if fn.name == "_log":
            firmas[nombre] = [a.arg for a in fn.args.args][:4]
    assert firmas, "no se encontró ningún `_log`: el detector no ve nada"
    for nombre, args in firmas.items():
        assert args[3:4] == ["event_type"], (nombre, args)


def test_assign_batch_sigue_sin_llamadores():
    """El motivo de su lista blanca: si alguien lo cablea, que se entere aquí."""
    llamadas = []
    for path in _ITCJ2.rglob("*.py"):
        texto = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"\.assign_batch\(", texto):
            linea = texto.count("\n", 0, m.start()) + 1
            llamadas.append(f"{path.relative_to(_ITCJ2)}:{linea}")
    assert not llamadas, "SlotService.assign_batch ya tiene llamadores: " + ", ".join(llamadas)


def test_las_ramas_sin_correo_tienen_prueba_de_comportamiento():
    texto = _HOOKS_TEST.read_text(encoding="utf-8")
    for nombre, pruebas in RAMAS_SIN_CORREO.items():
        assert nombre in MAPEO
        for prueba in pruebas:
            assert f"def {prueba}(" in texto, f"falta {prueba} en {_HOOKS_TEST.name}"


# ---------------------------------------------------------------------------
# Que el detector no sea decorativo
# ---------------------------------------------------------------------------
_MUESTRA = '''
class X:
    @staticmethod
    def agenda(db, appt):
        X._log(
            db, appt.process_id, 1,
            "appointment_scheduled",
            {"a": 1})

    @staticmethod
    def dictamina(db, status):
        X._log(db, 1, 2, "document_approved" if status == "approved"
               else "document_rejected", 1)
        StudentMail.doc_reviewed(db, None)

    @staticmethod
    def revoca(db, proc):
        db.add(ProcessEvent(event_type="process_cancelled",
                            payload={"appointment_cancelled": True}))
        proc.status = "cancelled"

    @staticmethod
    def importa(db):
        st = "approved" if 1 else "pending"
        db.add(ProcessPhase(status=st))
        db.add(Document(review_status="pending"))
'''


def test_el_detector_ve_lo_que_tiene_que_ver():
    fns = dict(_funciones_de(ast.parse(_MUESTRA), "muestra"))

    def _estados(fn):
        return [h.split(" (línea")[0] for h in _escrituras_de_estado(fn)]

    # literal en su propia línea (AppointmentService.create)
    assert _eventos(fns["X.agenda"]) == ({"appointment_scheduled"}, [])
    # `if/else`: las dos ramas, no la condición (DocumentService.review)
    assert _eventos(fns["X.dictamina"])[0] == {"document_approved", "document_rejected"}
    assert _correos(fns["X.dictamina"]) == {"doc_reviewed"}
    # la LLAVE del payload no es el event_type (ProcessService.cancel)
    assert _eventos(fns["X.revoca"])[0] == {"process_cancelled"}
    assert _estados(fns["X.revoca"]) == [".status = …"]
    # nombre local con un estado vigilado; `review_status='pending'` no es dictamen
    assert _estados(fns["X.importa"]) == ["ProcessPhase(status=…)"]
