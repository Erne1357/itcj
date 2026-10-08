"""Contrato del vocabulario de la bitácora (spec 2026-10-07 §4.1, §5 y §8).

Mismo espíritu que `test_event_labels.py` con `EVENT_TYPES`: un vocabulario
cerrado solo sirve si algo obliga a mantenerlo. Aquí se fijan tres de las
cuatro partes de §8 (la «b», «todo código registrado se usa», la agrega la
Tarea 10 cuando ya exista la instrumentación):

(a) todo literal que se le pasa a `AuditService.record(` en
    `itcj2/apps/titulatec/**`, `itcj2/cli/titulatec.py` e
    `itcj2/tasks/titulatec_tasks.py` está en `AUDIT_ACTIONS` — y es un LITERAL
    en una llamada directa (sin alias ni referencias sueltas a `record`), para
    que (b) pueda encontrarlo;
(c) todo módulo que nombra el vocabulario existe en `AUDIT_MODULES`, las
    etiquetas son frases en español y los códigos llevan punto;
(d) toda tabla `titulatec_*` de `Base.metadata` está clasificada: o la cubre la
    red ORM con módulo y etiqueta, o está en `NET_EXCLUDED_TABLES`. Una tabla
    nueva obliga a decidir.

Sin BD: todo es AST o lectura de constantes.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_APP_DIR = _REPO / "itcj2" / "apps" / "titulatec"
_CLI = _REPO / "itcj2" / "cli" / "titulatec.py"
_TASKS = _REPO / "itcj2" / "tasks" / "titulatec_tasks.py"
_ACTIONS_FILE = _APP_DIR / "services" / "audit_actions.py"

# El segmento de módulo de un código NUNCA puede empezar así (lo barre
# `test_event_labels.py::test_todo_event_type_que_el_codigo_escribe_esta_en_el_dominio`
# y se confundiría con un `event_type` de `ProcessEvent`).
_PREFIJOS_DE_EVENTO = ("process_", "document_", "phase_", "requirement_",
                       "appointment_", "survey_review_", "enrollment_", "library_")

# Los 18 módulos de la spec §4.1, con su etiqueta. Copia literal a propósito:
# si alguien renombra uno, la UI cambia de palabra y este test lo hace explícito.
_MODULOS_SPEC = {
    "processes": "Procesos",
    "documents": "Documentos",
    "appointments": "Citas",
    "cohorts": "Convocatorias",
    "windows": "Espacios de cotejo",
    "format_b": "Formato B",
    "enrollment": "Solicitudes",
    "access": "Accesos",
    "officers": "Encargados",
    "import": "Importaciones",
    "library": "Biblioteca",
    "cashier": "Caja",
    "certificates": "Folios",
    "surveys": "Encuestas",
    "mail": "Correos",
    "sii": "SII",
    "system": "Sistema",
    "data": "Datos",
}

# Toda acción de la spec §5 (vocabulario inicial) con su módulo.
_ACCIONES_SPEC = {
    "cohort.created": "cohorts",
    "cohort.window_changed": "cohorts",
    "cohort.donation_changed": "cohorts",
    "cohort.review_day_toggled": "cohorts",
    "cohort.requirement_created": "cohorts",
    "cohort.requirement_updated": "cohorts",
    "cohort.requirement_deleted": "cohorts",
    "window.created": "windows",
    "window.updated": "windows",
    "window.paused": "windows",
    "window.resumed": "windows",
    "window.places_added": "windows",
    "window.deleted": "windows",
    "window.copied": "windows",
    "format_b.step_saved": "format_b",
    "format_b.submitted": "format_b",
    "format_b.reviewed": "format_b",
    "enrollment.request_created": "enrollment",
    "enrollment.approved": "enrollment",
    "enrollment.rejected": "enrollment",
    "enrollment.reopened": "enrollment",
    "enrollment.link_resent": "enrollment",
    "enrollment.notice_resent": "enrollment",
    "enrollment.sii_recheck_requested": "enrollment",
    "access.returned": "access",
    "officer.created": "officers",
    "officer.users_changed": "officers",
    "officer.programs_changed": "officers",
    "officer.deactivated": "officers",
    "officer.account_reactivated": "officers",
    "import.students_committed": "import",
    "import.mapping_saved": "import",
    "import.credential_set": "import",
    "import.user_email_changed": "import",
    "import.roles_synced": "import",
    "certificate.issued": "certificates",
    "certificate.voided": "certificates",
    "certificate.batch_created": "certificates",
    "certificate.backfill_run": "certificates",
    "prior_clearance.deferred": "library",
    "prior_clearance.replaced": "library",
    "prior_clearance.import_run": "library",
    "survey.submitted": "surveys",
    "survey.import_run": "surveys",
    "system.cli_command": "system",
    "system.audit_purged": "system",
}

_CODIGO_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def _vocab():
    from itcj2.apps.titulatec.services import audit_actions
    return audit_actions


# ---------------------------------------------------------------------------
# (a) Literales de `AuditService.record(` contra el vocabulario
# ---------------------------------------------------------------------------
def _es_audit_service(node: ast.AST) -> bool:
    """`AuditService` o `<lo que sea>.AuditService` (`audit_service.AuditService`)."""
    return ((isinstance(node, ast.Name) and node.id == "AuditService")
            or (isinstance(node, ast.Attribute) and node.attr == "AuditService"))


def _es_record(node: ast.AST) -> bool:
    """El atributo `AuditService.record` (llamado o no)."""
    return (isinstance(node, ast.Attribute) and node.attr == "record"
            and _es_audit_service(node.value))


def _es_llamada_a_record(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _es_record(node.func)


def _desvios(tree: ast.AST) -> list[tuple[int, str]]:
    """Formas de llegar a `record` que el barrido de literales NO puede seguir.

    Un alias (`AS = AuditService`, `import ... AuditService as AS`), una
    referencia suelta (`rec = AuditService.record`, pasarla como callback, un
    `partial`), `getattr(AuditService, ...)` o importar un `record` suelto del
    módulo: por cualquiera de ellas pasaría un código sin registrar.
    """
    llamados = {id(n.func) for n in ast.walk(tree) if _es_llamada_a_record(n)}
    out = []
    for n in ast.walk(tree):
        if _es_record(n) and id(n) not in llamados:
            out.append((n.lineno, "referencia a AuditService.record sin llamarla"))
        elif isinstance(n, ast.ImportFrom):
            for alias in n.names:
                if alias.name == "AuditService" and alias.asname not in (None, "AuditService"):
                    out.append((n.lineno, f"AuditService importado como {alias.asname!r}"))
                if alias.name == "record" and (n.module or "").endswith("audit_service"):
                    out.append((n.lineno, "`record` importado suelto"))
        elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            if n.value is not None and _es_audit_service(n.value):
                out.append((n.lineno, "AuditService asignado a otro nombre"))
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "getattr" and n.args and _es_audit_service(n.args[0])):
            out.append((n.lineno, "getattr(AuditService, ...)"))
    return out


def _literales_de_accion(call: ast.Call) -> list[str] | None:
    """Los códigos que puede recibir la llamada, o `None` si no es literal.

    Acepta el literal tal cual y un `a if cond else b` de dos literales (la
    forma natural de «pausó / reanudó» en un solo sitio). Cualquier otra cosa
    —una variable, un f-string— devuelve `None`: la parte (b) del contrato no
    podría encontrar el código.
    """
    arg = None
    if len(call.args) >= 2:
        arg = call.args[1]
    for kw in call.keywords:
        if kw.arg == "action":
            arg = kw.value
    if arg is None:
        return None
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return [arg.value]
    if (isinstance(arg, ast.IfExp)
            and isinstance(arg.body, ast.Constant) and isinstance(arg.body.value, str)
            and isinstance(arg.orelse, ast.Constant) and isinstance(arg.orelse.value, str)):
        return [arg.body.value, arg.orelse.value]
    return None


def _barrer_llamadas(source: str, origen: str) -> tuple[list, list, list]:
    """-> (códigos encontrados [(origen:línea, código)], llamadas no literales,
    desvíos ["origen:línea: qué"])."""
    tree = ast.parse(source, filename=origen)
    codigos, no_literales = [], []
    for node in ast.walk(tree):
        if not _es_llamada_a_record(node):
            continue
        lits = _literales_de_accion(node)
        donde = f"{origen}:{node.lineno}"
        if lits is None:
            no_literales.append(donde)
        else:
            codigos += [(donde, c) for c in lits]
    desvios = [f"{origen}:{linea}: {que}" for linea, que in _desvios(tree)]
    return codigos, no_literales, desvios


def _fuentes_instrumentadas() -> list[Path]:
    """Todo lo que puede llamar a `record`: la app, su CLI y sus tareas de Celery."""
    rutas = sorted(_APP_DIR.rglob("*.py"))
    for extra in (_CLI, _TASKS):
        assert extra.exists(), f"el contrato debe barrer {extra}, y no existe"
        rutas.append(extra)
    return rutas


def test_el_barrido_de_record_reconoce_las_formas_validas_e_invalidas():
    """Guarda del propio barrido: si deja de ver llamadas, (a) pasaría en verde
    sin revisar nada."""
    fuente = (
        "AuditService.record(db, 'cohort.created', entity_id=1)\n"
        "AuditService.record(db, action='window.paused')\n"
        "AuditService.record(db, 'window.paused' if x else 'window.resumed')\n"
        "AuditService.record(db, accion)\n"
        "AuditService.record(db, f'cohort.{x}')\n"
        "OtraCosa.record(db, 'no.cuenta')\n"
        "audit_service.AuditService.record(db, 'typo.calificado')\n"
    )
    codigos, no_literales, desvios = _barrer_llamadas(fuente, "sintetico.py")
    assert [c for _, c in codigos] == [
        "cohort.created", "window.paused", "window.paused", "window.resumed",
        "typo.calificado"]
    assert no_literales == ["sintetico.py:4", "sintetico.py:5"]
    assert desvios == []


@pytest.mark.parametrize("fuente", [
    "rec = AuditService.record\nrec(db, 'typo.x')\n",
    "from itcj2.apps.titulatec.services.audit_service import AuditService as AS\n",
    "AS = AuditService\n",
    "x: type = AuditService\n",
    "functools.partial(AuditService.record, db)\n",
    "hacer(callback=AuditService.record)\n",
    "getattr(AuditService, 'record')(db, 'typo.x')\n",
    "from itcj2.apps.titulatec.services.audit_service import record\n",
    "f = mod.AuditService.record\n",
])
def test_el_barrido_rechaza_alias_y_referencias_sueltas(fuente):
    """Cualquiera de estas formas esconde el código de acción del barrido."""
    _, _, desvios = _barrer_llamadas(fuente, "sintetico.py")
    assert desvios, f"el barrido no vio el desvío en: {fuente!r}"


def test_el_barrido_acepta_las_formas_canonicas():
    fuente = (
        "from itcj2.apps.titulatec.services.audit_service import AuditService\n"
        "from itcj2.apps.titulatec.services import audit_service\n"
        "AuditService.record(db, 'cohort.created')\n"
        "AuditService.safe({'a': 1})\n"
        "audit_service.AuditService.record(db, 'cohort.created')\n"
    )
    assert _barrer_llamadas(fuente, "sintetico.py")[2] == []


def test_toda_accion_que_el_codigo_registra_esta_en_el_vocabulario():
    vocab = _vocab()
    fuera, no_literales, desvios = [], [], []
    for ruta in _fuentes_instrumentadas():
        rel = ruta.relative_to(_REPO).as_posix()
        codigos, nl, dv = _barrer_llamadas(ruta.read_text(encoding="utf-8"), rel)
        no_literales += nl
        desvios += dv
        fuera += [f"{donde} -> {c!r}" for donde, c in codigos
                  if c not in vocab.AUDIT_ACTIONS]
    assert not desvios, (
        "llama a `AuditService.record` SIEMPRE como `AuditService.record(db, "
        "'<código>', ...)`: con alias o referencias sueltas el contrato no ve el "
        "código:\n  " + "\n  ".join(desvios)
    )
    assert not no_literales, (
        "`AuditService.record(` debe recibir el código como LITERAL (o un "
        "`'a' if cond else 'b'` de literales) para que el contrato lo vea:\n  "
        + "\n  ".join(no_literales)
    )
    assert not fuera, (
        "estos códigos se registran pero no están en `AUDIT_ACTIONS` "
        "(agrégalos en `services/audit_actions.py`, en el bloque de su módulo):\n  "
        + "\n  ".join(fuera)
    )


# ---------------------------------------------------------------------------
# (c) Módulos, etiquetas y forma de los códigos
# ---------------------------------------------------------------------------
def test_los_modulos_son_los_18_de_la_spec():
    assert _vocab().AUDIT_MODULES == _MODULOS_SPEC


def test_toda_accion_de_la_spec_esta_registrada_en_su_modulo():
    acciones = _vocab().AUDIT_ACTIONS
    faltan = sorted(set(_ACCIONES_SPEC) - set(acciones))
    assert not faltan, f"acciones de la spec §5 sin registrar: {faltan}"
    mal = {c: acciones[c][0] for c, m in _ACCIONES_SPEC.items() if acciones[c][0] != m}
    assert not mal, f"acciones en el módulo equivocado: {mal}"


def test_todo_codigo_lleva_punto_y_no_parece_un_event_type():
    for codigo in _vocab().AUDIT_ACTIONS:
        assert _CODIGO_RE.match(codigo), f"código mal formado: {codigo!r}"
        assert len(codigo) <= 64, f"{codigo!r} no cabe en `action` (String(64))"
        segmento = codigo.split(".", 1)[0]
        assert not segmento.startswith(_PREFIJOS_DE_EVENTO), (
            f"{codigo!r}: el segmento de módulo empieza como un event_type "
            f"({_PREFIJOS_DE_EVENTO})"
        )
        assert not codigo.startswith(("process.", "data.")), (
            f"{codigo!r}: `process.*` y `data.*` los escribe la escucha, no `record`"
        )


def test_todo_modulo_nombrado_existe_y_las_etiquetas_son_frases():
    vocab = _vocab()
    for codigo, valor in vocab.AUDIT_ACTIONS.items():
        assert isinstance(valor, tuple) and len(valor) == 2, f"{codigo}: {valor!r}"
        modulo, etiqueta = valor
        assert modulo in vocab.AUDIT_MODULES, f"{codigo}: módulo {modulo!r} no existe"
        assert etiqueta and etiqueta[:1].isupper(), f"{codigo}: etiqueta {etiqueta!r}"
        assert "_" not in etiqueta, f"{codigo}: la etiqueta es el código, no una frase"
        assert not etiqueta.endswith("."), f"{codigo}: sin punto final ({etiqueta!r})"
    for clave, etiqueta in vocab.AUDIT_MODULES.items():
        assert etiqueta[:1].isupper() and "_" not in etiqueta, (clave, etiqueta)


def test_el_espejo_de_process_event_cae_en_un_modulo_valido():
    """Cada `event_type` de `ProcessEvent` tiene módulo (spec §4.1) y su código
    espejo `process.<tipo>` cabe en la columna."""
    from itcj2.apps.titulatec.models.process_event import EVENT_TYPES
    vocab = _vocab()
    for tipo in EVENT_TYPES:
        modulo = vocab.process_event_module(tipo)
        assert modulo in vocab.AUDIT_MODULES, (tipo, modulo)
        assert len(vocab.PROCESS_EVENT_PREFIX + tipo) <= 64, tipo


@pytest.mark.parametrize("tipo, modulo", [
    ("document_uploaded", "documents"),
    ("appointment_no_show", "appointments"),
    ("library_payment_registered", "cashier"),
    ("library_payment_reverted", "cashier"),
    ("library_observed", "library"),
    ("survey_review_approved", "surveys"),
    ("survey_paper_delivered", "surveys"),
    ("enrollment_access_reset", "access"),
    ("phase_approved", "processes"),
    ("process_cancelled", "processes"),
    ("requirement_fulfilled", "processes"),
    ("algo_nuevo_sin_prefijo", "processes"),
])
def test_modulo_del_espejo_por_prefijo(tipo, modulo):
    """Mismo mapeo que el `CASE` del backfill de `tt20261007b`: el historial
    copiado y el espejo en vivo caen en el mismo módulo."""
    assert _vocab().process_event_module(tipo) == modulo


def test_el_vocabulario_no_depende_de_modelos():
    """`audit_actions.py` lo importan la escucha (que se instala al cargar
    `models/`), el servicio y la página: sin modelos ni servicios, nunca un
    ciclo de imports."""
    tree = ast.parse(_ACTIONS_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not mod.startswith(("itcj2", ".")), f"importa {mod!r}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("itcj2"), f"importa {alias.name!r}"


def test_las_partes_sensibles_son_las_de_d9():
    assert _vocab().SENSITIVE_KEY_PARTS == ("password", "nip", "token", "secret", "hash")


@pytest.mark.parametrize("clave, sensible", [
    ("password", True), ("new_password", True), ("NIP", True), ("nip_status", True),
    ("verify_token_hash", True), ("created_ip_hash", True), ("client_secret", True),
    ("folio", False), ("process_id", False), ("reason", False), ("", False),
])
def test_clave_sensible(clave, sensible):
    assert _vocab().is_sensitive_key(clave) is sensible


# ---------------------------------------------------------------------------
# (d) Toda tabla titulatec está clasificada para la red ORM
# ---------------------------------------------------------------------------
def _tablas_titulatec() -> set[str]:
    import itcj2.apps.titulatec.models  # noqa: F401 - registra el paquete entero
    from itcj2.models.base import Base
    return {t for t in Base.metadata.tables if t.startswith("titulatec_")}


def test_toda_tabla_titulatec_esta_clasificada():
    vocab = _vocab()
    tablas = _tablas_titulatec()
    assert len(tablas) >= 33, f"el registro solo ve {len(tablas)} tablas"
    sin_clasificar = sorted(t for t in tablas
                            if t not in vocab.TABLE_MODULES
                            and t not in vocab.NET_EXCLUDED_TABLES)
    assert not sin_clasificar, (
        "tablas titulatec sin módulo en `TABLE_MODULES` ni exclusión en "
        f"`NET_EXCLUDED_TABLES` (decide cuál): {sin_clasificar}"
    )
    sin_etiqueta = sorted(t for t in tablas if t not in vocab.TABLE_LABELS)
    assert not sin_etiqueta, f"tablas sin nombre legible en `TABLE_LABELS`: {sin_etiqueta}"


def test_no_hay_tablas_fantasma_en_el_vocabulario():
    """Una tabla renombrada o borrada no puede quedarse clasificada."""
    vocab = _vocab()
    tablas = _tablas_titulatec()
    for nombre, mapa in (("TABLE_MODULES", vocab.TABLE_MODULES),
                         ("TABLE_LABELS", vocab.TABLE_LABELS)):
        fantasmas = sorted(set(mapa) - tablas)
        assert not fantasmas, f"{nombre} nombra tablas que no existen: {fantasmas}"
    fantasmas = sorted(set(vocab.NET_EXCLUDED_TABLES) - tablas)
    assert not fantasmas, f"NET_EXCLUDED_TABLES nombra tablas que no existen: {fantasmas}"
    for tabla, modulo in vocab.TABLE_MODULES.items():
        assert modulo in vocab.AUDIT_MODULES, (tabla, modulo)
    for tabla, etiqueta in vocab.TABLE_LABELS.items():
        assert etiqueta[:1].isupper() and "_" not in etiqueta, (tabla, etiqueta)


def test_la_red_excluye_d14_y_el_contenido_de_las_encuestas():
    """Exactamente estas seis, ni una más ni una menos:

    - D14: la bitácora misma, la tabla de eventos (ya espejada) y la bandeja de
      correos (su propio registro; Celery la toca cada 5 minutos).
    - Spec §5, «sin respuestas»: las tres tablas que guardan el CONTENIDO de la
      encuesta de egresados (la proyección JSON `answers`, una fila por pregunta
      con `value_*` y los borradores). La entrega queda en la bitácora por la
      acción explícita `survey.submitted`, sin las respuestas.
    """
    assert _vocab().NET_EXCLUDED_TABLES == frozenset({
        "titulatec_audit_log", "titulatec_process_events", "titulatec_email_outbox",
        "titulatec_survey_responses", "titulatec_survey_answers", "titulatec_survey_drafts",
    })


def test_las_acciones_de_la_red_tienen_etiqueta():
    assert _vocab().DATA_ACTIONS == {
        "data.insert": "Alta", "data.update": "Cambio", "data.delete": "Baja",
    }


# ---------------------------------------------------------------------------
# (e) Todo `entity_type` de una acción explícita tiene nombre legible
# ---------------------------------------------------------------------------
def _entity_types_de(source: str, origen: str) -> tuple[list, list]:
    """-> ([(origen:línea, entity_type literal)], [origen:línea no literales])."""
    tree = ast.parse(source, filename=origen)
    literales, no_literales = [], []
    for node in ast.walk(tree):
        if not _es_llamada_a_record(node):
            continue
        for kw in node.keywords:
            if kw.arg != "entity_type":
                continue
            donde = f"{origen}:{node.lineno}"
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                literales.append((donde, kw.value.value))
            elif not (isinstance(kw.value, ast.Constant) and kw.value.value is None):
                no_literales.append(donde)
    return literales, no_literales


def test_el_barrido_de_entity_type_ve_literales_y_variables():
    fuente = (
        "AuditService.record(db, 'cohort.created', entity_type='cohort', entity_id=1)\n"
        "AuditService.record(db, 'window.paused', entity_type=tipo)\n"
        "AuditService.record(db, 'window.resumed')\n"
        "OtraCosa.record(db, 'x.y', entity_type='no_cuenta')\n"
    )
    literales, no_literales = _entity_types_de(fuente, "sintetico.py")
    assert literales == [("sintetico.py:1", "cohort")]
    assert no_literales == ["sintetico.py:2"]


def test_todo_entity_type_de_record_tiene_etiqueta():
    """Las acciones explícitas usan nombres cortos (`review_window`,
    `cohort_requirement`, `certificate`…) y la red usa la tabla: sin una
    etiqueta, «Sobre qué» y el detalle pintaban «review_window #12» (revisión
    final M8). Un `entity_type` nuevo en un `record(` obliga a nombrarlo en
    `ENTITY_LABELS`, y como literal (el barrido no puede seguir una variable)."""
    vocab = _vocab()
    vistos, no_literales = [], []
    for ruta in _fuentes_instrumentadas():
        rel = ruta.relative_to(_REPO).as_posix()
        lits, nl = _entity_types_de(ruta.read_text(encoding="utf-8"), rel)
        vistos += lits
        no_literales += nl
    assert len({t for _, t in vistos}) >= 10, f"el barrido solo vio {vistos}"
    assert not no_literales, (
        "`entity_type=` de `AuditService.record(` debe ser un literal:\n  "
        + "\n  ".join(no_literales))
    sin_etiqueta = sorted({f"{t!r} ({donde})" for donde, t in vistos
                           if t not in vocab.ENTITY_LABELS})
    assert not sin_etiqueta, (
        "entity_type sin nombre legible en `ENTITY_LABELS` "
        f"(services/audit_actions.py): {sin_etiqueta}")


def test_las_etiquetas_de_entidad_son_frases_y_coinciden_con_su_tabla():
    """Una misma entidad se lee igual en las dos fuentes: el nombre corto de
    una tabla titulatec usa la etiqueta de `TABLE_LABELS`."""
    vocab = _vocab()
    for clave, etiqueta in vocab.ENTITY_LABELS.items():
        assert etiqueta and etiqueta[:1].isupper() and "_" not in etiqueta, (clave, etiqueta)
    for corto, tabla in vocab.ENTITY_TABLES.items():
        assert tabla in vocab.TABLE_LABELS, (corto, tabla)
        assert vocab.ENTITY_LABELS[corto] == vocab.TABLE_LABELS[tabla], corto
    assert vocab.entity_label("review_window") == "Espacio de cotejo"
    assert vocab.entity_label("titulatec_review_windows") == "Espacio de cotejo"
    assert vocab.entity_label("algo_desconocido") == "algo_desconocido"
    assert vocab.entity_label(None) == ""
