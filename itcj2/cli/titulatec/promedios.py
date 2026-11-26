"""Promedios oficiales del SII: exportar-controles, cargar-promedios e
init-promedios-pendientes (permisos de la bandeja «Promedios», 2026-11-26)."""
from pathlib import Path

import click

from itcj2.cli.titulatec._common import (
    DML_TITULATEC,
    _abortar_con,
    _leer_dos_columnas,
    titulatec_cli,
)

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


# ---------------------------------------------------------------------------
# Bandeja «Promedios» (spec 2026-11-26-titulatec-promedios-pendientes-design.md §4)
# ---------------------------------------------------------------------------
# El 28 inserta los 3 `titulatec.average.*` y los concede EXPLICITO, `admin`
# incluido. En produccion el 15 NUNCA se re-corre (reparte todo titulatec a
# `admin`), asi que este comando corre SOLO el 28. Invalida el cache de authz
# SOLO de titulatec (nunca `invalidate_all`).
_DML_PROMEDIOS_2026_11_FILES = ["promedios_2026_11/28_insert_average_queue_perms.sql"]
_ROLES_BANDEJA = ("admin", "titulatec_computer_center",
                  "titulatec_school_services", "titulatec_school_services_head")
_AVERAGE_GRANTS = {
    "titulatec.average.page.list": _ROLES_BANDEJA,
    "titulatec.average.api.capture": _ROLES_BANDEJA,
    "titulatec.average.api.request": ("admin", "titulatec_computer_center"),
}


def _verify_promedios_pendientes() -> list[str]:
    """Comprueba que el 28 ATERRIZO: cada permiso existe y lo tienen sus roles.
    Devuelve problemas (contrato de `_verify_reemplazo_docs`). Sesion propia,
    solo lectura."""
    from sqlalchemy import text

    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        concedidos = {
            (code, rol) for code, rol in db.execute(
                text("SELECT p.code, r.name FROM core_permissions p "
                     "JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                     "LEFT JOIN core_role_permissions rp ON rp.perm_id = p.id "
                     "LEFT JOIN core_roles r ON r.id = rp.role_id "
                     "WHERE p.code = ANY(:codes)"),
                {"codes": list(_AVERAGE_GRANTS)})
        }
    finally:
        db.close()
    existen = {code for code, _rol in concedidos}
    problemas = [f"permiso ausente: {code}" for code in _AVERAGE_GRANTS if code not in existen]
    problemas += [f"el rol {rol} no tiene {code}"
                  for code, roles in _AVERAGE_GRANTS.items() if code in existen
                  for rol in roles if (code, rol) not in concedidos]
    return problemas


@titulatec_cli.command("init-promedios-pendientes")
@click.option("--dry-run", is_flag=True,
              help="Comprueba los archivos en disco y los lista, sin escribir nada.")
def init_promedios_pendientes_command(dry_run):
    """Da de alta los permisos de la bandeja «Promedios».

    Corre `promedios_2026_11/28_insert_average_queue_perms.sql`: inserta
    `titulatec.average.{page.list,api.capture,api.request}` y los concede a
    Centro de Computo, Servicios Escolares (operativo y jefatura) y `admin`
    (`api.request` solo a Centro de Computo y `admin`). Corre SOLO ese archivo:
    NO re-ejecuta el 15 ni el resto de `SEED_FILES`. Idempotente (ON CONFLICT).
    Invalida el cache de authz solo de titulatec y VERIFICA con
    `_verify_promedios_pendientes()`; aborta si algo no aterrizo. `--dry-run`:
    comprueba que los archivos existen y los lista, sin escribir.
    """
    faltan = [n for n in _DML_PROMEDIOS_2026_11_FILES if not (DML_TITULATEC / n).exists()]

    if dry_run:
        if faltan:
            click.echo(click.style(f"ERROR: faltan archivos en disco: {faltan}", fg="red"))
        else:
            click.echo("Archivos en disco: OK. Se ejecutarian:")
            for nombre in _DML_PROMEDIOS_2026_11_FILES:
                click.echo(f"  {nombre}")
        click.echo("Dry-run: no se ejecuto nada.")
        if faltan:
            raise click.Abort()
        return

    if faltan:
        _abortar_con([f"faltan archivos en disco: {faltan} "
                      "(database/ esta gitignored: subelos al host)"])

    from itcj2.cli.core import execute_sql_file

    for nombre in _DML_PROMEDIOS_2026_11_FILES:
        click.echo(f"   Ejecutando: {nombre}")
        execute_sql_file(str(DML_TITULATEC / nombre), invalidate_authz=False)
        click.echo(f"   Completado: {nombre}")

    # Tras el commit y ANTES de verificar; best-effort (Redis caido = TTL de 5 min).
    from itcj2.core.services.authz_cache import invalidate_app
    invalidate_app("titulatec")
    click.echo("Cache de authz de titulatec invalidado (solo esta app).")

    problemas = _verify_promedios_pendientes()
    if problemas:
        _abortar_con(problemas)

    click.echo(click.style(
        f"OK: {len(_AVERAGE_GRANTS)} permisos titulatec.average.* con sus roles.", fg="green"))
