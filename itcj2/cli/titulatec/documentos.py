"""Delta 2026-10-15: reemplazo de documentos en cotejo.

`init-reemplazo-docs` corre SOLO `reemplazo_2026_10/27_insert_doc_replacement_perm.sql`.
Vive en su propio módulo porque `deltas.py` ya roza el tope de 800 líneas.
"""
import click

from itcj2.cli.titulatec._common import (
    DML_TITULATEC,
    _abortar_con,
    titulatec_cli,
)

# El 27 inserta `titulatec.document.api.request_replacement` y lo concede EXPLICITO
# a `titulatec_school_services_head` Y a `admin`. En produccion el 15 NUNCA se
# re-corre (reparte todo titulatec a `admin`), asi que este comando corre SOLO el 27.
# Invalida el cache de authz SOLO de titulatec (nunca `invalidate_all`).
_DML_REEMPLAZO_2026_10_DIR = "reemplazo_2026_10"
_DML_REEMPLAZO_2026_10_FILES = ["27_insert_doc_replacement_perm.sql"]
_REPLACEMENT_PERM = "titulatec.document.api.request_replacement"
_REPLACEMENT_ROLES = ("titulatec_school_services_head", "admin")


def _verify_reemplazo_docs() -> list[str]:
    """Comprueba que el 27 ATERRIZO: el permiso existe y lo tienen la jefa de SE
    y `admin`. Devuelve problemas (contrato de `_verify_reportes`). Sesion
    propia, solo lectura."""
    from sqlalchemy import text

    from itcj2.database import SessionLocal

    problemas: list[str] = []
    db = SessionLocal()
    try:
        existe = db.execute(
            text("SELECT 1 FROM core_permissions p JOIN core_apps a ON a.id = p.app_id "
                 "WHERE a.key = 'titulatec' AND p.code = :code"),
            {"code": _REPLACEMENT_PERM},
        ).first()
        if existe is None:
            return [f"permiso ausente: {_REPLACEMENT_PERM}"]
        for rol in _REPLACEMENT_ROLES:
            concedido = db.execute(
                text("SELECT 1 FROM core_role_permissions rp "
                     "JOIN core_roles r ON r.id = rp.role_id "
                     "JOIN core_permissions p ON p.id = rp.perm_id "
                     "JOIN core_apps a ON a.id = p.app_id "
                     "WHERE a.key = 'titulatec' AND r.name = :rol AND p.code = :code"),
                {"rol": rol, "code": _REPLACEMENT_PERM},
            ).first()
            if concedido is None:
                problemas.append(f"el rol {rol} no tiene {_REPLACEMENT_PERM}")
    finally:
        db.close()
    return problemas


@titulatec_cli.command("init-reemplazo-docs")
@click.option("--dry-run", is_flag=True,
              help="Comprueba los archivos en disco y los lista, sin escribir nada.")
def init_reemplazo_docs_command(dry_run):
    """Da de alta el permiso de pedir reemplazo de documentos en cotejo.

    Corre `reemplazo_2026_10/27_insert_doc_replacement_perm.sql` (inserta
    `titulatec.document.api.request_replacement` y lo concede a
    `titulatec_school_services_head` y a `admin`). Corre SOLO ese archivo: NO
    re-ejecuta el 15 ni el resto de `SEED_FILES`. Idempotente (ON CONFLICT).
    Invalida el cache de authz solo de titulatec y VERIFICA con
    `_verify_reemplazo_docs()`; aborta si algo no aterrizo. `--dry-run`:
    comprueba que los archivos existen y los lista, sin escribir.
    """
    archivos = [f"{_DML_REEMPLAZO_2026_10_DIR}/{n}" for n in _DML_REEMPLAZO_2026_10_FILES]
    faltan = [n for n in archivos if not (DML_TITULATEC / n).exists()]

    if dry_run:
        if faltan:
            click.echo(click.style(f"ERROR: faltan archivos en disco: {faltan}", fg="red"))
        else:
            click.echo("Archivos en disco: OK. Se ejecutarian:")
            for nombre in archivos:
                click.echo(f"  {nombre}")
        click.echo("Dry-run: no se ejecuto nada.")
        if faltan:
            raise click.Abort()
        return

    if faltan:
        _abortar_con([f"faltan archivos en disco: {faltan} "
                      "(database/ esta gitignored: subelos al host)"])

    from itcj2.cli.core import execute_sql_file

    for nombre in archivos:
        click.echo(f"   Ejecutando: {nombre}")
        execute_sql_file(str(DML_TITULATEC / nombre), invalidate_authz=False)
        click.echo(f"   Completado: {nombre}")

    # Tras el commit y ANTES de verificar; best-effort (Redis caido = TTL de 5 min).
    from itcj2.core.services.authz_cache import invalidate_app
    invalidate_app("titulatec")
    click.echo("Cache de authz de titulatec invalidado (solo esta app).")

    problemas = _verify_reemplazo_docs()
    if problemas:
        _abortar_con(problemas)

    click.echo(click.style(
        f"OK: {_REPLACEMENT_PERM} existe y lo tienen {' y '.join(_REPLACEMENT_ROLES)}.",
        fg="green"))
