/* ===========================================================================
   TitulaTec · Admin — Bandeja de Procesos.

   Qué resuelve
   ------------
   La tabla conserva UNA lente de cliente: el orden por columna, que reordena
   las filas de la página visible. Buscar, filtrar por fase y paginar son del
   SERVIDOR desde 2026-10-04 (spec titulatec-paginacion §7): con la tabla
   paginada, un filtro de cliente solo vería las 50 filas de la página. El
   buscador (`#proc-q`) y las franjas del funnel hacen `hx-get` con los
   filtros vigentes; aquí no se tocan.
   El tablero necesita además que alguien le fije el alto al viewport y le
   pinte las sombras de "hay más".

   Contrato (igual que import.js)
   ------------------------------
   · Se carga UNA vez desde `admin/base_admin.html`, en el bloque `scripts`, que
     no entra al swap.
   · Guarda de doble carga (`window.TitulaTecProcesses`).
   · TODOS los listeners son delegados en `document`, que nunca se reemplaza. No
     hay guardas `data-tt-bound`: Idiomorph sincroniza atributos, así que borraría
     la guarda y volveríamos a duplicar listeners.
   · El estado del orden vive en este módulo, no en el DOM, porque el morph
     borra cualquier `data-*` que la respuesta no traiga: así el orden elegido
     SOBREVIVE a un cambio de filtro o de página.
   · Marca con `.tt-enter` solo las filas/tarjetas cuyo id NO existía antes del
     swap. Es la otra mitad de la regla "si algo no cambia, que no se mueva":
     el contenedor ya no se re-anima entero (`data-tt-view`, titulatec-utils.js) y
     aquí se anima únicamente lo que de verdad entró.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecProcesses) return;          // guarda de doble carga

  // Lente de cliente: el orden de la página. Sobrevive al morph porque vive
  // aquí, no en el DOM.
  var estado = { orden: null, dir: -1 };

  // ------------------------------- Tabla -------------------------------
  function laTabla() { return document.getElementById('proc-table'); }

  function filasDe(tabla) {
    // Solo filas de proceso; la fila de estado vacío no se ordena.
    return Array.prototype.slice.call(tabla.tBodies[0].rows)
      .filter(function (r) { return /^proc-row-\d+$/.test(r.id); });
  }

  function ordenar(tabla) {
    if (!estado.orden) return;
    var tbody = tabla.tBodies[0];
    var attr = 'data-' + estado.orden;
    filasDe(tabla).slice().sort(function (a, b) {
      return ((parseFloat(a.getAttribute(attr)) || 0) -
              (parseFloat(b.getAttribute(attr)) || 0)) * estado.dir;
    }).forEach(function (r) { tbody.appendChild(r); });
  }

  function pintarCabeceras(tabla) {
    Array.prototype.forEach.call(tabla.querySelectorAll('th.sortable'), function (th) {
      var activa = !!estado.orden && th.dataset.sort === estado.orden;
      th.classList.toggle('is-sorted', activa);
      var ic = th.querySelector('.bi');
      if (ic) {
        ic.className = 'bi ' + (activa
          ? (estado.dir > 0 ? 'bi-sort-up' : 'bi-sort-down')
          : 'bi-arrow-down-up');
      }
    });
  }

  // ------------------------------ Tablero ------------------------------
  var HUECO_INFERIOR = 22;

  function pintarSombra(scroll) {
    var body = scroll.querySelector('.body');
    if (!body) return;
    var falta = body.scrollHeight - body.clientHeight;
    scroll.classList.toggle('show-top', body.scrollTop > 2);
    scroll.classList.toggle('show-bottom', falta > 2 && body.scrollTop < falta - 2);
  }

  function medirTablero() {
    var board = document.getElementById('proc-board');
    if (!board) return;
    // Una sola zona de scroll horizontal; cada columna scrollea en vertical.
    var arriba = board.getBoundingClientRect().top;
    board.style.height = Math.max(260, window.innerHeight - arriba - HUECO_INFERIOR) + 'px';
    Array.prototype.forEach.call(board.querySelectorAll('.col-scroll'), pintarSombra);
  }

  // --------------------- Marcado de lo REALMENTE nuevo ---------------------
  var SELECTOR_ITEMS = '#proc-table tbody tr[id], #proc-board a.tt-kanban-card[id]';
  var antesDelSwap = null;

  function idsPresentes() {
    var vistos = Object.create(null);
    document.querySelectorAll(SELECTOR_ITEMS).forEach(function (el) { vistos[el.id] = true; });
    return vistos;
  }

  function marcarNuevos(previos) {
    if (!previos) return;
    // Si antes del swap no habia NINGUN item, es que veniamos de otra pestana:
    // ahi la entrada la hace `tt-anim-in` sobre el contenedor entero y marcar
    // ademas cada fila seria animar dos veces lo mismo.
    var habia = false;
    for (var k in previos) { habia = true; break; }
    if (!habia) return;
    document.querySelectorAll(SELECTOR_ITEMS).forEach(function (el) {
      if (!previos[el.id]) el.classList.add('tt-enter');
    });
  }

  // --------------------------- Sincronización ---------------------------
  function sincronizar() {
    var tabla = laTabla();
    if (tabla) {
      // El morph devuelve las filas al orden del servidor: reponemos el elegido.
      ordenar(tabla);
      pintarCabeceras(tabla);
    }
    medirTablero();
    // Segunda pasada tras layout/fuentes: la primera medida del kanban se toma
    // antes de que las fuentes web asienten y sale corta.
    requestAnimationFrame(medirTablero);
  }

  // ------------------------------ Listeners ------------------------------
  // Todos en `document`: sobreviven a cualquier swap sin duplicarse.

  document.addEventListener('click', function (e) {
    if (!e.target || !e.target.closest) return;

    var th = e.target.closest('#proc-table th.sortable');
    if (th) {
      var clave = th.dataset.sort;
      estado.dir = (estado.orden === clave) ? -estado.dir : -1;   // 1er clic: desc
      estado.orden = clave;
      var tabla = laTabla();
      if (tabla) { ordenar(tabla); pintarCabeceras(tabla); }
    }
  });

  // `scroll` no burbujea, pero sí baja en fase de captura.
  document.addEventListener('scroll', function (e) {
    var t = e.target;
    if (!t || !t.classList || !t.classList.contains('body')) return;
    var scroll = t.parentNode;
    if (scroll && scroll.classList && scroll.classList.contains('col-scroll')) pintarSombra(scroll);
  }, true);

  window.addEventListener('resize', medirTablero);

  document.addEventListener('htmx:beforeSwap', function () { antesDelSwap = idsPresentes(); });
  document.addEventListener('htmx:afterSwap', function () {
    marcarNuevos(antesDelSwap);
    antesDelSwap = null;
  });

  // La clase se quita al terminar: así un swap posterior puede volver a
  // marcarla, y ningún nodo se queda con animación pendiente encima.
  document.addEventListener('animationend', function (e) {
    if (e.target && e.target.classList && e.target.classList.contains('tt-enter')) {
      e.target.classList.remove('tt-enter');
    }
  }, true);

  document.addEventListener('htmx:afterSettle', sincronizar);
  if (document.readyState !== 'loading') sincronizar();
  else document.addEventListener('DOMContentLoaded', sincronizar);

  window.TitulaTecProcesses = { sincronizar: sincronizar, estado: estado };
})();
