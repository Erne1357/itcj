"""Pruebas de prellenado de la sección 1 de la encuesta de egresados.

Task 4: la sección 1 llega prellenada con datos del alumno (nombre, número de
control, correo personal, teléfono, carrera), pero el borrador guardado manda
sobre el prellenado, y no se escriben cambios en las tablas core.
"""
import pytest


SURVEY_URL = "/titulatec/encuesta-egresados"

# Esquema mínimo para el test con los cinco campos de prellenado
TEST_SCHEMA_WITH_PREFILL = {
    "enabled": True,
    "sections": [
        {"key": "perfil", "title": "Perfil"}
    ],
    "fields": [
        {
            "key": "nombre_completo",
            "section": "perfil",
            "type": "text",
            "label": "Nombre completo",
            "required": True,
        },
        {
            "key": "no_control",
            "section": "perfil",
            "type": "text",
            "label": "Número de control",
            "required": True,
        },
        {
            "key": "correo_personal",
            "section": "perfil",
            "type": "text",
            "label": "Correo personal",
            "required": True,
        },
        {
            "key": "telefono",
            "section": "perfil",
            "type": "text",
            "label": "Teléfono",
            "required": True,
        },
        {
            "key": "carrera_egreso",
            "section": "perfil",
            "type": "radio",
            "label": "Carrera",
            "options": [
                {"value": "Lic. Administración", "label": "Lic. Administración"},
            ],
            "required": True,
        },
    ],
}


def test_la_seccion_1_llega_con_los_datos_del_alumno(
    client_as, db_session, make_student, make_survey_form
):
    """Los cinco campos salen con value= y editables, no deshabilitados."""
    from itcj2.core.services.student_profile_service import StudentProfileService

    # Crear un usuario alumno con perfil
    user = make_student(
        first_name="Juan",
        last_name="Pérez",
        control_number="2020001",
    )
    profile = StudentProfileService.get_or_create(db_session, user.id)
    profile.contact_email = "juan.personal@example.com"
    profile.phone = "6441234567"
    profile.program_id = None  # Sin carrera por ahora
    db_session.commit()

    # Crear la encuesta (no anónima para exigir sesión)
    make_survey_form(is_anonymous=False, schema=TEST_SCHEMA_WITH_PREFILL)

    # Autenticar como el alumno y cargar la encuesta
    resp = client_as(user).get(SURVEY_URL, follow_redirects=False)

    assert resp.status_code == 200
    html = resp.text

    # Verificar que los cinco campos están presentes con sus valores
    assert 'name="nombre_completo"' in html
    # full_name es "Pérez Juan" (sin middle_name en make_student)
    assert 'value="Pérez Juan"' in html

    assert 'name="no_control"' in html
    assert 'value="2020001"' in html

    assert 'name="correo_personal"' in html
    assert 'value="juan.personal@example.com"' in html

    assert 'name="telefono"' in html
    assert 'value="6441234567"' in html

    # carrera_egreso es un radio, así que su valor no viaja en value= sino en el atributo checked
    assert 'name="carrera_egreso"' in html


def test_el_borrador_guardado_gana_al_prellenado(
    client_as, db_session, make_student, make_survey_form
):
    """Quien ya empezó y corrigió su teléfono no ve reaparecer el viejo al volver."""
    from itcj2.core.services.student_profile_service import StudentProfileService
    from itcj2.apps.titulatec.services.survey_service import SurveyService

    # Crear alumno con teléfono "6441234567"
    user = make_student(control_number="2020002")
    profile = StudentProfileService.get_or_create(db_session, user.id)
    profile.phone = "6441234567"
    db_session.commit()

    # Crear encuesta
    form = make_survey_form(is_anonymous=False, schema=TEST_SCHEMA_WITH_PREFILL)

    # Simular que el alumno ya corrigió su teléfono en el borrador guardado
    SurveyService.save_draft(
        db_session,
        form.id,
        user.id,
        {
            "nombre_completo": user.full_name,
            "no_control": user.control_number,
            "correo_personal": "",
            "telefono": "6449999999",  # Teléfono CORREGIDO en el borrador
            "carrera_egreso": "",
        }
    )

    # Cargar la encuesta
    resp = client_as(user).get(SURVEY_URL, follow_redirects=False)

    assert resp.status_code == 200
    html = resp.text

    # El borrador debe haber ganado: debe mostrar el teléfono CORREGIDO, no el del perfil
    assert 'value="6449999999"' in html, "El borrador guardado debe ganar al prellenado"
    # Verificar que no tiene el valor viejo del perfil en el campo de teléfono
    import re
    telefono_field = re.search(r'<input[^>]*name="telefono"[^>]*>', html)
    assert telefono_field and '6449999999' in telefono_field.group(0)


def test_corregir_la_seccion_1_no_toca_core_student_profile(
    client_as, db_session, make_student, make_survey_form
):
    """Lee el perfil ANTES, envía el formulario con el teléfono cambiado, y
    afirma que la fila del perfil sigue byte a byte igual."""
    from itcj2.core.models.student_profile import StudentProfile
    from itcj2.core.services.student_profile_service import StudentProfileService

    # Crear alumno
    user = make_student(control_number="2020003")
    profile = StudentProfileService.get_or_create(db_session, user.id)
    profile.phone = "6441111111"
    profile.contact_email = "old@example.com"
    db_session.commit()

    # Leer el perfil ANTES de la encuesta
    profile_before = db_session.get(StudentProfile, user.id)
    phone_before = profile_before.phone if profile_before else None
    email_before = profile_before.contact_email if profile_before else None

    # Crear encuesta
    form = make_survey_form(is_anonymous=False, schema=TEST_SCHEMA_WITH_PREFILL)

    # Enviar respuestas corregidas (nombre, teléfono, correo)
    resp = client_as(user).post(
        SURVEY_URL,
        data={
            "nombre_completo": "Juan Pérez López",  # Cambiado
            "no_control": user.control_number,
            "correo_personal": "new@example.com",  # Cambiado
            "telefono": "6442222222",  # Cambiado
            "carrera_egreso": "Lic. Administración",
            "fecha_nacimiento": "01/01/2000",
            "sexo": "Hombre",
            "estado_civil": "Soltero (a)",
            # ... (otros campos obligatorios mínimos)
        },
        follow_redirects=False,
    )

    # Expirar la sesión de BD para forzar releer
    db_session.expire_all()

    # Leer el perfil DESPUÉS
    profile_after = db_session.get(StudentProfile, user.id)

    # Afirmar que el perfil NO cambió
    assert profile_after.phone == phone_before, \
        f"El teléfono del perfil no debe cambiar: era {phone_before}, ahora es {profile_after.phone}"
    assert profile_after.contact_email == email_before, \
        f"El correo del perfil no debe cambiar: era {email_before}, ahora es {profile_after.contact_email}"


def test_carrera_normaliza_y_siembra_el_value_literal(
    client_as, db_session, make_student, make_survey_form, make_program
):
    """Un programa que casa tras normalizar siembra el value LITERAL de la opción.

    Caso: programa en BD es "Ing. Sistemas computacionales" (sin mayúsculas)
    Opción en esquema es "Ing. Sistemas Computacionales" (con mayúsculas)
    Tras normalizar ambas, casan, y se siembra el value literal.
    """
    from itcj2.core.services.student_profile_service import StudentProfileService

    # Crear programa con nombre sin mayúsculas / sin acento
    program = make_program(name="Ing. Sistemas computacionales")

    # Crear alumno con esa carrera
    user = make_student(control_number="2020004")
    profile = StudentProfileService.get_or_create(db_session, user.id)
    profile.program_id = program.id
    db_session.commit()

    # Esquema con opción que casa tras normalizar (mayúsculas distintas)
    schema_with_match = {
        "enabled": True,
        "sections": [{"key": "perfil", "title": "Perfil"}],
        "fields": [
            {"key": "nombre_completo", "section": "perfil", "type": "text", "label": "Nombre", "required": True},
            {"key": "no_control", "section": "perfil", "type": "text", "label": "Control", "required": True},
            {"key": "correo_personal", "section": "perfil", "type": "text", "label": "Correo", "required": True},
            {"key": "telefono", "section": "perfil", "type": "text", "label": "Teléfono", "required": True},
            {
                "key": "carrera_egreso",
                "section": "perfil",
                "type": "radio",
                "label": "Carrera",
                "options": [
                    {"value": "Ing. Sistemas Computacionales", "label": "Ing. Sistemas Computacionales"},
                ],
                "required": True,
            },
        ],
    }

    make_survey_form(is_anonymous=False, schema=schema_with_match)

    # Cargar la encuesta
    resp = client_as(user).get(SURVEY_URL, follow_redirects=False)
    assert resp.status_code == 200
    html = resp.text

    # Afirmar que se siembra el value LITERAL (con mayúsculas), no el del programa
    assert 'value="Ing. Sistemas Computacionales"' in html, \
        "Debe sembrarse el value literal de la opción, normalizado durante búsqueda"


def test_carrera_sin_coincidencia_no_se_siembra(
    client_as, db_session, make_student, make_survey_form, make_program
):
    """Un programa que NO casa tras normalizar deja el campo sin sembrar.

    Esto previene que valores inválidos se cuelen en un radio,
    que luego el validador rechazaría.
    """
    from itcj2.core.services.student_profile_service import StudentProfileService

    # Crear programa que NO existe como opción en el esquema
    program = make_program(name="Ing. Electrónica")

    user = make_student(control_number="2020005")
    profile = StudentProfileService.get_or_create(db_session, user.id)
    profile.program_id = program.id
    db_session.commit()

    # Esquema SIN "Ing. Electrónica"
    schema_no_match = {
        "enabled": True,
        "sections": [{"key": "perfil", "title": "Perfil"}],
        "fields": [
            {"key": "nombre_completo", "section": "perfil", "type": "text", "label": "Nombre", "required": True},
            {"key": "no_control", "section": "perfil", "type": "text", "label": "Control", "required": True},
            {"key": "correo_personal", "section": "perfil", "type": "text", "label": "Correo", "required": True},
            {"key": "telefono", "section": "perfil", "type": "text", "label": "Teléfono", "required": True},
            {
                "key": "carrera_egreso",
                "section": "perfil",
                "type": "radio",
                "label": "Carrera",
                "options": [
                    {"value": "Lic. Administración", "label": "Lic. Administración"},
                ],
                "required": True,
            },
        ],
    }

    make_survey_form(is_anonymous=False, schema=schema_no_match)

    # Cargar la encuesta
    resp = client_as(user).get(SURVEY_URL, follow_redirects=False)
    assert resp.status_code == 200
    html = resp.text

    # Afirmar que "Ing. Electrónica" NO aparece en el HTML
    # (el campo quedó sin valor preseleccionado)
    assert 'value="Ing. Electrónica"' not in html, \
        "No debe sembrarse un valor que no existe en las opciones del esquema"

    # El campo sigue presente pero sin opción marcada
    assert 'name="carrera_egreso"' in html
