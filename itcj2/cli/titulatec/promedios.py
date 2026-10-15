"""Promedios oficiales del SII: exportar-controles y cargar-promedios."""
from pathlib import Path

import click

from itcj2.cli.titulatec._common import _leer_dos_columnas, titulatec_cli

# ---------------------------------------------------------------------------
# Promedios oficiales (spec 2026-10-13-titulatec-promedios-design.md §5)
# ---------------------------------------------------------------------------
_PROMEDIOS_ALIAS = {"promedio", "promedio_final", "promedio_oficial", "promedio_general"}
_PROMEDIOS_ETIQUETAS = {
    "applied": "Aplicados a su proceso",
    "stored": "Guardados (aún sin proceso)",
    "updated": "Actualizados (antes → después)",
    "same": "Sin cambio",
    "no_request": "Sin solicitud ni proceso",
    "out_of_range": "Fuera de rango (70-100)",
    "invalid": "Formato inválido",
    "duplicate": "Duplicados",
}


@titulatec_cli.command("exportar-controles")
@click.option("--salida", "salida", type=click.Path(dir_okay=False, path_type=Path),
              default=None, help="Archivo CSV de salida (por omisión, la pantalla).")
def exportar_controles_command(salida):
    """Lista los controles a los que se les puede cargar un promedio oficial.

    Es la lista que se lleva al SII para pedir los promedios: controles con
    alguna solicitud NO rechazada o con proceso (uno por control; nombre y
    estado de su solicitud más reciente no rechazada). `promedio_actual` es el
    valor ya guardado, vacío si no hay.
    """
    import csv
    import io

    from itcj2.apps.titulatec.models import (
        EnrollmentRequest, OfficialAverage, TitulationProcess,
    )
    from itcj2.apps.titulatec.services.import_service import normalize_control
    from itcj2.core.models.program import Program
    from itcj2.core.models.user import User
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        # De la más vieja a la más nueva: la última solicitud pisa a las
        # anteriores, y una no rechazada pisa a cualquier rechazada.
        solicitud: dict[str, tuple] = {}
        for req, programa in (db.query(EnrollmentRequest, Program.name)
                              .outerjoin(Program, Program.id == EnrollmentRequest.program_id)
                              .order_by(EnrollmentRequest.id).all()):
            control = normalize_control(req.control_number)
            previa = solicitud.get(control)
            if req.status == "rejected" and previa is not None and previa[0].status != "rejected":
                continue
            solicitud[control] = (req, programa)
        proceso: dict[str, tuple] = {}
        for user, proc, programa in (
                db.query(User, TitulationProcess, Program.name)
                .join(TitulationProcess, TitulationProcess.student_id == User.id)
                .outerjoin(Program, Program.id == TitulationProcess.program_id)
                .filter(TitulationProcess.status != "cancelled",
                        User.control_number.isnot(None))
                .order_by(TitulationProcess.id).all()):
            proceso[normalize_control(user.control_number)] = (user, proc, programa)
        guardados = {c: a for c, a in db.query(OfficialAverage.control_number,
                                               OfficialAverage.average).all()}
    finally:
        db.close()

    controles = {c for c, (req, _p) in solicitud.items() if req.status != "rejected"}
    controles |= set(proceso)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["control", "nombre", "apellidos", "carrera", "estado", "tiene_proceso",
                "promedio_actual"])
    for control in sorted(controles):
        # Con solicitud (no rechazada) manda ella; sin ella, el alumno y su proceso.
        if control in solicitud and solicitud[control][0].status != "rejected":
            req, programa = solicitud[control]
            nombre, estado = req.first_name, req.status
            apellidos = " ".join(x for x in (req.last_name, req.middle_name) if x)
            carrera = req.program_text or programa or ""
        else:
            user, proc, programa = proceso[control]
            nombre, estado = user.first_name, proc.status
            apellidos = " ".join(x for x in (user.last_name, user.middle_name) if x)
            carrera = programa or ""
        actual = guardados.get(control)
        w.writerow([control, nombre, apellidos, carrera, estado,
                    "si" if control in proceso else "no",
                    "" if actual is None else f"{actual:.2f}"])

    if salida is None:
        click.echo(buf.getvalue(), nl=False)
        return
    # `utf-8-sig`: ver `exportar-sin-cuenta`.
    with open(salida, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write(buf.getvalue())
    click.echo(f"{len(controles)} control(es) escritos en {salida}.")


@titulatec_cli.command("cargar-promedios")
@click.argument("archivo", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--actor", "actor", required=True,
              help="Usuario (username) que queda como autor de la carga.")
@click.option("--dry-run", is_flag=True, help="Solo clasifica cada fila; no escribe nada.")
def cargar_promedios_command(archivo, actor, dry_run):
    """Carga los promedios oficiales del SII por número de control.

    El archivo trae las columnas `control` y `promedio` (CSV de Excel con BOM,
    `;` o tabulador; el promedio con punto o coma decimal). Cada promedio se
    guarda y, si el alumno ya tiene proceso, se copia a `final_average`; si
    todavía no lo tiene (pero sí solicitud) se aplica solo al crearse el proceso.
    Volver a cargar un control actualiza su valor. Un solo commit al final.

    Con `,` como separador la coma decimal NO sirve sin comillas («85,5» parte
    la fila): esas filas salen como «Formato inválido» y no se cargan.
    """
    from itcj2.apps.titulatec.services.official_average_service import (
        LOAD_BUCKETS, OfficialAverageService,
    )
    from itcj2.core.models.user import User
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        usuario = db.query(User).filter(User.username == actor).first()
        if usuario is None:
            click.echo(click.style(f"ERROR: no existe el usuario {actor!r} (--actor).",
                                   fg="red"), err=True)
            raise SystemExit(1)
        filas = _leer_dos_columnas(Path(archivo), "promedio", _PROMEDIOS_ALIAS,
                                   estricto=True)
        try:
            resultado = OfficialAverageService.load_rows(
                db, filas, actor_id=usuario.id, dry_run=dry_run)
            # En dry-run `load_rows` ya deshizo cada savepoint: no hay nada
            # que commitear y `close()` suelta la transacción.
            if not dry_run:
                db.commit()
        except Exception:
            db.rollback()
            raise
    finally:
        db.close()

    # Ninguna fila aterrizó: casi seguro es el archivo (separador, encabezado,
    # coma decimal), no los datos. No debe verse como una corrida normal.
    nada = bool(filas) and not any(
        resultado[k] for k in ("applied", "stored", "updated", "same"))
    if nada:
        click.secho(
            "Ninguna fila requiere cambios o todas fueron rechazadas: revisa el "
            "detalle abajo. Si esperabas cargas, revisa separador/encabezados.",
            fg="red", bold=True, err=True)
    prefijo = "[dry-run] " if dry_run else ""
    click.echo(f"{prefijo}{len(filas)} fila(s) de {Path(archivo).name}.")
    for bucket in LOAD_BUCKETS:
        items = resultado[bucket]
        click.echo(f"  {_PROMEDIOS_ETIQUETAS[bucket]}: {len(items)}")
        for control, motivo in items:
            click.echo(f"    · {control}" + (f": {motivo}" if motivo else ""))
    if dry_run:
        click.echo("Dry-run: no se escribió nada.")
    if nada:
        raise SystemExit(1)
