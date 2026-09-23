"""Bandeja de liberaciones de GTV (`pages/survey_reviews_admin.py`).

GTV revisa lo que el egresado ya envió (`SurveyReview`, Tarea 2) y decide si
libera el requisito de cotejo `graduate_survey` o deja observaciones. Estas
pruebas cubren la RUTA (permisos, pestañas, formularios, códigos de error);
la máquina de estados en sí ya la cubre `test_survey_review_service.py`.

`make_gtv` es un actor sintético con rol DIRECTO (`grant_user_role`), no por
puesto: el reparto puesto -> rol de producción (Servicio Externo / jefatura
de GTV) ya lo verifica `test_permissions_contract.py` contra el DML de la
Tarea 7. Aquí solo importa el CONJUNTO de permisos que el gate exige.
"""
from __future__ import annotations

import re

import pytest

URL = "/titulatec/admin/liberaciones"

GTV_PERMS = (
    "titulatec.survey_review.page.list",
    "titulatec.survey_review.api.approve",
    "titulatec.survey_review.api.reject",
    "titulatec.survey.page.list",
)


@pytest.fixture()
def make_gtv(make_user, make_role, grant_user_role):
    """Actor sintético de GTV: rol DIRECTO con los permisos de la bandeja."""
    def _make(perm_codes=GTV_PERMS, first_name="GTV", last_name="FICTICIA"):
        user = make_user(first_name=first_name, last_name=last_name)
        role = make_role("tt_test_gtv", perm_codes)
        grant_user_role(user, role)
        return user

    return _make


def _tab_span(html, tab_id):
    """Recorta el botón de una pestaña completo, para revisar SU contador
    (y no un dígito suelto en cualquier otra parte de la página)."""
    m = re.search(r'id="%s".*?</button>' % re.escape(tab_id), html, re.S)
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------
def test_una_jefatura_de_escolares_sin_permiso_de_gtv_no_entra(client_as, make_head):
    """Medido, no asumido: `require_page_app` sin el permiso de esta página
    devuelve 403 (la jefa SÍ tiene acceso a la app, solo le falta el permiso
    de `survey_review.page.list` -> `PageForbidden(has_app_access=True)`)."""
    resp = client_as(make_head()).get(URL)

    assert resp.status_code == 403, resp.text[:300]


def test_un_graduate_no_entra(client_as, make_student):
    """El alumno de titulación (`graduate` en producción; aquí el actor
    sintético `make_student`) tampoco tiene el permiso de esta bandeja."""
    resp = client_as(make_student()).get(URL)

    assert resp.status_code == 403, resp.text[:300]


def test_menu_solo_muestra_liberaciones_con_el_permiso(client_as, make_head, make_gtv):
    sin_permiso = client_as(make_head()).get("/titulatec/admin/documents")
    assert sin_permiso.status_code == 200, sin_permiso.text[:500]
    assert "/titulatec/admin/liberaciones" not in sin_permiso.text

    con_permiso = client_as(make_gtv()).get(URL)
    assert con_permiso.status_code == 200, con_permiso.text[:500]
    assert "/titulatec/admin/liberaciones" in con_permiso.text
    assert "Liberaciones" in con_permiso.text


def test_un_actor_con_permiso_de_escolares_y_de_gtv_ve_ambos_items_del_menu(
    client_as, make_user, make_role, grant_user_role,
):
    """Spec §8: un usuario con roles/permisos de Escolares Y de GTV no pierde
    ningún item del menú (`admin_nav_items` es la UNION de lo que sus
    permisos alcanzan, no el primero que matchea -- eso solo aplica al
    ATERRIZAJE, cubierto en `test_nav_dashboard_url.py`)."""
    user = make_user(first_name="DOBLE", last_name="ROL")
    role = make_role("tt_test_escolares_y_gtv", (
        "titulatec.process.page.list",          # item "Procesos" (Escolares)
        "titulatec.survey_review.page.list",    # item "Liberaciones" (GTV)
    ))
    grant_user_role(user, role)

    resp = client_as(user).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "/titulatec/admin/processes" in resp.text
    assert "/titulatec/admin/liberaciones" in resp.text


# ---------------------------------------------------------------------------
# Bandeja: pestañas, contadores, filas, búsqueda
# ---------------------------------------------------------------------------
def test_gtv_ve_pestanas_con_contadores_y_filas(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    gtv = make_gtv()
    student = make_student(control_number="99500001", first_name="EGRESADA",
                           last_name="PRUEBA")
    proc = make_process(student, current_phase=2)
    review = make_survey_review(proc, status="in_review")

    resp = client_as(gtv).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "En revisión" in resp.text
    assert "Con observaciones" in resp.text
    assert "Liberadas" in resp.text
    # Los contadores se comparan contra `counts_by_status`, NO contra 1 y 0
    # (2026-09-18). Esta pestaña se pide SIN búsqueda, así que anuncia el total
    # GLOBAL: los absolutos daban por hecho que la base de dev no tiene ni una
    # liberación de verdad, y se pusieron rojos el día que un alumno real envió
    # su encuesta y GTV se la aprobó. Comparar contra el service prueba algo más
    # fuerte -que la pestaña imprime el conteo REAL y no un número cualquiera- y
    # deja de depender de que la base esté vacía.
    #
    # El test de más abajo que sí busca (`q=99500071`) conserva sus absolutos, y
    # debe: ahí los contadores son del conjunto FILTRADO, que el propio test
    # siembra entero.
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService
    counts = SurveyReviewService.counts_by_status(db_session)
    assert counts["in_review"] >= 1, "la solicitud sembrada tiene que contar"
    assert f'>{counts["in_review"]}<' in _tab_span(resp.text, "tt-rev-tab-in_review")
    assert f'>{counts["approved"]}<' in _tab_span(resp.text, "tt-rev-tab-approved")
    assert f'id="tt-rev-{review.id}"' in resp.text
    assert student.control_number in resp.text
    assert f"/titulatec/admin/encuestas/{review.response_id}" in resp.text


def test_body_acepta_los_mismos_query_params_que_la_pagina(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    gtv = make_gtv()
    proc = make_process(make_student(control_number="99500002"), current_phase=1)
    make_survey_review(proc, status="in_review")
    c = client_as(gtv)

    pagina = c.get(f"{URL}?status=in_review")
    cuerpo = c.get(f"{URL}/body?status=in_review")

    assert pagina.status_code == 200 and cuerpo.status_code == 200
    assert 'id="tt-releases-body"' in cuerpo.text
    assert "99500002" in pagina.text
    assert "99500002" in cuerpo.text


def test_busqueda_filtra_por_control_o_nombre(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    gtv = make_gtv()
    s1 = make_student(control_number="99500011", first_name="ANA", last_name="BUSCADA")
    s2 = make_student(control_number="99500022", first_name="LUIS", last_name="OTRO")
    make_survey_review(make_process(s1, current_phase=1), status="in_review")
    make_survey_review(make_process(s2, current_phase=1), status="in_review")

    resp = client_as(gtv).get(f"{URL}/body?status=in_review&q=99500011")

    assert resp.status_code == 200, resp.text[:500]
    assert "99500011" in resp.text
    assert "99500022" not in resp.text


def test_los_contadores_de_pestana_respetan_la_busqueda(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    """`counts_by_status` debe filtrar igual que `list_for_inbox`: sin esto,
    buscar a un alumno deja una sola fila bajo pestañas que siguen anunciando
    el total global (12/3/40)."""
    gtv = make_gtv()
    s1 = make_student(control_number="99500071", first_name="BUSCADA",
                      last_name="COINCIDE")
    s2 = make_student(control_number="99500072", first_name="OTRO",
                      last_name="ALUMNO")
    make_survey_review(make_process(s1, current_phase=1), status="in_review")
    make_survey_review(make_process(s2, current_phase=1), status="in_review")

    resp = client_as(gtv).get(f"{URL}/body?status=in_review&q=99500071")

    assert resp.status_code == 200, resp.text[:500]
    assert ">1<" in _tab_span(resp.text, "tt-rev-tab-in_review")
    assert ">0<" in _tab_span(resp.text, "tt-rev-tab-approved")
    assert ">0<" in _tab_span(resp.text, "tt-rev-tab-rejected")


def test_pestana_sin_solicitudes_muestra_bandeja_limpia(client_as, db_session, make_gtv):
    """El vacío se FABRICA, no se supone (2026-09-18).

    Antes se pedía la pestaña «Liberadas» dando por hecho que estaría vacía. En
    la base de dev hay liberaciones de verdad, así que la bandeja traía filas y
    el test se caía por el estado de los datos, no por el código. Se vacía ese
    estado dentro del savepoint —`db_session` hace rollback al terminar, así que
    la fila real no se pierde— y entonces sí se puede exigir el vacío.
    """
    from itcj2.apps.titulatec.models import SurveyReview

    db_session.query(SurveyReview).filter_by(status="approved").delete(
        synchronize_session=False)
    db_session.flush()

    resp = client_as(make_gtv()).get(f"{URL}/body?status=approved")

    assert resp.status_code == 200, resp.text[:500]
    assert "Bandeja limpia" in resp.text


def test_busqueda_sin_resultados_avisa_que_es_por_el_filtro(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    gtv = make_gtv()
    proc = make_process(make_student(control_number="99500034"), current_phase=1)
    make_survey_review(proc, status="in_review")

    resp = client_as(gtv).get(f"{URL}/body?status=in_review&q=noexiste000")

    assert resp.status_code == 200, resp.text[:500]
    assert "con ese filtro" in resp.text


def test_una_busqueda_de_solo_espacios_no_filtra_nada(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    """Resolución fijada en el brief: "   " se recorta a `None` en la ruta,
    no llega al service como patrón `ILIKE '%%'`."""
    gtv = make_gtv()
    proc = make_process(make_student(control_number="99500033"), current_phase=1)
    make_survey_review(proc, status="in_review")

    resp = client_as(gtv).get(f"{URL}/body?status=in_review&q=%20%20%20")

    assert resp.status_code == 200, resp.text[:500]
    assert "99500033" in resp.text


# ---------------------------------------------------------------------------
# Liberar / observar / revocar: caminos felices
# ---------------------------------------------------------------------------
def test_liberar_desde_en_revision_re_renderiza_la_pestana(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    gtv = make_gtv()
    proc = make_process(make_student(control_number="99500041"), current_phase=1)
    review = make_survey_review(proc, status="in_review")

    resp = client_as(gtv).post(
        f"{URL}/{review.id}/liberar",
        data={"status": "in_review", "q": "", "page": "1"})

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-releases-body"' in resp.text
    # Se liberó: ya no aparece en la pestaña "En revisión" de donde vino.
    assert f'id="tt-rev-{review.id}"' not in resp.text
    db_session.refresh(review)
    assert review.status == "approved"


def test_observar_desde_en_revision_re_renderiza_la_pestana(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    gtv = make_gtv()
    proc = make_process(make_student(control_number="99500042"), current_phase=1)
    review = make_survey_review(proc, status="in_review")

    resp = client_as(gtv).post(
        f"{URL}/{review.id}/observar",
        data={"status": "in_review", "q": "", "page": "1",
              "reason": "Falta constancia de Servicio Social"})

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-releases-body"' in resp.text
    assert f'id="tt-rev-{review.id}"' not in resp.text
    db_session.refresh(review)
    assert review.status == "rejected"
    assert review.rejection_reason == "Falta constancia de Servicio Social"


def test_revocar_una_liberacion_re_renderiza_la_pestana(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    gtv = make_gtv()
    # Fase 2 en "pending" (2 > current_phase=1): can_revoke == True.
    proc = make_process(make_student(control_number="99500043"), current_phase=1)
    review = make_survey_review(proc, status="approved", reviewer=gtv)

    resp = client_as(gtv).post(
        f"{URL}/{review.id}/revocar",
        data={"status": "approved", "q": "", "page": "1",
              "reason": "Se liberó por error"})

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-releases-body"' in resp.text
    assert f'id="tt-rev-{review.id}"' not in resp.text
    db_session.refresh(review)
    assert review.status == "rejected"
    assert review.rejection_reason == "Se liberó por error"


# ---------------------------------------------------------------------------
# Errores: 400 de regla, 404 de existencia
# ---------------------------------------------------------------------------
def test_motivo_vacio_al_observar_responde_400(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    gtv = make_gtv()
    proc = make_process(make_student(control_number="99500051"), current_phase=1)
    review = make_survey_review(proc, status="in_review")

    resp = client_as(gtv).post(
        f"{URL}/{review.id}/observar",
        data={"status": "in_review", "q": "", "page": "1", "reason": "   "})

    assert resp.status_code == 400, resp.text[:300]
    assert resp.headers.get("X-Tt-Error")
    db_session.refresh(review)
    assert review.status == "in_review"


def test_transicion_invalida_al_liberar_dos_veces_responde_400(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    gtv = make_gtv()
    proc = make_process(make_student(control_number="99500052"), current_phase=1)
    review = make_survey_review(proc, status="approved", reviewer=gtv)

    resp = client_as(gtv).post(
        f"{URL}/{review.id}/liberar",
        data={"status": "approved", "q": "", "page": "1"})

    assert resp.status_code == 400, resp.text[:300]
    assert resp.headers.get("X-Tt-Error")


def test_revocar_con_fase_2_ya_aprobada_responde_400(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    from itcj2.apps.titulatec.models import ProcessPhase

    gtv = make_gtv()
    proc = make_process(make_student(control_number="99500053"), current_phase=1)
    (db_session.query(ProcessPhase)
     .filter_by(process_id=proc.id, phase_number=2)
     .update({"status": "approved"}))
    db_session.flush()
    review = make_survey_review(proc, status="approved", reviewer=gtv)

    resp = client_as(gtv).post(
        f"{URL}/{review.id}/revocar",
        data={"status": "approved", "q": "", "page": "1", "reason": "me equivoqué"})

    assert resp.status_code == 400, resp.text[:300]
    assert resp.headers.get("X-Tt-Error")
    db_session.refresh(review)
    assert review.status == "approved"


def test_id_inexistente_responde_404(client_as, make_gtv):
    resp = client_as(make_gtv()).post(
        f"{URL}/999999/liberar", data={"status": "in_review", "q": "", "page": "1"})

    assert resp.status_code == 404, resp.text[:300]


def test_permiso_de_observar_no_alcanza_para_liberar(
    client_as, db_session, make_user, make_role, grant_user_role,
    make_student, make_process, make_survey_review,
):
    """`perms=[...]` es OR, pero cada ruta trae un SOLO código: quien solo
    puede observar/revocar (`survey_review.api.reject`) no puede liberar."""
    user = make_user(first_name="SOLO", last_name="OBSERVA")
    role = make_role("tt_test_solo_observa", (
        "titulatec.survey_review.page.list",
        "titulatec.survey_review.api.reject",
    ))
    grant_user_role(user, role)
    proc = make_process(make_student(control_number="99500054"), current_phase=1)
    review = make_survey_review(proc, status="in_review")

    resp = client_as(user).post(
        f"{URL}/{review.id}/liberar",
        data={"status": "in_review", "q": "", "page": "1"})

    assert resp.status_code == 403, resp.text[:300]
