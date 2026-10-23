/* ===========================================================================
   TitulaTec · Admin — Pestaña «Titulación» (Formato B, fase 3).

   Spec 2026-10-21-titulatec-fase3-formato-b-titulacion §8.2. Lo que el
   servidor no puede hacer solo en el detalle (`partials/titulacion/_detalle.html`):

     - ⚑ por campo editable: despliega su nota (y la habilita: una caja
       deshabilitada no viaja en el POST), cuenta los marcados en «Regresar con
       observaciones (N)» y deshabilita «Aprobar» con uno o más;
     - antes de «Observar» del Anexo III (`#tt-anx-observe`) exige el motivo
       (`#tt-anx-reason`), con el mismo mecanismo de captura;
     - antes de «Regresar» exige al menos una observación y que cada campo
       marcado tenga su nota (en CAPTURA: el listener de htmx vive en el propio
       botón y, en burbuja, ya habría abierto el `hx-confirm`). El servidor lo
       vuelve a exigir (400 + `X-Tt-Error`);
     - lápiz «Corregir» (`data-tt-tit-toggle`): despliega/pliega el form del
       registro;
     - lista + detalle (2026-10-23): la lista conserva su scroll interno al
       elegir una fila o dictaminar (el swap de `#tt-tit-body` cambia su contenido y
       la reconstruye) y mantiene la fila activa a la vista; si el detalle quedó
       arriba de la pantalla, la página sube hasta él; al «Volver a la lista»
       (angosto) la página baja hasta la fila que se tenía abierta. Sin scroll
       suave: lo que no cambia no se mueve.

   Las confirmaciones son `hx-confirm` + `data-tt-confirm-ok`: el puente de
   `titulatec-utils.js` las convierte en `confirmDialog` (nunca el diálogo
   nativo del navegador).

   Contrato (igual que `doc-viewer.js`): se carga UNA vez desde
   `admin/base_admin.html`, después de `doc-viewer.js`; clics por delegación en
   `document.body` leyendo el DOM VIGENTE; el contenido de `#tt-tit-body` se
   reemplaza en cada swap y el estado se recalcula en `htmx:afterSettle`,
   `htmx:historyRestore` y `htmx:afterRequest` (htmx re-habilita lo que
   deshabilitó `hx-disabled-elt` sin mirar las marcas).

   Expone solo `window.TitulaTecTitulacion = { init() }`.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecTitulacion) return;   // doble carga del <script>

  function $(id) { return document.getElementById(id); }

  function toast(msg) {
    if (window.TitulaTecUtils) window.TitulaTecUtils.showToast(msg, 'danger');
  }

  // Cancela el clic antes de que llegue al botón (y a su listener de htmx).
  function cortar(e) {
    e.preventDefault();
    e.stopPropagation();
  }

  // ————————————————————————————————— banderas ⚑
  function banderas() {
    var root = $('tt-tit-review');
    return root ? Array.prototype.slice.call(root.querySelectorAll('.tt-tit-flag')) : [];
  }

  function marcadas() {
    return banderas().filter(function (b) { return b.getAttribute('aria-pressed') === 'true'; });
  }

  function cajaDe(bandera) {
    var box = $('tt-tit-note-' + bandera.getAttribute('data-field'));
    return box ? box.querySelector('textarea') : null;
  }

  function marcar(bandera, on) {
    bandera.setAttribute('aria-pressed', on ? 'true' : 'false');
    bandera.classList.toggle('is-on', on);
    var campo = bandera.closest('.tt-tit-field');
    if (campo) campo.classList.toggle('is-flagged', on);
    var box = $('tt-tit-note-' + bandera.getAttribute('data-field'));
    if (!box) return;
    box.hidden = !on;
    var caja = box.querySelector('textarea');
    if (!caja) return;
    caja.disabled = !on;            // desmarcar conserva el texto pero no lo envía
    if (on) caja.focus();
  }

  function enVuelo() {
    var a = $('tt-tit-approve');
    var o = $('tt-tit-observe');
    return !!((a && a.classList.contains('htmx-request'))
      || (o && o.classList.contains('htmx-request')));
  }

  // Conteo en «Regresar con observaciones (N)» y «Aprobar» apagado con marcas.
  // Con una petición en vuelo manda htmx (`hx-disabled-elt`); al terminar,
  // `htmx:afterRequest` vuelve a llamar aquí.
  function sync() {
    var n = marcadas().length;
    var badge = $('tt-tit-obs-count');
    if (badge) badge.textContent = n > 0 ? ' (' + n + ')' : '';
    var aprobar = $('tt-tit-approve');
    if (!aprobar || enVuelo()) return;
    aprobar.disabled = n > 0;
    aprobar.title = n > 0 ? 'Quita las marcas ⚑ para aprobar.' : '';
  }

  // ————————————————————————————————— lista + detalle
  // Lo que se recuerda del swap en curso de `#tt-tit-body`.
  var pendiente = null;   // {scroll, keep, back}

  function detalle() {
    return document.querySelector('#tt-tit-body .tt-tit-detail');
  }

  // Lleva la fila activa a la vista DENTRO de la lista (sin mover la página).
  function filaVisible(lista) {
    var fila = lista.querySelector('.tt-tit-row.is-active');
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

  // Sube la página si `el` quedó arriba de la pantalla (o debajo de la barra),
  // o la baja si quedó abajo. `margen`: aire sobre el elemento.
  function aLaVista(el, margen) {
    if (!el) return;
    var tope = barra();
    var r = el.getBoundingClientRect();
    if (r.top < tope || r.top > window.innerHeight - 48) {
      // `instant`: Bootstrap pone `scroll-behavior: smooth` en :root y un
      // recorrido animado de miles de píxeles marea más de lo que orienta.
      window.scrollTo({ top: Math.max(0, window.pageYOffset + r.top - tope - margen),
                        behavior: 'instant' });
    }
  }

  document.body.addEventListener('htmx:beforeSwap', function (e) {
    var target = e.detail && e.detail.target;
    if (!target || target.id !== 'tt-tit-body') return;
    var elt = e.detail.requestConfig && e.detail.requestConfig.elt;
    var lista = $('tt-tit-list');
    var back = elt && elt.closest ? elt.closest('[data-tt-tit-back]') : null;
    pendiente = {
      scroll: lista ? lista.scrollTop : 0,
      // Elegir una fila o dictaminar: misma lista, mismo scroll. Pestaña,
      // búsqueda, carrera o página: lista nueva, desde arriba.
      keep: !!(elt && elt.closest && elt.closest('.tt-tit-row, .tt-tit-detail, #tt-tit-registro')),
      back: back ? back.getAttribute('data-tt-tit-back') : null,
    };
  });

  document.body.addEventListener('htmx:afterSettle', function (e) {
    var target = e.detail && e.detail.target;
    if (!target || target.id !== 'tt-tit-body' || !pendiente) return;
    var p = pendiente;
    pendiente = null;
    var lista = $('tt-tit-list');
    if (lista && p.keep) {
      lista.scrollTop = p.scroll;
      filaVisible(lista);
    }
    if (p.back) {
      aLaVista($('tt-tit-row-' + p.back) || $('tt-anx-row-' + p.back), 16);
    } else if (detalle()) {
      aLaVista(target, 16);
    }
  });

  // ————————————————————————————————— delegación (una sola vez)
  // «Regresar con observaciones»: al menos una observación y cada campo marcado
  // con su nota. En CAPTURA, antes del `hx-confirm` del botón.
  document.body.addEventListener('click', function (e) {
    var t = e.target;
    if (!t || !t.closest) return;
    // Vista «Anexo III»: el motivo es obligatorio antes de abrir el `hx-confirm`
    // (el servidor lo vuelve a exigir: 200 con el error en el formulario).
    if (t.closest('#tt-anx-observe')) {
      var motivo = $('tt-anx-reason');
      if (!motivo || !motivo.value.trim()) {
        cortar(e);
        toast('Escribe el motivo de la observación.');
        if (motivo) motivo.focus();
      }
      return;
    }
    if (!t.closest('#tt-tit-observe')) return;
    var sinNota = marcadas().filter(function (b) {
      var caja = cajaDe(b);
      return !caja || !caja.value.trim();
    })[0];
    if (sinNota) {
      cortar(e);
      toast('Escribe la observación de cada campo marcado.');
      var caja = cajaDe(sinNota);
      if (caja) caja.focus();
      return;
    }
    var general = $('tt-tit-general');
    if (!marcadas().length && !(general && general.value.trim())) {
      cortar(e);
      toast('Marca al menos un campo con ⚑ o escribe una nota general.');
      if (general) general.focus();
    }
  }, true);

  document.body.addEventListener('click', function (e) {
    var t = e.target;
    if (!t || !t.closest) return;

    var bandera = t.closest('#tt-tit-review .tt-tit-flag');
    if (bandera) {
      marcar(bandera, bandera.getAttribute('aria-pressed') !== 'true');
      sync();
      return;
    }

    var toggle = t.closest('[data-tt-tit-toggle]');
    if (toggle) {
      var id = toggle.getAttribute('data-tt-tit-toggle');
      var bloque = $(id);
      if (!bloque) return;
      bloque.hidden = !bloque.hidden;
      document.querySelectorAll('[data-tt-tit-toggle="' + id + '"][aria-expanded]').forEach(function (b) {
        b.setAttribute('aria-expanded', bloque.hidden ? 'false' : 'true');
      });
      if (!bloque.hidden) {
        var primero = bloque.querySelector('input:not([type="hidden"]), select, textarea');
        if (primero) primero.focus();
      }
      return;
    }

  });

  // ————————————————————————————————— init
  function init() {
    sync();
  }

  document.body.addEventListener('htmx:afterSettle', init);
  // En el siguiente tick: para entonces htmx ya quitó `htmx-request` y
  // re-habilitó lo que `hx-disabled-elt` había apagado.
  document.body.addEventListener('htmx:afterRequest', function () { setTimeout(sync, 0); });
  // Back/Forward: htmx restaura el body desde un snapshot (nodos nuevos).
  document.body.addEventListener('htmx:historyRestore', init);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.TitulaTecTitulacion = { init: init };
})();
