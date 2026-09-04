"""Prueba de que el HARNESS sirve, no de la feature.

Estos 4 tests son el canario del conftest: si alguno se cae, lo primero que hay
que sospechar es el andamiaje (sesion, cookie, permisos), no la ruta.

Ruta elegida: `GET /titulatec/admin/documents` (`pages/documents.py:81`), porque
recorre las tres cosas que el harness debe resolver a la vez:

  1. el gate `require_page_app(..., perms=_VIEW_PERMS)` -> `Depends(get_db)`;
  2. el cuerpo, que abre su propia sesion con `SessionLocal()`
     (`documents.py:84-85`) y filtra por `officer_programs()`;
  3. `render_titulatec` -> `admin_nav_items`, que usa `with SessionLocal() as db:`
     (`nav.py:111`) y por tanto exige que el proxy soporte el context manager.

Todos los datos los crea el test. Cero dependencia de la BD de dev.
"""
from __future__ import annotations

URL = "/titulatec/admin/documents"


def test_admin_documents_200_para_actor_con_permiso(
    client_as, make_head, make_program, make_cohort, make_student,
    make_process, make_document, seed_document_types,
):
    """200 y la pagina trae los datos que sembro EL TEST.

    La asercion sobre el numero de control es la que prueba que el cuerpo de la
    ruta corre contra la sesion del test: un control `99xxxxxx` no existe en la
    BD de dev. Si solo estuviera puesto `dependency_overrides[get_db]`, la ruta
    autorizaria bien y devolveria la bandeja REAL, sin este alumno.
    """
    seed_document_types()
    head = make_head()
    program = make_program("Ingenieria Ficticia A")
    cohort = make_cohort()
    student = make_student(control_number="99000123",
                           first_name="ALUMNA", last_name="INVENTADA")
    proc = make_process(student, cohort=cohort, program=program)
    make_document(proc, type_code="birth_certificate", review_status="pending")

    resp = client_as(head).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "99000123" in resp.text
    assert "INVENTADA" in resp.text


def test_admin_documents_403_sin_el_permiso_de_la_pagina(
    client_as, make_app_user_without_perms,
):
    """Con acceso a la app pero sin `document.page.list` -> PageForbidden.

    Cubre la rama `has_app_access=True` de `require_page_app`
    (`dependencies.py:133-137`).
    """
    resp = client_as(make_app_user_without_perms()).get(URL)

    assert resp.status_code == 403, resp.text[:500]


def test_admin_documents_403_sin_acceso_a_la_app(client_as, make_outsider, titulatec_app):
    """Sin ninguna asignacion en titulatec -> PageForbidden(has_app_access=False).

    `titulatec_app` va explicito: sin la fila de `core_apps`, `get_or_404_app`
    lanzaria 404 y el test pasaria por la razon equivocada.
    """
    resp = client_as(make_outsider()).get(URL)

    assert resp.status_code == 403, resp.text[:500]


def test_admin_documents_respeta_el_scope_por_carrera(
    client_as, make_officer, make_program, make_cohort, make_student,
    make_process, make_document, seed_document_types,
):
    """El encargado de la carrera A no ve al alumno de la carrera B.

    `officer_programs()` (`scope_service.py:32`) corre DENTRO del cuerpo de la
    ruta, con la sesion que abre `SessionLocal()`. Sin el parcheo, la consulta
    de `core_program_positions` iria contra la BD de dev y el filtro daria un
    resultado ajeno al test.
    """
    seed_document_types()
    prog_a = make_program("Ingenieria Ficticia A")
    prog_b = make_program("Ingenieria Ficticia B")
    cohort = make_cohort()
    officer, _pos = make_officer([prog_a])

    student_a = make_student(control_number="99000201", last_name="DENTRODESCOPE")
    student_b = make_student(control_number="99000202", last_name="FUERADESCOPE")
    proc_a = make_process(student_a, cohort=cohort, program=prog_a)
    proc_b = make_process(student_b, cohort=cohort, program=prog_b)
    make_document(proc_a)
    make_document(proc_b)

    resp = client_as(officer).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "99000201" in resp.text
    assert "99000202" not in resp.text
