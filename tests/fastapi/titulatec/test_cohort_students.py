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


# ---------------------------------------------------------------------------
# Formato del número de control (2026-09-17): normaliza y rechaza el viejo,
# ejercitando la ruta HTTP real (`student_add`), no solo `_add_student`: la
# normalización vive en la ruta, ANTES de llamar a `_add_student`.
# ---------------------------------------------------------------------------
def test_student_add_normaliza_letra_del_control_a_mayuscula(
    client_as, db_session, titulatec_app, seed_phase_defs, make_cohort,
    make_program, make_modality, make_head,
):
    """`b99400001` (traslado, minúscula) se guarda como `B99400001`: el merge
    de `import_rows` es un filter_by exacto y una letra distinta duplicaría
    la cuenta en vez de adjuntarla a la convocatoria."""
    from itcj2.core.models.user import User

    seed_phase_defs()
    cohort = make_cohort()
    program = make_program("Ingenieria Manual")
    modality = make_modality(name="Modalidad Manual")
    client = client_as(make_head())

    resp = client.post(
        "/titulatec/admin/cohorts/{}/students".format(cohort.id),
        data={"control_number": "b99400001", "full_name": "ALUMNA TRASLADO",
              "email": "", "program_id": str(program.id), "modality_id": str(modality.id)},
    )

    assert resp.status_code == 200, resp.text[:400]
    assert db_session.query(User).filter_by(control_number="B99400001").count() == 1
    assert db_session.query(User).filter_by(control_number="b99400001").count() == 0


def test_student_add_no_crea_usuario_con_formato_viejo_de_control(
    client_as, db_session, titulatec_app, seed_phase_defs, make_cohort,
    make_program, make_modality, make_head,
):
    """Letra + 7 dígitos (formato viejo, retirado el 2026-09-17): `import_rows`
    descarta la fila (`skipped`) igual que con cualquier otro control inválido,
    así que el alta manual no crea nada."""
    from itcj2.core.models.user import User

    seed_phase_defs()
    cohort = make_cohort()
    program = make_program("Ingenieria Manual")
    modality = make_modality(name="Modalidad Manual")
    client = client_as(make_head())

    resp = client.post(
        "/titulatec/admin/cohorts/{}/students".format(cohort.id),
        data={"control_number": "M9940002", "full_name": "ALUMNO VIEJO FORMATO",
              "email": "", "program_id": str(program.id), "modality_id": str(modality.id)},
    )

    assert resp.status_code == 200, resp.text[:400]
    assert db_session.query(User).filter_by(control_number="M9940002").count() == 0
