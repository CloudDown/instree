#!/usr/bin/env python3
"""Capture Home / Graph / Settings with clearly fictional usernames."""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
BASE = "http://127.0.0.1:8765"

# Injected before any page JS — rewrites JSON API usernames consistently.
ANON_INIT = r"""
(() => {
  // Noms volontairement fictifs / « demo » (pas de vrais handles IG).
  const handles = [
    "alice.demo", "bruno.exemple", "chloe.fiction", "diego.sample", "emma.test",
    "felix.dummy", "gina.mock", "hugo.placeholder", "iris.sandbox", "jules.staging",
    "karen.fake", "leo.notreal", "maya.demoapp", "noah.sampleapp", "olga.testdata",
    "paul.mockuser", "quin.fictional", "rita.example", "sam.demouser", "tina.fakename",
    "uma.sandboxed", "vic.placeholder", "wren.dummyacc", "xo.testhandle", "yuki.mockdata",
    "zane.fiction", "aria.demo", "beau.exemple", "cara.sample", "drew.notreal",
  ];
  const display = [
    "Alice Demo", "Bruno Exemple", "Chloé Fiction", "Diego Sample", "Emma Test",
    "Félix Dummy", "Gina Mock", "Hugo Placeholder", "Iris Sandbox", "Jules Staging",
    "Karen Fake", "Léo Notreal", "Maya Demoapp", "Noah Sample", "Olga Testdata",
    "Paul Mockuser", "Quin Fictional", "Rita Example", "Sam Demouser", "Tina Fakename",
  ];
  const map = new Map();
  let n = 0;

  function fakeUser(raw) {
    const key = String(raw || "").replace(/^@/, "").trim().toLowerCase();
    if (!key) return raw;
    if (!map.has(key)) {
      const base = handles[n % handles.length];
      map.set(key, n >= handles.length ? `${base}${Math.floor(n / handles.length)}` : base);
      n += 1;
    }
    return map.get(key);
  }

  function fakeFullName(raw) {
    if (raw == null || raw === "") return raw;
    const key = "fn:" + String(raw);
    if (!map.has(key)) map.set(key, display[map.size % display.length]);
    return map.get(key);
  }

  const USER_KEYS = new Set([
    "username", "subject_username", "progress_user", "watch_user",
    "id", "source", "target",
  ]);

  function looksLikeHandle(s) {
    if (typeof s !== "string" || !s) return false;
    if (s.includes("/") || s.includes(" ")) return false;
    if (s.includes("T") && /\d{4}-\d{2}-\d{2}/.test(s)) return false;
    if (s.length > 40) return false;
    return /^@?[A-Za-z0-9._]+$/.test(s);
  }

  function walk(value, key) {
    if (Array.isArray(value)) return value.map((v) => walk(v, key));
    if (value && typeof value === "object") {
      const out = {};
      for (const [k, v] of Object.entries(value)) out[k] = walk(v, k);
      return out;
    }
    if (typeof value === "string") {
      if (key === "full_name") return fakeFullName(value);
      if (key === "name" && value.startsWith("@")) return "@" + fakeUser(value);
      if (USER_KEYS.has(key) && looksLikeHandle(value)) {
        return value.startsWith("@") ? "@" + fakeUser(value) : fakeUser(value);
      }
    }
    return value;
  }

  const origFetch = window.fetch.bind(window);
  window.fetch = async function (...args) {
    const res = await origFetch(...args);
    const ct = res.headers.get("content-type") || "";
    if (!ct.includes("application/json")) return res;
    try {
      const data = walk(await res.clone().json());
      return new Response(JSON.stringify(data), {
        status: res.status,
        statusText: res.statusText,
        headers: res.headers,
      });
    } catch {
      return res;
    }
  };

  // Remplace aussi tout @handle restant dans le DOM (filet de sécurité).
  window.__instreeAnonDom = function () {
    const re = /@([A-Za-z0-9._]{2,30})/g;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const t = node.nodeValue;
      if (!t || !t.includes("@")) continue;
      node.nodeValue = t.replace(re, (_, u) => "@" + fakeUser(u));
    }
    for (const a of document.querySelectorAll('a[href*="instagram.com"]')) {
      const href = a.getAttribute("href") || "";
      const m = href.match(/instagram\.com\/([A-Za-z0-9._]+)/);
      if (m) {
        const nu = fakeUser(m[1]);
        a.setAttribute("href", `https://instagram.com/${nu}`);
        if (a.textContent && a.textContent.includes("@")) {
          a.textContent = a.textContent.replace(re, () => "@" + nu);
        }
      }
    }
  };
})();
"""

# Nouveaux noms de fichiers = invalide le cache Camo/GitHub des anciennes captures.
PAGES = [
    ("/changes", "readme-home.png", 2800),
    ("/graph", "readme-graph.png", 5000),
    ("/settings", "readme-settings.png", 2200),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            device_scale_factor=1.5,
            locale="fr-FR",
        )
        context.add_init_script(ANON_INIT)
        context.add_init_script("localStorage.setItem('instree.lang','fr');")
        page = context.new_page()

        for path, filename, wait_ms in PAGES:
            page.goto(f"{BASE}{path}", wait_until="networkidle")
            page.wait_for_timeout(wait_ms)
            if path == "/graph":
                page.wait_for_timeout(2500)
            page.evaluate("() => window.__instreeAnonDom && window.__instreeAnonDom()")
            page.wait_for_timeout(200)
            dest = OUT / filename
            page.screenshot(path=str(dest), full_page=False)
            print(f"wrote {dest}")

        browser.close()

    # Supprime les anciennes captures (évite de republier de vrais @).
    for old in ("home.png", "graph.png", "settings.png"):
        p = OUT / old
        if p.exists():
            p.unlink()
            print(f"removed {p}")


if __name__ == "__main__":
    main()
