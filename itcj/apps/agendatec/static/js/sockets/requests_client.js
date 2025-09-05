// static/js/sockets/requests_client.js
(() => {
  if (!window.io) {
    console.warn("socket.io client no cargado");
    return;
  }
  if (window.__reqSocket) return;

  const socket = io("/requests", {
    withCredentials: true,
    reconnection: true,
    timeout: 20000,
    transport: ["websocket"],
    upgrade: true
  });
  window.__reqSocket = socket;

  socket.on("connect", () => console.log("[WS req] conectado", socket.id));
  socket.on("disconnect", (r) => console.log("[WS req] desconectado:", r));
  socket.on("connect_error", (e) => console.error("[WS req] error:", e?.message || e));
  socket.on("hello", (p) => console.log("[WS req] hello:", p));

  // Helpers globales para otros scripts
  window.__reqJoinApDay = ({ coord_id, day }) => {
    if (!coord_id || !day) return;
    socket.emit("join_ap_day", { coord_id, day });
  };
  window.__reqLeaveApDay = ({ coord_id, day }) => {
    if (!coord_id || !day) return;
    socket.emit("leave_ap_day", { coord_id, day });
  };
  window.__reqJoinDrops = ({ coord_id }) => {
    if (!coord_id) return;
    socket.emit("join_drops", { coord_id });
  };
})();
