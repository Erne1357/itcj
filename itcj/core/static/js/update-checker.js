/**
 * update-checker.js
 *
 * Detecta cuando los archivos estaticos de la pagina actual fueron actualizados
 * y muestra un banner discreto sugiriendo recargar.
 *
 * Este script es parte del Pilar 3 del plan de zero-downtime deployment.
 * Solo notifica a usuarios cuya pagina usa archivos que cambiaron.
 */
(() => {
  'use strict';

  // 1. Recopilar los archivos estaticos que esta pagina cargo
  const loadedFiles = new Set();

  // CSS (stylesheets)
  document.querySelectorAll('link[rel="stylesheet"][href*="/static/"]').forEach(el => {
    const match = el.href.match(/\/static\/(.+?)(?:\?|$)/);
    if (match) loadedFiles.add(match[1]);
  });

  // JavaScript
  document.querySelectorAll('script[src*="/static/"]').forEach(el => {
    const match = el.src.match(/\/static\/(.+?)(?:\?|$)/);
    if (match) loadedFiles.add(match[1]);
  });

  // Imagenes (opcional, para assets importantes)
  document.querySelectorAll('img[src*="/static/"]').forEach(el => {
    const match = el.src.match(/\/static\/(.+?)(?:\?|$)/);
    if (match) loadedFiles.add(match[1]);
  });

  // Si no hay archivos estaticos, no hacemos nada
  if (loadedFiles.size === 0) return;

  // 2. Esperar a que el socket de notificaciones se conecte
  const waitForSocket = () => {
    return new Promise((resolve) => {
      // Si ya existe el socket de notify, usarlo
      if (window.__notifySocket) {
        return resolve(window.__notifySocket);
      }

      // Esperar hasta 15s a que el socket de notificaciones se conecte
      let attempts = 0;
      const maxAttempts = 30;
      const interval = setInterval(() => {
        if (window.__notifySocket) {
          clearInterval(interval);
          resolve(window.__notifySocket);
        }
        if (++attempts > maxAttempts) {
          clearInterval(interval);
          resolve(null);
        }
      }, 500);
    });
  };

  waitForSocket().then(socket => {
    if (!socket) {
      console.debug('[UpdateChecker] Socket de notificaciones no disponible');
      return;
    }

    // 3. Escuchar el evento de actualizacion
    socket.on('static_update', (data) => {
      const changed = data.changed || [];

      if (changed.length === 0) return;

      // 4. Verificar si alguno de los archivos de ESTA pagina cambio
      const affected = changed.filter(f => loadedFiles.has(f));

      if (affected.length === 0) {
        console.debug('[UpdateChecker] Deploy detectado pero esta pagina no esta afectada');
        return;
      }

      console.info('[UpdateChecker] Archivos actualizados:', affected);

      // 5. Mostrar banner de actualizacion
      showUpdateBanner(affected);
    });

    console.debug('[UpdateChecker] Escuchando actualizaciones para', loadedFiles.size, 'archivos');
  });

  /**
   * Muestra un banner discreto indicando que hay una nueva version disponible
   */
  function showUpdateBanner(affectedFiles) {
    // Evitar mostrar multiples banners
    if (document.getElementById('static-update-banner')) return;

    const banner = document.createElement('div');
    banner.id = 'static-update-banner';
    banner.style.cssText = `
      position: fixed;
      bottom: 20px;
      right: 20px;
      z-index: 99999;
      background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
      color: #fff;
      padding: 16px 20px;
      border-radius: 12px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.1);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 14px;
      max-width: 360px;
      animation: updateBannerSlideIn 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
      display: flex;
      align-items: center;
      gap: 12px;
    `;

    banner.innerHTML = `
      <div style="flex-shrink:0; width:36px; height:36px; background:rgba(67,97,238,0.2); border-radius:50%; display:flex; align-items:center; justify-content:center;">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4361ee" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
      </div>
      <div style="flex:1; min-width:0;">
        <div style="font-weight:600; margin-bottom:2px; font-size:14px;">
          Nueva version disponible
        </div>
        <div style="opacity:0.7; font-size:12px; line-height:1.3;">
          Recarga para obtener las ultimas mejoras
        </div>
      </div>
      <button onclick="location.reload()"
        style="
          flex-shrink:0;
          background: #4361ee;
          color: #fff;
          border: none;
          padding: 8px 14px;
          border-radius: 8px;
          cursor: pointer;
          font-size: 13px;
          font-weight: 500;
          transition: background 0.2s, transform 0.1s;
        "
        onmouseover="this.style.background='#3651d4'"
        onmouseout="this.style.background='#4361ee'"
        onmousedown="this.style.transform='scale(0.95)'"
        onmouseup="this.style.transform='scale(1)'"
      >
        Recargar
      </button>
      <button onclick="this.parentElement.remove()"
        style="
          flex-shrink:0;
          background: none;
          border: none;
          color: #fff;
          opacity: 0.4;
          cursor: pointer;
          font-size: 20px;
          padding: 0 4px;
          line-height: 1;
          transition: opacity 0.2s;
        "
        onmouseover="this.style.opacity='0.8'"
        onmouseout="this.style.opacity='0.4'"
        title="Cerrar"
      >
        &times;
      </button>
    `;

    // Agregar animacion CSS si no existe
    if (!document.getElementById('update-banner-styles')) {
      const style = document.createElement('style');
      style.id = 'update-banner-styles';
      style.textContent = `
        @keyframes updateBannerSlideIn {
          from {
            transform: translateY(100px) scale(0.9);
            opacity: 0;
          }
          to {
            transform: translateY(0) scale(1);
            opacity: 1;
          }
        }
      `;
      document.head.appendChild(style);
    }

    document.body.appendChild(banner);

    // Auto-dismiss despues de 60 segundos
    setTimeout(() => {
      if (banner.parentElement) {
        banner.style.animation = 'updateBannerSlideIn 0.3s ease-out reverse';
        setTimeout(() => banner.remove(), 300);
      }
    }, 60000);
  }
})();
