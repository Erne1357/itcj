const cfg = window.adminRequest;

let currentRequests = [];
let currentPayments = [];
let editingId = null;
let editingId2 = null;
let editingId3 = null;
let  mdlConfirm, mdlRequest, mdlPayments, mdlAprovepay;

document.addEventListener("DOMContentLoaded", () => {
mdlRequest = new bootstrap.Modal(document.getElementById("mdlRequest"));

mdlPayments = new bootstrap.Modal(document.getElementById("mdlPayments"));
mdlAprovepay = new bootstrap.Modal(document.getElementById("mdlAprovepay"));

document.getElementById("btnApprove").addEventListener("click", () => updateStatus("APPROVED"));
document.getElementById("btnDeny").addEventListener("click", () => updateStatus("REJECTED"));
document.getElementById("btnPending").addEventListener("click", () => updateStatus("PENDING"));


document.getElementById("btnConfirmAction2").addEventListener("click", updatePayment);

  loadRequests();
});

async function loadRequests() {
  try {
    const resp = await fetch(cfg.listUrl);

    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(text);
    }

    const data = await resp.json();

    currentRequests = data.items || data;
        document.getElementById("lblTotal").textContent =
      `${currentRequests.length} registros`;

    renderRequests();

  } catch (err) {
    console.error("ERROR:", err);
    console.log("URL:", cfg.listUrl);
  }
}



function renderRequests() {
    // const resp = await fetch(cfg.listUrl);
  const tbody = document.getElementById("tblReqBody");

  if (!currentRequests.length) {
    tbody.innerHTML = `<tr><td colspan="5">Sin solicitudes</td></tr>`;
    return;
  }

  tbody.innerHTML = currentRequests.map(r => `
    <tr>
      <td>${r.id}</td>
      <td>${r.student.control_number}</td>
    <td>${r.student.name}</td>
      <td>
        ${r.period ? r.period.name : r.period_id}
      </td>

      <td>
        <span class="badge ${getStatusClass(r.status)}">
          ${r.status}
        </span>
      </td>
    <td>${r.student.career}</td>
      <td>${r.payments_terms}</td>
        
      <td>${formatDateTime(r.created_at)}</td>
      <td>
        <button onclick="editItem(${r.id})" class="btn btn-sm btn-primary">Revisar</button>
        <button onclick="editItem2(${r.id})" class="btn btn-sm btn-primary">Pagos</button>
      </td>
    </tr>
  `).join("");
}

// ✅ =============================
// ✅ EDITAR
// ✅ =============================
function editItem(id) {
  openModal(id);
}

function editItem2(id) {
  openModal2(id);
}

function editItem3(id) {
  openModal3(id);
  
}

// ✅ =============================
// ✅ ABRIR MODAL
// ✅ =============================
function openModal(id = null) {
  editingId = id;

  if (id) {
    const item = currentRequests.find(p => p.id === id);

    document.getElementById("fNocontrol").textContent =
      item.student.control_number;
    document.getElementById("fAlumno").textContent =
      item.student.name;
    document.getElementById("fcareer").textContent =
      item.student.career;
    document.getElementById("fpayments").textContent =
      item.payments_terms;
    document.getElementById("fletter").textContent =
      item.letter;
  } else {
    document.getElementById("fNocontrol").textContent = "";
    document.getElementById("fcareer").textContent = "";
    document.getElementById("fpayments").textContent = "";
    document.getElementById("fAlumno").textContent = "";
  }

  mdlRequest.show();
}

function openModal2(id = null) {
  editingId2 = id;

  if (id) {
    const item = currentRequests.find(p => p.id === id);

    document.getElementById("fNocontrol2").textContent =
      item.student.control_number;
    document.getElementById("fAlumno2").textContent =
      item.student.name;
    document.getElementById("fcareer2").textContent =
      item.student.career;
    document.getElementById("fpayments2").textContent =
      item.payments_terms;
    document.getElementById("fletter").textContent =
      item.letter;
    
  } else {
    document.getElementById("fNocontrol2").textContent = "";
    document.getElementById("fcareer2").textContent = "";
    document.getElementById("fpayments").textContent = "";
    document.getElementById("fAlumno2").textContent = "";
    document.getElementById("fletter").textContent = "";
  }
  
  loadPayments(id);
  mdlPayments.show();
}

function openModal3(id = null) {

  editingId3 = id;

 
 if (id) {
    const items = currentPayments.find(p => p.id === id);
//   document.getElementById("fPaymentNumber").textContent =
//     items.num_payments_terms;

//   document.getElementById("famount").value = items.amount || "";
    document.getElementById("famount").textContent = items.amount;
    // document.getElementById("fstatus").textContent = items.status;
    
    document.getElementById("fstatus").value =
  items.status || "PENDING";

    document.getElementById("fcoment").textContent = items.admin_comment;
    // document.getElementById("fPayday").textContent = items.payday;



 } else{


 }

  mdlAprovepay.show();
}

async function loadPayments(requestId) {

  const tbody = document.getElementById("tblpayments");

  try {

    tbody.innerHTML = `
      <tr>
        <td colspan="5">Cargando...</td>
      </tr>
    `;

    const resp = await fetch(
      cfg.payments.replace("{id}", requestId)
    );

    if (!resp.ok) {
      throw new Error("Error al obtener pagos");
    }

    const data = await resp.json();

    const payments = data.items || data;

    currentPayments = payments;
    
    renderPayments(payments);

  } catch (err) {

    console.error(err);

    tbody.innerHTML = `
      <tr>
        <td colspan="5">Error al cargar pagos</td>
      </tr>
    `;
  }
}

function renderPayments(payments) {

  const tbody = document.getElementById("tblpayments");

  if (!payments.length) {

    tbody.innerHTML = `
      <tr>
        <td colspan="5">Sin pagos registrados</td>
      </tr>
    `;

    return;
  }

  tbody.innerHTML = payments.map(p => `
    <tr>
      <td>${p.id}</td>


      <td>
        <span class="badge ${getStatusClass(p.status)}">
          ${p.status}
        </span>
      </td>

      <td>$${p.amount}</td>
        <td>${formatDateTime(p.expiration_date)}</td>
      <td>${formatDateTime(p.payday)}</td>

      <td><button onclick="editItem3(${p.id})" class="btn btn-sm btn-primary">Validar</button></td>
    </tr>
  `).join("");
}
async function updatePayment() {

  try {

    const payload = {
      status: document.getElementById("fstatus").value,
      admin_comment: document.getElementById("fcoment").value,
      payday: new Date()
    };

    const resp = await fetch(
      cfg.update_payment.replace("{id}", editingId3),
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      }
    );

    const text = await resp.text();

    const data = text ? JSON.parse(text) : {};

    if (!resp.ok) {
      throw new Error(
        data.detail || "Error al actualizar el pago"
      );
    }

    mdlAprovepay.hide();

    alert("Pago actualizado correctamente");

    // Recargar la tabla de pagos
    await loadPayments(editingId2);

  } catch (err) {

    console.error(err);
    alert(err.message);

  }
}

async function updateStatus(status) {
  try {

    const resp = await fetch(
      cfg.update.replace("{id}", editingId),
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          status: status
        })
      }
    );

    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.detail || "Error al actualizar");
    }

    mdlRequest.hide();
    showToast("Solicitud actualizada correctamente", "success");
    loadRequests();

  } catch (err) {
    console.error(err);
    alert(err.message);
  }
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

// ✅ =============================
// ✅ HELPERS
// ✅ =============================

function formatDate(dateStr) {
  if (!dateStr) return "-";
  return new Date(dateStr).toLocaleDateString("es-MX");
}
function formatDateTime(dateStr) {
  if (!dateStr) return "-";

  return new Date(dateStr).toLocaleString("es-MX", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function getStatusClass(status) {
  return {
    PENDING: "bg-warning",
    APPROVED: "bg-success",
    REJECTED: "bg-danger"
  }[status] || "bg-secondary";
}