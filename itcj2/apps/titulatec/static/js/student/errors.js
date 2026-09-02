/* ===========================================================================
   errors.js — un solo sitio donde el alumno se entera de que algo falló.

   Por qué existe
   --------------
   Cada página del alumno traía (o no) su propio listener de
   `htmx:responseError`, con tres resultados distintos:

     · documents.html  → leía `X-Tt-Error` y lo mostraba. Bien.
     · cita.html       → lo IGNORABA y mostraba "No se pudo completar la acción".
     · formato_b.html  → no tenía listener: htmx no hace swap en un 4xx, así que
                         el botón "Enviar Formato B" no hacía NADA visible.

   Ese último caso no necesita un atacante: el alumno está legítimamente en la
   fase 3 con el Formato B abierto, el administrador aprueba y avanza el proceso,
   el alumno pulsa Enviar → 400 de la guarda de fase → cero señal, formulario
   intacto. Reintentará sin entender por qué.

   Al vivir en la base del alumno, cualquier vista nueva lo hereda sin acordarse.

   Nota sobre los acentos: `X-Tt-Error` viaja como cabecera HTTP y Starlette la
   codifica en latin-1, así que el servidor la escribe sin acentos ("se
   habilitara"). Es deuda conocida y compartida con el lado admin; no se
   compensa aquí para no inventar un texto distinto del que el servidor mandó.

   Morph-safe: se registra en `document`, que nunca entra a un swap de htmx, y
   se protege de una doble carga.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecStudentErrors) return;      // guarda de doble carga

  var GENERICO = 'No se pudo completar la accion. Intentalo de nuevo.';

  function mostrar(mensaje) {
    if (window.TitulaTecUtils && TitulaTecUtils.showToast) {
      TitulaTecUtils.showToast(mensaje, 'danger');
      return;
    }
    // Sin utils no hay toast, pero callar es peor que un fallback feo.
    console.error('[titulatec]', mensaje);
  }

  document.addEventListener('htmx:responseError', function (e) {
    var xhr = e.detail && e.detail.xhr;
    var msg = '';
    try {
      msg = (xhr && xhr.getResponseHeader('X-Tt-Error')) || '';
    } catch (_) { /* cabecera ausente o XHR en un estado raro */ }
    mostrar(msg || GENERICO);
  });

  // Un fallo de red no llega como responseError y tambien dejaba al alumno a
  // ciegas (boton pulsado, nada ocurre).
  document.addEventListener('htmx:sendError', function () {
    mostrar('Sin conexion con el servidor. Revisa tu internet e intentalo de nuevo.');
  });

  window.TitulaTecStudentErrors = true;
})();
