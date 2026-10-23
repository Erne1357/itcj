/* ===========================================================================
   TitulaTec · Conversación de la revisión de sinodales (fase 5) — compartido.

   Spec 2026-10-22-titulatec-fase5-revision-sinodales §7.1. Lo cargan UNA vez
   `admin/base_admin.html` («Mis revisiones» del docente) y
   `student/base_student.html` (alumno). Comportamiento que el servidor no
   puede dar solo, sobre este contrato de marcado (las páginas lo arman; las
   burbujas salen de `partials/review/_messages.html`):

     <div class="tt-rv-thread" data-tt-review-thread>        (contenedor con scroll)
       <ol class="tt-rv-list" id="tt-rv-list" data-tt-review-list>
         <li data-tt-msg-id="17">…</li> …
       </ol>
     </div>
     <div data-tt-review-poll="#tt-rv-list" hx-get="…/mensajes"
          hx-trigger="every 15s [document.visibilityState=='visible']"
          hx-target="#tt-rv-list" hx-swap="beforeend"></div>
     <form data-tt-review-form="#tt-rv-list" hx-post="…/mensaje"
           hx-target="#tt-rv-list" hx-swap="beforeend"> … </form>

   - Refresco incremental: a toda petición que sale de `[data-tt-review-poll]`
     le agrega `after=<último id pintado>` (`htmx:configRequest`): el servidor
     solo manda lo nuevo. Sin la marca de sondeo (conversación cerrada), no hay
     refresco.
   - Al cargar y tras cada swap a la lista: quita `li` repetidos por
     `data-tt-msg-id` (el sondeo y el POST propio pueden traer el mismo) y baja
     al final si el usuario ya estaba abajo, si la lista es nueva o si el swap
     vino de su propio formulario.
   - Formulario: tras una respuesta 2xx se limpia (`reset`, también el
     archivo). Una ruta que conteste 200 con un error de validación manda
     `X-Tt-Review-Keep: 1` y el texto se queda.

   Morph-safe: delegación en `document.body`, estado en atributos del DOM
   vigente (`data-tt-bound`, que el morph quita al traer una lista nueva, y
   `data-tt-review-stick`); re-inicia en `DOMContentLoaded`, `htmx:afterSettle`
   y `htmx:historyRestore`. Sin lista, no hace nada.

   Expone solo `window.TitulaTecReviewThread = { init, lastId }`.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecReviewThread) return;   // doble carga del <script>

  var NEAR_PX = 80;

  // ————————————————————————————————— utilidades
  function listsIn(root) {
    return Array.prototype.slice.call((root || document).querySelectorAll('[data-tt-review-list]'));
  }

  function scrollerOf(list) {
    return (list.closest && list.closest('[data-tt-review-thread]')) || list;
  }

  function lastId(list) {
    var max = 0;
    if (!list) return 0;
    Array.prototype.forEach.call(list.querySelectorAll('[data-tt-msg-id]'), function (li) {
      var n = parseInt(li.getAttribute('data-tt-msg-id'), 10);
      if (n > max) max = n;
    });
    return max;
  }

  function dedupe(list) {
    var vistos = {};
    Array.prototype.forEach.call(list.querySelectorAll('[data-tt-msg-id]'), function (li) {
      var id = li.getAttribute('data-tt-msg-id');
      if (vistos[id]) {
        li.parentNode.removeChild(li);
      } else {
        vistos[id] = true;
      }
    });
  }

  function nearBottom(el) {
    return el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_PX;
  }

  function toBottom(el) {
    el.scrollTop = el.scrollHeight;
  }

  // La lista a la que apunta un sondeo o un formulario: su selector, si no la
  // del mismo hilo, si no la única de la página.
  function listFor(el, attr) {
    var sel = el.getAttribute(attr);
    var list = null;
    if (sel) {
      try { list = document.querySelector(sel); } catch (err) { list = null; }
    }
    if (!list) {
      var hilo = el.closest && el.closest('[data-tt-review-thread]');
      list = hilo ? hilo.querySelector('[data-tt-review-list]') : null;
    }
    return list || document.querySelector('[data-tt-review-list]');
  }

  // ————————————————————————————————— refresco incremental
  document.body.addEventListener('htmx:configRequest', function (e) {
    var elt = e.detail && e.detail.elt;
    if (!elt || !elt.closest) return;
    var sondeo = elt.closest('[data-tt-review-poll]');
    if (!sondeo) return;
    var list = listFor(sondeo, 'data-tt-review-poll');
    if (!list) return;
    e.detail.parameters.after = String(lastId(list));
  });

  // Antes de agregar: ¿el usuario estaba abajo, o es su propio envío?
  document.body.addEventListener('htmx:beforeSwap', function (e) {
    var target = e.detail && e.detail.target;
    if (!target || !target.matches || !target.matches('[data-tt-review-list]')) return;
    var cfg = e.detail.requestConfig || {};
    var elt = cfg.elt;
    var propio = !!(elt && elt.closest && elt.closest('form[data-tt-review-form]'));
    target.setAttribute('data-tt-review-stick',
      (propio || nearBottom(scrollerOf(target))) ? '1' : '0');
  });

  // ————————————————————————————————— formulario
  document.body.addEventListener('htmx:afterRequest', function (e) {
    var elt = e.detail && e.detail.elt;
    if (!elt || !elt.matches || !elt.matches('form[data-tt-review-form]')) return;
    if (!e.detail.successful) return;
    var xhr = e.detail.xhr;
    if (xhr && xhr.getResponseHeader && xhr.getResponseHeader('X-Tt-Review-Keep') === '1') return;
    elt.reset();
  });

  // ————————————————————————————————— init
  function init() {
    listsIn(document).forEach(function (list) {
      dedupe(list);
      var scroller = scrollerOf(list);
      if (!list.hasAttribute('data-tt-bound')) {
        list.setAttribute('data-tt-bound', '1');
        toBottom(scroller);
      } else if (list.getAttribute('data-tt-review-stick') === '1') {
        toBottom(scroller);
      }
      list.removeAttribute('data-tt-review-stick');
    });
  }

  document.body.addEventListener('htmx:afterSettle', init);
  // Back/Forward: htmx restaura el body desde un snapshot (nodos nuevos).
  document.body.addEventListener('htmx:historyRestore', init);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.TitulaTecReviewThread = {
    init: init,
    lastId: function (sel) {
      var list = sel ? document.querySelector(sel) : document.querySelector('[data-tt-review-list]');
      return lastId(list);
    }
  };
})();
