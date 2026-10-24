"""WCAG contrast and layout audit for Country Detail (Playwright).

Usage:
    python3 scripts/visual_qa/contrast.py --serve _site_qa OUT_DIR
    python3 scripts/visual_qa/contrast.py --serve _site_qa OUT_DIR --countries ca,us --viewports iphone,laptop

Serves the site directory over HTTP (see capture.serve), opens every country drilldown,
and writes a JSON report plus element screenshots. Exits non-zero on failures outside
Not used by CI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from scripts.visual_qa.capture import open_details_in_country, select, serve, slice_image

VIEWPORTS = {
    "laptop": {"width": 1440, "height": 900, "mobile": False},
    "iphone": {"width": 390, "height": 844, "mobile": True},
}

COUNTRY_RADIO = {
    "us": "c-us",
    "ca": "c-ca",
    "au": "c-au",
    "nz": "c-nz",
    "ea": "c-ea",
    "jp": "c-jp",
}

BODY_BASE = "#0a0f15"

CONTRAST_AUDIT_SCRIPT = """
(rootSelector) => {
  const BODY_BASE = {r: 10, g: 15, b: 21, a: 1};

  function parseColor(raw) {
    if (!raw || raw === "transparent") return null;
    const m = raw.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?\\)/);
    if (m) {
      return {
        r: +m[1] / 255,
        g: +m[2] / 255,
        b: +m[3] / 255,
        a: m[4] !== undefined ? +m[4] : 1,
      };
    }
    const h = raw.match(/^#([0-9a-f]{3,8})$/i);
    if (!h) return null;
    let hex = h[1];
    if (hex.length === 3) hex = hex.split("").map((c) => c + c).join("");
    const n = parseInt(hex.slice(0, 6), 16);
    return { r: ((n >> 16) & 255) / 255, g: ((n >> 8) & 255) / 255, b: (n & 255) / 255, a: 1 };
  }

  function clamp01(c) {
    return {
      r: Math.min(1, Math.max(0, c.r)),
      g: Math.min(1, Math.max(0, c.g)),
      b: Math.min(1, Math.max(0, c.b)),
      a: Math.min(1, Math.max(0, c.a)),
    };
  }

  function over(fg, bg) {
    const a = fg.a + bg.a * (1 - fg.a);
    if (a <= 0) return clamp01(bg);
    return clamp01({
      r: (fg.r * fg.a + bg.r * bg.a * (1 - fg.a)) / a,
      g: (fg.g * fg.a + bg.g * bg.a * (1 - fg.a)) / a,
      b: (fg.b * fg.a + bg.b * bg.a * (1 - fg.a)) / a,
      a,
    });
  }

  function luminance(c) {
    const f = (v) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  }

  function contrastRatio(fg, bg) {
    const L1 = luminance(fg);
    const L2 = luminance(bg);
    const hi = Math.max(L1, L2);
    const lo = Math.min(L1, L2);
    return (hi + 0.05) / (lo + 0.05);
  }

  function effectiveBackground(el) {
    let bg = { ...BODY_BASE };
    const chain = [];
    let node = el;
    while (node && node.nodeType === 1) {
      chain.unshift(node);
      node = node.parentElement;
    }
    for (const node of chain) {
      if (node === document.documentElement) continue;
      const st = getComputedStyle(node);
      const c = parseColor(st.backgroundColor);
      if (!c || c.a <= 0.01) continue;
      if (node === document.body && c.a < 0.99 && luminance(c) > 0.9) continue;
      bg = over(c, bg);
    }
    return bg;
  }

  function isVisible(el) {
    if (!el || !el.isConnected) return false;
    const st = getComputedStyle(el);
    if (st.display === "none" || st.visibility === "hidden" || +st.opacity === 0) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function isBold(st) {
    const w = st.fontWeight;
    if (w === "bold" || w === "bolder") return true;
    const n = parseInt(w, 10);
    return !Number.isNaN(n) && n >= 700;
  }

  function isMicroLabel(st) {
    return st.textTransform === "uppercase" && parseFloat(st.letterSpacing || "0") >= 0.03;
  }

  function selectorPath(el) {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 12) {
      let bit = node.tagName.toLowerCase();
      if (node.id) bit += "#" + node.id;
      else if (node.className && typeof node.className === "string") {
        const cls = node.className.trim().split(/\\s+/).slice(0, 2).join(".");
        if (cls) bit += "." + cls;
      }
      parts.unshift(bit);
      node = node.parentElement;
    }
    return parts.join(" > ");
  }

  const root = document.querySelector(rootSelector);
  if (!root) return { error: "root missing", checked: 0, failures: [], primaFailures: [] };

  const failures = [];
  const primaFailures = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let checked = 0;
  let node;
  while ((node = walker.nextNode())) {
    const text = (node.textContent || "").replace(/\\s+/g, " ").trim();
    if (!text) continue;
    const el = node.parentElement;
    if (!el || !root.contains(el)) continue;
    if (el.closest("script, style, noscript")) continue;
    if (!isVisible(el)) continue;
    checked += 1;
    const st = getComputedStyle(el);
    const fg = parseColor(st.color);
    const bg = effectiveBackground(el);
    if (!fg || !bg) continue;
    const fgSolid = over(fg, bg);
    const ratio = contrastRatio(fgSolid, bg);
    const fs = parseFloat(st.fontSize) || 0;
    const large = fs >= 24 || (fs >= 18.66 && isBold(st));
    const need = large ? 3.0 : 4.5;
    const inPrima = !!el.closest(".prima-pressure");
    const buckets = failures;
    const row = {
      text: text.slice(0, 120),
      selector: selectorPath(el),
      fg: st.color,
      bg: `rgb(${Math.round(bg.r * 255)}, ${Math.round(bg.g * 255)}, ${Math.round(bg.b * 255)})`,
      ratio: Math.round(ratio * 100) / 100,
      fontSizePx: fs,
      kind: null,
    };
    if (ratio < need) {
      row.kind = "contrast";
      buckets.push(row);
      if (inPrima) primaFailures.push(row);
      continue;
    }
    if (fs > 0 && fs < 11) {
      row.kind = "font_tiny";
      buckets.push(row);
      if (inPrima) primaFailures.push(row);
      continue;
    }
    if (fs > 0 && fs < 12 && !isMicroLabel(st)) {
      row.kind = "font_small";
      buckets.push(row);
      if (inPrima) primaFailures.push(row);
    }
  }

  const layout = [];
  const overflowX =
    document.documentElement.scrollWidth - document.documentElement.clientWidth;
  if (overflowX > 1) {
    layout.push({ kind: "document_overflow", px: overflowX });
  }
  root.querySelectorAll("*").forEach((el) => {
    if (el.closest(".nav .stamp")) return;
    const st = getComputedStyle(el);
    const ov = st.overflowX;
    if (ov !== "hidden" && ov !== "clip") return;
    if (el.scrollWidth > el.clientWidth + 1) {
      layout.push({
        kind: "clipped",
        selector: selectorPath(el),
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
      });
    }
  });

  return { checked, failures, primaFailures, layout };
}
"""


def chrome_path() -> str:
    return os.environ.get("CHROME_PATH", "/usr/local/bin/google-chrome")


def run_audit(
    base_url: str,
    out_dir: Path,
    countries: list[str],
    viewports: list[str],
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"baseUrl": base_url, "viewports": {}}
    any_fail = False

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome_path())
        for vname in viewports:
            vp = VIEWPORTS[vname]
            report["viewports"][vname] = {"countries": {}}
            ctx = browser.new_context(
                viewport={"width": vp["width"], "height": vp["height"]},
                device_scale_factor=2 if vp["mobile"] else 1,
                is_mobile=vp["mobile"],
                has_touch=vp["mobile"],
            )
            page = ctx.new_page()
            page.goto(base_url, wait_until="networkidle")
            for code in countries:
                select(page, "p-country")
                select(page, COUNTRY_RADIO[code])
                page.wait_for_timeout(400)
                open_details_in_country(page, code)
                page.wait_for_timeout(200)
                root_sel = f".cdetail.{code}"
                audit = page.evaluate(CONTRAST_AUDIT_SCRIPT, root_sel)
                failures = audit.get("failures") or []
                layout_bad = audit.get("layout") or []
                prima = audit.get("primaFailures") or []
                report["viewports"][vname]["countries"][code] = {
                    "checked": audit.get("checked", 0),
                    "failures": failures,
                    "primaFailures": prima,
                    "layout": layout_bad,
                }
                if failures or layout_bad:
                    any_fail = True
                el = page.query_selector(root_sel)
                if el:
                    shot = out_dir / f"{vname}-cdetail-{code}.png"
                    el.screenshot(path=str(shot))
                    slice_image(shot, out_dir / f"slices-{vname}-{code}")
            ctx.close()
        browser.close()

    report_path = out_dir / "contrast-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report, any_fail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Country Detail contrast audit")
    parser.add_argument("--serve", metavar="SITE_DIR", required=True)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--countries", default="us,ca,au,nz,ea,jp")
    parser.add_argument("--viewports", default="iphone,laptop")
    args = parser.parse_args(argv)
    site = Path(args.serve)
    countries = [c.strip().lower() for c in args.countries.split(",") if c.strip()]
    viewports = [v.strip() for v in args.viewports.split(",") if v.strip()]
    for v in viewports:
        if v not in VIEWPORTS:
            raise SystemExit(f"unknown viewport {v}")
    base = serve(str(site.resolve()))
    _, failed = run_audit(base, args.out_dir, countries, viewports)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
