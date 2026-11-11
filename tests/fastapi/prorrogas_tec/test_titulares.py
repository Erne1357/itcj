"""Nombres de director y subdirector tomados de los puestos de core (puestos sintéticos: no tocan los reales)."""
from datetime import date, timedelta

import pytest

from itcj2.apps.prorrogas_tec.documents.catalog import default_template_path
from itcj2.apps.prorrogas_tec.services import titulares as t
from itcj2.apps.prorrogas_tec.services.docx_fill import find_placeholders
from itcj2.apps.prorrogas_tec.services.document_service import DocumentService
from itcj2.core.models.position import Position, UserPosition


@pytest.fixture()
def puestos(db_session, monkeypatch):
    monkeypatch.setattr(t, "PUESTOS", {"director_nombre": ("pr_test_director_2088", "Director"),
                                       "subdirector_nombre": ("pr_test_subdir_2088", "Subdirector Académico")})
    p = Position(code="pr_test_director_2088", title="Director")
    db_session.add(p)
    db_session.flush()
    return p


def test_titular_activo_en_orden_nombre_paterno_materno_y_vacante_vacia(db_session, make_user, puestos):
    anterior = make_user(first_name="Pedro", last_name="Viejo", middle_name="Salido")
    actual = make_user(first_name="Ana María", last_name="López", middle_name="Ruiz")
    db_session.add_all([
        UserPosition(user_id=anterior.id, position_id=puestos.id, start_date=date(2020, 1, 1),
                     end_date=date.today() - timedelta(days=1), is_active=True),
        UserPosition(user_id=actual.id, position_id=puestos.id, start_date=date(2020, 1, 1), is_active=True),
    ])
    db_session.flush()
    valores = t.titulares(db_session)
    assert valores == {"director_nombre": "ANA MARÍA LÓPEZ RUIZ", "subdirector_nombre": ""}
    assert t.vacantes(valores) == ["Subdirector Académico"]


def test_el_documento_guarda_el_nombre_con_el_que_se_genero(db_session, solicitud, pdf_falso, monkeypatch):
    monkeypatch.setattr("itcj2.apps.prorrogas_tec.services.document_service.titulares",
                        lambda db: {"director_nombre": "DIRECTOR DE PRUEBA", "subdirector_nombre": "SUBDIRECTOR DE PRUEBA"})
    doc = DocumentService.generate(db_session, solicitud, "formato_solicitud", actor_id=None, today=date(2091, 2, 1))
    assert doc.context["subdirector_nombre"] == "SUBDIRECTOR DE PRUEBA"


_COMPROMISO = {"director_nombre", "subdirector_nombre", "subdirector_admin_nombre"}


@pytest.mark.parametrize("code, marcadores", [
    ("carta_compromiso_1", _COMPROMISO), ("carta_compromiso_2", _COMPROMISO),
    ("formato_solicitud", {"subdirector_nombre"}),
])
def test_las_plantillas_del_sistema_ya_no_traen_el_nombre_escrito(code, marcadores):
    assert marcadores <= set(find_placeholders(default_template_path(code).read_bytes()))
