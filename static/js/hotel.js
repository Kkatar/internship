/* VILAS — hotel detail: rooms + coverflow, availability board,
   reservation hold → simulated payment, food menu + cart + checkout */

const SLUG = document.body.dataset.slug;
let HOTEL = null;          // detail payload
let MENU = [];             // menu items
let CART = new Map();      // id -> qty
let payTarget = null;      // reservation code being paid
let payMethod = "card";
let orderPayMethod = "card";
let orderMode = "online";

/* ================= boot ================= */
document.addEventListener("DOMContentLoaded", async () => {
  initSubnav();
  await loadHotel();
  await loadMenu();
  initReserveModal();
  initPayModal();
  initCartUI();
  initCheckout();
  restoreSearchDates();
});

async function loadHotel() {
  try {
    HOTEL = await api(`/api/hotels/${SLUG}`);
  } catch (err) {
    $("#roomList").innerHTML = `<div class="empty-state"><h3>Could not load this stay</h3><p>${esc(err.message)}</p>
      <a class="btn btn-ghost" href="/#stays">Back to search</a></div>`;
    return;
  }
  document.title = `${HOTEL.name} · Vilas`;
  $("#heroImg").src = HOTEL.image;
  $("#heroImg").alt = HOTEL.name;
  $("#hName").textContent = HOTEL.name;
  $("#hKicker").textContent = `${HOTEL.category} · ${HOTEL.city}`;
  $("#hMeta").innerHTML = `
    <span class="chip gold">★ ${Number(HOTEL.rating).toFixed(1)} · ${Number(HOTEL.reviews).toLocaleString("en-IN")} reviews</span>
    <span class="chip">${esc(HOTEL.category)}</span>
    <span class="chip">${esc(HOTEL.dine_label || HOTEL.city)}</span>
    <span class="chip free"><span class="dot"></span>${HOTEL.occupancy_totals.available} rooms free tonight onwards</span>`;
  $("#aboutName").textContent = HOTEL.name;
  $("#aboutText").textContent = HOTEL.about;
  $("#aboutFacts").innerHTML = `
    <div class="fact"><span>Address</span><b>${esc(HOTEL.address)}</b></div>
    <div class="fact"><span>Front desk</span><b>24×7 · ${esc(HOTEL.phone)}</b></div>
    <div class="fact"><span>Kitchen hours</span><b>${esc(HOTEL.hours)}</b></div>
    <div class="fact"><span>Category</span><b>${esc(HOTEL.category)} · from ${money(HOTEL.min_price)}</b></div>`;
  $("#contactGrid").innerHTML = `
    <div class="contact-card"><div class="ico">✦</div><h4>Address</h4><p>${esc(HOTEL.address)}</p></div>
    <div class="contact-card"><div class="ico">☎</div><h4>Phone</h4><p><a href="tel:${esc(HOTEL.phone)}">${esc(HOTEL.phone)}</a></p></div>
    <div class="contact-card"><div class="ico">✉</div><h4>Email</h4><p><a href="mailto:${esc(HOTEL.email)}">${esc(HOTEL.email)}</a></p></div>
    <div class="contact-card"><div class="ico">◷</div><h4>Hours</h4><p>${esc(HOTEL.hours)}</p></div>`;

  const fav = $("#favToggle");
  const setFav = on => { fav.textContent = on ? "♥ Saved" : "♡ Save"; fav.classList.toggle("on", on); fav.dataset.on = on ? "1" : ""; };
  setFav(!!HOTEL.favourite);
  fav.addEventListener("click", async () => {
    const user = await requireUser(); if (!user) return;
    try {
      if (fav.dataset.on) { await api(`/api/favourites/${SLUG}`, { method: "DELETE" }); setFav(false); toast("Removed from favourites."); }
      else { await api("/api/favourites", { method: "POST", body: { slug: SLUG } }); setFav(true); toast("Saved to favourites ♥", "ok"); }
    } catch (e) { toast(e.message, "err"); }
  });

  renderRooms();
  renderAvailability();
}

/* ================= rooms + coverflow ================= */
function roomCard(room, idx) {
  const chips = room.amenities.map(a => `<span class="chip">${esc(a)}</span>`).join("");
  const imgs = room.images.map(src =>
    `<figure class="cf-card"><img src="${esc(src)}" alt="${esc(room.name)} — ${idx + 1}" loading="lazy"></figure>`
  ).join("");
  const pct = v => (room.total ? (v / room.total) * 100 : 0);
  return `
  <div class="room-block">
    <div class="room-media coverflow" data-reveal="${idx % 2 ? "right" : "left"}">
      <div class="cf-track">${imgs}</div>
      <div class="cf-hint">‹ drag / scroll the gallery ›</div>
    </div>
    <div class="room-info" data-reveal>
      <span class="eyebrow">Category ${idx + 1} of 3</span>
      <h3>${esc(room.name)}</h3>
      <div class="room-price"><b>${money(room.price)}</b><span>/ night · ${room.total} rooms in category</span></div>
      <p class="desc">${esc(room.desc)}</p>
      <div class="amenities">${chips}</div>
      <div class="room-occ">
        <div class="row">
          <span class="free-note"><b>${room.available}</b> of ${room.total} available now</span>
          <span class="free-note">reflected across all guests</span>
        </div>
        <div class="bar">
          <div class="fill-r" style="width:${pct(room.reserved)}%"></div>
          <div class="fill-b" style="width:${pct(room.booked)}%"></div>
        </div>
        <div class="row" style="margin:12px 0 0">
          <span class="chip reserved"><span class="dot"></span>${room.reserved} reserved</span>
          <span class="chip booked"><span class="dot"></span>${room.booked} booked</span>
          <span class="chip free"><span class="dot"></span>${room.available} free</span>
        </div>
      </div>
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <button class="btn btn-gold" data-reserve="${room.id}" ${room.available < 1 ? "disabled" : ""}>
          ${room.available < 1 ? "Fully held" : "Reserve this room"}
        </button>
        <a class="btn btn-ghost" href="#availability">See live board</a>
      </div>
    </div>
  </div>`;
}

function renderRooms() {
  const list = $("#roomList");
  list.innerHTML = HOTEL.rooms.map(roomCard).join("");
  $$(".cf-track", list).forEach(initCoverflow);
  $$("[data-reserve]", list).forEach(btn => btn.addEventListener("click", () => openReserve(+btn.dataset.reserve)));
  initReveal();
  initTilt(list);
}

function renderAvailability() {
  const rows = $("#availRows");
  rows.innerHTML = HOTEL.rooms.map(r => {
    const pct = v => (r.total ? (v / r.total) * 100 : 0);
    return `
    <div class="avail-row">
      <div class="cat"><b>${esc(r.name)}</b><span>${money(r.price)} / night</span></div>
      <div class="avail-num"><b>${r.total}</b><span>Total</span></div>
      <div class="avail-num reserved"><b>${r.reserved}</b><span>Reserved</span></div>
      <div class="avail-num booked"><b>${r.booked}</b><span>Booked</span></div>
      <div class="avail-num free"><b>${r.available}</b><span>Available</span></div>
      <div class="avail-bar" style="grid-column:1/-1">
        <div class="r" style="width:${pct(r.reserved)}%"></div>
        <div class="b" style="width:${pct(r.booked)}%"></div>
        <div class="f" style="width:${pct(r.available)}%"></div>
      </div>
    </div>`;
  }).join("");
  const t = HOTEL.occupancy_totals;
  $("#availTotals").innerHTML = `
    <div><b>${t.total}</b><span>Rooms in hotel</span></div>
    <div><b style="color:var(--amber)">${t.reserved}</b><span>Reserved (unpaid)</span></div>
    <div><b style="color:var(--green)">${t.booked}</b><span>Booked (paid)</span></div>
    <div><b>${t.available}</b><span>Available now</span></div>`;
}

/* refresh just the numbers after booking actions */
async function refreshAvailability() {
  try {
    HOTEL = await api(`/api/hotels/${SLUG}`);
    renderRooms();
    renderAvailability();
  } catch (_) { /* keep stale */ }
}

/* ================= subnav active state ================= */
function initSubnav() {
  const links = $$("#subnav a");
  const map = new Map();
  links.forEach(a => {
    const sec = document.querySelector(a.getAttribute("href"));
    if (sec) map.set(sec, a);
  });
  const io = new IntersectionObserver(entries => {
    entries.forEach(en => {
      if (en.isIntersecting) {
        links.forEach(a => a.classList.remove("active"));
        map.get(en.target)?.classList.add("active");
      }
    });
  }, { rootMargin: "-40% 0px -55% 0px" });
  map.forEach((_, sec) => io.observe(sec));
}

/* ================= reserve flow ================= */
function restoreSearchDates() {
  let saved = null;
  try { saved = JSON.parse(sessionStorage.getItem("vilas_search")); } catch (_) {}
  const min = todayISO();
  const ci = $("#rIn"), co = $("#rOut");
  ci.min = min; co.min = min;
  ci.value = saved?.check_in && saved.check_in >= min ? saved.check_in : addDays(min, 1);
  co.value = saved?.check_out && saved.check_out > ci.value ? saved.check_out : addDays(ci.value, 2);
  if (saved?.guests) $("#rGuests").value = saved.guests;
}

function openReserve(roomTypeId) {
  const sel = $("#rRoom");
  sel.innerHTML = HOTEL.rooms.map(r =>
    `<option value="${r.id}" ${r.id === roomTypeId ? "selected" : ""} ${r.available < 1 ? "disabled" : ""}>
      ${esc(r.name)} — ${money(r.price)}/night (${r.available} free)</option>`).join("");
  $("#reserveFormView").style.display = "";
  $("#reserveSuccessView").style.display = "none";
  updateReserveSummary();
  openModal("reserveModal");
}

function updateReserveSummary() {
  const room = HOTEL.rooms.find(r => r.id === +$("#rRoom").value) || HOTEL.rooms[0];
  const ci = $("#rIn").value, co = $("#rOut").value;
  let nights = 0;
  if (ci && co) nights = Math.round((new Date(co) - new Date(ci)) / 86400000);
  const rooms = +$("#rRooms").value;
  const total = nights > 0 ? room.price * rooms * nights : 0;
  $("#rSummary").innerHTML = `
    <div class="line"><span>${esc(room.name)} · ${money(room.price)} × ${rooms} room(s)</span><span>${money(room.price * rooms)}</span></div>
    <div class="line"><span>${nights > 0 ? nights : "—"} night(s) · ${$("#rGuests").value} guest(s)</span><span>${nights > 0 ? money(room.price * rooms * nights) : "—"}</span></div>
    <div class="line total"><span>Estimated total</span><b>${money(total)}</b></div>
    <div class="line" style="color:var(--amber)"><span>Status after holding</span><span>Reserved — pay later</span></div>`;
}

function initReserveModal() {
  ["rRoom", "rIn", "rOut", "rGuests", "rRooms"].forEach(id =>
    $("#" + id).addEventListener("change", updateReserveSummary));
  $("#rIn").addEventListener("change", () => {
    const co = $("#rOut");
    co.min = $("#rIn").value;
    if (co.value <= $("#rIn").value) co.value = addDays($("#rIn").value, 1);
    updateReserveSummary();
  });

  $("#reserveForm").addEventListener("submit", async e => {
    e.preventDefault();
    const btn = e.target.querySelector("[type=submit]");
    btn.disabled = true; btn.textContent = "Holding your room…";
    try {
      const data = await api("/api/reservations", {
        method: "POST",
        body: {
          hotel_slug: SLUG,
          room_type_id: +$("#rRoom").value,
          check_in: $("#rIn").value,
          check_out: $("#rOut").value,
          guests: +$("#rGuests").value,
          rooms: +$("#rRooms").value,
        },
      });
      const r = data.reservation;
      $("#reserveFormView").style.display = "none";
      $("#reserveSuccessView").style.display = "";
      $("#sCode").textContent = r.code;
      $("#sSummary").textContent =
        `${r.room_name} · ${fmtDate(r.check_in)} → ${fmtDate(r.check_out)} · ${r.nights} night(s) · ${money(r.amount)}`;
      $("#sPayNow").onclick = () => { closeModal("reserveModal"); openPay(r.code); };
      toast("Room held — it's yours for 30 minutes of thinking ✦", "ok");
      refreshAvailability();
    } catch (err) {
      toast(err.message, "err");
      if (err.status === 401) setTimeout(() => location.href = "/auth?next=" + encodeURIComponent(location.pathname), 800);
    } finally {
      btn.disabled = false; btn.textContent = "Hold reservation ✦";
    }
  });
}

/* ================= pay flow ================= */
function openPay(code) {
  payTarget = code;
  const r = lastReservation(code);
  $("#pSummary").innerHTML = r ? `
    <div class="line"><span>${esc(r.hotel_name)} · ${esc(r.room_name)}</span><span>${fmtDate(r.check_in)} → ${fmtDate(r.check_out)}</span></div>
    <div class="line"><span>Booking code</span><span>${esc(r.code)}</span></div>
    <div class="line total"><span>Amount due</span><b>${money(r.amount)}</b></div>` :
    `<div class="line total"><span>Booking code</span><b>${esc(code)}</b></div>`;
  openModal("payModal");
}

let cachedReservations = null;
async function lastReservation(code) {
  if (!cachedReservations) {
    try { cachedReservations = (await api("/api/reservations")).reservations; } catch (_) { return null; }
  }
  return cachedReservations.find(r => r.code === code) || null;
}

function initPayModal() {
  $$("#payMethods button").forEach(b => b.addEventListener("click", () => {
    $$("#payMethods button").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    payMethod = b.dataset.m;
    $("#payCardFields").style.display = payMethod === "card" ? "" : "none";
    $("#payUpiFields").style.display = payMethod === "upi" ? "" : "none";
    $("#payWalletFields").style.display = payMethod === "wallet" ? "" : "none";
  }));

  const num = $("#pNum"), exp = $("#pExp"), cvv = $("#pCvv");
  num.addEventListener("input", () => {
    num.value = num.value.replace(/\D/g, "").slice(0, 16).replace(/(.{4})/g, "$1 ").trim();
  });
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
      toast("Payment captured — booking is now confirmed ✓", "ok");
      cachedReservations = null;
      refreshAvailability();
      if (document.body.dataset.page === "profile") window.dispatchEvent(new CustomEvent("vilas:refresh"));
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false; btn.textContent = "Simulate payment";
    }
  });
}

/* ================= menu & cart ================= */
async function loadMenu() {
  try {
    const data = await api(`/api/hotels/${SLUG}/menu`);
    MENU = data.menu;
    $("#dineLabel").textContent = data.dine_label || "Restaurant";
    $("#dineHours").textContent = data.hours;
    renderMenu();
  } catch (err) {
    $("#menuGrid").innerHTML = `<div class="empty-state" style="grid-column:1/-1"><h3>Menu unavailable</h3><p>${esc(err.message)}</p></div>`;
  }
}

function menuCard(item) {
  const qty = CART.get(item.id) || 0;
  const media = item.img
    ? `<img src="${esc(item.img)}" alt="${esc(item.name)}" loading="lazy">`
    : `<div class="menu-tile">${esc(item.name[0])}</div>`;
  return `
  <article class="menu-card" data-reveal>
    <div class="menu-media">${media}<span class="menu-tag">${esc(item.tag || "Chef's pick")}</span></div>
    <div class="menu-body">
      <h4>${esc(item.name)}</h4>
      <p>${esc(item.desc)}</p>
      <div class="menu-foot">
        <span class="price">${money(item.price)}</span>
        <span data-cart-for="${esc(item.id)}">${qty ? stepperHTML(item.id, qty) : `<button class="add-btn" data-add="${esc(item.id)}">+ Add</button>`}</span>
      </div>
    </div>
  </article>`;
}
const stepperHTML = (id, q) => `
  <span class="qty-stepper">
    <button type="button" data-dec="${esc(id)}">−</button><span>${q}</span><button type="button" data-inc="${esc(id)}">+</button>
  </span>`;

function renderMenu() {
  const grid = $("#menuGrid");
  grid.innerHTML = MENU.map(menuCard).join("");
  wireCartButtons(grid);
  initReveal();
}

function wireCartButtons(root) {
  $$("[data-add]", root).forEach(b => b.addEventListener("click", () => setQty(b.dataset.add, 1)));
  $$("[data-inc]", root).forEach(b => b.addEventListener("click", () => setQty(b.dataset.inc, (CART.get(b.dataset.inc) || 0) + 1)));
  $$("[data-dec]", root).forEach(b => b.addEventListener("click", () => setQty(b.dataset.dec, (CART.get(b.dataset.dec) || 0) - 1)));
}

function setQty(id, q) {
  if (q <= 0) CART.delete(id); else CART.set(id, Math.min(q, 20));
  // update just that item's slot
  const slot = $(`[data-cart-for="${CSS.escape(id)}"]`);
  if (slot) slot.innerHTML = CART.has(id)
    ? stepperHTML(id, CART.get(id))
    : `<button class="add-btn" data-add="${esc(id)}">+ Add</button>`;
  wireCartButtons(slot);
  syncFab();
}

function syncFab() {
  const count = [...CART.values()].reduce((a, b) => a + b, 0);
  const fab = $("#cartFab");
  $("#cartCount").textContent = count;
  const total = cartTotal();
  $("#cartFabText").textContent = count ? `${count} item${count > 1 ? "s" : ""} · ${money(total)}` : "Cart";
  fab.classList.toggle("show", count > 0);
}

const cartTotal = () => [...CART.entries()].reduce((sum, [id, q]) => {
  const it = MENU.find(m => m.id === id); return sum + (it ? it.price * q : 0);
}, 0);

function renderCart() {
  const box = $("#cartItems");
  if (!CART.size) { box.innerHTML = `<p class="small">Your cart is empty.</p>`; }
  else {
    box.innerHTML = [...CART.entries()].map(([id, q]) => {
      const it = MENU.find(m => m.id === id); if (!it) return "";
      return `<div class="cart-item">
        <span class="nm"><b>${esc(it.name)}</b><span>${money(it.price)} each</span></span>
        <span class="qty-stepper">
          <button type="button" data-cdec="${esc(id)}">−</button><span>${q}</span>
          <button type="button" data-cinc="${esc(id)}">+</button>
        </span>
        <span class="pr">${money(it.price * q)}</span>
      </div>`;
    }).join("");
    $$("[data-cinc]", box).forEach(b => b.addEventListener("click", () => { setQty(b.dataset.cinc, (CART.get(b.dataset.cinc) || 0) + 1); renderCart(); }));
    $$("[data-cdec]", box).forEach(b => b.addEventListener("click", () => { setQty(b.dataset.cdec, (CART.get(b.dataset.cdec) || 0) - 1); renderCart(); }));
  }
  $("#cartSummary").innerHTML = `
    <div class="line"><span>${[...CART.values()].reduce((a, b) => a + b, 0)} item(s)</span><span>${money(cartTotal())}</span></div>
    <div class="line"><span>Delivery / dine-in</span><span>Chosen at checkout</span></div>
    <div class="line total"><span>Total</span><b>${money(cartTotal())}</b></div>`;
}

function initCartUI() {
  $("#cartFab").addEventListener("click", () => { renderCart(); openModal("cartModal"); });
  $("#toCheckout").addEventListener("click", () => { closeModal("cartModal"); openCheckout(); });
  $("#clearCart").addEventListener("click", () => { CART.clear(); renderCart(); syncFab(); renderMenu(); toast("Cart cleared."); });
}

/* ================= checkout ================= */
function openCheckout() {
  updateCheckoutSummary();
  $("#oDate").min = todayISO();
  if (!$("#oDate").value) $("#oDate").value = addDays(todayISO(), 1);
  openModal("checkoutModal");
}

function updateCheckoutSummary() {
  const items = [...CART.entries()].map(([id, q]) => {
    const it = MENU.find(m => m.id === id); if (!it) return "";
    return `<div class="line"><span>${esc(it.name)} × ${q}</span><span>${money(it.price * q)}</span></div>`;
  }).join("");
  const modeLine = orderMode === "online"
    ? `<div class="line"><span>Delivery · pay online now</span><span>30–45 min</span></div>`
    : `<div class="line"><span>Dine-in · ${fmtDate($("#oDate").value)} ${esc($("#oTime").value || "")}</span><span>Pay at restaurant</span></div>`;
  $("#coSummary").innerHTML = `${items}${modeLine}<div class="line total"><span>Total</span><b>${money(cartTotal())}</b></div>`;
}

function initCheckout() {
  $$("#orderModes button").forEach(b => b.addEventListener("click", () => {
    $$("#orderModes button").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    orderMode = b.dataset.mode;
    $("#onlineFields").style.display = orderMode === "online" ? "" : "none";
    $("#offlineFields").style.display = orderMode === "offline" ? "" : "none";
    $("#coSubmit").textContent = orderMode === "online"
      ? `Pay ${money(cartTotal())} & place order ✦`
      : "Reserve table & order ✦";
    updateCheckoutSummary();
  }));
  ["oDate", "oTime", "oGuests"].forEach(id => $("#" + id).addEventListener("change", updateCheckoutSummary));

  $$("#orderPayMethods button").forEach(b => b.addEventListener("click", () => {
    $$("#orderPayMethods button").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    orderPayMethod = b.dataset.m;
    $("#omCard").style.display = orderPayMethod === "card" ? "" : "none";
    $("#omUpi").style.display = orderPayMethod === "upi" ? "" : "none";
  }));

  const num = $("#oNum"), exp = $("#oExp"), cvv = $("#oCvv");
  num.addEventListener("input", () => { num.value = num.value.replace(/\D/g, "").slice(0, 16).replace(/(.{4})/g, "$1 ").trim(); });
  exp.addEventListener("input", () => {
    let v = exp.value.replace(/\D/g, "").slice(0, 4);
    if (v.length > 2) v = v.slice(0, 2) + "/" + v.slice(2);
    exp.value = v;
  });
  cvv.addEventListener("input", () => { cvv.value = cvv.value.replace(/\D/g, "").slice(0, 4); });

  $("#checkoutForm").addEventListener("submit", async e => {
    e.preventDefault();
    if (!CART.size) { toast("Your cart is empty.", "err"); return; }
    const btn = $("#coSubmit");
    const label = btn.textContent;
    btn.disabled = true; btn.textContent = "Placing…";
    try {
      const body = {
        hotel_slug: SLUG,
        type: orderMode,
        items: [...CART.entries()].map(([id, qty]) => ({ id, qty })),
      };
      if (orderMode === "online") {
        body.address = $("#oAddress").value;
        body.payment_method = orderPayMethod;
        if (orderPayMethod === "card") body.card = { number: num.value, name: "Guest", expiry: exp.value, cvv: cvv.value };
        if (orderPayMethod === "upi") body.upi = $("#oUpi").value;
      } else {
        body.dining_date = $("#oDate").value;
        body.dining_time = $("#oTime").value;
        body.guests = +$("#oGuests").value;
      }
      const data = await api("/api/orders", { method: "POST", body });
      CART.clear(); syncFab(); renderMenu();
      closeModal("checkoutModal");
      const o = data.order;
      toast(orderMode === "online"
        ? `Order ${o.code} confirmed & paid — arriving soon ✓`
        : `Table for ${o.guests} on ${fmtDate(o.dining_date)} at ${o.dining_time} ✓`, "ok");
    } catch (err) {
      toast(err.message, "err");
      if (err.status === 401) setTimeout(() => location.href = "/auth?next=" + encodeURIComponent(location.pathname), 800);
    } finally {
      btn.disabled = false; btn.textContent = label;
    }
  });
}
