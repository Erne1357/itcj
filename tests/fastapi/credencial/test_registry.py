"""Contrato de registro de la app credencial: modelos, CLI y estaticos."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_tables_registered():
    import itcj2.apps.credencial.models  # noqa: F401
    from itcj2.models.base import Base

    assert "credencial_photos" in Base.metadata.tables
    assert "credencial_verifications" in Base.metadata.tables


def test_check_constraint_text():
    from itcj2.apps.credencial.models import CredentialVerification

    texts = [str(c.sqltext) for c in CredentialVerification.__table__.constraints
             if c.__class__.__name__ == "CheckConstraint"]
    assert any("'valid','inactive'" in t for t in texts)


def test_init_files_listed():
    from itcj2.cli.credencial import _DML_BASE_FILES

    assert _DML_BASE_FILES == [
        "00_insert_app.sql", "01_insert_permissions.sql",
        "02_insert_roles.sql", "03_insert_role_permission.sql",
    ]


def test_static_registered():
    for rel in (
        "docker/scripts/generate-static-manifest.sh",
        "docker/nginx/nginx.dev.conf", "docker/nginx/nginx.prod.conf",
        "docker/compose/docker-compose.dev.yml", "docker/compose/docker-compose.prod.yml",
    ):
        assert "credencial" in (ROOT / rel).read_text(encoding="utf-8"), rel
