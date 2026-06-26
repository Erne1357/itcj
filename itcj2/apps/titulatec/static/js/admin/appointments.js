/* ===========================================================================
   TitulaTec · Admin — Citas de cotejo.
   Cargado una vez por base_admin. Usa delegación a nivel document.body, así que
   funciona con cualquier contenido inyectado por HTMX (rejilla del día, detalle
   del alumno) sin re-enlazar nada en cada swap.
     · .freebtn[data-tt-slot]  → fija la hora elegida en el form y resalta el slot
   (El alternar [data-tt-toggle] es genérico y vive en titulatec-utils.js.)
   =========================================================================== */
(function () {
  'use strict';

  document.body.addEventListener('click', function (e) {
    // — Elegir hora libre en la rejilla del día —
    var slotBtn = e.target.closest('.freebtn[data-tt-slot]');
    if (!slotBtn) return;
    var label = slotBtn.getAttribute('data-tt-slot');
    var t = document.getElementById('tt-sched-time');
    if (t) { t.value = label; t.dispatchEvent(new Event('change')); }
    var grid = slotBtn.closest('.tt-hourgrid');
    if (grid) grid.querySelectorAll('.freebtn.is-pick').forEach(function (b) { b.classList.remove('is-pick'); });
    slotBtn.classList.add('is-pick');
  });
})();
