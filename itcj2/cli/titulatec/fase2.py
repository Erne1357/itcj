"""Comando `init-titulatec-fase-2`: UNICO camino de despliegue del DML de la
«fase 2 del desarrollo» de TitulaTec (fases 3-8).

Cada spec nuevo agrega su archivo a `_DML_FASE_2_FILES` (y sus grants a
`_FASE_2_EXPECTED`); el comando los corre todos, en orden, y verifica.
"""
import click

from itcj2.cli.titulatec._common import DML_TITULATEC, _abortar_con, titulatec_cli

_DML_FASE_2_DIR = "fase_2"
# Debe listar TODOS los .sql de `database/DML/titulatec/fase_2/`.
_DML_FASE_2_FILES = ["01_titulacion_formato_b.sql"]

# rol -> permisos que DEBEN tener tras correr el comando.
_FASE_2_EXPECTED: dict[str, set[str]] = {
    "titulatec_titulacion": {
        "titulatec.titulacion.page.list",
        "titulatec.format_b.api.read.all",
        "titulatec.format_b.api.correct_registry",
    },
    "titulatec_titulaciones": {
        "titulatec.titulacion.page.list",
        "titulatec.format_b.api.correct_registry",
    },
    "admin": {
        "titulatec.titulacion.page.list",
        "titulatec.format_b.api.correct_registry",
    },
}


def _verify_fase_2() -> list[str]:
    """Comprueba que cada rol tenga sus grants de fase 2. Devuelve problemas
    (lista vacia = todo bien). Sesion propia, solo lectura."""
    from sqlalchemy import text

    from itcj2.database import SessionLocal

    problemas: list[str] = []
    db = SessionLocal()
    try:
        for rol, codigos in _FASE_2_EXPECTED.items():
            for codigo in sorted(codigos):
                concedido = db.execute(
                    text("SELECT 1 FROM core_role_permissions rp "
                         "JOIN core_roles r ON r.id = rp.role_id "
                         "JOIN core_permissions p ON p.id = rp.perm_id "
                         "JOIN core_apps a ON a.id = p.app_id "
                         "WHERE a.key = 'titulatec' AND r.name = :rol AND p.code = :code"),
                    {"rol": rol, "code": codigo},
                ).first()
                if concedido is None:
                    problemas.append(f"el rol {rol} no tiene {codigo}")
    finally:
        db.close()
    return problemas


@titulatec_cli.command("init-titulatec-fase-2")
@click.option("--dry-run", is_flag=True,
              help="Comprueba los archivos en disco y los lista, sin escribir nada.")
def init_titulatec_fase_2_command(dry_run):
    """Carga el DML de la fase 2 del desarrollo (fases 3-8) y lo verifica.

    Corre SOLO `database/DML/titulatec/fase_2/*.sql` (en el orden de
    `_DML_FASE_2_FILES`): NO re-ejecuta el 15 ni el resto de `SEED_FILES`.
    Idempotente (ON CONFLICT). Invalida el cache de authz solo de titulatec y
    VERIFICA con `_verify_fase_2()`; aborta si algo no aterrizo.

    IMPORTANTE: tras cualquier `init-titulatec` o `init-ajustes-2026-10` hay
    que volver a correr este comando (sus DELETE de convergencia quitan los
    grants de fase 2). `--dry-run`: comprueba que los archivos existen y los
    lista, sin escribir.
    """
    archivos = [f"{_DML_FASE_2_DIR}/{n}" for n in _DML_FASE_2_FILES]
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

    problemas = _verify_fase_2()
    if problemas:
        _abortar_con(problemas)

    click.echo(click.style(
        "OK: permisos de fase 2 concedidos a "
        + ", ".join(sorted(_FASE_2_EXPECTED)) + ".", fg="green"))
