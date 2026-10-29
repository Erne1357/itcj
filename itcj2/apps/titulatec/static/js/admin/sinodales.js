/* ===========================================================================
   TitulaTec · Admin — Pestaña «Sinodales» (fase 4).

   Spec 2026-10-21-titulatec-fase4-sinodales §9. Lo que el servidor no puede
   hacer solo en el detalle (`partials/sinodales/_detalle.html`):

     - en «Asignar sinodales», apaga en cada select a los docentes que ya se
       eligieron en otra posición (los 4 deben ser personas distintas; el
       servidor lo vuelve a exigir con 400 + `X-Tt-Error`);
     - «Sustituir» por fila (`data-tt-sin-toggle`): despliega/pliega el
       formulario de esa posición y enfoca su primer campo;
     - lista + detalle (molde de `titulacion.js`, 2026-10-29): la lista conserva
       su scroll interno al elegir una fila o actuar en el detalle (el swap de
       `#tt-sin-body` la reconstruye) y mantiene la fila activa a la vista; si el
       detalle quedó fuera de la pantalla, la página va hasta él; al «Volver a la
       lista» (angosto) la página baja hasta la fila que se tenía abierta. Sin
       scroll suave: lo que no cambia no se mueve.

   Las confirmaciones son `hx-confirm` + `data-tt-confirm-ok`: el puente de
   `titulatec-utils.js` las convierte en `confirmDialog` (nunca el diálogo
   nativo del navegador).

   Contrato (igual que `titulacion.js`): se carga UNA vez desde
   `admin/base_admin.html`; clics y cambios por delegación en `document.body`
   leyendo el DOM VIGENTE; el contenido de `#tt-sin-body` se reemplaza en cada
   swap y el estado se recalcula en `htmx:afterSettle` y
   `htmx:historyRestore`. Sin raíz (`#tt-sin-assign`), no hace nada.

   Expone solo `window.TitulaTecSinodales = { init() }`.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecSinodales) return;   // doble carga del <script>

  function $(id) { return document.getElementById(id); }

  // ————————————————————————————————— selects de «Asignar»
  function selects() {
    var form = $('tt-sin-assign');
    return form ? Array.prototype.slice.call(form.querySelectorAll('select.tt-sin-pick')) : [];
  }

  // Cada docente elegido en una posición queda deshabilitado en las otras.
  function syncPicks() {
    var lista = selects();
    if (!lista.length) return;
    lista.forEach(function (sel) {
      var otros = lista.filter(function (s) { return s !== sel && s.value; })
        .map(function (s) { return s.value; });
      Array.prototype.forEach.call(sel.options, function (opt) {
        opt.disabled = !!opt.value && otros.indexOf(opt.value) !== -1;
      });
    });
  }

  // ————————————————————————————————— delegación (una sola vez)
  document.body.addEventListener('change', function (e) {
    var t = e.target;
    if (t && t.closest && t.closest('#tt-sin-assign select.tt-sin-pick')) syncPicks();
  });

  document.body.addEventListener('click', function (e) {
    var t = e.target;
    if (!t || !t.closest) return;
    var toggle = t.closest('[data-tt-sin-toggle]');
    if (!toggle) return;
    var id = toggle.getAttribute('data-tt-sin-toggle');
    var bloque = $(id);
    if (!bloque) return;
    bloque.hidden = !bloque.hidden;
    document.querySelectorAll('[data-tt-sin-toggle="' + id + '"][aria-expanded]').forEach(function (b) {
      b.setAttribute('aria-expanded', bloque.hidden ? 'false' : 'true');
    });
    if (!bloque.hidden) {
      var primero = bloque.querySelector('select, textarea, input:not([type="hidden"])');
      if (primero) primero.focus();
    }
  });

  // ————————————————————————————————— lista + detalle
  // Lo que se recuerda del swap en curso de `#tt-sin-body`.
  var pendiente = null;   // {scroll, keep, back}

  // Lleva la fila activa a la vista DENTRO de la lista (sin mover la página).
  function filaVisible(lista) {
    var fila = lista.querySelector('.tt-sin-row.is-active');
    if (!fila || lista.scrollHeight <= lista.clientHeight) return;
    var arriba = fila.offsetTop - lista.offsetTop;
    if (arriba < lista.scrollTop) lista.scrollTop = arriba;
    else if (arriba + fila.offsetHeight > lista.scrollTop + lista.clientHeight) {
      lista.scrollTop = arriba + fila.offsetHeight - lista.clientHeight;
    }
  }

  // Alto de la barra superior fija del admin (solo existe bajo 992 px).
  function barra() {
    var b = document.querySelector('.tt-admin-topbar');
    if (!b) return 0;
    var r = b.getBoundingClientRect();
    return r.height > 0 && r.top <= 0 ? r.bottom : 0;
  }

  // Mueve la página solo si `el` quedó fuera de la pantalla (o bajo la barra).
  function aLaVista(el, margen) {
    if (!el) return;
    var tope = barra();
    var r = el.getBoundingClientRect();
    if (r.top < tope || r.top > window.innerHeight - 48) {
      // `instant`: Bootstrap pone `scroll-behavior: smooth` en :root.
      window.scrollTo({ top: Math.max(0, window.pageYOffset + r.top - tope - margen),
                        behavior: 'instant' });
    }
  }

  document.body.addEventListener('htmx:beforeSwap', function (e) {
    var target = e.detail && e.detail.target;
    if (!target || target.id !== 'tt-sin-body') return;
    var elt = e.detail.requestConfig && e.detail.requestConfig.elt;
    var lista = $('tt-sin-list');
    var back = elt && elt.closest ? elt.closest('[data-tt-sin-back]') : null;
    pendiente = {
      scroll: lista ? lista.scrollTop : 0,
      // Elegir una fila o actuar en el detalle: misma lista, mismo scroll.
      // Pestaña, etapa, búsqueda, filtro o página: lista nueva, desde arriba.
      keep: !!(elt && elt.closest && elt.closest('.tt-sin-row, #tt-sin-detail')),
      back: back ? back.getAttribute('data-tt-sin-back') : null,
    };
  });

  document.body.addEventListener('htmx:afterSettle', function (e) {
    var target = e.detail && e.detail.target;
    if (!target || target.id !== 'tt-sin-body' || !pendiente) return;
    var p = pendiente;
    pendiente = null;
    var lista = $('tt-sin-list');
    if (lista && p.keep) {
      lista.scrollTop = p.scroll;
      filaVisible(lista);
    }
    if (p.back) {
      aLaVista($('tt-sin-row-' + p.back), 16);
    } else if ($('tt-sin-detail')) {
      aLaVista(target, 16);
    }
  });

  // ————————————————————————————————— init
  function init() {
    syncPicks();
  }

  document.body.addEventListener('htmx:afterSettle', init);
  // Back/Forward: htmx restaura el body desde un snapshot (nodos nuevos).
  document.body.addEventListener('htmx:historyRestore', init);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.TitulaTecSinodales = { init: init };
})();
