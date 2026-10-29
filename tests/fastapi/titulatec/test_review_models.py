"""Fase 5, tarea 1: modelos de la revision de sinodales y sus fixtures.

Spec 2026-10-22-titulatec-fase5-revision-sinodales §5. Se fija:
- `ChatMessage.kind` ('message' por omision), `author_id` NULL-able, constantes;
- unicos de version y voto, CHECK del veredicto, PK compuesta del recordatorio;
- `NonWorkingDay.day` unico;
- la fixture `make_review_case` arma el caso (fase por codigo, regla de firma,
  4 sinodales vigentes, chat abierto, versiones con PDF).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError


@pytest.fixture()
def caso(make_review_case):
    return make_review_case(versions=2)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
def test_constantes_del_dominio():
    from itcj2.apps.titulatec.models.chat import CHAT_KINDS
    from itcj2.apps.titulatec.models.review import REMINDER_KINDS, VOTE_VERDICTS

    assert CHAT_KINDS == ("message", "system", "version", "vote")
    assert VOTE_VERDICTS == ("approved", "changes_requested")
    assert REMINDER_KINDS == ("due_soon", "due_today")


def test_kind_por_omision_es_message(db_session, caso):
    from itcj2.apps.titulatec.models import ChatMessage

    m = ChatMessage(chat_id=caso.chat.id, author_id=caso.student.id, body="hola")
    db_session.add(m)
    db_session.flush()
    db_session.refresh(m)
    assert m.kind == "message"
    assert m.version_id is None and m.attachment_mime is None and m.attachment_size is None


def test_mensaje_de_sistema_sin_autor_y_ligado_a_version(db_session, caso):
    from itcj2.apps.titulatec.models import ChatMessage

    v = caso.versions[0]
    m = ChatMessage(chat_id=caso.chat.id, author_id=None, kind="version",
                    version_id=v.id, body="Version 1")
    db_session.add(m)
    db_session.flush()
    db_session.refresh(m)
    assert m.author_id is None and m.version_id == v.id and m.kind == "version"
    assert m.to_dict()["kind"] == "version"


def test_chat_nace_abierto_y_las_lecturas_tienen_pk_compuesta(db_session, caso):
    from itcj2.apps.titulatec.models import ChatMessage, ChatRead

    assert caso.chat.closed_at is None
    m = ChatMessage(chat_id=caso.chat.id, author_id=caso.student.id, body="x")
    db_session.add(m)
    db_session.flush()
    db_session.add(ChatRead(chat_id=caso.chat.id, user_id=caso.student.id,
                            last_read_message_id=m.id))
    db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(ChatRead(chat_id=caso.chat.id, user_id=caso.student.id,
                                    last_read_message_id=m.id))
            db_session.flush()


# ---------------------------------------------------------------------------
# Versiones, votos y recordatorios
# ---------------------------------------------------------------------------
def test_version_proceso_numero_es_unico(db_session, caso):
    from itcj2.apps.titulatec.models import ReviewVersion

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(ReviewVersion(process_id=caso.process.id, number=1,
                                         uploaded_by_id=caso.student.id))
            db_session.flush()


def test_voto_unico_por_version_y_asignacion(db_session, caso):
    from itcj2.apps.titulatec.models import ReviewVote

    asg = caso.assignments["president"]
    v = caso.versions[0]
    db_session.add(ReviewVote(version_id=v.id, assignment_id=asg.id,
                              user_id=asg.user_id, verdict="approved"))
    db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(ReviewVote(version_id=v.id, assignment_id=asg.id,
                                      user_id=asg.user_id, verdict="changes_requested"))
            db_session.flush()
    # Otra version del mismo sinodal si cabe.
    db_session.add(ReviewVote(version_id=caso.versions[1].id, assignment_id=asg.id,
                              user_id=asg.user_id, verdict="changes_requested",
                              comment="Falta el marco teorico"))
    db_session.flush()


def test_voto_con_veredicto_invalido_viola_el_check(db_session, caso):
    from itcj2.apps.titulatec.models import ReviewVote

    asg = caso.assignments["secretary"]
    with pytest.raises(IntegrityError) as exc:
        with db_session.begin_nested():
            db_session.add(ReviewVote(version_id=caso.versions[0].id, assignment_id=asg.id,
                                      user_id=asg.user_id, verdict="maybe"))
            db_session.flush()
    assert "ck_titulatec_review_votes_verdict" in str(exc.value)


def test_recordatorio_tiene_pk_compuesta(db_session, caso):
    from itcj2.apps.titulatec.models import ReviewReminder

    asg = caso.assignments["vocal"]
    v = caso.versions[0]
    db_session.add(ReviewReminder(version_id=v.id, assignment_id=asg.id, kind="due_soon"))
    db_session.flush()
    # Otro tipo para la misma version y sinodal si cabe.
    db_session.add(ReviewReminder(version_id=v.id, assignment_id=asg.id, kind="due_today"))
    db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(ReviewReminder(version_id=v.id, assignment_id=asg.id,
                                          kind="due_soon"))
            db_session.flush()


# ---------------------------------------------------------------------------
# Dias inhabiles
# ---------------------------------------------------------------------------
def test_dia_inhabil_es_unico(db_session, make_non_working_day):
    from itcj2.apps.titulatec.models import NonWorkingDay

    dia = date(2031, 3, 17)
    fila = make_non_working_day(dia, "Natalicio de Benito Juarez")
    assert fila.description == "Natalicio de Benito Juarez"
    assert make_non_working_day(dia) is fila            # la fixture es idempotente
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(NonWorkingDay(day=dia, description="Duplicado"))
            db_session.flush()


# ---------------------------------------------------------------------------
# La fixture arma el caso
# ---------------------------------------------------------------------------
def test_la_fixture_arma_el_caso(db_session, caso):
    from itcj2.apps.titulatec.models import ProcessPhase
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    n_review = PhaseService.phase_number_for_code(db_session, "synodal_review")
    proc = caso.process
    assert proc.status == "active" and proc.current_phase == n_review

    fases = {p.phase_number: p.status for p in
             db_session.query(ProcessPhase).filter_by(process_id=proc.id)}
    assert all(fases[k] == "approved" for k in range(n_review))
    assert fases[n_review] == "in_progress"

    assert set(caso.teachers) == {"president", "secretary", "vocal", "alternate"}
    assert set(caso.assignments) == set(caso.teachers)
    assert all(a.is_active and a.process_id == proc.id for a in caso.assignments.values())
    assert len({t.id for t in caso.teachers.values()}) == 4
    assert all(caso.assignments[r].user_id == caso.teachers[r].id for r in caso.teachers)

    assert caso.chat.process_id == proc.id and caso.chat.closed_at is None

    assert [v.number for v in caso.versions] == [1, 2]
    for v in caso.versions:
        assert v.id and v.process_id == proc.id and v.uploaded_by_id == caso.student.id
        assert Path(v.file_path).read_bytes().startswith(b"%PDF-1.4")


def test_la_fixture_respeta_regla_fase_y_versiones(db_session, make_review_case):
    from itcj2.apps.titulatec.models import Modality, ProcessPhase
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    a = make_review_case(signature_rule="all_synodals", versions=0, phase_status="approved")
    b = make_review_case()
    assert a.versions == [] and len(b.versions) == 1
    mod_a = db_session.get(Modality, a.process.modality_id)
    mod_b = db_session.get(Modality, b.process.modality_id)
    assert mod_a.signature_rule == "all_synodals" and mod_a.requires_synodals
    assert mod_b.signature_rule == "president_only"
    assert mod_a.code != mod_b.code
    n = PhaseService.phase_number_for_code(db_session, "synodal_review")
    estado = db_session.query(ProcessPhase.status).filter_by(
        process_id=a.process.id, phase_number=n).scalar()
    assert estado == "approved"
