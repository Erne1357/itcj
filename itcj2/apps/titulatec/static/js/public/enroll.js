/* ===========================================================================
   TitulaTec — inscripción pública.

   Hasta 2026-09-21 este archivo mostraba/ocultaba el campo de carrera libre
   cuando el visitante elegía "mi carrera no aparece"
   (`data-tt-enroll="program-text-wrap"`). Esa opción se eliminó de raíz: la
   carrera ahora es obligatoria y siempre del catálogo (`core_programs`),
   validada en el servidor (`pages/public.py::enroll_submit`) contra un id
   inventado o inexistente, no solo contra que tenga forma de dígito.

   El archivo queda vacío (con el guardado de doble carga, mismo patrón que el
   resto de la app) porque `public/enroll.html` lo sigue cargando y tocar esa
   plantilla no es parte de este cambio.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecEnrollPublic) return;      // guarda de doble carga
  window.TitulaTecEnrollPublic = true;
})();
