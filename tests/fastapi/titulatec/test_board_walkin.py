"""Tablero: el bloque «sin horario» lista TODAS las citas vivas y «Abrir más
lugares» (spec 2026-09-29-titulatec-cotejo-espacios-design.md §4 · D6, D8).

Nota de la revisión de T2 (arrastrada aquí): `_board_ctx` agrupaba las citas
por `(window_id, hora)`, así que la cita de LEGADO de un `walkin` -sentada a
mano a una hora distinta de la apertura- no caía en ninguna franja y
desaparecía de la lista sin dejar de contar en `ocupados`. El bloque walkin
arma su propia lista: TODAS las vivas de la ventana (estado != cancelled /
superseded, NUNCA por `is_current` -- el mismo criterio de
`SlotService.occupancy`), ordenadas por `(scheduled_at, id)`; `libres` sale de
`window_occupancy`, no de contar filas.
"""
from __future__ import annotations

from datetime import date, datetime, time
from urllib.parse import unquote

import lxml.html
import pytest

from itcj2.apps.titulatec.pages.appointments import _board_ctx
from itcj2.apps.titulatec.services.slot_service import SlotService
from tests.fastapi.titulatec.conftest import OFFICER_PERMS

URL = "/titulatec/admin/appointments"
_D = date(2029, 5, 7)
_ESPACIO_PERM = "titulatec.review_window.api.manage"
_PERMS = OFFICER_PERMS + (_ESPACIO_PERM,)


@pytest.fixture()
def esc(seed_phase_defs, seed_document_types, make_program, make_cohort,
        make_review_day, make_officer, make_student, make_process,
        make_document, make_review_window):
    """Un sin horario 08:00-14:00 con CINCO lugares, y tres procesos listos."""
    seed_phase_defs()
    seed_document_types()
    prog = make_program("Ingeniería de Tablero Walkin")
    cohort = make_cohort()
    dia = make_review_day(cohort, day=_D)
    officer, pos = make_officer([prog], perm_codes=_PERMS)
    w = make_review_window(dia, officer, start="08:00", end="14:00", slot=30,
                           cap=5, location="Sala 3", position=pos,
                           visibility="walkin")
    procs = [make_process(make_student(last_name="WALKIN" + str(i)), cohort=cohort,
                          program=prog, current_phase=2) for i in range(3)]
    for p in procs:
        for code in ("birth_certificate", "high_school_cert", "curp"):
            make_document(p, type_code=code, review_status="approved")
    return {"prog": prog, "cohort": cohort, "dia": dia, "off": officer,
            "pos": pos, "w": w, "p": procs}


def _apartar(db, esc, i, hora=time(8, 0)):
    return SlotService.assign(db, esc["w"].id, hora, esc["p"][i].id, esc["off"].id)


def _legado(db, make_appointment, w, proc, hhmm, **kw):
    """Cita sentada a mano a una HORA dentro del espacio, con su ventana."""
    a = make_appointment(proc, when=datetime.combine(_D, hhmm), **kw)
    a.window = w
    db.flush()
    return a


def _grupo(board, window_id):
    (g,) = [g for g in board["grupos"] if g["id"] == window_id]
    return g


# ===========================================================================
# `_board_ctx`: orden de apartado y libres
# ===========================================================================
def test_el_grupo_walkin_lleva_modo_sin_horario(db_session, esc):
    board = _board_ctx(db_session, esc["dia"].date, None,
                       user_id=esc["off"].id, cohort_id=esc["cohort"].id)
    g = _grupo(board, esc["w"].id)

    assert g["modo"] == "sin_horario"
    assert g["apertura"] == "08:00"
    assert g["horario"] == "08:00–14:00"
    assert g["location"] == "Sala 3"
    assert g["lista"] == []
    assert g["capacidad"] == 5
    assert g["ocupados"] == 0
    assert g["libres"] == 5


def test_la_lista_incluye_la_de_legado_por_orden_de_apartado(
        db_session, esc, make_appointment):
    """Review Focus 3 (T2) llevado al tablero: la de legado NO desaparece, y
    el desempate de la MISMA hora es el `id` (orden de llegada)."""
    apartada = _apartar(db_session, esc, 0)                       # 08:00
    legado = _legado(db_session, make_appointment, esc["w"], esc["p"][1],
                     time(10, 30))                                 # 10:30
    otra = _apartar(db_session, esc, 2)                            # 08:00, después

    board = _board_ctx(db_session, esc["dia"].date, None,
                       user_id=esc["off"].id, cohort_id=esc["cohort"].id)
    g = _grupo(board, esc["w"].id)

    assert [f["process_id"] for f in g["lista"]] == [
        apartada.process_id, otra.process_id, legado.process_id]
    assert [f["n"] for f in g["lista"]] == [1, 2, 3]
    # La de legado conserva SU hora (regla de legado, D11/§6): "Sin horario"
    # es solo para el apartado a la apertura.
    assert g["lista"][0]["time_label"] == "Sin horario"
    assert g["lista"][2]["time_label"] == "10:30"


def test_libres_sale_de_window_occupancy_no_de_contar_filas(
        db_session, esc, make_appointment):
    """Una cancelada NO ocupa lugar (`_ESTADOS_QUE_LIBERAN`): si `libres`
    contara filas crudas en vez de restar de `window_occupancy`, la cancelada
    se comería un lugar que en realidad sigue libre."""
    _apartar(db_session, esc, 0)
    _legado(db_session, make_appointment, esc["w"], esc["p"][1], time(10, 30))
    _legado(db_session, make_appointment, esc["w"], esc["p"][2], time(9, 0),
           status="cancelled", is_current=False)

    board = _board_ctx(db_session, esc["dia"].date, None,
                       user_id=esc["off"].id, cohort_id=esc["cohort"].id)
    g = _grupo(board, esc["w"].id)

    assert len(g["lista"]) == 2, "la cancelada no es una cita VIVA"
    ocupados, capacidad = SlotService.window_occupancy(db_session, esc["w"])
    assert (g["ocupados"], g["capacidad"]) == (ocupados, capacidad) == (2, 5)
    assert g["libres"] == 3


def test_una_no_show_no_vigente_sigue_en_la_lista(db_session, esc, make_appointment):
    """D10: un `no_show` sigue ocupando su lugar aunque `is_current=False`
    (el proceso ya tiene otra cita vigente en otra parte). El filtro es por
    ESTADO, nunca por `is_current`."""
    vieja = _legado(db_session, make_appointment, esc["w"], esc["p"][0],
                    time(8, 0), status="no_show", is_current=False)

    board = _board_ctx(db_session, esc["dia"].date, None,
                       user_id=esc["off"].id, cohort_id=esc["cohort"].id)
    g = _grupo(board, esc["w"].id)

    assert [f["process_id"] for f in g["lista"]] == [vieja.process_id]
    assert g["ocupados"] == 1
    assert g["libres"] == 4


def test_es_hoy_distingue_el_dia(db_session, esc, make_review_day,
                                 make_review_window):
    from itcj2.core.utils.timezone import db_now

    hoy = db_now().date()
    dia_hoy = make_review_day(esc["cohort"], day=hoy)
    w_hoy = make_review_window(dia_hoy, esc["off"], start="08:00", end="14:00",
                               cap=3, position=esc["pos"], visibility="walkin")

    board_futuro = _board_ctx(db_session, esc["dia"].date, None,
                              user_id=esc["off"].id, cohort_id=esc["cohort"].id)
    board_hoy = _board_ctx(db_session, hoy, None,
                           user_id=esc["off"].id, cohort_id=esc["cohort"].id)

    assert _grupo(board_futuro, esc["w"].id)["es_hoy"] is False
    assert _grupo(board_hoy, w_hoy.id)["es_hoy"] is True


def test_un_walkin_y_una_franja_el_mismo_dia_no_se_mezclan(
        db_session, esc, make_review_window, make_process, make_student):
    """El `for g` recorre los dos modos: uno no puede pisar al otro."""
    franjas = make_review_window(esc["dia"], esc["off"], start="15:00", end="16:00",
                                 slot=30, cap=1, position=esc["pos"],
                                 visibility="private")
    p_franja = make_process(make_student(last_name="FRANJA"), cohort=esc["cohort"],
                            program=esc["prog"], current_phase=2)
    SlotService.assign(db_session, franjas.id, time(15, 0), p_franja.id, esc["off"].id)
    _apartar(db_session, esc, 0)

    board = _board_ctx(db_session, esc["dia"].date, None,
                       user_id=esc["off"].id, cohort_id=esc["cohort"].id)
    modos = {g["id"]: g["modo"] for g in board["grupos"]}

    assert modos[esc["w"].id] == "sin_horario"
    assert modos[franjas.id] == "franjas"
    g_franjas = _grupo(board, franjas.id)
    assert g_franjas["franjas"][0]["ocupantes"][0]["process_id"] == p_franja.id


# ===========================================================================
# La ruta: «Abrir más lugares»
# ===========================================================================
def _url_lugares(window_id, day=_D):
    return f"{URL}/espacios/{window_id}/lugares?v=agenda&date={day.isoformat()}"


def test_la_ruta_abre_lugares_el_dueno(db_session, esc, client_as):
    resp = client_as(esc["off"]).post(_url_lugares(esc["w"].id), data={"n": "5"})

    assert resp.status_code == 200, unquote(resp.headers.get("X-Tt-Error", ""))
    assert unquote(resp.headers["X-Tt-Notice"]) == "Listo: 5 lugares más."
    assert resp.headers["X-Tt-Notice-Kind"] == "success"
    db_session.expire_all()
    assert esc["w"].capacity == 10


def test_la_ruta_abre_lugares_en_singular(db_session, esc, client_as):
    resp = client_as(esc["off"]).post(_url_lugares(esc["w"].id), data={"n": "1"})

    assert resp.status_code == 200, unquote(resp.headers.get("X-Tt-Error", ""))
    assert unquote(resp.headers["X-Tt-Notice"]) == "Listo: 1 lugar más."
    db_session.expire_all()
    assert esc["w"].capacity == 6


def test_la_ruta_de_lugares_es_404_para_un_espacio_ajeno(
        db_session, esc, client_as, make_officer):
    otro, _ = make_officer([esc["prog"]], perm_codes=_PERMS, first_name="OTRO")

    resp = client_as(otro).post(_url_lugares(esc["w"].id), data={"n": "5"})

    assert resp.status_code == 404
    assert "X-Tt-Error" not in resp.headers
    db_session.expire_all()
    assert esc["w"].capacity == 5


@pytest.mark.parametrize("n", ["0", "51"])
def test_la_ruta_de_lugares_rechaza_fuera_de_rango(db_session, esc, client_as, n):
    resp = client_as(esc["off"]).post(_url_lugares(esc["w"].id), data={"n": n})

    assert resp.status_code == 400
    assert unquote(resp.headers["X-Tt-Error"]) == (
        "Puedes abrir de 1 a 50 lugares a la vez, hasta 500 en total.")
    db_session.expire_all()
    assert esc["w"].capacity == 5


def test_la_ruta_de_lugares_rechaza_un_espacio_con_franjas(
        db_session, esc, client_as, make_review_window):
    franjas = make_review_window(esc["dia"], esc["off"], start="15:00", end="16:00",
                                 cap=2, position=esc["pos"], visibility="private")

    resp = client_as(esc["off"]).post(_url_lugares(franjas.id), data={"n": "5"})

    assert resp.status_code == 400
    assert unquote(resp.headers["X-Tt-Error"]) == (
        "Solo los espacios sin horario abren lugares.")


# ===========================================================================
# El markup del tablero
# ===========================================================================
def _seccion_walkin(html, window_id):
    (sec,) = lxml.html.fromstring(html).xpath(
        '//*[@id="appt-walkin-%d"]' % window_id)
    return sec


def test_la_raiz_y_las_filas_llevan_ids_estables(db_session, esc, client_as,
                                                  make_appointment):
    apartada = _apartar(db_session, esc, 0)
    _legado(db_session, make_appointment, esc["w"], esc["p"][1], time(10, 30))

    html = client_as(esc["off"]).get(URL + "?date=" + _D.isoformat()).text
    sec = _seccion_walkin(html, esc["w"].id)

    assert sec.xpath('.//a[@id="appt-walkin-row-p%d"]' % apartada.process_id)
    assert sec.xpath('.//*[@id="appt-walkin-drop-%d"]' % esc["w"].id)
    # El form de «Abrir más lugares» vuelve a la Agenda de este día.
    (form,) = sec.xpath('.//form[.//input[@name="n"]]')
    assert form.get("hx-post") == (
        f"{URL}/espacios/{esc['w'].id}/lugares?v=agenda&date={_D.isoformat()}")
    (campo,) = form.xpath('.//input[@name="n"]')
    assert (campo.get("type"), campo.get("min"), campo.get("max"), campo.get("value")) == (
        "number", "1", "50", "1")


def test_el_alumno_aparto_dice_aparto_no_agendo(db_session, esc, client_as,
                                                make_appointment):
    """D11 en su vocabulario propio: en el sin horario el egresado APARTA
    lugar, no agenda una hora."""
    a = make_appointment(esc["p"][0], when=datetime.combine(_D, time(8, 0)),
                         booked_by="student")
    a.window = esc["w"]
    db_session.flush()

    html = client_as(esc["off"]).get(URL + "?date=" + _D.isoformat()).text
    sec = _seccion_walkin(html, esc["w"].id)
    fila = sec.xpath('.//a[@id="appt-walkin-row-p%d"]' % esc["p"][0].id)[0]

    assert "El alumno apartó" in lxml.html.tostring(fila, encoding="unicode")
    assert "El alumno agendó" not in lxml.html.tostring(fila, encoding="unicode")


def test_lleno_dice_lleno_y_con_libres_dice_cuantos(db_session, esc, client_as,
                                                    make_review_window):
    chico = make_review_window(esc["dia"], esc["off"], start="16:00", end="17:00",
                               cap=1, location="Ventanilla 1", position=esc["pos"],
                               visibility="walkin")
    SlotService.assign(db_session, chico.id, time(16, 0), esc["p"][0].id, esc["off"].id)

    html = client_as(esc["off"]).get(URL + "?date=" + _D.isoformat()).text
    lleno = _seccion_walkin(html, chico.id)
    libre = _seccion_walkin(html, esc["w"].id)

    assert "Lleno" in lleno.text_content()
    assert "5 lugares libres" in " ".join(libre.text_content().split())


def test_con_seleccion_ofrece_apartarle_lugar_y_atender_ahora_si_es_hoy(
        db_session, esc, client_as, make_review_day, make_review_window,
        make_process, make_student):
    from itcj2.core.utils.timezone import db_now

    hoy = db_now().date()
    dia_hoy = make_review_day(esc["cohort"], day=hoy)
    w_hoy = make_review_window(dia_hoy, esc["off"], start="08:00", end="14:00",
                               cap=3, position=esc["pos"], visibility="walkin")
    pendiente = make_process(make_student(last_name="PENDIENTE"), cohort=esc["cohort"],
                             program=esc["prog"], current_phase=2)

    html = client_as(esc["off"]).get(
        f"{URL}?date={hoy.isoformat()}&p={pendiente.id}").text
    sec = _seccion_walkin(html, w_hoy.id)

    assert "Apartarle lugar" in sec.text_content()
    (form,) = sec.xpath('.//form[@id="appt-walkin-atender-%d"]' % w_hoy.id)
    assert form.get("hx-post") == (
        f"{URL}/{pendiente.id}/atender-ahora?v=atender&date={hoy.isoformat()}"
        f"&selected={pendiente.id}")
    assert form.xpath('.//input[@name="window_id"]/@value') == [str(w_hoy.id)]


def test_con_mover_ofrece_mover_aqui(db_session, esc, client_as):
    apartada = _apartar(db_session, esc, 0)

    html = client_as(esc["off"]).get(
        f"{URL}?date={_D.isoformat()}&mover={apartada.process_id}").text
    sec = _seccion_walkin(html, esc["w"].id)

    assert "Mover aquí" in sec.text_content()
    (boton,) = sec.xpath('.//button[@id="appt-walkin-drop-%d"]' % esc["w"].id)
    assert boton.get("hx-post") == (
        f"{URL}/{apartada.process_id}/move?v=agenda&date={_D.isoformat()}"
        f"&window_id={esc['w'].id}&slot=08:00")
