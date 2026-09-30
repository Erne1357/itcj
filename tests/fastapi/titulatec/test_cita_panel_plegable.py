"""La cita del alumno se pliega (Tarea 9, D10/D11, spec §6).

`/titulatec/student/cita` dejó de crecer sin control: los requisitos van
plegados arriba (`<details id="tt-cita-reqs">`), una sola tira de días incluye
también los espacios «sin horario» -ya no hay una tarjeta de walk-ins aparte,
D3/D4 hace que apartar lugar SEA agendar-, los encargados de cada día son
plegables y una franja con muchas horas se recorta a 12 con «Ver N horas más».
Todo con `<details>`/`<summary>` NATIVO: cero JS nuevo.

Reusa el andamiaje de `test_cita_card_sin_cita.py` (alumno en fase 2, encuesta
LIBERADA, con carrera) y `test_self_booking_routes.py`/`test_self_booking_
eligibility.py` (bloqueo por D9, `AppointmentService.create` para sentar a un
segundo proceso a mano).
"""
from __future__ import annotations

import lxml.html
import pytest

import itcj2.models  # noqa: F401

URL = "/titulatec/student/cita"
AGENDAR = "/titulatec/student/cita/agendar"


@pytest.fixture()
def esc(db_session, seed_phase_defs, make_student, make_cohort, make_process,
        make_survey_review, make_program):
    """Alumno en fase 2, SIN cita, con la encuesta ya LIBERADA y con carrera.

    Mismo montaje que `test_cita_card_sin_cita.py::esc`: la encuesta hace
    falta LIBERADA (D1) o `eligibility` se para en la regla 3, y la carrera
    hace falta o `offer()` nunca encuentra la ventana del encargado.
    """
    seed_phase_defs()
    cohort = make_cohort()
    student = make_student()
    process = make_process(student, cohort=cohort, current_phase=2)
    prog = make_program("Ingenieria de la Cita Plegable")
    process.program_id = prog.id
    make_survey_review(process, status="approved")
    db_session.flush()
    return {"student": student, "cohort": cohort, "process": process, "program": prog}


def _doc(resp):
    return lxml.html.fromstring(resp.text)


def _slotblocks(doc):
    return doc.xpath('//details[contains(concat(" ", @class, " "), " tt-slotblock ")]')


# ---------------------------------------------------------------------------
# Ids estables (autorrevisión del brief)
# ---------------------------------------------------------------------------
def test_los_cuatro_ids_estables_siguen_en_la_pagina(
        db_session, esc, client_as, make_officer, make_review_day, make_review_window):
    officer, pos = make_officer([esc["program"]])
    dia = make_review_day(esc["cohort"])
    ventana = make_review_window(dia, officer, position=pos)
    ventana.visibility = "bookable"
    db_session.flush()

    resp = client_as(esc["student"]).get(URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    doc = _doc(resp)
    for anchor in ("tt-cita-panel", "tt-cita-card", "tt-cita-agendar", "tt-cita-reqs"):
        assert doc.xpath(f'//*[@id="{anchor}"]'), f"falta #{anchor}"


# ---------------------------------------------------------------------------
# Encargados plegables: ≤2 los dos abiertos, si no solo el primero
# ---------------------------------------------------------------------------
def test_tres_encargados_el_mismo_dia_solo_el_primero_va_abierto(
        db_session, esc, client_as, make_officer, make_review_day, make_review_window):
    dia = make_review_day(esc["cohort"])
    # Apellidos en orden alfabetico: `offer()` ordena por `full_name`
    # ("apellido nombre"), asi que el primero en el DOM tiene que ser Aguilar.
    for i, apellido in enumerate(("Aguilar", "Beltran", "Cisneros")):
        officer, pos = make_officer([esc["program"]], last_name=apellido)
        make_review_window(dia, officer, position=pos,
                           start=f"{9 + i:02d}:00", end=f"{10 + i:02d}:00",
                           visibility="bookable")
    db_session.flush()

    resp = client_as(esc["student"]).get(URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    bloques = _slotblocks(_doc(resp))
    assert len(bloques) == 3
    abiertos = [b for b in bloques if b.get("open") is not None]
    assert len(abiertos) == 1, "con 3 encargados solo el primero va abierto"
    assert abiertos[0] is bloques[0], "el abierto tiene que ser el primero (orden de offer())"
    assert "Aguilar" in bloques[0].text_content()


def test_dos_encargados_el_mismo_dia_los_dos_van_abiertos(
        db_session, esc, client_as, make_officer, make_review_day, make_review_window):
    dia = make_review_day(esc["cohort"])
    for i, apellido in enumerate(("Aguilar", "Beltran")):
        officer, pos = make_officer([esc["program"]], last_name=apellido)
        make_review_window(dia, officer, position=pos,
                           start=f"{9 + i:02d}:00", end=f"{10 + i:02d}:00",
                           visibility="bookable")
    db_session.flush()

    resp = client_as(esc["student"]).get(URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    bloques = _slotblocks(_doc(resp))
    assert len(bloques) == 2
    assert all(b.get("open") is not None for b in bloques), "con 2 o menos, los dos abiertos"


# ---------------------------------------------------------------------------
# Franjas: 12 visibles + «Ver N horas más»
# ---------------------------------------------------------------------------
def test_veinte_franjas_muestran_doce_y_pliegan_las_otras_ocho(
        db_session, esc, client_as, make_officer, make_review_day, make_review_window):
    officer, pos = make_officer([esc["program"]])
    dia = make_review_day(esc["cohort"])
    # 09:00 a 19:00 en pasos de 30 min -> 20 franjas exactas.
    ventana = make_review_window(dia, officer, position=pos,
                                 start="09:00", end="19:00", slot=30, cap=1)
    ventana.visibility = "bookable"
    db_session.flush()

    resp = client_as(esc["student"]).get(URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert "Ver 8 horas más" in resp.text
    doc = _doc(resp)
    todas = doc.xpath('//button[contains(concat(" ", @class, " "), " tt-slot ")]')
    assert len(todas) == 20, "las 20 siguen en el DOM, aunque 8 esten plegadas"
    # `parent::details` y no `//details[.//summary[...]]`: ese otro xpath
    # tambien empareja el `<details class="tt-slotblock">` del encargado -es
    # ANCESTRO del summary «Ver mas», asi que tambien tiene un descendiente con
    # esa clase-. Subir desde el summary a su padre INMEDIATO da solo el
    # `<details>` de «Ver N horas mas».
    mas = doc.xpath('//summary[contains(@class, "tt-cita-more-sum")]/parent::details')
    assert len(mas) == 1
    ocultas = mas[0].xpath('.//button[contains(concat(" ", @class, " "), " tt-slot ")]')
    assert len(ocultas) == 8


def test_doce_franjas_o_menos_no_ofrecen_ver_mas(
        db_session, esc, client_as, make_officer, make_review_day, make_review_window):
    officer, pos = make_officer([esc["program"]])
    dia = make_review_day(esc["cohort"])
    # 09:00 a 15:00 en pasos de 30 min -> 12 franjas exactas.
    ventana = make_review_window(dia, officer, position=pos,
                                 start="09:00", end="15:00", slot=30, cap=1)
    ventana.visibility = "bookable"
    db_session.flush()

    resp = client_as(esc["student"]).get(URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert "horas más" not in resp.text


# ---------------------------------------------------------------------------
# Sin horario dentro de la tira: con lugares y botón, lleno sin botón
# ---------------------------------------------------------------------------
def test_sin_horario_con_lugares_ofrece_el_boton_de_apartar(
        db_session, esc, client_as, make_officer, make_review_day, make_review_window):
    officer, pos = make_officer([esc["program"]])
    dia = make_review_day(esc["cohort"])
    ventana = make_review_window(dia, officer, position=pos,
                                 start="08:00", end="14:00", cap=3)
    ventana.visibility = "walkin"
    db_session.flush()

    resp = client_as(esc["student"]).get(URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert "3 de 3 lugares" in resp.text
    assert "Apartar mi lugar" in resp.text
    assert "Lleno por ahora" not in resp.text


def test_sin_horario_lleno_no_ofrece_boton(
        db_session, esc, client_as, make_officer, make_review_day, make_review_window,
        make_student, make_cohort, make_process, make_survey_review):
    from datetime import time

    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    officer, pos = make_officer([esc["program"]])
    dia = make_review_day(esc["cohort"])
    ventana = make_review_window(dia, officer, position=pos,
                                 start="08:00", end="14:00", cap=1)
    ventana.visibility = "walkin"
    db_session.flush()

    # Otro proceso ocupa el UNICO lugar.
    otro = make_process(make_student(), cohort=esc["cohort"], program=esc["program"],
                        current_phase=2)
    make_survey_review(otro, status="approved")
    AppointmentService.create(db_session, otro.id, window_id=ventana.id,
                              slot_start=time(8, 0), created_by_id=officer.id)

    resp = client_as(esc["student"]).get(URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    # M-7 (revisión final): plural real -antes siempre decía "lugares", aun
    # con capacity=1-.
    assert "0 de 1 lugar" in resp.text
    assert "0 de 1 lugares" not in resp.text
    assert "Lleno por ahora" in resp.text
    assert "Apartar mi lugar" not in resp.text


def test_sin_horario_que_cierra_pronto_no_dice_lleno(
        db_session, esc, client_as, make_officer, make_review_day, make_review_window,
        monkeypatch):
    """I-2 (revisión final): con lugares libres pero a menos de MIN_LEAD del
    cierre, la pantalla NO dice «Lleno por ahora» -el encargado no puede
    arreglar esto abriendo lugares- sino que ya cerró la reserva en línea, y
    sin el conteo «N de M lugares» (que seguiría prometiendo cupo)."""
    from datetime import datetime, time

    import itcj2.apps.titulatec.services.self_booking_service as sb_mod

    officer, pos = make_officer([esc["program"]])
    dia = make_review_day(esc["cohort"])
    ventana = make_review_window(dia, officer, position=pos,
                                 start="08:00", end="14:00", cap=3)
    ventana.visibility = "walkin"
    db_session.flush()
    # A las 13:30 faltan 30 min para el cierre (14:00): menos que el
    # TITULATEC_SELF_BOOK_MIN_LEAD_MINUTES por omisión (60).
    monkeypatch.setattr(sb_mod, "db_now",
                        lambda: datetime.combine(dia.date, time(13, 30)))

    resp = client_as(esc["student"]).get(URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert "Ya no se aparta en línea: cierra a las 14:00." in resp.text
    assert "Lleno por ahora" not in resp.text
    assert "Apartar mi lugar" not in resp.text
    assert "de 3 lugares" not in resp.text


# ---------------------------------------------------------------------------
# Bloqueado por D9: modo "presentarse", sin ningún botón
# ---------------------------------------------------------------------------
def test_bloqueado_por_d9_ve_el_texto_de_presentarse_sin_boton(
        db_session, esc, client_as, make_officer, make_review_day, make_review_window,
        make_appointment):
    from itcj2.apps.titulatec.models import ReviewAppointment
    from itcj2.config import get_settings

    officer, pos = make_officer([esc["program"]])
    dia = make_review_day(esc["cohort"])
    ventana = make_review_window(dia, officer, position=pos,
                                 start="08:00", end="14:00", cap=5)
    ventana.visibility = "walkin"
    db_session.flush()

    tope = get_settings().TITULATEC_SELF_CANCEL_MAX
    for _ in range(tope):
        make_appointment(esc["process"], status="cancelled", is_current=False)
    for ap in (db_session.query(ReviewAppointment)
               .filter_by(process_id=esc["process"].id).all()):
        ap.cancelled_by_id = esc["student"].id
    db_session.flush()

    resp = client_as(esc["student"]).get(URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert "Preséntate en este horario; tu encargado te registra si hay lugar." in resp.text
    assert "Apartar mi lugar" not in resp.text
    assert "de 5 lugares" not in resp.text, "en modo presentarse no se cuentan lugares"
    assert 'name="window_id"' not in resp.text


# ---------------------------------------------------------------------------
# `?dia=` con HX-Request también respeta el modo (no solo `can_book`)
# ---------------------------------------------------------------------------
def test_dia_con_htmx_en_modo_presentarse_devuelve_el_selector_no_el_panel(
        db_session, esc, client_as, make_officer, make_review_day, make_review_window,
        make_appointment):
    """Regresión: la ruta `?dia=` comparaba `agenda.can_book` -que en modo
    `presentarse` es SIEMPRE `False`- y por eso el bloqueado por D9 que
    cambiaba de día por htmx recibía el panel entero (`HX-Retarget`) en vez
    del selector con la ventana sin horario de ese otro día. La condición
    correcta es `agenda.modo`, que sí es `"presentarse"`."""
    from datetime import timedelta

    from itcj2.apps.titulatec.models import ReviewAppointment
    from itcj2.config import get_settings

    officer, pos = make_officer([esc["program"]])
    dia1 = make_review_day(esc["cohort"])
    dia2 = make_review_day(esc["cohort"], day=dia1.date + timedelta(days=1))
    for dia in (dia1, dia2):
        ventana = make_review_window(dia, officer, position=pos, start="08:00", end="14:00", cap=5)
        ventana.visibility = "walkin"
    db_session.flush()

    tope = get_settings().TITULATEC_SELF_CANCEL_MAX
    for _ in range(tope):
        make_appointment(esc["process"], status="cancelled", is_current=False)
    for ap in (db_session.query(ReviewAppointment)
               .filter_by(process_id=esc["process"].id).all()):
        ap.cancelled_by_id = esc["student"].id
    db_session.flush()

    resp = client_as(esc["student"]).get(
        URL + "?dia=" + dia2.date.isoformat(), follow_redirects=False,
        headers={"HX-Request": "true"})

    assert resp.status_code == 200, resp.text[:300]
    assert resp.headers.get("HX-Retarget") is None, (
        "en modo presentarse SI hay selector que devolver; no debe redirigir "
        "el swap al panel entero")
    assert 'id="tt-cita-agendar"' in resp.text
    assert "Preséntate en este horario; tu encargado te registra si hay lugar." in resp.text


# ---------------------------------------------------------------------------
# Requisitos: abiertos con cita viva, cerrados sin ella
# ---------------------------------------------------------------------------
def test_requisitos_abiertos_cuando_hay_cita_viva(
        db_session, esc, client_as, make_appointment):
    make_appointment(esc["process"], status="scheduled")
    db_session.flush()

    resp = client_as(esc["student"]).get(URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    [reqs] = _doc(resp).xpath('//*[@id="tt-cita-reqs"]')
    assert reqs.get("open") is not None


def test_requisitos_cerrados_sin_cita(db_session, esc, client_as):
    resp = client_as(esc["student"]).get(URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    [reqs] = _doc(resp).xpath('//*[@id="tt-cita-reqs"]')
    assert reqs.get("open") is None


def test_el_resumen_de_requisitos_cuenta_totales_y_listos(
        db_session, esc, client_as):
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )
    from itcj2.apps.titulatec.services.requirement_service import RequirementService

    item = CotejoRequirementService.create(db_session, esc["cohort"].id,
                                           label="Unico", hint=None, icon=None)
    RequirementService.fulfill(db_session, esc["process"].id, item.id,
                               source="officer", commit=False)
    db_session.flush()

    resp = client_as(esc["student"]).get(URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    # M-7 (revisión final): plural real -antes siempre decía "1 requisitos
    # (1 listos)", aunque fueran uno solo-.
    assert "Qué llevar a tu cita · 1 requisito (1 listo)" in resp.text


def test_el_resumen_de_requisitos_usa_plural_con_mas_de_uno(
        db_session, esc, client_as):
    """Control positivo del anterior: con MÁS de un requisito, el plural
    sigue diciendo «requisitos»/«listos» -M-7 no rompe el caso normal-."""
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )
    from itcj2.apps.titulatec.services.requirement_service import RequirementService

    uno = CotejoRequirementService.create(db_session, esc["cohort"].id,
                                          label="Uno", hint=None, icon=None)
    CotejoRequirementService.create(db_session, esc["cohort"].id,
                                    label="Dos", hint=None, icon=None)
    RequirementService.fulfill(db_session, esc["process"].id, uno.id,
                               source="officer", commit=False)
    db_session.flush()

    resp = client_as(esc["student"]).get(URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert "Qué llevar a tu cita · 2 requisitos (1 listo)" in resp.text


# ---------------------------------------------------------------------------
# El checklist viaja en la respuesta de los POST del auto-agendado
# ---------------------------------------------------------------------------
def test_el_checklist_sale_en_la_respuesta_del_post_de_agendar(
        db_session, esc, client_as, make_role, grant_user_role, make_officer,
        make_review_day, make_review_window):
    from itcj2.core.models.user import User
    from tests.fastapi.titulatec.conftest import ROLE_STUDENT, STUDENT_PERMS

    officer, pos = make_officer([esc["program"]])
    dia = make_review_day(esc["cohort"])
    ventana = make_review_window(dia, officer, position=pos, start="09:00", end="11:00",
                                 slot=30, cap=1)
    ventana.visibility = "bookable"
    db_session.flush()

    alumno = db_session.get(User, esc["student"].id)
    perms = STUDENT_PERMS + ("titulatec.appointment.api.book.own",
                             "titulatec.appointment.api.cancel.own")
    grant_user_role(alumno, make_role(ROLE_STUDENT, perms))

    resp = client_as(alumno).post(
        AGENDAR, data={"window_id": str(ventana.id), "slot": "09:30"})

    assert resp.status_code == 200, resp.text[:300]
    assert 'id="tt-cita-reqs"' in resp.text
    assert "Qué llevar a tu cita" in resp.text
