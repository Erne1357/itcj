"""
Tests de contrato para los 26 modelos de `itcj2.apps.sgi.sgc.models`.

Introspección sobre `__table__` (no requiere BD): nombres de tabla exactos,
BigInteger en toda FK a `core_users`, índice en toda columna FK, vocabularios
cerrados de los CheckConstraint, UniqueConstraint y nullability tal como los
especifica `docs/sgi/sgc/PLAN_MIGRACION_SGC.md` §2. Debe fallar si alguien
cambia el esquema sin actualizar el plan.
"""
from sqlalchemy import BigInteger, CheckConstraint, Column, Date, DateTime, Table, UniqueConstraint

from itcj2.apps.sgi.sgc.models import (
    SgcApprovalFlow,
    SgcApprovalFlowStep,
    SgcArea,
    SgcDocument,
    SgcDocumentAcknowledgement,
    SgcDocumentCategory,
    SgcDocumentClassification,
    SgcDocumentVisibility,
    SgcIncident,
    SgcIncidentCategory,
    SgcIncidentFile,
    SgcIndicator,
    SgcIndicatorTracking,
    SgcIndicatorYear,
    SgcMailConfig,
    SgcProcess,
    SgcProgramCategory,
    SgcProgramEvent,
    SgcProgramEventFile,
    SgcTask,
    SgcTaskApproval,
    SgcTaskComment,
    SgcTaskCommentFile,
    sgc_flow_step_assignees,
    sgc_task_assignees,
    sgc_user_areas,
)


# Las 23 clases mapeadas (entidad + catálogo + singleton).
MAPPED_MODELS = [
    SgcArea, SgcProcess,
    SgcIndicatorYear, SgcIndicator, SgcIndicatorTracking,
    SgcMailConfig,
    SgcDocumentCategory, SgcDocumentClassification,
    SgcApprovalFlow, SgcApprovalFlowStep, SgcDocument,
    SgcDocumentAcknowledgement, SgcDocumentVisibility,
    SgcIncidentCategory, SgcIncident, SgcIncidentFile,
    SgcProgramCategory, SgcProgramEvent, SgcProgramEventFile,
    SgcTask, SgcTaskComment, SgcTaskCommentFile, SgcTaskApproval,
]

# Las 3 tablas de asociación puras (sqlalchemy.Table, sin clase mapeada).
ASSOC_TABLES = [sgc_user_areas, sgc_flow_step_assignees, sgc_task_assignees]

ALL_TABLES = [m.__table__ for m in MAPPED_MODELS] + ASSOC_TABLES

EXPECTED_TABLENAMES = {
    "SgcArea": "sgc_areas",
    "SgcProcess": "sgc_processes",
    "SgcIndicatorYear": "sgc_indicator_years",
    "SgcIndicator": "sgc_indicators",
    "SgcIndicatorTracking": "sgc_indicator_trackings",
    "SgcMailConfig": "sgc_mail_config",
    "SgcDocumentCategory": "sgc_document_categories",
    "SgcDocumentClassification": "sgc_document_classifications",
    "SgcApprovalFlow": "sgc_approval_flows",
    "SgcApprovalFlowStep": "sgc_approval_flow_steps",
    "SgcDocument": "sgc_documents",
    "SgcDocumentAcknowledgement": "sgc_document_acknowledgements",
    "SgcDocumentVisibility": "sgc_document_visibility",
    "SgcIncidentCategory": "sgc_incident_categories",
    "SgcIncident": "sgc_incidents",
    "SgcIncidentFile": "sgc_incident_files",
    "SgcProgramCategory": "sgc_program_categories",
    "SgcProgramEvent": "sgc_program_events",
    "SgcProgramEventFile": "sgc_program_event_files",
    "SgcTask": "sgc_tasks",
    "SgcTaskComment": "sgc_task_comments",
    "SgcTaskCommentFile": "sgc_task_comment_files",
    "SgcTaskApproval": "sgc_task_approvals",
}

EXPECTED_ASSOC_TABLENAMES = {
    "sgc_user_areas", "sgc_flow_step_assignees", "sgc_task_assignees",
}


def _is_indexed(table: Table, colname: str) -> bool:
    """True si la columna está cubierta por algún índice: index=True en la
    Column, parte de la PK (btree de la PK indexa su columna líder), o un
    Index() explícito a nivel de tabla (como el de la columna trasera de las
    tablas de asociación)."""
    col: Column = table.columns[colname]
    if col.primary_key or col.index:
        return True
    for ix in table.indexes:
        if colname in [c.name for c in ix.columns]:
            return True
    return False


def _check_constraints(table: Table) -> list[CheckConstraint]:
    return [c for c in table.constraints if isinstance(c, CheckConstraint)]


def _unique_constraints(table: Table) -> list[UniqueConstraint]:
    return [c for c in table.constraints if isinstance(c, UniqueConstraint)]


# ─────────────────────────────────────────────────────────────────────────
# 1. Las 26 tablas existen con el nombre exacto
# ─────────────────────────────────────────────────────────────────────────

def test_26_tables_total():
    # 22 originales + las 4 de la migracion del SGC legacy:
    # acuses, visibilidad, archivos de incidencia y archivos de comentario.
    assert len(MAPPED_MODELS) + len(ASSOC_TABLES) == 26


def test_tablenames_exact():
    for model in MAPPED_MODELS:
        expected = EXPECTED_TABLENAMES[model.__name__]
        assert model.__tablename__ == expected
        assert model.__table__.name == expected


def test_assoc_tablenames_exact():
    names = {t.name for t in ASSOC_TABLES}
    assert names == EXPECTED_ASSOC_TABLENAMES


def test_no_tablename_collides_with_other_apps():
    """sgc_* no debe colisionar con tablas de otras apps ya registradas."""
    import itcj2.models  # noqa: F401
    base = MAPPED_MODELS[0].__table__.metadata
    sgc_names = {t.name for t in ALL_TABLES}
    other_names = {name for name in base.tables if not name.startswith("sgc_")}
    assert sgc_names.isdisjoint(other_names)


# ─────────────────────────────────────────────────────────────────────────
# 2. Toda FK a core_users es BigInteger
# ─────────────────────────────────────────────────────────────────────────

def test_all_core_users_fks_are_biginteger():
    checked = 0
    for table in ALL_TABLES:
        for col in table.columns:
            for fk in col.foreign_keys:
                if fk.target_fullname == "core_users.id":
                    assert isinstance(col.type, BigInteger), (
                        f"{table.name}.{col.name} referencia core_users.id "
                        f"pero es {col.type!r}, no BigInteger"
                    )
                    checked += 1
    # 14 FKs a core_users en total: user_areas.user_id, flow_step_assignees.user_id,
    # documents.author_id, incidents.responsible_id, program_events.responsible_id,
    # program_event_files.uploaded_by_id, tasks.created_by_id, task_assignees.user_id,
    # task_comments.user_id, task_approvals.user_id, y las 4 de la migracion del
    # SGC legacy: document_acknowledgements.user_id, document_visibility.user_id,
    # incident_files.uploaded_by_id, task_comment_files.uploaded_by_id.
    assert checked == 14


# ─────────────────────────────────────────────────────────────────────────
# 3. Toda columna FK tiene índice (Column(index=True), PK, o Index() de tabla)
# ─────────────────────────────────────────────────────────────────────────

def test_all_fk_columns_are_indexed():
    offenders = []
    for table in ALL_TABLES:
        for col in table.columns:
            if col.foreign_keys and not _is_indexed(table, col.name):
                offenders.append(f"{table.name}.{col.name}")
    assert not offenders, f"Columnas FK sin índice: {offenders}"


# ─────────────────────────────────────────────────────────────────────────
# 4. CheckConstraint — vocabularios cerrados exactos del plan §2
# ─────────────────────────────────────────────────────────────────────────

def _assert_check_contains(table: Table, *values: str):
    texts = " | ".join(str(c.sqltext) for c in _check_constraints(table))
    for v in values:
        assert f"'{v}'" in texts, f"{table.name}: falta '{v}' en sus CheckConstraint ({texts!r})"


def test_indicator_frequency_vocabulary():
    _assert_check_contains(SgcIndicator.__table__, "Semanal", "Mensual", "Anual")


def test_indicator_tracking_color_vocabulary():
    _assert_check_contains(SgcIndicatorTracking.__table__, "blanco", "rojo", "amarillo", "verde")


def test_document_status_vocabulary():
    # 'Obsoleto' = versión superada por otra más nueva de la misma cadena.
    # Lo trajo la migración del SGC legacy, donde 59 de 206 documentos lo son.
    _assert_check_contains(
        SgcDocument.__table__,
        "Borrador", "En Revisión", "Aprobado", "Rechazado", "Obsoleto",
    )


def test_document_status_vocabulary_matches_constants():
    """El CheckConstraint y `DOCUMENT_STATUSES` no pueden divergir."""
    from itcj2.apps.sgi.sgc.utils.constants import DOCUMENT_STATUSES
    texts = " | ".join(
        str(c.sqltext) for c in _check_constraints(SgcDocument.__table__)
    )
    for value in DOCUMENT_STATUSES:
        assert f"'{value}'" in texts, f"falta '{value}' en ck_sgc_documents_status"


def test_document_version_chain_columns():
    """`parent_id` sin ondelete (RESTRICT) e `is_current` indexado."""
    cols = SgcDocument.__table__.columns
    assert cols["parent_id"].nullable is True
    assert cols["is_current"].nullable is False
    assert _is_indexed(SgcDocument.__table__, "is_current")
    fk = next(iter(cols["parent_id"].foreign_keys))
    assert fk.target_fullname == "sgc_documents.id"
    # Sin ondelete a propósito: borrar la raíz de una cadena con versiones
    # colgando debe fallar, no dejar huérfanos.
    assert fk.ondelete is None


def test_acknowledgement_requires_a_real_date():
    """Una tabla de acuses con fechas vacías no sostiene una auditoría ISO."""
    cols = SgcDocumentAcknowledgement.__table__.columns
    assert cols["acknowledged_at"].nullable is False
    uniques = {
        tuple(c.name for c in u.columns)
        for u in _unique_constraints(SgcDocumentAcknowledgement.__table__)
    }
    assert ("document_id", "user_id") in uniques


def test_visibility_is_separate_from_acknowledgements():
    """`ver_doctos` del legacy es visibilidad, no acuse: tablas distintas."""
    assert SgcDocumentVisibility.__tablename__ != SgcDocumentAcknowledgement.__tablename__
    assert "acknowledged_at" not in SgcDocumentVisibility.__table__.columns


def test_legacy_file_paths_are_nullable():
    """Hay adjuntos del legacy que existen como registro sin binario en el servidor."""
    for model in (SgcIncidentFile, SgcTaskCommentFile, SgcProgramEventFile):
        cols = model.__table__.columns
        assert cols["file_path"].nullable is True, model.__name__
        assert cols["original_name"].nullable is False, model.__name__


def test_legacy_id_columns_are_unique():
    """`legacy_id` da idempotencia al ETL: sin UNIQUE no sirve para nada."""
    expected = {
        "sgc_areas", "sgc_processes", "sgc_approval_flows", "sgc_documents",
        "sgc_incidents", "sgc_program_events", "sgc_indicators", "sgc_tasks",
    }
    found = set()
    for table in ALL_TABLES:
        if "legacy_id" in table.columns:
            assert table.columns["legacy_id"].unique is True, table.name
            found.add(table.name)
    assert found == expected


def test_incident_status_and_priority_vocabulary():
    _assert_check_contains(SgcIncident.__table__, "No Iniciada", "Iniciada", "Cerrada")
    _assert_check_contains(SgcIncident.__table__, "Baja", "Media", "Alta", "Urgente")
    # El default 'Abierto' del legacy y el 'Completado' del workflow quedan fuera.
    texts = " | ".join(str(c.sqltext) for c in _check_constraints(SgcIncident.__table__))
    assert "'Abierto'" not in texts
    assert "'Completado'" not in texts


def test_program_event_status_and_priority_vocabulary():
    _assert_check_contains(SgcProgramEvent.__table__, "Planeado", "En Proceso", "Completado")
    _assert_check_contains(SgcProgramEvent.__table__, "Baja", "Media", "Alta", "Urgente")


def test_task_status_and_priority_vocabulary():
    _assert_check_contains(
        SgcTask.__table__,
        "Pendiente", "En Proceso", "En Revisión", "En Espera", "Completada", "Rechazada",
    )
    _assert_check_contains(SgcTask.__table__, "Baja", "Media", "Alta", "Urgente")


def test_task_approval_decision_vocabulary():
    _assert_check_contains(SgcTaskApproval.__table__, "aprobado", "rechazado")


def test_task_single_parent_check_constraint_present():
    texts = " | ".join(str(c.sqltext) for c in _check_constraints(SgcTask.__table__))
    assert "incident_id" in texts and "program_id" in texts and "document_id" in texts
    assert "= 1" in texts


def test_mail_config_singleton_check_constraint():
    texts = " | ".join(str(c.sqltext) for c in _check_constraints(SgcMailConfig.__table__))
    assert "id = 1" in texts


# ─────────────────────────────────────────────────────────────────────────
# 5. UniqueConstraint / unique=True
# ─────────────────────────────────────────────────────────────────────────

def test_indicator_tracking_unique_indicator_period():
    ucs = _unique_constraints(SgcIndicatorTracking.__table__)
    cols = [{c.name for c in uc.columns} for uc in ucs]
    assert {"indicator_id", "period_index"} in cols


def test_approval_flow_step_unique_flow_order():
    ucs = _unique_constraints(SgcApprovalFlowStep.__table__)
    cols = [{c.name for c in uc.columns} for uc in ucs]
    assert {"flow_id", "step_order"} in cols


def test_task_approval_unique_task_user():
    ucs = _unique_constraints(SgcTaskApproval.__table__)
    cols = [{c.name for c in uc.columns} for uc in ucs]
    assert {"task_id", "user_id"} in cols


def test_unique_name_catalogs():
    for model in (
        SgcArea, SgcProcess, SgcDocumentCategory, SgcDocumentClassification,
        SgcIncidentCategory, SgcProgramCategory,
    ):
        assert model.__table__.columns["name"].unique is True, f"{model.__name__}.name debe ser unique"
    assert SgcIndicatorYear.__table__.columns["year"].unique is True


# ─────────────────────────────────────────────────────────────────────────
# 6. Nullability (§2 del plan, spot checks obligatorios)
# ─────────────────────────────────────────────────────────────────────────

def test_area_columns():
    cols = SgcArea.__table__.columns
    assert cols["name"].nullable is False
    assert cols["color"].nullable is False
    assert cols["is_active"].nullable is False
    assert cols["is_active"].index is True


def test_process_columns():
    cols = SgcProcess.__table__.columns
    assert cols["name"].nullable is False
    assert cols["color"].nullable is False   # columna REAL, no @property
    assert cols["description"].nullable is True


def test_indicator_columns():
    cols = SgcIndicator.__table__.columns
    assert cols["year_id"].nullable is False
    assert cols["process_id"].nullable is False
    assert cols["frequency"].nullable is True   # el legacy escribe '' -> NULL
    assert cols["responsible"].nullable is True
    assert cols["facilitator"].nullable is True
    # 4 columnas de umbral, no un planned_value concatenado
    for name in ("planned_white", "planned_red", "planned_yellow", "planned_green"):
        assert name in cols
    assert "planned_value" not in cols


def test_indicator_tracking_columns():
    cols = SgcIndicatorTracking.__table__.columns
    assert cols["indicator_id"].nullable is False
    assert cols["period_index"].nullable is False
    assert cols["color"].nullable is False


def test_mail_config_columns():
    cols = SgcMailConfig.__table__.columns
    assert cols["is_enabled"].nullable is False
    assert "sender_name" not in cols
    assert "sender_email" not in cols
    assert "created_at" not in cols   # solo updated_at (singleton sembrado por DML)
    assert "updated_at" in cols


def test_document_columns():
    cols = SgcDocument.__table__.columns
    assert cols["title"].nullable is False
    assert cols["code"].nullable is True
    assert cols["author_id"].nullable is True
    assert isinstance(cols["approval_date"].type, DateTime)   # NO Date (bug del legacy)
    for fk_col in ("category_id", "area_id", "process_id", "classification_id",
                    "flow_id", "current_step_id"):
        assert cols[fk_col].nullable is True


def test_approval_flow_step_flow_id_not_null():
    # El legacy lo tenía nullable: un paso sin flujo es basura.
    assert SgcApprovalFlowStep.__table__.columns["flow_id"].nullable is False


def test_incident_and_program_event_dates_are_date_type():
    for model in (SgcIncident, SgcProgramEvent):
        cols = model.__table__.columns
        for name in ("start_date", "commitment_date", "real_date"):
            assert isinstance(cols[name].type, Date), (
                f"{model.__name__}.{name} debe ser Date, es {cols[name].type!r}"
            )
            assert not isinstance(cols[name].type, DateTime)


def test_incident_status_and_priority_defaults():
    cols = SgcIncident.__table__.columns
    assert cols["status"].nullable is False
    assert cols["priority"].nullable is False
    assert str(cols["status"].server_default.arg) == "'No Iniciada'"


def test_program_event_status_default():
    cols = SgcProgramEvent.__table__.columns
    assert cols["status"].nullable is False
    assert str(cols["status"].server_default.arg) == "'Planeado'"


def test_task_columns():
    cols = SgcTask.__table__.columns
    assert cols["description"].nullable is False
    assert cols["status"].nullable is False
    assert cols["priority"].nullable is False
    for fk_col in ("incident_id", "program_id", "document_id", "flow_step_id"):
        assert cols[fk_col].nullable is True


def test_task_assignees_no_is_completed():
    assert "is_completed" not in sgc_task_assignees.columns
    assert "notified_overdue" in sgc_task_assignees.columns
    assert sgc_task_assignees.columns["notified_overdue"].nullable is False


def test_flow_step_assignees_notify_on_overdue():
    cols = sgc_flow_step_assignees.columns
    assert cols["notify_on_overdue"].nullable is False


def test_task_comment_columns():
    cols = SgcTaskComment.__table__.columns
    assert cols["task_id"].nullable is False
    assert cols["user_id"].nullable is False
    assert cols["comment"].nullable is False
    assert cols["file_path"].nullable is True
    assert "updated_at" not in cols   # inmutable: se crea y se borra


def test_task_approval_columns():
    cols = SgcTaskApproval.__table__.columns
    assert cols["task_id"].nullable is False
    assert cols["user_id"].nullable is False
    assert cols["decision"].nullable is False
    assert "updated_at" not in cols   # inmutable


def test_program_event_file_columns():
    cols = SgcProgramEventFile.__table__.columns
    assert cols["event_id"].nullable is False
    # `file_path` es nullable desde la migración del SGC legacy: hay adjuntos
    # cuyo registro existe pero cuyo binario ya no está en el servidor del
    # proveedor. Se conserva el rastro (quién adjuntó qué y cuándo) en vez de
    # perder la fila; `original_name` sigue siendo obligatorio.
    assert cols["file_path"].nullable is True
    assert cols["original_name"].nullable is False
    assert "updated_at" not in cols   # inmutable


# ─────────────────────────────────────────────────────────────────────────
# 7. Timestamps — excepciones explícitas del plan §2 (nota transversal)
# ─────────────────────────────────────────────────────────────────────────

ONLY_CREATED_AT = {
    "sgc_program_event_files", "sgc_task_comments", "sgc_task_approvals",
    # Las 4 de la migracion del SGC legacy: registros de hecho, inmutables.
    "sgc_document_acknowledgements", "sgc_document_visibility",
    "sgc_incident_files", "sgc_task_comment_files",
}
ONLY_UPDATED_AT = {"sgc_mail_config"}
NO_TIMESTAMPS = EXPECTED_ASSOC_TABLENAMES   # las 3 tablas de asociación


def test_timestamp_exceptions_match_plan():
    for table in ALL_TABLES:
        name = table.name
        has_created = "created_at" in table.columns
        has_updated = "updated_at" in table.columns
        if name in NO_TIMESTAMPS:
            assert not has_created and not has_updated, f"{name} no debe llevar timestamps"
        elif name in ONLY_CREATED_AT:
            assert has_created and not has_updated, f"{name} debe llevar solo created_at"
        elif name in ONLY_UPDATED_AT:
            assert has_updated and not has_created, f"{name} debe llevar solo updated_at"
        else:
            assert has_created and has_updated, f"{name} debe llevar created_at y updated_at"


# ─────────────────────────────────────────────────────────────────────────
# 8. Cascadas — ondelete CASCADE donde el plan lo exige, RESTRICT donde no
# ─────────────────────────────────────────────────────────────────────────

def _ondelete(table: Table, colname: str) -> str | None:
    col = table.columns[colname]
    fk = next(iter(col.foreign_keys))
    return fk.ondelete


def test_association_tables_cascade_both_sides():
    for table, cols in (
        (sgc_user_areas, ("user_id", "area_id")),
        (sgc_flow_step_assignees, ("step_id", "user_id")),
        (sgc_task_assignees, ("task_id", "user_id")),
    ):
        for c in cols:
            assert _ondelete(table, c) == "CASCADE", f"{table.name}.{c} debe ser ondelete=CASCADE"


def test_task_parent_fks_cascade():
    for col in ("incident_id", "program_id", "document_id"):
        assert _ondelete(SgcTask.__table__, col) == "CASCADE"


def test_task_flow_step_and_document_current_step_are_restrict():
    """flow_step_id / current_step_id son FK SIN ondelete a propósito (RESTRICT):
    borrar un paso con tareas/documentos activos debe fallar con error claro,
    no dejar columnas huérfanas (ver document_flow_service en §7 del plan)."""
    assert _ondelete(SgcTask.__table__, "flow_step_id") is None
    assert _ondelete(SgcDocument.__table__, "current_step_id") is None


def test_indicator_year_and_flow_step_cascade():
    assert _ondelete(SgcIndicator.__table__, "year_id") == "CASCADE"
    assert _ondelete(SgcIndicatorTracking.__table__, "indicator_id") == "CASCADE"
    assert _ondelete(SgcApprovalFlowStep.__table__, "flow_id") == "CASCADE"
    assert _ondelete(SgcProgramEventFile.__table__, "event_id") == "CASCADE"
    assert _ondelete(SgcTaskComment.__table__, "task_id") == "CASCADE"
    assert _ondelete(SgcTaskApproval.__table__, "task_id") == "CASCADE"


# ─────────────────────────────────────────────────────────────────────────
# 9. Relationships añadidos que el legacy no tenía
# ─────────────────────────────────────────────────────────────────────────

def test_document_has_current_step_relationship():
    assert "current_step" in SgcDocument.__mapper__.relationships


def test_task_has_flow_step_relationship():
    assert "flow_step" in SgcTask.__mapper__.relationships


def test_no_backref_pollutes_user_model():
    """Ninguna relación de sgc debe declarar `backref` (prohibido por el
    plan): las relaciones a User son unidireccionales."""
    from itcj2.core.models import User
    for name in User.__mapper__.relationships.keys():
        assert not name.startswith("sgi"), (
            f"User.{name} sugiere que algún relationship de sgc usó backref"
        )
