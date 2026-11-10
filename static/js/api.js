/* =========================================================================
   VILAS — shared core: API, auth nav, toasts, modals, and the 3D
   scroll choreography (parallax, tilt, reveal, counters, fan, coverflow)
   ========================================================================= */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/* ---------- formatting ---------- */
const money = n => "₹" + Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
const todayISO = () => {
  const d = new Date(); d.setHours(0, 0, 0, 0);
  return d.toISOString().slice(0, 10);
};
const addDays = (iso, n) => {
  const d = new Date(iso + "T00:00:00"); d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
};
const fmtDate = iso => {
  if (!iso) return "—";
  return new Date(iso + (iso.length === 10 ? "T00:00:00" : "")).toLocaleDateString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
  });
};
const fmtDateTime = s => {
  if (!s) return "—";
  return new Date(s).toLocaleString("en-IN", {
    day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit",
  });
};
const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const initials = name => (name || "?").trim().split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase();

/* ---------- API ---------- */
async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* binary / empty */ }
  if (!res.ok) {
    const err = new Error((data && data.error) || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

/* ---------- toasts ---------- */
function toast(msg, type = "") {
  const root = $("#toastRoot");
  if (!root) return;
  const el = document.createElement("div");
  el.className = "toast " + type;
  el.textContent = msg;
  root.appendChild(el);
  setTimeout(() => { el.classList.add("hide"); setTimeout(() => el.remove(), 400); }, 3800);
}

/* ---------- modals ---------- */
function openModal(id) {
  const root = document.getElementById(id);
  if (!root) return;
  root.classList.add("open");
  document.body.classList.add("no-scroll");
}
function closeModal(id) {
  const root = typeof id === "string" ? document.getElementById(id) : id;
  if (!root) return;
  root.classList.remove("open");
  if (!document.querySelector(".modal-root.open")) document.body.classList.remove("no-scroll");
}
document.addEventListener("click", e => {
  if (e.target.matches("[data-close]")) {
    const root = e.target.closest(".modal-root");
    if (root) closeModal(root);
  }
  if (e.target.classList.contains("modal-backdrop")) closeModal(e.target.closest(".modal-root"));
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    document.querySelectorAll(".modal-root.open").forEach(closeModal);
  }
});

/* ---------- auth-aware nav ---------- */
async function initNav() {
  const nav = $("#nav");
  const burger = $("#burger");
  const links = $("#navLinks");
  const page = document.body.dataset.page;

  const onScroll = () => {
    nav.classList.toggle("scrolled", window.scrollY > 24);
    const bar = $("#scrollProgress");
    if (bar) {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.transform = `scaleX(${max > 0 ? window.scrollY / max : 0})`;
    }
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  burger?.addEventListener("click", () => {
    burger.classList.toggle("open");
    links.classList.toggle("open");
  });
  $$("#navLinks a").forEach(a => a.addEventListener("click", () => {
    burger?.classList.remove("open"); links?.classList.remove("open");
  }));

  const activeMap = { home: "home", hotel: null, profile: "profile", favourites: "favourites", auth: null };
  const key = activeMap[page];
  if (key) $(`#navLinks a[data-nav="${key}"]`)?.classList.add("active");

  // auth chip
  try {
    const me = await api("/api/me");
    const box = $("#navAuth");
    if (!box) return;
    if (me.user) {
      box.innerHTML = `
        <a class="user-chip" href="/profile" title="My bookings">
          <span class="nm">${esc(me.user.name)}</span>
          <span class="user-avatar">${esc(initials(me.user.name))}</span>
        </a>
        <a class="btn btn-ghost btn-sm" href="/signout">Sign out</a>`;
    } else {
      box.innerHTML = `<a class="btn btn-gold btn-sm" href="/auth">Sign in</a>`;
    }
  } catch (_) { /* nav is decorative on failure */ }
}

/* ---------- image fallbacks ---------- */
document.addEventListener("error", e => {
  const img = e.target;
  if (img.tagName !== "IMG") return;
  const fb = img.dataset.fallback;
  if (fb && img.src !== fb) { img.dataset.fallback = ""; img.src = fb; return; }
  img.classList.add("img-fallback");
}, true);

/* ---------- scroll reveal ---------- */
function initReveal() {
  const io = new IntersectionObserver(entries => {
    entries.forEach(en => {
      if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
  $$("[data-reveal]").forEach(el => {
    if (el._revealed) return;
    el._revealed = true;
    io.observe(el);
  });
}

/* ---------- counters ---------- */
function initCounters() {
  const io = new IntersectionObserver(entries => {
    entries.forEach(en => {
      if (!en.isIntersecting) return;
      const el = en.target; io.unobserve(el);
      const target = parseFloat(el.dataset.count);
      const decimals = parseInt(el.dataset.decimals || "0", 10);
      const suffix = el.dataset.suffix || "";
      const dur = 1600; const start = performance.now();
      const tick = now => {
        const p = Math.min((now - start) / dur, 1);
        const eased = 1 - Math.pow(1 - p, 3);
        const val = target * eased;
        el.textContent = (decimals ? val.toFixed(decimals) : Math.round(val).toLocaleString("en-IN")) + suffix;
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }, { threshold: 0.6 });
  $$("[data-count]").forEach(el => io.observe(el));
}

/* ---------- 3D tilt on hover ---------- */
function initTilt(root = document) {
  $$("[data-tilt]", root).forEach(card => {
    if (card._tilt) return; card._tilt = true;
    const strength = parseFloat(card.dataset.tilt) || 9;
    card.style.transformStyle = "preserve-3d";
    card.addEventListener("mousemove", e => {
      const r = card.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width - 0.5;
      const py = (e.clientY - r.top) / r.height - 0.5;
      card.style.transform = `perspective(900px) rotateY(${px * strength}deg) rotateX(${-py * strength}deg) translateY(-6px)`;
    });
    card.addEventListener("mouseleave", () => { card.style.transform = ""; });
  });
}

/* ---------- hero + generic parallax (scroll-driven 3D) ---------- */
function initParallax() {
  const items = $$("[data-parallax]").map(el => ({ el, speed: parseFloat(el.dataset.parallax) }));
  const hero = $(".hero");
  const heroInner = $(".hero-inner");
  let ticking = false;

  const update = () => {
    ticking = false;
    const y = window.scrollY;
    items.forEach(({ el, speed }) => {
      const isHero = el.classList.contains("hero-media");
      const rect = isHero && hero ? hero.getBoundingClientRect() : null;
      const visible = !rect || (rect.bottom > 0 && rect.top < window.innerHeight);
      if (!visible) return;
      const offset = y * speed;
      if (isHero) {
        const p = Math.min(Math.max(y / (window.innerHeight || 1), 0), 1);
        el.style.transform = `translate3d(0, ${offset}px, 0) scale(${1 + p * 0.12}) rotateX(${p * 7}deg)`;
        el.style.transformOrigin = "50% 100%";
      } else {
        el.style.transform = `translate3d(0, ${offset}px, 0)`;
      }
    });
    if (heroInner && hero) {
      const p = Math.min(Math.max(y / (window.innerHeight || 1), 0), 1);
      heroInner.style.transform = `translate3d(0, ${y * -0.12}px, 0) rotateX(${p * 5}deg)`;
      heroInner.style.opacity = String(1 - p * 0.85);
    }
  };
  window.addEventListener("scroll", () => {
    if (!ticking) { ticking = true; requestAnimationFrame(update); }
  }, { passive: true });
  update();
}

/* ---------- 3D fan gallery (pinned scroll section) ---------- */
function initFan() {
  const section = $("#fanSection");
  const stage = $("#fanStage");
  if (!section || !stage) return;
  const cards = $$(".fan-card", stage);
  let ticking = false;

  const update = () => {
    ticking = false;
    const rect = section.getBoundingClientRect();
    const total = section.offsetHeight - window.innerHeight;
    const p = Math.min(Math.max(-rect.top / (total || 1), 0), 1);
    const n = cards.length;
    cards.forEach((card, i) => {
      const off = i - (n - 1) / 2;
      const spread = Math.min(stage.clientWidth * 0.24, 300);
      const x = off * spread * p;
      const rotY = -off * 15 * p;
      const rotZ = off * 4.5 * p;
      const z = -Math.abs(off) * 130 * p;
      const y = Math.abs(off) * 12 * p + Math.sin(p * Math.PI) * -18;
      const scale = 0.9 + 0.1 * p;
      card.style.transform =
        `translate3d(${x}px, ${y}px, ${z}px) rotateY(${rotY}deg) rotateZ(${rotZ}deg) scale(${scale})`;
      card.style.zIndex = String(10 - Math.abs(Math.round(off)));
    });
  };
  window.addEventListener("scroll", () => {
    if (!ticking) { ticking = true; requestAnimationFrame(update); }
  }, { passive: true });
  window.addEventListener("resize", update);
  update();
}

/* ---------- coverflow strip (rooms gallery) ---------- */
function initCoverflow(track) {
  if (!track || track._cf) return; track._cf = true;
  const cards = $$(".cf-card", track);

  const update = () => {
    const tr = track.getBoundingClientRect();
    const cx = tr.left + tr.width / 2;
    let best = null, bestDist = Infinity;
    cards.forEach(card => {
      const r = card.getBoundingClientRect();
      const d = (r.left + r.width / 2) - cx;
      const norm = Math.max(-1.6, Math.min(1.6, d / (tr.width * 0.62)));
      card.style.transform = `perspective(1300px) rotateY(${-norm * 17}deg) scale(${1 - Math.abs(norm) * 0.1})`;
      card.style.zIndex = String(50 - Math.round(Math.abs(norm) * 20));
      card.classList.remove("is-center");
      const dist = Math.abs(d);
      if (dist < bestDist) { bestDist = dist; best = card; }
    });
    best?.classList.add("is-center");
  };

  track.addEventListener("scroll", () => requestAnimationFrame(update), { passive: true });
  window.addEventListener("resize", update);

  // drag to scroll
  let down = false, startX = 0, startL = 0, moved = false;
  track.addEventListener("pointerdown", e => {
    down = true; moved = false; startX = e.clientX; startL = track.scrollLeft;
    track.classList.add("dragging");
  });
  window.addEventListener("pointermove", e => {
    if (!down) return;
    const dx = e.clientX - startX;
    if (Math.abs(dx) > 6) moved = true;
    track.scrollLeft = startL - dx;
  });
  window.addEventListener("pointerup", () => {
    if (!down) return;
    down = false; track.classList.remove("dragging");
    if (moved) {
      // snap to nearest card
      const tr = track.getBoundingClientRect();
      const cx = tr.left + tr.width / 2;
      let best = null, bd = Infinity;
      cards.forEach(c => {
        const r = c.getBoundingClientRect();
        const d = Math.abs((r.left + r.width / 2) - cx);
        if (d < bd) { bd = d; best = c; }
      });
      best?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
    }
  });
  // wheel → horizontal inside gallery
  track.addEventListener("wheel", e => {
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
      const before = track.scrollLeft;
      track.scrollLeft += e.deltaY;
      if (track.scrollLeft !== before) e.preventDefault();
    }
  }, { passive: false });

  update();
}

/* ---------- boot ---------- */
document.addEventListener("DOMContentLoaded", () => {
  initNav();
  initReveal();
  initCounters();
  initParallax();
  initFan();
  initTilt();
});

/* require a signed-in guest — returns user or null after nudging to /auth */
async function requireUser() {
  try {
    const me = await api("/api/me");
    if (me.user) return me.user;
  } catch (_) { /* ignore */ }
  toast("Please sign in to continue.", "err");
  setTimeout(() => { location.href = "/auth?next=" + encodeURIComponent(location.pathname); }, 700);
  return null;
}
