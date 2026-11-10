/* VILAS — sign in / register */

let mode = "login";

document.addEventListener("DOMContentLoaded", async () => {
  // already signed in? go home (or back)
  try {
    const me = await api("/api/me");
    if (me.user) { location.href = nextPath(); return; }
  } catch (_) { /* show form */ }

  $$("#authTabs button").forEach(b => b.addEventListener("click", () => setMode(b.dataset.mode)));
  $("#switchMode").addEventListener("click", () => setMode(mode === "login" ? "register" : "login"));
  $("#authForm").addEventListener("submit", submit);
});

function setMode(m) {
  mode = m;
  $$("#authTabs button").forEach(x => x.classList.toggle("active", x.dataset.mode === m));
  $("#nameField").style.display = m === "register" ? "" : "none";
  $("#phoneField").style.display = m === "register" ? "" : "none";
  $("#authSubmit").textContent = m === "register" ? "Create account ✦" : "Sign in ✦";
  $("#aPass").autocomplete = m === "register" ? "new-password" : "current-password";
  $("#switchHint").innerHTML = m === "login"
    ? `New here? <span class="text-link" id="switchMode">Create an account</span>`
    : `Already with us? <span class="text-link" id="switchMode">Sign in</span>`;
  $("#switchMode").addEventListener("click", () => setMode(mode === "login" ? "register" : "login"));
}

const nextPath = () => {
  const n = new URLSearchParams(location.search).get("next");
  return n && n.startsWith("/") ? n : "/";
};

async function submit(e) {
  e.preventDefault();
  const btn = $("#authSubmit");
  const label = btn.textContent;
  btn.disabled = true; btn.textContent = "Just a moment…";
  try {
    const body = { email: $("#aEmail").value, password: $("#aPass").value };
    if (mode === "register") {
      body.name = $("#aName").value;
      body.phone = $("#aPhone").value;
      await api("/api/auth/register", { method: "POST", body });
      toast("Welcome to Vilas ✦", "ok");
    } else {
      await api("/api/auth/login", { method: "POST", body });
      toast("Welcome back ✓", "ok");
    }
    setTimeout(() => { location.href = nextPath(); }, 450);
  } catch (err) {
    toast(err.message, "err");
    btn.disabled = false; btn.textContent = label;
  }
}
