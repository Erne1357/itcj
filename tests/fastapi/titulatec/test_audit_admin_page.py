"""Pestaña «Bitácora» (2026-10-07): `pages/audit_admin.py`, solo lectura.

Permiso `titulatec.audit.page.list` (solo el rol `admin`). Las filas se siembran
directo con `TitulatecAuditLog(...)` dentro de la transacción de la prueba (se
revierte), y toda prueba acota su universo con un `token` único en el motivo
(`q`): la BD de dev es compartida.

Se fija: autorización, filtros (vacíos no dan 422), paginación, «Incluir
cambios de datos», detalle antes/después + hermanas por `request_id`, escape de
HTML y la liga «Ver bitácora» del expediente.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta

import pytest

URL = "/titulatec/admin/bitacora"
PERM = "titulatec.audit.page.list"
DOCS_PAGE = "/titulatec/admin/documents"


def _token() -> str:
    return "zqx" + uuid.uuid4().hex[:10]


def _ahora() -> datetime:
    from itcj2.core.utils.timezone import db_now
    return db_now()


def _fila(db, *, token, source="action", action="cohort.created", module="cohorts",
          actor_id=None, actor_kind="user", actor_label=None, entity_type=None,
          entity_id=None, process_id=None, subject_label=None, before=None,
          after=None, payload=None, request_id=None, occurred_at=None,
          reason_extra=""):
    from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog

    row = TitulatecAuditLog(
        occurred_at=occurred_at or _ahora(), source=source, action=action,
        module=module, actor_id=actor_id, actor_kind=actor_kind,
        actor_label=actor_label, entity_type=entity_type, entity_id=entity_id,
        process_id=process_id, subject_label=subject_label,
        reason=f"{token} {reason_extra}".strip(), before=before, after=after,
        payload=payload, request_id=request_id, ip="10.0.0.9",
        user_agent="pytest-agent", route="/titulatec/x",
    )
    db.add(row)
    db.flush()
    return row


def _ids(html: str) -> set[int]:
    return {int(m) for m in re.findall(r'id="tt-audit-(\d+)"', html)}


def _sidebar_urls(html: str) -> list[str]:
    import lxml.html

    doc = lxml.html.fromstring(html)
    return [a.get("hx-get") for a in doc.xpath('//aside[@id="ttSide"]//a[@hx-get]')]


@pytest.fixture()
def admin(make_head):
    return make_head(perm_codes=(PERM,))


def _body(c, **params):
    r = c.get(f"{URL}/body", params=params)
    assert r.status_code == 200, r.text[:500]
    return r.text


# ---------------------------------------------------------------------------
# 1. Autorización y menú
# ---------------------------------------------------------------------------
def test_con_el_permiso_pagina_e_item(client_as, admin):
    resp = client_as(admin).get(URL)
    assert resp.status_code == 200, resp.text[:500]
    assert URL in _sidebar_urls(resp.text)
    assert 'id="tt-audit-body"' in resp.text


def test_sin_el_permiso_403_y_sin_item(client_as, make_head):
    c = client_as(make_head())
    docs = c.get(DOCS_PAGE)
    assert docs.status_code == 200
    assert URL not in _sidebar_urls(docs.text)
    assert c.get(URL).status_code == 403
    assert c.get(f"{URL}/body").status_code == 403
    assert c.get(f"{URL}/entry/1").status_code == 403


def test_item_en_la_tabla_de_nav_antes_de_actos():
    from itcj2.apps.titulatec.pages.nav import _ADMIN_NAV

    urls = [url for _l, _i, url, _n in _ADMIN_NAV]
    i = urls.index(URL)
    assert _ADMIN_NAV[i] == ("Bitácora", "bi-journal-text", URL, {PERM})
    assert _ADMIN_NAV[i + 1][0] == "Actos protocolarios"


# ---------------------------------------------------------------------------
# 2. Filtros
# ---------------------------------------------------------------------------
def test_filtros_vacios_no_dan_422(client_as, admin):
    c = client_as(admin)
    r = c.get(f"{URL}/body", params={
        "desde": "", "hasta": "", "module": "", "action": "", "who": "",
        "student": "", "process_id": "", "q": "", "page": ""})
    assert r.status_code == 200
    assert c.get(f"{URL}/body?process_id=abc&desde=basura").status_code == 200


def test_texto_en_motivo_y_ordenamiento(client_as, db_session, admin):
    t = _token()
    ahora = _ahora()
    viejo = _fila(db_session, token=t, occurred_at=ahora - timedelta(hours=2))
    nuevo = _fila(db_session, token=t, occurred_at=ahora - timedelta(hours=1))
    otro = _fila(db_session, token=_token())
    html = _body(client_as(admin), q=t)
    assert _ids(html) == {viejo.id, nuevo.id}
    assert otro.id not in _ids(html)
    assert html.index(f'id="tt-audit-{nuevo.id}"') < html.index(f'id="tt-audit-{viejo.id}"')


def test_modulo_y_accion(client_as, db_session, admin):
    t = _token()
    a = _fila(db_session, token=t, action="cohort.created", module="cohorts")
    b = _fila(db_session, token=t, action="window.created", module="windows")
    c = client_as(admin)
    assert _ids(_body(c, q=t, module="windows")) == {b.id}
    assert _ids(_body(c, q=t, action="cohort.created")) == {a.id}
    assert _ids(_body(c, q=t, module="no_existe")) == {a.id, b.id}  # se ignora


def test_fechas_default_siete_dias_y_rango(client_as, db_session, admin):
    t = _token()
    ahora = _ahora()
    reciente = _fila(db_session, token=t, occurred_at=ahora - timedelta(days=1))
    antigua = _fila(db_session, token=t, occurred_at=ahora - timedelta(days=30))
    c = client_as(admin)
    # El shell (sin desde/hasta) aplica los últimos 7 días.
    shell = c.get(f"{URL}?q={t}").text
    assert _ids(shell) == {reciente.id}
    # En el parcial, vacío = sin límite.
    assert _ids(_body(c, q=t, desde="", hasta="")) == {reciente.id, antigua.id}
    d = (ahora - timedelta(days=30)).strftime("%Y-%m-%d")
    assert _ids(_body(c, q=t, desde=d, hasta=d)) == {antigua.id}


def test_quien_por_nombre_y_usuario(client_as, db_session, admin, make_user):
    t = _token()
    u = make_user(first_name="ZULEMA", last_name="QUIROGA" + t[3:7].upper())
    otro = make_user(first_name="OTRO", last_name="SUJETO")
    a = _fila(db_session, token=t, actor_id=u.id)
    _fila(db_session, token=t, actor_id=otro.id)
    c = client_as(admin)
    assert _ids(_body(c, q=t, who="QUIROGA" + t[3:7].upper())) == {a.id}
    assert _ids(_body(c, q=t, who=u.username)) == {a.id}


def test_alumno_por_control_nombre_y_subject(client_as, db_session, admin, make_user,
                                             make_process):
    t = _token()
    alumno = make_user(first_name="BRENDA", last_name="FICTICIA" + t[3:7].upper(),
                       control_number="99" + str(uuid.uuid4().int)[:6])
    proc = make_process(alumno)
    por_proc = _fila(db_session, token=t, process_id=proc.id)
    por_subj = _fila(db_session, token=t, subject_label="20990000 · Persona Ajena")
    c = client_as(admin)
    assert _ids(_body(c, q=t, student=alumno.control_number)) == {por_proc.id}
    assert _ids(_body(c, q=t, student="FICTICIA" + t[3:7].upper())) == {por_proc.id}
    assert _ids(_body(c, q=t, student="Persona Ajena")) == {por_subj.id}
    assert _ids(_body(c, q=t, process_id=str(proc.id))) == {por_proc.id}


def test_incluir_cambios_de_datos(client_as, db_session, admin):
    t = _token()
    act = _fila(db_session, token=t, source="action")
    esp = _fila(db_session, token=t, source="process_event", action="process.process_created",
                module="processes")
    dat = _fila(db_session, token=t, source="data", action="data.update", module="data",
                entity_type="titulatec_cohorts", entity_id=3)
    c = client_as(admin)
    assert _ids(_body(c, q=t)) == {act.id, esp.id}
    assert _ids(_body(c, q=t, data="1")) == {act.id, esp.id, dat.id}


# ---------------------------------------------------------------------------
# 3. Etiquetas y actor
# ---------------------------------------------------------------------------
def test_etiquetas_y_actores(client_as, db_session, admin, make_user):
    from itcj2.apps.titulatec.services.audit_actions import AUDIT_ACTIONS

    t = _token()
    u = make_user(first_name="LUCERO", last_name="ACTORA")
    a = _fila(db_session, token=t, actor_id=u.id)
    d = _fila(db_session, token=t, source="data", action="data.delete", module="data",
              entity_type="titulatec_cohorts", entity_id=1, actor_kind="cli",
              actor_label="init-x")
    e = _fila(db_session, token=t, source="process_event", action="process.tipo_que_no_existe",
              module="processes", actor_kind="public")
    html = _body(client_as(admin), q=t, data="1")
    assert AUDIT_ACTIONS["cohort.created"][1] in html
    assert "Baja en Convocatoria" in html
    assert u.full_name in html
    assert "init-x" in html
    assert "tipo_que_no_existe" in html  # fallback sin tronar
    assert {a.id, d.id, e.id} <= _ids(html)


# ---------------------------------------------------------------------------
# 4. Paginación
# ---------------------------------------------------------------------------
def test_paginacion_50_por_pagina(client_as, db_session, admin):
    t = _token()
    ahora = _ahora()
    filas = [_fila(db_session, token=t, occurred_at=ahora - timedelta(seconds=i))
             for i in range(53)]
    c = client_as(admin)
    p1 = _ids(_body(c, q=t))
    p2 = _ids(_body(c, q=t, page="2"))
    assert len(p1) == 50 and len(p2) == 3
    assert p1 | p2 == {f.id for f in filas}


# ---------------------------------------------------------------------------
# 5. Detalle
# ---------------------------------------------------------------------------
def test_detalle_antes_despues_payload_y_hermanas(client_as, db_session, admin):
    t = _token()
    rid = "req-" + uuid.uuid4().hex[:12]
    a = _fila(db_session, token=t, request_id=rid, entity_type="titulatec_cohorts",
              entity_id=7, before={"name": "Vieja", "solo_antes": 1},
              after={"name": "Nueva", "solo_despues": 2},
              payload={"clave": "valor <b>x</b>"})
    h = _fila(db_session, token=t, request_id=rid, action="window.created",
              module="windows")
    solo = _fila(db_session, token=t, request_id="otro-" + rid)
    c = client_as(admin)
    r = c.get(f"{URL}/entry/{a.id}")
    assert r.status_code == 200, r.text[:400]
    html = r.text
    for s in ("Vieja", "Nueva", "solo_antes", "solo_despues", "clave", "10.0.0.9",
              "pytest-agent", "/titulatec/x", rid):
        assert s in html
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html
    assert f"/entry/{h.id}" in html
    assert f"/entry/{solo.id}" not in html
    assert c.get(f"{URL}/entry/999999999").status_code == 404


# ---------------------------------------------------------------------------
# 6. Liga del expediente
# ---------------------------------------------------------------------------
def test_liga_ver_bitacora_con_permiso(client_as, make_head, make_user, make_process):
    from tests.fastapi.titulatec.conftest import HEAD_PERMS

    proc = make_process(make_user(first_name="EXPE", last_name="DIENTE"))
    con = make_head(perm_codes=HEAD_PERMS + (PERM,))
    r = client_as(con).get(f"/titulatec/admin/processes/{proc.id}")
    assert r.status_code == 200, r.text[:300]
    assert f"{URL}?process_id={proc.id}" in r.text


def test_sin_permiso_no_hay_liga_ver_bitacora(client_as, make_head, make_user,
                                              make_process):
    """Test aparte: `make_head` comparte el rol por nombre dentro de la misma
    transacción, así que con y sin permiso no pueden convivir en una prueba."""
    proc = make_process(make_user(first_name="EXPE", last_name="DIENTE"))
    sin = make_head()
    r = client_as(sin).get(f"/titulatec/admin/processes/{proc.id}")
    assert r.status_code == 200, r.text[:300]
    assert "exp-ver-bitacora" not in r.text
    assert f"{URL}?process_id=" not in r.text
