#!/usr/bin/env python3
"""
Comandos CLI de TitulaTec para itcj2.

Comandos:
    titulatec init-titulatec              Registra la app, roles, permisos, puestos y catálogos base.
    titulatec fix-missing-credentials     Repone la credencial inicial de alumnos sin password_hash.
    titulatec sii-ping                    Comprueba que el SII responde (backend configurado).
    titulatec sii-rules-validate [--dir]  Valida rules.toml + queries/*.sql del SII.
    titulatec sii-check <control>         Dry-run de las reglas del SII (NIP enmascarado).
    titulatec sii-sweep [--cohort ID]     Barrido manual del SII (consulta, reintenta, aprueba).
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
# lleva DELETE que revocan `cohort.*` a `titulatec_school_services` (las
# convocatorias son de la JEFATURA de Servicios Escolares, no del operativo) y
# TODO lo de titulatec a `student` (desde 2026-09-15 el alumno es `graduate`).
# Eso se aplica EN CADA CORRIDA: una concesión manual posterior de esos
# permisos se pierde al re-sembrar. Es la política declarada, no un accidente.
# (2026-09-21: el 03 también le daba `titulatec_titulaciones` la jefatura de
# la División solo-lectura, D6/D7; el usuario revirtió ese recorte — ver
# `_verify_titulacion` y el propio 03 para el detalle.)
SEED_FILES = [
    "00_insert_app.sql",                  # Registra la app en core_apps
    "01_insert_roles.sql",                # 7 roles nuevos: incl. 'graduate' (alumno) y titulatec_tech_management (GTV)
    "02_insert_permissions.sql",          # Permisos titulatec.*
    "03_insert_role_permissions.sql",     # Asignación rol→permisos (incl. 'graduate') + revocaciones
    "04_insert_vinculacion_positions.sql",# Puestos nuevos coord_vinculacion_* por depto
    # 2026-09-21 (spec 2026-09-21-titulatec-dpto-titulacion): Departamento de
    # Titulación (depto + puestos head_titulacion/aux_titulacion), colgado de
    # prof_studies_div. Debe correr DESPUÉS del 04 (no depende de él, pero
    # sigue la numeración) y ANTES del 05: el mapeo puesto→rol de abajo
    # necesita estos puestos ya creados.
    "04b_insert_titulacion_department.sql",
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
    "survey_2026_09/10_insert_survey_role_permissions.sql",# grants (GTV 9; jefatura recortada a enrollment_request+requirement.mark; operativo enrollment_request+requirement.mark, 2026-09-21)
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
    # --- Delta 2026-09-25: elegibilidad automática contra el SII -------------
    # Alta de la tarea periódica `itcj2.tasks.titulatec_tasks.sii_sweep`
    # (definición + `core_periodic_tasks`, cada 10 min): Celery Beat corre con
    # `DatabaseScheduler`, que SOLO lee la BD. Idempotente (ON CONFLICT). No
    # inserta permisos, así que va antes del 15 sin problema. Fuera del modo
    # `sii` la tarea no hace nada.
    "sii_2026_09/16_insert_sii_sweep_task.sql",
    # El 15 va SIEMPRE AL FINAL: concede DINÁMICAMENTE (SELECT sobre
    # core_permissions, sin listar códigos) todos los permisos de titulatec al
    # rol 'admin' y le da ese rol al usuario `username='admin'`. Tiene que
    # correr después de CUALQUIER archivo que inserte permisos (02, 07, 08 y
    # survey_2026_09/09) para que "todos" sea de verdad todos. Solo concede
    # (ON CONFLICT DO NOTHING): re-correrlo nunca revoca nada.
    "15_grant_admin_all_perms.sql",
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
# 2026-09-21 (spec 2026-09-21-titulatec-dpto-titulacion, "encargados de
# carrera en la bandeja de Solicitudes"): el operativo deja de tener SOLO
# `requirement.mark` y gana ADEMAS los mismos 3 `enrollment_request.*` que ya
# tenia la jefatura -- los encargados de carrera (puestos `se_officer_*`),
# la secretaria y el auxiliar del depto cuelgan de este rol. El alcance por
# carrera de esa bandeja YA estaba implementado en `requests_admin.py`
# (`officer_programs` + `_load_scoped_request`/`_program_in_scope`); este
# delta solo abre la puerta del permiso. `api.approve` tambien gatea el
# reenvio de liga (`requests_admin.py::resend`) -- intencional.
_PERMISOS_OPERATIVO_CONSERVA = (
    _PERM_MARCA_REQUISITO,
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
)


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
    `titulatec_school_services` (las convocatorias son de la JEFATURA de
    Servicios Escolares, no del operativo) y todo lo de titulatec a `student`
    (el alumno es `graduate` desde 2026-09-15).

    Aborta si falta cualquier archivo: sembrar a medias deja la app en 404.

    El 10 (dentro de `survey_2026_09/`) también revoca en cada corrida
    `titulatec.survey.%` a la jefatura de Servicios Escolares: esa bandeja
    pasó a Gestión Tecnológica y Vinculación (GTV, rol `titulatec_tech_management`)
    desde 2026-09-15 (spec 2026-09-15-titulatec-liberacion-gtv).

    Al terminar VERIFICA contra la base con `_verify_survey_2026_09` —el mismo
    chequeo que ya traía `load-survey-2026-09`—: los 11 permisos del delta, los
    9 grants de GTV, el recorte de `titulatec.survey.%` a la jefatura, el
    puesto de ventanilla y sus exactamente 2 filas puesto→rol, y el formulario
    'egresados' abierto. Y con `_verify_titulacion` (spec
    2026-09-21-titulatec-dpto-titulacion): el departamento `titulacion`
    colgado de `prof_studies_div`, sus 2 puestos, los 2 permisos de la bandeja
    de liberados, el grant completo del rol `titulatec_titulacion` (22), sus
    exactamente 2 filas puesto→rol (y 1 la del rol viejo, `head_prof_studies_div`),
    y que `titulatec_titulaciones` tenga el reparto PLENO (25) que el usuario
    pidió al revertir el recorte D6/D7 — dictamen, ceremony y cohort incluidos,
    no solo supervisión. Y con `_verify_computer_center` (spec
    2026-09-24-titulatec-accesos-centro-computo): el rol
    `titulatec_computer_center` con EXACTAMENTE sus 4 permisos de la bandeja
    de Accesos, el mapeo puesto→rol con `head_comp_center` y
    `secretary_comp_center` (contiene al menos, igual que el resto de mapeos
    de este comando) y `head_comp_center` con el rol `admin` en titulatec.
    Acumula los problemas de LOS TRES verifies antes de abortar: un error del
    primero no debe esconder uno de los otros.

    Aborta si algo no aterrizó. Antes este comando no comprobaba nada: en una
    base destino sin `head_tech_management` o sin el departamento
    `tech_management`, los `INSERT ... SELECT` de grants insertan 0 filas y el
    comando salía en verde de todos modos — y el runbook de lanzamiento
    (`alembic upgrade head` → `init-titulatec` → asignar a la persona) nunca
    corre `load-survey-2026-09` por separado para atraparlo.

    Prerequisitos:
      - Tablas titulatec_* existen (alembic upgrade head).
      - 04 antes que 04b antes que 05: el mapeo puesto→rol necesita los
        puestos ya creados (incluidos `external_service_tech_management` de
        GTV y `head_titulacion`/`aux_titulacion` del Departamento de
        Titulación).
    """
    click.echo("🎓 Inicializando app de TitulaTec...")
    click.echo()
    try:
        _run_sql_files(SEED_FILES)
    except Exception as e:
        click.echo(f"\n💥 Error durante init-titulatec: {e}")
        raise

    problemas = _verify_survey_2026_09() + _verify_titulacion() + _verify_computer_center()
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

    2026-09-21 (spec 2026-09-21-titulatec-dpto-titulacion, "encargados de
    carrera en la bandeja de Solicitudes"): el encargado operativo
    (`titulatec_school_services`) ADEMÁS recibe los 3 `enrollment_request.*`
    -mismo trío que ya tenía la jefatura- para que los encargados de carrera
    puedan resolver la bandeja de Solicitudes de SU carrera. El alcance real
    no lo da este permiso: lo acota `scope_service.officer_programs()` +
    `_load_scoped_request`/`_program_in_scope` en `pages/requests_admin.py`,
    que ya filtraba esa bandeja antes de este delta.
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
        for code in _PERMISOS_OPERATIVO_CONSERVA:
            if (_ROL_OPERATIVO_ESCOLARES, code) not in concedidos:
                problemas.append(f"sin grant al encargado operativo: {code}")

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


# ---------------------------------------------------------------------------
# Departamento de Titulación (2026-09-21, spec
# 2026-09-21-titulatec-dpto-titulacion): rol nuevo `titulatec_titulacion` con
# sus 2 puestos (`head_titulacion`, `aux_titulacion`), colgado del
# departamento `titulacion` (a su vez colgado de `prof_studies_div`).
#
# `titulatec_titulaciones` (la jefatura de la División) se recortó ese mismo
# día a solo-supervisión (D6/D7) y el usuario REVIRTIÓ el recorte poco
# después: quiere que la jefatura pueda hacer cualquier cosa en TitulaTec,
# aunque el trabajo diario de dictamen lo siga haciendo el Departamento de
# Titulación. Hoy `titulatec_titulaciones` tiene el reparto PLENO (25) y
# `titulatec_titulacion` se quedó igual (22) — ver spec secciones 3 y 6, y el
# comentario de cada bloque del ARRAY en `03_insert_role_permissions.sql`.
# ---------------------------------------------------------------------------
_DEPTO_TITULACION = "titulacion"
_DEPTO_PADRE_TITULACION = "prof_studies_div"
_PUESTO_HEAD_TITULACION = "head_titulacion"
_PUESTO_AUX_TITULACION = "aux_titulacion"
_ROL_TITULACION = "titulatec_titulacion"
_ROL_TITULACIONES_DIV = "titulatec_titulaciones"
_PUESTO_HEAD_PROF_STUDIES_DIV = "head_prof_studies_div"

_PERMISOS_HANDOFF = (
    "titulatec.handoff.page.list",
    "titulatec.handoff.api.export",
)

# Los 8 permisos de dictamen de las fases 3-8 (Formato B en adelante). Los
# tiene `titulatec_titulacion` (Departamento de Titulación, quien dictamina
# en el día a día) y, desde que el usuario revirtió el recorte D6/D7, también
# `titulatec_titulaciones` (la jefatura de la División — puede hacerlo aunque
# normalmente no lo haga).
_PERMISOS_DICTAMEN_FASES_3_8 = (
    "titulatec.process.api.approve_phase",
    "titulatec.process.api.reject_phase",
    "titulatec.process.api.cancel",
    "titulatec.process.api.hold",
    "titulatec.format_b.api.approve",
    "titulatec.format_b.api.reject",
    "titulatec.document.api.approve",
    "titulatec.document.api.reject",
)

# Los 2 de escritura de ceremony (fase 8). Mismo reparto que
# `_PERMISOS_DICTAMEN_FASES_3_8` de arriba: `titulatec_titulacion` los tiene
# desde que nació, y `titulatec_titulaciones` los recuperó al revertirse D6/D7.
_PERMISOS_CEREMONY_ESCRITURA = (
    "titulatec.ceremony.api.create",
    "titulatec.ceremony.api.update",
)

# Los 3 de Convocatorias (cohort). Decisión explícita del usuario al revertir
# D6/D7: la jefatura de la División (`titulatec_titulaciones`) también debe
# ver Convocatorias, no solo dictaminar. `titulatec_titulacion` (Departamento
# de Titulación) NO los tiene -- por eso ese rol se queda en 22 y este otro
# sube a 25: la diferencia es intencional, no hay que "igualarlos".
_PERMISOS_COHORT_TITULACIONES_DIV = (
    "titulatec.cohort.page.list",
    "titulatec.cohort.page.detail",
    "titulatec.cohort.api.read",
)

# Los 12 permisos de SUPERVISIÓN (lectura de todo + la bandeja de liberados)
# que comparten los dos roles de Titulación. Arreglo A3(c) (revisión final
# 2026-09-21): antes `_verify_titulacion()` solo comprobaba que
# `titulatec_titulacion` tuviera los 10 del delta (dictamen + ceremony), no
# los 22 completos del rol -- una siembra que dejara sin sembrar alguno de
# estos 12 (p.ej. si `02_insert_permissions.sql` se ejecutara truncado) pasaba
# en verde. Mismo motivo por el que el verify de `titulatec_titulaciones`
# (abajo) también exige el reparto completo, no un subconjunto.
_PERMISOS_SUPERVISION_TITULACIONES = (
    "titulatec.dashboard.titulaciones",
    "titulatec.process.page.list",
    "titulatec.process.page.detail",
    "titulatec.process.api.read.all",
    "titulatec.document.api.read.all",
    "titulatec.document.page.list",
    "titulatec.format_b.api.read.all",
    "titulatec.ceremony.page.list",
) + _PERMISOS_HANDOFF + (
    "titulatec.notifications.api.read.own",
    "titulatec.notifications.api.mark_read",
)

# Los 22 permisos completos de `titulatec_titulacion` (D5): los 12 de
# supervision (arriba) mas los 10 de dictamen (8 de fase 3-8 + 2 de ceremony).
_PERMISOS_ROL_TITULACION = (
    _PERMISOS_SUPERVISION_TITULACIONES
    + _PERMISOS_DICTAMEN_FASES_3_8
    + _PERMISOS_CEREMONY_ESCRITURA
)

# Los 25 permisos completos de `titulatec_titulaciones` (jefatura de la
# División) tras revertir el recorte D6/D7: los mismos 22 de arriba MÁS los 3
# de cohort. Queda con MÁS permisos que `titulatec_titulacion` -- es
# intencional (ver `_PERMISOS_COHORT_TITULACIONES_DIV`), no lo "corrijas".
_PERMISOS_ROL_TITULACIONES_DIV = (
    _PERMISOS_SUPERVISION_TITULACIONES
    + _PERMISOS_DICTAMEN_FASES_3_8
    + _PERMISOS_CEREMONY_ESCRITURA
    + _PERMISOS_COHORT_TITULACIONES_DIV
)


def _verify_titulacion() -> list[str]:
    """Comprueba que el Departamento de Titulación ATERRIZÓ Y que la jefatura de
    la División quedó con su reparto PLENO. Devuelve problemas.

    Mismo contrato que `_verify_survey_2026_09`: abre su propia conexión,
    arma sets contra la BD y devuelve strings de problema en vez de levantar.
    Sin esto un `INSERT ... SELECT` que inserta 0 filas (p.ej. porque `04b` no
    corrió antes que `05`, o `prof_studies_div` no existe en esta base) sale
    en verde igual que la app a medio sembrar del incidente de los seeders
    borrados. Ver spec 2026-09-21-titulatec-dpto-titulacion, sección 6.

    Fija el reparto COMPLETO de los dos roles de Titulación, no un subconjunto:
    `titulatec_titulacion` con sus 22 (`_PERMISOS_ROL_TITULACION`) y
    `titulatec_titulaciones` con sus 25 (`_PERMISOS_ROL_TITULACIONES_DIV`) —
    el usuario revirtió el recorte D6/D7 del mismo día: la jefatura de la
    División puede dictaminar, escribir ceremony y ver Convocatorias, aunque
    el trabajo diario lo siga haciendo el Departamento de Titulación.
    """
    from sqlalchemy import text

    from itcj2.cli.core import _get_engine

    problemas: list[str] = []

    with _get_engine().connect() as conn:
        # Departamento titulacion con su parent_id correcto.
        depto = conn.execute(
            text(
                "SELECT d.id, padre.code "
                "FROM core_departments d "
                "LEFT JOIN core_departments padre ON padre.id = d.parent_id "
                "WHERE d.code = :code"
            ),
            {"code": _DEPTO_TITULACION},
        ).first()
        if depto is None:
            problemas.append(f"departamento ausente: {_DEPTO_TITULACION}")
        elif depto[1] != _DEPTO_PADRE_TITULACION:
            problemas.append(
                f"departamento {_DEPTO_TITULACION}: parent_id apunta a "
                f"'{depto[1]}', se esperaba '{_DEPTO_PADRE_TITULACION}'"
            )

        # Los 2 puestos nuevos.
        puestos = {
            row[0]
            for row in conn.execute(
                text("SELECT code FROM core_positions WHERE code = ANY(:codes)"),
                {"codes": [_PUESTO_HEAD_TITULACION, _PUESTO_AUX_TITULACION]},
            )
        }
        for code in (_PUESTO_HEAD_TITULACION, _PUESTO_AUX_TITULACION):
            if code not in puestos:
                problemas.append(f"puesto ausente: {code}")

        # Los 2 permisos de la bandeja de liberados.
        permisos = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT p.code FROM core_permissions p "
                    "JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                    "WHERE p.code = ANY(:codes)"
                ),
                {"codes": list(_PERMISOS_HANDOFF)},
            )
        }
        for code in _PERMISOS_HANDOFF:
            if code not in permisos:
                problemas.append(f"permiso ausente: {code}")

        # Mapeo puesto→rol: el rol nuevo debe INCLUIR head+aux, y el viejo
        # debe INCLUIR head_prof_studies_div. Arreglo A7 (revision final
        # 2026-09-21): antes esto exigia una CUENTA EXACTA (2 y 1 filas). Si
        # un admin mapeara mas adelante, con toda intencion, un tercer puesto
        # al rol nuevo (o a la supervision de la Division) desde el
        # organigrama del core, `init-titulatec` abortaba en rojo con la
        # siembra perfectamente sana -- "contiene al menos estos puestos" no
        # se rompe con una decision de organigrama que nada tiene que ver con
        # el DML.
        puestos_de = {}
        for rol in (_ROL_TITULACION, _ROL_TITULACIONES_DIV):
            puestos_de[rol] = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT pos.code FROM core_position_app_roles par "
                        "  JOIN core_apps a ON a.id = par.app_id AND a.key = 'titulatec' "
                        "  JOIN core_roles r ON r.id = par.role_id "
                        "  JOIN core_positions pos ON pos.id = par.position_id "
                        " WHERE r.name = :rol"
                    ),
                    {"rol": rol},
                )
            }

        faltan_nuevo = {_PUESTO_HEAD_TITULACION, _PUESTO_AUX_TITULACION} - puestos_de[_ROL_TITULACION]
        if faltan_nuevo:
            problemas.append(
                f"mapeo puesto→rol de {_ROL_TITULACION}: faltan {sorted(faltan_nuevo)} "
                f"(hay {sorted(puestos_de[_ROL_TITULACION])})"
            )

        if _PUESTO_HEAD_PROF_STUDIES_DIV not in puestos_de[_ROL_TITULACIONES_DIV]:
            problemas.append(
                f"mapeo puesto→rol de {_ROL_TITULACIONES_DIV}: falta "
                f"{_PUESTO_HEAD_PROF_STUDIES_DIV} "
                f"(hay {sorted(puestos_de[_ROL_TITULACIONES_DIV])})"
            )

        # El rol nuevo debe tener el dictamen + la bandeja de liberados.
        concedidos_nuevo = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT p.code FROM core_role_permissions rp "
                    "  JOIN core_roles r ON r.id = rp.role_id "
                    "  JOIN core_permissions p ON p.id = rp.perm_id "
                    "  JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                    " WHERE r.name = :rol"
                ),
                {"rol": _ROL_TITULACION},
            )
        }
        # Arreglo A3(c): los 22 completos, no solo los 10 del delta de dictamen.
        for code in _PERMISOS_ROL_TITULACION:
            if code not in concedidos_nuevo:
                problemas.append(f"sin grant a {_ROL_TITULACION}: {code}")

        # titulatec_titulaciones (jefatura de la División) debe tener su
        # reparto PLENO: 25 -- los 12 de supervisión, los 8 de dictamen de
        # fases 3-8, los 2 de escritura de ceremony y los 3 de cohort. El
        # usuario revirtió el recorte D6/D7 del 2026-09-21: la jefatura puede
        # hacer cualquier cosa en TitulaTec aunque el trabajo diario de
        # dictamen lo siga haciendo el Departamento de Titulación (rol de
        # arriba). Positivo, no negativo: antes de este cambio este verify
        # exigía que el rol NO tuviera dictamen/ceremony; el usuario invirtió
        # esa decisión, así que el verify se invierte con ella.
        concedidos_div = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT p.code FROM core_role_permissions rp "
                    "  JOIN core_roles r ON r.id = rp.role_id "
                    "  JOIN core_permissions p ON p.id = rp.perm_id "
                    "  JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                    " WHERE r.name = :rol"
                ),
                {"rol": _ROL_TITULACIONES_DIV},
            )
        }
        for code in _PERMISOS_ROL_TITULACIONES_DIV:
            if code not in concedidos_div:
                problemas.append(f"sin grant a {_ROL_TITULACIONES_DIV}: {code}")

    return problemas


# ---------------------------------------------------------------------------
# Centro de Cómputo (2026-09-24, spec 2026-09-24-titulatec-accesos-centro-
# computo): NIP en dos pasos. Servicios Escolares aprueba y, si el
# solicitante no tiene cuenta, la solicitud pasa a `awaiting_access`; Centro
# de Cómputo (CC) es quien le da el NIP desde la bandeja nueva «Accesos».
# ---------------------------------------------------------------------------
_ROL_COMPUTER_CENTER = "titulatec_computer_center"
_ROL_ADMIN = "admin"
_PUESTO_HEAD_COMP_CENTER = "head_comp_center"
_PUESTO_SECRETARY_COMP_CENTER = "secretary_comp_center"

_PERMISOS_ACCESOS_COMPUTO = (
    "titulatec.enrollment_access.page.list",
    "titulatec.enrollment_access.api.grant",
    "titulatec.enrollment_access.api.return",
    "titulatec.enrollment_access.api.reject",
)


def _verify_computer_center() -> list[str]:
    """Comprueba que el rol de Centro de Cómputo ATERRIZÓ. Devuelve problemas.

    Mismo contrato que `_verify_survey_2026_09`/`_verify_titulacion`: abre su
    propia conexión, arma sets contra la BD y devuelve strings de problema en
    vez de levantar. Sin esto un `INSERT ... SELECT` que inserta 0 filas
    (p.ej. porque `head_comp_center`/`secretary_comp_center` no existen en
    esta base) sale en verde igual que la app a medio sembrar del incidente de
    los seeders borrados.

    Tres chequeos (spec sección 7, D1/D2):
      - el rol `titulatec_computer_center` concede EXACTAMENTE los 4 códigos
        de la bandeja de Accesos, ni uno más ni uno menos;
      - el mapeo puesto→rol INCLUYE `head_comp_center` y
        `secretary_comp_center` -- semántica "contiene al menos" (arreglo A7,
        igual que `_verify_titulacion`): no exige conteo exacto de filas, así
        que mapear a mano un tercer puesto más adelante no rompe esto;
      - `head_comp_center` tiene ADEMÁS el rol `admin` en titulatec (D2).

    Si algún puesto no existe en la base (0 filas), el mensaje lo dice
    explícitamente en vez de reportar solo "falta el mapeo": la causa más
    probable es que el organigrama de Centro de Cómputo no esté sembrado
    todavía en ese ambiente.
    """
    from sqlalchemy import text

    from itcj2.cli.core import _get_engine

    problemas: list[str] = []

    with _get_engine().connect() as conn:
        puestos = {
            row[0]
            for row in conn.execute(
                text("SELECT code FROM core_positions WHERE code = ANY(:codes)"),
                {"codes": [_PUESTO_HEAD_COMP_CENTER, _PUESTO_SECRETARY_COMP_CENTER]},
            )
        }
        for code in (_PUESTO_HEAD_COMP_CENTER, _PUESTO_SECRETARY_COMP_CENTER):
            if code not in puestos:
                problemas.append(
                    f"puesto ausente: {code} (el organigrama de Centro de "
                    "Cómputo no está sembrado en esta base)"
                )

        concedidos = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT p.code FROM core_role_permissions rp "
                    "  JOIN core_roles r ON r.id = rp.role_id "
                    "  JOIN core_permissions p ON p.id = rp.perm_id "
                    "  JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                    " WHERE r.name = :rol"
                ),
                {"rol": _ROL_COMPUTER_CENTER},
            )
        }
        if concedidos != set(_PERMISOS_ACCESOS_COMPUTO):
            faltan = set(_PERMISOS_ACCESOS_COMPUTO) - concedidos
            sobran = concedidos - set(_PERMISOS_ACCESOS_COMPUTO)
            problemas.append(
                f"{_ROL_COMPUTER_CENTER} no tiene exactamente los 4 permisos "
                f"de Accesos (faltan {sorted(faltan)}, sobran {sorted(sobran)})"
            )

        # Mapeo puesto→rol para los dos roles que nos importan aquí, con la
        # MISMA consulta parametrizada (patrón de `_verify_titulacion`:
        # ~639-653) en vez de repetirla una vez por rol.
        puestos_de_rol = {}
        for rol in (_ROL_COMPUTER_CENTER, _ROL_ADMIN):
            puestos_de_rol[rol] = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT pos.code FROM core_position_app_roles par "
                        "  JOIN core_apps a ON a.id = par.app_id AND a.key = 'titulatec' "
                        "  JOIN core_roles r ON r.id = par.role_id "
                        "  JOIN core_positions pos ON pos.id = par.position_id "
                        " WHERE r.name = :rol"
                    ),
                    {"rol": rol},
                )
            }

        faltan_mapeo = (
            {_PUESTO_HEAD_COMP_CENTER, _PUESTO_SECRETARY_COMP_CENTER}
            - puestos_de_rol[_ROL_COMPUTER_CENTER]
        )
        if faltan_mapeo:
            problemas.append(
                f"mapeo puesto→rol de {_ROL_COMPUTER_CENTER}: faltan "
                f"{sorted(faltan_mapeo)} (hay {sorted(puestos_de_rol[_ROL_COMPUTER_CENTER])})"
            )

        if _PUESTO_HEAD_COMP_CENTER not in puestos_de_rol[_ROL_ADMIN]:
            problemas.append(
                f"mapeo puesto→rol de {_ROL_ADMIN}: falta {_PUESTO_HEAD_COMP_CENTER} "
                f"(hay {sorted(puestos_de_rol[_ROL_ADMIN])})"
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


# ---------------------------------------------------------------------------
# Elegibilidad automática contra el SII (spec 2026-09-25 §3.4 y §7). Orden de
# despliegue: sii-ping → sii-rules-validate → sii-check <control de prueba>.
# Ninguno escribe en la BD. El NIP del SII jamás se imprime (`****`).
# ---------------------------------------------------------------------------
def _sii_fail(msg: str) -> None:
    click.echo(click.style(f"ERROR: {msg}", fg="red"))
    raise SystemExit(1)


@titulatec_cli.command("sii-ping")
def sii_ping_command():
    """Comprueba que el SII responde con el backend configurado."""
    import time

    from itcj2.apps.titulatec.services.sii.client import SiiConfig, get_sii_client
    from itcj2.apps.titulatec.services.sii.errors import SiiError

    backend = SiiConfig.backend()
    click.echo(f"Backend: {backend}")
    t0 = time.monotonic()
    try:
        with get_sii_client() as sii:
            sii.ping()
    except SiiError as exc:
        _sii_fail(str(exc))
    ms = int((time.monotonic() - t0) * 1000)
    click.echo(click.style(f"OK: el SII responde ({ms} ms).", fg="green"))


@titulatec_cli.command("sii-rules-validate")
@click.option("--dir", "rules_dir", type=click.Path(file_okay=False, path_type=Path),
              default=None,
              help="Carpeta a validar (default: TITULATEC_SII_RULES_DIR). Útil para "
                   "revisar reglas nuevas ANTES de copiarlas a su lugar.")
def sii_rules_validate_command(rules_dir):
    """Valida rules.toml + queries/*.sql sin consultar al SII."""
    from itcj2.apps.titulatec.services.sii.client import SiiConfig
    from itcj2.apps.titulatec.services.sii.errors import SiiRulesError
    from itcj2.apps.titulatec.services.sii.rules import RuleSet

    rules_dir = rules_dir or SiiConfig.rules_dir()
    click.echo(f"Reglas: {rules_dir}")
    try:
        rs = RuleSet.load(rules_dir)
    except SiiRulesError as exc:
        _sii_fail(str(exc))
    click.echo(f"Versión: {rs.version or '(sin versión)'} · {len(rs.queries)} consultas · "
               f"{len(rs.rules)} reglas · credencial (NIP): "
               f"{'sí' if rs.has_credential else 'no'}")
    errors = rs.validate()
    if errors:
        for e in errors:
            click.echo(click.style(f"  - {e}", fg="red"))
        _sii_fail(f"{len(errors)} error(es) en las reglas.")
    click.echo(click.style("OK: reglas válidas. (Las columnas de los mensajes se "
                           "verifican al ejecutar: usa sii-check.)", fg="green"))


_SII_STATUS_LABEL = {"apt": "APTA", "not_apt": "NO APTA", "error": "ERROR"}


def _sii_cohort_outcome(cohort_id: int, verdict_status: str) -> None:
    """Imprime qué pasaría con esta convocatoria. Solo lectura (rollback)."""
    from itcj2.apps.titulatec.models import Cohort
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        cohort = db.get(Cohort, cohort_id)
        if cohort is None:
            _sii_fail(f"No existe la convocatoria {cohort_id}.")
        # `sii_auto_approve` llega con la migración tt20260925a (server_default
        # TRUE); antes de ella la convocatoria se comporta como encendida.
        auto = bool(getattr(cohort, "sii_auto_approve", True))
        click.echo(f"Convocatoria: {cohort.name} (id {cohort.id}, {cohort.status}) · "
                   f"aprobación automática: {'encendida' if auto else 'apagada'}")
        if verdict_status == "apt" and auto and cohort.status == "open":
            click.echo("  → se aprobaría automáticamente (sujeto a la ventana de veto "
                       "TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS).")
        else:
            why = ("no es apta" if verdict_status == "not_apt"
                   else "la consulta falló" if verdict_status == "error"
                   else "la convocatoria no está abierta" if cohort.status != "open"
                   else "la aprobación automática está apagada")
            click.echo(f"  → quedaría «Por revisar» de Servicios Escolares ({why}).")
    finally:
        db.rollback()
        db.close()


@titulatec_cli.command("sii-check")
@click.argument("control_number")
@click.option("--cohort", "cohort_id", type=int, default=None,
              help="Muestra además qué pasaría en esa convocatoria (solo lectura).")
def sii_check_command(control_number, cohort_id):
    """Dry-run: evalúa las reglas del SII para un número de control.

    Imprime el resultado por regla, los hechos, la identidad y si el SII
    devuelve NIP (siempre enmascarado). No escribe nada.
    """
    import time

    from itcj2.apps.titulatec.services.sii.client import SiiConfig, get_sii_client
    from itcj2.apps.titulatec.services.sii.errors import SiiError, SiiRulesError
    from itcj2.apps.titulatec.services.sii.rules import RuleSet

    control = control_number.strip().upper()
    rules_dir = SiiConfig.rules_dir()
    try:
        rs = RuleSet.load(rules_dir)
        sii = get_sii_client()
    except SiiError as exc:
        _sii_fail(str(exc))

    t0 = time.monotonic()
    credential_failed = False  # un nip.sql roto NO pasa en verde (runbook §7)
    with sii:
        verdict = rs.evaluate(sii, control)
        if not rs.has_credential:
            nip_line = "sin NIP (las reglas no declaran [credential])"
        elif verdict.status == "error":
            nip_line = "no consultado (la evaluación falló)"
        else:
            # El mensaje de estas excepciones ya viene sin el NIP: la consulta
            # va en modo sensible y el motor solo nombra columnas.
            try:
                secret = rs.fetch_credential(sii, control)
            except SiiRulesError as exc:
                credential_failed = True
                nip_line = f"error en las reglas ({exc})"
            except SiiError as exc:
                credential_failed = True
                nip_line = f"no se pudo consultar ({exc})"
            else:
                nip_line = "**** (el SII lo devuelve)" if secret else "sin NIP (el SII no lo devuelve)"
                del secret
    ms = int((time.monotonic() - t0) * 1000)

    color = {"apt": "green", "not_apt": "yellow"}.get(verdict.status, "red")
    click.echo(f"Número de control: {control} · reglas {verdict.rules_version or '?'} "
               f"· backend {SiiConfig.backend()}")
    click.echo(click.style(f"Veredicto: {_SII_STATUS_LABEL.get(verdict.status, verdict.status)}",
                           fg=color, bold=True))
    if verdict.error:
        click.echo(click.style(f"  {verdict.error}", fg="red"))
    if verdict.results:
        width = max(len(r.rule) for r in verdict.results)
        for r in verdict.results:
            mark = click.style("OK   ", fg="green") if r.ok else click.style("FALLA", fg="red")
            click.echo(f"  {mark} {r.rule.ljust(width)}  {r.message}")
    for title, data in (("Hechos", verdict.facts), ("Identidad", verdict.identity)):
        click.echo(f"{title}:" + ("" if data else " (ninguno)"))
        for k, v in data.items():
            click.echo(f"  {k} = {v}")
    for w in verdict.warnings:
        click.echo(click.style(f"Advertencia: {w}", fg="yellow"))
    click.echo(f"NIP: {nip_line}")
    click.echo(f"Duración: {ms} ms")

    if cohort_id is not None:
        _sii_cohort_outcome(cohort_id, verdict.status)
    if verdict.status == "error" or credential_failed:
        raise SystemExit(1)


@titulatec_cli.command("sii-sweep")
@click.option("--cohort", "cohort_id", type=int, default=None,
              help="Solo las solicitudes de esa convocatoria.")
def sii_sweep_command(cohort_id):
    """Barrido manual del SII (lo mismo que la tarea periódica `sii_sweep`).

    Consulta las solicitudes por revisar que no tienen consulta, reintenta las
    fallidas y aprueba las aptas con la ventana de veto vencida. Solo en el
    modo `sii`. ESCRIBE en la BD (consultas y aprobaciones) y manda los
    correos de las aprobadas; imprime solo los conteos.
    """
    from itcj2.apps.titulatec.services.eligibility_service import EligibilityService
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    from itcj2.database import SessionLocal

    mode = EnrollmentRequestService.reviewer_mode()
    if mode != "sii":
        click.echo(click.style(
            f"El modo de revisión es '{mode}', no 'sii' (TITULATEC_ENROLLMENT_REVIEWER): "
            "el barrido no hace nada.", fg="yellow"))
        return
    db = SessionLocal()
    try:
        out = EligibilityService.sweep(db, cohort_id=cohort_id)
    finally:
        db.close()
    click.echo(f"Consultadas: {out['checked']} · reintentadas: {out['retried']} · "
               f"aprobadas: {out['approved']}")
