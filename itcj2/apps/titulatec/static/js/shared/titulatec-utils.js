/* ===========================================================================
   TitulaTec — utils compartidos (toast + confirmDialog).
   PROHIBIDO confirm()/alert()/prompt() nativos. Usar estos helpers.
   Expone window.TitulaTecUtils.
   =========================================================================== */
(function () {
  'use strict';

  function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
  }

  function _toastContainer() {
    let c = document.getElementById('tt-toast-container');
    if (!c) {
      c = document.createElement('div');
      c.id = 'tt-toast-container';
      c.className = 'toast-container position-fixed top-0 end-0 p-3';
      c.style.zIndex = '1090';
      document.body.appendChild(c);
    }
    return c;
  }

  // type: success | danger | warning | info
  function showToast(message, type = 'info') {
    const tones = {
      success: 'tt-pill--success', danger: 'tt-pill--danger',
      warning: 'tt-pill--amber', info: 'tt-pill--navy',
    };
    const icons = {
      success: 'check-circle', danger: 'exclamation-octagon',
      warning: 'exclamation-triangle', info: 'info-circle',
    };
    const el = document.createElement('div');
    el.className = 'toast align-items-center border-0 mb-2';
    el.setAttribute('role', 'alert');
    el.innerHTML =
      '<div class="d-flex align-items-center tt-card p-2">' +
      '<span class="tt-pill ' + (tones[type] || tones.info) + ' me-2">' +
      '<i class="bi bi-' + (icons[type] || icons.info) + '"></i></span>' +
      '<div class="flex-grow-1" style="font-size:.85rem">' + escapeHtml(message) + '</div>' +
      '<button type="button" class="btn-close ms-2" data-bs-dismiss="toast"></button></div>';
    _toastContainer().appendChild(el);
    const t = new bootstrap.Toast(el, { delay: 4000 });
    t.show();
    el.addEventListener('hidden.bs.toast', () => el.remove());
  }

  // Devuelve Promise<boolean>. Reemplazo de confirm().
  function confirmDialog(title, message, confirmText = 'Confirmar', cancelText = 'Cancelar') {
    return new Promise((resolve) => {
      const id = 'tt-confirm-' + Date.now();
      const wrap = document.createElement('div');
      wrap.innerHTML =
        '<div class="modal fade" id="' + id + '" tabindex="-1">' +
        '<div class="modal-dialog modal-dialog-centered"><div class="modal-content tt-card">' +
        '<div class="modal-header border-0"><h5 class="modal-title tt-display">' + escapeHtml(title) + '</h5>' +
        '<button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>' +
        '<div class="modal-body" style="font-size:.9rem">' + escapeHtml(message) + '</div>' +
        '<div class="modal-footer border-0">' +
        '<button type="button" class="btn tt-btn-ghost" data-tt-action="cancel">' + escapeHtml(cancelText) + '</button>' +
        '<button type="button" class="btn tt-btn-ink" data-tt-action="confirm">' + escapeHtml(confirmText) + '</button>' +
        '</div></div></div></div>';
      document.body.appendChild(wrap);
      const modalEl = wrap.querySelector('.modal');
      const modal = new bootstrap.Modal(modalEl);
      let result = false;
      modalEl.querySelector('[data-tt-action="confirm"]').addEventListener('click', () => { result = true; modal.hide(); });
      modalEl.querySelector('[data-tt-action="cancel"]').addEventListener('click', () => { result = false; modal.hide(); });
      modalEl.addEventListener('hidden.bs.modal', () => { wrap.remove(); resolve(result); });
      modal.show();
    });
  }

  // — Retardo de los indicadores de carga —
  //
  // Regla del usuario (2026-09-02): «si no hace falta la animacion de carga, que
  // no se haga; queda raro que aparezca y desaparezca algo rapido». Medido: el
  // skeleton de Documentos vivia 150-192 ms y reservaba 24 px; en Citas el salto
  // era de 341.8 px. Por debajo de --tt-ind-delay la respuesta se percibe
  // instantanea y el indicador solo estorba.
  //
  // Por que esto es JS y no CSS: para no reservar alto, un indicador oculto tiene
  // que estar en `display: none`, y un elemento en `display: none` tiene
  // TERMINADAS sus animaciones (CSS Animations 1). Una animacion con retardo
  // nunca llega a devolverlo a `block`: probado en Chromium 149, el indicador se
  // quedaba oculto para siempre. Asi que la puerta la abre una clase.
  //
  // Contrato: htmx marca con `.htmx-request` tanto al emisor como a lo que
  // apunte `hx-indicator`. Vencido el retardo se les anade `.tt-ind-on`, que es
  // lo unico que el CSS mira para mostrar spinner/skeleton. `pointer-events:none`
  // del boton NO pasa por aqui: es inmediato, es la defensa anti doble-clic.
  var _retardo = null;                 // ms, leidos una vez de --tt-ind-delay
  var _pendientes = new Map();         // emisor -> {n: en vuelo, id: temporizador}

  function retardoIndicador() {
    if (_retardo !== null) return _retardo;
    var raw = '';
    try {
      raw = getComputedStyle(document.documentElement)
        .getPropertyValue('--tt-ind-delay').trim();
    } catch (_) { /* sin CSSOM utilizable */ }
    var n = parseFloat(raw);
    _retardo = (n > 0) ? (/ms\s*$/.test(raw) ? n : n * 1000) : 300;
    return _retardo;
  }

  function abrirPuerta() {
    document.querySelectorAll('.htmx-request').forEach(function (el) {
      el.classList.add('tt-ind-on');
    });
  }

  // Barre lo que ya no esta pidiendo nada. Al ser una reconciliacion (y no un
  // "deshaz lo que hice"), un evento de cierre perdido no deja indicadores
  // pegados: la siguiente peticion los limpia.
  function cerrarPuerta() {
    document.querySelectorAll('.tt-ind-on').forEach(function (el) {
      if (!el.classList.contains('htmx-request')) el.classList.remove('tt-ind-on');
    });
  }

  // Un registro por emisor, con contador de peticiones en vuelo: si el mismo
  // boton dispara dos veces seguidas, la primera en terminar NO puede cancelar
  // el temporizador que la segunda todavia necesita (o esa segunda peticion, aun
  // siendo lenta, se quedaria sin indicador).
  document.body.addEventListener('htmx:beforeRequest', function (e) {
    var emisor = (e.detail && e.detail.elt) || null;
    if (!emisor) return;
    var reg = _pendientes.get(emisor);
    if (reg) { reg.n++; return; }
    // La clase `.htmx-request` puede no estar puesta todavia; por eso el
    // querySelectorAll vive DENTRO del temporizador.
    _pendientes.set(emisor, {
      n: 1,
      id: setTimeout(function () {
        var r = _pendientes.get(emisor);
        if (r) r.id = null;
        abrirPuerta();
      }, retardoIndicador()),
    });
  });

  function finPeticion(e) {
    var emisor = (e.detail && e.detail.elt) || null;
    var reg = emisor && _pendientes.get(emisor);
    if (reg) {
      reg.n--;
      if (reg.n <= 0) {
        if (reg.id) clearTimeout(reg.id);
        _pendientes.delete(emisor);
      }
    }
    // htmx quita `.htmx-request` alrededor de este evento: reconciliamos en el
    // siguiente tick para no adelantarnos.
    setTimeout(cerrarPuerta, 0);
  }
  document.body.addEventListener('htmx:afterRequest', finPeticion);
  document.body.addEventListener('htmx:sendError', finPeticion);
  document.body.addEventListener('htmx:timeout', finPeticion);
  document.body.addEventListener('htmx:afterSettle', function () { cerrarPuerta(); });

  // — Animación de entrada para contenido insertado por HTMX —
  //
  // Regla del usuario (2026-09-02): «si algo no cambia, que no se mueva».
  // Antes esto re-disparaba `tt-anim-in` en TODOS los swaps, así que pulsar un
  // filtro que devolvía exactamente el mismo listado repintaba la pantalla
  // entera con la animación de entrada — movimiento sin cambio.
  //
  // Ahora se compara la IDENTIDAD DE VISTA del destino (`data-tt-view`) antes y
  // después del swap:
  //
  //   · ambos presentes e IGUALES  → no se re-anima (es la misma vista).
  //   · distintos, o cualquiera de los dos ausente → se re-anima, exactamente
  //     como antes. Un destino sin `data-tt-view` (todas las vistas del alumno)
  //     conserva el comportamiento de siempre, sin excepción.
  //
  // Cómo leerlo según el tipo de swap:
  //   · `morph:outerHTML` — Idiomorph CONSERVA el nodo destino y le sincroniza
  //     los atributos, así que después del swap `data-tt-view` ya trae el valor
  //     de la respuesta: la comparación distingue de verdad vista-vs-vista.
  //   · `innerHTML` — el destino no se reemplaza y su `data-tt-view` no cambia
  //     nunca. Ponerlo ahí significa, a propósito, «esta región no re-anima».
  var _prev = null;                  // respaldo si el swap sustituyó el nodo

  function _viewOf(el) {
    return (el && el.getAttribute) ? (el.getAttribute('data-tt-view') || null) : null;
  }

  document.body.addEventListener('htmx:beforeSwap', function (e) {
    var t = e.detail && e.detail.target;
    var v = _viewOf(t);
    if (t) { try { t.__ttView = v; } catch (_) { /* nodo exótico */ } }
    _prev = { id: (t && t.id) || null, view: v };
  });

  document.body.addEventListener('htmx:afterSwap', function (e) {
    var t = e.detail && e.detail.target;
    // Tras un outerHTML el `target` puede quedar desconectado: el nodo vivo es
    // el que conserva su id.
    if (t && t.isConnected === false && t.id) t = document.getElementById(t.id) || t;
    if (!t || !t.classList) return;

    var before = t.__ttView;
    if (before === undefined && _prev && _prev.id && _prev.id === t.id) before = _prev.view;
    try { delete t.__ttView; } catch (_) { /* nada que limpiar */ }
    _prev = null;

    var after = _viewOf(t);
    if (before && after && before === after) return;   // misma vista: quieta

    t.classList.remove('tt-anim-in');
    void t.offsetWidth;              // reinicia la animación
    t.classList.add('tt-anim-in');
  });

  // ————————————————————————————————— mensajes que llegan por header
  //
  // Los valores de header HTTP son latin-1 por especificación, así que el
  // servidor los percent-codifica (`pages/appointments.py::_hdr`) y aquí se
  // decodifican. Sin eso, cualquier mensaje con acentos —o sea, todos— llegaba
  // como bytes rotos.
  function decodeHeaderMsg(raw) {
    if (!raw) return '';
    try { return decodeURIComponent(raw); } catch (_) { return raw; }
  }

  // `X-Tt-Notice` viaja en respuestas 200. Es para las COLISIONES DE ESTADO:
  // otro encargado ganó la franja, o la cita ya cambió. Con un 4xx htmx no
  // swappea y el usuario se quedaría mirando una pantalla que miente, así que
  // el servidor manda el cuerpo fresco Y el aviso.
  document.body.addEventListener('htmx:afterRequest', function (e) {
    var xhr = e.detail && e.detail.xhr;
    if (!xhr || xhr.status < 200 || xhr.status >= 300) return;
    var msg = decodeHeaderMsg(xhr.getResponseHeader('X-Tt-Notice'));
    if (!msg) return;
    // `success` cuando la accion salio bien; `warning` cuando fue una colision
    // de estado (otro encargado gano la franja, la cita ya cambio).
    var kind = xhr.getResponseHeader('X-Tt-Notice-Kind') === 'success' ? 'success' : 'warning';
    showToast(msg, kind);
    // Y al lector de pantalla, por la region viva persistente que sobrevive al
    // swap: el toast se pinta y se va, y aria-live sobre un nodo recien
    // insertado no se anuncia de forma fiable.
    var say = document.getElementById('appt-say');
    if (say) say.textContent = msg;
  });

  // ————————————————————————————————— puente `hx-confirm` -> confirmDialog
  //
  // `confirmDialog` existía pero NADIE lo enganchaba a htmx, así que un
  // `hx-confirm` caía al `confirm()` nativo del navegador, que este proyecto
  // prohíbe. Mismo patrón que `apps/directory/static/js/index.js`.
  document.body.addEventListener('htmx:confirm', function (e) {
    if (!e.detail || !e.detail.question) return;   // sin hx-confirm: request normal
    e.preventDefault();
    var partes = String(e.detail.question).split('|');
    var titulo = partes.length > 1 ? partes[0].trim() : 'Confirmar';
    var cuerpo = (partes.length > 1 ? partes.slice(1).join('|') : partes[0]).trim();
    var elt = e.detail.elt;
    var ok = (elt && elt.getAttribute('data-tt-confirm-ok')) || 'Confirmar';
    confirmDialog(titulo, cuerpo, ok, 'Cancelar').then(function (si) {
      if (si) e.detail.issueRequest(true);
    });
  });

  window.TitulaTecUtils = { showToast, confirmDialog, escapeHtml, decodeHeaderMsg };
})();
