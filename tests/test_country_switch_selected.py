"""Selected country pill stays visible on the dark theme and on a light page."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "scripts" / "dashboard_repair" / "theme.css"
CHROME = os.environ.get("CHROME_PATH", "/usr/bin/google-chrome")
NODE = shutil.which("node")
COUNTRIES = (
    ("us", "United States"),
    ("ca", "Canada"),
    ("au", "Australia"),
    ("nz", "New Zealand"),
    ("ea", "Euro Area"),
    ("jp", "Japan"),
)
SELECTED_FILL = (33, 123, 181)  # #217bb5
FOCUS_RING = (247, 251, 255)  # #f7fbff
FOCUS_HALO = (11, 61, 102)  # #0b3d66

_NODE = r"""
import { spawn } from 'node:child_process';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs';

const htmlPath = process.argv[2];
const width = Number(process.argv[3]);
const port = 9400 + Math.floor(Math.random() * 400);
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'mw-chrome-'));
const chrome = spawn(process.env.CHROME_PATH || '/usr/bin/google-chrome', [
  '--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run',
  `--user-data-dir=${profile}`, `--remote-debugging-port=${port}`, htmlPath,
], { stdio: 'ignore' });

function get(url) {
  return new Promise((resolve, reject) => {
    http.get(url, res => {
      let data = '';
      res.on('data', chunk => { data += chunk; });
      res.on('end', () => resolve(data));
    }).on('error', reject);
  });
}
async function waitJson() {
  for (let i = 0; i < 50; i++) {
    try {
      const tabs = JSON.parse(await get(`http://127.0.0.1:${port}/json/list`));
      const page = tabs.find(tab => tab.type === 'page' && tab.webSocketDebuggerUrl);
      if (page) return page;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('no tab');
}
const page = await waitJson();
const ws = new WebSocket(page.webSocketDebuggerUrl);
let seq = 0;
const pending = new Map();
ws.addEventListener('message', event => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
  }
});
await new Promise(resolve => ws.addEventListener('open', resolve, { once: true }));
function send(method, params = {}) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise(resolve => pending.set(id, resolve));
}
if (width >= 500) {
  await send('Emulation.setDeviceMetricsOverride', {
    width, height: 844, deviceScaleFactor: 1, mobile: false,
  });
}
const expr = `(() => {
  const column = ${width};
  const app = document.querySelector('.app');
  if (column < 500) app.style.width = column + 'px';
  const radio = document.getElementById('c-ca');
  radio.checked = true;
  radio.focus();
  const selected = document.querySelector('label[for="c-ca"]');
  const other = document.querySelector('label[for="c-us"]');
  const sel = getComputedStyle(selected);
  const uns = getComputedStyle(other);
  const rect = selected.getBoundingClientRect();
  const box = app.getBoundingClientRect();
  const labels = [...document.querySelectorAll('.country-switch label')].map(label => {
    const r = label.getBoundingClientRect();
    return { right: r.right, bottom: r.bottom };
  });
  return {
    width: innerWidth,
    columnRight: box.right,
    active: document.activeElement && document.activeElement.id,
    radioFocus: radio.matches(':focus'),
    radioFocusVisible: radio.matches(':focus-visible'),
    scrollWidth: document.documentElement.scrollWidth,
    selectedBg: sel.backgroundColor,
    selectedColor: sel.color,
    selectedBorder: sel.borderTopColor,
    selectedWeight: sel.fontWeight,
    otherBg: uns.backgroundColor,
    bodyBg: getComputedStyle(document.body).backgroundColor,
    outline: sel.outlineColor,
    outlineWidth: sel.outlineWidth,
    shadow: sel.boxShadow,
    top: rect.top,
    right: rect.right,
    bottom: rect.bottom,
    labelRights: labels.map(item => item.right),
    labelBottoms: labels.map(item => item.bottom)
  };
})()`;
const result = await send('Runtime.evaluate', { expression: expr, returnByValue: true });
if (result.result && result.result.exceptionDetails) {
  console.log(JSON.stringify({ error: result.result.exceptionDetails.text }));
} else {
  console.log(JSON.stringify((result.result && result.result.result && result.result.result.value) || result));
}
ws.close();
chrome.kill('SIGKILL');
process.exit(0);
"""


def _rgb(text: str) -> tuple[int, int, int]:
    match = re.search(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", text or "")
    if not match:
        raise AssertionError(f"not a colour: {text!r}")
    return tuple(int(part) for part in match.groups())


def _channel(value: int) -> float:
    scaled = value / 255
    if scaled <= 0.04045:
        return scaled / 12.92
    return ((scaled + 0.055) / 1.055) ** 2.4


def _contrast(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    def lum(rgb: tuple[int, int, int]) -> float:
        red, green, blue = rgb
        return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)

    lighter, darker = sorted((lum(fg), lum(bg)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _page(theme_class: str) -> str:
    theme = THEME.read_text(encoding="utf-8")
    codes = [code for code, _name in COUNTRIES]
    checked = ",".join(f"#c-{code}:checked~.app label[for=c-{code}]" for code in codes)
    labels = "".join(f'<label for="c-{code}">{name}</label>' for code, name in COUNTRIES)
    radios = "\n".join(
        f'<input id="c-{code}" name="country" type="radio"{" checked" if code == "us" else ""}>'
        for code, _name in COUNTRIES
    )
    return f"""<!DOCTYPE html>
<html class="{theme_class}"><head><meta charset="utf-8">
<style>
:root {{
  --navy:#13283a; --line:#d8e1e8;
  --mw-panel-2:#16202b; --mw-ink:#e7edf3; --mw-line:#233140; --mw-bg:#0a0f15; --mw-focus:#9fd0ff;
}}
body {{ margin:0; background:var(--mw-bg); font:14px/1.4 Inter,sans-serif; }}
input[type=radio] {{ position:absolute; left:-9999px; }}
.country-switch {{ display:flex; gap:7px; flex-wrap:wrap; margin:16px; }}
.country-switch label {{
  border:1px solid var(--line); background:#fff; padding:7px 12px; border-radius:7px;
  cursor:pointer; font-weight:750; color:#506679;
}}
{checked} {{ background:var(--navy); color:#fff; border-color:var(--navy); }}
.country-switch label {{ background:var(--mw-panel-2); color:var(--mw-ink); border-color:var(--mw-line); }}
{theme}
html.light {{
  --mw-panel-2:#fff; --mw-ink:#506679; --mw-line:#d8e1e8; --mw-bg:#f3f6f8; --navy:#13283a;
  color-scheme:light;
}}
html.light body {{ background:#f3f6f8; color:#172432; }}
</style></head><body>
{radios}
<div class="app"><div class="country-switch">{labels}</div></div>
</body></html>
"""


def _render(theme_class: str, width: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        html_path = root / "country-switch.html"
        html_path.write_text(_page(theme_class), encoding="utf-8")
        script = root / "probe.mjs"
        script.write_text(_NODE, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(script), html_path.as_uri(), str(width)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "CHROME_PATH": CHROME},
        )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-2000:] or proc.stdout[-2000:])
    payload = json.loads(proc.stdout)
    if payload.get("error"):
        raise AssertionError(payload["error"])
    return payload


class CountrySwitchSelectedTest(unittest.TestCase):
    def test_theme_targets_every_country_without_using_navy(self) -> None:
        css = THEME.read_text(encoding="utf-8")
        for code, _name in COUNTRIES:
            self.assertIn(f"#c-{code}:checked~.app .country-switch label[for=c-{code}]", css)
            self.assertIn(f"#c-{code}:focus-visible~.app .country-switch label[for=c-{code}]", css)
        block = css.split("Selected country.", 1)[1].split("outline:3px solid #f7fbff", 1)[0]
        self.assertNotIn("var(--navy)", block)
        self.assertIn("background:#217bb5", block)
        self.assertIn("font-weight:800", block)

    @unittest.skipUnless(Path(CHROME).is_file() and NODE, "Chrome and Node required")
    def test_selected_pill_contrasts_on_dark_and_light_at_phone_and_desktop(self) -> None:
        for theme, width in (("dark", 390), ("dark", 1280), ("light", 390), ("light", 1280)):
            with self.subTest(theme=theme, width=width):
                probe = _render(theme, width)
                selected_bg = _rgb(probe["selectedBg"])
                other_bg = _rgb(probe["otherBg"])
                selected_ink = _rgb(probe["selectedColor"])
                self.assertEqual(selected_bg, SELECTED_FILL)
                self.assertNotEqual(selected_bg, other_bg)
                self.assertGreaterEqual(_contrast(selected_ink, selected_bg), 4.5)
                self.assertGreaterEqual(_contrast(selected_bg, other_bg), 3.0)
                self.assertEqual(probe["selectedWeight"], "800")
                self.assertEqual(_rgb(probe["selectedBorder"]), FOCUS_HALO)
                self.assertTrue(probe["radioFocus"])
                self.assertTrue(probe["radioFocusVisible"])
                self.assertEqual(probe["active"], "c-ca")
                self.assertEqual(_rgb(probe["outline"]), FOCUS_RING)
                self.assertEqual(probe["outlineWidth"], "3px")
                self.assertEqual(_rgb(probe["shadow"]), FOCUS_HALO)
                ring = max(
                    _contrast(FOCUS_RING, _rgb(probe["bodyBg"])),
                    _contrast(FOCUS_HALO, _rgb(probe["bodyBg"])),
                )
                self.assertGreaterEqual(ring, 3.0)
                limit = 390 if width < 500 else probe["width"]
                self.assertLessEqual(max(probe["labelRights"]), limit + 1)
                self.assertGreaterEqual(probe["top"], 0)
                self.assertGreater(probe["bottom"], probe["top"])
                if width >= 500:
                    self.assertGreaterEqual(probe["width"], 1200)
                    self.assertLessEqual(probe["scrollWidth"], probe["width"] + 1)


if __name__ == "__main__":
    unittest.main()
