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
     `X-Tt-Review-Keep: 1` y el texto se queda. Con
     `data-tt-close-on-success="<id>"`, además pliega ese panel.

   Chat (rediseño 2026-10-27), sobre estos ganchos:
   - `[data-tt-chat-toggle="<id>"]`: muestra/oculta el panel `#<id>` (voto,
     subida de versión, detalles) y mantiene `aria-expanded` de TODOS sus
     botones al día, también tras un swap fuera de banda. Con
     `data-tt-chat-open` solo abre (el botón de la tarjeta de la versión).
     Al abrir, el foco va a su primer campo.
   - `[data-tt-pick="<id>"]`: abre el selector del `<input type="file">` (que
     no recibe Tab: lo representa el botón). El archivo elegido se ve como
     ficha (`[data-tt-composer-file]`, con quitar) o en la etiqueta del botón
     (`[data-tt-pick-label]`).
   - `[data-tt-composer-text]`: la caja crece con el texto (hasta un tope) y,
     con puntero fino (escritorio), Enter envía y Mayús+Enter salta de línea.
     En pantalla táctil Enter es salto de línea y se envía con el botón.

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
    var cerrar = elt.getAttribute('data-tt-close-on-success');
    if (cerrar) setPanel(document.getElementById(cerrar), false);
  });

  // ————————————————————————————————— paneles del chat (voto, subida, detalles)
  function syncToggles() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-tt-chat-toggle]'), function (btn) {
      var panel = document.getElementById(btn.getAttribute('data-tt-chat-toggle'));
      btn.setAttribute('aria-expanded', panel && !panel.hidden ? 'true' : 'false');
    });
  }

  function setPanel(panel, abrir) {
    if (!panel) return;
    panel.hidden = !abrir;
    syncToggles();
    if (!abrir) return;
    var campo = panel.querySelector('textarea, [data-tt-pick], button[type=submit]');
    if (campo) {
      try { campo.focus({ preventScroll: false }); } catch (err) { campo.focus(); }
    }
  }

  document.body.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-tt-chat-toggle]');
    if (btn) {
      var panel = document.getElementById(btn.getAttribute('data-tt-chat-toggle'));
      setPanel(panel, btn.hasAttribute('data-tt-chat-open') ? true : !!(panel && panel.hidden));
      return;
    }
    var pick = e.target.closest && e.target.closest('[data-tt-pick]');
    if (pick) {
      var input = document.getElementById(pick.getAttribute('data-tt-pick'));
      if (input) input.click();
      return;
    }
    var limpiar = e.target.closest && e.target.closest('[data-tt-composer-clear]');
    if (limpiar) {
      var form = limpiar.closest('form');
      var file = form && form.querySelector('input[type=file]');
      if (file) { file.value = ''; showFile(form, null); }
      var texto = form && form.querySelector('[data-tt-composer-text]');
      if (texto) texto.focus();
    }
  });

  // ————————————————————————————————— archivo elegido
  function sizeLabel(n) {
    if (!n) return '';
    return n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
  }

  function showFile(form, file) {
    var texto = file ? file.name + ' · ' + sizeLabel(file.size) : '';
    var ficha = form.querySelector('[data-tt-composer-file]');
    if (ficha) {
      var nombre = ficha.querySelector('[data-tt-composer-file-name]');
      if (nombre) nombre.textContent = texto;
      ficha.hidden = !file;
    }
    var etiqueta = form.querySelector('[data-tt-pick-label]');
    if (etiqueta) {
      etiqueta.textContent = file ? texto : etiqueta.getAttribute('data-tt-pick-label');
      etiqueta.closest('[data-tt-pick]').classList.toggle('has-file', !!file);
    }
  }

  document.body.addEventListener('change', function (e) {
    var input = e.target;
    if (!input.matches || !input.matches('form input[type=file]')) return;
    var form = input.closest('form');
    if (form && (form.querySelector('[data-tt-composer-file]') || form.querySelector('[data-tt-pick-label]'))) {
      showFile(form, input.files && input.files[0] ? input.files[0] : null);
    }
  });

  document.body.addEventListener('reset', function (e) {
    var form = e.target;
    if (!form.matches || !form.matches('form[data-tt-review-form]')) return;
    showFile(form, null);
    var texto = form.querySelector('[data-tt-composer-text]');
    if (texto) setTimeout(function () { autosize(texto); }, 0);   // tras vaciarse
  }, true);

  // ————————————————————————————————— caja de texto
  var MAX_TEXT_PX = 180;

  function autosize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight + 2, MAX_TEXT_PX) + 'px';
    el.style.overflowY = el.scrollHeight + 2 > MAX_TEXT_PX ? 'auto' : 'hidden';
  }

  document.body.addEventListener('input', function (e) {
    if (e.target.matches && e.target.matches('[data-tt-composer-text]')) autosize(e.target);
  });

  var punteroFino = window.matchMedia ? window.matchMedia('(hover: hover) and (pointer: fine)') : null;

  document.body.addEventListener('keydown', function (e) {
    var el = e.target;
    if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
    if (!el.matches || !el.matches('[data-tt-composer-text]')) return;
    if (!punteroFino || !punteroFino.matches) return;
    e.preventDefault();
    var form = el.closest('form');
    if (!form) return;
    var boton = form.querySelector('button[type=submit]');
    var archivo = form.querySelector('input[type=file]');
    var vacio = !el.value.trim() && !(archivo && archivo.files && archivo.files.length);
    if ((boton && boton.disabled) || vacio) return;     // en vuelo, o nada que enviar
    if (form.requestSubmit) form.requestSubmit(boton || undefined);
    else if (boton) boton.click();
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
    syncToggles();
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
