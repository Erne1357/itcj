"""Comando `titulatec init-bitacora` (2026-10-07): permiso de la bitácora.

`titulatec.audit.page.list` (solo `admin`): el 25 inserta el permiso y el 15
(concesión dinámica a `admin`) lo reparte. Aquí se fija el contrato del
comando y su lugar en `SEED_FILES` (25 antes de 15, el 15 siempre al final).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from tests.fastapi.titulatec.test_permissions_contract import requires_dml

PERM = "titulatec.audit.page.list"
ARCHIVO = "audit_2026_10/25_insert_audit_perm.sql"
DML = Path(__file__).resolve().parents[3] / "database" / "DML" / "titulatec"


def test_seed_files_tiene_el_25_antes_del_15_y_el_15_al_final():
    from itcj2.cli.titulatec import SEED_FILES

    assert ARCHIVO in SEED_FILES
    assert SEED_FILES.index(ARCHIVO) < SEED_FILES.index("15_grant_admin_all_perms.sql")
    assert SEED_FILES[-1] == "15_grant_admin_all_perms.sql"


def test_el_comando_corre_el_25_y_luego_el_15_y_verifica():
    from itcj2.cli import titulatec as cli

    with patch.object(cli, "_run_sql_files") as correr, \
            patch.object(cli, "_verify_bitacora", return_value=[]) as verificar:
        res = CliRunner().invoke(cli.init_bitacora_command, [])

    assert res.exit_code == 0, res.output
    correr.assert_called_once_with([ARCHIVO, "15_grant_admin_all_perms.sql"])
    verificar.assert_called_once_with()


def test_el_comando_aborta_si_no_aterrizo():
    from itcj2.cli import titulatec as cli

    with patch.object(cli, "_run_sql_files"), \
            patch.object(cli, "_verify_bitacora",
                         return_value=["el rol admin no tiene " + PERM]):
        res = CliRunner().invoke(cli.init_bitacora_command, [])

    assert res.exit_code != 0


@requires_dml
def test_dry_run_no_ejecuta_nada():
    from itcj2.cli import titulatec as cli

    with patch.object(cli, "_run_sql_files") as correr:
        res = CliRunner().invoke(cli.init_bitacora_command, ["--dry-run"])

    assert res.exit_code == 0, res.output
    correr.assert_not_called()


@requires_dml
def test_el_sql_es_idempotente_y_no_concede_a_roles():
    sql = (DML / ARCHIVO).read_text(encoding="utf-8")
    assert PERM in sql
    assert "ON CONFLICT (app_id, code) DO NOTHING" in sql
    assert "core_role_permissions" not in sql.replace("--", "\n--").split("DO $$", 1)[1]


def test_verify_lee_la_base(patched_session_local, make_role):
    """Con el permiso en un rol `admin` de prueba, nada que reportar; sin la
    concesion o sin el permiso, lo dice."""
    from itcj2.cli.titulatec import _verify_bitacora
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role import Role
    from itcj2.core.models.role_permission import RolePermission

    make_role("admin", (PERM,))
    assert _verify_bitacora() == []

    db = patched_session_local
    rol = db.query(Role).filter_by(name="admin").one()
    perm = db.query(Permission).filter_by(code=PERM).one()
    db.query(RolePermission).filter_by(role_id=rol.id, perm_id=perm.id).delete()
    db.flush()
    assert _verify_bitacora() == [f"el rol admin no tiene {PERM}"]

    db.query(RolePermission).filter_by(perm_id=perm.id).delete()
    db.query(Permission).filter_by(id=perm.id).delete()
    db.flush()
    assert _verify_bitacora() == [f"permiso ausente: {PERM}"]
