"""Perfil (/itcj/profile): markup server-side y filtro Jinja `fecha_es`."""
from datetime import date, datetime
from unittest.mock import patch

import lxml.html
import pytest

from itcj2.database import get_db
from itcj2.templates import fecha_es
from tests.conftest import make_jwt

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


class TestFechaEs:
    @pytest.mark.parametrize("mes", range(1, 13))
    def test_largo_los_12_meses(self, mes):
        assert fecha_es(datetime(2026, mes, 5, 8, 21)) == f"5 de {MESES[mes - 1]} de 2026"

    def test_largo_es_el_default(self):
        assert fecha_es(date(2026, 10, 15)) == "15 de octubre de 2026"

    def test_corto(self):
        assert fecha_es(datetime(2026, 10, 15, 8, 21), "corto") == "15/10/2026"

    def test_hora(self):
        assert fecha_es(datetime(2026, 10, 15, 8, 21), "hora") == "15 de octubre de 2026 a las 08:21"

    def test_none(self):
        assert fecha_es(None) == "No disponible"
        assert fecha_es(None, "corto") == "No disponible"

    def test_registrado_como_filtro(self):
        from itcj2.templates import templates
        assert templates.env.filters["fecha_es"] is fecha_es


@pytest.fixture()
def client(app_client, db_session, patched_session_local):
    def _override():
        yield db_session

    app_client.app.dependency_overrides[get_db] = _override
    yield app_client
    app_client.app.dependency_overrides.pop(get_db, None)


PROFILE = {
    "id": 200, "full_name": "PEREZ LOPEZ ANA", "email": "ana@x.mx", "username": "ana",
    "control_number": None, "roles": ["admin"], "is_active": True,
    "created_at": datetime(2026, 3, 5, 9, 0), "last_login_at": datetime(2026, 10, 15, 8, 21),
    "positions": [], "app_assignments": {
        "helpdesk": {"app_name": "Help Desk", "app_icon": "bi-headset", "app_color": "#0d6efd",
                     "roles": ["admin"], "direct_permissions": [],
                     "effective_permissions": ["helpdesk.tickets.api.read.all"]},
    },
}


@pytest.fixture()
def html(client):
    cookie = {"Cookie": f"itcj_token={make_jwt(user_id=200, role='admin', name='PEREZ LOPEZ ANA')}"}

    def _get(qs=""):
        with patch("itcj2.core.services.profile_service.get_user_profile_data", return_value=dict(PROFILE)):
            r = client.get("/itcj/profile" + qs, headers=cookie, follow_redirects=False)
        assert r.status_code == 200, r.text[:300]
        return r.text
    return _get


class TestProfileMarkup:
    def test_tab_inicial_notifications(self, html):
        doc = lxml.html.document_fromstring(html("?tab=notifications"))
        assert doc.xpath("//body/@data-initial-tab") == ["notifications"]
        assert doc.xpath('//*[@id="notifications-tab"]')

    def test_tab_invalido_cae_a_info(self, html):
        doc = lxml.html.document_fromstring(html("?tab=<script>"))
        assert doc.xpath("//body/@data-initial-tab") == ["info"]

    def test_sin_pestana_actividad(self, html):
        text = html()
        assert 'id="activity-tab"' not in text
        assert 'id="activityContainer"' not in text

    def test_fechas_en_espanol(self, html):
        text = html()
        assert "15 de octubre de 2026 a las 08:21" in text
        assert "5 de marzo de 2026" in text

    def test_avatar_con_iniciales(self, html):
        doc = lxml.html.document_fromstring(html())
        assert doc.xpath('//*[contains(@class,"profile-avatar")]')[0].text_content().strip() == "PL"

    def test_permisos_en_details_con_icono_en_summary(self, html):
        doc = lxml.html.document_fromstring(html())
        assert doc.xpath('//details//summary//*[contains(@class,"app-icon")][@data-app-key="helpdesk"]')
