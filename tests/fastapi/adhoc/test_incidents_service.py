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
from io import BytesIO

import pytest
from pydantic import ValidationError

from itcj2.apps.adhoc.schemas.incidents import (
    IncidentBulkCreate,
    IncidentCreate,
    IncidentUpdate,
    file_to_dict,
    serialize_incident,
)
from itcj2.apps.adhoc.services import upload_service
from itcj2.apps.adhoc.services.incident_service import (
    IncidentFileNotFound,
    IncidentNotFound,
    IncidentService,
)


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


def test_update_title_vacio_lanza_valueerror_y_no_deja_none_para_el_orm(db_session):
    """D2: ``title`` es NOT NULL. El ``""`` del cliente llega como ``None`` al
    service (coaccionado por el schema); a diferencia de ``priority``/``status``
    no tiene un default razonable, así que se rechaza en vez de escribir NULL
    y reventar con ``IntegrityError`` (500 sin traducir)."""
    inc = _create(db_session, title="Original")

    with pytest.raises(ValueError):
        IncidentService.update(db_session, inc.id, IncidentUpdate(title=""))

    db_session.expire(inc)
    assert inc.title == "Original"


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


# ==========================================================================
# Adjuntos (351 filas migradas del SGC legacy, sin service hasta ahora)
# ==========================================================================
#
# Espejo de ``test_programs_service.py`` para el circuito de archivos. Única
# diferencia real: ``AdhocIncidentFile.file_path`` es NULLABLE (51 de los 351
# adjuntos migrados no tienen binario en el servidor del proveedor), así que
# aquí se cubre también el camino "registro sin archivo" -> 404 legible.

class _FakeSettings:
    def __init__(self, root):
        self.ADHOC_UPLOAD_PATH = str(root)
        self.ADHOC_MAX_FILE_SIZE = 1024 * 1024
        self.ADHOC_ALLOWED_EXTENSIONS = "pdf,png,txt"


class _FakeUpload:
    """Duck-type de ``fastapi.UploadFile``."""

    def __init__(self, filename, content=b"contenido", content_type="application/pdf"):
        self.filename = filename
        self.content_type = content_type
        self.file = BytesIO(content)


@pytest.fixture()
def uploads_root(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_service, "_settings", lambda: _FakeSettings(tmp_path))
    return tmp_path


def _sin_binario(db, incident_id, *, original_name="NOTIFICACION VR-01"):
    """Un adjunto migrado sin archivo: ``file_path`` es ``NULL`` a propósito."""
    from itcj2.apps.adhoc.models.incidents import AdhocIncidentFile

    row = AdhocIncidentFile(
        incident_id=incident_id, file_path=None, original_name=original_name,
    )
    db.add(row)
    db.flush()
    return row


def test_add_files_y_list_files(db_session, uploads_root):
    inc = _create(db_session, title="Con adjuntos")

    saved = IncidentService.add_files(
        db_session, inc.id, [_FakeUpload("evidencia.pdf")], uploaded_by_id=None
    )

    assert len(saved) == 1
    assert saved[0].original_name == "evidencia.pdf"
    assert saved[0].size_bytes > 0
    assert [f.id for f in IncidentService.list_files(db_session, inc.id)] == [saved[0].id]


def test_list_files_incluye_los_registros_sin_binario(db_session):
    inc = _create(db_session, title="Con huecos")
    huerfano = _sin_binario(db_session, inc.id)

    filas = IncidentService.list_files(db_session, inc.id)

    assert [f.id for f in filas] == [huerfano.id]
    assert filas[0].file_path is None


def test_list_files_de_incidencia_inexistente_lanza_incident_not_found(db_session):
    with pytest.raises(IncidentNotFound):
        IncidentService.list_files(db_session, 99_999_999)


def test_add_files_a_incidencia_inexistente_lanza_incident_not_found(db_session, uploads_root):
    with pytest.raises(IncidentNotFound):
        IncidentService.add_files(
            db_session, 99_999_999, [_FakeUpload("x.pdf")], uploaded_by_id=None
        )


def test_add_files_sin_archivos_lanza_value_error(db_session, uploads_root):
    inc = _create(db_session, title="Sin archivos")
    with pytest.raises(ValueError):
        IncidentService.add_files(db_session, inc.id, [], uploaded_by_id=None)


def test_add_files_rechaza_extension_no_permitida_sin_dejar_rastro(db_session, uploads_root):
    inc = _create(db_session, title="Extension mala")

    with pytest.raises(ValueError):
        IncidentService.add_files(
            db_session, inc.id, [_FakeUpload("shell.php", content_type="application/x-php")],
            uploaded_by_id=None,
        )

    assert IncidentService.list_files(db_session, inc.id) == []


def test_get_file_inexistente_lanza_incident_file_not_found(db_session):
    with pytest.raises(IncidentFileNotFound):
        IncidentService.get_file(db_session, 99_999_999)


def test_open_file_devuelve_la_ruta_absoluta_verificada(db_session, uploads_root):
    inc = _create(db_session, title="Descargable")
    saved = IncidentService.add_files(
        db_session, inc.id, [_FakeUpload("plan.pdf")], uploaded_by_id=None
    )[0]

    path = IncidentService.open_file(saved)

    assert path.is_file()
    assert path.name == "plan.pdf"


def test_open_file_sin_binario_lanza_incident_file_not_found(db_session):
    """51 de los 351 adjuntos migrados no tienen archivo en el proveedor."""
    inc = _create(db_session, title="Sin binario")
    huerfano = _sin_binario(db_session, inc.id)

    with pytest.raises(IncidentFileNotFound):
        IncidentService.open_file(huerfano)


def test_delete_file_borra_la_fila_y_el_archivo(db_session, uploads_root):
    inc = _create(db_session, title="Borrable")
    saved = IncidentService.add_files(
        db_session, inc.id, [_FakeUpload("plan.pdf")], uploaded_by_id=None
    )[0]
    on_disk = upload_service.open_stored("incidents", saved.file_path)
    file_id = saved.id

    IncidentService.delete_file(db_session, file_id)

    from itcj2.apps.adhoc.models.incidents import AdhocIncidentFile

    assert db_session.get(AdhocIncidentFile, file_id) is None
    assert not on_disk.exists()


def test_delete_file_sin_binario_solo_borra_la_fila(db_session):
    """Un registro migrado sin archivo no debe reventar al borrarse."""
    from itcj2.apps.adhoc.models.incidents import AdhocIncidentFile

    inc = _create(db_session, title="Borrable sin binario")
    huerfano = _sin_binario(db_session, inc.id)
    file_id = huerfano.id

    IncidentService.delete_file(db_session, file_id)

    assert db_session.get(AdhocIncidentFile, file_id) is None


def test_delete_file_inexistente_lanza_incident_file_not_found(db_session):
    with pytest.raises(IncidentFileNotFound):
        IncidentService.delete_file(db_session, 99_999_999)


def test_file_to_dict_marca_is_available_segun_el_binario(db_session):
    inc = _create(db_session, title="Serializable con adjuntos")

    from itcj2.apps.adhoc.models.incidents import AdhocIncidentFile

    con_archivo = AdhocIncidentFile(
        incident_id=inc.id, file_path="1/plan.pdf", original_name="plan.pdf",
    )
    sin_archivo = _sin_binario(db_session, inc.id, original_name="NOTIFICACION VR-01")
    db_session.add(con_archivo)
    db_session.flush()

    assert file_to_dict(con_archivo)["is_available"] is True
    assert file_to_dict(sin_archivo)["is_available"] is False
    assert file_to_dict(sin_archivo)["original_name"] == "NOTIFICACION VR-01"


# ==========================================================================
# A22/A23 — borrar la incidencia también limpia el disco
#
# `adhoc_incident_files` cae por el CASCADE de Postgres, pero los binarios de
# `instance/apps/adhoc/incidents/{id}/` sobrevivían a la incidencia y quedaban
# huérfanos para siempre: es el mismo bug #18 que `program_event_service` ya
# arreglaba para los eventos de programa. Los 11 huérfanos que quedan hoy en
# disco no se tocan; lo que se arregla es que no se generen más.
#
# El orden es la mitad importante del arreglo, y por eso el test que manda aquí
# es el del commit fallido: si el disco se limpiara ANTES del commit, una
# transacción que no cuaja deja la fila viva apuntando a un binario que ya no
# existe. Eso es peor que el huérfano —el expediente ISO se queda sin su
# evidencia y la UI sigue ofreciendo la descarga—, así que el caso feliz no
# basta para demostrar que está bien hecho.
#
# Estos tests van al final del bloque de adjuntos porque necesitan
# `uploads_root` y `_FakeUpload`, que se declaran ahí arriba.
# ==========================================================================

def test_delete_borra_los_binarios_y_el_directorio(db_session, uploads_root):
    inc = _create(db_session, title="Con evidencia")
    guardado = IncidentService.add_files(
        db_session, inc.id, [_FakeUpload("evidencia.pdf")], uploaded_by_id=None
    )[0]
    en_disco = upload_service.open_stored("incidents", guardado.file_path)
    directorio = en_disco.parent
    assert en_disco.is_file()

    assert IncidentService.delete(db_session, inc.id) is True

    assert not en_disco.exists()
    assert not directorio.exists()


def test_delete_no_toca_el_disco_si_el_commit_falla(db_session, uploads_root, monkeypatch):
    """**El caso que justifica el orden.** Si el commit revienta, los ficheros
    tienen que seguir donde estaban: la fila sigue viva y su evidencia también.

    Es lo único que distingue "borra el disco después de commitear" de "borra el
    disco y luego commitea", que en el camino feliz se ven idénticos.
    """
    inc = _create(db_session, title="Commit fallido")
    guardado = IncidentService.add_files(
        db_session, inc.id, [_FakeUpload("evidencia.pdf")], uploaded_by_id=None
    )[0]
    en_disco = upload_service.open_stored("incidents", guardado.file_path)
    directorio = en_disco.parent

    def _revienta():
        raise RuntimeError("la transacción no cuajó")

    monkeypatch.setattr(db_session, "commit", _revienta)

    with pytest.raises(RuntimeError):
        IncidentService.delete(db_session, inc.id)

    assert en_disco.is_file(), "el binario se borró antes de que la BD confirmara"
    assert directorio.is_dir()


def test_delete_de_una_incidencia_sin_archivos_no_revienta(db_session, uploads_root):
    """El caso mayoritario: ni fila de adjunto ni directorio en disco.

    `resolve_dir` devuelve una ruta que no existe y el borrado no puede
    tropezar con ella.
    """
    inc = _create(db_session, title="Sin adjuntos")
    directorio = upload_service.resolve_dir("incidents", inc.id)
    assert not directorio.exists()

    assert IncidentService.delete(db_session, inc.id) is True


def test_delete_tolera_el_adjunto_migrado_sin_binario(db_session, uploads_root):
    """51 de los 351 adjuntos del SGC llegaron con ``file_path`` NULL.

    Sus filas caen con el CASCADE; el borrado del disco tiene que saltárselas
    en vez de intentar resolver una ruta que no existe.
    """
    inc = _create(db_session, title="Con hueco")
    _sin_binario(db_session, inc.id)

    assert IncidentService.delete(db_session, inc.id) is True


def test_delete_conserva_un_fichero_que_no_tiene_fila(db_session, uploads_root):
    """Un binario sin registro —el ETL a medias, una subida interrumpida— se
    queda, y con él su directorio. Perder evidencia de una auditoría ISO es más
    caro que dejar un huérfano en disco, así que el ``rmdir`` solo entra si el
    directorio quedó vacío."""
    inc = _create(db_session, title="Con intruso")
    guardado = IncidentService.add_files(
        db_session, inc.id, [_FakeUpload("evidencia.pdf")], uploaded_by_id=None
    )[0]
    en_disco = upload_service.open_stored("incidents", guardado.file_path)
    directorio = en_disco.parent
    intruso = directorio / "sin_fila.pdf"
    intruso.write_bytes(b"reliquia del ETL")

    assert IncidentService.delete(db_session, inc.id) is True

    assert not en_disco.exists()          # lo que sí tenía fila, fuera
    assert intruso.is_file()              # lo que no, se queda
    assert directorio.is_dir()


def test_delete_de_inexistente_no_toca_nada_del_disco(db_session, uploads_root):
    """El contrato de ``False`` es anterior a todo esto y no cambia."""
    assert IncidentService.delete(db_session, 987_654_321) is False
