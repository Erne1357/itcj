/**
 * presence-client.js — conexión /notify PRESENCE-ONLY del shell de config.
 *
 * El propio /itcj/config no cargaba ningún widget que conecte /notify, así que
 * los admins configurando el sistema no contaban como "en línea" (gap de spec
 * §3.5). Este módulo abre (o reutiliza) la conexión compartida window.__notifySocket
 * — mismo contrato que app-fab-widget/notification-widget — y no pinta nada.
 *
 * Vive en los scripts BASE de config_base.html (fuera del registry ConfigPage):
 * debe sobrevivir a los morphs de navegación, no tiene ciclo init/destroy.
 */
(function () {
    'use strict';
    if (window.__cfgPresenceClient) return;   // singleton (scripts base cargan 1 vez)
    window.__cfgPresenceClient = true;

    function connect() {
        if (!window.io) {
            console.warn('[ConfigPresence] socket.io no disponible');
            return;
        }
        if (window.__notifySocket) return;    // ya hay conexión compartida
        window.__notifySocket = window.io('/notify', {
            withCredentials: true,
            reconnection: true,
            timeout: 20000,
            transports: ['websocket', 'polling']
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', connect);
    } else {
        connect();
    }
})();
