"""Bandeja «Accesos» paginada (spec 2026-10-04 §3.3 y §5).

Sin el tope de 300: `_body_ctx` pagina con `paginate_query`, conserva el FIFO de
las colas de trabajo («Por dar acceso» por `reviewed_at`, «Por revisar» del modo
alterno por `created_at`) con desempate por `id`, busca con
`enrollment_request_search` (la misma de Solicitudes, Ruling R1) y cuenta cada
pestaña con la MISMA regla que su lista (una consulta de conteo condicional).

Las pruebas que van directo a `_body_ctx` le pasan `per_page=3` (Ruling R2); las
de ruta parchean `access_admin._body_ctx` con ese `per_page`.
"""
from __future__ import annotations

import functools
import re
from datetime import datetime, timedelta

import pytest

from tests.fastapi.titulatec.test_access_inbox import (  # noqa: F401
    CC_PERMS, URL, _cuenta, _en_espera, _fila, _make_req, _pestana_activa,
    correo_falso, make_cc,
)


def _ctx(db, **kw):
    from itcj2.apps.titulatec.pages.access_admin import _body_ctx

    kw.setdefault("status", "awaiting_access")
    kw.setdefault("cohort_id", None)
    return _body_ctx(db, **kw)


def _ids(ctx):
    return [r["id"] for r in ctx["rows"]]


@pytest.fixture()
def tres_por_pagina(monkeypatch):
    from itcj2.apps.titulatec.pages import access_admin

    monkeypatch.setattr(access_admin, "_body_ctx",
                        functools.partial(access_admin._body_ctx, per_page=3))


# ---------------------------------------------------------------------------
# Orden total entre páginas
# ---------------------------------------------------------------------------
def test_por_dar_acceso_fifo_entre_paginas(db_session, make_cohort):
    cohort = make_cohort(status="open")
    # id al revés de reviewed_at y dos con la misma hora: solo `id` desempata.
    reqs = [_en_espera(db_session, cohort, control=f"9990{i:04d}",
                       reviewed_at=datetime(2001, 3, 10 - min(i, 5), 9, 0))
            for i in range(7)]
    esperado = [r.id for r in sorted(reqs, key=lambda r: (r.reviewed_at, r.id))]

    vistos = []
    for p in (1, 2, 3):
        vistos += _ids(_ctx(db_session, cohort_id=cohort.id, page=p, per_page=3))

    assert vistos == esperado
    ctx = _ctx(db_session, cohort_id=cohort.id, page=3, per_page=3)
    assert (ctx["page"].total, ctx["page"].page, ctx["page"].pages) == (7, 3, 3)


def test_pending_review_alterno_fifo_entre_paginas(db_session, make_cohort, modo_alterno):
    cohort = make_cohort(status="open")
    base = datetime(2001, 1, 1, 9, 0)
    reqs = [_make_req(db_session, cohort, control=f"9991{i:04d}",
                      created_at=base + timedelta(days=7 - min(i, 6)))
            for i in range(7)]
    esperado = [r.id for r in sorted(reqs, key=lambda r: (r.created_at, r.id))]

    vistos = []
    for p in (1, 2, 3):
        vistos += _ids(_ctx(db_session, status="pending_review", cohort_id=cohort.id,
                            page=p, per_page=3))

    assert vistos == esperado


def test_ya_no_hay_tope_de_300(db_session, make_cohort):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    cohort = make_cohort(status="open")
    db_session.add_all([
        EnrollmentRequest(cohort_id=cohort.id, control_number=f"992{i:05d}",
                          first_name="EGRESADO", last_name="MASIVO", program_text="X",
                          phone="6561234567", contact_email="m@example.invalid",
                          has_efirma=False, kind="unknown", status="awaiting_access",
                          reviewed_at=datetime(2001, 1, 1, 9, 0), verify_send_count=0)
        for i in range(301)])
    db_session.flush()

    ctx = _ctx(db_session, cohort_id=cohort.id, page=7)

    assert ctx["page"].per_page == 50
    assert ctx["page"].total == 301
    assert len(ctx["rows"]) == 1
    assert ctx["tab_counts"]["awaiting_access"] == 301


# ---------------------------------------------------------------------------
# Contador por pestaña
# ---------------------------------------------------------------------------
def test_con_acceso_excluye_nip_sii_en_lista_y_contador(db_session, make_cohort, modo_sii):
    cohort = make_cohort(status="open")
    ahora = datetime.now()
    cc = _make_req(db_session, cohort, control="99930001", status="converted",
                   access_granted_at=ahora, nip_source="computer_center")
    antigua = _make_req(db_session, cohort, control="99930002", status="converted",
                        access_granted_at=ahora - timedelta(days=1), nip_source=None)
    _make_req(db_session, cohort, control="99930003", status="converted",
              access_granted_at=ahora, nip_source="sii")
    _make_req(db_session, cohort, control="99930004", status="converted",
              access_granted_at=ahora, nip_source="sii")
    _en_espera(db_session, cohort, control="99930005")
    # Conserva el sello pero volvió a una cola de trabajo: tampoco es «Con acceso».
    _en_espera(db_session, cohort, control="99930006", access_granted_at=ahora)

    ctx = _ctx(db_session, status="granted", cohort_id=cohort.id, per_page=3)

    assert _ids(ctx) == [cc.id, antigua.id]
    assert ctx["page"].total == 2
    assert ctx["tab_counts"] == {"awaiting_access": 2, "granted": 2, "returned": 0}


def test_contador_de_cada_pestana_coincide_con_su_lista(db_session, make_cohort, modo_alterno):
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99940001")
    _make_req(db_session, cohort, control="99940002", status="unverified")
    _en_espera(db_session, cohort, control="99940003")
    _make_req(db_session, cohort, control="99940004", status="approved")
    _make_req(db_session, cohort, control="99940005", status="converted")
    _make_req(db_session, cohort, control="99940006", status="rejected")
    _make_req(db_session, cohort, control="99940007", status="rejected")

    base = _ctx(db_session, status="pending_review", cohort_id=cohort.id)
    assert base["tab_counts"] == {"pending_review": 3, "approved": 1, "converted": 1,
                                  "rejected": 2, "all": 7}
    for tab, n in base["tab_counts"].items():
        assert _ctx(db_session, status=tab, cohort_id=cohort.id)["page"].total == n, tab


def test_contador_en_el_boton_de_la_pestana(client_as, db_session, make_cc, make_cohort):
    cohort = make_cohort(status="open")
    _en_espera(db_session, cohort, control="99950001")
    _en_espera(db_session, cohort, control="99950002")
    _make_req(db_session, cohort, control="99950003", returned_at=datetime.now())

    html = client_as(make_cc()).get(f"{URL}/body?cohort_id={cohort.id}").text

    boton = re.search(r'<button id="tt-acc-tab-awaiting_access".*?</button>', html, re.S).group(0)
    assert "(2)" in boton
    boton = re.search(r'<button id="tt-acc-tab-returned".*?</button>', html, re.S).group(0)
    assert "(1)" in boton


# ---------------------------------------------------------------------------
# Búsqueda
# ---------------------------------------------------------------------------
def test_busqueda_control_minuscula_y_comodines(db_session, make_cohort):
    cohort = make_cohort(status="open")
    con_letra = _en_espera(db_session, cohort, control="B20111234")
    _en_espera(db_session, cohort, control="99960001")

    ctx = _ctx(db_session, cohort_id=cohort.id, q="  b20111234  ")
    assert _ids(ctx) == [con_letra.id]
    assert ctx["q"] == "b20111234"
    assert ctx["tab_counts"]["awaiting_access"] == 1

    for comodin in ("%", "_", "\\"):
        ctx = _ctx(db_session, cohort_id=cohort.id, q=comodin)
        assert ctx["page"].total == 0, comodin
        assert ctx["tab_counts"]["awaiting_access"] == 0, comodin


def test_busqueda_por_nombre_correo_y_folio(
    db_session, make_cohort, make_student, make_process,
):
    cohort = make_cohort(status="open")
    req = _en_espera(db_session, cohort, control="99961001", first_name="ROSA",
                     last_name="PEREZ", middle_name="LUNA", email="rosa.luna@example.invalid")
    _en_espera(db_session, cohort, control="99961002")
    for q in ("rosa perez", "perez luna rosa", "ROSA.LUNA@"):
        assert _ids(_ctx(db_session, cohort_id=cohort.id, q=q)) == [req.id], q

    proc = make_process(make_student(control_number="99961003"), cohort=cohort,
                        folio="TT-ZQ-98766", phases=False, library_clearance=None)
    inscrita = _make_req(db_session, cohort, control="99961003", status="converted",
                         converted_process_id=proc.id, access_granted_at=datetime.now())
    assert _ids(_ctx(db_session, status="granted", cohort_id=cohort.id,
                     q="zq-9876")) == [inscrita.id]


def test_busqueda_sin_resultados_accesos(client_as, db_session, make_cc, make_cohort):
    cohort = make_cohort(status="open")
    _en_espera(db_session, cohort, control="99962001")

    html = client_as(make_cc()).get(
        f"{URL}/body", params={"cohort_id": cohort.id, "q": "<b>nadie"}).text

    assert 'Sin resultados para "&lt;b&gt;nadie"' in html
    assert "<b>nadie" not in html
    assert "tt-pager-range" not in html
    assert "Bandeja limpia" not in html


# ---------------------------------------------------------------------------
# Rutas: la página y los filtros viajan
# ---------------------------------------------------------------------------
def test_dar_acceso_ultima_fila_repinta_pagina_valida(
    client_as, db_session, make_cc, make_cohort, correo_falso, tres_por_pagina,
):
    cohort = make_cohort(status="open")
    reqs = [_en_espera(db_session, cohort, control=f"9997{i:04d}",
                       reviewed_at=datetime(2001, 1, 1 + i, 9, 0))
            for i in range(4)]
    ultima = reqs[-1]

    resp = client_as(make_cc()).post(
        f"{URL}/{ultima.id}/dar-acceso",
        data={"nip": "4826", "status": "awaiting_access", "cohort_id": str(cohort.id),
              "page": "2", "q": ""})

    assert resp.status_code == 200, resp.headers.get("X-Tt-Error")
    assert _pestana_activa(resp.text) == "awaiting_access"
    assert f'id="tt-acc-{ultima.id}"' not in resp.text
    for r in reqs[:3]:
        assert f'id="tt-acc-{r.id}"' in resp.text
    assert "1–3 de 3" in resp.text
    assert "Bandeja limpia" not in resp.text


def test_get_page_2_conserva_pestana_y_cohort(
    client_as, db_session, make_cc, make_cohort, tres_por_pagina,
):
    cohort = make_cohort(status="open")
    otra = make_cohort(status="open")
    reqs = [_make_req(db_session, cohort, control=f"9998{i:04d}", status="converted",
                      access_granted_at=datetime(2001, 1, 1 + i, 9, 0))
            for i in range(5)]
    _make_req(db_session, otra, control="99989999", status="converted",
              access_granted_at=datetime(2000, 1, 1, 9, 0))
    desc = sorted(reqs, key=lambda r: (r.access_granted_at, r.id), reverse=True)

    html = client_as(make_cc()).get(
        f"{URL}/body?status=granted&cohort_id={cohort.id}&page=2").text

    assert _pestana_activa(html) == "granted"
    assert [int(i) for i in re.findall(r'<tr id="tt-acc-(\d+)"', html)] == [r.id for r in desc[3:]]
    assert "4–5 de 5" in html
    filtros = re.search(r'<div[^>]*id="tt-access-filters".*?<div class="tt-search">',
                        html, re.S).group(0)
    assert re.search(r'name="status"\s+value="granted"', filtros)
    assert re.search(rf'name="cohort_id"\s+value="{cohort.id}"', filtros)
    assert re.search(r'name="page"\s+value="1"', filtros)
    prev = re.search(r'<button[^>]*id="tt-access-pager-prev"[^>]*>', html, re.S).group(0)
    assert 'hx-include="#tt-access-filters"' in prev
    assert '"page": 1' in prev


def test_las_formas_de_fila_llevan_page_y_q(
    client_as, db_session, make_cc, make_cohort, tres_por_pagina,
):
    cohort = make_cohort(status="open")
    reqs = [_en_espera(db_session, cohort, control=f"9999{i:04d}", first_name="LUCERO",
                       reviewed_at=datetime(2001, 1, 1 + i, 9, 0))
            for i in range(4)]

    html = client_as(make_cc()).get(
        f"{URL}/body", params={"cohort_id": cohort.id, "q": "lucero", "page": 2}).text

    formularios = re.findall(r"<form.*?</form>", _fila(html, reqs[3]), flags=re.S)
    assert formularios
    for form in formularios:
        assert re.search(r'name="page"\s+value="2"', form), form
        assert re.search(r'name="q"\s+value="lucero"', form), form
    tab = re.search(r'<button id="tt-acc-tab-granted"[^>]*>', html).group(0)
    assert "q=lucero" in tab
    assert "page=" not in tab


# ---------------------------------------------------------------------------
# Presupuesto de consultas
# ---------------------------------------------------------------------------
def test_consultas_fijas_con_3_y_con_40(client_as, db_session, make_cc, make_cohort):
    from sqlalchemy import event

    chica, grande = make_cohort(status="open"), make_cohort(status="open")
    for cohort, n, pre in ((chica, 3, "9970"), (grande, 40, "9971")):
        for i in range(n):
            control = f"{pre}{i:04d}"
            if i % 2:
                _cuenta(db_session, control)
            _en_espera(db_session, cohort, control=control)
            _make_req(db_session, cohort, control=f"1{control}", status="rejected",
                      returned_at=datetime.now())
    c = client_as(make_cc())
    engine = db_session.get_bind()

    def _medir(cohort_id):
        sentencias = []

        def _sql(conn, cursor, statement, *a):
            sentencias.append(statement)

        event.listen(engine, "before_cursor_execute", _sql)
        try:
            resp = c.get(f"{URL}/body?status=awaiting_access&cohort_id={cohort_id}")
        finally:
            event.remove(engine, "before_cursor_execute", _sql)
        assert resp.status_code == 200
        return resp, sentencias

    _medir(chica.id)
    _, con_3 = _medir(chica.id)
    resp_grande, con_40 = _medir(grande.id)

    assert len(re.findall(r'<tr id="tt-acc-', resp_grande.text)) == 40
    assert len(con_40) == len(con_3), (len(con_3), len(con_40))
