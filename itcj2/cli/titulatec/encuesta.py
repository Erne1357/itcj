"""Encuesta de egresados: load-survey-2026-09 (delta de septiembre) e import-survey-xlsx (Forms)."""
from pathlib import Path

import click

from itcj2.cli.titulatec._common import DML_TITULATEC, titulatec_cli
from itcj2.cli.titulatec.verificaciones import _verify_survey_2026_09

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
    constancias previas (fecha = «Completion time» / «Hora de finalización»;
    Id en naranja = constancia en papel por recoger). Acepta el Excel de Forms
    exportado en inglés o en español. Vigencia: el semestre de la respuesta y
    los 2 siguientes.

    \b
    - Guardadas y liberadas: tenía proceso abierto; se liberó y se ligó.
    - Guardadas, liberación diferida: sin proceso; se libera al inscribirse.
    - Guardadas (ya liberadas): ya tenía liberación (se le liga la respuesta
      si era una previa sin respuesta).
    - Guardadas (conflicto): ya envió la encuesta aquí o GTV revocó; lo decide GTV.
    - Guardadas sin liberar: control inválido/vacío o constancia vencida.
    - (diferida) «ya tenía una liberación pendiente más nueva»: se conserva
      esa; esta respuesta se guarda pero no la reemplaza.
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
