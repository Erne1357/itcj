"""PhotoService: normalización, guardado sin huérfanos y carga por lote."""
import io
import secrets

import pytest
from PIL import Image

from itcj2.apps.credencial.services import photo_service
from itcj2.apps.credencial.services.photo_service import (
    PHOTO_SIZE, PhotoError, PhotoService,
)
from itcj2.core.models.user import User


@pytest.fixture
def photo_dir(tmp_path, monkeypatch):
    from itcj2.config import get_settings
    monkeypatch.setattr(get_settings(), "CREDENCIAL_PHOTO_PATH", str(tmp_path))
    return tmp_path


def _img(fmt="JPEG", size=(200, 300), mode="RGB", color=(10, 20, 30), exif=None):
    buf = io.BytesIO()
    kw = {"exif": exif} if exif else {}
    Image.new(mode, size, color).save(buf, fmt, **kw)
    return buf.getvalue()


def _ctl():
    from itcj2.database import SessionLocal
    while True:
        c = "9" + "".join(secrets.choice("0123456789") for _ in range(7))
        with SessionLocal() as s:
            if s.query(User.id).filter_by(control_number=c).first() is None:
                return c


def _user(db, control=None):
    control = control or _ctl()
    u = User(first_name="Ana", last_name="Test", control_number=control)
    db.add(u)
    db.flush()
    return u


def _files(d):
    return [p for p in d.iterdir() if p.is_file()]


def test_normalize_size_and_no_exif():
    exif = Image.Exif()
    exif[0x010F] = "CamaraSecreta"
    raw = PhotoService.normalize(_img(exif=exif.tobytes()))
    out = Image.open(io.BytesIO(raw))
    assert out.format == "JPEG" and out.size == PHOTO_SIZE
    assert len(out.getexif()) == 0 and b"CamaraSecreta" not in raw


def test_exif_rotation_applied():
    exif = Image.Exif()
    exif[0x0112] = 6  # rotar 90 CW: 300x200 apaisada pasa a vertical, el rojo queda arriba
    src = Image.new("RGB", (300, 200), (0, 0, 255))
    src.paste((255, 0, 0), (0, 0, 150, 200))  # mitad izquierda roja
    buf = io.BytesIO()
    src.save(buf, "JPEG", exif=exif.tobytes())
    out = Image.open(io.BytesIO(PhotoService.normalize(buf.getvalue()))).convert("RGB")
    top, bottom = out.getpixel((228, 30)), out.getpixel((228, 570))
    assert top[0] > 200 and bottom[2] > 200


def test_png_alpha_flattened():
    out = Image.open(io.BytesIO(PhotoService.normalize(_img("PNG", mode="RGBA", color=(0, 0, 0, 0)))))
    r, g, b = out.convert("RGB").getpixel((10, 10))
    assert min(r, g, b) > 245  # transparente => blanco, no negro


def test_not_an_image_rejected():
    with pytest.raises(PhotoError):
        PhotoService.normalize(b"%PDF-1.4 no soy imagen")


def test_mpo_multi_picture_jpeg_accepted_as_plain_jpeg():
    """Ultra HDR / Samsung: JPEG con varias imágenes que Pillow reporta como MPO."""
    buf = io.BytesIO()
    Image.new("RGB", (200, 300), (200, 30, 30)).save(
        buf, "MPO", save_all=True, append_images=[Image.new("RGB", (200, 300), (0, 0, 255))])
    assert Image.open(io.BytesIO(buf.getvalue())).format == "MPO"
    raw = PhotoService.normalize(buf.getvalue())
    out = Image.open(io.BytesIO(raw))
    assert out.format == "JPEG" and out.size == PHOTO_SIZE
    assert getattr(out, "n_frames", 1) == 1
    r, g, b = out.getpixel((10, 10))
    assert r > 150 and b < 100  # la imagen principal, no la secundaria


def test_any_decoder_exception_is_photo_error(monkeypatch):
    """Un archivo armado a mano puede tronar un plugin con struct.error/IndexError: 400, no 500."""
    import struct

    def boom(img):
        raise struct.error("crafted")

    monkeypatch.setattr(photo_service.ImageOps, "exif_transpose", boom)
    with pytest.raises(PhotoError, match="no es una imagen válida"):
        PhotoService.normalize(_img())


def test_oversize_rejected(monkeypatch):
    monkeypatch.setattr(photo_service, "MAX_UPLOAD_BYTES", 100)
    with pytest.raises(PhotoError, match="10 MB"):
        PhotoService.normalize(_img(size=(400, 400)))


def test_too_many_pixels_rejected(monkeypatch):
    monkeypatch.setattr(photo_service, "MAX_PIXELS", 1000)
    with pytest.raises(PhotoError, match="píxeles"):
        PhotoService.normalize(_img("PNG", size=(100, 100)))


def test_decompression_bomb_rejected(monkeypatch):
    data = _img(size=(100, 100))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)  # 10 000 px > 2x => DecompressionBombError
    with pytest.raises(PhotoError, match="píxeles"):
        PhotoService.normalize(data)


def test_save_created_then_replaced_keeps_ref_and_deletes_old_file(db_session, photo_dir):
    u = _user(db_session)
    p1, s1 = PhotoService.save(db_session, u.id, _img(), None)
    old_name, ref = p1.file_name, p1.ref
    assert s1 == "created" and (photo_dir / old_name).exists()
    p2, s2 = PhotoService.save(db_session, u.id, _img(color=(200, 0, 0)), None)
    assert s2 == "replaced" and p2.ref == ref and p2.file_name != old_name
    assert not (photo_dir / old_name).exists()
    assert [f.name for f in _files(photo_dir)] == [p2.file_name]
    assert PhotoService.read_bytes(p2)[:2] == b"\xff\xd8"
    assert PhotoService.delete(db_session, u.id) is True and _files(photo_dir) == []
    assert PhotoService.delete(db_session, u.id) is False


def test_failed_commit_leaves_no_orphan(db_session, photo_dir, monkeypatch):
    u = _user(db_session)
    p, _ = PhotoService.save(db_session, u.id, _img(), None)
    before = {f.name for f in _files(photo_dir)}

    def boom():
        raise RuntimeError("commit roto")
    monkeypatch.setattr(db_session, "commit", boom)
    with pytest.raises(RuntimeError):
        PhotoService.save(db_session, u.id, _img(color=(1, 2, 3)), None)
    assert {f.name for f in _files(photo_dir)} == before  # viejo intacto, nuevo borrado


def test_match_filename_by_control(db_session):
    u = _user(db_session)
    c = u.control_number
    assert PhotoService.match_filename(db_session, f"{c}.jpg").id == u.id
    assert PhotoService.match_filename(db_session, f"L{c}.PNG").id == u.id
    assert PhotoService.match_filename(db_session, f"{c}X.jpg") is None  # sufijo no numérico: no existe


def test_import_batch_statuses(db_session, photo_dir):
    a, b = _user(db_session).control_number, _user(db_session).control_number
    PhotoService.import_batch(db_session, [(f"{b}.jpg", _img())], None)
    rows = PhotoService.import_batch(db_session, [
        (f"{a}.jpg", _img()),
        (f"{b}.jpg", _img()),
        (f"{a}X.jpg", _img()),
        (f"{a}.png", b"basura"),
    ], None)
    assert [r.status for r in rows] == ["created", "replaced", "no_student", "invalid"]
