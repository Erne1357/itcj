"""CardService.build: datos de la tarjeta (orden del nombre, etiquetas, foto).

Fixtures (`student`, `photo_dir`) en conftest.py; CI = base vacía.
"""
import uuid
from unittest.mock import patch

from fastapi import HTTPException

from itcj2.apps.credencial.services.card_service import CardService
from itcj2.core.models.app import App
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from tests.fastapi.credencial.conftest import FIRST, LAST, MIDDLE


def test_card_name_order(db_session, student):
    user, photo, program_name = student
    card = CardService.build(db_session, user.id)
    assert card.display_name == f"{FIRST} {LAST} {MIDDLE}"   # Nombre Apellido paterno Apellido materno
    assert card.control_number == user.control_number
    assert card.program_label == program_name
    assert card.role_label == "Estudiante"
    assert (card.has_photo, card.photo_ref) == (True, photo.ref)


def test_card_egresado_label(db_session, student):
    user, _, _ = student
    app = db_session.query(App).filter_by(key="titulatec").first()
    if app is None:
        app = App(key="titulatec", name="TitulaTec", is_active=True)
        db_session.add(app)
    app.is_active = True
    role = db_session.query(Role).filter_by(name="graduate").first() or Role(name="graduate")
    db_session.add(role)
    db_session.flush()
    db_session.add(UserAppRole(user_id=user.id, app_id=app.id, role_id=role.id))
    db_session.flush()
    assert CardService.build(db_session, user.id).role_label == "Egresado"


def test_card_without_titulatec_app_is_estudiante(db_session, student):
    """CI no siembra titulatec: get_or_404_app lanza 404 y la tarjeta no debe dar 500."""
    user, _, _ = student
    with patch("itcj2.core.services.authz_cache.cached_roles",
               side_effect=HTTPException(status_code=404, detail="App 'titulatec' no existe")):
        assert CardService.build(db_session, user.id).role_label == "Estudiante"


def test_card_none_for_staff(db_session):
    staff = User(first_name="Ana", last_name="Personal", username=f"st_{uuid.uuid4().hex[:8]}")
    db_session.add(staff)
    db_session.flush()
    assert CardService.build(db_session, staff.id) is None
    assert CardService.build(db_session, staff.id + 10_000_000) is None


def test_card_without_program_or_photo(db_session, photo_dir):
    user = User(first_name="Sin", last_name="Datos", control_number=f"Y{uuid.uuid4().hex[:9]}")
    db_session.add(user)
    db_session.flush()
    card = CardService.build(db_session, user.id)
    assert card.program_label is None
    assert (card.has_photo, card.photo_ref) == (False, None)


def test_card_photo_row_without_file_has_no_photo(db_session, student, photo_dir):
    """Fila sin archivo en disco = sin foto: ni hueco roto ni QR que verifique sin cara."""
    user, photo, _ = student
    (photo_dir / photo.file_name).unlink()
    card = CardService.build(db_session, user.id)
    assert (card.has_photo, card.photo_ref) == (False, None)


def test_card_uppercase_name_title_cased(db_session):
    user = User(first_name="JOSÉ ÁNGEL", last_name="NÚÑEZ", middle_name="O'NEIL",
                control_number=f"Y{uuid.uuid4().hex[:9]}")
    mixed = User(first_name="Ana", last_name="de la Rosa", control_number=f"Y{uuid.uuid4().hex[:9]}")
    db_session.add_all([user, mixed])
    db_session.flush()
    assert CardService.build(db_session, user.id).display_name == "José Ángel Núñez O'Neil"
    assert CardService.build(db_session, mixed.id).display_name == "Ana de la Rosa"   # mixto: tal cual
