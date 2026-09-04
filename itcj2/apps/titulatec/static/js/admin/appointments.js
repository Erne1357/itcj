/* ===========================================================================
   TitulaTec · Admin — Citas de cotejo.

   Se carga UNA vez desde `admin/base_admin.html` (el bloque `scripts` no entra
   al morph de `#tt-admin-content`) y no se re-enlaza nunca: todo va por
   delegación en `document`. Mismo contrato que `admin/import.js` y
   `admin/processes.js`.

   Nada de `data-tt-bound`: Idiomorph sincroniza atributos, así que una guarda
   escrita en el DOM la borra el primer swap que no la traiga y los listeners se
   duplicarían.

   Tres cosas:
     1. visor de documentos — `[data-tt-doc]` cambia el `src` del iframe.
     2. modal grande — es GENÉRICO (vive en `{% block modals %}`, fuera del
        morph): sus pestañas y su iframe se pueblan al abrir, leyendo la barra
        de documentos de la ficha viva, y se vacían al cerrar.
     3. `data-tt-fade-key` — anima SOLO lo que cambió tras un swap.
   =========================================================================== */
(function () {
  'use strict';

  if (window.__ttApptWired) return;   // doble carga del <script> (defensa barata)
  window.__ttApptWired = true;

  var FRAME = 'tt-appt-doc-frame';
  var MODAL = 'tt-appt-doc-modal';

  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  // ————————————————————————————————— 1. visor de documentos
  function activar(btn) {
    var url = btn.getAttribute('data-tt-doc');
    if (!url) return;
    var frame = document.getElementById(FRAME);
    if (frame) frame.src = url;
    var bar = btn.closest('#appt-docbar');
    if (bar) $$('[data-tt-doc]', bar).forEach(function (b) {
      b.classList.toggle('is-active', b === btn);
    });
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest ? e.target.closest('#appt-docbar [data-tt-doc]') : null;
    if (btn) { activar(btn); return; }

    // Desplegar/plegar un bloque por id (el form de reagendar). Sustituye al
    // `onclick` inline que había en el parcial.
    var tog = e.target.closest ? e.target.closest('[data-tt-toggle]') : null;
    if (tog) {
      var caja = document.getElementById(tog.getAttribute('data-tt-toggle'));
      if (!caja) return;
      // `toggle` devuelve true si la clase QUEDO puesta, o sea si quedo OCULTO.
      var oculto = caja.classList.toggle('d-none');
      tog.setAttribute('aria-expanded', oculto ? 'false' : 'true');
    }
  });

  // ————————————————————————————————— 2. modal grande (perezoso)
  // El modal no entra al morph, así que no puede venir renderizado con los
  // documentos del alumno: se arma en el momento de abrirlo.
  document.addEventListener('show.bs.modal', function (e) {
    if (!e.target || e.target.id !== MODAL) return;
    var tabs = document.getElementById('tt-appt-doc-modal-tabs');
    var frame = document.getElementById('tt-appt-doc-modal-frame');
    var botones = $$('#appt-docbar [data-tt-doc]');
    if (!tabs || !frame) return;

    tabs.textContent = '';
    var activo = botones.filter(function (b) { return b.classList.contains('is-active'); })[0]
                 || botones[0];
    botones.forEach(function (b) {
      var t = document.createElement('button');
      t.type = 'button';
      t.className = 'btn btn-sm ' + (b === activo ? 'tt-btn-soft is-active' : 'tt-btn-ghost');
      t.textContent = b.getAttribute('data-tt-doc-name') || 'Documento';
      t.addEventListener('click', function () {
        frame.src = b.getAttribute('data-tt-doc');
        $$('button', tabs).forEach(function (o) {
          o.classList.toggle('is-active', o === t);
          o.classList.toggle('tt-btn-soft', o === t);
          o.classList.toggle('tt-btn-ghost', o !== t);
        });
      });
      tabs.appendChild(t);
    });
    if (activo) frame.src = activo.getAttribute('data-tt-doc');
  });

  // Al cerrar se vacía: si no, el PDF se queda cargado detrás del backdrop y
  // vuelve a pedirse en cada apertura.
  document.addEventListener('hidden.bs.modal', function (e) {
    if (!e.target || e.target.id !== MODAL) return;
    var frame = document.getElementById('tt-appt-doc-modal-frame');
    if (frame) frame.removeAttribute('src');
    var tabs = document.getElementById('tt-appt-doc-modal-tabs');
    if (tabs) tabs.textContent = '';
  });

  // ————————————————————————————————— 3. animar SOLO lo que cambió
  //
  // Regla del usuario: «si algo no cambia, que no se mueva». El shell entero
  // tiene un `data-tt-view` constante, así que `titulatec-utils.js` nunca lo
  // re-anima; aquí se marca con `.tt-enter` (solo opacidad, .18s) la zona cuya
  // `data-tt-fade-key` cambió — o que no existía antes.
  //
  // Con `morph:outerHTML` Idiomorph CONSERVA los nodos y les sincroniza los
  // atributos, así que comparar la clave antes/después es comparar contenido,
  // no identidad de nodo.
  var _antes = null;

  function claves() {
    var m = {};
    $$('[data-tt-fade-key]').forEach(function (el) {
      if (el.id) m[el.id] = el.getAttribute('data-tt-fade-key');
    });
    return m;
  }

  // Solo los swaps de la propia agenda: los del menu admin traen la vista entera
  // nueva y ya los anima `titulatec-utils.js` con `tt-anim-in`.
  function esDeCitas(t) { return !!(t && t.id === 'appt-shell'); }

  document.body.addEventListener('htmx:beforeSwap', function (e) {
    var t = e.detail && e.detail.target;
    _antes = esDeCitas(t) ? claves() : null;
  });

  document.body.addEventListener('htmx:afterSwap', function () {
    if (!_antes) return;
    var previo = _antes;
    _antes = null;
    var fichaCambio = false;
    $$('[data-tt-fade-key]').forEach(function (el) {
      if (!el.id) return;
      if (previo[el.id] === el.getAttribute('data-tt-fade-key')) return;   // igual: quieto
      if (el.id === 'appt-detail') fichaCambio = true;
      el.classList.remove('tt-enter');
      void el.offsetWidth;                       // reinicia la animación
      el.classList.add('tt-enter');
    });
    if (fichaCambio) traerLaFichaAlaVista();
  });

  // — Móvil: llevar la ficha a la vista cuando de verdad cambió —
  //
  // Bajo 992 px el layout se apila y la ficha va ARRIBA, así que tocar a un
  // alumno desde «Por agendar» —que en móvil está al final de la página— cambiaba
  // la ficha 936 px por encima del scroll: medido a 390 px, el usuario tocaba un
  // nombre y aparentemente no pasaba nada.
  //
  // Solo se dispara cuando la clave de `#appt-detail` cambió (nunca en un no-op) y
  // solo en el layout apilado: a partir de 992 px la ficha está al lado de la
  // lista y siempre a la vista, así que ahí mover el scroll sería justo el
  // movimiento gratuito que este trabajo viene a quitar.
  function traerLaFichaAlaVista() {
    var ficha = document.getElementById('appt-detail');
    if (!ficha) return;
    try {
      if (window.matchMedia('(min-width: 992px)').matches) return;
      var r = ficha.getBoundingClientRect();
      if (r.top >= 0 && r.top < window.innerHeight * 0.5) return;   // ya se ve
      var quieto = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      ficha.scrollIntoView({ block: 'start', behavior: quieto ? 'auto' : 'smooth' });
    } catch (_) { /* sin matchMedia utilizable: mejor no tocar el scroll */ }
  }

  document.addEventListener('animationend', function (e) {
    if (e.target && e.target.classList && e.target.classList.contains('tt-enter')) {
      e.target.classList.remove('tt-enter');
    }
  }, true);

  // ————————————————————————————————— 4. arrastrar un alumno a un lugar libre
  //
  // Es un AÑADIDO al camino de clic, nunca el único: el arrastre nativo del
  // navegador no existe en táctil y no se puede hacer con teclado. Quien no
  // pueda arrastrar sigue teniendo «Mover de franja» en la ficha y «pulsar el
  // alumno, luego picar el lugar» en la cola, que son los caminos que ya
  // funcionaban y que los tests cubren.
  //
  // Todo por delegación en `document`, como el resto del módulo: el tablero se
  // reemplaza entero en cada swap, así que enlazar nodos concretos duraría
  // hasta la primera acción.
  var _arrastrando = null;   // { pid, nombre }

  function _drop(el) { return el && el.closest ? el.closest('[data-tt-drop]') : null; }

  document.addEventListener('dragstart', function (e) {
    var origen = e.target.closest ? e.target.closest('[data-tt-drag]') : null;
    if (!origen) return;
    _arrastrando = {
      pid: origen.getAttribute('data-tt-drag'),
      nombre: origen.getAttribute('data-tt-drag-name') || 'el alumno'
    };
    origen.classList.add('is-dragging');
    document.body.classList.add('tt-dragging');
    try {
      // Firefox exige que se escriba ALGO en el dataTransfer o no arranca.
      e.dataTransfer.setData('text/plain', _arrastrando.pid);
      e.dataTransfer.effectAllowed = 'move';
    } catch (_) { /* navegador sin dataTransfer utilizable */ }
  });

  document.addEventListener('dragend', function (e) {
    var origen = e.target.closest ? e.target.closest('[data-tt-drag]') : null;
    if (origen) origen.classList.remove('is-dragging');
    document.body.classList.remove('tt-dragging');
    _marcar(null);
    _arrastrando = null;
  });

  // El resaltado se lleva en UNA variable, no quitando la clase en `dragleave`.
  //
  // `dragenter`/`dragleave` se disparan tambien al cruzar entre los HIJOS del
  // destino, asi que quitar la clase en cada `dragleave` la hace parpadear y, en
  // la practica, desaparecer justo cuando el cursor esta encima. Medido: al
  // soltar, `.is-drop-over` estaba en cero elementos.
  var _sobre = null;

  function _marcar(destino) {
    if (_sobre === destino) return;
    if (_sobre) _sobre.classList.remove('is-drop-over');
    _sobre = destino;
    if (_sobre) _sobre.classList.add('is-drop-over');
  }

  document.addEventListener('dragover', function (e) {
    if (!_arrastrando) return;
    var destino = _drop(e.target);
    if (!destino) { _marcar(null); return; }
    // Sin `preventDefault` el navegador NO considera el elemento un destino
    // válido y el cursor sigue diciendo "prohibido".
    e.preventDefault();
    try { e.dataTransfer.dropEffect = 'move'; } catch (_) { /* nada */ }
    _marcar(destino);
  });

  document.addEventListener('drop', function (e) {
    if (!_arrastrando) return;
    var destino = _drop(e.target);
    if (!destino) return;
    e.preventDefault();
    _marcar(null);

    // La URL viene con un hueco para el id, porque el destino no sabe a quién
    // va a recibir hasta que alguien lo suelta encima.
    var url = (destino.getAttribute('data-tt-drop-url') || '')
                .replace('@PID@', encodeURIComponent(_arrastrando.pid));
    var quien = _arrastrando.nombre;
    _arrastrando = null;
    document.body.classList.remove('tt-dragging');
    if (!url || !window.htmx) return;

    // Mismo contrato que el clic: POST que devuelve el shell entero. Así el
    // arrastre y el clic no pueden divergir en lo que hacen.
    htmx.ajax('POST', url, {
      target: '#appt-shell',
      swap: 'morph:outerHTML',
      indicator: '#appt-skel'
    });
    var say = document.getElementById('appt-say');
    if (say) say.textContent = 'Moviendo a ' + quien + '…';
  });
})();
