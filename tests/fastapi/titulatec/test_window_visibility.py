"""Contrato de ESQUEMA de `ReviewWindow.visibility` (Tarea 1, auto-agendado de cotejo).

Cubre solo la columna nueva y su `CheckConstraint`: los tres modos del espacio
(privado/agendable/sin-cita) para el auto-agendado del egresado. Quien ve y
quien agenda segun el modo es logica de `SelfBookingService` (tarea aparte).

Patron para la violacion de constraint: `with db_session.begin_nested():`. Un
`db_session.rollback()` pelado descarta tambien las filas que sembraron las
fixtures (`join_transaction_mode="create_savepoint"`, ver conftest); el
savepoint anidado solo descarta el INSERT/UPDATE que fallo. Ver
`test_review_window_model.py`.
"""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

_D = date(2029, 5, 7)


@pytest.fixture()
def dia_y_encargado(make_program, make_cohort, make_review_day, make_officer):
    """Un dia de cotejo y un encargado con carrera. Lo minimo para una ventana."""
    prog = make_program("Ingenieria de Visibilidad")
    cohort = make_cohort()
    dia = make_review_day(cohort, day=_D)
    officer, pos = make_officer([prog])
    return {"prog": prog, "cohort": cohort, "dia": dia, "off": officer, "pos": pos}


def test_una_ventana_nueva_nace_privada(db_session, dia_y_encargado, make_review_window):
    esc = dia_y_encargado
    w = make_review_window(esc["dia"], esc["off"], position=esc["pos"])
    assert w.visibility == "private"


@pytest.mark.parametrize("valor", ["private", "bookable", "walkin"])
def test_los_tres_valores_legales_se_guardan(db_session, dia_y_encargado,
                                             make_review_window, valor):
    esc = dia_y_encargado
    w = make_review_window(esc["dia"], esc["off"], position=esc["pos"])
    w.visibility = valor
    db_session.flush()
    assert w.visibility == valor


def test_un_valor_fuera_del_dominio_levanta_integrity_error(db_session, dia_y_encargado,
                                                             make_review_window):
    esc = dia_y_encargado
    w = make_review_window(esc["dia"], esc["off"], position=esc["pos"])
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            w.visibility = "publico"
            db_session.flush()


# ===========================================================================
# El modo se PUBLICA desde el editor de espacios (Tarea 7, spec §5 y §6)
# ===========================================================================
# `visibility` no gana ruta propia: es un campo mas del `POST
# /admin/appointments/espacios/{window_id}` que ya existia, protegido por
# `_ESPACIO_PERMS` y por `_espacio_en_alcance`. Sin permiso nuevo: quien puede
# editar un espacio puede publicarlo.
#
# El encargado del fixture de arriba NO trae `review_window.api.manage`
# (`OFFICER_PERMS` es el set de bandeja), asi que estas pruebas fabrican el
# suyo: un actor con el permiso de espacios y otro sin la propiedad de la
# ventana, que es el par que hace falta para probar la guarda.

_ESPACIO_PERM = "titulatec.review_window.api.manage"


def _form(**kw):
    """El cuerpo completo del editor. `space_save` lee TODOS los campos, asi que
    mandar solo `visibility` reescribiria el horario con los `Form(...)` por
    omision y la prueba pasaria mintiendo sobre lo que guardo."""
    base = {"start_time": "09:00", "end_time": "14:00", "slot_minutes": "30",
            "capacity": "1", "location": "Edificio A", "visibility": "private"}
    base.update(kw)
    return base


@pytest.fixture()
def editor(make_program, make_cohort, make_review_day, make_officer,
           make_review_window):
    """Un encargado que SI puede editar espacios, su ventana y un segundo dia.

    El segundo dia existe para «Copiar a los demas dias»: sin un destino, la
    copia no copia nada y el test pasaria sin ejercitar nada.
    """
    from tests.fastapi.titulatec.conftest import OFFICER_PERMS

    prog = make_program("Ingenieria de Publicacion")
    cohort = make_cohort()
    dia = make_review_day(cohort, day=_D)
    otro = make_review_day(cohort, day=date(2029, 5, 8))
    officer, pos = make_officer(
        [prog], perm_codes=OFFICER_PERMS + (_ESPACIO_PERM,))
    w = make_review_window(dia, officer, start="09:00", end="14:00", slot=30,
                           cap=1, location="Edificio A", position=pos)
    return {"prog": prog, "cohort": cohort, "dia": dia, "otro": otro,
            "off": officer, "pos": pos, "w": w}


def _url(esc, sufijo=""):
    return ("/titulatec/admin/appointments/espacios/%d%s?v=espacios&date=%s"
            % (esc["w"].id, sufijo, _D.isoformat()))


@pytest.mark.parametrize("modo", ["private", "bookable", "walkin"])
def test_guardar_el_espacio_persiste_el_modo(editor, client_as, db_session, modo):
    esc = editor
    resp = client_as(esc["off"]).post(_url(esc), data=_form(visibility=modo))

    assert resp.status_code == 200, resp.text[:300]
    db_session.expire_all()
    assert esc["w"].visibility == modo


def test_un_modo_inventado_no_llega_a_la_base(editor, client_as, db_session):
    """El CHECK lo rechazaria con un `IntegrityError` crudo, o sea un 500.

    La ruta lo corta antes y contesta 400 con `X-Tt-Error`, que htmx NO swappea:
    lo que hay en pantalla sigue siendo verdad.
    """
    esc = editor
    resp = client_as(esc["off"]).post(_url(esc), data=_form(visibility="publico"))

    assert resp.status_code == 400
    assert resp.headers.get("X-Tt-Error")
    db_session.expire_all()
    assert esc["w"].visibility == "private", "un valor invalido no debe tocar la fila"


def test_quien_no_es_dueno_de_la_ventana_recibe_404(editor, client_as, make_officer,
                                                    db_session):
    """`_espacio_en_alcance` ya cubria el resto de campos; tiene que seguir
    cubriendo el nuevo. 404 y no 403: el id es secuencial y enumerable."""
    from tests.fastapi.titulatec.conftest import OFFICER_PERMS

    esc = editor
    ajeno, _ = make_officer([esc["prog"]], perm_codes=OFFICER_PERMS + (_ESPACIO_PERM,),
                            first_name="OTRO", last_name="ENCARGADO")

    resp = client_as(ajeno).post(_url(esc), data=_form(visibility="bookable"))

    assert resp.status_code == 404
    db_session.expire_all()
    assert esc["w"].visibility == "private", "la ventana ajena no debe cambiar"


def test_copiar_a_los_demas_dias_copia_tambien_el_modo(editor, client_as, db_session):
    """Copiar el horario sin el modo dejaba espacios gemelos con visibilidad
    distinta: el encargado publica el lunes y el martes sigue invisible sin que
    nada se lo diga."""
    from itcj2.apps.titulatec.models import ReviewWindow

    esc = editor
    esc["w"].visibility = "bookable"
    db_session.flush()

    resp = client_as(esc["off"]).post(_url(esc, "/copiar"))
    assert resp.status_code == 200, resp.text[:300]

    db_session.expire_all()
    copia = (db_session.query(ReviewWindow)
             .filter(ReviewWindow.review_day_id == esc["otro"].id,
                     ReviewWindow.owner_user_id == esc["off"].id)
             .first())
    assert copia is not None, "no se copio el espacio al segundo dia"
    assert copia.visibility == "bookable"


def test_el_editor_ofrece_los_tres_modos_con_su_linea_derivada(editor, client_as):
    """Los textos de §6, calculados en el SERVIDOR.

    La linea derivada dice la verdad sobre ESTE espacio («tus 10 franjas
    libres»), no una frase generica: duplicar el calculo de franjas en
    JavaScript es justamente lo que el editor evita desde su rediseno.
    """
    esc = editor
    url = ("/titulatec/admin/appointments?v=espacios&date=%s&w=%d"
           % (_D.isoformat(), esc["w"].id))
    html = client_as(esc["off"]).get(url).text

    assert 'name="visibility"' in html, "el editor no ofrece el modo del espacio"
    for valor in ("private", "bookable", "walkin"):
        assert ('value="%s"' % valor) in html
    assert "El egresado no lo ve" in html
    assert "10 franjas libres" in html, (
        "la linea de «Agendable» no cuenta las franjas reales de esta ventana")
    assert "llega sin cita" in html
