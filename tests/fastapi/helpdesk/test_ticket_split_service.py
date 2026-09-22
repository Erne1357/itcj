"""Task 3 (7) de la feature "Partir ticket": servicio
`ticket_split_service.split_ticket(db, ticket_id, split_by_id, original, parts)`.

El ticket original queda como parte 1 (se edita para acotarlo) y se crean 1..4
tickets nuevos a nombre del mismo solicitante, todo o nada, con copia FISICA de
los adjuntos iniciales (`attachment_type='ticket'`): nunca una ruta compartida,
porque la limpieza automatica borra el archivo de cada ticket al cerrarse y se
llevaria el de la otra parte.

Todo corre contra la BD real (`db_session`, savepoint). Los adjuntos viven en
`tmp_path` (nunca en `instance/`) con `Attachment.filepath` absoluto y un
`filename` con el prefijo `{id del original}` —igual que `_save_ticket_photo`:
`{id}.jpg`, `{id}_doc.{ext}.gz`— para ejercitar el renombrado por prefijo.

El servicio hace `db.rollback()` ante cualquier fallo, y con
`join_transaction_mode="create_savepoint"` eso desanda hasta el ultimo
`commit()`: por eso TODO el setup se commitea (los helpers lo hacen) antes de
llamarlo. Contra la base vacia de CI no hay catalogos: categorias (codigo unico
por test) y prioridades se siembran con `_catalog.py`.

El servicio se importa en tiempo de LLAMADA (`_svc()`), no de coleccion: asi la
evidencia RED es un `ModuleNotFoundError` por test, despues de que su setup
corrio, y no un error de coleccion que tumba el archivo entero.

Cubre (numeracion del brief de la tarea):
  1. PENDING en 3: el original cambia categoria/titulo/descripcion con sus
     `TicketEditLog` + el de `split`; las 2 partes nacen PENDING, sin asignar,
     con el solicitante, el depto sellado, la ubicacion, el folio y el
     `created_at` del original, `created_by_id` = actor, `split_from_ticket_id`
     = original y su StatusLog con la nota; folios distintos `TK-YYYY-NNNN`.
  2. Adjuntos `ticket` (imagen + doc `.gz`) copiados a archivos DISTINTOS por
     parte con el mismo contenido; el original conserva los suyos; los de
     `comment`/`resolution` no se copian.
  3. Archivo fuente borrado del disco -> la division sale igual, sin ese adjunto.
  4. ASSIGNED / IN_PROGRESS: conserva asignacion y estado, deja cambiar la
     categoria dentro del area; cambiar el area -> 400.
  5. Estados no partibles -> 400.
  6. Parte 3 invalida -> 400 "Parte 3: ..." y NADA persistido (ni tickets, ni
     ediciones del original, ni archivos). Extra: un error en la edicion del
     original llega como "Ticket original: ..." y tampoco deja nada.
  7. 0 partes o 5 partes nuevas -> 400 (extra: 4 nuevas, el tope, si sale).
  8. `custom_fields`: la parte que conserva la categoria PREVIA los hereda sin
     las claves de tipo `file`; la de otra categoria nace con `{}`.
  9. Falla TARDIA (el commit truena despues de copiar) -> 500, sin tickets
     nuevos y sin copias en disco.
  Extras: 404; titulo/descripcion de las partes guardados sin espacios
  alrededor; nombre de la copia cuando el destino ya existe (sufijo unico, sin
  pisar el archivo ajeno) y cuando el nombre no trae el prefijo del id.

La sesion de este modulo se comporta como la de la app (`autoflush=False`,
expira al commitear; ver `_session_like_production`): con los defaults del
arnes, un `flush()` olvidado entre partes pasaba en verde (medido).
"""
import gzip
import os
import re
import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException

from itcj2.apps.helpdesk.models.attachment import Attachment
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.comment import Comment
from itcj2.apps.helpdesk.models.status_log import StatusLog
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.apps.helpdesk.models.ticket_edit_log import TicketEditLog
from itcj2.apps.helpdesk.utils.timezone_utils import now_local
from itcj2.core.models.department import Department
from itcj2.core.models.user import User

from ._catalog import ensure_helpdesk_category, ensure_helpdesk_priority

# `created_at` explicito y en el pasado: dentro de la transaccion del test
# `NOW()` devuelve SIEMPRE el mismo instante, asi que con el default del
# servidor "la parte copia el created_at del original" pasaria aunque el
# servicio no lo copiara.
ORIGINAL_CREATED_AT = datetime(2026, 9, 1, 9, 30, 0)

SPLITTABLE_ERROR = "Solo se pueden partir tickets pendientes, asignados o en proceso"


# ─────────────────────────── infraestructura de test ───────────────────────────

@pytest.fixture(autouse=True)
def _session_like_production(db_session):
    """La sesion de la app (`SessionLocal`) corre con `autoflush=False` y expira
    todo al commitear; la de `db_session`, al reves. Sin esto, un `flush()`
    olvidado en el servicio —el que hace visible cada folio nuevo al siguiente
    `generate_ticket_number`— quedaria tapado por el autoflush del arnes, y las
    aserciones posteriores al commit leerian memoria en vez de la BD."""
    db_session.autoflush = False
    db_session.expire_on_commit = True
    yield


def _svc():
    """El modulo bajo prueba, resuelto en tiempo de llamada (ver docstring)."""
    from itcj2.apps.helpdesk.services import ticket_split_service
    return ticket_split_service


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _user(db, last) -> User:
    u = User(first_name="T", last_name=last, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _dept(db) -> Department:
    d = Department(code=f"tsplit_{_uid()}", name="Depto de prueba split", is_active=True)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _category(db, area, field_template=None) -> Category:
    cat = ensure_helpdesk_category(db, code=f"tsplit_{_uid()}", area=area)
    if field_template is not None:
        cat.field_template = field_template
        db.commit()
        db.refresh(cat)
    return cat


def _ticket(db, requester, category, **overrides) -> Ticket:
    defaults = dict(
        ticket_number=f"SPL-{_uid()}",
        requester_id=requester.id,
        requester_department_id=None,
        area=category.area,
        category_id=category.id,
        priority="MEDIA",
        title="Cuentas de Moodle, correo y SII",
        description="Necesito cuentas de Moodle, correo institucional y SII para el personal nuevo.",
        location="Edificio A, cubiculo 3",
        office_document_folio="OF-123/2026",
        status="PENDING",
        created_at=ORIGINAL_CREATED_AT,
        created_by_id=requester.id,
        updated_by_id=requester.id,
    )
    defaults.update(overrides)
    t = Ticket(**defaults)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _attachment(db, ticket, uploader, tmp_path, filename, content, *,
                attachment_type="ticket", mime_type="image/jpeg", comment=None) -> Attachment:
    path = tmp_path / filename
    path.write_bytes(content)
    att = Attachment(
        ticket_id=ticket.id,
        uploaded_by_id=uploader.id,
        attachment_type=attachment_type,
        comment_id=comment.id if comment else None,
        filename=filename,
        original_filename=f"subido_{filename}",
        filepath=str(path),
        mime_type=mime_type,
        file_size=len(content),
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


def _image_and_doc(db, ticket, uploader, tmp_path):
    """Los dos adjuntos iniciales tipicos, nombrados como `_save_ticket_photo`."""
    img = _attachment(
        db, ticket, uploader, tmp_path, f"{ticket.id}.jpg",
        b"\xff\xd8\xff\xe0" + b"imagen-de-prueba" * 16,
    )
    doc = _attachment(
        db, ticket, uploader, tmp_path, f"{ticket.id}_doc.pdf.gz",
        gzip.compress(b"%PDF-1.4 documento de prueba " * 64),
        mime_type="application/pdf",
    )
    return img, doc


def _part(category, *, title="Alta de cuenta de correo institucional",
          description="Crear la cuenta de correo institucional del personal de nuevo ingreso.",
          priority="MEDIA") -> dict:
    return {
        "area": category.area,
        "category_id": category.id,
        "priority": priority,
        "title": title,
        "description": description,
    }


def _same_as(ticket) -> dict:
    """Payload `original` que no cambia nada del ticket."""
    return {
        "area": ticket.area,
        "category_id": ticket.category_id,
        "priority": ticket.priority,
        "title": ticket.title,
        "description": ticket.description,
    }


def _split(db, ticket, actor, original, parts):
    return _svc().split_ticket(db, ticket.id, actor.id, original, parts)


def _parts_of(db, ticket) -> list[Ticket]:
    return (
        db.query(Ticket)
        .filter_by(split_from_ticket_id=ticket.id)
        .order_by(Ticket.id)
        .all()
    )


def _edit_logs(db, ticket_id) -> list[TicketEditLog]:
    return (
        db.query(TicketEditLog)
        .filter_by(ticket_id=ticket_id)
        .order_by(TicketEditLog.id)
        .all()
    )


def _files(directory) -> list[str]:
    return sorted(os.listdir(directory))


def _read(path) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


# ──────────────────────────── 1. PENDING en 3 ─────────────────────────────

class TestSplitPending:
    def test_split_pending_ticket_in_three(self, db_session):
        requester = _user(db_session, "SolicitanteSplit")
        actor = _user(db_session, "ActorSplit")
        dept = _dept(db_session)
        cat_moodle = _category(db_session, "DESARROLLO")
        cat_sii = _category(db_session, "DESARROLLO")
        cat_correo = _category(db_session, "DESARROLLO")
        cat_red = _category(db_session, "SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        ensure_helpdesk_priority(db_session, "ALTA")
        original = _ticket(db_session, requester, cat_moodle, requester_department_id=dept.id)
        original_number = original.ticket_number

        new_title = "Cuenta de SII para el personal nuevo"
        new_description = "Dar de alta en el SII al personal de nuevo ingreso del departamento."
        payloads = [
            _part(cat_correo),
            _part(
                cat_red, priority="ALTA",
                title="Punto de red para la oficina nueva",
                description="Instalar un punto de red en la oficina que ocupara el personal nuevo.",
            ),
        ]

        ticket, new_tickets = _split(
            db_session, original, actor,
            {
                "area": "DESARROLLO", "category_id": cat_sii.id, "priority": "MEDIA",
                "title": new_title, "description": new_description,
            },
            payloads,
        )

        # El servicio COMMITEA: todo sobrevive a un rollback posterior.
        db_session.rollback()

        # ── el original es la parte 1, acotada ──
        assert ticket.id == original.id
        assert ticket.ticket_number == original_number
        assert ticket.status == "PENDING"
        assert ticket.category_id == cat_sii.id
        assert ticket.title == new_title
        assert ticket.description == new_description
        assert ticket.updated_by_id == actor.id

        # ── las partes nuevas ──
        assert len(new_tickets) == 2
        numbers = [p.ticket_number for p in new_tickets]
        assert len(set(numbers) | {original_number}) == 3
        for number in numbers:
            assert re.fullmatch(rf"TK-{now_local().year}-\d{{4,}}", number), number

        assert [p.id for p in _parts_of(db_session, original)] == [p.id for p in new_tickets]
        assert [p.id for p in original.split_children.all()] == [p.id for p in new_tickets]

        for part, payload in zip(new_tickets, payloads):
            assert part.split_from_ticket_id == original.id
            assert part.status == "PENDING"
            assert part.assigned_to_user_id is None
            assert part.assigned_to_team is None
            assert part.requester_id == requester.id
            assert part.requester_department_id == dept.id
            assert part.location == original.location
            assert part.office_document_folio == original.office_document_folio
            assert part.created_at == ORIGINAL_CREATED_AT
            assert part.created_at == original.created_at
            assert part.created_by_id == actor.id
            assert part.updated_by_id == actor.id
            assert part.area == payload["area"]
            assert part.category_id == payload["category_id"]
            assert part.priority == payload["priority"]
            assert part.title == payload["title"]
            assert part.description == payload["description"]

            logs = db_session.query(StatusLog).filter_by(ticket_id=part.id).all()
            assert len(logs) == 1
            assert logs[0].from_status is None
            assert logs[0].to_status == "PENDING"
            assert logs[0].changed_by_id == actor.id
            assert logs[0].notes == f"Ticket creado al partir {original_number}"

        # ── auditoria del original: sus campos + la division con los folios ──
        edit_logs = _edit_logs(db_session, original.id)
        assert [l.field_name for l in edit_logs] == ["category_id", "title", "description", "split"]
        assert edit_logs[-1].new_value == ", ".join(numbers)
        assert all(l.changed_by_id == actor.id for l in edit_logs)

    def test_part_title_and_description_are_stored_stripped(self, db_session):
        requester = _user(db_session, "SolicitanteStrip")
        actor = _user(db_session, "ActorStrip")
        cat = _category(db_session, "DESARROLLO")
        ensure_helpdesk_priority(db_session, "MEDIA")
        original = _ticket(db_session, requester, cat)

        _, (part,) = _split(
            db_session, original, actor, _same_as(original),
            [_part(cat, title="   Titulo con espacios   ",
                   description="\n  Descripcion con espacios alrededor, suficientemente larga.  \n")],
        )

        assert part.title == "Titulo con espacios"
        assert part.description == "Descripcion con espacios alrededor, suficientemente larga."


# ──────────────────────────── 2 y 3. adjuntos ─────────────────────────────

class TestSplitAttachments:
    def test_ticket_attachments_are_copied_to_distinct_files_per_part(self, db_session, tmp_path):
        requester = _user(db_session, "SolicitanteAdj")
        actor = _user(db_session, "ActorAdj")
        cat = _category(db_session, "DESARROLLO")
        ensure_helpdesk_priority(db_session, "MEDIA")
        original = _ticket(db_session, requester, cat)
        img, doc = _image_and_doc(db_session, original, requester, tmp_path)

        comment = Comment(ticket_id=original.id, author_id=actor.id, content="Comentario con adjunto")
        db_session.add(comment)
        db_session.commit()
        _attachment(db_session, original, actor, tmp_path, f"{original.id}_comentario_1.jpg",
                    b"adjunto de comentario", attachment_type="comment", comment=comment)
        _attachment(db_session, original, actor, tmp_path, "resolucion.pdf",
                    b"adjunto de resolucion", attachment_type="resolution", mime_type="application/pdf")
        files_before = _files(tmp_path)
        original_rows_before = [
            (a.id, a.filepath) for a in original.attachments.order_by(Attachment.id).all()
        ]

        _, new_tickets = _split(
            db_session, original, actor, _same_as(original),
            [_part(cat), _part(cat, title="Segunda parte del ticket")],
        )
        assert len(new_tickets) == 2

        copies = []
        for part in new_tickets:
            atts = part.attachments.order_by(Attachment.id).all()
            # Solo los 2 iniciales: ni el de comentario ni el de resolucion.
            assert [a.attachment_type for a in atts] == ["ticket", "ticket"]
            for src, copy in zip((img, doc), atts):
                # Prefijo `{id original}` reemplazado por `{id de la parte}`, mismo directorio.
                assert copy.filename == f"{part.id}{src.filename[len(str(original.id)):]}"
                assert copy.filepath == os.path.join(str(tmp_path), copy.filename)
                assert os.path.isfile(copy.filepath)
                assert _read(copy.filepath) == _read(src.filepath)
                assert copy.original_filename == src.original_filename
                assert copy.mime_type == src.mime_type
                assert copy.file_size == src.file_size
                assert copy.uploaded_by_id == src.uploaded_by_id
                assert copy.comment_id is None
                assert copy.auto_delete_at is None
                copies.append(copy.filepath)

            # La descarga descomprime por `.gz` al final de la ruta: la copia lo conserva.
            assert atts[1].filepath.endswith(".gz")

        # Ninguna ruta compartida: ni con el original ni entre partes.
        assert len(set(copies)) == 4
        assert not set(copies) & {img.filepath, doc.filepath}

        # En disco: lo que habia + exactamente esas 4 copias.
        assert _files(tmp_path) == sorted(files_before + [os.path.basename(p) for p in copies])

        # El original conserva sus 4 adjuntos, con sus rutas y sus archivos.
        assert [
            (a.id, a.filepath) for a in original.attachments.order_by(Attachment.id).all()
        ] == original_rows_before
        assert all(os.path.isfile(path) for _, path in original_rows_before)

    def test_missing_source_file_is_skipped(self, db_session, tmp_path):
        requester = _user(db_session, "SolicitanteSinArchivo")
        actor = _user(db_session, "ActorSinArchivo")
        cat = _category(db_session, "DESARROLLO")
        ensure_helpdesk_priority(db_session, "MEDIA")
        original = _ticket(db_session, requester, cat)
        img, doc = _image_and_doc(db_session, original, requester, tmp_path)
        os.remove(img.filepath)

        _, (part,) = _split(db_session, original, actor, _same_as(original), [_part(cat)])

        atts = part.attachments.all()
        assert [a.filename for a in atts] == [f"{part.id}_doc.pdf.gz"]
        assert _read(atts[0].filepath) == _read(doc.filepath)
        assert _parts_of(db_session, original)[0].id == part.id


# ──────────────────────── 4. ASSIGNED / IN_PROGRESS ────────────────────────

class TestSplitAssignedOrInProgress:
    @pytest.mark.parametrize("status", ["ASSIGNED", "IN_PROGRESS"])
    def test_keeps_assignment_and_allows_category_change_within_area(self, db_session, status):
        requester = _user(db_session, "SolicitanteAsignado")
        actor = _user(db_session, "ActorAsignado")
        tech = _user(db_session, "TecnicoAsignado")
        cat_a = _category(db_session, "SOPORTE")
        cat_b = _category(db_session, "SOPORTE")
        cat_dev = _category(db_session, "DESARROLLO")
        ensure_helpdesk_priority(db_session, "MEDIA")
        original = _ticket(
            db_session, requester, cat_a,
            status=status, assigned_to_user_id=tech.id, assigned_to_team="soporte",
        )

        ticket, (part,) = _split(
            db_session, original, actor,
            {**_same_as(original), "category_id": cat_b.id},
            [_part(cat_dev)],
        )

        assert ticket.status == status
        assert ticket.assigned_to_user_id == tech.id
        assert ticket.assigned_to_team == "soporte"
        assert ticket.area == "SOPORTE"
        assert ticket.category_id == cat_b.id
        assert [l.field_name for l in _edit_logs(db_session, original.id)] == ["category_id", "split"]

        # La parte nace PENDING y sin asignar aunque el original ya lo este.
        assert part.status == "PENDING"
        assert part.assigned_to_user_id is None
        assert part.assigned_to_team is None
        assert part.area == "DESARROLLO"

    def test_area_change_on_assigned_ticket_is_rejected(self, db_session):
        requester = _user(db_session, "SolicitanteArea")
        actor = _user(db_session, "ActorArea")
        tech = _user(db_session, "TecnicoArea")
        cat_soporte = _category(db_session, "SOPORTE")
        cat_dev = _category(db_session, "DESARROLLO")
        ensure_helpdesk_priority(db_session, "MEDIA")
        original = _ticket(db_session, requester, cat_soporte, status="ASSIGNED", assigned_to_user_id=tech.id)

        with pytest.raises(HTTPException) as exc_info:
            _split(
                db_session, original, actor,
                {**_same_as(original), "area": "DESARROLLO", "category_id": cat_dev.id},
                [_part(cat_dev)],
            )

        assert exc_info.value.status_code == 400
        assert "área" in exc_info.value.detail
        assert _parts_of(db_session, original) == []
        assert original.area == "SOPORTE"
        assert original.category_id == cat_soporte.id
        assert original.status == "ASSIGNED"
        assert _edit_logs(db_session, original.id) == []


# ─────────────────────────── 5 y 7. guardas previas ───────────────────────────

class TestSplitGuards:
    def test_missing_ticket_is_404(self, db_session):
        actor = _user(db_session, "ActorNoExiste")
        cat = _category(db_session, "DESARROLLO")

        with pytest.raises(HTTPException) as exc_info:
            _svc().split_ticket(db_session, 999_999_999, actor.id, {}, [_part(cat)])

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Ticket no encontrado"

    @pytest.mark.parametrize("status", ["RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED", "CANCELED"])
    def test_non_splittable_status_is_rejected(self, db_session, status):
        requester = _user(db_session, "SolicitanteTerminal")
        actor = _user(db_session, "ActorTerminal")
        cat = _category(db_session, "DESARROLLO")
        ensure_helpdesk_priority(db_session, "MEDIA")
        original = _ticket(db_session, requester, cat, status=status)

        with pytest.raises(HTTPException) as exc_info:
            _split(db_session, original, actor, _same_as(original), [_part(cat)])

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == SPLITTABLE_ERROR
        assert _parts_of(db_session, original) == []

    @pytest.mark.parametrize("n_new_parts", [0, 5])
    def test_new_parts_count_out_of_range_is_rejected(self, db_session, n_new_parts):
        requester = _user(db_session, "SolicitanteCuenta")
        actor = _user(db_session, "ActorCuenta")
        cat = _category(db_session, "DESARROLLO")
        ensure_helpdesk_priority(db_session, "MEDIA")
        original = _ticket(db_session, requester, cat)

        with pytest.raises(HTTPException) as exc_info:
            _split(db_session, original, actor, _same_as(original), [_part(cat)] * n_new_parts)

        assert exc_info.value.status_code == 400
        assert "entre 1 y 4" in exc_info.value.detail
        assert _parts_of(db_session, original) == []
        assert _edit_logs(db_session, original.id) == []

    def test_four_new_parts_is_the_maximum(self, db_session):
        requester = _user(db_session, "SolicitanteTope")
        actor = _user(db_session, "ActorTope")
        cat = _category(db_session, "DESARROLLO")
        ensure_helpdesk_priority(db_session, "MEDIA")
        original = _ticket(db_session, requester, cat)
        assert _svc().MAX_TOTAL_PARTS == 5

        _, new_tickets = _split(
            db_session, original, actor, _same_as(original),
            [_part(cat, title=f"Parte numero {k}") for k in range(2, 6)],
        )

        assert [p.title for p in new_tickets] == [f"Parte numero {k}" for k in range(2, 6)]
        assert len(_parts_of(db_session, original)) == 4


# ───────────────────────────── 6 y 9. atomicidad ──────────────────────────────

class TestSplitAtomicity:
    @pytest.mark.parametrize("defect", ["descripcion_corta", "categoria_de_otra_area"])
    def test_invalid_part_three_persists_nothing(self, db_session, tmp_path, defect):
        requester = _user(db_session, "SolicitanteParte3")
        actor = _user(db_session, "ActorParte3")
        cat_dev = _category(db_session, "DESARROLLO")
        cat_dev_2 = _category(db_session, "DESARROLLO")
        cat_soporte = _category(db_session, "SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        original = _ticket(db_session, requester, cat_dev)
        _image_and_doc(db_session, original, requester, tmp_path)
        original_title = original.title
        files_before = _files(tmp_path)

        parts = [_part(cat_dev_2), _part(cat_dev_2, title="Tercera parte del ticket")]
        if defect == "descripcion_corta":
            parts[1]["description"] = "corta"
        else:
            parts[1]["category_id"] = cat_soporte.id  # el area de la parte sigue DESARROLLO

        with pytest.raises(HTTPException) as exc_info:
            _split(
                db_session, original, actor,
                {**_same_as(original), "title": "Titulo nuevo que no debe quedar"},
                parts,
            )

        assert exc_info.value.status_code == 400
        assert "Parte 3" in exc_info.value.detail
        assert _parts_of(db_session, original) == []
        assert db_session.query(Ticket).filter_by(requester_id=requester.id).count() == 1
        assert original.title == original_title
        assert _edit_logs(db_session, original.id) == []
        assert _files(tmp_path) == files_before

    @pytest.mark.parametrize("change, expected", [
        # `apply_ticket_field_edits` ya MUTO el titulo cuando rechaza la
        # descripcion: el rollback es lo unico que lo deshace.
        ({"title": "Titulo nuevo valido", "description": "corta"},
         "Ticket original: La descripcion debe tener al menos 20 caracteres"),
        ({"title": "x" * 201},
         "Ticket original: El título no debe exceder 200 caracteres"),
        ({"area": "SOPORTE"},
         "Ticket original: Al cambiar de area debe seleccionar una nueva categoria"),
    ], ids=["descripcion_corta", "titulo_largo", "area_sin_categoria_nueva"])
    def test_invalid_original_edit_is_prefixed_and_persists_nothing(self, db_session, tmp_path, change, expected):
        requester = _user(db_session, "SolicitanteOriginal")
        actor = _user(db_session, "ActorOriginal")
        cat = _category(db_session, "DESARROLLO")
        ensure_helpdesk_priority(db_session, "MEDIA")
        original = _ticket(db_session, requester, cat)
        _image_and_doc(db_session, original, requester, tmp_path)
        original_title = original.title
        files_before = _files(tmp_path)

        with pytest.raises(HTTPException) as exc_info:
            _split(db_session, original, actor, {**_same_as(original), **change}, [_part(cat)])

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == expected
        assert _parts_of(db_session, original) == []
        assert original.title == original_title
        assert original.area == "DESARROLLO"
        assert _edit_logs(db_session, original.id) == []
        assert _files(tmp_path) == files_before

    def test_late_failure_removes_copied_files(self, db_session, tmp_path, monkeypatch):
        requester = _user(db_session, "SolicitanteTardio")
        actor = _user(db_session, "ActorTardio")
        cat = _category(db_session, "DESARROLLO")
        ensure_helpdesk_priority(db_session, "MEDIA")
        original = _ticket(db_session, requester, cat)
        _image_and_doc(db_session, original, requester, tmp_path)
        original_title = original.title
        files_before = _files(tmp_path)

        files_at_commit = []

        def _broken_commit():
            files_at_commit.extend(_files(tmp_path))
            raise RuntimeError("commit roto a proposito")

        # Todo el setup ya se commiteo arriba: desde aqui el unico commit es el del servicio.
        monkeypatch.setattr(db_session, "commit", _broken_commit)

        with pytest.raises(HTTPException) as exc_info:
            _split(
                db_session, original, actor,
                {**_same_as(original), "title": "Titulo nuevo que no debe quedar"},
                [_part(cat), _part(cat, title="Tercera parte del ticket")],
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Error al partir ticket"
        # Las copias SI llegaron a existir (2 adjuntos x 2 partes) ...
        assert len(files_at_commit) == len(files_before) + 4
        # ... y el rollback las borro: solo quedan los archivos del original.
        assert _files(tmp_path) == files_before
        assert _parts_of(db_session, original) == []
        assert db_session.query(Ticket).filter_by(requester_id=requester.id).count() == 1
        assert original.title == original_title
        assert _edit_logs(db_session, original.id) == []


# ──────────────────────────── 8. custom_fields ─────────────────────────────

class TestSplitCustomFields:
    def test_parts_inherit_custom_fields_only_with_the_previous_category(self, db_session):
        requester = _user(db_session, "SolicitanteCampos")
        actor = _user(db_session, "ActorCampos")
        template = {"enabled": True, "fields": [
            {"key": "equipo", "type": "text", "label": "Equipo"},
            {"key": "urgencia", "type": "select", "label": "Urgencia"},
            {"key": "evidencia", "type": "file", "label": "Evidencia"},
        ]}
        cat_prev = _category(db_session, "SOPORTE", field_template=template)
        cat_other = _category(db_session, "SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        original = _ticket(
            db_session, requester, cat_prev,
            custom_fields={"equipo": "PC-01", "urgencia": "alta", "evidencia": "custom_fields/1_evidencia.jpg"},
        )

        # El original se muda a `cat_other` (`apply_ticket_field_edits` le vacia
        # `custom_fields`): la parte que se queda con la categoria PREVIA hereda
        # del estado anterior a esa edicion, no del `{}` que queda despues.
        ticket, (same_category_part, other_category_part) = _split(
            db_session, original, actor,
            {**_same_as(original), "category_id": cat_other.id},
            [_part(cat_prev), _part(cat_other, title="Parte con otra categoria")],
        )

        assert same_category_part.custom_fields == {"equipo": "PC-01", "urgencia": "alta"}
        assert other_category_part.custom_fields == {}
        assert ticket.custom_fields == {}


# ─────────────────── extras: nombre de la copia en disco ───────────────────

class TestCopyAttachmentNaming:
    def test_existing_destination_gets_a_unique_suffix_and_is_not_overwritten(self, db_session, tmp_path):
        requester = _user(db_session, "SolicitanteColision")
        cat = _category(db_session, "DESARROLLO")
        original = _ticket(db_session, requester, cat)
        part = _ticket(db_session, requester, cat, split_from_ticket_id=original.id)
        img, doc = _image_and_doc(db_session, original, requester, tmp_path)
        # Archivos AJENOS que ya ocupan el nombre que le tocaria a la copia.
        (tmp_path / f"{part.id}.jpg").write_bytes(b"de otro ticket")
        (tmp_path / f"{part.id}_doc.pdf.gz").write_bytes(b"de otro ticket")

        copied = []
        img_copy = _svc()._copy_ticket_attachment(db_session, img, part.id, copied)
        doc_copy = _svc()._copy_ticket_attachment(db_session, doc, part.id, copied)
        db_session.flush()

        assert re.fullmatch(rf"{part.id}_[0-9a-f]{{8}}\.jpg", img_copy.filename), img_copy.filename
        # El sufijo va ANTES de la extension compuesta: la ruta sigue terminando en `.gz`.
        assert re.fullmatch(rf"{part.id}_doc_[0-9a-f]{{8}}\.pdf\.gz", doc_copy.filename), doc_copy.filename
        assert (tmp_path / f"{part.id}.jpg").read_bytes() == b"de otro ticket"
        assert (tmp_path / f"{part.id}_doc.pdf.gz").read_bytes() == b"de otro ticket"
        assert _read(img_copy.filepath) == _read(img.filepath)
        assert _read(doc_copy.filepath) == _read(doc.filepath)
        assert copied == [img_copy.filepath, doc_copy.filepath]
        assert img_copy.ticket_id == part.id and doc_copy.ticket_id == part.id

    def test_filename_without_the_original_id_prefix_gets_the_part_id_prefix(self, db_session, tmp_path):
        requester = _user(db_session, "SolicitanteSinPrefijo")
        cat = _category(db_session, "DESARROLLO")
        original = _ticket(db_session, requester, cat)
        part = _ticket(db_session, requester, cat, split_from_ticket_id=original.id)
        scan = _attachment(db_session, original, requester, tmp_path, "escaneo.png", b"png de prueba",
                           mime_type="image/png")

        copied = []
        copy = _svc()._copy_ticket_attachment(db_session, scan, part.id, copied)

        assert copy.filename == f"{part.id}_escaneo.png"
        assert copy.filepath == os.path.join(str(tmp_path), f"{part.id}_escaneo.png")
        assert _read(copy.filepath) == b"png de prueba"
        assert copied == [copy.filepath]
