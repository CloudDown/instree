/* Auth pages (mode public) */
(async function () {
  await (window.I18n?.ready || Promise.resolve());
  if (window.I18n) {
    I18n.applyI18n();
    document.querySelectorAll(".lang-btn").forEach((btn) => {
      btn.onclick = () => I18n.setLocale(btn.dataset.lang);
    });
  }

  const form = document.getElementById("auth-form");
  const errEl = document.getElementById("auth-error");
  if (!form) return;

  const mode = form.dataset.mode || "login";
  const t = (key) => (window.I18n ? I18n.t(key) : key);

  function initPasswordToggles() {
    document.querySelectorAll("[data-secret-toggle]").forEach((btn) => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = "1";
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-secret-toggle");
        const input = id ? document.getElementById(id) : null;
        if (!input) return;
        const showPlain = input.type === "password";
        input.type = showPlain ? "text" : "password";
        btn.setAttribute("aria-pressed", showPlain ? "true" : "false");
        btn.setAttribute(
          "aria-label",
          t(showPlain ? "settings.hideSecret" : "settings.showSecret")
        );
      });
    });
  }

  initPasswordToggles();

  function showError(msg) {
    if (!errEl) return;
    errEl.textContent = msg;
    errEl.classList.remove("hidden");
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errEl?.classList.add("hidden");
    const username = document.getElementById("auth-username")?.value.trim() || "";
    const password = document.getElementById("auth-password")?.value || "";
    if (mode === "register") {
      const password2 = document.getElementById("auth-password2")?.value || "";
      if (password !== password2) {
        showError(t("auth.passwordMismatch"));
        return;
      }
    }
    const url = mode === "register" ? "/api/auth/register" : "/api/auth/login";
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      showError(data.detail || t("auth.error"));
      return;
    }
    const params = new URLSearchParams(location.search);
    const next = params.get("next") || "/changes";
    location.href = next.startsWith("/") ? next : "/changes";
  });
})();
