"""Tests de servicio contra Postgres real (fixture db_session, savepoint).

Por qué no MagicMock: estas rutas usan DISTINCT ON, funciones de ventana y un
CHECK de base de datos. Un MagicMock devuelve truthy para todo y no prueba nada.

Por qué los fixtures de abajo: la suite corre en DOS esquemas distintos. En dev el
esquema lo hace Alembic (la migración siembra la fila id=1 y hay usuarios reales);
en CI lo hace Base.metadata.create_all, la tabla nace VACÍA y core_users también
(database/ está gitignored y no llega al checkout). Un test que asuma la fila o un
id de usuario a pelo pasa en dev y revienta CI con UPDATE 0 o violación de FK.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from itcj2.apps.directory.services import directory_service as svc
from itcj2.apps.directory.services import settings_service
from itcj2.core.models.department import Department
from itcj2.core.models.position import Position, UserPosition
from itcj2.core.models.user import User


@pytest.fixture
def settings_row(db_session):
    """Garantiza la fila singleton, venga de Alembic o de create_all."""
    db_session.execute(text(
        "INSERT INTO directory_settings (id, show_unofficial_departments) "
        "VALUES (1, false) ON CONFLICT (id) DO NOTHING"
    ))
    db_session.flush()


@pytest.fixture
def some_user_id(db_session):
    """Un id de core_users que EXISTE aquí (updated_by_id es FK)."""
    existing = db_session.execute(text("SELECT id FROM core_users LIMIT 1")).scalar()
    if existing:
        return existing
    user = User(first_name="Test", last_name="Directory")
    db_session.add(user)
    db_session.flush()
    return user.id


# ── helpers de siembra ───────────────────────────────────────────────────────
def _mk_dept(db, code, name, parent_id=None, official=True):
    d = Department(code=code, name=name, parent_id=parent_id,
                   is_active=True, is_official=official)
    db.add(d)
    db.flush()
    return d


def _mk_user(db, suffix, email=None):
    u = User(first_name=f"Ana{suffix}", last_name="Test", email=email)
    db.add(u)
    db.flush()
    return u


def _mk_pos(db, code, *, allows_multiple=False, email=None, ext=None, dept_id=None):
    p = Position(code=code, title=code, is_active=True, allows_multiple=allows_multiple,
                 email=email, phone_extension=ext, department_id=dept_id)
    db.add(p)
    db.flush()
    return p


def _assign(db, user, pos, start=None, end=None, active=True):
    up = UserPosition(user_id=user.id, position_id=pos.id, is_active=active,
                      start_date=start or date.today() - timedelta(days=10), end_date=end)
    db.add(up)
    db.flush()
    return up


# ── settings_service ─────────────────────────────────────────────────────────
def test_show_unofficial_reads_persisted_true(db_session, settings_row):
    db_session.execute(text(
        "UPDATE directory_settings SET show_unofficial_departments = true WHERE id = 1"))
    assert settings_service.show_unofficial(db_session) is True


def test_show_unofficial_defaults_false_without_row(db_session):
    db_session.execute(text("DELETE FROM directory_settings"))
    assert settings_service.show_unofficial(db_session) is False


def test_set_show_unofficial_recreates_missing_row(db_session):
    db_session.execute(text("DELETE FROM directory_settings"))
    settings_service.set_show_unofficial(db_session, True, by_user_id=None)
    assert settings_service.show_unofficial(db_session) is True


def test_set_show_unofficial_records_author_and_timestamp(db_session, settings_row, some_user_id):
    before = db_session.execute(
        text("SELECT updated_at FROM directory_settings WHERE id = 1")).scalar()
    settings_service.set_show_unofficial(db_session, True, by_user_id=some_user_id)
    row = db_session.execute(text(
        "SELECT updated_by_id, updated_at FROM directory_settings WHERE id = 1")).one()
    assert row[0] == some_user_id
    assert row[1] >= before


def test_second_row_rejected_by_check(db_session, settings_row):
    with pytest.raises(Exception):
        db_session.execute(text(
            "INSERT INTO directory_settings (id, show_unofficial_departments) VALUES (2, true)"))
        db_session.flush()


# ── department_rows ──────────────────────────────────────────────────────────
def test_department_rows_excludes_unofficial_by_default(db_session):
    root = _mk_dept(db_session, "tst_root", "Raíz TST")
    unof = _mk_dept(db_session, "tst_unof", "No oficial TST", root.id, official=False)
    ids = {r["id"] for r in svc.department_rows(db_session, include_unofficial=False)}
    assert root.id in ids
    assert unof.id not in ids


def test_official_child_of_hidden_unofficial_is_rehung(db_session):
    """Un oficial NUNCA desaparece: se recuelga del ancestro superviviente."""
    root = _mk_dept(db_session, "tst_root2", "Raíz TST2")
    unof = _mk_dept(db_session, "tst_unof2", "Oculto TST2", root.id, official=False)
    child = _mk_dept(db_session, "tst_child2", "Hijo oficial TST2", unof.id)

    visible = {r["id"]: r for r in svc.department_rows(db_session, include_unofficial=False)}
    assert child.id in visible
    assert visible[child.id]["depth"] == visible[root.id]["depth"] + 1
    assert [a["id"] for a in visible[child.id]["ancestors"]] == [root.id]

    full = {r["id"]: r for r in svc.department_rows(db_session, include_unofficial=True)}
    assert full[child.id]["depth"] == visible[root.id]["depth"] + 2
    assert [a["id"] for a in full[child.id]["ancestors"]] == [root.id, unof.id]


# ── _position_holders ────────────────────────────────────────────────────────
def test_holders_count_zero_one_two(db_session):
    p0 = _mk_pos(db_session, "tst_h0")
    p1 = _mk_pos(db_session, "tst_h1")
    p2 = _mk_pos(db_session, "tst_h2")
    _assign(db_session, _mk_user(db_session, 1), p1)
    _assign(db_session, _mk_user(db_session, 2), p2)
    _assign(db_session, _mk_user(db_session, 3), p2)

    out = svc._position_holders(db_session, [p0.id, p1.id, p2.id])
    assert p0.id not in out
    assert out[p1.id]["holders_count"] == 1
    assert out[p2.id]["holders_count"] == 2


def test_holder_outside_validity_window_is_ignored(db_session):
    p = _mk_pos(db_session, "tst_h3")
    _assign(db_session, _mk_user(db_session, 4), p,
            start=date.today() - timedelta(days=40), end=date.today() - timedelta(days=1))
    assert p.id not in svc._position_holders(db_session, [p.id])


def test_holder_tiebreak_is_earliest_start(db_session):
    p = _mk_pos(db_session, "tst_h4")
    late = _mk_user(db_session, 5)
    early = _mk_user(db_session, 6)
    _assign(db_session, late, p, start=date.today() - timedelta(days=2))
    _assign(db_session, early, p, start=date.today() - timedelta(days=30))
    out = svc._position_holders(db_session, [p.id])
    assert out[p.id]["user_id"] == early.id
    assert out[p.id]["holders_count"] == 2


# ── regla de correo ──────────────────────────────────────────────────────────
def test_email_from_position_wins(db_session):
    p = _mk_pos(db_session, "tst_e1", email="puesto@cdjuarez.tecnm.mx", ext="2999")
    _assign(db_session, _mk_user(db_session, 10, email="persona@cdjuarez.tecnm.mx"), p)
    row = svc._position_row(p, svc._position_holders(db_session, [p.id]).get(p.id))
    assert row["email"] == "puesto@cdjuarez.tecnm.mx"
    assert row["email_source"] == "position"


def test_email_falls_back_to_single_holder(db_session):
    p = _mk_pos(db_session, "tst_e2", ext="2998")
    _assign(db_session, _mk_user(db_session, 11, email="persona@cdjuarez.tecnm.mx"), p)
    row = svc._position_row(p, svc._position_holders(db_session, [p.id]).get(p.id))
    assert row["email"] == "persona@cdjuarez.tecnm.mx"
    assert row["email_source"] == "holder"


def test_no_fallback_when_allows_multiple(db_session):
    p = _mk_pos(db_session, "tst_e3", allows_multiple=True, ext="2997")
    _assign(db_session, _mk_user(db_session, 12, email="persona@cdjuarez.tecnm.mx"), p)
    row = svc._position_row(p, svc._position_holders(db_session, [p.id]).get(p.id))
    assert row["email"] == ""
    assert row["email_source"] == ""


def test_no_fallback_with_two_holders(db_session):
    """Dato sucio: los DML insertan core_user_positions sin pasar por el guard."""
    p = _mk_pos(db_session, "tst_e4", ext="2996")
    _assign(db_session, _mk_user(db_session, 13, email="a@cdjuarez.tecnm.mx"), p)
    _assign(db_session, _mk_user(db_session, 14, email="b@cdjuarez.tecnm.mx"), p)
    row = svc._position_row(p, svc._position_holders(db_session, [p.id]).get(p.id))
    assert row["email"] == ""
    assert row["email_source"] == ""


def test_short_title_recorta_la_mayoria_de_los_puestos_sembrados(db_session):
    """Guard de D10: si un rename de core_departments.name rompe el recorte, salta aqui.

    Medido en dev 2026-09-07: recorta 79/87 = 91% de los puestos con departamento.
    """
    positions = db_session.query(Position).filter(Position.department_id.isnot(None)).all()
    trimmed = [p for p in positions if svc.short_title(p.title, p.department.name) != p.title]
    assert len(trimmed) >= int(0.8 * len(positions)), (
        f"solo {len(trimmed)}/{len(positions)} recortados: D10 quedo sin efecto"
    )


# ── list_directory ───────────────────────────────────────────────────────────
def test_ghost_groups_suppressed_when_filtering(db_session):
    """Con filtro activo no hay grupos fantasma: si no, «Sin resultados» es inalcanzable."""
    root = _mk_dept(db_session, "tst_g1", "Raíz G1")
    _mk_dept(db_session, "tst_g2", "Oculto G1", root.id, official=False)
    groups = svc.list_directory(
        db_session, q="zzz-no-existe", include_unofficial=True, include_empty_unofficial=True)
    assert all(g["rows"] for g in groups)


def test_ghost_group_emitted_without_filter(db_session):
    root = _mk_dept(db_session, "tst_g3", "Raíz G3")
    hidden = _mk_dept(db_session, "tst_g4", "Oculto G3", root.id, official=False)
    groups = svc.list_directory(
        db_session, include_unofficial=True, include_empty_unofficial=True)
    assert hidden.id in {g["department_id"] for g in groups}


def test_explicit_department_id_rescues_hidden_group(db_session):
    """Invariante de alcanzabilidad: un filtro explícito nunca se descarta."""
    from itcj2.apps.directory.models import DirectoryEntry
    root = _mk_dept(db_session, "tst_r1", "Raíz R1")
    hidden = _mk_dept(db_session, "tst_r2", "Oculto R1", root.id, official=False)
    db_session.add(DirectoryEntry(department_id=hidden.id, label="Recepción",
                                  extension="2777", is_active=True))
    db_session.flush()
    groups = svc.list_directory(db_session, department_id=hidden.id, include_unofficial=False)
    assert [g["department_id"] for g in groups] == [hidden.id]


def test_search_matches_email(db_session):
    d = _mk_dept(db_session, "tst_q2", "Depto Q")
    _mk_pos(db_session, "tst_q1", email="buscable@cdjuarez.tecnm.mx", ext="2995", dept_id=d.id)
    groups = svc.list_directory(db_session, q="buscable", include_unofficial=False)
    assert any(r["extension"] == "2995" for g in groups for r in g["rows"])


# ── escritura del correo ─────────────────────────────────────────────────────
def test_set_position_contact_rejects_duplicate_email(db_session):
    from itcj2.core.services.positions_service import PositionEmailConflict
    _mk_pos(db_session, "tst_c1", email="ocupado@cdjuarez.tecnm.mx")
    b = _mk_pos(db_session, "tst_c2")
    with pytest.raises(PositionEmailConflict):
        svc.set_position_contact(db_session, b.id, extension="2100", notes=None,
                                 email="OCUPADO@cdjuarez.tecnm.mx")


def test_set_position_contact_keeps_own_email(db_session):
    p = _mk_pos(db_session, "tst_c3", email="propio@cdjuarez.tecnm.mx")
    out = svc.set_position_contact(db_session, p.id, extension="2101", notes=None,
                                   email="propio@cdjuarez.tecnm.mx")
    assert out.email == "propio@cdjuarez.tecnm.mx"


def test_set_position_contact_clears_email(db_session):
    p = _mk_pos(db_session, "tst_c4", email="borrame@cdjuarez.tecnm.mx")
    out = svc.set_position_contact(db_session, p.id, extension="2102", notes=None, email="")
    assert out.email is None


def test_wrapper_does_not_touch_email(db_session):
    """El wrapper de 5 posicionales conserva el correo sin revalidarlo."""
    p = _mk_pos(db_session, "tst_c6", email="intacto@cdjuarez.tecnm.mx")
    out = svc.set_position_extension(db_session, p.id, "2104", None, None)
    assert out.email == "intacto@cdjuarez.tecnm.mx"


def test_entry_department_must_be_active(db_session):
    d = _mk_dept(db_session, "tst_c5", "Inactivo")
    d.is_active = False
    db_session.flush()
    with pytest.raises(ValueError):
        svc.create_entry(db_session, department_id=d.id, label="X", extension="2103",
                         by_user_id=None)


def test_entry_email_roundtrip_and_clear(db_session):
    d = _mk_dept(db_session, "tst_c7", "Depto entrada")
    entry = svc.create_entry(db_session, department_id=d.id, label="Recepción",
                             extension="2105", email=" recep@cdjuarez.tecnm.mx ")
    assert entry.email == "recep@cdjuarez.tecnm.mx"
    updated = svc.update_entry(db_session, entry.id, email="")
    assert updated.email is None
