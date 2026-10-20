"""`GET /itcj/login?next=` — el destino tras autenticarse, sin abrir un redirect.

Por qué existe este archivo
---------------------------
`/itcj/login` es la única página de login de las SIETE apps. Antes de este
trabajo no aceptaba `next` en absoluto (grep de `next=` en `itcj2/`: cero
resultados), así que un anónimo que iniciaba sesión a media encuesta de
egresados caía en `/itcj/m/` y perdía lo capturado.

Añadir el parámetro sin validarlo convertiría esa página en un open redirect
sobre el dominio institucional. Por eso la mitad de las pruebas de aquí son
negativas y cubren las DOS ramas: la anónima (el valor viaja al template) y la
de "ya autenticado" (el valor va al `Location`). Validar solo una deja el
agujero abierto para quien visite la liga con sesión.

Harness
-------
`client` es local a este módulo porque `tests/fastapi/core/conftest.py` no lo
trae; es copia literal de `tests/fastapi/titulatec/conftest.py:191-202` — ata la
sesión del test por AMBOS caminos (la dependencia `get_db` del gate y el
`SessionLocal()` que cualquier handler abra por su cuenta). Anónimo siempre con
`follow_redirects=False`: seguir un 302 al login devuelve 200 y la prueba pasaría
por la razón equivocada.
"""
from unittest.mock import patch

import pytest

from itcj2.database import get_db
from tests.conftest import make_jwt


@pytest.fixture()
def client(app_client, db_session, patched_session_local):
    """TestClient con la sesión del test atada por gate y por cuerpo."""
    def _override():
        yield db_session

    app_client.app.dependency_overrides[get_db] = _override
    yield app_client
    app_client.app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def cookie_admin():
    """Cookie de un usuario con sesión. Sin claim `sv`: el middleware
    (`itcj2/middleware.py:63`) se salta el chequeo de revocación y la prueba no
    depende de Redis ni de una fila real en `core_users`."""
    return {"Cookie": f"itcj_token={make_jwt(user_id=200, role='admin')}"}


# ---------------------------------------------------------------------------
# Rama anónima: el valor validado llega al formulario
# ---------------------------------------------------------------------------
def test_un_next_valido_llega_al_formulario(client):
    """La ruta relativa sobrevive y `auth.js` la puede leer del dataset."""
    client.cookies.clear()
    resp = client.get("/itcj/login?next=/titulatec/encuesta-egresados",
                      follow_redirects=False)

    assert resp.status_code == 200
    assert 'data-next="/titulatec/encuesta-egresados"' in resp.text, (
        "El destino validado debe viajar en el formulario; sin él auth.js no "
        "tiene a dónde volver y el alumno pierde lo que escribió."
    )


@pytest.mark.parametrize("malicioso", [
    "//evil.example",              # protocol-relative: el navegador SALE del sitio
    "https://evil.example",        # absoluta con esquema
    "/\\evil.example",             # backslash: varios navegadores lo tratan como //
    "http://enlinea.cdjuarez.tecnm.mx/itcj/dashboard",  # mismo host, pero absoluta
])
def test_un_next_fuera_del_sitio_se_descarta(client, malicioso):
    """Nada que pueda sacar al usuario del origen llega al HTML."""
    client.cookies.clear()
    resp = client.get("/itcj/login", params={"next": malicioso},
                      follow_redirects=False)

    assert resp.status_code == 200
    assert 'data-next=""' in resp.text, (
        f"`next={malicioso}` debio caer al valor vacio y no lo hizo. Con el "
        f"puesto, /itcj/login —la pagina de login de las 7 apps— es un open "
        f"redirect usable como fachada de phishing."
    )
    assert "evil.example" not in resp.text


def test_sin_next_el_anonimo_ve_el_login_igual_que_hoy(client):
    """Comportamiento previo intacto: 200 y el formulario, con `data-next` vacío."""
    client.cookies.clear()
    resp = client.get("/itcj/login", follow_redirects=False)

    assert resp.status_code == 200
    assert 'id="loginForm"' in resp.text
    assert 'data-next=""' in resp.text


# ---------------------------------------------------------------------------
# Rama "ya autenticado": el valor validado manda sobre role_home()
# ---------------------------------------------------------------------------
def test_con_sesion_un_next_valido_gana_a_role_home(client, cookie_admin):
    """El que ya tiene sesión y abre la liga también aterriza en `next`."""
    with patch("itcj2.core.services.authz_service.user_roles_in_app",
               return_value={"admin"}):
        resp = client.get("/itcj/login?next=/titulatec/encuesta-egresados",
                          headers=cookie_admin, follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "/titulatec/encuesta-egresados"


def test_con_sesion_un_next_malicioso_cae_a_role_home(client, cookie_admin):
    """La rama temprana usa el MISMO validador: si no, basta abrir la liga con
    sesión para saltarse el control de la rama anónima."""
    with patch("itcj2.core.services.authz_service.user_roles_in_app",
               return_value={"admin"}):
        resp = client.get("/itcj/login", params={"next": "//evil.example"},
                          headers=cookie_admin, follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "/itcj/dashboard"


def test_con_sesion_y_sin_next_el_destino_es_el_de_siempre(client, cookie_admin):
    """`role_home(user_roles_in_app(...))`, byte a byte como antes del cambio."""
    with patch("itcj2.core.services.authz_service.user_roles_in_app",
               return_value={"student"}):
        resp = client.get("/itcj/login", headers=cookie_admin,
                          follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "/itcj/m/"


# ---------------------------------------------------------------------------
# El validador, directo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("crudo,esperado", [
    ("/titulatec/encuesta-egresados", "/titulatec/encuesta-egresados"),
    ("/titulatec/inscripcion?x=1#y", "/titulatec/inscripcion?x=1#y"),
    ("/", "/"),
    (None, None),
    ("", None),
    ("   ", None),
    ("//evil.example", None),
    ("/\\evil.example", None),
    ("https://evil.example", None),
    ("javascript:alert(1)", None),
    ("titulatec/inscripcion", None),          # relativa sin barra inicial
    ("/ok\r\nSet-Cookie: a=b", None),         # CRLF: inyección en el Location
    pytest.param("/" + "a" * 512, None, id="mas-de-512-chars"),  # excede _MAX_NEXT_LENGTH
])
def test_safe_next(crudo, esperado):
    from itcj2.core.pages.auth import safe_next
    assert safe_next(crudo) == esperado
