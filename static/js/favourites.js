/* VILAS — favourites grid */

document.addEventListener("DOMContentLoaded", loadFavs);

async function loadFavs() {
  const grid = $("#favGrid");
  let data;
  try {
    data = await api("/api/favourites");
  } catch (err) {
    if (err.status === 401) { $("#signedOut").style.display = ""; return; }
    toast(err.message, "err");
    return;
  }

  const hotels = data.hotels || [];
  if (!hotels.length) { $("#empty").style.display = ""; return; }

  grid.style.display = "";
  grid.innerHTML = hotels.map((h, i) => {
    const t = h.occupancy_totals || { reserved: 0, booked: 0, available: 0 };
    return `
    <article class="hotel-card" data-tilt="7" data-reveal style="--d:${(i % 3) * 0.08}s">
      <div class="card-media">
        <img src="${esc(h.image)}" alt="${esc(h.name)}" loading="lazy">
        <span class="card-rating">★ <b>${Number(h.rating).toFixed(1)}</b> · ${Number(h.reviews).toLocaleString("en-IN")}</span>
        <button class="fav-btn on" data-slug="${esc(h.slug)}" title="Remove">♥</button>
      </div>
      <div class="card-body">
        <div class="card-kicker">
          <span class="cat">${esc(h.category)}</span>
          <span class="city">✦ ${esc(h.city)}</span>
        </div>
        <h3>${esc(h.name)}</h3>
        <p class="addr">${esc(h.tagline)}</p>
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
  }).join("");

  initTilt(grid);
  initReveal();

  $$(".fav-btn", grid).forEach(btn => btn.addEventListener("click", async () => {
    try {
      await api(`/api/favourites/${btn.dataset.slug}`, { method: "DELETE" });
      toast("Removed from favourites.");
      btn.closest(".hotel-card").remove();
      if (!grid.querySelector(".hotel-card")) $("#empty").style.display = "";
    } catch (err) { toast(err.message, "err"); }
  }));
}
