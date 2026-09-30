"""Las 7 reglas de elegibilidad del auto-agendado (spec 2026-09-15 §3; regla 5
nueva por D13 de 2026-09-29-titulatec-cotejo-espacios-design.md, 2026-09-30 —
no confundir con el otro D13, el de la partición dura/alumno del 2026-09-15).

**El ORDEN de evaluación es parte del contrato**, no un detalle de
implementación: la primera regla que falla es la que se reporta, así que un
proceso inactivo **y** sin encuesta dice `proceso_inactivo`, no `sin_encuesta`.
Por eso hay un test por fila de la tabla y van EN ESE ORDEN, más uno que mide
el orden en sí.

Los tres casos que **sí** dejan agendar son el corazón de la feature y llevan
test propio: `attended` con la fase 2 **rechazada** (D5, endurecido por D13
2026-09-30 -antes bastaba con que NO estuviera aprobada; ahora hace falta que
SÍ tenga veredicto, o cae en la regla 5 nueva, `cotejo_en_dictamen`-),
`no_show` (D7) y `cancelled` (D6). Ninguno de los tres se lee de
`appt.status` para la regla 2 — el corte es la FASE aprobada (`ProcessPhase`
de `PhaseService.PHASE_COTEJO`).

Y el que se olvida: el bloqueado por D9 (regla 6) pierde el derecho a
*reservar un lugar*, no el de *presentarse* a una atención anunciada como
abierta a todos (`can_walkin`).
"""
from datetime import time

import pytest

from itcj2.apps.titulatec.services.appointment_service import AppointmentService
from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService
from itcj2.core.utils.timezone import db_now

DOCS_INICIALES = ("birth_certificate", "high_school_cert", "curp")


# ---------------------------------------------------------------- andamiaje
@pytest.fixture()
def alumno(agenda_slots, make_survey_review):
    """`agenda_slots` con la encuesta de egresados YA LIBERADA para `p1`.

    Es el estado «puede agendar»: proceso activo, fase 2 sin aprobar,
    solicitud de liberación LIBERADA por GTV (D1, revierte D2 del
    2026-09-15: enviarla ya no basta) y ninguna cita.
    """
    make_survey_review(agenda_slots["p1"], status="approved")
    return agenda_slots


def _tope() -> int:
    from itcj2.config import get_settings
    return get_settings().TITULATEC_SELF_CANCEL_MAX


def _cancelacion(db, make_appointment, proc, *, intento, por=None):
    """Una cita YA cancelada en el historial (no vigente).

    `make_appointment` no expone `cancelled_by_id`, y es la única columna que
    mira el contador de D9: se sella aquí en vez de duplicar el constructor de
    `ReviewAppointment` (Ruling 3).
    """
    ap = make_appointment(proc, status="cancelled", is_current=False,
                          attempt_no=intento)
    ap.cancelled_by_id = por if por is not None else proc.student_id
    ap.cancelled_at = db_now()
    db.flush()
    return ap


def _bloquea_por_cancelaciones(db, make_appointment, proc, *, por=None):
    """Deja al proceso justo en el tope de D9."""
    for i in range(_tope()):
        _cancelacion(db, make_appointment, proc, intento=i + 1, por=por)


def _aprueba_la_fase_de_cotejo(db, proc):
    """Regla 2: se escribe en `ProcessPhase`, no en la cita.

    Usa `PhaseService.PHASE_COTEJO` y no un `2` literal, igual que la regla.
    """
    from itcj2.apps.titulatec.models import ProcessPhase
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    fila = (db.query(ProcessPhase)
            .filter_by(process_id=proc.id,
                       phase_number=PhaseService.PHASE_COTEJO).first())
    fila.status = "approved"
    db.flush()
    return fila


def _fase2_en(db, proc, estado):
    """Deja la fase 2 del proceso en `estado`, a mano.

    Generaliza a `_aprueba_la_fase_de_cotejo` (que sigue viva sin tocar: ya
    la usan otros tests) para la regla 5 (D13, 2026-09-30), que necesita más
    estados que solo `approved` -`pending`/`in_progress`/`in_review` bloquean
    con `cotejo_en_dictamen`, y `rejected` es la única puerta de salida-.
    """
    from itcj2.apps.titulatec.models import ProcessPhase
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    fila = (db.query(ProcessPhase)
            .filter_by(process_id=proc.id,
                       phase_number=PhaseService.PHASE_COTEJO).first())
    fila.status = estado
    db.flush()
    return fila


def _asiste(db, esc):
    """Cita agendada, iniciada y marcada `attended`, de punta a punta.

    No a mano (`make_appointment(status="attended")`): así se prueba el
    camino real, y `is_current` queda en `True` como lo deja
    `AppointmentService.mark_attended` de verdad (no toca la vigencia).
    """
    ap = AppointmentService.create(db, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.start(db, ap, esc["off"].id)
    AppointmentService.mark_attended(db, ap, esc["off"].id)
    return ap


# =========================================================================
# Las 7 reglas de §3, EN ORDEN
# =========================================================================
def test_regla_1_un_proceso_inactivo_no_puede_agendar(db_session, alumno):
    esc = alumno
    esc["p1"].status = "completed"
    db_session.flush()

    e = SelfBookingService.eligibility(db_session, esc["p1"].id)

    assert e["can_book"] is False
    assert e["reason"] == "proceso_inactivo"
    assert e["can_walkin"] is False


def test_regla_2_con_la_fase_de_cotejo_aprobada_ya_no_necesita_cita(db_session, alumno):
    esc = alumno
    _aprueba_la_fase_de_cotejo(db_session, esc["p1"])

    e = SelfBookingService.eligibility(db_session, esc["p1"].id)

    assert e["can_book"] is False
    assert e["reason"] == "fase_aprobada"
    assert e["can_walkin"] is False


def test_regla_3_sin_la_encuesta_enviada_no_puede_agendar(db_session, agenda_slots):
    """`agenda_slots` pelado: a `p1` nadie le sembró la solicitud."""
    e = SelfBookingService.eligibility(db_session, agenda_slots["p1"].id)

    assert e["can_book"] is False
    assert e["reason"] == "sin_encuesta"
    assert e["can_walkin"] is False
    assert SelfBookingService.message_for(e["reason"]) == (
        "Primero envía la encuesta de egresados.")


def test_regla_3_con_la_encuesta_en_revision_no_puede_agendar(
        db_session, agenda_slots, make_survey_review):
    """D1 (revierte D2 del 2026-09-15): la envió, pero GTV todavía no la
    libera. Motivo DISTINTO de "sin_encuesta" -el alumno ya hizo su parte-."""
    make_survey_review(agenda_slots["p1"], status="in_review")

    e = SelfBookingService.eligibility(db_session, agenda_slots["p1"].id)

    assert e["can_book"] is False
    assert e["reason"] == "encuesta_en_revision"
    assert e["can_walkin"] is False
    assert SelfBookingService.message_for(e["reason"]) == (
        "Tu encuesta de egresados está en revisión con Gestión Tecnológica y "
        "Vinculación. Podrás agendar en cuanto la liberen.")


def test_regla_3_con_la_encuesta_con_observaciones_no_puede_agendar(
        db_session, agenda_slots, make_survey_review):
    """D1: GTV la revisó y dejó observaciones; sigue sin poder agendar solo
    hasta que la libere (aprobar desde `rejected` también cuenta, §2)."""
    make_survey_review(agenda_slots["p1"], status="rejected", reason="Falta un sello")

    e = SelfBookingService.eligibility(db_session, agenda_slots["p1"].id)

    assert e["can_book"] is False
    assert e["reason"] == "encuesta_con_observaciones"
    assert e["can_walkin"] is False
    assert SelfBookingService.message_for(e["reason"]) == (
        "Gestión Tecnológica y Vinculación dejó observaciones en tu encuesta "
        "de egresados. Podrás agendar en cuanto la liberen.")


def test_regla_4_con_una_cita_viva_no_puede_abrir_otra(db_session, alumno):
    esc = alumno
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)

    e = SelfBookingService.eligibility(db_session, esc["p1"].id)

    assert e["can_book"] is False
    assert e["reason"] == "tiene_cita"
    assert e["current"] is not None and e["current"].id == ap.id
    assert e["can_walkin"] is False, "con lugar reservado no hay nada que anunciarle"


def test_regla_5_attended_con_la_fase_in_progress_no_puede_agendar_otra(db_session, alumno):
    """`agenda_slots` nace con la fase 2 en `in_progress` (`current_phase=2`
    la deja así): es el estado real de un alumno a mitad de su primer
    cotejo, sin tocar nada a mano."""
    esc = alumno
    ap = _asiste(db_session, esc)

    e = SelfBookingService.eligibility(db_session, esc["p1"].id)

    assert e["can_book"] is False
    assert e["reason"] == "cotejo_en_dictamen"
    assert e["can_walkin"] is False, "D13: tampoco se presenta mientras no haya dictamen"
    assert e["current"] is not None and e["current"].id == ap.id
    assert SelfBookingService.message_for(e["reason"]) == (
        "Tu cotejo ya se realizó. Servicios Escolares está por dictaminarlo; "
        "si queda con observaciones podrás agendar otra cita.")


def test_regla_5_attended_con_la_fase_pending_no_puede_agendar_otra(db_session, alumno):
    esc = alumno
    _asiste(db_session, esc)
    _fase2_en(db_session, esc["p1"], "pending")

    e = SelfBookingService.eligibility(db_session, esc["p1"].id)

    assert e["can_book"] is False
    assert e["reason"] == "cotejo_en_dictamen"


def test_regla_5_attended_con_la_fase_in_review_no_puede_agendar_otra(db_session, alumno):
    esc = alumno
    _asiste(db_session, esc)
    _fase2_en(db_session, esc["p1"], "in_review")

    e = SelfBookingService.eligibility(db_session, esc["p1"].id)

    assert e["can_book"] is False
    assert e["reason"] == "cotejo_en_dictamen"


def test_regla_5_attended_con_la_fase_aprobada_reporta_fase_aprobada_no_dictamen(
        db_session, alumno):
    """La regla 2 corta ANTES: una `attended` con la fase ya `approved` nunca
    llega a la regla 5 -el orden es el contrato, y una segunda implementación
    de la lectura de `ProcessPhase` (`_fase_cotejo_status`) no puede
    discreparle a la primera-."""
    esc = alumno
    _asiste(db_session, esc)
    _aprueba_la_fase_de_cotejo(db_session, esc["p1"])

    e = SelfBookingService.eligibility(db_session, esc["p1"].id)

    assert e["can_book"] is False
    assert e["reason"] == "fase_aprobada"


def test_regla_6_al_llegar_al_tope_de_cancelaciones_pierde_el_auto_agendado(
        db_session, alumno, make_appointment):
    esc = alumno
    _bloquea_por_cancelaciones(db_session, make_appointment, esc["p1"])

    e = SelfBookingService.eligibility(db_session, esc["p1"].id)

    assert e["can_book"] is False
    assert e["reason"] == "bloqueado_por_cancelaciones"
    assert e["cancellations"] == _tope()
    assert e["blocked_by_cancellations"] is True


def test_regla_7_sin_nada_que_lo_impida_puede_agendar(db_session, alumno):
    e = SelfBookingService.eligibility(db_session, alumno["p1"].id)

    assert e["can_book"] is True
    assert e["reason"] is None
    assert e["can_walkin"] is True
    assert e["cancellations"] == 0
    assert e["blocked_by_cancellations"] is False
    assert e["current"] is None


def test_el_orden_manda_inactivo_y_sin_encuesta_reporta_proceso_inactivo(
        db_session, agenda_slots):
    """Las dos reglas fallan a la vez; la que se reporta es la PRIMERA.

    Si alguien reordena la cadena, este test es el que lo caza: el alumno
    vería «Primero envía la encuesta» cuando su problema real es que su
    proceso ya no está activo.
    """
    agenda_slots["p1"].status = "cancelled"
    db_session.flush()

    e = SelfBookingService.eligibility(db_session, agenda_slots["p1"].id)

    assert e["reason"] == "proceso_inactivo"


# =========================================================================
# Los tres que SÍ dejan agendar (D5, D7, D6; D5 endurecido por D13 2026-09-30)
# =========================================================================
def test_atendido_con_la_fase_2_rechazada_puede_agendar_otra(db_session, alumno):
    """D5 (2026-09-15) + D13 (2026-09-30): el corte real es la FASE con
    VEREDICTO, no el estado `attended` a secas.

    Es el caso «vino, cotejamos y le faltaron papeles»: la cita se usó,
    Servicios Escolares dictaminó que faltó algo y tiene que poder volver.
    Hasta el 2026-09-29 bastaba con que la fase NO estuviera `approved` -este
    test agendaba, iniciaba y marcaba `attended` sin tocar la fase, y ya
    podía agendar otra-; desde D13 hace falta ADEMÁS el rechazo explícito, o
    cae en la regla 5 nueva (`cotejo_en_dictamen`, ver
    `test_regla_5_attended_con_la_fase_in_progress_no_puede_agendar_otra` y
    hermanos, más arriba).
    """
    esc = alumno
    ap = _asiste(db_session, esc)
    _fase2_en(db_session, esc["p1"], "rejected")

    e = SelfBookingService.eligibility(db_session, esc["p1"].id)

    assert e["can_book"] is True, "la fase 2 quedó rechazada (D13)"
    assert e["reason"] is None
    assert e["current"] is not None and e["current"].id == ap.id
    assert e["current"].status == "attended"


def test_tras_un_no_show_puede_agendar_otra_el_solo(db_session, alumno):
    """D7. Que su franja perdida NO se libere (D10) es otra cosa, y vive en
    `test_self_booking_cancel_frees_slot.py`."""
    esc = alumno
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.mark_no_show(db_session, ap, esc["off"].id)

    e = SelfBookingService.eligibility(db_session, esc["p1"].id)

    assert e["can_book"] is True
    assert e["reason"] is None


def test_tras_cancelar_puede_agendar_otra(db_session, alumno):
    """D6. Una sola cancelación no lo bloquea: el tope es D9."""
    esc = alumno
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.cancel(db_session, ap, esc["p1"].student_id)

    e = SelfBookingService.eligibility(db_session, esc["p1"].id)

    assert e["can_book"] is True
    assert e["reason"] is None
    assert e["cancellations"] == 1
    assert e["current"] is None, "la cancelada dejó de ser la vigente"


# =========================================================================
# `can_walkin` NO es `can_book`
# =========================================================================
def test_el_bloqueado_por_cancelaciones_sigue_pudiendo_llegar_sin_cita(
        db_session, alumno, make_appointment):
    """La regla 6 apaga `can_book` y **no** apaga `can_walkin` (§3).

    Perdió el derecho a RESERVAR un lugar, no el de PRESENTARSE a una
    atención que el encargado anunció abierta a todos. Colgar `can_walkin` de
    `can_book` le fabricaría un callejón sin salida: una pantalla que solo
    dice «pídele la cita a tu encargado» el mismo día en que su encargado
    atiende sin cita.
    """
    esc = alumno
    _bloquea_por_cancelaciones(db_session, make_appointment, esc["p1"])

    e = SelfBookingService.eligibility(db_session, esc["p1"].id)

    assert e["can_book"] is False
    assert e["can_walkin"] is True


def test_solo_cuentan_las_cancelaciones_del_alumno(db_session, alumno, make_appointment):
    """Si cancela el ENCARGADO no le consume cupo: si no, podría dejarlo
    bloqueado sin querer. El contador compara `cancelled_by_id` con
    `process.student_id`, las dos `BigInteger` a `core_users.id`."""
    esc = alumno
    _bloquea_por_cancelaciones(db_session, make_appointment, esc["p1"],
                               por=esc["off"].id)

    e = SelfBookingService.eligibility(db_session, esc["p1"].id)

    assert e["cancellations"] == 0
    assert e["blocked_by_cancellations"] is False
    assert e["can_book"] is True


def test_los_valores_de_config_son_los_de_la_spec():
    """D8 y D9 son configurables, pero sus defaults son contrato."""
    from itcj2.config import get_settings

    s = get_settings()
    assert s.TITULATEC_SELF_BOOK_MIN_LEAD_MINUTES == 60
    assert s.TITULATEC_SELF_CANCEL_MIN_LEAD_MINUTES == 120
    assert s.TITULATEC_SELF_CANCEL_MAX == 3


# =========================================================================
# El cubo del encargado (D10) — la MISMA regla vista desde el otro lado
# =========================================================================
@pytest.fixture()
def cola(alumno, make_document):
    """`p1` listo para «Por agendar»: encuesta enviada y los 3 documentos
    iniciales aprobados, que es lo que ese cubo exige."""
    for code in DOCS_INICIALES:
        make_document(alumno["p1"], type_code=code, review_status="approved")
    return alumno


class TestElCuboDeLosBloqueados:
    """§6: los cubos son **mutuamente excluyentes**. Si el bloqueado no sale
    de «Por agendar», aparece en dos sitios y el encargado no sabe cuál mirar.
    """

    @staticmethod
    def _ids(filas):
        return [p.id for p in filas]

    def test_el_que_puede_agendar_solo_sigue_en_por_agendar(self, db_session, cola):
        esc = cola
        pendientes = self._ids(AppointmentService.list_pending_processes(
            db_session, allowed_program_ids={esc["prog"].id}))
        bloqueados = self._ids(AppointmentService.list_self_blocked_processes(
            db_session, allowed_program_ids={esc["prog"].id}))

        assert esc["p1"].id in pendientes
        assert esc["p1"].id not in bloqueados

    def test_el_bloqueado_se_muda_de_cubo(self, db_session, cola, make_appointment):
        esc = cola
        _bloquea_por_cancelaciones(db_session, make_appointment, esc["p1"])

        pendientes = self._ids(AppointmentService.list_pending_processes(
            db_session, allowed_program_ids={esc["prog"].id}))
        bloqueados = self._ids(AppointmentService.list_self_blocked_processes(
            db_session, allowed_program_ids={esc["prog"].id}))

        assert esc["p1"].id in bloqueados
        assert esc["p1"].id not in pendientes, "saldría en dos cubos a la vez"

    def test_el_cubo_respeta_el_alcance_por_carrera(self, db_session, cola,
                                                    make_appointment, make_program):
        esc = cola
        _bloquea_por_cancelaciones(db_session, make_appointment, esc["p1"])
        ajena = make_program("Ingenieria Ajena al Cubo")

        assert esc["p1"].id not in self._ids(
            AppointmentService.list_self_blocked_processes(
                db_session, allowed_program_ids={ajena.id}))
        # Fail-closed: sin carreras asignadas no se ve nada.
        assert AppointmentService.list_self_blocked_processes(
            db_session, allowed_program_ids=set()) == []

    def test_el_cancelado_que_no_llego_al_tope_no_cae_en_el_cubo(
            self, db_session, cola, make_appointment):
        """Una cancelación legítima no es un bloqueo: sigue en «Por agendar»."""
        esc = cola
        _cancelacion(db_session, make_appointment, esc["p1"], intento=1)

        assert esc["p1"].id in self._ids(AppointmentService.list_pending_processes(
            db_session, allowed_program_ids={esc["prog"].id}))
        assert esc["p1"].id not in self._ids(
            AppointmentService.list_self_blocked_processes(
                db_session, allowed_program_ids={esc["prog"].id}))
