"""`utils/paging.py`: nucleo de paginacion compartido de las bandejas admin."""
import pytest

from itcj2.apps.titulatec.utils.paging import (
    PAGE_SIZE,
    Page,
    clamp_page,
    like_pattern,
    normalize_q,
    paginate_list,
    paginate_query,
    parse_page,
)


def test_page_size_es_50():
    assert PAGE_SIZE == 50


@pytest.mark.parametrize("raw", [None, "", "abc", "0", "-3", "2.5"])
def test_parse_page_invalido_es_1(raw):
    assert parse_page(raw) == 1


def test_parse_page_valido():
    assert parse_page("3") == 3


def test_page_start_end_vacio():
    p = Page(items=[], total=0, page=1, per_page=50)
    assert (p.start, p.end, p.pages) == (0, 0, 1)
    assert not p.has_prev and not p.has_next


def test_page_ultima_parcial():
    p = Page(items=[], total=487, page=10, per_page=50)
    assert (p.start, p.end, p.pages) == (451, 487, 10)
    assert p.has_prev and not p.has_next


def test_clamp_page():
    assert clamp_page(99, 120, 50) == 3
    assert clamp_page(0, 120, 50) == 1
    assert clamp_page(5, 0, 50) == 1


def test_paginate_list_fuera_de_rango_cae_a_la_ultima():
    p = paginate_list(list(range(120)), 99, per_page=50)
    assert p.page == 3 and len(p.items) == 20 and p.total == 120


def test_paginate_list_continuidad():
    seq = list(range(120))
    out = []
    for n in range(1, 4):
        out += paginate_list(seq, n, per_page=50).items
    assert out == seq


def test_like_pattern_escapa():
    assert like_pattern("50%_a\\b") == "%50\\%\\_a\\\\b%"


def test_normalize_q():
    assert normalize_q("  hola  ") == "hola"
    assert len(normalize_q("x" * 150)) == 100
    assert normalize_q("") is None
    assert normalize_q("   ") is None
    assert normalize_q(None) is None


def test_paginate_query_con_bd(db_session, make_cohort, make_student, make_process):
    from itcj2.apps.titulatec.models import TitulationProcess

    cohort = make_cohort()
    for _ in range(7):
        make_process(make_student(), cohort=cohort)
    q = (db_session.query(TitulationProcess)
         .filter(TitulationProcess.cohort_id == cohort.id)
         .order_by(TitulationProcess.created_at, TitulationProcess.id))
    todo = q.all()
    assert len(todo) == 7
    out = []
    for n in (1, 2, 3):
        pg = paginate_query(q, n, per_page=3)
        assert pg.total == 7 and pg.pages == 3
        out += pg.items
    assert [r.id for r in out] == [r.id for r in todo]
    assert paginate_query(q, 9, per_page=3).page == 3
