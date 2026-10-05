"""Interfaz de las respuestas importadas del Excel de Forms y de la
«constancia por recoger» (spec `2026-10-05-titulatec-import-encuesta-xlsx-
design.md` §4.4, D1/D3, R7/R9/R10).

- Encuestas (SE/GTV): fila importada sin usuario con control y nombre de la
  propia respuesta, píldora «Importada», detalle con valores `is_raw`
  marcados y «Otros datos importados» (R9), CSV con columna `importada`.
- Liberaciones (GTV): «Ver respuestas» en previas con `response_id`, píldora
  «Constancia por recoger» y «Marcar constancia entregada»
  (`POST /titulatec/admin/liberaciones/{review_id}/entregada`).
- Alumno: «Recoge tu constancia de liberación en Gestión Tecnológica y
  Vinculación.» solo mientras el papel esté pendiente.
- Correo de la previa (R10): la misma línea solo si `paper_pending`.

Nada aquí usa el Excel real (datos personales): las respuestas se siembran
directo en el modelo, con un formulario de código único.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import timedelta

import lxml.html
import pytest

ENC = "/titulatec/admin/encuestas"
LIB = "/titulatec/admin/liberaciones"
PICKUP = "Recoge tu constancia de liberación en Gestión Tecnológica y Vinculación."
RAW_NOTE = "Valor original, no coincide con las opciones actuales"

SURVEY_PERMS = (
    "titulatec.survey.page.list",
    "titulatec.survey.api.read",
    "titulatec.survey.api.export",
    "titulatec.process.api.read.all",
)
GTV_PERMS = (
    "titulatec.survey_review.page.list",
    "titulatec.survey_review.api.approve",
    "titulatec.survey_review.api.reject",
    "titulatec.survey.page.list",
)


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
def _texto(html: str) -> str:
    return " ".join(lxml.html.fromstring(html).text_content().split())


def _make_form(db_session):
    from itcj2.apps.titulatec.models import SurveyForm

    form = SurveyForm(
        code=f"egresados_imp_{uuid.uuid4().hex[:8]}",
        title="Encuesta de egresados (prueba de import)",
        description=None,
        schema={"enabled": True, "fields": [
            {"key": "nombre_completo", "type": "text", "label": "Nombre completo",
             "required": True},
            {"key": "situacion_laboral", "type": "radio",
             "label": "¿Cuál es tu situación laboral actual?", "required": True,
             "options": [{"value": "empleado", "label": "Trabajando"},
                         {"value": "buscando", "label": "Buscando empleo"}]},
            {"key": "comentarios", "type": "textarea", "label": "Comentarios",
             "required": False},
        ]},
        version=1, status="closed", is_anonymous=False,
    )
    db_session.add(form)
    db_session.flush()
    return form


def _imported(db_session, form, *, answers, control=None, user=None, raw=()):
    """Respuesta como la deja `SurveyImportService`: `identity_source='import'`,
    `import_ref`, y `SurveyAnswer.is_raw` en las llaves de `raw`."""
    from itcj2.apps.titulatec.models import SurveyAnswer, SurveyResponse

    resp = SurveyResponse(
        form_id=form.id, form_version=form.version,
        user_id=getattr(user, "id", None), identity_source="import",
        control_number=control, answers=answers,
        import_ref=f"msforms:{uuid.uuid4().hex[:6]}:2026-06-15T10:30:00",
    )
    db_session.add(resp)
    db_session.flush()
    for key, val in answers.items():
        db_session.add(SurveyAnswer(response_id=resp.id, field_key=key,
                                    field_type="text", value_text=str(val),
                                    is_raw=key in raw))
    db_session.flush()
    return resp


@pytest.fixture()
def make_gtv(make_user, make_role, grant_user_role):
    def _make(perm_codes=GTV_PERMS):
        user = make_user(first_name="GTV", last_name="IMPORT")
        grant_user_role(user, make_role("tt_test_gtv_imp", perm_codes))
        return user
    return _make


@pytest.fixture()
def previa(db_session, make_student, make_process):
    """Previa liberada por el import: `register_prior` con `response_id` y
    `paper_pending`. Devuelve `(review, process, response)`."""
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService
    from itcj2.core.utils.timezone import db_now

    def _make(control, *, paper=True, with_response=True, **proc_kw):
        proc = make_process(make_student(control_number=control), **proc_kw)
        response = None
        if with_response:
            response = _imported(db_session, _make_form(db_session), control=control,
                                 answers={"nombre_completo": "EGRESADA IMPORTADA"})
        review = SurveyReviewService.register_prior(
            db_session, proc, issued_on=db_now().date() - timedelta(days=10),
            response_id=response.id if response else None, paper_pending=paper)
        db_session.flush()
        return review, proc, response
    return _make


def _fila(html, review_id):
    marca = f'id="tt-rev-{review_id}"'
    assert marca in html, "falta la fila sembrada"
    return html.split(marca, 1)[1].split("</tr>", 1)[0]


# ---------------------------------------------------------------------------
# Encuestas: bandeja
# ---------------------------------------------------------------------------
def test_bandeja_muestra_control_nombre_y_pildora_de_una_importada_sin_usuario(
    client_as, db_session, make_head,
):
    head = make_head(perm_codes=SURVEY_PERMS)
    form = _make_form(db_session)
    _imported(db_session, form, control="99470001",
              answers={"nombre_completo": "PERSONA SIN CUENTA"})

    resp = client_as(head).get(f"{ENC}/body?form_id={form.id}")

    assert resp.status_code == 200, resp.text[:500]
    texto = _texto(resp.text)
    assert "99470001" in texto
    assert "PERSONA SIN CUENTA" in texto
    assert "Importada" in texto
    assert "Anónimo" not in texto


def test_bandeja_importada_con_usuario_usa_el_nombre_de_la_cuenta(
    client_as, db_session, make_head, make_user,
):
    head = make_head(perm_codes=SURVEY_PERMS)
    form = _make_form(db_session)
    user = make_user(first_name="CUENTA", last_name="REAL")
    _imported(db_session, form, control="99470002", user=user,
              answers={"nombre_completo": "NOMBRE DEL EXCEL"})

    texto = _texto(client_as(head).get(f"{ENC}/body?form_id={form.id}").text)

    assert user.full_name in texto
    assert "Importada" in texto


def test_bandeja_respuesta_no_importada_no_lleva_la_pildora(
    client_as, db_session, make_head,
):
    from itcj2.apps.titulatec.models import SurveyResponse

    head = make_head(perm_codes=SURVEY_PERMS)
    form = _make_form(db_session)
    db_session.add(SurveyResponse(form_id=form.id, form_version=1,
                                  identity_source="anonymous", answers={}))
    db_session.flush()

    texto = _texto(client_as(head).get(f"{ENC}/body?form_id={form.id}").text)

    assert "Anónimo" in texto
    assert "Importada" not in texto


# ---------------------------------------------------------------------------
# Encuestas: detalle
# ---------------------------------------------------------------------------
def test_detalle_marca_los_valores_raw_y_muestra_otros_datos_importados(
    client_as, db_session, make_head,
):
    head = make_head(perm_codes=SURVEY_PERMS)
    form = _make_form(db_session)
    r = _imported(db_session, form, control="99470003",
                  answers={"nombre_completo": "PERSONA RAW",
                           "situacion_laboral": "Desempleado (a)",
                           "comentarios": "Todo bien",
                           "extra_aspecto_no_trabajo": "Mucho 5"},
                  raw={"situacion_laboral"})

    resp = client_as(head).get(f"{ENC}/{r.id}")

    assert resp.status_code == 200, resp.text[:500]
    doc = lxml.html.fromstring(resp.text)
    texto = _texto(resp.text)
    assert "PERSONA RAW" in texto          # nombre desde la respuesta (sin usuario)
    assert "Importada" in texto
    # La marca sale UNA vez: solo en el valor raw.
    assert texto.count(RAW_NOTE) == 1
    raw_items = doc.xpath('//*[@data-tt-raw]')
    assert len(raw_items) == 1
    assert "Desempleado (a)" in " ".join(raw_items[0].text_content().split())
    # R9: la llave extra va en su propia sección, con etiqueta legible.
    extras = doc.xpath('//*[@id="tt-survey-extras"]')
    assert extras, "falta la sección «Otros datos importados»"
    extras_txt = " ".join(extras[0].text_content().split())
    assert "Otros datos importados" in extras_txt
    assert "Mucho 5" in extras_txt
    assert "No trabajo" in extras_txt
    assert "extra_aspecto_no_trabajo" not in texto


def test_detalle_sin_extras_ni_raw_no_pinta_las_marcas(client_as, db_session, make_head):
    head = make_head(perm_codes=SURVEY_PERMS)
    form = _make_form(db_session)
    r = _imported(db_session, form, control="99470004",
                  answers={"nombre_completo": "PERSONA LIMPIA",
                           "situacion_laboral": "empleado"})

    texto = _texto(client_as(head).get(f"{ENC}/{r.id}").text)

    assert RAW_NOTE not in texto
    assert "Otros datos importados" not in texto


# ---------------------------------------------------------------------------
# Encuestas: CSV
# ---------------------------------------------------------------------------
def test_csv_agrega_la_columna_importada(client_as, db_session, make_head):
    from itcj2.apps.titulatec.models import SurveyResponse

    head = make_head(perm_codes=SURVEY_PERMS)
    form = _make_form(db_session)
    imp = _imported(db_session, form, control="99470005",
                    answers={"nombre_completo": "CSV IMPORT"})
    nat = SurveyResponse(form_id=form.id, form_version=1,
                         identity_source="anonymous", answers={})
    db_session.add(nat)
    db_session.flush()

    resp = client_as(head).get(f"{ENC}/export.csv?form_id={form.id}")

    assert resp.status_code == 200, resp.text[:300]
    filas = list(csv.reader(io.StringIO(resp.text.lstrip("﻿"))))
    headers = filas[0]
    assert "importada" in headers
    col = headers.index("importada")
    por_id = {f[0]: f for f in filas[1:]}
    assert por_id[str(imp.id)][col] == "sí"
    assert por_id[str(nat.id)][col] == "no"


def test_csv_incluye_las_llaves_extra_importadas(client_as, db_session, make_head):
    """M5: `extra_aspecto_no_trabajo` (R9, sin pregunta en el schema) va al CSV."""
    head = make_head(perm_codes=SURVEY_PERMS)
    form = _make_form(db_session)
    imp = _imported(db_session, form, control="99470006",
                    answers={"nombre_completo": "CSV EXTRA",
                             "extra_aspecto_no_trabajo": "=Mucho 5"})

    resp = client_as(head).get(f"{ENC}/export.csv?form_id={form.id}")

    assert resp.status_code == 200, resp.text[:300]
    filas = list(csv.reader(io.StringIO(resp.text.lstrip("﻿"))))
    headers = filas[0]
    assert headers[-1] == "extra_aspecto_no_trabajo"
    fila = {f[0]: f for f in filas[1:]}[str(imp.id)]
    # Escapado contra inyección de fórmulas como cualquier otra columna.
    assert fila[headers.index("extra_aspecto_no_trabajo")] == "'=Mucho 5"


def test_csv_sin_importadas_no_agrega_columnas_extra(client_as, db_session, make_head):
    from itcj2.apps.titulatec.models import SurveyResponse

    head = make_head(perm_codes=SURVEY_PERMS)
    form = _make_form(db_session)
    db_session.add(SurveyResponse(form_id=form.id, form_version=1,
                                  identity_source="anonymous", answers={}))
    db_session.flush()

    resp = client_as(head).get(f"{ENC}/export.csv?form_id={form.id}")

    headers = next(csv.reader(io.StringIO(resp.text.lstrip("﻿"))))
    assert not [h for h in headers if h.startswith("extra_")]


# ---------------------------------------------------------------------------
# Liberaciones (GTV)
# ---------------------------------------------------------------------------
def test_previa_con_respuesta_y_papel_pendiente_ofrece_ver_respuestas_y_marcar(
    client_as, db_session, make_gtv, previa,
):
    review, _, response = previa("99470010", current_phase=1)

    resp = client_as(make_gtv()).get(f"{LIB}/body?status=approved&q=99470010")

    assert resp.status_code == 200, resp.text[:500]
    fila = _fila(resp.text, review.id)
    assert f'href="{ENC}/{response.id}"' in fila
    assert "Ver respuestas" in fila
    assert "Constancia por recoger" in fila
    assert f'hx-post="{LIB}/{review.id}/entregada"' in fila
    assert "Marcar constancia entregada" in fila
    # La confirmación va en el <form> (puente hx-confirm -> modal).
    form_tag = re.search(r'<form[^>]*hx-post="%s/%d/entregada"[^>]*>' % (LIB, review.id),
                         fila).group(0)
    assert "hx-confirm=" in form_tag


def test_previa_sin_papel_pendiente_no_ofrece_marcar(client_as, db_session, make_gtv, previa):
    review, _, _ = previa("99470011", paper=False, current_phase=1)

    fila = _fila(client_as(make_gtv()).get(
        f"{LIB}/body?status=approved&q=99470011").text, review.id)

    assert "Ver respuestas" in fila
    assert "Constancia por recoger" not in fila
    assert "/entregada" not in fila


def test_previa_con_inscripcion_revocada_no_muestra_la_pildora_ni_el_boton(
    client_as, db_session, make_gtv, previa,
):
    review, proc, _ = previa("99470012", current_phase=1)
    proc.status = "cancelled"
    db_session.flush()

    fila = _fila(client_as(make_gtv()).get(
        f"{LIB}/body?status=approved&q=99470012").text, review.id)

    assert "Revocada" in fila
    assert "Constancia por recoger" not in fila
    assert "/entregada" not in fila


def test_marcar_constancia_entregada_re_renderiza_y_quita_la_pildora(
    client_as, db_session, make_gtv, previa,
):
    from itcj2.apps.titulatec.models import ProcessEvent

    gtv = make_gtv()
    review, proc, _ = previa("99470012", current_phase=1)

    resp = client_as(gtv).post(f"{LIB}/{review.id}/entregada",
                               data={"status": "approved", "q": "99470012", "page": "1"})

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-releases-body"' in resp.text
    fila = _fila(resp.text, review.id)
    assert "Constancia por recoger" not in fila
    assert "/entregada" not in fila
    db_session.refresh(review)
    assert review.paper_delivered_at is not None
    assert review.paper_delivered_by_id == gtv.id
    assert (db_session.query(ProcessEvent)
            .filter_by(process_id=proc.id, event_type="survey_paper_delivered").count()) == 1


def test_marcar_entregada_sin_permiso_de_liberar_responde_403(
    client_as, db_session, make_gtv, previa,
):
    review, _, _ = previa("99470013", current_phase=1)
    solo_observa = make_gtv(perm_codes=("titulatec.survey_review.page.list",
                                        "titulatec.survey_review.api.reject"))

    resp = client_as(solo_observa).post(f"{LIB}/{review.id}/entregada",
                                        data={"status": "approved", "q": "", "page": "1"})

    assert resp.status_code == 403, resp.text[:300]
    db_session.refresh(review)
    assert review.paper_delivered_at is None


@pytest.mark.parametrize("caso", ["sin_papel", "ya_entregada"])
def test_marcar_entregada_que_no_aplica_responde_400(
    client_as, db_session, make_gtv, previa, caso,
):
    gtv = make_gtv()
    review, _, _ = previa("99470014", paper=(caso == "ya_entregada"), current_phase=1)
    datos = {"status": "approved", "q": "", "page": "1"}
    if caso == "ya_entregada":
        assert client_as(gtv).post(f"{LIB}/{review.id}/entregada", data=datos).status_code == 200

    resp = client_as(gtv).post(f"{LIB}/{review.id}/entregada", data=datos)

    assert resp.status_code == 400, resp.text[:300]
    assert resp.headers.get("X-Tt-Error")


def test_marcar_entregada_inexistente_responde_404(client_as, make_gtv):
    resp = client_as(make_gtv()).post(f"{LIB}/999999/entregada",
                                      data={"status": "approved", "q": "", "page": "1"})

    assert resp.status_code == 404, resp.text[:300]


# ---------------------------------------------------------------------------
# Alumno
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("estado,ve", [
    ("pendiente", True), ("entregada", False), ("sin_papel", False),
])
def test_alumno_ve_recoge_tu_constancia_solo_mientras_esta_pendiente(
    client_as, db_session, make_survey_form, seed_phase_defs, make_cohort,
    previa, make_user, estado, ve,
):
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

    seed_phase_defs()
    make_survey_form()
    review, proc, _ = previa("99470020", paper=(estado != "sin_papel"),
                             cohort=make_cohort(), current_phase=2)
    if estado == "entregada":
        SurveyReviewService.mark_paper_delivered(
            db_session, review.id, actor_id=make_user(first_name="GTV").id)
    db_session.commit()
    from itcj2.core.models.user import User
    student = db_session.get(User, proc.student_id)
    c = client_as(student)

    for url in ("/titulatec/encuesta-egresados", "/titulatec/student/dashboard",
                "/titulatec/student/cita"):
        resp = c.get(url, follow_redirects=False)
        assert resp.status_code == 200, (url, resp.text[:300])
        assert (PICKUP in _texto(resp.text)) is ve, url


# ---------------------------------------------------------------------------
# Correo de la previa (R10)
# ---------------------------------------------------------------------------
@pytest.fixture()
def _correo_encendido(monkeypatch):
    from itcj2.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "TITULATEC_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "TITULATEC_HANDOFF_PHASE", 3)
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent",
                        lambda *a, **k: pytest.fail("no se envía"))
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail",
                        lambda *a, **k: pytest.fail("no se envía"))


def _correo_previa(db_session, proc):
    from itcj2.apps.titulatec.models import EmailOutbox
    from itcj2.apps.titulatec.pages.nav import titulatec_templates
    from itcj2.apps.titulatec.services.mail_compose import Composed, MailComposer
    from itcj2.core.models.user import User
    from jinja2 import StrictUndefined

    db_session.flush()
    filas = (db_session.query(EmailOutbox)
             .filter_by(process_id=proc.id, status="pending", kind="survey_approved")
             .order_by(EmailOutbox.id).all())
    assert filas, "register_prior no encoló el correo"
    c = MailComposer.compose(db_session, filas, proc, db_session.get(User, proc.student_id))
    assert isinstance(c, Composed), c
    env = titulatec_templates.env.overlay(undefined=StrictUndefined)
    html = env.get_template(f"titulatec/email/{c.template}").render(**c.context)
    return _texto(html)


@pytest.mark.parametrize("paper,ve", [(True, True), (False, False)])
def test_correo_de_previa_lleva_la_linea_de_recoger_solo_con_papel(
    _correo_encendido, db_session, seed_phase_defs, previa, paper, ve,
):
    seed_phase_defs()
    _, proc, _ = previa("99470030", paper=paper, current_phase=2, phases=False)

    texto = _correo_previa(db_session, proc)

    assert "semestre anterior" in texto
    assert (PICKUP in texto) is ve


def test_correo_de_previa_omite_la_linea_si_ya_se_entrego_al_enviar(
    _correo_encendido, db_session, seed_phase_defs, previa, make_user,
):
    """Re-validado al ENVIAR (como el resto del compositor, D8): si GTV ya
    entregó el papel dentro de la espera, «recoge» sería falso."""
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

    seed_phase_defs()
    review, proc, _ = previa("99470031", paper=True, current_phase=2, phases=False)
    SurveyReviewService.mark_paper_delivered(
        db_session, review.id, actor_id=make_user(first_name="GTV").id)

    texto = _correo_previa(db_session, proc)

    assert PICKUP not in texto


# ---------------------------------------------------------------------------
# Encuesta pública: respuesta de Forms importada que espera la inscripción
# (decisión del usuario tras la revisión final)
# ---------------------------------------------------------------------------
SURVEY_PUBLIC = "/titulatec/encuesta-egresados"
IMPORTED_PENDING = ("Tu encuesta de Microsoft Forms ya está registrada; se liberará "
                    "cuando completes tu inscripción.")
OK_PAYLOAD = {"website": "", "situacion_laboral": "empleado", "relacion_carrera": "4",
              "areas_fuertes": ["tecnica", "idiomas"], "comentarios": "Prueba."}


@pytest.fixture()
def diferida(db_session, make_survey_form, make_student):
    """Egresado SIN proceso cuya respuesta de Forms se importó y quedó
    DIFERIDA (`PriorClearance` sin aplicar, ligada a la respuesta). Devuelve
    `(student, form, response)`."""
    from itcj2.apps.titulatec.models import PriorClearance
    from itcj2.core.utils.timezone import db_now

    def _make(control, *, dias=10, con_previa=True):
        form = make_survey_form()            # `egresados` abierto
        student = make_student(control_number=control)
        response = _imported(db_session, form, control=control,
                             answers={"nombre_completo": "EGRESADA DIFERIDA"})
        if con_previa:
            db_session.add(PriorClearance(
                kind="survey", control_number=control,
                issued_on=db_now().date() - timedelta(days=dias),
                source="egresados.xlsx", response_id=response.id, paper_pending=False))
        db_session.flush()
        return student, form, response
    return _make


def _cuenta_respuestas(db_session, form):
    from itcj2.apps.titulatec.models import SurveyResponse
    return db_session.query(SurveyResponse).filter_by(form_id=form.id).count()


def test_encuesta_publica_con_import_diferido_muestra_la_tarjeta_y_no_el_formulario(
    client_as, diferida,
):
    student, _, _ = diferida("99470031")

    resp = client_as(student).get(SURVEY_PUBLIC, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert IMPORTED_PENDING in _texto(resp.text)
    assert 'data-tt-review-status="imported"' in resp.text
    assert 'id="tt-survey-form"' not in resp.text


def test_envio_con_import_diferido_se_rechaza_sin_escribir(
    client_as, db_session, diferida,
):
    student, form, _ = diferida("99470032")
    antes = _cuenta_respuestas(db_session, form)

    resp = client_as(student).post(SURVEY_PUBLIC, data=OK_PAYLOAD,
                                   headers={"X-Real-IP": "203.0.113.131"},
                                   follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert 'data-tt-credit="imported"' in resp.text
    assert IMPORTED_PENDING in _texto(resp.text)
    assert _cuenta_respuestas(db_session, form) == antes


def test_submit_del_servicio_tambien_rechaza_con_import_diferido(db_session, diferida):
    """Defensa del lado del servicio, sin pasar por la ruta."""
    from itcj2.apps.titulatec.services.survey_service import SurveyService

    student, form, _ = diferida("99470033")
    antes = _cuenta_respuestas(db_session, form)

    resp, errors, estado = SurveyService.submit(
        db_session, form, dict(OK_PAYLOAD), user_id=student.id,
        client_ip="203.0.113.132", user_agent="pytest")

    assert (resp, errors, estado) == (None, {}, "imported")
    assert _cuenta_respuestas(db_session, form) == antes


@pytest.mark.parametrize("caso", ["sin_import", "importada_sin_previa", "previa_vencida"])
def test_sin_import_diferido_vigente_el_egresado_ve_el_formulario(
    client_as, make_survey_form, make_student, diferida, caso,
):
    """Sin respuesta importada -o con una que no liberará nada (sin previa
    diferida, o vencida)- la encuesta sigue abierta: nunca un callejón."""
    if caso == "sin_import":
        make_survey_form()
        student = make_student(control_number="99470034")
    elif caso == "importada_sin_previa":
        student, _, _ = diferida("99470035", con_previa=False)
    else:
        student, _, _ = diferida("99470036", dias=400)

    resp = client_as(student).get(SURVEY_PUBLIC, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert 'id="tt-survey-form"' in resp.text
    assert IMPORTED_PENDING not in _texto(resp.text)


def test_con_solicitud_existente_manda_la_solicitud_no_el_aviso_de_import(
    client_as, db_session, make_survey_form, seed_phase_defs, make_cohort, previa,
):
    """Si ya hay solicitud (previa aplicada), el comportamiento de siempre."""
    from itcj2.core.models.user import User

    seed_phase_defs()
    make_survey_form()
    _, proc, _ = previa("99470037", paper=False, cohort=make_cohort(), current_phase=2)
    db_session.commit()

    resp = client_as(db_session.get(User, proc.student_id)).get(
        SURVEY_PUBLIC, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert 'data-tt-review-status="approved"' in resp.text
    assert IMPORTED_PENDING not in _texto(resp.text)
