"""Las Convocatorias son de la JEFATURA de Servicios Escolares, no del encargado.

Por qué existe este archivo
---------------------------
Un encargado de carrera entraba a `/admin/cohorts`, a su detalle y al asistente
de importación de CSV. Medido con su JWT contra la app real: 200 en las tres.
Podía crear convocatorias, editarlas e importar alumnos — y una convocatoria es
de todo el instituto, no de su carrera.

La causa no era solo el DML. `require_page_app` evalúa su lista de permisos como
**OR** (`itcj2/dependencies.py:131`), y `_COHORT_PERMS` incluía
`titulatec.dashboard.school_services`, que el rol operativo SÍ tiene: los
permisos `cohort.*` de esa lista eran decorativos. Revocarlos en el DML sin tocar
la constante no habría cambiado nada.

Por eso el actor de estas pruebas se construye con `OFFICER_PERMS` tal cual —que
ya trae `dashboard.school_services` y ningún `cohort.*`—: si alguien vuelve a
colar un `dashboard.*` en `_COHORT_PERMS`, estos tests se ponen rojos. Sin ese
detalle serían una tautología.

Regla de la casa: ninguna aserción negativa va sola. Cada 403 del encargado se
empareja con la jefa entrando al MISMO recurso, para que un guard que rechazara
a todo el mundo no pasara por bueno.
"""
import pytest

# Rutas de convocatorias, tal como las expone `pages/admin.py`.
# `{cid}` se sustituye por la convocatoria creada en el fixture.
COHORT_ROUTES = [
    "/titulatec/admin/cohorts",
    "/titulatec/admin/cohorts/{cid}",
    "/titulatec/admin/cohorts/{cid}/import",
    "/titulatec/admin/cohorts/{cid}/students",
]


@pytest.fixture
def escenario(make_head, make_officer, make_program, make_cohort):
    """Una convocatoria, la jefa, y un encargado acotado a una carrera."""
    programa = make_program(name="Ing. de Prueba")
    head = make_head()
    officer, _pos = make_officer([programa])
    cohort = make_cohort()
    return {"head": head, "officer": officer, "cohort": cohort, "program": programa}


@pytest.mark.parametrize("plantilla", COHORT_ROUTES)
def test_el_encargado_no_entra_y_la_jefa_si(escenario, client_as, plantilla):
    """El encargado recibe 403; la jefa entra al MISMO recurso."""
    ruta = plantilla.format(cid=escenario["cohort"].id)

    r_officer = client_as(escenario["officer"]).get(ruta, follow_redirects=False)
    r_head = client_as(escenario["head"]).get(ruta, follow_redirects=False)

    assert r_officer.status_code == 403, (
        f"{ruta} deberia estar cerrada al encargado de carrera y devolvio "
        f"{r_officer.status_code}. Si es 200, revisa que `_COHORT_PERMS` "
        f"(pages/admin.py) no haya vuelto a incluir un `dashboard.*`: la lista "
        f"es un OR, basta uno para abrir la puerta."
    )
    # El caso positivo evita acreditar un guard que rechace a todo el mundo.
    assert r_head.status_code != 403, (
        f"{ruta} dejo fuera a la JEFATURA ({r_head.status_code}); el recorte se "
        f"paso de rosca."
    )


def test_el_encargado_conserva_sus_pestanas(escenario, client_as):
    """Quitarle Convocatorias no puede quitarle su trabajo diario."""
    cli = client_as(escenario["officer"])
    for ruta in ("/titulatec/admin/",
                 "/titulatec/admin/processes",
                 "/titulatec/admin/documents",
                 "/titulatec/admin/appointments"):
        resp = cli.get(ruta, follow_redirects=False)
        assert resp.status_code != 403, (
            f"{ruta} se cerro al encargado ({resp.status_code}): es una de sus "
            f"pestanas de trabajo, no una de convocatorias."
        )


def test_convocatorias_no_aparece_en_el_sidebar_del_encargado(escenario, client_as):
    """El menu es data-driven por permiso: sin `cohort.page.list` no debe salir.

    Se comprueba sobre el HTML renderizado y no llamando a `admin_nav_items`
    directamente, por dos razones: es lo que el usuario ve —un enlace visible a
    una ruta que da 403 es el defecto que se quiere evitar— y ese helper abre su
    PROPIA sesion con `SessionLocal()`, asi que fuera del ciclo de peticion no
    veria a los actores creados dentro de la transaccion del test.
    """
    html_officer = client_as(escenario["officer"]).get("/titulatec/admin/").text
    html_head = client_as(escenario["head"]).get("/titulatec/admin/").text

    assert "/titulatec/admin/cohorts" not in html_officer, (
        "El sidebar del encargado sigue enlazando a Convocatorias, que le responde 403."
    )
    assert "/titulatec/admin/cohorts" in html_head, (
        "La jefatura perdio el enlace a Convocatorias en su sidebar."
    )
    # Lo suyo sigue estando: el recorte no puede llevarse por delante su trabajo.
    assert "/titulatec/admin/processes" in html_officer
    assert "/titulatec/admin/documents" in html_officer


def test_cohort_perms_no_admite_permisos_de_dashboard():
    """Blindaje del error concreto que causo el agujero.

    `require_page_app` evalua la lista como OR, asi que un `dashboard.*` dentro
    de `_COHORT_PERMS` vuelve decorativos a los `cohort.*` y reabre el acceso sin
    que ningun test de ruta tenga por que notarlo.
    """
    from itcj2.apps.titulatec.pages.admin import _COHORT_PERMS

    colados = [p for p in _COHORT_PERMS if ".dashboard." in p]
    assert not colados, (
        f"`_COHORT_PERMS` volvio a incluir {colados}. La lista es un OR "
        f"(itcj2/dependencies.py:131): cualquier rol con ese permiso entra a "
        f"Convocatorias aunque el DML no le conceda un solo `cohort.*`."
    )
    assert all(p.startswith("titulatec.cohort.") for p in _COHORT_PERMS)
