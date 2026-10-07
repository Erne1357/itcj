"""`AuditService` y el contexto de la bitácora (spec 2026-10-07 §4.2, §4.3, §8).

Qué fija
--------
- `safe`: la máscara D9 (claves con password/nip/token/secret/hash -> "***")
  recursiva, el saneo a JSON y que NUNCA truene por datos.
- `changes` / `snapshot`: solo lo que cambió; valores ya saneados.
- `record`: un `db.add`, sin flush ni commit (D8). La fila viaja con la
  transacción del cambio: si la operación revierte, su rastro también (Review
  Focus 1). Acción fuera del vocabulario: `ValueError` en pruebas/dev,
  `module='system'` + warning en producción.
- Contexto: sin petición -> `system`; `audit_context("cli"|"celery", ...)` con
  `request_id` uuid; petición HTTP -> usuario/IP/navegador/ruta/request_id, o
  `public` sin sesión; y que todo eso se vea desde el threadpool, donde corren
  las rutas `def` de TitulaTec.

Las pruebas HTTP van contra la app real (`create_app`, con el middleware de
observabilidad que liga el `scope`) y una ruta mínima que se agrega a ESA
instancia; el contexto de observabilidad también se liga a mano para probar el
resolver sin servidor.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time
from decimal import Decimal

import pytest
from sqlalchemy import event, text


def _svc():
    from itcj2.apps.titulatec.services.audit_service import AuditService
    return AuditService


def _contar(db_session, fn, filtro=None) -> int:
    """Sentencias SQL que emite `fn()` sobre la conexión del test."""
    sentencias: list[str] = []

    def _ver(_conn, _cursor, statement, *_a):
        sentencias.append(statement)

    conn = db_session.connection()
    event.listen(conn, "before_cursor_execute", _ver)
    try:
        fn()
    finally:
        event.remove(conn, "before_cursor_execute", _ver)
    if filtro is not None:
        return sum(1 for s in sentencias if filtro in s)
    return len(sentencias)


def _filas(db_session, **filtros):
    from itcj2.apps.titulatec.models import TitulatecAuditLog
    return (db_session.query(TitulatecAuditLog).filter_by(**filtros)
            .order_by(TitulatecAuditLog.id).all())


# ---------------------------------------------------------------------------
# safe: máscara y saneo
# ---------------------------------------------------------------------------
class _Rebelde:
    def __str__(self):
        raise RuntimeError("no me conviertas")

    def __repr__(self):
        raise RuntimeError("tampoco así")


def test_safe_enmascara_claves_sensibles_en_cualquier_nivel():
    out = _svc().safe({
        "nip": "1234",
        "Password": "secreta",
        "folio": "TT-1",
        "anidado": {"verify_token_hash": "abc", "ok": 1, "nada": None},
        "lista": [{"client_secret": "x", "n": 2}],
        "nip_vacio": None,
    })
    assert out == {
        "nip": "***",
        "Password": "***",
        "folio": "TT-1",
        "anidado": {"verify_token_hash": "***", "ok": 1, "nada": None},
        "lista": [{"client_secret": "***", "n": 2}],
        # Un secreto vacío se queda vacío: "***" diría que había algo.
        "nip_vacio": None,
    }


def test_safe_deja_todo_serializable_a_json():
    import json
    out = _svc().safe({
        "monto": Decimal("850.50"),
        "cuando": datetime(2026, 10, 7, 9, 30),
        "dia": date(2026, 10, 7),
        "hora": time(9, 30),
        "conjunto": {3},
        "tupla": (1, "a"),
        "bytes": b"\x00\x01",
        "nan": float("nan"),
        "uid": uuid.UUID(int=1),
        "objeto": object(),
        7: "llave no textual",
    })
    json.dumps(out)  # no truena
    assert out["monto"] == "850.50"
    assert out["cuando"] == "2026-10-07T09:30:00"
    assert out["dia"] == "2026-10-07"
    assert out["hora"] == "09:30:00"
    assert out["conjunto"] == [3]
    assert out["tupla"] == [1, "a"]
    assert out["bytes"] == "<2 bytes>"
    assert out["nan"] == "nan"
    assert out["uid"] == str(uuid.UUID(int=1))
    assert out["7"] == "llave no textual"
    assert isinstance(out["objeto"], str)


def test_safe_recorta_y_limpia_cadenas():
    svc = _svc()
    assert len(svc.safe("x" * 5000)) == 2000
    assert svc.safe("a\x00b") == "ab"            # PostgreSQL no acepta NUL
    assert svc.safe("\ud800ok") == "?ok"         # sustituto suelto -> no truena al codificar


def test_safe_nunca_truena_por_datos():
    svc = _svc()
    assert isinstance(svc.safe(_Rebelde()), str)
    profundo = cur = {}
    for _ in range(50):
        cur["n"] = {}
        cur = cur["n"]
    svc.safe(profundo)                           # sin RecursionError
    grande = svc.safe(list(range(10_000)))
    assert len(grande) <= 501


# ---------------------------------------------------------------------------
# changes / snapshot
# ---------------------------------------------------------------------------
def test_changes_solo_devuelve_lo_que_cambio():
    antes, despues = _svc().changes(
        {"status": "open", "name": "A", "cap": 30, "solo_antes": 1},
        {"status": "closed", "name": "A", "cap": 30, "solo_despues": 2},
    )
    assert antes == {"status": "open", "solo_antes": 1, "solo_despues": None}
    assert despues == {"status": "closed", "solo_antes": None, "solo_despues": 2}


def test_changes_sin_diferencias_da_dos_vacios():
    assert _svc().changes({"a": 1}, {"a": 1}) == ({}, {})


def test_snapshot_es_json_y_enmascara():
    class _Obj:
        status = "open"
        closes_at = datetime(2026, 11, 1, 23, 59, 59)
        verify_token_hash = "abc"
        monto = Decimal("10.00")

    snap = _svc().snapshot(_Obj(), ["status", "closes_at", "verify_token_hash", "monto",
                                     "no_existe"])
    assert snap == {
        "status": "open",
        "closes_at": "2026-11-01T23:59:59",
        "verify_token_hash": "***",
        "monto": "10.00",
        "no_existe": None,
    }


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------
def test_record_solo_agrega_a_la_sesion_sin_emitir_sql(db_session):
    from itcj2.apps.titulatec.models import TitulatecAuditLog

    def _registrar():
        _svc().record(db_session, "cohort.created", entity_type="cohort", entity_id=7)

    assert _contar(db_session, _registrar) == 0, "record no hace flush ni commit (D8)"
    nuevas = [o for o in db_session.new if isinstance(o, TitulatecAuditLog)]
    assert len(nuevas) == 1
    assert nuevas[0].action == "cohort.created"
    assert nuevas[0].module == "cohorts"
    assert nuevas[0].source == "action"


def test_record_escribe_la_fila_completa_y_sanea(db_session):
    marca = f"motivo {uuid.uuid4().hex}"
    _svc().record(
        db_session, "cohort.window_changed",
        entity_type="cohort", entity_id="42", process_id=9,
        subject="99000001 · " + "N" * 300,
        reason=marca + "\x00",
        before={"closes_at": datetime(2026, 10, 1, 23, 59, 59)},
        after={"closes_at": datetime(2026, 10, 9, 23, 59, 59)},
        payload={"pausados": 3, "nip": "1234"},
    )
    db_session.flush()
    (fila,) = _filas(db_session, reason=marca)
    assert fila.source == "action"
    assert fila.module == "cohorts"
    assert fila.entity_type == "cohort" and fila.entity_id == 42
    assert fila.process_id == 9
    assert len(fila.subject_label) == 160
    assert fila.before == {"closes_at": "2026-10-01T23:59:59"}
    assert fila.after == {"closes_at": "2026-10-09T23:59:59"}
    assert fila.payload == {"pausados": 3, "nip": "***"}
    assert fila.actor_kind == "system" and fila.actor_id is None
    assert fila.occurred_at is not None


def test_record_sin_json_deja_null_de_sql(db_session):
    """`before/after/payload` ausentes son NULL de SQL, no el JSON `null`: la
    UI y cualquier `WHERE before IS NULL` los distinguen."""
    marca = f"sin json {uuid.uuid4().hex}"
    _svc().record(db_session, "cohort.created", reason=marca)
    _svc().record(db_session, "cohort.created", reason=marca + " vacio",
                  before={}, after={}, payload={})
    db_session.flush()
    nulos = db_session.execute(text(
        "SELECT before IS NULL, after IS NULL, payload IS NULL "
        "FROM titulatec_audit_log WHERE reason IN (:a, :b)"),
        {"a": marca, "b": marca + " vacio"}).all()
    assert nulos == [(True, True, True), (True, True, True)]


def test_el_modelo_guarda_none_como_null_de_sql(db_session):
    """`JSON(none_as_null=True)` en el modelo: quien construya la fila a mano
    (la página, una prueba) con `before=None` también deja NULL de SQL."""
    from itcj2.apps.titulatec.models import TitulatecAuditLog
    marca = f"modelo {uuid.uuid4().hex}"
    db_session.add(TitulatecAuditLog(source="action", action="cohort.created",
                                     module="cohorts", actor_kind="system", reason=marca,
                                     before=None, after=None, payload=None))
    db_session.flush()
    nulos = db_session.execute(text(
        "SELECT before IS NULL, after IS NULL, payload IS NULL "
        "FROM titulatec_audit_log WHERE reason = :m"), {"m": marca}).one()
    assert tuple(nulos) == (True, True, True)


def test_varios_record_distintos_en_un_flush_son_un_solo_insert(db_session):
    """Cada fila de `record` lleva el MISMO juego de llaves (las JSON también,
    aunque valgan None): el ORM las junta en un solo INSERT, sin importar qué
    trae cada una."""
    marca = f"lote {uuid.uuid4().hex}"
    svc = _svc()

    def _flush():
        svc.record(db_session, "cohort.created", reason=marca)
        svc.record(db_session, "cohort.window_changed", reason=marca, entity_id=3,
                   before={"a": 1}, after={"a": 2})
        svc.record(db_session, "window.paused", reason=marca, payload={"n": 1},
                   actor_id=9, process_id=4, subject="99000001 · X")
        svc.record(db_session, "cohort.donation_changed", reason=marca, after={"m": "1"})
        db_session.flush()

    assert _contar(db_session, _flush, filtro="titulatec_audit_log") == 1
    assert len(_filas(db_session, reason=marca)) == 4


@pytest.mark.parametrize("valor", [
    2 ** 70, -(2 ** 70), float("inf"), float("nan"), Decimal("Infinity"),
    Decimal("NaN"), "no-es-numero", True,
])
def test_ids_imposibles_quedan_null_sin_tronar(db_session, valor):
    """Spec §4.2: armar la fila no puede fallar por datos. Un id que no cabe en
    su columna (o no es número) se guarda NULL; nunca llega a PostgreSQL como
    «integer out of range», que abortaría la transacción del negocio."""
    marca = f"rango {uuid.uuid4().hex}"
    _svc().record(db_session, "cohort.created", reason=marca,
                  entity_id=valor, process_id=valor, actor_id=valor)
    db_session.flush()
    (fila,) = _filas(db_session, reason=marca)
    assert (fila.entity_id, fila.process_id) == (None, None)
    assert fila.actor_id is None and fila.actor_kind == "system"


def test_process_id_respeta_los_32_bits_de_su_columna(db_session):
    from itcj2.apps.titulatec.services.audit_context import INT32, INT64, to_db_int
    assert to_db_int(2 ** 31 - 1, INT32) == 2 ** 31 - 1
    assert to_db_int(2 ** 31, INT32) is None
    assert to_db_int(2 ** 31, INT64) == 2 ** 31
    assert to_db_int(-(2 ** 63), INT64) == -(2 ** 63)
    assert to_db_int(2 ** 63, INT64) is None
    assert to_db_int("42") == 42 and to_db_int(Decimal("7")) == 7

    marca = f"int32 {uuid.uuid4().hex}"
    _svc().record(db_session, "cohort.created", reason=marca,
                  process_id=2 ** 40, entity_id=2 ** 40)
    db_session.flush()
    (fila,) = _filas(db_session, reason=marca)
    assert fila.process_id is None and fila.entity_id == 2 ** 40


def test_etiqueta_de_cli_con_sustituto_suelto_no_rompe_el_flush(db_session):
    """Un usuario del SO decodificado con `surrogateescape` llega con
    sustitutos sueltos: el contexto los limpia igual que el servicio, así que ni
    `record` ni la escucha (que escribe la etiqueta tal cual) truenan."""
    from itcj2.apps.titulatec.services.audit_context import audit_context
    marca = f"sustituto {uuid.uuid4().hex}"
    with audit_context("cli", label="cli: audit-purge (us\udcffer)") as ctx:
        assert ctx.actor_label == "cli: audit-purge (us?er)"
        _svc().record(db_session, "system.cli_command", reason=marca)
        db_session.flush()
    (fila,) = _filas(db_session, reason=marca)
    assert fila.actor_label == "cli: audit-purge (us?er)"


def test_record_con_accion_desconocida_truena_en_pruebas(db_session):
    with pytest.raises(ValueError, match="no.existe"):
        _svc().record(db_session, "no.existe")


def test_record_con_accion_desconocida_en_produccion_cae_en_system(db_session, monkeypatch,
                                                                   caplog):
    from itcj2.apps.titulatec.services import audit_service
    monkeypatch.setattr(audit_service, "_strict", lambda: False)
    marca = f"desconocida {uuid.uuid4().hex}"
    with caplog.at_level(logging.WARNING, logger=audit_service.logger.name):
        _svc().record(db_session, "algo.inventado", reason=marca)
    db_session.flush()
    (fila,) = _filas(db_session, reason=marca)
    assert fila.module == "system" and fila.action == "algo.inventado"
    assert "algo.inventado" in caplog.text


# ---------------------------------------------------------------------------
# Review Focus 1: si la operación revierte, su rastro también
# ---------------------------------------------------------------------------
def test_rollback_despues_de_record_no_deja_fila(db_session):
    marca = f"rollback {uuid.uuid4().hex}"
    _svc().record(db_session, "cohort.created", reason=marca)
    db_session.flush()
    assert len(_filas(db_session, reason=marca)) == 1
    db_session.rollback()
    assert _filas(db_session, reason=marca) == []


def test_operacion_que_falla_despues_de_record_no_deja_aprobado_fantasma(db_session):
    """Un service registra y luego su commit truena (aquí, una FK rota): el
    `rollback` del service se lleva la fila de la bitácora."""
    from sqlalchemy.exc import IntegrityError
    from itcj2.apps.titulatec.models import CohortReviewDay

    marca = f"fantasma {uuid.uuid4().hex}"

    def _servicio(db):
        _svc().record(db, "cohort.review_day_toggled", reason=marca)
        db.add(CohortReviewDay(cohort_id=-999_999, date=date(2091, 1, 1)))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise ValueError("no se pudo")

    with pytest.raises(ValueError):
        _servicio(db_session)
    assert _filas(db_session, reason=marca) == []


# ---------------------------------------------------------------------------
# Contexto: sin petición, CLI/Celery, actor explícito
# ---------------------------------------------------------------------------
def test_sin_peticion_el_contexto_es_system():
    from itcj2.apps.titulatec.services.audit_context import current_audit_context
    ctx = current_audit_context()
    assert ctx.actor_kind == "system"
    assert ctx.actor_id is None and ctx.actor_label is None
    assert ctx.ip is None and ctx.user_agent is None and ctx.route is None


def test_audit_context_cli_genera_request_id_y_se_deshace():
    from itcj2.apps.titulatec.services.audit_context import (
        audit_context, current_audit_context,
    )
    with audit_context("cli", label="cli: audit-purge (root)") as ctx:
        visto = current_audit_context()
        assert visto is ctx
        assert visto.actor_kind == "cli"
        assert visto.actor_label == "cli: audit-purge (root)"
        uuid.UUID(visto.request_id)                     # es un uuid
        with audit_context("celery", label="celery: titulatec.sii_sweep") as interno:
            assert current_audit_context().actor_kind == "celery"
            assert interno.request_id != visto.request_id
        assert current_audit_context() is ctx           # el anidado se deshizo
    assert current_audit_context().actor_kind == "system"


def test_audit_context_rechaza_un_tipo_desconocido():
    from itcj2.apps.titulatec.services.audit_context import audit_context
    with pytest.raises(ValueError):
        with audit_context("robot"):
            pass


def test_record_toma_el_contexto_cli(db_session):
    from itcj2.apps.titulatec.services.audit_context import audit_context
    marca = f"cli {uuid.uuid4().hex}"
    with audit_context("cli", label="cli: init-bitacora (root)") as ctx:
        _svc().record(db_session, "system.cli_command", reason=marca)
    db_session.flush()
    (fila,) = _filas(db_session, reason=marca)
    assert fila.actor_kind == "cli" and fila.actor_id is None
    assert fila.actor_label == "cli: init-bitacora (root)"
    assert fila.request_id == ctx.request_id
    assert fila.module == "system"


def test_el_actor_explicito_gana_al_contexto(db_session):
    from itcj2.apps.titulatec.services.audit_context import audit_context
    marca = f"actor {uuid.uuid4().hex}"
    _svc().record(db_session, "cohort.created", reason=marca + " sys", actor_id=501)
    with audit_context("celery", label="celery: titulatec.email_dispatch"):
        _svc().record(db_session, "cohort.created", reason=marca + " cel", actor_id=502)
    db_session.flush()
    (sys_,) = _filas(db_session, reason=marca + " sys")
    (cel,) = _filas(db_session, reason=marca + " cel")
    assert (sys_.actor_id, sys_.actor_kind, sys_.actor_label) == (501, "user", None)
    # En CLI/Celery el tipo sigue diciendo POR DÓNDE entró; el id, a nombre de quién.
    assert (cel.actor_id, cel.actor_kind) == (502, "celery")
    assert cel.actor_label == "celery: titulatec.email_dispatch"


# ---------------------------------------------------------------------------
# Contexto HTTP: el resolver, con el scope ligado a mano
# ---------------------------------------------------------------------------
def _scope(headers=(), user=None, client=("10.0.0.9", 5555), path="/titulatec/admin/x/1"):
    scope = {
        "type": "http",
        "path": path,
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers],
        "client": client,
        "state": {},
    }
    if user is not None:
        scope["state"]["current_user"] = {"sub": str(user), "role": ""}
    return scope


def _resolver_con(scope, request_id="ab" * 16):
    from itcj2.apps.titulatec.services.audit_context import current_audit_context
    from itcj2.observability.context import bind, reset
    tokens = bind(scope=scope, request_id=request_id)
    try:
        return current_audit_context()
    finally:
        reset(tokens)


def test_peticion_con_usuario():
    ctx = _resolver_con(_scope(user=77, headers=[("User-Agent", "Firefox/130")]))
    assert ctx.actor_kind == "user" and ctx.actor_id == 77
    assert ctx.actor_label is None
    assert ctx.request_id == "ab" * 16
    assert ctx.ip == "10.0.0.9"                      # sin cabeceras: el peer
    assert ctx.user_agent == "Firefox/130"
    assert ctx.route == "/titulatec/admin/x/1"       # sin ruta enrutada: el path


def test_peticion_sin_sesion_es_public():
    ctx = _resolver_con(_scope())
    assert ctx.actor_kind == "public" and ctx.actor_id is None


@pytest.mark.parametrize("headers, ip", [
    ([("X-Real-IP", " 203.0.113.7 "), ("X-Forwarded-For", "1.1.1.1, 2.2.2.2")], "203.0.113.7"),
    ([("X-Forwarded-For", "6.6.6.6, 198.51.100.9")], "198.51.100.9"),
    ([], "10.0.0.9"),
])
def test_ip_con_la_regla_de_client_ip(headers, ip):
    """X-Real-IP primero; si no, la de MÁS A LA DERECHA de X-Forwarded-For (la
    izquierda la escribe el cliente); si no, el peer (`core/utils/client_ip.py`)."""
    assert _resolver_con(_scope(headers=headers)).ip == ip


def test_el_navegador_se_recorta_a_la_columna():
    ctx = _resolver_con(_scope(headers=[("User-Agent", "U" * 500)]))
    assert len(ctx.user_agent) == 200


# ---------------------------------------------------------------------------
# Contexto HTTP de verdad: middleware + ruta `def` (threadpool)
# ---------------------------------------------------------------------------
@pytest.fixture()
def ruta_sonda(client):
    """Agrega a ESTA instancia de la app una ruta `def` que devuelve su contexto."""
    from itcj2.apps.titulatec.services.audit_context import current_audit_context

    def _sonda(n: int):
        import dataclasses
        return dataclasses.asdict(current_audit_context())

    client.app.add_api_route("/titulatec/__sonda_bitacora/{n}", _sonda, methods=["GET"])
    return client


def test_ruta_def_ve_el_contexto_del_usuario(ruta_sonda, make_user, client_as):
    usuario = make_user()
    resp = client_as(usuario).get("/titulatec/__sonda_bitacora/5",
                                  headers={"X-Real-IP": "203.0.113.50",
                                           "User-Agent": "Sonda/1.0"})
    assert resp.status_code == 200, resp.text
    ctx = resp.json()
    assert ctx["actor_kind"] == "user" and ctx["actor_id"] == usuario.id
    assert ctx["ip"] == "203.0.113.50"
    assert ctx["user_agent"] == "Sonda/1.0"
    assert ctx["route"] == "/titulatec/__sonda_bitacora/{n}"      # plantilla, no el path
    assert ctx["request_id"] == resp.headers["x-request-id"]


def test_ruta_def_sin_sesion_es_public(ruta_sonda):
    ruta_sonda.cookies.clear()
    ctx = ruta_sonda.get("/titulatec/__sonda_bitacora/1").json()
    assert ctx["actor_kind"] == "public" and ctx["actor_id"] is None
    assert ctx["request_id"]


def test_audit_context_cruza_al_threadpool():
    """Lo que liga el CLI/Celery también lo ve un `anyio.to_thread` (las
    ContextVars se copian al hilo)."""
    import anyio
    from itcj2.apps.titulatec.services.audit_context import (
        audit_context, current_audit_context,
    )

    async def _main():
        with audit_context("celery", label="celery: prueba") as ctx:
            visto = await anyio.to_thread.run_sync(current_audit_context)
            return ctx, visto

    ctx, visto = anyio.run(_main)
    assert visto == ctx and visto.actor_kind == "celery"
