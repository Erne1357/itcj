"""Deltas de despliegue: cada comando corre SOLO su subcarpeta de `database/DML/titulatec/`.

En producción `init-titulatec` completo nunca se re-ejecuta, así que estos
comandos son el único camino de despliegue de su delta: init-email-tasks,
init-outbox-admin, init-bitacora, init-reportes, init-especialidades e
init-ajustes-2026-10 (cada uno con su verificación contra la BD).
"""
import click

from itcj2.cli.titulatec._common import (
    DML_TITULATEC,
    _abortar_con,
    _run_sql_files,
    titulatec_cli,
)
from itcj2.cli.titulatec.verificaciones import (
    _PERM_PROCESS_SUMMARY,
    _PERMISOS_HANDOFF,
    _PERMISOS_ROL_TITULACION,
    _ROL_ADMIN,
    _ROL_JEFATURA_ESCOLARES,
    _ROL_OPERATIVO_ESCOLARES,
    _ROL_TITULACION,
    _ROL_TITULACIONES_DIV,
)

# ---------------------------------------------------------------------------
# Correos del proceso al egresado (spec 2026-09-28 §6 C5): tareas periódicas
# `titulatec.email_dispatch` (cada 5 minutos) y `titulatec.email_reminders`
# (diaria 9:00), ya registradas en el worker (`TASK_DEFINITIONS`,
# `itcj2/tasks/titulatec_tasks.py`, tareas 7/8 de este plan). Faltaba darlas
# de alta en `core_periodic_tasks` — sin esa fila Celery Beat
# (`DatabaseScheduler`, SOLO lee BD) nunca las programa.
# ---------------------------------------------------------------------------
_DML_MAIL_2026_09_DIR = "mail_2026_09"
# Debe listar TODOS los .sql del directorio (mismo contrato que
# `_DML_SURVEY_2026_09_FILES` de arriba): lo fija
# `test_todo_sql_del_directorio_esta_en_la_lista`
# (tests/fastapi/titulatec/test_cli_mail_tasks.py). Un archivo que se cae de
# aquí no lo corre nadie y nada se pone rojo.
_DML_MAIL_2026_09_FILES = ["17_insert_email_tasks.sql"]


@titulatec_cli.command("init-email-tasks")
@click.option("--dry-run", is_flag=True, help="Lista el archivo sin ejecutarlo.")
def init_email_tasks_command(dry_run):
    """Da de alta las 2 tareas periódicas de correo del proceso al egresado.

    Corre SOLO `database/DML/titulatec/mail_2026_09/17_insert_email_tasks.sql`:
    `core_task_definitions` + `core_periodic_tasks` de `titulatec.email_dispatch`
    (cada 5 minutos) y `titulatec.email_reminders` (diaria 9:00) — spec
    2026-09-28 §6 C5. Celery Beat corre con `DatabaseScheduler`, que SOLO lee
    `core_periodic_tasks`: sin esta fila ninguna de las dos tareas se
    programa, aunque el worker ya las tenga registradas.

    NO re-ejecuta el resto de `SEED_FILES` (eso es `init-titulatec`): en
    producción el DML viejo NUNCA se re-ejecuta, así que este comando es el
    único camino de despliegue para el delta de correo. Idempotente, mismo
    patrón que `sii_2026_09/16_insert_sii_sweep_task.sql`: el `ON CONFLICT`
    no pisa `is_active` ni `cron_expression` si alguien pausó una periódica o
    le cambió la frecuencia desde `/config/system/tasks`. Correrlo dos veces
    no duplica nada.

    Córrelo DESPUÉS del deploy: `deploy.sh` (paso 11.1) ya recrea el celery
    worker y el beat con el código que registra
    `titulatec.email_dispatch`/`titulatec.email_reminders`, y el beat
    (`DatabaseScheduler`) relee `core_periodic_tasks` cada 30 s, así que no
    hace falta reiniciar nada. Antes del deploy, el beat viejo mandaría las
    tareas a un worker que aún no las conoce.
    """
    if dry_run:
        click.echo("[dry-run] Se ejecutaría:")
        for nombre in _DML_MAIL_2026_09_FILES:
            click.echo(f"  {_DML_MAIL_2026_09_DIR}/{nombre}")
        click.echo("Dry-run: no se ejecutó nada.")
        return

    _run_sql_files([f"{_DML_MAIL_2026_09_DIR}/{nombre}" for nombre in _DML_MAIL_2026_09_FILES])
    click.echo(click.style(
        "OK: titulatec.email_dispatch (cada 5 minutos) y titulatec.email_reminders "
        "(diaria 9:00) registradas en core_periodic_tasks. El beat las programa "
        "solo en ~30 s (el worker ya las conoce si corrió el deploy).",
        fg="green",
    ))


# ---------------------------------------------------------------------------
# Pestaña «Correos» (2026-10-06): vista de SOLO LECTURA de
# `titulatec_email_outbox` para el rol `admin` (`pages/mail_admin.py`). Un
# permiso nuevo, `titulatec.email_outbox.page.list`, concedido SOLO a `admin`
# y de forma EXPLICITA: en produccion `init-titulatec` (y con el el 15, que
# concede dinamicamente todo a `admin`) nunca se re-ejecuta, asi que este
# comando es el unico camino de despliegue del delta -- ademas de sumarse a
# `SEED_FILES` para una instalacion desde cero (mismo patron D10 que
# `init-email-tasks`/`init-posgrado`).
# ---------------------------------------------------------------------------
_DML_OUTBOX_2026_10_DIR = "outbox_2026_10"
# Debe listar TODOS los .sql del directorio (mismo contrato que
# `_DML_MAIL_2026_09_FILES`): lo fija
# `test_el_directorio_lista_exactamente_su_archivo`
# (tests/fastapi/titulatec/test_mail_outbox_admin.py). Un archivo que se cae
# de aqui no lo corre nadie y nada se pone rojo.
_DML_OUTBOX_2026_10_FILES = ["24_insert_email_outbox_perm.sql"]
_OUTBOX_PERM = "titulatec.email_outbox.page.list"


def _verify_outbox_admin() -> list[str]:
    """Comprueba que el 24 ATERRIZO: el permiso existe y el rol `admin` lo
    tiene. Devuelve problemas (mismo contrato que `_verify_biblioteca_caja`:
    los `RAISE NOTICE` del SQL son invisibles para `itcj2/`). Sesion propia
    (`SessionLocal`, import local) para que `patched_session_local` la
    intercepte en las pruebas. Solo lectura.

    Solo exige que `admin` lo CONTENGA: que ningun otro rol lo tenga es una
    decision del DML, no algo que este comando deba vigilar en una base que
    alguien pudo ajustar a mano despues.
    """
    from sqlalchemy import text

    from itcj2.database import SessionLocal

    problemas: list[str] = []
    db = SessionLocal()
    try:
        existe = db.execute(
            text("SELECT 1 FROM core_permissions p JOIN core_apps a ON a.id = p.app_id "
                 "WHERE a.key = 'titulatec' AND p.code = :code"),
            {"code": _OUTBOX_PERM},
        ).first()
        if existe is None:
            problemas.append(f"permiso ausente: {_OUTBOX_PERM}")
            return problemas
        concedido = db.execute(
            text("SELECT 1 FROM core_role_permissions rp "
                 "JOIN core_roles r ON r.id = rp.role_id "
                 "JOIN core_permissions p ON p.id = rp.perm_id "
                 "JOIN core_apps a ON a.id = p.app_id "
                 "WHERE a.key = 'titulatec' AND r.name = 'admin' AND p.code = :code"),
            {"code": _OUTBOX_PERM},
        ).first()
        if concedido is None:
            problemas.append(f"el rol admin no tiene {_OUTBOX_PERM}")
    finally:
        db.close()
    return problemas


@titulatec_cli.command("init-outbox-admin")
@click.option("--dry-run", is_flag=True,
              help="Comprueba el archivo en disco y lo lista, sin escribir nada.")
def init_outbox_admin_command(dry_run):
    """Da de alta la pestaña «Correos» (solo lectura del outbox) para `admin`.

    Corre SOLO `database/DML/titulatec/outbox_2026_10/24_insert_email_outbox_perm.sql`:
    el permiso `titulatec.email_outbox.page.list` y su concesion EXPLICITA al
    rol `admin` de titulatec. NO re-ejecuta el resto de `SEED_FILES`: en
    produccion el DML viejo nunca se re-corre. Idempotente (ON CONFLICT):
    correrlo dos veces no duplica nada.

    Al terminar VERIFICA con `_verify_outbox_admin()` y aborta si algo no
    aterrizo. Despues no hace falta reiniciar: el menu y la ruta leen los
    permisos por la cache de authz, que caduca sola (`AUTHZ_CACHE_TTL`).
    `--dry-run`: comprueba que el archivo existe y lo lista, sin escribir.
    """
    dml_dir = DML_TITULATEC / _DML_OUTBOX_2026_10_DIR
    faltan = [n for n in _DML_OUTBOX_2026_10_FILES if not (dml_dir / n).exists()]

    if dry_run:
        if faltan:
            click.echo(click.style(f"ERROR: faltan archivos en disco: {faltan}", fg="red"))
        else:
            click.echo("Archivos en disco: OK. Se ejecutaría:")
            for nombre in _DML_OUTBOX_2026_10_FILES:
                click.echo(f"  {_DML_OUTBOX_2026_10_DIR}/{nombre}")
        click.echo("Dry-run: no se ejecutó nada.")
        if faltan:
            raise click.Abort()
        return

    _run_sql_files([f"{_DML_OUTBOX_2026_10_DIR}/{nombre}" for nombre in _DML_OUTBOX_2026_10_FILES])

    problemas = _verify_outbox_admin()
    if problemas:
        _abortar_con(problemas)

    click.echo(click.style(
        f"OK: {_OUTBOX_PERM} existe y el rol admin lo tiene. La pestaña «Correos» "
        "aparece en el menú admin en cuanto caduque la caché de permisos.",
        fg="green",
    ))


# ---------------------------------------------------------------------------
# Bitacora de auditoria (2026-10-07): permiso `titulatec.audit.page.list`
# (solo `admin`). El 25 lo inserta Y lo concede explicito a `admin`, asi que el
# comando corre SOLO el 25 (patron `init-outbox-admin`). Nunca el 15: en
# produccion no se re-corre (concede TODO titulatec a `admin`, que por el
# puesto D2 llega a la jefatura de Centro de Computo; revision final I3).
# ---------------------------------------------------------------------------
_DML_AUDIT_2026_10_DIR = "audit_2026_10"
_DML_AUDIT_2026_10_FILES = ["25_insert_audit_perm.sql"]
_AUDIT_PERM = "titulatec.audit.page.list"


def _verify_bitacora() -> list[str]:
    """Comprueba que el 25 ATERRIZO: el permiso existe y el rol
    `admin` lo tiene. Devuelve problemas (mismo contrato que
    `_verify_outbox_admin`). Sesion propia, solo lectura."""
    from sqlalchemy import text

    from itcj2.database import SessionLocal

    problemas: list[str] = []
    db = SessionLocal()
    try:
        existe = db.execute(
            text("SELECT 1 FROM core_permissions p JOIN core_apps a ON a.id = p.app_id "
                 "WHERE a.key = 'titulatec' AND p.code = :code"),
            {"code": _AUDIT_PERM},
        ).first()
        if existe is None:
            problemas.append(f"permiso ausente: {_AUDIT_PERM}")
            return problemas
        concedido = db.execute(
            text("SELECT 1 FROM core_role_permissions rp "
                 "JOIN core_roles r ON r.id = rp.role_id "
                 "JOIN core_permissions p ON p.id = rp.perm_id "
                 "JOIN core_apps a ON a.id = p.app_id "
                 "WHERE a.key = 'titulatec' AND r.name = 'admin' AND p.code = :code"),
            {"code": _AUDIT_PERM},
        ).first()
        if concedido is None:
            problemas.append(f"el rol admin no tiene {_AUDIT_PERM}")
    finally:
        db.close()
    return problemas


@titulatec_cli.command("init-bitacora")
@click.option("--dry-run", is_flag=True,
              help="Comprueba los archivos en disco y los lista, sin escribir nada.")
def init_bitacora_command(dry_run):
    """Da de alta el permiso de la bitácora de auditoría para `admin`.

    Corre SOLO `audit_2026_10/25_insert_audit_perm.sql`: inserta
    `titulatec.audit.page.list` y lo concede EXPLÍCITO al rol `admin`. NO
    re-ejecuta el 15 ni el resto de `SEED_FILES`: en producción el DML viejo
    nunca se re-corre. Idempotente (ON CONFLICT). Al terminar VERIFICA con
    `_verify_bitacora()` y aborta si algo no aterrizo. `--dry-run`: comprueba
    que el archivo existe y lo lista, sin escribir.
    """
    archivos = [f"{_DML_AUDIT_2026_10_DIR}/{n}" for n in _DML_AUDIT_2026_10_FILES]
    faltan = [n for n in archivos if not (DML_TITULATEC / n).exists()]

    if dry_run:
        if faltan:
            click.echo(click.style(f"ERROR: faltan archivos en disco: {faltan}", fg="red"))
        else:
            click.echo("Archivos en disco: OK. Se ejecutaría:")
            for nombre in archivos:
                click.echo(f"  {nombre}")
        click.echo("Dry-run: no se ejecutó nada.")
        if faltan:
            raise click.Abort()
        return

    _run_sql_files(archivos)

    problemas = _verify_bitacora()
    if problemas:
        _abortar_con(problemas)

    click.echo(click.style(
        f"OK: {_AUDIT_PERM} existe y el rol admin lo tiene.", fg="green"))


# ---------------------------------------------------------------------------
# Tablero de la jefa de SE (2026-10-14): permiso `titulatec.reports.page.view`.
# El 26 lo inserta y lo concede EXPLICITO a `titulatec_school_services_head` Y a
# `admin` (revision final I1/I3, mismo patron que el 25). En produccion el 15
# NUNCA se re-corre (reparte todo titulatec a `admin`, y por el puesto D2 llega
# a la jefatura de Centro de Computo), asi que este comando corre SOLO el 26.
# Invalida el cache de authz SOLO de titulatec (nunca `invalidate_all`).
# ---------------------------------------------------------------------------
_DML_REPORTES_2026_10_DIR = "reportes_2026_10"
_DML_REPORTES_2026_10_FILES = ["26_insert_reports_perm.sql"]
_REPORTS_PERM = "titulatec.reports.page.view"
_REPORTS_ROLES = ("titulatec_school_services_head", "admin")


def _verify_reportes() -> list[str]:
    """Comprueba que el 26 (y el 15) ATERRIZARON: el permiso existe y lo tienen
    la jefa de SE y `admin`. Devuelve problemas (contrato de
    `_verify_bitacora`). Sesion propia, solo lectura."""
    from sqlalchemy import text

    from itcj2.database import SessionLocal

    problemas: list[str] = []
    db = SessionLocal()
    try:
        existe = db.execute(
            text("SELECT 1 FROM core_permissions p JOIN core_apps a ON a.id = p.app_id "
                 "WHERE a.key = 'titulatec' AND p.code = :code"),
            {"code": _REPORTS_PERM},
        ).first()
        if existe is None:
            return [f"permiso ausente: {_REPORTS_PERM}"]
        for rol in _REPORTS_ROLES:
            concedido = db.execute(
                text("SELECT 1 FROM core_role_permissions rp "
                     "JOIN core_roles r ON r.id = rp.role_id "
                     "JOIN core_permissions p ON p.id = rp.perm_id "
                     "JOIN core_apps a ON a.id = p.app_id "
                     "WHERE a.key = 'titulatec' AND r.name = :rol AND p.code = :code"),
                {"rol": rol, "code": _REPORTS_PERM},
            ).first()
            if concedido is None:
                problemas.append(f"el rol {rol} no tiene {_REPORTS_PERM}")
    finally:
        db.close()
    return problemas


@titulatec_cli.command("init-reportes")
@click.option("--dry-run", is_flag=True,
              help="Comprueba los archivos en disco y los lista, sin escribir nada.")
def init_reportes_command(dry_run):
    """Da de alta el permiso del Tablero de la jefa de Servicios Escolares.

    Corre `reportes_2026_10/26_insert_reports_perm.sql` (inserta
    `titulatec.reports.page.view` y lo concede a `titulatec_school_services_head`)
    y a `admin`). Corre SOLO ese archivo: NO re-ejecuta el 15 ni el resto de
    `SEED_FILES`. Idempotente (ON CONFLICT).
    Invalida el cache de authz solo de titulatec y VERIFICA con
    `_verify_reportes()`; aborta si algo no aterrizo. `--dry-run`: comprueba que
    los archivos existen y los lista, sin escribir.
    """
    archivos = [f"{_DML_REPORTES_2026_10_DIR}/{n}" for n in _DML_REPORTES_2026_10_FILES]
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

    problemas = _verify_reportes()
    if problemas:
        _abortar_con(problemas)

    click.echo(click.style(
        f"OK: {_REPORTS_PERM} existe y lo tienen {' y '.join(_REPORTS_ROLES)}.",
        fg="green"))


# ---------------------------------------------------------------------------
# Especialidades de la encuesta de egresados (2026-10-08): el 26 reescribe
# SOLO las opciones de `especialidad` del formulario 'egresados' abierto (en
# sitio, misma version), con `group` = carrera. Nunca quita un valor actual
# (aborta si lo haria). En produccion el 11 nunca se re-corre: este comando es
# el unico camino de despliegue; en una instalacion desde cero lo corre
# `init-titulatec` despues del 11.
# ---------------------------------------------------------------------------
_DML_SURVEY_2026_10_DIR = "survey_2026_10"
_DML_SURVEY_2026_10_FILES = ["26_especialidades_por_carrera.sql"]


def _verify_especialidades() -> list[str]:
    """Comprueba que el 26 ATERRIZO en el formulario 'egresados' abierto: el
    esquema sigue pasando `validate_schema` y toda opcion de `especialidad`
    trae carrera salvo «No tiene». Devuelve problemas (contrato de
    `_verify_bitacora`). Sesion propia, solo lectura."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.survey_service import SurveyService
    from itcj2.apps.titulatec.utils.survey_validator import (
        option_group_names, validate_schema,
    )

    problemas: list[str] = []
    db = SessionLocal()
    try:
        form = SurveyService.open_form(db, "egresados")
        if form is None:
            return ["no hay formulario 'egresados' abierto"]
        schema = form.schema or {}
        ok, errores = validate_schema(schema)
        if not ok:
            problemas.extend(f"esquema invalido: {e}" for e in errores)
        campo = next((f for f in schema.get("fields") or []
                      if isinstance(f, dict) and f.get("key") == "especialidad"), None)
        if campo is None:
            return problemas + ["el formulario abierto no tiene el campo 'especialidad'"]
        sin_carrera = [o.get("value") for o in campo.get("options") or []
                       if isinstance(o, dict) and o.get("value") != "No tiene"
                       and not option_group_names(o)]
        if sin_carrera:
            problemas.append(f"opciones de especialidad sin carrera: {sin_carrera}")
    finally:
        db.close()
    return problemas


@titulatec_cli.command("init-especialidades")
@click.option("--dry-run", is_flag=True,
              help="Comprueba el archivo en disco y lo lista, sin escribir nada.")
def init_especialidades_command(dry_run):
    """Especialidades de la encuesta de egresados agrupadas por carrera.

    Corre SOLO `survey_2026_10/26_especialidades_por_carrera.sql`: reescribe
    las opciones de `especialidad` del formulario 'egresados' abierto (sin
    cambiar ni quitar ningun valor que ya tenga respuestas) y agrega las de las
    reticulas 2014 en adelante. NO re-ejecuta el 11 ni el resto de
    `SEED_FILES`. Idempotente. Al terminar VERIFICA con
    `_verify_especialidades()` y aborta si algo no aterrizo. `--dry-run`:
    comprueba que el archivo existe y lo lista, sin escribir.
    """
    archivos = [f"{_DML_SURVEY_2026_10_DIR}/{n}" for n in _DML_SURVEY_2026_10_FILES]
    faltan = [n for n in archivos if not (DML_TITULATEC / n).exists()]

    if dry_run:
        if faltan:
            click.echo(click.style(f"ERROR: faltan archivos en disco: {faltan}", fg="red"))
        else:
            click.echo("Archivos en disco: OK. Se ejecutaría:")
            for nombre in archivos:
                click.echo(f"  {nombre}")
        click.echo("Dry-run: no se ejecutó nada.")
        if faltan:
            raise click.Abort()
        return

    _run_sql_files(archivos)

    problemas = _verify_especialidades()
    if problemas:
        _abortar_con(problemas)

    click.echo(click.style(
        "OK: la encuesta de egresados muestra las especialidades agrupadas por carrera.",
        fg="green"))


# ---------------------------------------------------------------------------
# Ajustes 2026-10 (spec 2026-10-07-titulatec-liberados-biblioteca-helpdesk-
# design.md, D1/D2/D7/D8, §1.1, §3, §6, §7): delta de PRODUCCIÓN.
#
#   - permiso NUEVO `titulatec.process.page.summary` (expediente resumido);
#   - `titulatec_titulacion` CONVERGE a su set EXACTO de 16 (el usuario editó
#     a mano sus permisos en la BD: se le concede lo que le falte del set y se
#     le quita todo lo de titulatec fuera de él);
#   - `titulatec_school_services` y `titulatec_school_services_head` ganan
#     Liberados (`handoff.page.list` + `handoff.api.export`), sin set exacto;
#   - `admin` recibe el permiso nuevo EXPLÍCITO (en producción nunca se
#     re-corre el 15, que se lo daría dinámicamente);
#   - `titulatec_titulaciones` (25) NO cambia;
#   - el requisito de cotejo `library_clearance` pasa de «No-adeudo de
#     biblioteca» a «Constancia de no adeudo de biblioteca» (solo donde sigue
#     con el texto viejo).
#
# NO va en `SEED_FILES`: una instalación desde cero ya nace con ese estado
# (el 02 declara el permiso nuevo; el 03 trae los ARRAYs nuevos y converge a
# titulación; el 15 da todo a `admin`; el 22 de `biblioteca_2026_10/` trae la
# etiqueta nueva). Este comando es el único camino de despliegue a una base
# ya sembrada (producción): el DML viejo nunca se re-corre allí.
# ---------------------------------------------------------------------------
_DML_AJUSTES_2026_10_DIR = "ajustes_2026_10"
# Debe listar TODOS los .sql del directorio: lo fija
# `test_todo_sql_del_directorio_esta_en_la_lista_del_comando`
# (tests/fastapi/titulatec/test_cli_ajustes_2026_10.py).
_DML_AJUSTES_2026_10_FILES = [
    "01_liberados_permisos.sql",
    "02_requisito_constancia.sql",
]
# Copia EXACTA de `CotejoRequirementService.DEFAULTS` (etiqueta nueva) y del
# texto viejo; los dos `.sql` (el 02 del delta y el 22 de la base) llevan los
# mismos literales.
_ETIQUETA_BIBLIOTECA_VIEJA = "No-adeudo de biblioteca"
_ETIQUETA_BIBLIOTECA = "Constancia de no adeudo de biblioteca"
_ROLES_AJUSTES_2026_10 = (
    _ROL_TITULACION,
    _ROL_TITULACIONES_DIV,
    _ROL_OPERATIVO_ESCOLARES,
    _ROL_JEFATURA_ESCOLARES,
)


def _snapshot_ajustes_2026_10() -> dict:
    """Foto de SOLO LECTURA de lo que toca el delta:

    `{"roles": {rol existente, ...},
      "perms": {rol: {codigo, ...}} (permisos de titulatec de los 4 roles),
      "existe_summary": bool (el permiso nuevo ya está en core_permissions),
      "admin_summary": bool (el rol `admin` ya lo tiene),
      "etiquetas": {label: n} (filas `code='library_clearance'` por etiqueta)}`

    Abre su PROPIA sesión (`SessionLocal`, import local) para que
    `patched_session_local` la intercepte en las pruebas; solo SELECT, y la
    cierra (sin `rollback` explícito, mismo criterio que
    `_precheck_activar_biblioteca`).
    """
    from sqlalchemy import text

    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        roles = {
            row[0]
            for row in db.execute(
                text("SELECT name FROM core_roles WHERE name = ANY(:roles)"),
                {"roles": list(_ROLES_AJUSTES_2026_10)},
            )
        }
        perms: dict[str, set[str]] = {rol: set() for rol in _ROLES_AJUSTES_2026_10}
        for rol, code in db.execute(
            text(
                "SELECT r.name, p.code FROM core_role_permissions rp "
                "  JOIN core_roles r ON r.id = rp.role_id "
                "  JOIN core_permissions p ON p.id = rp.perm_id "
                "  JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                " WHERE r.name = ANY(:roles)"
            ),
            {"roles": list(_ROLES_AJUSTES_2026_10)},
        ):
            perms[rol].add(code)
        existe_summary = db.execute(
            text(
                "SELECT 1 FROM core_permissions p "
                "  JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                " WHERE p.code = :code"
            ),
            {"code": _PERM_PROCESS_SUMMARY},
        ).first() is not None
        admin_summary = db.execute(
            text(
                "SELECT 1 FROM core_role_permissions rp "
                "  JOIN core_roles r ON r.id = rp.role_id "
                "  JOIN core_permissions p ON p.id = rp.perm_id "
                "  JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                " WHERE r.name = :rol AND p.code = :code"
            ),
            {"rol": _ROL_ADMIN, "code": _PERM_PROCESS_SUMMARY},
        ).first() is not None
        etiquetas = {
            label: int(n)
            for label, n in db.execute(
                text(
                    "SELECT label, COUNT(*) FROM titulatec_cotejo_requirements "
                    " WHERE code = 'library_clearance' GROUP BY label"
                )
            )
        }
    finally:
        db.close()
    return {"roles": roles, "perms": perms, "existe_summary": existe_summary,
            "admin_summary": admin_summary, "etiquetas": etiquetas}


def _esperado_ajustes_2026_10(perms_antes: dict[str, set[str]]) -> dict[str, set[str]]:
    """Lo que el delta debe dejar a cada rol, a partir de lo que tenía:
    titulación CONVERGE a su set exacto (lo que tuviera antes da igual);
    Servicios Escolares = lo de antes + Liberados; titulaciones igual."""
    liberados = set(_PERMISOS_HANDOFF)
    return {
        _ROL_TITULACION: set(_PERMISOS_ROL_TITULACION),
        _ROL_TITULACIONES_DIV: set(perms_antes.get(_ROL_TITULACIONES_DIV, set())),
        _ROL_OPERATIVO_ESCOLARES: set(perms_antes.get(_ROL_OPERATIVO_ESCOLARES, set())) | liberados,
        _ROL_JEFATURA_ESCOLARES: set(perms_antes.get(_ROL_JEFATURA_ESCOLARES, set())) | liberados,
    }


def _faltan_sobran(rol: str, tiene: set[str], debe: set[str], que: str) -> str | None:
    if tiene == debe:
        return None
    return (f"{rol} no quedó con {que} (faltan {sorted(debe - tiene)}, "
            f"sobran {sorted(tiene - debe)})")


def _verify_ajustes_2026_10(antes: dict, despues: dict) -> list[str]:
    """Comprueba que el delta ATERRIZÓ. Pura (recibe las dos fotos de
    `_snapshot_ajustes_2026_10`); devuelve problemas, mismo contrato de salida
    que el resto de los `_verify_*` (los `RAISE NOTICE` del SQL son invisibles
    para `itcj2/`).

    - Los 4 roles existen y el permiso nuevo existe.
    - `titulatec_titulacion` tiene EXACTAMENTE sus 16
      (`_PERMISOS_ROL_TITULACION`): contrato absoluto (D8), no relativo a lo
      que tenía antes (que el usuario editó a mano).
    - Servicios Escolares quedó EXACTAMENTE con lo de antes + Liberados (el
      delta no les quita nada) y titulaciones exactamente igual.
    - `admin` tiene el permiso nuevo.
    - Ninguna fila `library_clearance` conserva la etiqueta vieja.
    """
    problemas: list[str] = []
    for rol in _ROLES_AJUSTES_2026_10:
        if rol not in despues["roles"]:
            problemas.append(f"rol ausente: {rol}")
    if not despues["existe_summary"]:
        problemas.append(f"permiso ausente: {_PERM_PROCESS_SUMMARY}")

    esperado = _esperado_ajustes_2026_10(antes["perms"])
    que = {
        _ROL_TITULACION: f"exactamente sus {len(_PERMISOS_ROL_TITULACION)} permisos",
        _ROL_TITULACIONES_DIV: "lo que tenía (no debe cambiar)",
        _ROL_OPERATIVO_ESCOLARES: "lo que tenía más Liberados",
        _ROL_JEFATURA_ESCOLARES: "lo que tenía más Liberados",
    }
    for rol in _ROLES_AJUSTES_2026_10:
        p = _faltan_sobran(rol, despues["perms"].get(rol, set()), esperado[rol], que[rol])
        if p:
            problemas.append(p)

    if not despues["admin_summary"]:
        problemas.append(f"sin grant a {_ROL_ADMIN}: {_PERM_PROCESS_SUMMARY}")

    viejas = despues["etiquetas"].get(_ETIQUETA_BIBLIOTECA_VIEJA, 0)
    if viejas:
        problemas.append(
            f"{viejas} requisito(s) library_clearance conservan la etiqueta "
            f"«{_ETIQUETA_BIBLIOTECA_VIEJA}» (el 02 no aterrizó)")
    return problemas


def _echo_reparto_ajustes(antes: dict, perms_despues: dict[str, set[str]],
                          admin_summary_despues: bool) -> None:
    """Por rol: `rol: N → M` y debajo cada código que sale (`-`) o entra (`+`);
    luego la concesión explícita del permiso nuevo a `admin`."""
    for rol in _ROLES_AJUSTES_2026_10:
        tenia = antes["perms"].get(rol, set())
        queda = perms_despues.get(rol, set())
        click.echo(f"  {rol}: {len(tenia)} → {len(queda)}")
        for code in sorted(tenia - queda):
            click.echo(f"      - {code}")
        for code in sorted(queda - tenia):
            click.echo(f"      + {code}")
    if not antes["admin_summary"] and admin_summary_despues:
        click.echo(f"  {_ROL_ADMIN}: + {_PERM_PROCESS_SUMMARY}")


def _echo_etiquetas_ajustes(etiquetas: dict[str, int]) -> None:
    viejas = etiquetas.get(_ETIQUETA_BIBLIOTECA_VIEJA, 0)
    nuevas = etiquetas.get(_ETIQUETA_BIBLIOTECA, 0)
    otras = sum(n for label, n in etiquetas.items()
                if label not in (_ETIQUETA_BIBLIOTECA_VIEJA, _ETIQUETA_BIBLIOTECA))
    click.echo(f"  «{_ETIQUETA_BIBLIOTECA_VIEJA}»: {viejas} fila(s) · "
               f"«{_ETIQUETA_BIBLIOTECA}»: {nuevas} fila(s) · "
               f"otra etiqueta (editada a mano, no se toca): {otras} fila(s)")


@titulatec_cli.command("init-ajustes-2026-10")
@click.option("--dry-run", is_flag=True,
              help="Reporta el estado actual y lo que agregaría/quitaría, sin escribir nada.")
def init_ajustes_2026_10_command(dry_run):
    """Ajustes 2026-10: Liberados para Servicios Escolares; Titulación solo ve
    Liberados y el expediente resumido; requisito «Constancia de no adeudo de
    biblioteca».

    Corre SOLO los 2 archivos de `database/DML/titulatec/ajustes_2026_10/`
    (spec 2026-10-07-titulatec-liberados-biblioteca-helpdesk-design.md, §6/§7):

    - `01_liberados_permisos.sql`: crea `titulatec.process.page.summary`;
      CONVERGE `titulatec_titulacion` a su set EXACTO de 16 (concede lo que
      le falte y le quita todo lo de titulatec fuera de él: el usuario editó
      a mano sus permisos); `titulatec_school_services` y
      `titulatec_school_services_head` ganan `handoff.page.list` +
      `handoff.api.export`; `admin` recibe el permiso nuevo.
      `titulatec_titulaciones` no cambia.
    - `02_requisito_constancia.sql`: el requisito `library_clearance` que
      sigue llamándose «No-adeudo de biblioteca» pasa a «Constancia de no
      adeudo de biblioteca» (respeta las etiquetas editadas a mano).

    NO re-ejecuta el DML base (`init-titulatec`): en producción el DML viejo
    nunca se re-corre. Idempotente: correrlo dos veces no cambia nada la
    segunda.

    Cada archivo corre con `execute_sql_file(..., invalidate_authz=False)` y,
    con los dos ya aplicados, se invalida el caché de authz SOLO de titulatec
    (`invalidate_app("titulatec")`; nunca `invalidate_all`, que tiraría el
    caché de todas las apps). Después VERIFICA contra la BD
    (`_verify_ajustes_2026_10`; titulación con igualdad exacta del set) y
    aborta si algo no aterrizó. Imprime los permisos por rol antes y después
    y el set COMPLETO que tenía titulación antes (para la reversa: lo que el
    usuario editó a mano no se puede reconstruir de otro lado).

    `--dry-run`: solo lectura -- comprueba los archivos en disco e imprime el
    estado actual y qué agregaría/quitaría por código de permiso (y la
    etiqueta), sin escribir nada ni invalidar el caché.

    Reversa: el SQL inverso documentado en la cabecera de cada archivo del
    delta.
    """
    dml_dir = DML_TITULATEC / _DML_AJUSTES_2026_10_DIR
    faltan = [n for n in _DML_AJUSTES_2026_10_FILES if not (dml_dir / n).exists()]

    if not dry_run and faltan:
        _abortar_con([f"faltan archivos en disco en {dml_dir}: {faltan} "
                      "(database/ está gitignored: súbelos al host)"])

    antes = _snapshot_ajustes_2026_10()
    click.echo(f"{_ROL_TITULACION} hoy ({len(antes['perms'][_ROL_TITULACION])}, "
               "guárdalo para la reversa):")
    for code in sorted(antes["perms"][_ROL_TITULACION]):
        click.echo(f"      {code}")

    if dry_run:
        if faltan:
            click.echo(click.style(f"ERROR: faltan archivos en disco: {faltan}", fg="red"))
        else:
            click.echo("Archivos en disco: OK. Se ejecutarían:")
            for nombre in _DML_AJUSTES_2026_10_FILES:
                click.echo(f"  {_DML_AJUSTES_2026_10_DIR}/{nombre}")
        click.echo(f"[dry-run] Permiso {_PERM_PROCESS_SUMMARY}: "
                   + ("ya existe" if antes["existe_summary"] else "se crearía"))
        click.echo("[dry-run] Permisos en titulatec por rol (hoy → quedaría; "
                   "- quitaría, + agregaría):")
        _echo_reparto_ajustes(antes, _esperado_ajustes_2026_10(antes["perms"]), True)
        click.echo("[dry-run] Requisito de cotejo de biblioteca (hoy):")
        _echo_etiquetas_ajustes(antes["etiquetas"])
        click.echo(f"[dry-run] {antes['etiquetas'].get(_ETIQUETA_BIBLIOTECA_VIEJA, 0)} "
                   f"fila(s) pasarían a «{_ETIQUETA_BIBLIOTECA}».")
        click.echo("Dry-run: no se ejecutó nada.")
        if faltan:
            raise click.Abort()
        return

    from itcj2.cli.core import execute_sql_file

    for nombre in _DML_AJUSTES_2026_10_FILES:
        click.echo(f"   🔄 Ejecutando: {_DML_AJUSTES_2026_10_DIR}/{nombre}")
        execute_sql_file(str(dml_dir / nombre), invalidate_authz=False)
        click.echo(f"   ✅ Completado: {_DML_AJUSTES_2026_10_DIR}/{nombre}")

    # Después del commit de los dos archivos (execute_sql_file commitea por
    # dentro) y ANTES de verificar: si la verificación aborta, el SQL ya
    # quedó aplicado y el caché tiene que reflejarlo igual. Best-effort:
    # `invalidate_app` no levanta (un Redis caído lo deja al TTL, 5 min).
    from itcj2.core.services.authz_cache import invalidate_app
    invalidate_app("titulatec")
    click.echo("Caché de authz de titulatec invalidado (solo esta app).")

    despues = _snapshot_ajustes_2026_10()
    click.echo("Permisos en titulatec por rol (antes → después):")
    _echo_reparto_ajustes(antes, despues["perms"], despues["admin_summary"])
    click.echo("Requisito de cotejo de biblioteca (después):")
    _echo_etiquetas_ajustes(despues["etiquetas"])

    problemas = _verify_ajustes_2026_10(antes, despues)
    if problemas:
        _abortar_con(problemas)

    click.echo(click.style(
        f"OK: {_ROL_TITULACION} con exactamente sus {len(_PERMISOS_ROL_TITULACION)}, "
        "Liberados en los dos roles de Servicios Escolares, "
        f"{_ROL_TITULACIONES_DIV} sin cambio, {_PERM_PROCESS_SUMMARY} con admin y "
        f"el requisito «{_ETIQUETA_BIBLIOTECA}» verificados en la base.",
        fg="green",
    ))
