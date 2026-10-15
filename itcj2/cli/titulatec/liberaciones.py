"""Constancias previas y sus folios: import-prior-clearances y emitir-folios-previos.

Los helpers de folios (`_emitir_folios_previos`, `_echo_folios_por_tipo_y_semestre`)
viven en `_common`: también los corre `activar-biblioteca-caja` (su paso 5).
"""
from pathlib import Path

import click

from itcj2.cli.titulatec._common import (
    _echo_folios_por_tipo_y_semestre,
    _emitir_folios_previos,
    titulatec_cli,
)

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
    - `issued_on` fuera de su semestre y los 2 siguientes -> Vencidas.
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
