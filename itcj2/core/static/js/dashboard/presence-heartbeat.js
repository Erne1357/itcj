/**
 * presence-heartbeat.js — el shell reporta al servidor QUÉ app tiene abierta.
 *
 * Ronda 3 de observabilidad: la presencia solo se refrescaba en connect/
 * disconnect del socket /notify, así que la poda en lectura de la ventana de
 * 5 min (`PRESENCE_WINDOW_SECONDS`) borraba a gente que seguía conectada — y
 * no había ninguna señal de EN QUÉ app estaba cada quien (contrato completo
 * en `itcj2/sockets/notifications.py::HEARTBEAT_EVENT`). Este módulo manda
 * `{"app": "<app_key>"}` por el MISMO socket /notify que ya abre
 * notification-widget.js (namespace compartido `window.__notifySocket`, el
 * patrón que ya usan app-fab-widget/profile/mobile-notifications): nada de
 * abrir un socket nuevo ni de escribir a Redis por la vía HTTP.
 *
 * `app_key` no se valida ni se normaliza aquí a propósito: el vocabulario
 * cerrado (las 9 apps + alias `help-desk`/`itcj`) ya vive en
 * `itcj2/observability/route.py::normalize_app_key` y el servidor cuenta
 * cualquier otra cosa como "otro" sin descartar el latido (ver contrato del
 * evento). Duplicar esa lista aquí sería la misma trampa que ya se evitó en
 * `presence_service.py` (una sola fuente de verdad para el vocabulario).
 *
 * Un solo `setInterval` para toda la vida de la pestaña: `startTimer()` es
 * idempotente, así que navegar entre apps mil veces (mil llamadas a
 * `reportApp`) nunca crea un segundo temporizador.
 *
 * No pausamos ni espaciamos con `visibilitychange`: seguimos latiendo cada
 * ~60 s tenga o no el foco la pestaña. Es a propósito — el shell es la única
 * pestaña que sostiene el socket /notify de las apps embebidas, así que
 * taparla (cambiar a otra pestaña del navegador) no debe verse como
 * "el usuario se fue". Con esto la ventana de poda de 300 s (5 latidos de
 * tolerancia, R49) nunca se acerca a expirar solo por perder el foco.
 */
(function () {
    'use strict';
    if (window.CorePresenceHeartbeat) return; // singleton: el script solo se incluye una vez en dashboard.html

    var HEARTBEAT_EVENT = 'presence_heartbeat';
    var HEARTBEAT_INTERVAL_MS = 60000;
    var DEFAULT_APP = 'core'; // shell sin ninguna app abierta en el iframe (contrato de la ronda 3)

    var currentApp = DEFAULT_APP;
    var socket = null;
    var timerId = null;

    function ensureSocketIO() {
        return new Promise(function (resolve, reject) {
            if (window.io) {
                resolve();
                return;
            }
            var script = document.createElement('script');
            script.src = '/static/core/js/vendor/socket.io.min.js?v=4.7.5';
            script.onload = function () { resolve(); };
            script.onerror = function (e) { reject(e); };
            document.head.appendChild(script);
        });
    }

    function emitHeartbeat() {
        // Sin conexión viva no hay nada que mandar; el próximo tick (o el
        // 'connect' de una reconexión) lo vuelve a intentar solo.
        if (!socket || !socket.connected) return;
        socket.emit(HEARTBEAT_EVENT, { app: currentApp });
    }

    function startTimer() {
        if (timerId !== null) return; // ya hay un temporizador corriendo — nunca duplicar
        timerId = setInterval(emitHeartbeat, HEARTBEAT_INTERVAL_MS);
    }

    function connect() {
        ensureSocketIO().then(function () {
            // Reusar la conexión compartida si otro widget (notificaciones,
            // FAB, perfil) ya la abrió; si no, abrirla nosotros — mismo
            // patrón "check-and-set" que ya usan esos módulos.
            socket = window.__notifySocket || window.io('/notify', {
                withCredentials: true,
                reconnection: true,
                timeout: 20000,
                transports: ['websocket', 'polling']
            });
            window.__notifySocket = socket;

            // Latido al (re)conectar: el `connect` del servidor marca el
            // bucket de presencia pero NO la app (ver HEARTBEAT_EVENT), así
            // que sin este latido el usuario no aparece en ninguna app hasta
            // el primer tick de 60 s. `on` (no `once`): una reconexión tras
            // una caída de red crea una sesión de socket NUEVA en el
            // servidor (sin la `app` guardada), así que también necesita su
            // propio latido inmediato, no solo la primera vez.
            if (socket.connected) {
                emitHeartbeat();
            }
            socket.on('connect', emitHeartbeat);
            startTimer();
        }).catch(function (err) {
            console.warn('[CorePresenceHeartbeat] no se pudo cargar socket.io:', err);
        });
    }

    /**
     * Llamado por el shell (WindowsDesktop) cada vez que cambia la app que el
     * usuario tiene al frente. Sin `appKey` (o con un valor vacío) reporta
     * "core" — el shell sin ninguna app abierta.
     */
    function reportApp(appKey) {
        var next = (appKey && String(appKey).trim()) || DEFAULT_APP;
        if (next === currentApp) return; // nada que reportar, ya es la app vigente
        currentApp = next;
        emitHeartbeat(); // se reporta YA; no hace falta esperar el próximo tick de 60 s
    }

    window.CorePresenceHeartbeat = { reportApp: reportApp };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', connect);
    } else {
        connect();
    }
})();
