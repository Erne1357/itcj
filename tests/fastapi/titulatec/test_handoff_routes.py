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
