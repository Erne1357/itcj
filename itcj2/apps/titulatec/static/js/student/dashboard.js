/* ===========================================================================
   dashboard.js — acordeón de fases del dashboard del alumno.

   Sustituye a la pantalla /student/fase/{n} (2026-09-02): la descripción de
   cada fase se despliega dentro de la propia lista.

   Lo que NO hace este archivo, a propósito:
     · Abrir el acordeón del deep-link `?fase=N`. Eso lo resuelve el SERVIDOR:
       `_phases_ctx` emite el `aria-expanded` correcto y omite el atributo
       `hidden` del panel. Si el JS fuera el responsable, el alumno vería la
       lista cerrada y un parpadeo al abrirla. Aquí solo se DESPLAZA hasta ella.
     · Tocar la fase actual: su fila no es un <button> y no lleva `data-tt-acc`,
       así que el toggle no puede alcanzarla. La regla vive en el servidor
       (`can_expand`), no en una condición de este archivo.

   Morph-safe: listeners delegados en `document` (que nunca entra a un swap),
   guarda de doble carga por `window.TitulaTecDashboard`, y el auto-scroll se
   marca en el DOM (`data-tt-scrolled`) para no repetirse en cada afterSettle.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecDashboard) return;

  var REDUCED = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function panelOf(btn) {
    var id = btn.getAttribute('aria-controls');
    return id ? document.getElementById(id) : null;
  }

  function setOpen(btn, open) {
    var panel = panelOf(btn);
    var item = btn.closest('.tt-acc-item');
    if (!panel) return;
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    // `hidden` (no una altura de 0) para que el contenido cerrado no sea
    // alcanzable con Tab ni por lector de pantalla.
    panel.hidden = !open;
    if (item) item.classList.toggle('is-open', open);
    if (open) {
      // Re-dispara la entrada del contenido: es la misma primitiva del design
      // system (tt-anim-in), que ya degrada a fade con prefers-reduced-motion.
      var inner = panel.firstElementChild;
      if (inner && inner.classList.contains('tt-anim-in')) {
        inner.classList.remove('tt-anim-in');
        void inner.offsetWidth;               // fuerza reflow: sin esto no re-anima
        inner.classList.add('tt-anim-in');
      }
    }
  }

  function toggle(btn) {
    setOpen(btn, btn.getAttribute('aria-expanded') !== 'true');
  }

  function onClick(e) {
    var goto = e.target.closest ? e.target.closest('[data-tt-acc-goto]') : null;
    if (goto) {
      var card = document.getElementById('tt-fase-actual');
      if (card) {
        e.preventDefault();
        scrollTo(card);
        // El foco va a la tarjeta (tabindex="-1") para que el teclado y el
        // lector de pantalla sigan al mismo sitio que el ojo.
        try { card.focus({ preventScroll: true }); } catch (err) { card.focus(); }
      }
      return;
    }
    var btn = e.target.closest ? e.target.closest('[data-tt-acc]') : null;
    if (btn) toggle(btn);
  }

  // Teclado del patrón APG: flechas / Inicio / Fin recorren las cabeceras.
  // Enter y Espacio ya los da el <button> nativo; no se reimplementan.
  function onKeydown(e) {
    var btn = e.target.closest ? e.target.closest('[data-tt-acc]') : null;
    if (!btn) return;
    var keys = ['ArrowDown', 'ArrowUp', 'Home', 'End'];
    if (keys.indexOf(e.key) === -1) return;

    var root = btn.closest('[data-tt-acc-root]');
    if (!root) return;
    var all = Array.prototype.slice.call(root.querySelectorAll('[data-tt-acc]'));
    var i = all.indexOf(btn);
    if (i === -1) return;

    var next;
    if (e.key === 'ArrowDown') next = all[(i + 1) % all.length];
    else if (e.key === 'ArrowUp') next = all[(i - 1 + all.length) % all.length];
    else if (e.key === 'Home') next = all[0];
    else next = all[all.length - 1];

    if (next) { e.preventDefault(); next.focus(); }
  }

  function scrollTo(el) {
    try {
      el.scrollIntoView({ behavior: REDUCED ? 'auto' : 'smooth', block: 'center' });
    } catch (err) {
      el.scrollIntoView();
    }
  }

  /* Deep-link `?fase=N`: el servidor ya la dejó abierta y resaltada
     (`is_target`); aquí solo la traemos a la vista. Una sola vez por documento
     — si no, cada htmx:afterSettle robaría el scroll al alumno. */
  function init() {
    var root = document.querySelector('[data-tt-acc-root]');
    if (!root || root.hasAttribute('data-tt-scrolled')) return;
    root.setAttribute('data-tt-scrolled', '1');

    var target = root.querySelector('.tt-acc-item.is-target');
    if (!target) return;
    // Si el deep-link apunta a la fase ACTUAL, la fila no se despliega: lo que
    // hay que enseñar es la tarjeta grande, no la fila.
    var dest = target.classList.contains('is-current')
      ? (document.getElementById('tt-fase-actual') || target)
      : target;
    // rAF: el layout del hero/rejilla debe estar resuelto o el scroll cae corto.
    window.requestAnimationFrame(function () { scrollTo(dest); });
  }

  document.addEventListener('click', onClick);
  document.addEventListener('keydown', onKeydown);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  document.body.addEventListener('htmx:afterSettle', init);

  window.TitulaTecDashboard = { toggle: toggle, setOpen: setOpen };
})();
