"""Catálogo cerrado de los formatos de Prórrogas y sus marcadores.

Cada formato declara qué marcadores puede traer su plantilla (``allowed``),
cuáles no pueden faltar (``required``) y cuáles se sustituyen por imagen
(``images``). La validación de las plantillas que sube la secretaria y los
valores que se llenan al generar salen de aquí. Fuente: spec §6.2.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from itcj2.apps.prorrogas_tec.services.formatting import fecha_corta, fecha_larga, pesos, split_amount

DEFAULTS_DIR = Path(__file__).resolve().parent / "defaults"

COMMON_FIELDS: frozenset[str] = frozenset({"fecha", "folio", "nombre", "no_control", "carrera", "semestre"})

_FIRMA = frozenset({"firma_estudiante", "firma_estudiante_leyenda"})


@dataclass(frozen=True)
class DocType:
    code: str
    label: str
    required: frozenset[str]
    allowed: frozenset[str]
    images: frozenset[str]


def _compromiso(n: int) -> DocType:
    pagos = range(1, n + 1)
    fechas = {f"pago{i}_fecha" for i in pagos}
    montos = {f"pago{i}_monto" for i in pagos}
    return DocType(
        code=f"carta_compromiso_{n}",
        label=f"Carta compromiso · {n} pago" + ("" if n == 1 else "s"),
        # Con un solo pago la carta real dice "Pago Único: <fecha>": el monto
        # del pago es el total y no se repite.
        required=frozenset({"nombre", "no_control", "monto_total", "firma_estudiante"} | fechas
                           | (montos if n >= 2 else set())),
        allowed=COMMON_FIELDS | _FIRMA | {"monto_total"} | fechas | montos,
        images=frozenset({"firma_estudiante"}),
    )


DOC_TYPES: dict[str, DocType] = {
    t.code: t for t in (
        DocType(
            code="formato_solicitud",
            label="Formato de solicitud",
            required=frozenset({"nombre", "no_control", "motivo", "plazos_solicitados", "firma_estudiante"}),
            allowed=COMMON_FIELDS | _FIRMA | {"fecha_solicitud", "plazos_solicitados", "motivo", "correo"},
            images=frozenset({"firma_estudiante"}),
        ),
        DocType(
            code="carta_aceptacion",
            label="Carta de aceptación",
            required=frozenset({"nombre", "no_control"}),
            allowed=COMMON_FIELDS | {"comentario", "plazos_solicitados"},
            images=frozenset(),
        ),
        DocType(
            code="carta_rechazo",
            label="Carta de rechazo",
            required=frozenset({"nombre", "no_control", "motivo_rechazo"}),
            allowed=COMMON_FIELDS | {"motivo_rechazo"},
            images=frozenset(),
        ),
        _compromiso(1),
        _compromiso(2),
        _compromiso(3),
    )
}


def default_template_path(code: str) -> Path:
    """Plantilla del sistema (la que se usa si nadie ha subido una)."""
    return DEFAULTS_DIR / f"{code}.docx"


@lru_cache(maxsize=1)
def sample_signature_png() -> bytes:
    """Un trazo de ejemplo para la vista previa de los formatos con firma."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (600, 180), (0, 0, 0, 0))
    ImageDraw.Draw(img).line(
        [(30, 120), (110, 50), (170, 135), (250, 60), (330, 125), (420, 70), (570, 95)],
        fill="#1A130E", width=6, joint="curve",
    )
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


_SAMPLE_TOTAL = Decimal("3650")
_SAMPLE_DUE = (date(2026, 2, 13), date(2026, 2, 27), date(2026, 3, 27))


def sample_values(code: str, *, today: date | None = None) -> tuple[dict[str, str], dict[str, bytes]]:
    """Valores ficticios para la vista previa de ``code``: cubren todo lo permitido."""
    if today is None:
        from itcj2.core.utils.timezone import db_now
        today = db_now().date()
    t = DOC_TYPES[code]
    hoy = fecha_corta(today)
    pool = {
        "fecha": hoy,
        "fecha_solicitud": hoy,
        "folio": "PR-00000",
        "nombre": "ESTUDIANTE DE EJEMPLO",
        "no_control": "99000000",
        "carrera": "Ingeniería en Sistemas Computacionales",
        "semestre": "enero – junio 2026",
        "plazos_solicitados": "3",
        "motivo": "Motivo de ejemplo: el pago de nómina se retrasó este mes.",
        "correo": "L99000000@cdjuarez.tecnm.mx",
        "comentario": "Comentario de ejemplo.",
        "motivo_rechazo": "Motivo de ejemplo del rechazo.",
        "monto_total": pesos(_SAMPLE_TOTAL),
        "firma_estudiante_leyenda": (
            f"Firmado electrónicamente por ESTUDIANTE DE EJEMPLO el {today:%d/%m/%Y} 10:42 · folio PR-00000"
        ),
    }
    if code.startswith("carta_compromiso_"):
        n = int(code.rsplit("_", 1)[1])
        for i, (monto, due) in enumerate(zip(split_amount(_SAMPLE_TOTAL, n), _SAMPLE_DUE), start=1):
            pool[f"pago{i}_monto"] = pesos(monto)
            pool[f"pago{i}_fecha"] = fecha_larga(due)
    values = {k: pool[k] for k in t.allowed - t.images}
    images = {k: sample_signature_png() for k in t.images}
    return values, images
