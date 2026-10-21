"""Pestaña admin «Carreras por departamento» (spec 2026-10-21 fase 4 §13, R-C/R-F/R-G, Task 9).

- Corte a T-soft EXPLÍCITO en cada prueba: `corte(9)` opera la fase 4;
  `corte(3)` es producción y debe dejar la pantalla inerte (R-G).
- Departamentos y carreras SINTÉTICOS (la base de dev trae los reales): las
  pruebas solo afirman sobre sus propias filas.
"""
from __future__ import annotations

import os
from urllib.parse import unquote

import lxml.html
import pytest

from itcj2.apps.titulatec.models import DepartmentSettings, ProgramDepartment
from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog
from itcj2.apps.titulatec.services.phase_service import PhaseService
from itcj2.apps.titulatec.services.program_department_service import (
    ProgramDepartmentService,
)
from tests.fastapi.titulatec.conftest import audit_query

pytestmark = pytest.mark.usefixtures("audit_mark")

URL = "/titulatec/admin/carreras-deptos"
PAGE_PERM = "titulatec.program_department.page.list"
MANAGE_PERM = "titulatec.program_department.api.manage"

_RUN = os.getpid()
ROLE_ADMIN = f"tt_test_carr_admin_{_RUN}"
ROLE_LECTOR = f"tt_test_carr_lector_{_RUN}"


@pytest.fixture()
def corte(monkeypatch):
    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


@pytest.fixture()
def esc(db_session, corte, seed_phase_defs, make_department, make_program,
        make_program_department, make_position, make_user, make_role, grant_user_role):
    """Padre `sub_academic`, dos departamentos hijos, una carrera mapeada y un admin."""
    def _build(cut=9):
        corte(cut)
        seed_phase_defs()
        padre = make_department(code="sub_academic", name="Subdirección Académica")
        dep_a = make_department(code=f"tt_test_carr_a_{_RUN}", name="Depto A de prueba",
                                parent_id=padre.id)
        dep_b = make_department(code=f"tt_test_carr_b_{_RUN}", name="Depto B de prueba",
                                parent_id=padre.id)
        fuera = make_department(code=f"tt_test_carr_x_{_RUN}", name="Depto ajeno de prueba")
        carrera = make_program(f"Ingenieria Ficticia Carreras T9 {_RUN}")
        make_program_department(carrera, dep_a, official_name="Ingeniería Ficticia")
        make_position(code=f"tt_test_pos_dest_{_RUN}", title="Destinatario de prueba")
        make_position(code=f"tt_test_pos_atn_{_RUN}", title="Atn de prueba")
        admin = make_user(first_name="ADMIN", last_name="CARRERAS")
        grant_user_role(admin, make_role(ROLE_ADMIN, (PAGE_PERM, MANAGE_PERM)))
        lector = make_user(first_name="LECTOR", last_name="CARRERAS")
        grant_user_role(lector, make_role(ROLE_LECTOR, (PAGE_PERM,)))
        return type("E", (), dict(dep_a=dep_a, dep_b=dep_b, fuera=fuera, carrera=carrera,
                                  admin=admin, lector=lector, padre=padre))
    return _build


def _hdr(resp, name):
    return unquote(resp.headers.get(name, ""))


def _fila(db, program_id):
    db.expire_all()
    return db.get(ProgramDepartment, program_id)


# ---------------------------------------------------------------------------
# Acceso y menú
# ---------------------------------------------------------------------------
def test_sin_permiso_es_403(esc, client_as, make_user):
    esc()
    otro = make_user(first_name="OTRO", last_name="SINPERMISO")
    assert client_as(otro).get(URL).status_code == 403


def test_admin_ve_la_pantalla_y_el_item_del_menu(esc, client_as):
    e = esc()
    resp = client_as(e.admin).get(URL)
    assert resp.status_code == 200, resp.text[:400]
    doc = lxml.html.fromstring(resp.text)
    items = [(a.get("hx-get"), " ".join(a.text_content().split()))
             for a in doc.xpath('//aside[@id="ttSide"]//a[@hx-get]')]
    assert (URL, "Carreras por depto") in items
    fila = doc.xpath(f'//*[@id="tt-carr-row-{e.carrera.id}"]')
    assert fila, "falta la fila de la carrera de prueba"
    opciones = [o.get("value") for o in fila[0].xpath('.//select[@name="department_id"]/option')]
    # El catálogo trae los hijos de sub_academic y NO el departamento ajeno.
    assert str(e.dep_a.id) in opciones and str(e.dep_b.id) in opciones
    assert str(e.fuera.id) not in opciones
    assert doc.xpath(f'//*[@id="tt-carr-dept-{e.dep_a.id}"]')


def test_la_pantalla_no_trae_scripts_inline(esc, client_as):
    e = esc()
    html = client_as(e.admin).get(URL).text
    cuerpo = html.split('id="tt-carr-body"', 1)[1].split("</main>", 1)[0]
    assert "<script" not in cuerpo


# ---------------------------------------------------------------------------
# Mapeo de carreras
# ---------------------------------------------------------------------------
def test_editar_el_mapeo_guarda_y_deja_bitacora(esc, client_as, db_session):
    e = esc()
    resp = client_as(e.admin).post(
        f"{URL}/programa/{e.carrera.id}",
        data={"department_id": str(e.dep_b.id), "official_name": "  Nombre   Oficial Nuevo "})
    assert resp.status_code == 200, resp.text[:400]
    assert _hdr(resp, "X-Tt-Notice") == "Carrera actualizada."
    fila = _fila(db_session, e.carrera.id)
    assert fila.department_id == e.dep_b.id
    assert fila.official_name == "Nombre Oficial Nuevo"
    assert fila.updated_by_id == e.admin.id
    reg = audit_query(db_session).filter_by(action="program_department.changed").all()
    assert len(reg) == 1
    assert reg[0].entity_id == e.carrera.id
    assert reg[0].actor_id == e.admin.id
    assert reg[0].after["official_name"] == "Nombre Oficial Nuevo"


def test_sin_cambios_no_escribe_bitacora(esc, client_as, db_session):
    e = esc()
    resp = client_as(e.admin).post(
        f"{URL}/programa/{e.carrera.id}",
        data={"department_id": str(e.dep_a.id), "official_name": "Ingeniería Ficticia"})
    assert resp.status_code == 200
    assert _hdr(resp, "X-Tt-Notice") == "Sin cambios."
    assert audit_query(db_session).filter_by(action="program_department.changed").count() == 0


def test_departamento_fuera_del_catalogo_da_400_sin_escribir(esc, client_as, db_session):
    e = esc()
    resp = client_as(e.admin).post(
        f"{URL}/programa/{e.carrera.id}",
        data={"department_id": str(e.fuera.id), "official_name": "X"})
    assert resp.status_code == 400
    assert "académico" in _hdr(resp, "X-Tt-Error")
    assert _fila(db_session, e.carrera.id).department_id == e.dep_a.id
    assert audit_query(db_session).filter_by(action="program_department.changed").count() == 0


def test_remapear_con_procesos_en_fase_4_lo_avisa_en_la_bitacora(
        esc, client_as, db_session, seed_document_types, make_cohort, make_student, make_process):
    e = esc()
    seed_document_types()
    alumno = make_student(first_name="ALUMNO", last_name="CARRERAS")
    make_process(alumno, cohort=make_cohort(), program=e.carrera, current_phase=4)
    resp = client_as(e.admin).post(
        f"{URL}/programa/{e.carrera.id}",
        data={"department_id": str(e.dep_b.id), "official_name": "Ingeniería Ficticia"})
    assert resp.status_code == 200, resp.text[:300]
    reg = audit_query(db_session).filter_by(action="program_department.changed").one()
    assert (reg.payload or {}).get("processes_in_phase_4_5") == 1


def test_nombre_oficial_largo_da_400(esc, client_as, db_session):
    e = esc()
    resp = client_as(e.admin).post(
        f"{URL}/programa/{e.carrera.id}",
        data={"department_id": str(e.dep_a.id), "official_name": "x" * 201})
    assert resp.status_code == 400
    assert _fila(db_session, e.carrera.id).official_name == "Ingeniería Ficticia"


def test_quien_solo_puede_abrir_no_puede_guardar(esc, client_as, db_session):
    e = esc()
    assert client_as(e.lector).get(URL).status_code == 200
    resp = client_as(e.lector).post(
        f"{URL}/programa/{e.carrera.id}", data={"department_id": str(e.dep_b.id)})
    assert resp.status_code == 403
    assert _fila(db_session, e.carrera.id).department_id == e.dep_a.id


# ---------------------------------------------------------------------------
# Ajustes del oficio
# ---------------------------------------------------------------------------
def _datos(**kw):
    base = {"oficio_header": "Departamento de Prueba",
            "addressee_position_code": f"tt_test_pos_dest_{_RUN}",
            "attn_position_code": f"tt_test_pos_atn_{_RUN}"}
    base.update(kw)
    return base


def test_crear_y_editar_ajustes_del_oficio_con_bitacora(esc, client_as, db_session):
    e = esc()
    resp = client_as(e.admin).post(f"{URL}/depto/{e.dep_a.id}", data=_datos())
    assert resp.status_code == 200, resp.text[:400]
    assert _hdr(resp, "X-Tt-Notice") == "Ajustes del oficio guardados."
    db_session.expire_all()
    s = db_session.get(DepartmentSettings, e.dep_a.id)
    assert s.oficio_header == "Departamento de Prueba"
    assert s.attn_position_code == f"tt_test_pos_atn_{_RUN}"
    assert s.updated_by_id == e.admin.id

    # «Atn.» es opcional: vaciarlo lo deja en NULL.
    resp = client_as(e.admin).post(
        f"{URL}/depto/{e.dep_a.id}", data=_datos(attn_position_code=""))
    assert resp.status_code == 200
    db_session.expire_all()
    assert db_session.get(DepartmentSettings, e.dep_a.id).attn_position_code is None
    assert audit_query(db_session).filter_by(action="department_settings.changed").count() == 2


@pytest.mark.parametrize("campo", ["addressee_position_code", "attn_position_code"])
def test_codigo_de_puesto_inexistente_da_400_sin_escribir(esc, client_as, db_session, campo):
    e = esc()
    resp = client_as(e.admin).post(
        f"{URL}/depto/{e.dep_a.id}", data=_datos(**{campo: "no_existe_este_puesto"}))
    assert resp.status_code == 400
    assert "no_existe_este_puesto" in _hdr(resp, "X-Tt-Error")
    db_session.expire_all()
    assert db_session.get(DepartmentSettings, e.dep_a.id) is None
    assert audit_query(db_session).filter_by(action="department_settings.changed").count() == 0


def test_encabezado_y_destinatario_son_obligatorios(esc, client_as, db_session):
    e = esc()
    r1 = client_as(e.admin).post(f"{URL}/depto/{e.dep_a.id}", data=_datos(oficio_header="  "))
    r2 = client_as(e.admin).post(
        f"{URL}/depto/{e.dep_a.id}", data=_datos(addressee_position_code=""))
    assert r1.status_code == 400 and r2.status_code == 400
    db_session.expire_all()
    assert db_session.get(DepartmentSettings, e.dep_a.id) is None


def test_ajustes_de_un_departamento_fuera_del_catalogo_dan_400(esc, client_as):
    e = esc()
    resp = client_as(e.admin).post(f"{URL}/depto/{e.fuera.id}", data=_datos())
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# R-G: inerte con el corte en la fase 4 o antes
# ---------------------------------------------------------------------------
def test_con_el_corte_en_3_la_pantalla_es_informativa_y_las_acciones_dan_400(
        esc, client_as, db_session):
    e = esc(cut=3)
    resp = client_as(e.admin).get(URL)
    assert resp.status_code == 200
    doc = lxml.html.fromstring(resp.text)
    assert doc.xpath('//*[@id="tt-carr-handoff"]')
    assert not doc.xpath('//form[@hx-post]')

    r1 = client_as(e.admin).post(
        f"{URL}/programa/{e.carrera.id}", data={"department_id": str(e.dep_b.id)})
    r2 = client_as(e.admin).post(f"{URL}/depto/{e.dep_a.id}", data=_datos())
    assert r1.status_code == 400 and r2.status_code == 400
    assert _fila(db_session, e.carrera.id).department_id == e.dep_a.id
    db_session.expire_all()
    assert db_session.get(DepartmentSettings, e.dep_a.id) is None
    assert audit_query(db_session).filter(TitulatecAuditLog.action.in_(
        ["program_department.changed", "department_settings.changed"])).count() == 0


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------
def test_catalogo_incluye_coord_campus_2_y_ead(esc, db_session, make_department):
    esc()
    c2 = make_department(code="coord_campus_2", name="Coordinación Campus II")
    ead = make_department(code="ead", name="Educación a Distancia")
    ids = {d["id"] for d in ProgramDepartmentService.academic_departments_catalog(db_session)}
    assert c2.id in ids and ead.id in ids
