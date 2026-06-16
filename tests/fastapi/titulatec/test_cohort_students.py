"""Alta manual de alumno en convocatoria (crear/adjuntar)."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import itcj2.models  # noqa: F401
from itcj2.apps.titulatec.pages import admin as admin_page


@patch("itcj2.apps.titulatec.pages.admin.hash_nip", return_value="HASH")
def test_add_student_nuevo_setea_password(mock_hash):
    """Si el usuario no existía, tras import_rows se le setea password = control."""
    db = MagicMock()
    cohort = SimpleNamespace(id=3)
    nuevo = SimpleNamespace(id=99, password_hash=None, must_change_password=True)
    # 1ra llamada (antes del import): no existe; 2da (después): existe
    db.query.return_value.filter_by.return_value.first.side_effect = [None, nuevo]
    with patch("itcj2.apps.titulatec.services.import_service.ImportService.import_rows",
               return_value={"created_users": 1, "matched_users": 0, "processes_created": 1, "skipped": 0}):
        admin_page._add_student(db, cohort, control="10110220", full_name="X Y",
                                email=None, program_id=1, modality_id=1)
    assert nuevo.password_hash == "HASH"
    assert nuevo.must_change_password is True


@patch("itcj2.apps.titulatec.pages.admin.hash_nip", return_value="HASH")
def test_add_student_existente_no_cambia_password(mock_hash):
    """Si el usuario ya existía, NO se le toca el password."""
    db = MagicMock()
    cohort = SimpleNamespace(id=3)
    existente = SimpleNamespace(id=5, password_hash="VIEJO", must_change_password=False)
    db.query.return_value.filter_by.return_value.first.return_value = existente
    with patch("itcj2.apps.titulatec.services.import_service.ImportService.import_rows",
               return_value={"created_users": 0, "matched_users": 1, "processes_created": 1, "skipped": 0}):
        admin_page._add_student(db, cohort, control="10110220", full_name="X Y",
                                email=None, program_id=1, modality_id=1)
    assert existente.password_hash == "VIEJO"
    mock_hash.assert_not_called()
