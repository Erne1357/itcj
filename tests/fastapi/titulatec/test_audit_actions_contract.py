"""Contrato del vocabulario de la bitácora (spec 2026-10-07 §4.1, §5 y §8).

Mismo espíritu que `test_event_labels.py` con `EVENT_TYPES`: un vocabulario
cerrado solo sirve si algo obliga a mantenerlo. Aquí se fijan tres de las
cuatro partes de §8 (la «b», «todo código registrado se usa», la agrega la
Tarea 10 cuando ya exista la instrumentación):

(a) todo literal que se le pasa a `AuditService.record(` en
    `itcj2/apps/titulatec/**` y en `itcj2/cli/titulatec.py` está en
    `AUDIT_ACTIONS` — y es un LITERAL, para que (b) pueda encontrarlo;
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
def _es_llamada_a_record(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "record"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "AuditService")


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


def _barrer_llamadas(source: str, origen: str) -> tuple[list, list]:
    """-> (códigos encontrados [(origen:línea, código)], llamadas no literales)."""
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
    return codigos, no_literales


def _fuentes_instrumentadas() -> list[Path]:
    rutas = sorted(_APP_DIR.rglob("*.py"))
    if _CLI.exists():
        rutas.append(_CLI)
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
    )
    codigos, no_literales = _barrer_llamadas(fuente, "sintetico.py")
    assert [c for _, c in codigos] == [
        "cohort.created", "window.paused", "window.paused", "window.resumed"]
    assert no_literales == ["sintetico.py:4", "sintetico.py:5"]


def test_toda_accion_que_el_codigo_registra_esta_en_el_vocabulario():
    vocab = _vocab()
    fuera, no_literales = [], []
    for ruta in _fuentes_instrumentadas():
        rel = ruta.relative_to(_REPO).as_posix()
        codigos, nl = _barrer_llamadas(ruta.read_text(encoding="utf-8"), rel)
        no_literales += nl
        fuera += [f"{donde} -> {c!r}" for donde, c in codigos
                  if c not in vocab.AUDIT_ACTIONS]
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


def test_la_red_excluye_exactamente_las_tres_de_d14():
    assert _vocab().NET_EXCLUDED_TABLES == frozenset({
        "titulatec_audit_log", "titulatec_process_events", "titulatec_email_outbox",
    })


def test_las_acciones_de_la_red_tienen_etiqueta():
    assert _vocab().DATA_ACTIONS == {
        "data.insert": "Alta", "data.update": "Cambio", "data.delete": "Baja",
    }
