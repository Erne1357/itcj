// socket-base.js - Configuración base para todos los clientes WebSocket
window.SOCKET_CONFIG = {
    baseUrl: window.location.origin,
    options: {
        withCredentials: true,
        forceNew: false,
        reconnection: true,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        maxReconnectionAttempts: 5,
        timeout: 20000,
        transports: ['polling', 'websocket'], // Permitir ambos
        upgrade: true,
        rememberUpgrade: true
    }
};

// Función para cargar Socket.IO si no está disponible
window.ensureSocketIO = () => {
    return new Promise((resolve, reject) => {
        if (window.io) {
            resolve();
            return;
        }
        
        const script = document.createElement('script');
        script.src = 'https://cdn.socket.io/4.7.5/socket.io.min.js';
        script.crossOrigin = 'anonymous';
        script.onload = () => resolve();
        script.onerror = (e) => reject(e);
        document.head.appendChild(script);
    });
};

// Debug helper
window.debugSocket = (socket, name) => {
    if (!socket) return;
    
    socket.on('connect', () => {
    });
    
    socket.on('disconnect', (reason) => {
    });
    
    socket.on('connect_error', (error) => {
        console.error(`[${name}] Error de conexión:`, error);
    });
    
    socket.on('error', (error) => {
        console.error(`[${name}] Error del servidor:`, error);
    });
};