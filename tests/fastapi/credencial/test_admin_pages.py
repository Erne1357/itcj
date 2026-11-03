"""Panel de Servicios Escolares: /credencial/admin/*. CI = base vacia (fixtures en conftest.py)."""
import io
import uuid
from datetime import datetime

import pytest
from PIL import Image
from sqlalchemy import event

from itcj2.apps.credencial.models import CredentialPhoto, CredentialVerification
from itcj2.core.models.user import User
from tests.conftest import make_jwt
from tests.fastapi.credencial.conftest import FIRST, LAST, grant


def _cookie(user, role="staff"):
    return {"Cookie": f"itcj_token={make_jwt(user_id=user.id, role=role, cn=user.control_number)}"}


def _control() -> str:
    return str(uuid.uuid4().int)[:8]  # normalize_control exige 8 digitos


def _jpeg(color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), color).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def clerk(db_session, credencial_app):
    """Personal de Servicios Escolares con todos los permisos del panel."""
    user = User(first_name="Ventanilla", last_name="Escolares", username=f"se_{uuid.uuid4().hex[:8]}")
    db_session.add(user)
    db_session.flush()
    for code in ("credencial.admin.page.view", "credencial.photos.api.upload",
                 "credencial.photos.api.delete", "credencial.verifications.page.list"):
        grant(db_session, credencial_app, user, code)
    return user


@pytest.fixture
def outsider(db_session, credencial_app):
    """Tiene la app (otro permiso) pero no los del panel."""
    user = User(first_name="Otro", last_name="Personal", username=f"ot_{uuid.uuid4().hex[:8]}")
    db_session.add(user)
    db_session.flush()
    grant(db_session, credencial_app, user, "credencial.verify.page.full")
    return user


@pytest.fixture
def bare(db_session, photo_dir):
    user = User(first_name="Sin", last_name="Fotografia", control_number=_control(), is_active=True)
    db_session.add(user)
    db_session.flush()
    return user


def test_admin_requires_perm(client, outsider):
    r = client.get("/credencial/admin/", headers=_cookie(outsider), follow_redirects=False)
    assert r.status_code == 403
    r = client.get("/credencial/admin/", follow_redirects=False)
    assert r.status_code in (302, 303, 307) and "/login" in r.headers["location"]


def test_admin_page_ok_for_clerk_and_global_admin(client, clerk, db_session):
    assert client.get("/credencial/admin/", headers=_cookie(clerk)).status_code == 200
    root = User(first_name="Root", last_name="Admin", username=f"r_{uuid.uuid4().hex[:8]}")
    db_session.add(root)
    db_session.flush()
    assert client.get("/credencial/admin/", headers=_cookie(root, "admin")).status_code == 200


def test_search_by_control_and_name(client, clerk, student):
    user, _, _ = student
    r = client.get("/credencial/admin/buscar", params={"q": user.control_number[:6]}, headers=_cookie(clerk))
    assert r.status_code == 200 and user.control_number in r.text
    r = client.get("/credencial/admin/buscar", params={"q": f"{FIRST.lower()} {LAST}"}, headers=_cookie(clerk))
    assert user.control_number in r.text
    r = client.get("/credencial/admin/buscar", params={"q": "zzzznoexiste"}, headers=_cookie(clerk))
    assert user.control_number not in r.text


def test_search_excludes_staff(client, clerk):
    r = client.get("/credencial/admin/buscar", params={"q": "Ventanilla"}, headers=_cookie(clerk))
    assert "Ventanilla" not in r.text


def test_search_has_no_per_row_queries(client, clerk, student, bare, db_session):
    n = []
    engine = db_session.get_bind()

    def count(*a, **k):
        n.append(1)

    event.listen(engine, "before_cursor_execute", count)
    try:
        client.get("/credencial/admin/buscar", params={"q": ""}, headers=_cookie(clerk))
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(n) <= 14  # autorizacion + conteo + una consulta de filas; no crece con las filas


def test_upload_single_creates_photo(client, clerk, bare, db_session):
    r = client.post(f"/credencial/admin/alumnos/{bare.id}/foto", headers=_cookie(clerk),
                    files={"file": ("x.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 200 and r.json()["data"]["status"] == "created"
    assert db_session.get(CredentialPhoto, bare.id).uploaded_by_id == clerk.id
    r = client.get(f"/credencial/admin/alumnos/{bare.id}/foto", headers=_cookie(clerk))
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    assert r.content[:2] == b"\xff\xd8"


def test_upload_rejects_non_image(client, clerk, bare):
    r = client.post(f"/credencial/admin/alumnos/{bare.id}/foto", headers=_cookie(clerk),
                    files={"file": ("x.jpg", b"no soy imagen", "image/jpeg")})
    assert r.status_code == 400 and "detail" in r.json()


def test_batch_reports_statuses(client, clerk, bare, student):
    existing, _, _ = student
    existing.control_number = _control()
    files = [
        ("files", (f"{bare.control_number}.jpg", _jpeg(), "image/jpeg")),
        ("files", (f"{existing.control_number}.jpg", _jpeg((0, 90, 0)), "image/jpeg")),
        ("files", ("00000000.jpg", _jpeg(), "image/jpeg")),
        ("files", ("roto.png", b"basura", "image/png")),
    ]
    r = client.post("/credencial/admin/fotos/lote", headers=_cookie(clerk), files=files)
    assert r.status_code == 200 and r.json()["success"] is True
    by_name = {row["filename"]: row["status"] for row in r.json()["data"]}
    assert by_name[f"{bare.control_number}.jpg"] == "created"
    assert by_name[f"{existing.control_number}.jpg"] == "replaced"
    assert by_name["00000000.jpg"] == "no_student"
    assert by_name["roto.png"] in ("invalid", "no_student")


def test_batch_over_20_rejected_400(client, clerk):
    files = [("files", (f"{i}.jpg", b"x", "image/jpeg")) for i in range(21)]
    r = client.post("/credencial/admin/fotos/lote", headers=_cookie(clerk), files=files)
    assert r.status_code == 400


def test_batch_requires_perm_json_errors(client, outsider):
    files = [("files", ("1.jpg", b"x", "image/jpeg"))]
    assert client.post("/credencial/admin/fotos/lote", headers=_cookie(outsider), files=files).status_code == 403
    r = client.post("/credencial/admin/fotos/lote", files=files)
    assert r.status_code == 401 and "detail" in r.json()


def test_delete_photo(client, clerk, student, db_session, photo_dir):
    user, photo, _ = student
    name = photo.file_name
    r = client.delete(f"/credencial/admin/alumnos/{user.id}/foto", headers=_cookie(clerk))
    assert r.status_code == 200
    db_session.expire_all()
    assert db_session.get(CredentialPhoto, user.id) is None
    assert not (photo_dir / name).exists()
    r = client.delete(f"/credencial/admin/alumnos/{user.id}/foto", headers=_cookie(clerk))
    assert r.status_code == 404


def test_admin_photo_forbidden_without_perm(client, outsider, student):
    user, _, _ = student
    url = f"/credencial/admin/alumnos/{user.id}/foto"
    assert client.get(url, headers=_cookie(outsider)).status_code == 403
    assert client.get(url).status_code == 401
    assert client.post(url, headers=_cookie(outsider),
                       files={"file": ("a.jpg", _jpeg(), "image/jpeg")}).status_code == 403
    assert client.delete(url, headers=_cookie(outsider)).status_code == 403


def test_student_partial_has_preview(client, clerk, student):
    user, _, _ = student
    r = client.get(f"/credencial/admin/alumnos/{user.id}", headers=_cookie(clerk))
    assert r.status_code == 200 and f"/credencial/admin/alumnos/{user.id}/foto" in r.text
    assert client.get("/credencial/admin/alumnos/999999999", headers=_cookie(clerk)).status_code == 404


def test_verifications_list_paginated(client, clerk, student, outsider, db_session):
    user, _, _ = student
    for _ in range(51):
        db_session.add(CredentialVerification(student_id=user.id, verifier_id=clerk.id, result="valid",
                                              token_issued_at=datetime(2026, 11, 3, 10, 0)))
    db_session.flush()
    r1 = client.get("/credencial/admin/verificaciones", headers=_cookie(clerk))
    assert r1.status_code == 200 and r1.text.count("data-v-row") == 50
    r2 = client.get("/credencial/admin/verificaciones", params={"page": 2}, headers=_cookie(clerk))
    assert r2.text.count("data-v-row") >= 1
    assert client.get("/credencial/admin/verificaciones", headers=_cookie(outsider)).status_code == 403
