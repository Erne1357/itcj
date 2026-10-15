"""NIPs del SII precargados (spec 2026-10-13-titulatec-nip-precargado-design.md §5.3).

Comandos: exportar-sin-cuenta, cargar-nips y purgar-nips. El lector de CSV
(`_leer_dos_columnas`) vive en `_common`: también lo usa `cargar-promedios`.
"""
from pathlib import Path

import click

from itcj2.cli.titulatec._common import _leer_dos_columnas, titulatec_cli

_NIPS_ETIQUETAS = {
    "granted": "Acceso dado ahora",
    "stored": "Guardados para la aprobación",
    "stored_rejected": "Guardados (solicitud rechazada)",
    "has_account": "Ya tienen cuenta",
    "no_request": "Sin solicitud",
    "invalid_nip": "NIP inválido",
    "duplicate": "Duplicados",
    "failed": "Fallaron",
}


def _leer_nips(ruta: Path) -> list[tuple[str, str]]:
    """`(control, nip)` del archivo del SII. El NIP se deja TAL CUAL: validarlo (y
    avisar si Excel le quitó un cero) es de `NipStashService.load_rows`."""
    return _leer_dos_columnas(ruta, "nip", {"nip"})


@titulatec_cli.command("exportar-sin-cuenta")
@click.option("--salida", "salida", type=click.Path(dir_okay=False, path_type=Path),
              default=None, help="Archivo CSV de salida (por omisión, la pantalla).")
def exportar_sin_cuenta_command(salida):
    """Lista las solicitudes vivas cuyo control aún no tiene cuenta.

    Es la lista que se lleva al SII para pedir los NIP. Una fila por solicitud:
    control, nombre, apellidos, carrera, estado, convocatoria y si ya hay un NIP
    precargado (si/no; NUNCA se descifra ni se imprime).
    """
    import csv
    import io

    from sqlalchemy import exists

    from itcj2.apps.titulatec.models import Cohort, EnrollmentRequest, NipStash
    from itcj2.apps.titulatec.models.enrollment_request import OPEN_STATUSES
    from itcj2.apps.titulatec.services.import_service import normalize_control
    from itcj2.core.models.program import Program
    from itcj2.core.models.user import User
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        consulta = (db.query(EnrollmentRequest, Cohort.name, Program.name)
                    .join(Cohort, Cohort.id == EnrollmentRequest.cohort_id)
                    .outerjoin(Program, Program.id == EnrollmentRequest.program_id)
                    .filter(EnrollmentRequest.status.in_(OPEN_STATUSES),
                            ~exists().where(User.control_number
                                            == EnrollmentRequest.control_number))
                    .order_by(EnrollmentRequest.cohort_id, EnrollmentRequest.control_number,
                              EnrollmentRequest.id))
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["control", "nombre", "apellidos", "carrera", "estado",
                    "convocatoria", "nip_precargado"])
        n = 0
        for req, cohorte, programa in consulta.all():
            # El stash va por el control normalizado, igual que la carga.
            hay_nip = db.get(NipStash, normalize_control(req.control_number or "")) is not None
            apellidos = " ".join(x for x in (req.last_name, req.middle_name) if x)
            w.writerow([req.control_number, req.first_name, apellidos,
                        req.program_text or programa or "", req.status, cohorte,
                        "si" if hay_nip else "no"])
            n += 1
    finally:
        db.close()

    if salida is None:
        click.echo(buf.getvalue(), nl=False)
        return
    # `utf-8-sig`: con el BOM, Excel abre el CSV como UTF-8 y respeta los acentos;
    # sin él los lee como ANSI y «Ingeniería» sale «IngenierÃ­a».
    with open(salida, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write(buf.getvalue())
    click.echo(f"{n} solicitud(es) sin cuenta escritas en {salida}.")


@titulatec_cli.command("cargar-nips")
@click.argument("archivo", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--actor", "actor", required=True,
              help="Usuario (username) que queda como autor de la carga.")
@click.option("--dry-run", is_flag=True, help="Solo clasifica cada fila; no escribe ni manda nada.")
@click.option("--sin-correo", "sin_correo", is_flag=True,
              help="Crea las cuentas sin mandar el correo (Accesos las ve como «correo no enviado»).")
def cargar_nips_command(archivo, actor, dry_run, sin_correo):
    """Carga los NIP del SII de las solicitudes sin cuenta.

    El archivo trae las columnas `control` y `nip` (CSV de Excel con BOM, `;`
    o tabulador). Por cada control: si su solicitud espera acceso se crea la
    cuenta y sale el correo; si sigue en otra etapa viva (o fue rechazada) el NIP
    se guarda cifrado y se usa al aprobar. Volver a cargar un control reemplaza
    su NIP. Sin llave `TITULATEC_NIP_STASH_KEY` no se hace nada.

    El reporte nunca imprime un NIP. Sale con 1 si alguna fila falló.
    """
    from itcj2.apps.titulatec.services.nip_stash_service import (
        LOAD_BUCKETS, NipStashService,
    )
    from itcj2.core.models.user import User
    from itcj2.database import SessionLocal

    if not NipStashService.available():
        click.echo(click.style(
            "ERROR: falta TITULATEC_NIP_STASH_KEY (o no es una llave Fernet válida); "
            "sin ella no se puede guardar ningún NIP. No se leyó el archivo.",
            fg="red"), err=True)
        raise SystemExit(1)

    db = SessionLocal()
    try:
        usuario = db.query(User).filter(User.username == actor).first()
        if usuario is None:
            click.echo(click.style(f"ERROR: no existe el usuario {actor!r} (--actor).",
                                   fg="red"), err=True)
            raise SystemExit(1)
        actor_id = usuario.id
        filas = _leer_nips(Path(archivo))

        if not dry_run and not sin_correo:
            # Igual que `fix-control-l`: sin la cuenta de correo conectada los
            # accesos se crearían sin avisar a nadie. Antes de escribir nada.
            from itcj2.apps.titulatec.services.email_helper import _acquire_token
            if _acquire_token("cargar_nips") is None:
                click.echo(click.style(
                    "ERROR: el correo de TitulaTec no está conectado; los accesos no "
                    "saldrían. No se cambió nada. Conéctalo y vuelve a correr, o usa "
                    "--sin-correo y avisa a mano.", fg="red"), err=True)
                raise SystemExit(1)

        def _en_vivo(bucket, control, motivo):
            # Rastro al instante: si el lote se corta, se sabe a quién ya le llegó.
            click.echo(f"  [{_NIPS_ETIQUETAS[bucket]}] {control}"
                       + (f": {motivo}" if motivo else ""))

        resultado = NipStashService.load_rows(
            db, filas, actor_id=actor_id, dry_run=dry_run, send_mail=not sin_correo,
            on_row=None if dry_run else _en_vivo)
    finally:
        db.close()

    # Nada que cargar y nada que falló: puede ser el archivo (separador, encabezado,
    # NIP sin ceros) o un archivo correcto sin nada que hacer (todos con cuenta).
    # Sale con 1 para no verse como corrida normal, pero el texto no culpa a nadie.
    nada = bool(filas) and not resultado["failed"] and not (
        resultado["granted"] or resultado["stored"] or resultado["stored_rejected"])
    if nada:
        click.secho(
            "Ninguna fila requiere cambios o todas fueron rechazadas: revisa el "
            "detalle abajo. Si esperabas cargas, revisa separador/encabezados.",
            fg="red", bold=True, err=True)
    prefijo = "[dry-run] " if dry_run else ""
    click.echo(f"{prefijo}{len(filas)} fila(s) de {Path(archivo).name}.")
    for bucket in LOAD_BUCKETS:
        items = resultado[bucket]
        click.echo(f"  {_NIPS_ETIQUETAS[bucket]}: {len(items)}")
        for control, motivo in items:
            click.echo(f"    · {control}" + (f": {motivo}" if motivo else ""))
    if dry_run:
        click.echo("Dry-run: no se escribió nada.")
    if resultado["failed"] or nada:
        raise SystemExit(1)


@titulatec_cli.command("purgar-nips")
@click.option("--dry-run", is_flag=True, help="Solo cuenta lo que se borraría; no borra nada.")
def purgar_nips_command(dry_run):
    """Borra los NIP del SII precargados que ya no sirven.

    Los de quien ya tiene cuenta y los de quien solo tiene solicitudes
    rechazadas de convocatorias cerradas. Cerrar una convocatoria ya purga los
    suyos; esto barre lo que haya quedado. Imprime únicamente el conteo: nunca
    un control ni un NIP.
    """
    from itcj2.apps.titulatec.services.nip_stash_service import NipStashService
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        # SAVEPOINT: el dry-run borra de verdad y lo deshace, así el conteo es
        # exactamente el de la corrida real.
        savepoint = db.begin_nested()
        n = NipStashService.purge_stale(db)
        if dry_run:
            savepoint.rollback()
        else:
            savepoint.commit()
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if dry_run:
        click.echo(f"[dry-run] {n} NIP(s) se borrarían. No se borró nada.")
    else:
        click.echo(f"{n} NIP(s) precargado(s) borrado(s).")
