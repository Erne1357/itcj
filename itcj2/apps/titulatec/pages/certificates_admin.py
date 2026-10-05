"""Página «Folios» (misma URL `/titulatec/admin/constancias`): los folios de
liberación de no adeudo de biblioteca y de encuesta de egresados, sobre el
motor compartido de `services/certificate_service.py`.

Desde `2026-10-05-titulatec-folios-design.md` (§3.6) ya no se imprimen
constancias: el folio se genera solo al liberar y esta página es el lugar donde
cada área ve qué folio le tocó a cada persona. Una tabla por `kind`
-`CertificateService.list_folios`: folio · egresado · No. de control · carrera ·
emitido (dd/mm/aaaa) · estado («Vigente», o «Anulado» + fecha + motivo)-, con
pestañas por `kind` solo si el actor ve más de uno (admin), chips de estado
(`vigentes` por omisión, `anulados`, `todos`), buscador por folio, número de
control o nombre (`#tt-folio-q`, `hx-preserve`, §18 de la guía de la app) y
paginación con la macro `pager`. Los nombres internos (`Certificate*`, la URL,
los permisos) no cambian a propósito (spec C3).

El Centro de Información (no adeudo) y Gestión Tecnológica y Vinculación -GTV-
(encuesta) comparten esta MISMA página -cada quien ve solo los `kind` de
`CERT_KINDS` que le corresponden, D15/C2-. Los permisos `*.print_certificates`
ahora significan «ver los folios de ese tipo» (y además imprimir, si el switch
está encendido); no se renombran.

Gate de página -ÚNICO código, spec §4.6-: `titulatec.certificate.page.list`
en las CUATRO rutas. Es el permiso de ENTRAR a la página. Qué tipos puede de
verdad VER cada actor es una pregunta aparte, que resuelve el ÚNICO helper de
este archivo (`_visible_kinds`), leyendo sus permisos efectivos de la app
(`get_user_permissions_for_app`) contra `library_clearance.api.
print_certificates` / `survey_review.api.print_certificates`. El reparto real
del DML siempre concede ambos códigos juntos (`biblioteca_2026_10/
21_insert_library_cashier_roles_perms.sql`), pero el helper no lo asume: una
cuenta con `certificate.page.list` y SIN ningún permiso de tipo entra a la
página y ve el aviso «Sin tipos asignados». Un `kind` REAL de `CERT_KINDS`
fuera de lo que ese helper permite responde SIEMPRE 404 -nunca 403: la página
ya se aprobó con `page.list`, así que un 403 aquí no distinguiría nada que el
actor no supiera ya- mismo criterio que un recurso fuera de alcance en el
resto de la app. Un `kind` ausente o que NO es de `CERT_KINDS` es solo un
filtro de vista mal escrito (como un `estado` desconocido): cae en el primer
`kind` visible, nunca en error.

Las rutas van por `kind`/`batch_id`, NUNCA por `process_id` (spec §4.6: no hay
alcance por carrera, ve todo; §5 invariante 6, censo en
`tests/fastapi/titulatec/test_scope_guard.py`).

Switch de impresión (spec `2026-10-05-titulatec-folios-design.md` §3.5,
`TITULATEC_CERTIFICATE_PRINTING`, apagado por omisión) -- la parte de
impresión de la ronda del 2026-10-01/02 NO se borró (D2), solo se ocultó:

* Apagado: `create_batch` y `batch_pdf` responden 404 como PRIMERA sentencia
  -antes de leer el formulario, de resolver permisos por tipo o de buscar el
  lote: no hay nada que imprimir y no se escribe nada; el 403 del gate de
  página sigue primero porque es la dependencia de la ruta, no su cuerpo-, y
  la página no pinta ninguna sección de impresión (`_body_ctx` ni siquiera
  arma `sections`).
* Encendido: debajo de la tabla de folios se incluye
  `partials/_certificates_print.html`, tal cual: «Por imprimir (N)» ->
  «Generar lote (N)» (confirmación) -> el PDF del lote (2 o 3 por hoja carta
  A ELEGIR -`por_hoja`, WeasyPrint, `utils/certificate_pdf.py`-) se abre en
  pestaña nueva desde uno de los DOS `<a target="_blank">` PLANOS del parcial
  re-pintado, nunca con `<script>` inline. «Lotes» lista los anteriores con
  fecha, quién, cuántas (y cuántas anuladas) y los dos enlaces «PDF · N por
  hoja». «Por imprimir (N)» se despliega -`<details>` plegado, sin JS- para
  ver QUIÉNES son, en el mismo orden FIFO que tomará el lote
  (`CertificateService.pending`); «Anuladas después de imprimir (últimos 30
  días)» (`CertificateService.voided_after_print`) avisa que hay que retirar
  ese papel, y no sale si no hay ninguna. «Generar lote» y la paginación de
  «Lotes» incluyen `#tt-folio-filters` para que re-pintar `#tt-cert-body`
  conserve la pestaña, la búsqueda y el estado de la tabla de folios (§18
  regla 3).

Spec `docs/superpowers/specs/2026-10-01-titulatec-biblioteca-caja-design.md`
§4.5 (motor de constancias / la página), D7 (se acumulan, el área genera el
PDF cuando quiere), D15, §4.6 (permisos/menú), §5 invariantes 5 y 6; Tarea 1 de
`2026-10-02-titulatec-constancias-y-pendientes-design.md` §2 (E4/E8) y §3.1
(2 o 3 por hoja, `por_hoja` como filtro de vista); Tarea 2 §2 (E6/E7) y
§3.2/§3.5 (estado de impresión, lista de «Por imprimir» plegable y anuladas
tras imprimir); paginación: `2026-10-04-titulatec-paginacion-design.md`.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec
from itcj2.apps.titulatec.services.certificate_service import (
    CERT_KINDS, FOLIO_ESTADOS, printing_enabled,
)
from itcj2.apps.titulatec.utils.paging import PAGE_SIZE, normalize_q, parse_page

logger = logging.getLogger("itcj2.apps.titulatec.pages.certificates_admin")
router = APIRouter(prefix="/admin/constancias", tags=["titulatec-pages-certificates"])

_LIST = ["titulatec.certificate.page.list"]

# kind -> código que hace falta para VER (y, con el switch encendido,
# IMPRIMIR) ese tipo (spec §4.6, C2 del spec de folios). Es DISTINTO del código
# de la página (`_LIST`, arriba): entrar a la página y ver un tipo en concreto
# son preguntas separadas (docstring).
_KIND_PERM = {
    "library_clearance": "titulatec.library_clearance.api.print_certificates",
    "survey_release": "titulatec.survey_review.api.print_certificates",
}

# Etiqueta de pestaña/sección para la UI. No es `CERT_KINDS[...]['title']`: ese
# es el título IMPRESO en la constancia misma (mayúsculas a propósito, spec
# §4.5), una decisión de documento, no de pantalla.
_KIND_LABELS = {
    "library_clearance": "No adeudo de biblioteca",
    "survey_release": "Liberación de encuesta de egresados",
}

# Tamaño de página de «Lotes» (solo con el switch de impresión encendido). La
# tabla de folios pagina con `utils.paging.PAGE_SIZE` y el kwarg `per_page` de
# `_body_ctx`, nunca con esta constante.
_PAGE_SIZE = 20

# Chips de estado de la tabla de folios, en el orden de `FOLIO_ESTADOS`.
_ESTADO_LABELS = {"vigentes": "Vigentes", "anulados": "Anulados", "todos": "Todos"}
_DEFAULT_ESTADO = "vigentes"


def _hdr(msg: str) -> str:
    """Percent-encode para que un mensaje acentuado quepa en un header latin-1.

    Gemelo de `pages/survey_reviews_admin.py:54`, `pages/library_admin.py` y
    `pages/cashier_admin.py`; `titulatec-utils.js::decodeHeaderMsg` lo deshace
    al mostrarlo.
    """
    from urllib.parse import quote
    return quote(msg or "", safe="")


def _pages(lib_raw, survey_raw) -> dict[str, int]:
    """`{kind: página}` de «Lotes» para los 2 `CERT_KINDS`, SIEMPRE los dos
    (nunca solo el que trae la petición): así el formulario de «Generar lote»
    puede reenviar ambos en campos ocultos sin pelear con `None` en la
    plantilla."""
    return {"library_clearance": parse_page(lib_raw), "survey_release": parse_page(survey_raw)}


def _parse_por_hoja(raw) -> int:
    """`por_hoja` del query string del PDF -> 2 o 3, o
    `DEFAULT_PER_PAGE` si falta o viene fuera de forma (ausente, vacío,
    `abc`, `4`, ...): es un filtro de VISTA (spec §3.1, mismo criterio que
    `_parse_dia` de `pages/cashier_admin.py`), nunca una acción, así que un
    valor fuera de forma cae al valor por omisión en vez de responder 400.
    La función ESTRICTA (`ValueError` con cualquier otro valor) es
    `render_certificates_pdf`; esta normaliza ANTES de llamarla."""
    from itcj2.apps.titulatec.utils.certificate_pdf import ALLOWED_PER_PAGE, DEFAULT_PER_PAGE

    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PER_PAGE
    return n if n in ALLOWED_PER_PAGE else DEFAULT_PER_PAGE


def _visible_kinds(db, user_id: int) -> list[str]:
    """Los `CERT_KINDS` que este actor puede VER (y, con el switch encendido,
    imprimir), en el orden de `CERT_KINDS` (nunca el de llegada del set de
    permisos). ÚNICO lugar del archivo que resuelve esta pregunta -las cuatro
    rutas pasan por aquí, ver docstring del módulo-: un `kind` real fuera de
    esta lista responde 404."""
    from itcj2.core.services.authz_service import get_user_permissions_for_app

    perms = get_user_permissions_for_app(db, user_id, "titulatec")
    return [k for k in CERT_KINDS if _KIND_PERM[k] in perms]


def _kind_ajeno(raw, kinds: list[str]) -> bool:
    """¿`raw` es un `kind` REAL de `CERT_KINDS` que este actor no puede ver?
    Eso es un 404. Un valor ausente o que no es de `CERT_KINDS` NO lo es: es un
    filtro de vista mal escrito y `_body_ctx` lo resuelve al primer visible."""
    return isinstance(raw, str) and raw in CERT_KINDS and raw not in kinds


def _estado(raw) -> str:
    """El filtro de estado pedido, o `vigentes`. Nunca un valor arbitrario."""
    return raw if isinstance(raw, str) and raw in FOLIO_ESTADOS else _DEFAULT_ESTADO


def _body_url(pages: dict[str, int]) -> str:
    """URL de `GET /body` con el estado de paginación de los 2 kinds, en los
    MISMOS nombres de query param que leen las rutas (`page_{kind}`) -- `pages`
    viene indexado por `kind` a secas (`_pages`), así que sin este prefijo la
    URL generada traería `library_clearance=N` en vez de
    `page_library_clearance=N` y la ruta la ignoraría en silencio."""
    from urllib.parse import urlencode
    qs = {f"page_{kind}": page for kind, page in pages.items()}
    return "/titulatec/admin/constancias/body?" + urlencode(qs)


def _print_sections(db, kinds: list[str], pages: dict[str, int]) -> list[dict]:
    """Las secciones de impresión de la ronda del 2026-10-01/02: una por cada
    `kind` visible, en el orden de `CERT_KINDS`. SOLO se llama con el switch
    de impresión encendido (`_body_ctx`).

    Todo lo que la plantilla pinta -enlaces de paginación incluidos- ya viene
    PRECALCULADO: la plantilla no decide nada, solo pinta (mismo criterio que
    `utils/certificate_pdf.py`).

    Tarea 2 (E6/E7): cada sección también trae `pending_rows` -los nombres
    FIFO de `CertificateService.pending`, ya aplanados a dict (folio,
    egresado, control, carrera, emitida) para que la plantilla no toque el
    ORM- y `voided_rows` -de `CertificateService.voided_after_print` tal
    cual, sin transformar-. La plantilla decide con el largo de cada lista
    si pinta el `<details>` de pendientes o la sección de anuladas.
    `pending_count` sale de `len(pending_rows)`, NO de una llamada aparte a
    `CertificateService.pending_count` -esa haría una segunda consulta con
    el MISMO predicado (`_pending_criteria`) que `pending()` ya resolvió
    arriba; `pending_count` se queda disponible en el servicio para quien
    solo necesite el número sin pagar el costo de traer las filas."""
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    sections = []
    for kind in kinds:
        page = pages.get(kind, 1)
        batches, has_more = CertificateService.list_batches(
            db, kind=kind, page=page, per_page=_PAGE_SIZE)
        pending_rows = [
            {"id": c.id, "folio": c.number, "egresado": c.student_name,
             "control": c.control_number, "carrera": c.program_name,
             "emitida": c.issued_at}
            for c in CertificateService.pending(db, kind)
        ]
        sections.append({
            "kind": kind,
            "label": _KIND_LABELS[kind],
            "pending_count": len(pending_rows),
            "pending_rows": pending_rows,
            "voided_rows": CertificateService.voided_after_print(db, kind),
            "batches": batches,
            "page": page,
            "has_more": has_more,
            "prev_url": _body_url({**pages, kind: max(1, page - 1)}),
            "next_url": _body_url({**pages, kind: page + 1}),
        })
    return sections


def _body_ctx(db, *, user_id: int, pages: dict[str, int] | None = None,
              new_batch: dict | None = None, kinds: list[str] | None = None,
              kind: str | None = None, q=None, estado=None, page=1,
              per_page: int = PAGE_SIZE) -> dict:
    """Contexto del parcial: la tabla de folios y, SOLO con el switch de
    impresión encendido, las secciones de impresión de hoy (`sections`, vacío
    si está apagado: ni siquiera se consultan lotes ni pendientes).

    Folios (spec §3.6): `tabs` = `[(kind, etiqueta)]` de los `kind` que este
    actor ve, en el orden de `CERT_KINDS` (la plantilla solo pinta pestañas si
    hay más de uno); `kind` = el pedido si el actor lo ve, si no el primero
    visible (`None` si no ve ninguno, y entonces no se consulta nada); `q` ya
    normalizado (`normalize_q`); `estado` ∈ `FOLIO_ESTADOS` (cualquier otro
    valor cae en `vigentes`); `pg` = `Page` de `CertificateService.list_folios`
    y `rows` = sus items. `page` llega crudo (`str`/`int`): `parse_page`.
    `per_page` es kwarg (§18 regla 6) para que los tests no parchen la
    constante.

    `kinds=None` (el caso normal: `list_certificates`/`body`) los resuelve
    aquí mismo con `_visible_kinds`. Las rutas que YA los necesitan resueltos
    antes de llegar aquí (para decidir su propio 404) los pasan -- así no se
    preguntan permisos dos veces por la misma petición (m29,
    triage-minors.md). `pages` (la página de «Lotes» de cada `kind`) solo
    importa con el switch encendido."""
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    if kinds is None:
        kinds = _visible_kinds(db, user_id)
    if pages is None:
        pages = _pages(None, None)

    kind = kind if isinstance(kind, str) and kind in kinds else (kinds[0] if kinds else None)
    q_clean = normalize_q(q)
    estado = _estado(estado)
    pg = None
    if kind is not None:
        pg = CertificateService.list_folios(
            db, kind=kind, q=q_clean, estado=estado,
            page=parse_page(page), per_page=per_page)

    return {
        "tabs": [(k, _KIND_LABELS[k]) for k in kinds],
        "kind": kind,
        "kind_label": _KIND_LABELS[kind] if kind else "",
        "estados": [(e, _ESTADO_LABELS[e]) for e in FOLIO_ESTADOS],
        "estado": estado,
        "q": q_clean or "",
        "pg": pg,
        "rows": pg.items if pg is not None else [],
        "sections": _print_sections(db, kinds, pages) if printing_enabled() else [],
        "pages": pages,
        "new_batch": new_batch,
    }


@router.get("", name="titulatec.pages.certificates.list")
async def list_certificates(
    request: Request,
    kind: str = "", q: str = "", estado: str = "vigentes", page: str = "1",
    page_library_clearance: str = "1", page_survey_release: str = "1",
    user: dict = Depends(require_page_app("titulatec", perms=_LIST)),
):
    """La página: tabla de folios del `kind` pedido (o el primero visible),
    con `q`/`estado`/`page`. `page_library_clearance`/`page_survey_release`
    solo importan con el switch de impresión encendido («Lotes»). Un `kind`
    real que el actor no ve responde 404."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        uid = int(user["sub"])
        kinds = _visible_kinds(db, uid)
        if _kind_ajeno(kind, kinds):
            return Response(status_code=404)
        ctx = _body_ctx(db, user_id=uid, kinds=kinds,
                        pages=_pages(page_library_clearance, page_survey_release),
                        kind=kind, q=q, estado=estado, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/certificates.html", ctx)


@router.get("/body", name="titulatec.pages.certificates.body")
async def body(
    request: Request,
    kind: str = "", q: str = "", estado: str = "vigentes", page: str = "1",
    page_library_clearance: str = "1", page_survey_release: str = "1",
    user: dict = Depends(require_page_app("titulatec", perms=_LIST)),
):
    """Hermana de la página: acepta LOS MISMOS query params (HTMX manda los
    del contenedor de filtros, aunque este actor solo vea un `kind`)."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        uid = int(user["sub"])
        kinds = _visible_kinds(db, uid)
        if _kind_ajeno(kind, kinds):
            return Response(status_code=404)
        ctx = _body_ctx(db, user_id=uid, kinds=kinds,
                        pages=_pages(page_library_clearance, page_survey_release),
                        kind=kind, q=q, estado=estado, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/certificates_body.html", ctx)


@router.post("/{kind}/lote", name="titulatec.pages.certificates.create_batch")
async def create_batch(
    kind: str, request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=_LIST)),
):
    """«Generar lote» (D7): toma TODAS las pendientes de `kind` y las agrupa
    (`CertificateService.create_batch`, su propio commit). Los DOS enlaces
    para abrir el PDF en pestaña nueva (3 y 2 por hoja, `target="_blank"`,
    sin script inline) salen en el parcial re-pintado, como «Lote recién
    generado». El formulario incluye `#tt-folio-filters`, así que el
    parcial vuelve con la MISMA vista de folios (`kind`, `q`, `estado`,
    `page` del formulario; sin ellos, los valores por omisión).

    Con el switch de impresión apagado (`printing_enabled()`) responde 404
    ANTES de cualquier otra cosa (spec folios 2026-10-05 §3.5)."""
    if not printing_enabled():
        return Response(status_code=404)

    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    form = await request.form()
    pages = _pages(form.get("page_library_clearance"), form.get("page_survey_release"))

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        kinds = _visible_kinds(db, uid)
        if kind not in kinds:
            return Response(status_code=404)
        try:
            batch = CertificateService.create_batch(db, kind=kind, actor_id=uid)
        except ValueError as e:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(e))})
        batch_id, batch_count = batch.id, batch.count
        # El lote recién creado siempre sale en la primera página de «Lotes»
        # de SU kind; la página del otro kind (si lo hay) se conserva tal cual.
        pages[kind] = 1
        # `kinds` ya resuelto arriba (línea del 404): se lo pasamos a
        # `_body_ctx` para no volver a preguntar permisos (m29).
        ctx = _body_ctx(db, user_id=uid, pages=pages, kinds=kinds,
                        new_batch={"id": batch_id, "kind": kind, "count": batch_count},
                        kind=form.get("kind"), q=form.get("q"),
                        estado=form.get("estado"), page=form.get("page"))
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
    por_hoja: str = "",
    user: dict = Depends(require_page_app("titulatec", perms=_LIST)),
):
    """El PDF de un lote, inline (se abre en pestaña nueva desde uno de los
    dos `<a>` planos del parcial -3 o 2 por hoja-, nunca con JS). SIEMPRE se
    regenera -nunca se guarda, ver `utils/certificate_pdf.py`-; 404 si el
    lote no existe O si su `kind` no es de los que este actor puede ver
    (nunca 403: mismo criterio que `_visible_kinds`, arriba).

    `por_hoja` (spec §3.1/E4) es un filtro de VISTA, normalizado por
    `_parse_por_hoja` ANTES de llamar a `render_certificates_pdf` -ausente,
    vacío o fuera de forma (`4`, `abc`, ...) caen en 3, nunca 400/500-; el
    acomodo elegido se refleja en el nombre del archivo
    (`constancias_{kind}_{batch_id}_{n}xhoja.pdf`), nunca se guarda en el
    lote (el mismo lote puede reabrirse después con el otro acomodo).

    Es `def` y no `async def` a propósito (Ruling R23, I5 de la revisión
    final): WeasyPrint es CPU bloqueante -medido en el contenedor: 30
    constancias 1.7 s, 300 constancias 14.6 s- y en una `async def`
    congelaba el event loop del worker HTTP entero (de TODA la plataforma,
    no solo de TitulaTec) en cada «PDF · 3 por hoja»/«PDF · 2 por hoja». En
    `def`, FastAPI la corre en su threadpool, igual que `appointments.move`
    con el `FOR UPDATE` de `SlotService`. No lee el cuerpo de la petición,
    así que no necesita `await request.form()`.

    Con el switch de impresión apagado (`printing_enabled()`) responde 404
    ANTES de cualquier otra cosa, aunque el lote exista (spec folios
    2026-10-05 §3.5)."""
    if not printing_enabled():
        return Response(status_code=404)

    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import CertificateBatch
    from itcj2.apps.titulatec.services.certificate_service import CertificateService
    from itcj2.apps.titulatec.utils.certificate_pdf import render_certificates_pdf

    n = _parse_por_hoja(por_hoja)
    db = SessionLocal()
    try:
        uid = int(user["sub"])
        batch = db.get(CertificateBatch, batch_id)
        if batch is None:
            return Response(status_code=404)
        kind = batch.kind
        if kind not in _visible_kinds(db, uid):
            return Response(status_code=404)
        certs = CertificateService.certificates_of(db, batch_id)
        pdf_bytes = render_certificates_pdf(certs, per_page=n)
    finally:
        db.close()
    filename = f"constancias_{kind}_{batch_id}_{n}xhoja.pdf"
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})
