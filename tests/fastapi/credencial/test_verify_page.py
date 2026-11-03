"""Página pública /credencial/v/{token}: estados, cero fugas, cabeceras y bitácora.

CI corre contra una base vacía (create_all, sin DML): cada fila que la página
necesita (alumno, carrera, foto, app y permiso de credencial) se crea aquí dentro
del savepoint de `db_session`. Nada asume ids.
"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from itcj2.apps.credencial.models import CredentialPhoto, CredentialVerification
from itcj2.apps.credencial.services.token_service import CredentialTokenService
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.permission import Permission
from itcj2.core.models.program import Program
from itcj2.core.models.student_profile import StudentProfile
from itcj2.core.models.user import User
from itcj2.core.models.user_app_perm import UserAppPerm
from itcj2.database import get_db
from tests.conftest import make_jwt

FIRST, LAST, MIDDLE = "Xochiquetzal", "Zubizarreta", "Quirarte"
PHOTO_BYTES = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
PUBLIC_HEADERS = {
    "cache-control": "no-store",
    "x-robots-tag": "noindex, nofollow",
    "referrer-policy": "no-referrer",
}


@pytest.fixture
def client(app_client, db_session):
    def _override():
        yield db_session

    app_client.app.dependency_overrides[get_db] = _override
    yield app_client
    app_client.app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def photo_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "CREDENCIAL_PHOTO_PATH", str(tmp_path))
    return tmp_path


@pytest.fixture
def student(db_session, photo_dir):
    """Alumno activo con carrera y foto en disco. Devuelve (user, photo, program_name)."""
    program_name = f"Ing. Prueba Credencial {uuid.uuid4().hex[:8]}"
    program = Program(name=program_name)
    user = User(first_name=FIRST, last_name=LAST, middle_name=MIDDLE,
                control_number=f"Z{uuid.uuid4().hex[:9]}", is_active=True)
    db_session.add_all([program, user])
    db_session.flush()
    photo = CredentialPhoto(user_id=user.id, ref=secrets.token_urlsafe(12),
                            file_name=f"{uuid.uuid4().hex}.jpg",
                            width=600, height=789, size_bytes=len(PHOTO_BYTES))
    db_session.add_all([StudentProfile(user_id=user.id, program_id=program.id), photo])
    db_session.flush()
    (photo_dir / photo.file_name).write_bytes(PHOTO_BYTES)
    return user, photo, program_name


@pytest.fixture
def credencial_app(db_session):
    app = db_session.query(App).filter_by(key="credencial").first()
    if app is None:
        app = App(key="credencial", name="Credencial Digital", is_active=True)
        db_session.add(app)
    app.is_active = True
    db_session.flush()
    return app


@pytest.fixture
def staff(db_session, credencial_app):
    """Personal con el permiso de verificación completa asignado directo."""
    code = "credencial.verify.page.full"
    perm = db_session.query(Permission).filter_by(app_id=credencial_app.id, code=code).first()
    if perm is None:
        perm = Permission(app_id=credencial_app.id, code=code, name="Verificación completa")
        db_session.add(perm)
    user = User(first_name="Vigilante", last_name="Prueba", username=f"vig_{uuid.uuid4().hex[:8]}")
    db_session.add(user)
    db_session.flush()
    db_session.add(UserAppPerm(user_id=user.id, app_id=credencial_app.id, perm_id=perm.id, allow=True))
    db_session.flush()
    return user


def _token(photo, **delta):
    return CredentialTokenService.issue(photo.ref, now=datetime.now(timezone.utc) - timedelta(**delta))


def _get(client, token, cookie=None):
    headers = {"Cookie": f"itcj_token={cookie}"} if cookie else {}
    return client.get(f"/credencial/v/{token}", headers=headers)


def _log_count(db, user):
    return db.query(CredentialVerification).filter_by(student_id=user.id).count()


def _assert_no_personal_data(html, user):
    for leak in (FIRST, LAST, MIDDLE, user.control_number, "data:image"):
        assert leak not in html, leak


# ── estados ──────────────────────────────────────────────────────────────────
def test_valid_shows_name_program_photo(client, student):
    user, photo, program_name = student
    resp = _get(client, _token(photo))
    assert resp.status_code == 200
    html = resp.text
    assert "VÁLIDA" in html
    assert f"{FIRST} {LAST} {MIDDLE}" in html          # orden Nombre Apellidos
    assert program_name in html
    assert "data:image/jpeg;base64," in html
    assert user.control_number not in html              # vista anónima: sin nº de control
    assert "Verificado a las" in html and "Código emitido a las" in html


def test_valid_without_photo_file_still_renders(client, student, photo_dir):
    user, photo, _ = student
    (photo_dir / photo.file_name).unlink()
    resp = _get(client, _token(photo))
    assert resp.status_code == 200
    assert "VÁLIDA" in resp.text and "data:image" not in resp.text


def test_inactive_shows_no_vigente(client, db_session, student):
    user, photo, program_name = student
    token = _token(photo)
    user.is_active = False
    db_session.flush()
    html = _get(client, token).text
    assert "NO VIGENTE" in html
    assert "VÁLIDA" not in html
    assert f"{FIRST} {LAST} {MIDDLE}" in html and "data:image/jpeg" in html
    assert program_name not in html                     # «sin más datos»


def test_expired_leaks_nothing(client, student):
    user, photo, program_name = student
    resp = _get(client, _token(photo, seconds=61))
    assert "Código vencido" in resp.text
    _assert_no_personal_data(resp.text, user)
    assert program_name not in resp.text


@pytest.mark.parametrize("mangle", ["mac", "ref", "garbage"])
def test_invalid_leaks_nothing(client, student, mangle):
    user, photo, program_name = student
    ref, iat, mac = _token(photo).rsplit(".", 2)
    token = {
        "mac": f"{ref}.{iat}.{'A' if mac[0] != 'A' else 'B'}{mac[1:]}",
        "ref": f"{secrets.token_urlsafe(12)}.{iat}.{mac}",
        "garbage": "no-es-un-token",
    }[mangle]
    resp = _get(client, token)
    assert "Código no válido" in resp.text
    _assert_no_personal_data(resp.text, user)
    assert program_name not in resp.text


def test_unknown_ref_with_valid_signature_is_invalid(client, student):
    user, _, _ = student
    token = CredentialTokenService.issue(secrets.token_urlsafe(12))
    resp = _get(client, token)
    assert "Código no válido" in resp.text
    _assert_no_personal_data(resp.text, user)


# ── cabeceras y rate limit ───────────────────────────────────────────────────
def test_headers_on_every_status(client, db_session, student):
    user, photo, _ = student
    responses = [
        _get(client, _token(photo)),                  # valid
        _get(client, _token(photo, seconds=120)),     # expired
        _get(client, "x" * 200),                      # invalid (largo)
    ]
    user.is_active = False
    db_session.flush()
    responses.append(_get(client, _token(photo)))     # inactive
    with patch("itcj2.core.utils.rate_limit.check_and_count", return_value=(False, 42)):
        responses.append(_get(client, _token(photo)))  # 429

    assert len({r.status_code for r in responses}) >= 3
    for resp in responses:
        for name, value in PUBLIC_HEADERS.items():
            assert resp.headers.get(name) == value, (resp.status_code, name)


def test_rate_limited_429(client, student):
    user, photo, _ = student
    with patch("itcj2.core.utils.rate_limit.check_and_count", return_value=(False, 42)) as rl:
        resp = _get(client, _token(photo))
    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "42"
    _assert_no_personal_data(resp.text, user)
    scope, key = rl.call_args.args[:2]
    assert scope == "credencial-verify" and key
    assert rl.call_args.kwargs["limit"] == 30 and rl.call_args.kwargs["window"] == 60


def test_rate_limit_keys_on_real_client_ip(client, student):
    _, photo, _ = student
    with patch("itcj2.core.utils.rate_limit.check_and_count", return_value=(True, 0)) as rl:
        client.get(f"/credencial/v/{_token(photo)}", headers={"X-Real-IP": "203.0.113.7"})
    assert rl.call_args.args[1] == "203.0.113.7"


# ── vista completa y bitácora ────────────────────────────────────────────────
def test_staff_with_perm_sees_control_and_logs_row(client, db_session, student, staff):
    user, photo, _ = student
    resp = _get(client, _token(photo), cookie=make_jwt(user_id=staff.id, role="staff"))
    assert resp.status_code == 200
    assert user.control_number in resp.text
    assert "Verificación registrada" in resp.text
    row = db_session.query(CredentialVerification).filter_by(student_id=user.id).one()
    assert (row.verifier_id, row.result) == (staff.id, "valid")


def test_staff_inactive_logs_inactive(client, db_session, student, staff):
    user, photo, _ = student
    token = _token(photo)
    user.is_active = False
    db_session.flush()
    resp = _get(client, token, cookie=make_jwt(user_id=staff.id, role="staff"))
    assert "NO VIGENTE" in resp.text and "VÁLIDA" not in resp.text
    row = db_session.query(CredentialVerification).filter_by(student_id=user.id).one()
    assert row.result == "inactive"


def test_staff_expired_token_no_log_no_data(client, db_session, student, staff):
    user, photo, _ = student
    resp = _get(client, _token(photo, seconds=61), cookie=make_jwt(user_id=staff.id, role="staff"))
    _assert_no_personal_data(resp.text, user)
    assert _log_count(db_session, user) == 0


def test_student_session_gets_public_view_and_no_log(client, db_session, student, credencial_app):
    user, photo, _ = student
    other = User(first_name="Otro", last_name="Alumno", control_number=f"Y{uuid.uuid4().hex[:9]}")
    db_session.add(other)
    db_session.flush()
    resp = _get(client, _token(photo),
                cookie=make_jwt(user_id=other.id, role="student", cn=other.control_number))
    assert "VÁLIDA" in resp.text
    assert user.control_number not in resp.text
    assert "Verificación registrada" not in resp.text
    assert _log_count(db_session, user) == 0


def test_anonymous_no_log(client, db_session, student):
    user, photo, _ = student
    resp = _get(client, _token(photo))
    assert "VÁLIDA" in resp.text and "Verificación registrada" not in resp.text
    assert _log_count(db_session, user) == 0


def test_global_admin_sees_full_view_and_logs_row(client, db_session, student):
    """Admin global del JWT: vista completa sin asignación en la app (public.py, is_global_admin)."""
    user, photo, _ = student
    admin = User(first_name="Admin", last_name="Global", username=f"adm_{uuid.uuid4().hex[:8]}")
    db_session.add(admin)
    db_session.flush()
    resp = _get(client, _token(photo), cookie=make_jwt(user_id=admin.id, role="admin"))
    assert resp.status_code == 200
    assert user.control_number in resp.text and "Verificación registrada" in resp.text
    row = db_session.query(CredentialVerification).filter_by(student_id=user.id).one()
    assert row.verifier_id == admin.id


def test_session_with_credencial_app_inactive_gets_public_view(client, db_session, student, staff, credencial_app):
    """App credencial inactiva/ausente: cached_perms lanza 404 y la página sigue en vista pública."""
    user, photo, _ = student
    credencial_app.is_active = False
    db_session.flush()
    resp = _get(client, _token(photo), cookie=make_jwt(user_id=staff.id, role="staff"))
    assert resp.status_code == 200
    assert "VÁLIDA" in resp.text
    assert user.control_number not in resp.text and "Verificación registrada" not in resp.text
    for name, value in PUBLIC_HEADERS.items():
        assert resp.headers.get(name) == value, name
    assert _log_count(db_session, user) == 0


def test_referrer_meta_precedes_every_link(client, student):
    """La política de la página debe regir antes de pedir el primer recurso externo."""
    _, photo, _ = student
    html = _get(client, _token(photo)).text
    assert html.index('<meta name="referrer" content="no-referrer">') < html.index("<link")
