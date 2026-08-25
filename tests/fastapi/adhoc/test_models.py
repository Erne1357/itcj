"""
Tests de contrato para los 22 modelos de `itcj2.apps.adhoc.models`.

Introspección sobre `__table__` (no requiere BD): nombres de tabla exactos,
BigInteger en toda FK a `core_users`, índice en toda columna FK, vocabularios
cerrados de los CheckConstraint, UniqueConstraint y nullability tal como los
especifica `docs/adhoc/PLAN_MIGRACION_ADHOC.md` §2. Debe fallar si alguien
cambia el esquema sin actualizar el plan.
"""
from sqlalchemy import BigInteger, CheckConstraint, Column, Date, DateTime, Table, UniqueConstraint

from itcj2.apps.adhoc.models import (
    AdhocApprovalFlow,
    AdhocApprovalFlowStep,
    AdhocArea,
    AdhocDocument,
    AdhocDocumentCategory,
    AdhocDocumentClassification,
    AdhocIncident,
    AdhocIncidentCategory,
    AdhocIndicator,
    AdhocIndicatorTracking,
    AdhocIndicatorYear,
    AdhocMailConfig,
    AdhocProcess,
    AdhocProgramCategory,
    AdhocProgramEvent,
    AdhocProgramEventFile,
    AdhocTask,
    AdhocTaskApproval,
    AdhocTaskComment,
    adhoc_flow_step_assignees,
    adhoc_task_assignees,
    adhoc_user_areas,
)


# Las 19 clases mapeadas (entidad + catálogo + singleton).
MAPPED_MODELS = [
    AdhocArea, AdhocProcess,
    AdhocIndicatorYear, AdhocIndicator, AdhocIndicatorTracking,
    AdhocMailConfig,
    AdhocDocumentCategory, AdhocDocumentClassification,
    AdhocApprovalFlow, AdhocApprovalFlowStep, AdhocDocument,
    AdhocIncidentCategory, AdhocIncident,
    AdhocProgramCategory, AdhocProgramEvent, AdhocProgramEventFile,
    AdhocTask, AdhocTaskComment, AdhocTaskApproval,
]

# Las 3 tablas de asociación puras (sqlalchemy.Table, sin clase mapeada).
ASSOC_TABLES = [adhoc_user_areas, adhoc_flow_step_assignees, adhoc_task_assignees]

ALL_TABLES = [m.__table__ for m in MAPPED_MODELS] + ASSOC_TABLES

EXPECTED_TABLENAMES = {
    "AdhocArea": "adhoc_areas",
    "AdhocProcess": "adhoc_processes",
    "AdhocIndicatorYear": "adhoc_indicator_years",
    "AdhocIndicator": "adhoc_indicators",
    "AdhocIndicatorTracking": "adhoc_indicator_trackings",
    "AdhocMailConfig": "adhoc_mail_config",
    "AdhocDocumentCategory": "adhoc_document_categories",
    "AdhocDocumentClassification": "adhoc_document_classifications",
    "AdhocApprovalFlow": "adhoc_approval_flows",
    "AdhocApprovalFlowStep": "adhoc_approval_flow_steps",
    "AdhocDocument": "adhoc_documents",
    "AdhocIncidentCategory": "adhoc_incident_categories",
    "AdhocIncident": "adhoc_incidents",
    "AdhocProgramCategory": "adhoc_program_categories",
    "AdhocProgramEvent": "adhoc_program_events",
    "AdhocProgramEventFile": "adhoc_program_event_files",
    "AdhocTask": "adhoc_tasks",
    "AdhocTaskComment": "adhoc_task_comments",
    "AdhocTaskApproval": "adhoc_task_approvals",
}

EXPECTED_ASSOC_TABLENAMES = {
    "adhoc_user_areas", "adhoc_flow_step_assignees", "adhoc_task_assignees",
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
# 1. Las 22 tablas existen con el nombre exacto
# ─────────────────────────────────────────────────────────────────────────

def test_22_tables_total():
    assert len(MAPPED_MODELS) + len(ASSOC_TABLES) == 22


def test_tablenames_exact():
    for model in MAPPED_MODELS:
        expected = EXPECTED_TABLENAMES[model.__name__]
        assert model.__tablename__ == expected
        assert model.__table__.name == expected


def test_assoc_tablenames_exact():
    names = {t.name for t in ASSOC_TABLES}
    assert names == EXPECTED_ASSOC_TABLENAMES


def test_no_tablename_collides_with_other_apps():
    """adhoc_* no debe colisionar con tablas de otras apps ya registradas."""
    import itcj2.models  # noqa: F401
    base = MAPPED_MODELS[0].__table__.metadata
    adhoc_names = {t.name for t in ALL_TABLES}
    other_names = {name for name in base.tables if not name.startswith("adhoc_")}
    assert adhoc_names.isdisjoint(other_names)


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
    # 10 FKs a core_users en total: user_areas.user_id, flow_step_assignees.user_id,
    # documents.author_id, incidents.responsible_id, program_events.responsible_id,
    # program_event_files.uploaded_by_id, tasks.created_by_id, task_assignees.user_id,
    # task_comments.user_id, task_approvals.user_id.
    assert checked == 10


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
    _assert_check_contains(AdhocIndicator.__table__, "Semanal", "Mensual", "Anual")


def test_indicator_tracking_color_vocabulary():
    _assert_check_contains(AdhocIndicatorTracking.__table__, "blanco", "rojo", "amarillo", "verde")


def test_document_status_vocabulary():
    _assert_check_contains(AdhocDocument.__table__, "Borrador", "En Revisión", "Aprobado", "Rechazado")


def test_incident_status_and_priority_vocabulary():
    _assert_check_contains(AdhocIncident.__table__, "No Iniciada", "Iniciada", "Cerrada")
    _assert_check_contains(AdhocIncident.__table__, "Baja", "Media", "Alta", "Urgente")
    # El default 'Abierto' del legacy y el 'Completado' del workflow quedan fuera.
    texts = " | ".join(str(c.sqltext) for c in _check_constraints(AdhocIncident.__table__))
    assert "'Abierto'" not in texts
    assert "'Completado'" not in texts


def test_program_event_status_and_priority_vocabulary():
    _assert_check_contains(AdhocProgramEvent.__table__, "Planeado", "En Proceso", "Completado")
    _assert_check_contains(AdhocProgramEvent.__table__, "Baja", "Media", "Alta", "Urgente")


def test_task_status_and_priority_vocabulary():
    _assert_check_contains(
        AdhocTask.__table__,
        "Pendiente", "En Proceso", "En Revisión", "En Espera", "Completada", "Rechazada",
    )
    _assert_check_contains(AdhocTask.__table__, "Baja", "Media", "Alta", "Urgente")


def test_task_approval_decision_vocabulary():
    _assert_check_contains(AdhocTaskApproval.__table__, "aprobado", "rechazado")


def test_task_single_parent_check_constraint_present():
    texts = " | ".join(str(c.sqltext) for c in _check_constraints(AdhocTask.__table__))
    assert "incident_id" in texts and "program_id" in texts and "document_id" in texts
    assert "= 1" in texts


def test_mail_config_singleton_check_constraint():
    texts = " | ".join(str(c.sqltext) for c in _check_constraints(AdhocMailConfig.__table__))
    assert "id = 1" in texts


# ─────────────────────────────────────────────────────────────────────────
# 5. UniqueConstraint / unique=True
# ─────────────────────────────────────────────────────────────────────────

def test_indicator_tracking_unique_indicator_period():
    ucs = _unique_constraints(AdhocIndicatorTracking.__table__)
    cols = [{c.name for c in uc.columns} for uc in ucs]
    assert {"indicator_id", "period_index"} in cols


def test_approval_flow_step_unique_flow_order():
    ucs = _unique_constraints(AdhocApprovalFlowStep.__table__)
    cols = [{c.name for c in uc.columns} for uc in ucs]
    assert {"flow_id", "step_order"} in cols


def test_task_approval_unique_task_user():
    ucs = _unique_constraints(AdhocTaskApproval.__table__)
    cols = [{c.name for c in uc.columns} for uc in ucs]
    assert {"task_id", "user_id"} in cols


def test_unique_name_catalogs():
    for model in (
        AdhocArea, AdhocProcess, AdhocDocumentCategory, AdhocDocumentClassification,
        AdhocIncidentCategory, AdhocProgramCategory,
    ):
        assert model.__table__.columns["name"].unique is True, f"{model.__name__}.name debe ser unique"
    assert AdhocIndicatorYear.__table__.columns["year"].unique is True


# ─────────────────────────────────────────────────────────────────────────
# 6. Nullability (§2 del plan, spot checks obligatorios)
# ─────────────────────────────────────────────────────────────────────────

def test_area_columns():
    cols = AdhocArea.__table__.columns
    assert cols["name"].nullable is False
    assert cols["color"].nullable is False
    assert cols["is_active"].nullable is False
    assert cols["is_active"].index is True


def test_process_columns():
    cols = AdhocProcess.__table__.columns
    assert cols["name"].nullable is False
    assert cols["color"].nullable is False   # columna REAL, no @property
    assert cols["description"].nullable is True


def test_indicator_columns():
    cols = AdhocIndicator.__table__.columns
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
    cols = AdhocIndicatorTracking.__table__.columns
    assert cols["indicator_id"].nullable is False
    assert cols["period_index"].nullable is False
    assert cols["color"].nullable is False


def test_mail_config_columns():
    cols = AdhocMailConfig.__table__.columns
    assert cols["is_enabled"].nullable is False
    assert "sender_name" not in cols
    assert "sender_email" not in cols
    assert "created_at" not in cols   # solo updated_at (singleton sembrado por DML)
    assert "updated_at" in cols


def test_document_columns():
    cols = AdhocDocument.__table__.columns
    assert cols["title"].nullable is False
    assert cols["code"].nullable is True
    assert cols["author_id"].nullable is True
    assert isinstance(cols["approval_date"].type, DateTime)   # NO Date (bug del legacy)
    for fk_col in ("category_id", "area_id", "process_id", "classification_id",
                    "flow_id", "current_step_id"):
        assert cols[fk_col].nullable is True


def test_approval_flow_step_flow_id_not_null():
    # El legacy lo tenía nullable: un paso sin flujo es basura.
    assert AdhocApprovalFlowStep.__table__.columns["flow_id"].nullable is False


def test_incident_and_program_event_dates_are_date_type():
    for model in (AdhocIncident, AdhocProgramEvent):
        cols = model.__table__.columns
        for name in ("start_date", "commitment_date", "real_date"):
            assert isinstance(cols[name].type, Date), (
                f"{model.__name__}.{name} debe ser Date, es {cols[name].type!r}"
            )
            assert not isinstance(cols[name].type, DateTime)


def test_incident_status_and_priority_defaults():
    cols = AdhocIncident.__table__.columns
    assert cols["status"].nullable is False
    assert cols["priority"].nullable is False
    assert str(cols["status"].server_default.arg) == "'No Iniciada'"


def test_program_event_status_default():
    cols = AdhocProgramEvent.__table__.columns
    assert cols["status"].nullable is False
    assert str(cols["status"].server_default.arg) == "'Planeado'"


def test_task_columns():
    cols = AdhocTask.__table__.columns
    assert cols["description"].nullable is False
    assert cols["status"].nullable is False
    assert cols["priority"].nullable is False
    for fk_col in ("incident_id", "program_id", "document_id", "flow_step_id"):
        assert cols[fk_col].nullable is True


def test_task_assignees_no_is_completed():
    assert "is_completed" not in adhoc_task_assignees.columns
    assert "notified_overdue" in adhoc_task_assignees.columns
    assert adhoc_task_assignees.columns["notified_overdue"].nullable is False


def test_flow_step_assignees_notify_on_overdue():
    cols = adhoc_flow_step_assignees.columns
    assert cols["notify_on_overdue"].nullable is False


def test_task_comment_columns():
    cols = AdhocTaskComment.__table__.columns
    assert cols["task_id"].nullable is False
    assert cols["user_id"].nullable is False
    assert cols["comment"].nullable is False
    assert cols["file_path"].nullable is True
    assert "updated_at" not in cols   # inmutable: se crea y se borra


def test_task_approval_columns():
    cols = AdhocTaskApproval.__table__.columns
    assert cols["task_id"].nullable is False
    assert cols["user_id"].nullable is False
    assert cols["decision"].nullable is False
    assert "updated_at" not in cols   # inmutable


def test_program_event_file_columns():
    cols = AdhocProgramEventFile.__table__.columns
    assert cols["event_id"].nullable is False
    assert cols["file_path"].nullable is False
    assert cols["original_name"].nullable is False
    assert "updated_at" not in cols   # inmutable


# ─────────────────────────────────────────────────────────────────────────
# 7. Timestamps — excepciones explícitas del plan §2 (nota transversal)
# ─────────────────────────────────────────────────────────────────────────

ONLY_CREATED_AT = {"adhoc_program_event_files", "adhoc_task_comments", "adhoc_task_approvals"}
ONLY_UPDATED_AT = {"adhoc_mail_config"}
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
        (adhoc_user_areas, ("user_id", "area_id")),
        (adhoc_flow_step_assignees, ("step_id", "user_id")),
        (adhoc_task_assignees, ("task_id", "user_id")),
    ):
        for c in cols:
            assert _ondelete(table, c) == "CASCADE", f"{table.name}.{c} debe ser ondelete=CASCADE"


def test_task_parent_fks_cascade():
    for col in ("incident_id", "program_id", "document_id"):
        assert _ondelete(AdhocTask.__table__, col) == "CASCADE"


def test_task_flow_step_and_document_current_step_are_restrict():
    """flow_step_id / current_step_id son FK SIN ondelete a propósito (RESTRICT):
    borrar un paso con tareas/documentos activos debe fallar con error claro,
    no dejar columnas huérfanas (ver document_flow_service en §7 del plan)."""
    assert _ondelete(AdhocTask.__table__, "flow_step_id") is None
    assert _ondelete(AdhocDocument.__table__, "current_step_id") is None


def test_indicator_year_and_flow_step_cascade():
    assert _ondelete(AdhocIndicator.__table__, "year_id") == "CASCADE"
    assert _ondelete(AdhocIndicatorTracking.__table__, "indicator_id") == "CASCADE"
    assert _ondelete(AdhocApprovalFlowStep.__table__, "flow_id") == "CASCADE"
    assert _ondelete(AdhocProgramEventFile.__table__, "event_id") == "CASCADE"
    assert _ondelete(AdhocTaskComment.__table__, "task_id") == "CASCADE"
    assert _ondelete(AdhocTaskApproval.__table__, "task_id") == "CASCADE"


# ─────────────────────────────────────────────────────────────────────────
# 9. Relationships añadidos que el legacy no tenía
# ─────────────────────────────────────────────────────────────────────────

def test_document_has_current_step_relationship():
    assert "current_step" in AdhocDocument.__mapper__.relationships


def test_task_has_flow_step_relationship():
    assert "flow_step" in AdhocTask.__mapper__.relationships


def test_no_backref_pollutes_user_model():
    """Ninguna relación de adhoc debe declarar `backref` (prohibido por el
    plan): las relaciones a User son unidireccionales."""
    from itcj2.core.models import User
    for name in User.__mapper__.relationships.keys():
        assert not name.startswith("adhoc"), (
            f"User.{name} sugiere que algún relationship de adhoc usó backref"
        )
