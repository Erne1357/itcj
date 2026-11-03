"""Vista del alumno: /credencial/, /credencial/qr y /credencial/foto.

Fixtures (`client`, `student`, `photo_dir`, `credencial_app`) en conftest.py; CI = base vacía.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import segno

from itcj2.apps.credencial.services.token_service import TOKEN_TTL_SECONDS, CredentialTokenService
from itcj2.core.models.user import User
from tests.conftest import make_jwt
from tests.fastapi.credencial.conftest import FIRST, LAST, MIDDLE, PHOTO_BYTES, grant


def _cookie(user, role="student"):
    return {"Cookie": f"itcj_token={make_jwt(user_id=user.id, role=role, cn=user.control_number)}"}


@pytest.fixture
def bare_student(db_session, photo_dir):
    """Alumno activo sin carrera ni foto."""
    user = User(first_name="Sin", last_name="Foto", control_number=f"Y{uuid.uuid4().hex[:9]}", is_active=True)
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def plain_staff(db_session):
    user = User(first_name="Ana", last_name="Personal", username=f"st_{uuid.uuid4().hex[:8]}")
    db_session.add(user)
    db_session.flush()
    return user


# ── /credencial/ ─────────────────────────────────────────────────────────────
def test_student_page_requires_login(client):
    resp = client.get("/credencial/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/itcj/login"


@pytest.mark.parametrize("has_perm", [False, True])
def test_staff_redirected_or_forbidden(client, db_session, plain_staff, credencial_app, has_perm):
    if has_perm:
        grant(db_session, credencial_app, plain_staff, "credencial.admin.page.view")
    resp = client.get("/credencial/", headers=_cookie(plain_staff, "staff"), follow_redirects=False)
    if has_perm:
        assert resp.status_code == 302
        assert resp.headers["location"] == "/credencial/admin/"
    else:
        assert resp.status_code == 403


def test_global_admin_without_card_goes_to_panel(client, plain_staff):
    resp = client.get("/credencial/", headers=_cookie(plain_staff, "admin"), follow_redirects=False)
    assert resp.status_code == 302 and resp.headers["location"] == "/credencial/admin/"


def test_student_page_renders_card_and_qr_trigger(client, student):
    user, _, program_name = student
    resp = client.get("/credencial/", headers=_cookie(user))
    assert resp.status_code == 200
    html = resp.text
    assert f"{FIRST} {LAST} {MIDDLE}" in html and user.control_number in html
    assert f"{program_name} / Estudiante" in html
    assert "Instituto Tecnológico de Ciudad Juárez" in html
    assert 'src="/credencial/foto"' in html
    assert 'hx-get="/credencial/qr"' in html
    assert "every 30s [document.visibilityState === 'visible']" in html
    assert "/credencial/v/" not in html                  # el token solo viaja en el parcial
    assert 'id="mobileBackToDashboard"' in html          # volver al shell desde el iframe
    assert "css/card.css" in html and "js/credencial.js" in html


def test_student_page_without_photo_has_no_qr(client, bare_student):
    html = client.get("/credencial/", headers=_cookie(bare_student)).text
    assert "Foto pendiente" in html and "Servicios Escolares" in html
    assert "/credencial/qr" not in html and "/credencial/foto" not in html
    assert ">Estudiante<" in html                        # sin carrera: la línea 2 es solo el rol


def test_inactive_student_page_logs_out(client, db_session, student):
    user, _, _ = student
    user.is_active = False
    db_session.flush()
    resp = client.get("/credencial/", headers=_cookie(user), follow_redirects=False)
    assert resp.status_code == 302 and resp.headers["location"] == "/itcj/login"


# ── /credencial/qr ───────────────────────────────────────────────────────────
def test_qr_partial_svg_and_no_store(client, student):
    user, photo, _ = student
    with patch("segno.make", wraps=segno.make) as make:
        resp = client.get("/credencial/qr", headers=_cookie(user))
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    assert "<svg" in resp.text and 'data-expires-at="' in resp.text

    url = make.call_args.args[0]
    assert make.call_args.kwargs.get("error") == "m"
    prefix = "http://testserver/credencial/v/"
    assert url.startswith(prefix)
    claims = CredentialTokenService.parse(url.removeprefix(prefix))
    assert claims.ref == photo.ref

    expires = resp.text.split('data-expires-at="', 1)[1].split('"', 1)[0]
    delta = (datetime.fromisoformat(expires) - datetime.now(timezone.utc)).total_seconds()
    assert TOKEN_TTL_SECONDS - 5 < delta <= TOKEN_TTL_SECONDS


def test_qr_without_photo_409_no_token(client, bare_student):
    resp = client.get("/credencial/qr", headers=_cookie(bare_student))
    assert resp.status_code == 409
    assert resp.headers["cache-control"] == "no-store"
    assert "Foto pendiente" in resp.text
    assert "/credencial/v/" not in resp.text and "<svg" not in resp.text


def test_qr_photo_file_missing_409(client, student, photo_dir):
    user, photo, _ = student
    (photo_dir / photo.file_name).unlink()
    with patch("segno.make") as make:
        resp = client.get("/credencial/qr", headers=_cookie(user))
    assert resp.status_code == 409
    make.assert_not_called()


def test_qr_inactive_user_forbidden(client, db_session, student):
    user, _, _ = student
    user.is_active = False
    db_session.flush()
    with patch("segno.make") as make:
        resp = client.get("/credencial/qr", headers=_cookie(user))
    assert resp.status_code == 403
    assert "<svg" not in resp.text
    make.assert_not_called()


def test_qr_staff_forbidden(client, plain_staff):
    resp = client.get("/credencial/qr", headers=_cookie(plain_staff, "staff"))
    assert resp.status_code == 403


def test_qr_anonymous_401_with_hx_redirect(client):
    resp = client.get("/credencial/qr", follow_redirects=False)
    assert resp.status_code == 401
    assert resp.headers["hx-redirect"] == "/itcj/login"   # HTMX no mete el login dentro del QR
    assert "<svg" not in resp.text


# ── /credencial/foto ─────────────────────────────────────────────────────────
def test_own_photo_requires_session(client, student):
    user, _, _ = student
    resp = client.get("/credencial/foto", follow_redirects=False)
    assert resp.status_code == 302 and resp.headers["location"] == "/itcj/login"

    resp = client.get("/credencial/foto", headers=_cookie(user))
    assert resp.status_code == 200
    assert resp.content == PHOTO_BYTES
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.headers["cache-control"] == "private, no-store"


def test_own_photo_404_without_photo_or_card(client, bare_student, plain_staff):
    assert client.get("/credencial/foto", headers=_cookie(bare_student)).status_code == 404
    assert client.get("/credencial/foto", headers=_cookie(plain_staff, "staff")).status_code == 404
