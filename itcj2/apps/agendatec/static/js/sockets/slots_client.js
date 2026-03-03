// slots_client.js - Cliente corregido para slots
(() => {
    // Evitar múltiples inicializaciones
    if (window.__slotsSocket) {
        return;
    }

    // Asegurar que Socket.IO esté disponible
    window.ensureSocketIO().then(() => {
        // Conectar al namespace /slots
        const socket = io('/slots', window.SOCKET_CONFIG.options);
        window.__slotsSocket = socket;
        
        // Debug
        window.debugSocket(socket, 'Slots');
        
        // Eventos específicos del namespace
        socket.on('hello', (payload) => {
        });
        
        socket.on('joined_day', (data) => {
        });
        
        socket.on('slots_snapshot', (data) => {
            // Actualizar UI aquí
        });
        
        socket.on('slot_held', (data) => {
            // Actualizar UI aquí
        });
        
        socket.on('slot_released', (data) => {
            // Actualizar UI aquí
        });
        
        // Funciones helper globales
        window.__joinDay = (day) => {
            if (socket && socket.connected) {
                socket.emit('join_day', { day });
            } else {
                console.warn('[Slots] Socket no conectado para join_day');
            }
        };
        
        window.__leaveDay = (day) => {
            if (socket && socket.connected) {
                socket.emit('leave_day', { day });
            }
        };
        
        window.__holdSlot = (slot_id) => {
            if (socket && socket.connected) {
                socket.emit('hold_slot', { slot_id });
            }
        };
        
        window.__releaseHold = (slot_id) => {
            if (socket && socket.connected) {
                socket.emit('release_hold', { slot_id });
            }
        };
        
    }).catch(err => {
        console.error('[Slots] Error cargando Socket.IO:', err);
    });
})();