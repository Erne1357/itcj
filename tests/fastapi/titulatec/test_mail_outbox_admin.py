"""Pestaña «Correos» (2026-10-06): bandeja de salida del outbox, SOLO LECTURA.

`pages/mail_admin.py`, permiso `titulatec.email_outbox.page.list` (solo el rol
`admin`, `outbox_2026_10/24` + `titulatec init-outbox-admin`).

Lo que se fija aquí:

1. Autorización: con el permiso se ve el ítem del menú y la página; sin él, ni
   el ítem ni la ruta (403).
2. Pestañas: cada una filtra sus estados (Descartados = `no_recipient` +
   `obsolete`) y su contador cuenta el universo filtrado por tipo y búsqueda.
3. Búsqueda en servidor (asunto, destinatario, alumno, solicitud) y filtro
   por tipo (un tipo fuera del catálogo se ignora).
4. Paginación y orden (la cola, por `not_before`).
5. Solo lectura: ni un formulario ni un `hx-post`, y el `payload` jamás sale
   en el HTML.
6. El comando `init-outbox-admin` y su lugar en `SEED_FILES`.

La BD de dev es compartida (y con outbox real): toda prueba acota su universo
con un `token` único en el asunto y lo busca (`q`).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from click.testing import CliRunner

URL = "/titulatec/admin/correos"
PERM = "titulatec.email_outbox.page.list"
DOCS_PAGE = "/titulatec/admin/documents"


def _token() -> str:
    return "zqx" + uuid.uuid4().hex[:10]


def _fila(db, *, user=None, req=None, process=None, status="pending",
          kind="docs_review", subject=None, sent_to=None, attempts=0,
          last_error=None, created_at=None, not_before=None, sent_at=None,
          payload=None, group_key=None):
    from itcj2.apps.titulatec.models import EmailOutbox

    creada = created_at or datetime(2026, 10, 1, 9, 0)
    row = EmailOutbox(
        kind=kind,
        user_id=getattr(user, "id", None),
        enrollment_request_id=getattr(req, "id", None),
        process_id=getattr(process, "id", None),
        payload=payload or {"reason": "hecho congelado"},
        status=status, attempts=attempts, subject=subject, sent_to=sent_to,
        last_error=last_error, created_at=creada, not_before=not_before or creada,
        sent_at=sent_at, group_key=group_key,
    )
    db.add(row)
    db.flush()
    return row


def _solicitud(db, cohort, *, control, first_name="SOLICITANTE", last_name="DE CORREO"):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name=first_name, last_name=last_name, middle_name=None,
        program_id=None, program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email=f"{control}@example.invalid",
        has_efirma=False, kind="unknown", status="rejected", verify_send_count=0,
    )
    db.add(row)
    db.flush()
    return row


def _ids(html: str) -> set[int]:
    return {int(m) for m in re.findall(r'id="tt-mail-(\d+)"', html)}


def _conteo(html: str, label: str) -> int:
    m = re.search(rf">{re.escape(label)} \((\d+)\)</button>", html)
    assert m, f"no está la pestaña {label!r}"
    return int(m.group(1))


def _sidebar_urls(html: str) -> list[str]:
    import lxml.html

    doc = lxml.html.fromstring(html)
    return [a.get("hx-get") for a in doc.xpath('//aside[@id="ttSide"]//a[@hx-get]')]


@pytest.fixture()
def admin(make_head):
    """Actor con SOLO el permiso de la pestaña (como el rol `admin` en prod lo
    tiene entre todos los demás)."""
    return make_head(perm_codes=(PERM,))


# ---------------------------------------------------------------------------
# 1. Autorización
# ---------------------------------------------------------------------------
def test_con_el_permiso_se_ve_el_item_y_la_pagina(client_as, admin):
    resp = client_as(admin).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert URL in _sidebar_urls(resp.text)
    assert 'id="tt-mail-body"' in resp.text


def test_sin_el_permiso_ni_item_ni_pagina(client_as, make_head):
    """La jefa con su set de siempre (sin el permiso) no ve el ítem, y la ruta
    y su parcial le responden 403."""
    head = make_head()
    c = client_as(head)

    docs = c.get(DOCS_PAGE)
    assert docs.status_code == 200, docs.text[:300]
    assert URL not in _sidebar_urls(docs.text)
    assert c.get(URL).status_code == 403
    assert c.get(f"{URL}/body").status_code == 403


def test_el_item_va_en_la_tabla_de_nav_con_su_permiso():
    from itcj2.apps.titulatec.pages.nav import _ADMIN_NAV

    fila = [(label, url, need) for label, _i, url, need in _ADMIN_NAV if url == URL]
    assert fila == [("Correos", URL, {PERM})]


# ---------------------------------------------------------------------------
# 2. Pestañas y contadores
# ---------------------------------------------------------------------------
def test_cada_pestana_filtra_sus_estados_y_cuenta_bien(client_as, db_session, admin,
                                                        make_user):
    t = _token()
    alumno = make_user()
    filas = {s: _fila(db_session, user=alumno, status=s, subject=f"{t} {s}")
             for s in ("pending", "sent", "failed", "no_recipient", "obsolete")}
    c = client_as(admin)

    esperado = {
        "pending": {"pending"}, "sent": {"sent"}, "failed": {"failed"},
        "discarded": {"no_recipient", "obsolete"},
        "all": {"pending", "sent", "failed", "no_recipient", "obsolete"},
    }
    for tab, estados in esperado.items():
        html = c.get(f"{URL}/body", params={"status": tab, "q": t}).text
        assert _ids(html) == {filas[s].id for s in estados}, tab

    html = c.get(f"{URL}/body", params={"q": t}).text
    assert _conteo(html, "Pendientes") == 1
    assert _conteo(html, "Entregados") == 1
    assert _conteo(html, "Fallidos") == 1
    assert _conteo(html, "Descartados") == 2
    assert _conteo(html, "Todos") == 5


def test_pendientes_es_la_pestana_por_omision_y_una_desconocida_cae_ahi(
    client_as, db_session, admin, make_user,
):
    t = _token()
    alumno = make_user()
    pend = _fila(db_session, user=alumno, status="pending", subject=t)
    _fila(db_session, user=alumno, status="sent", subject=t)
    c = client_as(admin)

    for params in ({"q": t}, {"q": t, "status": "inventada"}):
        html = c.get(f"{URL}/body", params=params).text
        assert _ids(html) == {pend.id}
        assert 'id="tt-mail-tab-pending"' in html
        assert re.search(r'id="tt-mail-tab-pending"[^>]*aria-current="true"', html)


def test_la_cola_sale_por_not_before(client_as, db_session, admin, make_user):
    """Pendientes = la cola: primero lo que el despachador toma antes."""
    t = _token()
    alumno = make_user()
    base = datetime(2026, 10, 1, 9, 0)
    tarde = _fila(db_session, user=alumno, subject=t, created_at=base,
                  not_before=base + timedelta(minutes=30))
    pronto = _fila(db_session, user=alumno, subject=t, created_at=base + timedelta(minutes=1),
                   not_before=base + timedelta(minutes=5))

    html = client_as(admin).get(f"{URL}/body", params={"q": t}).text

    assert html.index(f'id="tt-mail-{pronto.id}"') < html.index(f'id="tt-mail-{tarde.id}"')
    assert "Sale 01/10/2026 09:30" in html, "la retenida dice cuándo sale"


# ---------------------------------------------------------------------------
# 3. Búsqueda y tipo
# ---------------------------------------------------------------------------
def test_busca_por_control_y_nombre_del_alumno(client_as, db_session, admin, make_user):
    control = "99" + uuid.uuid4().hex[:6].translate(str.maketrans("abcdef", "123456"))
    alumno = make_user(first_name="BRISEIDA", last_name="CORREOSA", control_number=control)
    otro = make_user()
    suya = _fila(db_session, user=alumno, status="sent", sent_to="x@example.invalid")
    _fila(db_session, user=otro, status="sent")
    c = client_as(admin)

    for q in (control, "CORREOSA BRISEIDA"):
        html = c.get(f"{URL}/body", params={"status": "all", "q": q}).text
        assert _ids(html) == {suya.id}, q
    assert control in _filas_html(c, control)


def _filas_html(c, q):
    return c.get(f"{URL}/body", params={"status": "all", "q": q}).text


def test_busca_por_la_solicitud_cuando_no_hay_alumno(client_as, db_session, admin,
                                                     make_cohort):
    control = "99" + uuid.uuid4().hex[:6].translate(str.maketrans("abcdef", "123456"))
    req = _solicitud(db_session, make_cohort(), control=control)
    fila = _fila(db_session, req=req, kind="enrollment_rejected", status="no_recipient")

    html = _filas_html(client_as(admin), control)

    assert _ids(html) == {fila.id}
    assert "Solicitud" in html
    # `no_recipient` de un correo de inscripción no nombra un buzón.
    assert "Sin correo" in html and "Sin correo personal" not in html


def test_busca_por_destinatario_y_asunto(client_as, db_session, admin, make_user):
    t = _token()
    alumno = make_user()
    por_dest = _fila(db_session, user=alumno, status="sent", sent_to=f"{t}@example.invalid")
    por_asunto = _fila(db_session, user=alumno, status="sent", subject=f"Asunto {t}")

    html = _filas_html(client_as(admin), t)

    assert _ids(html) == {por_dest.id, por_asunto.id}


def test_filtra_por_tipo_y_un_tipo_inventado_se_ignora(client_as, db_session, admin,
                                                       make_user):
    t = _token()
    alumno = make_user()
    rev = _fila(db_session, user=alumno, kind="docs_review", subject=t)
    rec = _fila(db_session, user=alumno, kind="appt_reminder", subject=t)
    c = client_as(admin)

    solo = c.get(f"{URL}/body", params={"q": t, "kind": "appt_reminder"}).text
    assert _ids(solo) == {rec.id}
    assert _conteo(solo, "Pendientes") == 1, "el contador respeta el tipo"
    assert 'value="appt_reminder" selected' in solo

    todos = c.get(f"{URL}/body", params={"q": t, "kind": "no_existe"}).text
    assert _ids(todos) == {rev.id, rec.id}


def test_sin_resultados_lo_dice(client_as, admin):
    html = client_as(admin).get(f"{URL}/body", params={"q": _token()}).text

    assert 'id="tt-mail-no-results"' in html


# ---------------------------------------------------------------------------
# 4. Paginación
# ---------------------------------------------------------------------------
def test_pagina_en_servidor(db_session, admin, make_user):
    from itcj2.apps.titulatec.pages.mail_admin import _body_ctx

    t = _token()
    alumno = make_user()
    base = datetime(2026, 10, 1, 9, 0)
    filas = [_fila(db_session, user=alumno, status="sent", subject=t,
                   created_at=base + timedelta(minutes=i)) for i in range(3)]

    p1 = _body_ctx(db_session, user_id=admin.id, status="sent", kind="", q=t,
                   page=1, per_page=2)
    p2 = _body_ctx(db_session, user_id=admin.id, status="sent", kind="", q=t,
                   page=2, per_page=2)
    fuera = _body_ctx(db_session, user_id=admin.id, status="sent", kind="", q=t,
                      page=9, per_page=2)

    assert p1["page"].total == 3 and p1["page"].pages == 2
    assert [r["id"] for r in p1["rows"]] == [filas[2].id, filas[1].id]
    assert [r["id"] for r in p2["rows"]] == [filas[0].id]
    assert fuera["page"].page == 2, "una página fuera de rango cae en la última"


# ---------------------------------------------------------------------------
# 5. Solo lectura y sin payload
# ---------------------------------------------------------------------------
def test_solo_lectura_y_el_payload_no_sale(client_as, db_session, admin, make_user):
    t = _token()
    alumno = make_user()
    secreto = "HECHO-CONGELADO-" + uuid.uuid4().hex
    _fila(db_session, user=alumno, status="failed", subject=t, attempts=6,
          last_error="Graph respondió 503", payload={"reason": secreto})

    pagina = client_as(admin).get(URL, params={"status": "failed", "q": t}).text
    parcial = client_as(admin).get(f"{URL}/body", params={"status": "failed", "q": t}).text

    for html in (pagina, parcial):
        assert secreto not in html
        assert "Graph respondió 503" in html
    assert "<form" not in parcial
    assert "hx-post" not in parcial and "hx-delete" not in parcial


def test_liga_al_expediente_solo_si_el_actor_puede_abrirlo(
    client_as, db_session, make_head, make_student, make_process, make_program,
    make_user, make_role, grant_user_role,
):
    t = _token()
    alumno = make_student()
    proc = make_process(alumno, program=make_program("Ingenieria De Correos Ficticia"),
                        phases=False)
    _fila(db_session, user=alumno, process=proc, status="sent", subject=t)
    liga = f'href="/titulatec/admin/processes/{proc.id}?from=/titulatec/admin/correos"'

    # Roles DISTINTOS: `make_head` reusa un solo rol por nombre (idempotente) y
    # los permisos del segundo actor se sumarían al primero.
    sin_vista = make_user(first_name="SOLO", last_name="CORREOS")
    grant_user_role(sin_vista, make_role("tt_test_solo_correos", (PERM,)))
    con_vista = make_head(perm_codes=(PERM, "titulatec.process.page.detail",
                                      "titulatec.process.api.read.all"))

    html_sin = _filas_html(client_as(sin_vista), t)
    html_con = _filas_html(client_as(con_vista), t)

    assert proc.folio in html_sin and liga not in html_sin
    assert liga in html_con


# ---------------------------------------------------------------------------
# 6. Despliegue: permiso por DML + comando
# ---------------------------------------------------------------------------
def test_seed_files_trae_el_delta_antes_del_15():
    from itcj2.cli.titulatec import SEED_FILES

    nombre = "outbox_2026_10/24_insert_email_outbox_perm.sql"
    assert nombre in SEED_FILES
    assert SEED_FILES.index(nombre) < SEED_FILES.index("15_grant_admin_all_perms.sql")


def _requires_dml():
    from itcj2.cli.titulatec import DML_TITULATEC, _DML_OUTBOX_2026_10_DIR

    return pytest.mark.skipif(
        not (DML_TITULATEC / _DML_OUTBOX_2026_10_DIR).is_dir(),
        reason="database/DML/titulatec/outbox_2026_10/ no está en el checkout (gitignored).",
    )


@_requires_dml()
def test_el_directorio_lista_exactamente_su_archivo():
    from itcj2.cli.titulatec import (
        DML_TITULATEC, _DML_OUTBOX_2026_10_DIR, _DML_OUTBOX_2026_10_FILES,
    )

    en_disco = sorted(p.name for p in (DML_TITULATEC / _DML_OUTBOX_2026_10_DIR).glob("*.sql"))
    assert en_disco == sorted(_DML_OUTBOX_2026_10_FILES)


@_requires_dml()
def test_el_sql_concede_solo_a_admin():
    from itcj2.cli.titulatec import (
        DML_TITULATEC, _DML_OUTBOX_2026_10_DIR, _DML_OUTBOX_2026_10_FILES,
    )

    texto = (DML_TITULATEC / _DML_OUTBOX_2026_10_DIR / _DML_OUTBOX_2026_10_FILES[0]).read_text(
        encoding="utf-8")
    sql = "\n".join(ln for ln in texto.splitlines() if not ln.lstrip().startswith("--"))
    assert f"'{PERM}'" in sql
    assert re.findall(r"r\.name\s*=\s*'([^']+)'", sql) == ["admin"]
    assert "perm_id" in sql and "permission_id" not in sql


def test_el_comando_corre_su_archivo_y_verifica():
    from itcj2.cli import titulatec as cli

    with patch.object(cli, "_run_sql_files") as correr, \
            patch.object(cli, "_verify_outbox_admin", return_value=[]) as verificar:
        res = CliRunner().invoke(cli.init_outbox_admin_command, [])

    assert res.exit_code == 0, res.output
    correr.assert_called_once_with(["outbox_2026_10/24_insert_email_outbox_perm.sql"])
    verificar.assert_called_once_with()


def test_el_comando_aborta_si_no_aterrizo():
    from itcj2.cli import titulatec as cli

    with patch.object(cli, "_run_sql_files"), \
            patch.object(cli, "_verify_outbox_admin",
                         return_value=["el rol admin no tiene " + PERM]):
        res = CliRunner().invoke(cli.init_outbox_admin_command, [])

    assert res.exit_code != 0


def test_verify_lee_la_base(patched_session_local, make_role):
    """Con el permiso en un rol `admin` de prueba, nada que reportar; sin la
    concesión, lo dice. Sesión interceptada por `patched_session_local`."""
    from itcj2.cli.titulatec import _verify_outbox_admin

    # La base de dev ya trae el 24 cargado (o no): se fuerza el estado bueno.
    make_role("admin", (PERM,))
    assert _verify_outbox_admin() == []

    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role import Role
    from itcj2.core.models.role_permission import RolePermission

    db = patched_session_local
    rol = db.query(Role).filter_by(name="admin").one()
    perm = db.query(Permission).filter_by(code=PERM).one()
    db.query(RolePermission).filter_by(role_id=rol.id, perm_id=perm.id).delete()
    db.flush()
    assert _verify_outbox_admin() == [f"el rol admin no tiene {PERM}"]
