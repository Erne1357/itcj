"""Bitácora de auditoría de TitulaTec: audit-purge y audit-backfill-solicitudes."""
import os
from pathlib import Path

import click

from itcj2.cli.titulatec._common import logger, titulatec_cli

# --- Purga de la bitácora (spec 2026-10-07 §6, D4) ---------------------------

# Menos que esto exige --force: la bitácora existe para poder mirar atrás.
_AUDIT_PURGE_MIN_DAYS = 365
_AUDIT_PURGE_BATCH = 1000


def _audit_row_to_dict(row) -> dict:
    """Una fila de la bitácora como dict JSON-seguro (para el archivo JSONL)."""
    from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog

    out = {}
    for col in TitulatecAuditLog.__table__.columns:
        value = getattr(row, col.name)
        out[col.name] = value.isoformat() if hasattr(value, "isoformat") else value
    return out


def _write_audit_archive(db, pred, archive: Path) -> int:
    """Escribe el JSONL de lo que va a borrarse y devuelve cuántas filas puso.

    Modo "x": si el archivo ya existe NO se pisa (sería destruir la única copia
    de una purga anterior)."""
    import json

    from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog as model

    archive.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    try:
        fh = archive.open("x", encoding="utf-8", newline="\n")
    except FileExistsError:
        raise click.ClickException(
            f"El archivo {archive} ya existe; elige otra ruta (no se sobrescribe).")
    with fh:
        q = db.query(model).filter(pred).order_by(model.id).yield_per(_AUDIT_PURGE_BATCH)
        for row in q:
            fh.write(json.dumps(_audit_row_to_dict(row), ensure_ascii=False,
                                default=str) + "\n")
            n += 1
        fh.flush()
        os.fsync(fh.fileno())
    db.expire_all()
    return n


def _do_audit_purge(db, cutoff, archive: Path | None, dry_run: bool) -> dict:
    """Lógica pura de `audit-purge` (testeable sin Click).

    Una sola transacción: `SET LOCAL titulatec.audit_purge = 'on'` (la única vía
    que el trigger de PostgreSQL deja pasar), archivo JSONL con lo que se va a
    borrar, `DELETE` y la fila `system.audit_purged`. Commitea quien llama.
    """
    import json

    from sqlalchemy import text

    from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog
    from itcj2.apps.titulatec.services.audit_service import AuditService

    model = TitulatecAuditLog
    pred = model.occurred_at < cutoff
    total = db.query(model).filter(pred).count()
    result = {"count": total, "deleted": 0, "archive": None}
    if dry_run or total == 0:
        return result

    # Misma transacción que el DELETE; muere con el commit o el rollback.
    db.execute(text("SET LOCAL titulatec.audit_purge = 'on'"))

    archived = None
    if archive is not None:
        archive = Path(archive).resolve()
        archived = _write_audit_archive(db, pred, archive)
        result["archive"] = str(archive)

    deleted = db.query(model).filter(pred).delete(synchronize_session=False)
    result["deleted"] = deleted
    if archived is not None and archived != deleted:
        # El archivo es la única copia de lo borrado: si no cuadra, nada se borra.
        archive.unlink(missing_ok=True)
        raise click.ClickException(
            f"El archivo tiene {archived} filas y el DELETE tocó {deleted}; "
            "se revierte todo, no se borró nada.")
    AuditService.record(
        db, "system.audit_purged", entity_type="audit_log",
        payload={"deleted": deleted, "before": cutoff.date().isoformat(),
                 "archive": result["archive"]},
    )
    return result


@titulatec_cli.command("audit-purge")
@click.option("--before", "before", required=True,
              type=click.DateTime(formats=["%Y-%m-%d"]),
              help="Borra las filas anteriores a esta fecha (AAAA-MM-DD, 00:00).")
@click.option("--archive", "archive", default=None,
              type=click.Path(dir_okay=False, path_type=Path),
              help="Archivo JSONL donde guardar lo borrado ANTES de borrarlo.")
@click.option("--dry-run", is_flag=True, help="Solo cuenta; no escribe ni borra nada.")
@click.option("--yes", "-y", "yes", is_flag=True, help="No pide confirmación.")
@click.option("--force", is_flag=True,
              help=f"Permite cortes de menos de {_AUDIT_PURGE_MIN_DAYS} días.")
def audit_purge_command(before, archive, dry_run, yes, force):
    """Purga la bitácora de TitulaTec (ÚNICA vía para borrar filas).

    La tabla es inmutable por trigger; este comando abre la compuerta
    (`SET LOCAL titulatec.audit_purge = 'on'`) solo dentro de su transacción.
    Deja una fila `system.audit_purged` con el conteo, el corte y el archivo.
    """
    from itcj2.core.utils.timezone import db_now
    from itcj2.database import SessionLocal

    dias = (db_now() - before).days
    if dias < _AUDIT_PURGE_MIN_DAYS and not force and not dry_run:
        raise click.ClickException(
            f"El corte {before:%Y-%m-%d} es de hace {dias} días (< "
            f"{_AUDIT_PURGE_MIN_DAYS}). Usa --force si de verdad quieres purgar tan reciente.")

    if archive is not None and Path(archive).exists():
        raise click.ClickException(
            f"El archivo {archive} ya existe; elige otra ruta (no se sobrescribe).")

    db = SessionLocal()
    try:
        previo = _do_audit_purge(db, before, archive, dry_run=True)
        if dry_run:
            click.echo(f"[DRY-RUN] Se purgarían {previo['count']} filas anteriores a "
                       f"{before:%Y-%m-%d}.")
            return
        if previo["count"] == 0:
            click.echo(f"Nada que purgar antes de {before:%Y-%m-%d}.")
            return
        if archive is None:
            click.echo(click.style(
                "AVISO: sin --archive las filas se pierden para siempre.", fg="yellow"))
        if not yes and not click.confirm(
                f"¿Borrar {previo['count']} filas de la bitácora anteriores a "
                f"{before:%Y-%m-%d}? No se puede deshacer", default=False):
            raise click.Abort()

        res = _do_audit_purge(db, before, archive, dry_run=False)
        db.commit()
        logger.warning("bitácora purgada: %s filas anteriores a %s (archivo=%s)",
                       res["deleted"], before.date(), res["archive"])
        click.echo(click.style(
            f"OK: {res['deleted']} filas purgadas"
            + (f"; archivo: {res['archive']}" if res["archive"] else ""), fg="green"))
    except click.Abort:
        raise  # confirmación negada: todavía no se escribió nada
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Recuperación de decisiones de solicitudes previas a la bitácora (2026-10-08).
# Lógica en `AuditBackfillService.enrollment_decisions`; aquí solo el comando.
# ---------------------------------------------------------------------------
@titulatec_cli.command("audit-backfill-solicitudes")
@click.option("--dry-run", is_flag=True, help="Solo cuenta; no escribe nada.")
def audit_backfill_solicitudes_command(dry_run):
    """Recupera en la bitácora las decisiones de solicitudes anteriores a ella.

    Lee `reviewed_*`, `returned_*` y `reopened_*` de las solicitudes de
    inscripción y escribe una fila por decisión (`enrollment.approved`,
    `enrollment.rejected`, `access.returned`, `enrollment.reopened`) con la
    fecha ORIGINAL y `payload.backfilled = true`, solo las ANTERIORES al corte
    (la primera fila en vivo de la bitácora). Idempotente: no repite lo que una
    corrida previa ya recuperó. Correr primero con `--dry-run`. La bitácora es
    inmutable: lo escrito no se puede deshacer salvo con `audit-purge`.
    """
    from itcj2.apps.titulatec.services.audit_backfill_service import AuditBackfillService
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        corte = AuditBackfillService.cutoff(db)
        conteo = AuditBackfillService.enrollment_decisions(db, dry_run=dry_run)
        total = sum(n for a, n in conteo.items() if a != "skipped_no_date")
        click.echo(f"Corte (inicio de la bitácora en vivo): {corte:%Y-%m-%d %H:%M:%S}; "
                   "solo se recuperan decisiones anteriores.")
        prefijo = "[DRY-RUN] Se recuperarían" if dry_run else "Recuperadas"
        for accion, n in conteo.items():
            click.echo(f"  {accion}: {n}")
        if dry_run:  # el servicio no escribe en dry-run: nada que revertir
            click.echo(f"{prefijo} {total} filas. No se escribió nada.")
            return
        db.commit()
        logger.warning("bitácora: %s decisiones de solicitudes recuperadas: %s", total, conteo)
        click.echo(click.style(f"OK: {prefijo.lower()} {total} filas.", fg="green"))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
