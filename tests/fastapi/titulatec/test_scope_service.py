"""Tests del helper de alcance por carrera."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import itcj2.models  # noqa: F401
from itcj2.apps.titulatec.services.scope_service import officer_programs


@patch("itcj2.apps.titulatec.services.scope_service._user_perms")
def test_all_si_tiene_read_all(mock_perms):
    mock_perms.return_value = {"titulatec.process.api.read.all"}
    assert officer_programs(MagicMock(), 1) == "ALL"


@patch("itcj2.apps.titulatec.services.scope_service._program_ids_for_user")
@patch("itcj2.apps.titulatec.services.scope_service._user_perms")
def test_set_de_program_position(mock_perms, mock_pids):
    mock_perms.return_value = {"titulatec.officers.api.manage"}  # sin read.all
    mock_pids.return_value = {3, 7}
    assert officer_programs(MagicMock(), 1) == {3, 7}


@patch("itcj2.apps.titulatec.services.scope_service._program_ids_for_user")
@patch("itcj2.apps.titulatec.services.scope_service._user_perms")
def test_vacio_sin_asignacion(mock_perms, mock_pids):
    mock_perms.return_value = set()
    mock_pids.return_value = set()
    assert officer_programs(MagicMock(), 1) == set()


@patch("itcj2.apps.titulatec.services.scope_service._user_perms")
def test_officer_sin_carreras_ve_set_vacio(mock_perms):
    from unittest.mock import patch as _p
    mock_perms.return_value = set()
    with _p("itcj2.apps.titulatec.services.scope_service._program_ids_for_user", return_value=set()):
        result = officer_programs(MagicMock(), 1)
        assert result == set()
