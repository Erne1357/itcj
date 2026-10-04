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
from datetime import timedelta

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


@pytest.mark.parametrize("estado", ["rejected", "approved"])
def test_una_inscripcion_revocada_no_ofrece_acciones_y_se_etiqueta(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
    estado,
):
    """Revisión final (diferido de T6): con la inscripción revocada toda acción
    de GTV responde 400 (`_active_process`); la fila la conserva el historial,
    pero sin botones y con la etiqueta «Revocada»."""
    gtv = make_gtv()
    proc = make_process(make_student(control_number="99500061"), current_phase=2,
                        status="cancelled")
    review = make_survey_review(proc, status=estado, reason="Falta la constancia",
                                reviewer=gtv)

    resp = client_as(gtv).get(f"{URL}/body?status={estado}&q=99500061")

    assert resp.status_code == 200, resp.text[:500]
    marca = f'id="tt-rev-{review.id}"'
    assert marca in resp.text
    fila = resp.text.split(marca, 1)[1].split("</tr>", 1)[0]
    assert "Revocada" in re.sub(r"<[^>]+>", " ", fila).split()
    assert "hx-post" not in fila
    assert "Fase 2 liberada" not in fila


def test_una_constancia_previa_muestra_su_pildora_y_oculta_ver_respuestas(
    client_as, db_session, make_gtv, make_student, make_process,
):
    """D9 (spec `2026-10-01-titulatec-biblioteca-caja-design.md` §4.12): una
    liberación por constancia previa (`SurveyReviewService.register_prior`,
    Tarea 6) sale en «Liberadas» con la píldora «Constancia previa» -no
    «Liberada»- y SIN «Ver respuestas»: no hay `response_id`, no hay
    encuesta real detrás. Se revoca igual que cualquier otra (sin cambios en
    la ruta de `/revocar`)."""
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService
    from itcj2.core.utils.timezone import db_now

    gtv = make_gtv()
    proc = make_process(make_student(control_number="99500070"), current_phase=1)
    # R14 (fix round 1): relativa a `db_now()`, no un `date(...)` fijo -- una
    # fecha absoluta vieja de más de 365 días vence sola contra el reloj real.
    review = SurveyReviewService.register_prior(
        db_session, proc, issued_on=db_now().date() - timedelta(days=30), note=None)
    db_session.flush()

    resp = client_as(gtv).get(f"{URL}/body?status=approved&q=99500070")

    assert resp.status_code == 200, resp.text[:500]
    marca = f'id="tt-rev-{review.id}"'
    assert marca in resp.text
    fila = resp.text.split(marca, 1)[1].split("</tr>", 1)[0]
    assert "Constancia previa" in fila
    assert "Liberada</span>" not in fila
    assert "Ver respuestas" not in fila
    # Revocar sigue disponible (fase 2 en pending == can_revoke).
    assert f"{URL}/{review.id}/revocar" in fila


# ---------------------------------------------------------------------------
# Columna «Constancia» (Tarea 3, 2026-10-02-titulatec-constancias-y-pendientes
# -design.md §3.3/E1/E6): folio + si ya se imprimió, a la derecha de «Estado»
# en las 3 pestañas.
# ---------------------------------------------------------------------------
def _certs(db_session, review_id):
    from itcj2.apps.titulatec.models import Certificate
    return (db_session.query(Certificate)
            .filter_by(source_ref=f"survey_review:{review_id}")
            .order_by(Certificate.id).all())


def _fila(html, marca):
    assert marca in html, "falta la fila sembrada"
    return html.split(marca, 1)[1].split("</tr>", 1)[0]


def _celda(fila, texto):
    """El ÚNICO `<td>` de `fila` que contiene `texto`, tal cual (HTML crudo):
    acota los asserts a ESA celda -la columna «Constancia»- y no a la fila."""
    celdas = [c for c in re.findall(r"<td[^>]*>(.*?)</td>", fila, re.S) if texto in c]
    assert len(celdas) == 1, celdas
    return celdas[0]


def _visible(html):
    """El texto que se lee de un pedazo de HTML: sin etiquetas, espacios juntos."""
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def test_columna_constancia_liberada_sin_imprimir_muestra_folio_y_pildora_ambar(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

    gtv = make_gtv()
    proc = make_process(make_student(control_number="99500080"), current_phase=1)
    review = make_survey_review(proc, status="in_review")
    SurveyReviewService.approve(db_session, review.id, gtv.id)
    cert = _certs(db_session, review.id)[0]

    resp = client_as(gtv).get(f"{URL}/body?status=approved&q=99500080")

    assert resp.status_code == 200, resp.text[:500]
    fila = _fila(resp.text, f'id="tt-rev-{review.id}"')
    assert cert.number in fila
    assert "Sin imprimir" in fila
    assert "tt-pill--amber" in fila
    assert "Impresa" not in fila


def test_columna_constancia_impresa_muestra_pildora_verde_lote_y_fecha(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    from itcj2.apps.titulatec.services.certificate_service import CertificateService
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

    gtv = make_gtv()
    proc = make_process(make_student(control_number="99500081"), current_phase=1)
    review = make_survey_review(proc, status="in_review")
    SurveyReviewService.approve(db_session, review.id, gtv.id)
    cert = _certs(db_session, review.id)[0]
    batch = CertificateService.create_batch(db_session, kind="survey_release", actor_id=gtv.id)

    resp = client_as(gtv).get(f"{URL}/body?status=approved&q=99500081")

    assert resp.status_code == 200, resp.text[:500]
    fila = _fila(resp.text, f'id="tt-rev-{review.id}"')
    assert cert.number in fila
    assert "Impresa" in fila
    assert "tt-pill--success" in fila
    assert f"lote #{batch.id}" in fila
    assert batch.created_at.strftime("%d/%m/%Y") in fila


def test_columna_constancia_anulada_tras_imprimir_avisa_retirar_el_papel(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    """M1 (revisión final): sin constancia vigente ni `prior`, la celda ABRE
    con el aviso de retirar el papel -nada de un «—» suelto ni un `<br>`
    arriba-: la fila SÍ tuvo constancia, «—» decía lo contrario."""
    from itcj2.apps.titulatec.services.certificate_service import CertificateService
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

    gtv = make_gtv()
    proc = make_process(make_student(control_number="99500082"), current_phase=1)
    review = make_survey_review(proc, status="in_review")
    SurveyReviewService.approve(db_session, review.id, gtv.id)
    cert = _certs(db_session, review.id)[0]
    batch = CertificateService.create_batch(db_session, kind="survey_release", actor_id=gtv.id)

    resp_rev = client_as(gtv).post(
        f"{URL}/{review.id}/revocar",
        data={"status": "approved", "q": "", "page": "1", "reason": "se liberó por error"})
    assert resp_rev.status_code == 200, resp_rev.text[:500]
    db_session.refresh(review)
    assert review.status == "rejected"

    resp = client_as(gtv).get(f"{URL}/body?status=rejected&q=99500082")

    assert resp.status_code == 200, resp.text[:500]
    fila = _fila(resp.text, f'id="tt-rev-{review.id}"')
    assert "Anulada tras imprimir" in fila
    assert "tt-pill--danger" in fila
    assert cert.number in fila
    assert f"lote #{batch.id} — retira ese papel" in fila
    celda = _celda(fila, "Anulada tras imprimir")
    assert not celda.lstrip().startswith(("—", "<br")), celda
    assert _visible(celda).startswith("Anulada tras imprimir"), _visible(celda)


def test_columna_constancia_en_constancia_previa_no_emite_folio(
    client_as, db_session, make_gtv, make_student, make_process,
):
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService
    from itcj2.core.utils.timezone import db_now

    gtv = make_gtv()
    proc = make_process(make_student(control_number="99500083"), current_phase=1)
    review = SurveyReviewService.register_prior(
        db_session, proc, issued_on=db_now().date() - timedelta(days=30), note=None)
    db_session.flush()

    resp = client_as(gtv).get(f"{URL}/body?status=approved&q=99500083")

    assert resp.status_code == 200, resp.text[:500]
    fila = _fila(resp.text, f'id="tt-rev-{review.id}"')
    assert "Constancia previa (papel del egresado)" in fila
    assert "GTV-" not in fila


def test_columna_constancia_revocada_conserva_la_celda_impresa_sin_acciones(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    """Review Focus #5: con el proceso `cancelled` una constancia YA impresa
    sigue diciendo «Impresa» -el papel existe; Ruling R13 solo cambia la
    vigente SIN lote, prueba de abajo- y la fila sigue sin acciones."""
    from itcj2.apps.titulatec.services.certificate_service import CertificateService
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

    gtv = make_gtv()
    proc = make_process(make_student(control_number="99500084"), current_phase=2)
    review = make_survey_review(proc, status="in_review")
    SurveyReviewService.approve(db_session, review.id, gtv.id)
    CertificateService.create_batch(db_session, kind="survey_release", actor_id=gtv.id)
    proc.status = "cancelled"          # se revocó DESPUÉS de liberarse e imprimirse
    db_session.flush()

    resp = client_as(gtv).get(f"{URL}/body?status=approved&q=99500084")

    assert resp.status_code == 200, resp.text[:500]
    fila = _fila(resp.text, f'id="tt-rev-{review.id}"')
    assert "Revocada" in re.sub(r"<[^>]+>", " ", fila).split()
    assert "hx-post" not in fila
    assert "Impresa" in fila
    assert "No se imprimirá" not in fila


def test_columna_constancia_revocada_sin_imprimir_dice_que_no_se_imprimira(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    """Ruling R13 (P4 de la revisión final): la constancia VIGENTE sin lote de
    una inscripción revocada nunca entrará a un lote (`_pending_criteria`,
    Ruling R26): la celda dice «No se imprimirá» en una píldora NEUTRA, no
    «Sin imprimir» ámbar, y -Ruling R18- el motivo «inscripción revocada» va
    FUERA de la píldora, en una nota tenue que puede partirse. El folio se
    conserva."""
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

    gtv = make_gtv()
    proc = make_process(make_student(control_number="99500085"), current_phase=2)
    review = make_survey_review(proc, status="in_review")
    SurveyReviewService.approve(db_session, review.id, gtv.id)
    cert = _certs(db_session, review.id)[0]
    proc.status = "cancelled"          # se revocó con la constancia todavía sin imprimir
    db_session.flush()

    resp = client_as(gtv).get(f"{URL}/body?status=approved&q=99500085")

    assert resp.status_code == 200, resp.text[:500]
    celda = _celda(_fila(resp.text, f'id="tt-rev-{review.id}"'), cert.number)
    pildora = re.search(r'<span class="tt-pill tt-pill--neutral">(.*?)</span>', celda, re.S)
    assert pildora and _visible(pildora.group(1)) == "No se imprimirá", celda
    assert '<span class="small text-body-secondary">inscripción revocada</span>' in celda
    assert "Sin imprimir" not in celda
    assert "tt-pill--amber" not in celda


def test_columna_constancia_no_hace_una_consulta_por_fila(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    """Invariante 2: `print_status_map` agrega el estado de impresión de TODA
    la página en, cuando mucho, 2 consultas -- nunca una por fila."""
    from sqlalchemy import event

    gtv = make_gtv()
    engine = db_session.get_bind()
    consultas = []

    def _cuenta(conn, cursor, statement, *a):
        if "titulatec_certificates" in statement or "titulatec_certificate_batches" in statement:
            consultas.append(statement)

    make_survey_review(
        make_process(make_student(control_number="99500090", last_name="CONSULTAUNO"),
                    current_phase=1),
        status="in_review")
    event.listen(engine, "before_cursor_execute", _cuenta)
    try:
        resp1 = client_as(gtv).get(f"{URL}/body?status=in_review&q=CONSULTAUNO")
    finally:
        event.remove(engine, "before_cursor_execute", _cuenta)
    assert resp1.status_code == 200, resp1.text[:300]
    con_una_fila = len(consultas)

    for i in range(20):
        make_survey_review(
            make_process(make_student(control_number=f"995001{i:02d}",
                                      last_name="CONSULTAVEINTE"), current_phase=1),
            status="in_review")
    consultas.clear()
    event.listen(engine, "before_cursor_execute", _cuenta)
    try:
        resp2 = client_as(gtv).get(f"{URL}/body?status=in_review&q=CONSULTAVEINTE")
    finally:
        event.remove(engine, "before_cursor_execute", _cuenta)
    assert resp2.status_code == 200, resp2.text[:300]
    con_veinte_filas = len(consultas)

    assert "CONSULTAVEINTE" in resp2.text, "control positivo: sí se sembraron las 20"
    assert con_una_fila >= 1, "la columna debe consultar el estado de impresión"
    assert con_una_fila == con_veinte_filas, (
        f"1 fila: {con_una_fila} consultas; 20 filas: {con_veinte_filas}")


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


# ---------------------------------------------------------------------------
# Pager compartido: «1–N de T»
# ---------------------------------------------------------------------------
def test_liberaciones_muestra_rango_de_total(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
    monkeypatch,
):
    import functools
    from itcj2.apps.titulatec.pages import survey_reviews_admin

    monkeypatch.setattr(survey_reviews_admin, "_body_ctx",
                        functools.partial(survey_reviews_admin._body_ctx, per_page=2))
    for _ in range(3):
        make_survey_review(
            make_process(make_student(last_name="PAGLIBZQ"), current_phase=2),
            status="in_review")
    c = client_as(make_gtv())

    p1 = c.get(f"{URL}/body?status=in_review&q=PAGLIBZQ").text
    p2 = c.get(f"{URL}/body?status=in_review&q=PAGLIBZQ&page=2").text

    assert "1–2 de 3" in p1
    assert "3–3 de 3" in p2
    assert "Siguientes" in p1 and "Anteriores" in p2
    prev = re.search(r'<button[^>]*id="tt-liberaciones-pager-prev"[^>]*>', p2, re.S).group(0)
    assert "status=in_review" in prev and "q=PAGLIBZQ" in prev and '"page": 1' in prev


def test_buscador_preservado_y_q_viaja(
    client_as, db_session, make_gtv, make_student, make_process, make_survey_review,
):
    """hx-preserve en el buscador (mismo defecto que las bandejas nuevas):
    id estable, q sigue viajando por `closest form` y en las pestañas."""
    from tests.fastapi.titulatec.paging_asserts import assert_buscador_preservado
    proc = make_process(make_student(control_number="99500091"), current_phase=1)
    make_survey_review(proc, status="in_review")
    c = client_as(make_gtv())
    for url in (URL, f"{URL}/body"):
        html = c.get(url, params={"status": "in_review", "q": "99500091"}).text
        assert_buscador_preservado(html, input_id="tt-releases-q",
                                   filters_id="tt-releases-filters", q="99500091",
                                   include="closest form")
        tab = re.search(r'<button id="tt-rev-tab-approved"[^>]*>', html).group(0)
        assert "q=99500091" in tab
