"""Aserciones compartidas de las bandejas paginadas (no es un módulo de tests).

`assert_buscador_preservado`: el buscador de una bandeja lleva
`hx-preserve="true"` (htmx re-inserta el MISMO nodo tras el swap: lo tecleado
mientras viaja la petición no se pierde y el `strip()` del servidor no le come
el espacio final). Además:

* id estable (hx-preserve empareja por id);
* el `value` del servidor sigue pre-llenando el input en una carga completa;
* vive DENTRO del contenedor de filtros que pestañas/pager/filas incluyen con
  `hx-include`, así que `q` sigue viajando;
* ese contenedor anuncia `data-tt-q-server` (el `q` con que se pintó), que lee
  `titulatec-utils.js::_syncPreservedSearch` para reponer el texto cuando una
  navegación cambia `q` sin pasar por el input.
"""
from __future__ import annotations

import re

import lxml.html


def assert_buscador_preservado(html, *, input_id, filters_id, q):
    doc = lxml.html.fromstring(html)
    (caja,) = doc.xpath('//*[@id="%s"]' % filters_id)
    inputs = caja.xpath('.//input[@id="%s"]' % input_id)
    assert len(inputs) == 1, "el buscador #%s no está dentro de #%s" % (input_id, filters_id)
    (inp,) = inputs
    assert len(doc.xpath('//*[@id="%s"]' % input_id)) == 1, "id del buscador no es único"
    assert inp.get("hx-preserve") == "true"
    assert inp.get("name") == "q"
    assert inp.get("value") == q, "la carga completa debe pre-llenar el buscador"
    assert inp.get("hx-include") == "#" + filters_id
    assert caja.get("data-tt-q-server") == q
    return doc


def assert_incluye_filtros(fragmento_tag, filters_id):
    assert re.search(r'hx-include="#%s"' % re.escape(filters_id), fragmento_tag), fragmento_tag
