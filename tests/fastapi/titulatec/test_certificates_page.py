"""Página «Folios» (`pages/certificates_admin.py`; antes «Constancias»).

Desde `2026-10-05-titulatec-folios-design.md` §3.6 la página es la tabla de
folios con buscador (`list_folios`, pestañas por `kind`, chips de estado,
paginación) y, SOLO con el switch de impresión encendido (`printing_on`), debajo
va la parte de impresión de la ronda del 2026-10-01/02, que se describe en el
resto de este docstring: el bloque «Pestaña «Folios»» de más abajo cubre lo
nuevo, y las pruebas de lotes/PDF/«Por imprimir» piden `printing_on` y afirman
lo mismo que antes. Con el switch apagado, lote y PDF dan 404 y ninguna vista
menciona la impresión.

Parte de impresión (switch encendido) -- El Centro de Información (no adeudo de biblioteca) y Gestión Tecnológica y
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
(2 o 3 por hoja, `por_hoja` como filtro de vista); Tarea 2 §2 (E6/E7) y
§3.2/§3.5 -el `<details>` plegado de «Por imprimir» (FIFO, con ids
`tt-cert-pending-{kind}`/`-row-{id}`) y la sección «Anuladas después de
imprimir», que solo sale cuando hay filas (`tt-cert-voided-{kind}`/
`-row-{number}`)-. Estas pruebas cubren la RUTA (permisos de página vs.
permiso de imprimir por tipo, 404 vs 403, el PDF, la cuenta de pendientes,
las dos listas nuevas); el motor en sí (numeración, anulación, lotes,
`print_status_map`/`voided_after_print`) ya lo cubre
`test_certificate_service.py` (Tarea 3/Tarea 2) y el PDF puro
`test_certificate_pdf.py`.

`make_*_cert_staff` son actores sintéticos con rol DIRECTO (`grant_user_role`),
no por puesto: el reparto puesto -> rol de producción ya lo verifica
`test_permissions_contract.py` contra el DML de `biblioteca_2026_10/`. Aquí
solo importa el CONJUNTO de permisos que el gate y el helper por tipo exigen.
"""
from __future__ import annotations

import itertools
import re
from datetime import datetime

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


# ---------------------------------------------------------------------------
# Switch de impresión APAGADO (`TITULATEC_CERTIFICATE_PRINTING=False`, el
# default; spec folios 2026-10-05 §3.5): «Generar lote» y el PDF responden 404
# ANTES de cualquier otra cosa (incluido el permiso por tipo y la existencia
# del lote), sin escribir nada. El 403 del gate de PÁGINA sigue primero: es la
# dependencia de la ruta, no su cuerpo.
# ---------------------------------------------------------------------------
def test_apagado_generar_lote_responde_404_aunque_el_actor_pueda_imprimir(
    client_as, db_session, make_both_cert_staff, make_cert_process,
):
    from itcj2.apps.titulatec.models import CertificateBatch
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    staff = make_both_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=2, actor_id=staff.id)
    lotes_antes = db_session.query(CertificateBatch).count()
    pendientes_antes = CertificateService.pending_count(db_session, "library_clearance")
    assert pendientes_antes >= 2

    resp = client_as(staff).post(
        f"{URL}/library_clearance/lote",
        data={"page_library_clearance": "1", "page_survey_release": "1"})

    assert resp.status_code == 404, resp.text[:300]
    assert CertificateService.pending_count(db_session, "library_clearance") == pendientes_antes
    assert db_session.query(CertificateBatch).count() == lotes_antes, "no escribió ningún lote"


def test_apagado_el_pdf_responde_404_aunque_el_lote_exista(
    client_as, db_session, make_both_cert_staff, make_cert_process,
):
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    staff = make_both_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=1, actor_id=staff.id)
    batch = CertificateService.create_batch(db_session, kind="library_clearance",
                                            actor_id=staff.id)

    resp = client_as(staff).get(f"{URL}/lotes/{batch.id}.pdf")

    assert resp.status_code == 404, resp.text[:300]


def test_apagado_lote_y_pdf_de_un_id_cualquiera_responden_404(client_as, make_both_cert_staff):
    """Los dos ejemplos literales de la spec: el 404 NO depende de que el
    lote o el `kind` existan."""
    staff = make_both_cert_staff()

    resp_lote = client_as(staff).post(f"{URL}/library_clearance/lote", data={})
    resp_pdf = client_as(staff).get(f"{URL}/lotes/1.pdf")

    assert resp_lote.status_code == 404, resp_lote.text[:300]
    assert resp_pdf.status_code == 404, resp_pdf.text[:300]


def test_encendido_el_pdf_del_lote_sigue_respondiendo_200(
    client_as, db_session, printing_on, make_both_cert_staff, make_cert_process,
):
    """Control positivo de los 404 de arriba: la MISMA petición, con el switch
    encendido, funciona."""
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    staff = make_both_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=1, actor_id=staff.id)
    batch = CertificateService.create_batch(db_session, kind="library_clearance",
                                            actor_id=staff.id)

    resp = client_as(staff).get(f"{URL}/lotes/{batch.id}.pdf")

    assert resp.status_code == 200, resp.text[:300]
    assert resp.headers["content-type"] == "application/pdf"


def test_el_menu_solo_muestra_folios_con_el_permiso(
    client_as, make_head, make_library_cert_staff,
):
    sin_permiso = client_as(make_head()).get("/titulatec/admin/documents")
    assert sin_permiso.status_code == 200, sin_permiso.text[:500]
    assert "/titulatec/admin/constancias" not in sin_permiso.text

    con_permiso = client_as(make_library_cert_staff()).get(URL)
    assert con_permiso.status_code == 200, con_permiso.text[:500]
    assert "/titulatec/admin/constancias" in con_permiso.text
    assert "Folios" in con_permiso.text


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
@pytest.mark.usefixtures("printing_on")
def test_por_imprimir_refleja_las_pendientes(
    client_as, db_session, make_library_cert_staff, make_cert_process,
):
    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=3, actor_id=staff.id)

    resp = client_as(staff).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "Generar lote (3)" in resp.text


@pytest.mark.usefixtures("printing_on")
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


@pytest.mark.usefixtures("printing_on")
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


@pytest.mark.usefixtures("printing_on")
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


@pytest.mark.usefixtures("printing_on")
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


@pytest.mark.usefixtures("printing_on")
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


@pytest.mark.usefixtures("printing_on")
def test_hx_confirm_usa_el_articulo_las_en_plural(
    client_as, db_session, make_library_cert_staff, make_cert_process,
):
    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=2, actor_id=staff.id)

    resp = client_as(staff).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "con las 2 constancias por imprimir" in resp.text


@pytest.mark.usefixtures("printing_on")
def test_create_batch_resuelve_kinds_imprimibles_una_sola_vez(
    client_as, db_session, make_library_cert_staff, make_cert_process, monkeypatch,
):
    """m29: `create_batch` llamaba `_visible_kinds` (-> 3 SELECT de
    permisos vía `get_user_permissions_for_app`/`effective_perm_set`, sin
    caché) DOS veces -- una para el 404 por `kind` ajeno, otra DENTRO de
    `_body_ctx` al repintar el parcial. `_body_ctx` ahora acepta `kinds` ya
    resuelto y `create_batch` se lo pasa.

    Se cuenta `_visible_kinds` (el helper de ESTE módulo), no
    `get_user_permissions_for_app` directo: la misma petición también pasa
    por `require_page_app` (gate de página, vía `cached_perms`) y por
    `render_titulatec` -> `admin_nav_items` (menú admin) -- las dos
    resuelven permisos de `titulatec` POR SU CUENTA, sin relación con este
    pendiente, y contarlas junto con `_visible_kinds` haría la prueba
    depender de si el caché de Redis está tibio o frío (ajeno a lo que aquí
    se arregla)."""
    import itcj2.apps.titulatec.pages.certificates_admin as certificates_admin

    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=1, actor_id=staff.id)

    llamadas = []
    original = certificates_admin._visible_kinds

    def _contador(db, user_id):
        llamadas.append(user_id)
        return original(db, user_id)

    monkeypatch.setattr(certificates_admin, "_visible_kinds", _contador)

    resp = client_as(staff).post(
        f"{URL}/library_clearance/lote",
        data={"page_library_clearance": "1", "page_survey_release": "1"})

    assert resp.status_code == 200, resp.text[:500]
    assert len(llamadas) == 1, f"_visible_kinds se llamó {len(llamadas)} veces, se esperaba 1"


@pytest.mark.usefixtures("printing_on")
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


@pytest.mark.usefixtures("printing_on")
def test_generar_lote_sin_pendientes_responde_400(client_as, make_library_cert_staff):
    resp = client_as(make_library_cert_staff()).post(f"{URL}/library_clearance/lote", data={})

    assert resp.status_code == 400, resp.text[:300]
    assert resp.headers.get("X-Tt-Error")


@pytest.mark.usefixtures("printing_on")
def test_generar_lote_de_tipo_ajeno_responde_404(client_as, make_library_cert_staff):
    resp = client_as(make_library_cert_staff()).post(f"{URL}/survey_release/lote", data={})

    assert resp.status_code == 404, resp.text[:300]


@pytest.mark.usefixtures("printing_on")
def test_generar_lote_de_kind_desconocido_responde_404(client_as, make_both_cert_staff):
    resp = client_as(make_both_cert_staff()).post(f"{URL}/no_existe/lote", data={})

    assert resp.status_code == 404, resp.text[:300]


# ---------------------------------------------------------------------------
# PDF del lote
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("printing_on")
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


@pytest.mark.usefixtures("printing_on")
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


@pytest.mark.usefixtures("printing_on")
def test_pdf_de_lote_inexistente_responde_404(client_as, make_library_cert_staff):
    resp = client_as(make_library_cert_staff()).get(f"{URL}/lotes/999999.pdf")

    assert resp.status_code == 404, resp.text[:300]


@pytest.mark.usefixtures("printing_on")
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


@pytest.mark.usefixtures("printing_on")
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
@pytest.mark.usefixtures("printing_on")
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


@pytest.mark.usefixtures("printing_on")
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


@pytest.mark.usefixtures("printing_on")
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
# «Por imprimir» plegable y «Anuladas después de imprimir» (Tarea 2, E6/E7)
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("printing_on")
def test_detalle_de_pendientes_lista_fifo_y_sale_colapsado(
    client_as, db_session, make_library_cert_staff, make_cert_process,
):
    import re

    staff = make_library_cert_staff()
    proc1 = make_cert_process(control_number="20260001")
    proc2 = make_cert_process(control_number="20260002")
    c1 = _issue(db_session, "library_clearance", proc1, n=1, actor_id=staff.id)[0]
    c2 = _issue(db_session, "library_clearance", proc2, n=1, actor_id=staff.id)[0]

    resp = client_as(staff).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    texto = resp.text
    assert 'id="tt-cert-pending-library_clearance"' in texto
    assert "Ver quiénes (2)" in texto
    assert f'id="tt-cert-pending-row-{c1.id}"' in texto
    assert f'id="tt-cert-pending-row-{c2.id}"' in texto
    # FIFO: la primera emitida sale primero en el marcado.
    assert (texto.index(f'id="tt-cert-pending-row-{c1.id}"')
            < texto.index(f'id="tt-cert-pending-row-{c2.id}"'))
    # Colapsado por omisión: el <details> no trae el atributo `open`.
    etiqueta = re.search(
        r'<details[^>]*id="tt-cert-pending-library_clearance"[^>]*>', texto)
    assert etiqueta is not None, texto[:500]
    assert " open" not in etiqueta.group()


@pytest.mark.usefixtures("printing_on")
def test_detalle_de_pendientes_no_se_pinta_con_0_pendientes(
    client_as, make_library_cert_staff,
):
    resp = client_as(make_library_cert_staff()).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-cert-pending-library_clearance"' not in resp.text


@pytest.mark.usefixtures("printing_on")
def test_seccion_de_anuladas_no_se_pinta_sin_filas(
    client_as, db_session, make_library_cert_staff, make_cert_process,
):
    staff = make_library_cert_staff()
    proc = make_cert_process()
    _issue(db_session, "library_clearance", proc, n=1, actor_id=staff.id)   # sin lote, sin anular

    resp = client_as(staff).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-cert-voided-library_clearance"' not in resp.text


@pytest.mark.usefixtures("printing_on")
def test_seccion_de_anuladas_aparece_con_folio_lote_y_motivo(
    client_as, db_session, make_library_cert_staff, make_cert_process,
):
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    staff = make_library_cert_staff()
    proc = make_cert_process()
    cert = _issue(db_session, "library_clearance", proc, n=1, actor_id=staff.id)[0]
    batch = CertificateService.create_batch(db_session, kind="library_clearance", actor_id=staff.id)
    CertificateService.void(db_session, source_ref=cert.source_ref, actor_id=staff.id,
                            reason="se corrigió después de imprimir")

    resp = client_as(staff).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    texto = resp.text
    assert 'id="tt-cert-voided-library_clearance"' in texto
    assert f'id="tt-cert-voided-row-{cert.number}"' in texto
    assert cert.number in texto
    assert f"#{batch.id}" in texto
    assert "se corrigió después de imprimir" in texto


@pytest.mark.usefixtures("printing_on")
def test_body_ctx_agrega_pending_rows_y_voided_rows(
    db_session, make_library_cert_staff, make_cert_process,
):
    """Contrato de `_body_ctx`: cada sección trae `pending_rows` (de
    `CertificateService.pending`, aplanado a dict) y `voided_rows` (de
    `CertificateService.voided_after_print`, tal cual). `pending_count` sale
    de `len(pending_rows)` -- fix round 1: antes repetía la consulta vía
    `CertificateService.pending_count` con el MISMO predicado."""
    from itcj2.apps.titulatec.pages.certificates_admin import _body_ctx

    staff = make_library_cert_staff()
    proc = make_cert_process()
    cert = _issue(db_session, "library_clearance", proc, n=1, actor_id=staff.id)[0]

    ctx = _body_ctx(db_session, user_id=staff.id,
                    pages={"library_clearance": 1, "survey_release": 1},
                    kinds=["library_clearance"])

    seccion = ctx["sections"][0]
    assert seccion["pending_rows"] == [{
        "id": cert.id, "folio": cert.number, "egresado": cert.student_name,
        "control": cert.control_number, "carrera": cert.program_name,
        "emitida": cert.issued_at,
    }]
    assert seccion["pending_count"] == 1
    assert seccion["voided_rows"] == []


# ---------------------------------------------------------------------------
# Pestaña «Folios» (spec folios 2026-10-05 §3.6): con el switch APAGADO (el
# default) la página es la tabla de folios con buscador; la impresión de abajo
# solo existe con `printing_on`.
#
# La BD de dev es COMPARTIDA y trae constancias reales y un lote real: cada
# prueba siembra SUS filas con un semestre SINTÉTICO (`2091A`, números
# `BIB-2091A-0001`…) y un apellido-marcador `ZZ…`, y mira solo esas filas
# (`?q=<marcador>`). Nunca afirma sobre totales ni sobre «Sin folios todavía»
# de un tipo real sin aislarlo (`list_folios` parchado).
# ---------------------------------------------------------------------------
_SEM = "2091A"


@pytest.fixture()
def emitir_folio(db_session, make_user, make_student, make_process, make_cohort):
    """Fábrica de folios con egresado propio. `last` es el marcador de
    búsqueda; `issued_at`/`anular` se fijan DESPUÉS de emitir (`NOW()` es
    constante dentro de la transacción de la prueba)."""
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    cohort = make_cohort()
    emisor = make_user(first_name="EMISOR", last_name="FOLIOS")

    def _emitir(kind="library_clearance", *, last="ZZFOLIOS", first="ALUMNO",
                control=None, issued_at=None, anular=None, semester=_SEM):
        alumno = make_student(control_number=control, first_name=first, last_name=last)
        proc = make_process(alumno, cohort=cohort)
        cert = CertificateService.issue(
            db_session, kind=kind, process=proc,
            source_ref=f"{kind}:tcp{next(_ref_counter)}", actor_id=emisor.id,
            semester=semester)
        if issued_at is not None:
            cert.issued_at = issued_at
        if anular is not None:
            CertificateService.void(db_session, source_ref=cert.source_ref,
                                    actor_id=emisor.id, reason=anular)
        db_session.flush()
        return cert

    return _emitir


@pytest.fixture()
def tres_por_pagina(monkeypatch):
    """Las pruebas de ruta de las bandejas paginadas parchean `_body_ctx` con
    `per_page=3` (Ruling R2): nunca la constante."""
    import functools

    from itcj2.apps.titulatec.pages import certificates_admin

    monkeypatch.setattr(certificates_admin, "_body_ctx",
                        functools.partial(certificates_admin._body_ctx, per_page=3))


def _filas(html):
    import lxml.html

    doc = lxml.html.fromstring(html)
    return doc.xpath('//tr[starts-with(@id, "tt-folio-row-")]')


def _numeros_en(html):
    return [tr.get("id").removeprefix("tt-folio-row-") for tr in _filas(html)]


def _texto(el):
    return " ".join("".join(el.itertext()).split())


def test_biblioteca_ve_solo_bib_y_sin_pestanas(client_as, emitir_folio, make_library_cert_staff):
    bib = emitir_folio("library_clearance", last="ZZSOLOBIB")
    gtv = emitir_folio("survey_release", last="ZZSOLOBIB")

    resp = client_as(make_library_cert_staff()).get(URL, params={"q": "ZZSOLOBIB"})

    assert resp.status_code == 200, resp.text[:500]
    assert _numeros_en(resp.text) == [bib.number]
    assert gtv.number not in resp.text
    assert "No adeudo de biblioteca" in resp.text
    assert 'id="tt-folio-tab-library_clearance"' not in resp.text
    assert 'id="tt-folio-tab-survey_release"' not in resp.text


def test_gtv_ve_solo_gtv_y_sin_pestanas(client_as, emitir_folio, make_gtv_cert_staff):
    bib = emitir_folio("library_clearance", last="ZZSOLOGTV")
    gtv = emitir_folio("survey_release", last="ZZSOLOGTV")

    resp = client_as(make_gtv_cert_staff()).get(URL, params={"q": "ZZSOLOGTV"})

    assert resp.status_code == 200, resp.text[:500]
    assert _numeros_en(resp.text) == [gtv.number]
    assert bib.number not in resp.text
    assert "Liberación de encuesta de egresados" in resp.text
    assert 'id="tt-folio-tab-survey_release"' not in resp.text


def test_admin_ve_las_pestanas_y_kind_cambia_la_tabla(
    client_as, emitir_folio, make_both_cert_staff,
):
    bib = emitir_folio("library_clearance", last="ZZAMBOS")
    gtv = emitir_folio("survey_release", last="ZZAMBOS")
    staff = make_both_cert_staff()

    por_omision = client_as(staff).get(URL, params={"q": "ZZAMBOS"})
    de_gtv = client_as(staff).get(URL, params={"q": "ZZAMBOS", "kind": "survey_release"})
    de_gtv_body = client_as(staff).get(f"{URL}/body",
                                       params={"q": "ZZAMBOS", "kind": "survey_release"})

    assert por_omision.status_code == de_gtv.status_code == de_gtv_body.status_code == 200
    # Sin `kind`: el primero visible (el orden de CERT_KINDS).
    assert _numeros_en(por_omision.text) == [bib.number]
    assert _numeros_en(de_gtv.text) == [gtv.number]
    assert _numeros_en(de_gtv_body.text) == [gtv.number]
    # Las dos pestañas, con la activa marcada.
    for html in (por_omision.text, de_gtv.text):
        assert 'id="tt-folio-tab-library_clearance"' in html
        assert 'id="tt-folio-tab-survey_release"' in html
    activa = re.search(r'<button[^>]*id="tt-folio-tab-survey_release"[^>]*>', de_gtv.text).group()
    assert 'aria-current="true"' in activa
    inactiva = re.search(r'<button[^>]*id="tt-folio-tab-library_clearance"[^>]*>', de_gtv.text).group()
    assert 'aria-current' not in inactiva


@pytest.mark.parametrize("ruta", ["", "/body"])
def test_un_kind_ajeno_da_404(
    client_as, make_library_cert_staff, make_gtv_cert_staff, make_list_only_staff, ruta,
):
    """Un `kind` REAL de `CERT_KINDS` que el actor no puede ver responde
    404 -nunca 403-, igual que el lote y el PDF."""
    assert client_as(make_library_cert_staff()).get(
        f"{URL}{ruta}", params={"kind": "survey_release"}).status_code == 404
    assert client_as(make_gtv_cert_staff()).get(
        f"{URL}{ruta}", params={"kind": "library_clearance"}).status_code == 404
    assert client_as(make_list_only_staff()).get(
        f"{URL}{ruta}", params={"kind": "library_clearance"}).status_code == 404


@pytest.mark.parametrize("kind", ["", "no_existe", "LIBRARY_CLEARANCE", "survey_release;x"])
def test_un_kind_que_no_es_de_cert_kinds_cae_en_el_primero_visible(
    client_as, emitir_folio, make_library_cert_staff, kind,
):
    bib = emitir_folio("library_clearance", last="ZZKINDMALO")

    resp = client_as(make_library_cert_staff()).get(URL, params={"q": "ZZKINDMALO", "kind": kind})

    assert resp.status_code == 200, resp.text[:300]
    assert _numeros_en(resp.text) == [bib.number]


def test_sin_tipos_visibles_pinta_el_aviso_y_ninguna_tabla(client_as, make_list_only_staff):
    resp = client_as(make_list_only_staff()).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-cert-body"' in resp.text
    assert "Sin tipos asignados" in resp.text
    assert 'id="tt-folio-filters"' not in resp.text
    assert _filas(resp.text) == []


@pytest.mark.parametrize("ruta", ["", "/body"])
def test_buscador_preservado_en_la_pagina_y_en_el_body(
    client_as, make_library_cert_staff, ruta,
):
    from tests.fastapi.titulatec.paging_asserts import assert_buscador_preservado

    resp = client_as(make_library_cert_staff()).get(f"{URL}{ruta}", params={"q": "ZZBUSCA"})

    assert resp.status_code == 200, resp.text[:300]
    assert_buscador_preservado(resp.text, input_id="tt-folio-q",
                               filters_id="tt-folio-filters", q="ZZBUSCA")


def test_el_buscador_sin_busqueda_va_vacio(client_as, make_library_cert_staff):
    from tests.fastapi.titulatec.paging_asserts import assert_buscador_preservado

    resp = client_as(make_library_cert_staff()).get(URL)

    assert_buscador_preservado(resp.text, input_id="tt-folio-q",
                               filters_id="tt-folio-filters", q="")


def test_el_buscador_dispara_con_retraso_y_apunta_a_la_raiz(client_as, make_library_cert_staff):
    resp = client_as(make_library_cert_staff()).get(URL)

    caja = re.search(r'<input[^>]*id="tt-folio-q"[^>]*>', resp.text, re.S).group()
    assert 'hx-get="/titulatec/admin/constancias/body"' in caja
    assert 'hx-target="#tt-cert-body"' in caja
    assert 'hx-swap="outerHTML"' in caja
    assert "delay:400ms" in caja


def test_la_busqueda_filtra_la_tabla_y_ignora_mayusculas_y_espacios(
    client_as, emitir_folio, make_library_cert_staff,
):
    a = emitir_folio(last="ZZQUIEN", first="LUCÍA", control="Z9920001")
    emitir_folio(last="ZZOTRA", first="PEDRO", control="Z9920002")
    staff = make_library_cert_staff()

    por_nombre = client_as(staff).get(URL, params={"q": "  zzquien  "})
    por_control = client_as(staff).get(URL, params={"q": "z9920001"})
    por_folio = client_as(staff).get(URL, params={"q": f"bib-{_SEM}-0001"})

    assert _numeros_en(por_nombre.text) == [a.number]
    assert _numeros_en(por_control.text) == [a.number]
    assert a.number in _numeros_en(por_folio.text)
    assert 'value="zzquien"' in por_nombre.text       # recortado, sin espacios


def test_sin_resultados_con_busqueda_dice_sin_resultados_y_escapa_el_q(
    client_as, make_library_cert_staff,
):
    q = "<b>ZZNOHAY</b>"

    resp = client_as(make_library_cert_staff()).get(URL, params={"q": q})

    assert resp.status_code == 200, resp.text[:300]
    assert "Sin resultados para" in resp.text
    assert "&lt;b&gt;ZZNOHAY&lt;/b&gt;" in resp.text
    assert q not in resp.text                       # nunca el HTML crudo
    assert _filas(resp.text) == []
    assert 'id="tt-folio-pager"' not in resp.text
    assert "Sin folios todavía" not in resp.text


def test_sin_folios_y_sin_busqueda_dice_sin_folios_todavia(
    client_as, monkeypatch, make_library_cert_staff, make_gtv_cert_staff,
):
    """La BD de dev ya trae folios reales: se aísla parchando `list_folios`."""
    from itcj2.apps.titulatec.services.certificate_service import CertificateService
    from itcj2.apps.titulatec.utils.paging import Page

    monkeypatch.setattr(
        CertificateService, "list_folios",
        staticmethod(lambda db, **kw: Page(items=[], total=0, page=1, per_page=50)))

    for staff in (make_library_cert_staff(), make_gtv_cert_staff()):
        resp = client_as(staff).get(URL)

        assert resp.status_code == 200, resp.text[:300]
        assert "Sin folios todavía" in resp.text
        assert "Sin resultados para" not in resp.text
        assert _filas(resp.text) == []


def test_la_tabla_trae_las_columnas_y_los_datos_del_folio(
    client_as, emitir_folio, make_library_cert_staff,
):
    cert = emitir_folio(last="ZZCOLS", first="ANA", control="Z9930001",
                        issued_at=datetime(2026, 3, 7, 9, 30))

    resp = client_as(make_library_cert_staff()).get(URL, params={"q": "ZZCOLS"})

    import lxml.html
    doc = lxml.html.fromstring(resp.text)
    (tabla,) = doc.xpath('//table[@id="tt-folio-table"]')
    cabeceras = [" ".join(th.text_content().split()) for th in tabla.xpath(".//thead//th")]
    assert cabeceras == ["Folio", "Egresado", "No. de control", "Carrera", "Emitido", "Estado"]
    (fila,) = tabla.xpath('.//tr[@id="tt-folio-row-%s"]' % cert.number)
    celdas = [" ".join(td.text_content().split()) for td in fila.xpath("./td")]
    assert celdas[0] == cert.number
    assert celdas[1] == "ZZCOLS ANA"
    assert celdas[2] == "Z9930001"
    assert celdas[4] == "07/03/2026"                 # dd/mm/aaaa
    assert celdas[5] == "Vigente"


def test_una_fecha_nula_sale_con_guion(client_as, monkeypatch, make_library_cert_staff):
    from itcj2.apps.titulatec.services.certificate_service import CertificateService
    from itcj2.apps.titulatec.utils.paging import Page

    fila = {"number": "BIB-2091A-0001", "student_name": "ZZ SIN FECHA",
            "control_number": "Z9930002", "program_name": "", "issued_at": None,
            "voided_at": None, "void_reason": None}
    monkeypatch.setattr(
        CertificateService, "list_folios",
        staticmethod(lambda db, **kw: Page(items=[fila], total=1, page=1, per_page=50)))

    resp = client_as(make_library_cert_staff()).get(URL)

    assert resp.status_code == 200, resp.text[:300]
    (tr,) = _filas(resp.text)
    assert _texto(tr.xpath("./td")[4]) == "—"


def test_las_filas_van_de_la_mas_reciente_a_la_mas_vieja(
    client_as, emitir_folio, make_library_cert_staff,
):
    viejo = emitir_folio(last="ZZORDEN", issued_at=datetime(2091, 1, 10, 9, 0))
    nuevo = emitir_folio(last="ZZORDEN", issued_at=datetime(2091, 5, 20, 9, 0))
    medio = emitir_folio(last="ZZORDEN", issued_at=datetime(2091, 3, 1, 9, 0))

    resp = client_as(make_library_cert_staff()).get(URL, params={"q": "ZZORDEN"})

    assert _numeros_en(resp.text) == [nuevo.number, medio.number, viejo.number]


def test_un_folio_anulado_muestra_anulado_fecha_y_motivo(
    client_as, emitir_folio, make_library_cert_staff,
):
    vigente = emitir_folio(last="ZZANULA")
    anulado = emitir_folio(last="ZZANULA", anular="Se capturó con otro egresado")
    staff = make_library_cert_staff()

    todos = client_as(staff).get(URL, params={"q": "ZZANULA", "estado": "todos"})

    assert set(_numeros_en(todos.text)) == {vigente.number, anulado.number}
    (fila_anulada,) = [tr for tr in _filas(todos.text)
                       if tr.get("id") == f"tt-folio-row-{anulado.number}"]
    texto = _texto(fila_anulada)
    assert "Anulado" in texto
    assert "Se capturó con otro egresado" in texto
    assert anulado.voided_at.strftime("%d/%m/%Y") in texto
    (fila_vigente,) = [tr for tr in _filas(todos.text)
                       if tr.get("id") == f"tt-folio-row-{vigente.number}"]
    assert "Vigente" in _texto(fila_vigente)
    assert "Anulado" not in _texto(fila_vigente)


def test_los_estados_filtran_y_vigentes_es_el_de_omision(
    client_as, emitir_folio, make_library_cert_staff,
):
    vigente = emitir_folio(last="ZZESTADOS")
    anulado = emitir_folio(last="ZZESTADOS", anular="duplicado")
    staff = make_library_cert_staff()

    def pedir(**extra):
        return client_as(staff).get(URL, params={"q": "ZZESTADOS", **extra})

    assert _numeros_en(pedir().text) == [vigente.number]
    assert _numeros_en(pedir(estado="vigentes").text) == [vigente.number]
    assert _numeros_en(pedir(estado="anulados").text) == [anulado.number]
    assert set(_numeros_en(pedir(estado="todos").text)) == {vigente.number, anulado.number}
    # Un valor desconocido cae en vigentes, y el chip activo lo refleja.
    raro = pedir(estado="basura")
    assert _numeros_en(raro.text) == [vigente.number]
    chip = re.search(r'<button[^>]*id="tt-folio-estado-vigentes"[^>]*>', raro.text).group()
    assert 'aria-current="true"' in chip


def test_los_chips_y_las_pestanas_conservan_los_otros_filtros(
    client_as, make_both_cert_staff,
):
    resp = client_as(make_both_cert_staff()).get(
        URL, params={"q": "ZZ cons", "kind": "survey_release", "estado": "todos"})

    chip = re.search(r'<button[^>]*id="tt-folio-estado-anulados"[^>]*>', resp.text).group()
    assert "/titulatec/admin/constancias/body?" in chip
    assert "kind=survey_release" in chip and "estado=anulados" in chip
    assert "q=ZZ%20cons" in chip
    pestana = re.search(r'<button[^>]*id="tt-folio-tab-library_clearance"[^>]*>', resp.text).group()
    assert "kind=library_clearance" in pestana and "estado=todos" in pestana
    assert "q=ZZ%20cons" in pestana
    for tag in (chip, pestana):
        assert 'hx-target="#tt-cert-body"' in tag and 'hx-swap="outerHTML"' in tag
    # Los campos ocultos del contenedor de filtros: lo que `hx-include` lleva.
    caja = re.search(r'<div[^>]*id="tt-folio-filters".*?</div>', resp.text, re.S).group()
    assert 'name="kind" value="survey_release"' in caja
    assert 'name="estado" value="todos"' in caja
    assert 'name="page" value="1"' in caja


def test_la_paginacion_pagina_de_a_3_y_lleva_los_filtros(
    client_as, emitir_folio, make_library_cert_staff, tres_por_pagina,
):
    from tests.fastapi.titulatec.paging_asserts import assert_incluye_filtros

    certs = [emitir_folio(last="ZZPAG", issued_at=datetime(2091, 1, n, 9, 0))
             for n in range(1, 8)]
    esperados = [c.number for c in reversed(certs)]            # el más nuevo primero
    staff = make_library_cert_staff()

    p1 = client_as(staff).get(URL, params={"q": "ZZPAG"})
    p2 = client_as(staff).get(f"{URL}/body", params={"q": "ZZPAG", "page": "2"})
    p3 = client_as(staff).get(URL, params={"q": "ZZPAG", "page": "3"})
    p99 = client_as(staff).get(URL, params={"q": "ZZPAG", "page": "99"})
    basura = client_as(staff).get(URL, params={"q": "ZZPAG", "page": "abc"})

    assert _numeros_en(p1.text) == esperados[0:3]
    assert _numeros_en(p2.text) == esperados[3:6]
    assert _numeros_en(p3.text) == esperados[6:7]
    assert _numeros_en(p99.text) == esperados[6:7]             # fuera de rango: la última
    assert _numeros_en(basura.text) == esperados[0:3]          # basura: la primera
    assert "1–3 de 7" in p1.text and "4–6 de 7" in p2.text and "7–7 de 7" in p3.text
    siguiente = re.search(r'<button[^>]*id="tt-folio-pager-next"[^>]*>', p1.text).group()
    assert_incluye_filtros(siguiente, "tt-folio-filters")
    assert 'hx-vals=\'{"page": 2}\'' in siguiente
    assert 'hx-get="/titulatec/admin/constancias/body"' in siguiente
    assert 'hx-target="#tt-cert-body"' in siguiente
    assert "disabled" in re.search(r'<button[^>]*id="tt-folio-pager-prev"[^>]*>', p1.text).group()
    assert "disabled" in re.search(r'<button[^>]*id="tt-folio-pager-next"[^>]*>', p3.text).group()


def test_con_una_sola_pagina_el_pager_solo_muestra_el_rango(
    client_as, emitir_folio, make_library_cert_staff,
):
    emitir_folio(last="ZZUNA")

    resp = client_as(make_library_cert_staff()).get(URL, params={"q": "ZZUNA"})

    assert "1–1 de 1" in resp.text
    assert 'id="tt-folio-pager"' not in resp.text


def test_sin_impresion_no_hay_ningun_texto_de_impresion_ni_lote(
    client_as, emitir_folio, make_both_cert_staff,
):
    """Invariante 6: con el switch apagado ninguna vista menciona la
    impresión. Se barre la página completa (menú y encabezado incluidos), el
    parcial y la respuesta de otro `kind`."""
    emitir_folio("library_clearance", last="ZZSINIMP")
    emitir_folio("survey_release", last="ZZSINIMP")
    staff = make_both_cert_staff()

    paginas = [
        client_as(staff).get(URL, params={"q": "ZZSINIMP"}),
        client_as(staff).get(f"{URL}/body", params={"q": "ZZSINIMP"}),
        client_as(staff).get(URL, params={"q": "ZZSINIMP", "kind": "survey_release",
                                          "estado": "todos"}),
    ]

    for resp in paginas:
        assert resp.status_code == 200, resp.text[:300]
        minusculas = resp.text.lower()
        for rastro in ("imprim", "generar lote", "lotes", "/lote", ".pdf", "por_hoja",
                       "tt-cert-kind-", "tt-cert-pending", "tt-cert-voided", "bi-printer"):
            assert rastro not in minusculas, rastro


def test_el_menu_dice_folios_con_su_icono(client_as, make_library_cert_staff):
    import lxml.html

    resp = client_as(make_library_cert_staff()).get(URL)

    doc = lxml.html.fromstring(resp.text)
    (enlace,) = doc.xpath('//aside//a[@href="/titulatec/admin/constancias"]')
    assert " ".join(enlace.text_content().split()) == "Folios"
    assert "bi-hash" in enlace.xpath("./i")[0].get("class")
    assert not [a for a in doc.xpath("//aside//a") if "Constancias" in a.text_content()]


def test_el_titulo_y_el_encabezado_de_la_pagina(client_as, make_library_cert_staff):
    resp = client_as(make_library_cert_staff()).get(URL)

    assert "<title>Folios · TitulaTec</title>" in resp.text
    assert "Folios de liberación" in resp.text
    assert ("El folio se genera solo al liberar; búscalo por folio, número de control "
            "o nombre.") in resp.text
    assert "Constancias acumuladas por lote" not in resp.text


def test_la_pagina_y_el_body_traen_la_misma_tabla(
    client_as, emitir_folio, make_library_cert_staff,
):
    cert = emitir_folio(last="ZZMISMA")
    staff = make_library_cert_staff()

    pagina = client_as(staff).get(URL, params={"q": "ZZMISMA"})
    cuerpo = client_as(staff).get(f"{URL}/body", params={"q": "ZZMISMA"})

    assert _numeros_en(pagina.text) == _numeros_en(cuerpo.text) == [cert.number]
    assert 'id="tt-cert-body"' in cuerpo.text and "<html" not in cuerpo.text


# ---------------------------------------------------------------------------
# `_body_ctx`: el contexto de folios y, solo con el switch, las secciones de hoy
# ---------------------------------------------------------------------------
def test_body_ctx_apagado_trae_folios_y_ninguna_seccion_de_impresion(
    db_session, emitir_folio, make_both_cert_staff,
):
    from itcj2.apps.titulatec.pages.certificates_admin import _body_ctx

    cert = emitir_folio("survey_release", last="ZZCTX")
    staff = make_both_cert_staff()

    ctx = _body_ctx(db_session, user_id=staff.id, kind="survey_release", q="  ZZCTX ",
                    estado="todos", page=1, per_page=3)

    assert ctx["sections"] == []
    assert ctx["kind"] == "survey_release"
    assert [k for k, _etiqueta in ctx["tabs"]] == ["library_clearance", "survey_release"]
    assert ctx["q"] == "ZZCTX"
    assert ctx["estado"] == "todos"
    assert [r["number"] for r in ctx["rows"]] == [cert.number]
    assert ctx["pg"].per_page == 3


def test_body_ctx_sin_kind_toma_el_primero_visible_y_un_estado_raro_cae_en_vigentes(
    db_session, make_gtv_cert_staff,
):
    from itcj2.apps.titulatec.pages.certificates_admin import _body_ctx

    ctx = _body_ctx(db_session, user_id=make_gtv_cert_staff().id, estado="basura")

    assert ctx["kind"] == "survey_release"
    assert ctx["estado"] == "vigentes"
    assert len(ctx["tabs"]) == 1


def test_body_ctx_sin_kinds_no_consulta_folios(db_session, make_list_only_staff, monkeypatch):
    from itcj2.apps.titulatec.pages.certificates_admin import _body_ctx
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    def _no_debe_llamarse(*a, **kw):
        raise AssertionError("list_folios no debe correr sin ningún kind visible")

    monkeypatch.setattr(CertificateService, "list_folios", staticmethod(_no_debe_llamarse))

    ctx = _body_ctx(db_session, user_id=make_list_only_staff().id)

    assert ctx["kind"] is None and ctx["tabs"] == [] and ctx["rows"] == []
    assert ctx["pg"] is None


# ---------------------------------------------------------------------------
# Con el switch ENCENDIDO: los folios y, debajo, la impresión de hoy sin cambios
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("printing_on")
def test_encendido_la_pagina_trae_folios_y_debajo_las_secciones_de_impresion(
    client_as, emitir_folio, make_both_cert_staff,
):
    emitir_folio("library_clearance", last="ZZAMBAS")

    resp = client_as(make_both_cert_staff()).get(URL, params={"q": "ZZAMBAS"})

    assert resp.status_code == 200, resp.text[:300]
    texto = resp.text
    assert 'id="tt-folio-filters"' in texto and 'id="tt-folio-table"' in texto
    for kind in ("library_clearance", "survey_release"):
        assert f'id="tt-cert-kind-{kind}"' in texto
    assert "Por imprimir" in texto and "Generar lote" in texto
    # La impresión va DEBAJO de la tabla de folios.
    assert texto.index('id="tt-folio-table"') < texto.index('id="tt-cert-kind-library_clearance"')
    # Una sola raíz, sin ids repetidos entre las dos partes.
    assert texto.count('id="tt-cert-body"') == 1


@pytest.mark.usefixtures("printing_on")
def test_encendido_el_body_tambien_trae_las_dos_partes(client_as, make_library_cert_staff):
    resp = client_as(make_library_cert_staff()).get(f"{URL}/body")

    assert resp.status_code == 200, resp.text[:300]
    assert 'id="tt-folio-filters"' in resp.text
    assert 'id="tt-cert-kind-library_clearance"' in resp.text
    assert 'id="tt-cert-kind-survey_release"' not in resp.text


@pytest.mark.usefixtures("printing_on")
def test_body_ctx_encendido_trae_las_secciones_de_impresion(db_session, make_both_cert_staff):
    from itcj2.apps.titulatec.pages.certificates_admin import _body_ctx

    ctx = _body_ctx(db_session, user_id=make_both_cert_staff().id)

    assert [s["kind"] for s in ctx["sections"]] == ["library_clearance", "survey_release"]
    assert ctx["kind"] == "library_clearance"


@pytest.mark.usefixtures("printing_on")
def test_los_enlaces_de_impresion_conservan_los_filtros_de_folios(
    client_as, emitir_folio, make_both_cert_staff,
):
    """Regla 3 de §18: una acción de la página re-pinta la MISMA vista.
    «Generar lote» y «Lotes» incluyen `#tt-folio-filters`."""
    emitir_folio("library_clearance", last="ZZLOTEFIL")

    resp = client_as(make_both_cert_staff()).get(URL, params={"q": "ZZLOTEFIL"})

    formulario = re.search(
        r'<form[^>]*hx-post="/titulatec/admin/constancias/library_clearance/lote"[^>]*>',
        resp.text, re.S).group()
    assert 'hx-include="#tt-folio-filters"' in formulario


@pytest.mark.usefixtures("printing_on")
def test_generar_lote_repinta_la_misma_vista_de_folios(
    client_as, db_session, emitir_folio, make_both_cert_staff,
):
    from tests.fastapi.titulatec.paging_asserts import assert_buscador_preservado

    emitir_folio("library_clearance", last="ZZREPINTA")
    gtv = emitir_folio("survey_release", last="ZZREPINTA")
    staff = make_both_cert_staff()

    resp = client_as(staff).post(
        f"{URL}/library_clearance/lote",
        data={"page_library_clearance": "1", "page_survey_release": "1",
              "kind": "survey_release", "q": "ZZREPINTA", "estado": "todos", "page": "1"})

    assert resp.status_code == 200, resp.text[:500]
    # El lote se creó y la parte de impresión sigue ahí...
    assert "Generar lote (0)" in resp.text and 'target="_blank"' in resp.text
    # ...y la tabla de folios es la MISMA que el actor tenía: pestaña, búsqueda y estado.
    assert _numeros_en(resp.text) == [gtv.number]
    assert_buscador_preservado(resp.text, input_id="tt-folio-q",
                               filters_id="tt-folio-filters", q="ZZREPINTA")
    chip = re.search(r'<button[^>]*id="tt-folio-estado-todos"[^>]*>', resp.text).group()
    assert 'aria-current="true"' in chip


@pytest.mark.usefixtures("printing_on")
def test_generar_lote_sin_vista_previa_cae_en_los_valores_de_omision(
    client_as, emitir_folio, make_library_cert_staff,
):
    """Un formulario viejo (o escrito a mano) sin `kind`/`q`/`estado`/`page`
    no revienta: re-pinta el primer `kind` visible, sin búsqueda."""
    emitir_folio("library_clearance", last="ZZSINCAMPOS")

    resp = client_as(make_library_cert_staff()).post(
        f"{URL}/library_clearance/lote", data={})

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-folio-filters"' in resp.text
    caja = re.search(r'<input[^>]*id="tt-folio-q"[^>]*>', resp.text, re.S).group()
    assert 'value=""' in caja


# ---------------------------------------------------------------------------
# Estructural: sin `{process_id}` en ninguna ruta (§5 invariante 6)
# ---------------------------------------------------------------------------
def test_ninguna_ruta_lleva_process_id():
    from itcj2.apps.titulatec.pages.certificates_admin import router

    paths = [getattr(r, "path", "") for r in router.routes]
    assert paths, "el router de constancias no tiene rutas"
    assert not any("{process_id}" in p for p in paths), paths
