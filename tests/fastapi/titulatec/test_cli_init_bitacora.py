"""Comando `titulatec init-bitacora` (2026-10-07): permiso de la bitácora.

`titulatec.audit.page.list` (solo `admin`): el 25 inserta el permiso Y lo
concede EXPLÍCITO al rol `admin` (revisión final I3). En producción el
`15_grant_admin_all_perms.sql` NUNCA se re-corre —concede TODO titulatec a
`admin`, y por el puesto D2 eso llega a la jefatura de Centro de Cómputo—, así
que el comando corre SOLO el 25, igual que `init-outbox-admin` corre solo el 24.
El 25 sigue en `SEED_FILES` antes del 15 para las instalaciones desde cero.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from tests.fastapi.titulatec.test_permissions_contract import requires_dml

PERM = "titulatec.audit.page.list"
ARCHIVO = "audit_2026_10/25_insert_audit_perm.sql"
QUINCE = "15_grant_admin_all_perms.sql"
DML = Path(__file__).resolve().parents[3] / "database" / "DML" / "titulatec"


def test_seed_files_tiene_el_25_antes_del_15_y_el_15_al_final():
    from itcj2.cli.titulatec import SEED_FILES

    assert ARCHIVO in SEED_FILES
    assert SEED_FILES.index(ARCHIVO) < SEED_FILES.index(QUINCE)
    assert SEED_FILES[-1] == QUINCE


def test_el_comando_corre_solo_el_25_y_verifica():
    from itcj2.cli import titulatec as cli

    with patch.object(cli, "_run_sql_files") as correr, \
            patch.object(cli, "_verify_bitacora", return_value=[]) as verificar:
        res = CliRunner().invoke(cli.init_bitacora_command, [])

    assert res.exit_code == 0, res.output
    correr.assert_called_once_with([ARCHIVO])
    verificar.assert_called_once_with()


def test_el_comando_aborta_si_no_aterrizo():
    from itcj2.cli import titulatec as cli

    with patch.object(cli, "_run_sql_files"), \
            patch.object(cli, "_verify_bitacora",
                         return_value=["el rol admin no tiene " + PERM]):
        res = CliRunner().invoke(cli.init_bitacora_command, [])

    assert res.exit_code != 0


@requires_dml
def test_dry_run_no_ejecuta_nada_y_no_lista_el_15():
    from itcj2.cli import titulatec as cli

    with patch.object(cli, "_run_sql_files") as correr:
        res = CliRunner().invoke(cli.init_bitacora_command, ["--dry-run"])

    assert res.exit_code == 0, res.output
    correr.assert_not_called()
    assert ARCHIVO in res.output
    assert QUINCE not in res.output


@requires_dml
def test_el_sql_es_idempotente_y_concede_solo_a_admin():
    sql = (DML / ARCHIVO).read_text(encoding="utf-8")
    cuerpo = sql.split("DO $$", 1)[1]
    assert PERM in cuerpo
    assert "ON CONFLICT (app_id, code) DO NOTHING" in cuerpo
    # Concesión explícita, idempotente y SOLO al rol `admin` (mismo bloque que el 24).
    assert "INSERT INTO core_role_permissions (role_id, perm_id)" in cuerpo
    assert "WHERE r.name = 'admin'" in cuerpo
    assert "ON CONFLICT DO NOTHING" in cuerpo
    assert "core_user_app_roles" not in cuerpo  # no toca a ningún usuario


@requires_dml
def test_el_25_concede_el_permiso_a_admin_dentro_de_la_transaccion(
        db_session, patched_session_local, titulatec_app, make_role):
    """Se corre el SQL real del 25 dentro de la transacción del test (se
    revierte): sin el 15, el rol `admin` termina con el permiso."""
    from itcj2.cli.titulatec import _verify_bitacora
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role import Role
    from itcj2.core.models.role_permission import RolePermission

    make_role("admin", ())
    rol = db_session.query(Role).filter_by(name="admin").one()
    perm = db_session.query(Permission).filter_by(app_id=titulatec_app.id, code=PERM).first()
    if perm is not None:  # dev ya lo tiene: se le quita al rol para ver que el 25 lo da
        db_session.query(RolePermission).filter_by(
            role_id=rol.id, perm_id=perm.id).delete()
        db_session.flush()
        assert _verify_bitacora() == [f"el rol admin no tiene {PERM}"]

    db_session.connection().exec_driver_sql((DML / ARCHIVO).read_text(encoding="utf-8"))
    assert _verify_bitacora() == []

    # Idempotente: una segunda corrida no truena ni duplica.
    db_session.connection().exec_driver_sql((DML / ARCHIVO).read_text(encoding="utf-8"))
    perm = db_session.query(Permission).filter_by(app_id=titulatec_app.id, code=PERM).one()
    assert db_session.query(RolePermission).filter_by(
        role_id=rol.id, perm_id=perm.id).count() == 1


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
