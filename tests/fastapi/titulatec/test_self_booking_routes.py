"""Las dos rutas del auto-agendado del egresado, de punta a punta (spec §5).

El test que manda aquí es **`test_no_agenda_en_la_ventana_de_otra_carrera`**:
`window_id` llega en el CUERPO del formulario, no en la ruta, así que el
regresor estructural `test_scope_guard.py` —que barre las rutas con
`{process_id}`— no lo ve. `test_self_booking_offer.py` ya fija la revalidación
en el service; esto la fija **por HTTP**, que es por donde entra el atacante.

Contrato de errores (T4):

* `NotYours`  -> **404 limpio, sin `X-Tt-Error`**. Mismo criterio que
  `assert_process_in_scope`: los ids son enteros secuenciales y un mensaje
  distintivo confirmaría cuáles existen.
* `SlotTooSoon` / `CancelTooLate` / `SelfBookingNotAllowed` -> 400 +
  `X-Tt-Error`, **salvo** `reason == "tiene_cita"`, que trae
  `refresca_la_vista` y responde 200 con el panel fresco + `X-Tt-Notice`.

Harness: `dependency_overrides[get_db]` NO alcanza al cuerpo de la ruta en esta
app. Se usa `client_as`, que arrastra `client` -> `patched_session_local`.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from urllib.parse import unquote

import pytest

import itcj2.models  # noqa: F401
import itcj2.apps.titulatec.services.self_booking_service as sb_mod
from itcj2.core.utils.timezone import db_now
from tests.fastapi.titulatec.conftest import ROLE_STUDENT, STUDENT_PERMS

CITA = "/titulatec/student/cita"
AGENDAR = "/titulatec/student/cita/agendar"
CANCELAR = "/titulatec/student/cita/cancelar"

# El mismo día que arma `agenda_slots` (2029: lejos, así que la anticipación
# mínima de D8 se cumple sola salvo donde el test fija el reloj a propósito).
_DIA = date(2029, 5, 7)

# Los dos permisos que nacen con esta feature (T5), sobre los del alumno.
SELF_PERMS = STUDENT_PERMS + (
    "titulatec.appointment.api.book.own",
    "titulatec.appointment.api.cancel.own",
)


def _msg(resp) -> str:
    """El `X-Tt-Error` ya decodificado (el servidor lo percent-codifica)."""
    return unquote(resp.headers.get("X-Tt-Error", ""))


def _citas(db, proc):
    from itcj2.apps.titulatec.models import ReviewAppointment
    return (db.query(ReviewAppointment)
            .filter_by(process_id=proc.id)
            .order_by(ReviewAppointment.id).all())


@pytest.fixture()
def escena(db_session, agenda_slots, make_survey_review, make_role, grant_user_role):
    """`agenda_slots` con la ventana PUBLICADA, la encuesta enviada y los permisos.

    `make_role` es aditivo e idempotente por nombre: añade los dos códigos
    nuevos al rol que `make_student` ya creó. `grant_user_role` invalida el
    cache de authz, que es lo que hace que la concesión se vea en el mismo test.
    """
    from itcj2.core.models.user import User

    esc = dict(agenda_slots)
    make_survey_review(esc["p1"])            # D2: sin encuesta no se agenda
    esc["w"].visibility = "bookable"         # D1: publicar es deliberado
    db_session.flush()

    alumno = db_session.get(User, esc["p1"].student_id)
    grant_user_role(alumno, make_role(ROLE_STUDENT, SELF_PERMS))
    esc["alumno"] = alumno
    return esc


# =========================================================================
# El control crítico: el IDOR que el regresor estructural no ve
# =========================================================================
def test_no_agenda_en_la_ventana_de_otra_carrera(
        db_session, escena, client_as, make_program, make_officer, make_review_window):
    """**404 limpio.** Cambiar un número en el formulario no sienta al egresado
    con el encargado de otra carrera.

    El 404 va SIN `X-Tt-Error` a propósito: un mensaje distintivo convertiría
    la ruta en un detector de ventanas existentes.
    """
    otra = make_program("Ingenieria Ajena a la Ruta")
    ajeno, pos_ajeno = make_officer([otra])
    w_ajena = make_review_window(escena["dia"], ajeno, start="12:00", end="13:00",
                                 slot=30, cap=1, position=pos_ajeno)
    w_ajena.visibility = "bookable"
    db_session.flush()

    cli = client_as(escena["alumno"])

    # 1) La ventana AJENA -mismo día, misma convocatoria, misma hora de
    #    rejilla: lo ÚNICO que cambia es de quién es- da 404 limpio.
    resp = cli.post(AGENDAR, data={"window_id": str(w_ajena.id), "slot": "12:00"})

    assert resp.status_code == 404, resp.text[:300]
    assert "X-Tt-Error" not in resp.headers, "el 404 no debe llevar oraculo"
    assert _citas(db_session, escena["p1"]) == [], "no debio crearse ninguna cita"

    # 2) Y la PROPIA, por la misma ruta, sí agenda.
    #
    #    Esta mitad no es decorativa: sin ella el test pasa en verde aunque la
    #    ruta NO EXISTA -un POST a una URL inexistente ya es 404 y la tabla ya
    #    está vacía-, que es exactamente como salió en la corrida en rojo de
    #    esta tarea. El discriminador tiene que vivir DENTRO del test y no en
    #    un hermano que alguien pueda borrar o saltarse.
    #
    #    Va DESPUÉS a propósito: agendar primero dejaría una cita viva y el 404
    #    de arriba se convertiría en el 200 de `tiene_cita`.
    ok = cli.post(AGENDAR, data={"window_id": str(escena["w"].id), "slot": "09:30"})

    assert ok.status_code == 200, _msg(ok) or ok.text[:300]
    assert len(_citas(db_session, escena["p1"])) == 1, (
        "la ruta tiene que existir y agendar de verdad; si esto falla, el 404 "
        "de arriba no prueba nada")


def test_no_agenda_en_un_espacio_privado(db_session, escena, client_as):
    """`private` es el default: no está publicado, así que tampoco por HTTP."""
    escena["w"].visibility = "private"
    db_session.flush()

    resp = client_as(escena["alumno"]).post(
        AGENDAR, data={"window_id": str(escena["w"].id), "slot": "09:30"})

    assert resp.status_code == 404
    assert _citas(db_session, escena["p1"]) == []


def test_no_agenda_en_un_espacio_walkin(db_session, escena, client_as):
    """D2: el walk-in es un anuncio, no una agenda. Y lo decide el SERVIDOR,
    no el hecho de no pintar el botón."""
    escena["w"].visibility = "walkin"
    db_session.flush()

    resp = client_as(escena["alumno"]).post(
        AGENDAR, data={"window_id": str(escena["w"].id), "slot": "09:30"})

    assert resp.status_code == 404
    assert _citas(db_session, escena["p1"]) == []


# =========================================================================
# Agendar
# =========================================================================
def test_agendar_deja_la_cita_marcada_como_agendada_por_el_alumno(
        db_session, escena, client_as):
    """El caso feliz: 200 con el panel re-renderizado y la fila en BD (D11)."""
    resp = client_as(escena["alumno"]).post(
        AGENDAR, data={"window_id": str(escena["w"].id), "slot": "09:30"})

    assert resp.status_code == 200, _msg(resp) or resp.text[:300]
    citas = _citas(db_session, escena["p1"])
    assert len(citas) == 1
    assert citas[0].booked_by == "student"
    assert citas[0].status == "scheduled" and citas[0].is_current is True
    assert citas[0].scheduled_at == datetime.combine(_DIA, time(9, 30))
    assert citas[0].created_by_id == escena["alumno"].id
    # Es un PARCIAL, no la pagina entera: el POST responde lo que se re-pinta.
    assert "<html" not in resp.text.lower()


def test_agendar_una_franja_que_arranca_en_menos_de_una_hora(
        db_session, escena, client_as, monkeypatch):
    """D8, por HTTP: 400 + `X-Tt-Error`. htmx no swappea en 4xx y está bien —
    lo que hay en pantalla sigue siendo verdad."""
    monkeypatch.setattr(sb_mod, "db_now",
                        lambda: datetime.combine(_DIA, time(9, 30)))

    resp = client_as(escena["alumno"]).post(
        AGENDAR, data={"window_id": str(escena["w"].id), "slot": "10:00"})

    assert resp.status_code == 400
    assert "menos de 1 hora" in _msg(resp), _msg(resp)
    # El header viaja latin-1 y el cliente lo lee UTF-8, así que el servidor lo
    # percent-codifica. Esta línea es la ÚNICA que lo fija: las subcadenas de
    # arriba están escritas sin acentos y sobreviven intactas al mojibake, así
    # que si alguien quita `_hdr` seguirían en verde mientras el alumno ve
    # basura en el toast.
    assert resp.headers["X-Tt-Error"].isascii(), resp.headers["X-Tt-Error"]
    assert _citas(db_session, escena["p1"]) == []


def test_con_una_cita_viva_el_segundo_clic_responde_con_el_panel_fresco(
        db_session, escena, client_as):
    """`tiene_cita` es la única que refresca la vista: es lo que produce un
    doble clic, y ahí la pantalla SÍ está rancia (ya existe una cita que el
    alumno no está viendo). Por eso 200 + `X-Tt-Notice`, no 400."""
    cli = client_as(escena["alumno"])
    cli.post(AGENDAR, data={"window_id": str(escena["w"].id), "slot": "09:30"})

    resp = cli.post(AGENDAR, data={"window_id": str(escena["w"].id), "slot": "10:00"})

    assert resp.status_code == 200
    assert "Ya tienes una cita" in unquote(resp.headers.get("X-Tt-Notice", ""))
    assert len(_citas(db_session, escena["p1"])) == 1, "no debio abrirse un segundo intento"


def test_el_choque_de_cita_activa_le_habla_al_ALUMNO_no_al_encargado(
        db_session, escena, client_as, make_appointment, monkeypatch):
    """El copy del camino de CARRERA, que es el que ningun test miraba.

    `eligibility` corre FUERA de los locks, asi que dos clics concurrentes en
    «Agendar» la pasan los dos y el segundo choca contra la guarda de D4 —la de
    `create`, o la de `_open_new_attempt` ya dentro del advisory lock, segun los
    tiempos—. Las dos levantan `AppointmentConflict`, cuyo texto esta escrito
    para el ENCARGADO: «Ese alumno ya tiene una cita activa». Como
    `refresca_la_vista` es True, eso sale 200 + `X-Tt-Notice` y se le pinta al
    propio egresado, que se lee a si mismo en tercera persona.

    Se reproduce la lectura RANCIA que hace posible el choque: `eligibility`
    dice que si puede (respondio antes de que existiera la cita) mientras la
    cita viva ya esta en la base. El camino secuencial de la misma pantalla ya
    daba el copy correcto —por eso el otro paso desapercibido—, asi que la
    asercion que manda es la NEGATIVA.
    """
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    make_appointment(escena["p1"])            # la cita viva que dejo el otro clic

    monkeypatch.setattr(
        sb_mod.SelfBookingService, "eligibility",
        staticmethod(lambda db, process_id: {
            "can_book": True, "can_walkin": True, "reason": None,
            "cancellations": 0, "blocked_by_cancellations": False, "current": None}))

    # ESPIA OBLIGATORIO, y no es adorno: sin el, este test seria VERDE CON Y SIN
    # EL ARREGLO. Si el parche de `eligibility` no tomara efecto, la regla 4 de
    # §3 levantaria `SelfBookingNotAllowed("tiene_cita")` con EXACTAMENTE el
    # mismo texto que se afirma abajo, sin haber llegado nunca a `create` ni,
    # por tanto, al `AppointmentConflict` que este test existe para medir. El
    # unico modo de distinguir los dos caminos es comprobar que se entro al
    # segundo.
    llamadas = []
    original_create = AppointmentService.create

    def _spy(*a, **kw):
        llamadas.append(1)
        return original_create(*a, **kw)

    monkeypatch.setattr(AppointmentService, "create", staticmethod(_spy))

    resp = client_as(escena["alumno"]).post(
        AGENDAR, data={"window_id": str(escena["w"].id), "slot": "09:30"})

    assert llamadas, (
        "no se llego a `AppointmentService.create`, asi que el mensaje medido "
        "sale de la regla 4 y no del choque: este test pasaria igual sin el "
        "arreglo. Revisa que el parche de `eligibility` siga aplicandose")
    aviso = unquote(resp.headers.get("X-Tt-Notice", ""))
    assert resp.status_code == 200, _msg(resp) or resp.text[:300]
    assert "Ese alumno" not in aviso, (
        "el copy del ENCARGADO llego al egresado: le habla de si mismo en "
        "tercera persona. Mensaje recibido: %r" % aviso)
    assert "Ya tienes una cita" in aviso, aviso
    assert len(_citas(db_session, escena["p1"])) == 1, "no debio abrirse un segundo intento"


def test_sin_el_permiso_de_agendar_no_pasa_el_gate(db_session, agenda_slots,
                                                    make_survey_review, client_as):
    """Sin `appointment.api.book.own` -> `PageForbidden`.

    Este test NO usa `escena` a propósito: esa fixture añade los dos códigos al
    rol COMPARTIDO de los alumnos, así que aquí el egresado se queda con los
    permisos de siempre, que es justo lo que se quiere medir.
    """
    from itcj2.core.models.user import User

    make_survey_review(agenda_slots["p1"])
    agenda_slots["w"].visibility = "bookable"
    db_session.flush()
    alumno = db_session.get(User, agenda_slots["p1"].student_id)

    resp = client_as(alumno).post(
        AGENDAR, data={"window_id": str(agenda_slots["w"].id), "slot": "09:30"})

    assert resp.status_code == 403, resp.text[:300]
    assert _citas(db_session, agenda_slots["p1"]) == []


def test_fuera_de_la_fase_dos_no_agenda(db_session, escena, client_as):
    """La guarda de fase del alumno, por la ruta: 400 + `X-Tt-Error`."""
    escena["p1"].current_phase = 3
    db_session.flush()

    resp = client_as(escena["alumno"]).post(
        AGENDAR, data={"window_id": str(escena["w"].id), "slot": "09:30"})

    assert resp.status_code == 400
    assert _citas(db_session, escena["p1"]) == []


# =========================================================================
# Cancelar
# =========================================================================
def test_cancelar_a_tiempo_libera_la_franja(db_session, escena, client_as):
    """D12: cancelar devuelve el lugar al pozo en el acto.

    Se agenda y se cancela POR LA RUTA, no a mano: es el único modo de que el
    `window_id` quede puesto y la franja pueda volver de verdad.
    """
    from itcj2.apps.titulatec.services.slot_service import SlotService

    cli = client_as(escena["alumno"])
    cli.post(AGENDAR, data={"window_id": str(escena["w"].id), "slot": "09:30"})
    assert time(9, 30) not in SlotService.free_slots(db_session, escena["w"])

    resp = cli.post(CANCELAR, data={"motivo": "Me empalma con un examen"})

    assert resp.status_code == 200, _msg(resp) or resp.text[:300]
    cita = _citas(db_session, escena["p1"])[0]
    assert cita.status == "cancelled" and cita.is_current is False
    assert cita.cancelled_by_id == escena["alumno"].id
    assert cita.cancel_reason == "Me empalma con un examen"
    assert time(9, 30) in SlotService.free_slots(db_session, escena["w"]), (
        "la franja tenia que volver al pozo (D12)")


def test_cancelar_faltando_menos_de_dos_horas(db_session, escena, client_as,
                                               make_appointment):
    """D8: dentro de la ventana de 2 h ya no puede cancelar solo."""
    make_appointment(escena["p1"], when=db_now() + timedelta(hours=1))

    resp = client_as(escena["alumno"]).post(CANCELAR, data={"motivo": "Ya no puedo"})

    assert resp.status_code == 400
    assert "2 horas" in _msg(resp), _msg(resp)
    cita = _citas(db_session, escena["p1"])[0]
    assert cita.status == "scheduled", "la cita no debio tocarse"


def test_cancelar_sin_cita_no_revienta(db_session, escena, client_as):
    """Un doble clic en «Cancelar» no puede dar un 500: la segunda vez ya no
    hay cita vigente y lo correcto es devolver el panel tal como quedó."""
    resp = client_as(escena["alumno"]).post(CANCELAR, data={"motivo": ""})

    assert resp.status_code == 200, _msg(resp) or resp.text[:300]


def test_sin_el_permiso_de_cancelar_no_pasa_el_gate(db_session, agenda_slots,
                                                     make_appointment, client_as):
    from itcj2.core.models.user import User

    make_appointment(agenda_slots["p1"])
    alumno = db_session.get(User, agenda_slots["p1"].student_id)

    resp = client_as(alumno).post(CANCELAR, data={"motivo": "x"})

    assert resp.status_code == 403, resp.text[:300]


# =========================================================================
# Las cuatro caras de la pantalla (§7)
# =========================================================================
def test_la_pagina_ofrece_las_franjas_como_botones(db_session, escena, client_as):
    """Cara 2: día -> encargado -> franjas. Una franja es un `<button>` dentro
    de un `<form method="post">`; no se teclea una hora."""
    resp = client_as(escena["alumno"]).get(CITA, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert 'name="slot"' in resp.text and 'value="09:30"' in resp.text
    assert 'name="window_id"' in resp.text
    assert "09:30" in resp.text


def test_el_dia_elegido_devuelve_el_parcial_no_la_pagina(db_session, escena, client_as):
    """`GET /student/cita?dia=` es la MISMA ruta con querystring: devuelve el
    parcial del día, no el documento entero."""
    resp = client_as(escena["alumno"]).get(
        CITA + "?dia=" + _DIA.isoformat(), follow_redirects=False,
        headers={"HX-Request": "true"})

    assert resp.status_code == 200
    assert "<html" not in resp.text.lower()
    assert 'value="09:30"' in resp.text


def test_el_mismo_dia_sin_htmx_devuelve_la_pagina_entera(db_session, escena, client_as):
    """El enlace del día abierto SIN htmx es una navegación de página.

    Devolverle el fragmento pelado —sin shell, sin estilos, sin navegación— es
    peor que no contestar, y además convertía en mentira el comentario que
    llama a `href`/`method` «el camino sin JS».
    """
    resp = client_as(escena["alumno"]).get(
        CITA + "?dia=" + _DIA.isoformat(), follow_redirects=False)

    assert resp.status_code == 200
    assert "<html" in resp.text.lower(), "sin htmx toca la pagina completa"
    assert 'value="09:30"' in resp.text, "y con el dia elegido ya pintado"


def test_el_dia_no_ofrece_franjas_a_quien_ya_no_puede_agendar(
        db_session, escena, client_as, make_appointment):
    """El parcial del día respeta la elegibilidad, igual que el panel.

    Sin esto, quien dejó la pestaña abierta y ya agendó (o perdió el derecho)
    recibía una rejilla de franjas VIVAS y ninguna explicación: el «botón mudo»
    que §7 existe para prohibir. El POST lo revalida, así que no era un
    agujero de seguridad — era una mentira en pantalla.
    """
    make_appointment(escena["p1"])            # -> reason `tiene_cita`

    resp = client_as(escena["alumno"]).get(
        CITA + "?dia=" + _DIA.isoformat(), follow_redirects=False,
        headers={"HX-Request": "true"})

    assert resp.status_code == 200
    assert 'name="slot"' not in resp.text, "no puede agendar: no hay franjas que pulsar"
    # El destino original era solo el selector, así que el panel entero tiene
    # que redirigir el swap; si no, entraría DENTRO del selector y el documento
    # acabaría con dos `#tt-cita-card`.
    assert resp.headers.get("HX-Retarget") == "#tt-cita-panel"
    assert resp.headers.get("HX-Reswap") == "innerHTML"


def test_el_walkin_se_anuncia_con_su_horario_y_su_encargado(db_session, escena,
                                                             client_as):
    """Cara 3: «Atención sin cita», con horario completo, lugar y nombre."""
    escena["w"].visibility = "walkin"
    escena["w"].location = "Edificio A"
    db_session.flush()

    resp = client_as(escena["alumno"]).get(CITA, follow_redirects=False)

    assert resp.status_code == 200
    assert "sin cita" in resp.text.lower()
    assert "Edificio A" in resp.text
    assert "09:00" in resp.text and "11:00" in resp.text
    assert 'name="slot"' not in resp.text, "un walk-in no ofrece franjas (D2)"


def test_el_bloqueado_por_cancelaciones_ve_la_frase_y_sigue_viendo_el_walkin(
        db_session, escena, client_as, make_appointment, make_review_window):
    """Caras 3 y 4 conviviendo, que es el único caso donde eso importa.

    El bloqueado por D9 perdió el derecho a RESERVAR, no el de PRESENTARSE:
    una pantalla que solo dijera «pídele la cita a tu encargado» el mismo día
    en que su encargado atiende sin cita sería un callejón sin salida.
    """
    for _ in range(3):                       # el tope de D9
        make_appointment(escena["p1"], status="cancelled", is_current=False)
    for cita in _citas(db_session, escena["p1"]):
        cita.cancelled_by_id = escena["alumno"].id
    walkin = make_review_window(escena["dia"], escena["off"], start="12:00",
                                end="14:00", slot=30, cap=1, position=escena["pos"])
    walkin.visibility = "walkin"
    db_session.flush()

    resp = client_as(escena["alumno"]).get(CITA, follow_redirects=False)

    assert resp.status_code == 200
    assert "Cancelaste 3 veces" in resp.text, "falta la frase que dice POR QUE"
    assert "sin cita" in resp.text.lower(), "el bloqueado sigue pudiendo presentarse"
    assert 'name="slot"' not in resp.text, "pero ya no reserva"


def test_quien_no_puede_agendar_ve_la_frase_nunca_un_boton_mudo(
        db_session, escena, client_as, make_survey_review):
    """Cara 4: la columna «Mensaje al alumno» de §3, literal y desde el service."""
    from itcj2.apps.titulatec.models import SurveyReview

    db_session.query(SurveyReview).filter_by(process_id=escena["p1"].id).delete()
    db_session.flush()

    resp = client_as(escena["alumno"]).get(CITA, follow_redirects=False)

    assert resp.status_code == 200
    assert "Primero envía la encuesta de egresados." in resp.text
    assert 'name="slot"' not in resp.text
