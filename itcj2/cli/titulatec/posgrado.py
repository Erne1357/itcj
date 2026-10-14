"""`titulatec init-posgrado`: clasifica las 4 carreras de posgrado y sus documentos de fase 1."""
import click

from itcj2.cli.titulatec._common import DML_TITULATEC, _run_sql_files, titulatec_cli

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
