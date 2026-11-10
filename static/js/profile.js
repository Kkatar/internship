/* VILAS — profile: reservations (hold/pay/cancel/details), food orders, export */

let USER = null;
let RES = [];
let ORDERS = [];
let payTarget = null;
let payMethod = "card";

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initPay();
  window.addEventListener("vilas:refresh", loadAll);
  $("#signOutBtn")?.addEventListener("click", () => { location.href = "/signout"; });
  $("#saveProfile")?.addEventListener("click", saveProfile);
  loadAll();
});

async function loadAll() {
  let me;
  try { me = await api("/api/me"); } catch (_) { me = { user: null }; }
  if (!me.user) {
    $("#signedOut").style.display = "";
    $("#profileView").style.display = "none";
    return;
  }
  $("#signedOut").style.display = "none";
  $("#profileView").style.display = "";
  USER = me.user;

  $("#pAvatar").textContent = initials(USER.name);
  $("#pName").textContent = USER.name;
  $("#pMail").textContent = USER.email + (USER.phone ? " · " + USER.phone : "");
  $("#pSince").textContent = "Member since " + fmtDate((USER.created_at || "").slice(0, 10));
  $("#pPhone").value = USER.phone || "";

  try {
    const [r, o] = await Promise.all([api("/api/reservations"), api("/api/orders")]);
    RES = r.reservations; ORDERS = o.orders;
  } catch (err) {
    if (err.status === 401) { location.href = "/auth?next=/profile"; return; }
    toast(err.message, "err");
  }

  const st = me.stats || {};
  $("#stBooked").textContent = st.booked || 0;
  $("#stReserved").textContent = st.reserved || 0;
  $("#stOrders").textContent = st.orders || 0;
  $("#stSpend").textContent = "spent " + money(st.spent || 0);
  $("#stFavs").textContent = st.favourites || 0;

  renderReservations();
  renderOrders();
}

/* ---------------- tabs ---------------- */
function initTabs() {
  $$("#tabs .tab").forEach(t => t.addEventListener("click", () => {
    $$("#tabs .tab").forEach(x => x.classList.remove("active"));
    t.classList.add("active");
    ["res", "orders", "data"].forEach(k => {
      $("#tab-" + k).style.display = t.dataset.tab === k ? "" : "none";
    });
  }));
}

/* ---------------- reservations ---------------- */
const STATUS_LABEL = { reserved: "Reserved — pay pending", booked: "Booked — confirmed", cancelled: "Cancelled" };

function bookingCard(r) {
  const canPay = r.status === "reserved";
  const canCancel = r.status !== "cancelled";
  return `
  <article class="booking-card" data-reveal>
    <div class="booking-main">
      <div class="thumb"><img src="${esc(r.room_image || r.hotel_image)}" alt="${esc(r.room_name)}" loading="lazy"></div>
      <div>
        <span class="tiny">${esc(r.hotel_city)} · ${esc(r.hotel_name)}</span>
        <h3>${esc(r.room_name)} room</h3>
        <div class="booking-meta">
          <span>📅 <b>${fmtDate(r.check_in)} → ${fmtDate(r.check_out)}</b> · ${r.nights} night(s)</span>
          <span>👥 <b>${r.guests}</b> guests · <b>${r.rooms}</b> room(s)</span>
          <span>✦ <b>${esc(r.code)}</b></span>
        </div>
      </div>
      <div class="booking-side">
        <span class="amount">${money(r.amount)}</span>
        <span class="badge ${esc(r.status)}">${STATUS_LABEL[r.status] || esc(r.status)}</span>
        <div class="booking-actions">
          <button class="btn btn-soft btn-sm" data-details="${esc(r.code)}">Details</button>
          ${canPay ? `<button class="btn btn-gold btn-sm" data-pay="${esc(r.code)}">Pay now</button>` : ""}
          ${canCancel ? `<button class="btn btn-danger btn-sm" data-cancel="${esc(r.code)}">Cancel</button>` : ""}
        </div>
      </div>
    </div>
    <div class="details-panel" id="det-${esc(r.code)}">
      <div class="detail-grid">
        <div class="item"><span>Booking code</span><b>${esc(r.code)}</b></div>
        <div class="item"><span>Status</span><b>${STATUS_LABEL[r.status] || esc(r.status)}</b></div>
        <div class="item"><span>Room category</span><b>${esc(r.room_name)} · ${money(r.room_price)}/night</b></div>
        <div class="item"><span>Hotel</span><b>${esc(r.hotel_name)}</b></div>
        <div class="item"><span>Check-in</span><b>${fmtDate(r.check_in)}</b></div>
        <div class="item"><span>Check-out</span><b>${fmtDate(r.check_out)}</b></div>
        <div class="item"><span>Booked on</span><b>${fmtDateTime(r.created_at)}</b></div>
        <div class="item"><span>Paid on</span><b>${r.paid_at ? fmtDateTime(r.paid_at) : "—"}</b></div>
        <div class="item"><span>Payment method</span><b>${r.payment_method ? esc(r.payment_method.toUpperCase()) : "Not paid yet"}</b></div>
        <div class="item"><span>Guests / rooms</span><b>${r.guests} / ${r.rooms}</b></div>
        <div class="item"><span>Nights</span><b>${r.nights}</b></div>
        <div class="item"><span>Total</span><b>${money(r.amount)}</b></div>
      </div>
      <p class="form-note" style="margin-top:14px">Address · ${esc(r.hotel_address)} · ${esc(r.hotel_phone)}</p>
    </div>
  </article>`;
}

function renderReservations() {
  const box = $("#bookingList");
  if (!RES.length) {
    box.innerHTML = `<div class="empty-state"><div class="big">✦</div><h3>No reservations yet</h3>
      <p>Find a stay and hold your first room — no card needed to hold.</p>
      <a class="btn btn-gold" href="/#stays">Search hotels</a></div>`;
    return;
  }
  box.innerHTML = RES.map(bookingCard).join("");
  initReveal();

  $$("[data-details]", box).forEach(b => b.addEventListener("click", () => {
    $("#det-" + b.dataset.details)?.classList.toggle("open");
  }));
  $$("[data-pay]", box).forEach(b => b.addEventListener("click", () => openPay(b.dataset.pay)));
  $$("[data-cancel]", box).forEach(b => b.addEventListener("click", async () => {
    if (!confirm("Cancel this reservation? The room returns to the available pool immediately.")) return;
    try {
      await api(`/api/reservations/${b.dataset.cancel}/cancel`, { method: "POST" });
      toast("Reservation cancelled — room released.", "ok");
      loadAll();
    } catch (err) { toast(err.message, "err"); }
  }));
}

/* ---------------- pay modal ---------------- */
function openPay(code) {
  payTarget = code;
  const r = RES.find(x => x.code === code);
  $("#pSummary").innerHTML = r ? `
    <div class="line"><span>${esc(r.hotel_name)} · ${esc(r.room_name)}</span><span>${fmtDate(r.check_in)} → ${fmtDate(r.check_out)}</span></div>
    <div class="line"><span>Booking code</span><span>${esc(r.code)}</span></div>
    <div class="line total"><span>Amount due</span><b>${money(r.amount)}</b></div>` : "";
  openModal("payModal");
}

function initPay() {
  $$("#payMethods button").forEach(b => b.addEventListener("click", () => {
    $$("#payMethods button").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    payMethod = b.dataset.m;
    $("#payCardFields").style.display = payMethod === "card" ? "" : "none";
    $("#payUpiFields").style.display = payMethod === "upi" ? "" : "none";
    $("#payWalletFields").style.display = payMethod === "wallet" ? "" : "none";
  }));

  const num = $("#pNum"), exp = $("#pExp"), cvv = $("#pCvv");
  num.addEventListener("input", () => { num.value = num.value.replace(/\D/g, "").slice(0, 16).replace(/(.{4})/g, "$1 ").trim(); });
  exp.addEventListener("input", () => {
    let v = exp.value.replace(/\D/g, "").slice(0, 4);
    if (v.length > 2) v = v.slice(0, 2) + "/" + v.slice(2);
    exp.value = v;
  });
  cvv.addEventListener("input", () => { cvv.value = cvv.value.replace(/\D/g, "").slice(0, 4); });

  $("#payForm").addEventListener("submit", async e => {
    e.preventDefault();
    const btn = $("#paySubmit");
    btn.disabled = true; btn.textContent = "Processing…";
    try {
      const body = { method: payMethod };
      if (payMethod === "card") body.card = { number: num.value, name: $("#pName").value, expiry: exp.value, cvv: cvv.value };
      if (payMethod === "upi") body.upi = $("#pUpi").value;
      if (payMethod === "wallet") body.wallet = $("#pWallet").value;
      await api(`/api/reservations/${payTarget}/pay`, { method: "POST", body });
      closeModal("payModal");
      toast("Payment captured — booking confirmed ✓", "ok");
      loadAll();
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false; btn.textContent = "Simulate payment";
    }
  });
}

/* ---------------- orders ---------------- */
function orderCard(o) {
  const online = o.type === "online";
  const items = o.items.map(i =>
    `<li><span>${esc(i.name)} × ${i.qty}</span><b>${money(i.price * i.qty)}</b></li>`).join("");
  const where = online
    ? `🛵 Delivery · ${esc(o.address || "")}`
    : `🍽 Dine-in · ${fmtDate(o.dining_date)} at ${esc(o.dining_time)} · ${o.guests} guest(s)`;
  const pay = o.paid
    ? `<span class="badge booked">Paid · ${esc((o.payment_method || "").toUpperCase())}</span>`
    : `<span class="badge pending">Pay at restaurant</span>`;
  return `
  <article class="order-card" data-reveal>
    <div class="order-head">
      <div>
        <h3>${esc(o.hotel_name)}<span class="order-type">${online ? "Online delivery" : "Offline dine-in"}</span></h3>
        <span class="tiny">✦ ${esc(o.code)} · ${fmtDateTime(o.created_at)}</span>
      </div>
      <span class="badge ${esc(o.status)}">${esc(o.status)}</span>
    </div>
    <ul class="order-items">${items}</ul>
    <div class="order-foot">
      <div>
        <p class="small" style="margin-bottom:6px">${where}</p>
        ${pay}
      </div>
      <span class="total">${money(o.total)}</span>
    </div>
  </article>`;
}

function renderOrders() {
  const box = $("#orderList");
  if (!ORDERS.length) {
    box.innerHTML = `<div class="empty-state"><div class="big">🍽</div><h3>No orders yet</h3>
      <p>Open any hotel and order from its kitchen — delivery or dine-in.</p>
      <a class="btn btn-gold" href="/hotel/tandoor-corner#dining">See the menu</a></div>`;
    return;
  }
  box.innerHTML = ORDERS.map(orderCard).join("");
  initReveal();
}

/* ---------------- profile save ---------------- */
async function saveProfile() {
  try {
    const data = await api("/api/profile", { method: "PUT", body: { phone: $("#pPhone").value } });
    USER = data.user;
    $("#pMail").textContent = USER.email + (USER.phone ? " · " + USER.phone : "");
    toast("Profile updated ✓", "ok");
  } catch (err) { toast(err.message, "err"); }
}
