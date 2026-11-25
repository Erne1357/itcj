"""Aviso de cierre de convocatoria (`cohort_closing`, 2026-11-25): a quién le
toca (`aviso_cierre_no_aplica`), cómo se compone y re-valida al enviar, y el
comando `titulatec avisar-cierre-convocatoria` que lo encola (idempotente por
fecha). La barrida de `test_mail_compose.py::todos` cubre el render estricto."""
from __future__ import annotations

from datetime import timedelta

import pytest
from click.testing import CliRunner

from itcj2.cli.titulatec.mantenimiento import avisar_cierre_convocatoria_command
from itcj2.core.utils.timezone import db_now


@pytest.fixture()
def proceso(seed_phase_defs, make_student, make_process):
    """Proceso con sus 9 fases: las anteriores a `fase` aprobadas. `fase=3` =
    liberado por Servicios Escolares (la fase 2 aprobada)."""
    seed_phase_defs()

    def _make(fase=1, status="active"):
        return make_process(make_student(first_name="ALUMNA"), current_phase=fase,
                            status=status)

    return _make


def _cierre(dias=2):
    return db_now().date() + timedelta(days=dias)


def _filas(db, proc):
    from itcj2.apps.titulatec.models import EmailOutbox

    db.flush()
    return (db.query(EmailOutbox)
            .filter_by(process_id=proc.id, kind="cohort_closing").all())


def _componer(db, proc):
    from itcj2.apps.titulatec.services.mail_compose import MailComposer
    from itcj2.core.models.user import User

    return MailComposer.compose(db, _filas(db, proc), proc, db.get(User, proc.student_id))


@pytest.mark.parametrize("fase,status,motivo", [
    (1, "active", None),
    (2, "active", None),
    (3, "active", "Servicios Escolares ya lo liberó"),
    (2, "on_hold", "el proceso ya no está activo"),
])
def test_le_toca_a_los_activos_sin_liberar(db_session, proceso, fase, status, motivo):
    from itcj2.apps.titulatec.services.mail_compose import aviso_cierre_no_aplica

    assert aviso_cierre_no_aplica(db_session, proceso(fase=fase, status=status)) == motivo


def test_se_compone_con_la_fecha_y_lo_que_falta(db_session, proceso):
    from itcj2.apps.titulatec.services.email_helper import _render
    from itcj2.apps.titulatec.services.mail_compose import Composed
    from itcj2.apps.titulatec.services.student_mail import StudentMail
    from itcj2.apps.titulatec.utils.dates_es import dia_largo

    p = proceso(fase=1)
    assert StudentMail.cohort_closing(db_session, p, closes_on=_cierre()) is True

    c = _componer(db_session, p)

    assert isinstance(c, Composed)
    assert c.subject == ("[TitulaTec ITCJ] Última semana para completar tu trámite "
                         "con Servicios Escolares")
    assert c.template == "cohort_closing.html"
    assert c.context["fecha_limite"] == dia_largo(_cierre())
    assert "que Servicios Escolares apruebe tus documentos iniciales" in c.context["falta"]
    html = _render(c.template, c.context)
    assert dia_largo(_cierre()) in html and "CURP" in html and c.link in html


@pytest.mark.parametrize("cambio,motivo", [
    ("liberado", "Servicios Escolares ya lo liberó"),
    ("en_pausa", "el proceso ya no está activo"),
])
def test_queda_obsoleto_si_ya_no_aplica_al_enviar(db_session, proceso, cambio, motivo):
    from itcj2.apps.titulatec.models import ProcessPhase
    from itcj2.apps.titulatec.services.mail_compose import Obsolete
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    p = proceso(fase=2)
    assert StudentMail.cohort_closing(db_session, p, closes_on=_cierre()) is True
    if cambio == "liberado":
        (db_session.query(ProcessPhase)
         .filter_by(process_id=p.id, phase_number=2).one()).status = "approved"
    else:
        p.status = "on_hold"
    db_session.flush()

    assert _componer(db_session, p) == Obsolete(motivo)


def test_queda_obsoleto_si_la_convocatoria_ya_cerro(db_session, proceso):
    from itcj2.apps.titulatec.services.mail_compose import Obsolete
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    p = proceso(fase=1)
    assert StudentMail.cohort_closing(db_session, p, closes_on=_cierre(-1)) is True

    assert _componer(db_session, p) == Obsolete("la convocatoria ya cerró")


def test_comando_encola_solo_a_quien_le_toca_y_no_duplica(
        db_session, patched_session_local, proceso):
    fase1, fase2 = proceso(fase=1), proceso(fase=2)
    liberado, en_pausa = proceso(fase=3), proceso(fase=2, status="on_hold")
    args = ["--cierre", _cierre().isoformat()]

    seco = CliRunner().invoke(avisar_cierre_convocatoria_command, args + ["--dry-run"])
    assert seco.exit_code == 0, seco.output
    assert "Dry-run" in seco.output
    assert all(not _filas(db_session, p) for p in (fase1, fase2, liberado, en_pausa))

    res = CliRunner().invoke(avisar_cierre_convocatoria_command, args)
    assert res.exit_code == 0, res.output
    assert [len(_filas(db_session, p)) for p in (fase1, fase2, liberado, en_pausa)] == [1, 1, 0, 0]
    fila = _filas(db_session, fase1)[0]
    assert fila.payload == {"closes_on": _cierre().isoformat()}
    assert fila.status == "pending"

    otra = CliRunner().invoke(avisar_cierre_convocatoria_command, args)
    assert otra.exit_code == 0, otra.output
    assert [len(_filas(db_session, p)) for p in (fase1, fase2)] == [1, 1]


def test_comando_rechaza_una_fecha_que_ya_paso(db_session, patched_session_local, proceso):
    p = proceso(fase=1)

    res = CliRunner().invoke(avisar_cierre_convocatoria_command,
                             ["--cierre", _cierre(-1).isoformat()])

    assert res.exit_code == 2
    assert "ya pasó" in res.output
    assert not _filas(db_session, p)
