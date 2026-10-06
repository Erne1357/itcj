"""«Con observaciones» (`observed`) en el gate y en todo lo que deriva de él.

Spec `docs/superpowers/specs/2026-10-05-titulatec-biblioteca-observaciones-
design.md` §3.4, Tarea 2 del plan 2026-10-05-titulatec-biblioteca-observaciones.

La Tarea 1 hizo que Biblioteca pueda observar/rehabilitar (`LibraryClearance.
status = 'observed'`). Antes de esta tarea el gate lo mapeaba, fallando
cerrado, a `library_pending` -bloqueaba, pero con el mensaje equivocado
(«el Centro de Información está revisando…»)-. Aquí se fija que `observed`:

* bloquea con su PROPIO código (`library_observed`) y su propia razón de
  autoagenda (`biblioteca_con_observaciones`, Review Focus 5);
* el encargado tampoco agenda (`LibraryNotCleared` con mensaje propio);
* cae al cubo «Liberaciones pendientes» de la cola;
* la guarda de la fase 2, el correo (`_FALTA`), la píldora, el dashboard del
  egresado (con el motivo), «Mi cita» y el expediente de SE lo dicen;
* rehabilitar lo regresa a `library_pending` (Review Focus 2): sigue
  bloqueado hasta que Biblioteca dictamine;
* ningún `LIBRARY_EVENT_TYPES` se pinta crudo en ningún historial.
"""
from __future__ import annotations

from datetime import time
from unittest.mock import patch

import lxml.html
import pytest

import itcj2.models  # noqa: F401

# El escenario (`esc`) y los cubos de la cola son los de la prueba del gate:
# importarlos registra el fixture aquí sin duplicar el armado.
from tests.fastapi.titulatec.test_clearance_gate import (  # noqa: F401
    NOTIFY, _cubos, esc,
)

MOTIVO = "Debe el libro «Cálculo diferencial» desde 2024."

# Review Focus 5, literal: el mensaje de autoagenda del observado.
MSG_OBSERVADO = ("Biblioteca registró observaciones en tu no adeudo: acude a la "
                 "Biblioteca (Centro de Información) para resolverlas. Podrás agendar "
                 "en cuanto se libere tu no adeudo.")


def _observado(esc, **kw):
    return esc["nuevo"](biblioteca="observed", observation_reason=MOTIVO, **kw)


def _gate():
    from itcj2.apps.titulatec.services.clearance_gate import ClearanceGate
    return ClearanceGate


def _texto(nodo) -> str:
    return " ".join(nodo.text_content().split())


# ===========================================================================
# Gate
# ===========================================================================
def test_gate_observed_bloquea(db_session, esc):
    from itcj2.apps.titulatec.services import clearance_gate as mod

    proc = _observado(esc)

    assert "observed" in mod.LIBRARY_STATES
    assert "library_observed" in mod.LIBRARY_BLOCKERS
    assert "library_observed" in mod.BLOCKERS
    assert _gate().status(db_session, proc.id)["library"] == "observed"
    assert _gate().blockers({"survey": "approved", "library": "observed"}) == [
        "library_observed"]
    assert _gate().is_clear(db_session, proc.id) is False


def test_rehabilitado_sigue_bloqueado_como_pendiente(db_session, esc):
    """Review Focus 2: rehabilitar lo regresa a «Por revisar»; el gate sigue
    bloqueando, ahora por `library_pending`, hasta que Biblioteca dictamine."""
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )
    from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

    proc = esc["nuevo"](biblioteca="pending")
    fila = LibraryClearanceService.get_for_process(db_session, proc.id)
    with patch(NOTIFY):
        LibraryClearanceService.observe(db_session, fila.id, reason=MOTIVO,
                                        actor_id=esc["off"].id)
        assert _gate().blockers(_gate().status(db_session, proc.id)) == ["library_observed"]
        LibraryClearanceService.reenable(db_session, fila.id, actor_id=esc["off"].id)

    assert _gate().blockers(_gate().status(db_session, proc.id)) == ["library_pending"]
    assert SelfBookingService.eligibility(db_session, proc.id)["reason"] == (
        "biblioteca_en_revision")


# ===========================================================================
# Autoagenda del egresado (Review Focus 5)
# ===========================================================================
def test_autoagenda_mensaje_observaciones(db_session, esc):
    from itcj2.apps.titulatec.services.appointment_errors import SelfBookingNotAllowed
    from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

    proc = _observado(esc)

    e = SelfBookingService.eligibility(db_session, proc.id)
    assert e["can_book"] is False and e["can_walkin"] is False
    assert e["reason"] == "biblioteca_con_observaciones"
    assert SelfBookingService.message_for(e["reason"]) == MSG_OBSERVADO

    with pytest.raises(SelfBookingNotAllowed) as exc:
        SelfBookingService.book(db_session, proc.id, esc["w"]["con"].id, time(9, 0),
                                proc.student_id)
    assert exc.value.reason == "biblioteca_con_observaciones"
    assert str(exc.value) == MSG_OBSERVADO


# ===========================================================================
# El encargado tampoco agenda
# ===========================================================================
def test_encargado_no_agenda_observado(db_session, esc):
    from itcj2.apps.titulatec.services import appointment_errors as err
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    proc = _observado(esc)

    with pytest.raises(err.LibraryNotCleared) as exc:
        AppointmentService.create(db_session, proc.id, window_id=esc["w"]["con"].id,
                                  slot_start=time(9, 0), created_by_id=esc["off"].id)

    assert exc.value.status == "observed"
    texto = str(exc.value)
    assert "observaciones" in texto and "este alumno" in texto
    assert "sigue en revisión" not in texto, "cayó al mensaje de pendiente"
    assert AppointmentService.get_for_process(db_session, proc.id) is None


def test_cubo_liberaciones_pendientes_incluye_observado(db_session, esc):
    proc = _observado(esc)

    cubos = _cubos(db_session, esc)
    donde = sorted(nombre for nombre, ids in cubos.items() if proc.id in ids)
    assert donde == ["liberaciones"]


# ===========================================================================
# Guarda de la fase 2 y correo
# ===========================================================================
def test_aprobar_fase2_lista_con_observaciones_de_biblioteca(db_session, esc, make_user):
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    proc = _observado(esc)

    with patch(NOTIFY):
        with pytest.raises(ValueError) as exc:
            PhaseService.approve_phase(db_session, proc, 2, reviewer_id=make_user().id)

    assert "No-adeudo de biblioteca (con observaciones de Biblioteca)" in str(exc.value)


def test_el_correo_dice_que_falta_atender_las_observaciones(db_session, esc):
    from itcj2.apps.titulatec.services.mail_compose import _FALTA, _que_falta

    proc = _observado(esc)

    falta = _que_falta(db_session, proc)
    assert falta == [_FALTA["library_observed"]]
    assert "observaciones" in _FALTA["library_observed"]


# ===========================================================================
# Píldora
# ===========================================================================
def test_pill_observed():
    from itcj2.apps.titulatec.pages.nav import titulatec_templates

    tpl = titulatec_templates.env.from_string(
        '{% from "titulatec/_macros.html" import library_clearance_pill %}'
        '{{ library_clearance_pill("observed") }}')
    html = " ".join(tpl.render().split())

    assert "tt-pill--danger" in html
    assert "Con observaciones" in html
    assert "observed" not in html


# ===========================================================================
# Pantallas del egresado
# ===========================================================================
def test_dashboard_alumno_muestra_motivo(db_session, esc, client_as):
    """El bloque «No adeudo de biblioteca» vive en el panel desplegable de la
    fase 2 cuando NO es la actual (en la actual solo va la píldora, igual que
    `test_student_library_status.py::TestHomeTarjetaActual`): fase 1."""
    proc = _observado(esc, fase=1)

    resp = client_as(proc.student).get("/titulatec/student/dashboard")
    assert resp.status_code == 200, resp.text[:400]
    (fase,) = lxml.html.fromstring(resp.text).xpath('//*[@data-tt-phase="2"]')
    texto = _texto(fase)

    assert "Con observaciones" in texto
    assert "Biblioteca registró observaciones en tu no adeudo" in texto
    assert MOTIVO in texto
    assert "El Centro de Información está revisando tu adeudo" not in texto


def test_mi_cita_muestra_pildora_y_motivo(db_session, esc, client_as):
    proc = _observado(esc)

    resp = client_as(proc.student).get("/titulatec/student/cita")
    assert resp.status_code == 200, resp.text[:400]
    texto = _texto(lxml.html.fromstring(resp.text))

    assert "Con observaciones" in texto
    assert MOTIVO in texto
    assert MSG_OBSERVADO in texto


def test_mi_cita_con_cita_vigente_no_promete_agendar(db_session, esc, client_as,
                                                     make_appointment):
    """Ruling R12: con una cita que ocupa el cotejo, el observado tampoco lee
    «Podrás agendar…»."""
    proc = _observado(esc)
    make_appointment(proc, status="scheduled")

    resp = client_as(proc.student).get("/titulatec/student/cita")

    assert resp.status_code == 200, resp.text[:400]
    assert "Podrás agendar en cuanto se libere tu no adeudo" not in resp.text
    assert "Servicios Escolares pueda liberar tu cotejo" in resp.text


# ===========================================================================
# Expediente de SE
# ===========================================================================
def test_expediente_se_muestra_observado(db_session, esc, client_as):
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )

    proc = esc["nuevo"](biblioteca="pending")
    fila = LibraryClearanceService.get_for_process(db_session, proc.id)
    with patch(NOTIFY):
        LibraryClearanceService.observe(db_session, fila.id, reason=MOTIVO,
                                        actor_id=esc["off"].id)

    resp = client_as(esc["off"]).get(f"/titulatec/admin/processes/{proc.id}")

    assert resp.status_code == 200, resp.text[:400]
    texto = _texto(lxml.html.fromstring(resp.text))
    assert "Con observaciones" in texto
    assert MOTIVO in texto
    # El historial: la etiqueta, nunca el código crudo.
    assert "Biblioteca registró observaciones" in texto
    assert "library_observed" not in texto


def test_ningun_evento_de_biblioteca_se_pinta_crudo():
    """El defecto de GTV (`pages/admin.py`, «el expediente enseñaba
    `survey_review_approved` en crudo») no se repite con el no adeudo: todo
    `LIBRARY_EVENT_TYPES` está en el dominio y en los DOS mapas."""
    from itcj2.apps.titulatec.models.process_event import EVENT_TYPES
    from itcj2.apps.titulatec.pages.admin import _EVENT_UI
    from itcj2.apps.titulatec.pages.student import _EVENT_LABELS
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LIBRARY_EVENT_TYPES,
    )

    for ev in LIBRARY_EVENT_TYPES:
        assert ev in EVENT_TYPES, ev
        assert ev in _EVENT_UI and _EVENT_UI[ev][0] != ev, ev
        assert ev in _EVENT_LABELS and _EVENT_LABELS[ev] != ev, ev
