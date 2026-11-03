"""CLI credencial import-photos: dry-run no escribe nada; real carga y reporta."""
import io

import pytest
from click.testing import CliRunner
from PIL import Image

from itcj2.cli.credencial import credencial_cli
from itcj2.core.models.user import User


class _NoCloseSession:
    """SessionLocal() de prueba: reutiliza db_session como context manager sin cerrarla."""
    def __init__(self, s):
        self.s = s

    def __call__(self):
        return self

    def __enter__(self):
        return self.s

    def __exit__(self, *a):
        return False


@pytest.fixture
def cli_env(db_session, tmp_path, monkeypatch):
    from itcj2.config import get_settings
    photos = tmp_path / "photos"
    monkeypatch.setattr(get_settings(), "CREDENCIAL_PHOTO_PATH", str(photos))
    monkeypatch.setattr("itcj2.database.SessionLocal", _NoCloseSession(db_session))
    src = tmp_path / "src"
    src.mkdir()
    buf = io.BytesIO()
    Image.new("RGB", (100, 150), (9, 9, 9)).save(buf, "JPEG")
    (src / "97654321.jpg").write_bytes(buf.getvalue())
    (src / "97654321X.jpg").write_bytes(buf.getvalue())
    (src / "notas.txt").write_text("ignorar")
    db_session.query(User).filter(User.control_number.in_(["97654321", "97654321X"])).delete()
    db_session.add(User(first_name="Luis", last_name="Test", control_number="97654321"))
    db_session.flush()
    return src, photos


def test_cli_dry_run_writes_nothing(cli_env, db_session):
    from itcj2.apps.credencial.models import CredentialPhoto
    src, photos = cli_env
    res = CliRunner().invoke(credencial_cli, ["import-photos", str(src), "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "match" in res.output and "no_student" in res.output and "notas.txt" not in res.output
    assert not photos.exists() or list(photos.iterdir()) == []
    assert db_session.query(CredentialPhoto).count() == 0


def test_cli_real_run_imports(cli_env, db_session):
    from itcj2.apps.credencial.models import CredentialPhoto
    src, photos = cli_env
    res = CliRunner().invoke(credencial_cli, ["import-photos", str(src)])
    assert res.exit_code == 0, res.output
    assert "created: 1" in res.output and "no_student: 1" in res.output
    assert db_session.query(CredentialPhoto).count() == 1 and len(list(photos.iterdir())) == 1
