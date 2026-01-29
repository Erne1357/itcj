// static/js/sockets/helpdesk_client.js
/**
 * Cliente WebSocket para Helpdesk
 * Namespace: /helpdesk
 *
 * Proporciona conexión en tiempo real para:
 * - Dashboard del técnico
 * - Detalle de tickets
 * - Lista de tickets (admin/secretaria)
 */
(() => {
    // Verificar que Socket.IO esté cargado
    if (!window.io) {
        console.warn("[WS helpdesk] socket.io client no cargado");
        return;
    }

    // Evitar doble inicialización
    if (window.__helpdeskSocket) return;

    // Crear conexión al namespace /helpdesk
    const socket = io("/helpdesk", {
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
    window.__helpdeskSocket = socket;

    // ==================== Connection Events ====================

    socket.on("connect", () => {
        console.log("[WS helpdesk] Conectado");
    });

    socket.on("disconnect", (reason) => {
        console.log("[WS helpdesk] Desconectado:", reason);
    });

    socket.on("connect_error", (e) => {
        console.error("[WS helpdesk] Error de conexión:", e?.message || e);
    });

    socket.on("hello", (data) => {
        console.log("[WS helpdesk]", data?.msg);
    });

    socket.on("error", (data) => {
        console.warn("[WS helpdesk] Error del servidor:", data?.error);
    });

    // ==================== Global Helpers ====================

    /**
     * Unirse al room de un ticket específico
     * @param {number} ticketId - ID del ticket
     */
    window.__hdJoinTicket = (ticketId) => {
        if (!ticketId) return;
        socket.emit("join_ticket", { ticket_id: ticketId });
    };

    /**
     * Salir del room de un ticket
     * @param {number} ticketId - ID del ticket
     */
    window.__hdLeaveTicket = (ticketId) => {
        if (!ticketId) return;
        socket.emit("leave_ticket", { ticket_id: ticketId });
    };

    /**
     * Unirse al room personal del técnico
     * (Usa el user_id del JWT automáticamente en el servidor)
     */
    window.__hdJoinTech = () => {
        socket.emit("join_tech", {});
    };

    /**
     * Salir del room personal del técnico
     */
    window.__hdLeaveTech = () => {
        socket.emit("leave_tech", {});
    };

    /**
     * Unirse al room del equipo (desarrollo/soporte)
     * @param {string} area - "desarrollo" o "soporte"
     */
    window.__hdJoinTeam = (area) => {
        if (!area) return;
        socket.emit("join_team", { area: area.toLowerCase() });
    };

    /**
     * Salir del room del equipo
     * @param {string} area - "desarrollo" o "soporte"
     */
    window.__hdLeaveTeam = (area) => {
        if (!area) return;
        socket.emit("leave_team", { area: area.toLowerCase() });
    };

    /**
     * Unirse al room de admin (todos los tickets - solo centro de cómputo)
     */
    window.__hdJoinAdmin = () => {
        socket.emit("join_admin", {});
    };

    /**
     * Salir del room de admin
     */
    window.__hdLeaveAdmin = () => {
        socket.emit("leave_admin", {});
    };

    /**
     * Unirse al room de un departamento específico (para secretarias)
     * @param {number} departmentId - ID del departamento
     */
    window.__hdJoinDept = (departmentId) => {
        if (!departmentId) return;
        socket.emit("join_dept", { department_id: departmentId });
    };

    /**
     * Salir del room de un departamento
     * @param {number} departmentId - ID del departamento
     */
    window.__hdLeaveDept = (departmentId) => {
        if (!departmentId) return;
        socket.emit("leave_dept", { department_id: departmentId });
    };

    // ==================== Debug Confirmations ====================

    socket.on("joined_ticket", (data) => {
        console.log("[WS helpdesk] Unido a ticket:", data?.ticket_id);
    });

    socket.on("joined_tech", (data) => {
        console.log("[WS helpdesk] Unido a tech room:", data?.user_id);
    });

    socket.on("joined_team", (data) => {
        console.log("[WS helpdesk] Unido a team:", data?.area);
    });

    socket.on("joined_admin", () => {
        console.log("[WS helpdesk] Unido a admin room");
    });

    socket.on("joined_dept", (data) => {
        console.log("[WS helpdesk] Unido a dept room:", data?.department_id);
    });

})();
