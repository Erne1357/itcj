/* Cámaras: deja que HTMX pinte las respuestas de error de dominio (404/422/500/503 con X-Cam-Error). */
document.addEventListener('htmx:beforeSwap', function (e) {
  var xhr = e.detail.xhr;
  if (xhr && (xhr.status === 404 || xhr.status === 422 || xhr.status === 500 || xhr.status === 503) && xhr.getResponseHeader('X-Cam-Error')) {
    e.detail.shouldSwap = true;
    e.detail.isError = false;
  }
});

// === BAJA DE DVR (confirmación con el modal compartido; nunca confirm nativo) ===
document.addEventListener('click', async function (e) {
  var btn = e.target.closest && e.target.closest('[data-cam-deactivate]');
  if (!btn || btn.disabled) return;
  var ok = await window.AppModal.confirm({
    title: 'Dar de baja el DVR',
    message: '«' + btn.getAttribute('data-name') + '» dejará de aparecer en la lista. La bitácora conserva su historial.',
    confirmText: 'Dar de baja', confirmVariant: 'danger', cancelText: 'Cancelar'
  });
  if (!ok) return;
  btn.disabled = true;
  try {
    var res = await fetch('/cameras/dvrs/' + btn.getAttribute('data-cam-deactivate') + '/deactivate',
      { method: 'POST', credentials: 'same-origin', headers: { 'HX-Request': 'true' } });
    if (res.ok) { window.location.reload(); return; }
    var msg = res.headers.get('X-Cam-Error');
    await window.AppModal.alert({ title: 'No se pudo dar de baja',
      message: msg ? decodeURIComponent(msg) : 'Error inesperado. Intenta de nuevo.' });
  } catch (err) {
    await window.AppModal.alert({ title: 'No se pudo dar de baja', message: 'Sin conexión con el servidor.' });
  }
  btn.disabled = false;
});

// === Buscar departamento: Enter no envía el formulario ===
document.addEventListener('keydown', function (e) {
  if (e.key === 'Enter' && e.target.closest && e.target.closest('[data-cam-filter]')) e.preventDefault();
});

// === Cancelar el cambio de contraseña (vacía el hueco de la tarjeta) ===
document.addEventListener('click', function (e) {
  var btn = e.target.closest && e.target.closest('[data-cam-pw-cancel]');
  if (!btn) return;
  var slot = document.getElementById('cam-pwslot-' + btn.getAttribute('data-cam-pw-cancel'));
  if (slot) slot.innerHTML = '';
});
