/* ===========================================================================
   TitulaTec · Admin — «Información para el alumno» de los requisitos de cotejo
   (partials/cohort/cohort_cotejo_reqs.html, pestaña «Requisitos» de la
   convocatoria).

   Qué hace, todo por delegación en `document`:
     1. Carga Quill 2.0.3 PEREZOSAMENTE (hoja + script de jsDelivr, con SRI) la
        primera vez que alguien abre un bloque: ninguna otra página admin lo
        descarga.
     2. Monta un editor por bloque abierto y lo mantiene sincronizado con el
        `<input type="hidden" name="info_html">` de SU formulario: en cada
        cambio y, además, en la fase de CAPTURA del `submit`, que llega antes de
        que htmx lea el formulario.
     3. Recuerda qué bloques dejó abiertos el usuario y los reabre tras un swap:
        cada guardado reemplaza el parcial entero (`outerHTML`) y la navegación
        admin es morph.

   Contrato de módulo admin (CLAUDE.md §4): una sola carga desde base_admin.html,
   guarda de doble carga, estado en el módulo y NINGUNA marca `data-tt-bound` en
   el DOM (Idiomorph sincroniza atributos y la borraría). Una instancia de Quill
   se reconoce por su nodo de montaje (WeakMap) y se da por muerta si su raíz ya
   no cuelga de él: así un morph que la desmonte no deja ni un editor fantasma
   ni una instancia duplicada.

   Nada de lo que sale de aquí es de confianza: el servidor sanitiza al guardar
   y al pintar (utils/rich_text.py). Este módulo solo produce el HTML.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecCotejoInfo) return;

  var QUILL = {
    js: 'https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.js',
    jsSri: 'sha384-utBUCeG4SYaCm4m7GQZYr8Hy8Fpy3V4KGjBZaf4WTKOcwhCYpt/0PfeEe3HNlwx8',
    css: 'https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.snow.css',
    cssSri: 'sha384-ecIckRi4QlKYya/FQUbBUjS4qp65jF/J87Guw5uzTbO1C1Jfa/6kYmd6dXUF6D7i',
  };

  var BLOQUE = '#cotejo-reqs-body details[data-tt-reqinfo]';

  // Los MISMOS formatos que acepta el servidor (utils/rich_text.py): lo que se
  // pegue con otro formato se descarta al pegar, en vez de «desaparecer» al
  // guardar.
  var FORMATOS = ['bold', 'italic', 'underline', 'list', 'link'];
  var BARRA = [
    ['bold', 'italic', 'underline'],
    [{ list: 'bullet' }, { list: 'ordered' }],
    ['link'],
    ['clean'],
  ];
  // Quill 2 rotula sus botones en inglés («bold», «list: bullet»).
  var ROTULOS = [
    ['button.ql-bold', 'Negritas'],
    ['button.ql-italic', 'Cursivas'],
    ['button.ql-underline', 'Subrayado'],
    ['button.ql-list[value="bullet"]', 'Lista con viñetas'],
    ['button.ql-list[value="ordered"]', 'Lista numerada'],
    ['button.ql-link', 'Insertar liga'],
    ['button.ql-clean', 'Limpiar formato'],
  ];

  var carga = null;               // Promise<Quill> en curso o resuelta; null tras un fallo
  var ajustado = false;           // parches de Quill aplicados
  var editores = new WeakMap();   // nodo de montaje -> instancia de Quill
  var abiertos = new Set();       // `data-tt-reqinfo` que el usuario dejó abiertos

  // ————————————————————————————————— carga perezosa de Quill
  function cargarHoja() {
    return new Promise(function (resolve) {
      if (document.querySelector('link[data-tt-quill]')) { resolve(); return; }
      var link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = QUILL.css;
      link.integrity = QUILL.cssSri;
      link.crossOrigin = 'anonymous';
      link.setAttribute('data-tt-quill', '');
      // La hoja es cosmética: si falla, el editor funciona igual.
      link.onload = link.onerror = function () { resolve(); };
      document.head.appendChild(link);
    });
  }

  function cargarScript() {
    return new Promise(function (resolve, reject) {
      if (window.Quill) { resolve(window.Quill); return; }
      var s = document.createElement('script');
      s.src = QUILL.js;
      s.integrity = QUILL.jsSri;
      s.crossOrigin = 'anonymous';
      s.onload = function () {
        if (window.Quill) resolve(window.Quill);
        else reject(new Error('Quill no quedó registrado'));
      };
      s.onerror = function () {
        s.remove();   // sin esto, el reintento convive con un <script> muerto
        reject(new Error('No se pudo descargar Quill'));
      };
      document.head.appendChild(s);
    });
  }

  function cargarQuill() {
    if (!carga) {
      carga = Promise.all([cargarScript(), cargarHoja()]).then(function (r) {
        ajustarQuill(r[0]);
        return r[0];
      });
      // Un fallo (red, bloqueo, SRI) no se queda guardado: la siguiente
      // apertura lo vuelve a intentar.
      carga.catch(function () { carga = null; });
    }
    return carga;
  }

  function ajustarQuill(Quill) {
    if (ajustado) return;
    ajustado = true;
    var Link = Quill.import('formats/link');
    Link.PROTOCOL_WHITELIST = ['http', 'https', 'mailto'];
    var sanitizar = Link.sanitize;
    Link.sanitize = function (url) {
      return sanitizar.call(this, normalizarLiga(url));
    };
  }

  // Una liga escrita sin esquema («biblioteca.itcj.edu.mx») queda RELATIVA, y el
  // servidor solo acepta http/https/mailto: la quitaría al guardar y la jefa
  // vería desaparecer su liga sin explicación. Se completa aquí.
  function normalizarLiga(url) {
    var v = String(url == null ? '' : url).trim();
    if (!v || /^[a-z][a-z0-9+.\-]*:/i.test(v)) return v;
    if (/^[^\s@\/]+@[^\s@\/]+\.[^\s@\/]+$/.test(v)) return 'mailto:' + v;
    return 'https://' + v.replace(/^\/+/, '');
  }

  // ————————————————————————————————— editores
  function vivo(nodo) {
    var q = editores.get(nodo);
    return !!(q && q.root && nodo.contains(q.root));
  }

  function avisar(bloque, texto, esError) {
    var msg = bloque.querySelector('[data-tt-reqinfo-msg]');
    if (!msg) return;
    msg.textContent = texto || '';
    msg.hidden = !texto;
    msg.classList.toggle('is-error', !!esError);
  }

  function campoDe(bloque) {
    return bloque ? bloque.querySelector('input[name="info_html"]') : null;
  }

  function montar(bloque) {
    var nodo = bloque.querySelector('[data-tt-reqinfo-editor]');
    var campo = campoDe(bloque);
    if (!nodo || !campo || vivo(nodo)) return;
    avisar(bloque, 'Cargando el editor…');
    cargarQuill().then(function (Quill) {
      // Entre la apertura y la descarga pudo llegar un swap (el nodo ya no
      // está) u otra apertura que ya lo montó.
      if (!nodo.isConnected) return;
      if (!vivo(nodo)) crear(Quill, nodo, campo);
      avisar(bloque, '');
    }, function () {
      if (!nodo.isConnected) return;
      avisar(bloque, 'No se pudo cargar el editor. Revisa tu conexión y vuelve a ' +
                     'abrir este bloque; la información guardada no cambió.', true);
    });
  }

  function crear(Quill, nodo, campo) {
    var nombre = nodo.getAttribute('data-tt-reqinfo-nombre') || 'el requisito';
    // Contenido inicial: el HTML que pintó el servidor dentro del nodo, ya
    // sanitizado. Quill 2 lo convierte a su modelo al construirse, y tras un
    // morph que desmontó el editor el nodo vuelve a traer ese HTML fresco.
    var q = new Quill(nodo, {
      theme: 'snow',
      formats: FORMATOS,
      modules: { toolbar: BARRA },
      placeholder: 'Qué debe saber el alumno sobre este requisito…',
    });
    editores.set(nodo, q);
    rotular(q, nombre);
    q.on('text-change', function () { volcar(q, campo); });
  }

  function serializar(q) {
    if (!q.getText().trim()) return '';
    // Quill 2.0.3 escribe CADA espacio como `&nbsp;` en getSemanticHTML (medido
    // en su dist/quill.js). El servidor lo normaliza igual; aquí es para no
    // inflar el tope de 20 000 caracteres.
    return q.getSemanticHTML().replace(/&nbsp;/g, ' ');
  }

  function volcar(q, campo) {
    campo.value = serializar(q);
  }

  function rotular(q, nombre) {
    var barra = q.getModule('toolbar');
    var cont = barra && barra.container;
    if (cont) {
      cont.setAttribute('role', 'toolbar');
      cont.setAttribute('aria-label', 'Formato de la información para el alumno');
      ROTULOS.forEach(function (par) {
        var b = cont.querySelector(par[0]);
        if (!b) return;
        b.setAttribute('aria-label', par[1]);
        b.setAttribute('title', par[1]);
      });
    }
    q.root.setAttribute('role', 'textbox');
    q.root.setAttribute('aria-multiline', 'true');
    q.root.setAttribute('aria-label', 'Información para el alumno sobre ' + nombre);
    var tip = q.theme && q.theme.tooltip;
    if (tip && tip.textbox) {
      tip.textbox.setAttribute('data-link', 'https://');
      tip.textbox.setAttribute('aria-label', 'Dirección de la liga');
    }
  }

  // ————————————————————————————————— eventos
  // El clic en el <summary> es la INTENCIÓN del usuario. No se usa `toggle`
  // para recordarla porque un morph también cierra el bloque (sincroniza `open`)
  // y borraría la memoria justo antes de que `reponer` la necesite.
  document.addEventListener('click', function (e) {
    var sum = e.target && e.target.closest && e.target.closest(BLOQUE + ' > summary');
    if (!sum) return;
    var bloque = sum.parentElement;
    var clave = bloque.getAttribute('data-tt-reqinfo');
    // El de alta no se recuerda: tras agregar, su formulario vuelve vacío.
    if (!clave || clave === 'nuevo') return;
    // El clic llega ANTES de que el navegador invierta `open`.
    if (bloque.open) abiertos.delete(clave);
    else abiertos.add(clave);
  });

  // `toggle` no burbujea: hay que escucharlo en CAPTURA para delegarlo.
  document.addEventListener('toggle', function (e) {
    var bloque = e.target;
    if (!bloque || !bloque.matches || !bloque.matches(BLOQUE) || !bloque.open) return;
    montar(bloque);
  }, true);

  // CAPTURA: llega antes que el listener de htmx en el <form>, que es el que lee
  // los valores. `update()` vacía los cambios que Quill aún no procesó.
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form || !form.closest || !form.closest('#cotejo-reqs-body')) return;
    form.querySelectorAll('[data-tt-reqinfo-editor]').forEach(function (nodo) {
      var campo = campoDe(nodo.closest('details'));
      if (!campo || !vivo(nodo)) return;
      var q = editores.get(nodo);
      q.update('user');
      volcar(q, campo);
    });
  }, true);

  // Tras un swap: reabre lo que el usuario dejó abierto y monta lo abierto que no
  // tenga editor vivo. `montar` es idempotente, así que no importa que además
  // llegue el `toggle`.
  function reponer() {
    document.querySelectorAll(BLOQUE).forEach(function (bloque) {
      if (abiertos.has(bloque.getAttribute('data-tt-reqinfo'))) bloque.open = true;
      if (bloque.open) montar(bloque);
    });
  }

  document.addEventListener('htmx:afterSettle', reponer);
  if (document.readyState !== 'loading') reponer();
  else document.addEventListener('DOMContentLoaded', reponer);

  window.TitulaTecCotejoInfo = { reponer: reponer, normalizarLiga: normalizarLiga };
})();
