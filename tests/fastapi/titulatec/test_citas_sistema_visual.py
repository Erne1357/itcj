"""Sistema visual de Citas de cotejo: contraste, escala tipografica y patrones.

Ratios calculados sobre la pestana viva el 2026-09-03 (formula WCAG 2.x):

    --tt-mute   #94A3B8 sobre #FFFFFF = 2.56:1   (texto normal pide 4.5)
    --tt-mute   #94A3B8 sobre #F8FAFC = 2.45:1
    --tt-accent #F59E0B como anillo   = 2.15:1   (no-texto pide 3.0, WCAG 1.4.11)
    .tt-cal .sel #FFF3D6              = 1.10:1   (era la UNICA senal del dia abierto)

Sustitutos, tambien calculados:

    --tt-text-3 #5B6B82 = 5.43 / 5.19   (se descarto #64748B: 4.76 / 4.55, al filo)
    --tt-focus  #B45309 = 5.02 / 4.80

Y la escala: se midieron ONCE tamanos renderizados entre 10.88 y 20 px con pasos
de 0.2 px. Eso no es una escala, es la razon por la que "se ve todo desalineado".
"""
import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[3] / "itcj2/apps/titulatec/static/css/titulatec.css"
INICIO_BLOQUE = "ADMIN - CITAS DE COTEJO"


def _texto():
    return CSS.read_text(encoding="utf-8")


def _sin_comentarios(t):
    return re.sub(r"/\*.*?\*/", "", t, flags=re.S)


def _bloque_citas(t):
    i = t.find(INICIO_BLOQUE)
    assert i != -1, f"no se encontro '{INICIO_BLOQUE}' en titulatec.css"
    return t[i:]


def test_ningun_texto_usa_tt_mute():
    """--tt-mute esta a 2.45-2.56:1. Queda solo para bordes e iconos decorativos.

    Lo tenia aplicado la capa ENTERA de etiquetas: .tt-kicker (los 18 rotulos de
    la pestana, ocho de ellos <label> de formulario), .tt-cal th a 10.88 px,
    .tt-appt-item .meta -que es el NUMERO DE CONTROL, el dato que se cruza
    caracter por caracter contra el expediente de papel-, .tt-appt-hint y
    .tt-appt-empty.
    """
    culpables = [
        ln.strip() for ln in _sin_comentarios(_texto()).splitlines()
        if re.search(r"(^|[^-\w])color\s*:\s*var\(\s*--tt-mute\s*\)", ln)
    ]
    assert not culpables, (
        "--tt-mute usado como color de TEXTO (2.56:1, necesita 4.5). "
        "Usa --tt-text-3 (#5B6B82, 5.43:1).\n" + "\n".join("  " + c for c in culpables)
    )


def test_existen_los_tokens_de_texto_y_de_foco():
    t = _texto()
    esperados = {"--tt-text-1": "#0F172A", "--tt-text-2": "#475569",
                 "--tt-text-3": "#5B6B82", "--tt-focus": "#B45309"}
    faltan = [f"{k}: {v}" for k, v in esperados.items()
              if not re.search(rf"{k}\s*:\s*{v}\b", t, re.I)]
    assert not faltan, "faltan tokens de contraste: " + ", ".join(faltan)


def test_la_escala_tipografica_tiene_seis_pasos_y_piso():
    """Base 16, razon ~1.125-1.25, piso 12.64 px. Nada por debajo."""
    t = _texto()
    esperados = {"--tt-fs-100": "0.79", "--tt-fs-200": "0.889", "--tt-fs-300": "1",
                 "--tt-fs-400": "1.125", "--tt-fs-500": "1.266", "--tt-fs-600": "1.602"}
    faltan = []
    for token, rem in esperados.items():
        # acepta `.79rem` y `0.79rem`
        patron = rf"{token}\s*:\s*0?{re.escape(rem.lstrip('0'))}rem"
        if not re.search(patron, t):
            faltan.append(f"{token}: {rem}rem")
    assert not faltan, "faltan pasos de la escala: " + ", ".join(faltan)


def test_el_bloque_de_citas_no_lleva_font_size_literal():
    culpables = [
        ln.strip() for ln in _sin_comentarios(_bloque_citas(_texto())).splitlines()
        if re.search(r"font-size\s*:\s*[\d.]+(rem|px|em)\b", ln)
    ]
    assert not culpables, (
        "font-size literal en el bloque de Citas; usa los tokens --tt-fs-*.\n"
        + "\n".join("  " + c for c in culpables)
    )


def test_ningun_patron_prohibido_en_todo_el_archivo():
    """Se barre el archivo ENTERO, no solo el bloque de Citas.

    Los tres patrones que usa esta pestana estan declarados en secciones
    COMPARTIDAS (`.tt-card--accent` en la de tarjetas, `.tt-cal .off` y
    `.tt-cal .sel` en la del calendario), asi que un barrido acotado al bloque
    de Citas pasaria en falso. Y arreglarlos ahi cura de paso el calendario de
    Convocatorias, que comparte `.tt-cal`.
    """
    limpio = _sin_comentarios(_texto())
    prohibidos = {
        r"border-left\s*:\s*[2-9]\d*px":
            "borde lateral de acento: desplaza 2 px el contenido respecto a la lista de al lado "
            "(medido: nombres a x=294 y x=296 en dos listas contiguas)",
        r"repeating-linear-gradient":
            "trama de rayas: hacia que los 24 dias MUERTOS fueran lo mas ruidoso de la "
            "pantalla, o sea jerarquia invertida",
        r"#FFF3D6":
            "hex fuera del sistema de tokens a 1.10:1 (usa var(--tt-accent-soft))",
    }
    fallos = []
    for patron, msg in prohibidos.items():
        lineas = [ln.strip() for ln in limpio.splitlines() if re.search(patron, ln, re.I)]
        if lineas:
            fallos.append(msg + "\n" + "\n".join("      " + l for l in lineas))
    assert not fallos, "\n".join(fallos)


def test_el_anillo_de_foco_no_usa_el_acento():
    """#F59E0B da 2.15:1 sobre blanco y 2.05:1 sobre mist. WCAG 1.4.11 pide 3:1."""
    bloque = _sin_comentarios(_bloque_citas(_texto()))
    culpables = [ln.strip() for ln in bloque.splitlines()
                 if "outline" in ln and "--tt-accent" in ln]
    assert not culpables, (
        "anillo de foco con --tt-accent (2.15:1). Usa --tt-focus (#B45309, 5.02:1).\n"
        + "\n".join("  " + c for c in culpables)
    )
