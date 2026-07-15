#!/usr/bin/env python3
"""Capture Home / Graph / Settings with randomized usernames (no real handles)."""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
BASE = "http://127.0.0.1:8765"

# Injected before any page JS — rewrites JSON API usernames consistently.
ANON_INIT = r"""
(() => {
  const adj = [
    "luna","neo","atlas","mira","quartz","velvet","harbor","cipher","nova","orbit",
    "ember","frost","pixel","cedar","amber","coral","drift","echo","flint","grove",
  ];
  const noun = [
    "park","vault","wave","stone","lane","ridge","bloom","field","brook","delta",
    "forge","glide","haven","ivory","jade","kite","lotus","maple","north","opal",
  ];
  const display = [
    "Ada Klein","Sam Ortega","Nina Brooks","Leo March","Ivy Chen","Omar Reed",
    "Tess Hale","Rio Vance","Jade Quinn","Eli Stone","Maya Frost","Cole Avery",
    "Quinn Park","Noah Blake","Nora West","Kai Rivers","Ruby Dane","Jules Fox",
  ];
  const map = new Map();
  let n = 0;

  function fakeUser(raw) {
    const key = String(raw || "").replace(/^@/, "").trim().toLowerCase();
    if (!key) return raw;
    if (!map.has(key)) {
      const u = `${adj[n % adj.length]}.${noun[(n * 3) % noun.length]}`;
      map.set(key, n >= adj.length * noun.length ? `${u}${n}` : u);
      n += 1;
    }
    return map.get(key);
  }

  function fakeFullName(raw) {
    if (raw == null || raw === "") return raw;
    const key = "fn:" + String(raw);
    if (!map.has(key)) {
      map.set(key, display[map.size % display.length]);
    }
    return map.get(key);
  }

  const USER_KEYS = new Set([
    "username", "subject_username", "progress_user", "watch_user",
    "id", "source", "target",
  ]);

  function looksLikeHandle(s) {
    if (typeof s !== "string" || !s) return false;
    if (s.includes("/") || s.includes(" ") || s.includes("T") && s.includes("-")) return false;
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
})();
"""

PAGES = [
    ("/changes", "home.png", 2500),
    ("/graph", "graph.png", 4500),
    ("/settings", "settings.png", 2000),
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
        page = context.new_page()
        # Prefer French UI for README
        page.add_init_script("localStorage.setItem('instree.lang','fr');")

        for path, filename, wait_ms in PAGES:
            page.goto(f"{BASE}{path}", wait_until="networkidle")
            page.wait_for_timeout(wait_ms)
            if path == "/graph":
                # Let force simulation settle a bit
                page.wait_for_timeout(2000)
            dest = OUT / filename
            page.screenshot(path=str(dest), full_page=False)
            print(f"wrote {dest}")

        browser.close()


if __name__ == "__main__":
    main()
