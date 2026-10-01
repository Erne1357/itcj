"""Página de Constancias (`pages/certificates_admin.py`), lotes e impresión.

El Centro de Información (no adeudo de biblioteca) y Gestión Tecnológica y
Vinculación -GTV- (encuesta de egresados) comparten esta MISMA página -cada
quien ve solo los `kind` de `CERT_KINDS` que puede imprimir (D15)-: «Por
imprimir (N)» -> «Generar lote (N)» (confirmación) -> el PDF del lote (3 por
hoja carta, WeasyPrint) se abre en pestaña nueva desde un `<a target="_blank">`
plano del parcial re-pintado. «Lotes» lista los anteriores con fecha, quién,
cuántas (y cuántas anuladas) y «Ver PDF».

Spec `docs/superpowers/specs/2026-10-01-titulatec-biblioteca-caja-design.md`
§4.5 (motor de constancias / la página), D7/D15, §4.6 (permisos/menú), §5
invariantes 5 y 6 (sin `{process_id}` en estas rutas). Estas pruebas cubren
la RUTA (permisos de página vs. permiso de imprimir por tipo, 404 vs 403, el
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
    `source_ref` únicos (contador de módulo, nunca choca entre pruebas)."""
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    out = []
    for _ in range(n):
        ref = f"{kind}:{next(_ref_counter)}"
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
