"""Rutas de la bandeja "Liberados" (Departamento de Titulación), a nivel HTTP.

Tarea 5 del deslinde a T-soft (spec `2026-09-21-titulatec-dpto-titulacion`,
design doc §5). Bandeja de SOLO LECTURA: la lógica de "quién está liberado"
la prueba `test_handoff_service.py` (Tarea 4) contra `HandoffService`; aquí se
prueba que la RUTA autoriza con el código correcto, pasa el alcance por
carrera tal cual y arma el CSV con la cabecera pactada.

Cada ruta lleva EXACTAMENTE el código que le toca en `perms=[...]`
(`page.list` para listar y ver el parcial, `api.export` para el CSV): la
lista es OR (`itcj2/dependencies.py:131`), así que un código de más abre la
bandeja entera a quien no debería.
"""
from __future__ import annotations

from datetime import datetime

import pytest

URL = "/titulatec/admin/liberados"

# `process.api.read.all` da alcance "ALL" (`scope_service.officer_programs`):
# sin él, un `make_head` sin puesto/ProgramPosition vería un alcance vacío y
# NINGUNA fila, con lo que los tests de "sí aparece" fallarían por la razón
# equivocada.
HANDOFF_LIST_PERMS = ("titulatec.handoff.page.list", "titulatec.process.api.read.all")
HANDOFF_EXPORT_PERMS = ("titulatec.handoff.api.export", "titulatec.process.api.read.all")

CSV_HEADER = "No. control,Nombre,Correo,Carrera,Modalidad,Convocatoria,Liberado el"


@pytest.fixture(autouse=True)
def _catalogo(seed_phase_defs):
    """`HandoffService` resuelve la fase de liberación contra el catálogo
    (`PhaseService.phase_number_for_code`); sin sembrarlo ningún proceso sale
    "liberado" y la bandeja se ve vacía por la razón equivocada."""
    seed_phase_defs()


def _release(db_session, process, when):
    """Marca la fase 2 (`review_appointment`) del proceso como aprobada.

    Mismo criterio que `test_handoff_service.py`: es la ÚNICA forma válida de
    "liberar" a un egresado para efectos de esta bandeja.
    """
    from itcj2.apps.titulatec.models import ProcessPhase
    ph = (db_session.query(ProcessPhase)
          .filter_by(process_id=process.id, phase_number=2).one())
    ph.status = "approved"
    ph.completed_at = when
    db_session.flush()
    return ph


def _liberado(db_session, make_program, make_cohort, make_user, make_process, *,
             control, suffix="", when=None):
    """Arma un egresado YA liberado, en su propia carrera/convocatoria (aislado
    de lo que ya traiga la BD de dev)."""
    program = make_program(f"Ingenieria Liberados {suffix or control}")
    cohort = make_cohort()
    student = make_user(first_name="EGRESADA", last_name="LIBERADA",
                        control_number=control)
    proc = make_process(student, cohort=cohort, program=program, current_phase=1)
    _release(db_session, proc, when or datetime(2026, 1, 20, 9, 0))
    return proc, program, cohort, student


# ---------------------------------------------------------------------------
# Autorización
# ---------------------------------------------------------------------------
def test_sin_el_permiso_de_la_pagina_no_se_abre(client_as, make_app_user_without_perms):
    resp = client_as(make_app_user_without_perms()).get(URL)

    assert resp.status_code == 403, resp.text[:300]


def test_sin_acceso_a_la_app_403(client_as, make_outsider, titulatec_app):
    resp = client_as(make_outsider()).get(URL)

    assert resp.status_code == 403, resp.text[:300]


def test_export_csv_sin_el_permiso_de_exportacion_se_rechaza(client_as, make_head):
    """`perms=[...]` es OR: `handoff.page.list` NO alcanza para exportar."""
    head = make_head(perm_codes=("titulatec.handoff.page.list",))

    resp = client_as(head).get(f"{URL}/export.csv")

    assert resp.status_code == 403, resp.text[:300]


def test_solo_api_export_no_basta_para_ver_la_pagina_ni_el_parcial(client_as, make_head):
    """Simétrico del test anterior: `handoff.api.export` es un código
    EXCLUSIVO del CSV, no abre la bandeja ni su parcial. `perms=[...]` es OR
    dentro de CADA ruta, no una unión entre rutas distintas
    (`itcj2/dependencies.py:131-136`)."""
    head = make_head(perm_codes=("titulatec.handoff.api.export",))

    resp_pagina = client_as(head).get(URL)
    resp_body = client_as(head).get(f"{URL}/body")

    assert resp_pagina.status_code == 403, resp_pagina.text[:300]
    assert resp_body.status_code == 403, resp_body.text[:300]


# ---------------------------------------------------------------------------
# Bandeja: filas, criterio de liberación, alcance
# ---------------------------------------------------------------------------
def test_la_bandeja_lista_al_egresado_liberado(
    client_as, db_session, make_head, make_program, make_cohort, make_user, make_process,
):
    head = make_head(perm_codes=HANDOFF_LIST_PERMS)
    _proc, program, cohort, _student = _liberado(
        db_session, make_program, make_cohort, make_user, make_process, control="99700001")

    resp = client_as(head).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "99700001" in resp.text
    assert "EGRESADA LIBERADA" in resp.text
    assert program.name in resp.text
    assert cohort.name in resp.text


def test_el_no_liberado_no_aparece(
    client_as, db_session, make_head, make_program, make_cohort, make_user, make_process,
):
    """Solo `ProcessPhase(2).status == 'approved'` cuenta como liberado (D2 del
    diseño): `current_phase=2` deja esa fase en `in_progress`, sin aprobar."""
    head = make_head(perm_codes=HANDOFF_LIST_PERMS)
    program = make_program("Ingenieria Sin Liberar")
    cohort = make_cohort()
    pendiente = make_user(first_name="AUN", last_name="PENDIENTE", control_number="99700002")
    make_process(pendiente, cohort=cohort, program=program, current_phase=2)

    resp = client_as(head).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "99700002" not in resp.text


def test_respeta_el_alcance_por_carrera(
    client_as, db_session, make_officer, make_program, make_cohort, make_user, make_process,
):
    prog_a = make_program("Ingenieria Alcance A")
    prog_b = make_program("Ingenieria Alcance B")
    cohort = make_cohort()
    officer, _pos = make_officer([prog_a], perm_codes=("titulatec.handoff.page.list",))
    alumno_a = make_user(first_name="DENTRO", last_name="DEALCANCE", control_number="99700005")
    alumno_b = make_user(first_name="FUERA", last_name="DEALCANCE", control_number="99700006")
    proc_a = make_process(alumno_a, cohort=cohort, program=prog_a, current_phase=1)
    proc_b = make_process(alumno_b, cohort=cohort, program=prog_b, current_phase=1)
    _release(db_session, proc_a, datetime(2026, 1, 20, 9, 0))
    _release(db_session, proc_b, datetime(2026, 1, 20, 9, 0))

    resp = client_as(officer).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "99700005" in resp.text
    assert "99700006" not in resp.text


def test_alcance_vacio_no_revienta_y_no_trae_filas_ajenas(
    client_as, db_session, make_user, make_role, grant_user_role,
    make_program, make_cohort, make_process,
):
    """Permiso de la bandeja SIN ninguna carrera asignada: alcance vacío
    (`officer_programs` falla cerrado). La página debe responder 200 con la
    tarjeta "Sin alcance" y el formulario de filtros OCULTO -- nunca la
    bandeja completa de "ALL". Se siembra un egresado liberado REAL, ajeno al
    actor: si la rama fail-closed se rompiera (p. ej. `officer_programs`
    devolviendo "ALL" por error), ese control number es justo lo que se
    filtraría, y las tres aserciones de abajo lo atrapan.
    """
    user = make_user(first_name="SIN", last_name="CARRERAS")
    role = make_role("tt_test_handoff_sin_carreras", ("titulatec.handoff.page.list",))
    grant_user_role(user, role)
    _liberado(db_session, make_program, make_cohort, make_user, make_process,
             control="99700010")

    resp = client_as(user).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "99700010" not in resp.text
    assert "Sin alcance" in resp.text
    # Con `no_programs`, `handoff_table.html` oculta el `<form>` de filtros
    # entero (no tiene sentido ofrecer un selector de carrera vacío).
    assert 'id="tt-handoff-filters"' not in resp.text


def test_body_es_hermana_de_la_pagina_y_responde_solo_el_fragmento(
    client_as, db_session, make_head, make_program, make_cohort, make_user, make_process,
):
    head = make_head(perm_codes=HANDOFF_LIST_PERMS)
    _liberado(db_session, make_program, make_cohort, make_user, make_process,
             control="99700004")
    cli = client_as(head)

    pagina = cli.get(URL)
    body = cli.get(f"{URL}/body")

    assert pagina.status_code == 200 and body.status_code == 200, body.text[:500]
    assert 'id="tt-handoff-table"' in body.text
    assert "99700004" in body.text
    # El parcial es SOLO el fragmento de la tabla: no repite el shell admin.
    assert 'id="ttSide"' not in body.text


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
def test_export_csv_trae_cabecera_y_una_fila_por_liberado(
    client_as, db_session, make_head, make_program, make_cohort, make_user, make_process,
):
    head = make_head(perm_codes=HANDOFF_EXPORT_PERMS)
    _proc, program, cohort, _student = _liberado(
        db_session, make_program, make_cohort, make_user, make_process, control="99700007")

    resp = client_as(head).get(f"{URL}/export.csv")

    assert resp.status_code == 200, resp.text[:500]
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    cuerpo = resp.content.decode("utf-8")
    assert cuerpo.startswith("﻿")   # BOM para Excel en Windows
    primera_linea = cuerpo.lstrip("﻿").split("\r\n", 1)[0]
    assert primera_linea == CSV_HEADER
    assert "99700007" in cuerpo
    assert program.name in cuerpo
    assert cohort.name in cuerpo


def test_export_csv_respeta_el_alcance_por_carrera(
    client_as, db_session, make_officer, make_program, make_cohort, make_user, make_process,
):
    prog_a = make_program("Ingenieria Alcance CSV A")
    prog_b = make_program("Ingenieria Alcance CSV B")
    cohort = make_cohort()
    officer, _pos = make_officer([prog_a], perm_codes=("titulatec.handoff.api.export",))
    alumno_a = make_user(first_name="CSV", last_name="DENTRO", control_number="99700008")
    alumno_b = make_user(first_name="CSV", last_name="FUERA", control_number="99700009")
    proc_a = make_process(alumno_a, cohort=cohort, program=prog_a, current_phase=1)
    proc_b = make_process(alumno_b, cohort=cohort, program=prog_b, current_phase=1)
    _release(db_session, proc_a, datetime(2026, 1, 20, 9, 0))
    _release(db_session, proc_b, datetime(2026, 1, 20, 9, 0))

    resp = client_as(officer).get(f"{URL}/export.csv")

    assert resp.status_code == 200, resp.text[:500]
    cuerpo = resp.content.decode("utf-8")
    assert "99700008" in cuerpo
    assert "99700009" not in cuerpo


def test_export_csv_escapa_celdas_que_empiezan_como_formula(
    client_as, db_session, make_head, make_program, make_cohort, make_user, make_process,
):
    """Cableado REAL de `escape_formula` en este endpoint, no solo en el de
    encuestas (`test_survey_export_route.py`): un nombre puede llegar con
    `=`/`+`/`-`/`@` al frente desde la inscripción pública, y esta es la
    primera vez que ese nombre sale en un CSV de esta bandeja."""
    head = make_head(perm_codes=HANDOFF_EXPORT_PERMS)
    program = make_program("Ingenieria Formula CSV")
    cohort = make_cohort()
    alumno = make_user(first_name="=CMD('calc')", last_name="RIESGO",
                       control_number="99700012")
    proc = make_process(alumno, cohort=cohort, program=program, current_phase=1)
    _release(db_session, proc, datetime(2026, 1, 21, 9, 0))

    resp = client_as(head).get(f"{URL}/export.csv")

    assert resp.status_code == 200, resp.text[:500]
    cuerpo = resp.content.decode("utf-8")
    assert "'=CMD('calc') RIESGO" in cuerpo
    # La celda cruda NO puede aparecer sin el apóstrofo antepuesto.
    assert ",=CMD" not in cuerpo


# ---------------------------------------------------------------------------
# Menú admin (data-driven por permiso)
# ---------------------------------------------------------------------------
def test_liberados_aparece_en_el_menu_solo_con_el_permiso(client_as, make_head):
    sin_permiso = client_as(make_head()).get("/titulatec/admin/documents")
    assert sin_permiso.status_code == 200, sin_permiso.text[:500]
    assert "/titulatec/admin/liberados" not in sin_permiso.text

    con_permiso = client_as(make_head(perm_codes=HANDOFF_LIST_PERMS)).get(URL)
    assert con_permiso.status_code == 200, con_permiso.text[:500]
    assert "/titulatec/admin/liberados" in con_permiso.text
    assert "Liberados" in con_permiso.text


# ---------------------------------------------------------------------------
# Boton "Exportar CSV": solo para quien puede usarlo (arreglo A5)
# ---------------------------------------------------------------------------
def test_el_boton_de_exportar_no_se_pinta_sin_el_permiso_de_exportacion(
    client_as, make_head,
):
    """`HANDOFF_LIST_PERMS` NO incluye `handoff.api.export`: el mismo GET que
    `export.csv` exige (ver `test_export_csv_sin_el_permiso_de_exportacion_se_rechaza`,
    arriba) responderia 403 si se le diera clic. Mismo criterio que
    `can_mark_reqs` (`pages/admin.py:1285-1291`): un boton que contesta 403 es
    peor que no estar."""
    head = make_head(perm_codes=HANDOFF_LIST_PERMS)

    resp = client_as(head).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "Exportar CSV" not in resp.text
    assert "/liberados/export.csv" not in resp.text


def test_el_boton_de_exportar_se_pinta_con_el_permiso_de_exportacion(
    client_as, make_head,
):
    """Positivo de la MISMA ruta (regla de oro heredada de
    `test_student_phase_guard.py`): con el permiso, el boton SI se pinta."""
    head = make_head(perm_codes=HANDOFF_LIST_PERMS + ("titulatec.handoff.api.export",))

    resp = client_as(head).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "Exportar CSV" in resp.text
    assert "/liberados/export.csv" in resp.text


def test_buscador_preservado_y_q_viaja(
    client_as, db_session, make_head, make_program, make_cohort, make_user, make_process,
):
    """hx-preserve en el buscador: id estable, q sigue viajando por `closest form`."""
    from tests.fastapi.titulatec.paging_asserts import assert_buscador_preservado
    head = make_head(perm_codes=HANDOFF_LIST_PERMS)
    _liberado(db_session, make_program, make_cohort, make_user, make_process,
              control="99700091")
    c = client_as(head)
    for url in (URL, f"{URL}/body"):
        html = c.get(url, params={"q": "99700091"}).text
        assert_buscador_preservado(html, input_id="tt-handoff-q",
                                   filters_id="tt-handoff-filters", q="99700091",
                                   include="closest form")


# ---------------------------------------------------------------------------
# «Ver expediente» → Regresar a Liberados (spec 2026-10-07 §1.2, D1/D2)
# ---------------------------------------------------------------------------
def _ver_expediente(html, process_id):
    """El `href` de «Ver expediente» de la fila, ya desescapado."""
    import html as _html
    import re
    m = re.search(r'href="(/titulatec/admin/processes/%d\?[^"]*)"[^>]*>Ver expediente'
                  % process_id, html)
    assert m, "la fila no enlaza al expediente"
    return _html.unescape(m.group(1))


def test_ver_expediente_manda_from_con_los_filtros_y_la_pagina(
    client_as, db_session, make_head, make_program, make_cohort, make_user, make_process,
):
    """`from` = URL CANÓNICA de la pestaña (no la del parcial `/body`) con sus
    filtros y su página, para que «Regresar» devuelva aquí mismo. Se pide el
    PARCIAL para probar que tampoco él manda `/body`."""
    from urllib.parse import parse_qs, urlsplit
    head = make_head(perm_codes=HANDOFF_LIST_PERMS)
    proc, program, cohort, _s = _liberado(
        db_session, make_program, make_cohort, make_user, make_process, control="99700020")

    html = client_as(head).get(f"{URL}/body", params={
        "cohort_id": str(cohort.id), "program_id": str(program.id), "q": "99700020",
    }).text

    href = _ver_expediente(html, proc.id)
    origen = parse_qs(urlsplit(href).query)["from"][0]
    partes = urlsplit(origen)
    assert partes.path == URL, origen
    qs = parse_qs(partes.query)
    assert qs["cohort_id"] == [str(cohort.id)]
    assert qs["program_id"] == [str(program.id)]
    assert qs["q"] == ["99700020"]


def test_ver_expediente_conserva_la_pagina_si_no_es_la_primera(
    db_session, make_head, make_program, make_cohort, make_user, make_process,
):
    from urllib.parse import parse_qs, urlsplit
    head = make_head(perm_codes=HANDOFF_LIST_PERMS)
    program = make_program("Ingenieria Liberados Paginada")
    cohort = make_cohort()
    procs = []
    for i in range(3):
        alumno = make_user(first_name="PAGINA", last_name=f"N{i}",
                           control_number=f"9970003{i}")
        p = make_process(alumno, cohort=cohort, program=program, current_phase=1)
        _release(db_session, p, datetime(2026, 1, 20, 9, i))
        procs.append(p)

    # `PAGE_SIZE` queda atado como default de `_body_ctx` al importar: para
    # una página 2 con 3 filas se llama con `per_page=2` y se pinta el parcial.
    import itcj2.apps.titulatec.pages.handoff_admin as mod
    from itcj2.apps.titulatec.pages.nav import titulatec_templates
    ctx = mod._body_ctx(db_session, user_id=head.id, cohort_id=cohort.id, program_id=None,
                        modality_id=None, q=None, page=2, per_page=2)
    html = titulatec_templates.get_template(
        "titulatec/partials/handoff_table.html").render(ctx)

    (fila,) = ctx["rows"]
    origen = parse_qs(urlsplit(_ver_expediente(html, fila.process_id)).query)["from"][0]
    assert parse_qs(urlsplit(origen).query)["page"] == ["2"]


def test_servicios_escolares_ve_liberados_y_el_expediente_regresa_ahi(
    client_as, db_session, make_officer, make_program, make_cohort, make_user, make_process,
):
    """D2: el encargado de carrera (con `handoff.page.list`) ve la pestaña y,
    al abrir un expediente desde ella, «Regresar» vuelve a Liberados aunque
    también pueda abrir Procesos."""
    import re
    from tests.fastapi.titulatec.conftest import OFFICER_PERMS
    program = make_program("Ingenieria Liberados Escolares")
    cohort = make_cohort()
    officer, _pos = make_officer([program], perm_codes=OFFICER_PERMS + (
        "titulatec.handoff.page.list", "titulatec.handoff.api.export"))
    alumno = make_user(first_name="ESCOLARES", last_name="LIBERADO",
                       control_number="99700040")
    proc = make_process(alumno, cohort=cohort, program=program, current_phase=1)
    _release(db_session, proc, datetime(2026, 1, 22, 9, 0))
    cli = client_as(officer)

    lista = cli.get(URL)
    assert lista.status_code == 200, lista.text[:500]
    menu = re.search(r'<aside[^>]*id="ttSide".*?</aside>', lista.text, re.S).group(0)
    assert f'href="{URL}"' in menu and "Liberados" in menu
    exp = cli.get(_ver_expediente(lista.text, proc.id))

    assert exp.status_code == 200, exp.text[:500]
    m = re.search(r'id="exp-back"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', exp.text, re.S)
    assert m.group(1).startswith(URL)
    assert "Liberados" in m.group(2)


# ---------------------------------------------------------------------------
# Correo personal y modalidad «Sin elegir» (spec 2026-10-07 §7, D9)
# ---------------------------------------------------------------------------
def test_la_tabla_muestra_el_correo_personal_y_sin_elegir(
    client_as, db_session, make_head, make_program, make_cohort, make_user, make_process,
):
    """La fila pinta el correo PERSONAL (perfil), no el institucional, y una
    modalidad nula se lee «Sin elegir». El CSV lleva el mismo correo y la
    modalidad vacía."""
    from itcj2.core.models.student_profile import StudentProfile
    head = make_head(perm_codes=HANDOFF_LIST_PERMS + ("titulatec.handoff.api.export",))
    proc, program, cohort, alumno = _liberado(
        db_session, make_program, make_cohort, make_user, make_process, control="99700050")
    db_session.add(StudentProfile(user_id=alumno.id, contact_email="personal.50@example.invalid"))
    db_session.flush()
    cli = client_as(head)

    html = cli.get(URL, params={"q": "99700050"}).text
    csv = cli.get(f"{URL}/export.csv", params={"q": "99700050"}).content.decode("utf-8")

    import re
    fila = re.search(r'<tr id="tt-hdf-%d">.*?</tr>' % proc.id, html, re.S).group(0)
    assert "personal.50@example.invalid" in fila
    assert alumno.email not in fila
    assert "Sin elegir" in fila
    linea = [ln for ln in csv.splitlines() if "99700050" in ln][0]
    assert "personal.50@example.invalid" in linea
    assert "Sin elegir" not in linea
