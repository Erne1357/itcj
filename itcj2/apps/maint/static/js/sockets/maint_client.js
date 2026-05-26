// static/js/sockets/maint_client.js
/**
 * Cliente WebSocket para Mantenimiento
 * Namespace: /maint
 *
 * Proporciona conexión en tiempo real para:
 * - Dashboard del técnico de mantenimiento
 * - Detalle de tickets
 * - Vista del dispatcher (todos los tickets)
 * - Vistas por departamento
 *
 * Socket.IO es inyectado por app-fab-widget.js; si el FAB aún no corrió,
 * este fallback garantiza que el CDN esté cargado antes de conectar.
 */
(() => {
    function _initMaintSocket() {
        // Evitar doble inicialización
        if (window.__maintSocket) return;

        // Crear conexión al namespace /maint
        const socket = io("/maint", {
            withCredentials: true,
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 5000,
            reconnectionAttempts: 5,
            timeout: 20000,
            transports: ["websocket", "polling"],
            upgrade: true
        });

        // Exponer socket globalmente
        window.__maintSocket = socket;

        // ==================== Connection Events ====================

        socket.on("connect", () => {
            console.log("[WS maint] Conectado");
        });

        socket.on("disconnect", (reason) => {
            console.log("[WS maint] Desconectado:", reason);
        });

        socket.on("connect_error", (e) => {
            console.error("[WS maint] Error de conexión:", e?.message || e);
        });

        socket.on("hello", (data) => {
            console.log("[WS maint]", data?.msg);
        });

        socket.on("error", (data) => {
            console.warn("[WS maint] Error del servidor:", data?.error);
        });

        // ==================== Global Helpers ====================

        /**
         * Unirse al room de un ticket específico
         * @param {number} ticketId - ID del ticket
         */
        window.__maintJoinTicket = (ticketId) => {
            if (!ticketId) return;
            socket.emit("join_ticket", { ticket_id: ticketId });
        };

        /**
         * Salir del room de un ticket
         * @param {number} ticketId - ID del ticket
         */
        window.__maintLeaveTicket = (ticketId) => {
            if (!ticketId) return;
            socket.emit("leave_ticket", { ticket_id: ticketId });
        };

        /**
         * Unirse al room personal del técnico/usuario
         * (Usa el user_id del JWT automáticamente en el servidor)
         */
        window.__maintJoinTech = () => {
            socket.emit("join_tech", {});
        };

        /**
         * Salir del room personal del técnico/usuario
         */
        window.__maintLeaveTech = () => {
            socket.emit("leave_tech", {});
        };

        /**
         * Unirse al room del dispatcher (todos los tickets)
         */
        window.__maintJoinDispatcher = () => {
            socket.emit("join_dispatcher", {});
        };

        /**
         * Salir del room del dispatcher
         */
        window.__maintLeaveDispatcher = () => {
            socket.emit("leave_dispatcher", {});
        };

        /**
         * Unirse al room de un departamento específico
         * @param {number} deptId - ID del departamento
         */
        window.__maintJoinDept = (deptId) => {
            if (!deptId) return;
            socket.emit("join_dept", { department_id: deptId });
        };

        /**
         * Salir del room de un departamento
         * @param {number} deptId - ID del departamento
         */
        window.__maintLeaveDept = (deptId) => {
            if (!deptId) return;
            socket.emit("leave_dept", { department_id: deptId });
        };

        // ==================== Debug Confirmations ====================

        socket.on("joined_ticket", (data) => {
            console.log("[WS maint] Unido a ticket:", data?.ticket_id);
        });

        socket.on("joined_tech", (data) => {
            console.log("[WS maint] Unido a tech room:", data?.user_id);
        });

        socket.on("joined_dispatcher", () => {
            console.log("[WS maint] Unido a dispatcher room");
        });

        socket.on("joined_dept", (data) => {
            console.log("[WS maint] Unido a dept room:", data?.department_id);
        });
    }

    // Fallback: cargar Socket.IO CDN si el FAB aún no lo inyectó
    if (window.io) {
        _initMaintSocket();
    } else {
        const script = document.createElement("script");
        script.src = "https://cdn.socket.io/4.7.2/socket.io.min.js";
        script.onload = _initMaintSocket;
        script.onerror = () => console.error("[WS maint] No se pudo cargar socket.io desde CDN");
        document.head.appendChild(script);
    }
})();
