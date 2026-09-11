/* ===========================================================================
   TitulaTec — inscripción pública: muestra el campo de carrera libre cuando el
   visitante elige "mi carrera no aparece". El servidor revalida TODO (§4.3 del
   diseño de la encuesta, mismo criterio aquí): esto es comodidad, no defensa.

   Delegado en `document` y registrado UNA vez: Idiomorph reemplaza el
   formulario entero en cada error (`hx-swap="outerHTML"`) y un listener por
   nodo moriría con él. PROHIBIDO `data-tt-bound`: Idiomorph sincroniza
   atributos y lo borraría.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecEnrollPublic) return;      // guarda de doble carga

  function sync() {
    var sel = document.querySelector('[data-tt-enroll="program"]');
    var wrap = document.querySelector('[data-tt-enroll="program-text-wrap"]');
    if (!sel || !wrap) { return; }
    wrap.hidden = sel.value !== '__other__';
  }

  document.addEventListener('change', function (ev) {
    if (ev.target && ev.target.matches && ev.target.matches('[data-tt-enroll="program"]')) {
      sync();
    }
  });
  document.addEventListener('htmx:afterSettle', sync);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', sync);
  } else {
    sync();
  }

  window.TitulaTecEnrollPublic = true;
})();
