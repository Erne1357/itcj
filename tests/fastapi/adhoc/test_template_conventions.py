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

import hashlib
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
# ── 9. las dos listas de documentos ────────────────────────────────────────
#
# /adhoc/documentos y /adhoc/documentos/panel son dos pantallas que pintan la
# MISMA tabla con el mismo módulo (`document-list.js`). Todo lo que se escriba
# dos veces —una por pantalla— diverge: ya pasó con el volcado de los filtros
# de la URL, que acabó con dos semánticas distintas para el mismo bloque de
# `page_data`. Estas tres reglas son estáticas a propósito: un E2E solo ve la
# pantalla que visita y solo si tiene datos, y lo que se vigila aquí es que las
# dos pantallas sigan compartiendo el mismo código.

JS_DOCS = RAIZ / "static" / "js" / "documents"


def _js(nombre: str) -> str:
    return (JS_DOCS / nombre).read_text(encoding="utf8")


def test_las_dos_tablas_de_documentos_acotan_su_columna_de_texto_libre():
    """El ancho de una tabla ``auto`` lo fija la columna que más pide.

    ``.adhoc-table-xl`` declara ``min-width: 1400px``, pero eso es un mínimo: la
    columna del título crece con el documento más largo del SGC —los hay de 120
    caracteres— y empuja las últimas columnas fuera de pantalla a 1280px, que es
    la resolución habitual de los equipos del ITCJ. El techo son dos cosas
    juntas, y ninguna funciona sola: ``clampCell`` (que mete el texto en un hijo
    bloque, porque un ``<td>`` no admite ``-webkit-line-clamp``) y un
    ``max-width`` sobre la celda en la hoja de la pantalla.
    """
    faltan = []
    for js, css, raiz_css in (
        ("documents.js", "documents.css", ".adhoc-documents"),
        ("documents-panel.js", "documents-panel.css", ".adhoc-doc-panel"),
    ):
        if "clampCell(tr, 'title'" not in _js(js):
            faltan.append(f"{js}: la celda 'title' no usa H.clampCell")
        hoja = (HOJAS / "documents" / css).read_text(encoding="utf8")
        if not re.search(
            re.escape(raiz_css) + r'[^{]*td\[data-adhoc-cell="title"\]\s*\{[^}]*max-width',
            hoja,
        ):
            faltan.append(f"{css}: falta el max-width de td[data-adhoc-cell=\"title\"]")
    assert not faltan, "Columna de título sin techo: " + " · ".join(faltan)


def test_el_volcado_de_los_filtros_de_la_url_vive_en_un_solo_sitio():
    """``applyInitialFilters`` es del contrato de la barra, no de la pantalla.

    Estuvo implementado dos veces, y las dos copias ya habían divergido: la de
    la consulta descartaba la cadena vacía y validaba la clave con un regex, la
    del panel no hacía ni lo uno ni lo otro. Un filtro nuevo se habría
    comportado distinto en cada pantalla sin que nada avisara.
    """
    dueños = [f.name for f in sorted(JS_DOCS.glob("*.js"))
              if "applyInitialFilters = function" in f.read_text(encoding="utf8")]
    assert dueños == ["document-list.js"], (
        "El volcado de `initial_filters` tiene que vivir SOLO en "
        f"document-list.js, junto al resto del contrato de la barra. Lo declaran: {dueños}"
    )
    for js in ("documents.js", "documents-panel.js"):
        assert "initialFilters:" in _js(js), (
            f"{js} no le pasa `initialFilters` a List.create, así que la pantalla "
            "ignora los filtros que vengan en la URL (el enlace del contador de "
            "vencidos del dashboard)."
        )


def test_el_modal_de_versiones_separa_el_vacio_de_la_version_unica():
    """Cero filas y una fila son casos distintos, no ``length <= 1``.

    Con ``items.length <= 1`` el modal enseñaba a la vez la fila "No se
    encontraron versiones de este documento" y la nota "Esta es la única versión
    registrada": dos frases que se contradicen en la misma pantalla.
    """
    # Solo el código: los comentarios citan la condición vieja para explicar
    # por qué se fue, y citarla no es volver a escribirla.
    fuente = "".join(
        linea for linea in _js("document-versions.js").splitlines(keepends=True)
        if not linea.lstrip().startswith(("//", "*", "/*"))
    )
    assert "items.length <= 1" not in fuente, (
        "`items.length <= 1` mete el caso vacío en la rama de 'única versión'. "
        "Son tres: 0 (habla la fila de vacío), 1 y más de 1."
    )
    for rama in ("items.length === 0", "items.length === 1"):
        assert rama in fuente, f"Falta la rama `{rama}` en el modal del historial."


def test_los_selects_del_modal_de_documentos_conservan_el_valor_guardado():
    """Gotcha 22: un ``<select>`` lleno de un catálogo FILTRADO borra lo que falte.

    Es el mismo defecto que se arregló en ``work-items.js`` con
    ``fillSelect``, y volvió a aparecer en el modal de documentos en cuanto se
    le conectó la edición: ``_document_catalogs`` solo manda las áreas con
    ``is_active``, la relación del documento no filtra nada, y en este PATCH un
    ``''`` **limpia la columna**. Con el valor guardado fuera de las opciones, el
    desplegable abría en el placeholder y guardar un cambio de título borraba el
    área del documento sin que nadie la hubiera tocado.

    Dos condiciones, y ninguna sirve sola: el prefill tiene que llevar el objeto
    anidado (el id pelado no da con qué rotular la opción) y
    ``makeCatalogSelect`` tiene que conservar el valor que no case con ninguna
    entrada del catálogo.
    """
    fuente = _js("documents-panel.js")

    reincidencia = [c for c in ("category", "area", "process", "classification")
                    if f"doc.{c} ? doc.{c}.id" in fuente]
    assert not reincidencia, (
        "El prefill del modal vuelve a mandar el id pelado en "
        f"{', '.join(reincidencia)}: sin el objeto anidado de `document_out` no "
        "hay nombre con el que conservar un valor que ya no está en el catálogo."
    )
    for campo in ("category", "area", "process", "classification"):
        assert f"{campo}: doc.{campo}" in fuente, (
            f"`openEdit`/`openNewVersion` no le pasan `doc.{campo}` al prefill."
        )

    cuerpo = fuente[fuente.index("function makeCatalogSelect"):]
    cuerpo = cuerpo[:cuerpo.index("\n    }\n")]
    assert "!matched" in cuerpo and "kept.selected = true" in cuerpo, (
        "`makeCatalogSelect` ya no conserva el valor guardado cuando no está "
        "entre las opciones: el select cae al placeholder y el PATCH manda '', "
        "que en este endpoint significa borrar la columna."
    )


# ── 11. ningún <form> boosted sin `action` ─────────────────────────────────
#
# `#adhoc-root` lleva `hx-boost="true"` y el atributo lo HEREDA todo
# descendiente, `{% block modals %}` incluido. Al procesar un <form> boosted,
# htmx 2.0.3 hace (`boostElement`):
#
#     path = getRawAttribute(elt, 'action')
#     if (verb === 'get' && path.includes('?')) ...
#
# Sin `action`, `path` es null y eso es un TypeError. No es cosmético:
#
#   · en la carga completa la excepción aborta el `ready()` de htmx ANTES de la
#     línea que instala `window.onpopstate`, así que en esa pantalla el botón
#     ATRÁS deja de hacer nada — y envenena el resto de la sesión, porque el
#     runtime a medio arrancar ya no actualiza `currentPathForHistory`;
#   · si se llega navegando, la excepción sube dentro de `restoreHistory()` y
#     `htmx:historyRestore` no llega a emitirse: la lista vuelve pintada del
#     caché, con sus marcas `data-adhoc-*-bound` rancias, y MUERTA.
#
# Tres plantillas lo tenían (`work/_work_item_page.html`, `work/tasks.html`,
# `documents/documents_panel.html`), que son los modales de alta y edición de
# incidencias, programas, tareas y documentos: las listas más usadas de la app.
#
# La regla vive aquí y no solo en el E2E porque el E2E únicamente ve las
# pantallas que visita y solo si tienen datos; esto recorre las 34 plantillas.

RE_FORM = re.compile(r"<form\b(?P<attrs>[^>]*)>", re.I)

#: Comentario de Jinja o de HTML. Se vacían antes de buscar: los comentarios de
#: estas mismas plantillas —y el que acompaña a cada `hx-boost="false"`— citan
#: `<form>` para explicar por qué llevan lo que llevan, y un lint que se
#: denuncia a sí mismo no lo arregla nadie. Se sustituyen por sus saltos de
#: línea para que el número del mensaje siga apuntando a la línea de verdad.
RE_COMENTARIO = re.compile(r"\{#.*?#\}|<!--.*?-->", re.S)


def _sin_comentarios(html: str) -> str:
    return RE_COMENTARIO.sub(lambda m: "\n" * m.group(0).count("\n"), html)


def test_ningun_form_se_queda_sin_action_dentro_del_boost():
    """Un <form> sin `action` dentro de #adhoc-root revienta el ATRÁS de la app."""
    culpables = []
    for nombre, html_crudo in _plantillas():
        html = _sin_comentarios(html_crudo)
        for m in RE_FORM.finditer(html):
            attrs = m.group("attrs")
            if re.search(r"\baction\s*=", attrs, re.I):
                continue
            if re.search(r'\bhx-boost\s*=\s*"false"', attrs, re.I):
                continue
            if re.search(r'\bmethod\s*=\s*"dialog"', attrs, re.I):
                continue
            linea = html[: m.start()].count("\n") + 1
            culpables.append(f"{nombre}:{linea}  <form{attrs.rstrip()}>")

    assert not culpables, (
        "<form> sin `action` heredando `hx-boost` de #adhoc-root:\n  "
        + "\n  ".join(culpables)
        + "\n\nhtmx 2.0.3 hace `getRawAttribute(form,'action').includes('?')` al "
        "boostearlo, y sin `action` eso es un TypeError que se lleva por delante "
        "el botón ATRÁS de toda la app.\n"
        "Si el formulario se manda con `fetch` desde su módulo —que es el caso "
        'de todos los de Calidad— la respuesta es `hx-boost="false"` en el '
        "propio <form>, no inventarle un `action` al que no se envía nunca."
    )


# ── 12. los <script> de la base viven en el <head> ─────────────────────────
#
# HTMX guarda y repone el historial sobre el "elemento de historial", que es el
# que lleve `hx-history-elt` o, si nadie lo lleva —el caso de esta app—,
# `document.body`. Repone con `swapInnerHTML`, que vuelve a CREAR cada <script>
# del fragmento y por tanto a EJECUTARLO (`htmx.config.allowScriptTags`).
#
# Con los <script> de la base dentro del <body> eso significaba una copia nueva
# de HTMX, de Bootstrap, de AdhocUtils y de table-filter.js por CADA ATRÁS:
# medido en Chromium con tres idas y vueltas, los listeners de `document`
# pasaban de 43 a 118, y dos runtimes de HTMX peleándose por
# `currentPathForHistory` dejaban el caché de historial corrupto (volvías a
# /adhoc/documentos y veías el tablero).
#
# En el <head> quedan fuera del elemento de historial. Y bloqueantes (sin
# `defer`), porque `{% block extra_js %}` vive dentro de #adhoc-root y sus
# <script> corren durante el parseo del <body>: con `defer` estos correrían
# DESPUÉS y cada módulo de página arrancaría sin `window.AdhocUtils`.

_BASE = PLANTILLAS / "base_adhoc.html"

#: Los que TIENEN que cargarse desde el <head>, por un trozo único de su `src`.
_SCRIPTS_DE_LA_BASE = (
    "htmx.org@2.0.3",
    "idiomorph",
    "head-support",
    "bootstrap.bundle.min.js",
    "js/adhoc-utils.js",
    "js/shared/table-filter.js",
    "js/apps/mobile-app-shell.js",
)

#: Los `src` de los <script> de un trozo de HTML. Se miran los `src` y no el
#: texto crudo para no confundir un <script> con una mención suya dentro de un
#: comentario `{# ... #}` — que las hay, y muchas.
RE_SCRIPT_SRC = re.compile(r'<script\b[^>]*\bsrc="([^"]+)"', re.I)


def _head_y_body(html: str) -> tuple[str, str]:
    """Parte la plantilla por la etiqueta <body> DE VERDAD.

    No vale `html.index("<body")`: el comentario de cabecera de base_adhoc.html
    menciona `<body>` varias veces al explicar por qué las clases de página van
    en #adhoc-root y no ahí, y el corte caería dentro del comentario.
    """
    m = re.search(r"(?m)^<body\b", html)
    assert m, "base_adhoc.html no tiene una etiqueta <body> a principio de línea"
    return html[: m.start()], html[m.start():]


@pytest.mark.parametrize("marca", _SCRIPTS_DE_LA_BASE)
def test_los_scripts_de_la_base_van_en_el_head(marca):
    """En el <body> se re-ejecutan en cada ATRÁS; en el <head> no."""
    head, body = _head_y_body(_BASE.read_text(encoding="utf8"))
    en_head = [s for s in RE_SCRIPT_SRC.findall(head) if marca in s]
    en_body = [s for s in RE_SCRIPT_SRC.findall(body) if marca in s]

    assert en_head, (
        f"El <script> de '{marca}' ya no se carga desde el <head> de "
        "base_adhoc.html.\nDentro del <body> entra en el elemento de historial "
        "de HTMX, y cada ATRÁS crea otra copia del archivo: otro juego de "
        "listeners globales, otro runtime de HTMX y el caché de historial "
        "corrupto a partir del segundo ATRÁS."
    )
    assert not en_body, (
        f"'{marca}' se carga TAMBIÉN desde el <body> ({en_body}): dos copias "
        "del mismo módulo es peor que una en el sitio malo."
    )


def test_solo_el_shell_movil_lleva_defer():
    """`defer` invierte el orden con los módulos de página.

    `mobile-app-shell.js` es del CORE y en su primera línea hace
    `document.body.classList.add(...)`; en un <head> bloqueante `document.body`
    todavía es null, así que es el único que necesita `defer` — y puede
    permitírselo porque no exporta nada que los módulos de página usen.

    Los otros seis NO pueden llevarlo: los <script> de `{% block extra_js %}`
    corren durante el parseo del <body>, así que con `defer` estos correrían
    después y cada módulo de página arrancaría con `window.AdhocUtils` sin
    definir — la pantalla se pintaría y quedaría muerta.
    """
    head, _ = _head_y_body(_BASE.read_text(encoding="utf8"))
    con_defer = re.findall(
        r'<script\b(?=[^>]*\bdefer\b)[^>]*\bsrc="([^"]+)"', head, re.I
    )
    sobran = [s for s in con_defer if "mobile-app-shell.js" not in s]
    assert not sobran, (
        f"Estos <script> del <head> llevan `defer` y no deben: {sobran}. "
        "Correrían después de los módulos de página, que arrancarían sin "
        "window.AdhocUtils."
    )
    assert con_defer, (
        "mobile-app-shell.js perdió el `defer`: en un <head> bloqueante su "
        "`document.body.classList.add(...)` de la primera línea revienta "
        "porque `document.body` todavía no existe."
    )


# ── 10. el bump de estáticos ───────────────────────────────────────────────
#
# En este repo NO hay `static-manifest.json`, así que `load_static_manifest()`
# devuelve `{}` y el `sv()` de todos los estáticos de adhoc cae siempre al
# fallback: la constante `STATIC_VERSION` de `itcj2/config.py`. Y nginx sirve
# /static/adhoc/ con `expires 1y` + `Cache-Control: immutable`
# (docker/nginx/nginx.prod.conf), que significa que el navegador ni siquiera
# revalida. Un cambio de CSS/JS sin bump se despliega para nadie: quien ya tenía
# la pantalla abierta sigue ejecutando la versión anterior hasta un ctrl+F5 que
# no sabe que hace falta. Pasó con la edición de documentos (A14): el JS del
# panel creció 450 líneas y la URL del `<script>` quedó idéntica.

_ESTATICOS = RAIZ / "static"

#: ``(STATIC_VERSION, huella)`` del último bump. **Se actualizan juntos**: al
#: tocar un CSS/JS de adhoc se sube la constante en ``itcj2/config.py`` y se
#: pega aquí la huella nueva que imprime el fallo. Son dos líneas, y son la
#: diferencia entre desplegar el cambio y creer que se desplegó.
_ULTIMO_BUMP = ("1.0.1111534", "647efd1a8eb255e3")


def _huella_estaticos() -> str:
    """SHA-256 de los CSS/JS de adhoc (ruta + contenido), normalizando CRLF.

    El salto de línea se normaliza porque ``core.autocrlf`` está activo en las
    máquinas Windows del ITCJ: un clon nuevo trae CRLF y la huella no puede
    depender de eso.
    """
    h = hashlib.sha256()
    for ruta in sorted(q for q in _ESTATICOS.rglob("*")
                       if q.is_file() and q.suffix in (".css", ".js")):
        h.update(ruta.relative_to(_ESTATICOS).as_posix().encode("utf8"))
        h.update(ruta.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def test_los_estaticos_de_adhoc_no_cambian_sin_bump_de_static_version():
    """Gotcha #4 del CLAUDE.md raíz, con un tripwire en vez de buena memoria."""
    from itcj2.config import get_settings

    if (Path(__file__).resolve().parents[3] / "static-manifest.json").exists():
        pytest.skip("Hay manifest: `sv()` versiona por archivo y el fallback no manda.")

    version = get_settings().STATIC_VERSION
    huella = _huella_estaticos()
    esperada_version, esperada_huella = _ULTIMO_BUMP

    if huella == esperada_huella:
        assert version == esperada_version, (
            "STATIC_VERSION cambió sin que cambiara ningún estático de adhoc. "
            f"Actualiza `_ULTIMO_BUMP` a ('{version}', '{huella}')."
        )
        return

    assert version != esperada_version, (
        "Cambiaron los estáticos de adhoc y STATIC_VERSION sigue en "
        f"'{version}'. Sin bump, nginx sirve el archivo viejo con `immutable` "
        "durante un año y el cambio no le llega a quien ya abrió la pantalla.\n"
        f"  1) sube STATIC_VERSION en itcj2/config.py\n"
        f"  2) pon aquí `_ULTIMO_BUMP = (\"<version nueva>\", \"{huella}\")`"
    )
    pytest.fail(
        "Bump correcto, falta cerrar el par: "
        f"`_ULTIMO_BUMP = (\"{version}\", \"{huella}\")`"
    )
