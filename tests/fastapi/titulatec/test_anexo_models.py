"""Fase 6, tarea 1: modelos del Anexo III (spec 2026-10-22-titulatec-fase6-anexo-iii §5)."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError


def _anexo(proc, folio, **kw):
    from itcj2.apps.titulatec.models import Anexo

    return Anexo(process_id=proc.id, folio=folio, semester="2026B",
                 released_at=datetime(2026, 10, 1, 12, 0), **kw)


def test_columnas_y_nombres_de_tabla():
    from itcj2.apps.titulatec.models import Anexo, AnexoCounter

    assert Anexo.__tablename__ == "titulatec_anexos"
    assert AnexoCounter.__tablename__ == "titulatec_anexo_counters"
    cols = Anexo.__table__.c
    assert set(cols.keys()) == {"id", "process_id", "folio", "semester", "released_at",
                                "issued_at", "issued_by_id"}
    assert cols.folio.type.length == 20 and cols.semester.type.length == 5
    assert not cols.released_at.nullable and not cols.issued_at.nullable
    assert cols.issued_by_id.nullable
    assert cols.issued_by_id.type.__class__.__name__ == "BigInteger"
    cc = AnexoCounter.__table__.c
    assert cc.semester.primary_key and not cc.last_value.nullable
    assert cc.last_value.server_default is not None


def test_uniques_con_el_nombre_de_la_migracion():
    from itcj2.apps.titulatec.models import Anexo

    nombres = {c.name for c in Anexo.__table__.constraints if c.name}
    assert {"uq_titulatec_anexos_process", "uq_titulatec_anexos_folio"} <= nombres


def test_issued_at_por_omision(db_session, make_user, make_process):
    a = _anexo(make_process(make_user()), "ANX-2026B-0001")
    db_session.add(a)
    db_session.flush()
    db_session.refresh(a)
    assert a.issued_at is not None and a.issued_by_id is None


def test_un_proceso_tiene_a_lo_mas_un_anexo(db_session, make_user, make_process):
    proc = make_process(make_user())
    db_session.add(_anexo(proc, "ANX-2026B-0001"))
    db_session.flush()
    db_session.add(_anexo(proc, "ANX-2026B-0002"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_el_folio_es_unico(db_session, make_user, make_process):
    db_session.add(_anexo(make_process(make_user()), "ANX-2026B-0009"))
    db_session.flush()
    db_session.add(_anexo(make_process(make_user()), "ANX-2026B-0009"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_product_label_existe_y_sale_en_to_dict():
    from itcj2.apps.titulatec.models import Modality

    assert "product_label" in Modality.__table__.c
    assert Modality.__table__.c.product_label.nullable
    assert Modality.__table__.c.product_label.type.length == 150
    m = Modality(code="x", name="X", product_label="Tesis")
    assert m.to_dict()["product_label"] == "Tesis"


def test_la_red_de_auditoria_conoce_las_tablas_nuevas():
    from itcj2.apps.titulatec.services import audit_actions as a

    assert a.TABLE_MODULES["titulatec_anexos"] == "anexo"
    assert a.TABLE_MODULES["titulatec_anexo_counters"] == "anexo"
    assert "anexo" in a.AUDIT_MODULES
    assert a.ENTITY_TABLES["anexo"] == "titulatec_anexos"
