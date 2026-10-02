"""Página de Constancias (`pages/certificates_admin.py`), lotes e impresión.

El Centro de Información (no adeudo de biblioteca) y Gestión Tecnológica y
Vinculación -GTV- (encuesta de egresados) comparten esta MISMA página -cada
quien ve solo los `kind` de `CERT_KINDS` que puede imprimir (D15)-: «Por
imprimir (N)» -> «Generar lote (N)» (confirmación) -> el PDF del lote (2 o 3
por hoja carta a elegir, WeasyPrint) se abre en pestaña nueva desde un
`<a target="_blank">` plano del parcial re-pintado -- dos enlaces por lote,
uno por acomodo. «Lotes» lista los anteriores con fecha, quién, cuántas (y
cuántas anuladas) y los dos «PDF · N por hoja».

Spec `docs/superpowers/specs/2026-10-01-titulatec-biblioteca-caja-design.md`
§4.5 (motor de constancias / la página), D7/D15, §4.6 (permisos/menú), §5
invariantes 5 y 6 (sin `{process_id}` en estas rutas); Tarea 1 de
`2026-10-02-titulatec-constancias-y-pendientes-design.md` §2 (E4/E8) y §3.1
(2 o 3 por hoja, `por_hoja` como filtro de vista). Estas pruebas cubren la
RUTA (permisos de página vs. permiso de imprimir por tipo, 404 vs 403, el
PDF, la cuenta de pendientes); el motor en sí (numeración, anulación, lotes)
ya lo cubre `test_certificate_service.py` (Tarea 3) y el PDF puro
`test_certificate_pdf.py`.

`make_*_cert_staff` son actores sintéticos con rol DIRECTO (`grant_user_role`),
no por puesto: el reparto puesto -> rol de producción ya lo verifica
`test_permissions_contract.py` contra el DML de `biblioteca_2026_10/`. Aquí
solo importa el CONJUNTO de permisos que el gate y el helper por tipo exigen.
"""
from __future__ import annotations

import itertools

import pytest

URL = "/titulatec/admin/constancias"

LIBRARY_PRINT_PERMS = (
    "titulatec.certificate.page.list",
    "titulatec.library_clearance.api.print_certificates",
)
GTV_PRINT_PERMS = (
    "titulatec.certificate.page.list",
    "titulatec.survey_review.api.print_certificates",
)
BOTH_PRINT_PERMS = LIBRARY_PRINT_PERMS + ("titulatec.survey_review.api.print_certificates",)
LIST_ONLY_PERMS = ("titulatec.certificate.page.list",)

_ref_counter = itertools.count(1)


def _issue(db_session, kind, proc, n=1, actor_id=1):
    """Emite `n` constancias sueltas (sin lote) de `kind` para `proc`, con
    `source_ref` únicos (contador de módulo, nunca choca entre pruebas NI con
    una fila REAL de la BD de dev compartida -- Ruling R30 #1: un origen de
    verdad siempre es `f"{kind}:{id}"` con `id` puramente numérico; el
    prefijo `tcp` deja la cadena completa imposible de igualar)."""
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    out = []
    for _ in range(n):
        ref = f"{kind}:tcp{next(_ref_counter)}"
        out.append(CertificateService.issue(db_session, kind=kind, process=proc,
                                             source_ref=ref, actor_id=actor_id))
    return out


# ---------------------------------------------------------------------------
# Actores sintéticos
# ---------------------------------------------------------------------------
@pytest.fixture()
def make_library_cert_staff(make_user, make_role, grant_user_role):
    """Centro de Información: imprime SOLO `library_clearance`."""
    def _make(first_name="BIBLIO", last_name="CONSTANCIAS"):
        user = make_user(first_name=first_name, last_name=last_name)
        role = make_role("tt_test_cert_library", LIBRARY_PRINT_PERMS)
        grant_user_role(user, role)
        return user
    return _make


@pytest.fixture()
def make_gtv_cert_staff(make_user, make_role, grant_user_role):
    """GTV: imprime SOLO `survey_release`."""
    def _make(first_name="GTV", last_name="CONSTANCIAS"):
        user = make_user(first_name=first_name, last_name=last_name)
        role = make_role("tt_test_cert_gtv", GTV_PRINT_PERMS)
        grant_user_role(user, role)
        return user
    return _make


@pytest.fixture()
def make_both_cert_staff(make_user, make_role, grant_user_role):
    """Actor con los dos permisos de imprimir (espejo de `admin`)."""
    def _make(first_name="AMBOS", last_name="CONSTANCIAS"):
        user = make_user(first_name=first_name, last_name=last_name)
        role = make_role("tt_test_cert_both", BOTH_PRINT_PERMS)
        grant_user_role(user, role)
        return user
    return _make


@pytest.fixture()
def make_list_only_staff(make_user, make_role, grant_user_role):
    """Entra a la página (`certificate.page.list`) pero no puede imprimir
    NINGÚN tipo -caso límite: ningún reparto real del DML deja a nadie así,
    pero el helper no debe asumirlo."""
    def _make(first_name="SOLO", last_name="LISTACONST"):
        user = make_user(first_name=first_name, last_name=last_name)
        role = make_role("tt_test_cert_list_only", LIST_ONLY_PERMS)
        grant_user_role(user, role)
        return user
    return _make


@pytest.fixture()
def make_cert_process(make_student, make_process, make_cohort):
    """Proceso mínimo para `CertificateService.issue` -mismo criterio que
    `escenario` de `test_certificate_service.py`: solo hace falta algo
    completo que congelar, no que tenga fases ni programa real."""
    def _make(control_number=None):
        return make_process(make_student(control_number=control_number), cohort=make_cohort())
    return _make


# ---------------------------------------------------------------------------
# Acceso a la página (gate único: `certificate.page.list`)
# ---------------------------------------------------------------------------
def test_un_outsider_no_entra(client_as, make_outsider, titulatec_app):
    """`titulatec_app` asegura la fila de `core_apps` -- en CI (réplica vacía,
    sin DML) un outsider no toca ningún fixture que la cree de rebote (a
    diferencia de `make_head`/`make_student`, vía `make_role`/
    `grant_user_role`), así que `has_any_assignment` -> `get_or_404_app`
    tronaba con 404 en vez del 403 que este test espera."""
    resp = client_as(make_outsider()).get(URL)
    assert resp.status_code == 403, resp.text[:300]


def test_un_graduate_no_entra(client_as, make_student):
    resp = client_as(make_student()).get(URL)
    assert resp.status_code == 403, resp.text[:300]


def test_sin_permiso_de_pagina_responde_403_en_lote_y_pdf(client_as, make_outsider,
                                                           titulatec_app):
    """`titulatec_app`: mismo motivo que `test_un_outsider_no_entra`."""
    outsider = make_outsider()

    resp_lote = client_as(outsider).post(f"{URL}/library_clearance/lote", data={})
    resp_pdf = client_as(outsider).get(f"{URL}/lotes/1.pdf")

    assert resp_lote.status_code == 403, resp_lote.text[:300]
    assert resp_pdf.status_code == 403, resp_pdf.text[:300]


def test_el_menu_solo_muestra_constancias_con_el_permiso(
    client_as, make_head, make_library_cert_staff,
):
    sin_permiso = client_as(make_head()).get("/titulatec/admin/documents")
    assert sin_permiso.status_code == 200, sin_permiso.text[:500]
    assert "/titulatec/admin/constancias" not in sin_permiso.text

    con_permiso = client_as(make_library_cert_staff()).get(URL)
    assert con_permiso.status_code == 200, con_permiso.text[:500]
    assert "/titulatec/admin/constancias" in con_permiso.text
    assert "Constancias" in con_permiso.text


# ---------------------------------------------------------------------------
# Kinds visibles por permiso (D15)
# ---------------------------------------------------------------------------
def test_biblioteca_solo_ve_no_adeudo(client_as, make_library_cert_staff):
    resp = client_as(make_library_cert_staff()).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "No adeudo de biblioteca" in resp.text
    assert "Liberación de encuesta" not in resp.text


def test_gtv_solo_ve_encuesta(client_as, make_gtv_cert_staff):
    resp = client_as(make_gtv_cert_staff()).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "Liberación de encuesta" in resp.text
    assert "No adeudo de biblioteca" not in resp.text


def test_actor_con_ambos_permisos_ve_las_dos_secciones(client_as, make_both_cert_staff):
    resp = client_as(make_both_cert_staff()).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "No adeudo de biblioteca" in resp.text
    assert "Liberación de encuesta" in resp.text


def test_solo_permiso_de_pagina_no_ve_ninguna_seccion(client_as, make_list_only_staff):
    resp = client_as(make_list_only_staff()).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "No adeudo de biblioteca" not in resp.text
    assert "Liberación de encuesta" not in resp.text


def test_pagina_y_body_responden_200_con_la_misma_raiz(client_as, make_library_cert_staff):
    staff = make_library_cert_staff()

    pagina = client_as(staff).get(URL)
    cuerpo = client_as(staff).get(f"{URL}/body")

    assert pagina.status_code == 200 and cuerpo.status_code == 200, (pagina.text[:300], cuerpo.text[:300])
    assert 'id="tt-cert-body"' in cuerpo.text
    assert 'id="tt-cert-body"' in pagina.text


# ---------------------------------------------------------------------------
# «Por imprimir (N)» y «Generar lote»
# ---------------------------------------------------------------------------
def test_por_imprimir_refleja_las_pendientes(
    client_as, db_session, make_library_cert_staff, make_cert_process,
):
    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=3, actor_id=staff.id)

    resp = client_as(staff).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "Generar lote (3)" in resp.text


def test_generar_lote_crea_y_vacia_por_imprimir(
    client_as, db_session, make_library_cert_staff, make_cert_process,
):
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=2, actor_id=staff.id)
    assert CertificateService.pending_count(db_session, "library_clearance") == 2

    resp = client_as(staff).post(
        f"{URL}/library_clearance/lote",
        data={"page_library_clearance": "1", "page_survey_release": "1"})

    assert resp.status_code == 200, resp.text[:500]
    assert CertificateService.pending_count(db_session, "library_clearance") == 0
    assert "Generar lote (0)" in resp.text
    assert 'target="_blank"' in resp.text
    assert ".pdf" in resp.text


def test_lote_generado_trae_los_dos_enlaces_de_pdf_y_el_de_3_va_primero(
    client_as, db_session, make_library_cert_staff, make_cert_process,
):
    """Spec §3.1 (E4): dos enlaces planos por lote, 3 por hoja primero (es el
    acomodo de siempre)."""
    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=1, actor_id=staff.id)

    resp = client_as(staff).post(
        f"{URL}/library_clearance/lote",
        data={"page_library_clearance": "1", "page_survey_release": "1"})

    assert resp.status_code == 200, resp.text[:500]
    texto = resp.text
    assert "PDF · 3 por hoja" in texto and "PDF · 2 por hoja" in texto
    assert texto.index("PDF · 3 por hoja") < texto.index("PDF · 2 por hoja")
    assert "por_hoja=3" in texto and "por_hoja=2" in texto
    assert 'target="_blank"' in texto and 'rel="noopener"' in texto


def test_generar_lote_no_duplica_ids_entre_la_tarjeta_y_la_fila(
    client_as, db_session, make_library_cert_staff, make_cert_process,
):
    """El lote recién creado sale en la tarjeta «Lote generado» Y en la
    primera fila de «Lotes» de la MISMA respuesta (`create_batch` manda ese
    lote a la página 1 de su `kind`) -- los ids de sus enlaces de PDF no deben
    chocar entre las dos secciones."""
    import re

    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=1, actor_id=staff.id)

    resp = client_as(staff).post(
        f"{URL}/library_clearance/lote",
        data={"page_library_clearance": "1", "page_survey_release": "1"})

    assert resp.status_code == 200, resp.text[:500]
    ids = re.findall(r'id="(tt-cert-(?:new-)?pdf-\d+-[23])"', resp.text)
    assert len(ids) == 4, ids              # tarjeta (2) + fila (2)
    assert len(ids) == len(set(ids)), f"ids de PDF duplicados: {ids}"


def test_cada_fila_de_lotes_trae_los_dos_enlaces_de_pdf_con_ids_estables(
    client_as, db_session, make_library_cert_staff, make_cert_process,
):
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=1, actor_id=staff.id)
    batch = CertificateService.create_batch(db_session, kind="library_clearance", actor_id=staff.id)

    resp = client_as(staff).get(f"{URL}/body")

    assert resp.status_code == 200, resp.text[:500]
    assert f'id="tt-cert-pdf-{batch.id}-3"' in resp.text
    assert f'id="tt-cert-pdf-{batch.id}-2"' in resp.text
    assert (resp.text.index(f'id="tt-cert-pdf-{batch.id}-3"')
            < resp.text.index(f'id="tt-cert-pdf-{batch.id}-2"'))


def test_hx_confirm_usa_el_articulo_la_con_una_sola_pendiente(
    client_as, db_session, make_library_cert_staff, make_cert_process,
):
    """m28: `certificates_body.html` decía «las 1 constancia» -- el artículo
    ahora concuerda con la cantidad, igual que ya hacía la «s» de plural."""
    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=1, actor_id=staff.id)

    resp = client_as(staff).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "con la 1 constancia por imprimir" in resp.text
    assert "con las 1 constancia" not in resp.text


def test_hx_confirm_usa_el_articulo_las_en_plural(
    client_as, db_session, make_library_cert_staff, make_cert_process,
):
    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=2, actor_id=staff.id)

    resp = client_as(staff).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "con las 2 constancias por imprimir" in resp.text


def test_create_batch_resuelve_kinds_imprimibles_una_sola_vez(
    client_as, db_session, make_library_cert_staff, make_cert_process, monkeypatch,
):
    """m29: `create_batch` llamaba `_printable_kinds` (-> 3 SELECT de
    permisos vía `get_user_permissions_for_app`/`effective_perm_set`, sin
    caché) DOS veces -- una para el 404 por `kind` ajeno, otra DENTRO de
    `_body_ctx` al repintar el parcial. `_body_ctx` ahora acepta `kinds` ya
    resuelto y `create_batch` se lo pasa.

    Se cuenta `_printable_kinds` (el helper de ESTE módulo), no
    `get_user_permissions_for_app` directo: la misma petición también pasa
    por `require_page_app` (gate de página, vía `cached_perms`) y por
    `render_titulatec` -> `admin_nav_items` (menú admin) -- las dos
    resuelven permisos de `titulatec` POR SU CUENTA, sin relación con este
    pendiente, y contarlas junto con `_printable_kinds` haría la prueba
    depender de si el caché de Redis está tibio o frío (ajeno a lo que aquí
    se arregla)."""
    import itcj2.apps.titulatec.pages.certificates_admin as certificates_admin

    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=1, actor_id=staff.id)

    llamadas = []
    original = certificates_admin._printable_kinds

    def _contador(db, user_id):
        llamadas.append(user_id)
        return original(db, user_id)

    monkeypatch.setattr(certificates_admin, "_printable_kinds", _contador)

    resp = client_as(staff).post(
        f"{URL}/library_clearance/lote",
        data={"page_library_clearance": "1", "page_survey_release": "1"})

    assert resp.status_code == 200, resp.text[:500]
    assert len(llamadas) == 1, f"_printable_kinds se llamó {len(llamadas)} veces, se esperaba 1"


def test_body_ctx_acepta_kinds_precalculado(db_session, make_library_cert_staff):
    """Contrato de `_body_ctx(..., kinds=None)`: si el llamador YA resolvió
    los `kind` imprimibles (como hace `create_batch`), se usan tal cual, sin
    volver a preguntar permisos."""
    from itcj2.apps.titulatec.pages.certificates_admin import _body_ctx

    staff = make_library_cert_staff()

    ctx = _body_ctx(db_session, user_id=staff.id,
                    pages={"library_clearance": 1, "survey_release": 1},
                    kinds=["library_clearance"])

    assert [s["kind"] for s in ctx["sections"]] == ["library_clearance"]


def test_generar_lote_sin_pendientes_responde_400(client_as, make_library_cert_staff):
    resp = client_as(make_library_cert_staff()).post(f"{URL}/library_clearance/lote", data={})

    assert resp.status_code == 400, resp.text[:300]
    assert resp.headers.get("X-Tt-Error")


def test_generar_lote_de_tipo_ajeno_responde_404(client_as, make_library_cert_staff):
    resp = client_as(make_library_cert_staff()).post(f"{URL}/survey_release/lote", data={})

    assert resp.status_code == 404, resp.text[:300]


def test_generar_lote_de_kind_desconocido_responde_404(client_as, make_both_cert_staff):
    resp = client_as(make_both_cert_staff()).post(f"{URL}/no_existe/lote", data={})

    assert resp.status_code == 404, resp.text[:300]


# ---------------------------------------------------------------------------
# PDF del lote
# ---------------------------------------------------------------------------
def test_pdf_del_lote_propio_responde_200_con_pdf(
    client_as, db_session, make_library_cert_staff, make_cert_process,
):
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=1, actor_id=staff.id)
    batch = CertificateService.create_batch(db_session, kind="library_clearance", actor_id=staff.id)

    resp = client_as(staff).get(f"{URL}/lotes/{batch.id}.pdf")

    assert resp.status_code == 200, resp.text[:300]
    assert resp.content[:4] == b"%PDF"
    assert resp.headers["content-type"] == "application/pdf"


def test_pdf_de_tipo_ajeno_responde_404(
    client_as, db_session, make_library_cert_staff, make_gtv_cert_staff, make_cert_process,
):
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    gtv = make_gtv_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "survey_release", proc, n=1, actor_id=gtv.id)
    batch = CertificateService.create_batch(db_session, kind="survey_release", actor_id=gtv.id)

    resp = client_as(make_library_cert_staff()).get(f"{URL}/lotes/{batch.id}.pdf")

    assert resp.status_code == 404, resp.text[:300]


def test_pdf_de_lote_inexistente_responde_404(client_as, make_library_cert_staff):
    resp = client_as(make_library_cert_staff()).get(f"{URL}/lotes/999999.pdf")

    assert resp.status_code == 404, resp.text[:300]


@pytest.mark.parametrize("por_hoja,esperado", [
    ("2", 2), ("3", 3), ("4", 3), ("abc", 3), ("", 3),
])
def test_pdf_por_hoja_200_pdf_y_el_nombre_refleja_el_acomodo_usado(
    client_as, db_session, make_library_cert_staff, make_cert_process, por_hoja, esperado,
):
    """Spec §3.1: `por_hoja` es un filtro de VISTA (como `_parse_dia` de
    Caja) -- fuera de forma (`4`, `abc`, vacío) cae en 3, nunca 400/500."""
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=1, actor_id=staff.id)
    batch = CertificateService.create_batch(db_session, kind="library_clearance", actor_id=staff.id)

    resp = client_as(staff).get(f"{URL}/lotes/{batch.id}.pdf", params={"por_hoja": por_hoja})

    assert resp.status_code == 200, resp.text[:300]
    assert resp.content[:4] == b"%PDF"
    assert f"_{esperado}xhoja.pdf" in resp.headers["content-disposition"]


def test_pdf_sin_por_hoja_en_absoluto_usa_3(
    client_as, db_session, make_library_cert_staff, make_cert_process,
):
    """Distinto del caso `por_hoja=""` de arriba: aquí el query param ni
    siquiera está presente en la URL."""
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=1, actor_id=staff.id)
    batch = CertificateService.create_batch(db_session, kind="library_clearance", actor_id=staff.id)

    resp = client_as(staff).get(f"{URL}/lotes/{batch.id}.pdf")

    assert resp.status_code == 200, resp.text[:300]
    assert "_3xhoja.pdf" in resp.headers["content-disposition"]


def test_el_pdf_del_lote_corre_en_el_threadpool_y_no_en_el_event_loop():
    """Ruling R23 (I5 de la revisión final): WeasyPrint tarda segundos con un
    lote de cientos (medido: 300 constancias = 14.6 s) y el PDF nunca se
    guarda, así que cada «Ver PDF» lo vuelve a armar. En una `async def` eso
    congelaba el event loop de un worker HTTP de TODA la plataforma; como
    `def`, FastAPI la corre en su threadpool (mismo criterio que
    `appointments.move`). El 200 + `%PDF` lo sigue fijando
    `test_pdf_del_lote_propio_responde_200_con_pdf`."""
    import inspect

    from itcj2.apps.titulatec.pages import certificates_admin

    assert not inspect.iscoroutinefunction(certificates_admin.batch_pdf), (
        "batch_pdf debe ser `def`: el render de WeasyPrint es bloqueante")
    ruta = next(r for r in certificates_admin.router.routes
                if getattr(r, "name", "") == "titulatec.pages.certificates.batch_pdf")
    assert not inspect.iscoroutinefunction(ruta.endpoint)


# ---------------------------------------------------------------------------
# «Lotes»: fecha, quién, cuántas, anuladas (Review Focus #6)
# ---------------------------------------------------------------------------
def test_lotes_lista_fecha_quien_y_cuantas(
    client_as, db_session, make_library_cert_staff, make_cert_process,
):
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=2, actor_id=staff.id)
    batch = CertificateService.create_batch(db_session, kind="library_clearance", actor_id=staff.id)

    resp = client_as(staff).get(f"{URL}/body")

    assert resp.status_code == 200, resp.text[:500]
    assert f'id="cert-batch-{batch.id}"' in resp.text
    assert staff.full_name in resp.text


def test_paginacion_de_lotes_usa_el_nombre_de_query_param_que_la_ruta_lee(
    client_as, db_session, make_library_cert_staff, make_cert_process, monkeypatch,
):
    """Regresión: `_body_url` indexaba `pages` por `kind` a secas
    (`library_clearance=N`) en vez del nombre que `GET /body` de verdad lee
    (`page_library_clearance=N`) -- el enlace «Siguientes» se veía bien pero
    no movía nada, porque la ruta ignoraba el query param en silencio."""
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    monkeypatch.setattr("itcj2.apps.titulatec.pages.certificates_admin._PAGE_SIZE", 1)
    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=1, actor_id=staff.id)
    batch1 = CertificateService.create_batch(db_session, kind="library_clearance", actor_id=staff.id)
    _issue(db_session, "library_clearance", proc, n=1, actor_id=staff.id)
    batch2 = CertificateService.create_batch(db_session, kind="library_clearance", actor_id=staff.id)

    pagina1 = client_as(staff).get(f"{URL}/body")

    assert pagina1.status_code == 200, pagina1.text[:500]
    assert f'id="cert-batch-{batch2.id}"' in pagina1.text   # más reciente primero
    assert f'id="cert-batch-{batch1.id}"' not in pagina1.text
    assert "page_library_clearance=2" in pagina1.text       # el enlace «Siguientes»

    pagina2 = client_as(staff).get(f"{URL}/body?page_library_clearance=2")

    assert pagina2.status_code == 200, pagina2.text[:500]
    assert f'id="cert-batch-{batch1.id}"' in pagina2.text
    assert f'id="cert-batch-{batch2.id}"' not in pagina2.text


def test_anuladas_se_listan_en_el_lote(
    client_as, db_session, make_library_cert_staff, make_cert_process,
):
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    staff = make_library_cert_staff()
    proc = make_cert_process()
    certs = _issue(db_session, "library_clearance", proc, n=2, actor_id=staff.id)
    batch = CertificateService.create_batch(db_session, kind="library_clearance", actor_id=staff.id)
    CertificateService.void(db_session, source_ref=certs[0].source_ref, actor_id=staff.id,
                            reason="se corrigió después de imprimir")

    resp = client_as(staff).get(f"{URL}/body")

    assert resp.status_code == 200, resp.text[:500]
    assert f'id="cert-batch-{batch.id}"' in resp.text
    assert "1 anulada" in resp.text


# ---------------------------------------------------------------------------
# Estructural: sin `{process_id}` en ninguna ruta (§5 invariante 6)
# ---------------------------------------------------------------------------
def test_ninguna_ruta_lleva_process_id():
    from itcj2.apps.titulatec.pages.certificates_admin import router

    paths = [getattr(r, "path", "") for r in router.routes]
    assert paths, "el router de constancias no tiene rutas"
    assert not any("{process_id}" in p for p in paths), paths
