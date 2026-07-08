/** Client-side i18n (FR / EN / ES), persisted in localStorage. */
const I18n = (() => {
  const STORAGE_KEY = "instree.lang";
  const SUPPORTED = ["fr", "en", "es"];
  let locale = "fr";
  let strings = {};
  let readyResolve;
  const ready = new Promise((resolve) => {
    readyResolve = resolve;
  });

  function normalize(lang) {
    const code = (lang || "fr").slice(0, 2).toLowerCase();
    return SUPPORTED.includes(code) ? code : "fr";
  }

  function getLocale() {
    return locale;
  }

  function interpolate(text, vars) {
    if (!vars) return text;
    return text.replace(/\{(\w+)\}/g, (_, key) =>
      vars[key] != null ? String(vars[key]) : `{${key}}`,
    );
  }

  function t(key, vars) {
    const raw = strings[key] ?? key;
    return interpolate(raw, vars);
  }

  function applyI18n(root = document) {
    root.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.dataset.i18n;
      if (key) el.textContent = t(key);
    });
    root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      const key = el.dataset.i18nPlaceholder;
      if (key) el.placeholder = t(key);
    });
    root.querySelectorAll("[data-i18n-title]").forEach((el) => {
      const key = el.dataset.i18nTitle;
      if (key) {
        el.title = t(key);
        if (el.hasAttribute("aria-label")) el.setAttribute("aria-label", t(key));
      }
    });
    document.documentElement.lang = locale;
    document.querySelectorAll("[data-lang]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.lang === locale);
    });
  }

  async function loadLocale(lang) {
    locale = normalize(lang);
    localStorage.setItem(STORAGE_KEY, locale);
    const res = await fetch(`/static/locales/${locale}.json`);
    strings = await res.json();
    document.documentElement.lang = locale;
    applyI18n();
    window.dispatchEvent(new CustomEvent("instree:locale", { detail: { locale } }));
    return locale;
  }

  async function setLocale(lang) {
    return loadLocale(lang);
  }

  async function init() {
    const stored = localStorage.getItem(STORAGE_KEY);
    const browser = navigator.language || "fr";
    await loadLocale(stored || browser);
    readyResolve();
  }

  init();

  return { ready, getLocale, setLocale, t, applyI18n };
})();
