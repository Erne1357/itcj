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
    titulatec init-ajustes-2026-10 [--dry-run]  Liberados para SE; Titulación: Liberados + expediente resumido (16 exactos); «Constancia de no adeudo de biblioteca».
    titulatec audit-backfill-solicitudes [--dry-run]  Recupera en la bitácora las decisiones de solicitudes previas a ella (idempotente).
    titulatec init-especialidades [--dry-run]  Especialidades de la encuesta de egresados por carrera (retículas 2014+).
    titulatec fix-control-l [--dry-run] [--sin-correo] [--solicitud ID]  Quita la «L» de licenciatura y emite folios faltantes.
    titulatec exportar-sin-cuenta [--salida RUTA]  Solicitudes vivas sin cuenta (CSV para pedir los NIP al SII).
    titulatec cargar-nips ARCHIVO --actor USUARIO [--dry-run] [--sin-correo]  Carga los NIP del SII (acceso o guardado cifrado).
    titulatec purgar-nips [--dry-run]  Borra los NIP precargados que ya no se pueden usar (solo imprime el conteo).
    titulatec exportar-controles [--salida RUTA]  Controles con solicitud no rechazada o proceso (CSV para pedir los promedios al SII).
    titulatec cargar-promedios ARCHIVO --actor USUARIO [--dry-run]  Carga los promedios oficiales (los aplica a los procesos existentes).
    titulatec init-reemplazo-docs [--dry-run]  Permiso para pedir reemplazo de un documento en cotejo (jefa de SE y admin).
"""
import logging
from pathlib import Path

import click

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
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
    # --- Delta 2026-10-06: pestaña «Correos» (bandeja de salida) -----------
    # El permiso `titulatec.email_outbox.page.list` (solo lectura del outbox)
    # concedido SOLO al rol `admin`, explicito porque en produccion el 15 no
    # se re-corre. Inserta un permiso, asi que va ANTES del 15. Tambien corre
    # SOLO con `titulatec init-outbox-admin` (mismo patron D10 que
    # `init-email-tasks`): es el unico camino de despliegue en produccion.
    "outbox_2026_10/24_insert_email_outbox_perm.sql",
    # --- Delta 2026-10-07: bitacora de auditoria. El permiso
    # `titulatec.audit.page.list` concedido SOLO al rol `admin`, explicito
    # porque en produccion el 15 no se re-corre (mismo patron que el 24).
    # Inserta un permiso, asi que va ANTES del 15. Tambien corre SOLO con
    # `titulatec init-bitacora`.
    "audit_2026_10/25_insert_audit_perm.sql",
    # --- Delta 2026-10-08: especialidades de la encuesta de egresados por
    # carrera (opciones con `group`, reticulas 2014+ del SII). Reescribe SOLO
    # las opciones de `especialidad` del formulario abierto que siembra el 11,
    # asi que va DESPUES del 11; no inserta permisos. Tambien corre SOLO con
    # `titulatec init-especialidades` (produccion: el 11 nunca se re-corre).
    "survey_2026_10/26_especialidades_por_carrera.sql",
    # --- Delta 2026-10-14: Tablero de la jefa de Servicios Escolares. El permiso
    # `titulatec.reports.page.view` para `titulatec_school_services_head` y `admin`
    # (explicito). Inserta un permiso, asi que va ANTES del 15. Tambien corre SOLO
    # con `titulatec init-reportes` (que NO re-corre el 15).
    "reportes_2026_10/26_insert_reports_perm.sql",
    # --- Delta 2026-10-15: reemplazo de documentos en cotejo. El permiso
    # `titulatec.document.api.request_replacement` para la jefa de SE y `admin`
    # (explicito). Inserta un permiso, asi que va ANTES del 15. Tambien corre SOLO
    # con `titulatec init-reemplazo-docs`.
    "reemplazo_2026_10/27_insert_doc_replacement_perm.sql",
    # El 15 va SIEMPRE AL FINAL: concede DINÁMICAMENTE (SELECT sobre
    # core_permissions, sin listar códigos) todos los permisos de titulatec al
    # rol 'admin' y le da ese rol al usuario `username='admin'`. Tiene que
    # correr después de CUALQUIER archivo que inserte permisos (02, 07, 08,
    # survey_2026_09/09, biblioteca_2026_10/21, outbox_2026_10/24 y
    # audit_2026_10/25) para que "todos" sea de
    # verdad todos. Solo concede (ON CONFLICT DO NOTHING): re-correrlo nunca
    # revoca nada.
    "15_grant_admin_all_perms.sql",
]


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


# Comandos de SOLO lectura que no dejan rastro en la bitácora (spec 2026-10-07 §6).
_AUDIT_EXCLUDED_COMMANDS = frozenset({"sii-ping", "sii-rules-validate"})


def _cli_user() -> str:
    """Usuario del SO que lanzó el comando (en un contenedor sin /etc/passwd
    para su uid, `getpass` truena: cae a «?»)."""
    import getpass

    try:
        return getpass.getuser()
    except Exception:
        return "?"


# Colas que SQLAlchemy pega al texto de sus errores: la sentencia y sus
# parámetros (un número de control, un `password_hash`). Nunca a la bitácora.
_ERROR_TAILS = ("[SQL:", "[parameters:")


def _cli_error_text(error: BaseException) -> str:
    """Clase + PRIMERA línea del mensaje del error, para `system.cli_command`.

    El texto crudo de un error de la BD trae `DETAIL: Key (...)=(...)` en la
    segunda línea y `[SQL: ...]`/`[parameters: ...]` al final: con la primera
    línea, recortada desde esas marcas, no sale nada de eso (revisión final
    M3). Luego la máscara D9: un mensaje que nombra un secreto (NIP,
    contraseña, token, hash) se guarda como "***". Nunca truena.
    """
    from itcj2.apps.titulatec.services.audit_actions import is_sensitive_key
    from itcj2.apps.titulatec.services.audit_service import MASK, AuditService

    clase = type(error).__name__
    try:
        texto = str(error)
    except Exception:
        texto = ""
    for marca in _ERROR_TAILS:
        corte = texto.find(marca)
        if corte >= 0:
            texto = texto[:corte]
    lineas = [ln.strip() for ln in texto.strip().splitlines() if ln.strip()]
    mensaje = lineas[0] if lineas else ""
    if mensaje and is_sensitive_key(mensaje):
        mensaje = MASK
    return AuditService.safe(f"{clase}: {mensaje}"[:300] if mensaje else clase)


def _record_cli_command(name: str, params: dict, status: str, duration_ms: int,
                        error: BaseException | None) -> None:
    """Escribe `system.cli_command` y lo commitea, con la MISMA fábrica de
    sesiones que usan los comandos (`itcj2.database.SessionLocal`, import local:
    los tests la parchean). Es una de las dos excepciones a «la bitácora no
    commitea» (D8). Nunca levanta: una bitácora caída no tumba el comando."""
    from itcj2.apps.titulatec.services.audit_service import AuditService
    from itcj2.database import SessionLocal

    payload = {
        "command": name,
        "status": status,
        "duration_ms": duration_ms,
        "params": AuditService.safe(params),
    }
    if error is not None:
        payload["error"] = _cli_error_text(error)
    try:
        db = SessionLocal()
        try:
            AuditService.record(db, "system.cli_command", entity_type="cli_command",
                                payload=payload)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception:
        logger.exception("bitácora: no se pudo registrar el comando %s", name)


class _AuditedCommand(click.Command):
    """Comando cuyo `invoke` corre dentro de un contexto `cli` de la bitácora y
    deja una fila `system.cli_command` (ok / error) al terminar."""

    def invoke(self, ctx):
        import time

        from itcj2.apps.titulatec.services.audit_context import audit_context

        name = self.name or ctx.info_name or "?"
        # Solo se audita al entrar POR EL GRUPO: invocar la función del comando
        # suelta (los tests, `CliRunner().invoke(cmd)`) no deja fila.
        por_el_grupo = ctx.parent is not None and isinstance(ctx.parent.command, _AuditedGroup)
        if not por_el_grupo or name in _AUDIT_EXCLUDED_COMMANDS:
            return super().invoke(ctx)

        started = time.monotonic()
        error: BaseException | None = None
        status = "ok"
        with audit_context("cli", label=f"cli: {name} ({_cli_user()})"):
            try:
                return super().invoke(ctx)
            except BaseException as exc:  # se re-lanza SIEMPRE
                code = getattr(exc, "exit_code", getattr(exc, "code", None))
                if isinstance(exc, (click.exceptions.Exit, SystemExit)) and code in (0, None):
                    pass
                else:
                    status, error = "error", exc
                raise
            finally:
                _record_cli_command(
                    name, dict(ctx.params), status,
                    int((time.monotonic() - started) * 1000), error)


class _AuditedGroup(click.Group):
    """Grupo cuyos comandos nacen auditados (`_AuditedCommand`)."""
    command_class = _AuditedCommand


@click.group("titulatec", cls=_AuditedGroup)
def titulatec_cli():
    """Comandos de inicialización de la app de TitulaTec."""


def _abortar_con(problemas: list[str]) -> None:
    """Imprime cada problema en rojo (stderr) y sale distinto de 0."""
    click.echo()
    for p in problemas:
        click.echo(click.style(f"ERROR: {p}", fg="red"), err=True)
    raise click.Abort()


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


# ---------------------------------------------------------------------------
# NIPs del SII precargados (spec 2026-10-13-titulatec-nip-precargado-design.md §5.3)
# ---------------------------------------------------------------------------
_NIPS_COLUMNAS_CONTROL = {"control", "no_control", "numero_control", "numero_de_control",
                          "num_control", "n_control", "no._control"}


def _leer_dos_columnas(ruta: Path, valor: str, alias_valor: set[str], *,
                       estricto: bool = False) -> list[tuple[str, str]]:
    """Lee `(control, <valor>)` de un CSV/TXT con encabezado. Acepta BOM (Excel),
    `,` `;` o tabulador, y `no_control`/`numero_control` como encabezado del
    control. La celda del valor se deja TAL CUAL: validarla es del servicio.
    `ClickException` si falta una columna.

    `estricto`: una fila con MÁS celdas que el encabezado se devuelve con el
    valor roto a propósito (las celdas sobrantes pegadas con un espacio). Es lo
    que pasa con «85,5» sin comillas en un CSV separado por comas: sin esto se
    leería «85» y el «5» se perdería en silencio."""
    import csv
    import io
    import unicodedata

    texto = ruta.read_bytes().decode("utf-8-sig", errors="replace")
    primera = texto.splitlines()[0] if texto.strip() else ""
    delim = max(("\t", ";", ","), key=primera.count)
    lector = csv.reader(io.StringIO(texto), delimiter=delim)

    def _norm(h: str) -> str:
        sin = unicodedata.normalize("NFKD", h or "").encode("ascii", "ignore").decode()
        return sin.strip().lower().replace(" ", "_")

    encabezado = [_norm(h) for h in next(lector, [])]
    i_control = next((i for i, h in enumerate(encabezado)
                      if h in _NIPS_COLUMNAS_CONTROL), None)
    i_valor = next((i for i, h in enumerate(encabezado) if h in alias_valor), None)
    if i_control is None or i_valor is None:
        raise click.ClickException(
            f"El archivo necesita un encabezado con las columnas «control» y «{valor}» "
            "(también vale «no_control» o «numero_control»).")
    filas = []
    for r in lector:
        if not any((c or "").strip() for c in r):
            continue
        celda = r[i_valor] if i_valor < len(r) else ""
        if estricto and any((c or "").strip() for c in r[len(encabezado):]):
            celda = " ".join([celda, *r[len(encabezado):]])
        filas.append((r[i_control] if i_control < len(r) else "", celda))
    return filas
