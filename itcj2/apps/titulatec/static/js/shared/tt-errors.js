/* ===========================================================================
   tt-errors.js — errores de HTMX en las paginas PUBLICAS de TitulaTec.

   Por que NO se reutiliza `student/errors.js`
   -------------------------------------------
   Ese modulo pinta `X-Tt-Error` CRUDO (`student/errors.js:49`). Las rutas
   publicas escriben la cabecera percent-codificada (mismo helper `_hdr()` que
   `pages/appointments.py`), asi que un mensaje con acentos —o sea, todos—
   llegaria a pantalla como `n%C3%BAmero`. Aqui se DECODIFICA con
   `TitulaTecUtils.decodeHeaderMsg` (`titulatec-utils.js:227`), que es el patron
   de `admin/base_admin.html:101-108`, no el de `errors.js`.

   Por que existe
   --------------
   htmx NO hace swap en un 4xx y el escucha de `htmx:responseError` es POR BASE:
   `titulatec-utils.js` deliberadamente no trae uno. Una base nueva sin escucha
   propia deja el boton mudo: el visitante pulsa "Enviar" y no ocurre nada
   visible. `htmx:sendError` cubre ademas el fallo de red, que no llega como
   responseError.

   Recordatorio de contrato: un 4xx aqui es para estados SIN formulario que
   pintar. Todo lo que el visitante deba corregir vuelve 200 con el formulario
   re-renderizado; este escucha es la red de seguridad, no el canal normal.

   Morph-safe: se registra en `document` —que nunca entra a un swap de htmx— y
   se protege de una doble carga. Nada de `data-tt-bound`: Idiomorph sincroniza
   atributos y lo borraria.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecPublicErrors) return;      // guarda de doble carga

  var GENERICO = 'No se pudo completar la acción. Inténtalo de nuevo.';
  var SIN_RED = 'Sin conexión con el servidor. Revisa tu internet e inténtalo de nuevo.';

  function mostrar(mensaje) {
    if (window.TitulaTecUtils && TitulaTecUtils.showToast) {
      TitulaTecUtils.showToast(mensaje, 'danger');
      return;
    }
    // Sin utils no hay toast, pero callar es peor que un respaldo feo.
    console.error('[titulatec/public]', mensaje);
  }

  document.addEventListener('htmx:responseError', function (e) {
    var crudo = '';
    try {
      var xhr = e.detail && e.detail.xhr;
      crudo = (xhr && xhr.getResponseHeader('X-Tt-Error')) || '';
    } catch (_) { /* cabecera ausente o XHR en un estado raro */ }
    var msg = (window.TitulaTecUtils && TitulaTecUtils.decodeHeaderMsg(crudo))
              || crudo || GENERICO;
    mostrar(msg);
  });

  document.addEventListener('htmx:sendError', function () {
    mostrar(SIN_RED);
  });

  window.TitulaTecPublicErrors = true;
})();
