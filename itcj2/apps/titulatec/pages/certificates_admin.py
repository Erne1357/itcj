"""Página de Constancias (lotes e impresión): no adeudo de biblioteca y
liberación de encuesta de egresados, sobre el motor compartido de
`services/certificate_service.py` (Tarea 3).

El Centro de Información (constancias de no adeudo) y Gestión Tecnológica y
Vinculación -GTV- (constancias de encuesta) comparten esta MISMA página -cada
quien ve solo los `kind` de `CERT_KINDS` que puede imprimir, D15-. Una vez al
día: «Por imprimir (N)» -> «Generar lote (N)» (confirmación) -> el PDF del
lote (3 por hoja carta, WeasyPrint, `utils/certificate_pdf.py`) se abre en
pestaña nueva desde un `<a target="_blank">` PLANO del parcial re-pintado,
nunca con `<script>` inline. «Lotes» lista los anteriores con fecha, quién,
cuántas (y cuántas anuladas) y «Ver PDF».

Spec `docs/superpowers/specs/2026-10-01-titulatec-biblioteca-caja-design.md`
§4.5 (motor de constancias / la página), D7 (3 por hoja, se acumulan, el área
genera el PDF cuando quiere), D15 (Centro de Información imprime no adeudo;
GTV imprime encuesta), §4.6 (permisos/menú), §5 invariantes 5 y 6.

Gate de página -ÚNICO código, spec §4.6-: `titulatec.certificate.page.list`
en las CUATRO rutas. Es el permiso de ENTRAR a la página. Qué tipos puede de
verdad IMPRIMIR cada actor es una pregunta aparte, que resuelve el ÚNICO
helper de este archivo (`_printable_kinds`), leyendo sus permisos efectivos
de la app (`get_user_permissions_for_app`) contra
`library_clearance.api.print_certificates` / `survey_review.api.
print_certificates`. El reparto real del DML siempre concede ambos códigos
juntos (`biblioteca_2026_10/21_insert_library_cashier_roles_perms.sql`), pero
el helper no lo asume: una cuenta con `certificate.page.list` y SIN ningún
permiso de imprimir entra a la página y ve 0 secciones. Un `kind` fuera de lo
que ese helper permite responde SIEMPRE 404 -nunca 403: la página ya se
aprobó con `page.list`, así que un 403 aquí no distinguiría nada que el actor
no supiera ya- mismo criterio que un recurso fuera de alcance en el resto de
la app.

Las rutas van por `kind`/`batch_id`, NUNCA por `process_id` (spec §4.6:
Constancias no tiene alcance por carrera, ve todo; §5 invariante 6, censo en
`tests/fastapi/titulatec/test_scope_guard.py`).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec
from itcj2.apps.titulatec.services.certificate_service import CERT_KINDS

logger = logging.getLogger("itcj2.apps.titulatec.pages.certificates_admin")
router = APIRouter(prefix="/admin/constancias", tags=["titulatec-pages-certificates"])

_LIST = ["titulatec.certificate.page.list"]

# kind -> código que hace falta para IMPRIMIR ese tipo (spec §4.6). Es
# DISTINTO del código de la página (`_LIST`, arriba): entrar a la página y
# poder imprimir un tipo en concreto son preguntas separadas (docstring).
_KIND_PERM = {
    "library_clearance": "titulatec.library_clearance.api.print_certificates",
    "survey_release": "titulatec.survey_review.api.print_certificates",
}

# Etiqueta de sección para la UI. No es `CERT_KINDS[...]['title']`: ese es el
# título IMPRESO en la constancia misma (mayúsculas a propósito, spec §4.5),
# una decisión de documento, no de pantalla.
_KIND_LABELS = {
    "library_clearance": "No adeudo de biblioteca",
    "survey_release": "Liberación de encuesta de egresados",
}

_PAGE_SIZE = 20


def _hdr(msg: str) -> str:
    """Percent-encode para que un mensaje acentuado quepa en un header latin-1.

    Gemelo de `pages/survey_reviews_admin.py:54`, `pages/library_admin.py` y
    `pages/cashier_admin.py`; `titulatec-utils.js::decodeHeaderMsg` lo deshace
    al mostrarlo.
    """
    from urllib.parse import quote
    return quote(msg or "", safe="")


def _to_page(raw) -> int:
    try:
        n = int(raw) if raw not in (None, "") else 1
    except (TypeError, ValueError):
        return 1
    return n if n > 0 else 1


def _pages(lib_raw, survey_raw) -> dict[str, int]:
    """`{kind: página}` para los 2 `CERT_KINDS`, SIEMPRE los dos (nunca solo
    el que trae la petición): así el formulario de «Generar lote» puede
    reenviar ambos en campos ocultos sin pelear con `None` en la plantilla."""
    return {"library_clearance": _to_page(lib_raw), "survey_release": _to_page(survey_raw)}


def _printable_kinds(db, user_id: int) -> list[str]:
    """Los `CERT_KINDS` que este actor puede IMPRIMIR, en el orden de
    `CERT_KINDS` (nunca el de llegada del set de permisos). ÚNICO lugar del
    archivo que resuelve esta pregunta -las cuatro rutas pasan por aquí, ver
    docstring del módulo-: un `kind` fuera de esta lista responde 404."""
    from itcj2.core.services.authz_service import get_user_permissions_for_app

    perms = get_user_permissions_for_app(db, user_id, "titulatec")
    return [k for k in CERT_KINDS if _KIND_PERM[k] in perms]


def _body_url(pages: dict[str, int]) -> str:
    """URL de `GET /body` con el estado de paginación de los 2 kinds, en los
    MISMOS nombres de query param que leen las rutas (`page_{kind}`) -- `pages`
    viene indexado por `kind` a secas (`_pages`), así que sin este prefijo la
    URL generada traería `library_clearance=N` en vez de
    `page_library_clearance=N` y la ruta la ignoraría en silencio."""
    from urllib.parse import urlencode
    qs = {f"page_{kind}": page for kind, page in pages.items()}
    return "/titulatec/admin/constancias/body?" + urlencode(qs)


def _body_ctx(db, *, user_id: int, pages: dict[str, int], new_batch: dict | None = None) -> dict:
    """Contexto del parcial: una sección por cada `kind` que este actor puede
    imprimir, en el orden de `CERT_KINDS`. Todo lo que la plantilla pinta
    -enlaces de paginación incluidos- ya viene PRECALCULADO: la plantilla no
    decide nada, solo pinta (mismo criterio que `utils/certificate_pdf.py`)."""
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    kinds = _printable_kinds(db, user_id)
    sections = []
    for kind in kinds:
        page = pages.get(kind, 1)
        batches, has_more = CertificateService.list_batches(
            db, kind=kind, page=page, per_page=_PAGE_SIZE)
        sections.append({
            "kind": kind,
            "label": _KIND_LABELS[kind],
            "pending_count": CertificateService.pending_count(db, kind),
            "batches": batches,
            "page": page,
            "has_more": has_more,
            "prev_url": _body_url({**pages, kind: max(1, page - 1)}),
            "next_url": _body_url({**pages, kind: page + 1}),
        })
    return {"sections": sections, "pages": pages, "new_batch": new_batch}


@router.get("", name="titulatec.pages.certificates.list")
async def list_certificates(
    request: Request,
    page_library_clearance: str = "1", page_survey_release: str = "1",
    user: dict = Depends(require_page_app("titulatec", perms=_LIST)),
):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]),
                        pages=_pages(page_library_clearance, page_survey_release))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/certificates.html", ctx)


@router.get("/body", name="titulatec.pages.certificates.body")
async def body(
    request: Request,
    page_library_clearance: str = "1", page_survey_release: str = "1",
    user: dict = Depends(require_page_app("titulatec", perms=_LIST)),
):
    """Hermana de la página: acepta LOS MISMOS query params (HTMX manda los
    dos, aunque este actor solo vea un `kind`)."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]),
                        pages=_pages(page_library_clearance, page_survey_release))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/certificates_body.html", ctx)


@router.post("/{kind}/lote", name="titulatec.pages.certificates.create_batch")
async def create_batch(
    kind: str, request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=_LIST)),
):
    """«Generar lote» (D7): toma TODAS las pendientes de `kind` y las agrupa
    (`CertificateService.create_batch`, su propio commit). El enlace para
    abrir el PDF en pestaña nueva (`target="_blank"`, sin script inline) sale
    en el parcial re-pintado, como «Lote recién generado»."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    form = await request.form()
    pages = _pages(form.get("page_library_clearance"), form.get("page_survey_release"))

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        if kind not in _printable_kinds(db, uid):
            return Response(status_code=404)
        try:
            batch = CertificateService.create_batch(db, kind=kind, actor_id=uid)
        except ValueError as e:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(e))})
        batch_id, batch_count = batch.id, batch.count
        # El lote recién creado siempre sale en la primera página de «Lotes»
        # de SU kind; la página del otro kind (si lo hay) se conserva tal cual.
        pages[kind] = 1
        ctx = _body_ctx(db, user_id=uid, pages=pages,
                        new_batch={"id": batch_id, "kind": kind, "count": batch_count})
    finally:
        db.close()
    resp = render_titulatec(request, "titulatec/admin/partials/certificates_body.html", ctx)
    plural = "s" if batch_count != 1 else ""
    resp.headers["X-Tt-Notice"] = _hdr(f"Lote generado: {batch_count} constancia{plural}.")
    resp.headers["X-Tt-Notice-Kind"] = "success"
    return resp


@router.get("/lotes/{batch_id}.pdf", name="titulatec.pages.certificates.batch_pdf")
def batch_pdf(
    batch_id: int,
    user: dict = Depends(require_page_app("titulatec", perms=_LIST)),
):
    """El PDF de un lote, inline (se abre en pestaña nueva desde un `<a>`
    plano del parcial, nunca con JS). SIEMPRE se regenera -nunca se guarda,
    ver `utils/certificate_pdf.py`-; 404 si el lote no existe O si su `kind`
    no es de los que este actor puede imprimir (nunca 403: mismo criterio que
    `_printable_kinds`, arriba).

    Es `def` y no `async def` a propósito (Ruling R23, I5 de la revisión
    final): WeasyPrint es CPU bloqueante -medido en el contenedor: 30
    constancias 1.7 s, 300 constancias 14.6 s- y en una `async def`
    congelaba el event loop del worker HTTP entero (de TODA la plataforma,
    no solo de TitulaTec) en cada «Ver PDF». En `def`, FastAPI la corre en su
    threadpool, igual que `appointments.move` con el `FOR UPDATE` de
    `SlotService`. No lee el cuerpo de la petición, así que no necesita
    `await request.form()`."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import CertificateBatch
    from itcj2.apps.titulatec.services.certificate_service import CertificateService
    from itcj2.apps.titulatec.utils.certificate_pdf import render_certificates_pdf

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        batch = db.get(CertificateBatch, batch_id)
        if batch is None:
            return Response(status_code=404)
        kind = batch.kind
        if kind not in _printable_kinds(db, uid):
            return Response(status_code=404)
        certs = CertificateService.certificates_of(db, batch_id)
        pdf_bytes = render_certificates_pdf(certs)
    finally:
        db.close()
    filename = f"constancias_{kind}_{batch_id}.pdf"
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})
