"""Fase 5 (revisión de sinodales), Task 7: `ReviewService`, la puerta de la fase 5
y los parciales compartidos de la conversación.

Spec 2026-10-22-titulatec-fase5-revision-sinodales §6 (motor) y §7
(conversación). Lo que se fija aquí:

- la regla de firma sale SOLO de `ReviewService.counting_roles` (integral: vota
  el Presidente; tesis: los 4, suplente incluido; desconocida: falla cerrado) y
  nadie fuera de `review_service.py` lee `signature_rule` (AST);
- votos por versión (una versión nueva reinicia), cambio de voto, comentario
  obligatorio al pedir cambios, versión vieja en pantalla -> nada escrito;
- el voto que cierra exige reconfirmación (sin `confirm` no escribe NADA) y,
  confirmado, cierra por la puerta del motor: fase 5 aprobada, fase 6 en curso,
  conversación cerrada y mensaje de liberación según la fase 6 sea operable;
- `approve_phase(5)` por otra vía -> `REVIEW_ONLY_MSG`;
- sustituir agrega un mensaje y el voto del sustituido deja de contar;
- solo lectura con la conversación cerrada, el proceso en pausa o revocado;
- `assign` abre la conversación; participantes, archivos, leídos, estado y los
  parciales `partials/review/_messages.html` y `_status.html`.

Todo test fija el corte EXPLÍCITO en 9 (el comando corre con 3, como
producción); las pruebas del corte lo vuelven a fijar.
"""
from __future__ import annotations

import ast
import io
import re
import zipfile
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import itcj2
from itcj2.apps.titulatec.services import email_helper
from itcj2.apps.titulatec.services import review_service as rs_mod
from itcj2.apps.titulatec.services.phase_service import PhaseService
from itcj2.apps.titulatec.services.review_service import (
    CLOSED_MSG,
    COMMENT_REQUIRED_MSG,
    CONFIRM_CLOSE_MSG,
    INERT_MSG,
    MESSAGE_EMPTY_MSG,
    MESSAGE_TOO_LONG_MSG,
    NO_VERSION_MSG,
    NOT_COUNTING_MSG,
    NOT_PARTICIPANT_MSG,
    ONLY_STUDENT_MSG,
    OPEN_CHAT_MSG,
    PHASE_CODE,
    RULE_UNKNOWN_MSG,
    SIGNATURE_RULES,
    VERDICT_MSG,
    VERSION_CHANGED_MSG,
    ReviewNeedsConfirmation,
    ReviewService,
    ReviewVersionChanged,
)
from itcj2.apps.titulatec.services.synodal_service import ROLES, SynodalService
from itcj2.apps.titulatec.utils import storage
from itcj2.apps.titulatec.utils.business_days import add_business_days
from tests.fastapi.titulatec.conftest import audit_query

pytestmark = pytest.mark.usefixtures("audit_mark")

_APP = Path(itcj2.__file__).resolve().parent / "apps" / "titulatec"

PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
       b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def _zip(names: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, c in names.items():
            z.writestr(n, c)
    return buf.getvalue()


DOCX = _zip({"[Content_Types].xml": "<x/>", "word/document.xml": "<w/>"})


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture()
def corte(monkeypatch):
    """Fija el corte a T-soft. `corte(9)` lo apaga; `corte(3)` es producción."""
    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


@pytest.fixture(autouse=True)
def entorno(monkeypatch, patched_session_local, corte, tmp_path):
    """Corte en 9, `SessionLocal` = la sesión del test (los avisos de
    `SynodalService` abren la suya), raíz de archivos en `tmp_path` (la misma
    carpeta donde `make_review_case` escribe sus PDFs) y correo parcheado."""
    corte(9)
    monkeypatch.setattr(storage, "_base", lambda: tmp_path)
    enviados = []

    def _deliver(*, template, context, subject, to, que, link=None):
        enviados.append({"template": template, "to": to, "que": que})
        return True, None

    monkeypatch.setattr(email_helper, "deliver_detailed", _deliver)
    return SimpleNamespace(base=tmp_path, enviados=enviados)


@pytest.fixture()
def caso(db_session, make_review_case):
    """`make_review_case` + commit: el servicio hace `rollback` en sus negativas
    bajo el candado, y bajo `create_savepoint` eso borraría lo sembrado."""
    def _build(**kw):
        c = make_review_case(**kw)
        db_session.commit()
        return c
    return _build


def _n5(db) -> int:
    return PhaseService.phase_number_for_code(db, PHASE_CODE)


def _votos(db, version_id) -> dict:
    from itcj2.apps.titulatec.models import ReviewVote, SynodalAssignment
    return {r: v for r, v in db.query(SynodalAssignment.role, ReviewVote.verdict)
            .join(ReviewVote, ReviewVote.assignment_id == SynodalAssignment.id)
            .filter(ReviewVote.version_id == version_id).all()}


def _filas_voto(db, version_id) -> list:
    from itcj2.apps.titulatec.models import ReviewVote
    return db.query(ReviewVote).filter_by(version_id=version_id).order_by(ReviewVote.id).all()


def _mensajes(db, chat_id) -> list:
    from itcj2.apps.titulatec.models import ChatMessage
    return (db.query(ChatMessage).filter_by(chat_id=chat_id)
            .order_by(ChatMessage.id).all())


def _eventos(db, pid, tipo) -> list:
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db.query(ProcessEvent).filter_by(process_id=pid, event_type=tipo)
            .order_by(ProcessEvent.id).all())


def _acciones(db, action) -> list:
    from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog
    db.flush()
    return (audit_query(db).filter_by(source="action", action=action)
            .order_by(TitulatecAuditLog.id).all())


def _fases(db, pid) -> dict:
    from itcj2.apps.titulatec.models import ProcessPhase
    return {p.phase_number: p.status
            for p in db.query(ProcessPhase).filter_by(process_id=pid).all()}


def _chat(db, pid):
    from itcj2.apps.titulatec.models import ProcessChat
    db.expire_all()
    return db.query(ProcessChat).filter_by(process_id=pid).first()


def _votar(db, c, role, verdict="approved", *, comment=None, version=None, confirm=False):
    numero = version if version is not None else ReviewService.current_version(
        db, c.process.id).number
    return ReviewService.vote(db, c.process, c.teachers[role].id, verdict=verdict,
                              comment=comment, seen_version=numero, confirm=confirm)


def _nada_escrito(db, c, *, mensajes_antes: int) -> None:
    """Ningún voto, mensaje, evento ni bitácora; la fase 5 sigue en curso."""
    db.expire_all()
    for v in c.versions:
        assert _filas_voto(db, v.id) == []
    assert len(_mensajes(db, c.chat.id)) == mensajes_antes
    assert _eventos(db, c.process.id, "review_vote_cast") == []
    assert _acciones(db, "review.vote_cast") == []
    assert _fases(db, c.process.id)[_n5(db)] == "in_progress"
    assert _chat(db, c.process.id).closed_at is None
    assert PhaseService.DOOR_KEY not in db.info


def _nombre(user) -> str:
    return " ".join(p for p in (user.first_name, user.last_name, user.middle_name) if p)


# ---------------------------------------------------------------------------
# Regla de firma: un solo traductor (§6.1)
# ---------------------------------------------------------------------------
class TestReglaDeFirma:
    def test_el_traductor(self):
        assert SIGNATURE_RULES == {"president_only": ("president",), "all_synodals": ROLES}
        assert ReviewService.counting_roles("president_only") == ("president",)
        assert ReviewService.counting_roles("all_synodals") == ROLES
        for desconocida in (None, "", "todos", "PRESIDENT_ONLY"):
            with pytest.raises(ValueError) as exc:
                ReviewService.counting_roles(desconocida)
            assert str(exc.value) == RULE_UNKNOWN_MSG
        assert RULE_UNKNOWN_MSG == ("Regla de firma desconocida; avisa al Departamento "
                                    "de Titulación.")

    def test_texto_de_firmas(self):
        assert ReviewService.signature_text("president_only") == "basta la firma del Presidente"
        assert ReviewService.signature_text("all_synodals") == (
            "se necesitan las firmas de tus 4 sinodales")
        with pytest.raises(ValueError):
            ReviewService.signature_text("otra")

    def test_rule_for_lee_la_modalidad_del_proceso(self, caso):
        assert ReviewService.rule_for(caso().process) == "president_only"
        assert ReviewService.rule_for(caso(signature_rule="all_synodals").process) == (
            "all_synodals")
        assert ReviewService.rule_for(SimpleNamespace(modality=None)) is None

    def test_integral_solo_vota_el_presidente(self, db_session, caso):
        c = caso()
        antes = len(_mensajes(db_session, c.chat.id))
        for role in ("secretary", "vocal", "alternate"):
            with pytest.raises(ValueError) as exc:
                _votar(db_session, c, role, "changes_requested", comment="Revisa el capítulo 2")
            assert str(exc.value) == NOT_COUNTING_MSG
            assert ReviewService.would_close(db_session, c.process, c.teachers[role].id) is False
        _nada_escrito(db_session, c, mensajes_antes=antes)
        # Los que no cuentan sí comentan.
        ReviewService.post_message(db_session, c.process, c.teachers["vocal"].id,
                                   body="Sugiero revisar la bibliografía")
        assert ReviewService.would_close(db_session, c.process,
                                         c.teachers["president"].id) is True

        out = _votar(db_session, c, "president", confirm=True)

        assert out == {"closed": True, "version": 1}

    def test_tesis_votan_los_4_suplente_incluido(self, db_session, caso):
        c = caso(signature_rule="all_synodals")
        for role in ("president", "secretary", "alternate"):
            assert _votar(db_session, c, role) == {"closed": False, "version": 1}
            assert ReviewService.rule_satisfied(db_session, c.process) is False
        assert ReviewService.would_close(db_session, c.process, c.teachers["vocal"].id)

        out = _votar(db_session, c, "vocal", confirm=True)

        assert out == {"closed": True, "version": 1}
        assert _votos(db_session, c.versions[0].id) == {r: "approved" for r in ROLES}

    def test_regla_desconocida_falla_cerrado(self, db_session, caso):
        c = caso(signature_rule="otra_regla")
        antes = len(_mensajes(db_session, c.chat.id))
        with pytest.raises(ValueError) as exc:
            _votar(db_session, c, "president", confirm=True)
        assert str(exc.value) == RULE_UNKNOWN_MSG
        _nada_escrito(db_session, c, mensajes_antes=antes)
        assert ReviewService.rule_satisfied(db_session, c.process) is False
        assert ReviewService.would_close(db_session, c.process,
                                         c.teachers["president"].id) is False
        estado = ReviewService.status_for_process(db_session, c.process.id)
        assert estado["rule_label"] == RULE_UNKNOWN_MSG
        assert not any(v["counts"] for v in estado["votes"])

    def test_sin_modalidad_falla_cerrado(self, db_session, caso):
        c = caso()
        c.process.modality_id = None
        db_session.flush()
        db_session.expire(c.process, ["modality"])
        db_session.commit()
        with pytest.raises(ValueError) as exc:
            _votar(db_session, c, "president", confirm=True)
        assert str(exc.value) == RULE_UNKNOWN_MSG
        assert ReviewService.rule_satisfied(db_session, c.process) is False


class TestNadieMasLeeSignatureRule:
    """Como `TrackService` con `Program.level`: la regla solo la traduce
    `ReviewService.counting_roles`. Un segundo lector es una segunda definición
    de «quién vota» que puede desincronizarse del catálogo."""

    @staticmethod
    def _lecturas(tree: ast.AST) -> list[int]:
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "signature_rule":
                out.append(node.lineno)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id in ("getattr", "hasattr") and len(node.args) >= 2
                  and isinstance(node.args[1], ast.Constant)
                  and node.args[1].value == "signature_rule"):
                out.append(node.lineno)
        return sorted(out)

    def test_el_detector_ve_lo_que_tiene_que_ver(self):
        muestra = (
            "def a(p):\n"
            "    return p.modality.signature_rule == 'all_synodals'\n"   # 2: SÍ
            "def b(m):\n"
            "    return getattr(m, 'signature_rule', None)\n"           # 4: SÍ
            "def c(rule):\n"
            "    return ReviewService.counting_roles(rule)\n"           # NO
            "X = {'signature_rule': 1}\n"                               # NO (llave)
        )
        assert self._lecturas(ast.parse(muestra)) == [2, 4]

    def test_solo_review_service_lee_signature_rule(self):
        ofensas = []
        for carpeta in ("services", "pages"):
            for ruta in sorted((_APP / carpeta).glob("*.py")):
                if ruta.name == "review_service.py":
                    continue
                arbol = ast.parse(ruta.read_text(encoding="utf-8"))
                ofensas += [f"{carpeta}/{ruta.name}:{n}" for n in self._lecturas(arbol)]
        assert not ofensas, (
            "`signature_rule` se lee fuera de services/review_service.py (usa "
            "ReviewService.counting_roles / rule_for / signature_text):\n"
            + "\n".join(ofensas))
        assert self._lecturas(ast.parse(
            (_APP / "services" / "review_service.py").read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# Votos por versión (§6.3)
# ---------------------------------------------------------------------------
class TestVotos:
    def test_version_nueva_reinicia_los_votos(self, db_session, caso):
        c = caso(signature_rule="all_synodals")
        for role in ("president", "secretary", "vocal"):
            _votar(db_session, c, role)

        v2 = ReviewService.upload_version(db_session, c.process, c.student.id,
                                          raw=PDF, original_name="tesis v2.pdf")

        assert v2.number == 2
        assert ReviewService.current_version(db_session, c.process.id).id == v2.id
        estado = ReviewService.status_for_process(db_session, c.process.id)
        assert estado["version"] == 2
        assert [v["verdict"] for v in estado["votes"]] == [None, None, None, None]
        assert ReviewService.would_close(db_session, c.process,
                                         c.teachers["alternate"].id) is False
        # La historia no se borra: los votos de la v1 siguen ahí.
        assert len(_votos(db_session, c.versions[0].id)) == 3
        # Votar viendo la v1 ya no vale.
        with pytest.raises(ReviewVersionChanged):
            _votar(db_session, c, "alternate", version=1)

    def test_cambiar_de_voto(self, db_session, caso):
        c = caso(signature_rule="all_synodals")
        antes = len(_mensajes(db_session, c.chat.id))

        _votar(db_session, c, "secretary", "changes_requested",
               comment="  Falta el marco teórico  ")
        _votar(db_session, c, "secretary", "approved")

        (fila,) = _filas_voto(db_session, c.versions[0].id)
        assert fila.verdict == "approved" and fila.comment is None
        assert fila.assignment_id == c.assignments["secretary"].id
        assert fila.user_id == c.teachers["secretary"].id
        votos = [m for m in _mensajes(db_session, c.chat.id)[antes:]]
        assert [m.kind for m in votos] == ["vote", "vote"]
        assert votos[0].body == ("El Secretario pidió cambios en la versión 1:\n"
                                 "Falta el marco teórico")
        assert votos[1].body == "El Secretario aprobó la versión 1."
        assert all(m.version_id == c.versions[0].id for m in votos)
        assert all(m.author_id == c.teachers["secretary"].id for m in votos)
        eventos = _eventos(db_session, c.process.id, "review_vote_cast")
        assert [e.payload for e in eventos] == [
            {"version": 1, "role": "secretary", "verdict": "changes_requested"},
            {"version": 1, "role": "secretary", "verdict": "approved"},
        ]
        assert all(e.phase_number == _n5(db_session) for e in eventos)
        bitacora = _acciones(db_session, "review.vote_cast")
        assert [b.payload for b in bitacora] == [e.payload for e in eventos]
        assert bitacora[0].process_id == c.process.id

    @pytest.mark.parametrize("comentario", [None, "", "   ", "x" * 2001])
    def test_pedir_cambios_exige_comentario(self, db_session, caso, comentario):
        c = caso(signature_rule="all_synodals")
        antes = len(_mensajes(db_session, c.chat.id))
        with pytest.raises(ValueError) as exc:
            _votar(db_session, c, "vocal", "changes_requested", comment=comentario)
        assert str(exc.value) == COMMENT_REQUIRED_MSG
        _nada_escrito(db_session, c, mensajes_antes=antes)

    def test_veredicto_desconocido(self, db_session, caso):
        c = caso()
        with pytest.raises(ValueError) as exc:
            _votar(db_session, c, "president", "aprobado")
        assert str(exc.value) == VERDICT_MSG

    def test_aprobar_admite_comentario(self, db_session, caso):
        c = caso(signature_rule="all_synodals")
        _votar(db_session, c, "vocal", comment="Muy buen trabajo")
        (fila,) = _filas_voto(db_session, c.versions[0].id)
        assert fila.comment == "Muy buen trabajo"
        assert _mensajes(db_session, c.chat.id)[-1].body == (
            "El Vocal aprobó la versión 1.\nMuy buen trabajo")

    def test_voto_con_version_vieja_no_escribe(self, db_session, caso):
        c = caso(versions=2)
        antes = len(_mensajes(db_session, c.chat.id))
        for vista in (1, None):
            with pytest.raises(ReviewVersionChanged) as exc:
                ReviewService.vote(db_session, c.process, c.teachers["president"].id,
                                   verdict="approved", comment=None, seen_version=vista,
                                   confirm=True)
            assert str(exc.value) == VERSION_CHANGED_MSG
            assert isinstance(exc.value, ValueError)
        _nada_escrito(db_session, c, mensajes_antes=antes)

    def test_sin_version_no_se_vota(self, db_session, caso):
        c = caso(versions=0)
        with pytest.raises(ValueError) as exc:
            ReviewService.vote(db_session, c.process, c.teachers["president"].id,
                               verdict="approved", comment=None, seen_version=None,
                               confirm=True)
        assert str(exc.value) == NO_VERSION_MSG

    def test_quien_no_es_sinodal_no_vota(self, db_session, caso, make_user):
        c = caso()
        for actor in (make_user(first_name="AJENO"), c.student):
            with pytest.raises(ValueError) as exc:
                ReviewService.vote(db_session, c.process, actor.id, verdict="approved",
                                   comment=None, seen_version=1, confirm=True)
            assert str(exc.value) == NOT_PARTICIPANT_MSG


# ---------------------------------------------------------------------------
# Reconfirmación y cierre por la puerta (§6.3, §6.4, D6)
# ---------------------------------------------------------------------------
class TestCierre:
    def test_el_voto_que_cierra_sin_confirm_no_escribe_nada(self, db_session, caso,
                                                              monkeypatch):
        c = caso()
        antes = len(_mensajes(db_session, c.chat.id))
        llamadas = []
        original = db_session.rollback
        monkeypatch.setattr(db_session, "rollback",
                            lambda: (llamadas.append(1), original())[1])

        with pytest.raises(ReviewNeedsConfirmation) as exc:
            _votar(db_session, c, "president", confirm=False)

        assert str(exc.value) == CONFIRM_CLOSE_MSG
        assert isinstance(exc.value, ValueError)
        assert llamadas == [1], "la decisión se toma bajo el candado: deshace y suelta"
        _nada_escrito(db_session, c, mensajes_antes=antes)
        assert CONFIRM_CLOSE_MSG == (
            "Al aprobar se cerrará la revisión: la conversación quedará solo para "
            "consulta y ya no habrá más cambios ni versiones. ¿Confirmas?")

    def test_dos_aprobaciones_de_tesis_la_segunda_sin_confirm_no_cierra(self, db_session,
                                                                         caso):
        """El Vocal Suplente abrió la conversación cuando faltaban dos votos (su
        formulario no lleva `confirm`). El Vocal aprueba primero; la aprobación
        del suplente ahora sí cerraría: se decide bajo el candado y pide
        reconfirmación en vez de cerrar."""
        c = caso(signature_rule="all_synodals")
        _votar(db_session, c, "president")
        _votar(db_session, c, "secretary")
        assert ReviewService.would_close(db_session, c.process,
                                         c.teachers["alternate"].id) is False

        assert _votar(db_session, c, "vocal") == {"closed": False, "version": 1}
        with pytest.raises(ReviewNeedsConfirmation):
            _votar(db_session, c, "alternate", confirm=False)

        db_session.expire_all()
        assert _fases(db_session, c.process.id)[_n5(db_session)] == "in_progress"
        assert _chat(db_session, c.process.id).closed_at is None
        assert "alternate" not in _votos(db_session, c.versions[0].id)
        assert ReviewService.would_close(db_session, c.process, c.teachers["alternate"].id)

    def test_con_confirm_cierra_por_la_puerta_y_libera_hacia_el_anexo(self, db_session,
                                                                       caso):
        c = caso()
        n5 = _n5(db_session)

        out = _votar(db_session, c, "president", comment="Listo", confirm=True)

        assert out == {"closed": True, "version": 1}
        db_session.expire_all()
        fases = _fases(db_session, c.process.id)
        assert fases[n5] == "approved" and fases[n5 + 1] == "in_progress"
        assert c.process.current_phase == n5 + 1
        chat = _chat(db_session, c.process.id)
        assert chat.closed_at is not None
        ultimo = _mensajes(db_session, c.chat.id)[-1]
        assert ultimo.kind == "system" and ultimo.author_id is None
        assert ultimo.body == ("Proyecto liberado. Ya puedes pasar por tu Anexo III para que "
                               "lo firmen tus sinodales: basta la firma del Presidente.")
        (aprobada,) = [e for e in _eventos(db_session, c.process.id, "phase_approved")
                       if e.phase_number == n5]
        assert aprobada.payload == {
            "version": 1, "rule": "president_only",
            "voters": [{"role": "president", "user_id": c.teachers["president"].id}]}
        assert aprobada.actor_id == c.teachers["president"].id
        assert PhaseService.DOOR_KEY not in db_session.info
        assert ReviewService.is_open(c.process, chat) is False
        # Cerrada: nadie escribe, sube ni vota.
        with pytest.raises(ValueError) as exc:
            ReviewService.post_message(db_session, c.process, c.student.id, body="¿Y ahora?")
        assert str(exc.value) == CLOSED_MSG
        with pytest.raises(ValueError) as exc:
            ReviewService.upload_version(db_session, c.process, c.student.id,
                                         raw=PDF, original_name="v2.pdf")
        assert str(exc.value) == CLOSED_MSG

    def test_tesis_libera_con_la_linea_de_las_4_firmas(self, db_session, caso):
        c = caso(signature_rule="all_synodals")
        for role in ("president", "secretary", "vocal"):
            _votar(db_session, c, role)
        _votar(db_session, c, "alternate", confirm=True)
        ultimo = _mensajes(db_session, c.chat.id)[-1]
        assert ultimo.body.endswith("se necesitan las firmas de tus 4 sinodales.")
        (aprobada,) = [e for e in _eventos(db_session, c.process.id, "phase_approved")
                       if e.phase_number == _n5(db_session)]
        assert aprobada.payload["rule"] == "all_synodals"
        assert [v["role"] for v in aprobada.payload["voters"]] == list(ROLES)

    def test_con_la_fase_6_en_t_soft_el_mensaje_es_de_traspaso(self, db_session, caso,
                                                               corte):
        c = caso()
        corte(6)        # la 5 se opera aquí; el Anexo III, todavía no
        assert ReviewService.operable(db_session) is True

        _votar(db_session, c, "president", confirm=True)

        ultimo = _mensajes(db_session, c.chat.id)[-1]
        assert ultimo.kind == "system"
        assert "Anexo III" not in ultimo.body
        assert ultimo.body == (
            "Proyecto liberado. Tu proceso continúa en el Departamento de Titulación, en el "
            "sistema T-soft. El departamento te contactará por correo para darte tu usuario.")

    def test_approve_phase_5_por_otra_via_da_review_only(self, db_session, caso):
        c = caso()
        n5 = _n5(db_session)
        revisor = c.assignments["president"].assigned_by_id
        assert PhaseService._DOOR_PHASES[PHASE_CODE] == PhaseService.REVIEW_ONLY_MSG

        with pytest.raises(ValueError) as exc:
            PhaseService.approve_phase(db_session, c.process, n5, reviewer_id=revisor)
        assert str(exc.value) == PhaseService.REVIEW_ONLY_MSG

        # La marca sola no basta: la regla no se cumple.
        PhaseService.open_door(db_session, PHASE_CODE, c.process.id, "approved")
        with pytest.raises(ValueError) as exc:
            PhaseService.approve_phase(db_session, c.process, n5, reviewer_id=revisor)
        assert str(exc.value) == PhaseService.REVIEW_ONLY_MSG
        assert PhaseService.DOOR_KEY not in db_session.info, "se consume"

        # La fase 5 no tiene rechazo.
        PhaseService.open_door(db_session, PHASE_CODE, c.process.id, "rejected")
        with pytest.raises(ValueError) as exc:
            PhaseService.reject_phase(db_session, c.process, n5, reviewer_id=revisor,
                                      reason="por la otra puerta")
        assert str(exc.value) == PhaseService.REVIEW_ONLY_MSG
        db_session.rollback()
        db_session.expire_all()
        assert _fases(db_session, c.process.id)[n5] == "in_progress"

    def test_la_regla_cumplida_sin_marca_tampoco_abre(self, db_session, caso):
        """Votos escritos a mano (sin el servicio): el motor sigue exigiendo la
        marca de `ReviewService`."""
        from itcj2.apps.titulatec.models import ReviewVote
        c = caso()
        db_session.add(ReviewVote(version_id=c.versions[0].id,
                                  assignment_id=c.assignments["president"].id,
                                  user_id=c.teachers["president"].id, verdict="approved"))
        db_session.commit()
        assert ReviewService.rule_satisfied(db_session, c.process) is True
        with pytest.raises(ValueError) as exc:
            PhaseService.approve_phase(db_session, c.process, _n5(db_session),
                                       reviewer_id=c.teachers["president"].id)
        assert str(exc.value) == PhaseService.REVIEW_ONLY_MSG


# ---------------------------------------------------------------------------
# Sustitución durante la revisión (§6.3)
# ---------------------------------------------------------------------------
class TestSustitucion:
    def test_agrega_mensaje_y_el_voto_del_sustituido_deja_de_contar(
            self, db_session, caso, make_teacher, make_user):
        from itcj2.apps.titulatec.models import ProgramDepartment
        from itcj2.core.models.department import Department

        c = caso(signature_rule="all_synodals")
        for role in ("president", "secretary", "vocal"):
            _votar(db_session, c, role)
        depto = db_session.get(Department, db_session.get(
            ProgramDepartment, c.process.program_id).department_id)
        entrante = make_teacher(depto, user=make_user(first_name="ENTRANTE",
                                                      last_name="SUPLENTE"))
        db_session.commit()
        saliente = c.teachers["secretary"]
        jefe = c.assignments["president"].assigned_by_id

        SynodalService.replace(db_session, c.process, jefe, role="secretary",
                               new_user_id=entrante.id, reason="Licencia")

        ultimo = _mensajes(db_session, c.chat.id)[-1]
        assert ultimo.kind == "system" and ultimo.author_id is None
        assert ultimo.body == f"{_nombre(entrante)} sustituye a {_nombre(saliente)} como Secretario."
        estado = ReviewService.status_for_process(db_session, c.process.id)
        secretario = next(v for v in estado["votes"] if v["role"] == "secretary")
        assert secretario["name"] == _nombre(entrante) and secretario["verdict"] is None
        # El voto viejo sigue en la tabla, pero ya no cuenta.
        assert _votos(db_session, c.versions[0].id)["secretary"] == "approved"
        assert ReviewService.would_close(db_session, c.process,
                                         c.teachers["alternate"].id) is False
        assert _votar(db_session, c, "alternate") == {"closed": False, "version": 1}
        assert ReviewService.rule_satisfied(db_session, c.process) is False
        # El sustituido pierde el acceso; quien entra vota sobre la vigente.
        with pytest.raises(HTTPException) as exc:
            ReviewService.assert_participant(db_session, saliente.id, c.process.id)
        assert exc.value.status_code == 404
        with pytest.raises(ValueError) as exc2:
            _votar(db_session, c, "secretary")
        assert str(exc2.value) == NOT_PARTICIPANT_MSG
        out = ReviewService.vote(db_session, c.process, entrante.id, verdict="approved",
                                 comment=None, seen_version=1, confirm=True)
        assert out == {"closed": True, "version": 1}

    def test_sin_conversacion_no_falla(self, db_session, caso):
        c = caso()
        db_session.delete(c.chat)
        db_session.commit()
        ReviewService.on_replaced(db_session, c.process, role="vocal",
                                  old_user_id=c.teachers["vocal"].id,
                                  new_user_id=c.teachers["vocal"].id)
        assert _chat(db_session, c.process.id) is None


# ---------------------------------------------------------------------------
# Solo lectura: cerrada, en pausa, revocada (§6.4)
# ---------------------------------------------------------------------------
class TestSoloLectura:
    @pytest.mark.parametrize("como", ["cerrada", "on_hold", "cancelled", "fase_aprobada"])
    def test_nadie_escribe_sube_ni_vota(self, db_session, caso, como):
        c = caso(phase_status="approved" if como == "fase_aprobada" else "in_progress")
        if como == "cerrada":
            c.chat.closed_at = datetime(2026, 10, 1, 9, 0)
        elif como in ("on_hold", "cancelled"):
            c.process.status = como
        db_session.commit()
        antes = len(_mensajes(db_session, c.chat.id))

        assert ReviewService.is_open(c.process, c.chat) is False
        acciones = (
            lambda: ReviewService.post_message(db_session, c.process, c.student.id, body="Hola"),
            lambda: ReviewService.post_message(db_session, c.process,
                                               c.teachers["vocal"].id, body="Hola"),
            lambda: ReviewService.upload_version(db_session, c.process, c.student.id,
                                                 raw=PDF, original_name="v.pdf"),
            lambda: _votar(db_session, c, "president", confirm=True),
        )
        for accion in acciones:
            with pytest.raises(ValueError) as exc:
                accion()
            assert str(exc.value) == CLOSED_MSG
        assert len(_mensajes(db_session, c.chat.id)) == antes
        assert ReviewService.would_close(db_session, c.process,
                                         c.teachers["president"].id) is False

    def test_abierta(self, caso):
        c = caso()
        assert ReviewService.is_open(c.process, c.chat) is True
        assert ReviewService.is_open(c.process, None) is False


# ---------------------------------------------------------------------------
# Corte a T-soft: con el corte en la fase 5 o antes, nada se opera
# ---------------------------------------------------------------------------
class TestCorte:
    @pytest.mark.parametrize("fase", [3, 5])
    def test_inerte(self, db_session, caso, corte, fase):
        c = caso()
        corte(fase)
        assert ReviewService.operable(db_session) is False
        antes = len(_mensajes(db_session, c.chat.id))
        for accion in (
            lambda: ReviewService.post_message(db_session, c.process, c.student.id, body="Hola"),
            lambda: ReviewService.upload_version(db_session, c.process, c.student.id,
                                                 raw=PDF, original_name="v.pdf"),
            lambda: _votar(db_session, c, "president", confirm=True),
        ):
            with pytest.raises(ValueError) as exc:
                accion()
            assert str(exc.value) == INERT_MSG
        assert len(_mensajes(db_session, c.chat.id)) == antes

    def test_operable_con_el_corte_arriba(self, db_session, caso):
        caso()
        assert ReviewService.operable(db_session) is True


# ---------------------------------------------------------------------------
# Versiones y mensajes (§6.3, §7)
# ---------------------------------------------------------------------------
class TestVersionesYMensajes:
    def test_subir_version(self, db_session, caso, entorno):
        c = caso(versions=0)
        control = c.student.control_number

        v1 = ReviewService.upload_version(db_session, c.process, c.student.id,
                                          raw=PDF, original_name="Mi tesis.pdf")
        v2 = ReviewService.upload_version(db_session, c.process, c.student.id,
                                          raw=DOCX, original_name="Mi tesis corregida.docx")

        assert (v1.number, v2.number) == (1, 2)
        assert v1.file_path.endswith(f"/revision/v1_{control}.pdf")
        assert v2.file_path.endswith(f"/revision/v2_{control}.docx")
        assert (entorno.base / v1.file_path).read_bytes() == PDF
        assert v2.mime_type.endswith("wordprocessingml.document")
        assert v2.size_bytes == len(DOCX) and v2.original_name == "Mi tesis corregida.docx"
        assert v1.uploaded_by_id == c.student.id and v1.uploaded_at is not None
        mensajes = [m for m in _mensajes(db_session, c.chat.id) if m.kind == "version"]
        assert [(m.version_id, m.author_id) for m in mensajes] == [
            (v1.id, c.student.id), (v2.id, c.student.id)]
        assert mensajes[0].body == "Versión 1 del proyecto."
        assert mensajes[1].attachment_name == "Mi tesis corregida.docx"
        eventos = _eventos(db_session, c.process.id, "review_version_uploaded")
        assert [e.payload for e in eventos] == [{"version": 1}, {"version": 2}]
        assert eventos[0].phase_number == _n5(db_session)
        bitacora = _acciones(db_session, "review.version_uploaded")
        assert [b.payload["version"] for b in bitacora] == [1, 2]

    def test_archivo_invalido_no_escribe_nada(self, db_session, caso, entorno):
        from itcj2.apps.titulatec.models import ReviewVersion
        from itcj2.apps.titulatec.utils.review_files import ReviewFileError
        c = caso(versions=0)
        for raw, nombre in ((DOCX, "renombrado.pdf"), (b"", "vacio.pdf"), (PDF, "x.exe")):
            with pytest.raises(ReviewFileError):
                ReviewService.upload_version(db_session, c.process, c.student.id,
                                             raw=raw, original_name=nombre)
        assert db_session.query(ReviewVersion).filter_by(process_id=c.process.id).count() == 0
        assert not list(entorno.base.rglob("revision"))
        assert _mensajes(db_session, c.chat.id) == []

    def test_solo_el_alumno_dueno_sube_versiones(self, db_session, caso):
        c = caso(versions=0)
        otro = caso(versions=0).student
        for actor in (c.teachers["president"], otro):
            with pytest.raises(ValueError) as exc:
                ReviewService.upload_version(db_session, c.process, actor.id,
                                             raw=PDF, original_name="v.pdf")
            assert str(exc.value) == ONLY_STUDENT_MSG

    def test_mensaje_con_y_sin_adjunto(self, db_session, caso, entorno):
        c = caso()
        control = c.student.control_number

        texto = ReviewService.post_message(db_session, c.process, c.student.id,
                                           body="  Hola,\nsubí la versión  ")
        anotado = ReviewService.post_message(db_session, c.process,
                                             c.teachers["secretary"].id, body=None,
                                             raw=DOCX, original_name="anotado.docx")

        assert texto.kind == "message" and texto.body == "Hola,\nsubí la versión"
        assert texto.attachment_path is None and texto.author_id == c.student.id
        assert anotado.body is None and anotado.attachment_name == "anotado.docx"
        assert anotado.attachment_path.endswith(f"/revision/m{anotado.id}_{control}.docx")
        assert (entorno.base / anotado.attachment_path).read_bytes() == DOCX
        assert anotado.attachment_size == len(DOCX)
        assert anotado.attachment_mime.endswith("wordprocessingml.document")
        assert _eventos(db_session, c.process.id, "review_vote_cast") == []

    def test_mensaje_vacio_largo_o_de_un_extrano(self, db_session, caso, make_user):
        c = caso()
        antes = len(_mensajes(db_session, c.chat.id))
        for cuerpo in (None, "", "   \n "):
            with pytest.raises(ValueError) as exc:
                ReviewService.post_message(db_session, c.process, c.student.id, body=cuerpo)
            assert str(exc.value) == MESSAGE_EMPTY_MSG
        with pytest.raises(ValueError) as exc:
            ReviewService.post_message(db_session, c.process, c.student.id, body="x" * 4001)
        assert str(exc.value) == MESSAGE_TOO_LONG_MSG
        ReviewService.post_message(db_session, c.process, c.student.id, body="x" * 4000)
        for extrano in (make_user(first_name="AJENO"), caso().teachers["president"]):
            with pytest.raises(ValueError) as exc:
                ReviewService.post_message(db_session, c.process, extrano.id, body="Hola")
            assert str(exc.value) == NOT_PARTICIPANT_MSG
        assert len(_mensajes(db_session, c.chat.id)) == antes + 1

    def test_messages_orden_after_y_autores(self, db_session, caso):
        c = caso(versions=0)
        v = ReviewService.upload_version(db_session, c.process, c.student.id,
                                         raw=PDF, original_name="tesis.pdf")
        m1 = ReviewService.post_message(db_session, c.process, c.teachers["president"].id,
                                        body="Revisa la portada")
        _votar(db_session, c, "president", "changes_requested", comment="Portada")
        m3 = ReviewService.post_message(db_session, c.process, c.student.id, body="Listo")

        items = ReviewService.messages(db_session, c.chat.id)

        assert [i["kind"] for i in items] == ["version", "message", "vote", "message"]
        assert [i["id"] for i in items] == sorted(i["id"] for i in items)
        version, msg, voto, mio = items
        assert version["version_number"] == 1 and version["attachment"]["name"] == "tesis.pdf"
        assert version["author_label"] == "Alumno" and version["is_student"] is True
        assert msg["author_role"] == "president" and msg["author_label"] == "Presidente"
        assert msg["author_name"] == _nombre(c.teachers["president"])
        assert msg["attachment"] is None and msg["created_label"]
        assert voto["version_id"] == v.id
        assert mio["body"] == "Listo"
        nuevos = ReviewService.messages(db_session, c.chat.id, after_id=m1.id)
        assert [i["id"] for i in nuevos] == [voto["id"], m3.id]
        assert ReviewService.messages(db_session, c.chat.id, after_id=m3.id) == []

    def test_messages_sin_n_mas_1(self, db_session, caso):
        from sqlalchemy import event

        def _contar(fn):
            sentencias = []
            conn = db_session.connection()

            def _ver(_c, _cur, statement, *_a):
                sentencias.append(statement)
            event.listen(conn, "before_cursor_execute", _ver)
            try:
                fn()
            finally:
                event.remove(conn, "before_cursor_execute", _ver)
            return len(sentencias)

        c = caso()
        chat_id = c.chat.id
        roles = ("president", "secretary", "vocal")
        for role in roles:
            ReviewService.post_message(db_session, c.process, c.teachers[role].id, body=role)
        pocos = _contar(lambda: ReviewService.messages(db_session, chat_id))
        for _ in range(3):
            for role in roles:
                ReviewService.post_message(db_session, c.process, c.teachers[role].id,
                                           body=role)
            ReviewService.post_message(db_session, c.process, c.student.id, body="alumno")
        db_session.expire_all()
        muchos = _contar(lambda: ReviewService.messages(db_session, chat_id))
        assert muchos == pocos <= 4


# ---------------------------------------------------------------------------
# Apertura: `assign` crea la conversación; respaldo `chat_for(create=True)`
# ---------------------------------------------------------------------------
class TestApertura:
    def test_assign_crea_la_conversacion_y_su_mensaje(
            self, db_session, seed_phase_defs, make_department, make_program,
            make_program_department, make_academic_head, make_teacher, make_user,
            make_student, make_process, make_modality, make_format_b):
        seed_phase_defs()
        depto = make_department(name="Depto apertura revision")
        programa = make_program("Ingenieria Ficticia Apertura Revision")
        make_program_department(programa, depto)
        jefe = make_academic_head(depto, kind="head")
        docentes = [make_teacher(depto, user=make_user(first_name=f"DOC{i}",
                                                       last_name="APERTURA"))
                    for i in range(4)]
        modalidad = make_modality(name="Tesis apertura", requires_synodals=True)
        alumno = make_student(first_name="ALUMNA", last_name="APERTURA")
        proc = make_process(alumno, program=programa, modality=modalidad, current_phase=4)
        make_format_b(proc, status="approved", modality=modalidad, submission_count=1,
                      project_name="Proyecto apertura")
        assert _chat(db_session, proc.id) is None

        SynodalService.assign(db_session, proc, jefe.id,
                              president_id=docentes[0].id, secretary_id=docentes[1].id,
                              vocal_id=docentes[2].id, alternate_id=docentes[3].id)

        chat = _chat(db_session, proc.id)
        assert chat is not None and chat.closed_at is None
        (mensaje,) = _mensajes(db_session, chat.id)
        assert (mensaje.kind, mensaje.author_id, mensaje.body) == ("system", None, OPEN_CHAT_MSG)
        assert OPEN_CHAT_MSG == ("Tus sinodales quedaron asignados. Sube la primera versión "
                                 "de tu proyecto para empezar la revisión.")
        assert ReviewService.is_open(proc, chat) is True

    def test_open_chat_es_idempotente(self, db_session, caso):
        c = caso()
        assert ReviewService.open_chat(db_session, c.process).id == c.chat.id
        assert _mensajes(db_session, c.chat.id) == []

    def test_chat_for_respaldo_de_procesos_viejos(self, db_session, caso):
        c = caso()
        db_session.delete(c.chat)
        db_session.commit()
        assert ReviewService.chat_for(db_session, c.process) is None

        nuevo = ReviewService.chat_for(db_session, c.process, create=True)
        otra_vez = ReviewService.chat_for(db_session, c.process, create=True)

        assert nuevo is not None and otra_vez.id == nuevo.id
        (mensaje,) = _mensajes(db_session, nuevo.id)
        assert mensaje.kind == "system" and mensaje.body == OPEN_CHAT_MSG


# ---------------------------------------------------------------------------
# Participantes (§12): solo asignaciones VIGENTES; 404 sin header
# ---------------------------------------------------------------------------
class TestParticipantes:
    def test_assert_participant(self, db_session, caso, make_user):
        c, otro = caso(), caso()
        for role in ROLES:
            proc = ReviewService.assert_participant(db_session, c.teachers[role].id,
                                                    c.process.id)
            assert proc.id == c.process.id
            assert ReviewService.participant_role(db_session, c.process.id,
                                                  c.teachers[role].id) == role
        ajenos = (make_user(first_name="EXTRANO"), otro.student, c.student,
                  otro.teachers["president"])
        for ajeno in ajenos:
            with pytest.raises(HTTPException) as exc:
                ReviewService.assert_participant(db_session, ajeno.id, c.process.id)
            assert exc.value.status_code == 404
            assert not exc.value.headers
            assert ReviewService.participant_role(db_session, c.process.id, ajeno.id) is None
        with pytest.raises(HTTPException):
            ReviewService.assert_participant(db_session, c.teachers["president"].id,
                                             999_999_999)


# ---------------------------------------------------------------------------
# Archivos: solo dentro de la conversación del proceso autorizado (§7.2, §12)
# ---------------------------------------------------------------------------
class TestArchivos:
    def test_version_y_adjunto(self, db_session, caso):
        c = caso(versions=0)
        ReviewService.upload_version(db_session, c.process, c.student.id,
                                     raw=PDF, original_name="Mi tésis.pdf")
        version = next(m for m in _mensajes(db_session, c.chat.id) if m.kind == "version")
        adjunto = ReviewService.post_message(db_session, c.process, c.teachers["vocal"].id,
                                             body="Anotado", raw=DOCX,
                                             original_name="notas.docx")

        info = ReviewService.attachment_for(db_session, c.process.id, version.id)
        assert info["disposition"] == "inline" and info["mime"] == "application/pdf"
        assert info["download_name"] == "Mi_tesis.pdf"
        assert Path(info["path"]).read_bytes() == PDF

        info = ReviewService.attachment_for(db_session, c.process.id, adjunto.id)
        assert info["disposition"] == "attachment"
        assert info["mime"].endswith("wordprocessingml.document")
        assert info["download_name"] == "notas.docx"
        assert Path(info["path"]).read_bytes() == DOCX

    def test_mensaje_de_otro_proceso_o_sin_archivo(self, db_session, caso):
        a, b = caso(), caso()
        ajeno = ReviewService.post_message(db_session, b.process, b.student.id, body=None,
                                           raw=PDF, original_name="ajeno.pdf")
        texto = ReviewService.post_message(db_session, a.process, a.student.id, body="Hola")
        assert ReviewService.attachment_for(db_session, b.process.id, ajeno.id) is not None
        assert ReviewService.attachment_for(db_session, a.process.id, ajeno.id) is None
        assert ReviewService.attachment_for(db_session, a.process.id, texto.id) is None
        assert ReviewService.attachment_for(db_session, a.process.id, 999_999_999) is None

    def test_ruta_que_escapa_de_la_raiz(self, db_session, caso):
        c = caso()
        m = ReviewService.post_message(db_session, c.process, c.student.id, body=None,
                                       raw=PDF, original_name="a.pdf")
        m.attachment_path = "../../etc/passwd.pdf"
        db_session.commit()
        assert ReviewService.attachment_for(db_session, c.process.id, m.id) is None


# ---------------------------------------------------------------------------
# Leídos (§7.1)
# ---------------------------------------------------------------------------
class TestLeidos:
    def test_mark_read_y_unread_counts(self, db_session, caso):
        c, vacio = caso(), caso()
        alumno, presidente = c.student.id, c.teachers["president"].id
        a1 = ReviewService.post_message(db_session, c.process, alumno, body="uno")
        a2 = ReviewService.post_message(db_session, c.process, alumno, body="dos")
        p1 = ReviewService.post_message(db_session, c.process, presidente, body="tres")
        chats = [c.chat.id, vacio.chat.id]

        assert ReviewService.unread_counts(db_session, alumno, chats) == {
            c.chat.id: 1, vacio.chat.id: 0}
        assert ReviewService.unread_counts(db_session, presidente, chats)[c.chat.id] == 2
        assert ReviewService.unread_counts(db_session, presidente, []) == {}

        ReviewService.mark_read(db_session, c.chat.id, presidente, a2.id)
        assert ReviewService.unread_counts(db_session, presidente, chats)[c.chat.id] == 0
        ReviewService.mark_read(db_session, c.chat.id, presidente, a1.id)   # no retrocede
        assert ReviewService.unread_counts(db_session, presidente, chats)[c.chat.id] == 0
        ReviewService.mark_read(db_session, c.chat.id, alumno, p1.id)
        assert ReviewService.unread_counts(db_session, alumno, chats)[c.chat.id] == 0

        ReviewService.post_message(db_session, c.process, alumno, body="cuatro")
        assert ReviewService.unread_counts(db_session, presidente, chats)[c.chat.id] == 1


# ---------------------------------------------------------------------------
# Estado para el panel y para quien no está en la conversación (§8.3, §9.3)
# ---------------------------------------------------------------------------
class TestEstado:
    def test_sin_conversacion_es_none(self, db_session, caso):
        c = caso()
        db_session.delete(c.chat)
        db_session.commit()
        assert ReviewService.status_for_process(db_session, c.process.id) is None

    def test_integral(self, db_session, caso):
        c = caso()
        estado = ReviewService.status_for_process(db_session, c.process.id,
                                                  holidays=frozenset())
        assert estado["version"] == 1 and estado["closed"] is False
        assert estado["uploaded_at"] is not None and estado["due"] is not None
        assert estado["semaphore"] in ("ok", "warn", "late")
        assert [v["role"] for v in estado["votes"]] == list(ROLES)
        assert [v["counts"] for v in estado["votes"]] == [True, False, False, False]
        assert [v["role_label"] for v in estado["votes"]] == [
            "Presidente", "Secretario", "Vocal", "Vocal Suplente"]
        assert estado["votes"][0]["name"] == _nombre(c.teachers["president"])
        assert estado["rule_label"] == "Basta la aprobación del Presidente"
        assert (estado["approvals"], estado["required"]) == (0, 1)

    def test_tesis_y_cerrada(self, db_session, caso):
        c = caso(signature_rule="all_synodals")
        _votar(db_session, c, "secretary", "changes_requested", comment="Faltan anexos")
        _votar(db_session, c, "vocal")
        estado = ReviewService.status_for_process(db_session, c.process.id)
        assert all(v["counts"] for v in estado["votes"])
        assert [v["verdict"] for v in estado["votes"]] == [
            None, "changes_requested", "approved", None]
        assert estado["rule_label"] == "Se necesita la aprobación de los 4 sinodales"
        assert (estado["approvals"], estado["required"]) == (1, 4)

        for role in ("president", "secretary", "alternate"):
            _votar(db_session, c, role, confirm=True)
        estado = ReviewService.status_for_process(db_session, c.process.id)
        assert estado["closed"] is True and estado["semaphore"] is None

    def test_sin_version_no_corre_plazo(self, db_session, caso):
        c = caso(versions=0)
        estado = ReviewService.status_for_process(db_session, c.process.id)
        assert estado["version"] is None and estado["due"] is None
        assert estado["semaphore"] is None and estado["uploaded_at"] is None
        assert [v["verdict"] for v in estado["votes"]] == [None] * 4

    def test_plazo_y_semaforo_con_dias_inhabiles(self, db_session, caso, monkeypatch,
                                                  make_non_working_day):
        c = caso()
        c.versions[0].uploaded_at = datetime(2026, 10, 19, 10, 0)      # lunes
        db_session.commit()
        festivo = date(2026, 10, 20)
        assert ReviewService.due_date(c.versions[0], holidays=frozenset()) == date(2026, 11, 2)
        assert ReviewService.due_date(c.versions[0], holidays=frozenset({festivo})) == (
            date(2026, 11, 3))
        assert add_business_days(date(2026, 10, 19), 10) == date(2026, 11, 2)

        def _hoy(d):
            monkeypatch.setattr(rs_mod, "db_now", lambda: datetime.combine(d, datetime.min.time()))
            return ReviewService.status_for_process(db_session, c.process.id,
                                                    holidays=frozenset())

        assert _hoy(date(2026, 10, 28))["semaphore"] == "ok"      # faltan 3 hábiles
        assert _hoy(date(2026, 10, 29))["semaphore"] == "warn"    # faltan 2
        assert _hoy(date(2026, 11, 2))["semaphore"] == "warn"     # vence hoy
        assert _hoy(date(2026, 11, 3))["semaphore"] == "late"
        # El calendario se lee si no lo pasan: el festivo recorre el plazo.
        from itcj2.apps.titulatec.services.non_working_day_service import (
            NonWorkingDayService,
        )
        make_non_working_day(festivo, "Inhábil de prueba")
        db_session.commit()
        calendario = NonWorkingDayService.holidays(db_session)
        assert festivo in calendario
        estado = ReviewService.status_for_process(db_session, c.process.id)
        assert estado["due"] == ReviewService.due_date(c.versions[0], holidays=calendario)
        assert estado["due"] >= date(2026, 11, 3)


# ---------------------------------------------------------------------------
# Bitácora: la red ORM copia versiones y votos, nunca mensajes ni leídos (§11)
# ---------------------------------------------------------------------------
class TestRedOrm:
    def test_versiones_y_votos_si_mensajes_y_leidos_no(self, db_session, caso):
        c = caso(signature_rule="all_synodals", versions=0)
        v = ReviewService.upload_version(db_session, c.process, c.student.id,
                                         raw=PDF, original_name="v.pdf")
        m = ReviewService.post_message(db_session, c.process, c.student.id, body="secreto")
        _votar(db_session, c, "vocal")
        ReviewService.mark_read(db_session, c.chat.id, c.student.id, m.id)
        db_session.flush()

        def _red(tabla):
            return audit_query(db_session).filter_by(source="data", entity_type=tabla).all()

        (alta_version,) = _red("titulatec_review_versions")
        assert alta_version.entity_id == v.id and alta_version.module == "review"
        (alta_voto,) = _red("titulatec_review_votes")
        assert alta_voto.action == "data.insert" and alta_voto.module == "review"
        assert _red("titulatec_chat_messages") == []
        assert _red("titulatec_chat_reads") == []


# ---------------------------------------------------------------------------
# Parciales compartidos: `partials/review/_messages.html` y `_status.html`
# ---------------------------------------------------------------------------
def _render(nombre, **ctx) -> str:
    from itcj2.apps.titulatec.pages.nav import titulatec_templates
    return titulatec_templates.get_template(
        f"titulatec/partials/review/{nombre}").render(**ctx)


class TestParciales:
    def test_mensajes_escapa_y_pinta_distinto_cada_tipo(self, db_session, caso):
        c = caso(versions=0)
        ReviewService.upload_version(db_session, c.process, c.student.id,
                                     raw=PDF, original_name="tesis.pdf")
        ReviewService.post_message(db_session, c.process, c.teachers["president"].id,
                                   body="<b>hola</b>\n<script>x</script>")
        _votar(db_session, c, "president", "changes_requested", comment="<i>ojo</i>")
        ReviewService.on_replaced(db_session, c.process, role="vocal",
                                  old_user_id=c.teachers["vocal"].id,
                                  new_user_id=c.teachers["alternate"].id)
        db_session.commit()
        items = ReviewService.messages(db_session, c.chat.id)

        html = _render("_messages.html", items=items, me_id=c.student.id,
                       file_base="/titulatec/student/revision/archivo/")

        assert "<b>hola</b>" not in html and "&lt;b&gt;hola&lt;/b&gt;" in html
        assert "<script>" not in html and "<i>ojo</i>" not in html
        for kind in ("message", "system", "version", "vote"):
            assert f"tt-rv-msg--{kind}" in html, kind
        for item in items:
            assert f'data-tt-msg-id="{item["id"]}"' in html
        version = next(i for i in items if i["kind"] == "version")
        assert f'href="/titulatec/student/revision/archivo/{version["id"]}"' in html
        assert "Tú" in html and "Presidente" in html
        # Sin `file_base` no hay ligas (el archivo solo sale por la ruta con guarda).
        assert "href=" not in _render("_messages.html", items=items, me_id=c.student.id)
        assert _render("_messages.html", items=[], me_id=1).strip() == ""

    def test_estado_integral_y_tesis(self, db_session, caso):
        integral, tesis = caso(), caso(signature_rule="all_synodals")
        _votar(db_session, tesis, "secretary", "changes_requested", comment="Faltan anexos")

        html_i = _render("_status.html", review_status=ReviewService.status_for_process(
            db_session, integral.process.id))
        html_t = _render("_status.html", review_status=ReviewService.status_for_process(
            db_session, tesis.process.id))

        assert "Basta la aprobación del Presidente" in html_i
        assert html_i.count("tt-rv-vote--counts") == 1
        assert html_i.count("tt-rv-vote--comments") == 3
        assert "Se necesita la aprobación de los 4 sinodales" in html_t
        assert html_t.count("tt-rv-vote--counts") == 4
        assert "Pidió cambios" in html_t and "Versión 1" in html_t
        for html in (html_i, html_t):
            assert 'id="tt-rv-status"' in html
            assert "/revisiones/" not in html and "Faltan anexos" not in html
        vacio = _render("_status.html", review_status=None)
        assert "Sin versiones todavía" in vacio

    def test_plantillas_y_estaticos_siguen_las_reglas_de_la_casa(self):
        plantillas = sorted((_APP / "templates" / "titulatec" / "partials" / "review")
                            .glob("*.html"))
        assert [p.name for p in plantillas] == ["_messages.html", "_status.html"]
        for p in plantillas:
            texto = p.read_text(encoding="utf-8")
            assert "<script" not in texto.lower(), p.name
            assert "style=" not in texto, p.name
        css = (_APP / "static" / "css" / "review.css").read_text(encoding="utf-8")
        sin_comentarios = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
        tamanos = re.findall(r"font-size\s*:\s*([^;}]+)", sin_comentarios)
        assert tamanos and all(t.strip().startswith("var(--tt-fs-") for t in tamanos), tamanos
        js = (_APP / "static" / "js" / "shared" / "review-thread.js").read_text(encoding="utf-8")
        assert re.search(r"^\(function \(\) \{", js, flags=re.MULTILINE), "IIFE"
        for gancho in ("DOMContentLoaded", "htmx:afterSettle", "htmx:configRequest"):
            assert gancho in js, gancho
        assert not re.search(r"\b(confirm|alert|prompt)\s*\(", js)
        assert "window.TitulaTecReviewThread" in js
