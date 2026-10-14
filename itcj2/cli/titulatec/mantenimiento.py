"""Reparaciones puntuales de datos: fix-missing-credentials, rename-documents y fix-control-l."""
import os
from pathlib import Path, PurePosixPath

import click

from itcj2.cli.titulatec._common import titulatec_cli


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


# ---------------------------------------------------------------------------
# Corrección de la «L» de licenciatura (2026-10-09). Quien escribió
# «L21111134» quedaba «sin cuenta» y Centro de Cómputo podía crearle una
# segunda cuenta. Desde este cambio el formulario quita la L
# (`import_service.normalize_control`); este comando corrige lo que ya entró.
# Lógica y reglas: `services/control_fix_service.py`. Sin DML: corre sobre los
# datos con el ORM (la bitácora registra cada cambio) y mueve los archivos.
# ---------------------------------------------------------------------------
@titulatec_cli.command("fix-control-l")
@click.option("--dry-run", is_flag=True, help="Solo muestra qué haría con cada solicitud.")
@click.option("--sin-correo", "sin_correo", is_flag=True,
              help="No envía avisos ni ligas (la liga se puede reenviar desde Solicitudes).")
@click.option("--solicitud", "solo", type=int, multiple=True,
              help="Solo estas solicitudes (repetible). Por omisión, todas las que tienen L.")
def fix_control_l_command(dry_run, sin_correo, solo):
    """Quita la «L» de licenciatura de solicitudes y cuentas de TitulaTec.

    Cada solicitud se corrige en su propia transacción: si una falla, las demás
    siguen y el comando sale con 1. Idempotente: una segunda corrida no
    encuentra nada que corregir.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.control_fix_service import ControlFixService

    db = SessionLocal()
    try:
        plan = ControlFixService.plan(db)
        def _etq(a):
            # Las constancias previas (encuesta de Forms o CSV) llevan su propio id.
            return (f"previa #{a.request_id}" if a.status.startswith("previa")
                    else f"#{a.request_id}")

        if solo:
            plan = [a for a in plan if not a.status.startswith("previa")
                    and a.request_id in set(solo)]
        # Folios faltantes (2026-10-09): liberaciones vigentes sin folio, p. ej.
        # las encuestas liberadas antes de desplegar los folios. Se emiten al
        # final, después de las correcciones (una previa aplicada aquí ya trae
        # el suyo). Con `--solicitud` no se tocan.
        from itcj2.apps.titulatec.services.folio_backfill_service import FolioBackfillService
        folios = [] if solo else FolioBackfillService.candidates(db)
        if not plan and not folios:
            click.echo("No hay solicitudes ni constancias previas con la «L» de licenciatura, "
                       "ni liberaciones sin folio. Nada que hacer.")
            return
        if plan:
            click.echo(f"{len(plan)} registro(s) con L:")
        for a in plan:
            otra = f" (otra: #{a.otra_id})" if a.otra_id else ""
            click.echo(f"  {_etq(a)} {a.control} -> {a.plain} [{a.status}] "
                       f"{a.tipo}: {a.detalle}{otra}")
        if folios:
            from itcj2.apps.titulatec.models import TitulationProcess
            click.echo(f"{len(folios)} liberación(es) sin folio:")
            for c in folios:
                proc = db.get(TitulationProcess, c["process_id"])
                click.echo(f"  {c['source_ref']} {proc.folio if proc else ''} "
                           f"liberada {c['anchor']:%d/%m/%Y} -> folio {c['kind']} {c['semester']}")
        if dry_run:
            click.echo("Dry-run: no se cambió nada.")
            return
        if plan and not sin_correo:
            # El aviso de usuario cambiado y la liga salen UNA vez, al aplicar:
            # una segunda corrida ya no encuentra nada que corregir. Sin la cuenta
            # de correo conectada no se toca nada (salvo `--sin-correo`, y
            # entonces se avisa a mano).
            from itcj2.apps.titulatec.services.email_helper import _acquire_token
            if _acquire_token("fix_control_l") is None:
                click.echo(click.style(
                    "ERROR: el correo de TitulaTec no está conectado; los avisos y la liga "
                    "no saldrían. No se cambió nada. Conéctalo y vuelve a correr, o usa "
                    "--sin-correo y avisa a mano.", fg="red"), err=True)
                raise SystemExit(1)
        db.rollback()       # suelta la lectura del plan antes de escribir

        errores = 0
        for a in plan:
            if a.tipo == "revisar":
                click.echo(click.style(f"  {_etq(a)}: se deja para revisar a mano "
                                       f"({a.detalle})", fg="yellow"))
                continue
            ControlFixService.apply(db, a, send_mail=not sin_correo)
            ok = not a.resultado.startswith("ERROR")
            errores += 0 if ok else 1
            extra = "".join(f"; {x}" for x in (a.correo,
                            f"{len(a.movidos)} archivo(s) movido(s)" if a.movidos else "") if x)
            click.echo(click.style(f"  {_etq(a)} {a.tipo}: {a.resultado}{extra}",
                                   fg="green" if ok else "red"))
        if not solo:
            try:
                conteo = FolioBackfillService.run(db, dry_run=False)
            except Exception as exc:
                db.rollback()
                errores += 1
                click.echo(click.style(f"  folios: ERROR {type(exc).__name__}: {exc}",
                                       fg="red"), err=True)
            else:
                for (kind, sem), n in conteo.items():
                    click.echo(click.style(f"  folios: {n} de {kind} en {sem}", fg="green"))
        if errores:
            raise SystemExit(1)
    finally:
        db.close()
