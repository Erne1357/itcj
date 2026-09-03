/* ===========================================================================
   TitulaTec · Admin — Expediente del alumno (/admin/processes/{id}).

   Tres cosas, y las tres por delegación en `document`:
     1. acordeón de las 9 fases (abrir/cerrar);
     2. recuerdo de qué fases quedaron abiertas, para que un swap no las cierre;
     3. el modal de mover de fase: pedir motivo antes de rechazar.

   Contrato, igual que `admin/processes.js` y `admin/appointments.js`:
   se carga UNA vez desde `admin/base_admin.html` (el bloque `scripts` no entra
   al morph de `#tt-admin-content`), guarda de doble carga, y NINGUNA guarda
   `data-tt-bound` en el DOM — Idiomorph sincroniza atributos, así que la
   borraría y los listeners se duplicarían.

   Por qué no reusa el acordeón del alumno (`js/student/dashboard.js`): allí la
   fase ACTUAL no se despliega (vive en grande en su propia tarjeta) y hay un
   auto-scroll al deep-link. Aquí la actual sí se despliega y es justo la que
   llega abierta. Son dos comportamientos distintos sobre el mismo CSS.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecExpediente) return;

  // Qué fases están abiertas. Vive AQUÍ y no en el DOM: tras aprobar una fase
  // el servidor devuelve el expediente entero, y sin esto el revisor perdía
  // todo lo que había desplegado para comparar.
  var abiertas = null;   // Set de números de fase, o null = «aún no sé»

  function panelDe(btn) {
    var id = btn.getAttribute('aria-controls');
    return id ? document.getElementById(id) : null;
  }

  function abrir(btn, on) {
    var panel = panelDe(btn);
    if (!panel) return;
    var item = btn.closest('.tt-acc-item');
    btn.setAttribute('aria-expanded', on ? 'true' : 'false');
    // `hidden`, no altura 0: el contenido cerrado no debe ser alcanzable con
    // Tab ni por lector de pantalla.
    panel.hidden = !on;
    if (item) item.classList.toggle('is-open', on);
    if (on) {
      // Re-dispara la entrada: misma primitiva del design system, que ya
      // degrada a fundido con prefers-reduced-motion.
      var dentro = panel.firstElementChild;
      if (dentro && dentro.classList.contains('tt-anim-in')) {
        dentro.classList.remove('tt-anim-in');
        void dentro.offsetWidth;              // reflow: sin esto no re-anima
        dentro.classList.add('tt-anim-in');
      }
    }
  }

  function leerDelDom() {
    var vistas = new Set();
    document.querySelectorAll('#exp-fases [data-tt-acc]').forEach(function (b) {
      if (b.getAttribute('aria-expanded') === 'true') vistas.add(b.getAttribute('data-tt-acc'));
    });
    return vistas;
  }

  function reponer() {
    var botones = document.querySelectorAll('#exp-fases [data-tt-acc]');
    if (!botones.length) { abiertas = null; return; }   // otra página
    if (abiertas === null) { abiertas = leerDelDom(); return; }
    botones.forEach(function (b) {
      var quiero = abiertas.has(b.getAttribute('data-tt-acc'));
      if ((b.getAttribute('aria-expanded') === 'true') !== quiero) abrir(b, quiero);
    });
  }

  document.addEventListener('click', function (e) {
    if (!e.target || !e.target.closest) return;

    var btn = e.target.closest('#exp-fases [data-tt-acc]');
    if (btn) {
      var on = btn.getAttribute('aria-expanded') !== 'true';
      abrir(btn, on);
      if (abiertas === null) abiertas = new Set();
      if (on) abiertas.add(btn.getAttribute('data-tt-acc'));
      else abiertas.delete(btn.getAttribute('data-tt-acc'));
      return;
    }

    // Rechazar sin decir por qué le deja al alumno un «Fase rechazada» a secas
    // en su panel. El servidor también lo exige (400 + X-Tt-Error); esto es
    // para no gastar el viaje.
    var rech = e.target.closest('#exp-rechazar');
    if (rech) {
      var motivo = document.getElementById('exp-motivo');
      if (motivo && !motivo.value.trim()) {
        e.preventDefault();
        e.stopPropagation();
        motivo.focus();
        if (window.TitulaTecUtils) {
          TitulaTecUtils.showToast('Escribe el motivo del rechazo.', 'danger');
        }
      }
    }
  }, true);   // captura: hay que llegar ANTES que htmx al botón de rechazar

  // Al cerrar el modal, el motivo no se queda escrito para la siguiente fase.
  document.addEventListener('hidden.bs.modal', function (e) {
    if (!e.target || e.target.id !== 'exp-modal-fase') return;
    var motivo = document.getElementById('exp-motivo');
    if (motivo) motivo.value = '';
  });

  document.addEventListener('htmx:afterSettle', reponer);
  if (document.readyState !== 'loading') reponer();
  else document.addEventListener('DOMContentLoaded', reponer);

  window.TitulaTecExpediente = { reponer: reponer };
})();
