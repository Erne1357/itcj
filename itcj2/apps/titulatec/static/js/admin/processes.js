/* ===========================================================================
   TitulaTec · Admin — Bandeja de Procesos.

   Qué resuelve
   ------------
   La tabla tiene tres lentes de CLIENTE (buscador, orden por columna y filtro
   por franja del funnel) y el tablero necesita que alguien le fije el alto al
   viewport y le pinte las sombras de "hay más". Antes esto vivía DUPLICADO
   inline en `admin/processes.html`, dentro del fragmento que el morph
   reemplaza; este archivo existía en `static/js/admin/` desde hace tiempo pero
   NINGÚN template lo cargaba.

   Por qué el inline no podía quedarse
   -----------------------------------
   Desde que los filtros de la página son HTMX (`morph:outerHTML` sobre
   `#tt-admin-content`), el `<script>` inline se re-ejecuta en cada swap:
     · el IIFE viejo capturaba `rows`, `search` y `funnel` en un closure que tras
       el morph apuntaba a nodos ya reemplazados -> el buscador dejaba de filtrar;
     · y cada re-ejecución añadía OTRO listener a los mismos `th.sortable`, así
       que el primer clic ordenaba dos veces (o sea, al revés).

   Contrato (igual que import.js)
   ------------------------------
   · Se carga UNA vez desde `admin/base_admin.html`, en el bloque `scripts`, que
     no entra al swap.
   · Guarda de doble carga (`window.TitulaTecProcesses`).
   · TODOS los listeners son delegados en `document`, que nunca se reemplaza. No
     hay guardas `data-tt-bound`: Idiomorph sincroniza atributos, así que borraría
     la guarda y volveríamos a duplicar listeners.
   · El estado de las lentes vive en este módulo, no en el DOM, precisamente
     porque el morph borra cualquier `data-*` que la respuesta no traiga. Gracias
     a eso el texto del buscador, el orden y la fase seleccionada SOBREVIVEN a un
     cambio de filtro del servidor (antes se perdían en cada recarga completa).
   · Marca con `.tt-enter` solo las filas/tarjetas cuyo id NO existía antes del
     swap. Es la otra mitad de la regla "si algo no cambia, que no se mueva":
     el contenedor ya no se re-anima entero (`data-tt-view`, titulatec-utils.js) y
     aquí se anima únicamente lo que de verdad entró.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecProcesses) return;          // guarda de doble carga

  // Lentes de cliente. Sobreviven al morph porque viven aquí, no en el DOM.
  //
  // `q` es la consulta NORMALIZADA (recortada y en minúsculas), que es contra lo
  // que se compara `data-search`. `qTexto` es lo que el usuario escribió, tal
  // cual, y es lo único que puede volver al `<input>`: el morph le borra el
  // `value` (la respuesta del servidor no trae ninguno) y si repusiéramos `q`,
  // teclear "ANDREA" y pulsar un filtro le reescribiría su propio texto a
  // "andrea" delante de los ojos. Filtrar y mostrar son cosas distintas.
  var estado = { q: '', qTexto: '', fase: '', orden: null, dir: -1 };

  // ------------------------------- Tabla -------------------------------
  function laTabla() { return document.getElementById('proc-table'); }

  function filasDe(tabla) {
    return Array.prototype.slice.call(tabla.tBodies[0].rows)
      .filter(function (r) { return r.dataset.search !== undefined; });
  }

  function aplicarFiltros() {
    var tabla = laTabla();
    if (!tabla) return;
    var contador = document.getElementById('proc-count');
    var filas = filasDe(tabla), total = filas.length, visibles = 0;

    filas.forEach(function (r) {
      var okTexto = !estado.q || (r.dataset.search || '').indexOf(estado.q) !== -1;
      var okFase = !estado.fase || r.dataset.phase === estado.fase;
      var on = okTexto && okFase;
      r.style.display = on ? '' : 'none';
      if (on) visibles++;
    });

    if (contador) {
      contador.textContent = (visibles === total && !estado.q && !estado.fase)
        ? total + ' proceso(s)'
        : visibles + ' de ' + total + ' proceso(s)';
    }
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

  function pintarFunnel() {
    var funnel = document.getElementById('proc-funnel');
    if (!funnel) return;
    Array.prototype.forEach.call(funnel.querySelectorAll('.seg'), function (s) {
      var esta = !!estado.fase && s.dataset.phase === estado.fase;
      s.classList.toggle('is-sel', esta);
      s.classList.toggle('is-dim', !!estado.fase && !esta);
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
  var SELECTOR_ITEMS = '#proc-table tbody tr[id], #proc-board a[id]';
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
      // El morph resetea el `value` del input (la respuesta no trae ninguno) y
      // devuelve las filas al orden del servidor: reponemos ambas cosas.
      var buscador = document.getElementById('proc-search');
      if (buscador && buscador.value !== estado.qTexto) buscador.value = estado.qTexto;
      ordenar(tabla);
      pintarCabeceras(tabla);
      pintarFunnel();
      aplicarFiltros();
    }
    medirTablero();
    // Segunda pasada tras layout/fuentes: la primera medida del kanban se toma
    // antes de que las fuentes web asienten y sale corta.
    requestAnimationFrame(medirTablero);
  }

  // ------------------------------ Listeners ------------------------------
  // Todos en `document`: sobreviven a cualquier swap sin duplicarse.

  document.addEventListener('input', function (e) {
    var t = e.target;
    if (!t || t.id !== 'proc-search') return;
    estado.qTexto = t.value || '';
    estado.q = estado.qTexto.trim().toLowerCase();
    aplicarFiltros();
  });

  document.addEventListener('click', function (e) {
    if (!e.target || !e.target.closest) return;

    var th = e.target.closest('#proc-table th.sortable');
    if (th) {
      var clave = th.dataset.sort;
      estado.dir = (estado.orden === clave) ? -estado.dir : -1;   // 1er clic: desc
      estado.orden = clave;
      var tabla = laTabla();
      if (tabla) { ordenar(tabla); pintarCabeceras(tabla); }
      return;
    }

    var seg = e.target.closest('#proc-funnel .seg');
    if (seg && !seg.classList.contains('is-empty')) {
      var fase = seg.dataset.phase;
      estado.fase = (estado.fase === fase) ? '' : fase;
      pintarFunnel();
      aplicarFiltros();
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
