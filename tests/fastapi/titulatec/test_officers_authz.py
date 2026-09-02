"""Encargados: quien puede tocar que puesto del organigrama COMPARTIDO.

BLOQUEADOR reproducido en el contenedor antes de escribir estos tests. La
pestana Encargados (`pages/officers.py`, 4 rutas) escribe sobre `core_positions`
y `core_user_positions`, las tablas del organigrama que comparten helpdesk,
maint, agendatec y adhoc. Con solo `titulatec.officers.api.manage` se podia:

  * asignar a CUALQUIER usuario del instituto a un puesto de encargado
    (`officer_service.py:75`: `allowed = department_user_ids(...) | set(user_ids)`
    -> `bad` es vacio por algebra de conjuntos; el `raise` de :78 es inalcanzable
    y el `except ValueError` de `officers.py:93` nunca se disparaba por esa via);
  * asignarse a si mismo a cualquier `position_id` del instituto via
    `POST /admin/officers/{id}` -> hereda los `PositionAppRole` de ese puesto en
    CUALQUIER app (`officers.py:79-98` no miraba el departamento del puesto);
  * desactivar cualquier puesto del organigrama via
    `POST /admin/officers/{id}/deactivate` -> `positions_service.deactivate_position`
    pone `Position.is_active=False` y cierra TODAS las `UserPosition` activas con
    `end_date=hoy` (`positions_service.py:172-194`). El puesto del jefe de
    Mantenimiento entra en ese rango.

Correccion segun `docs/superpowers/specs/2026-09-01-titulatec-scope-carrera-design.md`
seccion 7.2 (dos conjuntos de aceptacion, asimetria deliberada):

  A - administrable: `Position` del depto del jefe, activo y CON rol en titulatec
      -> `update` (set_users + set_programs).
  B - destruible:    A interseccion `code LIKE se_officer_%` -> `deactivate`.
      El prefijo es la marca de propiedad: esta app solo destruye lo que creo.

REGLA DE ORO (heredada de la spec de scope): ninguna asercion negativa va sola.
Cada "no se pudo" viene con el positivo del MISMO actor sobre la MISMA ruta.

Todo el organigrama de estas pruebas es sintetico y vive dentro del savepoint.
"""
from __future__ import annotations

import pytest

from tests.fastapi.titulatec.conftest import HEAD_PERMS, OFFICER_PERMS, ROLE_HEAD, ROLE_OFFICER

from itcj2.apps.titulatec.services.officer_service import OfficerService

ROLE_ASSIGNED = "titulatec_school_services"  # el que usa `officers.py:13`


def _url(position_id: int) -> str:
    return f"/titulatec/admin/officers/{position_id}"


def _deactivate_url(position_id: int) -> str:
    return f"/titulatec/admin/officers/{position_id}/deactivate"


def _ocupantes(db, position_id: int) -> set[int]:
    """user_id con `UserPosition` VIVA en el puesto (lo que la escalada crea)."""
    from itcj2.core.models.position import UserPosition
    rows = (db.query(UserPosition.user_id)
            .filter_by(position_id=position_id, is_active=True).all())
    return {r[0] for r in rows}


def _carreras(db, position_id: int) -> set[int]:
    from itcj2.core.models.position import ProgramPosition
    rows = db.query(ProgramPosition.program_id).filter_by(position_id=position_id).all()
    return {r[0] for r in rows}


@pytest.fixture()
def organigrama(make_department, make_position, make_user, make_role,
                bind_position_role, assign_position, titulatec_app):
    """Dos departamentos con puestos del organigrama compartido.

    D1 es el que la jefa gestiona: `get_user_primary_managed_department`
    solo reconoce puestos `head_%`/`subdirector_%`/`director` con departamento
    activo, de ahi el `code=f"head_{dept.code}"`.
    D2 es ajeno: ahi viven los puestos que el bloqueador dejaba tocar.
    """
    def _build():
        d1 = make_department(name="Servicios Escolares (ficticio)")
        d2 = make_department(name="Mantenimiento (ficticio)")
        rol_head = make_role(ROLE_HEAD, HEAD_PERMS)
        rol_officer = make_role(ROLE_OFFICER, OFFICER_PERMS)

        pos_head_d1 = make_position(code=f"head_{d1.code}",
                                    title="Jefatura ficticia D1", department=d1)
        bind_position_role(pos_head_d1, rol_head)
        jefa = make_user(first_name="JEFA", last_name="FICTICIA")
        assign_position(jefa, pos_head_d1)

        # Encargado legitimo: lo que crea `create_officer` (prefijo + rol titulatec).
        pos_off_d1 = make_position(code=f"se_officer_{d1.code}",
                                   title="Encargado ficticio D1", department=d1)
        bind_position_role(pos_off_d1, rol_officer)

        # Mismo prefijo y mismo rol, pero de OTRO departamento: aisla la
        # dimension "departamento" del conjunto A.
        pos_off_d2 = make_position(code=f"se_officer_{d2.code}",
                                   title="Encargado ficticio D2", department=d2)
        bind_position_role(pos_off_d2, rol_officer)

        # Puesto ajeno del organigrama: sin rol de titulatec y con ocupante. Es
        # el analogo del jefe de Mantenimiento del reporte.
        pos_head_d2 = make_position(code=f"head_{d2.code}",
                                    title="Jefatura ficticia D2", department=d2)
        jefe_d2 = make_user(first_name="JEFE", last_name="AJENO")
        assign_position(jefe_d2, pos_head_d2)

        # Del depto del jefe pero SIN rol en titulatec: aisla la tercera
        # dimension del conjunto A.
        pos_sinrol_d1 = make_position(code=f"se_officer_x_{d1.code}",
                                      title="Puesto sin rol titulatec", department=d1)

        # Personal asignable: un colega del propio departamento.
        pos_aux_d1 = make_position(code=f"aux_{d1.code}",
                                   title="Auxiliar ficticio D1", department=d1)
        colega_d1 = make_user(first_name="COLEGA", last_name="DEUNO")
        assign_position(colega_d1, pos_aux_d1)

        return {
            "d1": d1, "d2": d2,
            "jefa": jefa, "pos_head_d1": pos_head_d1,
            "pos_off_d1": pos_off_d1, "pos_off_d2": pos_off_d2,
            "pos_head_d2": pos_head_d2, "pos_sinrol_d1": pos_sinrol_d1,
            "colega_d1": colega_d1, "jefe_d2": jefe_d2,
        }

    return _build


# ---------------------------------------------------------------------------
# O1 / O4 en el service
# ---------------------------------------------------------------------------
class TestSetUsers:
    def test_rechaza_un_usuario_de_otro_departamento(self, db_session, organigrama):
        """El `| set(user_ids)` volvia inalcanzable el `raise` de `:78`."""
        org = organigrama()

        with pytest.raises(ValueError):
            OfficerService.set_users(db_session, org["pos_off_d1"].id,
                                     {org["jefe_d2"].id},
                                     department_id=org["d1"].id,
                                     assigned_role=ROLE_ASSIGNED)

        assert org["jefe_d2"].id not in _ocupantes(db_session, org["pos_off_d1"].id)

    def test_acepta_a_un_usuario_del_propio_departamento(self, db_session, organigrama):
        """Positivo del mismo metodo: la guarda no dice que no a todo."""
        org = organigrama()

        OfficerService.set_users(db_session, org["pos_off_d1"].id,
                                 {org["colega_d1"].id},
                                 department_id=org["d1"].id,
                                 assigned_role=ROLE_ASSIGNED)

        assert _ocupantes(db_session, org["pos_off_d1"].id) == {org["colega_d1"].id}

    def test_sin_departamento_no_asigna_a_nadie(self, db_session, organigrama):
        """O4: `department_id=None` degradaba a todo-permitido."""
        org = organigrama()

        with pytest.raises(ValueError):
            OfficerService.set_users(db_session, org["pos_off_d1"].id,
                                     {org["jefe_d2"].id},
                                     department_id=None,
                                     assigned_role=ROLE_ASSIGNED)

        assert _ocupantes(db_session, org["pos_off_d1"].id) == set()

    def test_sigue_desasignando_a_quien_ya_no_esta_en_el_departamento(
        self, db_session, organigrama,
    ):
        """Test de FIJACION (verde antes y despues).

        Las bajas salen de `current - set(user_ids)` y NO pasan por `allowed`
        (spec 7.3, "Nota importante sobre las bajas"). Quitar la union no puede
        dejar atrapado a un ocupante que ya no pertenece al departamento.
        """
        from itcj2.core.models.position import UserPosition

        org = organigrama()
        OfficerService.set_users(db_session, org["pos_off_d1"].id,
                                 {org["colega_d1"].id},
                                 department_id=org["d1"].id,
                                 assigned_role=ROLE_ASSIGNED)
        # El colega se va del departamento: se le cierra su otra adscripcion.
        (db_session.query(UserPosition)
         .filter_by(user_id=org["colega_d1"].id, is_active=True)
         .filter(UserPosition.position_id != org["pos_off_d1"].id)
         .update({"is_active": False}, synchronize_session=False))
        db_session.flush()

        OfficerService.set_users(db_session, org["pos_off_d1"].id, set(),
                                 department_id=org["d1"].id,
                                 assigned_role=ROLE_ASSIGNED)

        assert _ocupantes(db_session, org["pos_off_d1"].id) == set()


# ---------------------------------------------------------------------------
# O1 / O2 / O4 en la ruta de edicion
# ---------------------------------------------------------------------------
class TestRutaUpdate:
    def test_no_toca_un_puesto_de_otro_departamento(
        self, client_as, db_session, organigrama,
    ):
        """La escalada del reporte: la jefa se asigna a un puesto ajeno.

        Ocupar un `Position` arrastra sus `PositionAppRole` en CUALQUIER app; el
        id crudo del path llegaba a `set_users` sin pasar por ningun filtro.
        """
        org = organigrama()

        resp = client_as(org["jefa"]).post(
            _url(org["pos_off_d2"].id), data={"user_ids": [str(org["jefa"].id)]})

        assert resp.status_code == 404, resp.text[:300]
        assert _ocupantes(db_session, org["pos_off_d2"].id) == set()

    def test_no_toca_un_puesto_sin_rol_de_titulatec(
        self, client_as, db_session, organigrama,
    ):
        """Conjunto A exige rol en titulatec, aunque el depto y el prefijo cuadren."""
        org = organigrama()

        resp = client_as(org["jefa"]).post(
            _url(org["pos_sinrol_d1"].id), data={"user_ids": [str(org["colega_d1"].id)]})

        assert resp.status_code == 404, resp.text[:300]
        assert _ocupantes(db_session, org["pos_sinrol_d1"].id) == set()

    def test_un_position_id_inexistente_devuelve_404(self, client_as, organigrama):
        """Hoy revienta como 400 desde dentro de `positions_service`."""
        org = organigrama()

        resp = client_as(org["jefa"]).post(
            _url(999_999_999), data={"user_ids": [str(org["colega_d1"].id)]})

        assert resp.status_code == 404, resp.text[:300]

    def test_no_asigna_a_un_usuario_de_otro_departamento(
        self, client_as, db_session, organigrama,
    ):
        """O1 visto desde la ruta: 400 por el canal de error de la app."""
        org = organigrama()

        resp = client_as(org["jefa"]).post(
            _url(org["pos_off_d1"].id), data={"user_ids": [str(org["jefe_d2"].id)]})

        assert resp.status_code == 400, resp.text[:300]
        assert resp.headers.get("X-Tt-Error"), "el error viaja por el canal de la app"
        assert _ocupantes(db_session, org["pos_off_d1"].id) == set()

    def test_sin_departamento_gestionado_no_muta(
        self, client_as, db_session, organigrama, make_head,
    ):
        """O4: `_managed_department_id` -> None seguia adelante igual."""
        org = organigrama()
        sin_depto = make_head()  # puesto sin departamento: no gestiona nada

        resp = client_as(sin_depto).post(
            _url(org["pos_off_d1"].id), data={"user_ids": [str(sin_depto.id)]})

        assert resp.status_code == 400, resp.text[:300]
        assert _ocupantes(db_session, org["pos_off_d1"].id) == set()

    def test_edita_su_propio_encargado(
        self, client_as, db_session, organigrama, make_program,
    ):
        """Positivo de la MISMA ruta: usuarios y carreras sincronizados."""
        org = organigrama()
        prog = make_program("Ingenieria Ficticia A")

        resp = client_as(org["jefa"]).post(
            _url(org["pos_off_d1"].id),
            data={"user_ids": [str(org["colega_d1"].id)],
                  "program_ids": [str(prog.id)]})

        assert resp.status_code == 200, resp.text[:300]
        assert _ocupantes(db_session, org["pos_off_d1"].id) == {org["colega_d1"].id}
        assert _carreras(db_session, org["pos_off_d1"].id) == {prog.id}


# ---------------------------------------------------------------------------
# O3 / O4 en la ruta de baja
# ---------------------------------------------------------------------------
class TestRutaDeactivate:
    def test_no_desactiva_un_puesto_ajeno_del_organigrama(
        self, client_as, db_session, organigrama,
    ):
        """El caso del reporte: tumbar la jefatura de otro departamento.

        `deactivate_position` no solo apaga el `Position`: cierra todas sus
        `UserPosition` activas, asi que el ocupante pierde el puesto en todas
        las apps que ese puesto le concedia.
        """
        org = organigrama()
        victima = org["pos_head_d2"]

        resp = client_as(org["jefa"]).post(_deactivate_url(victima.id))

        assert resp.status_code == 404, resp.text[:300]
        db_session.refresh(victima)
        assert victima.is_active is True, "un puesto ajeno no se apaga desde titulatec"
        assert _ocupantes(db_session, victima.id) == {org["jefe_d2"].id}

    def test_no_desactiva_un_puesto_propio_sin_el_prefijo(
        self, client_as, db_session, organigrama,
    ):
        """Conjunto B: el prefijo `se_officer_` es la marca de propiedad.

        Sin el, la jefa podia apagar su propia jefatura (y con ella el acceso
        que ese puesto concede en las demas apps).
        """
        org = organigrama()
        victima = org["pos_head_d1"]

        resp = client_as(org["jefa"]).post(_deactivate_url(victima.id))

        assert resp.status_code == 404, resp.text[:300]
        db_session.refresh(victima)
        assert victima.is_active is True
        assert _ocupantes(db_session, victima.id) == {org["jefa"].id}

    def test_no_desactiva_un_encargado_de_otro_departamento(
        self, client_as, db_session, organigrama,
    ):
        """Prefijo correcto pero departamento ajeno: sigue fuera del conjunto B."""
        org = organigrama()
        victima = org["pos_off_d2"]

        resp = client_as(org["jefa"]).post(_deactivate_url(victima.id))

        assert resp.status_code == 404, resp.text[:300]
        db_session.refresh(victima)
        assert victima.is_active is True

    def test_sin_departamento_gestionado_no_desactiva(
        self, client_as, db_session, organigrama, make_head,
    ):
        org = organigrama()
        sin_depto = make_head()
        victima = org["pos_off_d1"]

        resp = client_as(sin_depto).post(_deactivate_url(victima.id))

        assert resp.status_code == 400, resp.text[:300]
        db_session.refresh(victima)
        assert victima.is_active is True

    def test_desactiva_su_propio_encargado(self, client_as, db_session, organigrama):
        """Positivo de la MISMA ruta: lo que esta app creo si se puede dar de baja."""
        org = organigrama()
        propio = org["pos_off_d1"]

        resp = client_as(org["jefa"]).post(_deactivate_url(propio.id))

        assert resp.status_code == 200, resp.text[:300]
        db_session.refresh(propio)
        assert propio.is_active is False
