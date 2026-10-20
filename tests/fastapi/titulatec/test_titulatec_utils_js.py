"""Puente `hx-confirm` -> `confirmDialog` en titulatec-utils.js, y que ningun
template de la app use `confirm()`/`alert()`/`prompt()` nativos.

Test ESTRUCTURAL: sin navegador, sin TestClient, sin BD. Lee los archivos tal
cual quedan en el repo, igual que `test_citas_sistema_visual.py` /
`test_citas_layout_contract.py` (mismo patron: `Path(__file__).resolve()
.parents[3]` para la raiz del repo, helpers de texto + regex).

Regla del proyecto (CLAUDE.md raiz y el de titulatec): PROHIBIDO `confirm()`,
`alert()` o `prompt()` nativos. Siempre el modal de Bootstrap via
`window.TitulaTecUtils.confirmDialog`, y para HTMX el puente `htmx:confirm`
de mas abajo (mismo patron que `apps/directory/static/js/index.js`).
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
JS = REPO_ROOT / "itcj2/apps/titulatec/static/js/shared/titulatec-utils.js"
TEMPLATES_DIR = REPO_ROOT / "itcj2/apps/titulatec/templates"


def _js_texto():
    return JS.read_text(encoding="utf-8")


def _bloque_htmx_confirm(texto):
    """Recorta desde 'htmx:confirm' hasta el siguiente landmark inconfundible
    (la exposicion final de window.TitulaTecUtils). Evita depender de contar
    llaves balanceadas -fragil con regex- para aislar el cuerpo del listener,
    que ademas anida su propio `.then(function (si) {...})`."""
    inicio = texto.find("htmx:confirm")
    assert inicio != -1, "no se encontro 'htmx:confirm' en titulatec-utils.js"
    fin = texto.find("window.TitulaTecUtils", inicio)
    assert fin != -1, "no se encontro 'window.TitulaTecUtils =' despues del listener"
    return texto[inicio:fin]


# --- puente htmx:confirm -------------------------------------------------

def test_existe_listener_htmx_confirm():
    texto = _js_texto()
    assert re.search(r"addEventListener\(\s*['\"]htmx:confirm['\"]", texto), (
        "titulatec-utils.js no engancha 'htmx:confirm': un hx-confirm caeria "
        "al confirm() nativo del navegador, que el proyecto prohibe."
    )


def test_listener_delegado_en_document():
    texto = _js_texto()
    assert re.search(r"(document\.body|document)\.addEventListener\(\s*['\"]htmx:confirm['\"]", texto), (
        "el listener debe delegarse en document o document.body (no en un "
        "elemento puntual: se perderia en los swaps de HTMX)."
    )


def test_listener_ignora_peticiones_sin_hx_confirm():
    bloque = _bloque_htmx_confirm(_js_texto())
    assert re.search(r"if\s*\([^)]*question[^)]*\)\s*return", bloque), (
        "sin hx-confirm en el elemento, e.detail.question es undefined: el "
        "listener debe salir temprano (return) y dejar pasar la peticion "
        "normal, sin abrir ningun modal."
    )


def test_listener_previene_el_default_y_reanuda_al_confirmar():
    bloque = _bloque_htmx_confirm(_js_texto())
    assert "preventDefault" in bloque, (
        "el listener debe llamar e.preventDefault() para que htmx no dispare "
        "tambien su confirm() nativo."
    )
    assert "issueRequest(true)" in bloque, (
        "al confirmar en el modal de la app, el listener debe reanudar la "
        "peticion con e.detail.issueRequest(true)."
    )


def test_listener_parsea_titulo_y_cuerpo_por_pipe():
    bloque = _bloque_htmx_confirm(_js_texto())
    assert "split('|')" in bloque or 'split("|")' in bloque, (
        "el listener debe partir la pregunta 'Titulo|Cuerpo' por '|'."
    )
    assert "'Confirmar'" in bloque or '"Confirmar"' in bloque, (
        "sin '|' en hx-confirm, el titulo por defecto debe ser 'Confirmar'."
    )


def test_listener_evita_doble_registro():
    """`base.html` carga este script en TODAS las paginas; si algun fragmento
    morpheado llegara a incluirlo de nuevo, sin guarda el listener quedaria
    registrado dos veces y el modal se abriria doble por cada hx-confirm."""
    texto = _js_texto()
    antes = texto[: texto.find("htmx:confirm")]
    cola = antes[-400:]
    assert re.search(r"if\s*\(\s*!\s*window\.\w+", cola), (
        "falta una guarda de doble carga (p.ej. `if (!window.<flag>) { ... "
        "addEventListener(...) }`) antes de registrar el listener de "
        "htmx:confirm."
    )


def test_confirm_dialog_sigue_expuesto_en_window():
    texto = _js_texto()
    assert re.search(r"window\.TitulaTecUtils\s*=\s*\{[^}]*confirmDialog", texto), (
        "TitulaTecUtils.confirmDialog debe seguir expuesto: el puente lo usa "
        "para reemplazar a confirm()."
    )


# --- nada de dialogos nativos en los templates ----------------------------

_JINJA_COMMENT_RE = re.compile(r"\{#.*?#\}", re.S)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
# Negativo detras: no confunde `confirmDialog(`/`.confirm(` de otro objeto,
# ni un identificador que TERMINE en confirm/alert/prompt.
_DIALOGO_NATIVO_RE = re.compile(r"(?<![\w.])(confirm|alert|prompt)\(")


def _sin_comentarios(texto):
    texto = _JINJA_COMMENT_RE.sub("", texto)
    texto = _HTML_COMMENT_RE.sub("", texto)
    return texto


def _templates():
    return sorted(TEMPLATES_DIR.rglob("*.html"))


def test_hay_templates_que_revisar():
    # Salvaguarda: si esto da 0, la ruta esta mal y el resto pasaria en falso
    # (cero templates escaneados = cero violaciones encontradas).
    assert len(_templates()) > 30


def test_ningun_template_usa_dialogos_nativos():
    culpables = []
    for tpl in _templates():
        texto = _sin_comentarios(tpl.read_text(encoding="utf-8"))
        for m in _DIALOGO_NATIVO_RE.finditer(texto):
            linea = texto.count("\n", 0, m.start()) + 1
            culpables.append(f"{tpl.relative_to(REPO_ROOT)}:{linea} -> {m.group(0)}")
    assert not culpables, (
        "PROHIBIDO confirm()/alert()/prompt() nativos (CLAUDE.md raiz). Usa "
        "window.TitulaTecUtils.confirmDialog o hx-confirm (puente en "
        "titulatec-utils.js).\n" + "\n".join("  " + c for c in culpables)
    )


# --- <details data-tt-remember> -------------------------------------------

def _bloque_remember(texto):
    inicio = texto.find("data-tt-remember")
    assert inicio != -1, "no se encontro el comportamiento data-tt-remember"
    fin = texto.find("window.TitulaTecUtils", inicio)
    return texto[inicio:fin]


def test_remember_escucha_toggle_en_captura():
    """`toggle` de <details> NO burbujea: escuchado en fase de burbuja sobre
    `document` nunca llegaria y el estado no se guardaria jamas."""
    bloque = _bloque_remember(_js_texto())
    assert re.search(r"addEventListener\(\s*'toggle'[\s\S]*?\},\s*true\s*\)", bloque), (
        "el listener de 'toggle' debe registrarse en fase de CAPTURA "
        "(tercer argumento `true`)."
    )


def test_remember_restaura_tras_el_swap_de_htmx():
    """Las bandejas re-pintan su parcial en cada accion y el servidor lo manda
    cerrado: sin restaurar en `htmx:load` el bloque se cerraria a cada clic."""
    assert "htmx:load" in _bloque_remember(_js_texto())


def test_remember_nunca_revienta_sin_almacenamiento():
    """En modo privado o con almacenamiento bloqueado `localStorage` LANZA: cada
    acceso va dentro de un try, y sin almacenamiento el bloque nace cerrado."""
    bloque = _bloque_remember(_js_texto())
    usos = [m.start() for m in re.finditer(r"localStorage\.(get|set)Item", bloque)]
    assert usos, "no se encontraron accesos a localStorage"
    for pos in usos:
        linea = bloque[bloque.rfind("\n", 0, pos):bloque.find("\n", pos)]
        assert "try" in linea, "acceso a localStorage fuera de try: " + linea.strip()


# --- `data-tt-count-into` — contador de lote (m22, triage-minors.md) ------
#
# Sin navegador ni htmx reales en este arnes (test ESTRUCTURAL, como el resto
# del archivo): se fija el CONTRATO en el texto fuente -la unica forma
# practica de pinchar la guarda aqui es leerla-, no su efecto en un DOM vivo.
# Mutacion manual verificada a mano (revertida): quitar la linea
# `if (boton.classList.contains('htmx-request')) return;` hace fallar
# `test_sync_count_groups_no_reactiva_un_boton_con_peticion_en_vuelo`; quitar
# el listener de `htmx:afterRequest` hace fallar
# `test_sync_count_groups_se_re_sincroniza_al_terminar_la_peticion`.

def _bloque_sync_count(texto):
    """Recorta desde `_syncCountGroups` hasta el siguiente landmark
    inconfundible (la exposicion final de `window.TitulaTecUtils`), mismo
    patron que `_bloque_htmx_confirm`/`_bloque_remember`."""
    inicio = texto.find("_syncCountGroups")
    assert inicio != -1, "no se encontro _syncCountGroups en titulatec-utils.js"
    fin = texto.find("window.TitulaTecUtils", inicio)
    assert fin != -1, "no se encontro 'window.TitulaTecUtils =' despues de _syncCountGroups"
    return texto[inicio:fin]


def test_sync_count_groups_no_reactiva_un_boton_con_peticion_en_vuelo():
    """`hx-disabled-elt="this"` deshabilita el boton de lote mientras su
    peticion esta en vuelo y htmx le agrega la clase `htmx-request`; las
    casillas que alimentan el contador NO se deshabilitan. Sin esta guarda,
    desmarcar/marcar una casilla mientras se espera la respuesta reactivaria
    el boton (via el listener de `change`) y abriria la puerta a un doble
    envio del lote."""
    bloque = _bloque_sync_count(_js_texto())
    m_guarda = re.search(
        r"if\s*\(\s*boton\.classList\.contains\(\s*['\"]htmx-request['\"]\s*\)\s*\)\s*return",
        bloque)
    assert m_guarda, (
        "falta la guarda `if (boton.classList.contains('htmx-request')) "
        "return;` antes de asignar boton.disabled -sin ella, un boton con "
        "una peticion en vuelo se podria re-habilitar."
    )
    i_disabled = bloque.find(".disabled =")
    assert i_disabled != -1 and i_disabled > m_guarda.end(), (
        "boton.disabled debe asignarse DESPUES de la guarda de 'htmx-request', "
        "no antes."
    )


def test_sync_count_groups_se_re_sincroniza_al_terminar_la_peticion():
    """Al terminar la peticion (exito o error -sin swap en un 4xx-) htmx
    limpia 'htmx-request' y el `disabled` de `hx-disabled-elt` por su cuenta,
    SIN mirar el conteo real de casillas: `htmx:afterRequest` debe volver a
    llamar `_syncCountGroups()` para que el boton quede disabled/enabled
    segun el conteo VIGENTE en ese momento, no el de antes de la peticion."""
    texto = _js_texto()
    assert re.search(
        r"addEventListener\(\s*['\"]htmx:afterRequest['\"]\s*,\s*function\s*\([^)]*\)\s*"
        r"\{\s*_syncCountGroups\(\)\s*;?\s*\}\s*\)",
        texto), (
        "falta un listener de 'htmx:afterRequest' que vuelva a llamar "
        "_syncCountGroups() al terminar la peticion."
    )
