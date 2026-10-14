/* ===========================================================================
   reports.js — Tablero de la jefa de Servicios Escolares (2026-10-14)
   ---------------------------------------------------------------------------
   Spec docs/superpowers/specs/2026-10-14-titulatec-tablero-design.md §7.
   Se carga UNA vez en `admin/base_admin.html`. Morph-safe: todo se enlaza por
   delegación en `document` una sola vez (`window.__ttReportsBound`); lo que
   depende del cuerpo vivo se rehace en `htmx:afterSettle` + `DOMContentLoaded`
   (guarda por raíz `#tt-report-body` y `data-tt-bound`). Sin estado de
   filtros: las ligas ya traen su URL calculada por el servidor.

   Qué hace:
   - TOOLTIP de `[data-tt-tip]` en hover y en foco. Vive como hijo de <body>
     (creado una vez): dentro de #tt-admin-content un `position: fixed` se
     ancla al contenedor animado (.tt-anim-in). Contenido SIEMPRE con
     `textContent`. «Etiqueta: valor» se pinta valor primero.
   - CROSSHAIR de las líneas (`[data-tt-xhair]`): se ajusta al día más
     cercano al puntero (o con flechas, con el plot enfocado) y lista todas
     las series de ese día.
   - IMPRIMIR: `[data-tt-print]` -> `window.print()`.
   - POPOVERS `.tt-rep-pop`: clic fuera o Escape los cierran. Los
     `details[data-tt-keep]` abiertos siguen abiertos tras el swap (el morph
     les quita `open` porque el servidor los manda cerrados).
   - RECARGA: `is-loading` en #tt-report-body desde `htmx:beforeRequest`
     hasta `htmx:afterSettle` (render anterior a opacidad reducida).
   - Chips con `role="button"`: la barra espaciadora también los activa.
   =========================================================================== */
(function () {
  'use strict';

  if (window.__ttReportsBound) return;
  window.__ttReportsBound = true;

  var ROOT_ID = 'tt-report-body';
  var tip = null;          // el tooltip (hijo de <body>)
  var tipOwner = null;     // elemento cuyo tooltip se muestra
  var activePlot = null;   // plot con el crosshair visible
  var keepOpen = [];       // ids de details[data-tt-keep] abiertos antes del swap

  function root() { return document.getElementById(ROOT_ID); }
  function inRoot(el) {
    var r = root();
    return !!(r && el && r.contains(el));
  }
  function isRootTarget(e) {
    var t = e.detail && e.detail.target;
    return !!(t && t.id === ROOT_ID);
  }

  // === TOOLTIP ===============================================================
  function ensureTip() {
    if (tip && tip.isConnected) return tip;
    tip = document.createElement('div');
    tip.className = 'tt-rep-tip';
    tip.id = 'tt-rep-tip';
    tip.setAttribute('role', 'tooltip');
    // Con el plot enfocado, cada flecha cambia de día: que el lector de
    // pantalla lo anuncie (la tabla gemela sigue siendo la vía completa).
    tip.setAttribute('aria-live', 'polite');
    tip.hidden = true;
    document.body.appendChild(tip);
    return tip;
  }

  function clear(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function piece(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text != null) el.textContent = text;
    return el;
  }

  // «Etiqueta: valor» -> valor arriba (fuerte), etiqueta abajo.
  function fillText(text) {
    var t = ensureTip();
    clear(t);
    var i = text.indexOf(': ');
    if (i > 0) {
      t.appendChild(piece('span', 'tt-rep-tip-val', text.slice(i + 2)));
      t.appendChild(piece('span', 'tt-rep-tip-label', text.slice(0, i)));
    } else {
      t.appendChild(piece('span', 'tt-rep-tip-text', text));
    }
  }

  function place(x, y) {
    var t = ensureTip();
    t.hidden = false;
    var m = 14;
    var w = t.offsetWidth;
    var h = t.offsetHeight;
    var left = x + m;
    var top = y - h - m;
    if (left + w > window.innerWidth - 8) left = x - w - m;
    if (left < 8) left = 8;
    if (top < 8) top = y + m;
    if (top + h > window.innerHeight - 8) top = window.innerHeight - h - 8;
    t.style.left = Math.round(left) + 'px';
    t.style.top = Math.round(top) + 'px';
  }

  function hideTip() {
    if (tip) tip.hidden = true;
    tipOwner = null;
  }

  // La fila entera de una barra es la dueña del tooltip (área de toque mayor
  // que la marca); dentro de un plot de líneas manda el crosshair.
  function tipTarget(el) {
    if (!el || !el.closest) return null;
    if (el.closest('[data-tt-xhair]')) return null;
    var t = el.closest('.tt-rep-hlink[data-tt-tip]') || el.closest('[data-tt-tip]');
    return (t && inRoot(t)) ? t : null;
  }

  function showFor(owner, x, y) {
    tipOwner = owner;
    fillText(owner.getAttribute('data-tt-tip') || '');
    place(x, y);
  }

  // === CROSSHAIR =============================================================
  function days(plot) { return plot.querySelectorAll('[data-tt-day]'); }

  function nearestIndex(plot, clientX) {
    var list = days(plot);
    if (!list.length) return -1;
    var r = plot.getBoundingClientRect();
    var pct = r.width ? (clientX - r.left) / r.width * 100 : 0;
    var best = 0;
    var dist = Infinity;
    for (var i = 0; i < list.length; i++) {
      var d = Math.abs(parseFloat(list[i].getAttribute('data-tt-x')) - pct);
      if (d < dist) { dist = d; best = i; }
    }
    return best;
  }

  function hideCrosshair(plot) {
    if (!plot) return;
    var line = plot.querySelector('.tt-rep-xhair');
    if (line) line.hidden = true;
    plot.querySelectorAll('.tt-rep-xdot').forEach(function (dot) { dot.hidden = true; });
    if (activePlot === plot) activePlot = null;
  }

  function showDay(plot, index, clientX, clientY) {
    var list = days(plot);
    var li = list[index];
    if (!li) return;
    if (activePlot && activePlot !== plot) hideCrosshair(activePlot);
    activePlot = plot;
    plot.__ttDay = index;

    var x = parseFloat(li.getAttribute('data-tt-x')) || 0;
    var ys = (li.getAttribute('data-tt-ys') || '').split(',');
    var vals = (li.getAttribute('data-tt-vals') || '').split(',');
    var keys = (plot.getAttribute('data-tt-keys') || '').split('|');
    var labels = (plot.getAttribute('data-tt-labels') || '').split('|');
    var svg = plot.querySelector('svg');
    var vb = svg && svg.viewBox && svg.viewBox.baseVal;
    var H = (vb && vb.height) || 1;

    var line = plot.querySelector('.tt-rep-xhair');
    if (line) { line.hidden = false; line.style.left = x + '%'; }
    plot.querySelectorAll('.tt-rep-xdot').forEach(function (dot, i) {
      var y = parseFloat(ys[i]);
      if (isNaN(y)) { dot.hidden = true; return; }
      dot.hidden = false;
      dot.style.left = x + '%';
      dot.style.top = (y / H * 100) + '%';
    });

    var t = ensureTip();
    clear(t);
    t.appendChild(piece('span', 'tt-rep-tip-head', li.getAttribute('data-tt-head') || ''));
    keys.forEach(function (k, i) {
      var row = piece('span', 'tt-rep-tip-row');
      row.appendChild(piece('span', 'tt-rep-tip-key tt-rep-c--s-' + k));
      row.appendChild(piece('strong', null, vals[i] != null ? vals[i] : ''));
      row.appendChild(piece('span', null, labels[i] || k));
      t.appendChild(row);
    });
    tipOwner = plot;

    if (clientX == null) {
      var r = plot.getBoundingClientRect();
      clientX = r.left + r.width * x / 100;
      clientY = r.top + 12;
    }
    place(clientX, clientY);
  }

  // === PUNTERO Y FOCO ========================================================
  document.addEventListener('pointerover', function (e) {
    var t = tipTarget(e.target);
    if (t && t !== tipOwner) showFor(t, e.clientX, e.clientY);
  });

  document.addEventListener('pointermove', function (e) {
    var plot = e.target && e.target.closest ? e.target.closest('[data-tt-xhair]') : null;
    if (plot && inRoot(plot)) {
      var i = nearestIndex(plot, e.clientX);
      if (i >= 0) showDay(plot, i, e.clientX, e.clientY);
      return;
    }
    if (activePlot) { hideCrosshair(activePlot); hideTip(); }
    // Tras un scroll el tooltip se oculta; al volver a mover el puntero sobre
    // la MISMA fila no hay `pointerover`, así que aquí también se reabre.
    var t = tipTarget(e.target);
    if (t && t !== tipOwner) showFor(t, e.clientX, e.clientY);
    else if (t) place(e.clientX, e.clientY);
  });

  document.addEventListener('pointerout', function (e) {
    if (!tipOwner) return;
    var to = e.relatedTarget;
    if (to && tipOwner.contains(to)) return;
    if (activePlot === tipOwner) hideCrosshair(activePlot);
    hideTip();
  });

  document.addEventListener('focusin', function (e) {
    var el = e.target;
    if (el && el.matches && el.matches('[data-tt-xhair]') && inRoot(el)) {
      var n = days(el).length;
      if (n) showDay(el, el.__ttDay != null ? Math.min(el.__ttDay, n - 1) : n - 1);
      return;
    }
    var t = tipTarget(el);
    if (!t) return;
    var r = t.getBoundingClientRect();
    showFor(t, r.left + Math.min(r.width / 2, 80), r.top);
  });

  document.addEventListener('focusout', function (e) {
    if (!tipOwner) return;
    if (e.relatedTarget && tipOwner.contains(e.relatedTarget)) return;
    if (tipOwner === e.target || tipOwner.contains(e.target)) {
      if (activePlot) hideCrosshair(activePlot);
      hideTip();
    }
  });

  document.addEventListener('keydown', function (e) {
    var el = e.target;
    if (!el || !el.matches) return;

    // Crosshair con teclado.
    if (el.matches('[data-tt-xhair]') && inRoot(el)) {
      var n = days(el).length;
      if (!n) return;
      var cur = el.__ttDay != null ? el.__ttDay : n - 1;
      var next = null;
      if (e.key === 'ArrowRight') next = Math.min(n - 1, cur + 1);
      else if (e.key === 'ArrowLeft') next = Math.max(0, cur - 1);
      else if (e.key === 'Home') next = 0;
      else if (e.key === 'End') next = n - 1;
      else if (e.key === 'Escape') { hideCrosshair(el); hideTip(); return; }
      if (next != null) { e.preventDefault(); showDay(el, next); }
      return;
    }

    // Chips de carrera (`role="button"` en un <a>): Espacio también activa.
    if (e.key === ' ' && el.matches('a[role="button"]') && inRoot(el)) {
      e.preventDefault();
      el.click();
      return;
    }

    // Escape cierra el popover abierto; si el foco estaba dentro, vuelve a su
    // botón.
    if (e.key === 'Escape') {
      var r = root();
      if (r) {
        r.querySelectorAll('.tt-rep-pop[open]').forEach(function (pop) {
          var dentro = pop.contains(el);
          pop.open = false;
          var s = dentro ? pop.querySelector('summary') : null;
          if (s) s.focus();
        });
      }
      hideTip();
    }
  });

  window.addEventListener('scroll', function () { if (tipOwner) { hideCrosshair(activePlot); hideTip(); } },
                          { passive: true, capture: true });

  // === IMPRIMIR Y POPOVERS ===================================================
  document.addEventListener('click', function (e) {
    var el = e.target;
    var btn = el && el.closest ? el.closest('[data-tt-print]') : null;
    if (btn && inRoot(btn)) {
      e.preventDefault();
      hideTip();
      window.print();
      return;
    }
    var r = root();
    if (!r) return;
    r.querySelectorAll('.tt-rep-pop[open]').forEach(function (pop) {
      if (!pop.contains(el)) pop.open = false;
    });
  });

  // === SWAP: RECARGA Y details QUE SE QUEDAN ABIERTOS ========================
  document.body.addEventListener('htmx:beforeRequest', function (e) {
    if (isRootTarget(e)) e.detail.target.classList.add('is-loading');
  });

  function doneLoading() {
    var r = root();
    if (r) r.classList.remove('is-loading');
  }
  document.body.addEventListener('htmx:afterRequest', function (e) {
    if (isRootTarget(e) && !(e.detail && e.detail.successful)) doneLoading();
  });
  ['htmx:responseError', 'htmx:sendError', 'htmx:timeout', 'htmx:abort'].forEach(function (ev) {
    document.body.addEventListener(ev, doneLoading);
  });

  document.body.addEventListener('htmx:beforeSwap', function (e) {
    hideTip();
    if (activePlot) hideCrosshair(activePlot);
    if (!isRootTarget(e)) return;
    keepOpen = [];
    var r = root();
    if (!r) return;
    r.querySelectorAll('details[data-tt-keep][open]').forEach(function (d) {
      if (d.id) keepOpen.push(d.id);
    });
  });

  // `afterSwap` corre antes del primer pintado: el details no parpadea.
  document.body.addEventListener('htmx:afterSwap', function () {
    keepOpen.forEach(function (id) {
      var d = document.getElementById(id);
      if (d && d.tagName === 'DETAILS') d.open = true;
    });
    keepOpen = [];
  });

  // === INIT POR RAÍZ =========================================================
  function init() {
    var r = root();
    if (!r) { hideTip(); return; }
    r.classList.remove('is-loading');
    if (r.getAttribute('data-tt-bound') !== '1') r.setAttribute('data-tt-bound', '1');
    // El <title> de las marcas SVG es el respaldo nativo sin JS; con JS el
    // tooltip propio lo sustituye y el nativo saldría encima, duplicado.
    r.querySelectorAll('.tt-rep-mark > title').forEach(function (t) {
      t.parentNode.removeChild(t);
    });
  }

  document.body.addEventListener('htmx:afterSettle', init);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
