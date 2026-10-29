"""Fixtures de Prórrogas.

Las pruebas corren contra el Postgres de dev dentro de un savepoint
(`tests/fastapi/conftest.py::db_session`): lo que crean se descarta al final,
pero SÍ ven lo que ya esté commiteado en dev. Por eso las pruebas de plantillas
usan años lejanos (2089–2095), donde no hay plantillas reales.
"""
from io import BytesIO
from itertools import count

import pytest

_seq = count(1)


@pytest.fixture(autouse=True)
def almacen(tmp_path, monkeypatch):
    """Los archivos de plantillas van a `tmp_path`, nunca a `instance/` real."""
    from itcj2.apps.prorrogas_tec.services import template_service

    base = tmp_path / "prorrogas_tec"
    monkeypatch.setattr(template_service, "_base", lambda: base)
    return base


@pytest.fixture()
def make_user(db_session):
    """Usuario sintético. Nombres ficticios, correo .invalid."""
    from itcj2.core.models.user import User

    def _make(first_name="ACTOR", last_name="PRUEBA", middle_name=None, control_number=None,
              username=None, email=None):
        n = next(_seq)
        user = User(
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            username=username or f"pr_test_{n}_{id(db_session)}",
            control_number=control_number,
            email=email or f"pr.test.{n}@example.invalid",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
        return user

    return _make


@pytest.fixture()
def docx_con():
    """`.docx` con un párrafo por línea."""
    from docx import Document

    def _make(*lines: str) -> bytes:
        d = Document()
        for line in lines:
            d.add_paragraph(line)
        buf = BytesIO()
        d.save(buf)
        return buf.getvalue()

    return _make
