"""Tests de ``document_flow_service`` — la lógica más delicada de Adhoc.

Escritos ANTES del service (TDD). Cubren, uno por uno, los bugs que el plan
manda arreglar (§7, §10.b y §11 del PLAN_MIGRACION_ADHOC):

* **#3** ``save_flow_steps`` borraba TODOS los pasos y los recreaba con ids
  nuevos, dejando ``adhoc_tasks.flow_step_id`` y
  ``adhoc_documents.current_step_id`` apuntando a filas muertas. Aquí el upsert
  es **por ``step_order``** y conserva el id, y además se bloquea con 409 si hay
  documentos activos.
* ``set_step_validators`` reasignaba la lista entera y **borraba
  ``notify_on_overdue``** de todos sin avisar.
* ``delete_flow`` necesita el mismo guard que el upsert: los pasos son
  ``ondelete CASCADE`` pero ``adhoc_tasks.flow_step_id`` y
  ``adhoc_documents.current_step_id`` son RESTRICT.
* ``start_flow`` asignaba ``doc.flow_id`` con el valor crudo del JSON, sin
  comprobar que el flujo existiera.

Se usa el ``db_session`` transaccional de ``tests/fastapi/conftest.py`` (Postgres
real con rollback) porque lo que se está probando **son** las FK, los unique y
la tabla de asociación con payload: con ``MagicMock`` no se prueba nada de eso.
"""
import uuid

import pytest

from itcj2.apps.adhoc.models import (
    AdhocApprovalFlow,
    AdhocApprovalFlowStep,
    AdhocDocument,
    AdhocTask,
    adhoc_flow_step_assignees,
)
from itcj2.apps.adhoc.schemas.documents import FlowCreate, FlowStepIn, FlowUpdate
from itcj2.apps.adhoc.services.document_flow_service import AdhocDocumentFlowService as SVC
from itcj2.apps.adhoc.services.document_service import AdhocConflict
from itcj2.core.models.user import User


# --------------------------------------------------------------------------
# Factories locales (el conftest de adhoc es compartido con otros dominios)
# --------------------------------------------------------------------------

def make_user(db, label="val"):
    tag = uuid.uuid4().hex[:10]
    u = User(
        first_name=label.upper(),
        last_name="ADHOC",
        username=f"e2e_adhoc_{label}_{tag}",
        email=f"e2e_adhoc_{label}_{tag}@test.local",
    )
    db.add(u)
    db.flush()
    return u


def make_flow(db, name=None, steps=(("Revisión", 3), ("Autorización", 5))):
    flow = AdhocApprovalFlow(name=name or f"e2e_flow_{uuid.uuid4().hex[:8]}")
    db.add(flow)
    db.flush()
    for i, (step_name, days) in enumerate(steps, start=1):
        db.add(AdhocApprovalFlowStep(
            flow_id=flow.id, name=step_name, days_limit=days, step_order=i,
        ))
    db.flush()
    db.refresh(flow)
    return flow


def make_document(db, **kw):
    kw.setdefault("title", f"e2e_doc_{uuid.uuid4().hex[:8]}")
    kw.setdefault("status", "Borrador")
    doc = AdhocDocument(**kw)
    db.add(doc)
    db.flush()
    return doc


def notify_map(db, step_id):
    rows = db.execute(
        adhoc_flow_step_assignees.select().where(
            adhoc_flow_step_assignees.c.step_id == step_id
        )
    ).fetchall()
    return {r.user_id: r.notify_on_overdue for r in rows}


# ==========================================================================
# CRUD de flujos
# ==========================================================================

def test_create_flow_persiste_nombre_y_descripcion(db_session):
    flow = SVC.create_flow(db_session, FlowCreate(name="  Flujo A  ", description="desc"))
    assert flow.id is not None
    assert flow.name == "Flujo A"          # AdhocSchema recorta espacios
    assert flow.description == "desc"


def test_update_flow_solo_toca_lo_enviado(db_session):
    flow = SVC.create_flow(db_session, FlowCreate(name="Original", description="d"))
    SVC.update_flow(db_session, flow.id, FlowUpdate(name="Renombrado"))
    db_session.refresh(flow)
    assert flow.name == "Renombrado"
    assert flow.description == "d"


def test_update_flow_inexistente_es_404(db_session):
    with pytest.raises(LookupError):
        SVC.update_flow(db_session, 99_999_999, FlowUpdate(name="X"))


def test_delete_flow_borra_sus_pasos_en_cascada(db_session):
    flow = make_flow(db_session)
    step_ids = [s.id for s in flow.steps]
    SVC.delete_flow(db_session, flow.id)
    assert db_session.get(AdhocApprovalFlow, flow.id) is None
    assert db_session.query(AdhocApprovalFlowStep).filter(
        AdhocApprovalFlowStep.id.in_(step_ids)
    ).count() == 0


def test_delete_flow_bloquea_si_un_documento_lo_usa(db_session):
    """RESTRICT real: ``adhoc_documents.flow_id`` no tiene ``ondelete``."""
    flow = make_flow(db_session)
    make_document(db_session, flow_id=flow.id, current_step_id=flow.steps[0].id,
                  status="En Revisión")
    with pytest.raises(AdhocConflict):
        SVC.delete_flow(db_session, flow.id)
    assert db_session.get(AdhocApprovalFlow, flow.id) is not None


def test_delete_flow_bloquea_si_una_tarea_apunta_a_un_paso(db_session):
    flow = make_flow(db_session)
    doc = make_document(db_session, status="Aprobado")
    db_session.add(AdhocTask(
        description="Aprobar", status="Completada", priority="Alta",
        document_id=doc.id, flow_step_id=flow.steps[1].id,
    ))
    db_session.flush()
    with pytest.raises(AdhocConflict):
        SVC.delete_flow(db_session, flow.id)


# ==========================================================================
# upsert_flow_steps — bug #3
# ==========================================================================

def test_upsert_crea_los_pasos_de_un_flujo_vacio(db_session):
    flow = SVC.create_flow(db_session, FlowCreate(name="Vacío"))
    steps = SVC.upsert_flow_steps(db_session, flow.id, [
        FlowStepIn(name="Uno", days_limit=2),
        FlowStepIn(name="Dos", days_limit=4),
    ])
    assert [s.step_order for s in steps] == [1, 2]
    assert [s.name for s in steps] == ["Uno", "Dos"]
    assert [s.days_limit for s in steps] == [2, 4]


def test_upsert_conserva_el_id_del_paso_con_el_mismo_step_order(db_session):
    """El corazón del bug #3: editar un paso NO debe cambiar su id."""
    flow = make_flow(db_session)
    ids_antes = {s.step_order: s.id for s in flow.steps}

    SVC.upsert_flow_steps(db_session, flow.id, [
        FlowStepIn(name="Revisión editada", days_limit=9, step_order=1),
        FlowStepIn(name="Autorización", days_limit=5, step_order=2),
    ])

    db_session.refresh(flow)
    ids_despues = {s.step_order: s.id for s in flow.steps}
    assert ids_despues == ids_antes
    assert flow.steps[0].name == "Revisión editada"
    assert flow.steps[0].days_limit == 9


def test_upsert_agrega_un_paso_sin_tocar_los_previos(db_session):
    flow = make_flow(db_session)
    ids_antes = {s.step_order: s.id for s in flow.steps}
    SVC.upsert_flow_steps(db_session, flow.id, [
        FlowStepIn(name="Revisión", days_limit=3, step_order=1),
        FlowStepIn(name="Autorización", days_limit=5, step_order=2),
        FlowStepIn(name="Publicación", days_limit=1, step_order=3),
    ])
    db_session.refresh(flow)
    assert len(flow.steps) == 3
    assert {s.step_order: s.id for s in flow.steps if s.step_order in (1, 2)} == ids_antes


def test_upsert_borra_los_pasos_sobrantes(db_session):
    flow = make_flow(db_session)
    sobrante = flow.steps[1].id
    SVC.upsert_flow_steps(db_session, flow.id, [FlowStepIn(name="Revisión", step_order=1)])
    db_session.refresh(flow)
    assert len(flow.steps) == 1
    assert db_session.get(AdhocApprovalFlowStep, sobrante) is None


def test_upsert_rechaza_step_order_duplicado(db_session):
    flow = SVC.create_flow(db_session, FlowCreate(name="Dup"))
    with pytest.raises(ValueError):
        SVC.upsert_flow_steps(db_session, flow.id, [
            FlowStepIn(name="A", step_order=1),
            FlowStepIn(name="B", step_order=1),
        ])


def test_upsert_rechaza_lista_vacia(db_session):
    flow = make_flow(db_session)
    with pytest.raises(ValueError):
        SVC.upsert_flow_steps(db_session, flow.id, [])
    db_session.refresh(flow)
    assert len(flow.steps) == 2


def test_upsert_bloquea_con_409_si_hay_documentos_en_revision(db_session):
    """Regresión obligatoria: el upsert no huerfaniza documentos activos."""
    flow = make_flow(db_session)
    make_document(db_session, flow_id=flow.id, current_step_id=flow.steps[0].id,
                  status="En Revisión")
    with pytest.raises(AdhocConflict):
        SVC.upsert_flow_steps(db_session, flow.id, [FlowStepIn(name="Solo uno", step_order=1)])
    db_session.refresh(flow)
    assert len(flow.steps) == 2


def test_upsert_bloquea_si_el_paso_a_borrar_tiene_tareas(db_session):
    """El documento ya no está en revisión, pero la tarea sigue apuntando al paso."""
    flow = make_flow(db_session)
    doc = make_document(db_session, status="Aprobado")
    db_session.add(AdhocTask(
        description="Aprobar", status="Completada", priority="Alta",
        document_id=doc.id, flow_step_id=flow.steps[1].id,
    ))
    db_session.flush()
    with pytest.raises(AdhocConflict):
        SVC.upsert_flow_steps(db_session, flow.id, [FlowStepIn(name="Revisión", step_order=1)])


def test_upsert_flujo_inexistente_es_404(db_session):
    with pytest.raises(LookupError):
        SVC.upsert_flow_steps(db_session, 99_999_999, [FlowStepIn(name="X")])


# ==========================================================================
# Validadores del paso
# ==========================================================================

def test_set_step_validators_asigna_y_quita(db_session):
    flow = make_flow(db_session)
    step = flow.steps[0]
    u1, u2, u3 = make_user(db_session, "a"), make_user(db_session, "b"), make_user(db_session, "c")

    SVC.set_step_validators(db_session, step.id, [u1.id, u2.id])
    assert set(notify_map(db_session, step.id)) == {u1.id, u2.id}

    SVC.set_step_validators(db_session, step.id, [u2.id, u3.id])
    assert set(notify_map(db_session, step.id)) == {u2.id, u3.id}


def test_set_step_validators_preserva_notify_on_overdue(db_session):
    """El legacy reasignaba la lista entera y borraba el flag de todos."""
    flow = make_flow(db_session)
    step = flow.steps[0]
    u1, u2 = make_user(db_session, "a"), make_user(db_session, "b")

    SVC.set_step_validators(db_session, step.id, [u1.id, u2.id])
    SVC.set_step_overdue_notifications(db_session, step.id, [u1.id])
    assert notify_map(db_session, step.id)[u1.id] is True

    # Se vuelve a guardar la asignación (u2 sigue, se suma u3).
    u3 = make_user(db_session, "c")
    SVC.set_step_validators(db_session, step.id, [u1.id, u2.id, u3.id])

    flags = notify_map(db_session, step.id)
    assert flags[u1.id] is True, "notify_on_overdue se perdió al reasignar validadores"
    assert flags[u2.id] is False
    assert flags[u3.id] is False


def test_set_step_validators_rechaza_usuarios_inexistentes(db_session):
    flow = make_flow(db_session)
    with pytest.raises(ValueError):
        SVC.set_step_validators(db_session, flow.steps[0].id, [99_999_999])


def test_set_step_validators_paso_inexistente_es_404(db_session):
    with pytest.raises(LookupError):
        SVC.set_step_validators(db_session, 99_999_999, [])


def test_set_step_overdue_notifications_resetea_los_no_enviados(db_session):
    flow = make_flow(db_session)
    step = flow.steps[0]
    u1, u2 = make_user(db_session, "a"), make_user(db_session, "b")
    SVC.set_step_validators(db_session, step.id, [u1.id, u2.id])

    SVC.set_step_overdue_notifications(db_session, step.id, [u1.id, u2.id])
    assert all(notify_map(db_session, step.id).values())

    SVC.set_step_overdue_notifications(db_session, step.id, [u2.id])
    flags = notify_map(db_session, step.id)
    assert flags[u1.id] is False
    assert flags[u2.id] is True


def test_set_step_overdue_notifications_agrega_al_que_no_estaba_asignado(db_session):
    """Comportamiento del legacy que se conserva: marcar implica asignar."""
    flow = make_flow(db_session)
    step = flow.steps[0]
    u1 = make_user(db_session, "a")
    SVC.set_step_overdue_notifications(db_session, step.id, [u1.id])
    assert notify_map(db_session, step.id) == {u1.id: True}


def test_get_step_details_devuelve_asignados_y_notificados(db_session):
    flow = make_flow(db_session)
    step = flow.steps[0]
    u1, u2 = make_user(db_session, "a"), make_user(db_session, "b")
    SVC.set_step_validators(db_session, step.id, [u1.id, u2.id])
    SVC.set_step_overdue_notifications(db_session, step.id, [u2.id])

    got_step, assigned, notify_ids = SVC.get_step_details(db_session, step.id)
    assert got_step.id == step.id
    assert {u.id for u in assigned} == {u1.id, u2.id}
    assert notify_ids == {u2.id}


# ==========================================================================
# start_flow — plan §10.b
# ==========================================================================

def test_start_flow_sin_flow_id_es_400(db_session):
    doc = make_document(db_session)
    with pytest.raises(ValueError):
        SVC.start_flow(db_session, doc.id, None, actor_id=None)


def test_start_flow_documento_inexistente_es_404(db_session):
    flow = make_flow(db_session)
    with pytest.raises(LookupError):
        SVC.start_flow(db_session, 99_999_999, flow.id, actor_id=None)


def test_start_flow_valida_que_el_flujo_exista(db_session):
    """El legacy asignaba ``doc.flow_id`` con el valor crudo del JSON."""
    doc = make_document(db_session)
    with pytest.raises(LookupError):
        SVC.start_flow(db_session, doc.id, 99_999_999, actor_id=None)
    db_session.refresh(doc)
    assert doc.flow_id is None
    assert doc.status == "Borrador"


def test_start_flow_rechaza_flujo_sin_pasos(db_session):
    flow = SVC.create_flow(db_session, FlowCreate(name="Sin pasos"))
    doc = make_document(db_session)
    with pytest.raises(ValueError):
        SVC.start_flow(db_session, doc.id, flow.id, actor_id=None)


def test_start_flow_rechaza_documento_ya_iniciado(db_session):
    """409, no 400: el documento existe, es su estado el que impide la operación.

    Antes esto era un ``ValueError`` → 400, y solo cuando además había
    ``flow_id``: el mismo documento 'En Revisión' contestaba 400 con flujo y 409
    sin él, según una columna que ni siquiera es la que bloquea. Ahora las dos
    puertas —el gate de ``DOCUMENT_STATUSES_STARTABLE`` y el de tareas vivas—
    hablan el mismo idioma que el resto del contrato: ``AdhocConflict`` → 409.
    """
    flow = make_flow(db_session)
    doc = make_document(db_session, flow_id=flow.id, status="En Revisión",
                        current_step_id=flow.steps[0].id)
    with pytest.raises(AdhocConflict):
        SVC.start_flow(db_session, doc.id, flow.id, actor_id=None)


def test_start_flow_no_duplica_las_tareas_de_un_flujo_ya_vivo(db_session):
    """El guard mira las TAREAS, no ``status`` (documento 202 de la migración).

    202 llegó del SGC legacy en ``status='Borrador'`` con ``flow_id=5``,
    ``current_step_id=NULL`` y **dos tareas vivas** (pasos 1 y 2). El guard viejo
    exigía ``status == 'En Revisión'``, así que no disparaba; y 'Borrador' sí
    está en ``DOCUMENT_STATUSES_STARTABLE``, así que el panel pintaba el botón
    del sello y volver a pulsarlo creaba un segundo juego completo de tareas: dos
    "Aprobar Documento: …" por paso en el tablero de cada validador.
    """
    flow = make_flow(db_session)
    doc = make_document(db_session, flow_id=flow.id, status="Borrador")
    for step, estado in zip(flow.steps, ("En Revisión", "En Espera")):
        db_session.add(AdhocTask(
            description=f"Aprobar Documento: {doc.title} (Paso: {step.name})",
            status=estado, priority="Alta",
            document_id=doc.id, flow_step_id=step.id,
        ))
    db_session.flush()

    with pytest.raises(AdhocConflict) as exc:
        SVC.start_flow(db_session, doc.id, flow.id, actor_id=None)
    assert "en curso" in str(exc.value)

    assert db_session.query(AdhocTask).filter_by(document_id=doc.id).count() == 2
    db_session.refresh(doc)
    assert doc.status == "Borrador"
    assert doc.current_step_id is None


def test_start_flow_no_lo_bloquea_una_tarea_de_seguimiento_del_documento(db_session):
    """Una tarea de trabajo NO es un flujo. El guard exige ``flow_step_id``.

    Este es el falso positivo que costó el primer intento del guard: se reutilizó
    ``AdhocDocumentService._assert_sin_flujo_vivo``, que cuenta CUALQUIER tarea
    en ``'En Revisión'`` o ``'En Espera'``, y con eso una tarea de seguimiento
    creada a mano dejaba el documento imposible de sellar, con un 409 que
    afirmaba un flujo inexistente y pedía cerrar trabajo legítimo.

    No es hipotético: la pantalla ``/adhoc/documentos/{id}/tareas`` que entregó
    B4 deja crear tareas de documento y su ``<select>`` ofrece esos dos estados
    entre los seis. Medido contra la base real sobre el documento 2
    (``'Borrador'``, sin flujo y sin tareas): una sola tarea manual en
    ``'En Espera'`` o en ``'En Revisión'`` producía el 409.

    ``flow_step_id`` es la marca que distingue las dos cosas, y solo la pone
    ``start_flow``.
    """
    flow = make_flow(db_session)
    doc = make_document(db_session, status="Borrador")
    for estado in ("En Revisión", "En Espera", "Pendiente"):
        db_session.add(AdhocTask(
            description=f"Revisión de redacción ({estado})",
            status=estado, priority="Media", document_id=doc.id,
        ))
    db_session.flush()

    SVC.start_flow(db_session, doc.id, flow.id, actor_id=None)

    db_session.refresh(doc)
    assert doc.status == "En Revisión"
    assert doc.current_step_id == flow.steps[0].id
    # Las 3 de seguimiento + una por paso del flujo.
    assert db_session.query(AdhocTask).filter_by(document_id=doc.id).count() == 5


def test_start_flow_ignora_el_flujo_vivo_de_otra_version_de_la_cadena(db_session):
    """El alcance es ESTE documento, no la cadena de versiones.

    La otra puerta que mide "flujo vivo" —``_supersede_chain`` antes de anexar—
    sí mira la cadena entera, y hace bien: lo que va a marcar ``'Obsoleto'`` es
    la cadena. Aquí la pregunta es otra ("¿puedo sellar ESTA versión?") y copiar
    aquel alcance sería un cepo:

    * una versión solo se anexa si la cadena no tiene flujo vivo, así que por la
      app este estado no se alcanza (medido sobre la base real: 0 documentos
      startables con tareas de flujo vivas en otra versión de su cadena);
    * y si se alcanzara —una tarea huérfana sobre una versión superada—, el
      alcance de cadena dejaría la versión nueva imposible de sellar PARA
      SIEMPRE, porque la tarea que habría que cerrar cuelga de un documento que
      las dos listas ocultan (``is_current=False``) y al que no lleva ninguna
      pantalla.
    """
    flow = make_flow(db_session)
    raiz = make_document(db_session, status="Obsoleto", is_current=False)
    punta = make_document(db_session, status="Borrador", parent_id=raiz.id)
    db_session.add(AdhocTask(
        description="Aprobar Documento: huérfana", status="En Revisión",
        priority="Alta", document_id=raiz.id, flow_step_id=flow.steps[0].id,
    ))
    db_session.flush()

    SVC.start_flow(db_session, punta.id, flow.id, actor_id=None)

    db_session.refresh(punta)
    assert punta.status == "En Revisión"
    # Una tarea por paso, solo para la punta: la huérfana de la raíz no se toca.
    assert db_session.query(AdhocTask).filter_by(document_id=punta.id).count() == 2
    assert db_session.query(AdhocTask).filter_by(document_id=raiz.id).count() == 1


def test_start_flow_arranca_un_borrador_cuyas_tareas_ya_estan_cerradas(db_session):
    """No regresión: "flujo vivo" son DOS estatus, no "el documento tiene tareas".

    El guard nuevo mira ``'En Revisión'`` y ``'En Espera'``, que es la misma
    definición que usa el anexado de versión. Un borrador cuyo intento anterior
    acabó —aprobado o rechazado, que es como se cierra un flujo en el SGC— tiene
    tareas y no tiene flujo: sellarlo otra vez es exactamente lo que se espera
    del botón, y ensanchar el guard a "no tiene ninguna tarea" dejaría sin
    reintento a todo documento rechazado.
    """
    flow = make_flow(db_session)
    doc = make_document(db_session, status="Borrador")
    for step, estado in zip(flow.steps, ("Completada", "Rechazada")):
        db_session.add(AdhocTask(
            description=f"Aprobar Documento: {doc.title} (Paso: {step.name})",
            status=estado, priority="Alta",
            document_id=doc.id, flow_step_id=step.id,
        ))
    db_session.flush()

    SVC.start_flow(db_session, doc.id, flow.id, actor_id=None)

    db_session.refresh(doc)
    assert doc.status == "En Revisión"
    assert doc.flow_id == flow.id
    assert doc.current_step_id == flow.steps[0].id
    # Las dos viejas siguen ahí y se suma una por paso: el arranque no borra
    # historial, y por eso el guard tiene que mirar el ESTATUS y no el conteo.
    assert db_session.query(AdhocTask).filter_by(document_id=doc.id).count() == 4


def test_start_flow_por_http_contesta_409_sobre_un_borrador_con_flujo_vivo(
    app_client, db_session, auth_headers
):
    """El código de la frontera, fijado donde lo ve el navegador.

    El service habla en excepciones (``AdhocConflict``) y quien las traduce es
    el ``_domain_errors()`` de ``api/documents.py``. Es la mitad que le importa a
    ``documents-panel.js``: con A13 haciendo visibles los errores de Calidad, un
    409 con su frase pinta el aviso de "ya hay un flujo en curso", mientras que
    un 500 —o el 400 genérico que daba el guard viejo— deja al supervisor
    pulsando el sello sin saber por qué no pasa nada.

    El JWT es de admin, que bypasea ``require_perms``: aquí lo que se mide es el
    guard, no la autorización.
    """
    from itcj2.database import get_db

    app = app_client.app

    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    try:
        flow = make_flow(db_session)
        doc = make_document(db_session, flow_id=flow.id, status="Borrador")
        db_session.add(AdhocTask(
            description="Aprobar Documento: el que ya está en curso",
            status="En Revisión", priority="Alta",
            document_id=doc.id, flow_step_id=flow.steps[0].id,
        ))
        db_session.flush()

        res = app_client.post(
            f"/api/adhoc/v2/documents/{doc.id}/start-flow",
            json={"flow_id": flow.id},
            headers=auth_headers,
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert res.status_code == 409, res.text[:300]
    cuerpo = res.json()
    # Forma del error de la app: {"error": <string>, "status": N}. Nunca "detail".
    assert cuerpo["status"] == 409
    assert "en curso" in cuerpo["error"]
    assert "detail" not in cuerpo

    # Y no se creó nada: el 409 es un rechazo, no un arranque a medias.
    assert db_session.query(AdhocTask).filter_by(document_id=doc.id).count() == 1
    db_session.refresh(doc)
    assert doc.status == "Borrador"


@pytest.mark.parametrize("status", ["Obsoleto", "Aprobado"])
def test_start_flow_solo_arranca_desde_los_estados_startable(db_session, status):
    """``DOCUMENT_STATUSES_STARTABLE`` es 'Borrador' y 'Rechazado', y nada más.

    Hasta ahora esa tupla solo la respetaba el navegador
    (``documents-panel.js`` esconde el botón del sello en los demás estados);
    el servidor no la miraba. Con la cadena de versiones eso dejó de ser
    teórico: anexar deja la versión anterior en ``'Obsoleto'``, y un flujo
    arrancado sobre ella la devolvía a ``'En Revisión'`` con tareas nuevas para
    sus validadores —invisible en las dos listas, porque ``is_current`` sigue en
    ``false``—. ``'Aprobado'`` va en el mismo saco: un documento ya aprobado se
    revisa anexando una versión, no reabriendo su propio flujo.
    """
    flow = make_flow(db_session)
    doc = make_document(db_session, status=status)

    with pytest.raises(AdhocConflict) as exc:
        SVC.start_flow(db_session, doc.id, flow.id, actor_id=None)
    assert status in str(exc.value)

    db_session.refresh(doc)
    assert doc.status == status
    assert doc.flow_id is None
    assert db_session.query(AdhocTask).filter_by(document_id=doc.id).count() == 0


def test_start_flow_crea_una_tarea_por_paso_con_snapshot_de_validadores(db_session):
    flow = make_flow(db_session)
    u1, u2 = make_user(db_session, "a"), make_user(db_session, "b")
    SVC.set_step_validators(db_session, flow.steps[0].id, [u1.id])
    SVC.set_step_validators(db_session, flow.steps[1].id, [u2.id])

    autor = make_user(db_session, "autor")
    doc = make_document(db_session, author_id=autor.id, title="Manual de Calidad")

    result = SVC.start_flow(db_session, doc.id, flow.id, actor_id=autor.id)

    db_session.refresh(doc)
    assert doc.status == "En Revisión"
    assert doc.flow_id == flow.id
    assert doc.current_step_id == flow.steps[0].id

    tasks = db_session.query(AdhocTask).filter_by(document_id=doc.id).order_by(
        AdhocTask.flow_step_id
    ).all()
    assert len(tasks) == 2
    por_paso = {t.flow_step_id: t for t in tasks}
    assert por_paso[flow.steps[0].id].status == "En Revisión"
    assert por_paso[flow.steps[1].id].status == "En Espera"
    assert all(t.priority == "Alta" for t in tasks)
    assert all(t.created_by_id == autor.id for t in tasks)
    assert "Manual de Calidad" in por_paso[flow.steps[0].id].description
    assert [u.id for u in por_paso[flow.steps[0].id].assignees] == [u1.id]
    assert [u.id for u in por_paso[flow.steps[1].id].assignees] == [u2.id]

    assert result["document"].id == doc.id
    assert result["first_step"].id == flow.steps[0].id
    assert isinstance(result["email_sent"], bool)


def test_start_flow_es_fail_soft_ante_fallo_de_notificacion(db_session, monkeypatch):
    """Una notificación rota nunca debe tumbar el arranque del flujo."""
    from itcj2.apps.adhoc.services import document_flow_service as mod

    def _boom(*a, **kw):
        raise RuntimeError("redis caído")

    monkeypatch.setattr(mod.notify, "notify_flow_started", _boom)

    flow = make_flow(db_session)
    u1 = make_user(db_session, "a")
    SVC.set_step_validators(db_session, flow.steps[0].id, [u1.id])
    doc = make_document(db_session)

    SVC.start_flow(db_session, doc.id, flow.id, actor_id=None)
    db_session.refresh(doc)
    assert doc.status == "En Revisión"


# ==========================================================================
# advance_to_next_step
# ==========================================================================

def test_advance_to_next_step_mueve_el_documento_al_siguiente(db_session):
    flow = make_flow(db_session)
    doc = make_document(db_session, flow_id=flow.id, status="En Revisión",
                        current_step_id=flow.steps[0].id)
    nxt = SVC.advance_to_next_step(db_session, doc)
    assert nxt is not None and nxt.id == flow.steps[1].id
    assert doc.current_step_id == flow.steps[1].id
    assert doc.status == "En Revisión"


def test_advance_to_next_step_sin_siguiente_aprueba_el_documento(db_session):
    flow = make_flow(db_session)
    doc = make_document(db_session, flow_id=flow.id, status="En Revisión",
                        current_step_id=flow.steps[1].id)
    nxt = SVC.advance_to_next_step(db_session, doc)
    assert nxt is None
    assert doc.status == "Aprobado"
    assert doc.approval_date is not None


def test_advance_to_next_step_sin_paso_actual_es_conflicto(db_session):
    """El legacy reventaba con ``AttributeError`` → 500."""
    flow = make_flow(db_session)
    doc = make_document(db_session, flow_id=flow.id, status="En Revisión",
                        current_step_id=None)
    with pytest.raises(AdhocConflict):
        SVC.advance_to_next_step(db_session, doc)
