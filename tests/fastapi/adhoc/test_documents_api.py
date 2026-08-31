"""Tests de la API v2 de documentos y flujos de aprobación (Adhoc / Calidad).

Cubren el contrato del plan §3: sobre ``{"success": True, ...}``, errores
``{"error": "<texto>", "status": N}`` (**nunca** ``{"detail": ...}``), 401 sin
cookie y 403 sin permiso.

Dos particularidades del harness que conviene tener presentes:

1. Los sub-routers ya están cableados en ``itcj2/apps/adhoc/router.py``, así
   que el fixture NO los monta: usa las rutas reales de ``create_app()``. (El
   guard anterior miraba ``app.routes``, que en esta versión de FastAPI ya no
   expone las rutas anidadas, así que siempre duplicaba el montaje.)
2. Un JWT con ``role="admin"`` **bypasea ``require_perms``** (``dependencies.py``
   corta antes de tocar la BD). Sirve para el camino feliz; para probar que los
   permisos están bien puestos hay que usar ``role="staff"`` y parchear
   ``cached_has_assignment`` / ``cached_perms`` **en su módulo fuente**
   (``itcj2.core.services.authz_cache``), porque el endpoint los importa dentro
   de la función.
"""
import uuid
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from itcj2.apps.adhoc.models import (
    AdhocApprovalFlow,
    AdhocApprovalFlowStep,
    AdhocDocument,
    AdhocDocumentAcknowledgement,
    AdhocDocumentVisibility,
    AdhocTask,
)
from itcj2.apps.adhoc.services import upload_service
from itcj2.core.models.user import User
from itcj2.database import get_db
from tests.conftest import TEST_SECRET, make_jwt

API = "/api/adhoc/v2"
DOCS = f"{API}/documents"
FLOWS = f"{API}/approval-flows"


# --------------------------------------------------------------------------
# Cliente
# --------------------------------------------------------------------------

@pytest.fixture()
def client(db_session):
    """App real (routers ya cableados), atada a la sesión del test."""
    with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET):
        from itcj2.main import create_app

        app = create_app()

        def _override():
            yield db_session

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def admin_cookies():
    return {"itcj_token": make_jwt(user_id=1, role="admin")}


@pytest.fixture()
def uploads_root(tmp_path, monkeypatch):
    class _S:
        ADHOC_UPLOAD_PATH = str(tmp_path)
        ADHOC_MAX_FILE_SIZE = 1024 * 1024
        ADHOC_ALLOWED_EXTENSIONS = "pdf,png,txt"

    monkeypatch.setattr(upload_service, "_settings", lambda: _S())
    return tmp_path


# --------------------------------------------------------------------------
# Factories
# --------------------------------------------------------------------------

def make_user(db, label="val"):
    tag = uuid.uuid4().hex[:10]
    u = User(
        first_name=label.upper(), last_name="ADHOC",
        username=f"e2e_adhoc_{label}_{tag}",
        email=f"e2e_adhoc_{label}_{tag}@test.local",
    )
    db.add(u)
    db.flush()
    return u


def make_flow(db, steps=(("Revisión", 3), ("Autorización", 5))):
    flow = AdhocApprovalFlow(name=f"e2e_flow_{uuid.uuid4().hex[:8]}")
    db.add(flow)
    db.flush()
    for i, (name, days) in enumerate(steps, start=1):
        db.add(AdhocApprovalFlowStep(
            flow_id=flow.id, name=name, days_limit=days, step_order=i,
        ))
    db.flush()
    db.refresh(flow)
    return flow


def make_document(db, **kw):
    kw.setdefault("title", f"e2e_doc_{uuid.uuid4().hex[:8]}")
    kw.setdefault("status", "Borrador")
    doc = AdhocDocument(**kw)
    db.add(doc)
    db.flush()
    return doc


# ==========================================================================
# Autenticación y autorización
# ==========================================================================

@pytest.mark.parametrize("method,path", [
    ("get", DOCS),
    ("post", DOCS),
    ("get", f"{DOCS}/1"),
    ("get", f"{DOCS}/1/versions"),
    ("get", f"{DOCS}/1/acknowledgements"),
    ("patch", f"{DOCS}/1"),
    ("delete", f"{DOCS}/1"),
    ("get", f"{DOCS}/1/download"),
    ("post", f"{DOCS}/1/start-flow"),
    ("get", FLOWS),
    ("post", FLOWS),
    ("patch", f"{FLOWS}/1"),
    ("delete", f"{FLOWS}/1"),
    ("get", f"{FLOWS}/1/steps"),
    ("put", f"{FLOWS}/1/steps"),
    ("get", f"{FLOWS}/steps/1"),
    ("put", f"{FLOWS}/steps/1/validators"),
    ("put", f"{FLOWS}/steps/1/overdue-notifications"),
])
def test_sin_cookie_es_401(client, method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code == 401
    assert resp.json()["error"]


def test_sin_permiso_es_403(client):
    """``role="staff"`` no bypasea: se comprueban permisos de verdad."""
    cookies = {"itcj_token": make_jwt(user_id=1, role="staff")}
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms", return_value=set()):
        resp = client.get(DOCS, cookies=cookies)
    assert resp.status_code == 403
    assert "error" in resp.json()


def test_con_el_permiso_exacto_pasa(client):
    cookies = {"itcj_token": make_jwt(user_id=1, role="staff")}
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.documents.api.read"}):
        resp = client.get(DOCS, cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ==========================================================================
# Documentos
# ==========================================================================

def test_listado_devuelve_sobre_paginado(client, admin_cookies, db_session):
    make_document(db_session, title="e2e_listado")
    resp = client.get(DOCS, params={"page": 1, "per_page": 5}, cookies=admin_cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)
    assert {"total", "page", "per_page", "total_pages"} <= set(body)


def test_listado_con_status_invalido_es_400_no_500(client, admin_cookies):
    resp = client.get(DOCS, params={"status": "Inventado"}, cookies=admin_cookies)
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_alta_masiva_multipart(client, admin_cookies, uploads_root, db_session):
    resp = client.post(
        DOCS,
        data={
            "titles": ["e2e Manual", "e2e Procedimiento"],
            "codes": ["E2E-1", "E2E-2"],
            "versions": ["", "2.0"],
        },
        files=[("files", ("evidencia.pdf", BytesIO(b"pdf"), "application/pdf"))],
        cookies=admin_cookies,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    creados = {d["title"]: d for d in body["data"]}
    assert creados["e2e Manual"]["version"] == "1.0"
    assert creados["e2e Procedimiento"]["version"] == "2.0"
    assert creados["e2e Manual"]["has_file"] is True
    assert creados["e2e Procedimiento"]["has_file"] is False


def test_alta_masiva_sin_filas_utiles_es_400(client, admin_cookies):
    resp = client.post(DOCS, data={"titles": ["   "]}, cookies=admin_cookies)
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_alta_masiva_con_fk_inexistente_es_400(client, admin_cookies):
    resp = client.post(
        DOCS,
        data={"titles": ["e2e FK"], "area_ids": ["99999999"]},
        cookies=admin_cookies,
    )
    assert resp.status_code == 400


def test_detalle_de_documento_inexistente_es_404(client, admin_cookies):
    resp = client.get(f"{DOCS}/99999999", cookies=admin_cookies)
    assert resp.status_code == 404
    assert resp.json() == {"error": "Documento no encontrado", "status": 404}


def test_patch_actualiza_solo_lo_enviado(client, admin_cookies, db_session):
    doc = make_document(db_session, code="E2E-P", title="Antes")
    resp = client.patch(
        f"{DOCS}/{doc.id}", data={"title": "Después"}, cookies=admin_cookies,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["title"] == "Después"
    assert resp.json()["data"]["code"] == "E2E-P"


def test_patch_sin_cambios_es_400(client, admin_cookies, db_session):
    doc = make_document(db_session)
    resp = client.patch(f"{DOCS}/{doc.id}", data={}, cookies=admin_cookies)
    assert resp.status_code == 400


def test_patch_con_status_invalido_es_422(client, admin_cookies, db_session):
    doc = make_document(db_session)
    resp = client.patch(
        f"{DOCS}/{doc.id}", data={"status": "Inventado"}, cookies=admin_cookies,
    )
    assert resp.status_code == 422
    assert "error" in resp.json()


def test_delete_documento(client, admin_cookies, db_session):
    doc = make_document(db_session)
    resp = client.delete(f"{DOCS}/{doc.id}", cookies=admin_cookies)
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert db_session.get(AdhocDocument, doc.id) is None


def test_descarga_sin_adjunto_es_404_json(client, admin_cookies, db_session):
    """El legacy devolvía texto plano ``"El documento no tiene archivo adjunto."``."""
    doc = make_document(db_session)
    resp = client.get(f"{DOCS}/{doc.id}/download", cookies=admin_cookies)
    assert resp.status_code == 404
    assert resp.json()["status"] == 404


def test_descarga_devuelve_el_archivo(client, admin_cookies, uploads_root, db_session):
    doc = make_document(db_session)
    destino = Path(uploads_root) / "documents" / str(doc.id)
    destino.mkdir(parents=True)
    (destino / "informe.pdf").write_bytes(b"%PDF-1.4 e2e")
    doc.file_url = f"{doc.id}/informe.pdf"
    db_session.flush()

    resp = client.get(f"{DOCS}/{doc.id}/download", cookies=admin_cookies)
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 e2e"


# ==========================================================================
# Versionado — only_current y el historial de la cadena
# ==========================================================================

def make_version_chain(db, versions=("1.0", "2.0")):
    """Cadena real: raíz **superada** + su versión vigente, con el mismo ``code``.

    Es la forma que tienen los 202 documentos migrados —``parent_id`` a la raíz,
    una sola fila ``is_current`` por cadena— y el ``code`` repetido es
    precisamente el problema que ``only_current`` resuelve: 54 códigos aparecen
    dos o tres veces en la base.
    """
    code = f"E2E-VER-{uuid.uuid4().hex[:8]}"
    raiz = make_document(
        db, code=code, title="e2e versión vieja", version=versions[0],
        is_current=False, status="Obsoleto",
    )
    nueva = make_document(
        db, code=code, title="e2e versión vigente", version=versions[1],
        parent_id=raiz.id, is_current=True,
    )
    return code, raiz, nueva


def test_listado_oculta_por_defecto_las_versiones_superadas(client, admin_cookies, db_session):
    """Sin ``only_current`` en el query string, la lista solo trae la punta."""
    code, raiz, nueva = make_version_chain(db_session)
    resp = client.get(DOCS, params={"q": code}, cookies=admin_cookies)
    assert resp.status_code == 200, resp.text
    assert [d["id"] for d in resp.json()["data"]] == [nueva.id]


def test_listado_con_only_current_false_incluye_las_superadas(client, admin_cookies, db_session):
    """El checkbox "Ver versiones anteriores" manda ``only_current=false``."""
    code, raiz, nueva = make_version_chain(db_session)
    resp = client.get(
        DOCS, params={"q": code, "only_current": "false"}, cookies=admin_cookies,
    )
    assert resp.status_code == 200, resp.text
    assert {d["id"] for d in resp.json()["data"]} == {raiz.id, nueva.id}


def test_only_current_vacio_no_es_422_y_vale_como_el_default(client, admin_cookies, db_session):
    """Un checkbox nunca tocado reenvía ``?only_current=``; eso no puede ser un 422.

    Es la razón por la que el parámetro se declara ``str`` y no ``bool``: FastAPI
    rechazaría el vacío antes de que ``query_flag_to_bool`` llegara a verlo.
    """
    code, raiz, nueva = make_version_chain(db_session)
    resp = client.get(DOCS, params={"q": code, "only_current": ""}, cookies=admin_cookies)
    assert resp.status_code == 200, resp.text
    assert [d["id"] for d in resp.json()["data"]] == [nueva.id]


def test_historial_de_versiones_devuelve_la_cadena_completa(client, admin_cookies, db_session):
    """``GET /documents/{id}/versions`` — sobre ``ok_list``, raíz primero."""
    code, raiz, nueva = make_version_chain(db_session)
    resp = client.get(f"{DOCS}/{nueva.id}/versions", cookies=admin_cookies)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["total"] == 2
    assert [d["id"] for d in body["data"]] == [raiz.id, nueva.id]
    assert [d["is_current"] for d in body["data"]] == [False, True]


def test_historial_de_versiones_desde_la_raiz_es_el_mismo(client, admin_cookies, db_session):
    """Da igual el id de la cadena con el que se entre."""
    code, raiz, nueva = make_version_chain(db_session)
    desde_raiz = client.get(f"{DOCS}/{raiz.id}/versions", cookies=admin_cookies).json()
    desde_punta = client.get(f"{DOCS}/{nueva.id}/versions", cookies=admin_cookies).json()
    assert desde_raiz["data"] == desde_punta["data"]


def test_historial_de_versiones_de_un_documento_suelto_trae_una_fila(
    client, admin_cookies, db_session,
):
    doc = make_document(db_session)
    body = client.get(f"{DOCS}/{doc.id}/versions", cookies=admin_cookies).json()
    assert body["total"] == 1
    assert body["data"][0]["id"] == doc.id


def test_historial_de_versiones_de_un_id_inexistente_es_404(client, admin_cookies):
    resp = client.get(f"{DOCS}/99999999/versions", cookies=admin_cookies)
    assert resp.status_code == 404
    assert resp.json() == {"error": "Documento no encontrado", "status": 404}


def test_historial_de_versiones_sin_el_permiso_de_lectura_es_403(client, db_session):
    """``role="staff"`` no bypasea: el historial exige ``adhoc.documents.api.read``."""
    doc = make_document(db_session)
    cookies = {"itcj_token": make_jwt(user_id=1, role="staff")}
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.documents.api.create"}):
        resp = client.get(f"{DOCS}/{doc.id}/versions", cookies=cookies)
    assert resp.status_code == 403
    assert "error" in resp.json()


def test_historial_de_versiones_con_el_permiso_exacto_pasa(client, db_session):
    doc = make_document(db_session)
    cookies = {"itcj_token": make_jwt(user_id=1, role="staff")}
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.documents.api.read"}):
        resp = client.get(f"{DOCS}/{doc.id}/versions", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ==========================================================================
# Vigencia — las seis claves nuevas de document_out y el filtro
# ==========================================================================

def test_document_out_trae_las_seis_claves_de_versionado_y_vigencia(
    client, admin_cookies, db_session,
):
    """El JS pinta el badge desde ``expiry_state``; no hace aritmética de fechas.

    Si la hiciera, la haría contra el reloj del cliente y un navegador con la
    zona horaria mal puesta cambiaría de color un documento vencido.
    """
    vence = date.today() + timedelta(days=5)
    doc = make_document(db_session, expiration_date=vence)
    data = client.get(f"{DOCS}/{doc.id}", cookies=admin_cookies).json()["data"]

    assert {"is_current", "parent_id", "expiration_date",
            "is_expired", "days_to_expire", "expiry_state"} <= set(data)
    assert data["is_current"] is True
    assert data["parent_id"] is None
    assert data["expiration_date"] == vence.isoformat()
    assert data["is_expired"] is False
    assert data["days_to_expire"] == 5
    assert data["expiry_state"] == "por_vencer"


def test_document_out_marca_vencido_el_documento_caducado(client, admin_cookies, db_session):
    """45 de los 47 documentos vencidos de la base siguen marcados ``is_current``."""
    doc = make_document(db_session, expiration_date=date.today() - timedelta(days=3))
    data = client.get(f"{DOCS}/{doc.id}", cookies=admin_cookies).json()["data"]
    assert data["is_expired"] is True
    assert data["days_to_expire"] == -3
    assert data["expiry_state"] == "vencido"


def test_document_out_sin_vigencia_deja_expiry_state_en_null(client, admin_cookies, db_session):
    """``None`` es lo que distingue "no vence" de "vence hoy"."""
    doc = make_document(db_session)
    data = client.get(f"{DOCS}/{doc.id}", cookies=admin_cookies).json()["data"]
    assert data["expiration_date"] is None
    assert data["is_expired"] is False
    assert data["days_to_expire"] is None
    assert data["expiry_state"] is None


def test_el_listado_tambien_trae_las_seis_claves(client, admin_cookies, db_session):
    """No solo el detalle: la columna "Vigencia" se pinta desde la tabla."""
    code = f"E2E-VIG-{uuid.uuid4().hex[:8]}"
    make_document(db_session, code=code, expiration_date=date.today() + timedelta(days=2))
    fila = client.get(DOCS, params={"q": code}, cookies=admin_cookies).json()["data"][0]
    assert fila["expiry_state"] == "por_vencer"
    assert fila["days_to_expire"] == 2
    assert fila["is_current"] is True
    assert fila["parent_id"] is None


def test_filtro_expiring_acota_a_los_vencidos(client, admin_cookies, db_session):
    code = f"E2E-VIG-{uuid.uuid4().hex[:8]}"
    vencido = make_document(
        db_session, code=code, expiration_date=date.today() - timedelta(days=1),
    )
    make_document(db_session, code=code, expiration_date=date.today() + timedelta(days=90))
    make_document(db_session, code=code)

    resp = client.get(
        DOCS, params={"q": code, "expiring": "vencidos"}, cookies=admin_cookies,
    )
    assert resp.status_code == 200, resp.text
    assert [d["id"] for d in resp.json()["data"]] == [vencido.id]


def test_expiring_con_valor_inventado_es_400_con_detail_string(client, admin_cookies):
    """400 legible, no el 422 de FastAPI ni un 500 por ``ValidationError`` suelta.

    Y el ``error`` tiene que ser un **string**: un dict produciría
    ``{"error": {...}, "status": 400}`` anidado y rompería al JS.
    """
    resp = client.get(DOCS, params={"expiring": "inventado"}, cookies=admin_cookies)
    assert resp.status_code == 400
    body = resp.json()
    assert body["status"] == 400
    assert isinstance(body["error"], str)
    assert "expiring" in body["error"]
    assert "detail" not in body


def test_el_filtro_de_vigencia_y_el_badge_comparten_el_mismo_hoy(
    client, admin_cookies, db_session, monkeypatch
):
    """El ``WHERE`` de ``?expiring`` y el ``expiry_state`` salen del mismo reloj.

    Son dos implementaciones del mismo criterio —el SQL de ``list_documents`` y
    la aritmética de ``schemas.documents._expiry``—, así que cada una con su
    ``date.today()`` puede discrepar en la ventana en que una petición cruza la
    medianoche: el filtro devuelve una fila que el badge pinta como "por
    vencer". Aquí se adelanta el reloj **del endpoint** diez días: si el ``hoy``
    viaja a los dos sitios, el documento que vence dentro de cinco sale en
    ``vencidos`` Y se serializa como ``'vencido'``.
    """
    from itcj2.apps.adhoc.api import documents as api_documents

    dentro_de_cinco = date.today() + timedelta(days=5)
    doc = make_document(db_session, code=f"E2E-RELOJ-{uuid.uuid4().hex[:6]}",
                        expiration_date=dentro_de_cinco)

    class _RelojAdelantado:
        @staticmethod
        def today():
            return date.today() + timedelta(days=10)

    monkeypatch.setattr(api_documents, "date", _RelojAdelantado)

    resp = client.get(DOCS, params={"q": doc.code, "expiring": "vencidos"},
                      cookies=admin_cookies)
    assert resp.status_code == 200, resp.text
    filas = resp.json()["data"]
    assert [d["id"] for d in filas] == [doc.id]
    assert filas[0]["expiry_state"] == "vencido"
    assert filas[0]["is_expired"] is True
    assert filas[0]["days_to_expire"] == -5


# ==========================================================================
# Alta y edición con vigencia / anexado de versión
# ==========================================================================

def test_alta_masiva_con_vigencia_y_anexado_de_version(client, admin_cookies, db_session):
    """``expiration_dates`` y ``parent_ids``, listas paralelas por índice.

    La segunda fila es el "Anexar nueva versión" del panel de gestión, que
    reutiliza este mismo endpoint: se anexa sobre la **punta** de la cadena y el
    service tiene que normalizar el puntero a la **raíz**, además de dejar toda
    la cadena anterior superada y obsoleta.
    """
    code, raiz, punta = make_version_chain(db_session)
    vence = (date.today() + timedelta(days=10)).isoformat()

    resp = client.post(
        DOCS,
        data={
            "titles": ["e2e con vigencia", "e2e versión nueva"],
            "codes": ["E2E-VIG-ALTA", code],
            "expiration_dates": [vence, ""],
            "parent_ids": ["", str(punta.id)],
        },
        cookies=admin_cookies,
    )
    assert resp.status_code == 200, resp.text
    creados = {d["title"]: d for d in resp.json()["data"]}

    con_vigencia = creados["e2e con vigencia"]
    assert con_vigencia["expiration_date"] == vence
    assert con_vigencia["expiry_state"] == "por_vencer"
    assert con_vigencia["parent_id"] is None
    assert con_vigencia["is_current"] is True

    version = creados["e2e versión nueva"]
    assert version["expiration_date"] is None
    assert version["parent_id"] == raiz.id      # la RAÍZ, no el padre inmediato
    assert version["is_current"] is True

    # El UPDATE en lote de `_supersede_chain` va con `synchronize_session=False`
    # y la sesión del harness es `expire_on_commit=False`: hay que releer, que
    # es lo que en producción hace el commit del request.
    db_session.expire_all()
    historial = client.get(
        f"{DOCS}/{version['id']}/versions", cookies=admin_cookies,
    ).json()["data"]
    assert [d["id"] for d in historial] == [raiz.id, punta.id, version["id"]]
    assert [d["is_current"] for d in historial] == [False, False, True]
    assert [d["status"] for d in historial] == ["Obsoleto", "Obsoleto", "Borrador"]


def test_anexar_version_con_el_flujo_en_curso_es_409(client, admin_cookies, db_session):
    """El anexado deja la cadena en ``'Obsoleto'``, que es terminal.

    Con una tarea de aprobación viva encima, ese ``'Obsoleto'`` es reversible:
    el validador que aprueba su tarea devuelve el documento superado a
    ``'Aprobado'``. Se rechaza antes, con un mensaje que dice qué hacer.
    """
    code, raiz, punta = make_version_chain(db_session)
    db_session.add(AdhocTask(
        description=f"Aprobar Documento: {punta.title}",
        status="En Revisión", priority="Alta", document_id=punta.id,
    ))
    db_session.commit()

    resp = client.post(
        DOCS,
        data={"titles": ["e2e versión nueva"], "codes": [code],
              "parent_ids": [str(punta.id)]},
        cookies=admin_cookies,
    )
    assert resp.status_code == 409, resp.text
    assert "flujo de aprobación en curso" in resp.json()["error"]

    # Nada a medias: la punta sigue vigente y la cadena no creció.
    db_session.expire_all()
    historial = client.get(
        f"{DOCS}/{punta.id}/versions", cookies=admin_cookies,
    ).json()["data"]
    assert [d["id"] for d in historial] == [raiz.id, punta.id]
    assert historial[-1]["is_current"] is True


def test_borrar_la_raiz_de_una_cadena_es_409_y_no_un_500(client, admin_cookies, db_session):
    """``fk_adhoc_documents_parent_id`` no tiene ``ON DELETE``.

    Sin el guard del service, el DELETE llega a Postgres, revienta con
    ``ForeignKeyViolation`` y sale como ``{"error": "internal_error"}`` con 500,
    porque ``_domain_errors`` no traduce ``IntegrityError``. El camino es real
    desde el panel: con "Ver versiones anteriores" marcado, la raíz aparece con
    su papelera como cualquier otra fila.
    """
    code, raiz, punta = make_version_chain(db_session)

    resp = client.delete(f"{DOCS}/{raiz.id}", cookies=admin_cookies)
    assert resp.status_code == 409, resp.text
    assert isinstance(resp.json()["error"], str)
    assert db_session.get(AdhocDocument, raiz.id) is not None

    # La versión anexada sí se borra: lo protegido es la raíz de la cadena.
    assert client.delete(f"{DOCS}/{punta.id}", cookies=admin_cookies).status_code == 200


def test_alta_masiva_con_parent_id_inexistente_es_400(client, admin_cookies):
    resp = client.post(
        DOCS,
        data={"titles": ["e2e huérfana"], "parent_ids": ["99999999"]},
        cookies=admin_cookies,
    )
    assert resp.status_code == 400
    assert isinstance(resp.json()["error"], str)


def test_patch_escribe_y_limpia_la_vigencia(client, admin_cookies, db_session):
    """Mandar el campo vacío es la forma de decir "este documento no vence"."""
    doc = make_document(db_session)
    vence = (date.today() + timedelta(days=60)).isoformat()

    puesta = client.patch(
        f"{DOCS}/{doc.id}", data={"expiration_date": vence}, cookies=admin_cookies,
    )
    assert puesta.status_code == 200, puesta.text
    assert puesta.json()["data"]["expiration_date"] == vence
    assert puesta.json()["data"]["expiry_state"] == "vigente"

    limpiada = client.patch(
        f"{DOCS}/{doc.id}", data={"expiration_date": ""}, cookies=admin_cookies,
    )
    assert limpiada.status_code == 200, limpiada.text
    assert limpiada.json()["data"]["expiration_date"] is None
    assert limpiada.json()["data"]["expiry_state"] is None


def test_patch_distingue_el_campo_ausente_del_campo_vacio(client, admin_cookies, db_session):
    """El bug que cazó este archivo, clavado como regresión.

    FastAPI sustituye por el default todo ``Form`` de texto que llegue vacío
    (``dependencies/utils.py``), así que con ``Optional[str]`` "no lo mandé" y
    "lo mandé vacío" llegaban los dos como ``None``: la vigencia se podía poner
    pero **no quitar**, y un PATCH que solo la vaciaba respondía 400 "No se
    envió ningún cambio". Los ``Form`` del PATCH son listas justamente por esto.
    """
    vence = date.today() + timedelta(days=20)
    doc = make_document(db_session, expiration_date=vence)

    ausente = client.patch(
        f"{DOCS}/{doc.id}", data={"title": "Otro título"}, cookies=admin_cookies,
    )
    assert ausente.status_code == 200, ausente.text
    assert ausente.json()["data"]["expiration_date"] == vence.isoformat()

    vacio = client.patch(
        f"{DOCS}/{doc.id}", data={"expiration_date": ""}, cookies=admin_cookies,
    )
    assert vacio.status_code == 200, vacio.text
    assert vacio.json()["data"]["expiration_date"] is None


def test_patch_con_fecha_invalida_es_422(client, admin_cookies, db_session):
    doc = make_document(db_session)
    resp = client.patch(
        f"{DOCS}/{doc.id}", data={"expiration_date": "31/12/2026"}, cookies=admin_cookies,
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["error"], str)


def test_patch_no_puede_mover_la_cadena_de_versiones(client, admin_cookies, db_session):
    """``is_current`` y ``parent_id`` no son campos del PATCH y se ignoran."""
    code, raiz, punta = make_version_chain(db_session)
    resp = client.patch(
        f"{DOCS}/{punta.id}",
        data={"title": "Editada", "is_current": "false", "parent_id": ""},
        cookies=admin_cookies,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["title"] == "Editada"
    assert data["is_current"] is True
    assert data["parent_id"] == raiz.id


# ==========================================================================
# start-flow
# ==========================================================================

def test_start_flow_sin_flow_id_es_400(client, admin_cookies, db_session):
    doc = make_document(db_session)
    resp = client.post(f"{DOCS}/{doc.id}/start-flow", json={}, cookies=admin_cookies)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Debe enviar flow_id."


def test_start_flow_con_flujo_inexistente_es_404(client, admin_cookies, db_session):
    doc = make_document(db_session)
    resp = client.post(
        f"{DOCS}/{doc.id}/start-flow", json={"flow_id": 99999999}, cookies=admin_cookies,
    )
    assert resp.status_code == 404


def test_start_flow_sobre_una_version_superada_es_409(client, admin_cookies, db_session):
    """``'Obsoleto'`` es terminal: de ahí no se sale arrancando otro flujo.

    ``DOCUMENT_STATUSES_STARTABLE`` solo lo respetaba el navegador (el panel
    esconde el botón del sello salvo en 'Borrador' y 'Rechazado'). Sin el guard
    del servidor, la versión superada volvía a 'En Revisión' con tareas nuevas
    para sus validadores, y las dos listas seguían ocultándola porque
    ``is_current`` no cambia.
    """
    flow = make_flow(db_session)
    code, raiz, punta = make_version_chain(db_session)

    resp = client.post(
        f"{DOCS}/{raiz.id}/start-flow", json={"flow_id": flow.id}, cookies=admin_cookies,
    )
    assert resp.status_code == 409, resp.text
    assert "Obsoleto" in resp.json()["error"]

    db_session.refresh(raiz)
    assert raiz.status == "Obsoleto"
    assert raiz.flow_id is None
    assert db_session.query(AdhocTask).filter_by(document_id=raiz.id).count() == 0


def test_start_flow_camino_feliz(client, admin_cookies, db_session):
    flow = make_flow(db_session)
    doc = make_document(db_session)
    resp = client.post(
        f"{DOCS}/{doc.id}/start-flow", json={"flow_id": flow.id}, cookies=admin_cookies,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "En Revisión"
    assert data["current_step_id"] == flow.steps[0].id
    assert "message" in data


# ==========================================================================
# Flujos
# ==========================================================================

def test_crud_de_flujos(client, admin_cookies):
    creado = client.post(FLOWS, json={"name": "e2e Flujo API"}, cookies=admin_cookies)
    assert creado.status_code == 200, creado.text
    flow_id = creado.json()["data"]["id"]
    assert creado.json()["data"]["step_count"] == 0

    listado = client.get(FLOWS, cookies=admin_cookies)
    assert listado.status_code == 200
    assert any(f["id"] == flow_id for f in listado.json()["data"])

    editado = client.patch(
        f"{FLOWS}/{flow_id}", json={"description": "d"}, cookies=admin_cookies,
    )
    assert editado.json()["data"]["description"] == "d"

    borrado = client.delete(f"{FLOWS}/{flow_id}", cookies=admin_cookies)
    assert borrado.status_code == 200
    assert borrado.json()["success"] is True


def test_crear_flujo_sin_nombre_es_422(client, admin_cookies):
    resp = client.post(FLOWS, json={"name": ""}, cookies=admin_cookies)
    assert resp.status_code == 422


def test_upsert_de_pasos_conserva_ids(client, admin_cookies, db_session):
    flow = make_flow(db_session)
    antes = {s.step_order: s.id for s in flow.steps}
    resp = client.put(
        f"{FLOWS}/{flow.id}/steps",
        json={"steps": [
            {"name": "Revisión editada", "days_limit": 7, "step_order": 1},
            {"name": "Autorización", "days_limit": 5, "step_order": 2},
        ]},
        cookies=admin_cookies,
    )
    assert resp.status_code == 200, resp.text
    despues = {s["step_order"]: s["id"] for s in resp.json()["data"]}
    assert despues == antes


def test_upsert_de_pasos_con_documento_en_revision_es_409(client, admin_cookies, db_session):
    flow = make_flow(db_session)
    make_document(db_session, flow_id=flow.id, current_step_id=flow.steps[0].id,
                  status="En Revisión")
    resp = client.put(
        f"{FLOWS}/{flow.id}/steps",
        json={"steps": [{"name": "Solo uno", "step_order": 1}]},
        cookies=admin_cookies,
    )
    assert resp.status_code == 409
    assert "error" in resp.json()


def test_delete_flujo_en_uso_es_409(client, admin_cookies, db_session):
    flow = make_flow(db_session)
    make_document(db_session, flow_id=flow.id, current_step_id=flow.steps[0].id,
                  status="En Revisión")
    resp = client.delete(f"{FLOWS}/{flow.id}", cookies=admin_cookies)
    assert resp.status_code == 409


def test_listado_de_pasos_de_flujo_inexistente_es_404(client, admin_cookies):
    resp = client.get(f"{FLOWS}/99999999/steps", cookies=admin_cookies)
    assert resp.status_code == 404


# ==========================================================================
# Validadores del paso
# ==========================================================================

def test_validadores_y_notificaciones_de_atraso(client, admin_cookies, db_session):
    flow = make_flow(db_session)
    step_id = flow.steps[0].id
    u1, u2 = make_user(db_session, "a"), make_user(db_session, "b")

    asignar = client.put(
        f"{FLOWS}/steps/{step_id}/validators",
        json={"user_ids": [u1.id, u2.id]},
        cookies=admin_cookies,
    )
    assert asignar.status_code == 200, asignar.text

    marcar = client.put(
        f"{FLOWS}/steps/{step_id}/overdue-notifications",
        json={"user_ids": [u1.id]},
        cookies=admin_cookies,
    )
    assert marcar.status_code == 200

    detalle = client.get(f"{FLOWS}/steps/{step_id}", cookies=admin_cookies)
    data = detalle.json()["data"]
    assert {u["id"] for u in data["assigned"]} == {u1.id, u2.id}
    assert [u["id"] for u in data["notify"]] == [u1.id]

    # Reasignar NO debe borrar el flag (bug del legacy).
    client.put(
        f"{FLOWS}/steps/{step_id}/validators",
        json={"user_ids": [u1.id, u2.id]},
        cookies=admin_cookies,
    )
    detalle2 = client.get(f"{FLOWS}/steps/{step_id}", cookies=admin_cookies)
    assert [u["id"] for u in detalle2.json()["data"]["notify"]] == [u1.id]


def test_validadores_con_usuario_inexistente_es_400(client, admin_cookies, db_session):
    flow = make_flow(db_session)
    resp = client.put(
        f"{FLOWS}/steps/{flow.steps[0].id}/validators",
        json={"user_ids": [99999999]},
        cookies=admin_cookies,
    )
    assert resp.status_code == 400


def test_detalle_de_paso_inexistente_es_404(client, admin_cookies):
    resp = client.get(f"{FLOWS}/steps/99999999", cookies=admin_cookies)
    assert resp.status_code == 404


# ==========================================================================
# A14 — el gate de edición visto desde HTTP
# ==========================================================================
#
# El hallazgo que cierra este bloque: ``PATCH /documents/{id}`` existía, tenía
# permiso propio (``adhoc.documents.api.update``, concedido a admin y
# supervisor_doc) y **no lo invocaba ni un solo archivo JS**. Corregir un título
# mal escrito pasaba por borrar el documento y volver a subirlo, llevándose por
# delante sus tareas y su archivo.
#
# Al conectarlo, la regla de producto quedó estrecha a propósito: solo se edita
# lo que todavía no pasó por el flujo ('Borrador' y 'Rechazado'), nunca una
# versión superada, y el archivo solo se sustituye en 'Borrador'. Aquí se prueba
# lo que ve el cliente: el **409 con sobre estándar** y los dos flags que el
# panel usa para pintar el botón.


def test_patch_sobre_un_documento_aprobado_es_409_con_el_sobre_estandar(
    client, admin_cookies, db_session,
):
    """Lo aprobado es inmutable: se corrige anexando una versión nueva.

    El sobre importa tanto como el código: ``AdhocConflict`` lleva un mensaje que
    explica qué hacer, y ``_domain_errors`` lo pasa como ``detail`` **string**.
    Un ``detail`` dict saldría como ``{"error": {...}, "status": 409}`` anidado y
    el ``extractError`` del panel enseñaría "[object Object]" en el toast.
    """
    doc = make_document(db_session, title="Aprobado intocable", status="Aprobado")

    resp = client.patch(
        f"{DOCS}/{doc.id}", data={"title": "Editado a la fuerza"}, cookies=admin_cookies,
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["status"] == 409
    assert isinstance(body["error"], str)
    assert "Aprobado" in body["error"]
    assert "detail" not in body

    # `flush` antes de `expire_all`: si el service hubiera mutado la fila antes
    # de rechazar, el cambio seguiría pendiente en la sesión del request y
    # `expire_all` lo descartaría en silencio, tapando el fallo.
    db_session.flush()
    db_session.expire_all()
    assert db_session.get(AdhocDocument, doc.id).title == "Aprobado intocable"


@pytest.mark.parametrize("status", ["En Revisión", "Obsoleto"])
def test_patch_sobre_los_demas_estados_cerrados_tambien_es_409(
    client, admin_cookies, db_session, status,
):
    """'En Revisión' está en manos del motor de flujo; 'Obsoleto' es terminal."""
    doc = make_document(db_session, status=status)
    resp = client.patch(f"{DOCS}/{doc.id}", data={"title": "x"}, cookies=admin_cookies)
    assert resp.status_code == 409, resp.text
    assert status in resp.json()["error"]


@pytest.mark.parametrize("status", ["Borrador", "Rechazado"])
def test_patch_sobre_un_documento_editable_es_200(
    client, admin_cookies, db_session, status,
):
    """No regresión: el gate no puede cerrar los que sí se editan."""
    doc = make_document(db_session, code="E2E-A14", title="Antes", status=status)
    resp = client.patch(
        f"{DOCS}/{doc.id}", data={"title": "Después"}, cookies=admin_cookies,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["title"] == "Después"
    assert data["code"] == "E2E-A14"
    assert data["status"] == status      # editar no mueve el estado


def test_patch_sobre_una_version_superada_es_409_aunque_este_en_borrador(
    client, admin_cookies, db_session,
):
    """El cruce que separa las dos reglas del gate.

    ``('Borrador', is_current=False)`` pasaría si solo existiera el gate de
    ``status``. Es histórico del SGC: 58 filas de la base están así, y las dos
    listas ya las ocultan —editarlas sería reescribir en silencio lo que decía un
    documento cuando alguien lo firmó—.
    """
    raiz = make_document(db_session, code="E2E-A14-VER", title="Versión vieja",
                         status="Borrador", is_current=False)
    make_document(db_session, code="E2E-A14-VER", parent_id=raiz.id, is_current=True)

    resp = client.patch(
        f"{DOCS}/{raiz.id}", data={"title": "Reescrita"}, cookies=admin_cookies,
    )
    assert resp.status_code == 409, resp.text
    assert "superada" in resp.json()["error"]

    db_session.flush()
    db_session.expire_all()
    assert db_session.get(AdhocDocument, raiz.id).title == "Versión vieja"


def test_patch_con_archivo_sobre_un_rechazado_es_409_y_el_adjunto_sigue_ahi(
    client, admin_cookies, uploads_root, db_session,
):
    """El gate del archivo es más estrecho que el de la edición, también por HTTP.

    Un ``'Rechazado'`` acepta que le corrijan el código o el título, pero no que
    le cambien el PDF debajo: sus validadores rechazaron *ese* archivo y la
    decisión quedó escrita en ``adhoc_task_approvals``. El 409 llega antes de
    ``save_upload``, así que en disco no aparece ni desaparece nada.
    """
    doc = make_document(db_session, title="Original", status="Rechazado")
    carpeta = Path(uploads_root) / "documents" / str(doc.id)
    carpeta.mkdir(parents=True)
    (carpeta / "rechazado.pdf").write_bytes(b"%PDF-1.4 original")
    doc.file_url = f"{doc.id}/rechazado.pdf"
    db_session.flush()

    resp = client.patch(
        f"{DOCS}/{doc.id}",
        data={"title": "Editado"},
        files={"file": ("colado.pdf", BytesIO(b"%PDF-1.4 colado"), "application/pdf")},
        cookies=admin_cookies,
    )
    assert resp.status_code == 409, resp.text
    assert isinstance(resp.json()["error"], str)

    assert [p.name for p in carpeta.iterdir()] == ["rechazado.pdf"]
    assert (carpeta / "rechazado.pdf").read_bytes() == b"%PDF-1.4 original"
    db_session.flush()
    db_session.expire_all()
    recargado = db_session.get(AdhocDocument, doc.id)
    assert recargado.file_url == f"{doc.id}/rechazado.pdf"
    assert recargado.title == "Original"


def test_los_dos_vocabularios_de_status_del_patch_son_independientes(
    client, admin_cookies, db_session,
):
    """``DOCUMENT_STATUSES_EDITABLE`` y ``DOCUMENT_STATUSES_VIA_PATCH`` no son la
    misma lista, y este test fija en qué se traduce eso para el cliente.

    * *En qué estado tiene que estar* el documento para que el PATCH lo toque:
      'Borrador' y 'Rechazado' (gate de A14, 409 si no).
    * *Qué valores de ``status`` puede escribir* ese PATCH: 'Borrador' y
      'Obsoleto' (400 si no; los demás los produce el motor de flujo).

    Su intersección deja un solo camino vivo para retirar algo a mano —marcar
    'Obsoleto' un 'Borrador'—, y **desde 'Aprobado' ya no se puede**: es el 409
    de A14, igual que para cualquier otro campo. Retirar un documento aprobado
    pasa hoy por anexarle una versión nueva, que es lo que deja obsoleta la
    cadena entera. Queda escrito aquí para que nadie lo tome por un descuido.
    """
    borrador = make_document(db_session, status="Borrador")
    retirado = client.patch(
        f"{DOCS}/{borrador.id}", data={"status": "Obsoleto"}, cookies=admin_cookies,
    )
    assert retirado.status_code == 200, retirado.text
    assert retirado.json()["data"]["status"] == "Obsoleto"
    # Y 'Obsoleto' es terminal: acaba de cerrarse su propia puerta.
    assert retirado.json()["data"]["is_editable"] is False

    aprobado = make_document(db_session, status="Aprobado")
    resp = client.patch(
        f"{DOCS}/{aprobado.id}", data={"status": "Obsoleto"}, cookies=admin_cookies,
    )
    assert resp.status_code == 409, resp.text

    # El otro lado de la asimetría: un estado del motor de flujo es 400, no 409,
    # aunque el documento sí fuera editable. Son dos preguntas distintas.
    otro = make_document(db_session, status="Borrador")
    invalido = client.patch(
        f"{DOCS}/{otro.id}", data={"status": "Aprobado"}, cookies=admin_cookies,
    )
    assert invalido.status_code == 400, invalido.text
    assert "flujo de aprobación" in invalido.json()["error"]


def test_patch_sin_el_permiso_de_edicion_es_403(client, db_session):
    """``role="staff"`` no bypasea: editar exige ``adhoc.documents.api.update``.

    Se le dan todos los demás permisos de documentos (leer, crear, borrar) menos
    ese, que es la forma de comprobar que el 403 sale del permiso correcto y no
    de un conjunto vacío.
    """
    doc = make_document(db_session)
    cookies = {"itcj_token": make_jwt(user_id=1, role="staff")}
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.documents.api.read",
                             "adhoc.documents.api.create",
                             "adhoc.documents.api.delete"}):
        resp = client.patch(f"{DOCS}/{doc.id}", data={"title": "x"}, cookies=cookies)
    assert resp.status_code == 403
    assert "error" in resp.json()


def test_patch_con_el_permiso_exacto_pasa(client, db_session):
    doc = make_document(db_session, title="Antes")
    cookies = {"itcj_token": make_jwt(user_id=1, role="staff")}
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.documents.api.update"}):
        resp = client.patch(f"{DOCS}/{doc.id}", data={"title": "Después"}, cookies=cookies)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["title"] == "Después"


# --------------------------------------------------------------------------
# is_editable / file_replaceable — lo que el panel lee para pintar el botón
# --------------------------------------------------------------------------
#
# El botón "Editar" se pinta SIEMPRE (con el permiso puesto) y se deshabilita
# desde estos dos flags, con un `title` que explica por qué. Por eso viajan en
# cada fila y no se recalculan en JS: la regla es del servidor, y el navegador
# que la reimplementara acabaría discrepando en cuanto cambiara la lista de
# estados editables.

#: ``(status, is_current)`` -> ``(is_editable, file_replaceable)``. Los cuatro
#: cruces de "estado editable o no" por "vigente o superada", más el
#: ``'Rechazado'`` que separa un flag del otro.
CRUCES_DE_EDICION = [
    ("Borrador",  True,  True,  True),
    ("Rechazado", True,  True,  False),   # editable, pero el archivo no se toca
    ("Aprobado",  True,  False, False),
    ("Borrador",  False, False, False),   # superada: ni con estado editable
    ("Aprobado",  False, False, False),
]


@pytest.mark.parametrize(
    "status,is_current,editable,archivo",
    CRUCES_DE_EDICION,
    ids=[f"{s}-{'vigente' if c else 'superada'}" for s, c, _, _ in CRUCES_DE_EDICION],
)
def test_el_detalle_publica_los_dos_flags_de_edicion(
    client, admin_cookies, db_session, status, is_current, editable, archivo,
):
    doc = make_document(db_session, status=status, is_current=is_current)
    data = client.get(f"{DOCS}/{doc.id}", cookies=admin_cookies).json()["data"]

    assert data["is_editable"] is editable
    assert data["file_replaceable"] is archivo


@pytest.mark.parametrize(
    "status,is_current,editable,archivo",
    CRUCES_DE_EDICION,
    ids=[f"{s}-{'vigente' if c else 'superada'}" for s, c, _, _ in CRUCES_DE_EDICION],
)
def test_el_listado_tambien_publica_los_dos_flags(
    client, admin_cookies, db_session, status, is_current, editable, archivo,
):
    """El botón vive en la TABLA, así que los flags tienen que venir en la fila.

    Si solo los trajera el detalle, el panel tendría que pedir 25 documentos uno
    a uno para saber cuáles habilitar.
    """
    code = f"E2E-A14-{uuid.uuid4().hex[:8]}"
    make_document(db_session, code=code, status=status, is_current=is_current)
    fila = client.get(
        DOCS, params={"q": code, "only_current": "false"}, cookies=admin_cookies,
    ).json()["data"][0]

    assert fila["is_editable"] is editable
    assert fila["file_replaceable"] is archivo


def test_los_flags_predicen_lo_que_hara_el_patch(client, admin_cookies, db_session):
    """La coherencia que sostiene todo: lo que el panel pinta es lo que pasa.

    Fila a fila, ``is_editable`` tiene que valer exactamente "el PATCH responde
    200". Si divergieran, el usuario vería el botón encendido, rellenaría el
    formulario del modal y se llevaría un 409 al guardar —o al revés: el botón
    apagado sobre un documento que sí se podía corregir, que es justo el estado
    del que veníamos—.
    """
    for status, is_current, _, _ in CRUCES_DE_EDICION:
        doc = make_document(db_session, title="Original",
                            status=status, is_current=is_current)
        flags = client.get(f"{DOCS}/{doc.id}", cookies=admin_cookies).json()["data"]
        resp = client.patch(
            f"{DOCS}/{doc.id}", data={"title": "Editado"}, cookies=admin_cookies,
        )
        assert (resp.status_code == 200) is flags["is_editable"], (status, is_current)
        assert resp.status_code in (200, 409), resp.text

# ==========================================================================
# B6 — GET /documents/{id}/acknowledgements (difusión y acuses)
#
# Hallazgo A9: `adhoc_document_visibility` (9 390 filas, 55 usuarios, 198 de los
# 202 documentos) y `adhoc_document_acknowledgements` (987 acuses con fecha real
# entre 2019 y 2025) llegaron con el ETL del SGC y no las leía NINGUNA pantalla.
# Esta ruta es su única salida, y es de CONSULTA: aquí no se registran acuses
# nuevos.
#
# El sobre es `ok_item`, con tres bloques —`document` (un brief, no
# `document_out`), `summary` (los cuatro números ya sumados en el servidor) y
# `recipients`—. `has_app_access`/`without_access` se OMITEN cuando el servidor
# no pudo resolver quién entra hoy: un `false` afirmaría algo no comprobado.
# ==========================================================================

def make_recipient(db, first, last):
    """Usuario con apellido controlado: el orden de la lista es por apellido."""
    tag = uuid.uuid4().hex[:10]
    u = User(
        first_name=first, last_name=last,
        username=f"e2e_adhoc_dif_{tag}",
        email=f"e2e_adhoc_dif_{tag}@test.local",
    )
    db.add(u)
    db.flush()
    return u


def difundir(db, doc, *users):
    """Lista de distribución: a quién le tocaba conocer el documento."""
    for u in users:
        db.add(AdhocDocumentVisibility(document_id=doc.id, user_id=u.id))
    db.flush()


def acusar(db, doc, user, when=datetime(2021, 4, 8, 10, 15)):
    """Acuse con fecha real: ``acknowledged_at`` es NOT NULL a propósito."""
    db.add(AdhocDocumentAcknowledgement(
        document_id=doc.id, user_id=user.id, acknowledged_at=when,
    ))
    db.flush()


def _con_acceso(*users):
    """Parchea el conjunto de quienes pueden ENTRAR a Calidad.

    Módulo **fuente** (``authz_service``), porque ``_app_user_ids`` importa la
    función dentro del cuerpo. Devolver ids en vez del ``SELECT`` basta: el
    endpoint los mete en un ``User.id.in_(...)``.
    """
    return patch(
        "itcj2.core.services.authz_service.users_with_assignment_select",
        return_value=[u.id for u in users],
    )


def test_panel_de_difusion_devuelve_el_sobre_estandar(client, admin_cookies, db_session):
    """Camino feliz: tres destinatarios, uno acusó.

    El resumen lo suma el SERVIDOR —incluido el porcentaje—: es el número que se
    enseña como cobertura y una división en el navegador es también una división
    entre cero el día que el documento no tenga destinatarios.
    """
    doc = make_document(db_session, code="E2E-DIF-1", title="Manual de calidad",
                        version="2.1", status="Aprobado")
    ana = make_recipient(db_session, "Ana", "AAA")
    beto = make_recipient(db_session, "Beto", "BBB")
    cruz = make_recipient(db_session, "Cruz", "CCC")
    difundir(db_session, doc, ana, beto, cruz)
    acusar(db_session, doc, beto)

    with _con_acceso(ana, beto, cruz):
        resp = client.get(f"{DOCS}/{doc.id}/acknowledgements", cookies=admin_cookies)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["document"] == {
        "id": doc.id, "code": "E2E-DIF-1", "title": "Manual de calidad",
        "version": "2.1", "status": "Aprobado", "is_current": True,
    }
    assert data["summary"] == {
        "assigned": 3, "acknowledged": 1, "pending": 2,
        # 1 de 3 con un decimal: el redondeo lo hace el servidor.
        "coverage_pct": 33.3,
        "without_access": 0,
    }
    acuso = next(r for r in data["recipients"] if r["user"]["id"] == beto.id)
    assert acuso["acknowledged"] is True
    assert acuso["acknowledged_at"] == "2021-04-08T10:15:00"
    assert acuso["has_app_access"] is True
    pendiente = next(r for r in data["recipients"] if r["user"]["id"] == ana.id)
    assert pendiente["acknowledged"] is False
    assert pendiente["acknowledged_at"] is None


def test_el_documento_viaja_como_brief_no_como_document_out(
    client, admin_cookies, db_session,
):
    """Seis claves y ni una más.

    ``document_out`` arrastraría los cinco catálogos —cinco ``SELECT`` perezosos
    por abrir una ventana que solo necesita el encabezado—, y el modal se abre
    desde una fila que ya trae el documento entero.
    """
    doc = make_document(db_session)
    difundir(db_session, doc, make_recipient(db_session, "Ana", "AAA"))

    with _con_acceso():
        data = client.get(f"{DOCS}/{doc.id}/acknowledgements",
                          cookies=admin_cookies).json()["data"]

    assert set(data["document"]) == {"id", "code", "title", "version",
                                     "status", "is_current"}
    assert set(data) == {"document", "summary", "recipients"}


def test_el_destinatario_no_lleva_correo(client, admin_cookies, db_session):
    """``id`` y ``name``, y nada más: el correo NO sale por esta ruta.

    Es una decisión de exposición, no de ancho de tabla. El endpoint se sirve
    con ``adhoc.documents.api.read``, que también tiene ``consult``; con el
    correo dentro, recorrer los 202 ids de documento enumeraba las 55 personas
    de ``adhoc_document_visibility`` con su dirección —entre ellas 30 que ya no
    entran a la app, con direcciones personales de gente que se fue—. Lo que ese
    mismo rol podía enumerar por sus otros permisos es otro orden de magnitud:
    3 autores distintos en ``adhoc_documents`` y 8 validadores de paso, 11 en
    total. Y ``consult`` no tiene ``documents.page.manage``, así que ni siquiera
    puede abrir el panel donde vive el modal.

    La pantalla no lo echa de menos: la columna del correo no decía si acusó, ni
    cuándo, ni si conserva el acceso, y la app no registra acuses nuevos, así
    que tampoco hay a quién escribirle desde esa ventana.
    """
    doc = make_document(db_session)
    ana = make_recipient(db_session, "Ana", "AAA")
    difundir(db_session, doc, ana)

    with _con_acceso(ana):
        data = client.get(f"{DOCS}/{doc.id}/acknowledgements",
                          cookies=admin_cookies).json()["data"]

    destinatario = data["recipients"][0]["user"]
    assert set(destinatario) == {"id", "name"}
    assert "email" not in destinatario
    # Y el nombre sigue identificando a la persona, que es lo que pide la
    # evidencia ISO.
    assert destinatario["name"]


def test_el_autor_del_documento_si_conserva_su_correo(client, admin_cookies, db_session):
    """Lo que se recortó es ESTE serializador, no ``user_brief`` entero.

    ``document_out`` y los validadores de paso siguen emitiendo ``email``: son
    superficies con otro alcance —un autor por documento, no la lista de
    distribución completa— y tocarlas habría cambiado tres endpoints para
    arreglar uno.
    """
    autor = make_recipient(db_session, "Autora", "AAA")
    doc = make_document(db_session)
    doc.author_id = autor.id
    db_session.flush()

    data = client.get(f"{DOCS}/{doc.id}", cookies=admin_cookies).json()["data"]

    assert data["author"]["email"] == autor.email


def test_los_destinatarios_van_por_apellido_y_nombre(client, admin_cookies, db_session):
    """El mismo orden que los pickers, y **no** el del acuse.

    La lista se lee buscando un nombre; ordenar por acuse movería de sitio a una
    persona cada vez que alguien acusa.
    """
    doc = make_document(db_session)
    cruz = make_recipient(db_session, "Cruz", "ZZZ")
    ana = make_recipient(db_session, "Ana", "AAA")
    beto = make_recipient(db_session, "Beto", "MMM")
    difundir(db_session, doc, cruz, ana, beto)
    # El último de la lista es el único que acusó: si el orden fuera por acuse,
    # subiría al principio.
    acusar(db_session, doc, cruz)

    with _con_acceso(ana, beto, cruz):
        data = client.get(f"{DOCS}/{doc.id}/acknowledgements",
                          cookies=admin_cookies).json()["data"]

    assert [r["user"]["id"] for r in data["recipients"]] == [ana.id, beto.id, cruz.id]


def test_el_acuse_es_por_par_documento_usuario(client, admin_cookies, db_session):
    """Que un compañero acuse el documento no acusa por mí.

    Y el acuse de OTRO documento tampoco: el cruce es
    ``(document_id, user_id)``, el par que las dos tablas declaran ``UNIQUE``.
    """
    doc = make_document(db_session)
    otro = make_document(db_session)
    ana = make_recipient(db_session, "Ana", "AAA")
    beto = make_recipient(db_session, "Beto", "BBB")
    difundir(db_session, doc, ana, beto)
    difundir(db_session, otro, ana)
    acusar(db_session, doc, beto)
    acusar(db_session, otro, ana)

    with _con_acceso(ana, beto):
        data = client.get(f"{DOCS}/{doc.id}/acknowledgements",
                          cookies=admin_cookies).json()["data"]

    por_usuario = {r["user"]["id"]: r for r in data["recipients"]}
    assert por_usuario[beto.id]["acknowledged"] is True
    assert por_usuario[ana.id]["acknowledged"] is False
    assert data["summary"]["acknowledged"] == 1


def test_documento_inexistente_es_404(client, admin_cookies):
    resp = client.get(f"{DOCS}/99999999/acknowledgements", cookies=admin_cookies)
    assert resp.status_code == 404
    assert resp.json() == {"error": "Documento no encontrado", "status": 404}


def test_difusion_sin_el_permiso_de_lectura_es_403(client, db_session):
    """``role="staff"`` no bypasea: la difusión exige ``adhoc.documents.api.read``."""
    doc = make_document(db_session)
    cookies = {"itcj_token": make_jwt(user_id=1, role="staff")}
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.documents.api.update"}):
        resp = client.get(f"{DOCS}/{doc.id}/acknowledgements", cookies=cookies)
    assert resp.status_code == 403
    assert "error" in resp.json()


def test_difusion_con_el_permiso_exacto_pasa(client, db_session):
    """Sin permiso propio: el mismo ``read`` que el detalle, como ``/versions``.

    No revela nada que ``GET /documents/{id}`` no revelara ya; lo que añade es a
    quién se le distribuyó.
    """
    doc = make_document(db_session)
    cookies = {"itcj_token": make_jwt(user_id=1, role="staff")}
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.documents.api.read"}), \
         _con_acceso():
        resp = client.get(f"{DOCS}/{doc.id}/acknowledgements", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# --------------------------------------------------------------------------
# Los DOS vacíos, que no son el mismo
# --------------------------------------------------------------------------

def test_documento_sin_lista_de_distribucion(client, admin_cookies, db_session):
    """4 de los 202 están así, y **no** es un 404.

    "A nadie se le asignó este documento" es una afirmación sobre el SGC, no un
    error: el documento existe y su lista de distribución está vacía.
    """
    doc = make_document(db_session)

    with _con_acceso():
        resp = client.get(f"{DOCS}/{doc.id}/acknowledgements", cookies=admin_cookies)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["recipients"] == []
    assert data["summary"] == {
        "assigned": 0, "acknowledged": 0, "pending": 0,
        # Sin denominador no hay porcentaje: 0.0, y ninguna división.
        "coverage_pct": 0.0, "without_access": 0,
    }


def test_documento_difundido_que_nadie_acuso(client, admin_cookies, db_session):
    """141 de los 198 documentos con lista están así.

    El otro vacío, y dice algo distinto: aquí sí había a quién avisar y nadie
    contestó. El ``0 %`` significa exactamente lo que dice.
    """
    doc = make_document(db_session)
    ana = make_recipient(db_session, "Ana", "AAA")
    beto = make_recipient(db_session, "Beto", "BBB")
    difundir(db_session, doc, ana, beto)

    with _con_acceso(ana, beto):
        data = client.get(f"{DOCS}/{doc.id}/acknowledgements",
                          cookies=admin_cookies).json()["data"]

    assert len(data["recipients"]) == 2
    assert [r["acknowledged"] for r in data["recipients"]] == [False, False]
    assert [r["acknowledged_at"] for r in data["recipients"]] == [None, None]
    assert data["summary"] == {
        "assigned": 2, "acknowledged": 0, "pending": 2,
        "coverage_pct": 0.0, "without_access": 0,
    }


def test_los_dos_vacios_no_devuelven_la_misma_forma(client, admin_cookies, db_session):
    """La comparación explícita, porque la UI los pinta distinto.

    Sin destinatarios el modal esconde la tira de cifras —un "0 %" ahí se leería
    como "nadie acusó" cuando lo que pasa es que a nadie se le asignó el
    documento—; con destinatarios y sin acuses la enseña. Si las dos respuestas
    fueran iguales, esa distinción no se podría hacer en el cliente.
    """
    sin_lista = make_document(db_session)
    con_lista = make_document(db_session)
    ana = make_recipient(db_session, "Ana", "AAA")
    difundir(db_session, con_lista, ana)

    with _con_acceso(ana):
        vacio = client.get(f"{DOCS}/{sin_lista.id}/acknowledgements",
                           cookies=admin_cookies).json()["data"]
        pendiente = client.get(f"{DOCS}/{con_lista.id}/acknowledgements",
                               cookies=admin_cookies).json()["data"]

    assert vacio["summary"]["assigned"] == 0
    assert pendiente["summary"]["assigned"] == 1
    assert vacio["recipients"] == []
    assert pendiente["recipients"] != []
    # Los dos tienen 0 acuses y 0 % — lo que los separa es el denominador.
    assert vacio["summary"]["acknowledged"] == pendiente["summary"]["acknowledged"] == 0
    assert vacio["summary"] != pendiente["summary"]


# --------------------------------------------------------------------------
# La marca de "ya no puede entrar a Calidad"
# --------------------------------------------------------------------------

def test_a_quien_ya_no_entra_se_le_marca_pero_no_se_le_filtra(
    client, admin_cookies, db_session,
):
    """26 de los 55 usuarios con difusión no tienen acceso hoy.

    La difusión de 2019-2025 se hizo a esas 55 personas: ocultar a 26 falsearía
    la evidencia. Se les marca, que es lo que separa "no acusó" de "no acusó y
    hoy ya ni siquiera podría".
    """
    doc = make_document(db_session)
    dentro = make_recipient(db_session, "Ana", "AAA")
    fuera = make_recipient(db_session, "Beto", "BBB")
    difundir(db_session, doc, dentro, fuera)

    with _con_acceso(dentro):
        data = client.get(f"{DOCS}/{doc.id}/acknowledgements",
                          cookies=admin_cookies).json()["data"]

    por_usuario = {r["user"]["id"]: r for r in data["recipients"]}
    assert por_usuario[dentro.id]["has_app_access"] is True
    assert por_usuario[fuera.id]["has_app_access"] is False
    assert data["summary"]["without_access"] == 1
    assert data["summary"]["assigned"] == 2


def test_sin_conjunto_de_acceso_las_dos_claves_se_omiten(client, admin_cookies, db_session):
    """Sin fila de ``adhoc`` en ``core_apps`` no hay marca, pero sí hay panel.

    Un acuse de 2021 no deja de ser evidencia porque el servidor no pueda decir
    quién entra hoy. Y ausente ≠ ``false``: un ``false`` afirmaría algo no
    comprobado, la misma prudencia que ``serialize_task`` con
    ``assignees_without_access``.
    """
    from fastapi import HTTPException

    doc = make_document(db_session)
    ana = make_recipient(db_session, "Ana", "AAA")
    difundir(db_session, doc, ana)

    with patch("itcj2.core.services.authz_service.users_with_assignment_select",
               side_effect=HTTPException(status_code=404, detail="App inexistente")):
        resp = client.get(f"{DOCS}/{doc.id}/acknowledgements", cookies=admin_cookies)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert "without_access" not in data["summary"]
    assert "has_app_access" not in data["recipients"][0]
    # Lo que sí se sabe sigue viajando.
    assert data["summary"]["assigned"] == 1


# --------------------------------------------------------------------------
# Orden de rutas
# --------------------------------------------------------------------------

def test_la_ruta_de_acuses_no_la_atrapa_la_de_un_solo_tramo(
    client, admin_cookies, db_session,
):
    """``/{document_id}`` y ``/{document_id}/acknowledgements`` son dos rutas.

    Es el mismo cuidado que exigen ``/incidents/files/{id}`` y
    ``/program-events/files/{id}``: el convertidor por defecto de FastAPI es
    ``str``, así que un tramo de más casa con lo que no debe si el orden de
    declaración se tuerce. Aquí se comprueba por el resultado —cada URL devuelve
    SU forma— y no leyendo el módulo, que es lo que un reordenamiento rompería.
    """
    doc = make_document(db_session, code="E2E-RUTA", title="Con difusión")
    ana = make_recipient(db_session, "Ana", "AAA")
    difundir(db_session, doc, ana)

    with _con_acceso(ana):
        panel = client.get(f"{DOCS}/{doc.id}/acknowledgements", cookies=admin_cookies)
    detalle = client.get(f"{DOCS}/{doc.id}", cookies=admin_cookies)

    assert panel.status_code == 200 and detalle.status_code == 200
    assert set(panel.json()["data"]) == {"document", "summary", "recipients"}
    # El detalle es el documento pelado: ni resumen ni destinatarios.
    assert "summary" not in detalle.json()["data"]
    assert detalle.json()["data"]["code"] == "E2E-RUTA"


def test_una_version_superada_conserva_su_propia_difusion(
    client, admin_cookies, db_session,
):
    """El panel no recorta la cadena de versiones, y es deliberado.

    Las dos listas ocultan lo superado porque enseñar dos filas del mismo
    ``code`` entrega documentación vencida como si estuviera en vigor. Aquí no
    aplica: se entra por un documento concreto y lo que se pregunta es a quién
    se le distribuyó **ese**. 2 679 de las 9 390 filas de visibilidad apuntan a
    una versión superada; si el panel las escondiera, esa evidencia volvería a
    no tener pantalla.
    """
    code, raiz, nueva = make_version_chain(db_session)
    ana = make_recipient(db_session, "Ana", "AAA")
    beto = make_recipient(db_session, "Beto", "BBB")
    difundir(db_session, raiz, ana, beto)
    difundir(db_session, nueva, ana)
    acusar(db_session, raiz, ana)

    with _con_acceso(ana, beto):
        vieja = client.get(f"{DOCS}/{raiz.id}/acknowledgements",
                           cookies=admin_cookies).json()["data"]
        vigente = client.get(f"{DOCS}/{nueva.id}/acknowledgements",
                             cookies=admin_cookies).json()["data"]

    assert vieja["document"]["is_current"] is False
    assert vieja["summary"]["assigned"] == 2
    assert vieja["summary"]["acknowledged"] == 1
    # La difusión de la versión vigente es otra: ni hereda ni presta acuses.
    assert vigente["document"]["is_current"] is True
    assert vigente["summary"] == {
        "assigned": 1, "acknowledged": 0, "pending": 1,
        "coverage_pct": 0.0, "without_access": 0,
    }
