/* VILAS — home page: search, hotel cards, live occupancy board */

let state = { q: "", category: "All", categories: [], hotels: [] };

/* restore search params from the URL */
function readURL() {
  const p = new URLSearchParams(location.search);
  state.q = p.get("q") || "";
  state.category = p.get("category") || "All";
}

function renderFilters() {
  const box = $("#filters");
  box.innerHTML = state.categories.map(c =>
    `<button class="filter-chip ${c === state.category ? "active" : ""}" data-cat="${esc(c)}">${esc(c)}</button>`
  ).join("");
  $$(".filter-chip", box).forEach(btn => btn.addEventListener("click", () => {
    state.category = btn.dataset.cat;
    renderFilters();
    loadHotels();
  }));
}

function hotelCard(h) {
  const t = h.occupancy_totals || { reserved: 0, booked: 0, available: 0 };
  return `
  <article class="hotel-card" data-tilt="7" data-reveal style="--d:${(h._i % 3) * 0.08}s">
    <div class="card-media">
      <img src="${esc(h.image)}" alt="${esc(h.name)}" loading="lazy">
      <span class="card-rating">★ <b>${Number(h.rating).toFixed(1)}</b> · ${Number(h.reviews).toLocaleString("en-IN")}</span>
      <button class="fav-btn ${h.favourite ? "on" : ""}" data-slug="${esc(h.slug)}"
              title="Save to favourites" aria-label="Save">${h.favourite ? "♥" : "♡"}</button>
    </div>
    <div class="card-body">
      <div class="card-kicker">
        <span class="cat">${esc(h.category)}</span>
        <span class="city">✦ ${esc(h.city)}</span>
      </div>
      <h3>${esc(h.name)}</h3>
      <p class="addr">${esc(h.tagline)}<br><span style="opacity:.7">${esc(h.address.split(",")[0])}</span></p>
      <div class="card-occ">
        <span class="chip booked"><span class="dot"></span>${t.booked} booked</span>
        <span class="chip reserved"><span class="dot"></span>${t.reserved} reserved</span>
        <span class="chip free"><span class="dot"></span>${t.available} free</span>
      </div>
      <div class="card-foot">
        <span class="price">${money(h.min_price)} <small>/ night</small></span>
        <a class="go" href="/hotel/${esc(h.slug)}">View rooms →</a>
      </div>
    </div>
  </article>`;
}

function wireCards(root) {
  initTilt(root);
  $$(".fav-btn", root).forEach(btn => btn.addEventListener("click", async e => {
    e.preventDefault();
    const user = await requireUser();
    if (!user) return;
    const slug = btn.dataset.slug;
    const on = btn.classList.contains("on");
    try {
      if (on) { await api(`/api/favourites/${slug}`, { method: "DELETE" }); btn.classList.remove("on"); btn.textContent = "♡"; toast("Removed from favourites."); }
      else { await api("/api/favourites", { method: "POST", body: { slug } }); btn.classList.add("on"); btn.textContent = "♥"; toast("Saved to favourites ♥", "ok"); }
    } catch (err) { toast(err.message, "err"); }
  }));
}

async function loadHotels() {
  const grid = $("#hotelGrid");
  try {
    const data = await api(`/api/hotels?q=${encodeURIComponent(state.q)}&category=${encodeURIComponent(state.category)}`);
    state.hotels = data.hotels; state.categories = data.categories;
    renderFilters();
    if (!state.hotels.length) {
      grid.innerHTML = `
        <div class="empty-state" style="grid-column:1/-1">
          <div class="big">✦</div>
          <h3>No stays matched “${esc(state.q)}”</h3>
          <p>Try “Kolhapur”, “heritage”, “resort” — or clear the search.</p>
          <button class="btn btn-ghost" id="clearSearch">Clear search</button>
        </div>`;
      $("#clearSearch")?.addEventListener("click", () => {
        state.q = ""; state.category = "All"; $("#q").value = ""; loadHotels();
      });
      return;
    }
    grid.innerHTML = state.hotels.map((h, i) => { h._i = i; return hotelCard(h); }).join("");
    $("#resultsNote").textContent =
      `${state.hotels.length} stay${state.hotels.length > 1 ? "s" : ""} · every room shows live reserved & booked counts.`;
    wireCards(grid);
    initReveal();
  } catch (err) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1"><h3>Could not load stays</h3><p>${esc(err.message)}</p></div>`;
  }
}

/* ---------- occupancy board (manage view, open to all) ---------- */
function occCell(types, name) {
  const t = types.find(x => x.name === name);
  if (!t) return `<td class="occ-cell"><span class="tiny">—</span></td>`;
  const pct = v => (t.total ? (v / t.total) * 100 : 0);
  return `
  <td class="occ-cell">
    <div class="occ-nums">
      <span class="r">${t.reserved}<i>res</i></span>
      <span class="b">${t.booked}<i>bk</i></span>
      <span class="f">${t.available}<i>free</i></span>
    </div>
    <div class="bar">
      <div class="fill-r" style="width:${pct(t.reserved)}%"></div>
      <div class="fill-b" style="width:${pct(t.booked)}%"></div>
    </div>
  </td>`;
}

async function loadOccupancy() {
  const body = $("#occBody");
  try {
    const data = await api("/api/occupancy");
    body.innerHTML = data.hotels.map(h => `
      <tr>
        <td>
          <a class="occ-hotel" href="/hotel/${esc(h.slug)}">
            <img src="${esc(h.image)}" alt="${esc(h.name)}" loading="lazy">
            <span><b>${esc(h.name)}</b><span>✦ ${esc(h.city)}</span></span>
          </a>
        </td>
        ${occCell(h.types, "Standard")}
        ${occCell(h.types, "Deluxe")}
        ${occCell(h.types, "Suite")}
        <td>
          <div class="occ-nums">
            <span class="r">${h.totals.reserved}<i>reserved</i></span>
            <span class="b">${h.totals.booked}<i>booked</i></span>
            <span class="f">${h.totals.available}<i>free</i></span>
          </div>
        </td>
      </tr>`).join("");
  } catch (err) {
    body.innerHTML = `<tr><td colspan="5" class="small" style="text-align:center;padding:30px">${esc(err.message)}</td></tr>`;
  }
}

/* ---------- search form ---------- */
function initSearchForm() {
  const form = $("#searchForm");
  const ci = $("#checkIn"), co = $("#checkOut");
  const min = todayISO();
  ci.min = min; co.min = min;
  if (!ci.value) ci.value = addDays(min, 1);
  if (!co.value) co.value = addDays(min, 2);
  ci.addEventListener("change", () => {
    co.min = ci.value;
    if (co.value <= ci.value) co.value = addDays(ci.value, 1);
  });

  form.addEventListener("submit", e => {
    e.preventDefault();
    const q = $("#q").value.trim();
    state.q = q;
    // keep the chosen dates for the booking modal later
    sessionStorage.setItem("vilas_search", JSON.stringify({
      q, check_in: ci.value, check_out: co.value, guests: $("#guests").value,
    }));
    const url = new URL(location.href);
    q ? url.searchParams.set("q", q) : url.searchParams.delete("q");
    history.replaceState(null, "", url);
    loadHotels();
    document.getElementById("stays").scrollIntoView({ behavior: "smooth" });
    if (q) toast(`Searching stays for “${q}”…`);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  readURL();
  $("#q").value = state.q;
  initSearchForm();
  loadHotels();
  loadOccupancy();
});
