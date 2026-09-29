"""Zona «Correos» del expediente (spec 2026-09-28-titulatec-correos-notificaciones §7, Task 10).

`_detail_ctx` (`pages/admin.py`) agrega la clave `correos`: la bitácora de
`titulatec_email_outbox` de ESE proceso, más nueva primero, de SOLO LECTURA
(D11 — sin botón de reenviar). `_exp_shell.html` la pinta como una sección
colapsable y cerrada por omisión al final del expediente, que no existe en el
DOM si el proceso no tiene ninguna fila (mismo patrón que `#exp-otros`).

Esto cubre: la zona no se pinta sin filas, los cinco estados con su etiqueta
(y el motivo del fallo visible), el orden más nuevo primero, ids estables por
fila (`exp-mail-{id}`, morph-safe), el alcance por carrera (404, no 403 — la
misma guarda que el resto del expediente) y que leerla no agrega un N+1 (una
sola consulta de `StudentMail.history`, sin importar cuántas filas haya).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from tests.fastapi.titulatec.conftest import OFFICER_PERMS

URL = "/titulatec/admin/processes"


# ---------------------------------------------------------------------------
# Andamiaje local
# ---------------------------------------------------------------------------
@pytest.fixture()
def expediente(seed_phase_defs, seed_document_types, make_program, make_cohort,
               make_officer, make_student, make_process):
    """Un proceso con un encargado que puede VER el expediente.

    Mismo molde que `test_expediente_proceso.py::expediente`, sin los permisos
    de dictamen (`approve_phase`/`reject_phase`): esta zona es de solo lectura,
    no hace falta poder mover de fase para verla. `OFFICER_PERMS` ya trae
    `titulatec.process.page.detail`.
    """
    def _build(current_phase=2, status="active"):
        seed_phase_defs()
        seed_document_types()
        prog = make_program("Ingeniería del Expediente de Correos")
        cohort = make_cohort()
        officer, _pos = make_officer([prog], perm_codes=OFFICER_PERMS)
        student = make_student(first_name="ANA", last_name="CORREO")
        proc = make_process(student, cohort=cohort, program=prog,
                            current_phase=current_phase, status=status)
        return {"officer": officer, "student": student, "proc": proc,
                "program": prog, "cohort": cohort}
    return _build


def _fila(db_session, proc, *, kind="phase_approved", status="sent", subject=None,
         sent_to=None, last_error=None, group_key=None, sent_at=None, created_at=None):
    """Fila de `titulatec_email_outbox` insertada DIRECTO (no vía `StudentMail`,
    que solo deja filas `pending`): esta zona lee lo que el despachador YA
    dejó, así que las pruebas necesitan poblar cada estado a mano."""
    from itcj2.apps.titulatec.models import EmailOutbox

    row = EmailOutbox(kind=kind, process_id=proc.id, user_id=proc.student_id,
                      payload={}, status=status, subject=subject,
                      sent_to=sent_to, last_error=last_error, group_key=group_key,
                      sent_at=sent_at)
    if created_at is not None:
        row.created_at = created_at
    db_session.add(row)
    db_session.flush()
    return row


def _zona(html):
    """La bitácora: de `#exp-correos` al final del HTML."""
    return html.split('id="exp-correos"', 1)[1]


def _entradas(zona):
    """Entradas de la bitácora (una por correo)."""
    return zona.count('class="tt-timeline-item"')


# ===========================================================================
# 1. No se pinta sin filas
# ===========================================================================
def test_sin_correos_no_pinta_la_zona(expediente, client_as):
    esc = expediente()
    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}").text
    assert 'id="exp-correos"' not in html, (
        "un proceso sin ninguna fila del outbox no debería tener la sección")


# ===========================================================================
# 2. Los cinco estados, con su etiqueta y el motivo del fallo
# ===========================================================================
def test_pinta_los_cinco_estados_con_su_etiqueta(expediente, client_as, db_session):
    esc = expediente()
    proc = esc["proc"]
    casos = [
        ("sent", "Enviado", "alumno@example.com", None),
        ("pending", "En cola", None, None),
        ("failed", "Falló", None, "Cuenta de correo no conectada"),
        ("no_recipient", "Sin correo personal", None, None),
        ("obsolete", "Ya no aplicaba", None, None),
    ]
    for status, _etiqueta, to, err in casos:
        _fila(db_session, proc, status=status, sent_to=to, last_error=err)

    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}").text
    assert 'id="exp-correos"' in html
    for _status, etiqueta, _to, _err in casos:
        assert etiqueta in html, f"falta la etiqueta de {_status!r}: {etiqueta!r}"
    assert "Cuenta de correo no conectada" in html, (
        "el motivo del fallo (`last_error`) no salió en el fallido")
    assert "alumno@example.com" in html, "el destinatario del enviado no salió"


def test_sin_asunto_usa_la_etiqueta_del_tipo(expediente, client_as, db_session):
    """`subject` solo se llena al enviar (bitácora del despachador); antes de
    eso la fila enseña `StudentMail.KIND_LABELS[kind]`, no un hueco vacío."""
    esc = expediente()
    _fila(db_session, esc["proc"], kind="phase_rejected", status="pending",
         subject=None)

    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}").text
    assert "Fase rechazada" in html, (
        "sin asunto (aún no se envía) debería caer al nombre del tipo")


def test_kind_desconocido_no_revienta_la_pagina(expediente, client_as, db_session):
    """Fix round 1 (ronda de arreglo 1, hallazgo Importante): `EmailOutbox.kind`
    es `String(40)` SIN CHECK en BD — nada impide una fila con un `kind` que
    `StudentMail.KIND_LABELS` no conoce (`StudentMail.enqueue`, que sí valida
    contra `OUTBOX_KINDS`, no es el único camino de escritura posible; esta
    fila se inserta DIRECTO, como haría una migración de datos manual o un
    `kind` nuevo del catálogo sin actualizar `KIND_LABELS`). Antes del fix
    `KIND_LABELS[m.kind]` indexaba directo y tronaba con `KeyError` -> 500 de
    TODO el expediente, no solo de esa fila. El resto del archivo degrada con
    `.get(...)` (`_MAIL_STATUS_UI`, `_EVENT_UI`); esta fila debe hacer lo
    mismo: 200 y el código crudo en vez de una etiqueta."""
    esc = expediente()
    _fila(db_session, esc["proc"], kind="un_kind_que_no_existe", subject=None)

    r = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}")
    assert r.status_code == 200, (
        f"un kind sin etiqueta no debe tumbar la página: {r.status_code}")
    assert "un_kind_que_no_existe" in r.text, (
        "sin etiqueta debería degradar al código crudo, no ocultar la fila")


def test_sin_destinatario_muestra_raya(expediente, client_as, db_session):
    """`sent_to` va vacío en lo que no se ha enviado: la fila lo dice con «—»,
    no con un espacio en blanco ni resolviendo el correo aquí."""
    esc = expediente()
    _fila(db_session, esc["proc"], status="pending", sent_to=None)

    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}").text
    assert "—" in html.split('id="exp-correos"')[1][:4000]


# ===========================================================================
# 3. Orden e ids estables
# ===========================================================================
def test_orden_mas_nuevo_primero(expediente, client_as, db_session):
    from itcj2.core.utils.timezone import db_now

    esc = expediente()
    proc = esc["proc"]
    viejo = _fila(db_session, proc, kind="phase_rejected", subject="Correo viejo")
    nuevo = _fila(db_session, proc, kind="phase_approved", subject="Correo nuevo")
    ahora = db_now()
    viejo.created_at = ahora - timedelta(days=1)
    nuevo.created_at = ahora
    db_session.flush()

    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}").text
    assert html.index("Correo nuevo") < html.index("Correo viejo"), (
        "el más nuevo tiene que salir primero")


def test_ids_estables_por_fila(expediente, client_as, db_session):
    esc = expediente()
    fila = _fila(db_session, esc["proc"])
    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}").text
    assert f'id="exp-mail-{fila.id}"' in html, "morph-safe: id estable por fila"


# ===========================================================================
# 3b. Una entrada por CORREO, no por aviso (ruling 21)
# ===========================================================================
def test_un_grupo_enviado_junto_es_una_sola_entrada(expediente, client_as, db_session):
    """Los 3 dictámenes de documentos salieron en UN correo (mismo grupo, mismo
    estado, mismo `sent_at`, que el despachador pone igual a toda la unidad):
    UNA entrada con «3 avisos agrupados», la fecha de ENVÍO (no la de alta), el
    id de la fila más reciente del grupo, y el encabezado cuenta correos."""
    from datetime import datetime

    from itcj2.apps.titulatec.pages.admin import _fecha_larga

    esc = expediente()
    proc = esc["proc"]
    creado = datetime(2026, 3, 2, 10, 0)
    enviado = datetime(2026, 3, 4, 16, 45)
    avisos = [_fila(db_session, proc, kind="docs_review", status="sent",
                    subject="[TitulaTec ITCJ] Revisamos tus documentos",
                    sent_to="ana@example.com", group_key=f"docs:{proc.id}",
                    sent_at=enviado, created_at=creado + timedelta(minutes=i))
              for i in range(3)]
    _fila(db_session, proc, kind="phase_rejected", status="sent", subject="Otro correo",
          sent_to="ana@example.com", sent_at=datetime(2026, 3, 1, 9, 0),
          created_at=datetime(2026, 3, 1, 8, 50))

    zona = _zona(client_as(esc["officer"]).get(f"{URL}/{proc.id}").text)

    assert _entradas(zona) == 2
    assert zona.count("avisos agrupados") == 1
    assert "3 avisos agrupados" in zona
    assert _fecha_larga(enviado) in zona
    assert _fecha_larga(avisos[-1].created_at) not in zona   # la de alta NO
    assert f'id="exp-mail-{avisos[-1].id}"' in zona           # la fila más reciente
    assert not any(f'id="exp-mail-{f.id}"' in zona for f in avisos[:-1])
    assert "2 correos" in zona                                # correos, no 4 filas


def test_filas_sueltas_siguen_siendo_una_por_fila(expediente, client_as, db_session):
    """Sin `group_key` no hay a qué juntarlas, aunque compartan estado y hora de
    envío: cada una fue su propio correo."""
    from datetime import datetime

    esc = expediente()
    proc = esc["proc"]
    enviado = datetime(2026, 3, 4, 16, 45)
    sueltas = [_fila(db_session, proc, kind=kind, status="sent", subject=f"Correo {kind}",
                     sent_to="ana@example.com", sent_at=enviado)
               for kind in ("phase_approved", "survey_approved")]

    zona = _zona(client_as(esc["officer"]).get(f"{URL}/{proc.id}").text)

    assert _entradas(zona) == 2
    assert "avisos agrupados" not in zona
    assert all(f'id="exp-mail-{f.id}"' in zona for f in sueltas)


def test_el_mismo_grupo_en_dos_correos_son_dos_entradas(expediente, client_as, db_session):
    """Un grupo que salió en dos correos distintos (otro `sent_at`) son dos
    entradas; la del correo de un solo aviso no dice «agrupados»."""
    from datetime import datetime

    esc = expediente()
    proc = esc["proc"]
    grupo = f"cita:{proc.id}"
    primero, segundo = datetime(2026, 3, 4, 16, 45), datetime(2026, 3, 9, 11, 5)
    for enviado, n in ((primero, 2), (segundo, 1)):
        for _ in range(n):
            _fila(db_session, proc, kind="appt_changed", status="sent",
                  subject="[TitulaTec ITCJ] Tu cita de cotejo", sent_to="ana@example.com",
                  group_key=grupo, sent_at=enviado)

    zona = _zona(client_as(esc["officer"]).get(f"{URL}/{proc.id}").text)

    assert _entradas(zona) == 2
    assert zona.count("avisos agrupados") == 1 and "2 avisos agrupados" in zona


def test_un_grupo_en_cola_es_una_entrada_con_la_fecha_del_ultimo_aviso(
        expediente, client_as, db_session):
    """Lo que no ha salido muestra la fecha de ALTA del aviso más reciente del
    grupo (no hay fecha de envío): es el correo que va a salir con todos."""
    from datetime import datetime

    from itcj2.apps.titulatec.pages.admin import _fecha_larga

    esc = expediente()
    proc = esc["proc"]
    viejo, nuevo = datetime(2026, 3, 4, 16, 40), datetime(2026, 3, 4, 16, 47)
    for creado in (viejo, nuevo):
        _fila(db_session, proc, kind="docs_review", status="pending",
              group_key=f"docs:{proc.id}", created_at=creado)

    zona = _zona(client_as(esc["officer"]).get(f"{URL}/{proc.id}").text)

    assert _entradas(zona) == 1
    assert "2 avisos agrupados" in zona and "En cola" in zona
    assert _fecha_larga(nuevo) in zona and _fecha_larga(viejo) not in zona
    assert "1 correo</span>" in zona


# ===========================================================================
# 4. Alcance por carrera
# ===========================================================================
def test_fuera_de_alcance_404(expediente, client_as, make_program, make_officer,
                              db_session):
    """Un encargado de OTRA carrera no debe poder ver el expediente ajeno, ni
    su bitácora de correos: mismo 404 uniforme que el resto de la página."""
    esc = expediente()
    _fila(db_session, esc["proc"])
    otra_carrera = make_program("Otra Carrera Ajena a Correos")
    ajeno, _pos = make_officer([otra_carrera], perm_codes=OFFICER_PERMS)

    r = client_as(ajeno).get(f"{URL}/{esc['proc'].id}")
    assert r.status_code == 404


# ===========================================================================
# 5. Sin N+1: UNA consulta para toda la bitácora, no una por fila
# ===========================================================================
def test_una_sola_consulta_para_correos(expediente, client_as, db_session):
    from sqlalchemy import event

    esc = expediente()
    cli = client_as(esc["officer"])
    url = f"{URL}/{esc['proc'].id}"

    def _contar():
        n = [0]
        motor = db_session.get_bind()

        def _hook(*_a, **_k):
            n[0] += 1

        event.listen(motor, "before_cursor_execute", _hook)
        try:
            cli.get(url)
        finally:
            event.remove(motor, "before_cursor_execute", _hook)
        return n[0]

    _contar()                                    # calienta el caché de authz
    sin_correos = _contar()
    for _ in range(3):
        _fila(db_session, esc["proc"])
    con_correos = _contar()

    assert con_correos <= sin_correos, (
        f"la bitácora de correos crece las consultas: {sin_correos} -> {con_correos}")
