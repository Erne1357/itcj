"""Rutas del Formato B del alumno (fase 3, spec §5): formulario validado de tres
pasos, «Revisa y envía», observaciones tras un rechazo y vistas de solo lectura.

Cada «no» lleva su positivo de la MISMA ruta (regla de oro del arbol): una guarda
que dijera que no siempre, o unos fixtures rotos, saldrian en rojo.

El corte a T-soft se fija EXPLICITO (R7): la fase 3 se opera con el corte en 9 y
una prueba aparte demuestra que con el corte en 3 queda bloqueada.
"""
from __future__ import annotations

from datetime import date

import pytest

from itcj2.apps.titulatec.services.phase_service import PhaseService

PERMS = (
    "titulatec.format_b.page.fill",
    "titulatec.format_b.api.save",
    "titulatec.format_b.api.submit",
)
BASE = "/titulatec/student/formato-b"

PASO_1 = {"gender": "female", "age": "24", "mobile_phone": "6561234567",
          "postal_code": "32000", "neighborhood": "Centro", "street": "Calle Uno",
          "ext_number": "10"}


@pytest.fixture()
def corte_9(monkeypatch):
    monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: 9))


@pytest.fixture()
def escenario(db_session, seed_phase_defs, make_student, make_process, make_modality,
              make_format_b, make_program):
    """Alumno en fase 3 (por omision) con una modalidad que pide proyecto."""
    def _build(current_phase=3, fb_status=None, completo=True, **fb_extra):
        seed_phase_defs()
        modalidad = make_modality(name="Tesis de prueba")
        student = make_student(perm_codes=PERMS)
        proc = make_process(student, program=make_program("Ingenieria Ficticia B"),
                            current_phase=current_phase)
        fb = None
        if fb_status:
            datos = dict(
                first_name="ALUMNO", last_name="FICTICIO", gender="female", age=24,
                mobile_phone="6561234567", postal_code="32000", neighborhood="Centro",
                street="Calle Uno", ext_number="10", study_plan="ISIC-2010-224",
                admission_date=date(2018, 8, 1), graduation_date=date(2023, 6, 1),
                project_name="Proyecto de prueba suficientemente largo",
            ) if completo else {}
            datos.update(fb_extra)
            fb = make_format_b(proc, status=fb_status, modality=modalidad, **datos)
        return student, proc, modalidad, fb
    return _build


def _fb(db, process_id):
    from itcj2.apps.titulatec.models import FormatB
    db.expire_all()
    return db.query(FormatB).filter_by(process_id=process_id).first()


def _fase3(db, process_id):
    from itcj2.apps.titulatec.models import ProcessPhase
    db.expire_all()
    return (db.query(ProcessPhase)
            .filter_by(process_id=process_id, phase_number=3).one().status)


# ---------------------------------------------------------------------------
# Guardar un paso
# ---------------------------------------------------------------------------
class TestGuardarPaso:
    def test_paso_1_invalido_repinta_con_200_y_no_escribe(
        self, escenario, client_as, db_session, corte_9,
    ):
        student, proc, _m, _fb_ = escenario(fb_status="draft", completo=False)

        resp = client_as(student).post(f"{BASE}/step/1", data={**PASO_1, "age": "5"})

        assert resp.status_code == 200, resp.text[:300]
        assert "La edad debe ser un número entre 18 y 99" in resp.text
        assert "is-invalid" in resp.text
        assert "Revisa 1 campo" in resp.text
        assert 'value="5"' in resp.text, "se re-pinta lo que el alumno escribio"
        assert _fb(db_session, proc.id).age is None, "un paso invalido no escribe nada"

    def test_paso_1_valido_guarda_y_pasa_al_paso_2(
        self, escenario, client_as, db_session, corte_9,
    ):
        student, proc, _m, _fb_ = escenario(fb_status="draft", completo=False)

        resp = client_as(student).post(f"{BASE}/step/1", data=PASO_1)

        assert resp.status_code == 200, resp.text[:300]
        assert "is-invalid" not in resp.text
        assert 'name="study_plan"' in resp.text, "avanza al paso 2"
        assert _fb(db_session, proc.id).age == 24

    def test_paso_3_valido_muestra_la_revision_y_sigue_en_borrador(
        self, escenario, client_as, db_session, corte_9,
    ):
        student, proc, _m, _fb_ = escenario(fb_status="draft")

        resp = client_as(student).post(
            f"{BASE}/step/3", data={"project_name": "Un proyecto con nombre largo"})

        assert resp.status_code == 200, resp.text[:300]
        assert "Revisa y envía" in resp.text
        assert "Enviar Formato B" in resp.text
        assert _fb(db_session, proc.id).status == "draft", "el paso 3 ya no envia"
        assert _fase3(db_session, proc.id) != "in_review"

    def test_paso_con_formato_enviado_da_400_con_x_tt_error(
        self, escenario, client_as, db_session, corte_9,
    ):
        student, proc, _m, _fb_ = escenario(fb_status="submitted")

        resp = client_as(student).post(f"{BASE}/step/1", data=PASO_1)

        assert resp.status_code == 400, resp.text[:300]
        assert resp.headers.get("X-Tt-Error")
        assert _fb(db_session, proc.id).status == "submitted"

    def test_paso_fuera_de_rango_da_404(self, escenario, client_as, corte_9):
        student, _p, _m, _fb_ = escenario(fb_status="draft")
        assert client_as(student).post(f"{BASE}/step/4", data={}).status_code == 404

    def test_con_el_corte_en_3_el_paso_queda_bloqueado(
        self, escenario, client_as, db_session,
    ):
        student, proc, _m, _fb_ = escenario(fb_status="draft", completo=False)

        resp = client_as(student).post(f"{BASE}/step/1", data=PASO_1)

        assert resp.status_code == 400, resp.text[:300]
        assert resp.headers.get("X-Tt-Error") == PhaseService.HANDOFF_MSG
        assert _fb(db_session, proc.id).age is None


# ---------------------------------------------------------------------------
# Enviar
# ---------------------------------------------------------------------------
class TestEnviar:
    def test_envio_feliz_deja_submitted_y_pinta_solo_lectura(
        self, escenario, client_as, db_session, corte_9,
    ):
        student, proc, _m, _fb_ = escenario(fb_status="draft")

        resp = client_as(student).post(f"{BASE}/enviar")

        assert resp.status_code == 200, resp.text[:300]
        assert "Formato B enviado. Titulación lo revisa en orden de llegada." in resp.text
        assert "sinodales" not in resp.text
        assert _fb(db_session, proc.id).status == "submitted"
        assert _fase3(db_session, proc.id) == "in_review"

    def test_borrador_viejo_invalido_lleva_al_paso_del_error_con_200(
        self, escenario, client_as, db_session, corte_9,
    ):
        """RF3: el envio re-valida TODO; un borrador con el paso 1 vacio no entra a
        la cola, vuelve al paso 1 con los errores pintados."""
        student, proc, _m, _fb_ = escenario(fb_status="draft", age=None)

        resp = client_as(student).post(f"{BASE}/enviar")

        assert resp.status_code == 200, resp.text[:300]
        assert "La edad es obligatoria" in resp.text
        assert 'name="age"' in resp.text, "es el formulario del paso 1"
        assert _fb(db_session, proc.id).status == "draft"
        assert _fase3(db_session, proc.id) != "in_review"

    def test_reenvio_con_formato_enviado_da_400(
        self, escenario, client_as, db_session, corte_9,
    ):
        student, proc, _m, _fb_ = escenario(fb_status="submitted", submission_count=1)

        resp = client_as(student).post(f"{BASE}/enviar")

        assert resp.status_code == 400, resp.text[:300]
        assert resp.headers.get("X-Tt-Error")
        assert _fb(db_session, proc.id).submission_count == 1

    def test_con_el_corte_en_3_no_envia(self, escenario, client_as, db_session):
        student, proc, _m, _fb_ = escenario(fb_status="draft")

        resp = client_as(student).post(f"{BASE}/enviar")

        assert resp.status_code == 400, resp.text[:300]
        assert resp.headers.get("X-Tt-Error") == PhaseService.HANDOFF_MSG
        assert _fb(db_session, proc.id).status == "draft"

    def test_sin_el_permiso_de_enviar_da_403(
        self, db_session, seed_phase_defs, make_student, make_process, client_as, corte_9,
    ):
        seed_phase_defs()
        alumno = make_student(perm_codes=PERMS[:2])
        make_process(alumno, current_phase=3)

        resp = client_as(alumno).post(f"{BASE}/enviar", follow_redirects=False)

        assert resp.status_code in (302, 303, 401, 403), resp.status_code


# ---------------------------------------------------------------------------
# Revision
# ---------------------------------------------------------------------------
class TestRevision:
    def test_lista_los_tres_bloques_con_editar_y_la_casilla(
        self, escenario, client_as, corte_9,
    ):
        student, _p, _m, _fb_ = escenario(fb_status="draft")

        resp = client_as(student).get(f"{BASE}/revision")

        assert resp.status_code == 200, resp.text[:300]
        for rotulo in ("Personal", "Escolar", "Proyecto", "Confirmo que mis datos son correctos"):
            assert rotulo in resp.text
        assert f"{BASE}/step/1" in resp.text and f"{BASE}/step/3" in resp.text
        assert "Ingenieria Ficticia B" in resp.text, "la carrera sale en palabras"
        assert "agosto de 2018" in resp.text, "los meses salen en palabras"

    def test_avisa_los_campos_observados_que_no_cambio(
        self, escenario, client_as, db_session, corte_9,
    ):
        student, proc, _m, fb = escenario(fb_status="rejected")
        fb.review_observations = {
            "general": "Revisa tu domicilio", "at": "2026-10-21T10:00:00",
            "fields": {"postal_code": {"note": "No coincide", "value": "32000"},
                       "street": {"note": "Falta numero", "value": "Otra calle"}},
        }
        db_session.flush()

        resp = client_as(student).get(f"{BASE}/revision")

        assert resp.status_code == 200, resp.text[:300]
        assert "No cambiaste:" in resp.text
        assert "Código postal" in resp.text
        # La calle SI cambio (Otra calle -> Calle Uno): no entra en el aviso.
        aviso = resp.text.split("No cambiaste:")[1].split("</")[0]
        assert "Calle" not in aviso

    def test_con_formato_enviado_cae_a_solo_lectura(self, escenario, client_as, corte_9):
        student, _p, _m, _fb_ = escenario(fb_status="submitted")

        resp = client_as(student).get(f"{BASE}/revision")

        assert resp.status_code == 200
        assert "Confirmo que mis datos son correctos" not in resp.text


# ---------------------------------------------------------------------------
# Pagina principal: modos
# ---------------------------------------------------------------------------
class TestPagina:
    def test_borrador_se_abre_en_el_paso_1_con_nombre_de_solo_lectura(
        self, escenario, client_as, corte_9,
    ):
        student, _p, _m, _fb_ = escenario(fb_status="draft", completo=False)

        resp = client_as(student).get(BASE)

        assert resp.status_code == 200, resp.text[:300]
        assert 'name="age"' in resp.text
        assert "Tu nombre viene de tu registro" in resp.text
        assert 'name="first_name"' not in resp.text, "el nombre ya no se edita"

    def test_paso_2_ofrece_el_tipo_de_titulacion_y_carrera_de_solo_lectura(
        self, escenario, client_as, corte_9,
    ):
        student, _p, modalidad, _fb_ = escenario(fb_status="draft")

        resp = client_as(student).get(f"{BASE}/step/2")

        assert resp.status_code == 200, resp.text[:300]
        assert "Tipo de titulación" in resp.text
        assert f'value="{modalidad.id}"' in resp.text
        assert 'name="program_id"' not in resp.text
        assert "Ingenieria Ficticia B" in resp.text

    def test_enviado_se_abre_en_solo_lectura(self, escenario, client_as, corte_9):
        student, _p, _m, _fb_ = escenario(fb_status="submitted", submission_count=1)

        resp = client_as(student).get(BASE)

        assert resp.status_code == 200, resp.text[:300]
        assert "Titulación lo revisa en orden de llegada" in resp.text
        assert "<form" not in resp.text, "sin formularios en solo lectura"

    def test_aprobado_se_sirve_aunque_la_fase_ya_sea_la_4(
        self, escenario, client_as, db_session, corte_9,
    ):
        student, _p, _m, _fb_ = escenario(current_phase=4, fb_status="approved")

        resp = client_as(student).get(BASE, follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert "Aprobado" in resp.text
        assert "<form" not in resp.text

    def test_aprobado_no_abre_ninguna_accion(self, escenario, client_as, db_session, corte_9):
        """Excepcion solo de lectura: toda accion sigue bloqueada."""
        student, proc, _m, _fb_ = escenario(current_phase=4, fb_status="approved")

        paso = client_as(student).post(f"{BASE}/step/1", data=PASO_1)
        envio = client_as(student).post(f"{BASE}/enviar")

        assert paso.status_code == 400 and envio.status_code == 400
        assert _fb(db_session, proc.id).status == "approved"

    def test_borrador_desde_la_fase_2_redirige_302(
        self, escenario, client_as, db_session, corte_9,
    ):
        student, proc, _m, _fb_ = escenario(current_phase=2)

        resp = client_as(student).get(BASE, follow_redirects=False)

        assert resp.status_code == 302, resp.text[:300]
        assert resp.headers["location"] == "/titulatec/student/dashboard?fase=3"
        assert _fb(db_session, proc.id) is None, "un GET fuera de fase no crea el Formato B"

    def test_con_el_corte_en_3_la_pagina_redirige(self, escenario, client_as):
        student, _p, _m, _fb_ = escenario(fb_status="draft")

        resp = client_as(student).get(BASE, follow_redirects=False)

        assert resp.status_code == 302, resp.text[:300]

    def test_rechazado_muestra_banner_y_campos_observados(
        self, escenario, client_as, db_session, corte_9,
    ):
        from datetime import datetime
        student, proc, _m, fb = escenario(fb_status="rejected")
        fb.rejection_reason = "Revisa tu domicilio"
        fb.reviewed_at = datetime(2026, 10, 20, 9, 30)
        fb.review_observations = {
            "general": "Revisa tu domicilio", "at": "2026-10-20T09:30:00",
            "fields": {"postal_code": {"note": "No coincide con tu comprobante",
                                       "value": "32000"},
                       "street": {"note": "Falta la calle completa", "value": "Calle"}},
        }
        db_session.flush()

        pagina = client_as(student).get(BASE)
        paso = client_as(student).get(f"{BASE}/step/1")

        assert pagina.status_code == 200 and paso.status_code == 200
        assert "Revisa tu domicilio" in pagina.text
        assert "20 de octubre" in pagina.text
        assert f"{BASE}/step/1" in pagina.text, "cada campo observado enlaza a su paso"
        # Sin cambio: nota ambar. Cambiado (Calle -> Calle Uno): «Corregido ✓».
        assert "Observación de Titulación: No coincide con tu comprobante" in paso.text
        assert "Corregido ✓" in paso.text
        assert "is-observed" in paso.text

    def test_sin_proceso_muestra_el_estado_vacio(
        self, seed_phase_defs, make_student, client_as, corte_9,
    ):
        seed_phase_defs()
        alumno = make_student(perm_codes=PERMS)

        resp = client_as(alumno).get(BASE, follow_redirects=False)

        assert resp.status_code == 200
        assert "Sin proceso activo" in resp.text
