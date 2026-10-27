"""Fase 5 (revisión de sinodales), Task 9: `ReviewInboxService`, la bandeja
«Mis revisiones» del docente.

Spec 2026-10-22-titulatec-fase5-revision-sinodales §8.2:

- **Por revisar**: conversación abierta (proceso `active`, fase 5 en curso, sin
  `closed_at`), versión vigente, su voto cuenta según la regla de firma y no ha
  votado esa versión. FIFO por la fecha de la versión VIGENTE.
- **En curso**: abiertas que no son «por revisar» (esperando versión, ya votó,
  su voto no cuenta) y las que están en pausa (`on_hold` no entra a «Por
  revisar», §6.5).
- **Completados**: conversación cerrada (liberada) o inscripción revocada.

Solo las asignaciones VIGENTES del docente: un sustituido ya no ve el proceso.
La regla de quién vota sale de `ReviewService.counting_roles` (nunca de leer
`signature_rule`); semáforo con el calendario de días inhábiles; «N nuevos»
con `ReviewService.unread_counts`; búsqueda y paginado con `utils/paging`; y
un número FIJO de consultas (2 vs 6 procesos iguales).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from itcj2.apps.titulatec.services import email_helper
from itcj2.apps.titulatec.services.phase_service import PhaseService
from itcj2.apps.titulatec.utils import storage

PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
       b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture()
def corte(monkeypatch):
    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


@pytest.fixture(autouse=True)
def entorno(monkeypatch, patched_session_local, corte, tmp_path):
    """Corte en 9, raíz de archivos en `tmp_path` y correo parcheado (los
    servicios del motor pueden avisar después del commit)."""
    corte(9)
    monkeypatch.setattr(storage, "_base", lambda: tmp_path)
    monkeypatch.setattr(email_helper, "deliver_detailed",
                        lambda **kw: (True, None))
    return SimpleNamespace(base=tmp_path)


@pytest.fixture()
def yo(make_user):
    return make_user(first_name="DOCENTE", last_name="BANDEJA")


@pytest.fixture()
def caso(db_session, make_review_case):
    """Un caso de `make_review_case` donde `yo` ocupa la posición `role`.

    `uploaded_at` fija la fecha de la versión VIGENTE (la de mayor número): en
    el arnés todo `NOW()` es la misma hora (una sola transacción).
    """
    def _build(yo, *, role="president", signature_rule="president_only", versions=1,
               phase_status="in_progress", status="active", uploaded_at=None):
        c = make_review_case(signature_rule=signature_rule, versions=versions,
                             phase_status=phase_status)
        c.assignments[role].user_id = yo.id
        c.teachers[role] = yo
        c.process.status = status
        if uploaded_at is not None and c.versions:
            c.versions[-1].uploaded_at = uploaded_at
        db_session.flush()
        return c

    return _build


def _listar(db, user_id, tab, **kw):
    from itcj2.apps.titulatec.services.review_inbox_service import ReviewInboxService
    return ReviewInboxService.list(db, user_id, tab=tab, **kw)


def _ids(data):
    return [r["process_id"] for r in data["page"].items]


def _votar_directo(db, c, role, verdict="approved"):
    """Un voto escrito a mano (sin pasar por el motor) sobre la versión vigente."""
    from itcj2.apps.titulatec.models import ReviewVote

    db.add(ReviewVote(version_id=c.versions[-1].id, assignment_id=c.assignments[role].id,
                      user_id=c.assignments[role].user_id, verdict=verdict))
    db.flush()


def _cerrar(db, c):
    from itcj2.apps.titulatec.models import ProcessPhase

    c.chat.closed_at = datetime(2026, 10, 20, 12, 0)
    n5 = PhaseService.phase_number_for_code(db, "synodal_review")
    fase = db.query(ProcessPhase).filter_by(process_id=c.process.id, phase_number=n5).one()
    fase.status = "approved"
    db.flush()


class _Contador:
    def __init__(self, conexion):
        self.conexion, self.sentencias = conexion, []

    def __enter__(self):
        event.listen(self.conexion, "before_cursor_execute", self._ver)
        return self

    def __exit__(self, *exc):
        event.remove(self.conexion, "before_cursor_execute", self._ver)
        return False

    def _ver(self, conn, cursor, statement, params, context, executemany):
        # Fuera: la bitácora y los SAVEPOINT del arnés (no son de la bandeja).
        if "titulatec_audit_log" in statement or "SAVEPOINT" in statement:
            return
        self.sentencias.append(" ".join(statement.split()))


# ---------------------------------------------------------------------------
# Pestañas y conteos
# ---------------------------------------------------------------------------
class TestPestanas:
    def test_cada_proceso_cae_en_su_pestana(self, db_session, yo, caso):
        por_revisar = caso(yo)                                       # Presidente, integral, v1
        solo_comenta = caso(yo, role="secretary")                    # integral: no vota
        ya_voto = caso(yo, role="vocal", signature_rule="all_synodals")
        _votar_directo(db_session, ya_voto, "vocal", "changes_requested")
        sin_version = caso(yo, versions=0)
        en_pausa = caso(yo, status="on_hold")                        # §6.5: no a «Por revisar»
        liberado = caso(yo)
        _cerrar(db_session, liberado)
        revocado = caso(yo, status="cancelled")

        pr = _listar(db_session, yo.id, "por_revisar")
        ec = _listar(db_session, yo.id, "en_curso")
        co = _listar(db_session, yo.id, "completados")

        assert _ids(pr) == [por_revisar.process.id]
        assert set(_ids(ec)) == {solo_comenta.process.id, ya_voto.process.id,
                                 sin_version.process.id, en_pausa.process.id}
        assert set(_ids(co)) == {liberado.process.id, revocado.process.id}
        assert pr["counts"] == ec["counts"] == co["counts"] == {
            "por_revisar": 1, "en_curso": 4, "completados": 2}

    def test_las_filas_dicen_por_que_estan_ahi(self, db_session, yo, caso):
        solo_comenta = caso(yo, role="secretary")
        ya_voto = caso(yo, role="vocal", signature_rule="all_synodals")
        _votar_directo(db_session, ya_voto, "vocal", "approved")
        sin_version = caso(yo, versions=0)
        en_pausa = caso(yo, status="on_hold")
        liberado = caso(yo)
        _cerrar(db_session, liberado)
        revocado = caso(yo, status="cancelled")

        filas = {r["process_id"]: r for r in _listar(db_session, yo.id, "en_curso")["page"].items}
        filas.update({r["process_id"]: r
                      for r in _listar(db_session, yo.id, "completados")["page"].items})

        assert filas[solo_comenta.process.id]["counts"] is False
        assert filas[solo_comenta.process.id]["role_label"] == "Secretario"
        assert filas[solo_comenta.process.id]["state_label"] == "Solo comentas"
        assert filas[ya_voto.process.id]["my_verdict"] == "approved"
        assert filas[ya_voto.process.id]["state_label"] == "Aprobaste la versión 1"
        assert filas[sin_version.process.id]["version"] is None
        assert filas[sin_version.process.id]["state_label"] == "Esperando la primera versión"
        assert filas[en_pausa.process.id]["state_label"] == "En pausa"
        assert filas[liberado.process.id]["released"] is True
        assert filas[liberado.process.id]["revoked"] is False
        assert filas[revocado.process.id]["revoked"] is True
        assert filas[revocado.process.id]["released"] is False

    def test_el_voto_de_una_version_anterior_no_cuenta(self, db_session, yo, caso):
        """D4: votó la v1, el alumno subió la v2 -> vuelve a «Por revisar»."""
        from itcj2.apps.titulatec.models import ReviewVote

        c = caso(yo, versions=2)
        db_session.add(ReviewVote(version_id=c.versions[0].id,
                                  assignment_id=c.assignments["president"].id,
                                  user_id=yo.id, verdict="changes_requested",
                                  comment="Corrige el capítulo 2"))
        db_session.flush()

        data = _listar(db_session, yo.id, "por_revisar")

        assert _ids(data) == [c.process.id]
        assert data["page"].items[0]["version"] == 2

    def test_tesis_votan_los_cuatro_suplente_incluido(self, db_session, yo, caso):
        c = caso(yo, role="alternate", signature_rule="all_synodals")

        (fila,) = _listar(db_session, yo.id, "por_revisar")["page"].items

        assert fila["process_id"] == c.process.id
        assert fila["counts"] is True
        assert fila["role_label"] == "Vocal Suplente"

    def test_regla_desconocida_falla_cerrado(self, db_session, yo, caso):
        c = caso(yo, signature_rule="regla_inventada")

        assert _ids(_listar(db_session, yo.id, "por_revisar")) == []
        (fila,) = _listar(db_session, yo.id, "en_curso")["page"].items
        assert fila["process_id"] == c.process.id
        assert fila["counts"] is False
        assert fila["state_label"] == "Regla de firma desconocida"

    def test_un_sustituido_ya_no_ve_el_proceso(self, db_session, yo, caso):
        c = caso(yo)
        c.assignments["president"].is_active = False
        db_session.flush()

        for tab in ("por_revisar", "en_curso", "completados"):
            assert _ids(_listar(db_session, yo.id, tab)) == []

    def test_otro_docente_no_ve_mis_procesos(self, db_session, yo, caso, make_user):
        caso(yo)
        otro = make_user(first_name="OTRO", last_name="DOCENTE")

        assert _listar(db_session, otro.id, "por_revisar")["counts"] == {
            "por_revisar": 0, "en_curso": 0, "completados": 0}

    def test_pestana_desconocida_cae_en_por_revisar(self, db_session, yo, caso):
        c = caso(yo)

        data = _listar(db_session, yo.id, "basura")

        assert data["tab"] == "por_revisar"
        assert _ids(data) == [c.process.id]


# ---------------------------------------------------------------------------
# Orden, búsqueda y paginado
# ---------------------------------------------------------------------------
class TestOrdenBusquedaPaginado:
    def test_fifo_por_la_fecha_de_la_version_vigente(self, db_session, yo, caso):
        tarde = caso(yo, uploaded_at=datetime(2026, 10, 10, 9, 0))
        # Su v1 es la MÁS vieja de todas, pero la vigente (v2) es de en medio:
        # manda la vigente.
        medio = caso(yo, versions=2, uploaded_at=datetime(2026, 10, 5, 9, 0))
        medio.versions[0].uploaded_at = datetime(2026, 9, 1, 9, 0)
        temprano = caso(yo, uploaded_at=datetime(2026, 10, 1, 9, 0))
        db_session.flush()

        data = _listar(db_session, yo.id, "por_revisar")

        assert _ids(data) == [temprano.process.id, medio.process.id, tarde.process.id]

    def test_completados_del_mas_reciente_al_mas_viejo(self, db_session, yo, caso):
        viejo, nuevo = caso(yo), caso(yo)
        _cerrar(db_session, viejo)
        _cerrar(db_session, nuevo)
        viejo.chat.closed_at = datetime(2026, 9, 1, 9, 0)
        nuevo.chat.closed_at = datetime(2026, 10, 1, 9, 0)
        db_session.flush()

        assert _ids(_listar(db_session, yo.id, "completados")) == [nuevo.process.id,
                                                                    viejo.process.id]

    def test_busqueda_por_control_y_por_nombre(self, db_session, yo, caso):
        a, b = caso(yo), caso(yo)

        por_control = _listar(db_session, yo.id, "por_revisar", q=a.student.control_number)
        por_nombre = _listar(db_session, yo.id, "por_revisar", q=b.student.last_name.lower())

        assert _ids(por_control) == [a.process.id]
        assert por_control["counts"]["por_revisar"] == 1
        assert _ids(por_nombre) == [b.process.id]

    def test_paginado(self, db_session, yo, caso):
        cs = [caso(yo, uploaded_at=datetime(2026, 10, d, 9, 0)) for d in (1, 2, 3)]

        p1 = _listar(db_session, yo.id, "por_revisar", per_page=2, page=1)
        p2 = _listar(db_session, yo.id, "por_revisar", per_page=2, page=2)
        fuera = _listar(db_session, yo.id, "por_revisar", per_page=2, page=99)

        assert _ids(p1) == [cs[0].process.id, cs[1].process.id]
        assert (p1["page"].total, p1["page"].pages) == (3, 2)
        assert _ids(p2) == [cs[2].process.id]
        assert fuera["page"].page == 2 and _ids(fuera) == [cs[2].process.id]


# ---------------------------------------------------------------------------
# «N nuevos» y semáforo
# ---------------------------------------------------------------------------
class TestNuevosYSemaforo:
    def test_nuevos_cuenta_lo_de_otros_y_se_apaga_al_leer(self, db_session, yo, caso):
        from itcj2.apps.titulatec.services.review_service import ReviewService

        c = caso(yo)
        ReviewService.post_message(db_session, c.process, c.student.id, body="Buenas tardes")
        ReviewService.post_message(db_session, c.process, c.teachers["vocal"].id,
                                   body="Revisen el anexo")
        mio = ReviewService.post_message(db_session, c.process, yo.id, body="Lo reviso")

        (fila,) = _listar(db_session, yo.id, "por_revisar")["page"].items
        assert fila["unread"] == 2                      # el mío no cuenta

        ReviewService.mark_read(db_session, c.chat.id, yo.id, mio.id)
        (fila,) = _listar(db_session, yo.id, "por_revisar")["page"].items
        assert fila["unread"] == 0

    def test_semaforo_con_el_calendario_de_dias_inhabiles(self, db_session, yo, caso,
                                                          make_non_working_day, monkeypatch):
        from itcj2.apps.titulatec.services import review_inbox_service as mod
        from itcj2.apps.titulatec.services.non_working_day_service import (
            NonWorkingDayService,
        )
        from itcj2.apps.titulatec.services.review_service import ReviewService

        subida = datetime(2091, 3, 1, 9, 0)
        c = caso(yo, uploaded_at=subida)
        sin_feriado = ReviewService.due_date(c.versions[-1],
                                             holidays=NonWorkingDayService.holidays(db_session))
        make_non_working_day(date(2091, 3, 5), "Inhábil de prueba")
        feriados = NonWorkingDayService.holidays(db_session)
        hoy = sin_feriado - timedelta(days=1)
        monkeypatch.setattr(mod, "db_now", lambda: datetime.combine(hoy, datetime.min.time()))

        (fila,) = _listar(db_session, yo.id, "por_revisar")["page"].items

        assert fila["due"] == ReviewService.due_date(c.versions[-1], holidays=feriados)
        assert fila["due"] != sin_feriado               # el día inhábil recorre el plazo
        assert fila["semaphore"] == ReviewService.semaphore(fila["due"], today=hoy,
                                                            holidays=feriados)
        assert fila["due_label"]

    def test_solo_por_revisar_lleva_semaforo(self, db_session, yo, caso):
        caso(yo, role="secretary")

        (fila,) = _listar(db_session, yo.id, "en_curso")["page"].items

        assert fila["semaphore"] is None


# ---------------------------------------------------------------------------
# Presupuesto de consultas
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tab", ["por_revisar", "en_curso", "completados"])
def test_presupuesto_de_consultas_no_crece_con_los_procesos(tab, db_session, yo, caso,
                                                            make_user):
    """2 vs 6 procesos iguales: las MISMAS consultas (sin N+1), con mensajes
    sin leer y versiones en cada uno."""
    from itcj2.apps.titulatec.services.review_service import ReviewService

    def _sembrar(docente, n):
        for _ in range(n):
            c = caso(docente, role="president" if tab != "en_curso" else "secretary")
            ReviewService.post_message(db_session, c.process, c.student.id, body="Hola")
            if tab == "completados":
                _cerrar(db_session, c)

    pocos = make_user(first_name="POCOS", last_name="PRESUPUESTO")
    muchos = make_user(first_name="MUCHOS", last_name="PRESUPUESTO")
    _sembrar(pocos, 2)
    _sembrar(muchos, 6)

    medidas = []
    for docente_id, n in ((pocos.id, 2), (muchos.id, 6)):       # ids antes de expirar
        db_session.expire_all()
        with _Contador(db_session.get_bind()) as cont:
            data = _listar(db_session, docente_id, tab)
        assert data["page"].total == n
        medidas.append(cont.sentencias)

    assert len(medidas[0]) == len(medidas[1]), medidas
    assert len(medidas[0]) <= 5, medidas      # + el último mensaje de cada fila


# ---------------------------------------------------------------------------
# Vista previa del último mensaje (rediseño de chat, 2026-10-27)
# ---------------------------------------------------------------------------
class TestVistaPrevia:
    def test_ultimo_mensaje_con_autor_y_marca_corta(self, db_session, yo, caso):
        from itcj2.apps.titulatec.services.review_service import ReviewService

        c = caso(yo)
        ReviewService.post_message(db_session, c.process, c.student.id, body="Buenas tardes")
        ReviewService.post_message(db_session, c.process, c.teachers["vocal"].id,
                                   body="Revisen   el\nanexo B")

        (fila,) = _listar(db_session, yo.id, "por_revisar")["page"].items
        assert fila["last_text"] == "Revisen el anexo B"            # espacios colapsados
        assert fila["last_who"] == c.teachers["vocal"].first_name.split()[0].capitalize()
        assert fila["last_label"] and fila["last_icon"] is None
        assert fila["initials"] == (c.student.first_name[:1] + c.student.last_name[:1]).upper()

        ReviewService.post_message(db_session, c.process, yo.id, body="Lo reviso")
        (fila,) = _listar(db_session, yo.id, "por_revisar")["page"].items
        assert (fila["last_who"], fila["last_text"]) == ("Tú", "Lo reviso")

    def test_adjunto_sin_texto_y_texto_largo(self, db_session, yo, caso):
        from itcj2.apps.titulatec.services.review_service import ReviewService

        c = caso(yo)
        ReviewService.post_message(db_session, c.process, c.student.id, body=None,
                                   raw=PDF, original_name="anexo.pdf")
        (fila,) = _listar(db_session, yo.id, "por_revisar")["page"].items
        assert (fila["last_text"], fila["last_icon"]) == ("anexo.pdf", "paperclip")

        ReviewService.post_message(db_session, c.process, c.student.id, body="x" * 600)
        (fila,) = _listar(db_session, yo.id, "por_revisar")["page"].items
        assert len(fila["last_text"]) <= 140 and fila["last_text"].endswith("…")

    def test_sin_mensajes_queda_vacia(self, db_session, yo, caso):
        from itcj2.apps.titulatec.models import ChatMessage

        c = caso(yo)
        db_session.query(ChatMessage).filter_by(chat_id=c.chat.id).delete()
        db_session.flush()
        (fila,) = _listar(db_session, yo.id, "por_revisar")["page"].items
        assert (fila["last_text"], fila["last_who"], fila["last_label"]) == ("", "", "")


@pytest.mark.parametrize("cuando, esperado", [
    (datetime(2026, 10, 27, 9, 5), "09:05"),
    (datetime(2026, 10, 26, 23, 59), "Ayer"),
    (datetime(2026, 3, 4, 8, 0), "4 mar"),
    (datetime(2025, 12, 31, 8, 0), "31 dic 2025"),
])
def test_cuando_corto(cuando, esperado):
    from itcj2.apps.titulatec.utils.dates_es import cuando_corto
    assert cuando_corto(cuando, hoy=date(2026, 10, 27)) == esperado
