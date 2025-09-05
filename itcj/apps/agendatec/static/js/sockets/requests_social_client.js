// static/js/sockets/requests_social_client.js
(() => {
  const ensureIo = () =>
    new Promise((resolve, reject) => {
      if (window.io) return resolve();
      const s = document.createElement("script");
      s.src = "https://cdn.socket.io/4.7.5/socket.io.min.js";
      s.crossOrigin = "anonymous";
      s.onload = () => resolve();
      s.onerror = (e) => reject(e);
      document.head.appendChild(s);
    });

  ensureIo().then(() => {
    if (window.__reqSocket) return; // reutiliza si ya existe
    const socket = io("/requests", {
      withCredentials: true,
      reconnection: true,
      timeout: 20000,
      transport: ["websocket"],
      upgrade: true
    });
    window.__reqSocket = socket;

    socket.on("connect", () => console.log("[WS social] conectado", socket.id));
    socket.on("disconnect", (r) => console.log("[WS social] desconectado:", r));
    socket.on("connect_error", (e) => console.error("[WS social] error:", e?.message || e));
    socket.on("hello", (p) => console.log("[WS social] hello:", p));

    // Helpers para unirse/dejar rooms por día/programa
    window.__socialJoinApDay = ({ day, program_id }) => {
      if (!day) return;
      socket.emit("join_social_ap_day", { day, program_id: program_id ? Number(program_id) : null });
    };
    window.__socialLeaveApDay = ({ day, program_id }) => {
      if (!day) return;
      socket.emit("leave_social_ap_day", { day, program_id: program_id ? Number(program_id) : null });
    };
  }).catch((err) => {
    console.error("[WS social] no se pudo cargar socket.io", err);
  });
})();
