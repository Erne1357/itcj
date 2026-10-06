"""Macro `pager` compartido de las bandejas admin de TitulaTec."""
from itcj2.apps.titulatec.pages.nav import titulatec_templates
from itcj2.apps.titulatec.utils.paging import Page


def _render(page, **kw):
    args = {"url": "/titulatec/admin/x/body", "target": "#tt-x-body"}
    args.update(kw)
    tpl = titulatec_templates.env.from_string(
        '{% from "titulatec/_macros.html" import pager %}'
        '{{ pager(page, url, target, include=include, swap=swap, '
        'push_url=push_url, prefix=prefix) }}'
    )
    ctx = {"include": None, "swap": "outerHTML", "push_url": False, "prefix": "tt"}
    ctx.update(args)
    ctx["page"] = page
    return tpl.render(**ctx)


def _page(n, page=1, per=50):
    return Page(items=[], total=n, page=page, per_page=per)


def test_pager_vacio_no_pinta_nada():
    assert _render(_page(0)).strip() == ""


def test_pager_una_pagina_solo_rango():
    html = _render(_page(7))
    assert 'class="tt-pager-range"' in html
    assert "1–7 de 7" in html
    assert "<nav" not in html and "<button" not in html


def test_pager_primera_pagina_prev_deshabilitado():
    html = _render(_page(120, page=1))
    prev = html.split('id="tt-pager-prev"')[1].split(">")[0]
    nxt = html.split('id="tt-pager-next"')[1].split(">")[0]
    assert "disabled" in prev and 'aria-disabled="true"' in prev
    assert "disabled" not in nxt
    assert "1–50 de 120" in html


def test_pager_ultima_pagina_next_deshabilitado():
    html = _render(_page(120, page=3))
    nxt = html.split('id="tt-pager-next"')[1].split(">")[0]
    prev = html.split('id="tt-pager-prev"')[1].split(">")[0]
    assert "disabled" in nxt and 'aria-disabled="true"' in nxt
    assert "disabled" not in prev
    assert "101–120 de 120" in html


def test_pager_hx_vals_e_include():
    html = _render(_page(150, page=2), include="#tt-filters", push_url=True)
    prev, nxt = [b.split(">")[0] for b in html.split("<button")[1:3]]
    assert "&#34;page&#34;: 1" in prev or '"page": 1' in prev
    assert "&#34;page&#34;: 3" in nxt or '"page": 3' in nxt
    for b in (prev, nxt):
        assert 'hx-include="#tt-filters"' in b
        assert 'hx-get="/titulatec/admin/x/body"' in b
        assert 'hx-target="#tt-x-body"' in b
        assert 'hx-swap="outerHTML"' in b
        assert 'hx-push-url="true"' in b
        assert 'type="button"' in b
        assert "btn btn-sm tt-btn-ghost" in b
    assert "bi-chevron-left" in html and "bi-chevron-right" in html
    assert "Anteriores" in html and "Siguientes" in html
    assert "d-none d-sm-inline" in html


def test_pager_sin_include_ni_push():
    html = _render(_page(150, page=2))
    assert "hx-include" not in html and "hx-push-url" not in html


def test_pager_ids_estables_con_prefix():
    html = _render(_page(150, page=2), prefix="tt-rel")
    assert 'id="tt-rel-pager"' in html
    assert 'id="tt-rel-pager-prev"' in html
    assert 'id="tt-rel-pager-next"' in html
    assert 'class="tt-pager"' in html


def test_pager_sin_style_inline():
    assert "style=" not in _render(_page(150, page=2))
    assert "style=" not in _render(_page(5))
