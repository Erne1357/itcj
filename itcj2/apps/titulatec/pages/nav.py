"""Templates nativo + helpers de navegación para TitulaTec.

Usa su propia instancia de Jinja2Templates (independiente de itcj2/templates.py),
genera URLs directas y versiona estáticos vía el sv() global (nginx sirve /static/titulatec).
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Request
from starlette.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# Import a nivel de módulo SEGURO: `certificate_service` solo importa
# `db_now` arriba (modelos y servicios son locales) y no toca páginas.
from itcj2.apps.titulatec.services.certificate_service import printing_enabled
# Seguro también: el validador de encuestas es casi puro (solo `re`/`unicodedata`).
from itcj2.apps.titulatec.utils.survey_validator import option_groups

logger = logging.getLogger("itcj2.apps.titulatec.pages")

_HERE = Path(__file__).parent
_TEMPLATES_DIR = _HERE.parent / "templates"

# Instancia propia de Jinja2Templates — no toca itcj2/templates.py
titulatec_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Switch de impresión de constancias (spec folios 2026-10-05 §3.5): CALLABLE
# global, no variable de contexto -los globales de Jinja SÍ llegan a las macros
# importadas sin contexto (`{% from "titulatec/_macros.html" import
# certificate_cell %}`); el contexto de la página no-. Se evalúa en cada
# render: `printing_enabled()` lee `get_settings()` cada vez.
titulatec_templates.env.globals["tt_certificate_printing"] = printing_enabled

# Lista desplegable de la encuesta agrupada por `group` (<optgroup>), en orden
# alfabético en español. Global y no filtro por lo mismo que el de arriba: lo
# llama la macro `tt_field` de `public/partials/survey_form.html`.
titulatec_templates.env.globals["tt_option_groups"] = option_groups


def sv(path: str) -> str:
    """Versión de un estático de titulatec vía el manifest global → fallback STATIC_VERSION."""
    try:
        from itcj2.templates import sv as _sv_global
        return _sv_global("titulatec", path)
    except Exception:
        try:
            from itcj2.config import get_settings
            return str(get_settings().STATIC_VERSION)
        except Exception:
            return "0"


def sv_core(path: str) -> str:
    """Versión de un estático del CORE (p. ej. el shell mobile reutilizado por el alumno)."""
    try:
        from itcj2.templates import sv as _sv_global
        return _sv_global("core", path)
    except Exception:
        try:
            from itcj2.config import get_settings
            return str(get_settings().STATIC_VERSION)
        except Exception:
            return "0"


# ---------------------------------------------------------------------------
# Resolución del dashboard por rol (landing)
# ---------------------------------------------------------------------------

# Orden de prioridad: el primero que matchee gana.
_ROLE_DASHBOARD = [
    ("admin",                          "/titulatec/admin/"),
    ("titulatec_titulaciones",         "/titulatec/admin/"),
    # La jefa aterriza en el Tablero (spec 2026-10-14 D9). `admin` va primero y
    # sigue en la Bandeja (y `resolve_dashboard_url` corta con el JWT admin).
    ("titulatec_school_services_head", "/titulatec/admin/tablero"),
    ("titulatec_school_services",      "/titulatec/admin/"),
    # Departamento de Titulacion (rol de 2026-09-21; sin esta fila aterrizaba en
    # `/itcj/dashboard`). Desde 2026-10-07 (spec 2026-10-07-titulatec-liberados-
    # biblioteca-helpdesk-design.md D1) ya no ve la Bandeja: su pantalla de
    # trabajo es Liberados, una bandeja propia como las de GTV, Computo,
    # Biblioteca y Caja, y por eso va DESPUES de los roles con Bandeja completa
    # (titulaciones, admin y Escolares ganan si alguien tiene ambos).
    # Desde la fase 3 (spec 2026-10-21 §8.1) aterriza en la pestaña Titulación
    # SOLO si ya tiene `titulacion.page.list` (`resolve_dashboard_url`): sin el
    # permiso -producción hasta `init-titulatec-fase-2`- sigue en Liberados.
    ("titulatec_titulacion",      "/titulatec/admin/liberados"),
    ("titulatec_tech_management", "/titulatec/admin/liberaciones"),  # GTV: bandeja de liberaciones (2026-09-15)
    # Centro de Computo (2026-09-24): su bandeja de Accesos. La jefatura trae
    # ademas `admin` por su puesto (D2) y por eso aterriza arriba, en la Bandeja.
    ("titulatec_computer_center", "/titulatec/admin/accesos"),
    # No adeudo de biblioteca (2026-10-01): bandejas propias de Biblioteca y Caja.
    ("titulatec_library", "/titulatec/admin/biblioteca"),
    ("titulatec_cashier", "/titulatec/admin/caja"),
    ("titulatec_vinculacion",     "/titulatec/vinculacion/"),
    ("titulatec_sinodal",         "/titulatec/sinodal/"),
    ("graduate",                  "/titulatec/student/dashboard"),  # egresado: el alumno (2026-09-15)
    ("student",                   "/titulatec/student/dashboard"),  # legado: filas que el backfill 14 no movió
]


# El Tablero exige este permiso; el aterrizaje de la jefa depende de tenerlo.
_REPORTS_URL = "/titulatec/admin/tablero"
_REPORTS_PERM = "titulatec.reports.page.view"

# La pestaña Titulación (spec 2026-10-21 §8.1): mismo patrón que el Tablero, pero
# solo para la fila de `titulatec_titulacion` (la División y `admin` van antes y
# siguen en la Bandeja). Condicional al permiso para que en producción, donde no
# existe hasta `init-titulatec-fase-2`, nada cambie.
_TITULACION_ROLE = "titulatec_titulacion"
_TITULACION_URL = "/titulatec/admin/titulacion"
_TITULACION_PERM = "titulatec.titulacion.page.list"

# La pestaña Sinodales (spec 2026-10-21 fase 4 §9): el mismo patrón condicional,
# para la fila de `titulatec_vinculacion` (jefaturas y coordinaciones de
# vinculación de los departamentos académicos). Sin el permiso, o con
# `perms=None`, conserva su aterrizaje de siempre.
_SINODALES_ROLE = "titulatec_vinculacion"
_SINODALES_URL = "/titulatec/admin/sinodales"
_SINODALES_PERM = "titulatec.synodal.page.list"

# «Mis revisiones» (spec 2026-10-22 fase 5 §8.2): el docente sinodal
# (`titulatec_sinodal`) aterriza en su bandeja con el permiso Y la fase 5
# operable; sin eso, el placeholder de siempre (`/titulatec/sinodal/`).
_REVISIONES_ROLE = "titulatec_sinodal"
_REVISIONES_URL = "/titulatec/admin/revisiones"
_REVISIONES_PERM = "titulatec.synodal.page.my_reviews"


# Aterrizajes condicionales: rol -> (URL de la pestaña, permiso que la abre).
# Además de permiso, la pantalla debe OPERARSE con el corte vigente: su fase
# mínima sale de `_NAV_PHASE_GATE` (misma tabla que el menú, una sola fuente).
_CONDITIONAL_LANDING = {
    _TITULACION_ROLE: (_TITULACION_URL, _TITULACION_PERM),
    _SINODALES_ROLE: (_SINODALES_URL, _SINODALES_PERM),
    _REVISIONES_ROLE: (_REVISIONES_URL, _REVISIONES_PERM),
}


def resolve_dashboard_url(
    roles: set[str],
    jwt_role: str | None = None,
    perms: set[str] | None = None,
    operable: set[str] | None = None,
) -> str:
    """Devuelve la URL de dashboard según los roles del usuario en la app.

    `perms` (opcional) son los permisos efectivos del usuario en la app. Con él,
    el aterrizaje al Tablero exige además `titulatec.reports.page.view`: entre el
    deploy y `titulatec init-reportes` la jefa cae en la Bandeja en vez de un 403.
    Y el Departamento de Titulación aterriza en su pestaña solo con
    `titulatec.titulacion.page.list` (si no, Liberados, como antes); la
    vinculación de los departamentos académicos, en Sinodales solo con
    `titulatec.synodal.page.list` (si no, su página de siempre); y el docente
    sinodal, en «Mis revisiones» solo con `titulatec.synodal.page.my_reviews`
    (si no, el placeholder `/titulatec/sinodal/`).

    `operable` (ruling R5 de la fase 4) son los CÓDIGOS de fase del catálogo
    que hoy se operan en esta app (`PhaseService.operable_codes`). Esos
    aterrizajes exigen además que la fase de su pantalla (`_NAV_PHASE_GATE`)
    esté en el conjunto: con el corte en 3 (producción) el DML base ya da
    `synodal.page.list` a la vinculación, y sin esta guarda aterrizaría en una
    pestaña inerte. `operable=None` falla CERRADO: el aterrizaje de siempre.
    Con `perms=None` solo cuentan los roles (comportamiento anterior: Titulación
    sigue en Liberados, Ruling R5 de la fase 3).
    """
    if jwt_role == "admin":
        return "/titulatec/admin/"
    for role_name, url in _ROLE_DASHBOARD:
        if role_name in roles:
            if url == _REPORTS_URL and perms is not None and _REPORTS_PERM not in perms:
                # Sin el permiso: como el resto de Escolares, a la Bandeja.
                return "/titulatec/admin/"
            condicional = _CONDITIONAL_LANDING.get(role_name)
            if condicional is not None and perms is not None:
                destino, permiso = condicional
                fase = _NAV_PHASE_GATE.get(destino)
                if permiso in perms and (fase is None or fase in (operable or ())):
                    return destino
            return url
    # Sin rol de la app → de vuelta al dashboard core
    return "/itcj/dashboard"


def get_titulatec_roles(user_id: int) -> set[str]:
    """Roles del usuario en la app titulatec (directos + por puesto)."""
    from itcj2.database import SessionLocal
    from itcj2.core.services.authz_service import user_roles_in_app
    db = SessionLocal()
    try:
        return set(user_roles_in_app(db, user_id, "titulatec"))
    except Exception as exc:
        logger.warning("Error obteniendo roles titulatec para user %s: %s", user_id, exc)
        return set()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Menú admin data-driven
# ---------------------------------------------------------------------------

_ADMIN_NAV = [
    # Tablero de la jefa de Servicios Escolares (2026-10-14): solo lectura, un
    # solo código por fila (`perms & need` es OR). Va PRIMERO.
    ("Tablero",             "bi-speedometer2", "/titulatec/admin/tablero",    {"titulatec.reports.page.view"}),
    ("Bandeja",             "bi-inbox",       "/titulatec/admin/",             {"titulatec.dashboard.school_services", "titulatec.dashboard.titulaciones"}),
    ("Procesos",            "bi-people",      "/titulatec/admin/processes",    {"titulatec.process.page.list"}),
    ("Documentos",          "bi-file-earmark-check", "/titulatec/admin/documents",    {"titulatec.document.page.list"}),
    ("Convocatorias",       "bi-award",       "/titulatec/admin/cohorts",      {"titulatec.cohort.page.list"}),
    ("Citas de cotejo",     "bi-calendar",    "/titulatec/admin/appointments", {"titulatec.appointment.page.list"}),
    # Pantalla de trabajo del Departamento de Titulación (spec 2026-10-21 fase 3
    # §8): bandeja FIFO del Formato B; hospedará las fases siguientes.
    ("Titulación",          "bi-journal-check", "/titulatec/admin/titulacion", {"titulatec.titulacion.page.list"}),
    # Bandeja del departamento académico (spec 2026-10-21 fase 4 §9): asignar
    # los 4 sinodales (FIFO), sustituir y descargar el oficio.
    ("Sinodales",           "bi-people",      "/titulatec/admin/sinodales",    {"titulatec.synodal.page.list"}),
    # Pantalla del docente sinodal (spec 2026-10-22 fase 5 §8.2): sus
    # revisiones (por revisar / en curso / completados) y cada conversación.
    ("Mis revisiones",      "bi-chat-square-text", "/titulatec/admin/revisiones", {"titulatec.synodal.page.my_reviews"}),
    # Catálogo de docentes por departamento académico (spec 2026-10-21 fase 4 §8).
    ("Docentes",            "bi-person-badge", "/titulatec/admin/docentes",    {"titulatec.teacher.page.list"}),
    # Carrera -> departamento académico y ajustes del oficio (fase 4 §13, solo admin).
    ("Carreras por depto",  "bi-diagram-3",   "/titulatec/admin/carreras-deptos", {"titulatec.program_department.page.list"}),
    # Calendario de días inhábiles (fase 5 §9.1): de toda la app, SIN guarda de
    # fase; invisible en producción porque el permiso solo lo da `init-titulatec-fase-2`.
    ("Días inhábiles",      "bi-calendar-x",  "/titulatec/admin/dias-inhabiles", {"titulatec.non_working_day.page.list"}),
    # Bandeja de solo lectura del Departamento de Titulacion (2026-09-21, Tarea
    # 5 del deslinde a T-soft): egresados ya liberados por Servicios Escolares.
    ("Liberados",           "bi-box-arrow-right", "/titulatec/admin/liberados", {"titulatec.handoff.page.list"}),
    ("Encargados",          "bi-people-fill", "/titulatec/admin/officers",     {"titulatec.officers.page.list"}),
    # Un solo código por fila: `admin_nav_items` (:118) hace `perms & need`, que
    # es OR — un `dashboard.*` de más abriría el item a todos los oficiales.
    ("Solicitudes",         "bi-person-plus", "/titulatec/admin/solicitudes",  {"titulatec.enrollment_request.page.list"}),
    # Centro de Computo (2026-09-24): da el NIP a las solicitudes que SE aprobo
    # sin cuenta; en modo alterno, revisa todo.
    ("Accesos",             "bi-key",         "/titulatec/admin/accesos",      {"titulatec.enrollment_access.page.list"}),
    ("Liberaciones",        "bi-patch-check", "/titulatec/admin/liberaciones", {"titulatec.survey_review.page.list"}),
    # No adeudo de biblioteca (2026-10-01): bandejas de Biblioteca (Centro de
    # Información) y Caja (Recursos Financieros).
    ("Biblioteca",          "bi-book",        "/titulatec/admin/biblioteca",   {"titulatec.library_clearance.page.list"}),
    ("Caja",                "bi-cash-coin",   "/titulatec/admin/caja",         {"titulatec.library_payment.page.list"}),
    # Folios de liberación (2026-10-05): la pestaña que antes era «Constancias»
    # (misma URL, mismo permiso); la impresión por lotes quedó tras un switch.
    ("Folios",              "bi-hash",        "/titulatec/admin/constancias",  {"titulatec.certificate.page.list"}),
    ("Encuestas",           "bi-clipboard-data", "/titulatec/admin/encuestas", {"titulatec.survey.page.list"}),
    # Bandeja de salida de correos (2026-10-06): solo lectura, solo `admin`
    # (`outbox_2026_10/24`, `titulatec init-outbox-admin`).
    ("Correos",             "bi-envelope",    "/titulatec/admin/correos",      {"titulatec.email_outbox.page.list"}),
    # Bitácora de auditoría (2026-10-07): solo lectura, solo `admin` (D2 de la spec).
    ("Bitácora",            "bi-journal-text", "/titulatec/admin/bitacora",    {"titulatec.audit.page.list"}),
    ("Actos protocolarios", "bi-mortarboard", "#",                             {"titulatec.ceremony.page.list"}),
]

# Fase MÍNIMA de cada pantalla, por CÓDIGO del catálogo (ruling R5 de la
# revisión de la fase 4): el ítem solo se ve si esa fase se opera en esta app
# (`PhaseService._handoff_phase() > número de la fase`). Con el corte en 3
# (producción) el DML base ya da `synodal.page.list` a la vinculación y
# `init-titulatec-fase-2` da los de fase 2 a `admin`: sin esta guarda verían
# pestañas que solo dicen «se opera en T-soft». Sin la fase en el catálogo, el
# ítem se oculta (falla cerrado). Llave = URL de la fila de `_ADMIN_NAV` (la
# tabla conserva sus 4 columnas: varias pruebas la desempacan así); una pantalla
# nueva de fase entra aquí también.
_NAV_PHASE_GATE: dict[str, str] = {
    "/titulatec/admin/titulacion": "format_b",
    "/titulatec/admin/sinodales": "synodal_assignment",
    "/titulatec/admin/docentes": "synodal_assignment",
    "/titulatec/admin/carreras-deptos": "synodal_assignment",
    # Fase 5 (spec 2026-10-22 §8.2, §14): con el corte en 3 no aparece.
    "/titulatec/admin/revisiones": "synodal_review",
}


def _nav_items(db, user_id: int) -> list[dict]:
    """Los ítems con permiso, menos los de una fase que hoy no se opera.

    Permisos de `cached_perms`; el catálogo de fases se consulta UNA vez y solo
    si el usuario tiene algún ítem con fase (`PhaseService.operable_codes`). Si
    esa lectura falla, se ocultan solo los ítems con fase (falla cerrado) y el
    resto del menú sigue.
    """
    from itcj2.core.services.authz_cache import cached_perms

    perms = cached_perms(db, user_id, "titulatec")
    visibles = [fila for fila in _ADMIN_NAV if perms & fila[3]]
    codigos = {_NAV_PHASE_GATE[url] for _l, _i, url, _n in visibles if url in _NAV_PHASE_GATE}
    operables: set[str] = set()
    if codigos:
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        try:
            operables = PhaseService.operable_codes(db, codigos)
        except Exception as exc:
            logger.warning("Error leyendo el catálogo de fases para admin_nav (user %s): %s",
                           user_id, exc)
    return [{"label": label, "icon": icon, "url": url}
            for label, icon, url, _need in visibles
            if url not in _NAV_PHASE_GATE or _NAV_PHASE_GATE[url] in operables]


def admin_nav_items(user_id: int, db=None) -> list[dict]:
    """Items del menú admin visibles según los permisos del usuario en titulatec.

    Los permisos salen de `cached_perms`, la MISMA fuente que el gate
    (`require_page_app`): con la caché tibia no emite ninguna consulta. Con `db`
    usa esa sesión; sin ella abre la suya (`SessionLocal` no toma conexión del
    pool hasta la primera consulta, así que con la caché tibia ni eso cuesta) —
    `render_titulatec` no tiene la sesión de la ruta (cada ruta la cierra antes
    de renderizar) y no hay que abrir una tercera. Las pantallas de una fase que
    el corte a T-soft no deja operar se ocultan (`_NAV_PHASE_GATE`, ruling R5).
    """
    try:
        if db is not None:
            return _nav_items(db, user_id)
        from itcj2.database import SessionLocal
        with SessionLocal() as _db:
            return _nav_items(_db, user_id)
    except Exception as exc:
        logger.warning("Error obteniendo permisos titulatec para admin_nav (user %s): %s", user_id, exc)
        return []


# ---------------------------------------------------------------------------
# Menú del alumno por etapa (spec UI fase 3, 2026-10-23)
# ---------------------------------------------------------------------------

# Pantalla del alumno por CÓDIGO de fase: (clave activa, etiqueta, ícono, URL, permiso
# que exige la página). Los códigos sin fila (0, 4, 7, 8) no tienen pantalla.
_STUDENT_SCREENS: dict[str, tuple[str, str, str, str, str]] = {
    "initial_docs": ("docs", "Documentos", "file-earmark", "/titulatec/student/documents",
                     "titulatec.document.api.read.own"),
    "review_appointment": ("cita", "Cita de cotejo", "calendar-check", "/titulatec/student/cita",
                           "titulatec.appointment.page.my"),
    # `pencil` y no `pencil-square`: el activo pinta `{icono}-fill` y Bootstrap
    # Icons no trae `pencil-square-fill`.
    "format_b": ("formato_b", "Formato B", "pencil", "/titulatec/student/formato-b",
                 "titulatec.format_b.page.fill"),
    "synodal_review": ("revision", "Revisión", "chat-square-text", "/titulatec/student/revision",
                       "titulatec.chat.page.view"),
    "anexo_iii": ("anexo", "Anexo III", "file-earmark-check", "/titulatec/student/anexo",
                  "titulatec.document.api.read.own"),
}
# Orden de «Consultar»: las pantallas de solo lectura que sobreviven a su fase.
_STUDENT_CONSULT_ORDER = ("format_b", "synodal_review", "anexo_iii")


def _student_item(code: str, group: str) -> dict:
    key, label, icon, url, _perm = _STUDENT_SCREENS[code]
    return {"key": key, "label": label, "icon": icon, "url": url, "group": group}


def _student_nav_compute(db, user_id: int, process_id: int | None = None) -> list[dict]:
    """Ítems «Ahora» y «Consultar» del alumno (sin Inicio ni Perfil, que pone la macro).

    Reusa los predicados que ya deciden si la página abre: `PhaseService.can_student_act`
    (fase en curso + corte), `open_replacements`/`student_can_replace` (reemplazo en
    la cita), `review_consultable` y `anexo_consultable` (guardas de lectura) y el
    Formato B `approved` que `pages/student.py::formato_b` sirve en fase >= 4. Sin
    proceso `active` no hay ítems.
    """
    from itcj2.apps.titulatec.models import FormatB, PhaseDefinition, TitulationProcess
    from itcj2.apps.titulatec.pages.student import anexo_consultable, review_consultable
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.core.services.authz_cache import cached_perms

    # La página ya buscó el proceso (`student._nav_hint`): se toma por id en vez de
    # repetir la búsqueda por alumno. 0 = la página no encontró proceso. Sin pista
    # (o si no es de este alumno), la búsqueda de siempre.
    if process_id == 0:
        return []
    process = db.get(TitulationProcess, process_id) if process_id else None
    if process is None or process.student_id != user_id:
        process = DocumentService.get_active_process(db, user_id)
    if process is None or process.status != "active":
        return []
    perms = cached_perms(db, user_id, "titulatec")
    actual = process.current_phase
    corte = PhaseService._handoff_phase()
    numero = {code: int(n) for code, n in
              db.query(PhaseDefinition.code, PhaseDefinition.number)
              .filter(PhaseDefinition.code.in_(sorted(_STUDENT_SCREENS))).all()}
    code_actual = next((c for c, n in numero.items() if n == actual), None)

    def _permitido(code: str) -> bool:
        return _STUDENT_SCREENS[code][4] in perms

    ahora: list[str] = []
    if code_actual is not None and _permitido(code_actual):
        if code_actual == "synodal_review":
            abre = review_consultable(db, process)
        elif code_actual == "anexo_iii":
            abre = anexo_consultable(db, process)
        else:
            abre = PhaseService.can_student_act(db, process, actual)
        if abre:
            ahora.append(code_actual)
    # Reemplazo de un documento pedido en la cita de cotejo (misma regla que `documents`).
    if (ahora == ["review_appointment"]
            and _permitido("initial_docs") and "initial_docs" in numero
            and any(DocumentService.student_can_replace(db, process, r["type_code"])
                    for r in DocumentService.open_replacements(db, process.id))):
        ahora.append("initial_docs")

    consultar: list[str] = []
    for code in _STUDENT_CONSULT_ORDER:
        n = numero.get(code)
        # Solo fases ANTERIORES a la actual, que se operan en esta app (corte) y con permiso.
        if n is None or actual <= n or corte <= n or not _permitido(code):
            continue
        if code == "format_b":
            fb = db.get(FormatB, process.id)
            ok = fb is not None and fb.status == "approved"
        elif code == "synodal_review":
            ok = review_consultable(db, process)
        else:
            ok = anexo_consultable(db, process)
        if ok:
            consultar.append(code)

    return ([_student_item(c, "now") for c in ahora]
            + [_student_item(c, "consult") for c in consultar])


def student_nav_items(user_id: int, process_id: int | None = None) -> list[dict]:
    """Ítems de etapa del menú del alumno; `[]` (solo Inicio y Perfil) si falla.

    Abre su propia sesión (`render_titulatec` no tiene la de la ruta) y nunca rompe
    la página: ante cualquier error, `logger.warning` y menú mínimo.
    """
    try:
        from itcj2.database import SessionLocal
        db = SessionLocal()
        try:
            return _student_nav_compute(db, user_id, process_id)
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Error calculando el menú del alumno (user %s): %s", user_id, exc)
        return []


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render_titulatec(
    request: Request,
    template: str,
    context: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Renderiza un template de TitulaTec con el contexto estándar inyectado."""
    user = getattr(request.state, "current_user", None)
    ctx: dict = {
        "request": request,
        "current_user": user,
        "sv": sv,
        "sv_core": sv_core,
        "current_route": request.url.path,
        **(context or {}),
    }
    # `admin_nav` es un CALLABLE perezoso, no una lista: el menú cuesta (permisos
    # efectivos del usuario) y solo lo pinta `admin/base_admin.html`, que lo
    # invoca. Jinja evalúa un callable del contexto únicamente donde la plantilla
    # lo llama: las vistas del alumno y los parciales HTMX (que no extienden esa
    # base) ya no pagan nada. Si el llamador trae su propio `admin_nav` en el
    # contexto, se respeta.
    if "admin_nav" not in ctx and user is not None:
        try:
            uid = int(user["sub"])
        except Exception as exc:
            logger.warning("Error calculando admin_nav para user %s: %s", user.get("sub"), exc)
            ctx["admin_nav"] = lambda: []
        else:
            # `admin_nav_items` se resuelve como global del módulo al invocar.
            ctx["admin_nav"] = lambda: admin_nav_items(uid)
    # Igual de perezoso para el menú del alumno: solo `student/base_student.html` lo invoca.
    if "student_nav_items" not in ctx and user is not None:
        try:
            suid = int(user["sub"])
        except Exception:
            ctx["student_nav_items"] = lambda: []
        else:
            # Pista de la página (`student._nav_hint`): el proceso que ya cargó.
            pista = getattr(getattr(request, "state", None), "tt_student_process_id", None)
            ctx["student_nav_items"] = lambda: student_nav_items(suid, pista)
    return titulatec_templates.TemplateResponse(request, template, ctx, status_code=status_code)
