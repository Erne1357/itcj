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
# lleva DELETE que revocan `cohort.*` a `titulatec_titulaciones` (las
# convocatorias son de Servicios Escolares) y TODO lo de titulatec a `student`
# (desde 2026-09-15 el alumno es `graduate`). Eso se aplica EN CADA CORRIDA: una
# concesión manual posterior de esos permisos se pierde al re-sembrar. Es la
# política declarada, no un accidente.
SEED_FILES = [
    "00_insert_app.sql",                  # Registra la app en core_apps
    "01_insert_roles.sql",                # 7 roles nuevos: incl. 'graduate' (alumno) y titulatec_tech_management (GTV)
    "02_insert_permissions.sql",          # Permisos titulatec.*
    "03_insert_role_permissions.sql",     # Asignación rol→permisos (incl. 'graduate') + revocaciones
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
    "survey_2026_09/09_insert_survey_perms.sql",           # 11 permisos (8 encuesta/solicitudes + 3 liberacion GTV)
    "survey_2026_09/10_insert_survey_role_permissions.sql",# grants (GTV 9; jefatura recortada a enrollment_request+requirement.mark; operativo requirement.mark)
    "survey_2026_09/11_seed_survey_form.sql",              # formulario 'egresados' v1, status open
    "survey_2026_09/12_seed_cotejo_codes.sql",             # auto_source del requisito de la encuesta
    # El 13 es lo que ARMA la guarda de la fase 2 en las convocatorias que ya
    # existían. `cohort_create` siembra el checklist desde 2026-09-08, así que
    # sin este archivo toda convocatoria anterior queda con CERO requisitos y
    # `RequirementService.missing_required` devuelve `[]`: la guarda no falla,
    # simplemente nunca dispara, sin error ni aviso. Solo se auto-corrige por
    # accidente, si algún alumno de esa convocatoria abre su checklist antes que
    # el oficial (`list_or_seed` siembra al leer). Idempotente: solo inserta
    # donde hay cero.
    "survey_2026_09/13_seed_cotejo_reqs_all_cohorts.sql",  # checklist en convocatorias previas
    # El 14 mueve a `graduate` a quien ya tenía proceso antes del 2026-09-15.
    # Exige el rol CON sus permisos (el 01 y el 03, que corren antes en esta
    # lista) y aborta sin mover a nadie si faltan. No toca permisos de rol.
    "survey_2026_09/14_graduate_role_backfill.sql",        # rol graduate a alumnos con proceso
]

_DML_SURVEY_2026_09_DIR = "survey_2026_09"
# Debe listar TODOS los .sql del directorio: lo fija
# `test_todo_sql_del_delta_esta_en_la_lista_del_comando`
# (tests/fastapi/titulatec/test_cli_survey_delta.py). Un archivo que se cae de
# aquí no lo corre nadie y nada se pone rojo — así se perdió el 13.
_DML_SURVEY_2026_09_FILES = [
    "09_insert_survey_perms.sql",
    "10_insert_survey_role_permissions.sql",
    "11_seed_survey_form.sql",
    "12_seed_cotejo_codes.sql",
    "13_seed_cotejo_reqs_all_cohorts.sql",
    "14_graduate_role_backfill.sql",
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
    # 2026-09-15 (spec 2026-09-15-titulatec-liberacion-gtv): liberacion de la
    # encuesta de egresados por Gestion Tecnologica y Vinculacion (GTV).
    "titulatec.survey_review.page.list",
    "titulatec.survey_review.api.approve",
    "titulatec.survey_review.api.reject",
)

_PERM_MARCA_REQUISITO = "titulatec.process.api.requirement.mark"

# ---------------------------------------------------------------------------
# Reparto de GTV (2026-09-15): rol nuevo `titulatec_tech_management`, puesto
# de ventanilla `external_service_tech_management` (el de jefatura,
# `head_tech_management`, ya existe en el organigrama del core). Ver spec
# 2026-09-15-titulatec-liberacion-gtv-design.md, seccion 7.
# ---------------------------------------------------------------------------
_ROL_GTV = "titulatec_tech_management"
_PUESTO_GTV_VENTANILLA = "external_service_tech_management"

# Los 2 de notificaciones no son parte del delta (`_SURVEY_2026_09_PERMS`,
# arriba): ya existian desde 02_insert_permissions.sql. Se listan aparte para
# no inflar el contrato de "codigos que este delta declara" con permisos que
# ya declaraba otro archivo.
_PERMISOS_NOTIFICACIONES = (
    "titulatec.notifications.api.read.own",
    "titulatec.notifications.api.mark_read",
)

# Los 9 que debe tener GTV en titulatec: los 3 nuevos de liberacion + los 4
# `survey.*` (bandeja/detalle/exportar/administrar, que la jefatura pierde) +
# los 2 de notificaciones que ya tiene el resto de los roles de la app.
_PERMISOS_GTV = (
    "titulatec.survey_review.page.list",
    "titulatec.survey_review.api.approve",
    "titulatec.survey_review.api.reject",
    "titulatec.survey.page.list",
    "titulatec.survey.api.read",
    "titulatec.survey.api.export",
    "titulatec.survey.api.manage",
) + _PERMISOS_NOTIFICACIONES

# La jefatura de Servicios Escolares pierde `titulatec.survey.%` (pasa a GTV,
# spec D12) pero conserva estos 4: las 3 solicitudes de auto-inscripcion y el
# marcado de requisitos de cotejo.
_ROL_JEFATURA_ESCOLARES = "titulatec_school_services_head"
_PERMISOS_JEFATURA_CONSERVA = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    _PERM_MARCA_REQUISITO,
)

_ROL_OPERATIVO_ESCOLARES = "titulatec_school_services"


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

    Ejecuta en orden los seeders de database/DML/titulatec/ (ver SEED_FILES).
    Idempotentes, pero el 03 revoca en cada corrida `cohort.*` a
    `titulatec_titulaciones` (las convocatorias son de Servicios Escolares) y todo
    lo de titulatec a `student` (el alumno es `graduate` desde 2026-09-15).

    Aborta si falta cualquier archivo: sembrar a medias deja la app en 404.

    El 10 (dentro de `survey_2026_09/`) también revoca en cada corrida
    `titulatec.survey.%` a la jefatura de Servicios Escolares: esa bandeja
    pasó a Gestión Tecnológica y Vinculación (GTV, rol `titulatec_tech_management`)
    desde 2026-09-15 (spec 2026-09-15-titulatec-liberacion-gtv).

    Al terminar VERIFICA contra la base con `_verify_survey_2026_09` —el mismo
    chequeo que ya traía `load-survey-2026-09`—: los 11 permisos del delta, los
    9 grants de GTV, el recorte de `titulatec.survey.%` a la jefatura, el
    puesto de ventanilla y sus exactamente 2 filas puesto→rol, y el formulario
    'egresados' abierto. Aborta si algo no aterrizó. Antes este comando no
    comprobaba nada: en una base destino sin `head_tech_management` o sin el
    departamento `tech_management`, los `INSERT ... SELECT` de grants insertan
    0 filas y el comando salía en verde de todos modos — y el runbook de
    lanzamiento (`alembic upgrade head` → `init-titulatec` → asignar a la
    persona) nunca corre `load-survey-2026-09` por separado para atraparlo.

    Prerequisitos:
      - Tablas titulatec_* existen (alembic upgrade head).
      - 04 antes que 05: el mapeo puesto→rol necesita los puestos ya creados
        (incluido el nuevo `external_service_tech_management` de GTV).
    """
    click.echo("🎓 Inicializando app de TitulaTec...")
    click.echo()
    try:
        _run_sql_files(SEED_FILES)
    except Exception as e:
        click.echo(f"\n💥 Error durante init-titulatec: {e}")
        raise

    problemas = _verify_survey_2026_09()
    if problemas:
        click.echo()
        for p in problemas:
            click.echo(click.style(f"ERROR: {p}", fg="red"), err=True)
        raise click.Abort()

    click.echo()
    click.echo("🎉 init-titulatec completado.")


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

    2026-09-15: además del set original (8 permisos + grants a la jefatura y
    al operativo) verifica el reparto de la liberación de GTV (spec
    2026-09-15-titulatec-liberacion-gtv, sección 7):
      - el rol nuevo `titulatec_tech_management` con sus 9 permisos
        (3 `survey_review.*` + 4 `survey.*` + 2 `notifications.*`);
      - la jefatura de Servicios Escolares se quedó SIN ningún
        `titulatec.survey.%` (el DELETE de 10 se re-aplica en cada corrida)
        mientras conserva `enrollment_request.*` y `requirement.mark`;
      - el encargado operativo conserva `requirement.mark`;
      - el puesto de ventanilla (`external_service_tech_management`) existe y
        el mapeo puesto→rol de GTV tiene exactamente 2 filas (jefatura +
        ventanilla).
    """
    from sqlalchemy import text

    from itcj2.cli.core import _get_engine

    problemas: list[str] = []
    codigos = list(_SURVEY_2026_09_PERMS)
    # Para el chequeo de grants a GTV hace falta ademas los 2 de notificaciones,
    # que no son parte del delta (ya existian) pero si del reparto de GTV.
    codigos_grants = sorted(set(codigos) | set(_PERMISOS_NOTIFICACIONES))

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
                {"codes": codigos_grants},
            )
        }
        for code in _PERMISOS_JEFATURA_CONSERVA:
            if (_ROL_JEFATURA_ESCOLARES, code) not in concedidos:
                problemas.append(f"sin grant a la jefatura: {code}")
        if (_ROL_OPERATIVO_ESCOLARES, _PERM_MARCA_REQUISITO) not in concedidos:
            problemas.append(
                f"sin grant al encargado operativo: {_PERM_MARCA_REQUISITO}"
            )

        for code in _PERMISOS_GTV:
            if (_ROL_GTV, code) not in concedidos:
                problemas.append(f"sin grant a GTV ({_ROL_GTV}): {code}")

        # La jefatura NO debe conservar ningun titulatec.survey.% (paso a GTV,
        # spec D12). LIKE con punto literal tras "survey": no alcanza a
        # titulatec.survey_review.* (llevan '_' ahi, no '.').
        supervivientes = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT p.code FROM core_role_permissions rp "
                    "  JOIN core_roles r ON r.id = rp.role_id "
                    "  JOIN core_permissions p ON p.id = rp.perm_id "
                    "  JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                    " WHERE r.name = :rol AND p.code LIKE 'titulatec.survey.%'"
                ),
                {"rol": _ROL_JEFATURA_ESCOLARES},
            )
        ]
        if supervivientes:
            problemas.append(
                "la jefatura de Servicios Escolares todavía tiene "
                f"titulatec.survey.%: {supervivientes} "
                "(el DELETE de 10_insert_survey_role_permissions.sql no aterrizó)"
            )

        puesto_id = conn.execute(
            text("SELECT id FROM core_positions WHERE code = :code"),
            {"code": _PUESTO_GTV_VENTANILLA},
        ).scalar()
        if puesto_id is None:
            problemas.append(f"puesto ausente: {_PUESTO_GTV_VENTANILLA}")

        n_mapeo = conn.execute(
            text(
                "SELECT COUNT(*) FROM core_position_app_roles par "
                "  JOIN core_apps a ON a.id = par.app_id AND a.key = 'titulatec' "
                "  JOIN core_roles r ON r.id = par.role_id "
                " WHERE r.name = :rol"
            ),
            {"rol": _ROL_GTV},
        ).scalar()
        if n_mapeo != 2:
            problemas.append(
                f"mapeo puesto→rol de GTV ({_ROL_GTV}): se esperaban 2 filas, hay {n_mapeo}"
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

    Incluye desde 2026-09-15 los 3 permisos y el reparto de la liberación de
    la encuesta por Gestión Tecnológica y Vinculación (GTV): rol
    `titulatec_tech_management`, puesto `external_service_tech_management` y
    el recorte de `titulatec.survey.%` a la jefatura de Servicios Escolares
    (spec 2026-09-15-titulatec-liberacion-gtv).

    NO re-ejecuta el DML base de la app: `03_insert_role_permissions.sql` lleva
    tres DELETE que se re-aplican en cada corrida y revocarían permisos
    concedidos a mano. En producción eso es justo lo que no se quiere.

    Idempotente: los archivos llevan `ON CONFLICT DO NOTHING`, un
    `ON CONFLICT DO UPDATE` acotado, o —el 13— un `WHERE NOT EXISTS` que solo
    siembra donde hay cero.

    OJO CON EL 13: sembrar el checklist ARMA la guarda de la fase 2 en las
    convocatorias que hoy no lo tienen. A partir de esa corrida, liberar la fase
    2 exige palomear el checklist desde Citas o desde el expediente. Es el
    comportamiento buscado —la guarda es el encabezado de la campaña— pero no es
    invisible: avísale a Servicios Escolares antes de correrlo en producción.

    OJO CON EL 14: mueve a `graduate` a todo usuario con proceso (`graduate` en
    `itcj` y `titulatec`, fuera `student` en itcj/titulatec/agendatec, alias
    legado desde `student` o NULL). Exige el rol `graduate` CON sus permisos, que
    llegan por el 01 y el 03 del DML base (`init-titulatec`), y aborta sin mover a
    nadie si faltan. No toca permisos de rol. En producción hoy no hay procesos:
    ahí es un no-op.

    OJO CON EL 10 (2026-09-15): el DELETE que le quita `titulatec.survey.%` a
    la jefatura de Servicios Escolares se re-aplica en cada corrida de este
    comando —igual que los DELETE del 03 en `init-titulatec`—. Una concesión
    manual posterior de esos 4 códigos a la jefatura no sobrevive a una
    re-siembra: es la política declarada (spec D12), no un accidente.

    Al terminar VERIFICA contra la base que los 11 permisos existen; que GTV
    (`titulatec_tech_management`) tiene sus 9 (los 3 nuevos de liberación +
    los 4 `survey.*` + los 2 de notificaciones); que la jefatura de Servicios
    Escolares conserva sus otros 4 (`enrollment_request.*` +
    `requirement.mark`) y quedó SIN ningún `titulatec.survey.%`; que el
    encargado operativo conserva `requirement.mark`; que el puesto de
    ventanilla existe con sus 2 filas puesto→rol; y que queda exactamente un
    formulario `egresados` abierto. Sin esa verificación el comando saldría 0
    aunque no hubiera hecho nada: los `RAISE NOTICE` del SQL no se ven por
    ningún lado.
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
            "OK: 11 permisos (8 encuesta/solicitudes + 3 liberación GTV), sus "
            "grants (GTV 9, jefatura recortada a 4, operativo 1), el puesto de "
            "ventanilla con sus 2 filas puesto→rol y el formulario 'egresados' "
            "v1 verificados en la base.",
            fg="green",
        )
    )
