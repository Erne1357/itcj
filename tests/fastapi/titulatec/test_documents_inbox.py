"""Bandeja de Documentos: coste del render (N+1) e indicador de carga sin salto.

Dos defectos distintos, un solo modulo de tests porque comparten la vista:

1. **N+1 del render.** `pages/documents.py` construia cada fila con
   `db.get(User)`, `db.get(Program)` y, dentro de un segundo bucle sobre los 3
   tipos de documento iniciales, un `DocumentType` y un `get_document` por
   codigo. Medido contra la BD de dev (cache de authz caliente, sin identity map
   heredado): **273 consultas para 28 filas** con la jefa y **148 para 14** con
   el encargado. Ahora son **5** y **8**: el sobrecoste que queda es el de
   resolver el alcance por carrera, que este cambio no toca. En tiempo de
   servidor, 112.5 -> 3.8 ms y 63.8 -> 5.4 ms (mediana de 7 corridas).

   El regresor no es "que sean 4 consultas" sino que **el numero no dependa del
   numero de filas**: por eso se mide con 2 procesos y luego con 8, y se exige
   la MISMA cuenta. Un `.first()` que se cuele dentro del bucle rompe eso
   aunque el HTML salga bien.

2. **Indicador de carga.** El retardo de `--tt-ind-delay` (bloque A) ya evita
   que aparezca cuando la peticion es rapida; lo que faltaba es que, cuando SI
   aparece, no empuje el contenido. Medido en Chromium 149 con 900 ms de
   latencia artificial: Documentos reservaba 24 px (CLS 0.024) y Citas 341.8 px
   (CLS 0.318). Con la primitiva `tt-ind-host` + `tt-ind--overlay` los dos dan
   **0 px y CLS 0**. Aqui se fija el contrato de markup para que una pestana
   nueva no vuelva a nacer con el indicador en flujo.

Lo que estos tests NO cubren y se verifico a mano en navegador: los tiempos de
aparicion (`node C:/tmp/tt_b_probe.js`) y la comparacion byte a byte del HTML
renderizado antes/despues del cambio de consultas (7/7 parciales identicos).
"""
from __future__ import annotations

import re
from pathlib import Path

import lxml.html
import pytest
from sqlalchemy import event

import itcj2.apps.titulatec as _tt_pkg

TEMPLATES = Path(_tt_pkg.__file__).resolve().parent / "templates" / "titulatec"
CSS = Path(_tt_pkg.__file__).resolve().parent / "static" / "css" / "titulatec.css"

CODIGOS = ["birth_certificate", "high_school_cert", "curp"]
GUION = "\u2014"


class _Contador:
    """Cuenta las sentencias SQL reales que pasan por la conexion del test."""

    def __init__(self, conexion):
        self.conexion = conexion
        self.sentencias = []

    def __enter__(self):
        event.listen(self.conexion, "before_cursor_execute", self._ver)
        return self

    def __exit__(self, *exc):
        event.remove(self.conexion, "before_cursor_execute", self._ver)
        return False

    def _ver(self, conn, cursor, statement, params, context, executemany):
        self.sentencias.append(" ".join(statement.split()))

    def __len__(self):
        return len(self.sentencias)

    def tocan(self, tabla):
        return [s for s in self.sentencias if tabla in s]


@pytest.fixture()
def bandeja(seed_document_types, make_program, make_cohort, make_student,
            make_process, make_document):
    """Fabrica de procesos con documentos, con los catalogos ya sembrados."""
    seed_document_types()
    programa = make_program("Ingenieria Ficticia N+1")
    cohorte = make_cohort()

    def _nuevo(codigos=CODIGOS, estado="pending", programa_=Ellipsis):
        alumno = make_student()
        proc = make_process(alumno, cohort=cohorte,
                            program=(programa if programa_ is Ellipsis else programa_))
        for code in codigos:
            make_document(proc, type_code=code, review_status=estado)
        return proc

    return _nuevo


# ---------------------------------------------------------------------------
# 1 - El coste del render no crece con las filas
# ---------------------------------------------------------------------------
def test_las_filas_de_la_bandeja_cuestan_lo_mismo_con_2_que_con_8(db_session, bandeja):
    """El regresor del N+1: la cuenta de consultas NO puede depender de las filas.

    Con el codigo viejo esto daba ~4 consultas por fila (8 con 2 procesos, 32
    con 8) y el test se caia en la segunda medicion.
    """
    from itcj2.apps.titulatec.pages.documents import _doc_rows

    procs = [bandeja() for _ in range(2)]
    with _Contador(db_session.get_bind()) as c2:
        filas2 = _doc_rows(db_session, procs)

    procs += [bandeja() for _ in range(6)]
    # Sin `expire_all()` a proposito: expirar los procesos haria que leerles el
    # `.id` los recargara uno a uno y el contador mediria ESE N+1, no el de la
    # funcion bajo prueba. Las 4 consultas del lote son `IN (...)`, que se
    # emiten siempre: el identity map no las puede cortocircuitar.
    with _Contador(db_session.get_bind()) as c8:
        filas8 = _doc_rows(db_session, procs)

    assert len(filas2) == 2 and len(filas8) == 8
    assert len(c2) == len(c8), (
        "el render vuelve a escalar con las filas: %d consultas con 2 filas, "
        "%d con 8\n%s" % (len(c2), len(c8), "\n".join(c8.sentencias))
    )
    assert len(c8) == 4, "se esperaban 4 consultas fijas, hubo %d:\n%s" % (
        len(c8), "\n".join(c8.sentencias))
    # Y en concreto: UNA sola lectura de documentos y UNA sola del catalogo.
    assert len(c8.tocan("titulatec_documents")) == 1
    assert len(c8.tocan("titulatec_document_types")) == 1


def test_la_lista_vacia_no_dispara_ninguna_consulta(db_session):
    """Sin procesos no hay nada que resolver: no se emiten `IN ()` vacios."""
    from itcj2.apps.titulatec.pages.documents import _doc_rows

    with _Contador(db_session.get_bind()) as c:
        assert _doc_rows(db_session, []) == []
    assert len(c) == 0


def test_el_contexto_completo_lee_titulatec_en_3_consultas(db_session, bandeja,
                                                           make_head):
    """`_body_ctx` de punta a punta: procesos + documentos + catalogo, y ya.

    Se cuentan solo las tablas `titulatec_*` a proposito: lo demas (permisos,
    alcance por carrera) es coste de autorizacion, no de esta vista, y varia
    segun el actor y el estado del cache.

    La jefa ve TODO, asi que a las filas del test se le suman las que ya haya en
    la BD contra la que corre la suite (en dev, 28). Da igual: el invariante es
    que la cuenta de consultas no dependa de cuantas sean.
    """
    from itcj2.apps.titulatec.pages.documents import _body_ctx

    mios = [bandeja() for _ in range(5)]
    jefa = make_head()
    _body_ctx(db_session, user_id=jefa.id, status_filter=None, selected_id=None)
    with _Contador(db_session.get_bind()) as c:
        ctx = _body_ctx(db_session, user_id=jefa.id, status_filter=None, selected_id=None)

    vistos = {f["process_id"] for f in ctx["rows"]}
    assert {p.id for p in mios} <= vistos
    assert len(c.tocan("titulatec_")) == 3, "\n".join(c.tocan("titulatec_"))


# ---------------------------------------------------------------------------
# 2 - Equivalencia: lo que el diff byte-a-byte contra dev NO pudo probar
# ---------------------------------------------------------------------------
def test_un_proceso_con_documentos_incompletos_marca_missing_los_que_faltan(
        db_session, bandeja):
    """La BD de dev solo tiene procesos con 0 o con 3 documentos.

    O sea el pseudo-estado `missing` de una fila VISIBLE (>=1 archivo pero no
    los 3) no aparece en ningun HTML de dev y el diff antes/despues no lo
    tocaba. Aqui si.
    """
    from itcj2.apps.titulatec.pages.documents import _doc_rows

    proc = bandeja(codigos=["birth_certificate"])
    (fila,) = _doc_rows(db_session, [proc])

    por_codigo = {d["type_code"]: d for d in fila["docs"]}
    assert [d["type_code"] for d in fila["docs"]] == CODIGOS   # orden del catalogo
    assert por_codigo["birth_certificate"]["status"] == "pending"
    assert por_codigo["birth_certificate"]["has_file"] is True
    assert por_codigo["high_school_cert"]["status"] == "missing"
    assert por_codigo["curp"]["status"] == "missing"
    assert por_codigo["curp"]["has_file"] is False
    assert por_codigo["curp"]["view_url"] is None
    assert fila["pending"] == 3          # 1 pending + 2 missing
    assert fila["all_approved"] is False
    # El nombre sale del catalogo aunque el documento no exista.
    assert por_codigo["curp"]["name"] == "CURP certificada"


def test_los_documentos_no_se_cruzan_entre_procesos(db_session, bandeja):
    """El lote se indexa por (process_id, type_code): un vecino no contamina."""
    from itcj2.apps.titulatec.pages.documents import _doc_rows

    con_acta = bandeja(codigos=["birth_certificate"], estado="approved")
    con_curp = bandeja(codigos=["curp"], estado="rejected")
    a, b = _doc_rows(db_session, [con_acta, con_curp])

    assert {d["type_code"] for d in a["docs"] if d["has_file"]} == {"birth_certificate"}
    assert {d["type_code"] for d in b["docs"] if d["has_file"]} == {"curp"}
    assert a["all_approved"] is False and b["all_approved"] is False
    assert [d["status"] for d in a["docs"]] == ["approved", "missing", "missing"]


def test_un_proceso_con_los_3_aprobados_queda_listo(db_session, bandeja):
    from itcj2.apps.titulatec.pages.documents import _doc_rows

    (fila,) = _doc_rows(db_session, [bandeja(estado="approved")])
    assert fila["all_approved"] is True
    assert fila["pending"] == 0


def test_un_proceso_sin_carrera_no_revienta(db_session, bandeja):
    """`program_id` es nullable y en dev no hay ninguno: el guion largo es la UI."""
    from itcj2.apps.titulatec.pages.documents import _doc_rows

    (fila,) = _doc_rows(db_session, [bandeja(programa_=None)])
    assert fila["program"] == GUION
    assert fila["student"] and fila["student"] != GUION


def test_las_filas_salen_en_el_orden_en_que_se_piden(db_session, bandeja, make_head):
    """`_doc_rows` respeta el orden recibido; el criterio lo fija `_body_ctx`."""
    from itcj2.apps.titulatec.pages.documents import _body_ctx, _doc_rows

    procs = [bandeja() for _ in range(3)]
    filas = _doc_rows(db_session, procs)
    assert [f["process_id"] for f in filas] == [p.id for p in procs]

    # Y la bandeja completa los devuelve en orden estable. Ojo: los 3 se crean
    # en la MISMA transaccion y `created_at` es `server_default NOW()`, que en
    # Postgres es la hora de inicio de la transaccion -> los tres empatan. Sin
    # el desempate por `id` el orden seria el que quisiera el planificador, y la
    # lista se re-barajaria sola en cada filtro.
    jefa = make_head()
    ctx = _body_ctx(db_session, user_id=jefa.id, status_filter=None, selected_id=None)
    ids = [f["process_id"] for f in ctx["rows"]]
    mios = [i for i in ids if i in {p.id for p in procs}]
    assert mios == [p.id for p in reversed(procs)], (mios, [p.id for p in procs])


def test_la_bandeja_no_se_rebaraja_entre_recargas(db_session, bandeja, make_head):
    """Mismo orden en dos renders seguidos, aunque `created_at` empate."""
    from itcj2.apps.titulatec.pages.documents import _body_ctx

    for _ in range(6):
        bandeja()
    jefa = make_head()
    uno = _body_ctx(db_session, user_id=jefa.id, status_filter=None, selected_id=None)
    dos = _body_ctx(db_session, user_id=jefa.id, status_filter=None, selected_id=None)
    assert [f["process_id"] for f in uno["rows"]] == [f["process_id"] for f in dos["rows"]]


# ---------------------------------------------------------------------------
# 3 - Contrato de markup del indicador de carga
# ---------------------------------------------------------------------------
def _arbol(path: Path):
    """Plantilla Jinja -> arbol lxml. Los `{% %}` quedan como texto, dan igual."""
    return lxml.html.fragment_fromstring(path.read_text(encoding="utf-8"),
                                         create_parent="div")


def test_ningun_indicador_de_carga_reserva_alto():
    """Invariante del design system: todo `htmx-indicator` es overlay en un host.

    Un indicador EN FLUJO empuja la pagina entera al aparecer. Medido antes de
    arreglarlo: 24 px en Documentos y 341.8 px en Citas (CLS 0.318). La
    primitiva vive en `static/css/titulatec.css` y esta documentada en
    `docs/design/ui_motion.md`.
    """
    revisados, ofensores = 0, []
    for path in sorted(TEMPLATES.rglob("*.html")):
        for el in _arbol(path).find_class("htmx-indicator"):
            revisados += 1
            rel = path.relative_to(TEMPLATES)
            clases = set((el.get("class") or "").split())
            if "tt-ind--overlay" not in clases:
                ofensores.append("%s #%s: sin `tt-ind--overlay` (reservaria alto)"
                                 % (rel, el.get("id")))
                continue
            if not any("tt-ind-host" in (a.get("class") or "").split()
                       for a in el.iterancestors()):
                ofensores.append(
                    "%s #%s: el overlay no tiene ancestro `.tt-ind-host`, asi que se "
                    "posiciona contra un contenedor ajeno" % (rel, el.get("id")))
            if el.get("style"):
                ofensores.append("%s #%s: `style=` inline gana al fundido de "
                                 "`--tt-ind-fade`" % (rel, el.get("id")))
    # Censo real hoy: 2 (documents.html y appointments.html). El umbral es el
    # control positivo: si el barrido deja de encontrar indicadores, se cae.
    assert revisados >= 2, "el censo de indicadores encogio a %d" % revisados
    assert not ofensores, "indicadores que empujan el layout:\n" + "\n".join(ofensores)


def test_cada_hx_indicator_apunta_a_un_indicador_que_existe():
    """Un `hx-indicator="#id"` colgado deja la region sin senal de carga."""
    ids, referidos = set(), set()
    for path in sorted(TEMPLATES.rglob("*.html")):
        referidos |= set(re.findall(r'hx-indicator="#([\w-]+)"',
                                    path.read_text(encoding="utf-8")))
        for el in _arbol(path).find_class("htmx-indicator"):
            if el.get("id"):
                ids.add(el.get("id"))
    assert referidos, "no se encontro ni un hx-indicator: revisa el regex"
    assert referidos <= ids, "hx-indicator sin destino: %s" % sorted(referidos - ids)


def test_la_pagina_servida_trae_el_overlay_ya_montado(client_as, make_head, bandeja,
                                                      db_session):
    """De punta a punta: no basta con que la plantilla lo diga, tiene que llegar."""
    from itcj2.core.models.user import User

    proc = bandeja()
    control = db_session.get(User, proc.student_id).control_number
    html = client_as(make_head()).get("/titulatec/admin/documents").text

    assert "tt-ind-host" in html
    assert 'id="docs-skel"' in html and "tt-ind--overlay" in html
    assert 'style="opacity' not in html.split('id="docs-skel"')[1][:200]
    # Y el cuerpo corre contra la sesion del test: el control `99xxxxxx` no
    # existe en la BD de dev. (El folio no se afirma: solo sale en el panel de
    # detalle, o sea con `?selected=`.)
    assert control in html


def test_el_dictamen_re_renderiza_la_bandeja_con_el_estado_nuevo(
        client_as, make_head, db_session, bandeja):
    """El POST de revisión vuelve a pasar por `_doc_rows`: que no se rompa ahí.

    Es el unico camino que llama `_body_ctx` DESPUES de escribir; el resto son
    lecturas.
    """
    from tests.fastapi.titulatec.conftest import HEAD_PERMS

    proc = bandeja(codigos=["birth_certificate"])
    jefa = make_head(perm_codes=HEAD_PERMS + ("titulatec.document.api.approve",
                                              "titulatec.document.api.reject"))
    resp = client_as(jefa).post(
        "/titulatec/admin/documents/%d/document/review" % proc.id,
        data={"type_code": "birth_certificate", "action": "approve"},
    )

    assert resp.status_code == 200, resp.text[:400]
    from itcj2.apps.titulatec.pages.documents import _doc_rows
    (fila,) = _doc_rows(db_session, [proc])
    estados = {d["type_code"]: d["status"] for d in fila["docs"]}
    assert estados["birth_certificate"] == "approved"
    assert estados["curp"] == "missing"
    assert fila["all_approved"] is False        # faltan 2: no auto-avanza


def test_la_primitiva_del_indicador_existe_en_el_css():
    """El markup de arriba no sirve de nada si el CSS no define la primitiva."""
    css = CSS.read_text(encoding="utf-8")
    for regla in (".tt-ind-host", ".tt-ind--overlay", ".tt-ind-badge"):
        assert re.search(re.escape(regla) + r"\s*[,{]", css), (
            "falta la regla %s en titulatec.css" % regla)
    cuerpo = css.split(".tt-ind--overlay", 1)[1][:500]
    assert "position: absolute" in cuerpo, (
        "`.tt-ind--overlay` dejo de estar fuera del flujo: volveria a reservar alto")
