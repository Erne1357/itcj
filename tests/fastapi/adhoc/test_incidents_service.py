"""Tests de ``incident_service`` y de los schemas de incidencias.

Escritos ANTES del service (TDD, plan §9.1). Corren contra Postgres real vía la
fixture ``db_session`` de ``tests/fastapi/conftest.py`` (transacción con
SAVEPOINTs, rollback al final) en vez de con ``MagicMock``: tres de los cuatro
puntos críticos del dominio solo se pueden verificar contra la BD de verdad —
el ``CheckConstraint`` de ``status``, el ``NOT NULL`` de ``priority`` y el
``ON DELETE CASCADE`` de las tareas hijas. Con un mock, un service que escriba
``None`` en ``priority`` pasaría el test y reventaría en producción.

Regresiones del legacy cubiertas (``docs/adhoc/analysis/src_api.md`` §1.3):

* ``priority`` nunca llega ``None`` al ORM (el radio sin marcar mandaba ``None``).
* ``status`` fuera del vocabulario es 422, no ``IntegrityError`` a media tanda.
* Las tres fechas se guardan como ``date``, no como ``datetime``
  (``edit_incident`` hacía ``strptime`` sin ``.date()``).
* Un ``category_id`` inexistente aborta el lote **antes** de insertar nada, con
  un mensaje legible, en vez de un ``IntegrityError`` tragado por
  ``except Exception`` que devolvía un redirect "exitoso".
* Borrar una incidencia arrastra sus tareas (antes quedaban huérfanas).
* El alta masiva ya no cruza datos entre registros cuando las listas
  paralelas tienen longitudes distintas.
"""
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from itcj2.apps.adhoc.schemas.incidents import (
    IncidentBulkCreate,
    IncidentCreate,
    IncidentUpdate,
    serialize_incident,
)
from itcj2.apps.adhoc.services.incident_service import IncidentService


# ==========================================================================
# Fixtures locales (conftest.py de la app es compartido: no se toca)
# ==========================================================================

@pytest.fixture()
def catalogs(db_session):
    """Área, proceso y categoría de incidencia sobre los que colgar las FKs."""
    from itcj2.apps.adhoc.models.incidents import AdhocIncidentCategory
    from itcj2.apps.adhoc.models.structure import AdhocArea, AdhocProcess

    area = AdhocArea(name="e2e_area_incidencias")
    process = AdhocProcess(name="e2e_proceso_incidencias")
    category = AdhocIncidentCategory(name="e2e_cat_incidencias")
    db_session.add_all([area, process, category])
    db_session.flush()
    return {"area": area, "process": process, "category": category}


@pytest.fixture()
def responsible(db_session):
    from itcj2.core.models.role import Role
    from itcj2.core.models.user import User

    role = db_session.query(Role).filter_by(name="staff").first()
    if role is None:
        role = Role(name="staff")
        db_session.add(role)
        db_session.flush()
    user = User(first_name="ANA", last_name="RESPONSABLE", is_active=True, role_id=role.id)
    db_session.add(user)
    db_session.flush()
    return user


def _create(db, **kwargs):
    """Atajo: alta de una sola incidencia con los defaults del schema."""
    payload = {"title": "Incidencia de prueba"}
    payload.update(kwargs)
    return IncidentService.bulk_create(db, [IncidentCreate(**payload)])[0]


# ==========================================================================
# Schemas — vocabularios cerrados y coerciones (plan §2.8)
# ==========================================================================

def test_priority_none_se_resuelve_a_media():
    """El legacy mandaba ``None`` cuando el radio no estaba marcado."""
    assert IncidentCreate(title="X", priority=None).priority == "Media"


def test_priority_vacia_se_resuelve_a_media():
    assert IncidentCreate(title="X", priority="").priority == "Media"


def test_status_ausente_es_no_iniciada():
    assert IncidentCreate(title="X").status == "No Iniciada"


def test_status_none_se_resuelve_al_default():
    assert IncidentCreate(title="X", status=None).status == "No Iniciada"


@pytest.mark.parametrize("valor", ["Completado", "Abierto", "cerrada", "otro"])
def test_status_fuera_del_vocabulario_es_error_de_validacion(valor):
    """Los cuatro vocabularios en conflicto del legacy mueren aquí."""
    with pytest.raises(ValidationError):
        IncidentCreate(title="X", status=valor)


def test_priority_fuera_del_vocabulario_es_error_de_validacion():
    with pytest.raises(ValidationError):
        IncidentCreate(title="X", priority="Altisima")


def test_title_vacio_es_error_de_validacion():
    with pytest.raises(ValidationError):
        IncidentCreate(title="   ")


def test_fks_vacias_se_coaccionan_a_none():
    """El ``value=""`` del ``<option>`` placeholder no puede llegar a una FK."""
    inc = IncidentCreate(title="X", area_id="", category_id="", responsible_id="")
    assert (inc.area_id, inc.category_id, inc.responsible_id) == (None, None, None)


def test_fechas_vacias_se_coaccionan_a_none():
    inc = IncidentCreate(title="X", start_date="", commitment_date="", real_date="")
    assert (inc.start_date, inc.commitment_date, inc.real_date) == (None, None, None)


def test_fechas_se_parsean_como_date_no_datetime():
    inc = IncidentCreate(title="X", start_date="2026-03-01")
    assert inc.start_date == date(2026, 3, 1)
    assert not isinstance(inc.start_date, datetime)


def test_update_priority_vacia_no_deja_none_para_el_orm():
    """``priority`` es NOT NULL: un blanco explícito cae al default."""
    upd = IncidentUpdate(priority="")
    assert upd.priority == "Media"
    assert "priority" in upd.model_fields_set


def test_update_solo_marca_los_campos_enviados():
    upd = IncidentUpdate(title="Nuevo")
    assert upd.model_dump(exclude_unset=True) == {"title": "Nuevo"}


# --------------------------------------------------------------------------
# Alta masiva: listas paralelas del legacy
# --------------------------------------------------------------------------

def test_bulk_acepta_items():
    body = IncidentBulkCreate(items=[{"title": "A"}, {"title": "B"}])
    assert [i.title for i in body.items] == ["A", "B"]


def test_bulk_rechaza_lista_vacia():
    with pytest.raises(ValidationError):
        IncidentBulkCreate(items=[])


def test_bulk_adapta_listas_paralelas_del_legacy():
    body = IncidentBulkCreate(
        **{
            "titles[]": ["A", "B"],
            "priorities[]": ["Alta", ""],
            "statuses[]": ["Iniciada", "No Iniciada"],
            "area_ids[]": ["", ""],
        }
    )
    assert [i.title for i in body.items] == ["A", "B"]
    assert [i.priority for i in body.items] == ["Alta", "Media"]
    assert [i.status for i in body.items] == ["Iniciada", "No Iniciada"]
    assert all(i.area_id is None for i in body.items)


def test_bulk_listas_paralelas_descuadradas_es_error_explicito():
    """El legacy rellenaba con ``None`` fuera de rango y cruzaba los datos."""
    with pytest.raises(ValidationError) as exc:
        IncidentBulkCreate(**{"titles": ["A", "B", "C"], "priorities": ["Alta"]})
    assert "priority=1" in str(exc.value)


# ==========================================================================
# bulk_create
# ==========================================================================

def test_bulk_create_persiste_todas(db_session, catalogs, responsible):
    creadas = IncidentService.bulk_create(
        db_session,
        [
            IncidentCreate(
                title="Extintor vencido",
                folio="e2e-001",
                description="Recargar",
                start_date="2026-01-10",
                commitment_date="2026-01-20",
                priority="Alta",
                status="Iniciada",
                category_id=catalogs["category"].id,
                area_id=catalogs["area"].id,
                process_id=catalogs["process"].id,
                responsible_id=responsible.id,
            ),
            IncidentCreate(title="Señalización faltante"),
        ],
    )

    assert len(creadas) == 2
    assert all(i.id is not None for i in creadas)
    primera, segunda = creadas
    assert primera.folio == "e2e-001"
    assert primera.priority == "Alta"
    assert primera.status == "Iniciada"
    assert primera.responsible_id == responsible.id
    # Los defaults NOT NULL se materializan aunque el cliente no los mande.
    assert (segunda.priority, segunda.status) == ("Media", "No Iniciada")


def test_bulk_create_guarda_fechas_como_date(db_session):
    inc = _create(db_session, start_date="2026-02-01", commitment_date="2026-02-15",
                  real_date="2026-02-20")
    db_session.expire(inc)
    assert inc.start_date == date(2026, 2, 1)
    assert not isinstance(inc.start_date, datetime)
    assert not isinstance(inc.commitment_date, datetime)
    assert not isinstance(inc.real_date, datetime)


def test_bulk_create_rechaza_lote_vacio(db_session):
    with pytest.raises(ValueError):
        IncidentService.bulk_create(db_session, [])


def test_bulk_create_con_fk_inexistente_no_inserta_nada(db_session):
    from itcj2.apps.adhoc.models.incidents import AdhocIncident

    antes = db_session.query(AdhocIncident).count()
    with pytest.raises(ValueError) as exc:
        IncidentService.bulk_create(
            db_session,
            [IncidentCreate(title="ok"), IncidentCreate(title="mala", category_id=987654321)],
        )
    assert "987654321" in str(exc.value)
    assert db_session.query(AdhocIncident).count() == antes


def test_bulk_create_rechaza_responsable_inexistente(db_session):
    with pytest.raises(ValueError):
        IncidentService.bulk_create(
            db_session, [IncidentCreate(title="x", responsible_id=987654321)]
        )


# ==========================================================================
# list
# ==========================================================================

def test_list_pagina_y_reporta_total(db_session):
    for n in range(5):
        _create(db_session, title=f"e2e_list_{n}", folio=f"e2e_list_{n}")

    p = IncidentService.list(db_session, page=1, per_page=2, q="e2e_list_")
    assert p.total == 5
    assert p.pages == 3
    assert len(p.items) == 2

    p2 = IncidentService.list(db_session, page=3, per_page=2, q="e2e_list_")
    assert len(p2.items) == 1


def test_list_filtra_por_status_y_priority(db_session):
    _create(db_session, title="e2e_f_a", folio="e2e_f_a", status="Cerrada", priority="Alta")
    _create(db_session, title="e2e_f_b", folio="e2e_f_b", status="Iniciada", priority="Baja")

    p = IncidentService.list(db_session, q="e2e_f_", status="Cerrada")
    assert [i.folio for i in p.items] == ["e2e_f_a"]

    p = IncidentService.list(db_session, q="e2e_f_", priority="Baja")
    assert [i.folio for i in p.items] == ["e2e_f_b"]


def test_list_filtra_por_catalogos_y_responsable(db_session, catalogs, responsible):
    _create(db_session, title="e2e_c_1", folio="e2e_c_1", area_id=catalogs["area"].id,
            process_id=catalogs["process"].id, category_id=catalogs["category"].id,
            responsible_id=responsible.id)
    _create(db_session, title="e2e_c_2", folio="e2e_c_2")

    for kwargs in (
        {"area_id": catalogs["area"].id},
        {"process_id": catalogs["process"].id},
        {"category_id": catalogs["category"].id},
        {"responsible_id": responsible.id},
    ):
        p = IncidentService.list(db_session, q="e2e_c_", **kwargs)
        assert [i.folio for i in p.items] == ["e2e_c_1"], kwargs


def test_list_busca_en_folio_titulo_y_descripcion(db_session):
    _create(db_session, title="Fuga de agua", folio="e2e_q_folio")
    _create(db_session, title="e2e_q_titulo", folio="zzz")
    _create(db_session, title="otra", folio="yyy", description="e2e_q_desc")

    assert len(IncidentService.list(db_session, q="e2e_q_folio").items) == 1
    assert len(IncidentService.list(db_session, q="e2e_q_titulo").items) == 1
    assert len(IncidentService.list(db_session, q="e2e_q_desc").items) == 1


def test_list_filtra_por_rango_de_fechas(db_session):
    _create(db_session, title="e2e_d_1", folio="e2e_d_1", start_date="2026-01-01",
            commitment_date="2026-01-31")
    _create(db_session, title="e2e_d_2", folio="e2e_d_2", start_date="2026-06-01",
            commitment_date="2026-06-30")

    p = IncidentService.list(db_session, q="e2e_d_", start_from=date(2026, 5, 1))
    assert [i.folio for i in p.items] == ["e2e_d_2"]

    p = IncidentService.list(db_session, q="e2e_d_", start_to=date(2026, 3, 1))
    assert [i.folio for i in p.items] == ["e2e_d_1"]

    p = IncidentService.list(db_session, q="e2e_d_", commitment_to=date(2026, 2, 1))
    assert [i.folio for i in p.items] == ["e2e_d_1"]


def test_list_ordena_por_columna_permitida(db_session):
    _create(db_session, title="e2e_o_b", folio="e2e_o_b")
    _create(db_session, title="e2e_o_a", folio="e2e_o_a")

    asc = IncidentService.list(db_session, q="e2e_o_", order_by="title", order_dir="asc")
    assert [i.title for i in asc.items] == ["e2e_o_a", "e2e_o_b"]

    desc = IncidentService.list(db_session, q="e2e_o_", order_by="title", order_dir="desc")
    assert [i.title for i in desc.items] == ["e2e_o_b", "e2e_o_a"]


def test_list_rechaza_orden_no_permitido(db_session):
    with pytest.raises(ValueError):
        IncidentService.list(db_session, order_by="(select 1)")


# ==========================================================================
# task_counts
# ==========================================================================

def test_task_counts_agrupa_sin_n_mas_1(db_session):
    from itcj2.apps.adhoc.models.tasks import AdhocTask

    con_tareas = _create(db_session, title="e2e_tc_1")
    sin_tareas = _create(db_session, title="e2e_tc_2")
    db_session.add_all([
        AdhocTask(description="t1", incident_id=con_tareas.id),
        AdhocTask(description="t2", incident_id=con_tareas.id),
    ])
    db_session.flush()

    counts = IncidentService.task_counts(db_session, [con_tareas.id, sin_tareas.id])
    assert counts[con_tareas.id] == 2
    assert sin_tareas.id not in counts
    assert IncidentService.task_counts(db_session, []) == {}


# ==========================================================================
# update
# ==========================================================================

def test_update_aplica_solo_lo_enviado(db_session, catalogs):
    inc = _create(db_session, title="Original", folio="e2e_up", priority="Alta",
                  area_id=catalogs["area"].id)

    actualizada = IncidentService.update(db_session, inc.id, IncidentUpdate(title="Editada"))

    assert actualizada.title == "Editada"
    assert actualizada.folio == "e2e_up"          # no enviado -> intacto
    assert actualizada.priority == "Alta"         # no enviado -> intacto
    assert actualizada.area_id == catalogs["area"].id


def test_update_null_explicito_limpia_la_fk(db_session, catalogs):
    inc = _create(db_session, title="x", area_id=catalogs["area"].id)
    actualizada = IncidentService.update(db_session, inc.id, IncidentUpdate(area_id=None))
    assert actualizada.area_id is None


def test_update_priority_en_blanco_nunca_guarda_none(db_session):
    """Regresión directa de ``edit_incident``: ``priorities[1]`` -> ``None``."""
    inc = _create(db_session, title="x", priority="Alta")
    actualizada = IncidentService.update(db_session, inc.id, IncidentUpdate(priority=""))
    assert actualizada.priority == "Media"


def test_update_cambia_status_dentro_del_vocabulario(db_session):
    inc = _create(db_session, title="x")
    actualizada = IncidentService.update(db_session, inc.id, IncidentUpdate(status="Cerrada"))
    assert actualizada.status == "Cerrada"


def test_update_guarda_date_no_datetime(db_session):
    inc = _create(db_session, title="x")
    actualizada = IncidentService.update(
        db_session, inc.id, IncidentUpdate(real_date="2026-04-05")
    )
    db_session.expire(actualizada)
    assert actualizada.real_date == date(2026, 4, 5)
    assert not isinstance(actualizada.real_date, datetime)


def test_update_de_inexistente_devuelve_none(db_session):
    """El legacy convertía este 404 en un redirect 'exitoso'."""
    assert IncidentService.update(db_session, 987654321, IncidentUpdate(title="x")) is None


def test_update_con_fk_inexistente_lanza_y_no_muta(db_session):
    inc = _create(db_session, title="Intacta")
    with pytest.raises(ValueError):
        IncidentService.update(db_session, inc.id, IncidentUpdate(process_id=987654321))
    db_session.expire(inc)
    assert inc.title == "Intacta"
    assert inc.process_id is None


def test_update_sin_campos_devuelve_la_incidencia_sin_tocar(db_session):
    inc = _create(db_session, title="Igual")
    assert IncidentService.update(db_session, inc.id, IncidentUpdate()).title == "Igual"


# ==========================================================================
# delete
# ==========================================================================

def test_delete_borra_la_incidencia(db_session):
    from itcj2.apps.adhoc.models.incidents import AdhocIncident

    inc = _create(db_session, title="e2e_del")
    inc_id = inc.id
    assert IncidentService.delete(db_session, inc_id) is True
    assert db_session.get(AdhocIncident, inc_id) is None


def test_delete_cascadea_las_tareas_hijas(db_session, responsible):
    """``adhoc_tasks.incident_id`` es ``ON DELETE CASCADE``."""
    from itcj2.apps.adhoc.models.tasks import AdhocTask, AdhocTaskComment

    inc = _create(db_session, title="e2e_del_cascade")
    tarea = AdhocTask(description="revisar", incident_id=inc.id)
    db_session.add(tarea)
    db_session.flush()
    db_session.add(AdhocTaskComment(task_id=tarea.id, user_id=responsible.id, comment="hola"))
    db_session.flush()
    tarea_id = tarea.id

    assert IncidentService.delete(db_session, inc.id) is True

    # El CASCADE ocurre en Postgres, no en el ORM: sin expirar el identity map
    # `Session.get()` devolvería el objeto cacheado sin ir a la BD.
    db_session.expire_all()
    assert db_session.get(AdhocTask, tarea_id) is None
    assert (
        db_session.query(AdhocTaskComment).filter_by(task_id=tarea_id).count() == 0
    )


def test_delete_de_inexistente_devuelve_false(db_session):
    assert IncidentService.delete(db_session, 987654321) is False


# ==========================================================================
# Serialización
# ==========================================================================

def test_serialize_incluye_catalogos_anidados_y_fechas_iso(db_session, catalogs, responsible):
    inc = _create(
        db_session,
        title="Serializable",
        start_date="2026-05-05",
        area_id=catalogs["area"].id,
        process_id=catalogs["process"].id,
        category_id=catalogs["category"].id,
        responsible_id=responsible.id,
    )

    data = serialize_incident(inc, task_count=3)

    assert data["title"] == "Serializable"
    assert data["start_date"] == "2026-05-05"
    assert data["area"]["name"] == "e2e_area_incidencias"
    assert data["process"]["name"] == "e2e_proceso_incidencias"
    assert data["category"]["name"] == "e2e_cat_incidencias"
    assert data["responsible"]["full_name"] == "RESPONSABLE ANA"
    assert data["task_count"] == 3


def test_serialize_sin_catalogos_deja_nulos(db_session):
    data = serialize_incident(_create(db_session, title="Pelada"))
    assert data["area"] is None and data["responsible"] is None
    assert data["task_count"] == 0
