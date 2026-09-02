"""BLOQUEADOR: cada click del menu admin dejaba `#tt-admin-content` VACIO.

`admin/base_admin.html:38-39` declaraba a la vez::

    hx-target="#tt-admin-content" hx-select="#tt-admin-content" hx-swap="morph:innerHTML"

y el contenedor vivo es `<div id="tt-admin-content">` (`:54`). `hx-select` conserva
**el elemento coincidente**, no sus hijos, asi que el nodo recortado de la respuesta
trae EL MISMO id que el destino. Con un swap `innerHTML` htmx lo mete DENTRO de si
mismo: Idiomorph 0.7.3 lanza `HierarchyRequestError: The new child element contains
the parent`, htmx atrapa la excepcion de la extension y cae al `swapInnerHTML` de
respaldo sobre un fragmento que la extension ya consumio -> `innerHTML = ''`.
Resultado en navegador: menu que responde 200 y pantalla en blanco.

La app YA tiene el idiom correcto en sus otros tres `hx-select`, todos con la misma
forma **select == target + outerHTML** (`admin/cohort_detail.html:25`,
`partials/cohort_students.html:8`, `partials/cohort_days_calendar.html:6,9,23`):
con `outerHTML` el nodo recortado REEMPLAZA al destino en vez de anidarse, que es
justo lo que rompe el ciclo. El arreglo alinea el sidebar con ese idiom
(`morph:outerHTML`, conservando el morph que da la navegacion sin parpadeo).

Que prueba cada test
--------------------
* `test_la_navegacion_admin_no_anida_el_contenedor_en_si_mismo` simula el swap de
  htmx sobre el HTML REAL de la app (pagina viva + respuesta de la ruta destino) y
  exige que el destino siga siendo unico y con contenido. Es el test que ve el
  defecto: hoy termina con dos `#tt-admin-content`, uno dentro del otro.
* `test_ningun_template_selecciona_su_propio_destino_con_innerHTML` barre las
  plantillas y fija el invariante para las vistas futuras.

La verificacion de verdad (Chromium con htmx 2.0.3 + Idiomorph 0.7.3 reales) va
aparte: un pytest no ejecuta la extension, solo puede reproducir la mecanica del
swap que la hace estallar.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

import lxml.html
import pytest

import itcj2.apps.titulatec as _tt_pkg

TEMPLATES = Path(_tt_pkg.__file__).resolve().parent / "templates" / "titulatec"

# Familias de swap: lo unico que importa aqui es donde aterriza el nodo recortado.
_INNER = ("innerHTML",)
_OUTER = ("outerHTML",)


def _swap_family(swap):
    """'morph:innerHTML' -> 'innerHTML'. Quita el prefijo de extension y los modificadores."""
    base = (swap or "innerHTML").split(" ")[0]   # "outerHTML swap:200ms" -> "outerHTML"
    return base.split(":")[-1]                   # "morph:innerHTML"      -> "innerHTML"


def _xpath_for(selector):
    """Los `hx-select`/`hx-target` de esta app son siempre selectores de id."""
    assert selector.startswith("#"), "selector no soportado por este test: %r" % (selector,)
    return '//*[@id="%s"]' % selector[1:]


def _simulate_swap(live_html, response_html, target, select, swap):
    """Reproduce lo que hace htmx: recorta `hx-select` de la respuesta y lo pone en `hx-target`.

    Devuelve el arbol vivo ya modificado. No emula a Idiomorph (un pytest no puede):
    emula el MOVIMIENTO de nodos, que es lo que deja el id duplicado y hace estallar
    a la extension.
    """
    live = lxml.html.fromstring(live_html)
    resp = lxml.html.fromstring(response_html)

    destino = live.xpath(_xpath_for(target))
    assert len(destino) == 1, "%s no es unico en la pagina viva: %d" % (target, len(destino))
    destino = destino[0]

    fragmento = [copy.deepcopy(n) for n in resp.xpath(_xpath_for(select))]
    assert fragmento, "la respuesta no trae %s: hx-select recortaria la nada" % (select,)

    familia = _swap_family(swap)
    if familia in _INNER:
        for hijo in list(destino):
            destino.remove(hijo)
        destino.text = None
        for nodo in fragmento:
            destino.append(nodo)
    elif familia in _OUTER:
        padre = destino.getparent()
        i = padre.index(destino)
        padre.remove(destino)
        for off, nodo in enumerate(fragmento):
            padre.insert(i + off, nodo)
    else:
        pytest.fail("familia de swap no contemplada: %r" % (swap,))
    return live


def test_la_navegacion_admin_no_anida_el_contenedor_en_si_mismo(client_as, make_head):
    """Un click de menu debe dejar UN `#tt-admin-content`, con el contenido del destino.

    Se recorren los items reales del sidebar (los que `admin_nav_items` concede a la
    jefa), se pide cada URL con `HX-Request` como haria htmx y se aplica el swap que
    declara el propio template. Con controles positivos para que el test no pueda
    pasar por no haber revisado nada: >=5 items, destino presente en la pagina viva,
    respuesta 200 y contenido no vacio tras el swap.
    """
    head = make_head()
    cli = client_as(head)

    viva = cli.get("/titulatec/admin/documents")
    assert viva.status_code == 200, viva.text[:500]

    doc = lxml.html.fromstring(viva.text)
    items = doc.xpath('//aside[@id="ttSide"]//a[@hx-get]')
    urls = [a.get("hx-get") for a in items if a.get("hx-get") not in (None, "#")]
    assert len(urls) >= 5, "el menu de la jefa deberia traer >=5 items, trae %d" % len(urls)

    problemas = []
    for a in items:
        url = a.get("hx-get")
        if url in (None, "#"):
            continue
        target, select, swap = a.get("hx-target"), a.get("hx-select"), a.get("hx-swap")
        assert target and swap, "item %s sin contrato de swap completo" % url
        if not select:
            continue

        resp = cli.get(url, headers={"HX-Request": "true",
                                     "HX-Target": target.lstrip("#")})
        assert resp.status_code == 200, "%s -> %s" % (url, resp.status_code)

        arbol = _simulate_swap(viva.text, resp.text, target, select, swap)

        iguales = arbol.xpath(_xpath_for(target))
        if len(iguales) != 1:
            problemas.append(
                "%s: tras el swap hay %d nodos %s (hx-select=%s hx-swap=%s) -> id "
                "duplicado; Idiomorph revienta y la pantalla queda en blanco"
                % (url, len(iguales), target, select, swap)
            )
            continue
        assert len(iguales[0]) > 0, "%s: %s quedo sin hijos tras el swap" % (url, target)

    assert not problemas, "navegacion admin rota:\n" + "\n".join(problemas)


def test_ningun_template_selecciona_su_propio_destino_con_innerHTML():
    """Invariante para toda vista futura: `hx-select == hx-target` obliga a `outerHTML`.

    Con `innerHTML` el nodo recortado entra como hijo de si mismo: id duplicado y,
    bajo la extension `morph`, `HierarchyRequestError` + swap vacio. El censo
    (`revisados`) es el control positivo: si el regex deja de encontrar etiquetas,
    el test se cae en vez de pasar en vacio.
    """
    # Varios templates parten el tag en varias lineas, asi que se buscan etiquetas
    # completas y no lineas sueltas.
    tag_re = re.compile(r"<[a-zA-Z][^>]*hx-select=[^>]*>", re.S)

    def attr(tag, name):
        m = re.search(name + r'="([^"]*)"', tag)
        return m.group(1) if m else None

    revisados, ofensores = 0, []
    for path in sorted(TEMPLATES.rglob("*.html")):
        for tag in tag_re.findall(path.read_text(encoding="utf-8")):
            select, target = attr(tag, "hx-select"), attr(tag, "hx-target")
            if not select or not target:
                continue
            revisados += 1
            if select == target and _swap_family(attr(tag, "hx-swap")) in _INNER:
                ofensores.append(
                    "%s: hx-select=%s == hx-target=%s con hx-swap=%r"
                    % (path.relative_to(TEMPLATES), select, target, attr(tag, "hx-swap"))
                )

    # Censo real hoy: 14 etiquetas (base_admin 1, cohort_detail 1, cohort_students 1,
    # cohort_days_calendar 3 y processes 8 -- los filtros HTMX de la bandeja de
    # Procesos). Son 8 y no 12 porque el bucle de chips de status emite 5 anclas
    # desde UNA sola etiqueta del fuente, y este censo lee el fuente. El umbral
    # deja 2 de margen, como antes, para que no se caiga por una edicion menor.
    #
    # PUNTO CIEGO CONOCIDO: Citas de cotejo emite sus `hx-select` desde un macro
    # (`partials/appointments/_appt_macros.html`), o sea sin `<tag` delante, y
    # este regex no los ve. El mismo invariante se fija ahi con una asercion
    # directa sobre el macro, en `test_appointments_scope_day.py`. Cualquier
    # vista nueva que centralice sus atributos en un macro necesita lo mismo.
    assert revisados >= 12, "el censo de hx-select encogio a %d: revisa el regex" % revisados
    assert not ofensores, (
        "hx-select == hx-target con swap innerHTML (el nodo se anida en si mismo):\n"
        + "\n".join(ofensores)
    )
