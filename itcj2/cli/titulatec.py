#!/usr/bin/env python3
"""
Comandos CLI de TitulaTec para itcj2.

Comandos:
    titulatec init-titulatec              Registra la app, roles, permisos, puestos y catálogos base.
    titulatec fix-missing-credentials     Repone la credencial inicial de alumnos sin password_hash.
    titulatec rename-documents [--dry-run] Renombra los documentos en disco a {control}_{TIPO}.{ext}.
    titulatec sii-ping                    Comprueba que el SII responde (backend configurado).
    titulatec sii-rules-validate [--dir]  Valida rules.toml + queries/*.sql del SII.
    titulatec sii-check <control>         Dry-run de las reglas del SII (NIP enmascarado).
    titulatec sii-sweep [--cohort ID]     Barrido manual del SII (consulta y reintenta).
    titulatec init-email-tasks [--dry-run] Da de alta las periódicas de correo (envío + recordatorios).
    titulatec init-posgrado [--dry-run] [--allow-insert]  Clasifica las 4 carreras de posgrado y sus 4 documentos de fase 1.
    titulatec init-biblioteca-caja [--dry-run]  Paso 1: puestos/roles/permisos de Biblioteca-Caja + descripción de recordatorios (no enciende el candado).
    titulatec activar-biblioteca-caja [--dry-run] [--force]  Paso 2: pre-chequeos + requisito automático + re-backfill + promoción D17 + folios de previas y legado.
    titulatec emitir-folios-previos [--dry-run]  Folia las previas y el legado que quedaron sin folio vigente (idempotente).
    titulatec import-prior-clearances --tipo encuesta|biblioteca ARCHIVO.csv [opts]  Constancias previas (D9).
    titulatec import-survey-xlsx ARCHIVO.xlsx [--hoja Sheet1] [--dry-run]  Encuesta de egresados desde Forms.
"""
import os
from pathlib import Path, PurePosixPath

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
    # Alta de la tarea periódica `titulatec.sii_sweep`
    # (definición + `core_periodic_tasks`, cada 10 min): Celery Beat corre con
    # `DatabaseScheduler`, que SOLO lee la BD. Idempotente (ON CONFLICT). No
    # inserta permisos, así que va antes del 15 sin problema. Fuera del modo
    # `sii` la tarea no hace nada.
    "sii_2026_09/16_insert_sii_sweep_task.sql",
    # --- Delta 2026-09-28: correos del proceso al egresado --------------------
    # Alta de las tareas periódicas `titulatec.email_dispatch` (cada 5 minutos)
    # y `titulatec.email_reminders` (diaria 9:00): Celery Beat corre con
    # `DatabaseScheduler`, que SOLO lee `core_periodic_tasks` — sin esta fila
    # ninguna de las dos se programa, aunque el worker ya las tenga
    # registradas (`TASK_DEFINITIONS` en `itcj2/tasks/titulatec_tasks.py`).
    # Idempotente (ON CONFLICT, mismo patrón que el 16 de arriba: no pisa
    # `is_active` ni `cron_expression` al re-sembrar). No inserta permisos,
    # así que va antes del 15 sin problema. También corre SOLA con
    # `titulatec init-email-tasks` (spec 2026-09-28 §6 C5): en producción
    # `init-titulatec` completo NUNCA se re-ejecuta, así que ese comando es el
    # único camino de despliegue para este archivo.
    "mail_2026_09/17_insert_email_tasks.sql",
    # --- Delta 2026-10: egresados de posgrado (perfil de titulación) --------
    # Clasifica las 4 carreras de posgrado (2 maestrías + la de industrial +
    # el doctorado) por NOMBRE NORMALIZADO -- nunca por id ni "las últimas 4"
    # (spec 2026-09-30-titulatec-posgrado-design.md, D2) -- y da de alta los
    # 4 tipos de documento extra de fase 1 (`DocumentService.
    # POSGRADO_EXTRA_DOCS`). El 18 aborta SIN escribir ante cualquier
    # ambigüedad o carrera de posgrado a medias: nunca duplica (invariante 7).
    # No inserta permisos, así que va antes del 15 sin problema. También
    # corre SOLA con `titulatec init-posgrado` (D10, mismo patrón que el 17 de
    # arriba): en producción las 4 carreras YA EXISTEN (tecleadas a mano) e
    # `init-titulatec` completo NUNCA se re-ejecuta allí, así que ese comando
    # es el único camino de despliegue para este delta.
    "posgrado_2026_10/18_classify_posgrado_programs.sql",
    "posgrado_2026_10/19_insert_posgrado_doc_types.sql",
    # --- Delta 2026-10-01: no adeudo de biblioteca (Biblioteca -> Caja) -----
    # Spec 2026-10-01-titulatec-biblioteca-caja-design.md §4.6/§6: puestos
    # library_clearance_info_center/cashier_financial_resources (20), roles
    # titulatec_library/titulatec_cashier + los 10 permisos nuevos y TODAS sus
    # concesiones, incluido admin EXPLICITO (21), y el requisito automatico de
    # `library_clearance` sobre las convocatorias YA sembradas (22). No
    # inserta nada que el 03 pudiera revocar, asi que va antes del 15 sin
    # problema. En una instalacion desde cero los tres van juntos (no hay
    # procesos que proteger). En produccion `init-titulatec` completo NUNCA se
    # re-ejecuta: ahi corren en DOS pasos (Ruling R19) -- `titulatec
    # init-biblioteca-caja` (20, 21 y 23, no enciende nada) y, ya con
    # ocupantes y donaciones, `titulatec activar-biblioteca-caja` (22 +
    # re-backfill + promocion D17).
    "biblioteca_2026_10/20_insert_library_cashier_positions.sql",
    "biblioteca_2026_10/21_insert_library_cashier_roles_perms.sql",
    "biblioteca_2026_10/22_library_requirement_auto.sql",
    # El 23 (m33, spec 2026-10-02 §6) pone al dia la descripcion de
    # `titulatec.email_reminders` (ahora menciona el pago pendiente en Caja)
    # en una base YA sembrada. Aqui, despues del 17, no cambia nada (el 17 ya
    # siembra ese texto); va para que el delta siga completo en `SEED_FILES`.
    "biblioteca_2026_10/23_update_email_reminders_description.sql",
    # El 15 va SIEMPRE AL FINAL: concede DINÁMICAMENTE (SELECT sobre
    # core_permissions, sin listar códigos) todos los permisos de titulatec al
    # rol 'admin' y le da ese rol al usuario `username='admin'`. Tiene que
    # correr después de CUALQUIER archivo que inserte permisos (02, 07, 08,
    # survey_2026_09/09 y biblioteca_2026_10/21) para que "todos" sea de
    # verdad todos. Solo concede (ON CONFLICT DO NOTHING): re-correrlo nunca
    # revoca nada.
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


# Filas por commit en `rename-documents`. Un lote chico acota lo que hay que
# deshacer en disco si la BD falla a medio camino.
_RENAME_BATCH = 200


def _rename_no_replace(src: Path, dst: Path) -> None:
    """Renombra ``src`` a ``dst`` SIN pisar nunca un ``dst`` existente.

    ``Path.rename`` sobrescribe en POSIX: entre revisar que el destino está
    libre y renombrar cabe una subida del alumno, que se perdería (revisión
    2026-09-28, m4). ``os.link`` es atómico y falla con ``FileExistsError`` si
    el destino ya existe; después se borra el nombre viejo. Si el sistema de
    archivos no admite enlaces duros, se revisa y se renombra (en Windows
    ``os.rename`` tampoco pisa; en POSIX queda la ventana mínima).
    """
    try:
        os.link(src, dst)
    except FileExistsError:
        raise
    except OSError:
        if dst.exists():
            raise FileExistsError(str(dst)) from None
        os.rename(src, dst)
        return
    try:
        os.unlink(src)
    except BaseException:
        os.unlink(dst)          # sin dos nombres para el mismo archivo
        raise


@titulatec_cli.command("rename-documents")
@click.option("--dry-run", is_flag=True,
              help="Solo reporta lo que haría; no toca ni el disco ni la BD.")
def rename_documents_command(dry_run):
    """Renombra los documentos en disco a `{control}_{TIPO}.{ext}` (2026-09-28).

    Hasta el 2026-09-28 cada documento se guardaba como `{type_code}.{ext}`
    (`curp.pdf`); desde entonces `utils/storage.py` los guarda como
    `{control}_{ETIQUETA}.{ext}` (`99000401_CURP.pdf`). Este comando pone al
    día los que ya estaban, en la MISMA carpeta. Por cada fila `Document`:

    \b
    - el nombre ya es el esperado y el archivo
      existe en disco                         -> ya_bien
    - el viejo existe y el destino no         -> se renombra y se actualiza
                                                 `file_path` -> renombrados
    - el destino ya existe                    -> conflictos (no toca nada)
    - el archivo de la fila no existe (con
      nombre viejo o ya con el nuevo)         -> faltantes (no toca la fila)
    - control no alfanumérico o ruta fuera de TITULATEC_UPLOAD_PATH
                                              -> omitidos (no toca nada)

    Idempotente: una segunda corrida da todo `ya_bien`. El renombre nunca pisa
    un destino, ni uno que aparezca a última hora (cuenta como conflicto).
    Commits por lotes; si algo falla — también Ctrl-C, o el propio rollback —
    deshace en disco los renombres del lote sin commitear y sale con 1.
    Imprime conteos e ids, nunca contenido.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import Document, TitulationProcess
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.utils import storage
    from itcj2.core.utils.safe_paths import UnsafePath

    counts = {"ya_bien": 0, "renombrados": 0, "conflictos": 0, "faltantes": 0, "omitidos": 0}
    ids: dict[str, list[int]] = {"conflictos": [], "faltantes": [], "omitidos": []}
    pending: list[tuple[Path, Path]] = []      # (nuevo, viejo) sin commitear
    controls: dict[int, str | None] = {}

    def _control_of(db, process_id):
        if process_id not in controls:
            proc = db.get(TitulationProcess, process_id)
            controls[process_id] = (DocumentService._storage_keys(db, proc)[1]
                                    if proc is not None else None)
        return controls[process_id]

    db = SessionLocal()
    try:
        docs = db.query(Document).order_by(Document.id).all()
        for doc in docs:
            control = _control_of(db, doc.process_id)
            current = PurePosixPath(doc.file_path or "")
            try:
                if control is None or not current.name:
                    raise storage.StorageError("sin proceso o sin archivo")
                ext = storage._ext_of(current.name) or "pdf"
                expected = storage.document_filename(control, doc.type_code, ext)
                new_rel = (current.parent / expected).as_posix()
                old_abs = storage.safe_abs_path(doc.file_path)
                new_abs = storage.safe_abs_path(new_rel)
            except (storage.StorageError, UnsafePath):
                counts["omitidos"] += 1
                ids["omitidos"].append(doc.id)
                continue

            # `ya_bien` exige el archivo en disco (ronda 2): un lote deshecho
            # tras un commit «en duda» deja filas con el nombre nuevo y sin
            # archivo, que caen abajo como faltantes (aquí old_abs == new_abs).
            if current.name == expected and old_abs.exists():
                counts["ya_bien"] += 1
            elif not old_abs.exists():
                key = "conflictos" if new_abs.exists() else "faltantes"
                counts[key] += 1
                ids[key].append(doc.id)
            elif dry_run:
                if new_abs.exists():
                    counts["conflictos"] += 1
                    ids["conflictos"].append(doc.id)
                else:
                    counts["renombrados"] += 1
            else:
                try:
                    _rename_no_replace(old_abs, new_abs)
                except FileExistsError:
                    counts["conflictos"] += 1
                    ids["conflictos"].append(doc.id)
                    continue
                counts["renombrados"] += 1
                pending.append((new_abs, old_abs))
                doc.file_path = new_rel
                if len(pending) >= _RENAME_BATCH:
                    db.commit()
                    pending.clear()

        if not dry_run:
            db.commit()
            pending.clear()
    except BaseException as exc:
        # BaseException y no Exception: un Ctrl-C (KeyboardInterrupt) a media
        # corrida dejaba los renombres del lote en disco con la BD apuntando al
        # nombre viejo, y la corrida siguiente los veía como conflictos.
        bd = "BD revertida al último lote"
        try:
            db.rollback()
        except Exception as rb_exc:
            bd = f"el rollback también falló ({type(rb_exc).__name__}: {rb_exc})"
        deshechos = 0
        for new_abs, old_abs in reversed(pending):
            try:
                _rename_no_replace(new_abs, old_abs)
                deshechos += 1
            except OSError as undo_exc:
                click.echo(click.style(
                    f"ERROR: no se pudo deshacer {new_abs.name} -> {old_abs.name}: {undo_exc}",
                    fg="red"), err=True)
        click.echo(click.style(
            f"ERROR: rename-documents falló ({type(exc).__name__}: {exc}). "
            f"{bd}; {deshechos} renombre(s) deshecho(s) en disco.",
            fg="red"), err=True)
        raise SystemExit(1)
    finally:
        try:
            db.close()
        except Exception as close_exc:
            click.echo(f"AVISO: no se pudo cerrar la sesión: {close_exc}", err=True)

    total = sum(counts.values())
    if dry_run:
        click.echo(f"[dry-run] {total} documento(s) revisado(s); no se escribió nada "
                   "(ni disco ni BD).")
    else:
        click.echo(f"{total} documento(s) revisado(s).")
    for key in ("ya_bien", "renombrados", "conflictos", "faltantes", "omitidos"):
        line = f"  {key}: {counts[key]}"
        if key == "renombrados" and dry_run:
            line += " (se renombrarían)"
        if ids.get(key):
            line += " · ids: " + ", ".join(str(i) for i in ids[key])
        click.echo(line)


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
# Egresados de posgrado / perfil de titulación (2026-10, spec
# 2026-09-30-titulatec-posgrado-design.md): las 4 carreras de posgrado del
# ITCJ (2 maestrías + la de industrial + el doctorado) YA EXISTEN en
# producción -- tecleadas a mano, ortografía desconocida -- pero NO en dev/CI.
# `18_classify_posgrado_programs.sql` las ubica por NOMBRE NORMALIZADO (D2:
# nunca por id ni "las últimas 4", que en dev/CI marcaría licenciatura) y les
# marca `core_programs.level`; aborta SIN escribir ante cualquier ambigüedad
# o carrera de posgrado a medias (invariante 7). El 19 da de alta los 4
# tipos de documento extra de fase 1 (`DocumentService.POSGRADO_EXTRA_DOCS`).
# Mismo patrón D10 que el correo
# (`init-email-tasks`): producción ya corrió `init-titulatec` y ese comando
# nunca se re-ejecuta allí, así que este comando es el único camino de
# despliegue para este delta -- además de sumarse a `SEED_FILES` arriba.
# ---------------------------------------------------------------------------
_DML_POSGRADO_2026_10_DIR = "posgrado_2026_10"
# Debe listar TODOS los .sql del directorio (mismo contrato que
# `_DML_MAIL_2026_09_FILES`/`_DML_SURVEY_2026_09_FILES`): lo fija
# `test_directorio_lista_exactamente_los_dos_archivos`
# (tests/fastapi/titulatec/test_cli_posgrado.py). Un archivo que se cae de
# aquí no lo corre nadie y nada se pone rojo.
_DML_POSGRADO_2026_10_FILES = [
    "18_classify_posgrado_programs.sql",
    "19_insert_posgrado_doc_types.sql",
]

# Normalización y patrones EXACTOS de `18_classify_posgrado_programs.sql`.
# FUENTE ÚNICA para `_verify_posgrado` Y `_precheck_posgrado` (revisión de la
# Tarea 7, ronda 1): antes cada función traía su propia copia de los 4
# patrones -- un cambio en el 18 que no se replicara en AMBAS las
# desincronizaría del SQL real sin que nada lo señalara.
_POSGRADO_NORM = "upper(translate(name, 'áéíóúüÁÉÍÓÚÜ', 'aeiouuAEIOUU'))"
# (nivel esperado, patrón1, patrón2-o-None).
_POSGRADO_PATRONES = (
    ("maestria", "MAESTRIA%", "%NEGOCIOS%"),
    ("maestria", "MAESTRIA%", "%ADMINISTRATIVA%"),
    ("maestria", "MAESTRIA%", "%INDUSTRIAL%"),
    ("doctorado", "DOCTORADO%", None),
)


def _verify_posgrado() -> list[str]:
    """Comprueba que el delta de posgrado ATERRIZÓ. Devuelve la lista de problemas.

    Mismo contrato que `_verify_survey_2026_09`/`_verify_titulacion`/
    `_verify_computer_center`: abre su propia conexión, arma sets contra la
    BD y devuelve strings de problema en vez de levantar -- los `RAISE
    NOTICE` del 18/19 son INVISIBLES para `itcj2/` (nada lee
    `connection.notices`), así que sin esto el operador vería "OK" aunque,
    por ejemplo, el 19 no hubiera activado un tipo por un `ON CONFLICT` mal
    resuelto.

    Comprueba:
      - las 4 carreras de posgrado, cada una por SU patrón exacto del 18
        (spec §4.2, `_POSGRADO_PATRONES`): las 3 de `MAESTRIA%` con nivel
        `maestria`, y la de `DOCTORADO%` con nivel `doctorado`. Un patrón con
        0 o 2+ carreras es un problema (el 18 debería haber abortado antes de
        llegar aquí, pero esta verificación no confía en eso -- mismo
        espíritu que el resto de los `_verify_*`).
      - los 4 tipos de `DocumentService.POSGRADO_EXTRA_DOCS` existen,
        ACTIVOS y en fase 1 (`titulatec_document_types`).
    """
    from sqlalchemy import text

    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.cli.core import _get_engine

    problemas: list[str] = []

    with _get_engine().connect() as conn:
        for nivel, patron1, patron2 in _POSGRADO_PATRONES:
            condicion = f"{_POSGRADO_NORM} LIKE :p1"
            params = {"p1": patron1}
            if patron2:
                condicion += f" AND {_POSGRADO_NORM} LIKE :p2"
                params["p2"] = patron2
            filas = conn.execute(
                text(f"SELECT id, name, level FROM core_programs WHERE {condicion}"),
                params,
            ).fetchall()
            etiqueta = patron1 + (f" + {patron2}" if patron2 else "")
            if len(filas) != 1:
                problemas.append(
                    f"carrera de posgrado ({etiqueta}): se esperaba exactamente 1, hay {len(filas)}"
                )
            elif filas[0][2] != nivel:
                problemas.append(
                    f"carrera '{filas[0][1]}' (id {filas[0][0]}): nivel es "
                    f"'{filas[0][2]}', se esperaba '{nivel}'"
                )

        codigos = list(DocumentService.POSGRADO_EXTRA_DOCS)
        activos = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT code FROM titulatec_document_types "
                    " WHERE code = ANY(:codes) AND is_active = TRUE AND phase_number = 1"
                ),
                {"codes": codigos},
            )
        }
        for code in codigos:
            if code not in activos:
                problemas.append(f"tipo de documento ausente o inactivo en fase 1: {code}")

    return problemas


def _precheck_posgrado(conn=None) -> dict:
    """Lee (SIN escribir) qué rama tomaría `18_classify_posgrado_programs.sql`
    si corriera AHORA MISMO. Ronda 1 de revisión de la Tarea 7: sin esto, el
    operador no podía saber -- ni antes (`--dry-run`) ni después de la
    corrida real -- si el 18 clasificó las 4 filas tecleadas a mano o insertó
    4 canónicas nuevas (posible duplicado silencioso si los nombres reales
    usan abreviaturas como «Mtría.»/«Dr.», que no contienen ni MAESTR ni
    DOCTOR).

    Usa la MISMA normalización y los MISMOS 4 patrones que el 18
    (`_POSGRADO_NORM`/`_POSGRADO_PATRONES`, también usados por
    `_verify_posgrado`): un cambio en el SQL que no se replique aquí
    desincroniza el pre-chequeo del comportamiento real.

    Devuelve un dict:
      - `branch`: `"update"` (cada patrón casa EXACTAMENTE 1 fila y las 4 son
        ids DISTINTOS -- el 18 solo actualizaría `level`), `"insert"`
        (ninguna carrera normalizada contiene MAESTR ni DOCTOR -- el 18
        insertaría las 4 canónicas) o `"abort"` (el 18 fallaría con
        `RAISE EXCEPTION`: algún patrón con 0 o 2+ coincidencias mientras
        existen raíces, O el mismo id casando más de un patrón -- esto
        último el propio SQL no lo comprueba, se detecta aquí ANTES de
        correrlo: revisión minor #1, "nothing checks that the 4 matched ids
        are distinct").
      - `matches`: solo con sentido si `branch == "update"` -- lista de
        `{"pattern": str, "level": str, "id": int, "name": str}`, una por
        patrón.
      - `reasons`: solo con sentido si `branch == "abort"` -- lista de
        strings, uno por problema (puede haber más de uno).

    `conn` (opcional): conexión o `Session` YA ABIERTA para leer -- permite
    probar esta función DENTRO del mismo savepoint que `db_session`
    (`_precheck_posgrado(conn=db_session)`), sin que la lectura se pierda por
    vivir en una conexión aparte (ver harness de
    tests/fastapi/titulatec/conftest.py: una conexión nueva vía `_get_engine`
    NUNCA vería los datos sin comitear del savepoint de la prueba). `None`
    (uso normal, CLI real): abre su propia conexión contra el engine de
    producción, como el resto de los `_verify_*` de este archivo.
    """
    from sqlalchemy import text

    def _leer(c):
        resultados = []  # (nivel, etiqueta, filas)
        for nivel, patron1, patron2 in _POSGRADO_PATRONES:
            condicion = f"{_POSGRADO_NORM} LIKE :p1"
            params = {"p1": patron1}
            if patron2:
                condicion += f" AND {_POSGRADO_NORM} LIKE :p2"
                params["p2"] = patron2
            filas = c.execute(
                text(f"SELECT id, name FROM core_programs WHERE {condicion}"), params
            ).fetchall()
            etiqueta = patron1 + (f" + {patron2}" if patron2 else "")
            resultados.append((nivel, etiqueta, filas))

        hay_raiz = c.execute(text(
            f"SELECT count(*) FROM core_programs "
            f" WHERE {_POSGRADO_NORM} LIKE '%MAESTR%' OR {_POSGRADO_NORM} LIKE '%DOCTOR%'"
        )).scalar()
        return resultados, hay_raiz

    if conn is not None:
        resultados, hay_raiz = _leer(conn)
    else:
        from itcj2.cli.core import _get_engine
        with _get_engine().connect() as c:
            resultados, hay_raiz = _leer(c)

    reasons: list[str] = []
    for _nivel, etiqueta, filas in resultados:
        if len(filas) >= 2:
            nombres = " | ".join(f"{r[1]} (id {r[0]})" for r in filas)
            reasons.append(
                f"{etiqueta}: {len(filas)} carreras casan (se esperaba 1): {nombres}"
            )
    if reasons:
        return {"branch": "abort", "matches": [], "reasons": reasons}

    if hay_raiz == 0:
        return {"branch": "insert", "matches": [], "reasons": []}

    matches = []
    for nivel, etiqueta, filas in resultados:
        if len(filas) == 0:
            reasons.append(
                f"{etiqueta}: 0 carreras casan, pero hay carreras con MAESTR/DOCTOR "
                "en el nombre en otro lado"
            )
        else:
            row = filas[0]
            matches.append({"pattern": etiqueta, "level": nivel, "id": row[0], "name": row[1]})
    if reasons:
        return {"branch": "abort", "matches": [], "reasons": reasons}

    ids = [m["id"] for m in matches]
    if len(set(ids)) != len(ids):
        from collections import Counter
        repetidos = sorted({pid for pid, n in Counter(ids).items() if n > 1})
        reasons.append(
            "el mismo id casa más de un patrón (no son 4 carreras distintas): "
            f"{repetidos}"
        )
        return {"branch": "abort", "matches": [], "reasons": reasons}

    return {"branch": "update", "matches": matches, "reasons": []}


def _posgrado_resync_preview(db, program_ids: set[int]) -> list[tuple[int, str, str | None]]:
    """Vista previa de la resincronización, ANTES de correr el 18 de verdad.

    `_resync_posgrado_phase1` decide el perfil vía `TrackService`, que mira
    `Program.level` -- inútil aquí porque, antes de correr el 18, las 4
    carreras SIGUEN en `licenciatura` (revisión de la Tarea 7, ronda 1: sin
    esto el `--dry-run` en producción imprimía SIEMPRE «0 procesos», aunque
    hubiera posgrados esperando en `in_review`). En su lugar, el perfil
    posgrado sale DIRECTO de `program_ids` (los ids que `_precheck_posgrado`
    ya identificó): un proceso cuyo `program_id` está ahí es de posgrado sin
    necesidad de preguntarle a `TrackService`.

    Replica LITERALMENTE la lógica de transición de
    `DocumentService.sync_initial_phase` (mismas 3 reglas) con el set de
    posgrado FIJO (`DocumentService.initial_doc_types(TRACK_POSGRADO)`, los 7
    códigos) -- pero de SOLO LECTURA: nunca llama a la función real (que SÍ
    escribe en el objeto ORM), así que ni siquiera hace falta un rollback
    para que esto sea inofensivo. `program_ids` vacío -> `[]` sin consultar.
    """
    from itcj2.apps.titulatec.models import Document, ProcessPhase, TitulationProcess
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.track_service import TRACK_POSGRADO

    if not program_ids:
        return []

    n = PhaseService.phase_number_for_code(db, "initial_docs")
    if n is None:
        return []

    codes = DocumentService.initial_doc_types(TRACK_POSGRADO)
    procesos = (
        db.query(TitulationProcess)
        .filter(
            TitulationProcess.status == "active",
            TitulationProcess.current_phase == n,
            TitulationProcess.program_id.in_(program_ids),
        )
        .all()
    )

    resultados: list[tuple[int, str, str | None]] = []
    for proceso in procesos:
        count = (
            db.query(Document)
            .filter(Document.process_id == proceso.id, Document.type_code.in_(codes))
            .count()
        )
        completo = count >= len(codes)
        fase = db.query(ProcessPhase).filter_by(process_id=proceso.id, phase_number=n).first()
        actual = fase.status if fase else "pending"
        if completo:
            nuevo = "in_review" if actual in ("pending", "in_progress", "rejected") else None
        else:
            nuevo = "in_progress" if actual == "in_review" else None
        resultados.append((proceso.id, proceso.folio, nuevo))
    return resultados


def _posgrado_rg_population(db, program_ids: set[int]) -> list[tuple[int, str, int, str]]:
    """Población R-G (D9 sin herramienta, Tarea 8, revisión final 2026-09-30):
    procesos de posgrado que YA PASARON la fase de `initial_docs` con ALGÚN
    extra de `DocumentService.POSGRADO_EXTRA_DOCS` todavía sin fila.

    `initial_docs_all_approved` (vía `DocumentService.excused_initial_docs`,
    R-G) los exceptúa de por vida -- no se regresan a Documentos (D9) -- así
    que nunca vuelven a aparecer por su cuenta en ninguna bandeja. Sin esta
    lista, nadie en Servicios Escolares se entera de pedirles los 4 extras EN
    el cotejo: el checklist de despliegue (`engine_process_track.md`, spec §9)
    es la única otra forma, y es manual.

    SOLO LECTURA -- no escribe ni sincroniza nada (eso lo hace
    `_resync_posgrado_phase1`, que es justo lo contrario: fase 1 TODAVÍA
    abierta). `program_ids` es el mismo criterio que `_posgrado_resync_
    preview`: en el `--dry-run`, los ids que `_precheck_posgrado` ya casó
    (`level` real todavía sin marcar); en la corrida real, los que
    `_posgrado_clasificadas` acaba de confirmar. `program_ids` vacío -> `[]`
    sin consultar (ni el catálogo de fases).

    Devuelve `(process_id, folio, current_phase, program_name)`, uno por
    proceso en alcance, ordenado por folio -- un proceso con los 4 extras YA
    subidos (nada que pedir) no aparece, aunque su fase 1 también haya
    cerrado.
    """
    from itcj2.apps.titulatec.models import Document, TitulationProcess
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.core.models.program import Program

    if not program_ids:
        return []

    n = PhaseService.phase_number_for_code(db, "initial_docs")
    if n is None:
        return []

    procesos = (
        db.query(TitulationProcess)
        .filter(
            TitulationProcess.status == "active",
            TitulationProcess.program_id.in_(program_ids),
            TitulationProcess.current_phase > n,
        )
        .order_by(TitulationProcess.folio)
        .all()
    )
    if not procesos:
        return []

    extras = set(DocumentService.POSGRADO_EXTRA_DOCS)
    presentes_por_proceso: dict[int, set[str]] = {}
    for pid, code in (
        db.query(Document.process_id, Document.type_code)
        .filter(Document.process_id.in_([p.id for p in procesos]),
                Document.type_code.in_(extras))
        .all()
    ):
        presentes_por_proceso.setdefault(pid, set()).add(code)

    nombres = {p.id: p.name for p in db.query(Program).filter(Program.id.in_(program_ids)).all()}

    resultados: list[tuple[int, str, int, str]] = []
    for proceso in procesos:
        presentes = presentes_por_proceso.get(proceso.id, set())
        if len(presentes) >= len(extras):
            continue        # ya tiene los 4 extras: nada que pedir en el cotejo
        resultados.append((
            proceso.id, proceso.folio, proceso.current_phase,
            nombres.get(proceso.program_id, "—"),
        ))
    return resultados


def _posgrado_clasificadas(conn) -> list[tuple[int, str, str]]:
    """`id, name, level` de las carreras YA clasificadas como posgrado.

    Extraída a función propia (antes vivía inline en el comando) para que las
    pruebas del comando puedan parchear esta única llamada en vez de
    `_get_engine` completo -- mismo motivo que `_posgrado_warn_unclassified`.
    """
    from sqlalchemy import text

    return conn.execute(text(
        "SELECT id, name, level FROM core_programs "
        " WHERE level IN ('maestria', 'doctorado') ORDER BY id"
    )).fetchall()


def _posgrado_warn_unclassified(conn) -> list[tuple[int, str]]:
    """`id, name` de carreras con MAESTR/DOCTOR en el nombre que SIGUEN en
    `licenciatura` tras correr el 18 (revisión minor #2: antes quedaban en
    silencio). Puede pasar con la rama `insert` (`--allow-insert`): si los
    nombres reales usan una abreviatura que el 18 no reconoce (p. ej.
    «Mtría.»), el 18 inserta 4 canónicas NUEVAS y deja las originales
    intactas -- esta advertencia solo atrapa el caso en que el nombre SÍ
    contiene la raíz completa pero, por lo que sea, ningún patrón la marcó.
    """
    from sqlalchemy import text

    return conn.execute(text(
        f"SELECT id, name FROM core_programs "
        f" WHERE ({_POSGRADO_NORM} LIKE '%MAESTR%' OR {_POSGRADO_NORM} LIKE '%DOCTOR%') "
        f"   AND level = 'licenciatura'"
    )).fetchall()


def _resync_posgrado_phase1(dry_run: bool) -> list[tuple[int, str, str | None]]:
    """Re-sincroniza `ProcessPhase(1)` de los procesos de posgrado ACTIVOS que
    siguen en esa fase, tras clasificar las 4 carreras (spec
    2026-09-30-titulatec-posgrado-design.md §5).

    Por qué hace falta
    -------------------
    `DocumentService.sync_initial_phase` solo corre HOY MISMO como efecto
    secundario de `DocumentService.save`/`delete` (subir o borrar un
    documento). Un proceso de posgrado que YA TENÍA sus 3 documentos base
    ANTES de este despliegue quedó en `in_review` esperando revisión con
    SOLO 3 -- clasificar la carrera (18) no dispara por sí sola ese
    recálculo, y sin este resync el proceso se vería atorado en Documentos
    hasta que alguien subiera o borrara uno por casualidad.

    Alcance: proceso `status == 'active'` y `current_phase` igual al número
    de fase `initial_docs` en el catálogo, filtrado a perfil posgrado
    (`TrackService.for_processes`, invariante 2: el perfil sale SOLO de
    ahí). Sin el catálogo de fases (BD nueva sin `init-titulatec`), no hay
    nada que resincronizar -- devuelve `[]` sin abrir más consultas.

    R-G (invariante 8, spec §5/§6, deriva de D9): un proceso que YA PASÓ la
    fase 1 no entra aquí (su `current_phase` ya no es el de `initial_docs`),
    y `sync_initial_phase` en sí mismo nunca toca `approved`/`skipped` -- no
    se regresa.

    `dry_run=True`: calcula todo igual (incluidas las mutaciones en memoria
    de `sync_initial_phase`) y termina en ROLLBACK -- nunca escribe.
    `dry_run=False` hace COMMIT una sola vez, al final.

    Devuelve una tupla `(process_id, folio, nuevo_estado)` por proceso en
    alcance; `nuevo_estado` es lo que devolvió `sync_initial_phase` (`None`
    si no cambió nada -- p. ej. ya estaba `in_progress` con menos de 7).
    """
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.track_service import TRACK_POSGRADO, TrackService
    from itcj2.database import SessionLocal

    db = SessionLocal()
    resultados: list[tuple[int, str, str | None]] = []
    try:
        n = PhaseService.phase_number_for_code(db, "initial_docs")
        if n is None:
            return resultados

        procesos = (
            db.query(TitulationProcess)
            .filter(TitulationProcess.status == "active", TitulationProcess.current_phase == n)
            .all()
        )
        if procesos:
            tracks = TrackService.for_processes(db, procesos)
            for proceso in procesos:
                if tracks.get(proceso.id) != TRACK_POSGRADO:
                    continue
                nuevo_estado = DocumentService.sync_initial_phase(db, proceso)
                resultados.append((proceso.id, proceso.folio, nuevo_estado))

        if dry_run:
            db.rollback()
        else:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return resultados


@titulatec_cli.command("init-posgrado")
@click.option("--dry-run", is_flag=True,
              help="Muestra la rama que tomaría el 18 y los procesos a re-sincronizar, sin escribir.")
@click.option("--allow-insert", is_flag=True,
              help="Permite insertar las 4 carreras canónicas cuando NINGUNA existente casa "
                   "MAESTR/DOCTOR (bases nuevas/vacías). Sin esta bandera esa rama aborta: "
                   "evita duplicar carreras si los nombres reales usan una abreviatura "
                   "(p. ej. «Mtría.») que el 18 no reconoce.")
def init_posgrado_command(dry_run, allow_insert):
    """Clasifica las 4 carreras de posgrado y da de alta sus 4 documentos de fase 1.

    Corre SOLO `database/DML/titulatec/posgrado_2026_10/`
    (`_DML_POSGRADO_2026_10_FILES`, D10): producción ya corrió
    `init-titulatec` y ese comando nunca se re-ejecuta allí, así que este es
    el único camino de despliegue para este delta -- además de sumarse a
    `SEED_FILES` para una instalación desde cero.

    `18_classify_posgrado_programs.sql` ubica las 4 carreras (2 maestrías +
    la de industrial + el doctorado) POR NOMBRE NORMALIZADO (D2), nunca por
    id ni "las últimas 4": en una base sin posgrados tecleados a mano (dev,
    CI, instalación nueva) inserta las 4 con nombres canónicos; en una base
    con posgrado ya tecleado a mano (prod) las ubica y marca su nivel. Aborta
    SIN escribir ante cualquier ambigüedad (2+ carreras casan un mismo
    patrón) o ante una carrera de posgrado a medias (alguna raíz
    MAESTR/DOCTOR existe pero un patrón no casa) -- nunca duplica
    (invariante 7). `19_insert_posgrado_doc_types.sql` da de alta los 4 tipos
    de documento extra de fase 1 (`DocumentService.POSGRADO_EXTRA_DOCS`).

    Ronda 1 de revisión: antes de escribir NADA, `_precheck_posgrado()` lee
    (sin escribir) qué rama tomaría el 18. `abort` -> se detiene, nada se
    ejecuta. `insert` -> se detiene salvo que se pase `--allow-insert` (sin
    ella, un nombre real con una abreviatura que el 18 no reconoce insertaría
    4 canónicas DUPLICADAS en silencio -- exactamente lo que este pre-chequeo
    existe para impedir). `update` -> procede igual que antes.

    Al terminar VERIFICA con `_verify_posgrado()` (los `RAISE NOTICE` del SQL
    son invisibles, mismo motivo que el resto de los `_verify_*` de este
    archivo), imprime la RAMA que de verdad se tomó, e imprime id/nombre/nivel
    de las 4 carreras -- más una ADVERTENCIA (amarilla) si alguna carrera con
    MAESTR/DOCTOR en el nombre sigue en `licenciatura` (revisión minor #2).
    Después RE-SINCRONIZA la fase 1 de los procesos de posgrado ACTIVOS que
    siguen en esa fase (spec §5): uno que llevaba los 3 documentos base y
    estaba `in_review` esperando revisión pasa a `in_progress` (le faltan los
    4 nuevos) -- sin avisos ni correos, `sync_initial_phase` solo escribe
    estado. R-G (invariante 8): un proceso que YA PASÓ la fase 1 no se toca,
    aunque le falten los 4 extras -- no se regresa (D9). Por último, SOLO
    LECTURA, imprime la población R-G (D9 sin herramienta, Tarea 8): los
    procesos de posgrado que YA PASARON la fase 1 con algún extra todavía sin
    fila, bajo «Pedir en el cotejo (fase 1 ya cerrada): N» -- esos nunca
    vuelven a aparecer solos en ninguna bandeja (`initial_docs_all_approved`
    los exceptúa de por vida), así que esta es la única forma de que
    Servicios Escolares se entere de pedírselos EN el cotejo.

    `--dry-run`: corre `_precheck_posgrado()` e imprime la rama (con los
    ids/nombres que quedarían, o los motivos del abort), y lista los procesos
    que se re-sincronizarían (con el estado que resultaría) usando
    `_posgrado_resync_preview` -- que identifica candidatos por `program_id`,
    NUNCA por `Program.level` (que en este punto sigue en `licenciatura` para
    los 4) -- y, con el mismo criterio, la población R-G
    (`_posgrado_rg_population`) que se vería tras correr el 18 de verdad.
    También dice si los 2 archivos existen en disco (y en ese caso sale
    distinto de 0, aunque el resto del reporte se imprime igual: el precheck
    lee `core_programs` directo, no necesita los archivos). Nunca escribe
    nada. Sale 0 solo si los 2 archivos existen Y la rama no es `abort`.
    """
    if dry_run:
        faltan = [
            nombre for nombre in _DML_POSGRADO_2026_10_FILES
            if not (DML_TITULATEC / _DML_POSGRADO_2026_10_DIR / nombre).exists()
        ]
        if faltan:
            click.echo(click.style(f"ERROR: faltan archivos en disco: {faltan}", fg="red"))
        else:
            click.echo("Archivos en disco: OK. Se ejecutarían:")
            for nombre in _DML_POSGRADO_2026_10_FILES:
                click.echo(f"  {_DML_POSGRADO_2026_10_DIR}/{nombre}")

        precheck = _precheck_posgrado()
        click.echo(f"[dry-run] Rama que tomaría el 18: {precheck['branch']}")

        if precheck["branch"] == "abort":
            for r in precheck["reasons"]:
                click.echo(click.style(f"  ERROR: {r}", fg="red"))
        elif precheck["branch"] == "insert":
            click.echo(
                "  Ninguna carrera existente casa MAESTR/DOCTOR: insertaría las 4 "
                "canónicas (la corrida real necesitaría --allow-insert)."
            )
        else:
            for m in precheck["matches"]:
                click.echo(f"  {m['id']} · {m['name']} · quedaría en {m['level']}")

        resultados = []
        rg = []
        if precheck["branch"] == "update":
            from itcj2.database import SessionLocal

            program_ids = {m["id"] for m in precheck["matches"]}
            db = SessionLocal()
            try:
                resultados = _posgrado_resync_preview(db, program_ids)
                rg = _posgrado_rg_population(db, program_ids)
            finally:
                db.rollback()
                db.close()

        click.echo(
            f"[dry-run] Procesos de posgrado a re-sincronizar en fase 1: {len(resultados)}"
        )
        for pid, folio, nuevo_estado in resultados:
            click.echo(f"  {folio} (id {pid}): -> {nuevo_estado or '(sin cambio)'}")

        # D9 sin herramienta (Tarea 8): poblacion R-G -- procesos que YA
        # pasaron la fase 1 con algun extra sin fila. `initial_docs_all_
        # approved` los exceptua de por vida (no se regresan, D9), asi que
        # SE no se entera de pedirselos en el cotejo si nadie se lo dice.
        click.echo(f"[dry-run] Pedir en el cotejo (fase 1 ya cerrada): {len(rg)}")
        for pid, folio, fase, carrera in rg:
            click.echo(f"  {folio} (id {pid}): fase {fase:02d} · {carrera}")

        click.echo("Dry-run: no se ejecutó nada.")
        if faltan or precheck["branch"] == "abort":
            raise click.Abort()
        return

    precheck = _precheck_posgrado()
    if precheck["branch"] == "abort":
        click.echo()
        for r in precheck["reasons"]:
            click.echo(click.style(f"ERROR: {r}", fg="red"), err=True)
        raise click.Abort()
    if precheck["branch"] == "insert" and not allow_insert:
        click.echo(click.style(
            "ERROR: ninguna carrera existente casa con MAESTR/DOCTOR -- no se encontró "
            "ninguna carrera de posgrado tecleada a mano. Si esto es una base nueva o "
            "vacía (dev/CI), vuelve a correr con --allow-insert para insertar las 4 "
            "canónicas. Si esto es producción, revisa los nombres en core_programs "
            "antes de continuar: el 18 duplicaría carreras si los nombres reales usan "
            "una abreviatura que no reconoce.",
            fg="red",
        ), err=True)
        raise click.Abort()

    _run_sql_files(
        [f"{_DML_POSGRADO_2026_10_DIR}/{nombre}" for nombre in _DML_POSGRADO_2026_10_FILES]
    )

    problemas = _verify_posgrado()
    if problemas:
        click.echo()
        for p in problemas:
            click.echo(click.style(f"ERROR: {p}", fg="red"), err=True)
        raise click.Abort()

    click.echo(f"Rama tomada: {precheck['branch']}")

    from itcj2.cli.core import _get_engine

    with _get_engine().connect() as conn:
        carreras = _posgrado_clasificadas(conn)
        sin_clasificar = _posgrado_warn_unclassified(conn)

    click.echo("Carreras de posgrado clasificadas:")
    for pid, name, level in carreras:
        click.echo(f"  {pid} · {name} · {level}")

    if sin_clasificar:
        click.echo(click.style(
            "ADVERTENCIA: estas carreras contienen MAESTR/DOCTOR en el nombre pero "
            "siguen en nivel 'licenciatura' (revísalas a mano):",
            fg="yellow",
        ))
        for pid, name in sin_clasificar:
            click.echo(click.style(f"  {pid} · {name}", fg="yellow"))

    resultados = _resync_posgrado_phase1(dry_run=False)
    click.echo(f"Procesos de posgrado re-sincronizados en fase 1: {len(resultados)}")
    for pid, folio, nuevo_estado in resultados:
        click.echo(f"  {folio} (id {pid}): -> {nuevo_estado or '(sin cambio)'}")

    # D9 sin herramienta (Tarea 8, revisión final): población R-G -- procesos
    # que YA pasaron la fase 1 con algún extra sin fila. `initial_docs_all_
    # approved` los exceptúa de por vida (no se regresan, D9): sin este
    # aviso, nadie en Servicios Escolares se entera de pedírselos en el
    # cotejo. Mismos ids que `carreras` -- las recién clasificadas -- no
    # `Program.level` (ya coinciden en este punto, pero es la misma fuente
    # que ya trajo `_posgrado_clasificadas` arriba, sin una segunda lectura).
    from itcj2.database import SessionLocal

    program_ids = {pid for pid, _name, _level in carreras}
    db = SessionLocal()
    try:
        rg = _posgrado_rg_population(db, program_ids)
    finally:
        db.rollback()
        db.close()

    click.echo(f"Pedir en el cotejo (fase 1 ya cerrada): {len(rg)}")
    for pid, folio, fase, carrera in rg:
        click.echo(f"  {folio} (id {pid}): fase {fase:02d} · {carrera}")

    click.echo(click.style(
        "OK: 4 carreras de posgrado clasificadas y 4 tipos de documento de "
        "fase 1 dados de alta/actualizados.",
        fg="green",
    ))


# ---------------------------------------------------------------------------
# No adeudo de biblioteca (Biblioteca -> Caja), 2026-10-01 (spec
# 2026-10-01-titulatec-biblioteca-caja-design.md, §4.6/§6): Biblioteca revisa
# en FIFO a todo inscrito y registra si debe (y cuanto); el egresado va
# directo a Caja a pagar adeudo + "Donacion voluntaria de libro"; Caja
# registra el pago y eso libera el requisito `library_clearance`. Puesto
# nuevo por area, rol nuevo por puesto, 10 permisos nuevos (88 -> 98).
# ---------------------------------------------------------------------------
_DML_BIBLIOTECA_2026_10_DIR = "biblioteca_2026_10"
# Despliegue en DOS pasos (Ruling R19, I1 de la revision final): el comando
# que crea los puestos ya no puede ser el mismo que enciende el candado, o
# «asignar ocupantes antes» es imposible (los puestos no existen hasta el 20,
# y el 22 bloquea a todos en el mismo paso).
#   - `init-biblioteca-caja` corre SOLO estos: puestos (20); roles,
#     permisos, mapeo y concesiones (21), y la descripcion nueva de la tarea
#     de recordatorios por correo, que ahora menciona el pago pendiente en
#     Caja (23, m33 de 2026-10-02: el 17 de `mail_2026_09/` no se re-corre en
#     produccion). NO enciende nada.
#   - `activar-biblioteca-caja` corre SOLO el 22 (requisito automatico =
#     candado encendido), tras sus pre-chequeos, y luego el re-backfill y la
#     promocion de los marcados a mano (Ruling R20).
# Entre las DOS listas deben estar TODOS los .sql del directorio (mismo
# contrato que `_DML_POSGRADO_2026_10_FILES`/`_DML_MAIL_2026_09_FILES`/
# `_DML_SURVEY_2026_09_FILES`): lo fija
# `test_todo_sql_del_delta_esta_en_una_lista_de_comando`
# (tests/fastapi/titulatec/test_cli_biblioteca_caja.py). Un archivo que se
# caiga de las dos no lo corre nadie y nada se pone rojo. `SEED_FILES` (alta
# desde cero con `init-titulatec`) conserva los CUATRO: ahi no hay procesos
# que proteger y encender de inmediato esta bien (el 23, ahi, no cambia nada).
_DML_BIBLIOTECA_2026_10_FILES = [
    "20_insert_library_cashier_positions.sql",
    "21_insert_library_cashier_roles_perms.sql",
    "23_update_email_reminders_description.sql",
]
_DML_BIBLIOTECA_2026_10_ACTIVAR_FILES = [
    "22_library_requirement_auto.sql",
]

_ROL_LIBRARY = "titulatec_library"
_ROL_CASHIER = "titulatec_cashier"
_PUESTO_LIBRARY = "library_clearance_info_center"      # depto info_center, "Biblioteca · No adeudo"
_PUESTO_CASHIER = "cashier_financial_resources"         # depto financial_resources, "Caja"

# Los 5 de la bandeja de Biblioteca.
_PERMISOS_LIBRARY_CLEARANCE = (
    "titulatec.library_clearance.page.list",
    "titulatec.library_clearance.api.register",
    "titulatec.library_clearance.api.prior",
    "titulatec.library_clearance.api.revert",
    "titulatec.library_clearance.api.print_certificates",
)
# Los 3 de la bandeja de Caja.
_PERMISOS_LIBRARY_PAYMENT = (
    "titulatec.library_payment.page.list",
    "titulatec.library_payment.api.register",
    "titulatec.library_payment.api.revert",
)
# Los 2 sueltos del delta: imprimir constancias de la encuesta (GTV) y la
# bandeja de Constancias (comun a encuesta y no adeudo).
_PERM_SURVEY_PRINT_CERTIFICATES = "titulatec.survey_review.api.print_certificates"
_PERM_CERTIFICATE_PAGE_LIST = "titulatec.certificate.page.list"

# Los 10 del delta (spec §4.6, tabla). FUENTE UNICA para `_verify_biblioteca_
# caja` y para `test_los_diez_codigos_del_delta_son_los_del_contrato`.
_PERMISOS_BIBLIOTECA_CAJA_2026_10 = (
    _PERMISOS_LIBRARY_CLEARANCE
    + _PERMISOS_LIBRARY_PAYMENT
    + (_PERM_SURVEY_PRINT_CERTIFICATES, _PERM_CERTIFICATE_PAGE_LIST)
)

# Reparto EXACTO de los dos roles nuevos (spec §4.6): titulatec_library son
# los 5 de Biblioteca MAS certificate.page.list (ve la bandeja de
# Constancias); titulatec_cashier son SOLO los 3 de Caja.
_PERMISOS_ROL_LIBRARY = _PERMISOS_LIBRARY_CLEARANCE + (_PERM_CERTIFICATE_PAGE_LIST,)
_PERMISOS_ROL_CASHIER = _PERMISOS_LIBRARY_PAYMENT

# Puestos que deben tener ocupante antes de encender el candado (pre-chequeo
# de `activar-biblioteca-caja`): sin ellos nadie salvo `admin` libera a nadie.
_PUESTOS_BIBLIOTECA_CAJA = (_PUESTO_LIBRARY, _PUESTO_CASHIER)


# --- Re-backfill de `titulatec_library_clearances` --------------------------
# MISMO predicado que el backfill de la migracion `tt20261001a`
# (migrations/versions/tt20261001a_titulatec_biblioteca_caja.py,
# BACKFILL_SQL): por cada proceso activo/en pausa cuya fase 2 NO este
# aprobada (sin fila cuenta como NO aprobada) y que TODAVIA no tenga fila en
# `titulatec_library_clearances`, inserta 'cleared'/cleared_via='legacy' si
# ya tiene un `RequirementFulfillment` fulfilled|waived del requisito
# `library_clearance` de SU convocatoria; si no, 'pending'. Existe para
# alcanzar los procesos que se crearon durante la ventana blue/green, entre
# que corrio la migracion y que corre `activar-biblioteca-caja` (Review Focus
# #5 del plan; Ruling R19: lo corre la ACTIVACION, ya no
# `init-biblioteca-caja`) -- la migracion por si sola solo ve los procesos
# que existian AL MOMENTO de aplicarse.
#
# El fragmento de predicado es el MISMO texto Python para el INSERT real y
# para el COUNT de la vista previa (`--dry-run`): no hay forma de que
# diverjan sin que el propio archivo deje de compilar.
_LIBRARY_CLEARANCE_BACKFILL_PREDICATE = """
  FROM titulatec_processes p
 WHERE p.status IN ('active', 'on_hold')
   AND NOT EXISTS (
       SELECT 1 FROM titulatec_process_phases ph
        WHERE ph.process_id = p.id AND ph.phase_number = 2 AND ph.status = 'approved'
   )
   AND NOT EXISTS (
       SELECT 1 FROM titulatec_library_clearances lc WHERE lc.process_id = p.id
   )
"""

_LIBRARY_CLEARANCE_REBACKFILL_SQL = """
INSERT INTO titulatec_library_clearances
    (process_id, status, cleared_via, created_at, updated_at)
SELECT
    p.id,
    CASE WHEN EXISTS (
        SELECT 1
          FROM titulatec_requirement_fulfillments rf
          JOIN titulatec_cotejo_requirements req ON req.id = rf.requirement_id
         WHERE rf.process_id = p.id
           AND req.cohort_id = p.cohort_id
           AND req.code = 'library_clearance'
           AND rf.status IN ('fulfilled', 'waived')
    ) THEN 'cleared' ELSE 'pending' END,
    CASE WHEN EXISTS (
        SELECT 1
          FROM titulatec_requirement_fulfillments rf
          JOIN titulatec_cotejo_requirements req ON req.id = rf.requirement_id
         WHERE rf.process_id = p.id
           AND req.cohort_id = p.cohort_id
           AND req.code = 'library_clearance'
           AND rf.status IN ('fulfilled', 'waived')
    ) THEN 'legacy' ELSE NULL END,
    NOW(),
    NOW()
""" + _LIBRARY_CLEARANCE_BACKFILL_PREDICATE

_LIBRARY_CLEARANCE_REBACKFILL_COUNT_SQL = "SELECT COUNT(*)" + _LIBRARY_CLEARANCE_BACKFILL_PREDICATE


def _library_clearance_rebackfill(dry_run: bool) -> int:
    """Re-backfill idempotente de `titulatec_library_clearances`.

    Abre su PROPIA sesion (import local de `SessionLocal`, convencion del
    proyecto) para que `patched_session_local` pueda interceptarla en los
    tests -- mismo patron que `_resync_posgrado_phase1`. `dry_run=True` solo
    CUENTA (SELECT, nunca escribe); `dry_run=False` inserta y hace UN commit.
    Idempotente por construccion: el `NOT EXISTS` sobre la propia tabla hace
    que una segunda corrida inserte 0 filas.

    Devuelve cuantas filas creo (o crearia, en dry-run).
    """
    return _run_counted_sql(_LIBRARY_CLEARANCE_REBACKFILL_SQL,
                            _LIBRARY_CLEARANCE_REBACKFILL_COUNT_SQL, dry_run)


def _run_counted_sql(sql: str, count_sql: str, dry_run: bool) -> int:
    """Corre `sql` (un INSERT/UPDATE de datos) y devuelve cuantas filas tocó,
    o, con `dry_run`, solo cuenta con `count_sql` (SELECT, nunca escribe).
    Abre su PROPIA sesion (import local de `SessionLocal`, convencion del
    proyecto) para que `patched_session_local` la intercepte en las pruebas;
    UN commit en la corrida real."""
    from sqlalchemy import text

    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        if dry_run:
            count = db.execute(text(count_sql)).scalar() or 0
            db.rollback()
        else:
            result = db.execute(text(sql))
            count = result.rowcount or 0
            db.commit()
        return count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# --- Promocion D17 de la ventana de transicion (Ruling R20, I2) ------------
# El backfill decide `legacy` vs `pending` cuando corre (migracion o
# re-backfill). Hasta que la activacion enciende el candado, el requisito
# `library_clearance` sigue siendo MANUAL (`auto_source` NULL) y Servicios
# Escolares lo sigue marcando a mano -con el codigo viejo (blue/green) y con
# el nuevo-; el re-backfill nunca revisita una fila que YA existe. Sin esto,
# quien entrego su papel DESPUES de la migracion quedaria bloqueado
# (`library_pending`) y en la cola de Biblioteca, contra D17.
#
# Promueve a `cleared`/`cleared_via='legacy'` SOLO filas `pending` que
# Biblioteca no ha tocado (`library_at IS NULL`) cuando su convocatoria tiene
# el requisito `library_clearance` cumplido (`fulfilled|waived`) para ese
# proceso, o cuando su fase 2 ya esta `approved` (ya paso su cotejo). Es DATO
# como el backfill: sin eventos, sin avisos, sin correos, sin constancia EN ESTE
# PASO (el folio del legado lo saca el paso siguiente de `activar-biblioteca-caja`,
# `FolioBackfillService`). Idempotente: una fila promovida deja de ser `pending`.
# El predicado es el MISMO texto para el UPDATE real y el COUNT de la vista
# previa.
_LIBRARY_CLEARANCE_PROMOTE_CONDITIONS = """
       p.id = lc.process_id
   AND lc.status = 'pending'
   AND lc.library_at IS NULL
   AND (
       EXISTS (
           SELECT 1
             FROM titulatec_requirement_fulfillments rf
             JOIN titulatec_cotejo_requirements req ON req.id = rf.requirement_id
            WHERE rf.process_id = p.id
              AND req.cohort_id = p.cohort_id
              AND req.code = 'library_clearance'
              AND rf.status IN ('fulfilled', 'waived')
       )
       OR EXISTS (
           SELECT 1 FROM titulatec_process_phases ph
            WHERE ph.process_id = p.id AND ph.phase_number = 2 AND ph.status = 'approved'
       )
   )
"""

_LIBRARY_CLEARANCE_PROMOTE_SQL = (
    "UPDATE titulatec_library_clearances lc "
    "   SET status = 'cleared', cleared_via = 'legacy', updated_at = NOW() "
    "  FROM titulatec_processes p "
    " WHERE" + _LIBRARY_CLEARANCE_PROMOTE_CONDITIONS
)

_LIBRARY_CLEARANCE_PROMOTE_COUNT_SQL = (
    "SELECT COUNT(*) FROM titulatec_library_clearances lc, titulatec_processes p "
    " WHERE" + _LIBRARY_CLEARANCE_PROMOTE_CONDITIONS
)


def _library_clearance_promote(dry_run: bool) -> int:
    """Promocion D17 de la ventana de transicion (Ruling R20): `pending` no
    tocadas por Biblioteca -> `cleared/legacy` si el requisito ya esta
    cumplido a mano o la fase 2 ya esta aprobada. Devuelve cuantas promovio
    (o promoveria, en dry-run). Idempotente; sin eventos."""
    return _run_counted_sql(_LIBRARY_CLEARANCE_PROMOTE_SQL,
                            _LIBRARY_CLEARANCE_PROMOTE_COUNT_SQL, dry_run)


def _verify_biblioteca_caja() -> list[str]:
    """Comprueba que el 20 y el 21 ATERRIZARON (lo que corre
    `init-biblioteca-caja`). Devuelve problemas.

    Mismo contrato de SALIDA que el resto de los `_verify_*` de este archivo:
    arma sets contra la BD y devuelve strings de problema en vez de levantar
    -- los `RAISE NOTICE` del 20/21/22 son INVISIBLES para `itcj2/` (nada lee
    `connection.notices`). A diferencia de esos otros `_verify_*` (que abren
    `_get_engine().connect()` crudo), este abre su PROPIA sesión (import
    local de `SessionLocal`, convención del proyecto) para que
    `patched_session_local` pueda interceptarla en las pruebas -- mismo
    patrón que `_precheck_activar_biblioteca`/`_run_counted_sql` en este
    archivo (m04: antes usaba `_get_engine()` directo, intestable sin pegarle
    a la BD de dev de verdad). Solo lectura: no hace falta `commit`/
    `rollback` explícito, cerrar basta.

    Seis chequeos (spec §4.6):
      - los 2 puestos nuevos existen;
      - los 10 permisos existen;
      - `titulatec_library` concede EXACTAMENTE sus 6 (los 5 de Biblioteca +
        certificate.page.list) y `titulatec_cashier` EXACTAMENTE sus 3 --
        mismo patron "exacto" que `_verify_computer_center`;
      - GTV (`titulatec_tech_management`), Servicios Escolares operativo y su
        jefatura CONTIENEN sus concesiones nuevas -- semantica "al menos",
        porque ya traian otros permisos de antes (patron A7, igual que
        `_verify_titulacion`/`_verify_computer_center`);
      - `admin` CONTIENE los 10 (concesion EXPLICITA del 21: en produccion
        nunca se re-corre el 15, que es quien normalmente se lo daria
        dinamicamente);
      - el mapeo puesto->rol: cada puesto nuevo INCLUYE su rol nuevo.

    El requisito automatico (el 22) NO es de aqui: lo verifica
    `_verify_candado_biblioteca`, en `activar-biblioteca-caja` (Ruling R19).

    Si algun puesto no existe en la base (0 filas), el mensaje lo dice
    explicitamente -- igual que `_verify_computer_center` con Centro de
    Computo -- en vez de solo reportar que falta el mapeo.
    """
    from sqlalchemy import text

    from itcj2.database import SessionLocal

    problemas: list[str] = []

    db = SessionLocal()
    try:
        puestos = {
            row[0]
            for row in db.execute(
                text("SELECT code FROM core_positions WHERE code = ANY(:codes)"),
                {"codes": [_PUESTO_LIBRARY, _PUESTO_CASHIER]},
            )
        }
        for code in (_PUESTO_LIBRARY, _PUESTO_CASHIER):
            if code not in puestos:
                problemas.append(
                    f"puesto ausente: {code} (el organigrama de Biblioteca/Caja "
                    "no esta sembrado en esta base)"
                )

        permisos = {
            row[0]
            for row in db.execute(
                text(
                    "SELECT p.code FROM core_permissions p "
                    "JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                    "WHERE p.code = ANY(:codes)"
                ),
                {"codes": list(_PERMISOS_BIBLIOTECA_CAJA_2026_10)},
            )
        }
        for code in _PERMISOS_BIBLIOTECA_CAJA_2026_10:
            if code not in permisos:
                problemas.append(f"permiso ausente: {code}")

        concedidos = {
            (row[0], row[1])
            for row in db.execute(
                text(
                    "SELECT r.name, p.code "
                    "  FROM core_role_permissions rp "
                    "  JOIN core_roles r ON r.id = rp.role_id "
                    "  JOIN core_permissions p ON p.id = rp.perm_id "
                    "  JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                    " WHERE p.code = ANY(:codes)"
                ),
                {"codes": list(_PERMISOS_BIBLIOTECA_CAJA_2026_10)},
            )
        }

        concedidos_library = {c for (r, c) in concedidos if r == _ROL_LIBRARY}
        if concedidos_library != set(_PERMISOS_ROL_LIBRARY):
            faltan = set(_PERMISOS_ROL_LIBRARY) - concedidos_library
            sobran = concedidos_library - set(_PERMISOS_ROL_LIBRARY)
            problemas.append(
                f"{_ROL_LIBRARY} no tiene exactamente sus 6 permisos "
                f"(faltan {sorted(faltan)}, sobran {sorted(sobran)})"
            )

        concedidos_cashier = {c for (r, c) in concedidos if r == _ROL_CASHIER}
        if concedidos_cashier != set(_PERMISOS_ROL_CASHIER):
            faltan = set(_PERMISOS_ROL_CASHIER) - concedidos_cashier
            sobran = concedidos_cashier - set(_PERMISOS_ROL_CASHIER)
            problemas.append(
                f"{_ROL_CASHIER} no tiene exactamente sus 3 permisos "
                f"(faltan {sorted(faltan)}, sobran {sorted(sobran)})"
            )

        for code in (_PERM_SURVEY_PRINT_CERTIFICATES, _PERM_CERTIFICATE_PAGE_LIST):
            if (_ROL_GTV, code) not in concedidos:
                problemas.append(f"sin grant a GTV ({_ROL_GTV}): {code}")

        for rol in (_ROL_OPERATIVO_ESCOLARES, _ROL_JEFATURA_ESCOLARES):
            if (rol, "titulatec.library_clearance.api.prior") not in concedidos:
                problemas.append(
                    f"sin grant a {rol}: titulatec.library_clearance.api.prior "
                    "(respaldo D9)"
                )

        for code in _PERMISOS_BIBLIOTECA_CAJA_2026_10:
            if (_ROL_ADMIN, code) not in concedidos:
                problemas.append(f"sin grant a {_ROL_ADMIN}: {code}")

        puestos_de_rol = {}
        for rol in (_ROL_LIBRARY, _ROL_CASHIER):
            puestos_de_rol[rol] = {
                row[0]
                for row in db.execute(
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
        if _PUESTO_LIBRARY not in puestos_de_rol[_ROL_LIBRARY]:
            problemas.append(
                f"mapeo puesto→rol de {_ROL_LIBRARY}: falta {_PUESTO_LIBRARY} "
                f"(hay {sorted(puestos_de_rol[_ROL_LIBRARY])})"
            )
        if _PUESTO_CASHIER not in puestos_de_rol[_ROL_CASHIER]:
            problemas.append(
                f"mapeo puesto→rol de {_ROL_CASHIER}: falta {_PUESTO_CASHIER} "
                f"(hay {sorted(puestos_de_rol[_ROL_CASHIER])})"
            )
    finally:
        db.close()

    return problemas


# Requisitos `library_clearance` que el 22 todavia tiene que poner al dia
# (automatico + obligatorio + activo). Mismo predicado para el conteo de la
# vista previa de la activacion y para su verificacion final (debe dar 0).
_LIBRARY_REQUIREMENT_OFF_COUNT_SQL = """
SELECT COUNT(*) FROM titulatec_cotejo_requirements
 WHERE code = 'library_clearance'
   AND (auto_source IS DISTINCT FROM 'library_clearance'
        OR is_required IS DISTINCT FROM TRUE
        OR is_active IS DISTINCT FROM TRUE)
"""


def _library_requirements_off() -> tuple[int, int]:
    """`(por_encender, total)`: cuantas filas `code='library_clearance'`
    siguen sin el requisito automatico/obligatorio/activo, de cuantas.
    Solo lectura, conexion propia (como los `_verify_*`)."""
    from sqlalchemy import text

    from itcj2.cli.core import _get_engine

    with _get_engine().connect() as conn:
        por_encender = conn.execute(text(_LIBRARY_REQUIREMENT_OFF_COUNT_SQL)).scalar() or 0
        total = conn.execute(text(
            "SELECT COUNT(*) FROM titulatec_cotejo_requirements "
            " WHERE code = 'library_clearance'")).scalar() or 0
    return por_encender, total


# --- Pre-chequeos de `activar-biblioteca-caja` (Ruling R19) ----------------
# Ocupante VIGENTE: mismo criterio que `authz_service._active_position_filter`
# (activo, `start_date <= hoy`, `end_date` NULL o >= hoy) y usuario activo.
_OCUPANTES_SQL = """
SELECT pos.code, COUNT(u.id)
  FROM core_positions pos
  LEFT JOIN core_user_positions up
         ON up.position_id = pos.id
        AND up.is_active
        AND up.start_date <= CURRENT_DATE
        AND (up.end_date IS NULL OR up.end_date >= CURRENT_DATE)
  LEFT JOIN core_users u ON u.id = up.user_id AND u.is_active
 WHERE pos.code = ANY(:codes)
 GROUP BY pos.code
"""

# Convocatorias que QUEDARAN con candado (tienen fila `code='library_clearance'`:
# el 22 las pone TODAS automaticas) con procesos admitidos que todavia no
# pasan su cotejo (`active|on_hold`, fase 2 sin aprobar) y SIN donacion
# capturada: ahi Biblioteca no puede pasar a nadie a Caja (D19).
_SIN_DONACION_SQL = """
SELECT c.id, c.name, COUNT(DISTINCT p.id)
  FROM titulatec_cohorts c
  JOIN titulatec_processes p ON p.cohort_id = c.id
 WHERE c.book_donation_amount IS NULL
   AND p.status IN ('active', 'on_hold')
   AND NOT EXISTS (
       SELECT 1 FROM titulatec_process_phases ph
        WHERE ph.process_id = p.id AND ph.phase_number = 2 AND ph.status = 'approved'
   )
   AND EXISTS (
       SELECT 1 FROM titulatec_cotejo_requirements req
        WHERE req.cohort_id = c.id AND req.code = 'library_clearance'
   )
 GROUP BY c.id, c.name
 ORDER BY c.name, c.id
"""


def _precheck_activar_biblioteca() -> dict:
    """Pre-chequeos de SOLO LECTURA de `activar-biblioteca-caja` (Ruling R19).

    Devuelve `{"ocupantes": {codigo_de_puesto: N | None}, "sin_donacion":
    [{"cohort_id", "name", "pending"}], "problemas": [str, ...]}`:

    * cada puesto nuevo (`library_clearance_info_center`,
      `cashier_financial_resources`) con al menos UN ocupante vigente --
      `None` si el puesto ni existe (falta `init-biblioteca-caja`);
    * toda convocatoria que quedará con candado y tenga procesos admitidos
      sin la fase 2 aprobada, con `book_donation_amount` capturada.

    `problemas` vacío = se puede encender. Abre su PROPIA sesión
    (`SessionLocal`, import local) para que `patched_session_local` la
    intercepte en las pruebas; solo hace SELECT y la cierra (cerrar termina
    la transacción de lectura -- sin `rollback` explícito, que en las
    pruebas desharía los datos sembrados desde el último commit).
    """
    from sqlalchemy import text

    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        ocupantes: dict[str, int | None] = {code: None for code in _PUESTOS_BIBLIOTECA_CAJA}
        for code, n in db.execute(text(_OCUPANTES_SQL),
                                  {"codes": list(_PUESTOS_BIBLIOTECA_CAJA)}):
            ocupantes[code] = int(n)
        sin_donacion = [{"cohort_id": cid, "name": nombre, "pending": int(n)}
                        for cid, nombre, n in db.execute(text(_SIN_DONACION_SQL))]
    finally:
        db.close()

    problemas: list[str] = []
    for code in _PUESTOS_BIBLIOTECA_CAJA:
        if ocupantes[code] is None:
            problemas.append(
                f"puesto ausente: {code} (corre primero `titulatec init-biblioteca-caja`)")
        elif ocupantes[code] == 0:
            problemas.append(
                f"puesto {code} sin ocupante vigente: asígnalo en /itcj/config/positions "
                "antes de encender el candado (sin él nadie libera a nadie)")
    for c in sin_donacion:
        problemas.append(
            f"convocatoria «{c['name']}» (id {c['cohort_id']}) sin donación voluntaria de "
            f"libro y con {c['pending']} proceso(s) que aún no pasan su cotejo: Servicios "
            "Escolares debe capturarla (panel Resumen) o Biblioteca no podrá pasarlos a "
            "Caja (D19)")
    return {"ocupantes": ocupantes, "sin_donacion": sin_donacion, "problemas": problemas}


def _verify_candado_biblioteca() -> list[str]:
    """Comprueba que el 22 ATERRIZO (lo que corre `activar-biblioteca-caja`):
    NINGUNA fila `titulatec_cotejo_requirements` con `code='library_clearance'`
    se quedo sin `auto_source='library_clearance'`/`is_required=TRUE`/
    `is_active=TRUE` (el 22 las corrige TODAS, sin condicion sobre el valor
    anterior). Devuelve problemas, mismo contrato que los demas `_verify_*`."""
    por_encender, _total = _library_requirements_off()
    if por_encender:
        return [
            f"{por_encender} fila(s) de titulatec_cotejo_requirements con "
            "code='library_clearance' sin auto_source/is_required/is_active "
            "correctos (el 22_library_requirement_auto.sql no aterrizo)"
        ]
    return []


def _faltan_en_disco(nombres: list[str]) -> list[str]:
    """Los archivos de `biblioteca_2026_10/` de `nombres` que NO están en disco."""
    dml_dir = DML_TITULATEC / _DML_BIBLIOTECA_2026_10_DIR
    return [nombre for nombre in nombres if not (dml_dir / nombre).exists()]


def _abortar_con(problemas: list[str]) -> None:
    """Imprime cada problema en rojo (stderr) y sale distinto de 0."""
    click.echo()
    for p in problemas:
        click.echo(click.style(f"ERROR: {p}", fg="red"), err=True)
    raise click.Abort()


@titulatec_cli.command("init-biblioteca-caja")
@click.option("--dry-run", is_flag=True,
              help="Comprueba los archivos en disco y los lista, sin escribir nada.")
def init_biblioteca_caja_command(dry_run):
    """Paso 1 del despliegue de Biblioteca/Caja: puestos, roles y permisos.
    NO enciende el candado (eso es `activar-biblioteca-caja`, Ruling R19).

    Corre SOLO el 20, el 21 y el 23 de
    `database/DML/titulatec/biblioteca_2026_10/`
    (`_DML_BIBLIOTECA_2026_10_FILES`, D10 -- mismo patron que
    `init-posgrado`/`init-email-tasks`): produccion ya corrio
    `init-titulatec` y ese comando nunca se re-ejecuta alli, asi que este
    (con `activar-biblioteca-caja`) es el unico camino de despliegue para
    este delta -- ademas de sumarse a `SEED_FILES` para una instalacion desde
    cero, que si corre los cuatro de una vez.

    `20_insert_library_cashier_positions.sql` crea los 2 puestos NUEVOS
    (nacen SIN OCUPANTE: asignarlos es el paso siguiente del lanzamiento).
    `21_insert_library_cashier_roles_perms.sql` crea los roles
    `titulatec_library`/`titulatec_cashier`, el mapeo puesto→rol y los 10
    permisos con TODAS sus concesiones (incluido `admin` EXPLICITO: en
    produccion nunca se re-corre `15_grant_admin_all_perms.sql`).
    `23_update_email_reminders_description.sql` (m33, spec 2026-10-02 §6)
    pone al dia las dos descripciones de `titulatec.email_reminders`
    (`core_task_definitions` y su fila de `core_periodic_tasks`): ahora
    mencionan el recordatorio del pago pendiente en Caja. Solo UPDATE e
    idempotente; si la tarea todavia no esta sembrada (falta
    `init-email-tasks`), no hace nada y el 17 la sembrara ya con ese texto.

    Al terminar VERIFICA con `_verify_biblioteca_caja()` (los `RAISE NOTICE`
    del SQL son invisibles, mismo motivo que el resto de los `_verify_*` de
    este archivo): puestos, los 10 permisos, las concesiones EXACTAS de los
    2 roles nuevos, las concesiones nuevas de GTV/Servicios Escolares/admin y
    el mapeo puesto→rol. Aborta si algo no aterrizo. El 23 no se verifica
    (una base sin la tarea sembrada es valida). No toca convocatorias,
    requisitos ni filas de no adeudo: nadie queda bloqueado por correrlo.

    `--dry-run`: comprueba que los 3 archivos existen en disco y los lista,
    sin escribir nada.

    Despues: asignar ocupantes a «Biblioteca · No adeudo» y «Caja»
    (`/itcj/config/positions`), que Servicios Escolares capture la donacion
    de cada convocatoria que quedara con candado, y entonces
    `titulatec activar-biblioteca-caja --dry-run` (sus pre-chequeos dicen
    que falta).
    """
    faltan = _faltan_en_disco(_DML_BIBLIOTECA_2026_10_FILES)

    if dry_run:
        if faltan:
            click.echo(click.style(f"ERROR: faltan archivos en disco: {faltan}", fg="red"))
        else:
            click.echo("Archivos en disco: OK. Se ejecutarían:")
            for nombre in _DML_BIBLIOTECA_2026_10_FILES:
                click.echo(f"  {_DML_BIBLIOTECA_2026_10_DIR}/{nombre}")
        click.echo("[dry-run] El requisito automático (el candado) NO se toca aquí: "
                   "es `titulatec activar-biblioteca-caja`.")
        click.echo("Dry-run: no se ejecutó nada.")
        if faltan:
            raise click.Abort()
        return

    _run_sql_files(
        [f"{_DML_BIBLIOTECA_2026_10_DIR}/{nombre}" for nombre in _DML_BIBLIOTECA_2026_10_FILES]
    )

    problemas = _verify_biblioteca_caja()
    if problemas:
        _abortar_con(problemas)

    click.echo(click.style(
        "OK: 2 puestos, 2 roles, 10 permisos (88 → 98) con sus concesiones y "
        "mapeo puesto→rol verificados en la base. El candado sigue APAGADO.",
        fg="green",
    ))
    click.echo(
        "Descripción de titulatec.email_reminders al día (23), si la tarea ya "
        "estaba sembrada."
    )
    click.echo(
        "Siguiente: asignar ocupantes a «Biblioteca · No adeudo» y «Caja», capturar "
        "la donación de cada convocatoria con procesos por revisar y correr "
        "`titulatec activar-biblioteca-caja --dry-run`."
    )


@titulatec_cli.command("activar-biblioteca-caja")
@click.option("--dry-run", is_flag=True,
              help="Corre los pre-chequeos y cuenta lo que haría cada paso, sin escribir nada.")
@click.option("--force", is_flag=True,
              help="Enciende el candado AUNQUE fallen los pre-chequeos (ocupantes, donación).")
def activar_biblioteca_caja_command(dry_run, force):
    """Paso 2 del despliegue de Biblioteca/Caja: ENCIENDE el candado del no
    adeudo (Ruling R19). Desde que termina, nadie agenda ni es agendado sin no
    adeudo donde la convocatoria lo exige (salvo legado, quien ya pasó su
    cotejo y las citas ya agendadas, D17).

    1. Pre-chequeos de SOLO LECTURA (`_precheck_activar_biblioteca`): los 2
       puestos nuevos con al menos un ocupante vigente, y toda convocatoria
       que quedará con candado (tiene fila `code='library_clearance'`) con
       procesos que aún no pasan su cotejo y SIN donación capturada. Si algo
       falla, ABORTA (exit 1) listando lo que falta, sin escribir nada --
       salvo `--force`, que lo imprime como advertencia y sigue.
    2. `22_library_requirement_auto.sql` (`_DML_BIBLIOTECA_2026_10_ACTIVAR_
       FILES`): requisito `library_clearance` automático, obligatorio y
       activo en TODA convocatoria ya sembrada (y sus pistas, solo donde
       seguían en el default viejo).
    3. Re-backfill (`_library_clearance_rebackfill`, MISMO predicado que el
       backfill de `tt20261001a`): fila para los procesos creados en el
       blue/green. Idempotente.
    4. Promoción D17 (`_library_clearance_promote`, Ruling R20): `pending`
       sin tocar por Biblioteca -> `cleared/legacy` si su requisito ya está
       cumplido a mano o su fase 2 ya está aprobada. Idempotente, sin
       eventos.
    5. Folios de previas y legado (`_emitir_folios_previos`, spec
       `2026-10-05-titulatec-folios-design.md` §3.4): le saca su folio (GTV o
       BIB, del semestre ANTERIOR al de su fecha de registro) a toda previa
       y a todo `cleared/legacy` -el recién promovido incluido- que aún no
       tenga uno vigente (`FolioBackfillService.run`, UN commit). Va DESPUÉS
       de la promoción porque el legado nace ahí. Idempotente: es el mismo
       paso de `titulatec emitir-folios-previos`.
    6. Verificación (`_verify_candado_biblioteca`): ninguna fila
       `library_clearance` quedó sin el requisito automático. Aborta si algo
       no aterrizó.

    Imprime los conteos de cada paso. Correrlo dos veces no cambia nada la
    segunda (todos los pasos son idempotentes). `--dry-run`: pre-chequeos +
    lo que haría cada paso (requisitos por encender, filas del re-backfill,
    filas de la promoción, folios por emitir), sin escribir nada; sale
    distinto de 0 si faltan archivos o si los pre-chequeos fallan sin
    `--force` -- igual que la corrida real. Los folios del dry-run NO cuentan
    el legado que el re-backfill y la promoción crearían en la corrida real
    (el dry-run no escribe esas filas): la corrida real puede emitir más.

    Correrlo FUERA de horario y que Biblioteca haga ese mismo día su lote
    «Sin adeudo»: quien no tenga no adeudo liberado queda bloqueado desde
    este momento.
    """
    faltan = _faltan_en_disco(_DML_BIBLIOTECA_2026_10_ACTIVAR_FILES)
    pre = _precheck_activar_biblioteca()

    for code in _PUESTOS_BIBLIOTECA_CAJA:
        n = pre["ocupantes"][code]
        click.echo(f"Puesto {code}: "
                   + ("NO EXISTE" if n is None else f"{n} ocupante(s) vigente(s)"))
    click.echo(f"Convocatorias con candado sin donación y procesos por revisar: "
               f"{len(pre['sin_donacion'])}")
    for c in pre["sin_donacion"]:
        click.echo(f"  · {c['name']} (id {c['cohort_id']}): {c['pending']} proceso(s)")

    bloquea = bool(pre["problemas"]) and not force
    if pre["problemas"] and force:
        accion = "la corrida real encendería" if dry_run else "se enciende"
        click.echo(click.style(
            f"ADVERTENCIA: --force: {accion} el candado aunque fallen los pre-chequeos:",
            fg="yellow"))
        for p in pre["problemas"]:
            click.echo(click.style(f"  · {p}", fg="yellow"))

    if dry_run:
        if faltan:
            click.echo(click.style(f"ERROR: faltan archivos en disco: {faltan}", fg="red"))
        else:
            click.echo("Archivos en disco: OK. Se ejecutaría:")
            for nombre in _DML_BIBLIOTECA_2026_10_ACTIVAR_FILES:
                click.echo(f"  {_DML_BIBLIOTECA_2026_10_DIR}/{nombre}")
        por_encender, total = _library_requirements_off()
        click.echo(f"[dry-run] Requisitos de no adeudo por encender: {por_encender} "
                   f"de {total}")
        click.echo(f"[dry-run] Re-backfill: {_library_clearance_rebackfill(dry_run=True)} "
                   "fila(s) que crearía (pending/legacy)")
        click.echo(f"[dry-run] Promoción D17: {_library_clearance_promote(dry_run=True)} "
                   "fila(s) pending que pasarían a cleared/legacy")
        folios = _emitir_folios_previos(dry_run=True)
        click.echo(f"[dry-run] Folios de previas y legado: {sum(folios.values())} "
                   "folio(s) por emitir (sin contar el legado que el re-backfill y la "
                   "promoción crearían en la corrida real)")
        _echo_folios_por_tipo_y_semestre(folios)
        click.echo("Dry-run: no se ejecutó nada.")
        if bloquea:
            _abortar_con(pre["problemas"] + [
                "la corrida real abortaría: resuélvelo o pasa --force"])
        if faltan:
            raise click.Abort()
        return

    if faltan:
        _abortar_con([f"faltan archivos en disco: {faltan}"])
    if bloquea:
        _abortar_con(pre["problemas"] + [
            "no se encendió nada: resuélvelo o pasa --force"])

    por_encender, total = _library_requirements_off()
    _run_sql_files([f"{_DML_BIBLIOTECA_2026_10_DIR}/{nombre}"
                    for nombre in _DML_BIBLIOTECA_2026_10_ACTIVAR_FILES])
    click.echo(f"Requisito automático de no adeudo: {por_encender} fila(s) encendida(s) "
               f"de {total}.")

    creadas = _library_clearance_rebackfill(dry_run=False)
    click.echo(f"Re-backfill de no adeudo: {creadas} fila(s) creada(s) "
               "(pending/legacy) para procesos sin fila todavía.")

    promovidas = _library_clearance_promote(dry_run=False)
    click.echo(f"Promoción D17: {promovidas} fila(s) pending -> cleared/legacy "
               "(requisito ya cumplido a mano o fase 2 ya aprobada).")

    folios = _emitir_folios_previos(dry_run=False)
    click.echo(f"Folios de previas y legado: {sum(folios.values())} folio(s) emitido(s) "
               "(previas y legado sin folio vigente).")
    _echo_folios_por_tipo_y_semestre(folios)

    problemas = _verify_candado_biblioteca()
    if problemas:
        _abortar_con(problemas)

    click.echo(click.style(
        "OK: candado de no adeudo ENCENDIDO y verificado (requisito automático en "
        "toda convocatoria con la fila).",
        fg="green",
    ))


# ---------------------------------------------------------------------------
# Constancias previas (D9, spec 2026-10-01-titulatec-biblioteca-caja-design.md
# §4.12, Tarea 6): base de encuestas del semestre anterior (`--tipo encuesta`)
# o no adeudo de biblioteca ya pagado (`--tipo biblioteca`), por número de
# control. TODA la lógica vive en `PriorClearanceService.import_rows`; este
# comando solo lee el archivo y la imprime.
# ---------------------------------------------------------------------------
_IMPORT_PRIOR_ETIQUETAS = {
    "applied": "Aplicadas",
    "deferred": "Registradas para después",
    "already": "Ya liberadas",
    "conflicts": "Conflictos",
    "expired": "Vencidas",
    "invalid": "Inválidas",
}
_IMPORT_PRIOR_KIND = {"encuesta": "survey", "biblioteca": "library"}


@titulatec_cli.command("import-prior-clearances")
@click.argument("archivo", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--tipo", "tipo", type=click.Choice(["encuesta", "biblioteca"]),
              required=True,
              help="encuesta: liberación previa de GTV | biblioteca: no adeudo previo.")
@click.option("--fecha", "fecha_fija", default=None,
              help="Fecha de emisión para TODAS las filas, si el archivo no trae "
                   "columna (AAAA-MM-DD o DD/MM/AAAA, con hora opcional).")
@click.option("--columna-control", "columna_control", default=None,
              help="Encabezado de la columna del número de control "
                   "(si no se da, se autodetecta como en la importación de alumnos).")
@click.option("--columna-fecha", "columna_fecha", default=None,
              help="Encabezado de la columna con la fecha de emisión de cada fila.")
@click.option("--dry-run", is_flag=True, help="Solo clasifica cada fila; no escribe nada.")
def import_prior_clearances_command(archivo, tipo, fecha_fija, columna_control,
                                    columna_fecha, dry_run):
    """Carga constancias previas de no adeudo o de encuesta de egresados (D9).

    El egresado YA traía, de ANTES de este sistema, su liberación -otro
    semestre, en papel, en el sistema legado-: Servicios Escolares (o el
    desarrollador, para la base completa de encuestas del semestre anterior)
    entrega un CSV con el número de control y la fecha de emisión de cada
    constancia. Por fila (`PriorClearanceService.import_rows`):

    \b
    - con un proceso ABIERTO (activo/en pausa, fase 2 sin aprobar) para ese
      control -> se aplica YA (Aplicadas).
    - sin proceso -> se difiere; se aplica sola cuando el alumno se inscriba
      (Registradas para después).
    - ya estaba liberado -> Ya liberadas.
    - encuesta con una solicitud en revisión u observada -> Conflictos (lo
      decide GTV desde su bandeja, no esta CLI).
    - `issued_on` con más de 365 días -> Vencidas.
    - número de control o fecha inválidos -> Inválidas.

    La columna del número de control se autodetecta (mismo heurístico que la
    importación de alumnos) o se fija con `--columna-control`. La fecha sale
    de `--columna-fecha` (una por fila) o de `--fecha` (fija para todas);
    falta una de las dos -> error, sin leer ni clasificar ninguna fila. Formatos
    de fecha aceptados (Ruling R13): `AAAA-MM-DD`, `DD/MM/AAAA`, o cualquiera de
    los dos con hora (`15/03/2026 10:22:33`, como exporta Google Forms es-MX);
    cualquier otro formato cae en Inválidas con su motivo.

    `--dry-run`: clasifica TODO -incluida la búsqueda del proceso abierto-
    pero no escribe nada, ni siquiera un alta idempotente de la fila de
    biblioteca.

    `--fecha` y `--columna-fecha` son MUTUAMENTE EXCLUSIVAS: pasar las dos a
    la vez rechaza el comando (m16; antes `--columna-fecha` ganaba en
    silencio, sin avisar que `--fecha` se ignoraba).
    """
    from itcj2.apps.titulatec.services.import_service import ImportService
    from itcj2.apps.titulatec.services.prior_clearance_service import PriorClearanceService
    from itcj2.database import SessionLocal

    if columna_fecha and fecha_fija:
        raise click.UsageError(
            "No uses --fecha y --columna-fecha a la vez: --fecha fija la misma "
            "fecha para TODAS las filas y --columna-fecha trae una por fila; "
            "juntas, una de las dos se estaría ignorando en silencio. Elige una.")

    kind = _IMPORT_PRIOR_KIND[tipo]
    ruta = Path(archivo)
    headers, raw_rows = ImportService.parse(ruta.read_bytes())
    if not headers:
        raise click.ClickException(f"{archivo}: no se pudo leer ningún encabezado.")

    col_control = columna_control or ImportService.autodetect_mapping(headers).get(
        "control_number")
    if not col_control or col_control not in headers:
        raise click.ClickException(
            "No se pudo detectar la columna del número de control; "
            "pásala con --columna-control.")
    if columna_fecha and columna_fecha not in headers:
        raise click.ClickException(
            f"La columna de fecha {columna_fecha!r} no existe en el archivo.")
    if not columna_fecha and not fecha_fija:
        raise click.ClickException(
            "Falta la fecha de emisión: pasa --columna-fecha (una por fila) "
            "o --fecha AAAA-MM-DD (fija para todas las filas).")

    rows = [
        {"control_number": r.get(col_control, ""),
         "issued_on": (r.get(columna_fecha) if columna_fecha else fecha_fija)}
        for r in raw_rows
    ]

    db = SessionLocal()
    try:
        resultado = PriorClearanceService.import_rows(
            db, kind=kind, rows=rows, source=ruta.name, dry_run=dry_run)
    finally:
        db.close()

    prefijo = "[dry-run] " if dry_run else ""
    click.echo(f"{prefijo}{tipo}: {len(rows)} fila(s) de {ruta.name}.")
    for bote, etiqueta in _IMPORT_PRIOR_ETIQUETAS.items():
        filas = resultado[bote]
        click.echo(f"  {etiqueta}: {len(filas)}")
        for fila in filas:
            click.echo(f"    · {fila['control_number']}: {fila['reason']}")
    if dry_run:
        click.echo("Dry-run: no se escribió nada.")


# ---------------------------------------------------------------------------
# Folios de las previas y del legado (spec 2026-10-05-titulatec-folios-design.md
# §3.4, D5/D6). Las previas registradas desde la Tarea 2 de ese plan ya emiten su
# folio solas; esto cubre las que se registraron ANTES (las importadas de Forms
# en dev) y el no adeudo `cleared/legacy`, que escribe el SQL y no un service.
# TODA la lógica vive en `FolioBackfillService`; el comando solo la imprime y
# `activar-biblioteca-caja` la corre como su paso 5.
# ---------------------------------------------------------------------------
_FOLIOS_PREVIOS_ETIQUETAS = {
    "survey_release": "Encuesta (GTV)",
    "library_clearance": "No adeudo (BIB)",
}


def _emitir_folios_previos(dry_run: bool) -> dict[tuple[str, str], int]:
    """Folia las previas y el legado que aún no tienen folio vigente
    (`FolioBackfillService.run`) y devuelve el conteo por `(tipo, semestre)`.

    Abre su PROPIA sesion (import local de `SessionLocal`, convencion del
    proyecto) para que `patched_session_local` pueda interceptarla en los
    tests -- mismo patron que `_library_clearance_promote`. `dry_run=True`
    solo cuenta; `dry_run=False` emite y hace UN commit. Si algo falla, no
    queda ningun folio a medias: se deshace todo y se relanza el error.
    Idempotente: una segunda corrida devuelve un conteo vacio.
    """
    from itcj2.apps.titulatec.services.folio_backfill_service import FolioBackfillService
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        return FolioBackfillService.run(db, dry_run=dry_run)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _echo_folios_por_tipo_y_semestre(conteo: dict[tuple[str, str], int]) -> None:
    """Una línea por `(tipo, semestre)`: `  Encuesta (GTV) · 2026A: 372`."""
    for (kind, semestre), n in sorted(conteo.items()):
        click.echo(f"  {_FOLIOS_PREVIOS_ETIQUETAS.get(kind, kind)} · {semestre}: {n}")


@titulatec_cli.command("emitir-folios-previos")
@click.option("--dry-run", is_flag=True,
              help="Cuenta los folios que emitiría (por tipo y semestre); no escribe nada.")
def emitir_folios_previos_command(dry_run):
    """Emite el folio de las previas y del legado que aún no lo tienen.

    Lista toda liberación VIGENTE sin folio vigente de un proceso no
    `cancelled` -encuesta previa aprobada (`origin='prior'`) y no adeudo
    `cleared` por constancia previa o legado- y le saca su folio, sin emisor
    (`issued_by_id` NULL), en el semestre ANTERIOR al de su fecha de registro
    (registrada en 2026B da 2026A; D5/D6) y en orden de esa fecha, así que la
    numeración de cada semestre sigue el orden en que se registraron. Imprime
    los folios por tipo y semestre.

    \b
    - Las previas que se registren DESDE el código nuevo ya salen con su folio:
      esto es para las anteriores (p. ej. las importadas del Excel de Forms) y
      para el legado, que lo escribe el SQL, no un service.
    - Idempotente: una liberación con folio vigente no se toca, así que
      correrlo dos veces no emite nada la segunda. Un folio ANULADO no cuenta
      como vigente (nunca se reutiliza: sale uno nuevo).
    - `activar-biblioteca-caja` ya corre este mismo paso.

    `--dry-run`: solo cuenta; no escribe nada.
    """
    conteo = _emitir_folios_previos(dry_run)
    total = sum(conteo.values())
    prefijo = "[dry-run] " if dry_run else ""

    if not total:
        click.echo(f"{prefijo}No hay previas ni legado sin folio vigente: nada que emitir.")
    else:
        click.echo(f"{prefijo}Folios {'por emitir' if dry_run else 'emitidos'}: {total}")
        _echo_folios_por_tipo_y_semestre(conteo)
    if dry_run:
        click.echo("Dry-run: no se escribió nada.")


# ---------------------------------------------------------------------------
# Encuesta de egresados desde el Excel de Microsoft Forms (spec
# 2026-10-05-titulatec-import-encuesta-xlsx-design.md R1/§4.3). TODA la lógica
# vive en `SurveyImportService`; este comando lee el archivo y la imprime.
# ---------------------------------------------------------------------------
_IMPORT_SURVEY_ETIQUETAS = {
    "released": "Guardadas y liberadas",
    "deferred": "Guardadas, liberación diferida",
    "already_released": "Guardadas (ya liberadas)",
    "conflicts": "Guardadas (conflicto)",
    "saved_unreleased": "Guardadas sin liberar",
    "duplicates": "Duplicadas (no guardadas)",
    "already_imported": "Ya importadas",
    "invalid": "Inválidas (no guardadas)",
}


@titulatec_cli.command("import-survey-xlsx")
@click.argument("archivo", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--hoja", "hoja", default="Sheet1", show_default=True,
              help="Hoja del libro con las respuestas de Forms.")
@click.option("--dry-run", is_flag=True,
              help="Clasifica cada fila (incluida la liberación); no escribe nada.")
def import_survey_xlsx_command(archivo, hoja, dry_run):
    """Importa la encuesta de egresados desde el Excel de Microsoft Forms.

    Guarda cada respuesta (marcada como importada) ligada a su pregunta de la
    encuesta `egresados` abierta, y libera al egresado por la maquinaria de
    constancias previas (fecha = «Completion time»; Id en naranja = constancia
    en papel por recoger).

    \b
    - Guardadas y liberadas: tenía proceso abierto; se liberó y se ligó.
    - Guardadas, liberación diferida: sin proceso; se libera al inscribirse.
    - Guardadas (ya liberadas): ya tenía liberación (se le liga la respuesta
      si era una previa sin respuesta).
    - Guardadas (conflicto): ya envió la encuesta aquí o GTV revocó; lo decide GTV.
    - Guardadas sin liberar: control inválido/vacío o constancia vencida.
    - Duplicadas: mismo control repetido; solo se importa la más reciente.
    - Ya importadas: re-correr el archivo no duplica nada.
    - Inválidas (no guardadas): «Completion time» vacío o ilegible.

    Un encabezado desconocido o faltante aborta sin escribir nada.
    """
    from zipfile import BadZipFile

    from openpyxl.utils.exceptions import InvalidFileException
    from sqlalchemy.exc import IntegrityError

    from itcj2.apps.titulatec.services.survey_import_service import SurveyImportService
    from itcj2.database import SessionLocal

    ruta = Path(archivo)
    try:
        rows = SurveyImportService.read_xlsx(ruta.read_bytes(), sheet=hoja)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    except (BadZipFile, InvalidFileException):
        raise click.ClickException(
            f"{ruta.name} no es un libro .xlsx válido (¿archivo dañado o de otro "
            "formato? Expórtalo de nuevo desde Forms).") from None

    db = SessionLocal()
    stats: dict = {}
    try:
        resultado = SurveyImportService.import_rows(
            db, rows, source=ruta.name, dry_run=dry_run, stats=stats)
    except ValueError as exc:
        db.rollback()
        raise click.ClickException(str(exc)) from None
    except IntegrityError:
        db.rollback()
        raise click.ClickException(
            "Otra importación guardó estas mismas respuestas al mismo tiempo; no se "
            "escribió nada en esta corrida. Vuelve a correrla: lo ya guardado saldrá "
            "como «Ya importadas».") from None
    finally:
        db.close()

    prefijo = "[dry-run] " if dry_run else ""
    click.echo(f"{prefijo}encuesta de egresados: {len(rows)} fila(s) de {ruta.name} "
               f"(hoja {hoja}).")
    for bote, etiqueta in _IMPORT_SURVEY_ETIQUETAS.items():
        filas = resultado[bote]
        click.echo(f"  {etiqueta}: {len(filas)}")
        for fila in filas:
            click.echo(f"    · {fila['control_number']} (Id {fila['ms_id']}): "
                       f"{fila['reason']}")
    click.echo(f"  Celdas guardadas: {stats.get('cells', 0)} · con valor original "
               f"(raw): {stats.get('raw', 0)} · ocultas con valor real (guardadas; "
               f"informativo): {stats.get('hidden_kept', 0)}")
    if dry_run:
        click.echo("Dry-run: no se escribió nada.")


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
    for aviso in rs.advisories():
        click.echo(click.style(f"Advertencia: {aviso}", fg="yellow"))
    click.echo(click.style("OK: reglas válidas. (Las columnas de los mensajes se "
                           "verifican al ejecutar: usa sii-check.)", fg="green"))


_SII_STATUS_LABEL = {"apt": "APTA", "not_apt": "NO APTA", "error": "ERROR"}

# `nip_status` (`EligibilityService.classify_sii_nip`) → texto de `sii-check`.
# `None` = no se revisó (veredicto `error`), como en la consulta.
_SII_NIP_LABEL = {
    "available": "disponible",
    "missing": "no tiene",
    "invalid": "formato inválido",
    "unavailable": "no se pudo leer (el SII no respondió)",
    "error": "error de configuración",
    None: "sin revisar",
}
# El NIP no serviría para crear la cuenta: `sii-check` no pasa en verde.
_SII_NIP_FAILS = ("invalid", "unavailable", "error")


def _sii_cohort_outcome(cohort_id: int, control: str, nip_status: str | None) -> None:
    """Imprime lo que vería Servicios Escolares en «Por revisar» de esa
    convocatoria (spec 2026-09-27 §A7). Solo lectura (rollback).

    Ninguna se aprueba sola: con cualquier veredicto la decide SE. El botón
    sale de «¿tiene cuenta?» (contra `core_users` ahora, como al aprobar) y del
    estado del NIP, con la MISMA decisión que la bandeja
    (`EnrollmentRequestService.approval_path` + `APPROVAL_LABELS`, Ruling R8).
    Un control que no cumple `CONTROL_NUMBER_RE` no se busca en `core_users`
    (mismo corte que `EligibilityService.check` y la aprobación): cuenta como
    sin cuenta."""
    from itcj2.apps.titulatec.models import Cohort
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        APPROVAL_LABELS, EnrollmentRequestService,
    )
    from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE
    from itcj2.core.models.user import User
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        cohort = db.get(Cohort, cohort_id)
        if cohort is None:
            _sii_fail(f"No existe la convocatoria {cohort_id}.")
        tiene_cuenta = (CONTROL_NUMBER_RE.fullmatch(control) is not None
                        and db.query(User.id).filter_by(control_number=control)
                        .first() is not None)
        boton = APPROVAL_LABELS[EnrollmentRequestService.approval_path(tiene_cuenta, nip_status)]
        click.echo(f"Convocatoria: {cohort.name} (id {cohort.id}, {cohort.status})")
        click.echo(f"Cuenta: {'sí' if tiene_cuenta else 'no'}")
        click.echo(f"  → En «Por revisar», Servicios Escolares vería: {boton}")
    finally:
        db.rollback()
        db.close()


@titulatec_cli.command("sii-check")
@click.argument("control_number")
@click.option("--cohort", "cohort_id", type=int, default=None,
              help="Muestra además qué pasaría en esa convocatoria (solo lectura).")
def sii_check_command(control_number, cohort_id):
    """Dry-run: evalúa las reglas del SII para un número de control.

    Imprime el resultado por regla, los hechos, la identidad y el estado del
    NIP (`classify_sii_nip`; el valor siempre enmascarado): el que guardaría
    la consulta para una persona SIN cuenta. Aquí se pregunta siempre,
    aunque el control ya tenga cuenta (la consulta, en ese caso, ni lo pide y
    guarda `not_needed`). Con `--cohort`, el botón que vería Servicios
    Escolares. No escribe nada. Sale 1 ante `error` o un NIP que no serviría
    para crear la cuenta (formato inválido, SII sin respuesta, `[credential]`
    mal configurada).
    """
    import time

    from itcj2.apps.titulatec.services.eligibility_service import (
        EligibilityService, nip_failure,
    )
    from itcj2.apps.titulatec.services.sii.client import SiiConfig, get_sii_client
    from itcj2.apps.titulatec.services.sii.errors import SiiError, SiiRulesError
    from itcj2.apps.titulatec.services.sii.rules import RuleSet

    classify = EligibilityService.classify_sii_nip
    control = control_number.strip().upper()
    rules_dir = SiiConfig.rules_dir()
    try:
        rs = RuleSet.load(rules_dir)
        sii = get_sii_client()
    except SiiError as exc:
        _sii_fail(str(exc))

    t0 = time.monotonic()
    nip_status = None          # sin revisar, como la consulta con veredicto `error`
    with sii:
        verdict = rs.evaluate(sii, control)
        if verdict.status == "error":
            nip_detail = "no consultado (la evaluación falló)"
        elif not rs.has_credential:
            nip_status = classify(None, None)
            nip_detail = "sin NIP (las reglas no declaran [credential])"
        else:
            # El mensaje de estas excepciones ya viene sin el NIP: la consulta
            # va en modo sensible y el motor solo nombra columnas.
            try:
                # El `Secret` se clasifica y se descarta en esta misma línea.
                nip_status = classify(rs.fetch_credential(sii, control), None)
            except SiiRulesError as exc:
                nip_status = classify(None, nip_failure(exc))
                nip_detail = f"error en las reglas ({exc})"
            except SiiError as exc:
                nip_status = classify(None, nip_failure(exc))
                nip_detail = f"no se pudo consultar ({exc})"
            else:
                # Solo el formato, jamás el valor. Con otro formato la cuenta no
                # se podría crear al aprobarla: no pasa en verde.
                nip_detail = {
                    "available": "**** (el SII lo devuelve · 4 dígitos: sí)",
                    "invalid": ("**** (el SII lo devuelve · 4 dígitos: no — con ese "
                                "formato no se puede crear la cuenta)"),
                    "missing": "sin NIP (el SII no lo devuelve)",
                }[nip_status]
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
    click.echo(f"NIP: {_SII_NIP_LABEL[nip_status]} — {nip_detail}")
    click.echo(f"Duración: {ms} ms")

    if cohort_id is not None:
        _sii_cohort_outcome(cohort_id, control, nip_status)
    if verdict.status == "error" or nip_status in _SII_NIP_FAILS:
        raise SystemExit(1)


@titulatec_cli.command("sii-sweep")
@click.option("--cohort", "cohort_id", type=int, default=None,
              help="Solo las solicitudes de esa convocatoria.")
@click.option("--reconsultar-errores", "reconsultar_errores", is_flag=True,
              help="En vez del barrido: encola una consulta forzada para toda "
                   "solicitud por revisar cuya consulta vigente sea un error "
                   "(de configuración o en el tope de intentos) o esté colgada. "
                   "Úsalo tras corregir las reglas o la conexión.")
def sii_sweep_command(cohort_id, reconsultar_errores):
    """Barrido manual del SII (lo mismo que la tarea periódica `sii_sweep`).

    Consulta las solicitudes por revisar que no tienen consulta y reintenta las
    fallidas. No aprueba nada (eso es de Servicios Escolares, desde la bandeja).
    Solo en el modo `sii`. ESCRIBE en la BD (las consultas); imprime solo los
    conteos.

    Con `--reconsultar-errores` solo ENCOLA reconsultas forzadas de lo que el
    barrido ya no toma (`EligibilityService.recheck_errors`); las hace el
    worker de celery.

    Con el SII sin configurar (`TITULATEC_SII_BACKEND=disabled`, spec
    2026-09-27 D11) el servicio no consulta ni encola nada: se avisa y sale 0.
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
        if reconsultar_errores:
            out = EligibilityService.recheck_errors(db, cohort_id=cohort_id)
        else:
            out = EligibilityService.sweep(db, cohort_id=cohort_id)
    finally:
        db.close()
    if out.get("disabled"):
        click.echo(click.style(
            "El SII no está configurado (TITULATEC_SII_BACKEND=disabled); "
            "no se consultó nada.", fg="yellow"))
        return
    if reconsultar_errores:
        click.echo(f"Reconsultas encoladas: {out['queued']}")
        if out["failed"]:
            click.echo(click.style(
                f"No se pudo encolar: {out['failed']} (¿broker caído?). Vuelve a "
                "correr el comando.", fg="yellow"))
        return
    click.echo(f"Consultadas: {out['checked']} · reintentadas: {out['retried']}")
