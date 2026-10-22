"""Comando `init-titulatec-fase-2`: UNICO camino de despliegue del DML de la
«fase 2 del desarrollo» de TitulaTec (fases 3-8).

Cada spec nuevo agrega su archivo a `_DML_FASE_2_FILES` (y sus grants a
`_FASE_2_EXPECTED`); el comando los corre todos, en orden, y verifica.
"""
import click

from itcj2.cli.titulatec._common import DML_TITULATEC, _abortar_con, titulatec_cli

_DML_FASE_2_DIR = "fase_2"
# Debe listar TODOS los .sql de `database/DML/titulatec/fase_2/`.
_DML_FASE_2_FILES = ["01_titulacion_formato_b.sql", "02_sinodales.sql",
                     "03_revision_sinodales.sql", "04_anexo_iii.sql"]

# rol -> permisos que DEBEN tener tras correr el comando.
_FASE_2_EXPECTED: dict[str, set[str]] = {
    "titulatec_titulacion": {
        "titulatec.titulacion.page.list",
        "titulatec.format_b.api.read.all",
        "titulatec.format_b.api.correct_registry",
        "titulatec.synodal.api.read",
        "titulatec.non_working_day.page.list",
        "titulatec.non_working_day.api.manage",
        "titulatec.anexo_iii.api.generate",
        "titulatec.anexo_iii.api.review",
    },
    "titulatec_titulaciones": {
        "titulatec.titulacion.page.list",
        "titulatec.format_b.api.correct_registry",
        "titulatec.synodal.api.read",
        "titulatec.synodal.page.list",
        "titulatec.synodal.api.assign",
        "titulatec.synodal.api.replace",
        "titulatec.teacher.page.list",
        "titulatec.teacher.api.manage",
        "titulatec.non_working_day.page.list",
        "titulatec.non_working_day.api.manage",
        "titulatec.anexo_iii.api.generate",
        "titulatec.anexo_iii.api.review",
    },
    "titulatec_vinculacion": {
        "titulatec.teacher.page.list",
        "titulatec.teacher.api.manage",
        "titulatec.synodal.api.replace",
        "titulatec.anexo_iii.api.generate",
    },
    "admin": {
        "titulatec.titulacion.page.list",
        "titulatec.format_b.api.correct_registry",
        "titulatec.teacher.page.list",
        "titulatec.teacher.api.manage",
        "titulatec.synodal.api.replace",
        "titulatec.program_department.page.list",
        "titulatec.program_department.api.manage",
        "titulatec.non_working_day.page.list",
        "titulatec.non_working_day.api.manage",
        "titulatec.anexo_iii.api.generate",
        "titulatec.anexo_iii.api.review",
    },
    "graduate": {
        "titulatec.anexo_iii.api.generate.own",
    },
    "titulatec_sinodal": {
        "titulatec.synodal.page.my_reviews",
        "titulatec.synodal.api.vote",
        "titulatec.chat.page.view",
        "titulatec.chat.api.read",
        "titulatec.chat.api.send",
        "titulatec.chat.api.upload",
    },
}

# Permisos que nacen en `02_sinodales.sql` (deben existir en core_permissions).
_FASE_2_NEW_PERMISSIONS: set[str] = {
    "titulatec.teacher.page.list",
    "titulatec.teacher.api.manage",
    "titulatec.synodal.api.replace",
    "titulatec.program_department.page.list",
    "titulatec.program_department.api.manage",
    "titulatec.non_working_day.page.list",
    "titulatec.non_working_day.api.manage",
    "titulatec.anexo_iii.api.generate.own",
    "titulatec.anexo_iii.api.generate",
    "titulatec.anexo_iii.api.review",
}

# Tarea periodica sembrada por `03_revision_sinodales.sql` (cron diario 9:15).
# El verificador exige que EXISTA; inactiva (pausada desde /config/system/tasks)
# es solo un AVISO (`_avisos_fase_2`).
_FASE_2_PERIODIC_TASK = "titulatec.review_reminders"

# D12 (spec fase 5 §6.5): payload del `process_resumed` de la reactivacion.
_D12_PAYLOAD = {"reason": "checkpoint", "source": "init-titulatec-fase-2"}

# Producto final por modalidad (04_anexo_iii.sql): el verificador lo exige en las
# 3 modalidades con sinodales.
_FASE_2_PRODUCT_MODALITIES: tuple[str, ...] = (
    "integral_residencias", "thesis", "research_project")

# Los 8 departamentos con sinodales propios (spec fase 4 §5.1).
_FASE_2_DEPARTMENTS: tuple[str, ...] = (
    "sys_computing", "industrial_eng", "eco_admin_sci", "elec_electronics",
    "metal_mechanics", "coord_campus_2", "ead", "postgrad_research",
)

# Carrera (core_programs.name en dev) -> departamento (core_departments.code).
_FASE_2_PROGRAM_DEPARTMENTS: dict[str, str] = {
    "Ing. Sistemas computacionales": "sys_computing",
    "Ing. Tics": "sys_computing",
    "Ciberseguridad": "sys_computing",
    "Ing. Industrial": "industrial_eng",
    "Ing. Logistica": "industrial_eng",
    "Contador publico": "eco_admin_sci",
    "Ing. Gestión Empresarial": "eco_admin_sci",
    "Lic. Administracion": "eco_admin_sci",
    "Eléctrica": "elec_electronics",
    "Electrónica": "elec_electronics",
    "Semiconductores": "elec_electronics",
    "Mecatrónica": "elec_electronics",
    "Electromecánica": "metal_mechanics",
    "Mecánica": "metal_mechanics",
    "Ing. Sistemas computacionales CAMPUS II": "coord_campus_2",
    "Ing. Industrial CAMPUS II": "coord_campus_2",
    "Ing. Logistica CAMPUS II": "coord_campus_2",
    "Mecatrónica CAMPUS II": "coord_campus_2",
    "Ing. Gestión Empresarial CAMPUS II": "coord_campus_2",
    "Contador Público CAMPUS II": "coord_campus_2",
    "Lic. Administración CAMPUS II": "coord_campus_2",
    "Ing. Sistemas computacionales EAD": "ead",
    "Ing. Gestión Empresarial EAD": "ead",
    "Lic. Administración EAD": "ead",
    "Ing. Industrial EAD": "ead",
    "Maestría en Ingeniería Industrial": "postgrad_research",
    "Maestría en Administración de Negocios Internacionales": "postgrad_research",
    "Maestría en Ingeniería Administrativa": "postgrad_research",
    "Doctorado en Ciencias de la Ingeniería": "postgrad_research",
}

_FASE_2_MODALITIES: tuple[str, ...] = (
    "integral_residencias", "thesis", "research_project", "egel")

# Titulos con que el oficio REAL nombra al destinatario y al «At'n.» (hallazgo 17
# de la revision de rama, migracion `tt20261022b`); el 02 los siembra donde la
# columna sigue NULL y el verificador exige que esten.
_FASE_2_ADDRESSEE_TITLE = "JEFA DE LA DIVISIÓN DE ESTUDIOS PROFESIONALES"
_FASE_2_ATTN_TITLE = "Coordinadora de Apoyo a Titulación"


def _program_mapping_rows(db) -> list[tuple]:
    """`(nombre, depto sembrado, depto actual o None, existe en core_programs,
    el depto actual tiene puesto docente_*)` de cada carrera de la siembra."""
    from sqlalchemy import text

    filas = []
    for nombre, sembrado in _FASE_2_PROGRAM_DEPARTMENTS.items():
        fila = db.execute(
            text("SELECT d.code, EXISTS (SELECT 1 FROM core_positions p "
                 "WHERE p.code = 'docente_' || d.code AND p.is_active) "
                 "FROM core_programs pr "
                 "LEFT JOIN titulatec_program_departments pd ON pd.program_id = pr.id "
                 "LEFT JOIN core_departments d ON d.id = pd.department_id "
                 "WHERE pr.name = :n"), {"n": nombre}).first()
        if fila is None:
            filas.append((nombre, sembrado, None, False, False))
        else:
            filas.append((nombre, sembrado, fila[0], True, bool(fila[1])))
    return filas


def _avisos_fase_2() -> list[str]:
    """Diferencias con la siembra que NO son un problema y el comando imprime sin
    abortar: una carrera corregida en «Carreras por departamento» ya no esta en
    el depto sembrado (hallazgo 2), o la tarea periodica de la fase 5 esta
    pausada desde /config/system/tasks (el 03 respeta `is_active`; abortar
    bloquearia todo re-run). Sesion propia, solo lectura."""
    from sqlalchemy import text

    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        avisos = [f"la carrera '{nombre}' esta mapeada a {actual} (la siembra dice {sembrado})"
                  for nombre, sembrado, actual, existe, _docentes in _program_mapping_rows(db)
                  if existe and actual is not None and actual != sembrado]
        tarea = db.execute(
            text("SELECT is_active FROM core_periodic_tasks WHERE task_name = :t"),
            {"t": _FASE_2_PERIODIC_TASK}).first()
        if tarea is not None and not tarea[0]:
            avisos.append(f"la tarea periodica {_FASE_2_PERIODIC_TASK} esta inactiva "
                          "(pausada en /config/system/tasks): no habra recordatorios")
        return avisos
    finally:
        db.close()


def _query_d12(db):
    """Procesos 'on_hold' que ya pasaron su primer checkpoint (D12): el predicado
    UNICO de `ProcessService.first_checkpoint_clause` (fase `review_appointment`
    por codigo, `approved`)."""
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.process_service import ProcessService

    return db.query(TitulationProcess).filter(
        TitulationProcess.status == "on_hold",
        ProcessService.first_checkpoint_clause(db))


def _contar_d12(db) -> int:
    """Cuantos reactivaria D12. Solo lectura."""
    return _query_d12(db).count()


def _procesos_d12() -> int:
    """Sesion propia, solo lectura (para el --dry-run)."""
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        return _contar_d12(db)
    finally:
        db.close()


def _reactivar_d12() -> int:
    """D12 (spec fase 5 §6.5): los procesos 'on_hold' con el cotejo aprobado
    vuelven a 'active'. Por ORM, con un `ProcessEvent` `process_resumed` por
    proceso (`actor_id` NULL, `_D12_PAYLOAD`): el timeline del alumno y del
    expediente lo dicen, y la red de la bitacora espeja el evento y el cambio
    de estado (canal `cli` del comando). Filas con `FOR UPDATE` (una revocacion
    concurrente no se pisa). Idempotente: la segunda corrida no encuentra a
    nadie. Devuelve cuantos reactivo. Sesion propia, un commit."""
    from itcj2.apps.titulatec.models import ProcessEvent, TitulationProcess
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        procesos = (_query_d12(db).order_by(TitulationProcess.id)
                    .with_for_update(key_share=True).all())
        for proc in procesos:
            proc.status = "active"
            db.add(ProcessEvent(process_id=proc.id, actor_id=None,
                                event_type="process_resumed",
                                phase_number=proc.current_phase,
                                payload=dict(_D12_PAYLOAD)))
        db.commit()
        return len(procesos)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _query_egel_fase6(db):
    """Procesos 'active' parados en la fase `anexo_iii` cuya modalidad ya salta
    esa fase (EGEL tras el 04). Devuelve `(consulta, numero_de_fase)`; sin la fase
    en el catalogo, `(None, None)`."""
    from sqlalchemy import text

    from itcj2.apps.titulatec.models import TitulationProcess

    num = db.execute(text(
        "SELECT number FROM titulatec_phase_definitions WHERE code = 'anexo_iii'")).scalar()
    if num is None:
        return None, None
    q = db.query(TitulationProcess).filter(
        TitulationProcess.status == "active", TitulationProcess.current_phase == num)
    return q, num


def _procesos_egel_fase6(db=None) -> int:
    """Cuantos saltaria la correccion C10. Solo lectura; sin `db`, sesion propia."""
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    if db is None:
        from itcj2.database import SessionLocal
        db = SessionLocal()
        try:
            return _procesos_egel_fase6(db)
        finally:
            db.close()
    q, num = _query_egel_fase6(db)
    if q is None:
        return 0
    # Solo el catalogo actual (`skips_phases`): antes de la primera corrida real
    # del 04 EGEL aun no salta la fase 6 y esto cuenta 0.
    return sum(1 for p in q.all() if num in PhaseService._skips(p))


def _saltar_egel_fase6() -> int:
    """C10 (spec fase 6 §5): los procesos 'active' que estan en la fase 6 y cuya
    modalidad la salta (EGEL, tras el 04) pasan a la siguiente fase aplicable:
    la 6 queda `skipped`, la siguiente `in_progress` con `started_at`, y
    `current_phase` avanza. R1: NO crea `event_type` nuevo; la red ORM de la
    bitacora espeja los cambios de `ProcessPhase`/proceso (canal `cli`).
    Filas con `FOR NO KEY UPDATE`. Idempotente. Devuelve cuantos movio. Sesion
    propia, un commit."""
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.database import SessionLocal
    from itcj2.core.utils.timezone import db_now

    db = SessionLocal()
    try:
        q, num = _query_egel_fase6(db)
        if q is None:
            return 0
        ultima = max(PhaseService.phase_numbers(db))
        movidos = 0
        for proc in (q.order_by(TitulationProcess.id)
                     .with_for_update(key_share=True).all()):
            if num not in PhaseService._skips(proc):
                continue
            nxt = PhaseService._next_applicable(proc, num, ultima)
            if nxt is None:
                continue
            ph = PhaseService._ensure_phase(db, proc.id, num)
            if ph.status != "approved":
                ph.status = "skipped"
            sig = PhaseService._ensure_phase(db, proc.id, nxt)
            if sig.status in ("pending", "rejected"):
                sig.status = "in_progress"
                sig.started_at = db_now()
            proc.current_phase = nxt
            movidos += 1
        db.commit()
        return movidos
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _verify_fase_2() -> list[str]:
    """Comprueba grants, permisos, organigrama y datos sembrados de fase 2. Devuelve problemas
    (lista vacia = todo bien). Sesion propia, solo lectura."""
    from sqlalchemy import text

    from itcj2.database import SessionLocal

    problemas: list[str] = []
    db = SessionLocal()
    try:
        for rol, codigos in _FASE_2_EXPECTED.items():
            for codigo in sorted(codigos):
                concedido = db.execute(
                    text("SELECT 1 FROM core_role_permissions rp "
                         "JOIN core_roles r ON r.id = rp.role_id "
                         "JOIN core_permissions p ON p.id = rp.perm_id "
                         "JOIN core_apps a ON a.id = p.app_id "
                         "WHERE a.key = 'titulatec' AND r.name = :rol AND p.code = :code"),
                    {"rol": rol, "code": codigo},
                ).first()
                if concedido is None:
                    problemas.append(f"el rol {rol} no tiene {codigo}")

        # --- 02_sinodales: permisos nuevos ---
        existentes = {r[0] for r in db.execute(
            text("SELECT p.code FROM core_permissions p JOIN core_apps a ON a.id = p.app_id "
                 "WHERE a.key = 'titulatec' AND p.code = ANY(:c)"),
            {"c": sorted(_FASE_2_NEW_PERMISSIONS)})}
        for codigo in sorted(_FASE_2_NEW_PERMISSIONS - existentes):
            problemas.append(f"el permiso {codigo} no existe")

        # R-A: el sinodal no conserva ningun `*.read.all`.
        for (codigo,) in db.execute(
                text("SELECT p.code FROM core_role_permissions rp "
                     "JOIN core_roles r ON r.id = rp.role_id "
                     "JOIN core_permissions p ON p.id = rp.perm_id "
                     "JOIN core_apps a ON a.id = p.app_id "
                     "WHERE a.key = 'titulatec' AND r.name = 'titulatec_sinodal' "
                     "AND p.code LIKE '%.read.all' ORDER BY p.code")):
            problemas.append(f"el rol titulatec_sinodal conserva {codigo}")

        # Puestos docente_* -> titulatec_sinodal; head_* -> titulatec_vinculacion.
        for depto in _FASE_2_DEPARTMENTS:
            for prefijo, rol in (("docente_", "titulatec_sinodal"),
                                 ("head_", "titulatec_vinculacion")):
                codigo = f"{prefijo}{depto}"
                existe = db.execute(text("SELECT 1 FROM core_positions WHERE code = :c"),
                                    {"c": codigo}).first()
                if existe is None:
                    problemas.append(f"el puesto {codigo} no existe")
                    continue
                if db.execute(
                        text("SELECT 1 FROM core_position_app_roles par "
                             "JOIN core_positions p ON p.id = par.position_id "
                             "JOIN core_roles r ON r.id = par.role_id "
                             "JOIN core_apps a ON a.id = par.app_id "
                             "WHERE a.key = 'titulatec' AND p.code = :c AND r.name = :rol"),
                        {"c": codigo, "rol": rol}).first() is None:
                    problemas.append(f"{codigo} no tiene el rol {rol}")

        # Carreras mapeadas a un departamento que opera sinodales (hallazgo 2):
        # uno con puesto docente_* activo o de los 8 sembrados. Que difiera de
        # la siembra (correccion legitima en la pantalla) es solo un aviso
        # (`_avisos_fase_2`), nunca un problema: el comando no debe abortar
        # para siempre tras una correccion.
        for nombre, _sembrado, actual, existe, con_docentes in _program_mapping_rows(db):
            if not existe:
                problemas.append(f"la carrera '{nombre}' no existe en core_programs")
            elif actual is None:
                problemas.append(f"la carrera '{nombre}' no esta mapeada")
            elif not con_docentes and actual not in _FASE_2_DEPARTMENTS:
                problemas.append(f"la carrera '{nombre}' esta mapeada a {actual}, "
                                 f"que no tiene puesto docente_{actual}")

        # Ajustes del oficio por departamento, con los titulos del oficio real.
        for depto in _FASE_2_DEPARTMENTS:
            fila = db.execute(
                text("SELECT s.addressee_title, s.attn_title FROM titulatec_department_settings s "
                     "JOIN core_departments d ON d.id = s.department_id WHERE d.code = :c"),
                {"c": depto}).first()
            if fila is None:
                problemas.append(f"falta el ajuste del oficio de {depto}")
                continue
            if not fila[0]:
                problemas.append(f"el ajuste del oficio de {depto} no tiene el titulo del destinatario")
            if not fila[1]:
                problemas.append(f"el ajuste del oficio de {depto} no tiene el titulo del Atn.")

        # option_label de las 4 modalidades.
        for codigo in _FASE_2_MODALITIES:
            fila = db.execute(
                text("SELECT option_label FROM titulatec_modalities WHERE code = :c"),
                {"c": codigo}).first()
            if fila is None or not fila[0]:
                problemas.append(f"la modalidad {codigo} no tiene option_label")

        # Fase 4 del catalogo: responsable = departamento academico.
        fila = db.execute(
            text("SELECT responsible FROM titulatec_phase_definitions "
                 "WHERE code = 'synodal_assignment'")).first()
        if fila is None or fila[0] != "academic_department":
            problemas.append("la fase synodal_assignment no tiene responsible=academic_department")

        # 03_revision_sinodales: responsable de la fase de revision y tarea periodica.
        fila = db.execute(
            text("SELECT responsible FROM titulatec_phase_definitions "
                 "WHERE code = 'synodal_review'")).first()
        if fila is None or fila[0] != "synodals":
            problemas.append("la fase synodal_review no tiene responsible=synodals")
        # Solo que EXISTA: inactiva (pausada desde /config/system/tasks) es un
        # AVISO de `_avisos_fase_2`, nunca un problema que aborte el re-run.
        tarea = db.execute(
            text("SELECT 1 FROM core_periodic_tasks WHERE task_name = :t"),
            {"t": _FASE_2_PERIODIC_TASK}).first()
        if tarea is None:
            problemas.append(f"falta la tarea periodica {_FASE_2_PERIODIC_TASK}")

        # 04_anexo_iii: producto final por modalidad y EGEL salta la fase 6.
        for codigo in _FASE_2_PRODUCT_MODALITIES:
            fila = db.execute(
                text("SELECT product_label FROM titulatec_modalities WHERE code = :c"),
                {"c": codigo}).first()
            if fila is None or not fila[0]:
                problemas.append(f"la modalidad {codigo} no tiene product_label")
        fila = db.execute(
            text("SELECT skips_phases FROM titulatec_modalities WHERE code = 'egel'")).first()
        if fila is None or [int(x) for x in (fila[0] or [])] != [4, 5, 6]:
            problemas.append("la modalidad egel no salta [4, 5, 6]")
    finally:
        db.close()
    return problemas


@titulatec_cli.command("init-titulatec-fase-2")
@click.option("--dry-run", is_flag=True,
              help="Comprueba los archivos en disco y los lista, sin escribir nada.")
def init_titulatec_fase_2_command(dry_run):
    """Carga el DML de la fase 2 del desarrollo (fases 3-8) y lo verifica.

    Corre SOLO `database/DML/titulatec/fase_2/*.sql` (en el orden de
    `_DML_FASE_2_FILES`): NO re-ejecuta el 15 ni el resto de `SEED_FILES`.
    Idempotente (ON CONFLICT). Despues de los SQL hace la correccion D12 en
    Python (`_reactivar_d12`: 'on_hold' con el cotejo aprobado -> 'active',
    con su `process_resumed`) y la reporta. Invalida el cache de authz solo de
    titulatec y VERIFICA con `_verify_fase_2()`; aborta si algo no aterrizo.
    Una carrera corregida en «Carreras por departamento» (otro depto con
    docentes) o la tarea periodica pausada salen como AVISO
    (`_avisos_fase_2()`), sin abortar.

    IMPORTANTE: tras cualquier `init-titulatec` o `init-ajustes-2026-10` hay
    que volver a correr este comando (sus DELETE de convergencia quitan los
    grants de fase 2). `--dry-run`: comprueba que los archivos existen y los
    lista, sin escribir.
    """
    archivos = [f"{_DML_FASE_2_DIR}/{n}" for n in _DML_FASE_2_FILES]
    faltan = [n for n in archivos if not (DML_TITULATEC / n).exists()]

    if dry_run:
        if faltan:
            click.echo(click.style(f"ERROR: faltan archivos en disco: {faltan}", fg="red"))
        else:
            click.echo("Archivos en disco: OK. Se ejecutarian:")
            for nombre in archivos:
                click.echo(f"  {nombre}")
        if not faltan:
            try:
                n = _procesos_d12()
                click.echo(f"D12: se reactivarian {n} proceso(s) en pausa con el cotejo aprobado.")
            except Exception as exc:  # solo informativo; nunca escribe
                click.echo(click.style(f"D12: no se pudo contar ({exc})", fg="yellow"))
            try:
                n = _procesos_egel_fase6()
                click.echo(f"EGEL: se saltarian la fase 6 {n} proceso(s) "
                           "segun el catalogo actual (0 si el 04 aun no se corre).")
            except Exception as exc:  # solo informativo; nunca escribe
                click.echo(click.style(f"EGEL: no se pudo contar ({exc})", fg="yellow"))
        click.echo("Dry-run: no se ejecuto nada.")
        if faltan:
            raise click.Abort()
        return

    if faltan:
        _abortar_con([f"faltan archivos en disco: {faltan} "
                      "(database/ esta gitignored: subelos al host)"])

    from itcj2.cli.core import execute_sql_file

    for nombre in archivos:
        click.echo(f"   Ejecutando: {nombre}")
        execute_sql_file(str(DML_TITULATEC / nombre), invalidate_authz=False)
        click.echo(f"   Completado: {nombre}")

    # D12 (spec fase 5 §6.5): fuera del SQL para que deje rastro (evento +
    # bitacora) y el conteo se vea en la corrida real, no en un RAISE NOTICE.
    reactivados = _reactivar_d12()
    click.echo(f"D12: {reactivados} proceso(s) reactivado(s).")

    # C10 (spec fase 6): despues del 04, que es quien hace saltar la fase 6 a EGEL.
    saltados = _saltar_egel_fase6()
    click.echo(f"EGEL: {saltados} proceso(s) saltaron la fase 6.")

    # Tras el commit y ANTES de verificar; best-effort (Redis caido = TTL de 5 min).
    from itcj2.core.services.authz_cache import invalidate_app
    invalidate_app("titulatec")
    click.echo("Cache de authz de titulatec invalidado (solo esta app).")

    problemas = _verify_fase_2()
    if problemas:
        _abortar_con(problemas)

    # Diferencias con la siembra que no son problema (correcciones hechas en
    # «Carreras por departamento»): se informan y el comando sigue.
    for aviso in _avisos_fase_2():
        click.echo(click.style(f"AVISO: {aviso}", fg="yellow"))

    click.echo(click.style(
        "OK: permisos de fase 2 concedidos a "
        + ", ".join(sorted(_FASE_2_EXPECTED)) + ".", fg="green"))
