// slots_client.js - Cliente corregido para slots
(() => {
    // Evitar múltiples inicializaciones
    if (window.__slotsSocket) {
        console.log("[Slots] Ya existe conexión, reutilizando");
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
            console.log('[Slots] Hello:', payload);
        });
        
        socket.on('joined_day', (data) => {
            console.log('[Slots] Joined day:', data);
        });
        
        socket.on('slots_snapshot', (data) => {
            console.log('[Slots] Snapshot:', data);
            // Actualizar UI aquí
        });
        
        socket.on('slot_held', (data) => {
            console.log('[Slots] Slot held:', data);
            // Actualizar UI aquí
        });
        
        socket.on('slot_released', (data) => {
            console.log('[Slots] Slot released:', data);
            // Actualizar UI aquí
        });
        
        // Funciones helper globales
        window.__joinDay = (day) => {
            if (socket && socket.connected) {
                console.log(`[Slots] Joining day: ${day}`);
                socket.emit('join_day', { day });
            } else {
                console.warn('[Slots] Socket no conectado para join_day');
            }
        };
        
        window.__leaveDay = (day) => {
            if (socket && socket.connected) {
                console.log(`[Slots] Leaving day: ${day}`);
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