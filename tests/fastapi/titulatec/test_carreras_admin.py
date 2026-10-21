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
        # Hijo de la Subdirección SIN puesto docente (como Ciencias Básicas o
        # Desarrollo Académico en dev): no opera sinodales, no se ofrece (hallazgo 11).
        sin_docentes = make_department(code=f"tt_test_carr_s_{_RUN}",
                                       name="Depto sin docentes de prueba", parent_id=padre.id)
        for d in (dep_a, dep_b):
            make_position(code=f"docente_{d.code}", title="Docente de prueba", department=d)
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
                                  admin=admin, lector=lector, padre=padre,
                                  sin_docentes=sin_docentes))
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
    # El catálogo trae los departamentos con puesto docente y NO el ajeno ni
    # el hijo de la Subdirección que no tiene docentes (hallazgo 11).
    assert str(e.dep_a.id) in opciones and str(e.dep_b.id) in opciones
    assert str(e.fuera.id) not in opciones
    assert str(e.sin_docentes.id) not in opciones
    assert doc.xpath(f'//*[@id="tt-carr-dept-{e.dep_a.id}"]')
    assert not doc.xpath(f'//*[@id="tt-carr-dept-{e.sin_docentes.id}"]')


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
    cohorte = make_cohort()
    for fase in (4, 5, 6):   # 4 y 5 cuentan; la 6 ya no
        alumno = make_student(first_name=f"ALUMNO{fase}", last_name="CARRERAS")
        make_process(alumno, cohort=cohorte, program=e.carrera, current_phase=fase)
    resp = client_as(e.admin).post(
        f"{URL}/programa/{e.carrera.id}",
        data={"department_id": str(e.dep_b.id), "official_name": "Ingeniería Ficticia"})
    assert resp.status_code == 200, resp.text[:300]
    reg = audit_query(db_session).filter_by(action="program_department.changed").one()
    assert (reg.payload or {}).get("processes_in_phase_4_5") == 2


def test_las_fases_4_y_5_salen_del_catalogo_no_de_literales():
    """Hallazgo 9: el número de fase sale del catálogo por código
    (`synodal_assignment`, `synodal_review`), nunca un `(4, 5)` escrito a mano."""
    import inspect
    import re as _re

    from itcj2.apps.titulatec.services import program_department_service as mod

    fuente = inspect.getsource(mod)
    assert not _re.search(r"in_\(\s*\(\s*4\s*,\s*5\s*\)\s*\)", fuente)
    assert "synodal_assignment" in fuente or "PHASE_CODE" in fuente
    assert "synodal_review" in fuente or "REVIEW_PHASE_CODE" in fuente


# ---------------------------------------------------------------------------
# Perfil (posgrado) sin leer `Program.level` (hallazgo 10)
# ---------------------------------------------------------------------------
def test_el_perfil_de_posgrado_lo_rotula_track_service(esc, client_as, make_program,
                                                       make_program_department):
    e = esc()
    maestria = make_program(f"Maestria Ficticia Carreras {_RUN}", level="maestria")
    doctorado = make_program(f"Doctorado Ficticio Carreras {_RUN}", level="doctorado")
    for p in (maestria, doctorado):
        make_program_department(p, e.dep_b)

    doc = lxml.html.fromstring(client_as(e.admin).get(URL).text)

    def etiqueta(program):
        return [" ".join(s.text_content().split()) for s in
                doc.xpath(f'//*[@id="tt-carr-row-{program.id}"]//*[@class="tt-carr-level"]')]

    assert etiqueta(maestria) == ["Maestría"]
    assert etiqueta(doctorado) == ["Doctorado"]
    assert etiqueta(e.carrera) == []           # licenciatura: sin etiqueta


def test_ni_el_servicio_ni_la_plantilla_leen_level():
    """Invariante 2 del posgrado: solo `TrackService` lee `Program.level`."""
    from pathlib import Path

    import itcj2.apps.titulatec as _tt_pkg

    app = Path(_tt_pkg.__file__).resolve().parent
    servicio = (app / "services" / "program_department_service.py").read_text(encoding="utf-8")
    plantilla = (app / "templates" / "titulatec" / "partials" / "carreras"
                 / "_body.html").read_text(encoding="utf-8")
    assert ".level" not in servicio and '"level"' not in servicio
    assert "level" not in plantilla.replace("tt-carr-level", "")


# ---------------------------------------------------------------------------
# Procesos en fase 4/5 de carreras sin departamento (hallazgo 11)
# ---------------------------------------------------------------------------
def test_avisa_cuantos_procesos_en_fase_4_o_5_no_tienen_departamento(
        esc, client_as, db_session, seed_document_types, make_cohort, make_student,
        make_process, make_program, make_program_department):
    e = esc()
    seed_document_types()
    antes = ProgramDepartmentService.unassignable_in_flight(db_session)
    huerfana = make_program(f"Carrera Huerfana Carreras {_RUN}")
    sin_docentes = make_program(f"Carrera Sin Docentes Carreras {_RUN}")
    make_program_department(sin_docentes, e.sin_docentes)
    cohorte = make_cohort()
    casos = ((huerfana, 4, "active"), (huerfana, 5, "active"), (sin_docentes, 4, "active"),
             (huerfana, 6, "active"),            # ya pasó la fase 5: no cuenta
             (huerfana, 4, "cancelled"),         # proceso cancelado: no cuenta
             (e.carrera, 4, "active"))           # carrera con departamento: no cuenta
    for i, (programa, fase, estado) in enumerate(casos):
        alumno = make_student(first_name=f"HUERFANO{i}", last_name="CARRERAS")
        make_process(alumno, cohort=cohorte, program=programa, current_phase=fase,
                     status=estado)

    assert ProgramDepartmentService.unassignable_in_flight(db_session) == antes + 3

    doc = lxml.html.fromstring(client_as(e.admin).get(URL).text)
    aviso = doc.xpath('//*[@id="tt-carr-unassignable"]')
    assert aviso, "falta el aviso de procesos sin departamento"
    assert str(antes + 3) in aviso[0].text_content()


def test_sin_procesos_huerfanos_no_hay_aviso(esc, client_as, db_session, monkeypatch):
    e = esc()
    monkeypatch.setattr(ProgramDepartmentService, "unassignable_in_flight",
                        staticmethod(lambda db, catalog=None: 0))
    doc = lxml.html.fromstring(client_as(e.admin).get(URL).text)
    assert not doc.xpath('//*[@id="tt-carr-unassignable"]')


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
    # Un hijo de la Subdirección sin docentes tampoco es del catálogo (hallazgo 11).
    resp = client_as(e.admin).post(f"{URL}/depto/{e.sin_docentes.id}", data=_datos())
    assert resp.status_code == 400


def test_titulos_del_oficio_se_editan_con_bitacora(esc, client_as, db_session):
    """Hallazgo 17: títulos personalizados del destinatario y del «Atn.»
    (NULL = el título del puesto en el organigrama)."""
    e = esc()
    pagina = lxml.html.fromstring(client_as(e.admin).get(URL).text)
    form = pagina.xpath(f'//*[@id="tt-carr-dept-{e.dep_a.id}"]')[0]
    assert form.xpath('.//input[@name="addressee_title"]')
    assert form.xpath('.//input[@name="attn_title"]')

    resp = client_as(e.admin).post(f"{URL}/depto/{e.dep_a.id}", data=_datos(
        addressee_title="  JEFA DE LA DIVISIÓN   DE ESTUDIOS PROFESIONALES ",
        attn_title="Coordinadora de Apoyo a Titulación"))
    assert resp.status_code == 200, resp.text[:300]
    db_session.expire_all()
    s = db_session.get(DepartmentSettings, e.dep_a.id)
    assert s.addressee_title == "JEFA DE LA DIVISIÓN DE ESTUDIOS PROFESIONALES"
    assert s.attn_title == "Coordinadora de Apoyo a Titulación"
    reg = audit_query(db_session).filter_by(action="department_settings.changed").one()
    assert (reg.after or {}).get("attn_title") == "Coordinadora de Apoyo a Titulación"
    # Re-pintado con lo guardado.
    fila = lxml.html.fromstring(resp.text).xpath(f'//*[@id="tt-carr-dept-{e.dep_a.id}"]')[0]
    assert fila.xpath('string(.//input[@name="attn_title"]/@value)') == \
        "Coordinadora de Apoyo a Titulación"

    # Vacío = vuelve al título del puesto (NULL).
    resp = client_as(e.admin).post(f"{URL}/depto/{e.dep_a.id}", data=_datos(attn_title=""))
    assert resp.status_code == 200
    db_session.expire_all()
    s = db_session.get(DepartmentSettings, e.dep_a.id)
    assert s.attn_title is None and s.addressee_title is None


def test_titulo_del_oficio_largo_da_400_sin_escribir(esc, client_as, db_session):
    e = esc()
    resp = client_as(e.admin).post(f"{URL}/depto/{e.dep_a.id}",
                                   data=_datos(addressee_title="x" * 201))
    assert resp.status_code == 400
    assert "200" in _hdr(resp, "X-Tt-Error")
    db_session.expire_all()
    assert db_session.get(DepartmentSettings, e.dep_a.id) is None


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
def test_catalogo_incluye_coord_campus_2_y_ead(esc, db_session, make_department,
                                              make_position):
    esc()
    c2 = make_department(code="coord_campus_2", name="Coordinación Campus II")
    ead = make_department(code="ead", name="Educación a Distancia")
    for d in (c2, ead):
        make_position(code=f"docente_{d.code}", title="Docente", department=d)
    ids = {d["id"] for d in ProgramDepartmentService.academic_departments_catalog(db_session)}
    assert c2.id in ids and ead.id in ids


def test_catalogo_es_solo_de_departamentos_con_puesto_docente_vigente(esc, db_session,
                                                                     make_department,
                                                                     make_position):
    """Hallazgo 11: solo se ofrece un departamento que puede operar sinodales
    (tiene su puesto `docente_{code}` activo); los demás no aparecen."""
    from itcj2.core.models.position import Position

    e = esc()
    suelto = make_department(code=f"tt_test_carr_suelto_{_RUN}", name="Depto suelto")
    make_position(code=f"docente_{suelto.code}", title="Docente", department=suelto)
    apagado = make_department(code=f"tt_test_carr_off_{_RUN}", name="Depto apagado",
                              parent_id=e.padre.id)
    make_position(code=f"docente_{apagado.code}", title="Docente", department=apagado)
    (db_session.query(Position).filter_by(code=f"docente_{apagado.code}")
     .one()).is_active = False
    db_session.flush()

    ids = {d["id"] for d in ProgramDepartmentService.academic_departments_catalog(db_session)}

    assert {e.dep_a.id, e.dep_b.id, suelto.id} <= ids
    assert e.sin_docentes.id not in ids and e.fuera.id not in ids and apagado.id not in ids


def test_css_solo_con_tokens_de_tamano():
    """Hallazgo 12: ningún `font-size` literal en la hoja de la pestaña."""
    import re as _re
    from pathlib import Path

    import itcj2.apps.titulatec as _tt_pkg

    css = (Path(_tt_pkg.__file__).resolve().parent / "static" / "css" / "admin"
           / "carreras.css").read_text(encoding="utf-8")
    sin_comentarios = _re.sub(r"/\*.*?\*/", "", css, flags=_re.S)
    tamanos = _re.findall(r"font-size\s*:\s*([^;}]+)", sin_comentarios)
    assert tamanos and all(t.strip().startswith("var(--tt-fs-") for t in tamanos), tamanos
