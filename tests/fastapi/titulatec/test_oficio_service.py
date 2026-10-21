"""Fase 4, tarea 6: `OficioService` (oficio de asignación de sinodales, spec §12, R-C, R-F)."""
from __future__ import annotations

import re

import pytest

from itcj2.apps.titulatec.models import DepartmentSettings
from itcj2.apps.titulatec.services.oficio_service import (
    NO_SYNODALS_MSG, OficioService,
)
from tests.fastapi.titulatec.conftest import _n

ROLES = ("president", "secretary", "vocal", "alternate")


@pytest.fixture()
def caso(db_session, make_user, make_department, make_program, make_program_department,
         make_modality, make_student, make_process, make_format_b, make_teacher,
         make_academic_head, make_synodals, make_position, assign_position):
    """Proceso con 4 sinodales, jefe de depto y ocupantes de destinatario/atención."""
    n = _n()
    depto = make_department(code=f"tt_ofi_{n}", name="Sistemas y Computación")
    carrera = make_program(f"Carrera Catalogo Oficio {n}")
    make_program_department(carrera, depto, official_name="Ingeniería Oficial en TIC")
    modalidad = make_modality(name="Residencia")
    modalidad.option_label = "Informe Técnico de Residencia Profesional"
    alumno = make_student(first_name="ERNESTO", last_name="VILLARREAL")
    proceso = make_process(alumno, program=carrera, modality=modalidad, current_phase=4)
    make_format_b(proceso, project_name="desarrollo de aplicación web")
    jefe = make_academic_head(depto, kind="head")
    docentes = {r: make_teacher(depto, academic_degree=f"Grado {r}",
                                professional_license=f"{n}{i}")
                for i, r in enumerate(ROLES)}
    make_synodals(proceso, docentes, jefe)
    db_session.add(DepartmentSettings(
        department_id=depto.id, oficio_header="Departamento de Sistemas y Computación",
        addressee_position_code=f"tt_ofi_dest_{n}", attn_position_code=f"tt_ofi_atn_{n}"))
    db_session.flush()
    return {"n": n, "depto": depto, "carrera": carrera, "alumno": alumno, "proceso": proceso,
            "jefe": jefe, "docentes": docentes, "modalidad": modalidad}


def _ocupante(make_user, make_position, assign_position, code, title, first, last):
    u = make_user(first_name=first, last_name=last)
    assign_position(u, make_position(code=code, title=title))
    return u


def test_contexto_trae_todas_las_piezas(db_session, caso, make_user, make_position, assign_position):
    n = caso["n"]
    _ocupante(make_user, make_position, assign_position, f"tt_ofi_dest_{n}",
              "JEFA DE LA DIVISION", "YADIRA", "DOZAL")
    _ocupante(make_user, make_position, assign_position, f"tt_ofi_atn_{n}",
              "Coordinadora de Apoyo", "TANIA", "RUIZ")
    ctx = OficioService.context(db_session, caso["proceso"])
    assert ctx["header"] == "Departamento de Sistemas y Computación"
    assert ctx["addressee"] == {"name": "YADIRA DOZAL", "title": "JEFA DE LA DIVISION"}
    assert ctx["attn"]["name"] == "TANIA RUIZ"
    assert ctx["signer"]["name"].startswith("JEFE")
    assert ctx["program_name"] == "Ingeniería Oficial en TIC"      # R-C
    assert ctx["option_label"] == "Informe Técnico de Residencia Profesional"
    assert ctx["project_title"] == "DESARROLLO DE APLICACIÓN WEB"
    assert ctx["control_number"] == caso["alumno"].control_number
    assert re.fullmatch(r"\d{2}/[A-Z][a-zé]+/\d{4}", ctx["date_label"])
    assert len(ctx["synodals"]) == 4
    assert [s["role_label"].lower() for s in ctx["synodals"]][0].startswith("president")
    assert ctx["synodals"][0]["license"] and ctx["synodals"][0]["academic_degree"]


def test_el_titulo_personalizado_gana_al_del_puesto(db_session, caso, make_user, make_position,
                                                   assign_position):
    """Hallazgo 17: el organigrama usa títulos neutros («Jefe(a) del
    Departamento de Titulación»); el oficio real dice otra cosa. Los ajustes
    del departamento pueden fijar el título; vacío = el del puesto."""
    n = caso["n"]
    _ocupante(make_user, make_position, assign_position, f"tt_ofi_dest_{n}",
              "Jefe(a) de la División", "YADIRA", "DOZAL")
    _ocupante(make_user, make_position, assign_position, f"tt_ofi_atn_{n}",
              "Jefe(a) del Departamento de Titulación", "TANIA", "RUIZ")
    ajustes = db_session.get(DepartmentSettings, caso["depto"].id)
    ajustes.addressee_title = "JEFA DE LA DIVISIÓN DE ESTUDIOS PROFESIONALES"
    db_session.flush()

    ctx = OficioService.context(db_session, caso["proceso"])

    assert ctx["addressee"] == {"name": "YADIRA DOZAL",
                                "title": "JEFA DE LA DIVISIÓN DE ESTUDIOS PROFESIONALES"}
    # Sin título personalizado del «Atn.»: el del puesto.
    assert ctx["attn"] == {"name": "TANIA RUIZ", "title": "Jefe(a) del Departamento de Titulación"}

    ajustes.attn_title = "Coordinadora de Apoyo a Titulación"
    db_session.flush()
    html = _html(db_session, caso["proceso"])
    assert "Coordinadora de Apoyo a Titulación" in html
    assert "Jefe(a) del Departamento de Titulación" not in html


def test_con_titulo_personalizado_un_puesto_vacante_sigue_en_blanco(db_session, caso):
    ajustes = db_session.get(DepartmentSettings, caso["depto"].id)
    ajustes.addressee_title = "JEFA DE LA DIVISIÓN DE ESTUDIOS PROFESIONALES"
    ajustes.attn_title = "Coordinadora de Apoyo a Titulación"
    db_session.flush()
    ctx = OficioService.context(db_session, caso["proceso"])
    assert ctx["addressee"] is None and ctx["attn"] is None


def test_el_pie_usa_el_dominio_institucional():
    """Hallazgo 4 / ruling R7: `cdjuarez.tecnm.mx` (sin `.edu`), y sin copiar la
    errata «cdjurez» del oficio real."""
    from itcj2.apps.titulatec.services.oficio_service import FOOTER_CONTACT

    assert FOOTER_CONTACT.endswith("direccion@cdjuarez.tecnm.mx - www.cdjuarez.tecnm.mx")
    assert "tecnm.edu.mx" not in FOOTER_CONTACT and "cdjurez" not in FOOTER_CONTACT


def test_puesto_vacante_deja_la_linea_en_blanco(db_session, caso):
    ctx = OficioService.context(db_session, caso["proceso"])
    assert ctx["addressee"] is None and ctx["attn"] is None
    html = _html(db_session, caso["proceso"])
    assert "PRESENTE.-" in html


def test_official_name_null_usa_el_catalogo(db_session, caso):
    from itcj2.apps.titulatec.models import ProgramDepartment
    db_session.get(ProgramDepartment, caso["carrera"].id).official_name = None
    db_session.flush()
    assert OficioService.context(db_session, caso["proceso"])["program_name"] == caso["carrera"].name


def test_sin_sinodales_levanta_error(db_session, make_student, make_process):
    proc = make_process(make_student(), current_phase=4)
    with pytest.raises(ValueError, match=NO_SYNODALS_MSG):
        OficioService.context(db_session, proc)


def test_render_pdf_y_nombre(db_session, caso):
    pdf = OficioService.render_pdf(db_session, caso["proceso"])
    assert pdf.startswith(b"%PDF")
    assert OficioService.filename(db_session, caso["proceso"]) == \
        f"{caso['alumno'].control_number}_OFICIO_SINODALES.pdf"


def test_html_contiene_datos_clave(db_session, caso):
    html = _html(db_session, caso["proceso"])
    for s in OficioService.context(db_session, caso["proceso"])["synodals"]:
        assert s["name"] in html and f"CED.PROF {s['license']}" in html
    assert "Informe Técnico de Residencia Profesional" in html
    assert "<script" not in html


def _html(db, proceso):
    from itcj2.apps.titulatec.pages.nav import titulatec_templates
    ctx = OficioService.context(db, proceso)
    return titulatec_templates.get_template(
        "titulatec/oficios/asignacion_sinodales.html").render(**ctx)


def test_muestra_pdf_opcional(db_session, caso, make_user, make_position, assign_position):
    """Escribe el PDF de muestra si TT_OFICIO_SAMPLE apunta a una ruta."""
    import os
    n = caso["n"]
    _ocupante(make_user, make_position, assign_position, f"tt_ofi_dest_{n}",
              "JEFA DE LA DIVISIÓN DE ESTUDIOS PROFESIONALES", "YADIRA", "DOZAL ASSMAR")
    _ocupante(make_user, make_position, assign_position, f"tt_ofi_atn_{n}",
              "Coordinadora de Apoyo a Titulación", "TANIA GUADALUPE", "RUIZ ESCOBAR")
    ruta = os.environ.get("TT_OFICIO_SAMPLE")
    if ruta:
        with open(ruta, "wb") as f:
            f.write(OficioService.render_pdf(db_session, caso["proceso"]))
