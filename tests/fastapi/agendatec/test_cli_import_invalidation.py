"""R8 (agendatec): el import por CSV debe invalidar/revocar lo que muta.

Dos huecos cerrados en la Tarea 7:

1. FASE 1 (`_upsert_student_v2`): asignar el rol `student` de agendatec a un
   alumno debe invalidar su entrada `has` cacheada — si el alumno ya golpeó un
   guard de agendatec en un periodo anterior con el rol ausente, esa entrada
   `False` sobrevive hasta el TTL (5 min) y le seguiría dando 403 aunque el CSV
   ya le dio el rol.

2. FASE 2 (loop de desactivación): un alumno que sale del CSV debe perder el
   rol Y la sesión viva, atómicamente (`bump_version(db=db)`), y el caché de la
   época debe borrarse una SEGUNDA vez DESPUÉS del commit (Carrera A6, cerrada
   en las Tareas 5/6): el primer borrado, dentro de `bump_version`, ocurre
   ANTES de que el caller commitee, así que un lector puede colarse en esa
   ventana y repoblar el caché con la época vieja aún no commiteada.

El test de FASE 1 corre contra Postgres/Redis reales (mismo harness que el
resto de agendatec) porque está acotado a UN alumno y no toca `deactivate
_missing`. El de FASE 2 usa un `db` completamente mockeado a propósito: la
consulta real de "alumnos activos con rol agendatec/student" barre CUALQUIER
alumno real que ya tenga ese rol en la BD compartida de dev/test, y
`bump_version`/`forget_cached_version` hacen escrituras/borrados de Redis que
NO se revierten con el rollback de Postgres del savepoint — exactamente el tipo
de efecto colateral sobre sesiones reales que este plan existe para evitar. Un
mock total del `db` prueba el ORDEN y las condiciones sin tocar ningún dato
compartido.
"""
import csv
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from itcj2.cli.agendatec import sync_students_agendatec_command


# ---------------------------------------------------------------------------
# FASE 1 — asignar rol nuevo invalida el caché `has`, contra BD/Redis reales
# ---------------------------------------------------------------------------
class _SyncSessionLocalCtx:
    """Envuelve `db_session` como context manager para `with SessionLocal() as db:`.

    `patched_session_local` (conftest de agendatec) no sirve aquí: su proxy
    `_NoClose` solo implementa `__getattr__`, y el protocolo de `with` busca
    `__enter__`/`__exit__` en el TIPO, no vía `__getattr__` de la instancia —
    confirmado a mano antes de escribir esto. Este wrapper es local al test.
    """

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, tb):
        return False


def _write_csv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["no_de_control", "apellido_paterno", "apellido_materno", "nombre_alumno", "nip"]
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_sync_students_new_role_invalidates_has_cache(tmp_path, db_session, agendatec_app, make_user):
    from itcj2.core.models.role import Role
    from itcj2.core.models.user_app_role import UserAppRole
    from itcj2.core.utils.redis_conn import get_redis

    student = make_user(first_name="Ana", last_name="Lopez", control_number="20211234", role_name="student")

    r = get_redis()
    assert r is not None, "Redis debe estar disponible para este test"
    stale_key = f"authz:v1:has:agendatec:{student.id}"
    # Simula al alumno pegándole a un guard de agendatec ANTES de tener el rol:
    # la entrada `has` queda cacheada en False.
    r.setex(stale_key, 30, "false")

    csv_path = tmp_path / "students.csv"
    _write_csv(csv_path, [{
        "no_de_control": "20211234",
        "apellido_paterno": "Lopez",
        "apellido_materno": "Garcia",
        "nombre_alumno": "Ana",
        "nip": "1234",
    }])

    with patch("itcj2.database.SessionLocal", return_value=_SyncSessionLocalCtx(db_session)):
        result = CliRunner().invoke(
            sync_students_agendatec_command,
            ["--csv-path", str(csv_path), "--no-deactivate-missing"],
        )

    assert result.exit_code == 0, result.output

    role = db_session.query(Role).filter_by(name="student").first()
    link = db_session.query(UserAppRole).filter_by(
        user_id=student.id, app_id=agendatec_app.id, role_id=role.id
    ).first()
    assert link is not None, "el import debió crear el UserAppRole de agendatec/student"

    # Sin la invalidación, esta clave seguiría en Redis con el valor viejo
    # (False) hasta que expirara el TTL, aunque el rol ya existe en BD.
    assert r.get(stale_key) is None


# ---------------------------------------------------------------------------
# FASE 2 — loop de desactivación, con `db` mockeado (ver docstring del módulo)
# ---------------------------------------------------------------------------
def _make_query_side_effect(app_row, role_row, deactivation_candidates):
    from itcj2.core.models import App, Role, User

    def _side_effect(model):
        q = MagicMock()
        if model is App:
            q.filter_by.return_value.first.return_value = app_row
        elif model is Role:
            q.filter_by.return_value.first.return_value = role_row
        elif model is User:
            q.join.return_value.filter.return_value.all.return_value = deactivation_candidates
        return q

    return _side_effect


def _fake_deactivation_setup(tmp_path, student_id):
    fake_student = MagicMock()
    fake_student.id = student_id
    fake_student.control_number = "NOTINCSV1"
    fake_student.username = None
    fake_student.is_active = True

    db = MagicMock()
    db.query.side_effect = _make_query_side_effect(
        app_row=MagicMock(id=1), role_row=MagicMock(id=2), deactivation_candidates=[fake_student],
    )

    session_ctx = MagicMock()
    session_ctx.__enter__.return_value = db
    session_ctx.__exit__.return_value = False

    csv_path = tmp_path / "students_empty.csv"
    _write_csv(csv_path, [])  # nadie en el CSV -> el único candidato queda "not in_csv"

    return fake_student, db, session_ctx, csv_path


def test_sync_students_deactivation_bumps_before_commit_and_forgets_after(tmp_path):
    fake_student, db, session_ctx, csv_path = _fake_deactivation_setup(tmp_path, student_id=4242)

    with patch("itcj2.database.SessionLocal", return_value=session_ctx), \
         patch("itcj2.core.services.session_service.bump_version", return_value=99) as mock_bump, \
         patch("itcj2.core.services.session_service.forget_cached_version") as mock_forget:
        manager = MagicMock()
        manager.attach_mock(db.commit, "db_commit")
        manager.attach_mock(mock_bump, "bump_version")
        manager.attach_mock(mock_forget, "forget_cached_version")

        result = CliRunner().invoke(
            sync_students_agendatec_command, ["--csv-path", str(csv_path), "--commit-every", "500"],
        )

    assert result.exit_code == 0, result.output
    mock_bump.assert_called_once_with(4242, db=db)
    assert fake_student.is_active is False
    mock_forget.assert_called_once_with(4242)

    # Orden: bump_version (atómico con is_active=False) -> commit -> SOLO
    # ENTONCES forget_cached_version. Invertir esto reabre la Carrera A6.
    names_in_order = [c[0] for c in manager.mock_calls]
    idx_bump = names_in_order.index("bump_version")
    idx_commit = names_in_order.index("db_commit")
    idx_forget = names_in_order.index("forget_cached_version")
    assert idx_bump < idx_commit < idx_forget, names_in_order


def test_sync_students_deactivation_skips_student_when_revoke_fails(tmp_path):
    fake_student, db, session_ctx, csv_path = _fake_deactivation_setup(tmp_path, student_id=4343)

    with patch("itcj2.database.SessionLocal", return_value=session_ctx), \
         patch("itcj2.core.services.session_service.bump_version", return_value=None) as mock_bump, \
         patch("itcj2.core.services.session_service.forget_cached_version") as mock_forget:
        result = CliRunner().invoke(
            sync_students_agendatec_command, ["--csv-path", str(csv_path), "--commit-every", "500"],
        )

    assert result.exit_code == 0, result.output
    mock_bump.assert_called_once_with(4343, db=db)
    # No se pudo revocar -> NO se desactiva en silencio (ese es el modo de
    # falla que este plan elimina): el alumno se queda activo.
    assert fake_student.is_active is True
    db.commit.assert_not_called()
    mock_forget.assert_not_called()
    assert "Omitidos por fallo de revocación" in result.output
    assert "Desactivados: 0" in result.output
