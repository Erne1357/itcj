"""Bitácora de TitulaTec, Task 8: grupo CLI auditado, `audit-purge` y Celery.

Todo corre dentro de la transacción del test (`patched_session_local`): las
filas de bitácora son inmutables, así que nada de esto puede commitear de
verdad en la base de dev. La compuerta de la purga (`SET LOCAL`) muere con el
rollback del test.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog
from itcj2.apps.titulatec.services.audit_context import current_audit_context
from itcj2.cli import titulatec as cli


def _grupo():
    """Un grupo de juguete con la MISMA clase de grupo que `titulatec_cli`."""
    grp = click.group("t", cls=cli._AuditedGroup)(lambda: None)

    @grp.command("tt-ok-cmd")
    @click.option("--nip", default="1234")
    @click.option("--n", type=int, default=3)
    def _ok(nip, n):
        click.echo("hecho")

    @grp.command("tt-boom-cmd")
    def _boom():
        raise RuntimeError("fallo a propósito")

    @grp.command("tt-abort-cmd")
    def _abort():
        raise click.ClickException("no se pudo")

    @grp.command("sii-ping")
    def _ping():
        click.echo("pong")

    return grp


def _filas(db, comando: str):
    return [r for r in db.query(TitulatecAuditLog)
            .filter(TitulatecAuditLog.source == "action",
                    TitulatecAuditLog.action == "system.cli_command")
            .order_by(TitulatecAuditLog.id).all()
            if (r.payload or {}).get("command") == comando]


# --- grupo auditado ---------------------------------------------------------

def test_titulatec_cli_es_un_grupo_auditado():
    assert isinstance(cli.titulatec_cli, cli._AuditedGroup)
    assert cli.titulatec_cli.get_command(None, "audit-purge") is not None
    assert isinstance(cli.titulatec_cli.get_command(None, "init-bitacora"), cli._AuditedCommand)


def test_comando_ok_deja_una_fila_con_params_enmascarados(patched_session_local):
    res = CliRunner().invoke(_grupo(), ["tt-ok-cmd", "--nip", "9999", "--n", "7"])
    assert res.exit_code == 0, res.output

    filas = _filas(patched_session_local, "tt-ok-cmd")
    assert len(filas) == 1
    fila = filas[0]
    assert fila.actor_kind == "cli"
    assert fila.module == "system"
    assert fila.actor_label.startswith("cli: tt-ok-cmd (")
    p = fila.payload
    assert p["status"] == "ok"
    assert p["duration_ms"] >= 0
    assert p["params"]["nip"] == "***"
    assert p["params"]["n"] == 7
    assert "9999" not in json.dumps(fila.payload)


def test_comando_que_truena_deja_fila_error_y_relanza(patched_session_local):
    res = CliRunner().invoke(_grupo(), ["tt-boom-cmd"])
    assert res.exit_code != 0
    assert isinstance(res.exception, RuntimeError)

    fila, = _filas(patched_session_local, "tt-boom-cmd")
    assert fila.payload["status"] == "error"
    assert "RuntimeError" in fila.payload["error"]


def test_click_exception_deja_fila_error_y_sale_distinto_de_cero(patched_session_local):
    res = CliRunner().invoke(_grupo(), ["tt-abort-cmd"])
    assert res.exit_code != 0

    fila, = _filas(patched_session_local, "tt-abort-cmd")
    assert fila.payload["status"] == "error"


def test_comando_excluido_no_registra(patched_session_local):
    res = CliRunner().invoke(_grupo(), ["sii-ping"])
    assert res.exit_code == 0
    assert _filas(patched_session_local, "sii-ping") == []


def test_help_no_registra(patched_session_local):
    res = CliRunner().invoke(_grupo(), ["tt-ok-cmd", "--help"])
    assert res.exit_code == 0
    assert _filas(patched_session_local, "tt-ok-cmd") == []


def test_invocar_el_comando_suelto_no_deja_fila(patched_session_local):
    """Los tests que llaman `cli.init_bitacora_command` directo no ensucian la base."""
    antes = patched_session_local.query(TitulatecAuditLog).filter_by(
        action="system.cli_command").count()
    with patch.object(cli, "_run_sql_files"), \
            patch.object(cli, "_verify_bitacora", return_value=[]):
        res = CliRunner().invoke(cli.init_bitacora_command, [])
    assert res.exit_code == 0, res.output
    despues = patched_session_local.query(TitulatecAuditLog).filter_by(
        action="system.cli_command").count()
    assert despues == antes


def test_el_contexto_cli_vive_dentro_del_comando_y_se_restaura(patched_session_local):
    vistos = []
    grp = click.group("t", cls=cli._AuditedGroup)(lambda: None)

    @grp.command("tt-ctx-cmd")
    def _ctx():
        vistos.append(current_audit_context())

    res = CliRunner().invoke(grp, ["tt-ctx-cmd"])
    assert res.exit_code == 0
    assert vistos[0].actor_kind == "cli"
    assert current_audit_context().actor_kind != "cli"


# --- audit-purge ------------------------------------------------------------

_VIEJO = datetime(1999, 6, 1, 12, 0, 0)
_CORTE = "2000-01-01"


def _siembra(db, n=3, cuando=_VIEJO):
    marca = uuid.uuid4().hex[:8]
    for i in range(n):
        db.add(TitulatecAuditLog(
            source="action", action="system.cli_command", module="system",
            actor_kind="system", occurred_at=cuando + timedelta(minutes=i),
            payload={"command": f"semilla-{marca}", "i": i}))
    db.flush()
    return marca


def _viejas(db) -> int:
    return db.query(TitulatecAuditLog).filter(
        TitulatecAuditLog.occurred_at < datetime(2000, 1, 1)).count()


def test_purga_rechaza_un_corte_reciente(patched_session_local):
    hoy = datetime.now().strftime("%Y-%m-%d")
    res = CliRunner().invoke(cli.titulatec_cli, ["audit-purge", "--before", hoy, "--yes"])
    assert res.exit_code != 0
    assert "--force" in res.output


def test_purga_dry_run_no_borra(patched_session_local):
    db = patched_session_local
    _siembra(db, 3)
    antes = _viejas(db)

    res = CliRunner().invoke(cli.titulatec_cli, ["audit-purge", "--before", _CORTE, "--dry-run"])

    assert res.exit_code == 0, res.output
    assert "[DRY-RUN]" in res.output
    assert _viejas(db) == antes
    assert db.query(TitulatecAuditLog).filter_by(action="system.audit_purged").count() == 0


def test_purga_sin_confirmar_no_borra(patched_session_local):
    db = patched_session_local
    _siembra(db, 2)
    antes = _viejas(db)

    res = CliRunner().invoke(cli.titulatec_cli, ["audit-purge", "--before", _CORTE], input="n\n")

    assert res.exit_code != 0
    assert _viejas(db) == antes


def test_purga_borra_archiva_y_deja_system_audit_purged(patched_session_local, tmp_path):
    db = patched_session_local
    marca = _siembra(db, 3)
    total = _viejas(db)
    archivo = tmp_path / "purga.jsonl"

    res = CliRunner().invoke(cli.titulatec_cli, [
        "audit-purge", "--before", _CORTE, "--archive", str(archivo), "--yes"])

    assert res.exit_code == 0, res.output
    assert _viejas(db) == 0

    # el archivo trae EXACTAMENTE lo borrado, una fila por línea
    lineas = [json.loads(x) for x in archivo.read_text(encoding="utf-8").splitlines()]
    assert len(lineas) == total
    propias = [x for x in lineas if (x["payload"] or {}).get("command") == f"semilla-{marca}"]
    assert len(propias) == 3
    assert propias[0]["occurred_at"].startswith("1999-06-01")

    fila = db.query(TitulatecAuditLog).filter_by(action="system.audit_purged").one()
    assert fila.module == "system"
    assert fila.payload["deleted"] == total
    assert fila.payload["before"] == _CORTE
    assert fila.payload["archive"] == str(archivo.resolve())


def test_purga_sin_filas_no_hace_nada(patched_session_local):
    db = patched_session_local
    res = CliRunner().invoke(cli.titulatec_cli, ["audit-purge", "--before", "1980-01-01", "--yes"])
    assert res.exit_code == 0, res.output
    assert "Nada que purgar" in res.output
    assert db.query(TitulatecAuditLog).filter_by(action="system.audit_purged").count() == 0


def test_el_trigger_sigue_rechazando_el_delete_sin_la_compuerta(db_session):
    """Sanidad: sin `SET LOCAL` el DELETE no pasa (la purga es la ÚNICA vía)."""
    from sqlalchemy.exc import DBAPIError

    _siembra(db_session, 1)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.query(TitulatecAuditLog).filter(
                TitulatecAuditLog.occurred_at < datetime(2000, 1, 1)).delete(
                synchronize_session=False)


# --- Celery -----------------------------------------------------------------

def test_tareas_corren_con_contexto_celery(patched_session_local):
    import itcj2.tasks.titulatec_tasks as tasks
    from itcj2.apps.titulatec.services.eligibility_service import EligibilityService
    from itcj2.apps.titulatec.services.mail_dispatch import MailDispatcher
    from itcj2.apps.titulatec.services.mail_reminders import MailReminders

    vistos: dict[str, object] = {}

    def espia(nombre, valor):
        def _f(*a, **k):
            vistos[nombre] = current_audit_context()
            return valor
        return _f

    with patch.object(MailDispatcher, "run", side_effect=espia("dispatch", {"disabled": True})), \
            patch.object(MailReminders, "run", side_effect=espia("reminders", {"appt": 0})), \
            patch.object(EligibilityService, "sweep", side_effect=espia("sweep", {"checked": 0})), \
            patch.object(EligibilityService, "check", side_effect=espia("check", None)):
        tasks.email_dispatch.run()
        tasks.email_reminders.run()
        tasks.sii_sweep.run()
        tasks.sii_check_request.run(req_id=1)

    esperado = {
        "dispatch": "titulatec.email_dispatch",
        "reminders": "titulatec.email_reminders",
        "sweep": "titulatec.sii_sweep",
        "check": "titulatec.sii_check_request",
    }
    for clave, etiqueta in esperado.items():
        ctx = vistos[clave]
        assert ctx.actor_kind == "celery", clave
        assert ctx.actor_label == etiqueta, clave
    assert current_audit_context().actor_kind != "celery"


# --- ronda de arreglos: archivo, dry-run, cuadre, --force --------------------

def test_purga_no_pisa_un_archivo_existente(patched_session_local, tmp_path):
    db = patched_session_local
    _siembra(db, 2)
    antes = _viejas(db)
    archivo = tmp_path / "ya.jsonl"
    archivo.write_text("copia anterior\n", encoding="utf-8")

    res = CliRunner().invoke(cli.titulatec_cli, [
        "audit-purge", "--before", _CORTE, "--archive", str(archivo), "--yes"])

    assert res.exit_code != 0
    assert "ya existe" in res.output
    assert archivo.read_text(encoding="utf-8") == "copia anterior\n"
    assert _viejas(db) == antes


def test_dry_run_no_exige_force_con_corte_reciente(patched_session_local):
    hoy = datetime.now().strftime("%Y-%m-%d")
    res = CliRunner().invoke(cli.titulatec_cli, ["audit-purge", "--before", hoy, "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "[DRY-RUN]" in res.output


def test_purga_verifica_que_el_archivo_cuadre_con_lo_borrado(
        patched_session_local, tmp_path, monkeypatch):
    db = patched_session_local
    _siembra(db, 3)
    archivo = tmp_path / "descuadre.jsonl"
    real = cli._write_audit_archive
    monkeypatch.setattr(cli, "_write_audit_archive",
                        lambda *a, **k: real(*a, **k) - 1)

    res = CliRunner().invoke(cli.titulatec_cli, [
        "audit-purge", "--before", _CORTE, "--archive", str(archivo), "--yes"])

    assert res.exit_code != 0
    assert "se revierte todo" in res.output
    assert not archivo.exists()
    assert db.query(TitulatecAuditLog).filter_by(action="system.audit_purged").count() == 0


def test_purga_feliz_cuenta_igual_archivo_y_borrado(patched_session_local, tmp_path):
    db = patched_session_local
    _siembra(db, 2)
    total = _viejas(db)
    archivo = tmp_path / "ok.jsonl"
    res = CliRunner().invoke(cli.titulatec_cli, [
        "audit-purge", "--before", _CORTE, "--archive", str(archivo), "--yes"])
    assert res.exit_code == 0, res.output
    assert len(archivo.read_text(encoding="utf-8").splitlines()) == total
    fila = db.query(TitulatecAuditLog).filter_by(action="system.audit_purged").one()
    assert fila.payload["deleted"] == total


def test_force_permite_purgar_con_corte_viejo_y_con_corte_reciente(patched_session_local):
    db = patched_session_local
    _siembra(db, 2)
    res = CliRunner().invoke(cli.titulatec_cli,
                             ["audit-purge", "--before", _CORTE, "--yes", "--force"])
    assert res.exit_code == 0, res.output
    assert _viejas(db) == 0

    # corte reciente + --force: pasa la guarda y borra lo anterior a hoy
    _siembra(db, 1)
    hoy = datetime.now().strftime("%Y-%m-%d")
    res = CliRunner().invoke(cli.titulatec_cli,
                             ["audit-purge", "--before", hoy, "--yes", "--force"])
    assert res.exit_code == 0, res.output
    assert "OK:" in res.output or "Nada que purgar" in res.output
    assert _viejas(db) == 0
