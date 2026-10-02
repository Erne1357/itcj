"""`MailComposer`: qué correo sale de las filas del outbox, o por qué ya no
(spec 2026-09-28 §5 y §6 C3.6; Tarea 6).

Lo que se fija aquí. El despachador (Tarea 7) consume EXACTAMENTE esto:

1. Un correo por tipo y variante: asunto EXACTO con el prefijo
   `[TitulaTec ITCJ] `, plantilla (archivo bajo `titulatec/email/`) y liga
   (`{PUBLIC_ORIGIN}/itcj/login?next=<ruta>`).
2. Grupo `docs:` — el ÚLTIMO dictamen de cada documento, por `(created_at,
   id)`, y el avance de la fase 1 en el MISMO correo.
3. Grupo `cita:` (Review Focus 5) — se arma con la cita VIGENTE al enviar:
   ráfaga = un correo con la fecha final; agendada y cancelada = nada; la
   cancelación de una cita que ya conocía = aviso con el motivo; la cancelada
   por una vía sin correo (el propio alumno) = nada; la vigente ya en cotejo =
   obsoleto.
4. «No se presentó» re-validado al enviar (D8), y un solo aviso por cita
   aunque se marque dos veces dentro de la espera (ruling 2026-09-29).
5. Lectura pura: los requisitos NO se siembran, nada commitea, la sesión queda
   sin cambios.
6. Texto libre escapado (Review Focus 2); ninguna liga fuera de `safe_next`;
   ningún render con `None`, código crudo o variables sin definir.
7. Recordatorios (#8, #10, #11; Tarea 8), re-validados al enviar (D8): la cita
   sigue vigente, activa, con la misma fecha y en el futuro; siguen faltando
   documentos o hay por corregir (con los nombres del estado ACTUAL, no del
   payload); sigue en la fase 2 sin encuesta. Si no, `Obsolete`. Y ningún
   `kind` del catálogo se queda sin composición.
8. No adeudo de biblioteca y ajustes de GTV (spec 2026-10-01-titulatec-
   biblioteca-caja-design.md §4.11, D11-D14; Tarea 10 de ese plan): D11 «Ya
   puedes agendar» / «Para agendar te falta: …» con el estado VIVO del
   `ClearanceGate` en la encuesta liberada y en el no adeudo liberado; D12
   (`mailto:` en observaciones y revocación); D13; la variante `prior`; los
   cuatro correos nuevos, cada uno re-validado al enviar, con los montos
   VIGENTES y la «Información para el alumno» sanitizada.

Las filas se encolan con `StudentMail` (el contrato real de los payloads), no a
mano: si la Tarea 4 cambia un payload, esto se entera.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import unquote

import lxml.html
import pytest

import itcj2.models  # noqa: F401

PREFIJO = "[TitulaTec ITCJ] "
MALICIOSO = '<script>alert(1)</script> & "x"'
LOGGER = "itcj2.apps.titulatec.services.mail_compose"

# D12 (spec 2026-10-01-titulatec-biblioteca-caja-design.md §2), literal: la ÚNICA
# liga de un correo que no es la del login (observaciones y revocación de GTV).
MAILTO_GTV = "mailto:servicio_ext@cdjuarez.tecnm.mx"
D12_TEXTO = "Para más información, contactar con servicio_ext@cdjuarez.tecnm.mx"
# D11/D13: la frase que antes iba fija en la encuesta liberada.
YA_PUEDES = "Ya puedes agendar tu cita de cotejo"

_NOMBRES = {
    "birth_certificate": "Acta de nacimiento",
    "high_school_cert": "Certificado de bachillerato",
    "curp": "CURP certificada",
}

# Reloj del compositor para los recordatorios (el de cita dice «mañana» y se
# re-valida contra la hora). Lunes 10 de marzo de 2031: con `hoy` fijo, la
# fecha larga no depende del año en curso.
HOY_FIJO = datetime(2031, 3, 10, 9, 0)
CITA_MANANA = datetime(2031, 3, 11, 10, 30)
ANCLA = datetime(2031, 3, 1, 9, 0)
# Reloj de las pruebas de la cita (#7/#9): antes de la agenda de `agenda_slots`
# (lunes 7 de mayo de 2029) y en OTRO año, así que la fecha larga lleva siempre
# «de 2029». Sin reloj fijo era una bomba de tiempo: en 2029 `dia_largo` omite
# el año en curso y las aserciones «… de 2029» se rompían solas.
HOY_AGENDA = datetime(2028, 11, 6, 9, 0)


# ---------------------------------------------------------------------------
# Andamiaje local
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _correo_encendido(monkeypatch):
    """Encolar necesita el correo encendido, y el corte a T-soft va en su valor
    por omisión (fase 3). Se fijan ATRIBUTOS del singleton de `get_settings()`,
    como el resto de la suite, sin depender del `.env` del contenedor."""
    from itcj2.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "TITULATEC_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "TITULATEC_HANDOFF_PHASE", 3)


@pytest.fixture(autouse=True)
def _graph_prohibido(monkeypatch):
    """Componer no manda nada (eso es del despachador): cualquier intento de
    pedir el token de Graph o de enviar revienta la prueba."""
    def _prohibido(*_a, **_k):
        raise AssertionError("MailComposer no envía correo: eso es del despachador")

    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent", _prohibido)
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", _prohibido)


@pytest.fixture()
def proceso(seed_phase_defs, make_student, make_process):
    """Proceso vivo de un egresado ficticio. Con el catálogo de fases sembrado:
    sin él la fase 1 no se reconoce y su avance no entra al grupo `docs:`."""
    seed_phase_defs()

    def _make(fase=1, first_name="ALUMNO"):
        return make_process(make_student(first_name=first_name),
                            current_phase=fase, phases=False)

    return _make


@pytest.fixture()
def cita_esc(agenda_slots, make_survey_review):
    """`agenda_slots` (lunes 2029-05-07, ventana 09:00-11:00 en franjas de 30,
    cupo 1) con la encuesta de `p1` YA LIBERADA: sin liberarla no se agenda
    (D1, spec 2026-09-29-titulatec-cotejo-espacios-design.md §2, revierte D2
    del 2026-09-15)."""
    make_survey_review(agenda_slots["p1"], status="approved")
    return agenda_slots


@pytest.fixture()
def reloj(monkeypatch):
    """Fija el reloj del compositor (por omisión `HOY_FIJO`) y lo devuelve: su
    `db_now()` y el de `dates_es`, que es el que lee `dia_largo` para decidir
    si la fecha lleva año cuando el compositor no le pasa `hoy` (cita #7,
    cancelación, «no se presentó»)."""
    def _fijar(ahora=HOY_FIJO):
        monkeypatch.setattr("itcj2.apps.titulatec.services.mail_compose.db_now",
                            lambda: ahora)
        monkeypatch.setattr("itcj2.apps.titulatec.utils.dates_es.db_now",
                            lambda: ahora)
        return ahora

    return _fijar


def _recordatorio(db, kind, proc, appt=None):
    """Lo que encola el barrido diario (`MailReminders.run`), por el contrato
    real de `StudentMail`. Devuelve la fila."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    if kind == "appt_reminder":
        assert StudentMail.appointment_reminder(db, proc, appt=appt) is True
    elif kind == "docs_reminder":
        assert StudentMail.docs_reminder(db, proc, anchor=ANCLA, index=0) is True
    elif kind == "library_reminder":
        assert StudentMail.library_reminder(db, proc, anchor=ANCLA, index=0) is True
    else:
        assert StudentMail.survey_reminder(db, proc, anchor=ANCLA, index=0) is True
    return [f for f in _pendientes(db, proc.id) if f.kind == kind][-1]


def _texto(html):
    """El texto que LEE el egresado: sin etiquetas y con los espacios juntos
    (las plantillas parten las frases en varias líneas)."""
    return " ".join(lxml.html.fromstring(html).text_content().split())


@pytest.fixture()
def con_biblioteca(db_session, seed_phase_defs, make_student, make_cohort, make_process,
                   make_library_clearance, make_survey_review):
    """Proceso de una convocatoria CON candado de biblioteca (requisito
    automático `library_clearance` activo, con su «Información para el
    alumno» si se da `info_html`) y su fila de no adeudo en `biblioteca`
    (`cleared_via` = `via`). En caja o liberada lleva adeudo $300 + donación
    $800 = $1,100, sobrescribibles por `**cols`. `encuesta` = estado de su
    `SurveyReview` (`None` = no la ha enviado)."""
    from itcj2.apps.titulatec.models import CotejoRequirement

    seed_phase_defs()

    def _make(fase=2, biblioteca="pending", via=None, encuesta=None, info_html=None,
              **cols):
        cohort = make_cohort(book_donation_amount=Decimal("800.00"))
        db_session.add(CotejoRequirement(
            cohort_id=cohort.id, label="No-adeudo de biblioteca", icon="book",
            code="library_clearance", auto_source="library_clearance",
            order_index=0, info_html=info_html))
        db_session.flush()
        proc = make_process(make_student(first_name="ALUMNO"), cohort=cohort,
                            current_phase=fase, phases=False, library_clearance=None)
        if biblioteca in ("awaiting_payment", "cleared"):
            cols = {"debt_amount": Decimal("300.00"), "donation_amount": Decimal("800.00"),
                    "total_amount": Decimal("1100.00"),
                    "ready_at": datetime(2031, 3, 1, 9, 0), **cols}
        if via is not None:
            cols["cleared_via"] = via
        make_library_clearance(proc, status=biblioteca, **cols)
        if encuesta is not None:
            make_survey_review(proc, status=encuesta)
        return proc

    return _make


def _pasa_a_caja(db, proc, *, debt=Decimal("300.00"), donation=Decimal("800.00"),
                 total=Decimal("1100.00"), note=None, updated=False):
    """Lo que encola `LibraryClearanceService._mark_ready`."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    assert StudentMail.library_ready(db, proc, debt=debt, donation=donation, total=total,
                                     note=note, updated=updated) is True


def _pendientes(db, pid):
    """Filas `pending` del proceso en orden de llegada: lo que el despachador le
    pasaría al compositor. El flush es EXPLÍCITO (en producción
    `autoflush=False`)."""
    from itcj2.apps.titulatec.models import EmailOutbox

    db.flush()
    return (db.query(EmailOutbox).filter_by(process_id=pid, status="pending")
            .order_by(EmailOutbox.id).all())


def _ya_salio(db, pid):
    """Lo pendiente del proceso ya salió: el despachador lo marcó `sent`."""
    for fila in _pendientes(db, pid):
        fila.status = "sent"
    db.flush()


def _liberado_que_salio(db, proc, via="no_charge"):
    """El egresado YA recibió «Tu no adeudo de biblioteca quedó liberado»: el
    `library_cleared` real, dado por enviado. Sin eso, la reversión que
    venga después no sale (E10, spec 2026-10-02 §2)."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    assert StudentMail.library_cleared(db, proc, via=via) is True
    _ya_salio(db, proc.id)


def _componer(db, proc, filas=None):
    """`MailComposer.compose` tal como lo llama el despachador. De paso fija que
    componer es solo LECTURA: la sesión queda sin nada nuevo ni modificado."""
    from itcj2.apps.titulatec.services.mail_compose import MailComposer
    from itcj2.core.models.user import User

    filas = _pendientes(db, proc.id) if filas is None else filas
    resultado = MailComposer.compose(db, filas, proc, db.get(User, proc.student_id))
    assert not (db.new or db.dirty or db.deleted), "componer escribió en la sesión"
    return resultado


def _html(composed, *, estricto=False, sin_autoescape=False):
    """El HTML del correo con el MISMO Jinja que usa `email_helper._render`.

    `estricto`: una variable que el compositor no dio revienta en vez de
    pintarse vacía. `sin_autoescape`: el entorno real autoescapa los `.html`,
    así que un `|e` olvidado no se notaría; sin autoescape, lo único que
    protege es el `|e` de la propia plantilla (la convención de estos correos).
    """
    from itcj2.apps.titulatec.pages.nav import titulatec_templates

    nombre = f"titulatec/email/{composed.template}"
    if not (estricto or sin_autoescape):
        return titulatec_templates.get_template(nombre).render(**composed.context)
    from jinja2 import StrictUndefined

    opciones = {}
    if estricto:
        opciones["undefined"] = StrictUndefined
    if sin_autoescape:
        opciones["autoescape"] = False
    env = titulatec_templates.env.overlay(**opciones)
    return env.get_template(nombre).render(**composed.context)


def _liga(ruta):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    return StudentMail.link(ruta)


def _eventos(filas):
    return [f.payload["event"] for f in filas]


def _dictamen(db, proc, type_code, status, note=None):
    """Lo que encola `DocumentService.review` (grupo `docs:{pid}`)."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    assert StudentMail.doc_reviewed(db, proc, type_code=type_code,
                                    doc_name=_NOMBRES[type_code], status=status,
                                    note=note) is True


def _avance_fase_1(db, proc):
    """Lo que encola `PhaseService.approve_phase(1)`: va al MISMO grupo `docs:`."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    assert StudentMail.phase_approved(db, proc, phase_number=1,
                                      phase_name="Fase 01 · Documentos iniciales",
                                      next_phase=2, next_name="Fase 02 · Cita de cotejo",
                                      handoff=False) is True


def _requisito(db, cohort_id, label, *, hint=None, orden=0, activo=True):
    """Requisito de cotejo de la convocatoria (qué llevar a la cita)."""
    from itcj2.apps.titulatec.models import CotejoRequirement

    fila = CotejoRequirement(cohort_id=cohort_id, label=label, hint=hint,
                             order_index=orden, is_active=activo)
    db.add(fila)
    db.flush()
    return fila


def _agendar(db, esc, *, slot=time(9, 0), location="Ventanilla 3"):
    """El encargado agenda a `p1` (camino real: `AppointmentService.create`)."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    return AppointmentService.create(db, esc["p1"].id, window_id=esc["w"].id,
                                     slot_start=slot, created_by_id=esc["off"].id,
                                     location=location)


def _mover(db, esc, appt, slot):
    """El encargado lo mueve de franja: devuelve la cita NUEVA."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    return AppointmentService.reschedule(db, appt, window_id=esc["w"].id,
                                         slot_start=slot, actor_id=esc["off"].id)


@pytest.fixture()
def walkin_esc(seed_phase_defs, make_program, make_cohort, make_review_day, make_officer,
               make_student, make_process, make_review_window, make_survey_review):
    """Como `cita_esc`, pero con un espacio SIN HORARIO 08:00-14:00 (D3): la
    encuesta de `p1` ya liberada, así que `AppointmentService.create` real
    funciona igual que con franjas."""
    seed_phase_defs()
    prog = make_program("Ingenieria Sin Horario de Correos")
    cohort = make_cohort()
    dia = make_review_day(cohort, day=date(2029, 5, 7))
    officer, pos = make_officer([prog])
    w = make_review_window(dia, officer, start="08:00", end="14:00", slot=30, cap=3,
                           position=pos, visibility="walkin")
    p1 = make_process(make_student(), cohort=cohort, program=prog, current_phase=2)
    make_survey_review(p1, status="approved")
    return {"prog": prog, "cohort": cohort, "dia": dia, "off": officer, "pos": pos,
            "w": w, "p1": p1}


def _walkin_appt(db, esc, make_appointment, **kw):
    """Reserva sin horario (a la apertura) del `walkin` de `esc`, SIN pasar
    por `AppointmentService` (no encola `appt_changed`): igual que `_legado`
    en `test_walkin_core.py` pero a la HORA DE APERTURA, así que
    `is_walkin_reservation` la reconoce como reserva y no como legado."""
    w = esc["w"]
    appt = make_appointment(esc["p1"], when=datetime.combine(esc["dia"].date, w.start_time),
                            location="Sala de cotejo", **kw)
    appt.window = w
    db.flush()
    return appt


# ---------------------------------------------------------------------------
# #1 / #1b — grupo `docs:{pid}`
# ---------------------------------------------------------------------------
def test_docs_revisados_sin_correcciones(db_session, proceso):
    from itcj2.apps.titulatec.services.mail_compose import Composed

    proc = proceso()
    _dictamen(db_session, proc, "birth_certificate", "approved")
    _dictamen(db_session, proc, "curp", "approved")

    c = _componer(db_session, proc)

    assert isinstance(c, Composed)
    assert c.subject == "[TitulaTec ITCJ] Revisamos tus documentos"
    assert c.template == "docs_review.html"
    assert c.link == _liga("/titulatec/student/documents")
    assert c.context["advanced"] is False
    assert c.context["docs"] == [
        {"name": "Acta de nacimiento", "approved": True, "note": None},
        {"name": "CURP certificada", "approved": True, "note": None},
    ]


def test_docs_con_rechazo_pide_correcciones(db_session, proceso):
    proc = proceso()
    _dictamen(db_session, proc, "birth_certificate", "approved")
    _dictamen(db_session, proc, "curp", "rejected", note="La CURP no es legible")

    c = _componer(db_session, proc)

    assert c.subject == "[TitulaTec ITCJ] Revisamos tus documentos: hay correcciones"
    assert c.template == "docs_review.html"
    assert c.link == _liga("/titulatec/student/documents")
    html = _html(c)
    assert "La CURP no es legible" in html
    assert "Necesita corrección" in html and "Aprobado" in html


def test_docs_aprobados_y_avance_de_fase_1_en_el_mismo_correo(db_session, proceso):
    """#1b: el tercer aprobado auto-avanza la fase 1 y ese aviso cae en el MISMO
    grupo: un solo correo que dice «aprobados» y lleva a la cita."""
    proc = proceso()
    _dictamen(db_session, proc, "curp", "approved")
    _avance_fase_1(db_session, proc)
    filas = _pendientes(db_session, proc.id)
    assert {f.group_key for f in filas} == {f"docs:{proc.id}"}

    c = _componer(db_session, proc, filas)

    assert c.subject == "[TitulaTec ITCJ] ¡Tus documentos fueron aprobados!"
    assert c.template == "docs_review.html"
    assert c.link == _liga("/titulatec/student/cita")
    assert c.context["advanced"] is True
    html = _html(c)
    assert "Fase 02 · Cita de cotejo" in html
    # Siguientes pasos, en este orden: la encuesta de egresados y luego agendar.
    assert html.index("encuesta de egresados") < html.index("Agenda tu")


def test_avance_de_fase_1_con_un_rechazo_en_el_grupo_pide_correcciones(db_session, proceso):
    """B4: el grupo trae el avance de la fase 1 pero, tras el ÚLTIMO dictamen de
    cada tipo, queda un rechazo (dictamen tardío desde la bandeja, o la fase 1
    aprobada a mano con un documento rechazado). El asunto y el encabezado son
    los de correcciones, no «¡aprobados!»; el cuerpo sí menciona el avance, y no
    le pide volver a subir (la fase 1 ya no es la actual)."""
    proc = proceso()
    _dictamen(db_session, proc, "birth_certificate", "approved")
    _avance_fase_1(db_session, proc)
    _dictamen(db_session, proc, "curp", "rejected", note="La CURP no es legible")

    c = _componer(db_session, proc)

    assert c.subject == "[TitulaTec ITCJ] Revisamos tus documentos: hay correcciones"
    assert c.template == "docs_review.html"
    assert c.link == _liga("/titulatec/student/cita")
    html = _html(c)
    assert "fueron aprobados" not in html
    assert "hay correcciones" in html and "La CURP no es legible" in html
    assert "Fase 02 · Cita de cotejo" in html
    assert "vuélvelos a subir" not in html


def test_avance_de_fase_1_sin_dictamenes_en_el_grupo(db_session, proceso):
    """Los dictámenes salieron en un correo anterior y el avance llegó solo."""
    proc = proceso()
    _avance_fase_1(db_session, proc)

    c = _componer(db_session, proc)

    assert c.subject == "[TitulaTec ITCJ] ¡Tus documentos fueron aprobados!"
    assert c.link == _liga("/titulatec/student/cita")
    assert c.context["docs"] == []


def test_docs_ultimo_dictamen_por_tipo_gana(db_session, proceso):
    """Rechazó la CURP y luego la aprobó: el correo la da por aprobada y ya no
    pide correcciones. El orden es `created_at` y DESPUÉS id: aquí la fila de
    id menor es la más nueva, así que ordenar solo por id se equivocaría."""
    proc = proceso()
    _dictamen(db_session, proc, "curp", "approved")
    _dictamen(db_session, proc, "curp", "rejected", note="Ilegible")
    _dictamen(db_session, proc, "birth_certificate", "approved")
    aprobada, rechazada, acta = _pendientes(db_session, proc.id)
    base = aprobada.created_at
    rechazada.created_at = base + timedelta(minutes=1)
    acta.created_at = base + timedelta(minutes=2)
    aprobada.created_at = base + timedelta(minutes=5)
    db_session.flush()

    c = _componer(db_session, proc)

    assert c.subject == "[TitulaTec ITCJ] Revisamos tus documentos"
    # Cada documento, en el lugar de su PRIMER dictamen, con el ÚLTIMO.
    assert c.context["docs"] == [
        {"name": "CURP certificada", "approved": True, "note": None},
        {"name": "Acta de nacimiento", "approved": True, "note": None},
    ]
    assert "Ilegible" not in _html(c)


def test_docs_en_una_misma_transaccion_desempata_el_id(db_session, proceso):
    """Dos dictámenes de una misma transacción comparten `NOW()`: gana el id
    mayor, que es el que se escribió después."""
    proc = proceso()
    _dictamen(db_session, proc, "curp", "approved")
    _dictamen(db_session, proc, "curp", "rejected", note="Ilegible")
    uno, dos = _pendientes(db_session, proc.id)
    assert uno.created_at == dos.created_at

    c = _componer(db_session, proc)

    assert c.subject == "[TitulaTec ITCJ] Revisamos tus documentos: hay correcciones"
    assert c.context["docs"] == [
        {"name": "CURP certificada", "approved": False, "note": "Ilegible"}]


# ---------------------------------------------------------------------------
# #2 / #3 — fase aprobada y rechazada (individuales)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("pago, asunto, fase_liga, frase", [
    (dict(phase_number=3, phase_name="Fase 03 · Formato B", next_phase=4,
          next_name="Fase 04 · Asignación de sinodales", handoff=False),
     "[TitulaTec ITCJ] Avanzaste a Fase 04 · Asignación de sinodales", 4,
     "Avanzaste a Fase 04 · Asignación de sinodales"),
    (dict(phase_number=2, phase_name="Fase 02 · Cita de cotejo", next_phase=3,
          next_name="Fase 03 · Formato B", handoff=True),
     "[TitulaTec ITCJ] Concluiste tu trámite con Servicios Escolares", 3,
     "Departamento de Titulación, en el sistema T-soft"),
    (dict(phase_number=8, phase_name="Fase 08 · Acto protocolario", next_phase=None,
          next_name=None, handoff=False),
     "[TitulaTec ITCJ] ¡Proceso completado!", 8, "¡Proceso completado!"),
], ids=["avanza", "corte-a-tsoft", "completado"])
def test_fase_aprobada(db_session, proceso, pago, asunto, fase_liga, frase):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso(fase=pago["phase_number"])
    assert StudentMail.phase_approved(db_session, proc, **pago) is True
    (fila,) = _pendientes(db_session, proc.id)
    assert fila.group_key is None                  # individual: no es la fase 1

    c = _componer(db_session, proc)

    assert c.subject == asunto
    assert c.template == "phase_approved.html"
    assert c.link == _liga(f"/titulatec/student/dashboard?fase={fase_liga}")
    assert frase in _html(c)


def test_fase_rechazada_con_motivo_y_que_hacer(db_session, proceso):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso(fase=2)
    StudentMail.phase_rejected(db_session, proc, phase_number=2,
                               phase_name="Fase 02 · Cita de cotejo",
                               reason="Faltó el comprobante de pago")

    c = _componer(db_session, proc)

    assert c.subject == ("[TitulaTec ITCJ] Una fase necesita correcciones: "
                         "Fase 02 · Cita de cotejo")
    assert c.template == "phase_rejected.html"
    assert c.link == _liga("/titulatec/student/dashboard?fase=2")
    html = _html(c)
    assert "Faltó el comprobante de pago" in html
    assert "Qué hacer" in html


# ---------------------------------------------------------------------------
# #4-#6 — dictamen de GTV sobre la encuesta
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("resultado, asunto", [
    ("approved", "[TitulaTec ITCJ] GTV liberó tu encuesta de egresados"),
    ("rejected", "[TitulaTec ITCJ] GTV dejó observaciones en tu encuesta de egresados"),
    ("revoked", "[TitulaTec ITCJ] Se revocó la liberación de tu encuesta de egresados"),
])
def test_dictamen_de_gtv(db_session, proceso, make_survey_review, resultado, asunto):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso(fase=2)
    # El estado que deja cada dictamen (revocar la regresa a `rejected`).
    make_survey_review(proc, status="approved" if resultado == "approved" else "rejected")
    motivo = None if resultado == "approved" else "Debe Servicio Social"
    StudentMail.survey_result(db_session, proc, result=resultado, reason=motivo)

    c = _componer(db_session, proc)

    assert c.subject == asunto
    assert c.template == "survey_result.html"
    assert c.link == _liga("/titulatec/student/dashboard?fase=2")
    assert c.context["result"] == resultado
    html = _html(c)
    # Observaciones y revocación: el motivo y, D12 (spec 2026-10-01 §2), a quién
    # escribir; la ventanilla de GTV ya no se menciona.
    assert ("Debe Servicio Social" in html) is (motivo is not None)
    assert "ventanilla de GTV" not in html
    assert (D12_TEXTO in _texto(html)) is (resultado != "approved")
    assert (f'href="{MAILTO_GTV}"' in html) is (resultado != "approved")
    # D13: liberada ya no dice «Ya puedes agendar» fijo; lo decide D11 (aquí,
    # sin nada pendiente, sí lo dice).
    assert (YA_PUEDES in _texto(html)) is (resultado == "approved")


@pytest.mark.parametrize("resultado", ["rejected", "revoked"])
def test_d12_en_observaciones_y_revocacion(db_session, proceso, make_survey_review,
                                          resultado):
    """D12: «Acude a la ventanilla de GTV para resolverlo.» → «Para más
    información, contactar con servicio_ext@cdjuarez.tecnm.mx», con la liga
    `mailto:` en el correo."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso(fase=2)
    make_survey_review(proc, status="rejected")
    StudentMail.survey_result(db_session, proc, result=resultado, reason="Debe Servicio Social")

    html = _html(_componer(db_session, proc))

    assert ('Para más información, contactar con <a href="mailto:servicio_ext@cdjuarez'
            '.tecnm.mx"') in html
    assert ">servicio_ext@cdjuarez.tecnm.mx</a>" in html
    assert "Acude a la ventanilla" not in html


# ---------------------------------------------------------------------------
# D11 — «Ya puedes agendar» / «Para agendar te falta: …» con el estado VIVO
# (`ClearanceGate`, al componer) en los correos de liberación
# ---------------------------------------------------------------------------
def test_cada_bloqueo_del_gate_tiene_su_frase():
    """El conjunto cerrado de `ClearanceGate.BLOCKERS`, ni uno más ni uno menos:
    un bloqueo nuevo sin frase rompería la composición."""
    from itcj2.apps.titulatec.services.clearance_gate import BLOCKERS
    from itcj2.apps.titulatec.services.mail_compose import _FALTA

    assert set(_FALTA) == set(BLOCKERS)
    assert all(texto and texto[:1].islower() for texto in _FALTA.values())


@pytest.mark.parametrize("biblioteca, falta", [
    ("cleared", None),
    ("pending", "que el Centro de Información revise tu no adeudo de biblioteca"),
    ("awaiting_payment",
     "pagar $1,100.00 en Caja (Recursos Financieros) para liberar tu no adeudo de "
     "biblioteca"),
], ids=["biblioteca-liberada", "biblioteca-en-revision", "pago-pendiente"])
def test_encuesta_liberada_segun_el_no_adeudo(db_session, con_biblioteca, biblioteca,
                                             falta):
    """D11/D13: GTV liberó la encuesta; si el no adeudo sigue pendiente, el correo
    dice qué falta en vez de «Ya puedes agendar»."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = con_biblioteca(biblioteca=biblioteca, encuesta="approved")
    StudentMail.survey_result(db_session, proc, result="approved")

    c = _componer(db_session, proc)
    texto = _texto(_html(c, estricto=True))

    assert "liberó tu encuesta de egresados" in texto
    if falta is None:
        assert YA_PUEDES in texto
        assert "Para agendar te falta" not in texto
        assert c.context["falta"] == []
    else:
        assert YA_PUEDES not in texto
        assert "Para agendar te falta:" in texto
        assert c.context["falta"] == [falta]
        assert falta in texto


def test_convocatoria_sin_candado_no_pide_no_adeudo(db_session, proceso,
                                                   make_survey_review):
    """Invariante 8: sin el requisito automático, el no adeudo no bloquea."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso(fase=2)
    make_survey_review(proc, status="approved")
    StudentMail.survey_result(db_session, proc, result="approved")

    c = _componer(db_session, proc)

    assert c.context["falta"] == []
    assert YA_PUEDES in _texto(_html(c))


def test_constancia_previa_de_encuesta_usa_su_texto(db_session, con_biblioteca):
    """T6 dejó la variante `prior` en la plantilla; el compositor le pasa
    `origin` del payload: sale el texto de la constancia previa, no el de
    liberación normal, y con D11."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = con_biblioteca(biblioteca="pending", encuesta="approved")
    StudentMail.survey_result(db_session, proc, result="approved", origin="prior")

    c = _componer(db_session, proc)
    texto = _texto(_html(c, estricto=True))

    # GTV no dictaminó nada aquí: el asunto tampoco dice que la liberó.
    assert c.subject == "[TitulaTec ITCJ] Tu encuesta de egresados quedó registrada como liberada"
    assert c.context["origin"] == "prior"
    assert "Tu encuesta de egresados del semestre anterior quedó registrada como liberada" in texto
    assert "Lleva tu constancia física a tu cita de cotejo" in texto
    assert "Gestión Tecnológica y Vinculación (GTV) liberó" not in texto
    assert "Para agendar te falta:" in texto


def test_revocar_una_previa_pide_contestar_la_encuesta(db_session, proceso):
    """Ruling R22 (I4): la revocación de una constancia previa BORRA la
    solicitud; el correo lo dice -tiene que contestar la encuesta de
    egresados en la plataforma-, lleva el motivo y la línea D12, y su botón
    lleva directo a la encuesta (no al tablero)."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso(fase=2)
    StudentMail.survey_result(db_session, proc, result="revoked",
                              reason="La constancia era de otro egresado.", origin="prior")

    c = _componer(db_session, proc)
    html = _html(c, estricto=True)
    texto = _texto(html)

    assert c.context["origin"] == "prior"
    assert c.link == _liga("/titulatec/encuesta-egresados")
    assert "revocó la liberación que se había registrado con tu constancia" in texto
    assert "contesta la encuesta de egresados en la plataforma" in texto
    assert "La constancia era de otro egresado." in texto
    assert D12_TEXTO in texto and f'href="{MAILTO_GTV}"' in html
    assert "Contestar la encuesta" in texto


def test_revocar_una_liberacion_normal_no_pide_contestar_otra_vez(db_session, proceso,
                                                                  make_survey_review):
    """Control: la revocación de una encuesta REAL (la respuesta sigue
    guardada) no le pide volver a contestarla y lleva al tablero."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso(fase=2)
    make_survey_review(proc, status="rejected")
    StudentMail.survey_result(db_session, proc, result="revoked", reason="Motivo")

    c = _componer(db_session, proc)
    texto = _texto(_html(c, estricto=True))

    assert c.link == _liga("/titulatec/student/dashboard?fase=2")
    assert "contesta la encuesta" not in texto
    assert "Ver mi proceso" in texto


def test_encuesta_que_ya_no_esta_liberada_es_obsoleta(db_session, proceso,
                                                     make_survey_review):
    """D11 se arma con el estado VIVO: si GTV la revocó dentro de la espera, el
    «liberó tu encuesta» ya es falso (y sale el correo de la revocación)."""
    from itcj2.apps.titulatec.services.mail_compose import Obsolete
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso(fase=2)
    make_survey_review(proc, status="rejected")
    StudentMail.survey_result(db_session, proc, result="approved")

    assert _componer(db_session, proc) == Obsolete("la encuesta ya no está liberada")


@pytest.mark.parametrize("fase, encuesta, esperado", [
    (1, "approved", ["que Servicios Escolares apruebe tus documentos iniciales"]),
    (1, None, ["que Servicios Escolares apruebe tus documentos iniciales",
               "enviar tu encuesta de egresados"]),
    (2, None, ["enviar tu encuesta de egresados"]),
    (2, "in_review", ["que Gestión Tecnológica y Vinculación (GTV) libere tu encuesta "
                      "de egresados (ya la enviaste; está en revisión)"]),
    (2, "rejected", ["atender las observaciones de Gestión Tecnológica y Vinculación "
                     "(GTV) a tu encuesta de egresados"]),
    (2, "approved", []),
    (3, "approved", None),
], ids=["fase-1-encuesta-liberada", "fase-1-sin-encuesta", "sin-encuesta",
        "encuesta-en-revision", "encuesta-con-observaciones", "todo-liberado",
        "cotejo-ya-aprobado"])
def test_no_adeudo_liberado_dice_que_falta(db_session, con_biblioteca, fase, encuesta,
                                          esperado):
    """D11 en `library_cleared`. El no adeudo se libera desde la fase 1 (D3):
    ahí todavía faltan los documentos iniciales, aunque la encuesta ya venga
    liberada (constancia previa, D9). Con la fase 2 aprobada ya no hay cita
    por agendar: ninguna de las dos frases."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = con_biblioteca(fase=fase, biblioteca="cleared", via="no_charge",
                          encuesta=encuesta)
    StudentMail.library_cleared(db_session, proc, via="no_charge")

    c = _componer(db_session, proc)
    texto = _texto(_html(c, estricto=True))

    assert c.context["falta"] == esperado
    assert (YA_PUEDES in texto) is (esperado == [])
    assert ("Para agendar te falta:" in texto) is bool(esperado)
    for frase in esperado or ():
        assert frase in texto


def _liberacion(db, proc, kind):
    """El correo de liberación `kind` tal como lo encola su transición."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    if kind == "library_cleared":
        assert StudentMail.library_cleared(db, proc, via="no_charge") is True
    else:
        assert StudentMail.survey_result(db, proc, result="approved") is True


@pytest.mark.parametrize("kind", ["library_cleared", "survey_approved"])
@pytest.mark.parametrize("cita", ["scheduled", "confirmed", "in_progress", "attended"])
def test_con_cita_vigente_no_dice_que_agende(db_session, con_biblioteca, make_appointment,
                                            kind, cita):
    """D11 no le dice «Ya puedes agendar» a quien YA tiene cita: D17 conserva
    las agendadas antes del candado (su no adeudo quedó `pending` en el
    backfill y Biblioteca/Caja lo liberan después) y una `attended` en la fase
    2 espera el dictamen (`cotejo_en_dictamen`; aquí sin fila de la fase 2 =
    sin veredicto, y con la fase `rejected` ver la prueba del Ruling R17). Ni
    «Ya puedes agendar» ni «Para agendar te falta»: es lectura de la cita
    vigente, no de una liberación (invariante 2)."""
    proc = con_biblioteca(biblioteca="cleared", via="no_charge", encuesta="approved")
    make_appointment(proc, status=cita)
    _liberacion(db_session, proc, kind)

    c = _componer(db_session, proc)
    texto = _texto(_html(c, estricto=True))

    assert c.context["falta"] is None
    assert YA_PUEDES not in texto
    assert "Para agendar te falta" not in texto


def _fase_2(db, proc, status):
    """La `ProcessPhase` de la fase 2 con `status` (`con_biblioteca` crea el
    proceso sin fases: `None` = sin fila, que también es «sin veredicto»)."""
    from itcj2.apps.titulatec.models import ProcessPhase

    if status is not None:
        db.add(ProcessPhase(process_id=proc.id, phase_number=2, status=status))
        db.flush()


@pytest.mark.parametrize("kind", ["library_cleared", "survey_approved"])
@pytest.mark.parametrize("fase2, agenda", [
    (None, False),               # sin veredicto (sin fila de la fase 2)
    ("in_progress", False),
    ("in_review", False),        # `cotejo_en_dictamen`
    ("rejected", True),          # le faltaron papeles: agenda otra
])
def test_atendida_solo_apaga_d11_mientras_la_fase_2_no_tiene_veredicto(
        db_session, con_biblioteca, make_appointment, kind, fase2, agenda):
    """Ruling R17: una cita vigente `attended` apaga D11 SOLO mientras la fase
    2 no tenga veredicto -el predicado `cotejo_en_dictamen` (D13 2026-09-30)
    de `SelfBookingService.eligibility`-. Con la fase 2 `rejected` tiene que
    agendar OTRA, así que la línea sigue al gate como siempre. Es el caso real
    de la transición: un D17 cuyo cotejo se rechazó por el no adeudo que le
    faltaba y que después paga en Caja."""
    proc = con_biblioteca(biblioteca="cleared", via="payment", encuesta="approved")
    _fase_2(db_session, proc, fase2)
    make_appointment(proc, status="attended")
    _liberacion(db_session, proc, kind)

    c = _componer(db_session, proc)
    texto = _texto(_html(c, estricto=True))

    if agenda:
        assert c.context["falta"] == []
        assert YA_PUEDES in texto
    else:
        assert c.context["falta"] is None
        assert YA_PUEDES not in texto and "Para agendar te falta" not in texto


def test_atendida_con_fase_2_rechazada_dice_lo_que_le_falta(db_session, con_biblioteca,
                                                           make_appointment):
    """Ruling R17, la otra cara: con la fase 2 `rejected` y una liberación
    todavía pendiente, «Para agendar te falta: …» como a cualquiera."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = con_biblioteca(biblioteca="pending", encuesta="approved")
    _fase_2(db_session, proc, "rejected")
    make_appointment(proc, status="attended")
    StudentMail.survey_result(db_session, proc, result="approved")

    c = _componer(db_session, proc)

    assert c.context["falta"] == [
        "que el Centro de Información revise tu no adeudo de biblioteca"]
    assert "Para agendar te falta:" in _texto(_html(c, estricto=True))


@pytest.mark.parametrize("kind", ["library_cleared", "survey_approved"])
@pytest.mark.parametrize("cita, vigente", [
    ("no_show", True),           # no se presentó: agenda una nueva
    ("cancelled", False),        # la cancelada deja de ser la vigente (D6)
    ("superseded", False),       # un intento viejo, ya reemplazado
])
def test_sin_cita_que_lo_ocupe_si_dice_que_agende(db_session, con_biblioteca,
                                                 make_appointment, kind, cita, vigente):
    """El control positivo: una cita que no lo ocupa no apaga D11."""
    proc = con_biblioteca(biblioteca="cleared", via="no_charge", encuesta="approved")
    make_appointment(proc, status=cita, is_current=vigente)
    _liberacion(db_session, proc, kind)

    c = _componer(db_session, proc)

    assert c.context["falta"] == []
    assert YA_PUEDES in _texto(_html(c, estricto=True))


def test_agenda_falla_cerrado_si_no_le_llega_falta():
    """Con el entorno REAL (no estricto) un `falta` ausente es `Undefined`, que
    no es `none`: sin la guarda, `m.agenda` pintaría «Ya puedes agendar».
    Falla cerrado: no pinta ninguna de las dos frases."""
    from itcj2.apps.titulatec.pages.nav import titulatec_templates

    html = titulatec_templates.get_template("titulatec/email/survey_result.html").render(
        first_name="ALUMNO", link="https://example.invalid/liga", result="approved",
        reason=None, origin="submission")
    texto = _texto(html)

    assert "liberó tu encuesta de egresados" in texto
    assert YA_PUEDES not in texto and "Para agendar te falta" not in texto


# ---------------------------------------------------------------------------
# No adeudo de biblioteca (spec 2026-10-01 §4.11): los cuatro correos
# ---------------------------------------------------------------------------
def test_pasa_a_caja_con_desglose_nota_e_informacion(db_session, con_biblioteca):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = con_biblioteca(biblioteca="awaiting_payment", library_note="Debe 2 libros",
                          info_html="<p>Caja abre de <strong>9:00 a 14:00</strong>.</p>")
    _pasa_a_caja(db_session, proc)

    c = _componer(db_session, proc)
    html = _html(c, estricto=True)
    texto = _texto(html)

    assert c.subject == "[TitulaTec ITCJ] Ya puedes pasar a Caja por tu no adeudo de biblioteca"
    assert c.template == "library_ready.html"
    assert c.link == _liga("/titulatec/student/dashboard?fase=2")
    assert (c.context["debt"], c.context["donation"], c.context["total"]) == (
        "$300.00", "$800.00", "$1,100.00")
    assert c.context["updated"] is False
    for frase in ("Adeudo con la biblioteca", "$300.00", "Donación voluntaria de libro",
                  "$800.00", "Total a pagar", "$1,100.00", "Debe 2 libros",
                  "con tu número de control", "no necesitas cita",
                  "Información para el alumno", "Caja abre de 9:00 a 14:00"):
        assert frase in texto, frase
    # El HTML de SE sale como HTML (ya sanitizado), no escapado.
    assert "<strong>9:00 a 14:00</strong>" in html
    # Con el candado de biblioteca, por qué conviene pagar pronto.
    assert "para agendar tu cita de cotejo" in texto


def test_pasa_a_caja_sin_adeudo_ni_nota_ni_informacion(db_session, con_biblioteca):
    """«Sin adeudo» (adeudo 0) igual pasa a Caja por la donación; sin nota ni
    información, esas secciones no se pintan (nunca un hueco ni «None»)."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = con_biblioteca(biblioteca="awaiting_payment", debt_amount=Decimal("0.00"),
                          total_amount=Decimal("800.00"))
    _pasa_a_caja(db_session, proc, debt=Decimal("0.00"), total=Decimal("800.00"))

    c = _componer(db_session, proc)
    texto = _texto(_html(c, estricto=True))

    assert c.context["debt"] == "$0.00" and c.context["note"] is None
    assert c.context["info_html"] is None
    assert "Sin adeudo" in texto and "$800.00" in texto
    assert "Nota de Biblioteca" not in texto and "Información para el alumno" not in texto


def test_pasa_a_caja_pinta_los_montos_vigentes(db_session, con_biblioteca):
    """D8: los montos se releen de la fila al ENVIAR, no del payload."""
    from itcj2.apps.titulatec.models import LibraryClearance

    proc = con_biblioteca(biblioteca="awaiting_payment")
    _pasa_a_caja(db_session, proc)
    fila = db_session.query(LibraryClearance).filter_by(process_id=proc.id).one()
    fila.debt_amount, fila.total_amount = Decimal("500.00"), Decimal("1300.00")
    db_session.flush()

    c = _componer(db_session, proc)

    assert (c.context["debt"], c.context["total"]) == ("$500.00", "$1,300.00")


def test_la_informacion_de_se_sale_sanitizada(db_session, con_biblioteca):
    """`info_html` se vuelve a sanitizar al pintar (un UPDATE a mano no inyecta)
    y sus ligas http/https quedan; un `javascript:` o un `<script>`, no."""
    proc = con_biblioteca(
        biblioteca="awaiting_payment",
        info_html=('<p onclick="x()">Ver <a href="https://example.invalid/caja">horario</a>'
                   '<script>alert(1)</script><a href="javascript:alert(2)">mal</a></p>'))
    _pasa_a_caja(db_session, proc)

    html = _html(_componer(db_session, proc), sin_autoescape=True)

    assert "<script" not in html and "alert(" not in html and "onclick" not in html
    assert 'href="https://example.invalid/caja"' in html
    assert "javascript:" not in html


def test_correccion_del_monto(db_session, con_biblioteca):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = con_biblioteca(biblioteca="awaiting_payment")
    _pasa_a_caja(db_session, proc)
    _ya_salio(db_session, proc.id)
    _pasa_a_caja(db_session, proc, updated=True)

    c = _componer(db_session, proc)

    assert c.subject == ("[TitulaTec ITCJ] Biblioteca corrigió el monto de tu no adeudo "
                         "de biblioteca")
    assert c.context["updated"] is True
    assert "corrigió el monto" in _texto(_html(c))


def test_dos_avisos_de_caja_seguidos_sale_solo_el_ultimo(db_session, con_biblioteca):
    """Registrar y corregir dentro de la espera del despachador: los dos pintan
    los montos VIGENTES, así que el viejo sobra. Y como el egresado nunca
    recibió el primero, el que sale no habla de una «corrección»."""
    from itcj2.apps.titulatec.services.mail_compose import Obsolete

    proc = con_biblioteca(biblioteca="awaiting_payment")
    _pasa_a_caja(db_session, proc)
    _pasa_a_caja(db_session, proc, updated=True)
    viejo, nuevo = _pendientes(db_session, proc.id)

    assert _componer(db_session, proc, [viejo]) == Obsolete(
        "hay un aviso más reciente del monto a pagar")
    c = _componer(db_session, proc, [nuevo])
    assert c.context["updated"] is False
    assert c.subject.endswith("Ya puedes pasar a Caja por tu no adeudo de biblioteca")


@pytest.mark.parametrize("biblioteca", ["pending", "cleared"])
def test_pasa_a_caja_obsoleto_si_ya_no_debe(db_session, con_biblioteca, biblioteca):
    """Pagó (o se liberó de otro modo, o se revirtió a Biblioteca) antes de que
    saliera el aviso: ya no hay nada que pagar en Caja."""
    from itcj2.apps.titulatec.models import LibraryClearance
    from itcj2.apps.titulatec.services.mail_compose import Obsolete

    proc = con_biblioteca(biblioteca="awaiting_payment")
    _pasa_a_caja(db_session, proc)
    fila = db_session.query(LibraryClearance).filter_by(process_id=proc.id).one()
    fila.status = biblioteca
    fila.cleared_via = "payment" if biblioteca == "cleared" else None
    db_session.flush()

    assert _componer(db_session, proc) == Obsolete("ya no tiene un pago pendiente en Caja")


def test_pasa_a_caja_obsoleto_si_la_fase_2_ya_se_aprobo(db_session, con_biblioteca):
    """Ruling R30 #4 (re-revisión de la ola final, ronda 2): la fase 2 se
    aprobó DURANTE la espera del despachador (p. ej. SE marcó el requisito a
    mano en la transición) -el dueño lo clasifica `NOT_APPLICABLE` (Ruling
    R21), aunque la fila SIGA `awaiting_payment`-: `payment_due` devuelve
    `None` también ahí, así que TitulaTec deja de perseguir el pago por
    correo con el MISMO `Obsolete` genérico de «ya no tiene un pago
    pendiente» -este módulo no pregunta nada aparte (invariante 2)-; Caja
    sigue pudiendo cobrarlo si el egresado se presenta, eso no lo valida
    este correo."""
    from itcj2.apps.titulatec.models import ProcessPhase
    from itcj2.apps.titulatec.services.mail_compose import Obsolete

    proc = con_biblioteca(biblioteca="awaiting_payment")
    _pasa_a_caja(db_session, proc)
    db_session.add(ProcessPhase(process_id=proc.id, phase_number=2, status="approved"))
    db_session.flush()

    assert _componer(db_session, proc) == Obsolete("ya no tiene un pago pendiente en Caja")


@pytest.mark.parametrize("via, frases", [
    ("payment", ["Caja (Recursos Financieros) registró tu pago de $1,100.00",
                 "no necesitas llevar nada"]),
    ("no_charge", ["registró que no tienes nada que pagar",
                   "no necesitas llevar nada"]),
    ("prior", ["Tu constancia de no adeudo previa quedó registrada",
               "Lleva tu constancia física a tu cita de cotejo"]),
])
def test_no_adeudo_liberado_por_cada_via(db_session, con_biblioteca, via, frases):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = con_biblioteca(biblioteca="cleared", via=via, encuesta="approved")
    StudentMail.library_cleared(db_session, proc, via=via)

    c = _componer(db_session, proc)
    texto = _texto(_html(c, estricto=True))

    assert c.subject == "[TitulaTec ITCJ] Tu no adeudo de biblioteca quedó liberado"
    assert c.template == "library_cleared.html"
    assert c.link == _liga("/titulatec/student/dashboard?fase=2")
    assert c.context["via"] == via
    for frase in frases:
        assert frase in texto, frase
    assert YA_PUEDES in texto
    assert ("constancia física" in texto) is (via == "prior")


def test_no_adeudo_liberado_que_se_revirtio_es_obsoleto(db_session, con_biblioteca):
    """Con el candado, el gate ve que el no adeudo volvió a faltar: «quedó
    liberado» ya es falso. Y como este aviso no sale, el de la reversión
    tampoco (E10): para el egresado nada cambió."""
    from itcj2.apps.titulatec.models import LibraryClearance
    from itcj2.apps.titulatec.services.mail_compose import Obsolete
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = con_biblioteca(biblioteca="cleared", via="no_charge", encuesta="approved")
    StudentMail.library_cleared(db_session, proc, via="no_charge")
    fila = db_session.query(LibraryClearance).filter_by(process_id=proc.id).one()
    fila.status, fila.cleared_via = "pending", None
    db_session.flush()

    assert _componer(db_session, proc) == Obsolete("el no adeudo ya no está liberado")


def test_no_adeudo_liberado_con_una_reversion_posterior_es_obsoleto_y_la_reversion_tambien(
        db_session, proceso, make_survey_review):
    """Liberar y revertir dentro de la misma espera del despachador: NO sale
    ninguno de los dos correos.

    El liberado, porque «quedó liberado» ya es falso (sin candado el gate no lo
    distingue -`not_required`-: lo delata la fila de la reversión encolada
    después). Y la reversión -esta aserción se INVIRTIÓ con E10 (spec
    2026-10-02 §2, m30); antes salía- porque el egresado nunca recibió el
    «quedó liberado» que ella desmiente: para él nada cambió, y «Se revirtió
    tu no adeudo…» sin un liberado previo es ruido (un «Deshacer» de
    Biblioteca) o, peor, falso (Caja se equivocó de renglón)."""
    from itcj2.apps.titulatec.services.mail_compose import Obsolete
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso(fase=2)
    make_survey_review(proc, status="approved")
    StudentMail.library_cleared(db_session, proc, via="no_charge")
    StudentMail.library_reverted(db_session, proc, reason="Sí debía un libro",
                                 to_status="pending")
    liberado, revertido = _pendientes(db_session, proc.id)

    assert _componer(db_session, proc, [liberado]) == Obsolete(
        "el no adeudo se revirtió después")
    assert _componer(db_session, proc, [revertido]) == Obsolete(
        "no salió el aviso de la liberación que revierte")


# E10 (spec 2026-10-02 §2, m30): la reversión sale SOLO si salió el liberado
# que revierte -el `library_cleared` más reciente del proceso encolado ANTES
# que ella-, en las dos ramas (a Caja y a Biblioteca).
_HACIA_Y_VIA = [("awaiting_payment", "payment"), ("pending", "no_charge")]
_NO_SALIO = "no salió el aviso de la liberación que revierte"


@pytest.mark.parametrize("hacia, via", _HACIA_Y_VIA)
def test_la_reversion_sale_si_el_egresado_recibio_el_liberado(db_session, con_biblioteca,
                                                              hacia, via):
    """El control positivo de E10: el «quedó liberado» SÍ le llegó, así que la
    reversión es la noticia que lo corrige y sale."""
    from itcj2.apps.titulatec.services.mail_compose import Composed
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = con_biblioteca(biblioteca=hacia)
    _liberado_que_salio(db_session, proc, via=via)
    StudentMail.library_reverted(db_session, proc, reason="Motivo", to_status=hacia)

    c = _componer(db_session, proc)

    assert isinstance(c, Composed), c
    assert c.template == "library_reverted.html"
    assert c.context["to_status"] == hacia


@pytest.mark.parametrize("hacia, via", _HACIA_Y_VIA)
@pytest.mark.parametrize("estado", ["pending", "obsolete", "failed", "no_recipient"])
def test_la_reversion_no_sale_si_el_liberado_no_salio(db_session, con_biblioteca, hacia,
                                                      via, estado):
    """El liberado que revierte sigue en cola (en la misma corrida el
    despachador lo vuelve obsoleto), ya se declaró obsoleto, se agotaron sus
    intentos o no tenía a quién mandarse: el egresado nunca lo leyó, así que
    la reversión tampoco sale (E10)."""
    from itcj2.apps.titulatec.services.mail_compose import Obsolete
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = con_biblioteca(biblioteca=hacia)
    assert StudentMail.library_cleared(db_session, proc, via=via) is True
    liberado = _pendientes(db_session, proc.id)[-1]
    liberado.status = estado
    db_session.flush()
    StudentMail.library_reverted(db_session, proc, reason="Motivo", to_status=hacia)
    revertido = [f for f in _pendientes(db_session, proc.id)
                 if f.kind == "library_reverted"]

    assert _componer(db_session, proc, revertido) == Obsolete(_NO_SALIO)


@pytest.mark.parametrize("hacia, via", _HACIA_Y_VIA)
def test_la_reversion_sin_ningun_liberado_previo_no_sale(db_session, con_biblioteca, hacia,
                                                         via):
    """Sin NINGÚN `library_cleared` antes (p. ej. un legado del backfill, o
    una liberación de cuando el correo estaba apagado), el egresado nunca
    recibió un «quedó liberado» por correo: la reversión tampoco sale. El
    liberado que SÍ salió de OTRO egresado no cuenta."""
    from itcj2.apps.titulatec.services.mail_compose import Obsolete
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    otro = con_biblioteca(biblioteca=hacia)
    _liberado_que_salio(db_session, otro, via=via)
    proc = con_biblioteca(biblioteca=hacia)
    StudentMail.library_reverted(db_session, proc, reason="Motivo", to_status=hacia)

    assert _componer(db_session, proc) == Obsolete(_NO_SALIO)


@pytest.mark.parametrize("primero_salio, sale", [
    (True, False),     # liberó (salió) → revirtió (salió) → liberó (no salió) → revierte
    (False, True),     # liberó y revirtió en la espera → liberó (salió) → revierte
], ids=["el-mas-reciente-no-salio", "el-mas-reciente-si-salio"])
def test_la_reversion_mira_el_liberado_mas_reciente_anterior(db_session, con_biblioteca,
                                                             primero_salio, sale):
    """La reversión desmiente el liberado MÁS RECIENTE encolado antes que ella,
    no uno viejo de un ciclo anterior: con dos vueltas liberar → revertir,
    decide el segundo liberado."""
    from itcj2.apps.titulatec.services.mail_compose import Composed, Obsolete
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = con_biblioteca(biblioteca="pending")

    def _vuelta(salio):
        StudentMail.library_cleared(db_session, proc, via="no_charge")
        StudentMail.library_reverted(db_session, proc, reason="Vuelta", to_status="pending")
        for fila in _pendientes(db_session, proc.id):
            fila.status = "sent" if salio else "obsolete"
        db_session.flush()

    _vuelta(primero_salio)
    assert StudentMail.library_cleared(db_session, proc, via="no_charge") is True
    segundo = _pendientes(db_session, proc.id)[-1]
    segundo.status = "obsolete" if primero_salio else "sent"
    db_session.flush()
    StudentMail.library_reverted(db_session, proc, reason="Otra vez", to_status="pending")

    c = _componer(db_session, proc)

    if sale:
        assert isinstance(c, Composed), c
        assert c.context["reason"] == "Otra vez"
    else:
        assert c == Obsolete(_NO_SALIO)


@pytest.mark.parametrize("hacia, frases", [
    ("awaiting_payment", ["Caja (Recursos Financieros) revirtió el registro de tu pago",
                          "Tu pago de $1,100.00 vuelve a quedar pendiente",
                          "con tu número de control"]),
    ("pending", ["Se revirtió la liberación de tu no adeudo de biblioteca",
                 "El Centro de Información volverá a revisar tu caso"]),
])
def test_reversion_con_motivo_y_que_sigue(db_session, con_biblioteca, hacia, frases):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = con_biblioteca(biblioteca=hacia)
    _liberado_que_salio(db_session, proc,
                        via="payment" if hacia == "awaiting_payment" else "no_charge")
    StudentMail.library_reverted(db_session, proc, reason="Pago duplicado", to_status=hacia)

    c = _componer(db_session, proc)
    texto = _texto(_html(c, estricto=True))

    assert c.subject == "[TitulaTec ITCJ] Se revirtió tu no adeudo de biblioteca"
    assert c.template == "library_reverted.html"
    assert c.context["to_status"] == hacia
    assert "Pago duplicado" in texto
    for frase in frases:
        assert frase in texto, frase


def test_reversion_a_biblioteca_obsoleta_con_el_cotejo_ya_aprobado(db_session, proceso):
    """m40 (spec 2026-10-02 §3.7): la rama `pending` también se re-valida
    contra la fase 2. El caso del triage: convocatoria SIN candado, Biblioteca
    revierte (a `pending`) y la fase 2 se aprueba por otra vía antes de que el
    despachador mande el correo. «El Centro de Información volverá a revisar
    tu caso» ya es falso -a quien pasó su cotejo Biblioteca ya no lo revisa,
    Ruling R20-: obsoleto, por el predicado del dueño
    (`LibraryClearanceService.reviewable`), sin comparar estados aquí."""
    from itcj2.apps.titulatec.models import LibraryClearance
    from itcj2.apps.titulatec.services.mail_compose import Composed, Obsolete
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso(fase=2)
    _liberado_que_salio(db_session, proc)
    fila = db_session.query(LibraryClearance).filter_by(process_id=proc.id).one()
    fila.status, fila.cleared_via = "pending", None
    db_session.flush()
    StudentMail.library_reverted(db_session, proc, reason="Sí debía un libro",
                                 to_status="pending")
    assert isinstance(_componer(db_session, proc), Composed), "antes, sí aplica"

    _fase_2(db_session, proc, "approved")

    assert _componer(db_session, proc) == Obsolete(
        "Biblioteca ya no revisará su caso: ya pasó su cotejo")


def test_reversion_a_caja_obsoleta_con_el_cotejo_ya_aprobado(db_session, con_biblioteca):
    """La otra rama, ya cubierta desde el Ruling R32 y sin prueba propia hasta
    ahora: con la fase 2 aprobada `payment_due` es `None` (Ruling R30 #4), así
    que la reversión a Caja sale obsoleta con el MISMO motivo que «ya no
    debe» -este módulo no pregunta nada aparte-."""
    from itcj2.apps.titulatec.services.mail_compose import Composed, Obsolete
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = con_biblioteca(biblioteca="awaiting_payment")
    _liberado_que_salio(db_session, proc, via="payment")
    StudentMail.library_reverted(db_session, proc, reason="Pago duplicado",
                                 to_status="awaiting_payment")
    assert isinstance(_componer(db_session, proc), Composed), "antes, sí aplica"

    _fase_2(db_session, proc, "approved")

    assert _componer(db_session, proc) == Obsolete("ya no tiene un pago pendiente en Caja")


def test_reversion_obsoleta_si_se_volvio_a_liberar(db_session, proceso):
    from itcj2.apps.titulatec.services.mail_compose import Obsolete
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso(fase=2)
    StudentMail.library_reverted(db_session, proc, reason="Error", to_status="pending")
    StudentMail.library_cleared(db_session, proc, via="prior")
    revertido, _liberado = _pendientes(db_session, proc.id)

    assert _componer(db_session, proc, [revertido]) == Obsolete(
        "el no adeudo se volvió a liberar")


def test_recordatorio_de_pago(db_session, con_biblioteca):
    """El monto viaja SOLO en `titulo` (asunto y título del aviso in-app):
    m31 quitó del contexto un `total` que la plantilla nunca pintaba. El
    contexto es exactamente el que documenta `library_reminder.html`."""
    proc = con_biblioteca(biblioteca="awaiting_payment")
    _recordatorio(db_session, "library_reminder", proc)

    c = _componer(db_session, proc)
    texto = _texto(_html(c, estricto=True))

    assert c.subject == "[TitulaTec ITCJ] Tienes pendiente tu pago de $1,100.00 en Caja"
    assert c.template == "library_reminder.html"
    assert c.link == _liga("/titulatec/student/dashboard?fase=2")
    assert set(c.context) == {"first_name", "link", "titulo", "library_required"}
    assert c.context["titulo"] == "Tienes pendiente tu pago de $1,100.00 en Caja"
    for frase in ("Tienes pendiente tu pago de $1,100.00 en Caja",
                  "con tu número de control", "no necesitas cita",
                  "para agendar tu cita de cotejo"):
        assert frase in texto, frase


def test_recordatorio_de_pago_sin_candado_no_habla_de_agendar(db_session, proceso):
    """Sin el requisito automático el no adeudo no bloquea el agendado: el
    recordatorio no puede decir que lo necesita para agendar (pero lo que
    Biblioteca mandó a Caja se sigue debiendo y sí se recuerda)."""
    from itcj2.apps.titulatec.models import LibraryClearance

    proc = proceso(fase=2)
    fila = db_session.query(LibraryClearance).filter_by(process_id=proc.id).one()
    fila.status, fila.cleared_via = "awaiting_payment", None
    fila.debt_amount, fila.donation_amount = Decimal("300.00"), Decimal("800.00")
    fila.total_amount = Decimal("1100.00")
    db_session.flush()
    _recordatorio(db_session, "library_reminder", proc)

    texto = _texto(_html(_componer(db_session, proc), estricto=True))

    assert "Tienes pendiente tu pago de $1,100.00 en Caja" in texto
    assert "agendar" not in texto


@pytest.mark.parametrize("caso, motivo", [
    ("pagado", "ya no tiene un pago pendiente en Caja"),
    ("proceso-en-pausa", "el proceso ya no está activo"),
    # Ruling R30 #4 (re-revisión de la ola final, ronda 2): la fase 2 se
    # aprobó durante la espera del despachador -el dueño lo clasifica
    # `NOT_APPLICABLE` (Ruling R21), aunque la fila SIGA `awaiting_payment`-:
    # `payment_due` devuelve `None` también ahí, MISMO motivo que «pagado»
    # (este módulo no pregunta nada aparte, invariante 2) aunque el camino
    # que lo produce sea otro.
    ("fase-2-aprobada", "ya no tiene un pago pendiente en Caja"),
])
def test_recordatorio_de_pago_obsoleto_al_enviar(db_session, con_biblioteca, caso, motivo):
    """D8: deja de salir en cuanto se libera, si el proceso ya no está activo,
    o si su fase 2 ya se aprobó."""
    from itcj2.apps.titulatec.models import LibraryClearance, ProcessPhase
    from itcj2.apps.titulatec.services.mail_compose import Composed, Obsolete

    proc = con_biblioteca(biblioteca="awaiting_payment")
    fila = _recordatorio(db_session, "library_reminder", proc)
    assert isinstance(_componer(db_session, proc, [fila]), Composed), "antes, sí aplica"

    if caso == "pagado":
        no_adeudo = db_session.query(LibraryClearance).filter_by(process_id=proc.id).one()
        no_adeudo.status, no_adeudo.cleared_via = "cleared", "payment"
    elif caso == "fase-2-aprobada":
        db_session.add(ProcessPhase(process_id=proc.id, phase_number=2, status="approved"))
    else:
        proc.status = "on_hold"
    db_session.flush()

    assert _componer(db_session, proc, [fila]) == Obsolete(motivo)


# ---------------------------------------------------------------------------
# #7 — grupo `cita:{pid}`, armado con la cita VIGENTE (Review Focus 5)
# ---------------------------------------------------------------------------
def test_cita_agendada_lleva_fecha_lugar_requisitos_y_confirmar(db_session, cita_esc, reloj):
    reloj(HOY_AGENDA)
    esc = cita_esc
    _requisito(db_session, esc["cohort"].id, "12 fotografías",
               hint="Tamaño credencial", orden=2)
    _requisito(db_session, esc["cohort"].id, "Actas de nacimiento", orden=1)
    _requisito(db_session, esc["cohort"].id, "Requisito retirado", orden=0, activo=False)
    _agendar(db_session, esc)

    c = _componer(db_session, esc["p1"])

    assert c.subject == "[TitulaTec ITCJ] Tu cita de cotejo: 7 de mayo a las 09:00"
    assert c.template == "appt_changed.html"
    assert c.link == _liga("/titulatec/student/cita")
    assert c.context["changed"] is False
    assert (c.context["fecha"], c.context["hora"], c.context["lugar"]) == (
        "lunes 7 de mayo de 2029", "09:00", "Ventanilla 3")
    assert c.context["confirmar"] is True
    assert c.context["requisitos"] == [
        {"label": "Actas de nacimiento", "hint": None},
        {"label": "12 fotografías", "hint": "Tamaño credencial"},
    ]
    html = _html(c)
    assert "Confirma tu asistencia" in html
    assert "Ventanilla 3" in html and "Tamaño credencial" in html
    assert "Requisito retirado" not in html


def test_cita_confirmada_ya_no_pide_confirmar(db_session, cita_esc):
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    appt = _agendar(db_session, cita_esc)
    AppointmentService.confirm(db_session, appt, cita_esc["p1"].student_id)

    c = _componer(db_session, cita_esc["p1"])

    assert c.context["confirmar"] is False
    assert "Confirma tu asistencia" not in _html(c)


def test_cita_rafaga_un_solo_correo_con_la_fecha_final(db_session, cita_esc):
    """El alumno ya conocía su cita (ese correo salió) y el encargado la mueve
    dos veces dentro de la espera: UN correo «Cambió…», con la fecha de la
    cita vigente y no con la de cada fila (D7)."""
    esc = cita_esc
    conocida = _agendar(db_session, esc, slot=time(9, 0))
    _ya_salio(db_session, esc["p1"].id)
    segunda = _mover(db_session, esc, conocida, time(9, 30))
    _mover(db_session, esc, segunda, time(10, 0))
    filas = _pendientes(db_session, esc["p1"].id)
    assert _eventos(filas) == ["rescheduled", "rescheduled"]

    c = _componer(db_session, esc["p1"], filas)

    assert c.subject == "[TitulaTec ITCJ] Cambió tu cita de cotejo: 7 de mayo a las 10:00"
    assert c.template == "appt_changed.html"
    assert (c.context["hora"], c.context["changed"]) == ("10:00", True)
    html = _html(c)
    assert "10:00" in html
    assert "09:00" not in html and "09:30" not in html


def test_rafaga_que_empieza_en_creacion_dice_tu_cita(db_session, cita_esc):
    """Agendar → mover → mover dentro de la espera: para el alumno es la PRIMERA
    noticia de su cita, así que el correo no dice «Cambió…» aunque haya
    `rescheduled` en el grupo; es un solo correo con la fecha final (ruling 3,
    2026-09-29)."""
    esc = cita_esc
    primera = _agendar(db_session, esc, slot=time(9, 0))
    segunda = _mover(db_session, esc, primera, time(9, 30))
    _mover(db_session, esc, segunda, time(10, 0))
    filas = _pendientes(db_session, esc["p1"].id)
    assert _eventos(filas) == ["scheduled", "rescheduled", "rescheduled"]

    c = _componer(db_session, esc["p1"], filas)

    assert c.subject == "[TitulaTec ITCJ] Tu cita de cotejo: 7 de mayo a las 10:00"
    assert c.template == "appt_changed.html"
    assert (c.context["hora"], c.context["changed"]) == ("10:00", False)
    html = _html(c)
    assert "cambió" not in html.lower()          # ni en el título ni en el cuerpo
    assert "10:00" in html
    assert "09:00" not in html and "09:30" not in html


def test_cita_que_agendo_el_alumno_y_movio_el_encargado_dice_cambio(db_session, cita_esc):
    """B5 (refina el ruling 3): la ráfaga empieza con la creación POR EL ALUMNO
    (auto-agendado: ya conocía la fecha, lo que le llega es su comprobante). Si
    el encargado se la mueve dentro de la espera, el asunto es «Cambió…». Solo
    la creación por el ENCARGADO es la primera noticia de la cita."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    esc = cita_esc
    propia = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                       slot_start=time(9, 0),
                                       created_by_id=esc["p1"].student_id,
                                       location="Ventanilla 3")
    _mover(db_session, esc, propia, time(10, 0))
    filas = _pendientes(db_session, esc["p1"].id)
    assert [(f.payload["event"], f.payload["by"]) for f in filas] == [
        ("scheduled", "student"), ("rescheduled", "officer")]

    c = _componer(db_session, esc["p1"], filas)

    assert c.subject == "[TitulaTec ITCJ] Cambió tu cita de cotejo: 7 de mayo a las 10:00"
    assert (c.context["hora"], c.context["changed"]) == ("10:00", True)


def test_cita_que_agendo_el_alumno_sin_cambios_es_su_comprobante(db_session, cita_esc):
    """Sin `rescheduled` no hubo cambio: la cita que agendó él mismo sale como
    «Tu cita de cotejo: …» (comprobante, D9)."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    esc = cita_esc
    AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                              slot_start=time(9, 0), created_by_id=esc["p1"].student_id,
                              location="Ventanilla 3")

    c = _componer(db_session, esc["p1"])

    assert c.subject == "[TitulaTec ITCJ] Tu cita de cotejo: 7 de mayo a las 09:00"
    assert c.context["changed"] is False


def test_cita_sin_horario_lleva_el_rango_en_asunto_y_datos(db_session, walkin_esc, reloj):
    """Asunto walkin (D11, spec §6): «Tu cita de cotejo: 07 de mayo, de 08:00 a
    14:00» — día con cero, sin año, coma antes del rango. El contexto trae
    `sin_horario` para que `datos_cita` rotule «Horario»."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    reloj(HOY_AGENDA)
    esc = walkin_esc
    AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                              slot_start=esc["w"].start_time, created_by_id=esc["off"].id,
                              location="Sala de cotejo")

    c = _componer(db_session, esc["p1"])

    assert c.subject == "[TitulaTec ITCJ] Tu cita de cotejo: 07 de mayo, de 08:00 a 14:00"
    assert c.context["sin_horario"] is True
    assert (c.context["fecha"], c.context["hora"]) == (
        "lunes 7 de mayo de 2029", "de 08:00 a 14:00")
    html = _html(c, estricto=True)
    assert ">Horario<" in html
    assert ">Hora<" not in html


@pytest.mark.parametrize("mover", [False, True], ids=["agendar-cancelar",
                                                     "agendar-mover-cancelar"])
def test_cita_agendada_y_cancelada_es_neto_cero(db_session, cita_esc, mover):
    """El alumno nunca supo de esa cita: no hay nada que avisarle."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.mail_compose import Obsolete

    esc = cita_esc
    appt = _agendar(db_session, esc)
    if mover:
        appt = _mover(db_session, esc, appt, time(10, 30))
    AppointmentService.cancel(db_session, appt, esc["off"].id, "Se agendó por error")
    filas = _pendientes(db_session, esc["p1"].id)
    assert _eventos(filas)[0] == "scheduled" and _eventos(filas)[-1] == "cancelled"

    assert _componer(db_session, esc["p1"], filas) == Obsolete(
        "agendada y cancelada dentro de la espera")


@pytest.mark.parametrize("mover", [False, True], ids=["cancelada",
                                                     "reagendada-y-cancelada"])
def test_cita_cancelada_que_ya_conocia_manda_cancelacion(db_session, cita_esc, mover, reloj):
    """Su cita ya le había llegado por correo (esa fila salió); ahora el
    encargado se la cancela, con o sin moverla antes: aviso con el motivo."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    reloj(HOY_AGENDA)
    esc = cita_esc
    appt = _agendar(db_session, esc)
    _ya_salio(db_session, esc["p1"].id)
    if mover:
        appt = _mover(db_session, esc, appt, time(10, 30))
    AppointmentService.cancel(db_session, appt, esc["off"].id,
                              "El encargado no estará ese día")
    filas = _pendientes(db_session, esc["p1"].id)
    assert _eventos(filas) == (["rescheduled"] if mover else []) + ["cancelled"]

    c = _componer(db_session, esc["p1"], filas)

    assert c.subject == "[TitulaTec ITCJ] Tu cita de cotejo fue cancelada"
    assert c.template == "appt_cancelled.html"
    assert c.link == _liga("/titulatec/student/cita")
    assert c.context["reason"] == "El encargado no estará ese día"
    assert (c.context["fecha"], c.context["hora"]) == (
        "lunes 7 de mayo de 2029", "10:30" if mover else "09:00")
    assert "El encargado no estará ese día" in _html(c)


def test_cita_cancelada_dos_veces_usa_la_ultima_cancelacion(db_session, cita_esc):
    """Le cancelaron la que conocía, le agendaron otra y también se la
    cancelaron, todo dentro de la espera: el motivo es el de la ÚLTIMA."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    esc = cita_esc
    conocida = _agendar(db_session, esc)
    _ya_salio(db_session, esc["p1"].id)
    AppointmentService.cancel(db_session, conocida, esc["off"].id, "Primer motivo")
    otra = _agendar(db_session, esc, slot=time(9, 30))
    AppointmentService.cancel(db_session, otra, esc["off"].id, "Segundo motivo")
    filas = _pendientes(db_session, esc["p1"].id)
    assert _eventos(filas) == ["cancelled", "scheduled", "cancelled"]

    c = _componer(db_session, esc["p1"], filas)

    assert c.template == "appt_cancelled.html"
    assert (c.context["reason"], c.context["hora"]) == ("Segundo motivo", "09:30")


def test_cita_cancelada_sin_horario_lleva_el_rango(db_session, walkin_esc, reloj):
    """Aclaración del controlador: el correo de cancelación resuelve la cita
    por `appt_id` (no por la fecha cruda del payload), así que también sabe
    si era sin horario."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    reloj(HOY_AGENDA)
    esc = walkin_esc
    appt = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                     slot_start=esc["w"].start_time,
                                     created_by_id=esc["off"].id)
    _ya_salio(db_session, esc["p1"].id)
    AppointmentService.cancel(db_session, appt, esc["off"].id, "Ya no hay lugar")

    c = _componer(db_session, esc["p1"])

    assert c.template == "appt_cancelled.html"
    assert c.context["sin_horario"] is True
    assert (c.context["fecha"], c.context["hora"]) == (
        "lunes 7 de mayo de 2029", "de 08:00 a 14:00")
    html = _html(c)
    assert "(de 08:00 a 14:00, por orden de llegada)" in html
    assert "a las de 08:00" not in html


def test_cita_cancelada_con_appt_id_ilocalizable_usa_el_formato_del_payload(
        db_session, walkin_esc, reloj):
    """Si `db.get(ReviewAppointment, appt_id)` no encuentra la fila (dato
    corrupto, caso límite), se cae al formato normal con la fecha cruda del
    payload — sin `sin_horario`, porque sin la ventana no hay forma de
    saberlo (aclaración del controlador)."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    reloj(HOY_AGENDA)
    esc = walkin_esc
    appt = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                     slot_start=esc["w"].start_time,
                                     created_by_id=esc["off"].id)
    _ya_salio(db_session, esc["p1"].id)
    AppointmentService.cancel(db_session, appt, esc["off"].id, "Motivo")
    (fila,) = [f for f in _pendientes(db_session, esc["p1"].id)
              if f.payload.get("event") == "cancelled"]
    fila.payload = {**fila.payload, "appt_id": 999999}
    db_session.flush()

    c = _componer(db_session, esc["p1"], [fila])

    assert c.context["sin_horario"] is False
    assert (c.context["fecha"], c.context["hora"]) == (
        "lunes 7 de mayo de 2029", "08:00")


def test_cita_cancelada_por_el_propio_alumno_tras_reagendar_es_obsoleta(
        db_session, cita_esc):
    """Grupo = [rescheduled] y ya sin cita activa: la canceló el propio alumno
    (o la revocación), vías que no encolan. No hay qué avisar: ni la fecha
    nueva, que ya no existe, ni una cancelación que él mismo hizo (ruling
    2026-09-29)."""
    from itcj2.apps.titulatec.services.mail_compose import Obsolete
    from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

    esc = cita_esc
    appt = _agendar(db_session, esc)
    _ya_salio(db_session, esc["p1"].id)
    nueva = _mover(db_session, esc, appt, time(10, 0))
    SelfBookingService.cancel(db_session, nueva, esc["p1"].student_id, "Ya no puedo ir")
    filas = _pendientes(db_session, esc["p1"].id)
    assert _eventos(filas) == ["rescheduled"]      # su propia cancelación no encoló

    assert _componer(db_session, esc["p1"], filas) == Obsolete(
        "la cita se canceló por una vía sin correo")


def test_cita_en_cotejo_es_obsoleta(db_session, cita_esc):
    """El alumno ya está en la ventanilla: avisarle fecha y lugar no sirve."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.mail_compose import Obsolete

    appt = _agendar(db_session, cita_esc)
    AppointmentService.start(db_session, appt, cita_esc["off"].id)

    assert _componer(db_session, cita_esc["p1"]) == Obsolete(
        "la cita vigente ya está en cotejo")


@pytest.mark.parametrize("estado", ["attended", "no_show"])
def test_cita_vigente_ya_cerrada_es_obsoleta(db_session, proceso, make_appointment,
                                             estado):
    from itcj2.apps.titulatec.services.mail_compose import Obsolete
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso(fase=2)
    appt = make_appointment(proc, status=estado)
    StudentMail.appointment_changed(db_session, proc, event="scheduled", appt=appt,
                                    by="officer")

    resultado = _componer(db_session, proc)

    assert isinstance(resultado, Obsolete)
    assert resultado.reason.startswith("la cita vigente ya está")


def test_requisitos_no_siembran(db_session, cita_esc, monkeypatch):
    """La convocatoria no tiene requisitos: el correo sale sin «qué llevar» y la
    tabla sigue vacía. `RequirementService.list_with_status` y
    `CotejoRequirementService.list_or_seed` siembran Y commitean; componer es
    solo lectura, así que aquí sembrar o commitear revienta la prueba."""
    from itcj2.apps.titulatec.models import CotejoRequirement
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )

    esc = cita_esc
    _agendar(db_session, esc)
    total = db_session.query(CotejoRequirement).count()

    def _prohibido(*_a, **_k):
        raise AssertionError("componer un correo no siembra ni commitea")

    monkeypatch.setattr(db_session, "commit", _prohibido)
    monkeypatch.setattr(CotejoRequirementService, "seed_defaults",
                        staticmethod(_prohibido))

    c = _componer(db_session, esc["p1"])

    assert c.context["requisitos"] == []
    assert (db_session.query(CotejoRequirement)
            .filter_by(cohort_id=esc["cohort"].id).count()) == 0
    assert db_session.query(CotejoRequirement).count() == total
    assert "Qué llevar" not in _html(c)


# ---------------------------------------------------------------------------
# #9 — «no se presentó», re-validado al enviar (D8)
# ---------------------------------------------------------------------------
def test_no_show_avisa_con_la_fecha_de_la_cita(db_session, cita_esc, reloj):
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    reloj(HOY_AGENDA)
    esc = cita_esc
    appt = _agendar(db_session, esc)
    _ya_salio(db_session, esc["p1"].id)
    AppointmentService.mark_no_show(db_session, appt, esc["off"].id)

    c = _componer(db_session, esc["p1"])

    assert c.subject == "[TitulaTec ITCJ] No registramos tu asistencia a tu cita de cotejo"
    assert c.template == "appt_no_show.html"
    assert c.link == _liga("/titulatec/student/cita")
    assert (c.context["fecha"], c.context["hora"]) == ("lunes 7 de mayo de 2029", "09:00")


def test_no_show_deshecho_es_obsoleto(db_session, cita_esc):
    """El encargado lo corrigió dentro de la gracia: el correo no sale."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.mail_compose import Obsolete

    esc = cita_esc
    appt = _agendar(db_session, esc)
    _ya_salio(db_session, esc["p1"].id)
    AppointmentService.mark_no_show(db_session, appt, esc["off"].id)
    AppointmentService.undo_no_show(db_session, appt, esc["off"].id)

    assert _componer(db_session, esc["p1"]) == Obsolete("se corrigió la asistencia")


def test_no_show_duplicado_solo_sale_el_mas_reciente(db_session, cita_esc):
    """Marcar → deshacer → marcar dentro de la espera deja dos filas de la
    MISMA cita: la vieja queda obsoleta y sale solo la nueva (ruling
    2026-09-29)."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.mail_compose import Composed, Obsolete

    esc = cita_esc
    appt = _agendar(db_session, esc)
    _ya_salio(db_session, esc["p1"].id)
    AppointmentService.mark_no_show(db_session, appt, esc["off"].id)
    AppointmentService.undo_no_show(db_session, appt, esc["off"].id)
    AppointmentService.mark_no_show(db_session, appt, esc["off"].id)
    vieja, nueva = _pendientes(db_session, esc["p1"].id)
    assert vieja.payload["appt_id"] == nueva.payload["appt_id"] == appt.id

    assert _componer(db_session, esc["p1"], [vieja]) == Obsolete(
        "hay un aviso más reciente de la misma cita")
    c = _componer(db_session, esc["p1"], [nueva])
    assert isinstance(c, Composed)
    assert c.template == "appt_no_show.html"


def test_no_show_con_una_cita_nueva_ya_agendada_es_obsoleto(db_session, cita_esc):
    """B3: el encargado marcó «no se presentó» y, dentro de la gracia, ya le
    agendaron otra cita (o la agendó él). La del aviso sigue `no_show` pero ya
    no es la VIGENTE: «Agenda una nueva» sería falso, no sale."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.mail_compose import Obsolete

    esc = cita_esc
    appt = _agendar(db_session, esc)
    _ya_salio(db_session, esc["p1"].id)
    AppointmentService.mark_no_show(db_session, appt, esc["off"].id)
    nueva = _agendar(db_session, esc, slot=time(10, 0))
    db_session.flush()
    assert (appt.status, appt.is_current, nueva.is_current) == ("no_show", False, True)
    (aviso,) = [f for f in _pendientes(db_session, esc["p1"].id) if f.kind == "appt_no_show"]

    assert _componer(db_session, esc["p1"], [aviso]) == Obsolete("ya hay una cita nueva")


def test_no_show_de_otra_cita_no_lo_vuelve_obsoleto(db_session, proceso,
                                                    make_appointment):
    """La regla «hay un aviso más reciente» es de la MISMA cita (`appt_id`): un
    aviso más reciente de OTRO intento no vuelve obsoleto el de la cita
    vigente, que sigue siendo verdad y sale.

    B3 (ronda final) cambió la otra mitad de lo que esta prueba afirmaba antes:
    el aviso de un intento que YA NO es el vigente no sale («ya hay una cita
    nueva»), así que aquí la cita del aviso que sale es la vigente."""
    from itcj2.apps.titulatec.services.mail_compose import Composed, Obsolete
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso(fase=2)
    vieja = make_appointment(proc, status="no_show", is_current=False, attempt_no=1)
    vigente = make_appointment(proc, status="no_show", attempt_no=2)
    StudentMail.appointment_no_show(db_session, proc, appt=vigente)
    StudentMail.appointment_no_show(db_session, proc, appt=vieja)   # más reciente, OTRO intento
    de_la_vigente, de_la_vieja = _pendientes(db_session, proc.id)

    assert isinstance(_componer(db_session, proc, [de_la_vigente]), Composed)
    assert _componer(db_session, proc, [de_la_vieja]) == Obsolete("ya hay una cita nueva")


def test_no_show_sin_horario_lleva_el_rango(db_session, walkin_esc, make_appointment, reloj):
    """D11: la re-validación al enviar sigue usando la cita real (`appt_id`),
    así que también hereda su variante sin horario."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    reloj(HOY_AGENDA)
    esc = walkin_esc
    appt = _walkin_appt(db_session, esc, make_appointment, status="no_show")
    StudentMail.appointment_no_show(db_session, esc["p1"], appt=appt)

    c = _componer(db_session, esc["p1"])

    assert c.context["sin_horario"] is True
    assert (c.context["fecha"], c.context["hora"]) == (
        "lunes 7 de mayo de 2029", "de 08:00 a 14:00")
    html = _html(c)
    assert "(de 08:00 a 14:00, por orden de llegada)" in html


# ---------------------------------------------------------------------------
# #8 / #10 / #11 — recordatorios del barrido diario, re-validados al enviar (D8)
# ---------------------------------------------------------------------------
def test_recordatorio_de_cita_con_datos_requisitos_y_confirmar(db_session, proceso,
                                                              make_appointment, reloj):
    """«Mañana es tu cita de cotejo» + fecha, hora, lugar, qué llevar (lectura no
    sembradora, como #7) y «confirma tu asistencia» si no la confirmó."""
    reloj()
    proc = proceso(fase=2)
    appt = make_appointment(proc, when=CITA_MANANA, location="Ventanilla 3")
    _requisito(db_session, proc.cohort_id, "12 fotografías", hint="Tamaño credencial",
               orden=2)
    _requisito(db_session, proc.cohort_id, "Actas de nacimiento", orden=1)
    _requisito(db_session, proc.cohort_id, "Requisito retirado", orden=0, activo=False)
    _recordatorio(db_session, "appt_reminder", proc, appt)

    c = _componer(db_session, proc)

    assert c.subject == "[TitulaTec ITCJ] Mañana es tu cita de cotejo"
    assert c.template == "appt_reminder.html"
    assert c.link == _liga("/titulatec/student/cita")
    assert (c.context["fecha"], c.context["hora"], c.context["lugar"]) == (
        "martes 11 de marzo", "10:30", "Ventanilla 3")
    assert c.context["confirmar"] is True
    assert c.context["requisitos"] == [
        {"label": "Actas de nacimiento", "hint": None},
        {"label": "12 fotografías", "hint": "Tamaño credencial"},
    ]
    html = _html(c)
    assert "Mañana es tu cita de cotejo" in html
    assert "Confirma tu asistencia" in html
    assert "Ventanilla 3" in html and "Tamaño credencial" in html
    assert "Requisito retirado" not in html


def test_recordatorio_de_cita_confirmada_ya_no_pide_confirmar(db_session, proceso,
                                                             make_appointment, reloj):
    reloj()
    proc = proceso(fase=2)
    appt = make_appointment(proc, when=CITA_MANANA, status="confirmed")
    appt.confirmed_at = HOY_FIJO - timedelta(days=2)
    _recordatorio(db_session, "appt_reminder", proc, appt)

    c = _componer(db_session, proc)

    assert c.context["confirmar"] is False
    assert "Confirma tu asistencia" not in _html(c)


@pytest.mark.parametrize("cuando, asunto", [
    (CITA_MANANA, "Mañana es tu cita de cotejo"),
    (CITA_MANANA + timedelta(days=1), "Tu cita de cotejo es en 2 días"),
    (HOY_FIJO + timedelta(hours=3), "Hoy es tu cita de cotejo"),
], ids=["manana", "en-2-dias", "hoy"])
def test_recordatorio_de_cita_dice_cuando_de_verdad(db_session, proceso, make_appointment,
                                                   reloj, cuando, asunto):
    """«Mañana» solo si la cita es mañana al ENVIAR: el setting admite hasta 7
    días antes, y un correo reintentado puede salir ya el día de la cita."""
    reloj()
    proc = proceso(fase=2)
    _recordatorio(db_session, "appt_reminder", proc, make_appointment(proc, when=cuando))

    c = _componer(db_session, proc)

    assert c.subject == "[TitulaTec ITCJ] " + asunto
    assert asunto in _html(c)


def test_recordatorio_sin_horario_lleva_el_rango(db_session, walkin_esc, make_appointment,
                                                 reloj):
    reloj(HOY_AGENDA)
    esc = walkin_esc
    appt = _walkin_appt(db_session, esc, make_appointment)
    _recordatorio(db_session, "appt_reminder", esc["p1"], appt)

    c = _componer(db_session, esc["p1"])

    assert c.context["sin_horario"] is True
    assert (c.context["fecha"], c.context["hora"]) == (
        "lunes 7 de mayo de 2029", "de 08:00 a 14:00")


@pytest.mark.parametrize("docs, asunto, faltantes, por_corregir", [
    ({}, "Te faltan documentos por subir",
     ["Acta de nacimiento", "Certificado de bachillerato", "CURP certificada"], []),
    ({"birth_certificate": "approved", "high_school_cert": "pending", "curp": "rejected"},
     "Te faltan documentos por corregir", [], ["CURP certificada"]),
    ({"birth_certificate": "rejected", "curp": "pending"},
     "Te faltan documentos por subir", ["Certificado de bachillerato"],
     ["Acta de nacimiento"]),
], ids=["faltan-los-3", "solo-por-corregir", "falta-y-por-corregir"])
def test_recordatorio_de_documentos_por_nombre(db_session, proceso, seed_document_types,
                                              make_document, docs, asunto, faltantes,
                                              por_corregir):
    seed_document_types()
    proc = proceso(fase=1)
    for code, estado in docs.items():
        make_document(proc, type_code=code, review_status=estado)
    _recordatorio(db_session, "docs_reminder", proc)

    c = _componer(db_session, proc)

    assert c.subject == "[TitulaTec ITCJ] " + asunto
    assert c.template == "docs_reminder.html"
    assert c.link == _liga("/titulatec/student/documents")
    assert (c.context["faltantes"], c.context["por_corregir"]) == (faltantes, por_corregir)
    html = _html(c)
    for nombre in faltantes + por_corregir:
        assert nombre in html


def test_recordatorio_de_documentos_con_el_estado_actual(db_session, proceso,
                                                         seed_document_types,
                                                         make_document):
    """Encolado cuando faltaban los 3; al enviar ya subió dos: el correo nombra
    solo el que falta HOY (el payload no trae nombres, a propósito)."""
    seed_document_types()
    proc = proceso(fase=1)
    fila = _recordatorio(db_session, "docs_reminder", proc)
    make_document(proc, type_code="birth_certificate")
    make_document(proc, type_code="curp")
    db_session.flush()

    c = _componer(db_session, proc, [fila])

    assert c.context["faltantes"] == ["Certificado de bachillerato"]
    assert c.context["por_corregir"] == []
    html = _html(c)
    assert "Acta de nacimiento" not in html and "CURP certificada" not in html


def test_recordatorio_de_encuesta(db_session, proceso):
    proc = proceso(fase=2)
    _recordatorio(db_session, "survey_reminder", proc)

    c = _componer(db_session, proc)

    assert c.subject == "[TitulaTec ITCJ] Llena tu encuesta de egresados"
    assert c.template == "survey_reminder.html"
    assert c.link == _liga("/titulatec/encuesta-egresados")
    assert "sin ella no puedes agendar tu cita de cotejo" in _html(c)
    # Sin candado de biblioteca no se le pide el no adeudo (invariante 8).
    assert c.context["library_required"] is False
    assert "no adeudo" not in _texto(_html(c))


def test_recordatorio_de_encuesta_con_candado_pide_tambien_el_no_adeudo(
        db_session, con_biblioteca):
    """Spec 2026-10-01 §4.11: «en cuanto GTV la libere y tengas tu no adeudo,
    podrás agendar» (donde la convocatoria lo exige)."""
    proc = con_biblioteca(biblioteca="pending")
    _recordatorio(db_session, "survey_reminder", proc)

    c = _componer(db_session, proc)
    texto = _texto(_html(c, estricto=True))

    assert c.context["library_required"] is True
    assert "en cuanto GTV la libere y tengas tu no adeudo, podrás agendar" in texto


_KIND_DE = {"cita": "appt_reminder", "documentos": "docs_reminder",
            "encuesta": "survey_reminder"}


@pytest.mark.parametrize("caso, motivo", [
    ("cita-cancelada", "la cita ya no es la vigente"),
    ("cita-movida", "la cita ya no es la vigente"),
    ("cita-a-otra-hora", "la cita cambió de fecha"),
    ("cita-en-cotejo", "la cita ya está en cotejo"),
    ("cita-ya-paso", "la cita ya pasó"),
    ("cita-proceso-en-pausa", "el proceso ya no está activo"),
    ("documentos-completos", "ya no le faltan documentos ni tiene por corregir"),
    ("documentos-fase-aprobada", "ya no está en la fase de documentos"),
    ("documentos-proceso-en-pausa", "el proceso ya no está activo"),
    ("encuesta-enviada", "ya envió la encuesta de egresados"),
    ("encuesta-fase-aprobada", "ya no está en la fase de la cita de cotejo"),
    ("encuesta-proceso-en-pausa", "el proceso ya no está activo"),
])
def test_recordatorio_obsoleto_al_enviar(db_session, proceso, seed_document_types,
                                         make_appointment, make_document,
                                         make_survey_review, reloj, caso, motivo):
    """D8: el recordatorio se encoló cuando aplicaba (compone bien), pero al
    ENVIAR ya no: sale `Obsolete` con un motivo legible (va a `last_error`)."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.mail_compose import Composed, Obsolete

    seed_document_types()
    reloj()
    kind = _KIND_DE[caso.split("-")[0]]
    proc = proceso(fase=1 if kind == "docs_reminder" else 2)
    appt = make_appointment(proc, when=CITA_MANANA) if kind == "appt_reminder" else None
    fila = _recordatorio(db_session, kind, proc, appt)
    assert isinstance(_componer(db_session, proc, [fila]), Composed), "antes, sí aplica"

    if caso == "cita-cancelada":
        AppointmentService.cancel(db_session, appt, proc.student_id, "Ya no puedo ir")
    elif caso == "cita-movida":             # `reschedule`: otra fila pasa a ser la vigente
        appt.status, appt.is_current = "superseded", False
        db_session.flush()
        make_appointment(proc, when=CITA_MANANA + timedelta(days=2), attempt_no=2)
    elif caso == "cita-a-otra-hora":
        appt.scheduled_at = CITA_MANANA + timedelta(hours=2)
    elif caso == "cita-en-cotejo":
        appt.status = "in_progress"
    elif caso == "cita-ya-paso":
        reloj(CITA_MANANA + timedelta(minutes=1))
    elif caso.endswith("proceso-en-pausa"):
        proc.status = "on_hold"
    elif caso == "documentos-completos":
        for code in _NOMBRES:
            make_document(proc, type_code=code)
    elif caso == "documentos-fase-aprobada" or caso == "encuesta-fase-aprobada":
        proc.current_phase += 1
    elif caso == "encuesta-enviada":
        make_survey_review(proc)
    db_session.flush()

    assert _componer(db_session, proc, [fila]) == Obsolete(motivo)


# ---------------------------------------------------------------------------
# Review Focus 2 — el texto libre sale escapado
# ---------------------------------------------------------------------------
def test_texto_libre_sale_escapado(db_session, proceso, cita_esc, make_appointment,
                                  con_biblioteca, reloj):
    """Los motivos los escribe el personal y el nombre lo tecleó un formulario
    público: en un correo HTML eso es inyección. Sale escapado, nunca como
    HTML. El lugar de la cita también lo teclea el personal (recordatorio #8),
    igual que la nota de Biblioteca y el motivo de una reversión del no
    adeudo."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    correos = {}
    p = proceso(first_name=MALICIOSO)
    _dictamen(db_session, p, "curp", "rejected", note=MALICIOSO)
    correos["rechazo de documento"] = _componer(db_session, p)

    p = proceso(fase=2)
    StudentMail.phase_rejected(db_session, p, phase_number=2,
                               phase_name="Fase 02 · Cita de cotejo", reason=MALICIOSO)
    correos["rechazo de fase"] = _componer(db_session, p)

    for resultado in ("rejected", "revoked"):
        p = proceso(fase=2)
        StudentMail.survey_result(db_session, p, result=resultado, reason=MALICIOSO)
        correos[f"GTV {resultado}"] = _componer(db_session, p)

    appt = _agendar(db_session, cita_esc)
    _ya_salio(db_session, cita_esc["p1"].id)
    AppointmentService.cancel(db_session, appt, cita_esc["off"].id, MALICIOSO)
    correos["cancelación de cita"] = _componer(db_session, cita_esc["p1"])

    reloj()
    p = proceso(fase=2)
    _recordatorio(db_session, "appt_reminder", p,
                  make_appointment(p, when=CITA_MANANA, location=MALICIOSO))
    correos["recordatorio de cita"] = _componer(db_session, p)

    p = con_biblioteca(biblioteca="awaiting_payment", library_note=MALICIOSO)
    _pasa_a_caja(db_session, p, note=MALICIOSO)
    correos["pasa a Caja con nota"] = _componer(db_session, p)

    p = con_biblioteca(biblioteca="pending")
    _liberado_que_salio(db_session, p)
    StudentMail.library_reverted(db_session, p, reason=MALICIOSO, to_status="pending")
    correos["reversión del no adeudo"] = _componer(db_session, p)

    for nombre, c in correos.items():
        # Con el entorno real y sin autoescape: el `|e` de la plantilla basta solo.
        for html in (_html(c), _html(c, sin_autoescape=True)):
            assert "<script>" not in html, nombre
            assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html, nombre
            assert "&amp;" in html and "&#34;x&#34;" in html, nombre
    # El nombre de pila también: saludo + motivo.
    doc = correos["rechazo de documento"]
    assert _html(doc, sin_autoescape=True).count("&lt;script&gt;") == 2


def test_toda_variable_de_las_plantillas_de_correo_lleva_e():
    """La convención de `titulatec/email/` (patrón `process_cancelled.html`):
    TODO `{{ … }}` termina en `|e`, salvo la llamada a una macro de
    `_email_macros.html` (`m.…`), que escapa por dentro. Cubre también las
    ramas que ningún render de arriba recorre."""
    from pathlib import Path

    import itcj2

    carpeta = (Path(itcj2.__file__).resolve().parent / "apps" / "titulatec"
               / "templates" / "titulatec" / "email")
    revisadas, sin_e = 0, []
    for ruta in sorted(carpeta.glob("*.html")):
        texto = re.sub(r"\{#.*?#\}", "", ruta.read_text(encoding="utf-8"), flags=re.S)
        for expr in re.findall(r"\{\{-?\s*(.*?)\s*-?\}\}", texto, flags=re.S):
            revisadas += 1
            if not (re.search(r"\|\s*e$", expr) or expr.startswith("m.")):
                sin_e.append(f"{ruta.name}: {{{{ {expr} }}}}")
    assert revisadas >= 40, f"el barrido encogió a {revisadas}: revisa el regex"
    assert not sin_e, "variables sin `|e` en los correos:\n  " + "\n  ".join(sin_e)


# ---------------------------------------------------------------------------
# Barrida: un correo de cada tipo y variante
# ---------------------------------------------------------------------------
@pytest.fixture()
def todos(db_session, proceso, make_appointment, make_document, seed_document_types,
          make_survey_review, con_biblioteca, reloj):
    """Un correo de CADA tipo y variante, con los huecos opcionales en `None`
    donde el contrato lo permite (sin motivo, sin nota, sin lugar, sin
    requisitos). Devuelve `({variante: Composed}, {kinds cubiertos})`."""
    from itcj2.apps.titulatec.services.mail_compose import Composed
    from itcj2.apps.titulatec.services.student_mail import StudentMail
    from itcj2.core.utils.timezone import db_now

    db = db_session
    seed_document_types()
    reloj()                     # los recordatorios de cita se re-validan contra la hora
    correos, tipos = {}, set()

    def _anota(nombre, proc):
        filas = _pendientes(db, proc.id)
        c = _componer(db, proc, filas)
        assert isinstance(c, Composed), (nombre, c)
        correos[nombre] = c
        tipos.update(f.kind for f in filas)

    p = proceso()
    _dictamen(db, p, "curp", "approved")
    _anota("documentos revisados", p)

    p = proceso()
    _dictamen(db, p, "curp", "rejected")
    _dictamen(db, p, "birth_certificate", "rejected", note="Borroso")
    _anota("documentos con correcciones", p)

    p = proceso()
    _dictamen(db, p, "curp", "approved")
    _avance_fase_1(db, p)
    _anota("documentos aprobados", p)

    for nombre, pago in (
        ("fase avanza", dict(phase_number=3, phase_name="Fase 03 · Formato B",
                             next_phase=4, next_name="Fase 04 · Sinodales",
                             handoff=False)),
        ("fase corte a T-soft", dict(phase_number=2, phase_name="Fase 02 · Cita de cotejo",
                                     next_phase=3, next_name="Fase 03 · Formato B",
                                     handoff=True)),
        ("fase completada", dict(phase_number=8, phase_name="Fase 08 · Acto protocolario",
                                 next_phase=None, next_name=None, handoff=False)),
    ):
        p = proceso(fase=pago["phase_number"])
        StudentMail.phase_approved(db, p, **pago)
        _anota(nombre, p)

    p = proceso(fase=2)
    StudentMail.phase_rejected(db, p, phase_number=2, phase_name="Fase 02 · Cita de cotejo",
                               reason=None)
    _anota("fase rechazada sin motivo", p)

    for resultado in ("approved", "rejected", "revoked"):
        p = proceso(fase=2)
        make_survey_review(p, status="approved" if resultado == "approved" else "rejected")
        StudentMail.survey_result(db, p, result=resultado, reason=None)
        _anota(f"GTV {resultado} sin motivo", p)

    p = con_biblioteca(biblioteca="awaiting_payment", encuesta="approved")
    StudentMail.survey_result(db, p, result="approved", origin="prior")
    _anota("GTV constancia previa con pago pendiente", p)

    # No adeudo de biblioteca (spec 2026-10-01 §4.11).
    p = con_biblioteca(biblioteca="awaiting_payment")
    _pasa_a_caja(db, p)
    _anota("pasa a Caja sin nota ni información", p)

    p = con_biblioteca(biblioteca="awaiting_payment", library_note="Debe 2 libros",
                       info_html="<p>Caja abre de <strong>9:00 a 14:00</strong>.</p>")
    _pasa_a_caja(db, p)
    _ya_salio(db, p.id)
    _pasa_a_caja(db, p, note="Debe 2 libros", updated=True)
    _anota("corrección del monto con nota e información", p)

    for nombre, via, encuesta, fase in (
        ("liberado por pago con todo liberado", "payment", "approved", 2),
        ("liberado sin cargo sin encuesta", "no_charge", None, 2),
        ("liberado por constancia previa en fase 1", "prior", "in_review", 1),
        ("liberado con el cotejo ya aprobado", "payment", "approved", 3),
    ):
        p = con_biblioteca(fase=fase, biblioteca="cleared", via=via, encuesta=encuesta)
        StudentMail.library_cleared(db, p, via=via)
        _anota(f"no adeudo {nombre}", p)

    for hacia, motivo in (("awaiting_payment", "Pago duplicado"), ("pending", None)):
        p = con_biblioteca(biblioteca=hacia)
        # E10: la reversión sale solo si el liberado que revierte ya salió.
        _liberado_que_salio(db, p, via="payment" if hacia == "awaiting_payment" else "no_charge")
        StudentMail.library_reverted(db, p, reason=motivo, to_status=hacia)
        _anota(f"reversión a {hacia}", p)

    p = con_biblioteca(biblioteca="awaiting_payment")
    _recordatorio(db, "library_reminder", p)
    _anota("recordatorio de pago", p)

    p = con_biblioteca(biblioteca="pending")
    _recordatorio(db, "survey_reminder", p)
    _anota("recordatorio de encuesta con candado de biblioteca", p)

    p = proceso(fase=2)
    appt = make_appointment(p, location=None)
    StudentMail.appointment_changed(db, p, event="scheduled", appt=appt, by="student")
    _anota("cita sin lugar ni requisitos", p)

    p = proceso(fase=2)
    appt = make_appointment(p, status="confirmed")
    appt.confirmed_at = db_now()
    _requisito(db, p.cohort_id, "Actas de nacimiento", orden=0)
    _requisito(db, p.cohort_id, "12 fotografías", hint="Tamaño credencial", orden=1)
    StudentMail.appointment_changed(db, p, event="rescheduled", appt=appt, by="officer")
    _anota("cita cambiada y confirmada", p)

    p = proceso(fase=2)
    appt = make_appointment(p, status="cancelled", is_current=False)
    StudentMail.appointment_changed(db, p, event="cancelled", appt=appt, by="officer",
                                    reason=None)
    _anota("cita cancelada sin motivo", p)

    p = proceso(fase=2)
    appt = make_appointment(p, status="no_show")
    StudentMail.appointment_no_show(db, p, appt=appt)
    _anota("no se presentó", p)

    p = proceso(fase=2)
    _recordatorio(db, "appt_reminder", p, make_appointment(p, when=CITA_MANANA,
                                                           location=None))
    _anota("recordatorio de cita sin lugar ni requisitos", p)

    p = proceso(fase=2)
    appt = make_appointment(p, when=CITA_MANANA, status="confirmed")
    appt.confirmed_at = HOY_FIJO
    _requisito(db, p.cohort_id, "12 fotografías", hint="Tamaño credencial", orden=0)
    _recordatorio(db, "appt_reminder", p, appt)
    _anota("recordatorio de cita confirmada con requisitos", p)

    p = proceso(fase=1)
    _recordatorio(db, "docs_reminder", p)
    _anota("recordatorio de documentos por subir", p)

    p = proceso(fase=1)
    for code in _NOMBRES:
        make_document(p, type_code=code,
                      review_status="rejected" if code == "curp" else "approved")
    _recordatorio(db, "docs_reminder", p)
    _anota("recordatorio de documentos por corregir", p)

    p = proceso(fase=2)
    _recordatorio(db, "survey_reminder", p)
    _anota("recordatorio de encuesta", p)

    return correos, tipos


def test_todas_las_ligas_pasan_safe_next(todos):
    """C7: toda liga de todo correo es el login con un `next` que el propio
    login acepta tal cual, y el correo no trae ninguna otra liga. La única
    excepción es el `mailto:` de D12 (spec 2026-10-01 §2) en las observaciones
    y la revocación de GTV."""
    from itcj2.apps.titulatec.services.email_helper import PUBLIC_ORIGIN
    from itcj2.core.pages.auth import safe_next

    correos, _tipos = todos
    prefijo = f"{PUBLIC_ORIGIN}/itcj/login?next="
    for nombre, c in correos.items():
        assert c.link == c.context["link"], nombre
        assert c.link.startswith(prefijo), nombre
        ruta = unquote(c.link[len(prefijo):])
        assert safe_next(ruta) == ruta, nombre
        # Todas llevan a una pantalla del egresado; la encuesta de egresados es
        # la única fuera de `/titulatec/student/` (vive en `pages/public.py`).
        assert (ruta.startswith("/titulatec/student/")
                or ruta == "/titulatec/encuesta-egresados"), nombre
        html = _html(c)
        # El botón y la liga en texto plano: la MISMA liga, y ninguna otra.
        ligas = set(re.findall(r'href="([^"]*)"', html))
        d12 = nombre in ("GTV rejected sin motivo", "GTV revoked sin motivo")
        assert ligas == ({c.link, MAILTO_GTV} if d12 else {c.link}), nombre
        assert html.count(c.link) >= 2, nombre


def test_ningun_render_muestra_None(todos):
    """Ningún correo enseña `None` ni código de plantilla crudo, ni usa una
    variable que el compositor no le dio (Jinja estricto). La barrida cubre
    TODOS los tipos registrados: quien registre uno nuevo lo agrega a `todos`."""
    from itcj2.apps.titulatec.services.mail_compose import MailComposer

    correos, tipos = todos
    assert set(MailComposer.REGISTRY) <= tipos, set(MailComposer.REGISTRY) - tipos
    for nombre, c in correos.items():
        html = _html(c, estricto=True)
        assert c.subject.startswith(PREFIJO), nombre
        assert "None" not in c.subject and "None" not in html, nombre
        for crudo in ("{{", "}}", "{%", "%}", "{#", "#}"):
            assert crudo not in html, (nombre, crudo)
        assert "Hola <strong>ALUMNO</strong>" in html, nombre


def test_el_contexto_es_de_datos_planos(todos):
    """El despachador renderiza después de leer (y en producción la sesión
    expira al commitear): el contexto no lleva objetos ORM, solo datos
    serializables, y siempre `first_name` y `link`."""
    correos, _tipos = todos
    for nombre, c in correos.items():
        json.dumps(c.context)
        assert {"first_name", "link"} <= set(c.context), nombre


# ---------------------------------------------------------------------------
# Contrato con el despachador
# ---------------------------------------------------------------------------
def test_todo_kind_tiene_composicion():
    """Cada `kind` del catálogo tiene quién lo componga: su grupo (`docs:` /
    `cita:`, que el compositor reconoce por la llave) o una entrada del
    REGISTRY. Un tipo nuevo sin composición caería en `Obsolete` en silencio
    (solo un error en el log) y el egresado nunca recibiría ese correo."""
    from itcj2.apps.titulatec.models.email_outbox import OUTBOX_KINDS
    from itcj2.apps.titulatec.services.mail_compose import MailComposer

    # Los que viajan SIEMPRE en su grupo; el REGISTRY los cubre además por si
    # una fila llegara sin él.
    por_grupo = {"docs_review": "docs:", "appt_changed": "cita:"}
    sin_composicion = sorted(k for k in OUTBOX_KINDS
                             if k not in MailComposer.REGISTRY and k not in por_grupo)
    assert not sin_composicion, f"kinds sin composición: {sin_composicion}"
    assert set(MailComposer.REGISTRY) <= set(OUTBOX_KINDS), "REGISTRY con kinds que no existen"
    assert all(callable(fn) for fn in MailComposer.REGISTRY.values())
    for kind in ("appt_reminder", "docs_reminder", "survey_reminder",
                 "library_ready", "library_cleared", "library_reverted",
                 "library_reminder"):
        assert kind in MailComposer.REGISTRY, kind


def test_tipo_sin_composicion_queda_obsoleto_y_en_el_log(db_session, proceso,
                                                         monkeypatch, caplog):
    """Una fila que nadie sabe componer no se reintenta sin fin (atascaría el
    lote del despachador): queda obsoleta, con el motivo y un error en el log."""
    from itcj2.apps.titulatec.services.mail_compose import MailComposer, Obsolete
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso(fase=2)
    StudentMail.phase_rejected(db_session, proc, phase_number=2,
                               phase_name="Fase 02 · Cita de cotejo", reason="x")
    monkeypatch.setattr(MailComposer, "REGISTRY", {})

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        resultado = _componer(db_session, proc)

    assert resultado == Obsolete("sin composición para el tipo phase_rejected")
    assert "phase_rejected" in caplog.text


def test_filas_que_no_van_juntas_se_rechazan(db_session, proceso):
    """Juntar filas de dos procesos sería mandarle a un egresado lo de otro: el
    compositor lo rechaza en vez de adivinar. Igual con un alumno ajeno, dos
    grupos a la vez o varias filas sueltas."""
    from itcj2.apps.titulatec.services.mail_compose import MailComposer
    from itcj2.apps.titulatec.services.student_mail import StudentMail
    from itcj2.core.models.user import User

    a, b = proceso(fase=2), proceso(fase=2)
    for p in (a, b):
        StudentMail.phase_rejected(db_session, p, phase_number=2,
                                   phase_name="Fase 02 · Cita de cotejo", reason="x")
        StudentMail.survey_result(db_session, p, result="approved")
    _dictamen(db_session, a, "curp", "approved")
    alumno_a = db_session.get(User, a.student_id)
    rechazo_a, gtv_a, doc_a = _pendientes(db_session, a.id)
    rechazo_b = _pendientes(db_session, b.id)[0]

    for filas, usuario in (
        ([rechazo_b], alumno_a),                               # fila de otro proceso
        ([rechazo_a], db_session.get(User, b.student_id)),     # alumno ajeno
        ([rechazo_a, gtv_a], alumno_a),                        # dos sueltas sin grupo
        ([rechazo_a, doc_a], alumno_a),                        # dos grupos a la vez
        ([], alumno_a),                                        # nada
    ):
        with pytest.raises(ValueError):
            MailComposer.compose(db_session, filas, a, usuario)
