"""Instantánea del tablero: etapa + pelota + días sin movimiento (Task 3).

Spec `docs/superpowers/specs/2026-10-14-titulatec-tablero-design.md` §4.1-§4.4.

Dos partes:

1. **Puras** (sin BD): `classify_request` / `classify_process`, una prueba por
   fila de §4.3 y §4.4, más los bordes que fija el brief (doble pelota, cita
   futura agendada hace 20 días = «Al día», cita de ayer sin cerrar, `no_show`,
   fase 2 rechazada, umbrales 6/7/13/14).
2. **Con BD** (`db_session` + fábricas del conftest): `load_snapshot` respeta
   convocatoria y carreras, el cubo «Sin carrera» solo con `include_unmapped`,
   `on_hold` aparte, `cancelled` fuera y presupuesto de consultas FIJO (3 vs 12
   procesos).

«Hoy» siempre entra como parámetro: las puras usan una fecha fija; las de BD,
`db_now().date()` (nunca `date.today()`: el runner de CI está en UTC).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from itertools import count
from types import SimpleNamespace

import pytest

from itcj2.apps.titulatec.services import report_snapshot as rs

HOY = date(2026, 10, 14)
CFG = rs.ReportConfig(warn_days=7, crit_days=14)


def _hace(dias: int, hora: int = 10) -> datetime:
    """Un `datetime` naive `dias` antes de HOY (negativo = en el futuro)."""
    return datetime.combine(HOY - timedelta(days=dias), time(hora))


def _req(status="pending_review", **kw) -> rs.RequestRow:
    base = {"id": 1, "cohort_id": 10, "program_id": 20, "status": status,
            "first_name": "ANA", "last_name": "LOPEZ", "middle_name": None,
            "control_number": "99000001", "created_at": _hace(3),
            "reviewed_at": None, "updated_at": _hace(3),
            "access_granted_at": None, "verify_expires_at": _hace(-10)}
    base.update(kw)
    return rs.RequestRow(**base)


def _proc(**kw) -> rs.ProcessRow:
    base = {"id": 5, "cohort_id": 10, "program_id": 20, "process_status": "active",
            "current_phase": 1, "created_at": _hace(30), "last_event_at": _hace(2),
            "first_name": "LUIS", "last_name": "PEREZ", "middle_name": None,
            "control_number": "99000002", "pending_docs": 0,
            "phase2_status": None, "phase2_completed_at": None, "phase2_reviewed_by_id": None,
            "appt_status": None, "appt_scheduled_at": None, "appt_owner_id": None,
            "blockers": ()}
    base.update(kw)
    return rs.ProcessRow(**base)


def _fase2(**kw) -> rs.ProcessRow:
    """Proceso en fase 2 SIN veredicto (la fábrica la deja `in_progress`)."""
    kw.setdefault("current_phase", 2)
    kw.setdefault("phase2_status", "in_progress")
    return _proc(**kw)


def _actores(item) -> list[str]:
    return [actor for actor, _ in item.balls]


# ===========================================================================
# 0. Constantes (contrato con Task 4/5/6 y la paleta validada de §7)
# ===========================================================================
def test_la_solicitud_legado_se_llama_anterior_por_revisar():
    """Ronda 0: `unverified` es legado que Escolares revisa (ya no hay correo
    que confirmar)."""
    assert {c: label for c, label, _ in rs.STAGES}["req_unverified"] == (
        "Solicitud anterior (por revisar)")


def test_las_8_etapas_en_orden_y_cada_una_con_su_grupo():
    assert [c for c, _, _ in rs.STAGES] == [
        "req_unverified", "req_review", "req_access", "req_approved",
        "docs", "requisitos", "cita", "liberado"]
    grupos = {c for c, _, _ in rs.STAGE_GROUPS}
    assert all(g in grupos for _, _, g in rs.STAGES)
    assert all(label for _, label, _ in rs.STAGES)


def test_los_5_grupos_de_etapa_con_la_rampa_validada():
    assert [(c, color) for c, _, color in rs.STAGE_GROUPS] == [
        ("solicitud", "#86b6ef"), ("documentos", "#3987e5"), ("requisitos", "#256abf"),
        ("cita", "#184f95"), ("liberado", "#0d366b")]


def test_los_5_actores_en_orden_fijo_con_su_color():
    assert rs.ACTORS == [
        ("escolares", "Escolares", "#2a78d6"),
        ("alumno", "Alumno", "#eb6834"),
        ("gtv", "GTV", "#1baf7a"),
        ("biblioteca", "Biblioteca/Caja", "#eda100"),
        ("computo", "Cómputo", "#e87ba4"),
    ]


def test_la_config_sale_de_los_umbrales_de_titulatec(monkeypatch):
    from itcj2.config import get_settings

    monkeypatch.setattr(get_settings(), "TITULATEC_IDLE_WARN_DAYS", 3)
    monkeypatch.setattr(get_settings(), "TITULATEC_IDLE_CRIT_DAYS", 9)
    assert rs.ReportConfig.from_settings() == rs.ReportConfig(warn_days=3, crit_days=9)


def test_la_config_es_inmutable():
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        CFG.warn_days = 1


def test_cada_estado_vivo_de_solicitud_tiene_etapa():
    """Un estado nuevo en `OPEN_STATUSES` sin regla aquí truena en la prueba,
    no en la página de la jefa."""
    from itcj2.apps.titulatec.models.enrollment_request import OPEN_STATUSES

    for status in OPEN_STATUSES:
        item = rs.classify_request(_req(status), HOY, CFG)
        assert item.stage in {c for c, _, _ in rs.STAGES}, status
        assert item.balls, status


def test_cada_bloqueo_del_gate_tiene_su_pelota():
    """`ClearanceGate.BLOCKERS` es un conjunto CERRADO; cada código se traduce
    a una pelota propia (invariante 2: aquí no se re-deriva el estado)."""
    from itcj2.apps.titulatec.services.clearance_gate import BLOCKERS

    actores = {a for a, _, _ in rs.ACTORS}
    for code in BLOCKERS:
        item = rs.classify_process(_fase2(blockers=(code,)), HOY, CFG)
        assert len(item.balls) == 1, code
        assert item.balls[0][0] in actores, code
        assert item.balls[0][1] != rs.MOTIVE_UNKNOWN_BLOCKER, code


# ===========================================================================
# 1. Solicitudes (§4.2/§4.3, filas req_*)
# ===========================================================================
@pytest.mark.parametrize("status, etapa, pelota", [
    # Desviación documentada: `unverified` es LEGADO (ya no se escribe) y la liga
    # de confirmación ya no existe -`verify()` la responde `invalid`-; la bandeja
    # la lista en «Por revisar · anterior». Quien la mueve es Escolares (spec §4.3
    # corregida: motivo «Revisar solicitud (legado)»).
    ("unverified", "req_unverified", ("escolares", "Revisar solicitud (legado)")),
    ("verified", "req_review", ("escolares", "Revisar solicitud")),
    ("pending_review", "req_review", ("escolares", "Revisar solicitud")),
    ("awaiting_access", "req_access", ("computo", "Dar NIP")),
    ("approved", "req_approved", ("alumno", "Activar su cuenta")),
])
def test_solicitud_etapa_y_pelota(status, etapa, pelota):
    item = rs.classify_request(_req(status), HOY, CFG)
    assert item.kind == "request"
    assert item.stage == etapa
    assert item.balls == (pelota,)
    assert item.pending_docs == 0 and item.ready_to_book is False
    assert item.appt_owner_id is None and item.appt_date is None
    assert item.liberated_on is None and item.liberated_by_id is None


def test_solicitud_por_revisar_cuenta_desde_que_se_creo():
    item = rs.classify_request(
        _req("pending_review", created_at=_hace(15), reviewed_at=_hace(1),
             updated_at=_hace(1)), HOY, CFG)
    assert item.idle_days == 15
    assert item.level == "crit"


def test_solicitud_anterior_legado_cuenta_desde_que_se_creo():
    item = rs.classify_request(_req("unverified", created_at=_hace(8)), HOY, CFG)
    assert item.idle_days == 8 and item.level == "warn"


@pytest.mark.parametrize("status", ["awaiting_access", "approved"])
def test_en_computo_o_aprobada_cuenta_desde_la_revision(status):
    item = rs.classify_request(
        _req(status, created_at=_hace(30), reviewed_at=_hace(5), updated_at=_hace(1)),
        HOY, CFG)
    assert item.idle_days == 5 and item.level == "ok"


@pytest.mark.parametrize("revisada, acceso, dias", [
    (10, 3, 3),          # D10: Cómputo dio acceso CON cuenta -> la liga salió al dar acceso
    (3, 10, 3),          # acceso viejo (una D10 devuelta lo conserva): manda la revisión
    (None, 4, 4),
    (6, None, 6),
])
def test_aprobada_cuenta_desde_lo_ultimo_entre_revision_y_acceso(revisada, acceso, dias):
    item = rs.classify_request(
        _req("approved", created_at=_hace(30), updated_at=_hace(1),
             reviewed_at=None if revisada is None else _hace(revisada),
             access_granted_at=None if acceso is None else _hace(acceso)),
        HOY, CFG)
    assert item.idle_days == dias


def test_en_computo_ignora_un_acceso_viejo():
    """`awaiting_access` solo se alcanza al aprobar Escolares (`reviewed_at`);
    un `access_granted_at` ahí es de un ciclo anterior."""
    item = rs.classify_request(
        _req("awaiting_access", created_at=_hace(30), reviewed_at=_hace(8),
             access_granted_at=_hace(2), updated_at=_hace(1)), HOY, CFG)
    assert item.idle_days == 8


@pytest.mark.parametrize("vence, pelota", [
    (_hace(1, 23), ("escolares", "Reenviar liga")),         # venció ayer
    (_hace(40), ("escolares", "Reenviar liga")),
    (None, ("escolares", "Reenviar liga")),                 # sin vigencia = vencida (servicio)
    (_hace(0, 23), ("alumno", "Activar su cuenta")),        # vence HOY más tarde: vigente
    (_hace(0, 0), ("alumno", "Activar su cuenta")),         # granularidad de día (ver reporte)
    (_hace(-1, 8), ("alumno", "Activar su cuenta")),
])
def test_aprobada_con_la_liga_vencida_es_de_escolares(vence, pelota):
    item = rs.classify_request(
        _req("approved", reviewed_at=_hace(25), verify_expires_at=vence), HOY, CFG)
    assert item.stage == "req_approved"
    assert item.balls == (pelota,)
    assert item.href.startswith("/titulatec/admin/solicitudes?status=approved&")


def test_la_vigencia_de_la_liga_solo_importa_en_aprobadas():
    for status in ("pending_review", "awaiting_access", "unverified"):
        item = rs.classify_request(_req(status, verify_expires_at=None), HOY, CFG)
        assert item.balls[0][1] != "Reenviar liga", status


@pytest.mark.parametrize("status", ["awaiting_access", "approved"])
def test_sin_revision_cae_a_updated_at(status):
    item = rs.classify_request(
        _req(status, created_at=_hace(30), reviewed_at=None, updated_at=_hace(9)),
        HOY, CFG)
    assert item.idle_days == 9 and item.level == "warn"


def test_solicitud_etiqueta_y_liga_a_la_pestana_correcta():
    item = rs.classify_request(
        _req("awaiting_access", id=77, cohort_id=3, program_id=None,
             first_name="ANA", last_name="LOPEZ", middle_name="GARCIA",
             control_number="C99000001"), HOY, CFG)
    assert item.id == 77 and item.cohort_id == 3 and item.program_id is None
    assert item.label == "ANA LOPEZ GARCIA · C99000001"
    assert item.control == "C99000001"
    # La bandeja abre por omisión en «Por revisar»: sin `status` una solicitud
    # en Cómputo no aparecería con la búsqueda (desviación documentada).
    assert item.href == "/titulatec/admin/solicitudes?status=awaiting_access&q=C99000001"


@pytest.mark.parametrize("status, tab", [
    ("unverified", "pending_review"), ("verified", "pending_review"),
    ("pending_review", "pending_review"), ("approved", "approved"),
])
def test_la_liga_de_la_solicitud_abre_su_pestana(status, tab):
    item = rs.classify_request(_req(status, control_number="99000001"), HOY, CFG)
    assert item.href == f"/titulatec/admin/solicitudes?status={tab}&q=99000001"


def test_un_estado_de_solicitud_que_no_es_pendiente_no_se_clasifica():
    for status in ("converted", "rejected"):
        with pytest.raises(ValueError):
            rs.classify_request(_req(status), HOY, CFG)


# ===========================================================================
# 2. Documentos iniciales (fase 1)
# ===========================================================================
def test_docs_con_alguno_por_dictaminar_es_de_escolares():
    item = rs.classify_process(_proc(current_phase=1, pending_docs=2), HOY, CFG)
    assert item.stage == "docs"
    assert item.balls == (("escolares", "Dictaminar documentos"),)
    assert item.pending_docs == 2


def test_docs_sin_pendientes_es_del_alumno():
    item = rs.classify_process(_proc(current_phase=1, pending_docs=0), HOY, CFG)
    assert item.stage == "docs"
    assert item.balls == (("alumno", "Subir o corregir documentos"),)


def test_proceso_etiqueta_y_liga_al_expediente():
    item = rs.classify_process(_proc(id=42, cohort_id=3, program_id=7), HOY, CFG)
    assert item.kind == "process"
    assert item.id == 42 and item.cohort_id == 3 and item.program_id == 7
    assert item.label == "LUIS PEREZ · 99000002"
    assert item.control == "99000002"
    assert item.href == "/titulatec/admin/processes/42"


def test_proceso_sin_numero_de_control_no_pinta_el_separador():
    item = rs.classify_process(_proc(control_number=None), HOY, CFG)
    assert item.label == "LUIS PEREZ"
    assert item.control == ""


# ===========================================================================
# 3. Requisitos de cotejo (fase 2 sin cita vigente activa) — filas que se SUMAN
# ===========================================================================
@pytest.mark.parametrize("bloqueo, pelota", [
    ("survey_missing", ("alumno", "Llenar encuesta de egresados")),
    ("survey_in_review", ("gtv", "Liberar encuesta")),
    ("survey_rejected", ("alumno", "Corregir encuesta")),
    ("library_pending", ("biblioteca", "Registrar no adeudo")),
    ("library_awaiting_payment", ("alumno", "Pagar en Caja")),
    # Desviación documentada: «Con observaciones» detiene al egresado y el correo
    # le pide acudir a Biblioteca a aclararlas; la pelota es del alumno.
    ("library_observed", ("alumno", "Atender observación de Biblioteca")),
])
def test_requisito_pendiente_y_su_pelota(bloqueo, pelota):
    item = rs.classify_process(_fase2(blockers=(bloqueo,)), HOY, CFG)
    assert item.stage == "requisitos"
    assert item.balls == (pelota,)
    assert item.ready_to_book is False


def test_todo_liberado_y_sin_cita_es_agendar_del_alumno():
    item = rs.classify_process(_fase2(blockers=()), HOY, CFG)
    assert item.stage == "requisitos"
    assert item.balls == (("alumno", "Agendar cita"),)
    assert item.ready_to_book is True


def test_doble_pelota_encuesta_en_gtv_y_no_adeudo_en_biblioteca():
    item = rs.classify_process(
        _fase2(blockers=("survey_in_review", "library_pending")), HOY, CFG)
    assert item.balls == (("gtv", "Liberar encuesta"),
                          ("biblioteca", "Registrar no adeudo"))
    assert item.ready_to_book is False


def test_doble_pelota_encuesta_en_gtv_y_pago_en_caja():
    item = rs.classify_process(
        _fase2(blockers=("survey_in_review", "library_awaiting_payment")), HOY, CFG)
    # Orden fijo de ACTORS (alumno antes que gtv), una entrada por actor.
    assert item.balls == (("alumno", "Pagar en Caja"), ("gtv", "Liberar encuesta"))


def test_dos_motivos_del_mismo_actor_cuentan_una_sola_pelota():
    """Encuesta sin enviar + pago pendiente: las dos son del alumno. Una sola
    entrada por actor, con los dos motivos: «espera a dos áreas» cuenta
    actores, no motivos."""
    item = rs.classify_process(
        _fase2(blockers=("survey_missing", "library_awaiting_payment")), HOY, CFG)
    assert item.balls == (("alumno", "Llenar encuesta de egresados · Pagar en Caja"),)


def test_una_cita_cancelada_no_cuenta_como_vigente():
    item = rs.classify_process(
        _fase2(appt_status="cancelled", appt_scheduled_at=_hace(-3), blockers=()),
        HOY, CFG)
    assert item.stage == "requisitos"
    assert item.balls == (("alumno", "Agendar cita"),)
    assert item.appt_date is None and item.appt_owner_id is None


# ===========================================================================
# 4. En cita de cotejo
# ===========================================================================
@pytest.mark.parametrize("estado", ["scheduled", "confirmed"])
@pytest.mark.parametrize("dias_a_la_cita", [0, 6])
def test_cita_futura_agendada_hace_20_dias_esta_al_dia(estado, dias_a_la_cita):
    """En agenda: sin pelota y NUNCA atorado, aunque el último movimiento (el
    agendado) sea de hace 20 días."""
    item = rs.classify_process(
        _fase2(appt_status=estado, appt_scheduled_at=_hace(-dias_a_la_cita, 12),
               appt_owner_id=900, last_event_at=_hace(20), created_at=_hace(40),
               blockers=("library_pending",)),
        HOY, CFG)
    assert item.stage == "cita"
    assert item.balls == ()
    assert item.idle_days == 20
    assert item.level == "ok"
    assert item.appt_date == HOY + timedelta(days=dias_a_la_cita)
    assert item.appt_owner_id == 900
    assert item.ready_to_book is False


@pytest.mark.parametrize("estado", ["scheduled", "confirmed", "in_progress"])
@pytest.mark.parametrize("dias_quieto, nivel", [(15, "crit"), (8, "warn"), (1, "ok")])
def test_cita_de_ayer_sin_cerrar_es_de_escolares(estado, dias_quieto, nivel):
    item = rs.classify_process(
        _fase2(appt_status=estado, appt_scheduled_at=_hace(1), appt_owner_id=900,
               last_event_at=_hace(dias_quieto), created_at=_hace(40)),
        HOY, CFG)
    assert item.stage == "cita"
    assert item.balls == (("escolares", "Cerrar cita"),)
    assert item.idle_days == dias_quieto
    assert item.level == nivel
    assert item.appt_date == HOY - timedelta(days=1)


def test_cita_en_curso_hoy_la_cierra_escolares():
    item = rs.classify_process(
        _fase2(appt_status="in_progress", appt_scheduled_at=_hace(0), last_event_at=_hace(0)),
        HOY, CFG)
    assert item.balls == (("escolares", "Cerrar cita"),)
    assert item.level == "ok"


def test_atendida_sin_dictamen_es_de_escolares():
    item = rs.classify_process(
        _fase2(appt_status="attended", appt_scheduled_at=_hace(2)), HOY, CFG)
    assert item.stage == "cita"
    assert item.balls == (("escolares", "Dictaminar fase 2"),)
    assert item.ready_to_book is False


def test_atendida_sin_dictamen_suma_las_liberaciones_abiertas():
    item = rs.classify_process(
        _fase2(appt_status="attended", appt_scheduled_at=_hace(2),
               blockers=("survey_in_review", "library_pending")), HOY, CFG)
    assert item.balls == (("escolares", "Dictaminar fase 2"),
                          ("gtv", "Liberar encuesta"),
                          ("biblioteca", "Registrar no adeudo"))


def test_no_show_es_reagendar_del_alumno():
    item = rs.classify_process(
        _fase2(appt_status="no_show", appt_scheduled_at=_hace(3), appt_owner_id=900),
        HOY, CFG)
    assert item.stage == "cita"
    assert item.balls == (("alumno", "Reagendar"),)
    # Tras un `no_show` sí puede agendar otra (SelfBookingService.cita_ocupa_el_cotejo).
    assert item.ready_to_book is True
    assert item.appt_owner_id == 900


def test_no_show_con_requisitos_abiertos_no_esta_listo():
    item = rs.classify_process(
        _fase2(appt_status="no_show", appt_scheduled_at=_hace(3),
               blockers=("survey_in_review",)), HOY, CFG)
    assert item.balls == (("alumno", "Reagendar"), ("gtv", "Liberar encuesta"))
    assert item.ready_to_book is False


# ===========================================================================
# 5. Fase 2 rechazada
# ===========================================================================
def test_fase_2_rechazada_es_del_alumno():
    item = rs.classify_process(_fase2(phase2_status="rejected"), HOY, CFG)
    assert item.stage == "requisitos"
    assert item.balls == (("alumno", "Corregir lo señalado"),)
    assert item.ready_to_book is True


def test_fase_2_rechazada_tras_el_cotejo_sigue_siendo_del_alumno():
    item = rs.classify_process(
        _fase2(phase2_status="rejected", appt_status="attended",
               appt_scheduled_at=_hace(4)), HOY, CFG)
    assert item.stage == "cita"
    assert item.balls == (("alumno", "Corregir lo señalado"),)
    # Con la fase rechazada recupera el agendado (D13 del auto-agendado).
    assert item.ready_to_book is True


@pytest.mark.parametrize("dias_a_la_cita, pelotas", [
    (2, ()),                                         # ya reagendó: en agenda
    (-1, (("escolares", "Cerrar cita"),)),           # su nueva cita pasó sin cerrar
])
def test_fase_2_rechazada_con_cita_nueva_manda_la_cita(dias_a_la_cita, pelotas):
    item = rs.classify_process(
        _fase2(phase2_status="rejected", appt_status="scheduled",
               appt_scheduled_at=_hace(-dias_a_la_cita)), HOY, CFG)
    assert item.stage == "cita"
    assert item.balls == pelotas
    assert item.ready_to_book is False


def test_fase_2_rechazada_suma_las_liberaciones_abiertas():
    item = rs.classify_process(
        _fase2(phase2_status="rejected", blockers=("survey_in_review",)), HOY, CFG)
    assert item.balls == (("alumno", "Corregir lo señalado"), ("gtv", "Liberar encuesta"))
    assert item.ready_to_book is False


# ===========================================================================
# 6. Liberado
# ===========================================================================
@pytest.mark.parametrize("estado_proceso", ["active", "on_hold", "completed"])
def test_fase_2_aprobada_es_liberado(estado_proceso):
    item = rs.classify_process(
        _proc(current_phase=3, process_status=estado_proceso, phase2_status="approved",
              phase2_completed_at=datetime(2026, 10, 9, 13, 5), phase2_reviewed_by_id=321,
              appt_status="attended", appt_scheduled_at=datetime(2026, 10, 9, 10, 0),
              appt_owner_id=900, last_event_at=_hace(30)),
        HOY, CFG)
    assert item.stage == "liberado"
    assert item.balls == ()
    assert item.level == "ok"
    assert item.liberated_on == date(2026, 10, 9)
    assert item.liberated_by_id == 321
    assert item.ready_to_book is False


def test_liberado_sin_fecha_no_inventa_una():
    item = rs.classify_process(
        _proc(current_phase=3, phase2_status="approved", phase2_completed_at=None),
        HOY, CFG)
    assert item.stage == "liberado" and item.liberated_on is None


# ===========================================================================
# 7. Días sin movimiento y nivel (§4.4)
# ===========================================================================
@pytest.mark.parametrize("dias, nivel", [(0, "ok"), (6, "ok"), (7, "warn"),
                                         (13, "warn"), (14, "crit"), (40, "crit")])
def test_umbrales_exactos(dias, nivel):
    item = rs.classify_process(
        _proc(created_at=_hace(60), last_event_at=_hace(dias)), HOY, CFG)
    assert item.idle_days == dias
    assert item.level == nivel


def test_los_umbrales_salen_de_la_config():
    cfg = rs.ReportConfig(warn_days=2, crit_days=3)
    assert rs.classify_process(_proc(last_event_at=_hace(1)), HOY, cfg).level == "ok"
    assert rs.classify_process(_proc(last_event_at=_hace(2)), HOY, cfg).level == "warn"
    assert rs.classify_process(_proc(last_event_at=_hace(3)), HOY, cfg).level == "crit"


def test_sin_eventos_cuenta_desde_el_alta_del_proceso():
    item = rs.classify_process(_proc(created_at=_hace(9), last_event_at=None), HOY, CFG)
    assert item.idle_days == 9


def test_cuenta_desde_lo_mas_reciente_entre_evento_y_alta():
    # Un evento anterior al alta (backfill) no puede alargar la espera.
    item = rs.classify_process(_proc(created_at=_hace(4), last_event_at=_hace(20)), HOY, CFG)
    assert item.idle_days == 4


def test_los_dias_nunca_son_negativos():
    item = rs.classify_process(_proc(created_at=_hace(-1), last_event_at=_hace(-2)), HOY, CFG)
    assert item.idle_days == 0


def test_el_nivel_por_dias_es_publico():
    assert [rs.idle_level(d, CFG) for d in (6, 7, 13, 14)] == ["ok", "warn", "warn", "crit"]


# ===========================================================================
# 8. Con BD: `load_snapshot`
# ===========================================================================
# Todas las consultas van acotadas a convocatorias y carreras del escenario: la
# base de pruebas puede traer otros procesos (la de dev es copia de producción).
_SEQ = count(1)


class _Contador:
    """Sentencias SQL emitidas por la conexión del test mientras dura el bloque
    (patrón de `test_appt_queue_batch.py::_contar`). Antes de medir se hace
    `flush()` para que un autoflush pendiente no cuente como consulta."""

    def __init__(self, db):
        db.flush()
        db.expire_all()
        self.conexion = db.connection()
        self.sentencias: list[str] = []

    def __enter__(self):
        from sqlalchemy import event
        event.listen(self.conexion, "before_cursor_execute", self._ver)
        return self

    def __exit__(self, *exc):
        from sqlalchemy import event
        event.remove(self.conexion, "before_cursor_execute", self._ver)
        return False

    def _ver(self, _conn, _cursor, statement, *_a):
        # La bitácora de auditoría escribe en los flush: no es de esta lectura.
        if "titulatec_audit_log" not in statement:
            self.sentencias.append(" ".join(statement.split()))

    def __len__(self):
        return len(self.sentencias)


@pytest.fixture()
def tablero(db_session, seed_phase_defs, seed_document_types, make_program, make_cohort,
            make_student, make_process, make_document, make_survey_review,
            make_review_day, make_review_window, make_officer, make_head):
    """Dos convocatorias CON el candado de biblioteca (`seed_defaults`) y una
    SIN lista de requisitos, dos carreras, un encargado con un espacio de cotejo
    dentro de 3 días en `c1`.

    `proceso(clase, ...)` fabrica un egresado en una situación conocida;
    `solicitud(status, ...)` una solicitud viva.
    """
    from itcj2.apps.titulatec.models import (
        EnrollmentRequest,
        ProcessEvent,
        ProcessPhase,
        ReviewAppointment,
    )
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )
    from itcj2.core.utils.timezone import db_now

    seed_phase_defs()
    seed_document_types()
    pa = make_program("Ingenieria del Tablero Ficticia A")
    pb = make_program("Ingenieria del Tablero Ficticia B")
    c1, c2, sin_candado = make_cohort(), make_cohort(), make_cohort()
    for c in (c1, c2):
        CotejoRequirementService.seed_defaults(db_session, c.id, commit=False)
    officer, pos = make_officer([pa, pb])
    head = make_head()
    hoy = db_now().date()
    dia = make_review_day(c1, day=hoy + timedelta(days=3))
    ventana = make_review_window(dia, officer, position=pos)

    def evento(proc, cuando):
        db_session.add(ProcessEvent(process_id=proc.id, actor_id=None,
                                    event_type="document_uploaded", created_at=cuando))
        db_session.flush()

    def fase(proc, numero):
        return (db_session.query(ProcessPhase)
                .filter_by(process_id=proc.id, phase_number=numero).one())

    def proceso(clase, *, cohort=c1, program=pa, status="active"):
        alumno = make_student()
        if clase in ("docs_pend", "docs_alumno"):
            proc = make_process(alumno, cohort=cohort, program=program, status=status,
                                current_phase=1)
            if clase == "docs_pend":
                make_document(proc, type_code="birth_certificate", review_status="pending")
                make_document(proc, type_code="curp", review_status="approved")
            else:
                make_document(proc, type_code="birth_certificate", review_status="rejected")
            return proc
        if clase == "liberado":
            proc = make_process(alumno, cohort=cohort, program=program, status=status,
                                current_phase=3)
            f2 = fase(proc, 2)
            f2.completed_at = datetime.combine(hoy - timedelta(days=2), time(13, 0))
            f2.reviewed_by_id = head.id
            db_session.flush()
            return proc
        biblioteca, encuesta = {
            "gtv_biblio": ("pending", "in_review"),
            "gtv_pago": ("awaiting_payment", "in_review"),
            "biblio_pend": ("pending", "approved"),
            "listo": ("cleared", "approved"),
            "cita": ("cleared", "approved"),
        }[clase]
        proc = make_process(alumno, cohort=cohort, program=program, status=status,
                            current_phase=2, library_clearance=biblioteca)
        make_survey_review(proc, status=encuesta)
        if clase == "cita":
            db_session.add(ReviewAppointment(
                process_id=proc.id, window_id=ventana.id,
                scheduled_at=datetime.combine(dia.date, time(9, 0)),
                status="confirmed", created_by_id=alumno.id))
            db_session.flush()
        return proc

    def solicitud(status="pending_review", *, cohort=c1, program=pa, created_at=None,
                  reviewed_at=None, access_granted_at=None, verify_expires_at=None):
        n = next(_SEQ)
        row = EnrollmentRequest(
            cohort_id=cohort.id, control_number=f"98{n:06d}", first_name="SOLICITANTE",
            last_name="FICTICIO", program_id=getattr(program, "id", program),
            phone="6560000000", contact_email=f"s{n}@example.invalid", has_efirma=False,
            kind="unknown", status=status, verify_send_count=0,
            reviewed_at=reviewed_at, access_granted_at=access_granted_at,
            verify_expires_at=verify_expires_at,
            created_at=created_at or datetime.combine(hoy, time(8, 0)))
        db_session.add(row)
        db_session.flush()
        return row

    return SimpleNamespace(pa=pa, pb=pb, c1=c1, c2=c2, sin_candado=sin_candado,
                           officer=officer, head=head, hoy=hoy, ventana=ventana,
                           proceso=proceso, solicitud=solicitud, evento=evento,
                           fase=fase)


def _kw(t, *, cohort_ids=None, programs=None, include_unmapped=False) -> dict:
    """Argumentos de `load_snapshot` (por omisión: `c1` y las dos carreras).
    Se arman FUERA del contador: leer `t.c1.id` tras un `expire_all()` refresca
    la fila y esa consulta no es de la instantánea."""
    return {"cohort_ids": [t.c1.id] if cohort_ids is None else cohort_ids,
            "programs": {t.pa.id, t.pb.id} if programs is None else programs,
            "include_unmapped": include_unmapped, "today": t.hoy, "cfg": CFG}


def _snap(db, t, **kw):
    return rs.load_snapshot(db, **_kw(t, **kw))


def _llaves(snap) -> set[tuple[str, int]]:
    return {(it.kind, it.id) for it in snap.items}


def test_respeta_convocatoria_y_carreras(db_session, tablero):
    t = tablero
    p1 = t.proceso("docs_pend", cohort=t.c1, program=t.pa)
    r1 = t.solicitud("pending_review", cohort=t.c1, program=t.pa)
    p2 = t.proceso("docs_alumno", cohort=t.c1, program=t.pb)
    r2 = t.solicitud("awaiting_access", cohort=t.c1, program=t.pb)
    p3 = t.proceso("listo", cohort=t.c2, program=t.pa)
    r3 = t.solicitud("approved", cohort=t.c2, program=t.pa)

    solo = _snap(db_session, t, cohort_ids=[t.c1.id], programs={t.pa.id})
    assert _llaves(solo) == {("process", p1.id), ("request", r1.id)}

    ambas = _snap(db_session, t, cohort_ids=[t.c1.id, t.c2.id])
    assert _llaves(ambas) == {("process", p1.id), ("request", r1.id),
                              ("process", p2.id), ("request", r2.id),
                              ("process", p3.id), ("request", r3.id)}
    assert ambas.program_names == {t.pa.id: t.pa.name, t.pb.id: t.pb.name}

    # `cohort_ids=None` = todas las convocatorias (acotado por carrera del escenario).
    todas = rs.load_snapshot(db_session, cohort_ids=None, programs={t.pb.id},
                             include_unmapped=False, today=t.hoy, cfg=CFG)
    assert _llaves(todas) == {("process", p2.id), ("request", r2.id)}

    # "ALL" no filtra por carrera (dentro de la convocatoria nueva: solo las nuestras).
    assert _llaves(_snap(db_session, t, programs="ALL")) == {
        ("process", p1.id), ("request", r1.id), ("process", p2.id), ("request", r2.id)}


def test_el_filtro_sin_carreras_ni_include_unmapped_no_abre_sin_carrera(db_session, tablero):
    """`_scope_filters` por sí solo (sin el atajo temprano de `load_snapshot`):
    un set vacío sin `include_unmapped` no trae NADA -ni el cubo «Sin carrera»-,
    igual que `report_flow._filtros` (`false()`). Con `include_unmapped` sí."""
    from itcj2.apps.titulatec.models import EnrollmentRequest, TitulationProcess

    t = tablero
    p_sin = t.proceso("docs_pend", program=None)
    r_sin = t.solicitud(program=None)
    t.proceso("docs_pend", program=t.pa)
    for model, fila in ((TitulationProcess, p_sin), (EnrollmentRequest, r_sin)):
        cerrado = rs._scope_filters(model, cohort_ids=[t.c1.id], programs=set(),
                                    include_unmapped=False)
        assert db_session.query(model.id).filter(*cerrado).all() == [], model
        abierto = rs._scope_filters(model, cohort_ids=[t.c1.id], programs=set(),
                                    include_unmapped=True)
        assert [i for (i,) in db_session.query(model.id).filter(*abierto)] == [fila.id], model


def test_sin_alcance_o_sin_convocatorias_no_consulta(db_session, tablero):
    t = tablero
    t.proceso("docs_pend")
    t.solicitud()
    for kw in ({"cohort_ids": []}, {"programs": set()}):
        args = _kw(t, **kw)
        with _Contador(db_session) as c:
            snap = rs.load_snapshot(db_session, **args)
        assert snap.items == [] and snap.on_hold == 0 and snap.program_names == {}
        assert len(c) == 0, c.sentencias


def test_el_cubo_sin_carrera_solo_con_include_unmapped(db_session, tablero):
    t = tablero
    con = t.proceso("docs_pend", program=t.pa)
    p_sin = t.proceso("docs_pend", program=None)
    r_sin = t.solicitud(program=None)

    for programs in ("ALL", {t.pa.id}):
        fuera = _snap(db_session, t, programs=programs)
        assert _llaves(fuera) == {("process", con.id)}, programs
        dentro = _snap(db_session, t, programs=programs, include_unmapped=True)
        assert _llaves(dentro) == {("process", con.id), ("process", p_sin.id),
                                   ("request", r_sin.id)}, programs
        assert None not in dentro.program_names

    solo_sin = _snap(db_session, t, programs=set(), include_unmapped=True)
    assert _llaves(solo_sin) == {("process", p_sin.id), ("request", r_sin.id)}
    assert all(it.program_id is None for it in solo_sin.items)


def test_en_pausa_cuenta_aparte_y_revocados_fuera(db_session, tablero):
    t = tablero
    activo = t.proceso("docs_pend")
    t.proceso("docs_pend", status="on_hold")
    t.proceso("gtv_biblio", status="on_hold")
    revocado = t.proceso("docs_pend", status="cancelled")
    revocado_liberado = t.proceso("liberado", status="cancelled")
    pausado_liberado = t.proceso("liberado", status="on_hold")
    terminado = t.proceso("liberado", status="completed")

    snap = _snap(db_session, t)
    assert snap.on_hold == 2
    assert _llaves(snap) == {("process", activo.id), ("process", pausado_liberado.id),
                             ("process", terminado.id)}
    ids = {it.id for it in snap.items}
    assert revocado.id not in ids and revocado_liberado.id not in ids


def test_liberado_trae_su_fecha_y_quien_dictamino(db_session, tablero):
    t = tablero
    proc = t.proceso("liberado")
    (item,) = _snap(db_session, t).items
    assert item.id == proc.id
    assert item.stage == "liberado" and item.balls == ()
    assert item.liberated_on == t.hoy - timedelta(days=2)
    assert item.liberated_by_id == t.head.id


def test_la_pelota_de_requisitos_sale_del_gate(db_session, tablero):
    t = tablero
    gb = t.proceso("gtv_biblio")
    gp = t.proceso("gtv_pago")
    bp = t.proceso("biblio_pend")
    listo = t.proceso("listo")
    # Convocatoria SIN el requisito de no adeudo: biblioteca pendiente no bloquea
    # (invariante 8 de `ClearanceGate`, que una lectura directa del estado perdería).
    sin = t.proceso("biblio_pend", cohort=t.sin_candado)

    snap = _snap(db_session, t, cohort_ids=[t.c1.id, t.sin_candado.id])
    por_id = {it.id: it for it in snap.items}
    assert por_id[gb.id].balls == (("gtv", "Liberar encuesta"),
                                   ("biblioteca", "Registrar no adeudo"))
    assert por_id[gp.id].balls == (("alumno", "Pagar en Caja"), ("gtv", "Liberar encuesta"))
    assert por_id[bp.id].balls == (("biblioteca", "Registrar no adeudo"),)
    assert por_id[bp.id].ready_to_book is False
    for pid in (listo.id, sin.id):
        assert por_id[pid].stage == "requisitos"
        assert por_id[pid].balls == (("alumno", "Agendar cita"),)
        assert por_id[pid].ready_to_book is True


def test_la_cita_vigente_trae_el_dueno_de_su_ventana(db_session, tablero, make_appointment):
    t = tablero
    proc = t.proceso("cita")
    # Un intento viejo NO vigente no cuenta.
    make_appointment(proc, when=datetime.combine(t.hoy - timedelta(days=9), time(9)),
                     status="no_show", is_current=False)
    (item,) = _snap(db_session, t).items
    assert item.stage == "cita"
    assert item.balls == ()
    assert item.level == "ok"
    assert item.appt_owner_id == t.officer.id
    assert item.appt_date == t.hoy + timedelta(days=3)


def test_dias_desde_el_ultimo_evento_y_documentos_por_dictaminar(db_session, tablero,
                                                                 make_document):
    t = tablero
    proc = t.proceso("docs_pend")              # 1 pendiente + 1 aprobado
    make_document(proc, type_code="high_school_cert", review_status="pending")
    proc.created_at = datetime.combine(t.hoy - timedelta(days=30), time(8))
    t.evento(proc, datetime.combine(t.hoy - timedelta(days=20), time(9)))
    t.evento(proc, datetime.combine(t.hoy - timedelta(days=9), time(9)))
    quieto = t.proceso("docs_alumno")
    quieto.created_at = datetime.combine(t.hoy - timedelta(days=16), time(8))
    db_session.flush()

    por_id = {it.id: it for it in _snap(db_session, t).items}
    item = por_id[proc.id]
    assert item.pending_docs == 2
    assert item.balls == (("escolares", "Dictaminar documentos"),)
    assert (item.idle_days, item.level) == (9, "warn")
    otro = por_id[quieto.id]
    assert otro.pending_docs == 0
    assert otro.balls == (("alumno", "Subir o corregir documentos"),)
    assert (otro.idle_days, otro.level) == (16, "crit")


def test_solicitudes_vivas_con_su_etapa(db_session, tablero):
    t = tablero

    def hace(d):
        return datetime.combine(t.hoy - timedelta(days=d), time(8))

    revisar = t.solicitud("pending_review", created_at=hace(15))
    computo = t.solicitud("awaiting_access", created_at=hace(20), reviewed_at=hace(8))
    liga = t.solicitud("approved", created_at=hace(20), reviewed_at=hace(9),
                       access_granted_at=hace(2), verify_expires_at=hace(-19))
    vencida = t.solicitud("approved", created_at=hace(40), reviewed_at=hace(30),
                          verify_expires_at=hace(9))
    t.solicitud("converted")
    t.solicitud("rejected")

    snap = _snap(db_session, t)
    por_id = {it.id: it for it in snap.items}
    assert set(por_id) == {revisar.id, computo.id, liga.id, vencida.id}
    assert (por_id[revisar.id].stage, por_id[revisar.id].level) == ("req_review", "crit")
    assert (por_id[computo.id].stage, por_id[computo.id].idle_days) == ("req_access", 8)
    assert (por_id[liga.id].stage, por_id[liga.id].idle_days) == ("req_approved", 2)
    assert por_id[liga.id].balls == (("alumno", "Activar su cuenta"),)
    assert por_id[vencida.id].stage == "req_approved"
    assert por_id[vencida.id].balls == (("escolares", "Reenviar liga"),)
    assert por_id[revisar.id].label == f"SOLICITANTE FICTICIO · {revisar.control_number}"


_CLASES_LOTE = ("docs_pend", "gtv_pago", "cita")


def test_consultas_fijas_con_3_que_con_12_procesos(db_session, tablero):
    t = tablero

    def poblar(rondas):
        for _ in range(rondas):
            for clase in _CLASES_LOTE:
                t.proceso(clase)
            t.solicitud()

    def medir():
        args = _kw(t)
        with _Contador(db_session) as c:
            snap = rs.load_snapshot(db_session, **args)
        return c, snap

    poblar(1)                                 # 3 procesos + 1 solicitud
    chico, s1 = medir()
    poblar(3)                                 # 12 procesos + 4 solicitudes
    grande, s2 = medir()
    assert (len(s1.items), len(s2.items)) == (3 + 1, 12 + 4)
    assert len(chico) == len(grande), (chico.sentencias, grande.sentencias)
    # Medido el 2026-10-14: 6 (solicitudes, procesos y las 4 de
    # `ClearanceGate.status_map`). El techo del brief es 9.
    assert len(grande) <= 9, grande.sentencias
