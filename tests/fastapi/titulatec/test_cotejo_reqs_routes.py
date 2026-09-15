"""Editor de requisitos de cotejo: las 4 rutas y la pestana que des-huerfanan el parcial.

`partials/cohort/cohort_cotejo_reqs.html` existia desde el rediseno de Citas y
posteaba a TRES URLs que no existian. El permiso `titulatec.cohort.api.cotejo_reqs`
estaba sembrado (seeder 07) y no gateaba nada. Y ninguna plantilla lo incluia, asi
que aunque las rutas existieran el editor solo era alcanzable tecleando la URL.
Era una feature entera cableada a medias.

Contrato que fijan estos tests (lo dicta el parcial):
  * los CUATRO handlers devuelven el parcial COMPLETO con raiz `cotejo-reqs-body`,
    porque `hx-target` == la raiz y el swap es `outerHTML`;
  * el permiso de esas cuatro rutas es EXACTAMENTE `titulatec.cohort.api.cotejo_reqs`
    y nada mas — `require_page_app` evalua su lista como OR, asi que un
    `dashboard.*` colado ahi reabriria la puerta al encargado de carrera;
  * borrar un requisito que alguien ya cumplio se niega con 400 + X-Tt-Error;
  * la pestana `cotejo` de `/titulatec/admin/cohorts/{id}` pinta el editor y el
    resumen la enlaza — esa segunda mitad es la que caza el huerfano.
"""
from __future__ import annotations

import pytest

import itcj2.models  # noqa: F401

from urllib.parse import unquote

PERM = "titulatec.cohort.api.cotejo_reqs"
# Puerta de `cohort_detail` (`pages/admin.py:29`), que es OTRA lista: la pestana
# vive dentro de esa pagina, asi que sin este permiso no se puede ni pedir.
PAGE_PERM = "titulatec.cohort.page.list"


def _msg(resp) -> str:
    """El `X-Tt-Error` ya decodificado (el servidor lo percent-codifica)."""
    return unquote(resp.headers.get("X-Tt-Error", ""))


def _url(cohort_id, suffix=""):
    return f"/titulatec/admin/cohorts/{cohort_id}/cotejo-reqs{suffix}"


def _tab_url(cohort_id, tab):
    return f"/titulatec/admin/cohorts/{cohort_id}?tab={tab}"


def _row_html(html: str, req_id: int) -> str:
    """Aisla el `<form>` de UNA fila por su input `id="req-{req_id}"`.

    Sustring exacto: `req_id` termina en `"` en el HTML, asi que `req-1` nunca
    empata dentro de `req-12` (buscar el marcador completo entrecomillado).
    Sin esto, comprobar `disabled`/el boton de borrar por fila se vuelve un
    grep sobre el documento entero y una fila contamina la asercion de otra.
    """
    marker = f'id="req-{req_id}"'
    i = html.index(marker)
    start = html.rindex("<form", 0, i)
    end = html.index("</form>", i) + len("</form>")
    return html[start:end]


@pytest.fixture()
def escenario(db_session, make_head, make_officer, make_program, make_cohort):
    """La jefa CON el permiso, un encargado sin el, y una convocatoria vacia.

    La jefa lleva SOLO `PERM` a proposito: es la demostracion de que
    `titulatec.cohort.api.cotejo_reqs` basta por si solo para las cuatro rutas y
    de que nadie colo un segundo codigo en `_COTEJO_REQ_PERMS`. Por eso las
    pruebas de la pestana usan sus propias fixtures: `make_head` siempre escribe
    en `ROLE_HEAD` y `make_role` solo ANADE permisos (conftest.py:262-288), asi
    que mezclar ambas en una misma prueba le regalaria `cohort.page.list` a esta
    jefa y se perderia la demostracion.
    """
    programa = make_program(name="Ing. de Prueba")
    jefa = make_head(perm_codes=(PERM,))
    officer, _pos = make_officer([programa])
    return {"jefa": jefa, "officer": officer, "cohort": make_cohort()}


class TestLectura:
    def test_get_devuelve_el_parcial_completo(self, escenario, client_as):
        cid = escenario["cohort"].id

        resp = client_as(escenario["jefa"]).get(_url(cid), follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert 'id="cotejo-reqs-body"' in resp.text
        assert f'hx-post="{_url(cid)}"' in resp.text

    def test_muestra_los_inactivos(self, db_session, escenario, client_as):
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        cid = escenario["cohort"].id
        item = CotejoRequirementService.create(db_session, cid, label="Retirado",
                                               hint=None, icon=None)
        CotejoRequirementService.update(db_session, item.id, cid, is_active=False)

        resp = client_as(escenario["jefa"]).get(_url(cid), follow_redirects=False)

        assert "Retirado" in resp.text, (
            "el editor debe listar los inactivos: el parcial los pinta con "
            "opacity-50 y son la via soportada en vez de borrar")


class TestEscritura:
    def test_create_agrega_y_devuelve_el_parcial(self, db_session, escenario, client_as):
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        cid = escenario["cohort"].id

        resp = client_as(escenario["jefa"]).post(
            _url(cid),
            data={"icon": "book", "label": "No-adeudo de biblioteca",
                  "hint": "Constancia vigente", "is_required": "1"},
            follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert 'id="cotejo-reqs-body"' in resp.text
        filas = CotejoRequirementService.list(db_session, cid)
        assert [r.label for r in filas] == ["No-adeudo de biblioteca"]
        assert filas[0].icon == "book" and filas[0].is_required is True

    def test_create_sin_label_no_escribe(self, db_session, escenario, client_as):
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        cid = escenario["cohort"].id

        resp = client_as(escenario["jefa"]).post(_url(cid), data={"label": "   "},
                                                 follow_redirects=False)

        assert resp.status_code == 400
        assert "requisito" in _msg(resp).lower()
        assert CotejoRequirementService.list(db_session, cid) == []

    def test_update_renombra_y_desmarca_sin_order_index(self, db_session, escenario,
                                                        client_as):
        """El parcial NO tiene input de order_index: la ruta debe tolerarlo."""
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        cid = escenario["cohort"].id
        item = CotejoRequirementService.create(db_session, cid, label="Viejo",
                                               hint=None, icon=None)

        resp = client_as(escenario["jefa"]).post(
            _url(cid, f"/{item.id}/update"),
            data={"icon": "camera", "label": "Nuevo", "hint": "12 fotos",
                  "is_active": "1"},          # sin is_required -> False
            follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert 'id="cotejo-reqs-body"' in resp.text
        db_session.refresh(item)
        assert (item.label, item.icon, item.hint) == ("Nuevo", "camera", "12 fotos")
        assert item.is_required is False and item.is_active is True
        assert item.order_index == 0

    def test_delete_borra_si_nadie_lo_cumplio(self, db_session, escenario, client_as):
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        cid = escenario["cohort"].id
        item = CotejoRequirementService.create(db_session, cid, label="Sobra",
                                               hint=None, icon=None)

        resp = client_as(escenario["jefa"]).post(_url(cid, f"/{item.id}/delete"),
                                                 follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert CotejoRequirementService.list(db_session, cid) == []

    def test_delete_se_niega_si_ya_lo_cumplieron(self, db_session, escenario, client_as,
                                                 make_student, make_process):
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        from itcj2.apps.titulatec.services.requirement_service import RequirementService

        cohort = escenario["cohort"]
        item = CotejoRequirementService.create(db_session, cohort.id, label="Actas",
                                               hint=None, icon=None)
        process = make_process(make_student(), cohort=cohort, current_phase=2)
        RequirementService.fulfill(db_session, process.id, item.id,
                                   source="officer", commit=False)

        resp = client_as(escenario["jefa"]).post(
            _url(cohort.id, f"/{item.id}/delete"), follow_redirects=False)

        assert resp.status_code == 400, resp.text[:300]
        # La copia de usuario va ACENTUADA («desactívalo»), asi que la asercion
        # tiene que serlo tambien: "desactiv" NO es subcadena de "desactívalo".
        assert "1" in _msg(resp) and "desactívalo" in _msg(resp)
        assert [r.id for r in CotejoRequirementService.list(db_session, cohort.id)] == [item.id]

    def test_delete_se_niega_sobre_un_requisito_automatico(self, db_session, escenario,
                                                           client_as):
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        cohort = escenario["cohort"]
        CotejoRequirementService.seed_defaults(db_session, cohort.id, commit=False)
        encuesta = [r for r in CotejoRequirementService.list(db_session, cohort.id)
                    if r.auto_source == "graduate_survey"][0]

        resp = client_as(escenario["jefa"]).post(
            _url(cohort.id, f"/{encuesta.id}/delete"), follow_redirects=False)

        assert resp.status_code == 400, resp.text[:300]
        assert "sistema" in _msg(resp).lower()
        assert db_session.get(type(encuesta), encuesta.id) is not None


class TestCandadoAutomatico:
    """D9: el requisito automatico no puede volverse opcional ni inactivo
    desde el editor, ni por la ruta ni por el parcial que la sirve."""

    def test_update_sobre_el_automatico_sin_casillas_marcadas_sigue_true(
            self, db_session, escenario, client_as):
        """Checkboxes `disabled` -> el navegador NO los manda: la ruta/servicio
        deben sostener `True` igual, sin depender de que lleguen marcados."""
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        cohort = escenario["cohort"]
        CotejoRequirementService.seed_defaults(db_session, cohort.id, commit=False)
        encuesta = [r for r in CotejoRequirementService.list(db_session, cohort.id)
                    if r.auto_source == "graduate_survey"][0]

        resp = client_as(escenario["jefa"]).post(
            _url(cohort.id, f"/{encuesta.id}/update"),
            data={"icon": encuesta.icon, "label": encuesta.label,
                  "hint": encuesta.hint or ""},   # sin is_required ni is_active
            follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        db_session.refresh(encuesta)
        assert (encuesta.is_required, encuesta.is_active) == (True, True)

    def test_el_parcial_deshabilita_las_casillas_del_automatico_y_oculta_eliminar(
            self, db_session, escenario, client_as):
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        cohort = escenario["cohort"]
        CotejoRequirementService.seed_defaults(db_session, cohort.id, commit=False)
        encuesta = [r for r in CotejoRequirementService.list(db_session, cohort.id)
                    if r.auto_source == "graduate_survey"][0]
        normal = CotejoRequirementService.create(db_session, cohort.id, label="Normal",
                                                  hint=None, icon=None)

        resp = client_as(escenario["jefa"]).get(_url(cohort.id), follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        fila_encuesta = _row_html(resp.text, encuesta.id)
        assert "disabled" in fila_encuesta, (
            "las casillas Obligatorio/Activo del automatico deben salir disabled")
        assert _url(cohort.id, f"/{encuesta.id}/delete") not in fila_encuesta, (
            "el automatico no debe pintar boton Eliminar")
        assert "acredita el sistema" in fila_encuesta.lower(), (
            "falta la nota visible de que lo acredita el sistema")

        fila_normal = _row_html(resp.text, normal.id)
        assert "disabled" not in fila_normal, (
            "un requisito normal no debe salir con las casillas deshabilitadas")
        assert _url(cohort.id, f"/{normal.id}/delete") in fila_normal, (
            "un requisito normal si debe conservar el boton Eliminar")


class TestAutorizacion:
    @pytest.mark.parametrize("metodo,sufijo", [
        ("get", ""), ("post", ""), ("post", "/1/update"), ("post", "/1/delete"),
    ])
    def test_el_encargado_no_entra_y_la_jefa_si(self, escenario, client_as,
                                                metodo, sufijo):
        """El positivo va emparejado: un guard que rechace a todos no vale."""
        cid = escenario["cohort"].id
        ruta = _url(cid, sufijo)

        r_off = getattr(client_as(escenario["officer"]), metodo)(
            ruta, follow_redirects=False)
        r_jefa = getattr(client_as(escenario["jefa"]), metodo)(
            ruta, follow_redirects=False)

        assert r_off.status_code == 403, (
            f"{metodo.upper()} {ruta} devolvio {r_off.status_code} al encargado. "
            f"Si es 200, alguien colo un `dashboard.*` en la lista de permisos: "
            f"`require_page_app` la evalua como OR y basta uno para abrir.")
        assert r_jefa.status_code != 403, (
            f"{metodo.upper()} {ruta} dejo fuera a la jefatura ({r_jefa.status_code}).")


class TestPestana:
    """El editor tiene que ser ALCANZABLE, no solo existir (`_arbitration.md` A15)."""

    @pytest.fixture()
    def jefa_editora(self, make_head):
        """Puede ABRIR la convocatoria Y configurar sus requisitos.

        Son dos listas de permisos distintas: `_COHORT_PERMS` gatea la pagina y
        `_COTEJO_REQ_PERMS` el editor. Esta fixture NO se combina con `escenario`
        en la misma prueba (ver su docstring: `ROLE_HEAD` es compartido y
        `make_role` solo anade).
        """
        return make_head(perm_codes=(PAGE_PERM, PERM))

    @pytest.fixture()
    def jefa_mirona(self, make_head):
        """Abre la convocatoria pero NO configura requisitos."""
        return make_head(perm_codes=(PAGE_PERM,))

    def test_la_pestana_cotejo_pinta_el_editor(self, jefa_editora, make_cohort,
                                               client_as):
        cid = make_cohort().id

        resp = client_as(jefa_editora).get(_tab_url(cid, "cotejo"),
                                           follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert 'id="cotejo-reqs-body"' in resp.text, (
            "?tab=cotejo cayo de vuelta al resumen: falta la rama en la cadena "
            "`if/elif` de `cohort_detail` o el valor no esta en su lista blanca")
        assert f'hx-post="{_url(cid)}"' in resp.text

    def test_el_resumen_enlaza_la_pestana(self, jefa_editora, make_cohort, client_as):
        """La mitad que caza el huerfano: sin enlace el editor no existe."""
        cid = make_cohort().id

        resp = client_as(jefa_editora).get(_tab_url(cid, "resumen"),
                                           follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert f'href="{_tab_url(cid, "cotejo")}"' in resp.text, (
            "la barra de pestanas de cohort_detail.html:22 no ofrece 'cotejo': "
            "las rutas existirian y nadie llegaria a ellas")

    def test_sin_el_permiso_de_edicion_la_pestana_es_de_solo_lectura(
            self, jefa_mirona, make_cohort, client_as):
        """`_COTEJO_REQ_PERMS` NO se ensancha para que la pestana funcione."""
        cid = make_cohort().id

        resp = client_as(jefa_mirona).get(_tab_url(cid, "cotejo"),
                                          follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert 'id="cotejo-reqs-body"' in resp.text
        assert "Solo lectura" in resp.text
        assert f'hx-post="{_url(cid)}"' not in resp.text, (
            "sin `titulatec.cohort.api.cotejo_reqs` el parcial no debe emitir "
            "ningun formulario: `can_edit_reqs` es False")
