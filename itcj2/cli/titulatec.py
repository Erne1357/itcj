#!/usr/bin/env python3
"""
Comandos CLI de TitulaTec para itcj2.

Comandos:
    titulatec init-titulatec              Registra la app, roles, permisos, puestos y catálogos base.
    titulatec fix-missing-credentials     Repone la credencial inicial de alumnos sin password_hash.
"""
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).parent.parent.parent
DML_TITULATEC = PROJECT_ROOT / "database" / "DML" / "titulatec"

# Orden de ejecución de los seeders. FUENTE ÚNICA: `itcj2/cli/core.py`
# (`seed-reference-data`) importa esta misma lista, para que no vuelvan a divergir
# como divergieron hasta 2026-09 (core corría 00/04/06/07, este comando 00-06;
# ninguno de los dos cargaba el set completo).
#
# Todos son idempotentes, pero OJO con el 03: además de los INSERT ... ON CONFLICT
# lleva dos DELETE que revocan `cohort.*` al rol `titulatec_titulaciones` (las
# convocatorias son de Servicios Escolares). Eso se aplica EN CADA CORRIDA: una
# concesión manual posterior de esos permisos se pierde al re-sembrar. Es la
# política declarada, no un accidente.
SEED_FILES = [
    "00_insert_app.sql",                  # Registra la app en core_apps
    "01_insert_roles.sql",                # 5 roles nuevos (alumno recicla 'student' global)
    "02_insert_permissions.sql",          # Permisos titulatec.*
    "03_insert_role_permissions.sql",     # Asignación rol→permisos (incl. 'student') + revocaciones
    "04_insert_vinculacion_positions.sql",# Puestos nuevos coord_vinculacion_* por depto
    "05_insert_position_app_roles.sql",   # Mapeo puestos→roles (escolares, titulaciones, vinculación)
    "06_seed_catalogs.sql",               # Modalidades, fases (0-8) y tipos de documento
    "07_insert_cotejo_reqs_perm.sql",     # Permiso de requisitos de cotejo (rol head)
    "08_insert_review_window_perms.sql",  # Espacios de cotejo por encargado (ventanas)
    # --- Delta 2026-09: encuesta de egresados + convocatoria abierta ---------
    # Van en subcarpeta propia para que NUNCA acaben dentro del 03 (cuyos
    # DELETE se re-aplican). El prefijo `survey_2026_09/` es parte del nombre:
    # `_run_sql_files` hace `DML_TITULATEC / filename` y `_titulatec_seed_files`
    # (cli/core.py:205) hace `f"titulatec/{name}"`; ambas rutas resuelven bien.
    "survey_2026_09/09_insert_survey_perms.sql",           # 8 permisos nuevos
    "survey_2026_09/10_insert_survey_role_permissions.sql",# grants (head + operativo en requirement.mark)
    "survey_2026_09/11_seed_survey_form.sql",              # formulario 'egresados' v1, status open
    "survey_2026_09/12_seed_cotejo_codes.sql",             # auto_source del requisito de la encuesta
]

_DML_SURVEY_2026_09_DIR = "survey_2026_09"
_DML_SURVEY_2026_09_FILES = [
    "09_insert_survey_perms.sql",
    "10_insert_survey_role_permissions.sql",
    "11_seed_survey_form.sql",
    "12_seed_cotejo_codes.sql",
]

_SURVEY_2026_09_PERMS = (
    "titulatec.survey.page.list",
    "titulatec.survey.api.read",
    "titulatec.survey.api.export",
    "titulatec.survey.api.manage",
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.requirement.mark",
)

_PERM_MARCA_REQUISITO = "titulatec.process.api.requirement.mark"


def _run_sql_files(files: list[str]) -> None:
    """Ejecuta una lista de archivos SQL (relativos a DML_TITULATEC) vía el helper de core.

    Aborta si falta un archivo. Antes hacía `continue` con un warning y luego
    imprimía "init-titulatec completado" con exit 0: una app a medio sembrar
    (sin roles ni permisos) es indistinguible de una app sembrada, y todas sus
    páginas responden 404 sin que nada lo señale.
    """
    from itcj2.cli.core import execute_sql_file

    missing = [f for f in files if not (DML_TITULATEC / f).exists()]
    if missing:
        raise click.ClickException(
            "Faltan seeders en {}: {}.\n"
            "database/ está fuera del repo (gitignored): recupéralos del respaldo "
            "o de `git show db64df9^:database/DML/titulatec/<archivo>`. "
            "Sembrar a medias deja la app en 404 permanente.".format(
                DML_TITULATEC, ", ".join(missing)
            )
        )

    for filename in files:
        file_path = DML_TITULATEC / filename
        click.echo(f"   🔄 Ejecutando: {filename}")
        execute_sql_file(str(file_path))
        click.echo(f"   ✅ Completado: {filename}")


@click.group("titulatec")
def titulatec_cli():
    """Comandos de inicialización de la app de TitulaTec."""


@titulatec_cli.command("init-titulatec")
def init_titulatec_command():
    """Inicializa la app de TitulaTec completamente.

    Ejecuta en orden los 8 seeders de database/DML/titulatec/ (ver SEED_FILES).
    Idempotentes, pero el 03 revoca `cohort.*` a `titulatec_titulaciones` en cada
    corrida (política: las convocatorias son de Servicios Escolares).

    Aborta si falta cualquier archivo: sembrar a medias deja la app en 404.

    Prerequisitos:
      - Tablas titulatec_* existen (alembic upgrade head).
      - 04 antes que 05: el mapeo puesto→rol necesita los puestos ya creados.
    """
    click.echo("🎓 Inicializando app de TitulaTec...")
    click.echo()
    try:
        _run_sql_files(SEED_FILES)
        click.echo()
        click.echo("🎉 init-titulatec completado.")
    except Exception as e:
        click.echo(f"\n💥 Error durante init-titulatec: {e}")
        raise


@titulatec_cli.command("fix-missing-credentials")
@click.option("--cohort-id", type=int, default=None,
              help="Limita el barrido a una convocatoria.")
@click.option("--dry-run", is_flag=True, help="Solo reporta a quién repararía.")
def fix_missing_credentials_command(cohort_id, dry_run):
    """Repone la credencial inicial (= número de control) a los alumnos sin contraseña.

    Remedia a los que dio de alta el importador de CSV antes de 2026-09, cuando
    creaba el `User` sin `password_hash`: `auth_service` rechaza el login con ese
    campo NULL y el reset del core está prohibido para quien tiene `control_number`
    (`core/api/users_admin.py:427`), así que no había forma de desbloquearlos.

    Idempotente: nunca sobrescribe una contraseña existente, y no crea procesos,
    folios ni notificaciones. Los alumnos quedan con `must_change_password`.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.import_service import ImportService

    with SessionLocal() as db:
        if dry_run:
            from itcj2.core.models.user import User
            from itcj2.apps.titulatec.models import TitulationProcess
            q = (db.query(User)
                 .join(TitulationProcess, TitulationProcess.student_id == User.id)
                 .filter(User.password_hash.is_(None), User.control_number.isnot(None)))
            if cohort_id is not None:
                q = q.filter(TitulationProcess.cohort_id == cohort_id)
            pendientes = q.distinct().all()
            click.echo(f"🔎 {len(pendientes)} alumno(s) sin contraseña (dry-run, nada escrito):")
            for u in pendientes:
                click.echo(f"   · {u.control_number}")
            return

        n = ImportService.repair_missing_credentials(db, cohort_id=cohort_id)

    if n:
        click.echo(f"✅ {n} alumno(s) con credencial inicial repuesta "
                   f"(contraseña = número de control, deben cambiarla al entrar).")
    else:
        click.echo("✅ Nada que reparar: ningún alumno de TitulaTec sin contraseña.")


def _verify_survey_2026_09() -> list[str]:
    """Comprueba que el delta ATERRIZÓ. Devuelve la lista de problemas.

    Existe porque los `RAISE NOTICE` del DML son INVISIBLES: nada en `itcj2/`
    lee `connection.notices`. Sin esto, el operador ve "OK" aunque el
    `INSERT ... SELECT` de grants haya insertado cero filas — que es justo lo
    que pasa si el rol todavía no existe. Mismo patrón que
    `itcj2/cli/directory.py::_verify_settings_permission`.
    """
    from sqlalchemy import text

    from itcj2.cli.core import _get_engine

    problemas: list[str] = []
    codigos = list(_SURVEY_2026_09_PERMS)

    with _get_engine().connect() as conn:
        existentes = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT p.code FROM core_permissions p "
                    "JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                    "WHERE p.code = ANY(:codes)"
                ),
                {"codes": codigos},
            )
        }
        for code in codigos:
            if code not in existentes:
                problemas.append(f"permiso ausente: {code}")

        concedidos = {
            (row[0], row[1])
            for row in conn.execute(
                text(
                    "SELECT r.name, p.code "
                    "  FROM core_role_permissions rp "
                    "  JOIN core_roles r ON r.id = rp.role_id "
                    "  JOIN core_permissions p ON p.id = rp.perm_id "
                    "  JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                    " WHERE p.code = ANY(:codes)"
                ),
                {"codes": codigos},
            )
        }
        for code in codigos:
            if ("titulatec_school_services_head", code) not in concedidos:
                problemas.append(f"sin grant a la jefatura: {code}")
        if ("titulatec_school_services", _PERM_MARCA_REQUISITO) not in concedidos:
            problemas.append(
                f"sin grant al encargado operativo: {_PERM_MARCA_REQUISITO}"
            )

        abiertos = conn.execute(
            text(
                "SELECT version FROM titulatec_survey_forms "
                " WHERE code = 'egresados' AND status = 'open'"
            )
        ).fetchall()
        if len(abiertos) != 1:
            problemas.append(
                f"formularios 'egresados' abiertos: {len(abiertos)} "
                "(el índice parcial uq_titulatec_survey_forms_open exige exactamente 1)"
            )

    return problemas


@titulatec_cli.command("load-survey-2026-09")
@click.option("--dry-run", is_flag=True, help="Lista los archivos sin ejecutarlos.")
def load_survey_2026_09_command(dry_run):
    """Carga SOLO el delta de septiembre 2026 (encuesta de egresados + convocatoria).

    NO re-ejecuta el DML base de la app: `03_insert_role_permissions.sql` lleva
    tres DELETE que se re-aplican en cada corrida y revocarían permisos
    concedidos a mano. En producción eso es justo lo que no se quiere.

    Idempotente: los cuatro archivos llevan `ON CONFLICT DO NOTHING` o un
    `ON CONFLICT DO UPDATE` acotado.

    Al terminar VERIFICA contra la base que los 8 permisos existen, que están
    concedidos (los 8 a la jefatura, `requirement.mark` también al encargado
    operativo) y que queda exactamente un formulario `egresados` abierto. Sin
    esa verificación el comando saldría 0 aunque no hubiera hecho nada: los
    `RAISE NOTICE` del SQL no se ven por ningún lado.
    """
    from itcj2.cli.core import execute_sql_file

    dml_dir = DML_TITULATEC / _DML_SURVEY_2026_09_DIR
    if not dml_dir.is_dir():
        click.echo(
            click.style(
                f"ERROR: no existe {dml_dir}. `database/` está gitignored: "
                "súbelo por scp al host.",
                fg="red",
            ),
            err=True,
        )
        raise click.Abort()

    for sql_file in _DML_SURVEY_2026_09_FILES:
        file_path = dml_dir / sql_file
        if not file_path.exists():
            click.echo(click.style(f"ERROR: falta {file_path}", fg="red"), err=True)
            raise click.Abort()
        if dry_run:
            click.echo(f"  [dry-run] {file_path}")
            continue
        click.echo(f"  Ejecutando: {sql_file}")
        invalidated = execute_sql_file(str(file_path))
        click.echo(
            click.style(
                f"  OK: {sql_file} (caché authz invalidado: {invalidated})", fg="green"
            )
        )

    if dry_run:
        click.echo("Dry-run: no se ejecutó nada.")
        return

    problemas = _verify_survey_2026_09()
    if problemas:
        for p in problemas:
            click.echo(click.style(f"ERROR: {p}", fg="red"), err=True)
        raise click.Abort()

    click.echo(
        click.style(
            "OK: 8 permisos, sus grants y el formulario 'egresados' v1 "
            "verificados en la base.",
            fg="green",
        )
    )
