from __future__ import annotations

import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "_site/index.html")
html = path.read_text()
patch = Path("patch_v10/us_cpi_context.html").read_text()
anchor = (
    '<div class="evidence-row context-row"><div class="evidence-meta">'
    '<span class="evidence-role">CONTEXT ONLY</span><span>JUL 2026</span></div>'
    '<div class="evidence-main"><strong>Core PCE y/y</strong>'
)
if "CONTEXT ONLY · CPI" in html:
    raise SystemExit("v10 CPI context patch already present")
if html.count(anchor) != 1:
    raise SystemExit("US inflation CPI context anchor changed")
path.write_text(html.replace(anchor, patch + anchor, 1))
