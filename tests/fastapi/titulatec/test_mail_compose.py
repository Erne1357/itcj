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

Las filas se encolan con `StudentMail` (el contrato real de los payloads), no a
mano: si la Tarea 4 cambia un payload, esto se entera.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import time, timedelta
from urllib.parse import unquote

import pytest

import itcj2.models  # noqa: F401

PREFIJO = "[TitulaTec ITCJ] "
MALICIOSO = '<script>alert(1)</script> & "x"'
LOGGER = "itcj2.apps.titulatec.services.mail_compose"

_NOMBRES = {
    "birth_certificate": "Acta de nacimiento",
    "high_school_cert": "Certificado de bachillerato",
    "curp": "CURP certificada",
}


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
    cupo 1) con la encuesta de `p1` YA ENVIADA: sin ella no se agenda (D2)."""
    make_survey_review(agenda_slots["p1"])
    return agenda_slots


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
def test_dictamen_de_gtv(db_session, proceso, resultado, asunto):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso(fase=2)
    motivo = None if resultado == "approved" else "Debe Servicio Social"
    StudentMail.survey_result(db_session, proc, result=resultado, reason=motivo)

    c = _componer(db_session, proc)

    assert c.subject == asunto
    assert c.template == "survey_result.html"
    assert c.link == _liga("/titulatec/student/dashboard?fase=2")
    assert c.context["result"] == resultado
    html = _html(c)
    # Observaciones y revocación: el motivo y a dónde acudir.
    assert ("Debe Servicio Social" in html) is (motivo is not None)
    assert ("ventanilla de GTV" in html) is (resultado != "approved")


# ---------------------------------------------------------------------------
# #7 — grupo `cita:{pid}`, armado con la cita VIGENTE (Review Focus 5)
# ---------------------------------------------------------------------------
def test_cita_agendada_lleva_fecha_lugar_requisitos_y_confirmar(db_session, cita_esc):
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
def test_cita_cancelada_que_ya_conocia_manda_cancelacion(db_session, cita_esc, mover):
    """Su cita ya le había llegado por correo (esa fila salió); ahora el
    encargado se la cancela, con o sin moverla antes: aviso con el motivo."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

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
def test_no_show_avisa_con_la_fecha_de_la_cita(db_session, cita_esc):
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

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


def test_no_show_de_otra_cita_no_lo_vuelve_obsoleto(db_session, proceso,
                                                    make_appointment):
    """El aviso más reciente es de OTRO intento: el de la primera cita sigue
    siendo verdad y sale."""
    from itcj2.apps.titulatec.services.mail_compose import Composed
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso(fase=2)
    primera = make_appointment(proc, status="no_show", is_current=False, attempt_no=1)
    segunda = make_appointment(proc, status="no_show", attempt_no=2)
    StudentMail.appointment_no_show(db_session, proc, appt=primera)
    StudentMail.appointment_no_show(db_session, proc, appt=segunda)
    de_la_primera, _de_la_segunda = _pendientes(db_session, proc.id)

    assert isinstance(_componer(db_session, proc, [de_la_primera]), Composed)


# ---------------------------------------------------------------------------
# Review Focus 2 — el texto libre sale escapado
# ---------------------------------------------------------------------------
def test_texto_libre_sale_escapado(db_session, proceso, cita_esc):
    """Los motivos los escribe el personal y el nombre lo tecleó un formulario
    público: en un correo HTML eso es inyección. Sale escapado, nunca como
    HTML."""
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
def todos(db_session, proceso, make_appointment):
    """Un correo de CADA tipo y variante, con los huecos opcionales en `None`
    donde el contrato lo permite (sin motivo, sin nota, sin lugar, sin
    requisitos). Devuelve `({variante: Composed}, {kinds cubiertos})`."""
    from itcj2.apps.titulatec.services.mail_compose import Composed
    from itcj2.apps.titulatec.services.student_mail import StudentMail
    from itcj2.core.utils.timezone import db_now

    db = db_session
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
        StudentMail.survey_result(db, p, result=resultado, reason=None)
        _anota(f"GTV {resultado} sin motivo", p)

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

    return correos, tipos


def test_todas_las_ligas_pasan_safe_next(todos):
    """C7: toda liga de todo correo es el login con un `next` que el propio
    login acepta tal cual, y el correo no trae ninguna otra liga."""
    from itcj2.apps.titulatec.services.email_helper import PUBLIC_ORIGIN
    from itcj2.core.pages.auth import safe_next

    correos, _tipos = todos
    prefijo = f"{PUBLIC_ORIGIN}/itcj/login?next="
    for nombre, c in correos.items():
        assert c.link == c.context["link"], nombre
        assert c.link.startswith(prefijo), nombre
        ruta = unquote(c.link[len(prefijo):])
        assert safe_next(ruta) == ruta, nombre
        assert ruta.startswith("/titulatec/student/"), nombre
        html = _html(c)
        # El botón y la liga en texto plano: la MISMA liga, y ninguna otra.
        assert set(re.findall(r'href="([^"]*)"', html)) == {c.link}, nombre
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
def test_registry_cubre_el_catalogo_salvo_los_recordatorios():
    from itcj2.apps.titulatec.models.email_outbox import OUTBOX_KINDS
    from itcj2.apps.titulatec.services.mail_compose import MailComposer

    # Los tres recordatorios los registra la Tarea 8; al hacerlo, esto queda vacío.
    pendientes_t8 = {"appt_reminder", "docs_reminder", "survey_reminder"}
    assert set(MailComposer.REGISTRY) <= set(OUTBOX_KINDS)
    assert set(OUTBOX_KINDS) - set(MailComposer.REGISTRY) == pendientes_t8


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
