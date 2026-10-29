"""Pestaña «Sinodales»: la pantalla del departamento académico (fase 4).

Spec `docs/superpowers/specs/2026-10-21-titulatec-fase4-sinodales-design.md`
§9 (bandeja), §12 (oficio) y §16b (R-D, R-E, R-G). Bandeja FIFO master-detail
(mismo patrón que `pages/titulacion_admin.py`): «Por asignar» y «Asignados»,
asignar a los 4 sinodales (aprueba la fase 4: el proceso pasa a la 5),
sustituir a uno con motivo y descargar el oficio en PDF.

Reparto: asignar y sustituir viven en `SynodalService` (la ÚNICA puerta de la
fase 4), la bandeja en `SynodalInboxService`, el PDF en `OficioService`. Aquí
solo se arma el contexto y se traducen los errores.

Acceso:
- La página y el parcial exigen `synodal.page.list` (el ítem del menú).
- Cada ACCIÓN exige su propio permiso en el gate (`synodal.api.assign`,
  `synodal.api.replace`) y además, en este orden: `assert_process_in_scope`
  como primera sentencia del `try` (404 uniforme), `_exigir_bandeja` (poder
  abrir esta pestaña; el permiso de la acción solo no basta), el corte
  (`SynodalService.operable`, R-G) y `SynodalService.can_operate` (el
  departamento de la carrera; mide ALCANCE, no permiso: con `read.all` es
  True para cualquier departamento mapeado, R-D). El servicio vuelve a
  verificar todo bajo el candado.
- El oficio exige solo `synodal.api.read` + la guarda de alcance: también lo
  descargan el expediente y la pestaña Titulación (R-E), así que NO pasa por
  `_exigir_bandeja` (el Departamento de Titulación no abre Sinodales). Con el
  corte en la fase 4 o antes responde 404, como los documentos de Titulación.
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.sinodales_admin")
router = APIRouter(prefix="/admin/sinodales", tags=["titulatec-pages-sinodales"])

# Abrir la pestaña (y el ítem del menú, `nav._ADMIN_NAV`).
_VIEW_PERMS = ["titulatec.synodal.page.list"]
_ASSIGN_PERM = "titulatec.synodal.api.assign"
_REPLACE_PERM = "titulatec.synodal.api.replace"
_READ_PERM = "titulatec.synodal.api.read"
_ANEXO_PERM = "titulatec.anexo_iii.api.generate"
_PREPARE_PERM = "titulatec.anexo_iii.api.prepare"

_BASE_URL = "/titulatec/admin/sinodales"
_PAGE_TPL = "titulatec/admin/sinodales.html"
_BODY_TPL = "titulatec/partials/sinodales/_body.html"

# Pestañas en el orden de pantalla (las claves son `SynodalInboxService.TABS`).
_TABS = (("pending", "Por asignar"), ("assigned", "Asignados"))
_TAB_ANEXO = ("anexo", "En Anexo III")      # solo con el Anexo III operable (fase 6)
_VACIO = "—"


def _hdr(msg: str) -> str:
    """Percent-encode para que un mensaje acentuado quepa en un header latin-1.

    Gemelo de `pages/titulacion_admin.py::_hdr`; `titulatec-utils.js::
    decodeHeaderMsg` lo deshace al mostrarlo.
    """
    from urllib.parse import quote
    return quote(msg or "", safe="")


def _to_int(raw):
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _error(msg: str) -> Response:
    """Guarda o validación del servicio: 400 + `X-Tt-Error` (htmx no hace swap
    en un 4xx, así que el formulario se queda como está)."""
    return Response(status_code=400, headers={"X-Tt-Error": _hdr(msg)})


def _exigir_bandeja(db, user_id: int) -> None:
    """Las acciones exigen poder ABRIR esta pestaña, no solo el permiso de la
    acción (patrón `titulacion_admin.py::_exigir_bandeja`). 403 como el gate,
    ANTES de escribir. Va después de `assert_process_in_scope`."""
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.exceptions import PageForbidden

    if not set(_VIEW_PERMS) <= set(cached_perms(db, user_id, "titulatec")):
        raise PageForbidden(has_app_access=True)


def _operable(db) -> bool:
    """¿La fase 4 se opera en esta app? (R-G; falla cerrado)."""
    from itcj2.apps.titulatec.services.synodal_service import SynodalService
    return SynodalService.operable(db)


def _anexo_operable(db) -> bool:
    """¿La fase 6 (Anexo III) se opera en esta app? Falla cerrado."""
    from itcj2.apps.titulatec.services.anexo_service import AnexoService
    return AnexoService.operable(db)


def _sin_alcance_msg(db, proc) -> str:
    """Motivo de `can_operate == False`: la carrera sin departamento o un
    departamento que el usuario no opera (mismos textos que el servicio)."""
    from itcj2.apps.titulatec.services.scope_service import department_of_program
    from itcj2.apps.titulatec.services.synodal_service import NOT_MAPPED_MSG, OUT_OF_SCOPE_MSG

    if proc.program_id is None or department_of_program(db, proc.program_id) is None:
        return NOT_MAPPED_MSG
    return OUT_OF_SCOPE_MSG


def _nombre(user) -> str:
    """Nombre en orden natural (nombre(s), paterno, materno)."""
    if user is None:
        return ""
    return " ".join(p for p in (user.first_name, user.last_name, user.middle_name) if p)


def _limpio(raw) -> str:
    return " ".join(str(raw or "").split())


def _asignaciones_label(n: int) -> str:
    if n <= 0:
        return "sin asignaciones vigentes"
    return "1 asignación vigente" if n == 1 else f"{n} asignaciones vigentes"


def _docentes(db, department_id) -> list[dict]:
    """Opciones de los selects: docentes HOY del departamento de la carrera con
    la cuenta activa (hallazgo 3: el servicio lo vuelve a exigir) y perfil
    completo (grado y cédula no vacíos), con su número de asignaciones vigentes
    como dato informativo (spec §9)."""
    from itcj2.apps.titulatec.services.teacher_service import TeacherService

    if department_id is None:
        return []
    salida = []
    for d in TeacherService.roster(db, department_id):
        if d["account_status"] == "inactive":
            continue
        grado, cedula = _limpio(d["academic_degree"]), _limpio(d["professional_license"])
        if not (grado and cedula):
            continue
        n = int(d["active_assignments"] or 0)
        salida.append({"user_id": d["user_id"], "name": d["name"], "degree": grado,
                       "assignments": n, "assignments_label": _asignaciones_label(n)})
    return salida


def _anexo_ctx(db, proc, perms) -> dict | None:
    """Panel de la fase 6 del detalle (spec fase 6 v2 §8.2): etapa, folio,
    firmantes, motivo de reimpresion y el formulario de «listo para recoger»
    con la nota precargada. None si el Anexo no se opera / no se alcanzo.
    Tipos planos: la plantilla se pinta tras cerrar la sesion."""
    from itcj2.apps.titulatec.services.anexo_service import (
        NOTE_MAX, STAGE_LABELS, AnexoService,
    )

    etapa = AnexoService.stage(db, proc)
    if etapa is None:
        return None
    info = AnexoService.ready_info(db, proc) or {}
    try:
        firmantes = AnexoService.signer_labels(proc)
    except ValueError:
        firmantes = []
    imprimir = _READ_PERM in perms and _ANEXO_PERM in perms
    puede_listo = (imprimir and _PREPARE_PERM in perms
                   and etapa in ("preparing", "reprint", "ready"))
    return {
        "stage": etapa, "stage_label": STAGE_LABELS[etapa], "folio": info.get("folio"),
        "signers": firmantes,
        "reprint_reason": info.get("reprint_reason") if etapa == "reprint" else None,
        "ready_label": info.get("ready_label"), "pickup_note": info.get("pickup_note"),
        "can_print": imprimir, "can_ready": puede_listo,
        "note": (AnexoService.default_pickup_note(db, proc) or "") if puede_listo else "",
        "note_max": NOTE_MAX, "error": None,
    }


def _detail_ctx(db, *, process_id: int, user_id: int, perms, operable: bool) -> dict:
    """El detalle de UN proceso: datos de pantalla, sinodales, historial y qué
    acciones ofrecer. Todo dict plano (la sesión se cierra antes de pintar)."""
    from itcj2.apps.titulatec.models import (
        FormatB, Modality, ProcessPhase, ProgramDepartment, TitulationProcess,
    )
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.synodal_service import (
        NOT_MAPPED_MSG, PHASE_CODE, REVIEW_PHASE_CODE, ROLE_LABELS, ROLES, SynodalService,
    )
    from itcj2.apps.titulatec.utils.dates_es import dia_largo, dia_mes_hora
    from itcj2.core.models.department import Department
    from itcj2.core.models.program import Program
    from itcj2.core.models.user import User

    proc = db.get(TitulationProcess, process_id)
    alumno = db.get(User, proc.student_id)
    fb = db.get(FormatB, process_id)
    programa = db.get(Program, proc.program_id) if proc.program_id else None
    mapeo = db.get(ProgramDepartment, proc.program_id) if proc.program_id else None
    depto = db.get(Department, mapeo.department_id) if mapeo else None
    modalidad_id = proc.modality_id or getattr(fb, "modality_id", None)
    modalidad = db.get(Modality, modalidad_id) if modalidad_id else None
    opcion = ((modalidad.option_label or modalidad.name) if modalidad
              else getattr(fb, "titulation_type", None))

    sinodales = SynodalService.active_for_process(db, process_id)
    historial = SynodalService.history(db, process_id) if sinodales else []
    for h in historial:
        h["replaced_label"] = dia_mes_hora(h["replaced_at"]) if h["replaced_at"] else None

    n4 = PhaseService.phase_number_for_code(db, PHASE_CODE)
    n5 = PhaseService.phase_number_for_code(db, REVIEW_PHASE_CODE)
    fase5 = (db.query(ProcessPhase.status)
             .filter(ProcessPhase.process_id == process_id,
                     ProcessPhase.phase_number == n5).scalar()) if n5 is not None else None

    # `can_operate` mide el ALCANCE (departamento de la carrera); el permiso de
    # cada acción se exige aparte, igual que en el gate de su ruta.
    opera = operable and SynodalService.can_operate(db, user_id, proc)
    activo = proc.status == "active"
    can_assign = (opera and activo and not sinodales and n4 is not None
                  and proc.current_phase == n4 and _ASSIGN_PERM in perms)
    can_replace = (opera and activo and bool(sinodales) and fase5 != "approved"
                   and _REPLACE_PERM in perms)
    docentes = _docentes(db, depto.id if depto else None) if (can_assign or can_replace) else []
    vigentes = {s["user_id"] for s in sinodales}

    # Fase 5 (spec 2026-10-22 §8.3, D1): solo el ESTADO de la revisión, para
    # decidir sustituciones (quién no ha votado); nunca la conversación.
    from itcj2.apps.titulatec.services.non_working_day_service import NonWorkingDayService
    from itcj2.apps.titulatec.services.anexo_service import AnexoService
    from itcj2.apps.titulatec.services.review_service import ReviewService
    review_applies = (n5 is not None and (proc.current_phase or 0) >= n5
                      and ReviewService.operable(db))
    review_status = (ReviewService.status_for_process(
        db, process_id, holidays=NonWorkingDayService.holidays(db)) if review_applies else None)

    return {
        "anexo": _anexo_ctx(db, proc, perms),
        "process_id": process_id, "folio": proc.folio,
        "name": _nombre(alumno) or _VACIO,
        "control": (alumno.control_number if alumno else None) or _VACIO,
        "program": programa.name if programa else _VACIO,
        "department": depto.name if depto else None,
        "option": opcion or _VACIO,
        "project": (getattr(fb, "project_name", None) or "").strip() or _VACIO,
        "fb_approved_label": (dia_largo(fb.approved_at)
                              if fb is not None and fb.approved_at else None),
        "status": proc.status,
        "not_mapped_msg": NOT_MAPPED_MSG if depto is None else None,
        "synodals": sinodales, "history": historial,
        "review_applies": review_applies, "review_status": review_status,
        "roles": [{"code": r, "label": ROLE_LABELS[r]} for r in ROLES],
        "can_assign": can_assign, "can_replace": can_replace,
        "can_oficio": bool(sinodales) and _READ_PERM in perms,
        "teachers": docentes,
        # Para sustituir: el que entra no puede ser ya sinodal vigente.
        "replacements": [d for d in docentes if d["user_id"] not in vigentes],
        "oficio_url": f"{_BASE_URL}/{process_id}/oficio.pdf",
        # Fase 6 (D2): el PDF del Anexo, solo con la fase 6 operable y alcanzada.
        "can_anexo": (_anexo_operable(db) and _READ_PERM in perms and _ANEXO_PERM in perms
                      and AnexoService.reached(db, proc)),
        "anexo_url": f"{_BASE_URL}/{process_id}/anexo.pdf",
    }


def _body_ctx(db, *, user_id: int, tab, q, carrera, depto, page, selected_id,
              per_page: int | None = None, etapa="") -> dict:
    """Contexto del parcial `_body.html` (y de la página completa).

    Sin corte operable: solo el estado vacío (cero consultas de bandeja). Sin
    departamento a cargo: su estado vacío. Una carrera o un departamento que
    no son del universo del usuario se ignoran (no filtran nada que no vea).
    """
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.apps.titulatec.services.synodal_inbox_service import SynodalInboxService
    from itcj2.apps.titulatec.utils.dates_es import dia_largo
    from itcj2.apps.titulatec.utils.paging import PAGE_SIZE, Page, normalize_q

    operable = _operable(db)
    q = normalize_q(q) or ""
    tabs = _TABS + ((_TAB_ANEXO,) if _anexo_operable(db) else ())
    tab = tab if tab in {k for k, _ in tabs} else "pending"
    ctx = {
        "operable": operable, "tab": tab, "tabs": tabs, "q": q,
        "carrera": None, "depto": None, "rows": [],
        "page": Page(items=[], total=0, page=1, per_page=per_page or PAGE_SIZE),
        "counts": {t: 0 for t in SynodalInboxService.TABS},
        "departments": [], "programs": [], "detail": None, "selected_id": None,
        "etapa": "preparar",
        "etapa_counts": {e: 0 for e in SynodalInboxService.ETAPAS},
        "etapas": list(SynodalInboxService.ETAPA_LABELS.items()),
    }
    if not operable:
        return ctx

    departamentos = SynodalInboxService.departments(db, user_id)
    ctx["departments"] = departamentos
    if not departamentos:
        return ctx
    depto_id = _to_int(depto)
    if depto_id not in {d["id"] for d in departamentos}:
        depto_id = None
    carreras = SynodalInboxService.programs(db, user_id, department_id=depto_id)
    carrera_id = _to_int(carrera)
    if carrera_id not in {p["id"] for p in carreras}:
        carrera_id = None

    data = SynodalInboxService.list(db, user_id, tab=tab, q=q, program_id=carrera_id,
                                    department_id=depto_id, page=page, per_page=per_page,
                                    etapa=etapa)
    rows = data["rows"]
    for r in rows:
        r["started_label"] = dia_largo(r["started_at"]) if r["started_at"] else None
        r["assigned_label"] = dia_largo(r["assigned_at"]) if r["assigned_at"] else None

    # `?selected=` se resuelve DENTRO de las filas ya acotadas (lista == detalle),
    # también cuando el proceso cae en otra página.
    detail_id = None
    if selected_id and (selected_id in {r["process_id"] for r in rows}
                        or SynodalInboxService.contains(
                            db, user_id, selected_id, tab=tab, q=q, program_id=carrera_id,
                            department_id=depto_id)):
        detail_id = selected_id
    detail = None
    if detail_id:
        detail = _detail_ctx(db, process_id=detail_id, user_id=user_id,
                             perms=cached_perms(db, user_id, "titulatec"), operable=operable)

    ctx.update({"rows": rows, "page": data["page"], "counts": data["counts"],
                "carrera": carrera_id, "depto": depto_id, "programs": carreras,
                "detail": detail, "selected_id": detail_id})
    if tab == "anexo":
        ctx.update(etapa=data["etapa"], etapa_counts=data["etapa_counts"])
    return ctx


def _vista(form) -> dict:
    """La pestaña, búsqueda, carrera, departamento y página desde las que se
    actuó: la acción re-pinta la MISMA vista (regla 3 de la paginación)."""
    return {"tab": form.get("tab") or "pending", "q": form.get("q") or "",
            "carrera": form.get("carrera") or "", "depto": form.get("depto") or "",
            "page": form.get("page") or "", "etapa": form.get("etapa") or ""}


def _repintar(request, db, user_id: int, vista: dict, selected_id, aviso: str):
    """Re-pinta el cuerpo con `selected_id` y el aviso de éxito (`X-Tt-Notice`)."""
    ctx = _body_ctx(db, user_id=user_id, selected_id=selected_id, **vista)
    resp = render_titulatec(request, _BODY_TPL, ctx)
    resp.headers["X-Tt-Notice"] = _hdr(aviso)
    resp.headers["X-Tt-Notice-Kind"] = "success"
    return resp


# ===========================================================================
# Páginas
# ===========================================================================
@router.get("", name="titulatec.pages.sinodales.home")
def home(request: Request, tab: str = "", q: str = "", carrera: str = "", depto: str = "",
         page: str = "", selected: str = "", etapa: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    """Página completa. Los parámetros llegan como `str` (htmx los manda vacíos)
    y se parsean a mano."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), tab=tab, q=q, carrera=carrera,
                        depto=depto, page=page, selected_id=_to_int(selected),
                        etapa=etapa)
    finally:
        db.close()
    return render_titulatec(request, _PAGE_TPL, ctx)


@router.get("/body", name="titulatec.pages.sinodales.body")
def body(request: Request, tab: str = "", q: str = "", carrera: str = "", depto: str = "",
         page: str = "", selected: str = "", etapa: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    """Parcial `#tt-sin-body`: pestañas, búsqueda, filtros, página y detalle."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), tab=tab, q=q, carrera=carrera,
                        depto=depto, page=page, selected_id=_to_int(selected),
                        etapa=etapa)
    finally:
        db.close()
    return render_titulatec(request, _BODY_TPL, ctx)


# ===========================================================================
# Asignar y sustituir
# ===========================================================================
@router.post("/{process_id}/asignar", name="titulatec.pages.sinodales.assign")
async def assign(process_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=[_ASSIGN_PERM]))):
    """Registra a los 4 sinodales: aprueba la fase 4 y el proceso pasa a la 5 (§10)."""
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_assign, process_id=process_id, request=request, user=user, form=form)


def _cuerpo_assign(process_id, request, user, form):
    """Cuerpo síncrono de `assign`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope
    from itcj2.apps.titulatec.services.synodal_service import INERT_MSG, SynodalService

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if not _operable(db):
            return _error(INERT_MSG)
        if not SynodalService.can_operate(db, uid, proc):
            return _error(_sin_alcance_msg(db, proc))
        try:
            resultado = SynodalService.assign(
                db, proc, uid,
                president_id=form.get("president_id"),
                secretary_id=form.get("secretary_id"),
                vocal_id=form.get("vocal_id"),
                alternate_id=form.get("alternate_id"))
        except ValueError as exc:
            # Faltan, repetidos, no docente, sin perfil, ya asignados…
            return _error(str(exc))
        if resultado.get("completed"):
            aviso = "Sinodales registrados: el proceso quedó completo."
        else:
            aviso = ("Sinodales registrados: el proceso pasó a la fase "
                     f"{int(resultado['next_phase']):02d}. Ya puedes descargar el oficio.")
        # El proceso sale de «Por asignar»: se abre en «Asignados» (tabla de
        # los 4 y el oficio), conservando búsqueda, carrera y departamento.
        vista = dict(_vista(form), tab="assigned", page="")
        return _repintar(request, db, uid, vista, process_id, aviso)
    finally:
        db.close()


@router.post("/{process_id}/sustituir", name="titulatec.pages.sinodales.replace")
async def replace(process_id: int, request: Request,
                  user: dict = Depends(require_page_app("titulatec", perms=[_REPLACE_PERM]))):
    """Sustituye al sinodal de una posición, con motivo (D8)."""
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_replace, process_id=process_id, request=request, user=user, form=form)


def _cuerpo_replace(process_id, request, user, form):
    """Cuerpo síncrono de `replace`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope
    from itcj2.apps.titulatec.services.synodal_service import (
        INERT_MSG, ROLE_LABELS, SynodalService,
    )

    uid = int(user["sub"])
    role = form.get("role") or ""
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if not _operable(db):
            return _error(INERT_MSG)
        if not SynodalService.can_operate(db, uid, proc):
            return _error(_sin_alcance_msg(db, proc))
        try:
            SynodalService.replace(db, proc, uid, role=role,
                                   new_user_id=form.get("new_user_id"),
                                   reason=form.get("reason") or "")
        except ValueError as exc:
            # Motivo vacío, misma persona, ya vigente, fase 5 aprobada…
            return _error(str(exc))
        return _repintar(request, db, uid, _vista(form), process_id,
                         f"Se sustituyó al {ROLE_LABELS[role]}.")
    finally:
        db.close()


# ===========================================================================
# Anexo III: marcar listo para recoger (fase 6 v2, spec §7 y §8.2)
# ===========================================================================
@router.post("/{process_id}/anexo/listo", name="titulatec.pages.sinodales.anexo_ready")
async def anexo_ready(process_id: int, request: Request,
                      user: dict = Depends(require_page_app("titulatec", perms=[_PREPARE_PERM]))):
    """Marca el Anexo III listo para recoger con la nota de lugar y horario (o
    corrige la nota estando ya listo). Exige `prepare` (el gate) y, dentro,
    `generate` + `synodal.api.read` + alcance."""
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_anexo_ready, process_id=process_id, request=request, user=user, form=form)


def _cuerpo_anexo_ready(process_id, request, user, form):
    """Cuerpo síncrono de `anexo_ready`: corre en el threadpool, no en el event loop."""
    from itcj2.apps.titulatec.services.anexo_service import (
        NOT_OPERABLE_MSG, NOTE_REQUIRED_MSG, NOTE_TOO_LONG_MSG, AnexoService,
        AnexoStageChanged,
    )
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.database import SessionLocal
    from itcj2.exceptions import PageForbidden

    uid = int(user["sub"])
    nota = form.get("note") or ""
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if not {_READ_PERM, _ANEXO_PERM, _PREPARE_PERM} <= set(cached_perms(db, uid, "titulatec")):
            raise PageForbidden(has_app_access=True)
        if not _anexo_operable(db):
            return _error(NOT_OPERABLE_MSG)
        try:
            res = AnexoService.mark_ready(db, proc, uid, nota,
                                          expected_stage=form.get("expected_stage") or None)
            db.commit()
        except AnexoStageChanged:
            # Otra persona lo movió mientras tanto (molde R24): 200 + panel vigente + aviso.
            db.rollback()
            resp = render_titulatec(request, _BODY_TPL, _body_ctx(
                db, user_id=uid, selected_id=process_id, **dict(_vista(form), tab="anexo")))
            resp.headers["X-Tt-Notice"] = _hdr(
                "El Anexo III cambió mientras lo revisabas: revisa su estado e inténtalo de nuevo.")
            resp.headers["X-Tt-Notice-Kind"] = "warning"
            return resp
        except ValueError as exc:
            msg = str(exc)
            if msg not in (NOTE_REQUIRED_MSG, NOTE_TOO_LONG_MSG):
                return _error(msg)
            # Validación del formulario: 200 y el mismo panel con el error y lo tecleado.
            ctx = _body_ctx(db, user_id=uid, selected_id=process_id,
                            **dict(_vista(form), tab="anexo"))
            if ctx["detail"] and ctx["detail"].get("anexo"):
                ctx["detail"]["anexo"].update(error=msg, note=nota)
            return render_titulatec(request, _BODY_TPL, ctx)
        avisado = True
        try:
            if res["first"] or res.get("changed"):
                AnexoService.notify_ready(process_id)
        except Exception:
            avisado = False
            logger.warning("notify_ready fallo para el proceso %s", process_id, exc_info=True)
        if res["first"]:
            aviso = "Anexo III listo para recoger: se avisó al egresado."
        elif res.get("changed"):
            aviso = "Se actualizó el lugar y el horario de recogida."
        else:
            aviso = "Sin cambios: el lugar y el horario ya estaban así."
        vista = dict(_vista(form), tab="anexo", etapa="recoger", page="")
        resp = _repintar(request, db, uid, vista, process_id, aviso)
        if not avisado:
            # El marcado sí se guardó; solo el aviso al egresado falló.
            resp.headers["X-Tt-Notice"] = _hdr(
                "Quedó marcado como listo, pero no se pudo avisar al egresado.")
            resp.headers["X-Tt-Notice-Kind"] = "warning"
        return resp
    finally:
        db.close()


# ===========================================================================
# Oficio
# ===========================================================================
@router.get("/{process_id}/anexo.pdf", name="titulatec.pages.sinodales.anexo")
def anexo_pdf(process_id: int, request: Request,
              user: dict = Depends(require_page_app("titulatec", perms=[_ANEXO_PERM]))):
    """El Anexo III en PDF, INLINE, desde Sinodales (fase 6, D2). Emite el folio
    si aún no lo tiene: es el documento oficial (el alumno solo recibe la vista
    previa con marca de agua, sin folio). Exige
    `anexo_iii.api.generate` (la dependencia) y `synodal.api.read`, más la
    guarda de alcance (404 de otro departamento). Con el Anexo sin operar o sin
    alcanzar responde 400 + `X-Tt-Error`."""
    from itcj2.apps.titulatec.services.anexo_service import AnexoService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.database import SessionLocal
    from itcj2.exceptions import PageForbidden

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)
        if _READ_PERM not in cached_perms(db, uid, "titulatec"):
            raise PageForbidden(has_app_access=True)
        try:
            ctx = AnexoService.prepare_pdf(db, proc, uid)
        except ValueError as exc:
            db.rollback()
            return _error(str(exc))
        nombre = AnexoService.filename(db, proc)
        # Commit ANTES de pintar: suelta el bloqueo del proceso (y el del
        # contador en la primera emisión) mientras WeasyPrint trabaja.
        db.commit()
    finally:
        db.close()
    pdf = AnexoService.render(ctx)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{nombre}"',
                             "X-Content-Type-Options": "nosniff"})


@router.get("/{process_id}/oficio.pdf", name="titulatec.pages.sinodales.oficio")
def oficio(process_id: int, request: Request,
           user: dict = Depends(require_page_app("titulatec", perms=[_READ_PERM]))):
    """Oficio «Asignación de Sinodales» en PDF, INLINE y generado al vuelo
    (§12). 404 sin sinodales vigentes, fuera de alcance o con el corte en la
    fase 4 o antes. Sin `_exigir_bandeja`: lo enlazan también el expediente y
    la pestaña Titulación (R-E), que no abren Sinodales."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.oficio_service import OficioService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope
    from itcj2.apps.titulatec.services.synodal_service import SynodalService

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)
        if not _operable(db) or not SynodalService.active_for_process(db, process_id):
            return Response(status_code=404)
        try:
            pdf = OficioService.render_pdf(db, proc)
        except ValueError:
            # Sin sinodales vigentes (`NO_SYNODALS_MSG`): otro los quitó entre
            # la lectura de arriba y el render.
            return Response(status_code=404)
        filename = OficioService.filename(db, proc)
    finally:
        db.close()
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})
