"""PDF de constancias por lote (TitulaTec) -- WeasyPrint sobre HTML/CSS propio.

Spec `2026-10-02-titulatec-constancias-y-pendientes-design.md` §2 (E4/E8) y
§3.1: 2 o 3 constancias por hoja carta, acomodo elegido CADA VEZ que se abre
el PDF (nunca se guarda en el lote; antecede spec
`2026-10-01-titulatec-biblioteca-caja-design.md` §4.5, que fijaba 3 siempre).
Separadas por una línea de corte punteada con una tijera entre cada ranura.
El PDF NUNCA se guarda (ver el docstring de `models/certificate.py`): esta
función lo REGENERA siempre, a partir de los datos ya CONGELADOS en cada fila
-- mismo resultado cada vez, nada que mantener sincronizado con la base.

Plantilla en DOS PIEZAS (E8, pensando en los formatos oficiales que cada área
trae después): `sheet.html` (la hoja carta -- `@page`, acomodo `sheet--2`/
`sheet--3`, línea de corte) y la RANURA de una constancia, una plantilla por
`kind` (`SLOT_TEMPLATES`). Hoy los dos tipos comparten la misma
`_slot.html` (el contenido de siempre, sin cambios); el día que llegue un
formato propio por área, solo cambia esa entrada del mapa -- ni `sheet.html`
ni esta función se tocan. `_cert_ctx` ya resuelve la plantilla de ranura de
cada constancia (`slot_template`): `sheet.html` no decide nada, solo pinta.

La plantilla (`templates/titulatec/certificates/sheet.html`) NO extiende
`base.html` ni ningún layout HTTP de la app: es un documento HTML completo,
pensado solo para WeasyPrint, con su propio `@page` y su propio CSS. Se
renderiza con el motor de plantillas propio de la app
(`pages.nav.titulatec_templates`, `.get_template(...).render(...)`, igual que
`services/email_helper.py::_render`): aquí no hay una petición HTTP detrás, así
que nunca se usa `TemplateResponse`.

Las imágenes (logo TecNM + escudo ITCJ) se referencian en el HTML con rutas
RELATIVAS ('images/...'), resueltas por WeasyPrint contra `base_url` =
`itcj2/core/static/` -- los MISMOS archivos que sirve nginx para el resto de
la app (`images/logo_tecnm.png`, `images/escudo_itcj_negro.png`). Se calcula
desde el propio paquete (`itcj2.__file__`), nunca desde el cwd del proceso.
"""
from __future__ import annotations

from pathlib import Path

import itcj2

from itcj2.apps.titulatec.utils.dates_es import dia_mes

# Acomodos permitidos y el que se usa por omisión (spec E4: 3 si no se pide
# nada, D7 de ayer). Un `per_page` fuera de este dominio es un error de
# PROGRAMADOR -- `ValueError` -- distinto del filtro de VISTA `por_hoja` de
# la ruta (`pages/certificates_admin.py::_parse_por_hoja`), que normaliza
# cualquier valor fuera de forma ANTES de llegar aquí y nunca deja pasar uno
# inválido.
ALLOWED_PER_PAGE = (2, 3)
DEFAULT_PER_PAGE = 3

# `itcj2/core/static/`: calculado desde el paquete, no desde el cwd del
# proceso (WeasyPrint resuelve las rutas relativas del HTML contra esto).
CORE_STATIC_DIR = Path(itcj2.__file__).resolve().parent / "core" / "static"

_TEMPLATE_NAME = "titulatec/certificates/sheet.html"

# kind -> plantilla de RANURA (E8). Hoy los dos tipos comparten el mismo
# contenido (`_slot.html`); mañana, cuando lleguen los formatos oficiales de
# cada área, cada entrada apunta a la suya sin tocar `sheet.html` ni
# `render_certificates_pdf`.
SLOT_TEMPLATES: dict[str, str] = {
    "library_clearance": "titulatec/certificates/_slot.html",
    "survey_release": "titulatec/certificates/_slot.html",
}


def _cert_ctx(cert) -> dict:
    """Una `Certificate` -> el dict plano que consume la plantilla. Todo
    PRECALCULADO en Python (fecha en español, textos del tipo, plantilla de
    ranura según `kind`): la plantilla no toma ninguna decisión, solo pinta."""
    from itcj2.apps.titulatec.services.certificate_service import CERT_KINDS

    kind = CERT_KINDS[cert.kind]
    return {
        "number": cert.number,
        "control_number": cert.control_number,
        "student_name": cert.student_name,
        "program_name": cert.program_name,
        "period_label": cert.period_label,
        "issued_label": f"{dia_mes(cert.issued_at)} de {cert.issued_at.year}",
        "voided": cert.voided_at is not None,
        "title": kind["title"],
        "department": kind["department"],
        "phrase": kind["phrase"],
        "slot_template": SLOT_TEMPLATES[cert.kind],
    }


def render_certificates_pdf(certs: list[Certificate], per_page: int = DEFAULT_PER_PAGE) -> bytes:
    """Arma el PDF de una lista de constancias (típicamente las de UN lote,
    en el orden que traiga `certs`): `per_page` (2 o 3, spec E4) por hoja
    carta. Un `per_page` fuera de `ALLOWED_PER_PAGE` truena con `ValueError`:
    esta función no ve la petición HTTP directamente -- la ruta
    (`pages/certificates_admin.py::batch_pdf`) ya normalizó cualquier valor
    fuera de forma antes de llamarla, así que llegar aquí con otro valor es
    un error de quien programa, no de quien usa la página.

    Una lista vacía SÍ produce un PDF (de una página en blanco -- WeasyPrint
    siempre renderiza al menos el `@page` declarado, aunque el cuerpo esté
    vacío): decidir si eso es un error de negocio es tarea del llamador
    (`create_batch` ya impide un lote de 0 más arriba), no de esta función.
    """
    from weasyprint import HTML
    from itcj2.apps.titulatec.pages.nav import titulatec_templates

    if per_page not in ALLOWED_PER_PAGE:
        raise ValueError(f"per_page debe ser uno de {ALLOWED_PER_PAGE}, no {per_page!r}.")

    grupos = [
        [_cert_ctx(c) for c in certs[i:i + per_page]]
        for i in range(0, len(certs), per_page)
    ]
    template = titulatec_templates.get_template(_TEMPLATE_NAME)
    html = template.render(groups=grupos, per_page=per_page)
    return HTML(string=html, base_url=str(CORE_STATIC_DIR)).write_pdf()
