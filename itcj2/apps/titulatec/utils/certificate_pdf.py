"""PDF de constancias por lote (TitulaTec) -- WeasyPrint sobre HTML/CSS propio.

Spec `2026-10-01-titulatec-biblioteca-caja-design.md` §4.5: 3 constancias por
hoja carta, separadas por una línea de corte punteada con una tijera entre
cada ranura. El PDF NUNCA se guarda (ver el docstring de
`models/certificate.py`): esta función lo REGENERA siempre, a partir de los
datos ya CONGELADOS en cada fila -- mismo resultado cada vez, nada que
mantener sincronizado con la base.

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

# Constancias por hoja carta (spec D7/§4.5). Cambiar esto mueve también la
# plantilla (grupos de `PER_PAGE` ranuras por `.sheet`) -- ver
# `sheet.html`.
PER_PAGE = 3

# `itcj2/core/static/`: calculado desde el paquete, no desde el cwd del
# proceso (WeasyPrint resuelve las rutas relativas del HTML contra esto).
CORE_STATIC_DIR = Path(itcj2.__file__).resolve().parent / "core" / "static"

_TEMPLATE_NAME = "titulatec/certificates/sheet.html"


def _cert_ctx(cert) -> dict:
    """Una `Certificate` -> el dict plano que consume la plantilla. Todo
    PRECALCULADO en Python (fecha en español, textos del tipo): la plantilla
    no toma ninguna decisión, solo pinta."""
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
    }


def render_certificates_pdf(certs: list[Certificate]) -> bytes:
    """Arma el PDF de una lista de constancias (típicamente las de UN lote,
    en el orden que traiga `certs`): `PER_PAGE` por hoja carta.

    Una lista vacía SÍ produce un PDF (de una página en blanco -- WeasyPrint
    siempre renderiza al menos el `@page` declarado, aunque el cuerpo esté
    vacío): decidir si eso es un error de negocio es tarea del llamador
    (`create_batch` ya impide un lote de 0 más arriba), no de esta función.
    """
    from weasyprint import HTML
    from itcj2.apps.titulatec.pages.nav import titulatec_templates

    grupos = [
        [_cert_ctx(c) for c in certs[i:i + PER_PAGE]]
        for i in range(0, len(certs), PER_PAGE)
    ]
    template = titulatec_templates.get_template(_TEMPLATE_NAME)
    html = template.render(groups=grupos)
    return HTML(string=html, base_url=str(CORE_STATIC_DIR)).write_pdf()
