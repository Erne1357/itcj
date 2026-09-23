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
   codifica en latin-1, así que un mensaje con acentos llega como bytes que no
   son UTF-8 válido. El lado admin ya lo resolvió percent-codificando en el
   servidor (`pages/appointments.py::_hdr`) y decodificando en el cliente
   (`titulatec-utils.js::decodeHeaderMsg`), y las rutas del auto-agendado del
   alumno hacen lo mismo: sus mensajes vienen de `SelfBookingService` y de los
   errores de dominio, que están escritos en español de ventanilla y llevan
   acentos («Cancélala», «más adelante»).

   Por eso aquí se decodifica. Es seguro para las rutas del alumno que todavía
   escriben la cabecera EN CRUDO (la guarda de fase, los errores de subida):
   `decodeURIComponent` sobre un texto sin `%` es la identidad, y si lo tuviera
   —un `%` suelto la haría lanzar— el try/catch devuelve el original. O sea:
   ninguna ruta empeora, y las nuevas se leen bien.

   Morph-safe: se registra en `document`, que nunca entra a un swap de htmx, y
   se protege de una doble carga.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecStudentErrors) return;      // guarda de doble carga

  var GENERICO = 'No se pudo completar la accion. Intentalo de nuevo.';

  // El servidor percent-codifica los mensajes nuevos (ver la cabecera del
  // archivo). Se reusa el helper de los utils cuando está, para no tener dos
  // decodificadores que puedan divergir; el respaldo cubre el orden de carga.
  function decodificar(raw) {
    if (!raw) return '';
    if (window.TitulaTecUtils && TitulaTecUtils.decodeHeaderMsg) {
      return TitulaTecUtils.decodeHeaderMsg(raw);
    }
    try { return decodeURIComponent(raw); } catch (_) { return raw; }
  }

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
    mostrar(decodificar(msg) || GENERICO);
  });

  // Un fallo de red no llega como responseError y tambien dejaba al alumno a
  // ciegas (boton pulsado, nada ocurre).
  document.addEventListener('htmx:sendError', function () {
    mostrar('Sin conexion con el servidor. Revisa tu internet e intentalo de nuevo.');
  });

  window.TitulaTecStudentErrors = true;
})();
