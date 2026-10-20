"""«Atender ahora» y el orden por apartado (spec 2026-09-29-titulatec-cotejo-
espacios-design.md §4 · D7).

El egresado está enfrente y no tiene cita. El encargado lo sienta en SU espacio
sin horario de HOY y arranca el cotejo en una sola transacción: la cita nace
`in_progress`, con sus dos eventos (`appointment_scheduled` +
`appointment_in_progress`), y SIN aviso in-app ni correo de «agendada» — acaba
de llegar a la ventanilla.

`attend_now` solo valida lo propio de este camino (espacio sin horario, de hoy,
del propio encargado; si no, `NotWalkinToday`). Las guardas de `create`
(revocación, encuesta liberada, cita viva, día habilitado, cupo) NO se copian
(D13): se heredan, y aquí se prueba que llegan.

También vive aquí el arrastre de la revisión de la Tarea 2: `SlotService.
_lock_window` relee la ventana DESPUÉS del `FOR UPDATE`. Con una sola sesión no
hay dos transacciones, así que el «otro encargado» es un UPDATE crudo a la fila
(fuera del ORM): el objeto en memoria conserva el valor viejo y la fila ya dice
el nuevo, que es justo lo que ve quien consigue el lock después de esperarlo.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from urllib.parse import unquote

import lxml.html
import pytest
from sqlalchemy import event, text

from itcj2.apps.titulatec.services import appointment_errors as err
from itcj2.apps.titulatec.services.appointment_service import AppointmentService
from itcj2.apps.titulatec.services.review_window_service import ReviewWindowService
from itcj2.apps.titulatec.services.slot_service import SlotService
from itcj2.core.utils.timezone import db_now
from tests.fastapi.titulatec.conftest import OFFICER_PERMS

URL = "/titulatec/admin/appointments"
# «Atender ahora» pide el MISMO permiso que agendar (spec §7.4: sin permisos
# nuevos). `OFFICER_PERMS` es el set de bandeja, de solo lectura.
_PERMS = OFFICER_PERMS + ("titulatec.appointment.api.create",)
_DOCS = ("birth_certificate", "high_school_cert", "curp")
_MENSAJE = "“Atender ahora” solo funciona en tus espacios sin horario de hoy."


@pytest.fixture(autouse=True)
def _correo_encendido(monkeypatch):
    """Correo ENCENDIDO. Apagado, `StudentMail` devuelve `False` sin escribir
    nada y «cero filas en la bandeja» pasaría aunque la rama encolara."""
    from itcj2.config import get_settings

    monkeypatch.setattr(get_settings(), "TITULATEC_EMAIL_ENABLED", True)


@pytest.fixture()
def esc(seed_phase_defs, seed_document_types, make_program, make_cohort,
        make_review_day, make_officer, make_student, make_process, make_document,
        make_review_window, make_survey_review):
    """El sin horario de HOY del encargado —08:00-14:00, DOS lugares— y tres
    egresados listos para cotejo: documentos aprobados y encuesta LIBERADA (D1).
    Tres contra dos: el tercero es el que choca con el cupo.

    `nuevo()` fabrica otro egresado; `encuesta`, `program` y `status` arman los
    casos de las guardas heredadas y el de alcance.
    """
    seed_phase_defs()
    seed_document_types()
    prog = make_program("Ingenieria de Atender Ahora")
    cohort = make_cohort()
    dia = make_review_day(cohort, day=db_now().date())
    officer, pos = make_officer([prog], perm_codes=_PERMS)
    w = make_review_window(dia, officer, start="08:00", end="14:00", slot=30, cap=2,
                           location="Ventanilla 2", position=pos, visibility="walkin")

    def nuevo(*, encuesta="approved", program=prog, status="active"):
        proc = make_process(make_student(), cohort=cohort, program=program,
                            current_phase=2, status=status)
        for code in _DOCS:
            make_document(proc, type_code=code, review_status="approved")
        make_survey_review(proc, status=encuesta)
        return proc

    return {"prog": prog, "cohort": cohort, "dia": dia, "off": officer, "pos": pos,
            "w": w, "p": [nuevo() for _ in range(3)], "nuevo": nuevo}


# ---------------------------------------------------------------------------
# Ayudantes
# ---------------------------------------------------------------------------
def _atender(db, esc, proc, window=None):
    return AppointmentService.attend_now(db, proc.id, window_id=(window or esc["w"]).id,
                                         actor_id=esc["off"].id)


def _eventos(db, pid):
    from itcj2.apps.titulatec.models import ProcessEvent

    db.flush()
    return [(e.event_type, e.payload) for e in
            db.query(ProcessEvent).filter_by(process_id=pid).order_by(ProcessEvent.id)]


def _correos(db, pid):
    """Filas de la bandeja de correos del proceso. El flush es EXPLÍCITO: en
    producción `SessionLocal` es autoflush=False y el arnés no."""
    from itcj2.apps.titulatec.models import EmailOutbox

    db.flush()
    return db.query(EmailOutbox).filter_by(process_id=pid).count()


def _avisos(db, user_id):
    """Notificaciones in-app de titulatec del usuario, de CUALQUIER tipo."""
    from itcj2.core.models.notification import Notification

    db.flush()
    return db.query(Notification).filter_by(user_id=user_id, app_name="titulatec").count()


def _citas(db, pid):
    from itcj2.apps.titulatec.models import ReviewAppointment

    return (db.query(ReviewAppointment).filter_by(process_id=pid)
            .order_by(ReviewAppointment.id).all())


def _url(esc, proc):
    """La URL EXACTA del botón de la ficha: vuelve a Atender, en el día de hoy."""
    hoy = esc["dia"].date.isoformat()
    return f"{URL}/{proc.id}/atender-ahora?v=atender&date={hoy}&selected={proc.id}"


def _post(client_as, esc, proc, window=None):
    return client_as(esc["off"]).post(
        _url(esc, proc), data={"window_id": str((window or esc["w"]).id)})


def _ficha(client_as, esc, proc):
    hoy = esc["dia"].date.isoformat()
    resp = client_as(esc["off"]).get(f"{URL}/body?v=atender&date={hoy}&selected={proc.id}")
    assert resp.status_code == 200, resp.text[:300]
    (ficha,) = lxml.html.fromstring(resp.text).xpath('//section[@id="appt-attend"]')
    return ficha


def _texto(el):
    return " ".join(el.text_content().split())


def _vigente(make_appointment, esc, proc, status):
    """Cita VIGENTE de ayer en `status`, sin ventana (la de un intento anterior)."""
    ayer = datetime.combine(esc["dia"].date - timedelta(days=1), time(10, 0))
    return make_appointment(proc, when=ayer, status=status, created_by=esc["off"])


def _fase_02(db, proc, status):
    """Deja la fase 02 del proceso en `status` (`make_process` la crea `in_progress`)."""
    from itcj2.apps.titulatec.models import ProcessPhase

    fila = db.query(ProcessPhase).filter_by(process_id=proc.id, phase_number=2).one()
    fila.status = status
    db.flush()


# ===========================================================================
# El servicio
# ===========================================================================
def test_atender_ahora_sienta_y_arranca_el_cotejo_en_una_transaccion(db_session, esc):
    """La cita nace `in_progress` con sus dos eventos, sin correo ni aviso.

    La segunda mitad es el control positivo de los dos ceros: el MISMO espacio,
    agendado por la vía normal, sí encola y sí avisa. Sin ella, «cero filas» y
    «cero avisos» pasarían también con el correo apagado o el aviso roto.
    """
    p, otro = esc["p"][0], esc["p"][1]

    appt = _atender(db_session, esc, p)

    assert appt.status == "in_progress"
    assert appt.is_current is True
    assert appt.window_id == esc["w"].id
    assert appt.scheduled_at == datetime.combine(esc["dia"].date, time(8, 0))
    assert appt.location == "Ventanilla 2"
    assert appt.booked_by == "officer"
    assert appt.created_by_id == esc["off"].id
    assert _eventos(db_session, p.id) == [
        ("appointment_scheduled",
         {"scheduled_at": appt.scheduled_at.isoformat(), "location": "Ventanilla 2",
          "window_id": esc["w"].id, "walkin": True, "attend_now": True}),
        ("appointment_in_progress", None),
    ]
    assert _correos(db_session, p.id) == 0, "el egresado está enfrente: sin correo"
    assert _avisos(db_session, p.student_id) == 0, "ni aviso in-app"

    AppointmentService.create(db_session, otro.id, window_id=esc["w"].id,
                              slot_start=time(8, 0), created_by_id=esc["off"].id)
    assert _correos(db_session, otro.id) == 1, "control positivo: la vía normal SÍ encola"
    assert _avisos(db_session, otro.student_id) == 1, "control positivo: y SÍ avisa"


@pytest.mark.parametrize("caso", ["agendable", "otro_dia", "otro_dueno", "sin_id",
                                  "no_existe"])
def test_solo_en_tus_espacios_sin_horario_de_hoy(db_session, esc, caso, make_review_day,
                                                  make_review_window, make_officer):
    """D7: ni un espacio con franjas, ni el sin horario de otro día, ni el de
    otro encargado — tampoco para quien tenga `manage.all`: la vía es «del
    propio encargado», no «de quien puede editarlo». El id que no existe dice
    LO MISMO: una frase distinta confirmaría cuáles existen. Es error de
    ENTRADA (400): la ficha solo ofrece los espacios que sí valen."""
    p = esc["p"][0]
    if caso == "agendable":
        wid = make_review_window(esc["dia"], esc["off"], start="15:00", end="17:00",
                                 cap=3, visibility="bookable").id
    elif caso == "otro_dia":
        manana = make_review_day(esc["cohort"], day=esc["dia"].date + timedelta(days=1))
        wid = make_review_window(manana, esc["off"], start="08:00", end="14:00",
                                 cap=5, visibility="walkin").id
    elif caso == "otro_dueno":
        otro, _ = make_officer([esc["prog"]], first_name="OTRO")
        wid = make_review_window(esc["dia"], otro, start="08:00", end="14:00",
                                 cap=5, visibility="walkin").id
    elif caso == "sin_id":
        wid = None
    else:
        wid = db_session.execute(text(
            "SELECT COALESCE(MAX(id), 0) + 1000 FROM titulatec_review_windows")).scalar()

    with pytest.raises(err.NotWalkinToday) as exc:
        AppointmentService.attend_now(db_session, p.id, window_id=wid,
                                      actor_id=esc["off"].id)

    assert str(exc.value) == _MENSAJE
    assert exc.value.refresca_la_vista is False
    assert _citas(db_session, p.id) == []


def test_lleno_es_slotfull_y_no_sienta_a_nadie(db_session, esc):
    """El cupo lo decide `assign` bajo el lock, igual que para cualquier cita:
    colisión de estado (200 + panel fresco), nunca 3 de 2."""
    p0, p1, p2 = esc["p"]
    _atender(db_session, esc, p0)
    _atender(db_session, esc, p1)

    with pytest.raises(err.SlotFull) as exc:
        _atender(db_session, esc, p2)

    assert exc.value.refresca_la_vista is True
    assert _citas(db_session, p2.id) == []


@pytest.mark.parametrize("encuesta", ["in_review", "rejected"])
def test_hereda_la_guarda_de_la_encuesta_liberada(db_session, esc, encuesta):
    """D1: tampoco «Atender ahora» sienta a quien GTV no le ha liberado la
    encuesta. La guarda es la de `create`, no una copia."""
    p = esc["nuevo"](encuesta=encuesta)

    with pytest.raises(err.SurveyNotReleased) as exc:
        _atender(db_session, esc, p)

    assert exc.value.status == encuesta
    assert _citas(db_session, p.id) == []


def test_hereda_la_guarda_de_la_revocacion(db_session, esc):
    p = esc["nuevo"](status="cancelled")

    with pytest.raises(err.EnrollmentRevoked):
        _atender(db_session, esc, p)

    assert _citas(db_session, p.id) == []


def test_con_cita_viva_no_abre_otra(db_session, esc):
    """D4 heredado: el segundo «Atender ahora» del mismo egresado choca con la
    cita que ya está en proceso."""
    p = esc["p"][0]
    _atender(db_session, esc, p)

    with pytest.raises(err.AppointmentConflict):
        _atender(db_session, esc, p)

    assert [c.status for c in _citas(db_session, p.id)] == ["in_progress"]


@pytest.mark.parametrize("vigente,fase", [("no_show", "in_progress"),
                                          ("attended", "rejected")])
def test_tras_no_show_o_fase_rechazada_abre_un_intento_nuevo(db_session, esc,
                                                             make_appointment,
                                                             vigente, fase):
    """Los dos casos «sin cita viva» con cita vigente (ruling de la revisión
    de T6): quien no llegó a su cita, o a quien le rechazaron la fase 02 (D5),
    vuelve y está enfrente. `create` abre el intento siguiente y la fila vieja
    conserva su estado: ni se borra la ausencia ni la evidencia del cotejo."""
    p = esc["p"][0]
    vieja = _vigente(make_appointment, esc, p, vigente)
    _fase_02(db_session, p, fase)

    nueva = _atender(db_session, esc, p)

    assert nueva.id != vieja.id
    assert (nueva.status, nueva.is_current, nueva.attempt_no) == ("in_progress", True, 2)
    assert (vieja.status, vieja.is_current) == (vigente, False)


# ===========================================================================
# La ruta
# ===========================================================================
def test_la_ruta_responde_la_ficha_con_el_cotejo_iniciado(db_session, esc, client_as):
    p = esc["p"][0]

    resp = _post(client_as, esc, p)

    assert resp.status_code == 200, unquote(resp.headers.get("X-Tt-Error", ""))
    assert unquote(resp.headers["X-Tt-Notice"]) == "Cotejo iniciado."
    assert resp.headers["X-Tt-Notice-Kind"] == "success"
    (ficha,) = lxml.html.fromstring(resp.text).xpath('//section[@id="appt-attend"]')
    assert "Marcar asistió" in _texto(ficha), "la ficha tiene que abrir con el cotejo en curso"
    assert not ficha.xpath('.//*[starts-with(@id, "appt-atender-")]'), (
        "con la cita ya en proceso la ficha no vuelve a ofrecer «Atender ahora»")
    assert AppointmentService.get_for_process(db_session, p.id).status == "in_progress"


def test_la_ruta_no_alcanza_un_proceso_de_otra_carrera(db_session, esc, client_as,
                                                       make_program):
    """Mismo actor, misma ruta: 200 sobre SU carrera, 404 (sin `X-Tt-Error`)
    sobre la ajena."""
    ajeno = esc["nuevo"](program=make_program("Ingenieria Ajena"))

    ok = _post(client_as, esc, esc["p"][0])
    ko = _post(client_as, esc, ajeno)

    assert ok.status_code == 200, unquote(ok.headers.get("X-Tt-Error", ""))
    assert ko.status_code == 404
    assert "X-Tt-Error" not in ko.headers
    assert _citas(db_session, ajeno.id) == []


def test_la_ruta_rechaza_lo_que_no_es_tu_sin_horario_de_hoy(db_session, esc, client_as,
                                                            make_review_window):
    """Error de ENTRADA: 400 + `X-Tt-Error`, sin swap."""
    p = esc["p"][0]
    agendable = make_review_window(esc["dia"], esc["off"], start="15:00", end="17:00",
                                   cap=3, visibility="bookable")

    resp = _post(client_as, esc, p, window=agendable)

    assert resp.status_code == 400
    assert unquote(resp.headers["X-Tt-Error"]) == _MENSAJE
    assert _citas(db_session, p.id) == []


def test_doble_clic_crea_una_sola_cita(db_session, esc, client_as):
    """Review Focus 4. El segundo POST encuentra la cita viva
    (`AppointmentConflict`, colisión de estado) y responde 200 con la ficha
    fresca y el aviso: una sola cita, un solo par de eventos."""
    p = esc["p"][0]

    primero = _post(client_as, esc, p)
    segundo = _post(client_as, esc, p)

    assert primero.status_code == 200, unquote(primero.headers.get("X-Tt-Error", ""))
    assert unquote(primero.headers["X-Tt-Notice"]) == "Cotejo iniciado."
    assert segundo.status_code == 200, unquote(segundo.headers.get("X-Tt-Error", ""))
    assert unquote(segundo.headers["X-Tt-Notice"]) == str(err.AppointmentConflict())
    assert segundo.headers.get("X-Tt-Notice-Kind") != "success"
    assert [c.status for c in _citas(db_session, p.id)] == ["in_progress"]
    assert [t for t, _ in _eventos(db_session, p.id)] == [
        "appointment_scheduled", "appointment_in_progress"]


# ===========================================================================
# La ficha
# ===========================================================================
def test_la_ficha_sin_cita_ofrece_tu_sin_horario_de_hoy(db_session, esc, client_as,
                                                        make_review_day,
                                                        make_review_window,
                                                        make_officer):
    """Un botón por espacio sin horario de HOY del encargado, con sus lugares.

    El ruido que NO debe salir: su espacio con franjas de hoy, su sin horario
    de mañana, su sin horario de hoy EN PAUSA y el sin horario de hoy de otro
    encargado.
    """
    from itcj2.apps.titulatec.pages.appointments import _detail_ctx

    p = esc["p"][0]
    make_review_window(esc["dia"], esc["off"], start="15:00", end="17:00", cap=3,
                       visibility="bookable")
    manana = make_review_day(esc["cohort"], day=esc["dia"].date + timedelta(days=1))
    make_review_window(manana, esc["off"], start="08:00", end="14:00", cap=5,
                       visibility="walkin")
    make_review_window(esc["dia"], esc["off"], start="18:00", end="19:00", cap=5,
                       visibility="walkin", status="paused")
    otro, _ = make_officer([esc["prog"]], first_name="OTRO")
    make_review_window(esc["dia"], otro, start="08:00", end="14:00", cap=5,
                       visibility="walkin")

    ctx = _detail_ctx(db_session, p.id, user_id=esc["off"].id)
    assert ctx["walkins_hoy"] == [{"id": esc["w"].id, "horario": "08:00–14:00", "libres": 2}]

    ficha = _ficha(client_as, esc, p)
    assert len(ficha.xpath('.//*[starts-with(@id, "appt-atender-")]')) == 1
    (form,) = ficha.xpath('.//form[@id="appt-atender-%d"]' % esc["w"].id)
    assert form.get("hx-post") == _url(esc, p)
    assert form.xpath('.//input[@name="window_id"]/@value') == [str(esc["w"].id)]
    assert _texto(form) == "Atender ahora · sin horario 08:00–14:00 · quedan 2"


def test_la_ficha_cuenta_los_lugares_y_lleno_se_apaga(db_session, esc, client_as):
    """«queda 1» en singular, y lleno el botón se queda (para que se vea por
    qué no hay) pero apagado con `aria-disabled` —enfocable, como el visor— y
    fuera de todo formulario: no hay nada que enviar."""
    p0, p1, p2 = esc["p"]
    _atender(db_session, esc, p0)

    (form,) = _ficha(client_as, esc, p2).xpath(
        './/form[@id="appt-atender-%d"]' % esc["w"].id)
    assert _texto(form) == "Atender ahora · sin horario 08:00–14:00 · queda 1"

    _atender(db_session, esc, p1)

    (boton,) = _ficha(client_as, esc, p2).xpath('.//*[@id="appt-atender-%d"]' % esc["w"].id)
    assert boton.tag == "button"
    assert boton.get("aria-disabled") == "true"
    assert boton.get("type") == "button"
    assert not boton.xpath("ancestor::form")
    assert _texto(boton) == ("Atender ahora · sin horario 08:00–14:00 · "
                             "Lleno: abre más lugares en la Agenda")


def test_con_cita_viva_la_ficha_no_ofrece_atender_ahora(db_session, esc, client_as):
    from itcj2.apps.titulatec.pages.appointments import _detail_ctx

    p, otro = esc["p"][0], esc["p"][1]
    AppointmentService.create(db_session, p.id, window_id=esc["w"].id,
                              slot_start=time(8, 0), created_by_id=esc["off"].id)

    assert _detail_ctx(db_session, p.id, user_id=esc["off"].id)["walkins_hoy"] == []
    assert not _ficha(client_as, esc, p).xpath('.//*[starts-with(@id, "appt-atender-")]')
    # Control positivo: el de al lado, sin cita, sí lo ve (con un lugar menos).
    assert _detail_ctx(db_session, otro.id, user_id=esc["off"].id)["walkins_hoy"] == [
        {"id": esc["w"].id, "horario": "08:00–14:00", "libres": 1}]


@pytest.mark.parametrize("vigente,fase,ofrece", [
    ("no_show", "in_progress", True),     # no llegó a su cita; hoy está enfrente
    ("attended", "rejected", True),       # D5: le faltaron papeles y volvió
    ("attended", "in_progress", False),   # el cotejo ocurrió; falta el dictamen
    ("attended", "approved", False),      # fase 02 aprobada: no hay nada que atender
], ids=["no_show", "atendida-rechazada", "atendida-sin-dictamen", "atendida-aprobada"])
def test_con_cita_vigente_la_ficha_ofrece_atender_ahora_solo_si_abriria_otro_intento(
        db_session, esc, client_as, make_appointment, vigente, fase, ofrece):
    """D7 dice «sin cita viva», no «sin cita» (ruling de la revisión de T6): el
    botón sale también sobre un `no_show` vigente o una `attended` con la fase
    02 rechazada —los dos casos en que el encargado le abriría un intento
    nuevo—, y NO sobre una `attended` cuya fase está por dictaminarse o ya se
    aprobó."""
    from itcj2.apps.titulatec.pages.appointments import _detail_ctx

    p = esc["p"][0]
    _vigente(make_appointment, esc, p, vigente)
    _fase_02(db_session, p, fase)

    esperado = ([{"id": esc["w"].id, "horario": "08:00–14:00", "libres": 2}]
                if ofrece else [])
    assert _detail_ctx(db_session, p.id, user_id=esc["off"].id)["walkins_hoy"] == esperado

    ficha = _ficha(client_as, esc, p)
    formularios = ficha.xpath('.//form[@id="appt-atender-%d"]' % esc["w"].id)
    assert len(formularios) == (1 if ofrece else 0)
    if ofrece:
        (form,) = formularios
        assert form.get("hx-post") == _url(esc, p)
        assert _texto(form) == "Atender ahora · sin horario 08:00–14:00 · quedan 2"


@pytest.mark.parametrize("vigente", [None, "no_show"], ids=["sin_cita", "no_show"])
def test_sin_tu_sin_horario_de_hoy_no_se_ofrece(db_session, esc, client_as,
                                                make_appointment, vigente):
    """Sin un espacio sin horario de hoy no hay dónde «atender ahora», ni sin
    cita ni tras un `no_show`. El control positivo va primero: con su sin
    horario, el mismo egresado SÍ lo tenía."""
    from itcj2.apps.titulatec.pages.appointments import _detail_ctx

    p = esc["p"][0]
    if vigente:
        _vigente(make_appointment, esc, p, vigente)
    assert _detail_ctx(db_session, p.id, user_id=esc["off"].id)["walkins_hoy"]

    esc["w"].visibility = "bookable"
    db_session.flush()

    assert _detail_ctx(db_session, p.id, user_id=esc["off"].id)["walkins_hoy"] == []
    assert not _ficha(client_as, esc, p).xpath('.//*[starts-with(@id, "appt-atender-")]')


@pytest.mark.parametrize("encuesta", ["in_review", "rejected"])
def test_encuesta_sin_liberar_apaga_atender_ahora_y_agendar(
        db_session, esc, client_as, make_appointment, encuesta):
    """I-3 (revisión final): un `no_show` con la encuesta SIN LIBERAR (D1) es
    justo el caso que `abriria_intento` marcaría para «Atender ahora» -pero
    las dos guardas (`SurveyNotSubmitted`/`SurveyNotReleased`) lo rechazarían
    igual que a «Agendar a este alumno». Ninguno de los dos botones se ofrece:
    en su lugar, la píldora del estado real y el texto exacto."""
    from itcj2.apps.titulatec.pages.appointments import _detail_ctx

    p = esc["nuevo"](encuesta=encuesta)
    _vigente(make_appointment, esc, p, "no_show")

    ctx = _detail_ctx(db_session, p.id, user_id=esc["off"].id)
    assert ctx["encuesta_sin_liberar"] is True
    assert ctx["survey_status"] == encuesta
    assert ctx["walkins_hoy"] == []

    ficha = _texto(_ficha(client_as, esc, p))
    assert "Atender ahora" not in ficha
    assert "Agendar a este alumno" not in ficha
    assert "Se podrá agendar cuando Gestión Tecnológica y Vinculación libere su encuesta." in ficha


def test_encuesta_liberada_control_positivo_de_atender_ahora(
        db_session, esc, client_as, make_appointment):
    """Control positivo del test anterior: SOLO con la encuesta LIBERADA
    vuelve «Atender ahora», y el aviso de bloqueo desaparece."""
    from itcj2.apps.titulatec.pages.appointments import _detail_ctx

    p = esc["nuevo"](encuesta="approved")
    _vigente(make_appointment, esc, p, "no_show")

    ctx = _detail_ctx(db_session, p.id, user_id=esc["off"].id)
    assert ctx["encuesta_sin_liberar"] is False
    assert ctx["walkins_hoy"] == [{"id": esc["w"].id, "horario": "08:00–14:00", "libres": 2}]

    ficha = _ficha(client_as, esc, p)
    assert ficha.xpath('.//form[@id="appt-atender-%d"]' % esc["w"].id)
    assert ("Se podrá agendar cuando Gestión Tecnológica y Vinculación libere su encuesta."
            not in _texto(ficha))


# ===========================================================================
# La línea de tiempo del alumno
# ===========================================================================
def test_la_linea_de_tiempo_del_alumno_pone_la_cita_antes_que_el_cotejo(db_session, esc):
    """Ruling de la revisión de T6. Los dos eventos de «Atender ahora» comparten
    `created_at` —el `NOW()` de su transacción—, así que el orden lo tiene que
    decidir el `id`, como ya hacen el expediente y `process_service`.

    Postgres no promete el orden de los empates: devuelve las filas como las
    lee. El escenario reubica en el disco el `appointment_scheduled` (MISMO id y
    mismos datos: DELETE + INSERT crudos) para que quede detrás del
    `appointment_in_progress`, que es lo que el espacio libre de una tabla
    viva puede hacer por su cuenta. Sin el desempate, «Cotejo en proceso»
    salía antes que «Cita agendada».
    """
    import json

    from itcj2.apps.titulatec.pages.student import _phases_ctx

    p = esc["p"][0]
    _atender(db_session, esc, p)
    fila = db_session.execute(text(
        "SELECT id, process_id, actor_id, event_type, phase_number, payload, created_at "
        "FROM titulatec_process_events "
        "WHERE process_id = :p AND event_type = 'appointment_scheduled'"),
        {"p": p.id}).mappings().one()
    db_session.execute(text("DELETE FROM titulatec_process_events WHERE id = :id"),
                       {"id": fila["id"]})
    db_session.execute(text(
        "INSERT INTO titulatec_process_events "
        "(id, process_id, actor_id, event_type, phase_number, payload, created_at) "
        "VALUES (:id, :process_id, :actor_id, :event_type, :phase_number, "
        "CAST(:payload AS json), :created_at)"),
        {**fila, "payload": json.dumps(fila["payload"])})

    (fase2,) = [c for c in _phases_ctx(db_session, p)["phases"] if c["number"] == 2]
    assert [e["label"] for e in fase2["events"]] == ["Cita agendada", "Cotejo en proceso"]


# ===========================================================================
# Orden por apartado
# ===========================================================================
@pytest.mark.parametrize("listado", ["list_for_day", "list_appointments"])
def test_la_agenda_desempata_por_orden_de_apartado(db_session, listado, make_program,
                                                   make_cohort, make_review_day,
                                                   make_officer, make_student,
                                                   make_process, make_review_window):
    """Los apartados de un sin horario guardan TODOS la misma hora (la
    apertura): sin desempate, Postgres los devuelve en el orden en que los lee,
    que no es el de apartado. `(scheduled_at, id)`: el id es el orden de llegada.

    El escenario pone todo en contra del id: la fila de id MENOR se escribe
    DESPUÉS (queda detrás en el disco y en el índice por ventana) y es del
    proceso de id MAYOR. Así, sin el desempate, cualquier plan —recorrido de la
    tabla, índice por proceso o por ventana, join ordenado por proceso— entrega
    primero la de id mayor. Día lejano y carrera propia: solo estas dos filas.
    """
    from itcj2.apps.titulatec.models import ReviewAppointment

    dia = date(2031, 3, 10)
    prog = make_program("Ingenieria de Desempate")
    cohort = make_cohort()
    officer, _ = make_officer([prog])
    w = make_review_window(make_review_day(cohort, day=dia), officer, start="08:00",
                           end="14:00", cap=5, visibility="walkin")
    p_menor = make_process(make_student(), cohort=cohort, program=prog, current_phase=2)
    p_mayor = make_process(make_student(), cohort=cohort, program=prog, current_phase=2)
    siguiente = text("SELECT nextval(pg_get_serial_sequence("
                     "'titulatec_review_appointments', 'id'))")
    id_menor = db_session.execute(siguiente).scalar()
    id_mayor = db_session.execute(siguiente).scalar()
    for rid, proc in ((id_mayor, p_menor), (id_menor, p_mayor)):
        db_session.add(ReviewAppointment(
            id=rid, process_id=proc.id, window_id=w.id,
            scheduled_at=datetime.combine(dia, time(8, 0)), status="scheduled",
            created_by_id=officer.id, is_current=True, attempt_no=1))
        db_session.flush()

    if listado == "list_for_day":
        filas = AppointmentService.list_for_day(db_session, dia,
                                                allowed_program_ids={prog.id})
    else:
        filas = AppointmentService.list_appointments(db_session, program_id=prog.id)

    assert [a.id for a in filas] == [id_menor, id_mayor]


# ===========================================================================
# Arrastre de la revisión de T2: `_lock_window` relee la ventana bajo el lock
# ===========================================================================
def test_assign_valida_con_el_cupo_releido_bajo_el_lock(db_session, esc):
    """Otro encargado bajó el cupo a 1 mientras esta reserva esperaba el lock:
    en memoria sigue diciendo 2, la fila dice 1 y ya hay uno sentado. Validar
    con el 2 dejaba una de más."""
    w = esc["w"]
    SlotService.assign(db_session, w.id, time(8, 0), esc["p"][0].id, esc["off"].id)
    db_session.execute(text("UPDATE titulatec_review_windows SET capacity = 1 "
                            "WHERE id = :w"), {"w": w.id})
    assert w.capacity == 2, "el escenario necesita el cupo viejo en memoria"

    with pytest.raises(err.SlotFull):
        SlotService.assign(db_session, w.id, time(8, 0), esc["p"][1].id, esc["off"].id)

    assert _citas(db_session, esc["p"][1].id) == []


def test_assign_valida_con_el_modo_releido_bajo_el_lock(db_session, esc):
    """Otro encargado pasó el espacio a «Agendable» (franjas de 30, UN lugar
    cada una) mientras esta reserva esperaba: la apertura ya es una franja de
    un lugar y la ocupa el primero. Con el modo viejo en memoria —sin horario,
    dos lugares en total— entraba un segundo a las 08:00."""
    w = esc["w"]
    SlotService.assign(db_session, w.id, time(8, 0), esc["p"][0].id, esc["off"].id)
    db_session.execute(text("UPDATE titulatec_review_windows SET visibility = 'bookable', "
                            "capacity = 1 WHERE id = :w"), {"w": w.id})
    assert w.visibility == "walkin", "el escenario necesita el modo viejo en memoria"

    with pytest.raises(err.SlotFull):
        SlotService.assign(db_session, w.id, time(8, 0), esc["p"][1].id, esc["off"].id)


def test_assign_ve_los_lugares_que_otro_abrio_bajo_el_lock(db_session, esc):
    """La otra dirección: otro encargado abrió un lugar mientras se esperaba.
    Con el cupo viejo (2, lleno) el tercero se quedaba fuera sin razón."""
    w = esc["w"]
    for proc in esc["p"][:2]:
        SlotService.assign(db_session, w.id, time(8, 0), proc.id, esc["off"].id)
    db_session.execute(text("UPDATE titulatec_review_windows SET capacity = 3 "
                            "WHERE id = :w"), {"w": w.id})
    assert w.capacity == 2, "el escenario necesita el cupo viejo en memoria"

    appt = SlotService.assign(db_session, w.id, time(8, 0), esc["p"][2].id, esc["off"].id)

    assert appt.window_id == w.id


def test_el_espacio_borrado_mientras_se_esperaba_es_invalidslot(db_session, esc,
                                                                make_review_window):
    """Si la fila ya no existe, el `FOR UPDATE` no devuelve nada: la frase de
    ventanilla, no un error de integridad (ni de la relectura) al final."""
    vacia = make_review_window(esc["dia"], esc["off"], start="15:00", end="17:00",
                               cap=2, visibility="walkin")
    db_session.execute(text("DELETE FROM titulatec_review_windows WHERE id = :w"),
                       {"w": vacia.id})

    with pytest.raises(err.InvalidSlot) as exc:
        SlotService.assign(db_session, vacia.id, time(15, 0), esc["p"][0].id,
                           esc["off"].id)

    assert str(exc.value) == "Ese espacio ya no existe."


def test_abrir_lugares_relee_la_ventana_una_sola_vez(db_session, esc):
    """La relectura vive en `_lock_window` y es la ÚNICA: `add_places` ya no
    refresca por su cuenta (una segunda lectura no protege nada más). Se
    cuentan los SELECT a la tabla de ventanas que no son el propio lock."""
    lecturas = []

    def _cuenta(_conn, _cursor, statement, _params, _context, _executemany):
        sql = " ".join(statement.split()).upper()
        if (sql.startswith("SELECT") and "FROM TITULATEC_REVIEW_WINDOWS" in sql
                and "FOR UPDATE" not in sql):
            lecturas.append(sql)

    conn = db_session.connection()
    event.listen(conn, "before_cursor_execute", _cuenta)
    try:
        ReviewWindowService.add_places(db_session, esc["w"], 3)
    finally:
        event.remove(conn, "before_cursor_execute", _cuenta)

    assert esc["w"].capacity == 5
    assert len(lecturas) == 1, lecturas
