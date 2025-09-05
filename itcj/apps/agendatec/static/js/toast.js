// Simple toast helper (Bootstrap 5)
window.showToast = (msg, type = "info") => {
  const wrap = document.getElementById("toastContainer");
  const el = document.createElement("div");
  el.className = "toast align-items-center text-bg-" + (
    type === "success" ? "success" :
    type === "error" ? "danger" :
    type === "warn" ? "warning" : "primary"
  ) + " border-0 mb-2";
  el.setAttribute("role", "alert");
  el.innerHTML = `
    <div class="d-flex">
      <div class="toast-body">${msg}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
    </div>`;
  wrap.appendChild(el);
  const t = new bootstrap.Toast(el, { delay: 3500 });
  t.show();
  el.addEventListener("hidden.bs.toast", () => el.remove());
};
