"""Orden FIFO de la pestana "Por evaluar" (bandeja de Documentos).

Hasta ahora las 4 pestanas de `_body_ctx` (Todos/Por evaluar/Con rechazo/
Completos) compartian el mismo orden: `TitulationProcess.created_at desc, id
desc` -- cuando se CREO el proceso, no cuando llego el documento a revisar.
Con una convocatoria importada por CSV todos los procesos empatan en
`created_at` (mismo `NOW()` de transaccion) y el orden real lo decidia el
archivo de origen, no quien lleva mas tiempo esperando.

Este archivo cubre SOLO la pestana `pending`: las otras tres (`''`, `rejected`,
`approved`) no cambian y las prueba `test_las_filas_salen_en_el_orden_en_que_se_piden`
de `test_documents_inbox.py`.

La clave nueva es la espera REAL: el MINIMO, entre los documentos con archivo
en `review_status == 'pending'` de la fila, de la ULTIMA llegada de cada uno.
"Ultima" y no "primera" porque una resubida tras un rechazo es una llegada
NUEVA (se va al final, no conserva el lugar del primer intento). La fuente de
esa fecha es la bitacora (`ProcessEvent(document_uploaded)`, que
`DocumentService.save` escribe en la MISMA transaccion que cada subida) y no
`Document.created_at`/`updated_at`: la primera no se resetea al resubir
(`DocumentService.save` actualiza la fila en su lugar) y la segunda no tiene
`onupdate` ni la escribe nadie.

Reusa la fabrica `bandeja` y el contador de SQL `_Contador` de
`test_documents_inbox.py` (mismo patron que otros archivos de esta suite
importan piezas de un modulo hermano, p. ej.
`test_scope_guard.py::_rutas` en `test_expediente_proceso.py`).

Los datos reales de dev se cuelan en `ctx["rows"]` (la jefa ve TODO). Cada
aserto filtra a los `process_id` que crea el propio test (`mios`), como ya
hace `test_las_filas_salen_en_el_orden_en_que_se_piden`.
"""
from __future__ import annotations

from datetime import datetime

from tests.fastapi.titulatec.test_documents_inbox import _Contador, bandeja  # noqa: F401


def _evento_subida(db_session, proc, type_code, cuando, version=1):
    """`ProcessEvent(document_uploaded)` con `created_at` EXPLICITO.

    Es el mismo evento que escribe `DocumentService.save`
    (`services/document_service.py:184-189`), pero aqui se inserta a mano con
    una fecha fija: todas las filas de un test viven en la MISMA transaccion
    y `server_default NOW()` es la hora de INICIO de esa transaccion, asi que
    sin esto todos los eventos empatarian.
    """
    from itcj2.apps.titulatec.models import ProcessEvent

    ev = ProcessEvent(
        process_id=proc.id, actor_id=None, event_type="document_uploaded",
        phase_number=1,
        payload={"type_code": type_code, "original_name": "documento.pdf", "version": version},
        created_at=cuando,
    )
    db_session.add(ev)
    db_session.flush()
    return ev


# ---------------------------------------------------------------------------
# (a) Orden por llegada real, no por creacion del proceso
# ---------------------------------------------------------------------------
def test_por_evaluar_sale_en_orden_de_llegada_no_de_creacion(db_session, bandeja, make_head):
    """3 procesos creados p1,p2,p3 (ids ASCENDENTES) sea cual sea que llega su
    documento en el orden p3,p1,p2 -- ni el orden de creacion (p1,p2,p3) ni su
    inverso (p3,p2,p1, el que usa "Todos") coinciden con el esperado, asi que
    un desempate por id no puede hacer pasar este test por accidente."""
    from itcj2.apps.titulatec.pages.documents import _body_ctx

    t1 = datetime(2001, 1, 1, 9, 0)
    t2 = datetime(2001, 1, 1, 10, 0)
    t3 = datetime(2001, 1, 1, 11, 0)

    p1 = bandeja(codigos=["birth_certificate"])
    p2 = bandeja(codigos=["birth_certificate"])
    p3 = bandeja(codigos=["birth_certificate"])
    assert p1.id < p2.id < p3.id, "la fabrica dejo de dar ids ascendentes"
    _evento_subida(db_session, p3, "birth_certificate", t1)
    _evento_subida(db_session, p1, "birth_certificate", t2)
    _evento_subida(db_session, p2, "birth_certificate", t3)

    jefa = make_head()
    ctx = _body_ctx(db_session, user_id=jefa.id, status_filter="pending", selected_id=None)

    mios_ids = {p1.id, p2.id, p3.id}
    mios = [f["process_id"] for f in ctx["rows"] if f["process_id"] in mios_ids]
    assert mios == [p3.id, p1.id, p2.id], (mios, {"p1": p1.id, "p2": p2.id, "p3": p3.id})


# ---------------------------------------------------------------------------
# (b) Reenvio tras rechazo = llegada nueva
# ---------------------------------------------------------------------------
def test_reenvio_tras_rechazo_cuenta_como_llegada_nueva(db_session, bandeja, make_head):
    """p4 sube su documento PRIMERO que nadie (t0, el mas viejo) pero lo
    resube despues de que los otros tres ya llegaron (t4 > t3). Si el codigo
    tomara la PRIMERA subida en vez de la ULTIMA, p4 saldria primero; con la
    ultima, sale al final."""
    from itcj2.apps.titulatec.pages.documents import _body_ctx

    t0 = datetime(2001, 1, 1, 6, 0)
    t1 = datetime(2001, 1, 1, 9, 0)
    t2 = datetime(2001, 1, 1, 10, 0)
    t3 = datetime(2001, 1, 1, 11, 0)
    t4 = datetime(2001, 1, 1, 12, 0)

    p1 = bandeja(codigos=["birth_certificate"])
    p2 = bandeja(codigos=["birth_certificate"])
    p3 = bandeja(codigos=["birth_certificate"])
    p4 = bandeja(codigos=["birth_certificate"])
    _evento_subida(db_session, p3, "birth_certificate", t1)
    _evento_subida(db_session, p1, "birth_certificate", t2)
    _evento_subida(db_session, p2, "birth_certificate", t3)
    _evento_subida(db_session, p4, "birth_certificate", t0, version=1)   # 1er intento
    _evento_subida(db_session, p4, "birth_certificate", t4, version=2)   # reenvio

    jefa = make_head()
    ctx = _body_ctx(db_session, user_id=jefa.id, status_filter="pending", selected_id=None)

    mios_ids = {p1.id, p2.id, p3.id, p4.id}
    mios = [f["process_id"] for f in ctx["rows"] if f["process_id"] in mios_ids]
    assert mios == [p3.id, p1.id, p2.id, p4.id], mios


# ---------------------------------------------------------------------------
# (c) Sin evento en la bitacora -> respaldo Document.created_at
# ---------------------------------------------------------------------------
def test_sin_evento_de_bitacora_usa_created_at_del_documento(db_session, bandeja, make_head):
    """3 filas SIN ningun `ProcessEvent`: `bandeja()` crea el `Document` con
    `make_document` (no con `DocumentService.save`), asi que no hay bitacora y
    el respaldo tiene que ser `Document.created_at`. Mismo cuidado que en (a):
    ids ascendentes p1,p2,p3 pero `created_at` en el orden p3,p1,p2, para que
    ni el orden de creacion ni su inverso expliquen un acierto."""
    from itcj2.apps.titulatec.pages.documents import _body_ctx
    from itcj2.apps.titulatec.services.document_service import DocumentService

    t1 = datetime(2001, 1, 1, 9, 0)
    t2 = datetime(2001, 1, 1, 10, 0)
    t3 = datetime(2001, 1, 1, 11, 0)

    p1 = bandeja(codigos=["birth_certificate"])
    p2 = bandeja(codigos=["birth_certificate"])
    p3 = bandeja(codigos=["birth_certificate"])
    assert p1.id < p2.id < p3.id

    DocumentService.get_document(db_session, p3.id, "birth_certificate").created_at = t1
    DocumentService.get_document(db_session, p1.id, "birth_certificate").created_at = t2
    DocumentService.get_document(db_session, p2.id, "birth_certificate").created_at = t3
    db_session.flush()

    jefa = make_head()
    ctx = _body_ctx(db_session, user_id=jefa.id, status_filter="pending", selected_id=None)

    mios_ids = {p1.id, p2.id, p3.id}
    mios = [f["process_id"] for f in ctx["rows"] if f["process_id"] in mios_ids]
    assert mios == [p3.id, p1.id, p2.id], mios


# ---------------------------------------------------------------------------
# (d) Solo documentos "missing" -> al final, sin rebarajarse entre si
# ---------------------------------------------------------------------------
def test_las_filas_solo_con_documentos_faltantes_van_al_final(db_session, bandeja, make_head):
    """Dos filas con SOLO un documento missing (nada que dictaminar, se
    espera al alumno) van despues de la que si tiene un pendiente con
    archivo, y entre ellas mantienen el orden previo: `created_at desc, id
    desc`, o sea la mas nueva primero."""
    from itcj2.apps.titulatec.pages.documents import _body_ctx

    t_w = datetime(2001, 1, 1, 9, 0)
    esperando = bandeja(codigos=["birth_certificate"])
    _evento_subida(db_session, esperando, "birth_certificate", t_w)

    # `estado="approved"` en el UNICO codigo subido: los otros 2 tipos de la
    # fila quedan "missing" (sin fila `Document`) y no aportan ningun tiempo.
    solo_faltantes_1 = bandeja(codigos=["birth_certificate"], estado="approved")
    solo_faltantes_2 = bandeja(codigos=["birth_certificate"], estado="approved")
    assert solo_faltantes_1.id < solo_faltantes_2.id

    jefa = make_head()
    ctx = _body_ctx(db_session, user_id=jefa.id, status_filter="pending", selected_id=None)

    mios_ids = {esperando.id, solo_faltantes_1.id, solo_faltantes_2.id}
    mios = [f["process_id"] for f in ctx["rows"] if f["process_id"] in mios_ids]
    assert mios == [esperando.id, solo_faltantes_2.id, solo_faltantes_1.id], mios


# ---------------------------------------------------------------------------
# (e) La consulta extra es UNA por lote, no una por fila
# ---------------------------------------------------------------------------
def test_la_pestana_pendiente_no_escala_con_las_filas(db_session, bandeja, make_head):
    """Mismo patron que `test_las_filas_de_la_bandeja_cuestan_lo_mismo_con_2_que_con_8`
    en `test_documents_inbox.py`, pero sobre `_body_ctx` con `status_filter="pending"`:
    la cuenta de consultas `titulatec_*` no puede depender del numero de filas."""
    from itcj2.apps.titulatec.pages.documents import _body_ctx

    jefa = make_head()
    for _ in range(2):
        bandeja()
    with _Contador(db_session.get_bind()) as pocas:
        _body_ctx(db_session, user_id=jefa.id, status_filter="pending", selected_id=None)

    for _ in range(6):
        bandeja()
    with _Contador(db_session.get_bind()) as muchas:
        _body_ctx(db_session, user_id=jefa.id, status_filter="pending", selected_id=None)

    assert len(pocas.tocan("titulatec_")) == len(muchas.tocan("titulatec_")), (
        "la pestana 'pending' escala con las filas: %d consultas con pocas, "
        "%d con muchas\n%s" % (len(pocas.tocan("titulatec_")), len(muchas.tocan("titulatec_")),
                                "\n".join(muchas.sentencias))
    )
    # Las 3 de siempre (procesos, tipos, documentos) mas la nueva de eventos.
    assert len(muchas.tocan("titulatec_")) == 4, "\n".join(muchas.sentencias)
    assert len(muchas.tocan("titulatec_process_events")) == 1
