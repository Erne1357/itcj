"""Tests de ``services/catalog_service.py`` — los seis catálogos simples.

Escritos ANTES del service (TDD). Se apoyan en el fixture ``db_session`` de
``tests/fastapi/conftest.py`` (Postgres directo + SAVEPOINT + rollback) en vez
de en un ``MagicMock``: lo que hay que probar aquí es exactamente lo que un
mock no puede simular — el ``UNIQUE`` de ``name``, el ``ON DELETE`` implícito
(RESTRICT) de las FK que apuntan a los catálogos, y que un duplicado **no**
tumbe el lote entero. Nada se persiste: la transacción externa se revierte.

Regresiones del legacy cubiertas (``docs/adhoc/analysis/src_api.md`` §1.1, §1.2,
§2.4, §4):

* alta masiva con un duplicado → ``IntegrityError`` → **rollback del lote
  completo** y redirect "exitoso" (``save_areas``, ``save_processes``,
  ``save_incident_categories``, ``save_doc_categories``…);
* ``get_or_404`` tragado por ``except Exception`` → un 404 se volvía un 302
  "todo bien";
* ``Process(name=..., description=color)`` → el color vivía en la columna
  ``description``;
* ``Area.is_active`` sin UI para togglearlo pero **sí** filtrado en las
  consultas → las filas metidas por SQL quedaban ``NULL`` y desaparecían;
* ``delete_area`` sin verificar FKs → ``IntegrityError`` tragado.
"""
import pytest

from itcj2.apps.adhoc.models import (
    AdhocArea,
    AdhocDocument,
    AdhocDocumentCategory,
    AdhocDocumentClassification,
    AdhocIncident,
    AdhocIncidentCategory,
    AdhocProcess,
    AdhocProgramCategory,
    AdhocProgramEvent,
)
from itcj2.apps.adhoc.services import catalog_service as svc
from itcj2.apps.adhoc.services.catalog_service import (
    AdhocCatalogService,
    CatalogDuplicate,
    CatalogInUse,
    CatalogNotFound,
    CatalogValidationError,
)


#: Los cuatro catálogos que solo tienen ``name``.
NAME_ONLY_MODELS = [
    AdhocDocumentCategory,
    AdhocDocumentClassification,
    AdhocIncidentCategory,
    AdhocProgramCategory,
]

ALL_MODELS = NAME_ONLY_MODELS + [AdhocArea, AdhocProcess]


def _mk(db, model, **kw):
    """Crea una fila directamente (sin pasar por el service) y la flushea."""
    row = model(**kw)
    db.add(row)
    db.flush()
    return row


# ==========================================================================
# list_items
# ==========================================================================

class TestListItems:
    def test_ordena_por_nombre(self, db_session):
        _mk(db_session, AdhocArea, name="zzz_cat_zeta", color="#111111", is_active=True)
        _mk(db_session, AdhocArea, name="zzz_cat_alfa", color="#222222", is_active=True)

        names = [a.name for a in AdhocCatalogService.list_items(db_session, AdhocArea)]
        mine = [n for n in names if n.startswith("zzz_cat_")]
        assert mine == ["zzz_cat_alfa", "zzz_cat_zeta"]

    def test_devuelve_activos_e_inactivos_por_defecto(self, db_session):
        _mk(db_session, AdhocArea, name="zzz_on", color="#111111", is_active=True)
        _mk(db_session, AdhocArea, name="zzz_off", color="#111111", is_active=False)

        names = {a.name for a in AdhocCatalogService.list_items(db_session, AdhocArea)}
        assert {"zzz_on", "zzz_off"} <= names

    def test_filtro_is_active(self, db_session):
        """Regresión: el legacy filtraba por is_active sin exponerlo. Ahora es
        un filtro explícito y opcional."""
        _mk(db_session, AdhocArea, name="zzz_f_on", color="#111111", is_active=True)
        _mk(db_session, AdhocArea, name="zzz_f_off", color="#111111", is_active=False)

        activos = {a.name for a in AdhocCatalogService.list_items(db_session, AdhocArea, is_active=True)}
        assert "zzz_f_on" in activos
        assert "zzz_f_off" not in activos

        inactivos = {a.name for a in AdhocCatalogService.list_items(db_session, AdhocArea, is_active=False)}
        assert "zzz_f_off" in inactivos
        assert "zzz_f_on" not in inactivos

    def test_filtro_is_active_se_ignora_en_catalogos_sin_la_columna(self, db_session):
        _mk(db_session, AdhocDocumentCategory, name="zzz_sin_flag")
        items = AdhocCatalogService.list_items(db_session, AdhocDocumentCategory, is_active=True)
        assert "zzz_sin_flag" in {i.name for i in items}

    def test_busqueda_por_nombre(self, db_session):
        _mk(db_session, AdhocProcess, name="zzz_Gestión de Calidad", color="#333333")
        _mk(db_session, AdhocProcess, name="zzz_Compras", color="#333333")

        found = AdhocCatalogService.list_items(db_session, AdhocProcess, search="calidad")
        assert [p.name for p in found] == ["zzz_Gestión de Calidad"]

    def test_modelo_no_soportado(self, db_session):
        with pytest.raises(CatalogValidationError):
            AdhocCatalogService.list_items(db_session, AdhocDocument)


# ==========================================================================
# bulk_create
# ==========================================================================

class TestBulkCreate:
    def test_crea_todos_cuando_no_hay_duplicados(self, db_session):
        res = AdhocCatalogService.bulk_create(
            db_session, AdhocIncidentCategory,
            [{"name": "zzz_ic_a"}, {"name": "zzz_ic_b"}],
        )
        assert res.skipped == []
        assert [c.name for c in res.created] == ["zzz_ic_a", "zzz_ic_b"]
        assert all(c.id is not None for c in res.created)

    def test_duplicado_existente_no_tumba_el_lote(self, db_session):
        """LA regresión: el legacy hacía rollback de todo el lote por un solo
        duplicado y redirigía como si hubiera funcionado."""
        _mk(db_session, AdhocIncidentCategory, name="zzz_dup")

        res = AdhocCatalogService.bulk_create(
            db_session, AdhocIncidentCategory,
            [{"name": "zzz_nuevo_1"}, {"name": "zzz_dup"}, {"name": "zzz_nuevo_2"}],
        )

        assert res.skipped == ["zzz_dup"]
        assert [c.name for c in res.created] == ["zzz_nuevo_1", "zzz_nuevo_2"]

        persistidos = {
            c.name for c in db_session.query(AdhocIncidentCategory)
            .filter(AdhocIncidentCategory.name.like("zzz_%")).all()
        }
        assert persistidos == {"zzz_dup", "zzz_nuevo_1", "zzz_nuevo_2"}

    def test_duplicado_existente_es_case_insensitive(self, db_session):
        _mk(db_session, AdhocProgramCategory, name="zzz_Auditoria")

        res = AdhocCatalogService.bulk_create(
            db_session, AdhocProgramCategory, [{"name": "zzz_AUDITORIA"}],
        )
        assert res.created == []
        assert res.skipped == ["zzz_AUDITORIA"]

    def test_dedupe_dentro_del_propio_payload(self, db_session):
        res = AdhocCatalogService.bulk_create(
            db_session, AdhocDocumentClassification,
            [{"name": "zzz_x"}, {"name": "zzz_X"}, {"name": "zzz_y"}],
        )
        assert [c.name for c in res.created] == ["zzz_x", "zzz_y"]
        assert res.skipped == ["zzz_X"]

    def test_recorta_espacios(self, db_session):
        """Regresión de ``save_processes``: validaba ``name.strip()`` pero
        guardaba ``name`` con los espacios."""
        res = AdhocCatalogService.bulk_create(
            db_session, AdhocProcess, [{"name": "  zzz_espacios  ", "color": "#abcdef"}],
        )
        assert res.created[0].name == "zzz_espacios"

    def test_lista_vacia_es_error(self, db_session):
        with pytest.raises(CatalogValidationError):
            AdhocCatalogService.bulk_create(db_session, AdhocArea, [])

    def test_nombre_vacio_es_error(self, db_session):
        with pytest.raises(CatalogValidationError):
            AdhocCatalogService.bulk_create(db_session, AdhocArea, [{"name": "   "}])

    def test_campo_desconocido_es_error(self, db_session):
        with pytest.raises(CatalogValidationError):
            AdhocCatalogService.bulk_create(
                db_session, AdhocIncidentCategory, [{"name": "zzz_k", "color": "#000000"}],
            )

    def test_area_usa_defaults_de_color_y_is_active(self, db_session):
        res = AdhocCatalogService.bulk_create(db_session, AdhocArea, [{"name": "zzz_area_def"}])
        area = res.created[0]
        assert area.color == "#4834d4"
        assert area.is_active is True

    def test_area_respeta_is_active_false(self, db_session):
        res = AdhocCatalogService.bulk_create(
            db_session, AdhocArea, [{"name": "zzz_area_off", "is_active": False}],
        )
        assert res.created[0].is_active is False

    def test_process_guarda_color_en_columna_real(self, db_session):
        """Regresión: ``Process(name=..., description=color)``."""
        res = AdhocCatalogService.bulk_create(
            db_session, AdhocProcess,
            [{"name": "zzz_proc", "color": "#0f0f0f", "description": "Proceso de prueba"}],
        )
        proc = res.created[0]
        assert proc.color == "#0f0f0f"
        assert proc.description == "Proceso de prueba"


# ==========================================================================
# update
# ==========================================================================

class TestUpdate:
    def test_renombra(self, db_session):
        cat = _mk(db_session, AdhocIncidentCategory, name="zzz_viejo")
        out = AdhocCatalogService.update(db_session, AdhocIncidentCategory, cat.id, {"name": "zzz_nuevo"})
        assert out.name == "zzz_nuevo"

    def test_id_inexistente_lanza_not_found(self, db_session):
        """Regresión: ``except Exception`` tragaba el ``get_or_404``."""
        with pytest.raises(CatalogNotFound):
            AdhocCatalogService.update(db_session, AdhocIncidentCategory, 999_999_999, {"name": "x"})

    def test_nombre_duplicado_lanza_duplicate(self, db_session):
        _mk(db_session, AdhocDocumentCategory, name="zzz_ocupado")
        otro = _mk(db_session, AdhocDocumentCategory, name="zzz_libre")

        with pytest.raises(CatalogDuplicate):
            AdhocCatalogService.update(db_session, AdhocDocumentCategory, otro.id, {"name": "zzz_ocupado"})

        # El pre-chequeo corta ANTES de tocar el ORM: nada que revertir.
        assert db_session.get(AdhocDocumentCategory, otro.id).name == "zzz_libre"

    def test_renombrarse_a_si_mismo_no_es_conflicto(self, db_session):
        cat = _mk(db_session, AdhocDocumentCategory, name="zzz_igual")
        out = AdhocCatalogService.update(db_session, AdhocDocumentCategory, cat.id, {"name": "zzz_igual"})
        assert out.name == "zzz_igual"

    def test_sin_campos_es_error(self, db_session):
        cat = _mk(db_session, AdhocDocumentCategory, name="zzz_nada")
        with pytest.raises(CatalogValidationError):
            AdhocCatalogService.update(db_session, AdhocDocumentCategory, cat.id, {})

    def test_campo_desconocido_es_error(self, db_session):
        cat = _mk(db_session, AdhocDocumentCategory, name="zzz_raro")
        with pytest.raises(CatalogValidationError):
            AdhocCatalogService.update(db_session, AdhocDocumentCategory, cat.id, {"is_active": False})

    def test_area_toggle_is_active(self, db_session):
        """Regresión: el legacy nunca expuso el toggle aunque filtraba por él."""
        area = _mk(db_session, AdhocArea, name="zzz_toggle", color="#123456", is_active=True)
        out = AdhocCatalogService.update(db_session, AdhocArea, area.id, {"is_active": False})
        assert out.is_active is False

    def test_process_actualiza_color_sin_tocar_description(self, db_session):
        proc = _mk(db_session, AdhocProcess, name="zzz_pc", color="#111111", description="texto")
        out = AdhocCatalogService.update(db_session, AdhocProcess, proc.id, {"color": "#999999"})
        assert out.color == "#999999"
        assert out.description == "texto"

    def test_description_se_puede_limpiar(self, db_session):
        proc = _mk(db_session, AdhocProcess, name="zzz_pd", color="#111111", description="texto")
        out = AdhocCatalogService.update(db_session, AdhocProcess, proc.id, {"description": None})
        assert out.description is None

    def test_name_none_es_error(self, db_session):
        cat = _mk(db_session, AdhocDocumentCategory, name="zzz_nn")
        with pytest.raises(CatalogValidationError):
            AdhocCatalogService.update(db_session, AdhocDocumentCategory, cat.id, {"name": None})


# ==========================================================================
# delete / count_dependents
# ==========================================================================

class TestDelete:
    def test_borra(self, db_session):
        cat = _mk(db_session, AdhocProgramCategory, name="zzz_borrable")
        AdhocCatalogService.delete(db_session, AdhocProgramCategory, cat.id)
        assert db_session.get(AdhocProgramCategory, cat.id) is None

    def test_id_inexistente_lanza_not_found(self, db_session):
        with pytest.raises(CatalogNotFound):
            AdhocCatalogService.delete(db_session, AdhocProgramCategory, 999_999_999)

    def test_area_en_uso_por_documento(self, db_session):
        area = _mk(db_session, AdhocArea, name="zzz_area_usada", color="#123456", is_active=True)
        _mk(db_session, AdhocDocument, title="zzz doc", area_id=area.id)

        with pytest.raises(CatalogInUse) as exc:
            AdhocCatalogService.delete(db_session, AdhocArea, area.id)

        assert "zzz_area_usada" in str(exc.value)
        assert "documento" in str(exc.value)
        assert db_session.get(AdhocArea, area.id) is not None

    def test_area_en_uso_por_incidencia_y_evento(self, db_session):
        area = _mk(db_session, AdhocArea, name="zzz_area_multi", color="#123456", is_active=True)
        _mk(db_session, AdhocIncident, title="zzz inc", area_id=area.id)
        _mk(db_session, AdhocProgramEvent, title="zzz ev", area_id=area.id)

        deps = AdhocCatalogService.count_dependents(db_session, AdhocArea, area.id)
        assert deps == {"incidencia": 1, "evento de programa": 1}

        with pytest.raises(CatalogInUse):
            AdhocCatalogService.delete(db_session, AdhocArea, area.id)

    def test_process_en_uso(self, db_session):
        proc = _mk(db_session, AdhocProcess, name="zzz_proc_usado", color="#123456")
        _mk(db_session, AdhocIncident, title="zzz inc p", process_id=proc.id)

        with pytest.raises(CatalogInUse):
            AdhocCatalogService.delete(db_session, AdhocProcess, proc.id)

    def test_document_category_en_uso(self, db_session):
        cat = _mk(db_session, AdhocDocumentCategory, name="zzz_cat_usada")
        _mk(db_session, AdhocDocument, title="zzz doc c", category_id=cat.id)

        with pytest.raises(CatalogInUse):
            AdhocCatalogService.delete(db_session, AdhocDocumentCategory, cat.id)

    def test_document_classification_en_uso(self, db_session):
        cls = _mk(db_session, AdhocDocumentClassification, name="zzz_cls_usada")
        _mk(db_session, AdhocDocument, title="zzz doc cl", classification_id=cls.id)

        with pytest.raises(CatalogInUse):
            AdhocCatalogService.delete(db_session, AdhocDocumentClassification, cls.id)

    def test_incident_category_en_uso(self, db_session):
        cat = _mk(db_session, AdhocIncidentCategory, name="zzz_ic_usada")
        _mk(db_session, AdhocIncident, title="zzz inc c", category_id=cat.id)

        with pytest.raises(CatalogInUse):
            AdhocCatalogService.delete(db_session, AdhocIncidentCategory, cat.id)

    def test_program_category_en_uso(self, db_session):
        cat = _mk(db_session, AdhocProgramCategory, name="zzz_pc_usada")
        _mk(db_session, AdhocProgramEvent, title="zzz ev c", category_id=cat.id)

        with pytest.raises(CatalogInUse):
            AdhocCatalogService.delete(db_session, AdhocProgramCategory, cat.id)

    def test_sin_dependientes_count_es_vacio(self, db_session):
        cat = _mk(db_session, AdhocProgramCategory, name="zzz_pc_libre")
        assert AdhocCatalogService.count_dependents(db_session, AdhocProgramCategory, cat.id) == {}


# ==========================================================================
# Metadatos del registro (que no se olvide ningún catálogo)
# ==========================================================================

def test_los_seis_catalogos_estan_registrados():
    tablas = {m.__tablename__ for m in ALL_MODELS}
    assert tablas <= set(svc.CATALOG_FIELDS)
    assert tablas <= set(svc.CATALOG_DEPENDENTS)
    assert tablas <= set(svc.CATALOG_LABELS)


@pytest.mark.parametrize("model", NAME_ONLY_MODELS)
def test_catalogos_de_solo_nombre(model):
    assert svc.CATALOG_FIELDS[model.__tablename__] == ("name",)
