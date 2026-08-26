"""Vocabulario de controles de Calidad: un solo lenguaje para toda la app.

Por qué un lint sobre las plantillas y no un E2E
-----------------------------------------------
Lo que se vigila aquí es la FORMA del markup, no lo que hace el navegador con
él. Un E2E solo ve la pantalla que visita y solo si tiene datos; este recorre
las 34 plantillas siempre, en dos segundos y sin contenedor. Los defectos que
cubre son de los que crecen en silencio: nadie nota que el botón de "Guardar"
de una pantalla mide dos píxeles más que el de la de al lado hasta que están
juntos.

Lo que encontró la auditoría, y que estas reglas congelan:

  · 26 usos de cinco clases alias del legacy (``adhoc-btn-filter``,
    ``-clear``, ``-add``, ``-save``, ``-delete``) que son copias exactas de
    variantes que ya existen — pero SIN ``:hover``, y mezcladas al azar con las
    de verdad en la misma barra;
  · 47 botones sin ``btn-sm``: el mismo "Añadir Nuevos" medía 10px/0.9rem en
    una pantalla y 8px/0.85rem en su hermana;
  · tres pies de modal distintos entre 13 diálogos;
  · "Guardar" con disquete en 13 sitios y con un check en 4;
  · dos familias de icono de fila para el mismo papel.

Las reglas se escriben con el mensaje de error completo a propósito: cuando una
falla, el que la lea tiene que poder arreglarla sin abrir este archivo.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3] / "itcj2" / "apps" / "adhoc"
PLANTILLAS = RAIZ / "templates" / "adhoc"
HOJAS = RAIZ / "static" / "css"


def _plantillas() -> list[tuple[str, str]]:
    """(nombre relativo, contenido) de las plantillas de pantalla.

    Se excluyen las de correo: el CSS en línea ahí es obligatorio y su markup
    no comparte vocabulario con la app.
    """
    out = []
    for ruta in sorted(PLANTILLAS.rglob("*.html")):
        if "emails" in ruta.parts:
            continue
        out.append((str(ruta.relative_to(PLANTILLAS)).replace("\\", "/"),
                    ruta.read_text(encoding="utf8")))
    return out


#: `<button>` o `<a>` completos, con sus atributos y su contenido.
RE_CONTROL = re.compile(r"<(button|a)\b(?P<attrs>[^>]*)>(?P<inner>.*?)</(?:button|a)>", re.S)
RE_CLASE = re.compile(r'class="([^"]*)"')

#: Un hex de 3 a 8 dígitos, o un `rgb()`/`rgba()`.
RE_COLOR = r"(#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\))"

#: Una clase usada de verdad: entre comillas, espacios o el punto de un selector.
RE_USO_CLASE = r"[\s\"\'.]%s[\s\"\'{,:]"



def _controles(fuente: str):
    for m in RE_CONTROL.finditer(fuente):
        mc = RE_CLASE.search(m.group("attrs"))
        clases = mc.group(1).split() if mc else []
        yield clases, m.group("inner"), m.group(0)


# ── 1. las clases alias del legacy ─────────────────────────────────────────

#: Alias → variante real. Son copias EXACTAS salvo por el `:hover`, que los
#: alias no declaran: un botón "Limpiar" escrito con el alias no reaccionaba al
#: ratón y el de al lado sí.
ALIAS = {
    "adhoc-btn-filter": "btn-primary",
    "adhoc-btn-add": "btn-primary",
    "adhoc-btn-save": "btn-primary",
    "adhoc-btn-search": "btn-primary",
    "adhoc-btn-clear": "btn-secondary",
    "adhoc-btn-delete": "btn-danger",
}


def test_no_quedan_clases_alias_del_legacy():
    culpables = []
    for nombre, fuente in _plantillas():
        for alias, real in ALIAS.items():
            for i, linea in enumerate(fuente.splitlines(), 1):
                if re.search(rf"\b{alias}\b", linea):
                    culpables.append(f"{nombre}:{i} usa {alias} (usar {real})")
    assert not culpables, (
        "Clases alias del legacy en las plantillas. Son copias exactas de una "
        "variante que ya existe, pero sin `:hover`, así que dos botones del "
        "mismo papel se comportan distinto en la misma barra:\n  "
        + "\n  ".join(culpables)
    )


def test_las_clases_alias_no_existen_en_la_hoja():
    base = (HOJAS / "adhoc.css").read_text(encoding="utf8")
    vivos = [a for a in ALIAS if re.search(rf"^\.{a}\b", base, re.M)]
    assert not vivos, (
        f"adhoc.css todavía declara {vivos}. Borrar el bloque de alias: mientras "
        "exista, alguien lo volverá a usar."
    )


# ── 2. un solo tamaño de botón ─────────────────────────────────────────────

def test_todo_boton_lleva_btn_sm():
    culpables = []
    for nombre, fuente in _plantillas():
        for clases, _inner, crudo in _controles(fuente):
            if "btn" not in clases:
                continue
            if "btn-sm" in clases or "btn-lg" in clases:
                continue
            culpables.append(f"{nombre}: {' '.join(clases)[:60]}  ←  {crudo[:70]}")
    assert not culpables, (
        "Botones sin `btn-sm`. El tamaño de la app es UNO: `btn btn-sm {variante}`. "
        "Con dos tamaños conviviendo, el mismo botón mide distinto según la "
        "pantalla — y a veces dentro de la misma barra:\n  " + "\n  ".join(culpables)
    )


# ── 3. el pie de un diálogo es siempre el mismo ────────────────────────────

RE_PIE = re.compile(r'<div class="(?:adhoc-)?modal-footer"[^>]*>(?P<cuerpo>.*?)</div>', re.S)

#: Cancelar · confirmar · eliminar. El de eliminar va a la izquierda del todo
#: (`me-auto`) para que no quede pegado al de confirmar.
PIE_PERMITIDO = {
    "btn btn-sm btn-secondary",
    "btn btn-sm btn-primary",
    "btn btn-sm btn-danger me-auto",
}


def test_el_pie_de_los_modales_es_uno_solo():
    culpables = []
    for nombre, fuente in _plantillas():
        for m in RE_PIE.finditer(fuente):
            for clases in re.findall(r'class="((?:btn|adhoc-btn)[^"]*)"', m.group("cuerpo")):
                normal = " ".join(clases.split())
                if normal not in PIE_PERMITIDO:
                    culpables.append(f"{nombre}: '{normal}'")
    assert not culpables, (
        "Pies de modal fuera del vocabulario. Los 13 diálogos usan el mismo par:\n"
        "    cancelar   btn btn-sm btn-secondary\n"
        "    confirmar  btn btn-sm btn-primary\n"
        "    eliminar   btn btn-sm btn-danger me-auto\n"
        "Encontrado:\n  " + "\n  ".join(culpables)
    )


# ── 4. un concepto, un icono ───────────────────────────────────────────────

def test_guardar_siempre_es_el_disquete():
    culpables = []
    for nombre, fuente in _plantillas():
        for clases, inner, _crudo in _controles(fuente):
            texto = re.sub(r"<[^>]+>", "", inner).strip().lower()
            if "guardar" not in texto:
                continue
            if "fa-floppy-disk" in inner:
                continue
            iconos = re.findall(r"fa-[a-z-]+", inner)
            culpables.append(f"{nombre}: '{texto[:30]}' con {iconos}")
    assert not culpables, (
        "«Guardar» tiene que llevar SIEMPRE `fa-solid fa-floppy-disk`. El check "
        "(`fa-check`) significa «confirmar» en el resto de la app y usarlo aquí "
        "hace que dos botones distintos se vean iguales:\n  " + "\n  ".join(culpables)
    )


# ── 5. nada de clases muertas ──────────────────────────────────────────────

def test_toda_clase_de_body_tiene_reglas():
    """`{% block body_class %}` con un valor que ninguna hoja usa es ruido.

    Cuatro de los valores emitidos no tenían NI UNA regla: quien lee la
    plantilla cree que hacen algo y quien lee el CSS no las encuentra.
    """
    css = "\n".join(p.read_text(encoding="utf8") for p in HOJAS.rglob("*.css"))
    muertas = []
    for nombre, fuente in _plantillas():
        for m in re.finditer(r"{%\s*block body_class\s*%}(?P<v>[^{]*){%\s*endblock", fuente):
            for clase in m.group("v").split():
                if not clase.startswith("adhoc-"):
                    continue
                if re.search(rf"\.{re.escape(clase)}\b", css):
                    continue
                muertas.append(f"{nombre}: '{clase}'")
    assert not muertas, (
        "Clases de página que no tienen ninguna regla. O se les da estilo o se "
        "borran del `{% block body_class %}`:\n  " + "\n  ".join(muertas)
    )


# ── 6. la fila en edición se ve ────────────────────────────────────────────

def test_la_fila_en_edicion_tiene_senal_visual():
    """`catalog-crud.js` marca la fila con `.adhoc-row-editing` y ninguna hoja la pintaba."""
    css = "\n".join(p.read_text(encoding="utf8") for p in HOJAS.rglob("*.css"))
    assert re.search(r"\.adhoc-row-editing\b", css), (
        "`.adhoc-row-editing` la pone catalog-crud.js al entrar en edición en "
        "línea, pero ninguna hoja la pinta: la fila que estás editando se ve "
        "igual que las demás."
    )


# ── 7. el foco se ve en TODO control ───────────────────────────────────────

@pytest.mark.parametrize(
    "selector",
    [".adhoc-back", ".adhoc-btn-header"],
)
def test_los_controles_del_shell_tienen_foco_visible(selector):
    base = (HOJAS / "adhoc.css").read_text(encoding="utf8")
    assert re.search(rf"{re.escape(selector)}:focus-visible", base), (
        f"`{selector}` no declara `:focus-visible`. Es el control más repetido "
        "de la app (el «Volver» sale en 19 pantallas) y quien navega con teclado "
        "no puede saber dónde está."
    )


# ── 8. la capa de tokens es la fuente de verdad ────────────────────────────

def _css_sin_comentarios(texto: str) -> str:
    return re.sub(r"/\*.*?\*/", "", texto, flags=re.S)


def _hojas_sin_root() -> list:
    """Cada hoja sin comentarios y sin su bloque ``:root``."""
    out = []
    for ruta in sorted(HOJAS.rglob("*.css")):
        s = _css_sin_comentarios(ruta.read_text(encoding="utf8"))
        i = s.find(":root {")
        if i >= 0:
            s = s[:i] + s[s.index("}", i) + 1:]
        out.append((ruta.name, s))
    return out


def test_ningun_color_vive_fuera_de_root():
    """La capa 1 de adhoc.css lo declara, y durante la migración no se cumplía.

    Un hex suelto en la hoja de una pantalla es un color que nadie puede cambiar
    de golpe: para mover el violeta de la marca habría que abrir las 21 hojas.
    """
    sueltos = []
    for nombre, cuerpo in _hojas_sin_root():
        for m in re.finditer(RE_COLOR, cuerpo):
            linea = cuerpo[: m.start()].count("\n") + 1
            sueltos.append(nombre + ":" + str(linea) + " " + m.group(0))
    assert not sueltos, (
        "Colores fuera de `:root`. Todo color va como token; si el valor no "
        "encaja en ningún escalón, se le da SU token en vez de escribirlo a "
        "mano:\n  " + "\n  ".join(sueltos)
    )


def test_el_z_index_va_por_la_escala():
    """Había siete números mágicos y ningún token: así se acaba inventando un 9999."""
    sueltos = []
    for nombre, cuerpo in _hojas_sin_root():
        for m in re.finditer(r"z-index:\s*([^;]+);", cuerpo):
            if "var(--adhoc-z-" not in m.group(1):
                sueltos.append(nombre + ": z-index: " + m.group(1).strip())
    assert not sueltos, (
        "z-index sin token. La escala es --adhoc-z-{cell,cell-corner,sticky,"
        "modal,toast,top}; si algo pide colarse entre dos escalones, el que "
        "sobra es uno de los dos:\n  " + "\n  ".join(sueltos)
    )


#: Los tres cortes de la app, y sus pares `min-width`. Los `.98` evitan que un
#: `max-width: 575.98` y un `min-width: 576` se solapen en el píxel fraccionario
#: de una pantalla con escalado, que es donde aparecen los saltos de un píxel.
BREAKPOINTS = {"575.98px", "767.98px", "991.98px", "576px", "768px", "992px"}


def test_los_cortes_responsive_son_los_de_la_escala():
    sueltos = []
    for nombre, cuerpo in _hojas_sin_root():
        for m in re.finditer(r"@media[^{]*?\((?:min|max)-width:\s*([^)]+)\)", cuerpo):
            valor = m.group(1).strip()
            if valor not in BREAKPOINTS:
                sueltos.append(nombre + ": " + valor)
    assert not sueltos, (
        "Cortes fuera de la escala (575.98 / 767.98 / 991.98). Había ocho "
        "valores distintos, uno por cada hoja portada del legacy:\n  "
        + "\n  ".join(sueltos)
    )


def test_las_utilidades_declaradas_se_usan():
    """Eran 64 y solo once tenían un uso.

    No es solo peso muerto: `.h4` valía 1.5rem mientras el elemento ``<h4>``
    vale 1rem, así que la clase y la etiqueta con el mismo nombre daban tamaños
    distintos — una trampa esperando a que alguien la pisara.
    """
    # Los limites se buscan en el texto CRUDO: los rotulos de capa viven dentro
    # de un comentario, asi que quitarlos antes se lleva tambien las marcas.
    base = (HOJAS / "adhoc.css").read_text(encoding="utf8")
    capa = _css_sin_comentarios(base[base.index("CAPA 5"): base.index("CAPA 6")])
    clases = sorted(set(re.findall(r"^\.([\w-]+)\s*\{", capa, re.M)))

    corpus = ""
    for patron in ("templates/**/*.html", "static/js/**/*.js", "**/*.py"):
        for ruta in RAIZ.glob(patron):
            corpus += ruta.read_text(encoding="utf8", errors="ignore")
    for ruta in HOJAS.rglob("*.css"):
        if ruta.name != "adhoc.css":
            corpus += ruta.read_text(encoding="utf8")

    muertas = []
    for clase in clases:
        if clase == "visually-hidden":       # solo para lectores de pantalla
            continue
        if re.search(RE_USO_CLASE % re.escape(clase), corpus):
            continue
        muertas.append(clase)
    assert not muertas, (
        "Utilidades declaradas que no usa nadie. Esta lista no crece por gusto: "
        "si una pantalla necesita algo más, va en la hoja de esa pantalla:\n  "
        + " ".join(muertas)
    )
