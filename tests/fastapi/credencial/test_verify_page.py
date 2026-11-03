"""Página pública /credencial/v/{token}: estados, cero fugas, cabeceras y bitácora.

Las filas (alumno, carrera, foto, app y permiso) las crean las fixtures de
`conftest.py` dentro del savepoint de `db_session` (CI = base vacía).
"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from itcj2.apps.credencial.models import CredentialVerification
from itcj2.apps.credencial.services.token_service import CredentialTokenService
from itcj2.core.models.user import User
from tests.conftest import make_jwt
from tests.fastapi.credencial.conftest import FIRST, LAST, MIDDLE

PUBLIC_HEADERS = {
    "cache-control": "no-store",
    "x-robots-tag": "noindex, nofollow",
    "referrer-policy": "no-referrer",
}


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
    assert f"{program_name} / Estudiante" in html       # misma línea 2 que la tarjeta
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
    assert "Estudiante" not in html


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
        responses.append(_get(client, "no-es-un-token"))  # 429

    assert {r.status_code for r in responses} == {200, 404, 429}
    for resp in responses:
        for name, value in PUBLIC_HEADERS.items():
            assert resp.headers.get(name) == value, (resp.status_code, name)


@pytest.mark.parametrize("kind", ["invalid", "expired"])
def test_rate_limited_429(client, student, kind):
    from itcj2.config import get_settings

    user, photo, _ = student
    token = "no-es-un-token" if kind == "invalid" else _token(photo, seconds=61)
    with patch("itcj2.core.utils.rate_limit.check_and_count", return_value=(False, 42)) as rl:
        resp = _get(client, token)
    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "42"
    assert "Espera un momento" in resp.text
    _assert_no_personal_data(resp.text, user)
    scope, key = rl.call_args.args[:2]
    assert scope == "credencial-verify" and key
    assert rl.call_args.kwargs["limit"] == get_settings().CREDENCIAL_VERIFY_RL_LIMIT
    assert rl.call_args.kwargs["window"] == 60


def test_valid_token_never_rate_limited(client, db_session, student):
    """En prod el cubo es global (IP de Docker): un token bien firmado pasa aunque el cubo esté lleno."""
    user, photo, _ = student
    with patch("itcj2.core.utils.rate_limit.check_and_count", return_value=(False, 42)) as rl:
        valid = _get(client, _token(photo))
        user.is_active = False
        db_session.flush()
        inactive = _get(client, _token(photo))
    assert valid.status_code == 200 and "VÁLIDA" in valid.text
    assert inactive.status_code == 200 and "NO VIGENTE" in inactive.text
    rl.assert_not_called()


def test_rate_limit_counts_only_rejections(client, student):
    _, photo, _ = student
    with patch("itcj2.core.utils.rate_limit.check_and_count", return_value=(True, 0)) as rl:
        assert _get(client, "no-es-un-token").status_code == 404
        assert _get(client, _token(photo, seconds=61)).status_code == 404
        assert _get(client, _token(photo)).status_code == 200
    assert rl.call_count == 2


def test_verify_rate_limit_setting_is_bounded():
    from pydantic import ValidationError

    from itcj2.config import Settings

    with pytest.raises(ValidationError):
        Settings(CREDENCIAL_VERIFY_RL_LIMIT=0)


def test_rate_limit_keys_on_real_client_ip(client, student):
    with patch("itcj2.core.utils.rate_limit.check_and_count", return_value=(True, 0)) as rl:
        client.get("/credencial/v/no-es-un-token", headers={"X-Real-IP": "203.0.113.7"})
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


def test_valid_uses_card_labels(client, db_session, student):
    """Carrera con la etiqueta de la tarjeta (sin sufijo EAD) y «Egresado» para graduate."""
    from itcj2.core.models.program import Program
    from itcj2.core.models.student_profile import StudentProfile

    user, photo, _ = student
    program = Program(name=f"Ing. Sistemas computacionales {uuid.uuid4().hex[:6]} EAD")
    db_session.add(program)
    db_session.flush()
    db_session.get(StudentProfile, user.id).program_id = program.id
    db_session.flush()
    with patch("itcj2.core.services.authz_cache.cached_roles", return_value={"graduate"}):
        html = _get(client, _token(photo)).text
    assert "VÁLIDA" in html
    assert f"{program.name.removesuffix(' EAD')} / Egresado" in html
    assert " EAD" not in html
