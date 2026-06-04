from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import itcj2.models  # noqa: F401
from itcj2.apps.titulatec.services.officer_service import OfficerService


@patch("itcj2.apps.titulatec.services.officer_service.positions_service")
def test_set_programs_sincroniza(mock_ps):
    """set_programs borra las filas previas y crea las nuevas (ProgramPosition)."""
    db = MagicMock()
    existing = [SimpleNamespace(program_id=1), SimpleNamespace(program_id=2)]
    db.query.return_value.filter_by.return_value.all.return_value = existing

    OfficerService.set_programs(db, position_id=10, program_ids={2, 3})

    db.commit.assert_called_once()


@patch("itcj2.apps.titulatec.services.officer_service.positions_service")
def test_create_officer_rechaza_user_fuera_del_depto(mock_ps):
    db = MagicMock()
    mock_ps.create_position.return_value = SimpleNamespace(id=10)
    with patch.object(OfficerService, "department_user_ids", return_value={5}):
        try:
            OfficerService.create_officer(
                db, department_id=2, assigned_role="titulatec_school_services",
                name="Enc A", program_ids={1}, user_ids={9},
            )
            assert False, "debió lanzar ValueError"
        except ValueError:
            pass
