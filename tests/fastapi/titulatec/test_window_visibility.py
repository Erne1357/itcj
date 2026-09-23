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
# El de la jefatura: `puede_editar(..., manage_all=True)` abre los espacios de
# CUALQUIERA. Es la excepcion que distingue «no eres el dueno» de «no puedes».
_ESPACIO_PERM_ALL = "titulatec.review_window.api.manage.all"


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


def test_la_linea_de_agendable_cuenta_FRANJAS_no_CITAS(editor, client_as,
                                                       set_cohort_defaults, db_session):
    """Un espacio NUEVO no tiene ventana de la que sacar `free_slots`, asi que la
    cuenta se deriva del horario — y ahi se colaba `n * capacity`, que son CITAS.

    Con cupo 1 los dos numeros coinciden, y por eso el test de arriba pasaba sin
    que la frase fuera cierta. Con cupo 2 y 10 franjas, «20 franjas libres» es
    falso: el egresado ve DIEZ horas para elegir, no veinte.
    """
    esc = editor
    set_cohort_defaults(esc["cohort"], start="09:00", end="14:00", slot=30, cap=2)
    db_session.flush()

    html = client_as(esc["off"]).get(
        "/titulatec/admin/appointments?v=espacios&date=%s&w=nuevo" % _D.isoformat()).text

    # Sin esto el test pasaria en falso: si el cupo por omision no llegara a 2,
    # los dos calculos volverian a coincidir y no se estaria midiendo nada.
    assert "de 2 personas" in html, "el espacio nuevo no heredo el cupo 2 de la convocatoria"
    assert "10 franjas libres" in html
    assert "20 franjas libres" not in html, "la linea cuenta citas, no franjas"


# ---------------------------------------------------------------------------
# Las otras dos acciones de Espacios, que tampoco tenian prueba de RUTA
# ---------------------------------------------------------------------------
# El defecto que encontraron los tests de arriba (`_accion_espacio` llamaba a
# `_render_body` sin `selected_id`, obligatorio -> 500 en TODA accion que salia
# bien) afectaba a las cuatro: guardar, copiar, pausar y eliminar. Guardar y
# copiar ya quedaron cubiertas; estas dos son las que faltaban, y sin ellas
# `space_pause` y `space_delete` seguirian tan desprotegidas como antes.

def test_pausar_el_espacio_responde_200_y_cambia_la_fila(editor, client_as, db_session):
    """Y vuelve: el boton es un interruptor, no un viaje de ida."""
    esc = editor
    assert esc["w"].status == "open"

    resp = client_as(esc["off"]).post(_url(esc, "/pausa"))
    assert resp.status_code == 200, resp.text[:300]
    db_session.expire_all()
    assert esc["w"].status == "paused"

    resp = client_as(esc["off"]).post(_url(esc, "/pausa"))
    assert resp.status_code == 200, resp.text[:300]
    db_session.expire_all()
    assert esc["w"].status == "open"


def test_eliminar_el_espacio_responde_200_y_borra_la_fila(editor, client_as, db_session):
    """El espacio del fixture no tiene ninguna cita, asi que si se puede borrar.

    (Con citas vivas el service levanta `WindowInUse`, que es otro camino y ya
    tiene prueba propia en `test_review_window_service.py`.)
    """
    from itcj2.apps.titulatec.models import ReviewWindow

    esc = editor
    wid = esc["w"].id

    resp = client_as(esc["off"]).post(_url(esc, "/eliminar"))
    assert resp.status_code == 200, resp.text[:300]

    db_session.expire_all()
    assert db_session.query(ReviewWindow).filter_by(id=wid).first() is None


# ---------------------------------------------------------------------------
# Publicar sin carreras asignadas: se guarda, pero no lo ve NADIE
# ---------------------------------------------------------------------------
# `SelfBookingService.offer` resuelve la carrera con el predicado de alcance del
# encargado y es fail-closed (Ruling 14), asi que quien no tiene carreras puede
# publicar un `bookable` invisible. Se mantiene el predicado; lo que no se
# mantiene es el silencio.

@pytest.fixture()
def editor_sin_carreras(make_cohort, make_review_day, make_officer, make_review_window):
    """Un encargado que puede editar espacios pero NO atiende ninguna carrera."""
    from tests.fastapi.titulatec.conftest import OFFICER_PERMS

    cohort = make_cohort()
    dia = make_review_day(cohort, day=_D)
    officer, pos = make_officer([], perm_codes=OFFICER_PERMS + (_ESPACIO_PERM,),
                                first_name="JEFA", last_name="SINCARRERAS")
    w = make_review_window(dia, officer, start="09:00", end="14:00", slot=30,
                           cap=1, location="Edificio A", position=pos)
    return {"cohort": cohort, "dia": dia, "off": officer, "pos": pos, "w": w}


def test_el_editor_avisa_a_quien_no_tiene_carreras(editor_sin_carreras, client_as):
    esc = editor_sin_carreras
    html = client_as(esc["off"]).get(
        "/titulatec/admin/appointments?v=espacios&date=%s&w=%d"
        % (_D.isoformat(), esc["w"].id)).text

    assert "tt-vis-aviso" in html, "no se avisa de que nadie vera el espacio"
    assert "ningún egresado lo verá" in html


def test_el_encargado_CON_carreras_no_ve_ese_aviso(editor, client_as):
    """La negativa que impide que el aviso salga siempre y deje de significar algo."""
    esc = editor
    html = client_as(esc["off"]).get(
        "/titulatec/admin/appointments?v=espacios&date=%s&w=%d"
        % (_D.isoformat(), esc["w"].id)).text

    assert "tt-vis-aviso" not in html


def test_la_lista_repite_el_aviso_si_ya_hay_un_espacio_agendable(
        editor_sin_carreras, client_as, db_session):
    """El toast del guardado se va; el espacio publicado se queda.

    Sin `w=` no hay editor abierto, asi que este texto solo puede venir de la
    LISTA — que es justo lo que se quiere fijar.
    """
    esc = editor_sin_carreras
    esc["w"].visibility = "bookable"
    db_session.flush()

    html = client_as(esc["off"]).get(
        "/titulatec/admin/appointments?v=espacios&date=" + _D.isoformat()).text

    assert "ningún egresado los verá" in html


# ---------------------------------------------------------------------------
# El editor NO se renderiza para una ventana AJENA
# ---------------------------------------------------------------------------
# El camino de ESCRITURA ya comprobaba la propiedad (`_espacio_en_alcance`, el
# 404 de mas arriba). El de LECTURA comprobaba solo el DIA, asi que el encargado
# A abria `?v=espacios&date=...&w=<id de B>` y se llevaba horario, cupo, LUGAR y
# VISIBILIDAD de B con los radios premarcados — bastante mas de lo que la lista
# «de otros encargados» ensena a proposito (solo horario y conteos, sin nombre y
# sin lugar). Guardar daba 404, pero htmx NO swappea en 4xx: el toast generico
# le llegaba DESPUES de haber leido lo que no le tocaba.

def test_el_editor_no_se_abre_para_la_ventana_de_otro_encargado(
        editor, client_as, make_officer):
    """La negativa viaja con su positiva EN EL MISMO test.

    Si el `w=` estuviera mal formado, o el dia no existiera, el editor tampoco
    saldria y esto pasaria en verde sin haber medido la propiedad. La mitad del
    dueno es la que prueba que esa MISMA url si abre un editor.
    """
    from tests.fastapi.titulatec.conftest import OFFICER_PERMS

    esc = editor
    url = ("/titulatec/admin/appointments?v=espacios&date=%s&w=%d"
           % (_D.isoformat(), esc["w"].id))
    ajeno, _ = make_officer([esc["prog"]], perm_codes=OFFICER_PERMS + (_ESPACIO_PERM,),
                            first_name="MIRON", last_name="ENCARGADO")

    resp = client_as(ajeno).get(url)
    html = resp.text

    # La pagina sigue viva: lo que desaparece es el editor, no la vista del dia.
    assert resp.status_code == 200, html[:300]
    assert 'name="visibility"' not in html, (
        "se renderizo el editor de un espacio AJENO: filtra su modo de "
        "visibilidad, y ademas con el radio premarcado")
    assert "Edificio A" not in html, (
        "se filtro el LUGAR de la ventana ajena, que la lista de espacios de "
        "otros encargados omite a proposito")
    assert "franjas libres" not in html, (
        "se filtro la ocupacion real del espacio ajeno")

    # Positiva, en el mismo test: el DUENO si abre su editor por esa url.
    propio = client_as(esc["off"]).get(url).text
    assert 'name="visibility"' in propio, "el dueno dejo de poder editar lo suyo"
    assert "Edificio A" in propio


def test_la_jefatura_SI_abre_el_editor_de_una_ventana_ajena(
        editor, client_as, make_officer):
    """`manage.all` es exactamente la excepcion que `puede_editar` contempla.

    Sin esta prueba, cerrar la fuga de arriba con un `owner_user_id == user_id`
    pelado saldria igual de verde y le quitaria a la jefatura una facultad que
    el camino de ESCRITURA si le reconoce — o sea, dejaria los dos caminos
    discrepando, que es el defecto de origen al reves.
    """
    from tests.fastapi.titulatec.conftest import OFFICER_PERMS

    esc = editor
    jefa, _ = make_officer(
        [esc["prog"]],
        perm_codes=OFFICER_PERMS + (_ESPACIO_PERM, _ESPACIO_PERM_ALL),
        first_name="JEFA", last_name="DEESPACIOS")

    html = client_as(jefa).get(
        "/titulatec/admin/appointments?v=espacios&date=%s&w=%d"
        % (_D.isoformat(), esc["w"].id)).text

    assert 'name="visibility"' in html, (
        "la jefatura con `manage.all` tiene que poder abrir el editor de "
        "cualquiera: es lo que ya le permite el camino de escritura")
    assert "Edificio A" in html
