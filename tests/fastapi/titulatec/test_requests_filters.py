"""Bandeja de solicitudes: filtros «Carrera» y «Año de ingreso» (2026-10-06).

En servidor (la bandeja pagina), junto a la búsqueda `q`, con nombres propios
(`program`, `year`) porque `program_id` ya es la carrera que se elige al
APROBAR. Lo que fija este archivo:

- La carrera respeta el alcance: la jefatura elige cualquiera, el encargado
  solo las suyas; una carrera ajena o inexistente en la URL cae a «todas» y
  nunca muestra nada fuera del alcance. Acota TODO (KPIs, «Por año de
  ingreso», pestañas y lista), como si fuera el alcance.
- El año sale del número de control con la MISMA regla que el bloque «Por año
  de ingreso» (`entry_year`), en SQL (`entry_year_filter`): filtro y conteo no
  discrepan. Acota lista y pestañas; el bloque sigue mostrando todos los años.
- Los dos viajan en cada formulario de fila, en las pestañas y en el pager:
  una acción re-pinta con los mismos filtros.

La BD de dev es COMPARTIDA (copia de prod): cada prueba mira SU convocatoria.
"""
from __future__ import annotations

import re
from datetime import date
from html import unescape

import pytest

URL = "/titulatec/admin/solicitudes"

LIST_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.read.all",      # -> officer_programs() == "ALL"
)
OFFICER_LIST_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
)


def _make_req(db_session, cohort, *, control, status="pending_review", program=None, **kw):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADA", last_name="DE FILTROS", middle_name=None,
        program_id=getattr(program, "id", program), program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email="filtros@example.invalid",
        has_efirma=False, kind="unknown", status=status, verify_send_count=0,
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture()
def correo_falso(monkeypatch):
    """Rechazar manda (o encola) el correo: Graph nunca se toca de verdad."""
    enviados = []

    class _Resp:
        status_code = 202
        text = ""

    def _fake_send(access_token, subject, content_html, to_list, save_to_sent=True):
        enviados.append((subject, list(to_list)))
        return _Resp()

    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent",
                        lambda app_key: "token-de-prueba")
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", _fake_send)
    return enviados


def _ids(html: str) -> set[int]:
    return {int(x) for x in re.findall(r'<tr id="tt-req-(\d+)"', html)}


def _kpi(html: str, label: str) -> int:
    m = re.search(
        rf'<div class="tt-kicker">{re.escape(label)}</div><div class="num">(\d+)</div>', html)
    assert m, f"no se encontró el KPI {label!r}"
    return int(m.group(1))


def _tab_count(html: str, key: str) -> int:
    m = re.search(rf'id="tt-req-tab-{key}"[^>]*>[^<(]*\((\d+)\)', html, re.S)
    assert m, f"no se encontró la pestaña {key}"
    return int(m.group(1))


def _select(html: str, sel_id: str) -> str:
    m = re.search(rf'<select id="{sel_id}".*?</select>', html, re.S)
    assert m, f"no está el selector {sel_id}"
    return m.group(0)


def _selected(select_html: str) -> str | None:
    m = re.search(r'<option value="([^"]*)" selected>', select_html)
    return m.group(1) if m else None


def _year_tile(html: str, slug: str) -> int:
    m = re.search(rf'id="tt-req-year-{slug}".*?tt-yeartile-total">(\d+)<', html, re.S)
    assert m, f"no está la ficha del año {slug}"
    return int(m.group(1))


# ---------------------------------------------------------------------------
# entry_year_filter: la misma regla que entry_year, en SQL
# ---------------------------------------------------------------------------
_CONTROLES = ["18550001", "C18550002", "c18550003", " 18550004", "21550005",
              "99550006", "XX550007", "", "1", "E26550008"]


def test_el_filtro_sql_casa_con_entry_year_en_cada_control(db_session, make_cohort):
    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        entry_year, entry_year_filter,
    )

    hoy = date(2026, 10, 6)
    cohort = make_cohort(status="open")
    filas = {}
    for i, control in enumerate(_CONTROLES):
        # El índice parcial es por (convocatoria, control) vivo: los raros que
        # se repiten tras quitar espacios van rechazados.
        filas[_make_req(db_session, cohort, control=control,
                        status="rejected" if i % 2 else "pending_review").id] = control

    esperado: dict[str, set[int]] = {}
    for rid, control in filas.items():
        esperado.setdefault(entry_year(control, hoy), set()).add(rid)

    for year, ids in esperado.items():
        cond = entry_year_filter(EnrollmentRequest.control_number, year, hoy)
        assert cond is not None, year
        got = {r for (r,) in db_session.query(EnrollmentRequest.id)
               .filter(EnrollmentRequest.cohort_id == cohort.id, cond).all()}
        assert got == ids, f"{year}: SQL {sorted(got)} != Python {sorted(ids)}"


@pytest.mark.parametrize("year", ["2090", "abcd", "19", "", None, "２０１８", "20188"])
def test_el_filtro_sql_rechaza_un_ano_que_entry_year_no_produce(year):
    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.apps.titulatec.services.enrollment_request_service import entry_year_filter

    assert entry_year_filter(EnrollmentRequest.control_number, year, date(2026, 10, 6)) is None


# ---------------------------------------------------------------------------
# Carrera
# ---------------------------------------------------------------------------
def test_la_carrera_acota_lista_kpis_pestanas_y_por_ano(client_as, db_session, make_head,
                                                        make_program, make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    prog_a = make_program("Carrera de filtro A")
    prog_b = make_program("Carrera de filtro B")
    cohort = make_cohort(status="open")
    a1 = _make_req(db_session, cohort, control="18551001", program=prog_a)
    a2 = _make_req(db_session, cohort, control="21551002", program=prog_a, status="rejected")
    b1 = _make_req(db_session, cohort, control="18551003", program=prog_b)
    c = client_as(head)

    html = c.get(f"{URL}/body?status=all&cohort_id={cohort.id}&program={prog_a.id}").text

    assert _ids(html) == {a1.id, a2.id}
    assert b1.id not in _ids(html)
    assert _kpi(html, "Total") == 2 and _kpi(html, "Rechazadas") == 1
    assert _tab_count(html, "all") == 2 and _tab_count(html, "pending_review") == 1
    assert _year_tile(html, "2018") == 1, "la persona de la carrera B no cuenta"
    assert _selected(_select(html, "tt-req-program")) == str(prog_a.id)
    sin_filtro = c.get(f"{URL}/body?status=all&cohort_id={cohort.id}").text
    assert _ids(sin_filtro) == {a1.id, a2.id, b1.id} and _kpi(sin_filtro, "Total") == 3


def test_la_jefatura_ve_todas_las_carreras_en_el_selector(client_as, make_head, make_program,
                                                          make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    prog_a = make_program("Carrera de filtro C")
    prog_b = make_program("Carrera de filtro D")
    cohort = make_cohort(status="open")

    sel = _select(client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text,
                  "tt-req-program")

    assert '<option value="">Todas las carreras</option>' in sel
    assert f'value="{prog_a.id}"' in sel and f'value="{prog_b.id}"' in sel
    assert _selected(sel) is None


def test_el_encargado_solo_elige_entre_sus_carreras(client_as, make_officer, make_program,
                                                    make_cohort):
    propia = make_program("Carrera propia del encargado de filtros")
    ajena = make_program("Carrera ajena al encargado de filtros")
    officer, _pos = make_officer([propia], perm_codes=OFFICER_LIST_PERMS)
    cohort = make_cohort(status="open")

    sel = _select(client_as(officer).get(f"{URL}/body?cohort_id={cohort.id}").text,
                  "tt-req-program")

    assert '<option value="">Todas mis carreras</option>' in sel
    assert f'value="{propia.id}"' in sel
    assert f'value="{ajena.id}"' not in sel


def test_una_carrera_ajena_en_la_url_no_muestra_nada_ajeno(client_as, db_session, make_officer,
                                                           make_program, make_cohort):
    """El encargado pide a mano la carrera de otro: cae a «todas mis carreras»,
    sin una sola fila (ni KPI) de la carrera ajena."""
    propia = make_program("Carrera propia del encargado de filtros 2")
    ajena = make_program("Carrera ajena al encargado de filtros 2")
    officer, _pos = make_officer([propia], perm_codes=OFFICER_LIST_PERMS)
    cohort = make_cohort(status="open")
    mia = _make_req(db_session, cohort, control="18552001", program=propia)
    otra = _make_req(db_session, cohort, control="18552002", program=ajena)

    html = client_as(officer).get(
        f"{URL}/body?status=all&cohort_id={cohort.id}&program={ajena.id}").text

    assert _ids(html) == {mia.id}
    assert otra.id not in _ids(html)
    assert _kpi(html, "Total") == 1
    assert _selected(_select(html, "tt-req-program")) is None
    assert '<input type="hidden" name="program" value="">' in html


def test_una_carrera_que_no_existe_cae_a_todas(client_as, db_session, make_head, make_program,
                                              make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    r1 = _make_req(db_session, cohort, control="18553001", program=make_program("Carrera E"))
    r2 = _make_req(db_session, cohort, control="18553002")

    for basura in ("999999999", "abc", "-1"):
        html = client_as(head).get(
            f"{URL}/body?status=all&cohort_id={cohort.id}&program={basura}").text
        assert _ids(html) == {r1.id, r2.id}, basura


# ---------------------------------------------------------------------------
# Año de ingreso
# ---------------------------------------------------------------------------
def _cohorte_con_anos(db_session, make_cohort):
    cohort = make_cohort(status="open")
    filas = {
        "2018": [_make_req(db_session, cohort, control="18554001"),
                 _make_req(db_session, cohort, control="C18554002", status="rejected")],
        "2021": [_make_req(db_session, cohort, control="21554003")],
        "sin-anio": [_make_req(db_session, cohort, control="XX554004")],
    }
    return cohort, filas


def test_el_ano_filtra_la_lista_y_casa_con_el_bloque_por_ano(client_as, db_session, make_head,
                                                            make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    cohort, filas = _cohorte_con_anos(db_session, make_cohort)
    c = client_as(head)

    for slug, rows in filas.items():
        html = c.get(f"{URL}/body?status=all&cohort_id={cohort.id}&year={slug}").text
        assert _ids(html) == {r.id for r in rows}, slug
        # Una solicitud por persona: el conteo de la pestaña y el de la ficha
        # del año son el mismo número.
        assert _tab_count(html, "all") == _year_tile(html, slug) == len(rows), slug
        assert _selected(_select(html, "tt-req-year")) == slug


def test_con_ano_el_bloque_y_los_kpis_siguen_mostrando_todo(client_as, db_session, make_head,
                                                           make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    cohort, _filas = _cohorte_con_anos(db_session, make_cohort)

    html = client_as(head).get(f"{URL}/body?status=all&cohort_id={cohort.id}&year=2018").text

    assert _year_tile(html, "2021") == 1 and _year_tile(html, "sin-anio") == 1
    assert _kpi(html, "Total") == 4
    assert _tab_count(html, "all") == 2


def test_las_opciones_de_ano_son_las_del_bloque(client_as, db_session, make_head, make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    cohort, _filas = _cohorte_con_anos(db_session, make_cohort)

    sel = _select(client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text, "tt-req-year")

    assert re.findall(r'<option value="([^"]*)"', sel) == ["", "2021", "2018", "sin-anio"]
    assert '<option value="sin-anio">Sin año</option>' in sel


def test_un_ano_que_no_aparece_cae_a_todos(client_as, db_session, make_head, make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    cohort, filas = _cohorte_con_anos(db_session, make_cohort)
    todas = {r.id for rows in filas.values() for r in rows}

    for basura in ("1950", "2090", "Sin año", "x"):
        html = client_as(head).get(
            f"{URL}/body?status=all&cohort_id={cohort.id}&year={basura}").text
        assert _ids(html) == todas, basura
        assert _selected(_select(html, "tt-req-year")) is None


# ---------------------------------------------------------------------------
# Los filtros viajan
# ---------------------------------------------------------------------------
def test_los_filtros_viajan_en_cada_formulario_y_en_las_pestanas(client_as, db_session,
                                                                 make_head, make_program,
                                                                 make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    prog = make_program("Carrera de filtro F")
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="18555001", program=prog)
    _make_req(db_session, cohort, control="18555002", program=prog, status="rejected")

    html = client_as(head).get(
        f"{URL}/body?status=all&cohort_id={cohort.id}&program={prog.id}&year=2018").text

    formas = re.findall(r"<form .*?</form>", html, re.S)
    assert formas, "la pestaña Todas trae formularios de fila"
    for forma in formas:
        assert f'<input type="hidden" name="program" value="{prog.id}">' in forma
        assert '<input type="hidden" name="year" value="2018">' in forma
    for key in ("pending_review", "rejected", "all"):
        boton = unescape(re.search(rf'id="tt-req-tab-{key}"[^>]*>', html, re.S).group(0))
        assert f"&program={prog.id}&year=2018" in boton, key


def test_rechazar_repinta_con_los_mismos_filtros(client_as, db_session, make_head,
                                                 make_program, make_cohort, correo_falso):
    head = make_head(perm_codes=LIST_PERMS)
    prog = make_program("Carrera de filtro G")
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="18556001", program=prog)
    queda = _make_req(db_session, cohort, control="18556002", program=prog)
    fuera_ano = _make_req(db_session, cohort, control="21556003", program=prog)
    fuera_carrera = _make_req(db_session, cohort, control="18556004")

    resp = client_as(head).post(f"{URL}/{req.id}/rechazar", data={
        "note": "Prueba de filtros.", "status": "pending_review",
        "cohort_id": str(cohort.id), "program": str(prog.id), "year": "2018"})

    assert resp.status_code == 200, resp.headers.get("X-Tt-Error")
    assert _ids(resp.text) == {queda.id}
    assert fuera_ano.id not in _ids(resp.text) and fuera_carrera.id not in _ids(resp.text)
    assert _selected(_select(resp.text, "tt-req-program")) == str(prog.id)
    assert _selected(_select(resp.text, "tt-req-year")) == "2018"


def test_deshacer_rechazo_repinta_con_los_mismos_filtros(client_as, db_session, make_head,
                                                         make_program, make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    prog = make_program("Carrera de filtro H")
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="18557001", program=prog, status="rejected",
                    review_note="Rechazo de prueba.")
    _make_req(db_session, cohort, control="18557002", status="rejected")      # otra carrera

    resp = client_as(head).post(f"{URL}/{req.id}/reabrir", data={
        "note": "Aclaró.", "status": "rejected", "cohort_id": str(cohort.id),
        "program": str(prog.id), "year": "2018"})

    assert resp.status_code == 200, resp.headers.get("X-Tt-Error")
    assert _ids(resp.text) == set(), "ya no hay rechazadas de esa carrera y ese año"
    assert _selected(_select(resp.text, "tt-req-program")) == str(prog.id)
    assert _selected(_select(resp.text, "tt-req-year")) == "2018"


def test_la_paginacion_cuenta_y_corta_con_los_filtros(db_session, make_head, make_program,
                                                      make_cohort):
    """Página de 2 sobre 5 filas que pasan los dos filtros (más 3 que no): el
    total y el corte salen del universo filtrado, en SQL."""
    from itcj2.apps.titulatec.pages.requests_admin import _body_ctx

    head = make_head(perm_codes=LIST_PERMS)
    prog = make_program("Carrera de filtro I")
    cohort = make_cohort(status="open")
    buenas = [_make_req(db_session, cohort, control=f"1855800{i}", program=prog)
              for i in range(5)]
    _make_req(db_session, cohort, control="21558010", program=prog)
    _make_req(db_session, cohort, control="18558011")
    _make_req(db_session, cohort, control="XX558012", program=prog)

    vistos = []
    for n in (1, 2, 3):
        ctx = _body_ctx(db_session, user_id=head.id, status="all", cohort_id=cohort.id,
                        page=n, per_page=2, program=str(prog.id), year="2018")
        assert ctx["page"].total == 5
        vistos += [r["id"] for r in ctx["rows"]]
    assert sorted(vistos) == sorted(r.id for r in buenas)
