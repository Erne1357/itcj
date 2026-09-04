"""La limpieza de adjuntos y los tickets CANCELADOS.

Hasta 2026-09-04 la tarea `cleanup_attachments` solo miraba `status == 'CLOSED'`,
en sus DOS pasos: el que marca (`set_auto_delete_on_closed_tickets`) y el que
borra (`_cleanup_with_metrics`). Un ticket cancelado no recibia nunca
`auto_delete_at`, y aunque lo recibiera por otra via el segundo filtro lo volvia
a excluir.

Y no era «todavia no le toca»: `CANCELED` es estado TERMINAL — comprobado en
`helpdesk_status_transition`, no hay ninguna fila que salga de el. Asi que un
ticket cancelado JAMAS podia llegar a `CLOSED`, y sus archivos se quedaban en
disco para siempre. Alcanzable de verdad: `PENDING -> CANCELED` y
`ASSIGNED -> CANCELED` existen, y un ticket nace con sus imagenes ya adjuntas.

Decisiones del usuario (2026-09-04):

* Los cancelados se limpian **sin periodo de gracia**: si se cancelo hace un
  minuto y la tarea corre, sus archivos se van. No esperan los 7 dias de los
  cerrados, porque un ticket cancelado no va a volver.
* Se borran **los archivos**, no los comentarios. El texto de la conversacion se
  queda: es como se sabe por que se cancelo.
* Queda la **misma nota de auditoria** que en los cerrados. Sin ella, un ticket
  cancelado con fotos es indistinguible de uno que nunca tuvo ninguna.
"""
from __future__ import annotations

import os
from datetime import timedelta

import pytest

import itcj2.models  # noqa: F401  (resuelve los mappers)
from itcj2.core.utils.timezone import db_now

VIVOS = ("PENDING", "ASSIGNED", "IN_PROGRESS", "RESOLVED_SUCCESS", "RESOLVED_FAILED")


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture()
def escenario(db_session, tmp_path):
    """Fabrica tickets con adjuntos REALES en disco.

    Los archivos se escriben de verdad porque lo que se prueba es un borrado de
    disco: con rutas inventadas, `os.remove` nunca se ejecutaria y el test
    pasaria sin tocar la rama que importa.
    """
    from itcj2.apps.helpdesk.models.attachment import Attachment
    from itcj2.apps.helpdesk.models.category import Category
    from itcj2.apps.helpdesk.models.comment import Comment
    from itcj2.apps.helpdesk.models.ticket import Ticket
    from itcj2.core.models.user import User

    contador = {"n": 0}

    usuario = User(username=f"tst_clean_{os.getpid()}", first_name="ACTOR",
                   last_name="LIMPIEZA", is_active=True)
    db_session.add(usuario)
    db_session.flush()

    categoria = Category(area="SOPORTE", code=f"tst_clean_{os.getpid()}",
                         name="Categoria de prueba", is_active=True)
    db_session.add(categoria)
    db_session.flush()

    def _adjunto(ticket, tipo="ticket", comentario=None, marcado=None, nombre=None):
        contador["n"] += 1
        nombre = nombre or f"archivo_{contador['n']}.jpg"
        ruta = tmp_path / f"{ticket.id}_{contador['n']}_{nombre}"
        ruta.write_bytes(b"\xff\xd8\xff" + b"x" * 500)   # 503 bytes
        att = Attachment(
            ticket_id=ticket.id, uploaded_by_id=usuario.id,
            attachment_type=tipo,
            comment_id=comentario.id if comentario is not None else None,
            filename=nombre, original_filename=nombre, filepath=str(ruta),
            mime_type="image/jpeg", file_size=503, auto_delete_at=marcado,
        )
        db_session.add(att)
        db_session.flush()
        return att

    def _ticket(status, *, cerrado_hace_dias=None, adjuntos=1, con_comentario=False):
        contador["n"] += 1
        t = Ticket(
            ticket_number=f"TST-CLEAN-{os.getpid()}-{contador['n']:04d}",
            requester_id=usuario.id, area="SOPORTE", category_id=categoria.id,
            priority="MEDIA", title="Ticket de prueba",
            description="Descripcion original.", status=status,
            created_by_id=usuario.id, updated_by_id=usuario.id,
        )
        db_session.add(t)
        db_session.flush()
        if cerrado_hace_dias is not None:
            t.updated_at = db_now() - timedelta(days=cerrado_hace_dias)
            db_session.flush()

        comentario = None
        if con_comentario:
            comentario = Comment(ticket_id=t.id, author_id=usuario.id,
                                 content="El usuario ya no lo necesita.",
                                 is_internal=False)
            db_session.add(comentario)
            db_session.flush()

        atts = [_adjunto(t) for _ in range(adjuntos)]
        if con_comentario:
            atts.append(_adjunto(t, tipo="comment", comentario=comentario))
        return {"ticket": t, "adjuntos": atts, "comentario": comentario}

    return {"ticket": _ticket, "adjunto": _adjunto, "user": usuario,
            "categoria": categoria}


def _limpia(db):
    """Ejecuta el paso de borrado real y devuelve (borrados, bytes, por_ticket)."""
    from itcj2.tasks.helpdesk_tasks import _cleanup_with_metrics
    errores: list = []
    borrados, bytes_, por_ticket = _cleanup_with_metrics(db, errores)
    assert not errores, f"la limpieza reporto errores: {errores}"
    return borrados, bytes_, por_ticket


def _vive(db, att) -> bool:
    from itcj2.apps.helpdesk.models.attachment import Attachment
    return db.get(Attachment, att.id) is not None


# ===========================================================================
# 1. El cancelado se limpia YA
# ===========================================================================
def test_un_cancelado_pierde_sus_adjuntos_sin_esperar(escenario, db_session):
    """Sin periodo de gracia: se cancelo hace un instante y la tarea corre."""
    esc = escenario["ticket"]("CANCELED", adjuntos=2)
    rutas = [a.filepath for a in esc["adjuntos"]]
    assert all(os.path.exists(r) for r in rutas), "el andamiaje no escribio los archivos"

    borrados, bytes_, _ = _limpia(db_session)

    assert borrados == 2, "los adjuntos del cancelado siguen ahi"
    assert bytes_ == 2 * 503, "no se contaron los bytes liberados"
    assert not any(os.path.exists(r) for r in rutas), "la fila se borro pero el archivo no"
    assert not any(_vive(db_session, a) for a in esc["adjuntos"])


def test_no_hace_falta_que_alguien_lo_marque_antes(escenario, db_session):
    """El cancelado entra con `auto_delete_at` en NULL.

    Es el punto exacto donde fallaba: el paso 1 solo marca cerrados, asi que un
    cancelado nunca tiene marca, y el paso 2 exigia marca para borrar.
    """
    esc = escenario["ticket"]("CANCELED")
    assert esc["adjuntos"][0].auto_delete_at is None

    borrados, _, _ = _limpia(db_session)
    assert borrados == 1


def test_se_van_los_tres_tipos_de_adjunto(escenario, db_session):
    """Imagen del ticket, archivo de resolucion y archivo de un comentario.

    «Los adjuntos del ticket y cualquier comentario o cualquier cosa similar»:
    los tres cuelgan de la misma tabla y los tres se van.
    """
    esc = escenario["ticket"]("CANCELED", adjuntos=1, con_comentario=True)
    resolucion = escenario["adjunto"](esc["ticket"], tipo="resolution")

    borrados, _, por_ticket = _limpia(db_session)

    assert borrados == 3
    fila = por_ticket[esc["ticket"].ticket_number]
    assert fila["ticket_image"] == 1
    assert fila["resolution"] == 1
    assert fila["comment"] == 1
    assert not _vive(db_session, resolucion)


# ===========================================================================
# 2. Lo que NO se toca
# ===========================================================================
def test_el_comentario_sobrevive_a_su_archivo(escenario, db_session):
    """Decision del usuario: se borran los archivos, NO la conversacion.

    El texto es como se sabe por que se cancelo el ticket; sin el, un cancelado
    queda mudo.
    """
    from itcj2.apps.helpdesk.models.comment import Comment
    esc = escenario["ticket"]("CANCELED", adjuntos=0, con_comentario=True)
    comentario_id = esc["comentario"].id

    _limpia(db_session)

    vivo = db_session.get(Comment, comentario_id)
    assert vivo is not None, "se borro el comentario, no solo su archivo"
    assert "El usuario ya no lo necesita." in vivo.content, "se perdio el texto original"


@pytest.mark.parametrize("status", VIVOS)
def test_un_ticket_que_sigue_su_curso_no_pierde_nada(escenario, db_session, status):
    """La negativa que hace util a la positiva: solo CANCELED se salta la espera.

    RESOLVED_* entra aqui a proposito: no es estado final (transiciona a CLOSED
    cuando el solicitante califica), asi que sus archivos todavia se pueden
    necesitar.
    """
    esc = escenario["ticket"](status, adjuntos=1)

    borrados, _, _ = _limpia(db_session)

    assert borrados == 0, f"se borro un adjunto de un ticket {status}"
    assert os.path.exists(esc["adjuntos"][0].filepath)


def test_un_cerrado_reciente_sigue_esperando_sus_siete_dias(escenario, db_session):
    """Regresion: la guarda de los cerrados no se toca al añadir los cancelados."""
    esc = escenario["ticket"]("CLOSED", cerrado_hace_dias=1, adjuntos=1)
    esc["adjuntos"][0].auto_delete_at = db_now() - timedelta(hours=1)   # marca vencida
    db_session.flush()

    borrados, _, _ = _limpia(db_session)

    assert borrados == 0, (
        "se borro un cerrado de ayer: la doble guarda (marca + 7 dias) se perdio")


def test_un_cerrado_viejo_y_marcado_si_se_limpia(escenario, db_session):
    """Y la positiva del mismo actor: el camino de los cerrados sigue vivo."""
    esc = escenario["ticket"]("CLOSED", cerrado_hace_dias=30, adjuntos=1)
    esc["adjuntos"][0].auto_delete_at = db_now() - timedelta(days=23)
    db_session.flush()

    borrados, _, _ = _limpia(db_session)
    assert borrados == 1


# ===========================================================================
# 3. Rastro
# ===========================================================================
def test_queda_nota_de_auditoria_en_el_cancelado(escenario, db_session):
    """Sin nota, un cancelado con fotos no se distingue de uno que nunca las tuvo."""
    from itcj2.apps.helpdesk.models.ticket import Ticket
    esc = escenario["ticket"]("CANCELED", adjuntos=2)
    ticket_id = esc["ticket"].id

    _limpia(db_session)

    t = db_session.get(Ticket, ticket_id)
    db_session.refresh(t)
    assert "Descripcion original." in t.description, "la nota pisó la descripcion"
    assert "2 imagen(es)" in t.description, "no quedo constancia del borrado"


# ===========================================================================
# 4. Los dos caminos tienen que ver lo mismo
# ===========================================================================
def test_el_dry_run_cuenta_lo_mismo_que_borra_la_ejecucion_real(escenario, db_session):
    """El conteo del dry-run y el borrado real vivian en DOS consultas copiadas.

    Dos copias de un `filter` es una que se queda atras: el dry-run diria «no voy
    a borrar nada» mientras la real borra, o al reves. Ahora comparten predicado
    y este test lo fija.
    """
    from itcj2.tasks.helpdesk_tasks import _attachments_a_borrar

    escenario["ticket"]("CANCELED", adjuntos=2, con_comentario=True)
    escenario["ticket"]("PENDING", adjuntos=1)
    viejo = escenario["ticket"]("CLOSED", cerrado_hace_dias=30, adjuntos=1)
    viejo["adjuntos"][0].auto_delete_at = db_now() - timedelta(days=23)
    db_session.flush()

    previstos = {a.id for a in _attachments_a_borrar(db_session)}
    assert len(previstos) == 4, f"el predicado ve {len(previstos)}, esperaba 4"

    borrados, _, _ = _limpia(db_session)
    assert borrados == len(previstos)


def test_el_dry_run_no_borra_nada(escenario, db_session, monkeypatch):
    """Cuenta, informa y no toca ni disco ni base."""
    from itcj2.tasks.helpdesk_tasks import _attachments_a_borrar
    esc = escenario["ticket"]("CANCELED", adjuntos=2)

    previstos = _attachments_a_borrar(db_session)

    assert len(previstos) == 2
    assert all(os.path.exists(a.filepath) for a in esc["adjuntos"])
    assert all(_vive(db_session, a) for a in esc["adjuntos"])
