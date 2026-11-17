// Atrás tras filtrar la bitácora: sin caché (hx-history="false") recarga la URL completa en vez de pegar solo la tabla.
htmx.config.refreshOnHistoryMiss = true;

/* Cámaras: deja que HTMX pinte las respuestas de error de dominio (404/422/500/503 con X-Cam-Error). */
document.addEventListener('htmx:beforeSwap', function (e) {
  var xhr = e.detail.xhr;
  if (xhr && (xhr.status === 404 || xhr.status === 422 || xhr.status === 500 || xhr.status === 503) && xhr.getResponseHeader('X-Cam-Error')) {
    e.detail.shouldSwap = true;
    e.detail.isError = false;
  }
});

// === CONTEXTO DE PÁGINA (ventana del escritorio vs iframe móvil) ===
// shortcut: mismo origen + ItcjDesktop.wm = ventana del escritorio; cualquier otro iframe se queda como móvil.
function camInDesktopWindow() {
  try {
    return window.parent !== window && !!(window.parent.ItcjDesktop && window.parent.ItcjDesktop.wm);
  } catch (_) { return false; }
}
window.CamerasPage = { inDesktopWindow: camInDesktopWindow() };

document.addEventListener('DOMContentLoaded', function () {
  // mobile-app-shell.js corre después de este script y pone in-mobile-iframe: se reaplica en el siguiente tick.
  if (!window.CamerasPage.inDesktopWindow) return;
  var apply = function () {
    document.body.classList.remove('in-mobile-iframe');
    document.body.classList.add('in-desktop-window');
  };
  apply();
  setTimeout(apply, 0);
  window.addEventListener('load', apply);
});

// === ENLACE A HELP DESK (no navega el iframe de Cámaras; en el escritorio abre su ventana) ===
document.addEventListener('click', function (e) {
  var a = e.target.closest && e.target.closest('a[data-cam-helpdesk]');
  if (!a || !window.CamerasPage.inDesktopWindow) return;
  try {
    var D = window.parent.ItcjDesktop;
    var hit = D.registry && D.registry.resolve(a.getAttribute('href'));
    if (D.wm.open(hit ? hit.key : 'helpdesk', hit ? { url: hit.url } : undefined)) e.preventDefault();
  } catch (_) { /* cae al target=_top del enlace */ }
});

// === BAJA DE DVR (diálogo propio; nunca confirm nativo) ===
var camDeactivateOpener = null;

// Los atiende el focusin global de pattern.js.
function camFocusSentinels(panel) {
  ['start', 'end'].forEach(function (pos) {
    var s = document.createElement('span');
    s.className = 'cam-modal__sentinel';
    s.tabIndex = 0;
    s.setAttribute('data-cam-sentinel', pos);
    if (pos === 'start') panel.insertBefore(s, panel.firstChild); else panel.appendChild(s);
  });
}

document.addEventListener('click', function (e) {
  var dlg = document.getElementById('cam-deactivate');
  if (!dlg) return;
  var btn = e.target.closest && e.target.closest('[data-cam-deactivate]');
  if (btn && !btn.disabled) {
    camDeactivateOpener = btn;
    var panel = dlg.querySelector('.cam-modal__panel');
    if (panel && !panel.querySelector('[data-cam-sentinel]')) camFocusSentinels(panel);
    dlg.querySelector('[data-cam-deactivate-name]').textContent = btn.getAttribute('data-name');
    dlg.querySelector('[data-cam-deactivate-form]').setAttribute('action', '/cameras/dvrs/' + btn.getAttribute('data-cam-deactivate') + '/deactivate');
    var err = dlg.querySelector('[data-cam-deactivate-error]');
    err.hidden = true; err.textContent = '';
    var ok = dlg.querySelector('[data-cam-confirm-ok]');
    ok.disabled = false; ok.removeAttribute('aria-busy');
    dlg.showModal();
    dlg.querySelector('[data-cam-confirm-cancel]').focus();
    return;
  }
  if (e.target === dlg || (e.target.closest && e.target.closest('[data-cam-confirm-cancel]') && dlg.contains(e.target))) {
    if (dlg.open) dlg.close();   // fondo o Cancelar (Esc lo cierra el propio dialog)
  }
});

document.addEventListener('close', function (e) {
  if (e.target.id !== 'cam-deactivate') return;
  if (camDeactivateOpener && document.contains(camDeactivateOpener)) camDeactivateOpener.focus();
  camDeactivateOpener = null;
}, true);

document.addEventListener('submit', async function (e) {
  var form = e.target.closest && e.target.closest('[data-cam-deactivate-form]');
  if (!form) return;
  e.preventDefault();
  var ok = form.querySelector('[data-cam-confirm-ok]');
  var err = form.querySelector('[data-cam-deactivate-error]');
  if (ok.disabled) return;
  ok.disabled = true; ok.setAttribute('aria-busy', 'true'); err.hidden = true;
  try {
    var res = await fetch(form.getAttribute('action'),
      { method: 'POST', credentials: 'same-origin', headers: { 'HX-Request': 'true' } });
    if (res.ok && !res.redirected) { window.location.assign('/cameras/?ok=baja'); return; }
    var msg = res.headers.get('X-Cam-Error');
    err.textContent = msg ? decodeURIComponent(msg) : 'Error inesperado. Intenta de nuevo.';
  } catch (_) {
    err.textContent = 'Sin conexión con el servidor.';
  }
  err.hidden = false;
  ok.disabled = false; ok.removeAttribute('aria-busy');
});

// === VALIDACIÓN DEL FORMULARIO DE DVR ===
function camFieldError(ctrl, anchor, text) {
  var id = ctrl.id + '-error';
  var p = document.getElementById(id);
  if (!p) {
    p = document.createElement('p');
    p.className = 'cam-field__error';
    p.id = id;
    anchor.insertAdjacentElement('afterend', p);
  }
  p.textContent = text;
  ctrl.setAttribute('aria-invalid', 'true');
  ctrl.setAttribute('aria-describedby', id);
}

function camClearError(ctrl) {
  if (!ctrl) return;
  var p = document.getElementById(ctrl.id + '-error');
  if (p) p.remove();
  ctrl.removeAttribute('aria-invalid');
  ctrl.removeAttribute('aria-describedby');
}

function camValidateDvrForm(form) {
  var pat = form.querySelector('input[name="pattern"]');
  var edRoot = pat && pat.closest('[data-pattern-editor]');
  var ed = edRoot && edRoot.querySelector('svg.cam-grid--edit[role="application"]');
  var pw = form.querySelector('input[name="password"]');
  var pw2 = form.querySelector('input[name="password_confirm"]');
  if (ed && !ed.id) ed.id = 'f-pattern-editor';
  var edAnchor = (edRoot && edRoot.querySelector('.cam-editor__device')) || edRoot;   // el error va bajo la consola del aparato
  camClearError(ed); camClearError(pw2);
  var first = null;
  var n = pat ? pat.value.length : 0;
  if (ed && n > 0 && n < 4) {
    camFieldError(ed, edAnchor, 'El patrón necesita al menos 4 puntos, sin repetir.');
    first = ed;
  }
  if (pw && pw2 && pw.value !== pw2.value) {
    camFieldError(pw2, pw2, 'La confirmación no coincide con la contraseña.');
    first = first || pw2;
  }
  if (first) {
    first.focus();
    first.scrollIntoView({ block: 'center' });
  }
  return !first;
}

document.addEventListener('htmx:beforeRequest', function (e) {
  var form = e.target;
  if (form && form.id === 'cam-dvr-form' && !camValidateDvrForm(form)) e.preventDefault();
});

document.addEventListener('input', function (e) {
  if (e.target.matches && e.target.matches('#cam-dvr-form input[name="password_confirm"], #cam-dvr-form input[name="password"]')) {
    camClearError(document.querySelector('#cam-dvr-form input[name="password_confirm"]'));
  }
});
document.addEventListener('change', function (e) {
  if (e.target.matches && e.target.matches('#cam-dvr-form input[name="pattern"]')) camClearError(e.target.closest('[data-pattern-editor]').querySelector('svg.cam-grid--edit'));
});

// Error del servidor: llevarlo a la vista y enfocarlo.
document.addEventListener('htmx:afterSwap', function (e) {
  var t = e.detail && e.detail.target;
  if (!t || t.id !== 'cam-form-error' || !t.firstElementChild) return;
  t.scrollIntoView({ block: 'center' });
  t.focus();
});

// === CAMBIAR CONTRASEÑA (aria-expanded, foco, éxito) ===
function camPwOpener(slot) {
  var card = slot.closest('.cam-card');
  return card && card.querySelector('[hx-get$="/password"]');
}

document.addEventListener('htmx:afterSwap', function (e) {
  var t = e.detail && e.detail.target;
  if (!t || !t.id || t.id.indexOf('cam-pwslot-') !== 0) return;
  var form = t.querySelector('form');
  if (!form) return;
  var opener = camPwOpener(t);
  if (opener) opener.setAttribute('aria-expanded', 'true');
  var f = form.querySelector('[aria-invalid="true"]') || form.querySelector('input[name="password"]');
  if (f) f.focus();
  t.scrollIntoView({ block: 'nearest' });
});

// Validación previa y errores del servidor del formulario de contraseña (reusa camFieldError/camClearError).
var CAM_PW_MISMATCH = 'No coinciden. Escríbelas las dos otra vez.';
function camPwFields(form) {
  return [form.querySelector('input[name="password"]'), form.querySelector('input[name="password_confirm"]')];
}
function camPwHint(pw) { return 'pw-hint-' + pw.id.replace(/^pw-/, ''); }
function camPwClear(form) {
  camPwFields(form).forEach(function (c) {
    if (!c) return;
    camClearError(c);
    if (c.name === 'password') c.setAttribute('aria-describedby', camPwHint(c));
  });
  var slot = form.closest('[id^="cam-pwslot-"]');
  var box = slot && document.getElementById('cam-pwerr-' + slot.id.slice('cam-pwslot-'.length));
  if (box) box.textContent = '';
}
document.addEventListener('htmx:beforeRequest', function (e) {
  var form = e.target;
  if (!form || !form.closest || form.tagName !== 'FORM' || !form.closest('[id^="cam-pwslot-"]')) return;
  var f = camPwFields(form), pw = f[0], pw2 = f[1];
  if (!pw || !pw2) return;
  camPwClear(form);
  if (pw.value && pw.value === pw2.value) return;
  e.preventDefault();
  var empty = !pw.value ? pw : (!pw2.value ? pw2 : null);
  if (empty) {
    camFieldError(empty, empty, empty === pw ? 'Escribe la contraseña nueva.' : 'Confírmala.');
    if (empty === pw) pw.setAttribute('aria-describedby', camPwHint(pw) + ' ' + pw.id + '-error');
    empty.focus();
    return;
  }
  // No coinciden: un solo mensaje bajo «Confírmala»; ambos campos inválidos.
  camFieldError(pw2, pw2, CAM_PW_MISMATCH);
  pw.setAttribute('aria-invalid', 'true');
  pw.setAttribute('aria-describedby', camPwHint(pw) + ' ' + pw2.id + '-error');
  pw2.focus();
});
document.addEventListener('input', function (e) {
  var t = e.target;
  if (t.matches && t.matches('input[name="password"], input[name="password_confirm"]') && t.closest('[id^="cam-pwslot-"]')) camPwClear(t.form);
});
// Error del servidor en el hueco: lo lleva a la vista; marca los campos solo si el error es del valor (X-Cam-Field).
document.addEventListener('htmx:afterSwap', function (e) {
  var t = e.detail && e.detail.target;
  if (!t || !t.id || t.id.indexOf('cam-pwerr-') !== 0 || !t.firstElementChild) return;
  var form = t.closest('form');
  var byValue = e.detail.xhr && e.detail.xhr.getResponseHeader('X-Cam-Field');
  if (form && byValue) camPwFields(form).forEach(function (c) {
    if (!c) return;
    c.setAttribute('aria-invalid', 'true');
    c.setAttribute('aria-describedby', (c.name === 'password' ? camPwHint(c) + ' ' : '') + t.id);
  });
  t.scrollIntoView({ block: 'nearest' });
  var first = byValue && form && form.querySelector('input[name="password"]');
  if (first) first.focus();
});

document.addEventListener('click', function (e) {
  var btn = e.target.closest && e.target.closest('[data-cam-pw-cancel]');
  if (!btn) return;
  var slot = document.getElementById('cam-pwslot-' + btn.getAttribute('data-cam-pw-cancel'));
  var opener = slot && camPwOpener(slot);
  if (slot) slot.innerHTML = '';
  if (opener) { opener.setAttribute('aria-expanded', 'false'); opener.focus(); }
});

function camPwOk(ok) {
  if (ok.dataset.camSeen) return;
  ok.dataset.camSeen = '1';
  var opener = camPwOpener(ok);
  if (opener) { opener.setAttribute('aria-expanded', 'false'); opener.focus(); }
  var sp = ok.querySelector('span');
  if (sp) { var txt = sp.textContent; sp.textContent = ''; setTimeout(function () { sp.textContent = txt; }, 150); }   // re-inyecta para anunciarlo
  setTimeout(function () { ok.classList.add('is-leaving'); }, 5800);
  setTimeout(function () { ok.remove(); }, 6000);
}

// === ÉXITOS EN LA LISTA ===
function camScanSuccess() {
  var row = document.querySelector('[data-cam-flash]');
  if (row && !row.dataset.camSeen) {
    row.dataset.camSeen = '1';
    row.scrollIntoView({ block: 'center' });
    row.classList.add('is-flashing');
    setTimeout(function () { row.classList.remove('is-flashing'); }, 2600);
  }
  var note = document.getElementById('cam-flash');
  if (note && !note.dataset.camSeen) {
    note.dataset.camSeen = '1';
    var span = note.querySelector('span') || note;
    var nodes = [].slice.call(span.childNodes);   // nodos, no texto: conserva el enlace
    span.textContent = '';
    setTimeout(function () { nodes.forEach(function (n) { span.appendChild(n); }); }, 150);   // re-inyecta para que el lector lo anuncie
  }
  var pw = document.querySelector('[data-cam-pw-ok]');
  if (pw) camPwOk(pw);
}
document.addEventListener('DOMContentLoaded', function () {
  camScanSuccess();
  // Evita que F5 o la sesión del escritorio repitan el aviso (?ok=, dvr=).
  // Solo esos dos parámetros: los filtros de la bitácora se conservan.
  var q = new URLSearchParams(location.search);
  if (q.has('ok') || q.has('dvr')) {
    q.delete('ok'); q.delete('dvr');
    var rest = q.toString();
    try { history.replaceState(null, '', location.pathname + (rest ? '?' + rest : '') + location.hash); } catch (_) { /* sin history */ }
  }
});
document.addEventListener('htmx:afterSettle', camScanSuccess);

// === Buscar departamento: Enter no envía el formulario ===
document.addEventListener('keydown', function (e) {
  if (e.key === 'Enter' && e.target.closest && e.target.closest('[data-cam-filter]')) e.preventDefault();
});
