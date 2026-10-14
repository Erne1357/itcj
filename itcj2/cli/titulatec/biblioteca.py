"""No adeudo de biblioteca (Biblioteca -> Caja), despliegue en dos pasos.

`init-biblioteca-caja` (puestos, roles y permisos; no enciende el candado) y
`activar-biblioteca-caja` (pre-chequeos, requisito automático, re-backfill,
promoción D17 y folios de previas y legado).
"""
import click

from itcj2.cli.titulatec._common import (
    DML_TITULATEC,
    _abortar_con,
    _echo_folios_por_tipo_y_semestre,
    _emitir_folios_previos,
    _run_sql_files,
    titulatec_cli,
)
from itcj2.cli.titulatec.verificaciones import (
    _ROL_ADMIN,
    _ROL_GTV,
    _ROL_JEFATURA_ESCOLARES,
    _ROL_OPERATIVO_ESCOLARES,
)

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
