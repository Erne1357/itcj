"""Vista del alumno: /credencial/, /credencial/qr y /credencial/foto.

Fixtures (`client`, `student`, `photo_dir`, `credencial_app`) en conftest.py; CI = base vacía.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import segno

from itcj2.apps.credencial.services.token_service import TOKEN_TTL_SECONDS, CredentialTokenService
from itcj2.config import get_settings
from itcj2.core.models.program import Program
from itcj2.core.models.student_profile import StudentProfile
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
    assert 'href="/itcj/m/"' in html                     # y sola, a cualquier ancho
    assert "mobile-back-to-dashboard" not in html        # esa clase se oculta en >= 992 px
    assert "Vigente" in html
    assert "css/card.css" in html and "js/credencial.js" in html


def test_student_page_without_photo_has_no_qr(client, bare_student):
    html = client.get("/credencial/", headers=_cookie(bare_student)).text
    assert "Foto pendiente" in html and "Servicios Escolares" in html
    assert "/credencial/qr" not in html and "/credencial/foto" not in html
    assert ">Estudiante<" in html                        # sin carrera: la línea 2 es solo el rol
    assert "Vigente" not in html                         # sin foto no se presume vigente


def test_inactive_student_page_logs_out(client, db_session, student):
    user, _, _ = student
    user.is_active = False
    db_session.flush()
    resp = client.get("/credencial/", headers=_cookie(user), follow_redirects=False)
    assert resp.status_code == 302 and resp.headers["location"] == "/itcj/login"


# ── /credencial/qr ───────────────────────────────────────────────────────────
# CI no define FLASK_ENV y config.py cae a "production": se fijan las dos ramas.
@pytest.mark.parametrize("env, prefix", [
    ("development", "http://testserver/credencial/v/"),                # request.base_url
    ("production", "https://credencial.itcj.test/credencial/v/"),     # DOMAIN (TLS externo)
])
def test_qr_partial_svg_and_no_store(client, student, monkeypatch, env, prefix):
    monkeypatch.setattr(get_settings(), "FLASK_ENV", env)
    monkeypatch.setattr(get_settings(), "DOMAIN", "https://credencial.itcj.test/")
    user, photo, _ = student
    with patch("segno.make", wraps=segno.make) as make:
        resp = client.get("/credencial/qr", headers=_cookie(user))
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    assert "<svg" in resp.text and 'data-expires-at="' in resp.text

    url = make.call_args.args[0]
    assert make.call_args.kwargs.get("error") == "m"
    assert url.startswith(prefix)
    claims = CredentialTokenService.parse(url.removeprefix(prefix))
    assert claims.ref == photo.ref

    expires = resp.text.split('data-expires-at="', 1)[1].split('"', 1)[0]
    delta = (datetime.fromisoformat(expires) - datetime.now(timezone.utc)).total_seconds()
    assert TOKEN_TTL_SECONDS - 5 < delta <= TOKEN_TTL_SECONDS


def test_domain_default_is_official_origin():
    """El QR de prod y el pie «Dirección oficial» salen de DOMAIN: un .env sin él no puede dar localhost."""
    from itcj2.config import Settings

    assert Settings.model_fields["DOMAIN"].default == "https://enlinea.cdjuarez.tecnm.mx"


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
    assert resp.headers["cache-control"] == "no-store"
    assert "<svg" not in resp.text
    make.assert_not_called()


def test_qr_staff_forbidden(client, plain_staff):
    resp = client.get("/credencial/qr", headers=_cookie(plain_staff, "staff"))
    assert resp.status_code == 403


def test_qr_anonymous_401_with_hx_redirect(client):
    resp = client.get("/credencial/qr", follow_redirects=False)
    assert resp.status_code == 401
    assert resp.headers["cache-control"] == "no-store"
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


def test_qr_slim_check_skips_card_build(client, student):
    """El sondeo de 30 s no arma la tarjeta (carrera + roles de titulatec)."""
    user, _, _ = student
    with patch("itcj2.apps.credencial.services.card_service.CardService.build") as build:
        assert client.get("/credencial/qr", headers=_cookie(user)).status_code == 200
    build.assert_not_called()


def test_short_name_title_case_and_blank_first_name(client, db_session, photo_dir):
    upper = User(first_name="JOSÉ ÁNGEL", last_name="NÚÑEZ", control_number=f"Y{uuid.uuid4().hex[:9]}", is_active=True)
    blank = User(first_name=" ", last_name="Solo", control_number=f"Y{uuid.uuid4().hex[:9]}", is_active=True)
    db_session.add_all([upper, blank])
    db_session.flush()
    assert client.get("/credencial/", headers=_cookie(upper)).status_code == 200
    assert client.get("/credencial/", headers=_cookie(blank)).status_code == 200


def test_worst_case_lines_get_fit_classes(client, db_session, photo_dir):
    """Máximos reales de dev: las líneas largas salen con paso de letra, sin recorte."""
    program = Program(name=f"Maestría en Administración de Negocios Internacionales {uuid.uuid4().hex[:4]}")
    user = User(first_name="Daniel Arturo Amador Gordillo", last_name="Amador", middle_name="Gordillo",
                control_number=f"Y{uuid.uuid4().int % 10**8:08d}", is_active=True)
    db_session.add_all([program, user])
    db_session.flush()
    db_session.add(StudentProfile(user_id=user.id, program_id=program.id))
    db_session.flush()
    with patch("itcj2.core.services.authz_cache.cached_roles", return_value={"graduate"}):
        html = client.get("/credencial/", headers=_cookie(user)).text
    assert html.count('class="cc-line cc-fit-') == 2
    assert f'<span class="cc-num">{user.control_number}</span>' in html


def test_card_macro_photo_url_and_id_suffix(student, db_session):
    """Vista previa de OTRO alumno (panel): foto e ids propios; los defaults no cambian."""
    from itcj2.apps.credencial.pages.render import credencial_templates
    from itcj2.apps.credencial.services.card_service import CardService

    user, _, _ = student
    card = CardService.build(db_session, user.id)
    macro = credencial_templates.env.get_template("credencial/_card.html").module.render_card
    html = str(macro(card, "hero", photo_url=f"/credencial/admin/alumnos/{user.id}/foto", id_suffix=f"-{user.id}"))
    assert f'src="/credencial/admin/alumnos/{user.id}/foto"' in html
    assert f'id="cc-card-hero-{user.id}"' in html and f'id="cc-front-{user.id}"' in html
    default = str(macro(card))
    assert 'src="/credencial/foto"' in default and 'id="cc-front"' in default
