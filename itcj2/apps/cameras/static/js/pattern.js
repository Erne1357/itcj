/*
 * Cámaras: visor y editor del patrón 3x3, sello de lo revelado y copiado.
 *
 * Único global: window.CamerasPattern
 *   mountViewer(el)  visor. Lee data-pattern="1259" y data-autoplay de el.
 *   mountEditor(el)  editor. Escribe la secuencia en el input[name="pattern"]
 *                    que vive dentro del mismo [data-pattern-editor].
 *   sealAll(root)    quita del DOM cada [data-revealed] y cierra su diálogo
 *                    (lo llaman los 30 s, pagehide y visibilitychange a oculta).
 *
 * Reloj: corre tras el dibujo; [data-cam-extend] hace POST y reinicia el plazo.
 * Escritorio: sella al minimizar o perder el foco la ventana (eventos desktop:*).
 *
 * Diálogo de revelado (dialog[data-cam-modal], nativo): el botón
 * [data-cam-reveal] hace hx-post y su respuesta (o el error) entra en
 * [data-cam-modal-body]; al llegar se abre con showModal(). Cerrar (botón
 * [data-cam-modal-close], Esc, clic en el fondo) SELLA: vacía el cuerpo y
 * devuelve el foco al botón que lo abrió.
 *
 * Además, por delegación y por atributos (sin API): [data-cam-copy] copia la
 * contraseña de su bloque revelado, [data-cam-pw] se parte en celdas,
 * [data-cam-filter] filtra la lista de su aria-controls y [data-cam-picker]
 * cuenta sus casillas marcadas.
 *
 * Morph-safe (HTMX + Idiomorph): todo valor llega por data-*, se relee en cada
 * montaje y montar dos veces no duplica nada. El estado vive en un WeakMap.
 */
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var MIN_LEN = 4;          // espejo de PATTERN_MIN_LEN; el servidor es quien valida
  var SEAL_SECONDS = 30;
  var SEG_MS = 460;         // trazo de un punto al siguiente
  var EASE = 'cubic-bezier(0.25, 1, 0.5, 1)';
  var HIT = 32;             // radio de captura del editor, en unidades del viewBox (puntos a 100)
  var POS = [null, 'arriba a la izquierda', 'arriba al centro', 'arriba a la derecha',
    'en medio a la izquierda', 'al centro', 'en medio a la derecha',
    'abajo a la izquierda', 'abajo al centro', 'abajo a la derecha'];

  var states = new WeakMap();
  var motion = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };

  // === UTILIDADES ===
  function svg(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }

  function el(tag, cls, parent, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    if (parent) parent.appendChild(n);
    return n;
  }

  function button(parent, cls, icon, text, onClick, iconAfter) {
    var b = el('button', cls, parent);
    b.type = 'button';
    var i = el('i', 'bi ' + icon);
    i.setAttribute('aria-hidden', 'true');
    var s = text ? el('span', '', null, text) : null;
    if (!iconAfter) b.appendChild(i);
    if (s) b.appendChild(s);
    if (iconAfter) b.appendChild(i);
    b.addEventListener('click', onClick);
    return b;
  }

  function center(p) { return [50 + ((p - 1) % 3) * 100, 50 + Math.floor((p - 1) / 3) * 100]; }

  function parse(raw) {
    var s = String(raw || '').trim();
    if (!/^[1-9]{0,9}$/.test(s)) return [];
    var seq = s.split('').map(Number);
    return new Set(seq).size === seq.length ? seq : [];
  }

  // Con un diálogo modal abierto todo lo de afuera es inerte (y mudo): la región
  // viva va dentro del diálogo abierto, si lo hay.
  function announce(msg) {
    var host = document.querySelector('dialog[data-cam-modal][open] .cam-modal__panel') || document.body;
    var n = host.querySelector(':scope > .cam-live');
    if (!n) {
      n = el('div', 'visually-hidden cam-live', host);
      n.setAttribute('aria-live', 'polite');
    }
    n.textContent = '';
    setTimeout(function () { n.textContent = msg; }, 40);
  }

  // === CUADRÍCULA (común a visor y editor: la vista previa es idéntica) ===
  function buildGrid(editable) {
    var root = svg('svg', { viewBox: '0 0 300 300', class: 'cam-grid' + (editable ? ' cam-grid--edit' : ''), focusable: 'false' });
    var g = { root: root, segs: svg('g', {}, root), heads: svg('g', {}, root), lines: [], arrows: [], dots: [] };
    if (editable) g.rubber = svg('line', { class: 'cam-grid__rubber' }, root);
    for (var p = 1; p <= 9; p++) {
      var c = center(p);
      var dot = svg('g', { class: 'cam-dot', transform: 'translate(' + c[0] + ' ' + c[1] + ')' }, root);
      svg('circle', { class: 'cam-dot__halo', r: 33 }, dot);
      var ping = svg('circle', { class: 'cam-dot__ping', r: 23 }, dot);
      svg('circle', { class: 'cam-dot__idle', r: editable ? 17 : 7 }, dot);
      if (editable) svg('text', { class: 'cam-dot__pos', 'text-anchor': 'middle', dy: '0.35em' }, dot).textContent = p;
      svg('circle', { class: 'cam-dot__disc', r: 23 }, dot);
      var num = svg('text', { class: 'cam-dot__num', 'text-anchor': 'middle', dy: '0.35em' }, dot);
      g.dots[p] = { g: dot, ping: ping, num: num };
    }
    return g;
  }

  function setSeq(g, seq) {
    g.segs.textContent = '';
    g.heads.textContent = '';
    g.lines = [];
    g.arrows = [];
    for (var i = 1; i < seq.length; i++) {
      var a = center(seq[i - 1]), b = center(seq[i]);
      var dx = b[0] - a[0], dy = b[1] - a[1];
      // A la mitad, una flecha de 1→3 caería encima del 2: en tramos largos va antes.
      var t = Math.sqrt(dx * dx + dy * dy) > 150 ? 0.3 : 0.5;
      g.lines.push(svg('line', { class: 'cam-seg', x1: a[0], y1: a[1], x2: b[0], y2: b[1], pathLength: 1 }, g.segs));
      g.arrows.push(svg('path', {
        class: 'cam-arrow', d: 'M-8 -11 L10 0 L-8 11 L-4 0 Z',
        transform: 'translate(' + (a[0] + dx * t) + ' ' + (a[1] + dy * t) + ') rotate(' + (Math.atan2(dy, dx) * 180 / Math.PI) + ')'
      }, g.heads));
    }
    for (var p = 1; p <= 9; p++) g.dots[p].num.textContent = '';
    seq.forEach(function (q, idx) { g.dots[q].num.textContent = idx + 1; });
  }

  // lit = puntos encendidos, drawn = segmentos visibles, current = índice con pulso
  function paint(g, seq, lit, drawn, current) {
    for (var p = 1; p <= 9; p++) g.dots[p].g.setAttribute('class', 'cam-dot');
    seq.forEach(function (q, i) {
      var cls = 'cam-dot';
      if (i < lit) cls += ' is-on';
      if (i === 0 && lit > 0) cls += ' is-start';
      if (i === current) cls += ' is-current';
      g.dots[q].g.setAttribute('class', cls);
    });
    g.lines.forEach(function (l, i) { l.classList.toggle('is-on', i < drawn); });
    g.arrows.forEach(function (a, i) { a.classList.toggle('is-on', i < drawn); });
  }

  function ping(st, p) {
    var c = st.grid.dots[p].ping;
    if (motion.matches || !c.animate) return;
    st.anims.push(c.animate(
      [{ transform: 'scale(1)', opacity: 0.85 }, { transform: 'scale(1.9)', opacity: 0 }],
      { duration: 650, easing: EASE }
    ));
  }

  // === VISOR ===
  function mountViewer(host) {
    if (!host) return null;
    var raw = host.getAttribute('data-pattern') || '';
    var st = states.get(host);
    if (st && st.raw === raw && host.contains(st.box)) return st;   // nada cambió
    if (st) stop(st);

    var seq = parse(raw);
    host.textContent = '';
    st = { raw: raw, seq: seq, shown: seq.length, stepping: false, playing: false, timers: [], anims: [] };
    states.set(host, st);

    st.box = el('div', 'cam-pattern__screen', host);
    st.grid = buildGrid(false);
    st.grid.root.setAttribute('role', 'img');
    st.grid.root.setAttribute('aria-label', seq.length
      ? 'Patrón de ' + seq.length + ' puntos: ' + seq.join(' → ') + '. Puntos numerados del 1 al 9, de izquierda a derecha y de arriba abajo.'
      : 'Sin patrón');
    st.box.appendChild(st.grid.root);
    setSeq(st.grid, seq);

    var con = el('div', 'cam-pattern__console', host);
    st.caption = el('p', 'cam-pattern__caption', con);
    var ctr = el('div', 'cam-pattern__controls', con);
    st.replay = button(ctr, 'cam-btn cam-btn--dark', 'bi-arrow-repeat', 'Repetir', function () {
      st.stepping = false;
      play(st);
    });
    st.prev = button(ctr, 'cam-btn cam-btn--dark cam-btn--icon', 'bi-chevron-left', '', function () {
      stop(st);
      st.stepping = true;
      show(st, st.shown - 1, false);
    });
    st.prev.setAttribute('aria-label', 'Paso anterior');
    st.next = button(ctr, 'cam-btn cam-btn--signal', 'bi-chevron-right', 'Paso a paso', function () {
      stop(st);
      var restart = st.shown >= st.seq.length;
      st.stepping = true;
      show(st, restart ? 1 : st.shown + 1, true);
    }, true);

    if (!seq.length) {
      st.caption.textContent = 'Sin patrón';
      st.replay.disabled = st.prev.disabled = st.next.disabled = true;
      return st;
    }
    if (host.hasAttribute('data-autoplay')) play(st);
    else show(st, seq.length, false);
    return st;
  }

  function later(st, ms, fn) { st.timers.push(setTimeout(fn, ms)); }

  // Cortar el dibujo (Paso a paso, Paso anterior, Repetir) cuenta como terminado: el reloj
  // del revelado arranca aquí y nunca se queda en 'drawing' (start es idempotente).
  function stop(st) {
    st.timers.forEach(clearTimeout);
    st.timers = [];
    st.anims.forEach(function (a) { a.cancel(); });
    st.anims = [];
    if (st.playing) {
      st.playing = false;
      st.box.dispatchEvent(new CustomEvent('cam:drawn', { bubbles: true }));
    }
  }

  function play(st) {
    stop(st);
    var n = st.seq.length;
    if (motion.matches || n < 2) { show(st, n, false); return; }
    st.playing = true;
    st.shown = 0;
    paint(st.grid, st.seq, 0, 0, -1);
    var k = 0;
    (function tick() {
      k++;
      show(st, k, true);
      if (k < n) later(st, k === 1 ? 380 : SEG_MS + 140, tick);
      else later(st, SEG_MS + 200, function () {
        st.playing = false;
        sync(st);
        st.box.dispatchEvent(new CustomEvent('cam:drawn', { bubbles: true }));
      });
    })();
  }

  // Muestra k puntos. Si avanza uno y hay movimiento, traza el segmento nuevo.
  function show(st, k, animate) {
    var n = st.seq.length;
    k = Math.max(1, Math.min(n, k));
    var fwd = animate && !motion.matches && (k === 1 || k === st.shown + 1);
    var cur = st.stepping ? k - 1 : -1;
    st.shown = k;
    if (!fwd) { paint(st.grid, st.seq, k, k - 1, cur); sync(st); return; }
    if (k === 1) { paint(st.grid, st.seq, 1, 0, cur); ping(st, st.seq[0]); sync(st); return; }

    paint(st.grid, st.seq, k - 1, k - 2, -1);
    var line = st.grid.lines[k - 2];
    line.classList.add('is-on');
    if (line.animate) {
      st.anims.push(line.animate([{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { duration: SEG_MS, easing: EASE }));
    }
    later(st, SEG_MS - 60, function () {
      paint(st.grid, st.seq, k, k - 1, cur);
      ping(st, st.seq[k - 1]);
      sync(st);
    });
  }

  function sync(st) {
    var n = st.seq.length, k = st.shown;
    st.caption.textContent = '';
    if (!st.playing && !st.stepping) {
      el('b', '', st.caption, n + ' puntos');
      el('span', '', st.caption, 'Empieza en el 1 y sigue los números');
    } else {
      el('b', '', st.caption, 'Paso ' + k + ' de ' + n);
      el('span', '', st.caption, (k === 1 ? 'Empieza ' : k === n ? 'Termina ' : 'Sigue ') + POS[st.seq[k - 1]]);
    }
    // Mientras se dibuja solo, no se narra cada paso: se anuncia al terminar.
    st.caption.setAttribute('aria-live', st.playing ? 'off' : 'polite');
    st.prev.disabled = k <= 1;
    st.next.querySelector('span').textContent = k >= n ? 'Paso a paso' : 'Siguiente';
  }

  // === EDITOR ===
  function mountEditor(host) {
    if (!host) return null;
    var st = states.get(host);
    if (st && host.contains(st.box)) return st;

    var input = host.querySelector('input[name="pattern"]');
    st = { seq: parse(input && input.value), host: host, input: input, drawing: false, fresh: false, anims: [] };
    states.set(host, st);

    st.box = el('div', 'cam-pattern cam-editor__device');
    host.insertBefore(st.box, host.firstChild);
    var screen = el('div', 'cam-pattern__screen', st.box);
    st.grid = buildGrid(true);
    var pad = st.grid.root;
    pad.setAttribute('tabindex', '0');
    pad.setAttribute('role', 'application');
    pad.setAttribute('aria-label', 'Editor del patrón. Traza con el dedo o el mouse, o teclea los números del 1 al 9. Retroceso deshace, Suprimir limpia.');
    screen.appendChild(pad);

    var con = el('div', 'cam-pattern__console', st.box);
    st.readout = el('p', 'cam-editor__readout cam-editor__reading', con);
    st.status = el('p', 'cam-editor__status', con);
    st.status.setAttribute('aria-live', 'polite');
    var tools = el('div', 'cam-pattern__controls', con);
    st.undo = button(tools, 'cam-btn cam-btn--dark', 'bi-arrow-counterclockwise', 'Deshacer', function () { st.seq.pop(); render(st); });
    st.clear = button(tools, 'cam-btn cam-btn--dark', 'bi-x-lg', 'Limpiar', function () { st.seq = []; render(st); });

    function local(e) {
      var m = pad.getScreenCTM();
      if (!m) return null;
      var pt = pad.createSVGPoint();
      pt.x = e.clientX;
      pt.y = e.clientY;
      return pt.matrixTransform(m.inverse());
    }
    function end() {
      st.drawing = false;
      st.fresh = false;
      st.grid.rubber.classList.remove('is-on');
    }
    pad.addEventListener('contextmenu', function (e) { e.preventDefault(); });   // pulsación larga táctil
    pad.addEventListener('pointerdown', function (e) {
      if (e.button > 0 || (st.drawing && e.pointerId !== st.pid)) return;   // un solo puntero traza
      st.pid = e.pointerId;
      try { pad.setPointerCapture(e.pointerId); } catch (err) { /* puntero ya inactivo */ }
      st.drawing = true;
      st.fresh = true;          // trazo nuevo = patrón nuevo, pero solo si toca un punto
      st.last = local(e);
      if (st.last && hit(st, st.last, st.last)) render(st);
    });
    pad.addEventListener('pointermove', function (e) {
      if (!st.drawing || e.pointerId !== st.pid) return;
      var pt = local(e);
      if (!pt) return;
      if (!st.last) st.last = pt;
      if (hit(st, st.last, pt)) render(st);
      st.last = pt;
      rubber(st, pt);
    });
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(function (t) {
      pad.addEventListener(t, function (e) { if (e.pointerId === st.pid) end(); });
    });
    pad.addEventListener('keydown', function (e) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;   // no secuestrar Ctrl/Cmd+1 (cambio de pestaña)
      if (/^[1-9]$/.test(e.key)) add(st, +e.key);
      else if (e.key === 'Backspace') st.seq.pop();
      else if (e.key === 'Delete') st.seq = [];
      else return;
      e.preventDefault();
      render(st);
    });

    render(st);
    return st;
  }

  // Registra cada punto que el puntero CRUZA entre dos lecturas, en orden de paso:
  // un arrastre rápido de 1 a 3 no se salta el 2.
  function hit(st, a, b) {
    var taken = st.fresh ? [] : st.seq, found = [];
    var dx = b.x - a.x, dy = b.y - a.y, len2 = dx * dx + dy * dy;
    for (var p = 1; p <= 9; p++) {
      if (taken.indexOf(p) >= 0) continue;
      var c = center(p);
      var t = len2 ? Math.max(0, Math.min(1, ((c[0] - a.x) * dx + (c[1] - a.y) * dy) / len2)) : 0;
      var ex = a.x + t * dx - c[0], ey = a.y + t * dy - c[1];
      if (ex * ex + ey * ey <= HIT * HIT) found.push([t, p]);
    }
    found.sort(function (x, y) { return x[0] - y[0]; });
    found.forEach(function (f) { add(st, f[1]); });
    return found.length > 0;
  }

  function add(st, p) {
    if (st.fresh) { st.seq = []; st.fresh = false; }
    if (st.seq.length >= 9 || st.seq.indexOf(p) >= 0) return;
    st.seq.push(p);
    st.pinged = p;
    if (navigator.vibrate) { try { navigator.vibrate(8); } catch (e) { /* sin vibración */ } }
  }

  function rubber(st, pt) {
    var r = st.grid.rubber, last = st.seq[st.seq.length - 1];
    if (!st.drawing || st.fresh || !last) { r.classList.remove('is-on'); return; }
    var c = center(last);
    r.setAttribute('x1', c[0]);
    r.setAttribute('y1', c[1]);
    r.setAttribute('x2', pt.x);
    r.setAttribute('y2', pt.y);
    r.classList.add('is-on');
  }

  function render(st) {
    var n = st.seq.length, val = st.seq.join('');
    setSeq(st.grid, st.seq);
    paint(st.grid, st.seq, n, n - 1, -1);
    if (st.pinged) { ping(st, st.pinged); st.pinged = 0; }
    var input = st.host.querySelector('input[name="pattern"]') || st.input;   // un morph pudo reemplazarlo
    st.input = input;
    if (input && input.value !== val) {
      input.value = val;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }
    // orden + lugar con palabras (una sola numeración: la de los discos del aparato)
    var reading = st.seq.map(function (p, i) {
      // espacios no separables: un paso nunca se parte entre líneas
      return ((i + 1) + 'º ' + POS[p].replace(/^al /, '').replace(/ a(l| la) /, ' ')).replace(/ /g, ' ');
    }).join(' → ');
    st.readout.textContent = n ? reading : 'Traza el patrón sobre la cuadrícula';
    st.grid.root.setAttribute('aria-label', 'Editor del patrón. ' + (n ? 'Patrón actual: ' + reading + '. ' : '') +
      'Traza con el dedo o el mouse, o teclea los números del 1 al 9 de cada posición. Retroceso deshace, Suprimir limpia.');
    st.readout.classList.toggle('is-empty', !n);
    var miss = MIN_LEN - n;
    st.status.textContent = !n ? 'Mínimo ' + MIN_LEN + ' puntos, sin repetir'
      : miss > 0 ? 'Faltan ' + miss + (miss === 1 ? ' punto' : ' puntos')
      : 'Listo: ' + n + ' puntos';
    st.status.className = 'cam-editor__status' + (!n ? '' : miss > 0 ? ' is-short' : ' is-ready');
    st.undo.disabled = st.clear.disabled = !n;
  }

  // === CONTRASEÑA EN CELDAS ===
  // El texto se conserva tal cual (espacios incluidos) para copiarlo; el índice
  // de cada carácter es ::after y no se copia.
  function cells(pw) {
    if (pw.querySelector('.cam-pw__ch')) return;
    var text = pw.textContent, kinds = {};
    pw.textContent = '';
    Array.from(text).forEach(function (ch, i) {
      var kind = /[0-9]/.test(ch) ? 'digit' : ch === ' ' ? 'space' : /[\p{L}]/u.test(ch) ? '' : 'symbol';
      kinds[kind] = true;
      var c = el('span', 'cam-pw__ch' + (kind ? ' cam-pw__ch--' + kind : ''), pw, ch);
      c.setAttribute('data-i', i + 1);
      c.style.setProperty('--i', i);
    });
    var next = pw.nextElementSibling;
    if ((kinds.digit || kinds.symbol) && !(next && next.classList.contains('cam-pw__legend'))) {
      var lg = el('p', 'cam-pw__legend');
      lg.setAttribute('aria-hidden', 'true');
      if (kinds.digit) el('span', '', lg).innerHTML = '<span class="cam-pw__key cam-pw__ch--digit">7</span>número';
      if (kinds.symbol) el('span', '', lg).innerHTML = '<span class="cam-pw__key cam-pw__ch--symbol">#</span>símbolo';
      pw.parentNode.insertBefore(lg, next);
    }
  }

  function copy(btn) {
    var scope = btn.closest('[data-revealed]') || document;
    var pw = scope.querySelector('[data-cam-pw]');
    if (!pw) return;
    var text = pw.textContent;   // el portapapeles conserva la contraseña tras sellar (inherente, por diseño)
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(
        function () { copied(btn, pw, true); },
        function () { copied(btn, pw, selectCopy(pw, btn)); }
      );
    } else {
      copied(btn, pw, selectCopy(pw, btn));
    }
  }

  // Respaldo sin contexto seguro (http:// de la LAN, iframe): un campo de solo
  // lectura con el texto EXACTO, seleccionado. Seleccionar las celdas no sirve:
  // el navegador mete saltos de línea entre ellas y se come el espacio.
  // shortcut: execCommand('copy') es obsoleto; si falla, el campo queda a la vista y seleccionado.
  function selectCopy(pw, btn) {
    var plain = pw.parentNode.querySelector('.cam-pw__plain');
    if (!plain) {
      plain = el('input', 'form-control cam-pw__plain');
      plain.type = 'text';
      plain.readOnly = true;
      plain.setAttribute('aria-label', 'Contraseña en texto, seleccionada');
      pw.parentNode.insertBefore(plain, pw.nextSibling);
    }
    plain.value = pw.textContent;
    plain.focus({ preventScroll: true });
    plain.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    if (ok) { plain.remove(); btn.focus({ preventScroll: true }); }
    return ok;
  }

  function copied(btn, pw, ok) {
    var st = states.get(btn) || {};
    var label = btn.querySelector('[data-cam-copy-label]'), icon = btn.querySelector('.bi');
    if (!st.label) st.label = label ? label.textContent : '';
    if (!st.icon) st.icon = icon ? icon.className : '';
    states.set(btn, st);
    clearTimeout(st.t);
    if (ok) {
      btn.classList.add('is-copied');
      if (label) label.textContent = 'Copiada';
      if (icon) icon.className = 'bi bi-check2';
      pw.classList.remove('is-copied');
      void pw.offsetWidth;  // reinicia la ola de las celdas
      pw.classList.add('is-copied');
      announce('Contraseña copiada');
    } else {
      if (label) label.textContent = 'Seleccionada: cópiala';
      announce('Contraseña seleccionada. Cópiala con el menú del sistema.');
    }
    st.t = setTimeout(function () {
      btn.classList.remove('is-copied');
      if (label) label.textContent = st.label;
      if (icon) icon.className = st.icon;
      pw.classList.remove('is-copied');
    }, ok ? 1800 : 4000);
  }

  // === SELLO: reloj tras el dibujo, +30 s, 30 s, pagehide, pestaña oculta y escritorio ===
  // Estados en la raíz [data-revealed][data-cam-timer]: drawing (reloj parado) | running | ending | sealed.
  function setTimerState(box, v) {
    box.setAttribute('data-cam-timer', v);
    var x = box.querySelector('[data-cam-extend]');
    if (x) x.hidden = v === 'drawing' || v === 'sealed';
  }

  function arm(box) {
    if (states.has(box)) return;
    var secs = parseInt(box.getAttribute('data-seal-after'), 10) || SEAL_SECONDS;
    var st = { total: secs * 1000, warned: false, busy: false };
    states.set(box, st);
    attachDesktop();
    var v = box.querySelector('[data-pattern-viewer]');
    var vs = v && states.get(v);
    if (vs && vs.playing) {   // 'cam:drawn' lo arranca; el respaldo, por si ese aviso nunca llega
      setTimerState(box, 'drawing');
      setTimeout(function () { if (box.isConnected) start(box, st); }, 8000);
      return;
    }
    start(box, st);
  }

  function start(box, st) {
    if (st.timer) return;
    st.deadline = Date.now() + st.total;
    setTimerState(box, 'running');
    tick(box, st);
    st.timer = setInterval(function () { tick(box, st); }, 250);
  }

  function tick(box, st) {
    if (!box.isConnected || !box.hasAttribute('data-revealed')) { clearInterval(st.timer); return; }
    var left = st.deadline - Date.now();
    if (left <= 0) { autoSeal(box); return; }
    var s = Math.ceil(left / 1000);
    box.querySelectorAll('[data-cam-countdown]').forEach(function (n) { n.textContent = s; });
    box.querySelectorAll('[data-cam-fuse]').forEach(function (n) { n.style.transform = 'scaleX(' + (left / st.total).toFixed(3) + ')'; });
    box.classList.toggle('is-ending', s <= 5);
    setTimerState(box, s <= 5 ? 'ending' : 'running');
    if (s <= 5 && !st.warned) { st.warned = true; announce('Se ocultará en 5 segundos'); }
  }

  // El visor avisa al terminar de dibujar: ahí arranca el reloj.
  document.addEventListener('cam:drawn', function (e) {
    var box = e.target.closest && e.target.closest('[data-revealed]');
    var st = box && states.get(box);
    if (st && !st.timer) start(box, st);
  });

  // +30 s: el servidor lo registra (acción extend); solo si responde bien se reinicia el plazo.
  function extend(btn) {
    var box = btn.closest('[data-revealed]');
    var st = box && states.get(box);
    if (!st || !st.timer || st.busy) return;
    st.busy = true;
    btn.setAttribute('aria-busy', 'true');
    var old = box.querySelector('.cam-reveal__extend-msg');
    if (old) old.remove();
    function fail(why) {
      var msg = 'No se pudo extender.' + (why ? ' ' + why : '');
      el('span', 'cam-reveal__extend-msg', box.querySelector('.cam-reveal__timer') || box, msg).setAttribute('role', 'status');
      announce(msg);
    }
    // Solo 204 extiende. Sin seguir redirecciones: con la sesión vencida el servidor manda
    // al login (302) y eso no dejó fila 'extend' en la bitácora.
    fetch(btn.getAttribute('data-cam-extend-url'), {
      method: 'POST', credentials: 'same-origin', redirect: 'manual', headers: { 'HX-Request': 'true' }
    }).then(function (r) {
      if (r.status !== 204) {
        var why = r.type === 'opaqueredirect' ? 'Tu sesión terminó: vuelve a iniciar sesión.' : r.headers.get('X-Cam-Error');
        try { why = why && decodeURIComponent(why); } catch (e) { /* header mal codificado: queda tal cual */ }
        fail(why);
        return;
      }
      if (!box.isConnected || !box.hasAttribute('data-revealed')) return;
      st.deadline = Date.now() + st.total;
      st.warned = false;
      tick(box, st);
    }, function () { fail('Sin conexión con el servidor.'); }).then(function () {
      st.busy = false;
      btn.removeAttribute('aria-busy');
    });
  }

  // Lo que se ocultó, según lo que traía el revelado (no siempre son ambos).
  function hiddenMsg(box) {
    var p = !!box.querySelector('[data-pattern-viewer]'), w = !!box.querySelector('[data-cam-pw]');
    return p && w ? 'Se ocultaron el patrón y la contraseña' : p ? 'Se ocultó el patrón' : w ? 'Se ocultó la contraseña' : 'Se ocultó';
  }

  // Sello automático (reloj o salida del escritorio): un solo aviso (la nota de la tarjeta,
  // o la región viva si la tarjeta ya no está) y el disparador sin lima hasta que el puntero salga.
  function autoSeal(box) {
    var id = opener, text = box.getAttribute('data-cam-sealed-text'), msg = hiddenMsg(box);
    seal(box);
    var note = id && document.getElementById('cam-note-' + id);
    if (note && text) {
      note.textContent = text;
      clearTimeout(note._camT);
      note._camT = setTimeout(function () { note.textContent = ''; }, 8000);
    } else {
      announce(msg);
    }
    // Siempre: al cerrar el diálogo el navegador recalcula el hover sin mover el puntero, y
    // ':hover' aquí todavía es falso (el fondo del diálogo lo tapaba).
    var btn = id && document.querySelector('[data-cam-reveal="' + id + '"]');
    if (!btn) return;
    btn.setAttribute('data-cam-just-sealed', '');
    var clear = function (e) {
      if (e && e.type === 'pointermove' && btn.contains(e.target)) return;
      btn.removeAttribute('data-cam-just-sealed');
      btn.removeEventListener('pointerleave', clear);
      btn.removeEventListener('blur', clear);
      document.removeEventListener('pointermove', clear, true);
    };
    btn.addEventListener('pointerleave', clear);
    btn.addEventListener('blur', clear);
    document.addEventListener('pointermove', clear, true);
  }

  // Ventana del escritorio: sella al minimizarse o al dejar de ser la activa.
  // Eventos: window-manager.js:17-19 (desktop:window-minimized, desktop:active-changed, desktop:window-closed), en document del padre.
  var desk = null;
  function deskKey() {
    try {
      var cp = window.CamerasPage;   // lo expone cameras.js; respaldo propio si aún no existe
      var inDesk = cp && typeof cp.inDesktopWindow === 'boolean' ? cp.inDesktopWindow
        : window.parent !== window && !!window.parent.ItcjDesktop;
      var w = inDesk && window.frameElement && window.frameElement.closest('.app-window');
      return w && w.dataset.appId ? w.dataset.appId : null;
    } catch (e) { return null; }
  }
  function attachDesktop() {
    if (desk) return;
    var key = deskKey();
    if (!key) return;
    var pd = window.parent.document;
    var on = function (e) {
      var k = e.detail && e.detail.key;
      if (e.type === 'desktop:active-changed' ? k === key : k !== key) return;
      pending = null;   // un «Revelar» en vuelo ya no se abre: la ventana dejó de estar al frente
      sealAll(document, true);
    };
    var evs = ['desktop:window-minimized', 'desktop:active-changed', 'desktop:window-closed'];
    evs.forEach(function (n) { pd.addEventListener(n, on); });
    desk = function () { evs.forEach(function (n) { pd.removeEventListener(n, on); }); desk = null; };
  }

  // Quita lo revelado del DOM (no basta ocultarlo) y para sus relojes.
  function wipe(box) {
    box.querySelectorAll('[data-pattern-viewer]').forEach(function (v) {
      var vs = states.get(v);
      if (vs) stop(vs);   // antes del reloj: si dibujaba, stop() lo arranca y aquí abajo se para
    });
    var st = states.get(box);
    if (st && st.timer) clearInterval(st.timer);
    box.querySelectorAll('[data-cam-copy]').forEach(function (b) {
      var cs = states.get(b);
      if (cs) clearTimeout(cs.t);
    });
    box.remove();
    if (desk && !document.querySelector('[data-revealed]')) desk();
  }

  function seal(box) {
    var dlg = modalOf(box);
    wipe(box);
    if (dlg) closeModal(dlg);
  }

  function sealAll(root, withNote) {
    root = root || document;
    var list = Array.from(root.querySelectorAll('[data-revealed]'));
    if (root.matches && root.matches('[data-revealed]')) list.unshift(root);
    list.forEach(withNote ? autoSeal : seal);
    return list.length;
  }

  // === DIÁLOGO DE REVELADO ===
  var opener = null;        // id del DVR cuyo «Revelar» abrió el diálogo (el foco vuelve ahí)
  var pending = null;       // botón «Revelar» con petición en curso
  var downOnBackdrop = false;

  function modalOf(n) { return n && n.closest ? n.closest('dialog[data-cam-modal]') : null; }

  function openModal(dlg, btn) {
    if (btn) {
      opener = btn.getAttribute('data-cam-reveal');
      var title = dlg.querySelector('[data-cam-modal-title]'), sub = dlg.querySelector('[data-cam-modal-sub]');
      if (title) title.textContent = btn.getAttribute('data-name') || 'DVR';
      if (sub) {
        sub.textContent = btn.getAttribute('data-place') || '';
        sub.hidden = !sub.textContent;
      }
      // El panel entra desde el lado del botón (un tercio del trayecto): se lee de dónde salió.
      var r = btn.getBoundingClientRect(), panel = dlg.querySelector('.cam-modal__panel');
      if (panel) {
        panel.style.setProperty('--cam-from-x', Math.round((r.left + r.width / 2 - window.innerWidth / 2) / 3) + 'px');
        panel.style.setProperty('--cam-from-y', Math.round((r.top + r.height / 2 - window.innerHeight / 2) / 3) + 'px');
      }
    }
    var pn = dlg.querySelector('.cam-modal__panel');
    if (pn && !pn.querySelector('[data-cam-sentinel]')) {
      ['start', 'end'].forEach(function (w) {
        var sn = document.createElement('span');
        sn.className = 'cam-modal__sentinel';
        sn.tabIndex = 0;
        sn.setAttribute('data-cam-sentinel', w);
        if (w === 'start') pn.insertBefore(sn, pn.firstChild); else pn.appendChild(sn);
      });
    }
    if (dlg.open) return;
    // Al abrir, el foco va a «Ocultar»: sin esto el primer enfocable es el centinela del inicio
    // y la trampa lo manda al último control.
    var hide = dlg.querySelector('[data-cam-modal-close]');
    if (hide) hide.autofocus = true;
    dlg.showModal();
    if (hide) hide.focus();
  }

  // Trampa de foco: los centinelas devuelven el foco al extremo opuesto del panel.
  document.addEventListener('focusin', function (e) {
    var w = e.target.getAttribute && e.target.getAttribute('data-cam-sentinel');
    if (!w) return;
    var items = Array.from(e.target.parentNode.querySelectorAll('button, [href], input, select, textarea, [tabindex]'))
      .filter(function (n) { return !n.hasAttribute('data-cam-sentinel') && !n.disabled && n.tabIndex >= 0 && n.getClientRects().length; });
    var to = items[w === 'start' ? items.length - 1 : 0];
    if (to) to.focus({ preventScroll: true });
  });

  // Cerrar = sellar: el cuerpo se vacía antes de cerrar; el evento close devuelve el foco.
  function closeModal(dlg) {
    Array.from(dlg.querySelectorAll('[data-revealed]')).forEach(wipe);
    var body = dlg.querySelector('[data-cam-modal-body]');
    if (body) body.textContent = '';
    if (!dlg.open) return;
    // Sin foco en este documento (el escritorio minimizó o activó otra ventana), cerrar no debe
    // traer el foco al iframe: el wm lo tomaría por un clic y nos devolvería al frente. El
    // <dialog> restaura el foco a quien lo abrió, y un botón deshabilitado no lo recibe.
    var b = !document.hasFocus() && opener && document.querySelector('[data-cam-reveal="' + opener + '"]');
    if (b) b.disabled = true;
    dlg.close();
    if (b) b.disabled = false;
  }

  function failReveal(btn, msg) {
    if (btn !== pending) return;   // un revelado que ya no es el vigente no abre nada
    pending = null;
    var dlg = document.querySelector('dialog[data-cam-modal]');
    var body = dlg && dlg.querySelector('[data-cam-modal-body]');
    if (!body) return;
    body.textContent = '';
    el('p', 'cam-field__error', body, msg).setAttribute('role', 'alert');
    openModal(dlg, btn);
  }

  function revealBtn(n) { return n && n.closest ? n.closest('[data-cam-reveal]') : null; }

  // Solo el último «Revelar» pulsado es el vigente: la respuesta de otro (o una que llega
  // cuando la ventana del escritorio ya no está al frente) no entra al DOM. Así el título del
  // diálogo y el secreto salen siempre del mismo botón.
  function requester(e) { return e.detail && e.detail.requestConfig ? revealBtn(e.detail.requestConfig.elt) : null; }
  document.addEventListener('htmx:beforeRequest', function (e) {
    var b = revealBtn(e.target);
    if (!b) return;
    pending = b;
    attachDesktop();
  });
  // En window: corre después del htmx:beforeSwap de cameras.js, que reactiva el swap de errores.
  window.addEventListener('htmx:beforeSwap', function (e) {
    var b = requester(e);
    if (b && b !== pending) e.detail.shouldSwap = false;
  });
  document.addEventListener('htmx:afterSwap', function (e) {
    var dlg = modalOf(e.detail && e.detail.target), b = requester(e);
    if (!dlg || !b) return;
    if (b !== pending) { closeModal(dlg); return; }
    pending = null;
    openModal(dlg, b);
  });
  document.addEventListener('htmx:sendError', function (e) {
    var b = revealBtn(e.target);
    if (b) failReveal(b, 'Sin conexión con el servidor. Intenta de nuevo.');
  });
  document.addEventListener('htmx:responseError', function (e) {
    var b = revealBtn(e.target);
    if (b) failReveal(b, 'Error inesperado del servidor. Intenta de nuevo.');
  });

  // cancel y close no burbujean: se escuchan en captura.
  document.addEventListener('cancel', function (e) {
    var dlg = e.target;
    if (!dlg.matches || !dlg.matches('dialog[data-cam-modal]')) return;
    e.preventDefault();      // Esc: sellar antes de cerrar
    closeModal(dlg);
  }, true);
  document.addEventListener('close', function (e) {
    var dlg = e.target;
    if (!dlg.matches || !dlg.matches('dialog[data-cam-modal]')) return;
    closeModal(dlg);         // por si se cerró por otra vía: nada queda en el DOM
    var btn = opener && document.querySelector('[data-cam-reveal="' + opener + '"]');
    opener = null;
    if (btn && document.hasFocus()) btn.focus({ preventScroll: true });   // sin robar el foco a otra ventana
  }, true);
  // Clic en el fondo: el diálogo ocupa la pantalla y el panel es su único hijo,
  // así que un clic que empieza y termina en el diálogo mismo cayó fuera del panel
  // (arrastrar para seleccionar la contraseña y soltar afuera no cierra).
  document.addEventListener('pointerdown', function (e) {
    downOnBackdrop = !!(e.target.matches && e.target.matches('dialog[data-cam-modal]'));
  }, true);

  // === FILTRO Y CONTADOR DE LA MULTISELECCIÓN ===
  function fold(s) { return s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim(); }

  function count(picker) {
    var n = picker.querySelectorAll('input[type="checkbox"]:checked').length;
    picker.querySelectorAll('[data-cam-picker-count]').forEach(function (c) {
      c.textContent = n === 1 ? '1 seleccionado' : n + ' seleccionados';
    });
  }

  // === ARRANQUE (idempotente: DOMContentLoaded, htmx:load y htmx:afterSettle) ===
  function each(root, sel, fn) {
    if (root !== document && root.matches(sel)) fn(root);
    root.querySelectorAll(sel).forEach(function (n) { fn(n); });
  }

  function scan(root) {
    root = root && root.querySelectorAll ? root : document;
    each(root, '[data-pattern-viewer]', mountViewer);
    each(root, '[data-pattern-editor]', mountEditor);
    each(root, '[data-cam-pw]', cells);
    each(root, '[data-revealed]', arm);
    each(root, '[data-cam-picker]', count);
  }

  document.addEventListener('click', function (e) {
    if (e.target.matches && e.target.matches('dialog[data-cam-modal]')) {
      if (downOnBackdrop) closeModal(e.target);
      return;
    }
    var t = e.target.closest && e.target.closest('[data-cam-copy], [data-cam-modal-close], [data-cam-extend]');
    if (!t) return;
    if (t.hasAttribute('data-cam-extend')) { extend(t); return; }
    if (t.hasAttribute('data-cam-copy')) { copy(t); return; }
    var dlg = modalOf(t);
    if (!dlg) return;
    var had = dlg.querySelector('[data-revealed]');
    closeModal(dlg);
    if (had) announce(hiddenMsg(had));
  });

  document.addEventListener('input', function (e) {
    var f = e.target.closest && e.target.closest('[data-cam-filter]');
    var list = f && document.getElementById(f.getAttribute('aria-controls'));
    if (!list) return;
    var q = fold(f.value), any = false;
    list.querySelectorAll('[data-cam-filter-item]').forEach(function (it) {
      var ok = !q || fold(it.textContent).indexOf(q) >= 0;
      it.hidden = !ok;
      any = any || ok;
    });
    var empty = list.parentNode.querySelector('[data-cam-filter-empty]');
    if (empty) empty.hidden = any;
  });

  document.addEventListener('change', function (e) {
    var picker = e.target.closest && e.target.closest('[data-cam-picker]');
    if (picker) count(picker);
  });

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') sealAll(document);
  });
  window.addEventListener('pagehide', function () {
    sealAll(document);
    if (desk) desk();   // aunque ya no quede nada revelado: el listener vive en el document del padre
  });
  document.addEventListener('htmx:load', function (e) { scan(e.detail && e.detail.elt); });
  document.addEventListener('htmx:afterSettle', function () { scan(document); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { scan(document); });
  else scan(document);

  window.CamerasPattern = { mountViewer: mountViewer, mountEditor: mountEditor, sealAll: sealAll };
})();
