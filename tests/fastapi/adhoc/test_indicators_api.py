"""Tests HTTP de ``itcj2.apps.adhoc.api.indicators``.

Los tres routers de indicadores ya están cableados en
``itcj2/apps/adhoc/router.py``, así que el fixture ``client`` NO los monta:
pega contra las URLs reales de la app. Volver a montarlos duplicaría el árbol
de rutas y estos tests pasarían aunque el prefijo del cableado fuera otro.

Gotchas del harness que estos tests dan por sabidos (plan §9.1):

* el cuerpo de error es ``{"error": ..., "status": ...}``, **no** ``{"detail": ...}``;
* un JWT con ``role="admin"`` **bypasea** ``require_perms`` — para probar
  permisos hace falta ``role="staff"`` + parche de
  ``cached_has_assignment``/``cached_perms``;
* los endpoints importan los services **dentro** de la función, así que el
  parche va sobre el **módulo fuente**, nunca sobre el consumidor.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from itcj2.database import get_db
from tests.conftest import make_jwt

SVC = "itcj2.apps.adhoc.services.indicator_service.IndicatorService"

BASE = "/api/adhoc/v2"
YEARS = f"{BASE}/indicator-years"
INDICATORS = f"{BASE}/indicators"
TRACKINGS = f"{BASE}/indicator-trackings"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(app_client):
    """La app real (routers ya cableados) con ``get_db`` mockeado."""
    app_client.app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        yield app_client
    finally:
        app_client.app.dependency_overrides.pop(get_db, None)


def _admin():
    """Cookie de admin global: bypasea ``require_perms`` por diseño."""
    return {"Cookie": f"itcj_token={make_jwt(user_id=200, role='admin')}"}


def _staff():
    return {"Cookie": f"itcj_token={make_jwt(user_id=300, role='staff')}"}


def _fake_year(id_=7, year=2026):
    return SimpleNamespace(id=id_, year=year)


def _fake_indicator(id_=11, **overrides):
    data = dict(
        id=id_,
        year_id=7,
        process_id=3,
        process=SimpleNamespace(name="Gestión de Calidad", color="#4834d4"),
        objective="Satisfacción del cliente",
        prev_results=None,
        unit_calc=None,
        responsible="Ana",
        facilitator=None,
        source=None,
        strategic_rel=None,
        criteria=None,
        plan_b=None,
        frequency="Mensual",
        planned_white="95%",
        planned_red="<70%",
        planned_yellow="70-85%",
        planned_green=">85%",
        document_url=None,
        created_at=None,
        updated_at=None,
        trackings=[],
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def _fake_tracking(id_=5, period_index=3, real_value="92", color="verde"):
    return SimpleNamespace(
        id=id_, indicator_id=11, period_index=period_index,
        real_value=real_value, color=color,
    )


# ---------------------------------------------------------------------------
# Autenticación y autorización
# ---------------------------------------------------------------------------

ROUTES = [
    ("get", YEARS, None),
    ("post", YEARS, {"json": {"years": [2026]}}),
    ("delete", f"{YEARS}/1", None),
    ("get", f"{INDICATORS}?year_id=1", None),
    ("patch", f"{INDICATORS}/1", {"data": {"payload": '{"objective": "x"}'}}),
    ("delete", f"{INDICATORS}/1", None),
    ("get", f"{INDICATORS}/1/download", None),
    ("put", TRACKINGS, {"json": {"indicator_id": 1, "period_index": 1}}),
]


@pytest.mark.parametrize("method,url,kwargs", ROUTES)
def test_every_route_rejects_anonymous(client, method, url, kwargs):
    """Ningún endpoint de ``/api/adhoc/v2/*` responde 200 sin cookie válida.

    En el legacy las 6 rutas de indicadores eran **anónimas**.
    """
    resp = getattr(client, method)(url, **(kwargs or {}))
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] and body["status"] == 401
    assert isinstance(body["error"], str)   # detail STRING, no dict anidado


@pytest.mark.parametrize("method,url,kwargs", ROUTES)
def test_every_route_rejects_missing_permission(client, method, url, kwargs):
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms", return_value=set()):
        resp = getattr(client, method)(url, headers=_staff(), **(kwargs or {}))
    assert resp.status_code == 403
    assert resp.json()["status"] == 403


def test_permission_granted_lets_the_request_through(client):
    """El permiso exacto del DML (``adhoc.indicators.api.read``) abre la puerta."""
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.indicators.api.read"}), \
         patch(f"{SVC}.list_years", return_value=[]):
        resp = client.get(YEARS, headers=_staff())
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Años
# ---------------------------------------------------------------------------

def test_list_years_returns_the_list_envelope(client):
    with patch(f"{SVC}.list_years", return_value=[(_fake_year(7, 2026), 4)]):
        resp = client.get(YEARS, headers=_admin())

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True and body["total"] == 1
    assert body["data"][0] == {"id": 7, "year": 2026, "indicators_count": 4}


def test_create_years_reports_created_and_skipped(client):
    with patch(f"{SVC}.create_years",
               return_value={"created": [_fake_year(8, 2027)], "skipped": [2026]}) as mock:
        resp = client.post(YEARS, headers=_admin(), json={"years": [2026, 2027]})

    assert resp.status_code == 201
    body = resp.json()
    assert body["success"] is True
    assert body["data"] == [{"id": 8, "year": 2027, "indicators_count": 0}]
    assert body["skipped"] == [2026]
    mock.assert_called_once()
    assert mock.call_args.args[1] == [2026, 2027]


def test_create_years_rejects_an_empty_batch(client):
    resp = client.post(YEARS, headers=_admin(), json={"years": []})
    assert resp.status_code == 422


def test_create_years_rejects_an_absurd_year(client):
    """El legacy hacía ``int()`` sobre todos los valores del formulario."""
    resp = client.post(YEARS, headers=_admin(), json={"years": [19]})
    assert resp.status_code == 422


def test_delete_year_missing_is_a_real_404(client):
    """El ``except Exception`` del legacy convertía el 404 en un redirect de
    éxito."""
    with patch(f"{SVC}.delete_year", side_effect=LookupError("El año 9 no existe")):
        resp = client.delete(f"{YEARS}/9", headers=_admin())

    assert resp.status_code == 404
    assert resp.json() == {"error": "El año 9 no existe", "status": 404}


def test_delete_year_ok(client):
    with patch(f"{SVC}.delete_year") as mock:
        resp = client.delete(f"{YEARS}/9", headers=_admin())
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert mock.call_args.args[1] == 9


# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------

def test_list_indicators_requires_year_id(client):
    resp = client.get(INDICATORS, headers=_admin())
    assert resp.status_code == 422


def test_list_indicators_exposes_the_four_thresholds(client):
    """Regresión del ``planned_value = "b-r-a-v"``: el umbral amarillo lleva un
    guion y tiene que sobrevivir intacto."""
    with patch(f"{SVC}.list_indicators", return_value=[_fake_indicator()]):
        resp = client.get(f"{INDICATORS}?year_id=7", headers=_admin())

    assert resp.status_code == 200
    row = resp.json()["data"][0]
    assert row["planned_white"] == "95%"
    assert row["planned_red"] == "<70%"
    assert row["planned_yellow"] == "70-85%"
    assert row["planned_green"] == ">85%"
    assert row["process_name"] == "Gestión de Calidad"
    assert row["periods"] == 12          # Mensual
    assert row["has_document"] is False


def test_list_indicators_unknown_year_is_404(client):
    with patch(f"{SVC}.list_indicators", side_effect=LookupError("no existe")):
        resp = client.get(f"{INDICATORS}?year_id=999", headers=_admin())
    assert resp.status_code == 404


def test_create_indicators_bulk_multipart(client):
    payload = (
        '{"indicators": [{"process_id": 3, "objective": "Uno", '
        '"frequency": "", "planned_yellow": "70-85%"}]}'
    )
    with patch(f"{SVC}.bulk_create", return_value=[_fake_indicator()]) as mock:
        resp = client.post(
            INDICATORS, headers=_admin(),
            data={"year_id": "7", "payload": payload},
        )

    assert resp.status_code == 201
    assert resp.json()["total"] == 1
    rows = mock.call_args.args[2]
    # El '' del <select> placeholder nunca llega a la BD (CheckConstraint).
    assert rows[0]["frequency"] is None
    assert rows[0]["planned_yellow"] == "70-85%"


def test_create_indicators_accepts_a_bare_list(client):
    with patch(f"{SVC}.bulk_create", return_value=[_fake_indicator()]):
        resp = client.post(
            INDICATORS, headers=_admin(),
            data={"year_id": "7", "payload": '[{"process_id": 3}]'},
        )
    assert resp.status_code == 201


def test_create_indicators_rejects_broken_json(client):
    resp = client.post(
        INDICATORS, headers=_admin(),
        data={"year_id": "7", "payload": "no soy json"},
    )
    assert resp.status_code == 400
    assert "payload" in resp.json()["error"]


def test_create_indicators_rejects_a_row_without_process(client):
    resp = client.post(
        INDICATORS, headers=_admin(),
        data={"year_id": "7", "payload": '[{"objective": "sin proceso"}]'},
    )
    assert resp.status_code == 422
    assert "process_id" in resp.json()["error"]


def test_create_indicators_rejects_two_files_for_the_same_row(client):
    """``document_url`` es una columna: dos evidencias para una fila es un
    error del cliente, no un 'gana el último'."""
    resp = client.post(
        INDICATORS, headers=_admin(),
        data={
            "year_id": "7",
            "payload": '[{"process_id": 3}, {"process_id": 3}]',
            "file_indexes": ["0", "0"],
        },
        files=[
            ("files", ("a.pdf", b"uno", "application/pdf")),
            ("files", ("b.pdf", b"dos", "application/pdf")),
        ],
    )
    assert resp.status_code == 400
    assert "repetido" in resp.json()["error"]


def test_create_indicators_rejects_file_index_out_of_range(client):
    resp = client.post(
        INDICATORS, headers=_admin(),
        data={
            "year_id": "7",
            "payload": '[{"process_id": 3}]',
            "file_indexes": ["5"],
        },
        files=[("files", ("a.pdf", b"uno", "application/pdf"))],
    )
    assert resp.status_code == 400


def test_patch_only_forwards_the_fields_actually_sent(client):
    """El legacy leía 13 campos con ``getlist('x[]')[0]``: uno faltante mataba
    el request. Aquí lo ausente simplemente no se toca."""
    with patch(f"{SVC}.update_indicator", return_value=_fake_indicator()) as mock, \
         patch(f"{SVC}.get_indicator", return_value=_fake_indicator()):
        resp = client.patch(
            f"{INDICATORS}/11", headers=_admin(),
            data={"payload": '{"objective": "editado"}'},
        )

    assert resp.status_code == 200
    data = mock.call_args.args[2]
    assert data == {"objective": "editado"}


@pytest.mark.parametrize("sent", ['{"responsible": ""}', '{"responsible": null}'])
def test_patch_can_clear_a_field(client, sent):
    """"Borralo" (clave presente y vacia) tiene que distinguirse de "no lo
    toques" (clave ausente): por eso los campos van en un JSON y no en campos
    de formulario sueltos - FastAPI colapsa un ``Form`` vacio a su default."""
    with patch(f"{SVC}.update_indicator", return_value=_fake_indicator()) as mock, \
         patch(f"{SVC}.get_indicator", return_value=_fake_indicator()):
        resp = client.patch(
            f"{INDICATORS}/11", headers=_admin(), data={"payload": sent},
        )

    assert resp.status_code == 200
    assert mock.call_args.args[2] == {"responsible": None}


def test_patch_rejects_an_invalid_frequency(client):
    resp = client.patch(
        f"{INDICATORS}/11", headers=_admin(),
        data={"payload": '{"frequency": "Quincenal"}'},
    )
    assert resp.status_code == 422


def test_patch_rejects_broken_json(client):
    resp = client.patch(
        f"{INDICATORS}/11", headers=_admin(), data={"payload": "no soy json"},
    )
    assert resp.status_code == 400


def test_patch_without_any_change_is_400(client):
    resp = client.patch(f"{INDICATORS}/11", headers=_admin(), data={"payload": "{}"})
    assert resp.status_code == 400


def test_patch_accepts_a_file_only_edit(client):
    """Reemplazar la evidencia sin tocar ningun campo es una edicion valida."""
    with patch(f"{SVC}.update_indicator", return_value=_fake_indicator()) as mock, \
         patch(f"{SVC}.get_indicator", return_value=_fake_indicator()):
        resp = client.patch(
            f"{INDICATORS}/11", headers=_admin(),
            files={"file": ("nueva.pdf", b"%PDF", "application/pdf")},
        )

    assert resp.status_code == 200
    assert mock.call_args.args[2] == {}
    assert mock.call_args.kwargs["upload"] is not None


def test_patch_missing_indicator_is_404(client):
    with patch(f"{SVC}.update_indicator", side_effect=LookupError("El indicador 11 no existe")):
        resp = client.patch(
            f"{INDICATORS}/11", headers=_admin(),
            data={"payload": '{"objective": "x"}'},
        )
    assert resp.status_code == 404


def test_patch_invalid_process_is_400(client):
    with patch(f"{SVC}.update_indicator", side_effect=ValueError("El proceso 9 no existe")):
        resp = client.patch(
            f"{INDICATORS}/11", headers=_admin(),
            data={"payload": '{"process_id": 9}'},
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "El proceso 9 no existe"


def test_delete_indicator_ok(client):
    with patch(f"{SVC}.delete_indicator") as mock:
        resp = client.delete(f"{INDICATORS}/11", headers=_admin())
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert mock.call_args.args[1] == 11


def test_download_returns_the_file(client, tmp_path):
    """Endpoint NUEVO: el legacy subía la evidencia y no la dejaba recuperar."""
    evidence = tmp_path / "evidencia.pdf"
    evidence.write_bytes(b"%PDF-1.4 fake")

    with patch(f"{SVC}.document_path", return_value=evidence):
        resp = client.get(f"{INDICATORS}/11/download", headers=_admin())

    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 fake"
    assert "evidencia.pdf" in resp.headers.get("content-disposition", "")


def test_download_without_document_is_404(client):
    with patch(f"{SVC}.document_path",
               side_effect=LookupError("El indicador 11 no tiene evidencia adjunta")):
        resp = client.get(f"{INDICATORS}/11/download", headers=_admin())
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Seguimiento
# ---------------------------------------------------------------------------

def test_upsert_tracking_ok(client):
    with patch(f"{SVC}.upsert_tracking", return_value=_fake_tracking()) as mock:
        resp = client.put(
            TRACKINGS, headers=_admin(),
            json={"indicator_id": 11, "period_index": 3,
                  "real_value": "92", "color": "verde"},
        )

    assert resp.status_code == 200
    assert resp.json()["data"] == {
        "id": 5, "indicator_id": 11, "period_index": 3,
        "real_value": "92", "color": "verde",
    }
    assert mock.call_args.args[1:3] == (11, 3)


def test_upsert_tracking_defaults_null_color_to_blanco(client):
    """El legacy mandaba ``data.get('color')`` sin fallback y ``color`` es
    ``NOT NULL``."""
    with patch(f"{SVC}.upsert_tracking",
               return_value=_fake_tracking(color="blanco")) as mock:
        resp = client.put(
            TRACKINGS, headers=_admin(),
            json={"indicator_id": 11, "period_index": 3, "color": None},
        )

    assert resp.status_code == 200
    assert mock.call_args.kwargs["color"] == "blanco"


def test_upsert_tracking_rejects_an_invalid_color(client):
    resp = client.put(
        TRACKINGS, headers=_admin(),
        json={"indicator_id": 11, "period_index": 3, "color": "morado"},
    )
    assert resp.status_code == 422


def test_upsert_tracking_rejects_a_negative_period(client):
    resp = client.put(
        TRACKINGS, headers=_admin(),
        json={"indicator_id": 11, "period_index": -1},
    )
    assert resp.status_code == 422


def test_upsert_tracking_out_of_range_period_is_400(client):
    with patch(f"{SVC}.upsert_tracking",
               side_effect=ValueError("Periodo 13 fuera de rango para la frecuencia Mensual (0-12)")):
        resp = client.put(
            TRACKINGS, headers=_admin(),
            json={"indicator_id": 11, "period_index": 13},
        )
    assert resp.status_code == 400
    assert "fuera de rango" in resp.json()["error"]


def test_upsert_tracking_unknown_indicator_is_404(client):
    with patch(f"{SVC}.upsert_tracking", side_effect=LookupError("El indicador 11 no existe")):
        resp = client.put(
            TRACKINGS, headers=_admin(),
            json={"indicator_id": 11, "period_index": 1},
        )
    assert resp.status_code == 404
