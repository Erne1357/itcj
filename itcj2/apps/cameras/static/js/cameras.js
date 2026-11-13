/* Cámaras: deja que HTMX pinte las respuestas de error de dominio (404/422/503 con X-Cam-Error). */
document.addEventListener('htmx:beforeSwap', function (e) {
  var xhr = e.detail.xhr;
  if (xhr && (xhr.status === 404 || xhr.status === 422 || xhr.status === 503) && xhr.getResponseHeader('X-Cam-Error')) {
    e.detail.shouldSwap = true;
    e.detail.isError = false;
  }
});
