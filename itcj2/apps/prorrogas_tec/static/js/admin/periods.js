const cfg = window.adminPeriods;

let currentItems = [];
let editingId = null;

// ✅ MODALES
let mdlForm, mdlConfirm;

document.addEventListener("DOMContentLoaded", () => {
  mdlForm = new bootstrap.Modal(document.getElementById("mdlPeriod"));
  mdlConfirm = new bootstrap.Modal(document.getElementById("mdlConfirm"));

  document.getElementById("btnReload").addEventListener("click", loadItems);
  document.getElementById("btnNew").addEventListener("click", () => openModal());
  document.getElementById("btnSavePeriod").addEventListener("click", saveItem);

  loadItems();
  loadPeriodsSelect();
});

async function loadPeriodsSelect() {
  try {
    console.log("URL:", cfg.academicPeriods);

    const resp = await fetch(cfg.academicPeriods);

    if (!resp.ok) {
      const text = await resp.text();
      console.error("ERROR:", text);
      throw new Error("Error al cargar academic periods");
    }

    const data = await resp.json();
    console.log("DATA:", data);

    const select = document.getElementById("fPeriodId");

    if (!select) {
      console.error("No existe select fPeriodId");
      return;
    }

    select.innerHTML = `<option value="">Selecciona un período</option>`;

    data.forEach(p => {
      select.innerHTML += `
        <option value="${p.id}">
          ${p.code} - ${p.name}
        </option>
      `;
    });

  } catch (err) {
    console.error("ERROR SELECT:", err);
    console.log("URL:", cfg.listUrl);
  }
}




// ✅ =============================
// ✅ LISTAR
// ✅ =============================
async function loadItems() {
  try {
    const resp = await fetch(cfg.listUrl);

    const text = await resp.text();  // 👈 lee SIEMPRE como texto primero
    console.log("RESPUESTA RAW:", text); // 👈 AQUÍ verás el problema

    if (!resp.ok) {
      throw new Error(text);
    }

    const data = JSON.parse(text);

    currentItems = data;
       document.getElementById("lblTotal").textContent =
      `${currentItems.length} registros`;
    renderTable();

  } catch (err) {
    console.error("ERROR:", err);
  }
}



// ✅ =============================
// ✅ RENDER TABLA
// ✅ =============================
function renderTable() { 
  const tbody = document.getElementById("tblPeriod");

  if (!currentItems.length) {
    tbody.innerHTML = `<tr><td colspan="5">Sin datos</td></tr>`;
    return;
  }

  tbody.innerHTML = currentItems.map(p => `
    <tr>
      <td>${p.id}</td>
      <td>${p.period ? p.period.name : "-"}</td>
      <td>${formatDateTime(p.student_admission_start)}</td>
      <td>${formatDateTime(p.student_admission_deadline)}</td>
      <td>${formatDateTime(p.payment_1)}</td>
      <td>${formatDateTime(p.payment_2)}</td>
      <td>${formatDateTime(p.payment_3)}</td>
      <td>
        <button onclick="editItem(${p.id})" class="btn btn-sm btn-primary">Editar</button>
        <button onclick="deleteItem(${p.id})" class="btn btn-sm btn-danger">Eliminar</button>
      </td>
    </tr>
  `).join("");
}


// ✅ =============================
// ✅ ABRIR MODAL
// ✅ =============================
function openModal(id = null) {
  editingId = id;

  if (id) {
    const item = currentItems.find(p => p.id === id);

    document.getElementById("fPeriodId").value = item.period_id;

    setDateTimeInputs("fAdmissionStartDate", "fAdmissionStartTime", item.student_admission_start);
    setDateTimeInputs("fDeadlineDate", "fDeadlineTime", item.student_admission_deadline);
    document.getElementById("fPayment1").value =
    item.payment_1 ? item.payment_1.slice(0, 10) : "";

    document.getElementById("fPayment2").value =
      item.payment_2 ? item.payment_2.slice(0, 10) : "";

    document.getElementById("fPayment3").value =
      item.payment_3 ? item.payment_3.slice(0, 10) : "";
  } else {
    document.getElementById("fPeriodId").value = "";

    clearDateTime("fAdmissionStartDate", "fAdmissionStartTime");
    clearDateTime("fDeadlineDate", "fDeadlineTime");
    document.getElementById("fPayment1").value = "";
    document.getElementById("fPayment2").value = "";
    document.getElementById("fPayment3").value = "";
  }

  mdlForm.show();
}


// ✅ =============================
// ✅ GUARDAR (POST / PATCH)
// ✅ =============================
async function saveItem() {

  const period_id = parseInt(document.getElementById("fPeriodId").value);

  const start = buildDate("fAdmissionStartDate", "fAdmissionStartTime");
  const deadline = buildDate("fDeadlineDate", "fDeadlineTime");

  if (!period_id || !start || !deadline) {
    alert("Datos incompletos");
    return;
  }

  if (new Date(deadline) <= new Date(start)) {
    alert("La fecha límite debe ser mayor que la inicial");
    return;
  }

  const payload = {
    period_id,
    student_admission_start: start,
    student_admission_deadline: deadline,
    
    payment_1: document.getElementById("fPayment1").value || null,
    payment_2: document.getElementById("fPayment2").value || null,
    payment_3: document.getElementById("fPayment3").value || null
  };

  try {
    let url, method;

    if (editingId) {
      url = cfg.update.replace("{id}", editingId);
      method = "PATCH";
    } else {
      url = cfg.createUrl;
      method = "POST";
    }

    const resp = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    
    const text = await resp.text();
    console.log("RESPUESTA RAW:", text);

    let data;
    try {
      data = JSON.parse(text);
    } catch (e) {
      console.error("No es JSON válido");
      throw new Error("El backend no devolvió JSON");
    }


    if (!resp.ok) {
      console.log("ERROR BACKEND:", data);  // 👈 IMPORTANTE
      throw new Error(data.detail || JSON.stringify(data));
    }

    mdlForm.hide();
    loadItems();

  } catch (err) {
    console.error(err);
    alert(err.message);
  }
}


// ✅ =============================
// ✅ EDITAR
// ✅ =============================
function editItem(id) {
  openModal(id);
}

// ✅ =============================
// ✅ ELIMINAR
// ✅ =============================
async function deleteItem(id) {

  const period = currentItems.find(p => p.id === id);

  if (!period) {
    showToast("Registro no encontrado", "error");
    return;
  }

  const periodName = period.period
    ? `${period.period.code} - ${period.period.name}`
    : period.period_id;

  showConfirm(
    "Eliminar período",
    `¿Eliminar el período "${periodName}"?\n\nEsta acción no se puede deshacer.`,
    async () => {
      try {
        const url = cfg.delete.replace("{id}", id);

        const resp = await fetch(url, {
          method: "DELETE"
        });

        const text = await resp.text();
        const data = text ? JSON.parse(text) : {};

        if (!resp.ok) {
          throw new Error(data.detail || "Error al eliminar");
        }

        loadItems();
        showToast("Período eliminado correctamente", "success");

      } catch (err) {
        console.error(err);
        showToast("Error al eliminar: " + err.message, "error");
      }
    }
  );
}
async function deletePeriod(periodId) {
  const period = currentPeriods.find(p => p.id === periodId);
  showConfirm(
    "Eliminar período",
    `¿Eliminar el período "${period.name}"?\n\nEsta acción no se puede deshacer.`,
    async () => {
      try {
        const resp = await fetch(cfg.delete.replace('{id}', periodId), {
          method: "DELETE",
          credentials: "same-origin"
        });

        if (!resp.ok) {
          const data = await resp.json();
          throw new Error(data.message || data.error || "Error al eliminar");
        }

        showToast("Período eliminado correctamente", "success");
        loadPeriods();
      } catch (err) {
        console.error(err);
        showToast("Error al eliminar: " + err.message, "error");
      }
    }
  );
}

// ✅ =============================
// ✅ HELPERS
// ✅ =============================

function buildDate(dateId, timeId) {
  const d = document.getElementById(dateId).value;
  const t = document.getElementById(timeId).value;
  if (!d || !t) return null;
  return `${d}T${t}:00`;
}

function setDateTimeInputs(dateId, timeId, iso) {
  if (!iso) return;

  const d = new Date(iso);
  document.getElementById(dateId).value = d.toISOString().split("T")[0];
  document.getElementById(timeId).value = d.toTimeString().slice(0, 5);
}

function clearDateTime(dateId, timeId) {
  document.getElementById(dateId).value = "";
  document.getElementById(timeId).value = "00:00";
}

function formatDateTime(dt) {
  if (!dt) return "-";
  return new Date(dt).toLocaleString();
}


// Confirmation modal helper
function showConfirm(title, message, onConfirm) {
  const titleEl = document.getElementById("mdlConfirmTitle");
  const body = document.getElementById("mdlConfirmBody");

  titleEl.textContent = title;
  body.innerHTML = message.replace(/\n/g, "<br>");

  const btnConfirm = document.getElementById("btnConfirmAction");
  const newBtn = btnConfirm.cloneNode(true);
  btnConfirm.parentNode.replaceChild(newBtn, btnConfirm);

  newBtn.addEventListener("click", () => {
    mdlConfirm.hide();
    if (onConfirm) onConfirm();
  });

  mdlConfirm.show();
}

