/* ===========================================================================
   TitulaTec — Encargados por carrera (2026-09-17).

   Tres trabajos, todos de comodidad: el servidor revalida TODO y la pantalla
   funciona sin una línea de esto (las casillas se marcan, el formulario envía
   y el aviso de reactivación lo vuelve a decir la respuesta).

     1. Buscador de cada selector: oculta las filas que no coinciden.
     2. Contador «2 de 11 · 1 se reactivará».
     3. Aviso previo: cuántas cuentas inactivas se van a reactivar.
     4. Abrir y cerrar la edición en línea de cada encargado.

   CONTRATO DE ESTA APP (CLAUDE.md §4): se carga UNA vez desde
   `admin/base_admin.html` -el bloque `scripts` no entra al morph de
   `#tt-admin-content`- y todo va por delegación en `document`. PROHIBIDO
   `data-tt-bound`: Idiomorph sincroniza atributos y lo borraría, y además este
   parcial se reemplaza entero con `hx-swap="innerHTML"` en cada acción, así que
   un listener por nodo moriría con él.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecOfficers) { return; }        // guarda de doble carga

  var SEL_PICKER = '[data-tt-picker]';

  function texto(el, valor) {
    if (el) { el.textContent = valor; }
  }

  /** Normaliza para buscar sin acentos ni mayúsculas: en esta pantalla los
   *  nombres vienen en mayúsculas con acentos («BARRÓN») y nadie teclea la
   *  tilde al buscar. */
  function plano(s) {
    s = String(s || '').toLowerCase();
    return s.normalize ? s.normalize('NFD').replace(/[̀-ͯ]/g, '') : s;
  }

  /** Filtra las filas de UN selector contra lo tecleado en su buscador. */
  function filtrar(picker) {
    var campo = picker.querySelector('[data-tt-picker-search]');
    var q = plano(campo ? campo.value : '').trim();
    var filas = picker.querySelectorAll('.tt-picker-row');
    var visibles = 0;
    for (var i = 0; i < filas.length; i++) {
      var fila = filas[i];
      var casilla = fila.querySelector('input[type="checkbox"]');
      // Lo ya elegido NUNCA se esconde: si el filtro lo ocultara, el usuario
      // creería que se deseleccionó y no habría forma de quitarlo sin borrar
      // la búsqueda primero.
      var coincide = !q || plano(fila.getAttribute('data-tt-picker-text')).indexOf(q) !== -1;
      var mostrar = coincide || (casilla && casilla.checked);
      fila.hidden = !mostrar;
      if (mostrar) { visibles++; }
    }
    var vacio = picker.querySelector('[data-tt-picker-empty]');
    if (vacio) { vacio.hidden = visibles !== 0; }
  }

  /** Contador de un selector + cuántas de sus casillas marcadas están inactivas. */
  function contar(picker) {
    var casillas = picker.querySelectorAll('input[type="checkbox"]');
    var marcadas = 0;
    var inactivas = 0;
    for (var i = 0; i < casillas.length; i++) {
      if (!casillas[i].checked) { continue; }
      marcadas++;
      var fila = casillas[i].closest('.tt-picker-row');
      if (fila && fila.getAttribute('data-tt-picker-inactive') === '1') { inactivas++; }
    }
    var salida = picker.querySelector('[data-tt-picker-count]');
    if (salida) {
      var t = marcadas + ' de ' + casillas.length;
      if (inactivas > 0) {
        t += ' · ' + inactivas + (inactivas === 1 ? ' se reactivará' : ' se reactivarán');
      }
      texto(salida, t);
      if (inactivas > 0) {
        salida.setAttribute('data-tt-picker-warn', '1');
      } else {
        salida.removeAttribute('data-tt-picker-warn');
      }
    }
    return inactivas;
  }

  /** Recalcula contadores y aviso de UN formulario (el alta o una edición). */
  function sincronizar(form) {
    if (!form) { return; }
    var pickers = form.querySelectorAll(SEL_PICKER);
    var inactivas = 0;
    for (var i = 0; i < pickers.length; i++) {
      inactivas += contar(pickers[i]);
    }
    var aviso = form.querySelector('[data-tt-officers="warn"]');
    if (aviso) {
      aviso.hidden = inactivas === 0;
      // Plural correcto: «1 cuenta» / «3 cuentas». El trozo del medio, con el
      // `<code>`, no se toca desde aquí.
      var una = inactivas === 1;
      texto(aviso.querySelector('[data-tt-officers="warn-head"]'),
            (una ? 'Se reactivará 1 cuenta' : 'Se reactivarán ' + inactivas + ' cuentas'));
      texto(aviso.querySelector('[data-tt-officers="warn-tail"]'),
            (una ? 'Tendrá que cambiarla al entrar.' : 'Tendrán que cambiarla al entrar.'));
    }
  }

  function sincronizarTodo() {
    var forms = document.querySelectorAll('[data-tt-officers="form"], .tt-off-edit');
    for (var i = 0; i < forms.length; i++) { sincronizar(forms[i]); }
    var pickers = document.querySelectorAll(SEL_PICKER);
    for (var j = 0; j < pickers.length; j++) { filtrar(pickers[j]); }
  }

  // ————————————————————————————————————————————————— buscador
  document.addEventListener('input', function (ev) {
    var campo = ev.target && ev.target.closest && ev.target.closest('[data-tt-picker-search]');
    if (!campo) { return; }
    filtrar(campo.closest(SEL_PICKER));
  });

  // Esc limpia el buscador sin tocar lo elegido. `type="search"` lo hace solo
  // en algunos navegadores; aquí es igual en todos.
  document.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Escape') { return; }
    var campo = ev.target && ev.target.closest && ev.target.closest('[data-tt-picker-search]');
    if (!campo || !campo.value) { return; }
    ev.preventDefault();
    campo.value = '';
    filtrar(campo.closest(SEL_PICKER));
  });

  // ————————————————————————————————————————————————— casillas
  document.addEventListener('change', function (ev) {
    var casilla = ev.target;
    if (!casilla || !casilla.closest || casilla.type !== 'checkbox') { return; }
    var picker = casilla.closest(SEL_PICKER);
    if (!picker) { return; }
    sincronizar(casilla.closest('form'));
  });

  // ————————————————————————————————————————————————— edición en línea
  document.addEventListener('click', function (ev) {
    var abrir = ev.target.closest && ev.target.closest('[data-tt-officers="edit"]');
    if (abrir) {
      var id = abrir.getAttribute('aria-controls');
      var form = id && document.getElementById(id);
      if (!form) { return; }
      var abierto = form.hidden;
      form.hidden = !abierto;
      abrir.setAttribute('aria-expanded', abierto ? 'true' : 'false');
      if (abierto) {
        sincronizar(form);
        var buscador = form.querySelector('[data-tt-picker-search]');
        if (buscador) { buscador.focus(); }
      }
      return;
    }
    var cerrar = ev.target.closest && ev.target.closest('[data-tt-officers="cancel"]');
    if (cerrar) {
      var propio = cerrar.closest('.tt-off-edit');
      if (!propio) { return; }
      propio.hidden = true;
      // Devolver el foco al botón que abrió: si no, queda en un nodo oculto.
      var boton = document.querySelector('[aria-controls="' + propio.id + '"]');
      if (boton) {
        boton.setAttribute('aria-expanded', 'false');
        boton.focus();
      }
    }
  });

  // ————————————————————————————————————————————————— arranque y re-arranque
  // `htmx:afterSettle` porque el parcial entero se reemplaza en cada acción:
  // los contadores del marcado nuevo nacen con el valor del servidor y hay que
  // recalcular los «se reactivarán», que el servidor no sabe.
  document.addEventListener('htmx:afterSettle', sincronizarTodo);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', sincronizarTodo);
  } else {
    sincronizarTodo();
  }

  window.TitulaTecOfficers = true;
})();
