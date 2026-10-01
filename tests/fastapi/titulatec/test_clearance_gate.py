"""`ClearanceGate`: el candado ÚNICO de liberaciones para agendar el cotejo.

Spec `docs/superpowers/specs/2026-10-01-titulatec-biblioteca-caja-design.md`
§4.3 (requisito automático), §4.4 (el gate y sus consumidores), D6, D17 y §5
(invariantes 2 y 8). Tarea 5 del plan 2026-10-01-titulatec-biblioteca-caja.

Qué fija este archivo:

1. **Dónde aplica el candado de biblioteca** (invariante 8): SOLO donde la
   convocatoria tiene el requisito `library_clearance` ACTIVO y automático
   (`auto_source='library_clearance'`). La encuesta es incondicional.
2. **Una sola respuesta, cuatro formas de preguntarla**: `status`,
   `status_map` (en consultas fijas), `blockers`/`is_clear` y las dos
   cláusulas SQL dicen lo MISMO sobre los MISMOS casos.
3. **Los consumidores**: `AppointmentService.create` (`LibraryNotCleared`,
   después de las dos de la encuesta), los cubos de la cola (exclusión mutua
   intacta, «Liberaciones pendientes» con dos píldoras), la ficha de atender,
   `SelfBookingService.eligibility` (orden y mensajes, con el total formateado)
   y la etiqueta de la guarda de la fase 2.
4. **D17**: una cita ya agendada no se toca aunque el no adeudo vuelva a
   quedar pendiente; el candado se pregunta al ABRIR un intento.
5. **La prueba estructural** (invariante 2): fuera de los dos services dueños
   y del gate, ningún `.py` de la app compara `SurveyReview.status` ni
   `LibraryClearance.status`, ni pregunta por la liberación a los dueños.

Convocatoria «con candado» = `seed_defaults` (los DEFAULTS de hoy ya traen el
requisito automático, Ruling R2). Convocatoria «sin candado» = la lista VIEJA,
con el no adeudo marcado a mano (`auto_source` NULL): así queda toda
convocatoria hasta que corre el DML 22 de `activar-biblioteca-caja`.
"""
from __future__ import annotations

import ast
from datetime import date, time, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

import lxml.html
import pytest
from sqlalchemy import event

import itcj2.models  # noqa: F401
import itcj2.apps.titulatec as _tt_pkg

from tests.fastapi.titulatec.conftest import OFFICER_PERMS

# `ClearanceGate` se importa DENTRO de cada prueba (`_gate()`), como el resto
# de la suite importa sus services: así el RED de la tarea falla prueba por
# prueba y la estructural corre aunque el módulo todavía no exista.

URL = "/titulatec/admin/appointments"
NOTIFY = "itcj2.apps.titulatec.services.notify.notify_student"
# Agendar por la ruta pide `appointment.api.create`, que `OFFICER_PERMS` no trae.
SCHEDULE_PERMS = OFFICER_PERMS + ("titulatec.appointment.api.create",)

_D = date(2029, 5, 7)
_DOCS = ("birth_certificate", "high_school_cert", "curp")

# Spec §4.4.4, literal. El total va ya formateado por `format_amount`.
MSG_EN_BIBLIOTECA = ("El Centro de Información está revisando si tienes adeudo con la "
                     "biblioteca. Podrás agendar en cuanto se libere tu no adeudo.")
MSG_PAGO = ("Pasa a Caja (Recursos Financieros) a pagar $1,200.00; no necesitas "
            "cita. Podrás agendar en cuanto se libere tu no adeudo.")


def _gate():
    from itcj2.apps.titulatec.services.clearance_gate import ClearanceGate
    return ClearanceGate


def _msg(resp) -> str:
    return unquote(resp.headers.get("X-Tt-Error", ""))


def _lista_vieja(db, cohort):
    """La lista de requisitos ANTES del DML 22 (`activar-biblioteca-caja`): la
    encuesta automática y el no adeudo marcado a mano (`auto_source` NULL)."""
    from itcj2.apps.titulatec.models import CotejoRequirement

    filas = [
        CotejoRequirement(cohort_id=cohort.id, icon="clipboard-check",
                          label="Encuesta de egresados", code="graduate_survey",
                          auto_source="graduate_survey", order_index=0),
        CotejoRequirement(cohort_id=cohort.id, icon="book",
                          label="No-adeudo de biblioteca", code="library_clearance",
                          auto_source=None, order_index=1),
    ]
    db.add_all(filas)
    db.flush()
    return filas


class _Selects:
    """Cuenta los SELECT reales que pasan por la conexión del test."""

    def __init__(self, db):
        db.flush()                      # que un autoflush no cuente como consulta
        self.conexion = db.connection()
        self.sentencias = []

    def __enter__(self):
        event.listen(self.conexion, "before_cursor_execute", self._ver)
        return self

    def __exit__(self, *exc):
        event.remove(self.conexion, "before_cursor_execute", self._ver)
        return False

    def _ver(self, _conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            self.sentencias.append(" ".join(statement.split()))

    def __len__(self):
        return len(self.sentencias)


@pytest.fixture()
def esc(db_session, seed_phase_defs, seed_document_types, make_program, make_cohort,
        make_review_day, make_review_window, make_officer, make_student, make_process,
        make_document, make_survey_review, make_library_clearance):
    """Dos convocatorias de la MISMA carrera: `con` (candado de biblioteca,
    `seed_defaults`) y `sin` (lista vieja). Un espacio por convocatoria.

    `nuevo()` fabrica un egresado en fase 2 con los documentos iniciales
    aprobados; `encuesta` = estado de su `SurveyReview` («missing» = sin
    fila); `biblioteca` = estado de su `LibraryClearance` (`None` = sin fila);
    `**cols` va directo a esa fila (montos, `cleared_via`).
    """
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )

    seed_phase_defs()
    seed_document_types()
    prog = make_program("Ingenieria del Candado de Liberaciones")
    officer, pos = make_officer([prog], perm_codes=SCHEDULE_PERMS)
    con = make_cohort()
    CotejoRequirementService.seed_defaults(db_session, con.id, commit=False)
    sin = make_cohort()
    _lista_vieja(db_session, sin)

    ventanas = {}
    for clave, cohort, dia in (("con", con, _D), ("sin", sin, _D + timedelta(days=1))):
        fila_dia = make_review_day(cohort, day=dia)
        ventanas[clave] = make_review_window(fila_dia, officer, start="09:00", end="11:00",
                                             slot=30, cap=1, position=pos)

    def nuevo(*, cohort=None, encuesta="approved", biblioteca="pending", docs=True,
              status="active", fase=2, **cols):
        proc = make_process(make_student(), cohort=cohort or con, program=prog,
                            current_phase=fase, status=status, library_clearance=None)
        if biblioteca is not None:
            make_library_clearance(proc, status=biblioteca, **cols)
        if docs:
            for code in _DOCS:
                make_document(proc, type_code=code, review_status="approved")
        if encuesta != "missing":
            make_survey_review(proc, status=encuesta)
        return proc

    return {"prog": prog, "off": officer, "pos": pos, "con": con, "sin": sin,
            "w": ventanas, "nuevo": nuevo}


def _en_caja(esc, **kw):
    """Egresado «Por pagar en Caja»: adeudo $400 + donación $800 = $1,200."""
    return esc["nuevo"](biblioteca="awaiting_payment", debt_amount=Decimal("400.00"),
                        donation_amount=Decimal("800.00"),
                        total_amount=Decimal("1200.00"), **kw)


# ===========================================================================
# 1. ¿Dónde aplica el candado de biblioteca? (invariante 8)
# ===========================================================================
class TestLibraryRequired:
    def test_los_defaults_de_hoy_traen_el_candado(self, db_session, esc):
        assert _gate().library_required(db_session, esc["con"].id) is True

    def test_la_lista_vieja_no_lo_trae(self, db_session, esc):
        """Hasta que corre `activar-biblioteca-caja` nada cambia para nadie: el
        despliegue del código no bloquea el agendado (spec §4.4)."""
        assert _gate().library_required(db_session, esc["sin"].id) is False

    def test_tras_el_dml_la_misma_convocatoria_se_bloquea(self, db_session, esc):
        """Review Focus #5: lo que hace `22_library_requirement_auto.sql`
        (`auto_source='library_clearance'` sobre la fila vieja) enciende el
        candado SIN tocar nada más; el egresado pendiente deja de estar libre."""
        from itcj2.apps.titulatec.models import CotejoRequirement

        proc = esc["nuevo"](cohort=esc["sin"], biblioteca="pending")
        assert _gate().is_clear(db_session, proc.id) is True

        (db_session.query(CotejoRequirement)
         .filter_by(cohort_id=esc["sin"].id, code="library_clearance")
         .update({"auto_source": "library_clearance"}))
        db_session.flush()

        assert _gate().library_required(db_session, esc["sin"].id) is True
        assert _gate().status(db_session, proc.id)["library"] == "pending"
        assert _gate().is_clear(db_session, proc.id) is False

    def test_sin_lista_no_lo_trae_y_no_siembra(self, db_session, make_cohort):
        """Lectura pura, como `RequirementService.missing_required`: preguntar
        no escribe configuración."""
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )

        cohort = make_cohort()

        assert _gate().library_required(db_session, cohort.id) is False
        assert CotejoRequirementService.list(db_session, cohort.id, active_only=False) == []

    def test_el_requisito_automatico_inactivo_no_cuenta(self, db_session, esc):
        """«Requisito ACTIVO» (spec §4.4): uno apagado a mano en la BD no
        bloquea a nadie."""
        from itcj2.apps.titulatec.models import CotejoRequirement

        req = (db_session.query(CotejoRequirement)
               .filter_by(cohort_id=esc["con"].id, code="library_clearance").one())
        req.is_active = False
        db_session.flush()

        assert _gate().library_required(db_session, esc["con"].id) is False

    def test_el_mapa_en_una_sola_consulta(self, db_session, esc, make_cohort):
        vacia = make_cohort()

        with _Selects(db_session) as selects:
            mapa = _gate().library_required_map(
                db_session, [esc["con"].id, esc["sin"].id, vacia.id])

        assert mapa == {esc["con"].id: True, esc["sin"].id: False, vacia.id: False}
        assert len(selects) == 1, selects.sentencias
        assert _gate().library_required_map(db_session, []) == {}


# ===========================================================================
# 2. status / status_map / blockers / is_clear / cláusulas SQL: los MISMOS casos
# ===========================================================================
# (convocatoria, encuesta, biblioteca, status esperado, blockers esperados)
CASOS = [
    ("con", "approved", "cleared", {"survey": "approved", "library": "cleared"}, []),
    ("con", "approved", "pending", {"survey": "approved", "library": "pending"},
     ["library_pending"]),
    ("con", "approved", "awaiting_payment",
     {"survey": "approved", "library": "awaiting_payment"}, ["library_awaiting_payment"]),
    # Sin fila (alta durante el blue/green): cuenta como pendiente.
    ("con", "approved", None, {"survey": "approved", "library": "missing"},
     ["library_pending"]),
    ("con", "missing", "pending", {"survey": "missing", "library": "pending"},
     ["survey_missing", "library_pending"]),
    ("con", "in_review", "awaiting_payment",
     {"survey": "in_review", "library": "awaiting_payment"},
     ["survey_in_review", "library_awaiting_payment"]),
    ("con", "rejected", "cleared", {"survey": "rejected", "library": "cleared"},
     ["survey_rejected"]),
    # Convocatoria sin candado: la biblioteca no se pregunta, pase lo que pase.
    ("sin", "approved", "pending", {"survey": "approved", "library": "not_required"}, []),
    ("sin", "approved", None, {"survey": "approved", "library": "not_required"}, []),
    ("sin", "in_review", "awaiting_payment",
     {"survey": "in_review", "library": "not_required"}, ["survey_in_review"]),
    # Ya pasó su cotejo (6.º elemento = fase actual 3: la 2 quedó `approved`,
    # Ruling R21): sin un no adeudo liberado es `not_applicable` y no bloquea;
    # uno liberado sigue `cleared`; sin candado manda `not_required`.
    ("con", "approved", None, {"survey": "approved", "library": "not_applicable"}, [], 3),
    ("con", "approved", "pending",
     {"survey": "approved", "library": "not_applicable"}, [], 3),
    ("con", "in_review", "awaiting_payment",
     {"survey": "in_review", "library": "not_applicable"}, ["survey_in_review"], 3),
    ("con", "approved", "cleared", {"survey": "approved", "library": "cleared"}, [], 3),
    ("sin", "approved", "pending",
     {"survey": "approved", "library": "not_required"}, [], 3),
]


@pytest.fixture()
def casos(esc):
    out = []
    for conv, enc, bib, status, bloqueos, *resto in CASOS:
        fase = resto[0] if resto else 2
        out.append((esc["nuevo"](cohort=esc[conv], encuesta=enc, biblioteca=bib, fase=fase),
                    status, bloqueos))
    return out


class TestUnaSolaRespuesta:
    def test_status_y_blockers_por_proceso(self, db_session, casos):
        gate = _gate()
        for proc, esperado, bloqueos in casos:
            estado = gate.status(db_session, proc.id)
            assert estado == esperado, (proc.id, estado)
            assert gate.blockers(estado) == bloqueos, (proc.id, estado)
            assert gate.is_clear(db_session, proc.id) is (not bloqueos)

    def test_status_map_dice_lo_mismo_en_consultas_fijas(self, db_session, casos):
        gate = _gate()
        ids = [proc.id for proc, *_ in casos]

        with _Selects(db_session) as pocos:
            gate.status_map(db_session, ids[:2])
        with _Selects(db_session) as todos:
            mapa = gate.status_map(db_session, ids)

        assert mapa == {proc.id: esperado for proc, esperado, _ in casos}
        assert len(todos) <= 4, todos.sentencias
        assert len(todos) == len(pocos), (
            "status_map no puede crecer con el número de procesos: %r" % todos.sentencias)
        assert gate.status_map(db_session, []) == {}

    def test_las_clausulas_sql_parten_los_mismos_casos(self, db_session, casos):
        from itcj2.apps.titulatec.models import TitulationProcess

        gate = _gate()
        ids = [proc.id for proc, *_ in casos]
        base = db_session.query(TitulationProcess.id).filter(TitulationProcess.id.in_(ids))

        liberados = {pid for (pid,) in base.filter(gate.released_clause())}
        pendientes = {pid for (pid,) in base.filter(gate.not_released_clause())}

        assert liberados == {proc.id for proc, _e, bloqueos in casos if not bloqueos}
        assert pendientes == {proc.id for proc, _e, bloqueos in casos if bloqueos}
        assert liberados and pendientes, "el fixture no ejercita los dos lados"

    def test_proceso_inexistente_falla_cerrado(self, db_session):
        gate = _gate()
        assert gate.status(db_session, 987654321) == {"survey": "missing",
                                                      "library": "missing"}
        assert gate.is_clear(db_session, 987654321) is False


class TestBlockers:
    def test_encuesta_primero_luego_biblioteca(self):
        assert _gate().blockers({"survey": "rejected", "library": "awaiting_payment"}) == [
            "survey_rejected", "library_awaiting_payment"]

    @pytest.mark.parametrize("library", ["cleared", "not_required", "not_applicable"])
    def test_biblioteca_liberada_no_exigida_o_que_ya_no_aplica_no_bloquea(self, library):
        assert _gate().blockers({"survey": "approved", "library": library}) == []

    def test_los_dominios_de_estado_son_cerrados(self):
        """Ruling R21: `not_applicable` entra al dominio de `library` (lo
        produce el dueño, `LibraryClearanceService.NOT_APPLICABLE`) y el gate
        lo trata igual que `not_required`. Cada estado del dominio tiene una
        respuesta definida: libre (sin bloqueo) o un código de `BLOCKERS`."""
        from itcj2.apps.titulatec.services import clearance_gate as mod
        from itcj2.apps.titulatec.services.library_clearance_service import NOT_APPLICABLE

        assert mod.SURVEY_STATES == ("missing", "in_review", "approved", "rejected")
        assert mod.LIBRARY_STATES == ("missing", "pending", "awaiting_payment", "cleared",
                                      "not_required", "not_applicable")
        assert mod.LIBRARY_NOT_APPLICABLE == NOT_APPLICABLE == "not_applicable"
        libres = set()
        for estado in mod.LIBRARY_STATES:
            bloqueos = _gate().blockers({"survey": "approved", "library": estado})
            assert set(bloqueos) <= set(mod.LIBRARY_BLOCKERS), estado
            if not bloqueos:
                libres.add(estado)
        assert libres == {"cleared", "not_required", "not_applicable"}
        for estado in mod.SURVEY_STATES:
            bloqueos = _gate().blockers({"survey": estado, "library": "cleared"})
            assert (bloqueos == []) is (estado == "approved"), estado
            assert set(bloqueos) <= set(mod.SURVEY_BLOCKERS), estado

    def test_status_map_solo_devuelve_estados_del_dominio(self, db_session, casos):
        from itcj2.apps.titulatec.services import clearance_gate as mod

        mapa = _gate().status_map(db_session, [proc.id for proc, *_ in casos])

        assert {e["survey"] for e in mapa.values()} <= set(mod.SURVEY_STATES)
        assert {e["library"] for e in mapa.values()} <= set(mod.LIBRARY_STATES)
        assert "not_applicable" in {e["library"] for e in mapa.values()}, (
            "el fixture no ejercita el estado nuevo")

    def test_un_estado_desconocido_falla_cerrado(self):
        """Nunca un código fuera del conjunto cerrado: los consumidores traducen
        cada uno a un mensaje."""
        assert _gate().blockers({"survey": "???", "library": "???"}) == [
            "survey_missing", "library_pending"]

    def test_el_conjunto_cerrado_de_codigos(self):
        from itcj2.apps.titulatec.services import clearance_gate as mod

        assert mod.BLOCKERS == ("survey_missing", "survey_in_review", "survey_rejected",
                                "library_pending", "library_awaiting_payment")
        assert set(mod.SURVEY_BLOCKERS) | set(mod.LIBRARY_BLOCKERS) == set(mod.BLOCKERS)


# ===========================================================================
# 3. `AppointmentService.create`: la guarda dura (consumidor 1)
# ===========================================================================
class TestCreate:
    def _create(self, db, esc, proc, conv="con", hora=time(9, 0)):
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService
        return AppointmentService.create(db, proc.id, window_id=esc["w"][conv].id,
                                         slot_start=hora, created_by_id=esc["off"].id)

    @pytest.mark.parametrize("biblioteca,fragmento", [
        ("pending", "Centro de Información"),
        (None, "Centro de Información"),
        ("awaiting_payment", "Caja (Recursos Financieros)"),
    ], ids=["pendiente", "sin-fila", "por-pagar"])
    def test_sin_no_adeudo_liberado_no_agenda(self, db_session, esc, biblioteca, fragmento):
        from itcj2.apps.titulatec.services import appointment_errors as err
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService

        proc = esc["nuevo"](biblioteca=biblioteca)

        with pytest.raises(err.LibraryNotCleared) as exc:
            self._create(db_session, esc, proc)

        assert fragmento in str(exc.value)
        assert "este alumno" in str(exc.value), "el mensaje es del encargado"
        assert exc.value.status == (biblioteca or "missing")
        assert exc.value.refresca_la_vista is False, "entrada del usuario: 400"
        assert AppointmentService.get_for_process(db_session, proc.id) is None

    def test_la_encuesta_va_primero(self, db_session, esc):
        from itcj2.apps.titulatec.services import appointment_errors as err

        sin_enviar = esc["nuevo"](encuesta="missing", biblioteca="pending")
        en_revision = esc["nuevo"](encuesta="in_review", biblioteca="awaiting_payment")

        with pytest.raises(err.SurveyNotSubmitted):
            self._create(db_session, esc, sin_enviar)
        with pytest.raises(err.SurveyNotReleased) as exc:
            self._create(db_session, esc, en_revision)
        assert exc.value.status == "in_review"

    @pytest.mark.parametrize("via", ["legacy", "prior", "payment", "no_charge"])
    def test_liberado_agenda(self, db_session, esc, via):
        proc = esc["nuevo"](biblioteca="cleared", cleared_via=via)

        assert self._create(db_session, esc, proc).status == "scheduled"

    @pytest.mark.parametrize("biblioteca", ["pending", "awaiting_payment", None])
    def test_convocatoria_sin_candado_agenda_aunque_este_pendiente(
            self, db_session, esc, biblioteca):
        """Invariante 8: sin el requisito automático nadie se bloquea por
        biblioteca."""
        proc = esc["nuevo"](cohort=esc["sin"], biblioteca=biblioteca)

        assert self._create(db_session, esc, proc, conv="sin").status == "scheduled"

    def test_por_la_ruta_400_con_x_tt_error(self, db_session, esc, client_as):
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService

        proc = _en_caja(esc)

        resp = client_as(esc["off"]).post(
            f"{URL}/{proc.id}/schedule",
            data={"window_id": esc["w"]["con"].id, "slot_start": "09:00"})

        assert resp.status_code == 400, resp.text[:300]
        assert "Caja (Recursos Financieros)" in _msg(resp)
        assert AppointmentService.get_for_process(db_session, proc.id) is None


# ===========================================================================
# 4. D17: las citas ya agendadas no se tocan
# ===========================================================================
def test_la_cita_ya_agendada_sigue_vigente_y_se_puede_mover(db_session, esc):
    """El candado se pregunta al ABRIR un intento (`create`). Si después el no
    adeudo vuelve a quedar pendiente (transición, o Biblioteca revierte), la
    cita viva sigue vigente y el encargado la puede mover (`reschedule`)."""
    from itcj2.apps.titulatec.models import LibraryClearance
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    proc = esc["nuevo"](biblioteca="cleared")
    appt = AppointmentService.create(db_session, proc.id, window_id=esc["w"]["con"].id,
                                     slot_start=time(9, 0), created_by_id=esc["off"].id)
    fila = db_session.query(LibraryClearance).filter_by(process_id=proc.id).one()
    fila.status, fila.cleared_via = "pending", None
    db_session.flush()

    vigente = AppointmentService.get_for_process(db_session, proc.id)
    assert vigente is not None and vigente.id == appt.id and vigente.status == "scheduled"

    movida = AppointmentService.reschedule(db_session, vigente, window_id=esc["w"]["con"].id,
                                           slot_start=time(9, 30), actor_id=esc["off"].id)
    assert movida.is_current is True and movida.status == "scheduled"


# ===========================================================================
# 5. La cola del encargado (consumidores 2, 3 y 5)
# ===========================================================================
def _cubos(db, esc):
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    alcance = {esc["prog"].id}
    return {
        "por_agendar": {p.id for p in AppointmentService.list_pending_processes(
            db, allowed_program_ids=alcance)},
        "bloqueados": {p.id for p in AppointmentService.list_self_blocked_processes(
            db, allowed_program_ids=alcance)},
        "liberaciones": {p.id for p in AppointmentService.list_missing_clearance_processes(
            db, allowed_program_ids=alcance)},
    }


class TestCola:
    def test_cada_quien_en_un_solo_cubo(self, db_session, esc):
        liberado = esc["nuevo"](biblioteca="cleared")
        en_biblioteca = esc["nuevo"](biblioteca="pending")
        sin_fila = esc["nuevo"](biblioteca=None)
        en_caja = _en_caja(esc)
        sin_encuesta = esc["nuevo"](encuesta="missing", biblioteca="cleared")
        sin_candado = esc["nuevo"](cohort=esc["sin"], biblioteca="pending")

        cubos = _cubos(db_session, esc)
        esperado = {liberado.id: "por_agendar", sin_candado.id: "por_agendar",
                    en_biblioteca.id: "liberaciones", sin_fila.id: "liberaciones",
                    en_caja.id: "liberaciones", sin_encuesta.id: "liberaciones"}
        for pid, cubo in esperado.items():
            donde = sorted(nombre for nombre, ids in cubos.items() if pid in ids)
            assert donde == [cubo], "el proceso %d está en %s" % (pid, donde)

    def test_el_alcance_y_el_set_vacio(self, db_session, esc):
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService

        proc = esc["nuevo"](biblioteca="pending")

        assert proc.id in {p.id for p in AppointmentService.list_missing_clearance_processes(
            db_session, program_id=esc["prog"].id)}
        assert AppointmentService.list_missing_clearance_processes(
            db_session, allowed_program_ids=set()) == []

    def test_la_cola_pinta_liberaciones_pendientes_con_dos_pildoras(
            self, db_session, esc, client_as):
        en_biblioteca = esc["nuevo"](biblioteca="pending")
        en_caja = _en_caja(esc)
        sin_encuesta = esc["nuevo"](encuesta="missing", biblioteca="cleared")
        sin_candado = esc["nuevo"](cohort=esc["sin"], encuesta="in_review",
                                   biblioteca="pending")

        resp = client_as(esc["off"]).get(f"{URL}?date={_D.isoformat()}")

        assert resp.status_code == 200, resp.text[:300]
        assert "Liberaciones pendientes" in resp.text
        assert "Encuesta sin liberar" not in resp.text, "se quedó el rótulo viejo"
        arbol = lxml.html.fromstring(resp.text)

        def fila(proc):
            (nodo,) = arbol.xpath('//*[@id="appt-clearance-%d"]' % proc.id)
            assert not nodo.get("data-tt-drag") and not nodo.get("hx-get")
            return " ".join(nodo.text_content().split())

        assert "Liberada" in fila(en_biblioteca) and "En Biblioteca" in fila(en_biblioteca)
        assert "Por pagar en Caja" in fila(en_caja)
        assert "Encuesta pendiente" in fila(sin_encuesta) and "Liberado" in fila(sin_encuesta)
        # Sin candado: solo la píldora de la encuesta; ninguna de biblioteca.
        texto = fila(sin_candado)
        assert "En revisión" in texto
        assert "En Biblioteca" not in texto and "Liberado" not in texto

    def test_el_reagendar_con_biblioteca_pendiente_no_se_arrastra(
            self, db_session, esc, client_as, make_appointment):
        """I-3 extendido: reagendar abre un intento NUEVO y `create` lo
        rechazaría con `LibraryNotCleared`."""
        pendiente = esc["nuevo"](biblioteca="pending")
        make_appointment(pendiente, status="no_show", is_current=True)
        liberado = esc["nuevo"](biblioteca="cleared")
        make_appointment(liberado, status="no_show", is_current=True)

        resp = client_as(esc["off"]).get(f"{URL}?date={_D.isoformat()}")
        arbol = lxml.html.fromstring(resp.text)
        (fila,) = arbol.xpath('//*[@id="appt-requeue-%d"]' % pendiente.id)
        (control,) = arbol.xpath('//*[@id="appt-requeue-%d"]' % liberado.id)

        assert not fila.get("data-tt-drag"), "arrastrable con el no adeudo pendiente"
        assert "En Biblioteca" in fila.text_content()
        assert fila.get("hx-get"), "la ficha se sigue pudiendo abrir"
        assert control.get("data-tt-drag") == str(liberado.id)


# ===========================================================================
# 6. La ficha de atender (consumidor 5, I-3)
# ===========================================================================
class TestFicha:
    def test_no_ofrece_agendar_y_dice_por_que(self, db_session, esc, client_as,
                                              make_appointment):
        from itcj2.apps.titulatec.pages.appointments import _detail_ctx

        proc = _en_caja(esc)
        make_appointment(proc, status="no_show", is_current=True)

        ctx = _detail_ctx(db_session, proc.id, user_id=esc["off"].id)
        assert ctx["liberaciones_pendientes"] is True
        assert ctx["biblioteca_sin_liberar"] is True
        assert ctx["encuesta_sin_liberar"] is False
        assert ctx["library_status"] == "awaiting_payment"
        assert ctx["walkins_hoy"] == []

        resp = client_as(esc["off"]).get(
            f"{URL}/body?v=atender&date={_D.isoformat()}&selected={proc.id}")
        assert resp.status_code == 200, resp.text[:300]
        (ficha,) = lxml.html.fromstring(resp.text).xpath('//section[@id="appt-attend"]')
        texto = " ".join(ficha.text_content().split())
        assert "Por pagar en Caja" in texto
        assert "Se podrá agendar cuando se libere su no adeudo de biblioteca." in texto
        # Solo el aviso de lo que de verdad falta: la encuesta ya está liberada.
        assert "libere su encuesta" not in texto

    def test_con_todo_liberado_no_hay_aviso(self, db_session, esc, make_appointment):
        from itcj2.apps.titulatec.pages.appointments import _detail_ctx

        proc = esc["nuevo"](biblioteca="cleared")
        make_appointment(proc, status="no_show", is_current=True)

        ctx = _detail_ctx(db_session, proc.id, user_id=esc["off"].id)
        assert ctx["liberaciones_pendientes"] is False
        assert ctx["biblioteca_sin_liberar"] is False


# ===========================================================================
# 7. El egresado (consumidor 4): orden y mensajes
# ===========================================================================
class TestEligibility:
    def _elig(self, db, proc):
        from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService
        return SelfBookingService.eligibility(db, proc.id)

    @pytest.mark.parametrize("biblioteca", ["pending", None], ids=["pendiente", "sin-fila"])
    def test_biblioteca_en_revision(self, db_session, esc, biblioteca):
        from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

        e = self._elig(db_session, esc["nuevo"](biblioteca=biblioteca))

        assert e["can_book"] is False and e["can_walkin"] is False
        assert e["reason"] == "biblioteca_en_revision"
        assert SelfBookingService.message_for(e["reason"]) == MSG_EN_BIBLIOTECA

    def test_pago_pendiente_con_el_total(self, db_session, esc):
        from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

        e = self._elig(db_session, _en_caja(esc))

        assert e["can_book"] is False and e["can_walkin"] is False
        assert e["reason"] == "pago_pendiente"
        assert e["library_total"] == Decimal("1200.00")
        assert SelfBookingService.message_for(
            e["reason"], total=e["library_total"]) == MSG_PAGO

    def test_sin_total_el_mensaje_no_deja_el_marcador(self):
        from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

        texto = SelfBookingService.message_for("pago_pendiente")
        assert "{" not in texto and "None" not in texto
        assert texto.startswith("Pasa a Caja (Recursos Financieros) a pagar;")

    def test_la_encuesta_va_antes_que_la_biblioteca(self, db_session, esc):
        e = self._elig(db_session, _en_caja(esc, encuesta="in_review"))

        assert e["reason"] == "encuesta_en_revision"

    def test_inactivo_y_fase_aprobada_van_antes(self, db_session, esc):
        from itcj2.apps.titulatec.models import ProcessPhase

        inactivo = esc["nuevo"](biblioteca="pending", status="completed")
        aprobado = esc["nuevo"](biblioteca="pending")
        (db_session.query(ProcessPhase)
         .filter_by(process_id=aprobado.id, phase_number=2)
         .update({"status": "approved"}))
        db_session.flush()

        assert self._elig(db_session, inactivo)["reason"] == "proceso_inactivo"
        assert self._elig(db_session, aprobado)["reason"] == "fase_aprobada"

    def test_convocatoria_sin_candado_puede_agendar(self, db_session, esc):
        e = self._elig(db_session, esc["nuevo"](cohort=esc["sin"], biblioteca="pending"))

        assert e["can_book"] is True and e["reason"] is None
        assert e["library_total"] is None

    def test_book_levanta_la_razon_con_el_total(self, db_session, esc):
        from itcj2.apps.titulatec.services.appointment_errors import SelfBookingNotAllowed
        from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

        proc = _en_caja(esc)

        with pytest.raises(SelfBookingNotAllowed) as exc:
            SelfBookingService.book(db_session, proc.id, esc["w"]["con"].id, time(9, 0),
                                    proc.student_id)

        assert exc.value.reason == "pago_pendiente"
        assert str(exc.value) == MSG_PAGO
        assert exc.value.refresca_la_vista is False

    def test_cada_bloqueo_del_gate_tiene_razon_y_mensaje(self):
        from itcj2.apps.titulatec.services.clearance_gate import BLOCKERS
        from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

        for codigo in BLOCKERS:
            razon = SelfBookingService._CLEARANCE_REASONS[codigo]
            assert razon in SelfBookingService.MENSAJES, codigo


# ===========================================================================
# 8. La guarda de la fase 2 (consumidor 6): sufijo ASCII por estado
# ===========================================================================
@pytest.mark.parametrize("biblioteca,sufijo", [
    ("pending", "en revision por Biblioteca"),
    (None, "en revision por Biblioteca"),
    ("awaiting_payment", "pendiente de pago en Caja"),
], ids=["pendiente", "sin-fila", "por-pagar"])
def test_la_etiqueta_de_la_fase_2_dice_en_que_va_el_no_adeudo(
        db_session, esc, make_user, biblioteca, sufijo):
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    proc = (_en_caja(esc) if biblioteca == "awaiting_payment"
            else esc["nuevo"](biblioteca=biblioteca))
    revisor = make_user()

    with patch(NOTIFY):
        with pytest.raises(ValueError) as exc:
            PhaseService.approve_phase(db_session, proc, 2, reviewer_id=revisor.id)

    assert f"No-adeudo de biblioteca ({sufijo})" in str(exc.value)


# ===========================================================================
# 9. La píldora (`_macros.html::library_clearance_pill`)
# ===========================================================================
def _pildora(status, via=None):
    from itcj2.apps.titulatec.pages.nav import titulatec_templates

    tpl = titulatec_templates.env.from_string(
        '{% from "titulatec/_macros.html" import library_clearance_pill %}'
        '{{ library_clearance_pill(status, via) }}')
    return " ".join(tpl.render(status=status, via=via).split())


@pytest.mark.parametrize("status,via,texto", [
    ("pending", None, "En Biblioteca"),
    ("missing", None, "En Biblioteca"),
    ("awaiting_payment", None, "Por pagar en Caja"),
    ("cleared", "payment", "Liberado"),
    ("cleared", "no_charge", "Liberado"),
    ("cleared", "legacy", "Liberado"),
    ("cleared", None, "Liberado"),
    ("cleared", "prior", "Constancia previa"),
])
def test_la_pildora_de_cada_estado(status, via, texto):
    html = _pildora(status, via)

    assert "tt-pill" in html and texto in html


def test_la_pildora_no_pinta_nada_si_no_se_exige():
    """`not_required` (convocatoria sin candado): ni píldora ni código crudo."""
    assert _pildora("not_required") == ""


def test_la_pildora_dice_no_aplica_si_ya_paso_su_cotejo():
    """Ruling R21: `not_applicable` (fase 2 ya aprobada sin no adeudo
    liberado) es una píldora neutra, nunca «En Biblioteca» ni el código crudo."""
    html = _pildora("not_applicable")

    assert "tt-pill" in html
    assert "No aplica (cotejo ya liberado)" in html
    assert "En Biblioteca" not in html and "not_applicable" not in html


def test_cada_estado_del_dominio_tiene_su_pildora_sin_codigo_crudo():
    from itcj2.apps.titulatec.services.clearance_gate import LIBRARY_STATES

    for estado in LIBRARY_STATES:
        assert estado not in _pildora(estado), estado


# ===========================================================================
# 10. Estructural (invariante 2)
# ===========================================================================
_APP = Path(_tt_pkg.__file__).resolve().parent
_DUENOS = {"services/survey_review_service.py", "services/library_clearance_service.py",
           "services/clearance_gate.py"}
_MODELOS = {"SurveyReview", "LibraryClearance"}
_SERVICIOS = {"SurveyReviewService", "LibraryClearanceService"}
_API_LIBERACION = {"release_status", "release_status_map", "is_released"}
_FILTROS = {"in_", "notin_", "not_in", "is_", "is_not", "isnot"}


def _fuentes():
    for path in sorted(_APP.rglob("*.py")):
        if "__pycache__" not in path.parts:
            yield path.relative_to(_APP).as_posix(), ast.parse(
                path.read_text(encoding="utf-8"), filename=str(path))


def _status_de_modelo(nodo) -> bool:
    return (isinstance(nodo, ast.Attribute) and nodo.attr == "status"
            and isinstance(nodo.value, ast.Name) and nodo.value.id in _MODELOS)


def _comparaciones(arbol):
    """`SurveyReview.status ==/!= …` y `….status.in_(…)` (y familia)."""
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Compare):
            if any(_status_de_modelo(o) for o in (nodo.left, *nodo.comparators)):
                yield nodo.lineno, ast.unparse(nodo)
        elif (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
              and nodo.func.attr in _FILTROS and _status_de_modelo(nodo.func.value)):
            yield nodo.lineno, ast.unparse(nodo)


def _preguntas_de_liberacion(arbol):
    """`SurveyReviewService.release_status(…)` y familia."""
    for nodo in ast.walk(arbol):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr in _API_LIBERACION
                and isinstance(nodo.func.value, ast.Name)
                and nodo.func.value.id in _SERVICIOS):
            yield nodo.lineno, ast.unparse(nodo)


def test_nadie_fuera_del_gate_compara_el_estado_de_las_liberaciones():
    """Fuera de `SurveyReviewService`, `LibraryClearanceService` y
    `ClearanceGate`, ningún `.py` de la app filtra por `SurveyReview.status`
    ni por `LibraryClearance.status`: «¿le faltan liberaciones?» tiene UNA
    fuente (spec §5, invariante 2)."""
    ofensores, en_duenos, en_gate = [], 0, 0
    for ruta, arbol in _fuentes():
        hallazgos = list(_comparaciones(arbol))
        if ruta in _DUENOS:
            en_duenos += len(hallazgos)
            en_gate += len(hallazgos) if ruta == "services/clearance_gate.py" else 0
            continue
        ofensores += ["%s:%d: %s" % (ruta, linea, src) for linea, src in hallazgos]

    # Controles positivos: el detector SÍ ve las comparaciones donde deben vivir.
    assert en_duenos >= 6, "el detector no encontró las comparaciones de los dueños"
    assert en_gate >= 2, "las cláusulas SQL del gate deberían comparar los dos estados"
    assert not ofensores, ("comparan el estado de una liberación fuera del gate:\n"
                           + "\n".join(ofensores))


def test_solo_el_gate_pregunta_a_los_duenos_por_la_liberacion():
    """`release_status`/`release_status_map`/`is_released` solo se llaman
    desde el gate (y dentro de los propios dueños): un consumidor que los
    llamara tendría que compararlos contra `'approved'`/`'cleared'` por su
    cuenta, que es justo lo que el invariante 2 prohíbe."""
    ofensores, en_gate = [], 0
    for ruta, arbol in _fuentes():
        hallazgos = list(_preguntas_de_liberacion(arbol))
        if ruta == "services/clearance_gate.py":
            en_gate += len(hallazgos)
        if ruta in _DUENOS:
            continue
        ofensores += ["%s:%d: %s" % (ruta, linea, src) for linea, src in hallazgos]

    assert en_gate >= 2, "el gate debería preguntarle a los dos dueños"
    assert not ofensores, ("preguntan por la liberación sin pasar por ClearanceGate:\n"
                           + "\n".join(ofensores))
