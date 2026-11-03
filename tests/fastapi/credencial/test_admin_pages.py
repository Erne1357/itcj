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


def _cookie(user, role="staff", script=True):
    """Cabeceras como las manda el panel; script=False = un <form>/fetch no-cors de otro sitio."""
    headers = {"Cookie": f"itcj_token={make_jwt(user_id=user.id, role=role, cn=user.control_number)}"}
    if script:
        headers["X-Requested-With"] = "fetch"
    return headers


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
    # Vigilancia (solo vista completa): su tile del móvil abre aquí; ve cómo verificar, no el 403 del core.
    assert "Escanea el QR" in r.text and "Fotos de credencial" not in r.text
    assert 'id="mobileBackToDashboard"' in r.text
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


BOUND = 9  # medido


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
    assert len(n) <= BOUND  # autorizacion + conteo + una consulta de filas; no crece con las filas


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


def test_batch_reports_statuses(client, clerk, bare, student, db_session):
    existing, _, _ = student
    existing.control_number = _control()
    broken = User(first_name="Foto", last_name="Rota", control_number=_control(), is_active=True)
    db_session.add(broken)
    db_session.flush()
    files = [
        ("files", (f"{bare.control_number}.jpg", _jpeg(), "image/jpeg")),
        ("files", (f"{existing.control_number}.jpg", _jpeg((0, 90, 0)), "image/jpeg")),
        ("files", ("00000000.jpg", _jpeg(), "image/jpeg")),
        ("files", (f"{broken.control_number}.png", b"basura", "image/png")),
    ]
    r = client.post("/credencial/admin/fotos/lote", headers=_cookie(clerk), files=files)
    assert r.status_code == 200 and r.json()["success"] is True
    by_name = {row["filename"]: row["status"] for row in r.json()["data"]}
    assert by_name[f"{bare.control_number}.jpg"] == "created"
    assert by_name[f"{existing.control_number}.jpg"] == "replaced"
    assert by_name["00000000.jpg"] == "no_student"
    assert by_name[f"{broken.control_number}.png"] == "invalid"


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


def test_global_admin_reaches_photo_upload_and_batch(client, student, bare, db_session):
    root = User(first_name="Root", last_name="Admin", username=f"r_{uuid.uuid4().hex[:8]}")
    db_session.add(root)
    db_session.flush()
    h = _cookie(root, "admin")
    user, _, _ = student
    assert client.get(f"/credencial/admin/alumnos/{user.id}/foto", headers=h).status_code == 200
    r = client.post(f"/credencial/admin/alumnos/{bare.id}/foto", headers=h,
                    files={"file": ("x.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 200
    r = client.post("/credencial/admin/fotos/lote", headers=h,
                    files=[("files", ("00000000.jpg", _jpeg(), "image/jpeg"))])
    assert r.status_code == 200 and r.json()["data"][0]["status"] == "no_student"


def test_search_escapes_like_wildcards(client, clerk, student):
    user, _, _ = student
    for q in ("%", "_", "Z%", "Xochi_uetzal"):
        r = client.get("/credencial/admin/buscar", params={"q": q}, headers=_cookie(clerk))
        assert r.status_code == 200 and user.control_number not in r.text


def test_search_missing_filter(client, clerk, student, bare):
    with_photo, _, _ = student
    r = client.get("/credencial/admin/buscar", params={"q": bare.control_number, "missing": "1"}, headers=_cookie(clerk))
    assert bare.control_number in r.text
    r = client.get("/credencial/admin/buscar", params={"q": with_photo.control_number, "missing": "1"},
                   headers=_cookie(clerk))
    assert with_photo.control_number not in r.text


# ── CSRF: las escrituras exigen la cabecera que solo pone un script de la página ──
def test_writes_without_script_header_rejected(client, clerk, bare, student, db_session):
    user, _, _ = student
    forged = _cookie(clerk, script=False)
    r = client.post(f"/credencial/admin/alumnos/{bare.id}/foto", headers=forged,
                    files={"file": ("x.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 403 and "detail" in r.json()
    r = client.post("/credencial/admin/fotos/lote", headers=forged,
                    files=[("files", (f"{bare.control_number}.jpg", _jpeg(), "image/jpeg"))])
    assert r.status_code == 403
    assert client.delete(f"/credencial/admin/alumnos/{user.id}/foto", headers=forged).status_code == 403
    db_session.expire_all()
    assert db_session.get(CredentialPhoto, bare.id) is None
    assert db_session.get(CredentialPhoto, user.id) is not None
    # las lecturas no la piden
    assert client.get("/credencial/admin/buscar", headers=forged).status_code == 200


def test_htmx_header_accepted_for_writes(client, clerk, bare):
    headers = {**_cookie(clerk, script=False), "HX-Request": "true"}
    r = client.post(f"/credencial/admin/alumnos/{bare.id}/foto", headers=headers,
                    files={"file": ("x.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 200 and r.json()["data"]["status"] == "created"


def test_single_upload_crafted_file_is_400_not_500(client, clerk, bare, monkeypatch):
    import struct

    from itcj2.apps.credencial.services import photo_service

    def boom(img):
        raise struct.error("crafted")

    monkeypatch.setattr(photo_service.ImageOps, "exif_transpose", boom)
    r = client.post(f"/credencial/admin/alumnos/{bare.id}/foto", headers=_cookie(clerk),
                    files={"file": ("x.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 400 and "no es una imagen" in r.json()["detail"]


# ── páginas completas: nunca JSON crudo ──────────────────────────────────────
def test_admin_pages_render_html_when_app_inactive(client, clerk, credencial_app, db_session):
    """Antes de init-credencial (o con la app apagada) las páginas no deben pintar JSON."""
    credencial_app.is_active = False
    db_session.flush()
    r = client.get("/credencial/admin/", headers=_cookie(clerk))
    assert r.status_code == 403 and r.headers["content-type"].startswith("text/html")
    assert "Escanea el QR" in r.text
    r = client.get("/credencial/admin/verificaciones", headers=_cookie(clerk))
    assert r.headers["content-type"].startswith("text/html") and not r.text.lstrip().startswith("{")
    # los parciales y el JSON siguen respondiendo JSON
    r = client.get("/credencial/admin/buscar", headers=_cookie(clerk))
    assert r.status_code == 403 and r.json()["success"] is False


# ── mismo nombre en lista, bitácora y vista previa ───────────────────────────
def test_all_caps_name_title_cased_everywhere(client, clerk, db_session, photo_dir):
    caps = User(first_name="JUAN CARLOS", last_name="PÉREZ", middle_name="LÓPEZ",
                control_number=_control(), is_active=True)
    db_session.add(caps)
    db_session.flush()
    db_session.add(CredentialVerification(student_id=caps.id, verifier_id=clerk.id, result="valid",
                                          token_issued_at=datetime(2026, 11, 3, 10, 0)))
    db_session.flush()
    printed = "Juan Carlos Pérez López"
    r = client.get("/credencial/admin/buscar", params={"q": caps.control_number}, headers=_cookie(clerk))
    assert printed in r.text and "JUAN CARLOS" not in r.text
    r = client.get("/credencial/admin/verificaciones", headers=_cookie(clerk))
    assert printed in r.text
    r = client.get(f"/credencial/admin/alumnos/{caps.id}", headers=_cookie(clerk))
    assert printed in r.text


def test_deleted_verifier_labelled(client, clerk, student, db_session):
    user, _, _ = student
    db_session.add(CredentialVerification(student_id=user.id, verifier_id=None, result="valid",
                                          token_issued_at=datetime(2026, 11, 3, 10, 0)))
    db_session.flush()
    r = client.get("/credencial/admin/verificaciones", headers=_cookie(clerk))
    assert "Usuario eliminado" in r.text and "Sin sesión" not in r.text


def test_search_form_has_no_inline_handler(client, clerk):
    html = client.get("/credencial/admin/", headers=_cookie(clerk)).text
    assert "onsubmit=" not in html and "data-batch-max" not in html and "data-can-upload" not in html
    assert "bootstrap.bundle.min.js" in html and "mobile-app-shell.js" in html  # el panel sí los usa
