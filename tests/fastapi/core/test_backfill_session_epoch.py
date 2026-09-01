"""`core backfill-session-epoch`: la transición de Redis a Postgres.

**Por qué existe este comando.** Producción tiene HOY claves
`authz:v1:sessionver:{uid}` y JWTs vivos con `sv = N` acuñado desde ellas. La
migración `s1e2s3s4v001` siembra `core_users.session_epoch = 0` para todos. Si
la rama se despliega sin backfill, en el cutover:

- todo token con `sv >= 1` falla `sv != 0` y queda DESLOGUEADO — el síntoma del
  incidente del 2026-08-20; y
- todo token ya revocado que quedó en `sv == 0` y sigue dentro de sus 12h de
  expiración vuelve a cuadrar `0 == 0` y AUTENTICA otra vez — la mitad de
  seguridad del mismo incidente, cuentas desactivadas incluidas.

El backfill del plan (Tarea 5, Step 7) escaneaba `session:v1:ver:*`, un prefijo
que en producción está VACÍO (solo existió en un commit intermedio que nadie
desplegó), así que habría reportado cero usuarios y no habría mitigado nada.
Este comando escanea LOS DOS prefijos.

**Lo que estos tests pinnean** es lo que un humano confía a las sesiones de
producción: que el UPDATE es monótono (`WHERE session_epoch < :v`, nunca baja
una época y por tanto nunca resucita una sesión) y que el comando es
re-ejecutable sin efecto.

Redis va falseado a propósito: el comando escanea el keyspace ENTERO de los dos
prefijos, y contra el Redis compartido de dev eso barrería las claves de
sesiones reales y las mezclaría en los conteos. El SQL —la parte que importa—
corre contra Postgres real vía `db_session`.
"""
import fnmatch

import pytest
from click.testing import CliRunner
from sqlalchemy import text

from itcj2.cli.core import backfill_session_epoch_command
from itcj2.core.models.user import User

LEGACY = "authz:v1:sessionver:{uid}"
CURRENT = "session:v1:ver:{uid}"


class _FakeRedis:
    """redis-py síncrono con `decode_responses=True`: claves y valores son `str`."""

    def __init__(self, data: dict):
        self._data = {str(k): str(v) for k, v in data.items()}
        self.deleted: list[str] = []

    def scan_iter(self, match=None, count=None):
        for key in list(self._data):
            if match is None or fnmatch.fnmatchcase(key, match):
                yield key

    def get(self, key):
        return self._data.get(key)

    def delete(self, key):
        self.deleted.append(key)
        self._data.pop(key, None)


@pytest.fixture()
def run_backfill(monkeypatch):
    """Corre el comando con un Redis falso sembrado con `data`."""

    def _run(data: dict, args=()):
        monkeypatch.setattr(
            "itcj2.core.utils.redis_conn.get_redis", lambda: _FakeRedis(data)
        )
        return CliRunner().invoke(backfill_session_epoch_command, list(args))

    return _run


@pytest.fixture()
def run_backfill_tracking_redis(monkeypatch):
    """Como `run_backfill`, pero expone la MISMA instancia de `_FakeRedis` que ve
    el comando durante toda la corrida.

    `run_backfill` liga `get_redis` a una lambda que construye un `_FakeRedis`
    NUEVO cada vez que se llama — invisible desde el test, pero suficiente
    mientras el comando solo llamaba `get_redis()` una vez (para escanear). La
    invalidación post-commit añade una SEGUNDA fuente de llamadas a
    `get_redis()` (una por `forget_cached_version`), y con la lambda original
    cada una vería un `_FakeRedis` distinto, recién copiado de `data` — no se
    podría observar qué se borró. Esta fixture fija una única instancia para
    toda la corrida del comando.
    """

    def _run(data: dict, args=()):
        fake = _FakeRedis(data)
        monkeypatch.setattr("itcj2.core.utils.redis_conn.get_redis", lambda: fake)
        result = CliRunner().invoke(backfill_session_epoch_command, list(args))
        return result, fake

    return _run


@pytest.fixture()
def user(db_session):
    u = User(first_name="Backfill", last_name="Test", is_active=True)
    db_session.add(u)
    db_session.flush()
    return u


def _epoch(db_session, user_id: int) -> int:
    return db_session.execute(
        text("SELECT session_epoch FROM core_users WHERE id = :u"), {"u": user_id}
    ).scalar_one()


def _set_epoch(db_session, user_id: int, value: int) -> None:
    db_session.execute(
        text("UPDATE core_users SET session_epoch = :v WHERE id = :u"),
        {"v": value, "u": user_id},
    )


# ---------------------------------------------------------------------------
# El caso que motiva el comando: el prefijo LEGACY, el único que hay en prod
# ---------------------------------------------------------------------------
def test_backfills_from_the_legacy_prefix(user, db_session, patched_session_local, run_backfill):
    result = run_backfill({LEGACY.format(uid=user.id): 7})

    assert result.exit_code == 0, result.output
    assert _epoch(db_session, user.id) == 7
    assert "filas actualizadas: 1" in result.output


def test_backfills_from_the_current_prefix(user, db_session, patched_session_local, run_backfill):
    """Por si algún día se desplegó el commit intermedio: correcto en los dos casos."""
    result = run_backfill({CURRENT.format(uid=user.id): 5})

    assert result.exit_code == 0, result.output
    assert _epoch(db_session, user.id) == 5


def test_reports_both_prefixes_separately(user, db_session, patched_session_local, run_backfill):
    result = run_backfill({
        LEGACY.format(uid=user.id): 3,
        CURRENT.format(uid=user.id): 4,
    })

    assert result.exit_code == 0, result.output
    assert "escaneadas en authz:v1:sessionver:*: 1" in result.output
    assert "escaneadas en session:v1:ver:*: 1" in result.output
    # El mayor gana sin importar el orden de proceso: el UPDATE es monótono.
    assert _epoch(db_session, user.id) == 4


# ---------------------------------------------------------------------------
# La propiedad que no puede regresionar: NUNCA bajar una época
# ---------------------------------------------------------------------------
def test_never_lowers_an_epoch(user, db_session, patched_session_local, run_backfill):
    """Bajar la época RESUCITA sesiones ya revocadas: es la mitad de seguridad
    del incidente. Una clave de Redis rancia (o desalojada y recreada) no puede
    pisar un `session_epoch` mayor."""
    _set_epoch(db_session, user.id, 9)

    result = run_backfill({LEGACY.format(uid=user.id): 3})

    assert result.exit_code == 0, result.output
    assert _epoch(db_session, user.id) == 9
    assert "filas actualizadas: 0" in result.output
    assert "sin cambio (epoch ya >= valor): 1" in result.output


def test_is_idempotent(user, db_session, patched_session_local, run_backfill):
    """Re-ejecutable: el runbook manda correrlo otra vez tras el rolling restart."""
    data = {LEGACY.format(uid=user.id): 7}

    first = run_backfill(data)
    second = run_backfill(data)

    assert first.exit_code == 0 and second.exit_code == 0, second.output
    assert "filas actualizadas: 1" in first.output
    assert "filas actualizadas: 0" in second.output
    assert "sin cambio (epoch ya >= valor): 1" in second.output
    assert _epoch(db_session, user.id) == 7


def test_equal_value_is_not_an_update(user, db_session, patched_session_local, run_backfill):
    """`<` y no `<=`: reescribir el mismo valor sería ruido, no trabajo."""
    _set_epoch(db_session, user.id, 4)

    result = run_backfill({LEGACY.format(uid=user.id): 4})

    assert "filas actualizadas: 0" in result.output
    assert "sin cambio (epoch ya >= valor): 1" in result.output


# ---------------------------------------------------------------------------
# Robustez: un dato roto no puede tumbar el lote
# ---------------------------------------------------------------------------
def test_a_garbled_value_does_not_abort_the_batch(user, db_session, patched_session_local, run_backfill):
    result = run_backfill({
        LEGACY.format(uid=9999_000_001): "no-soy-un-numero",
        LEGACY.format(uid=user.id): 6,
    })

    assert result.exit_code == 0, result.output
    assert _epoch(db_session, user.id) == 6, "la clave rota no puede llevarse el resto"
    assert "valores ilegibles: 1" in result.output


def test_a_garbled_uid_does_not_abort_the_batch(user, db_session, patched_session_local, run_backfill):
    result = run_backfill({
        "authz:v1:sessionver:no-soy-un-uid": 8,
        LEGACY.format(uid=user.id): 6,
    })

    assert result.exit_code == 0, result.output
    assert _epoch(db_session, user.id) == 6
    assert "valores ilegibles: 1" in result.output


def test_non_positive_values_are_skipped(user, db_session, patched_session_local, run_backfill):
    """0 y negativos no llevan información: 0 es ya el default de la migración."""
    _set_epoch(db_session, user.id, 0)

    result = run_backfill({LEGACY.format(uid=user.id): 0})

    assert result.exit_code == 0, result.output
    assert "valores <= 0 omitidos: 1" in result.output
    assert "filas actualizadas: 0" in result.output


def test_reports_ids_without_a_matching_user(db_session, patched_session_local, run_backfill):
    """Usuarios borrados que dejaron su clave en Redis: se reportan, no se inventan."""
    result = run_backfill({LEGACY.format(uid=9999_000_002): 4})

    assert result.exit_code == 0, result.output
    assert "sin fila en core_users: 1" in result.output
    assert "filas actualizadas: 0" in result.output


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------
def test_dry_run_reports_without_writing(user, db_session, patched_session_local, run_backfill):
    result = run_backfill({LEGACY.format(uid=user.id): 7}, args=["--dry-run"])

    assert result.exit_code == 0, result.output
    assert "filas actualizadas: 1" in result.output, "debe reportar lo que HARÍA"
    assert _epoch(db_session, user.id) == 0, "dry-run no puede escribir"
    assert "DRY-RUN" in result.output


def test_dry_run_classifies_like_the_real_run(user, db_session, patched_session_local, run_backfill):
    _set_epoch(db_session, user.id, 9)

    result = run_backfill({LEGACY.format(uid=user.id): 3}, args=["--dry-run"])

    assert "filas actualizadas: 0" in result.output
    assert "sin cambio (epoch ya >= valor): 1" in result.output
    assert _epoch(db_session, user.id) == 9


def test_empty_keyspace_is_reported_not_crashed(db_session, patched_session_local, run_backfill):
    result = run_backfill({})

    assert result.exit_code == 0, result.output
    assert "escaneadas en authz:v1:sessionver:*: 0" in result.output
    assert "escaneadas en session:v1:ver:*: 0" in result.output


# ---------------------------------------------------------------------------
# Invalidación del caché de Redis tras el backfill (residual del re-review)
#
# El re-run que el runbook manda después del rolling restart ya no encuentra
# Redis vacío: workers nuevos poblaron `session:v1:ver:{uid}` desde Postgres
# con TTL de 1h (`session_service._TTL`). Si el backfill sube `session_epoch`
# en Postgres sin tocar esa clave, `current_version` sigue sirviendo la época
# vieja desde caché hasta que expira — el recovery que promete el runbook se
# demora hasta 1h en vez de ser inmediato. Ver session_service.py:130-136.
# ---------------------------------------------------------------------------
def test_invalidates_the_cache_for_a_row_it_actually_updated(
    user, db_session, patched_session_local, run_backfill_tracking_redis
):
    """La clave `session:v1:ver:{uid}` es a la vez posible fuente del backfill
    (segundo prefijo escaneado) Y el caché real que lee `current_version`. Se
    siembra con un valor viejo (simulando lo que un worker ya cacheó) para
    comprobar que el backfill la borra tras subir Postgres."""
    cache_key = CURRENT.format(uid=user.id)
    result, fake = run_backfill_tracking_redis({
        LEGACY.format(uid=user.id): 7,
        cache_key: 2,  # caché viva, época vieja
    })

    assert result.exit_code == 0, result.output
    assert _epoch(db_session, user.id) == 7
    assert cache_key in fake.deleted


def test_does_not_invalidate_a_row_it_did_not_update(
    user, db_session, patched_session_local, run_backfill_tracking_redis
):
    """Si el UPDATE no tocó la fila (epoch en Postgres ya iba por delante), no
    hay motivo para forzar una relectura — nada cambió."""
    _set_epoch(db_session, user.id, 9)
    cache_key = CURRENT.format(uid=user.id)

    result, fake = run_backfill_tracking_redis({LEGACY.format(uid=user.id): 3})

    assert result.exit_code == 0, result.output
    assert "filas actualizadas: 0" in result.output
    assert cache_key not in fake.deleted
    assert fake.deleted == []


def test_dry_run_does_not_invalidate_anything(
    user, db_session, patched_session_local, run_backfill_tracking_redis
):
    """`--dry-run` no escribe en Postgres; tampoco debe borrar caché de Redis."""
    result, fake = run_backfill_tracking_redis(
        {LEGACY.format(uid=user.id): 7}, args=["--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert "filas actualizadas: 1" in result.output
    assert fake.deleted == []


def test_invalidates_after_commit_not_before(
    user, db_session, patched_session_local, run_backfill, monkeypatch
):
    """Orden exigido por el residual: invalidar ANTES del commit reabre la
    carrera que esta rama ya cerró tres veces — un lector repuebla el caché
    con la época vieja aún no commiteada, y como escribir sobre una clave
    ausente es una subida legítima, la guarda monótona no puede rechazarla.
    Este test fija el orden observable: primero `commit()`, después
    `forget_cached_version`."""
    calls: list[str] = []

    real_commit = db_session.commit

    def _commit_then_record():
        real_commit()
        calls.append("commit")

    def _record_invalidate(uid):
        calls.append("invalidate")

    monkeypatch.setattr(db_session, "commit", _commit_then_record)
    monkeypatch.setattr(
        "itcj2.core.services.session_service.forget_cached_version",
        _record_invalidate,
    )

    result = run_backfill({LEGACY.format(uid=user.id): 7})

    assert result.exit_code == 0, result.output
    assert calls == ["commit", "invalidate"]
