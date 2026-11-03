"""Hero de la credencial en el inicio móvil del alumno (core/mobile/student_dashboard.html).

Fixtures (`client`, `student`) en conftest.py; CI = base vacía.
"""
from unittest.mock import patch

from tests.conftest import make_jwt
from tests.fastapi.credencial.conftest import FIRST, LAST, MIDDLE


def _cookie(user):
    return {"Cookie": f"itcj_token={make_jwt(user_id=user.id, role='student', cn=user.control_number)}"}


def test_dashboard_hero_replaces_user_card(client, student):
    user, _, program_name = student
    with patch("itcj2.templates._get_active_theme", return_value=None), \
         patch("itcj2.core.services.mobile_service.get_mobile_apps_for_user", return_value=[]):
        resp = client.get("/itcj/m/", headers=_cookie(user))
    assert resp.status_code == 200
    html = resp.text
    assert "mobile-user-card" not in html
    assert "cc-card--hero" in html and "data-open-in-app" in html
    assert 'href="/credencial/"' in html and 'src="/credencial/foto"' in html
    assert f"{FIRST} {LAST} {MIDDLE}" in html and f"{program_name} / Estudiante" in html
    assert "credencial/css/card.css" in html


def test_dashboard_hero_without_photo_stays_tappable(client, student, photo_dir):
    user, photo, _ = student
    (photo_dir / photo.file_name).unlink()
    with patch("itcj2.templates._get_active_theme", return_value=None), \
         patch("itcj2.core.services.mobile_service.get_mobile_apps_for_user", return_value=[]):
        html = client.get("/itcj/m/", headers=_cookie(user)).text
    assert "Foto pendiente" in html and "Servicios Escolares" in html
    assert 'href="/credencial/"' in html and "/credencial/foto" not in html
