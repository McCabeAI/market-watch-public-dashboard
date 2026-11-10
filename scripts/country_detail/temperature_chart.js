(function () {
  "use strict";

  function parseValues(raw) {
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch (_e) {
      return null;
    }
  }

  function activateWindow(panel, months) {
    var buttons = panel.querySelectorAll(".temp-window-btn");
    var blocks = panel.querySelectorAll("[data-window-panel]");
    var active = null;
    buttons.forEach(function (btn) {
      var win = btn.getAttribute("data-window");
      var on = String(win) === String(months);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      if (on) active = btn;
    });
    blocks.forEach(function (block) {
      var win = block.getAttribute("data-window-panel");
      if (String(win) === String(months)) {
        block.removeAttribute("hidden");
        var monthEl = panel.querySelector("[data-temp-month]");
        var label = block.getAttribute("data-latest-label");
        if (monthEl && label) monthEl.textContent = label;
        var values = parseValues(block.getAttribute("data-latest-values"));
        if (values) {
          panel.querySelectorAll(".temp-tile").forEach(function (tile) {
            var series = tile.getAttribute("data-series");
            var valNode = tile.querySelector(".temp-tile-value");
            if (valNode && series && Object.prototype.hasOwnProperty.call(values, series)) {
              valNode.textContent = values[series];
            }
          });
        }
      } else {
        block.setAttribute("hidden", "");
      }
    });
    if (active) active.focus();
  }

  function ensureTip(panel) {
    var tip = panel.querySelector(".temp-tip");
    if (tip) return tip;
    tip = document.createElement("div");
    tip.className = "temp-tip";
    tip.setAttribute("role", "status");
    tip.hidden = true;
    panel.appendChild(tip);
    return tip;
  }

  function showTip(panel, hit, tip) {
    if (!hit || !tip) return;
    var text = hit.getAttribute("data-tip");
    if (!text) return;
    tip.textContent = text;
    tip.hidden = false;
    var svg = hit.closest("svg");
    if (!svg) return;
    svg.querySelectorAll(".temp-hit.is-active").forEach(function (el) {
      el.classList.remove("is-active");
    });
    hit.classList.add("is-active");
    var rect = hit.getBoundingClientRect();
    var panelRect = panel.getBoundingClientRect();
    tip.style.left = rect.left - panelRect.left + rect.width / 2 + "px";
    tip.style.top = rect.top - panelRect.top + "px";
  }

  function hideTip(panel, tip) {
    if (!tip) tip = panel.querySelector(".temp-tip");
    if (tip) tip.hidden = true;
    panel.querySelectorAll(".temp-hit.is-active").forEach(function (el) {
      el.classList.remove("is-active");
    });
  }

  function hitAtX(scroll, clientX) {
    var hits = scroll.querySelectorAll(".temp-hit");
    if (!hits.length) return null;
    for (var i = 0; i < hits.length; i++) {
      var r = hits[i].getBoundingClientRect();
      if (clientX >= r.left && clientX <= r.right) return hits[i];
    }
    var best = null;
    var bestDist = Infinity;
    for (var j = 0; j < hits.length; j++) {
      var hr = hits[j].getBoundingClientRect();
      var mid = (hr.left + hr.right) / 2;
      var d = Math.abs(clientX - mid);
      if (d < bestDist) {
        bestDist = d;
        best = hits[j];
      }
    }
    return best;
  }

  function wireScroll(panel, scroll) {
    if (!scroll || scroll.getAttribute("data-temp-scroll-wired") === "1") return;
    scroll.setAttribute("data-temp-scroll-wired", "1");
    var tip = ensureTip(panel);

    scroll.addEventListener("pointermove", function (ev) {
      if (ev.pointerType === "mouse" && ev.buttons !== 0) return;
      var hit = hitAtX(scroll, ev.clientX);
      if (hit) showTip(panel, hit, tip);
    });
    scroll.addEventListener("pointerdown", function (ev) {
      var hit = hitAtX(scroll, ev.clientX);
      if (hit) showTip(panel, hit, tip);
    });
    scroll.addEventListener("keydown", function (ev) {
      var active = scroll.querySelector(".temp-hit.is-active");
      var hits = scroll.querySelectorAll(".temp-hit");
      if (!hits.length) return;
      var index = active ? parseInt(active.getAttribute("data-index") || "0", 10) : 0;
      if (ev.key === "Escape") {
        hideTip(panel, tip);
        ev.preventDefault();
        return;
      }
      if (ev.key === "ArrowLeft") {
        index = Math.max(0, index - 1);
        showTip(panel, hits[index], tip);
        ev.preventDefault();
      }
      if (ev.key === "ArrowRight") {
        index = Math.min(hits.length - 1, index + 1);
        showTip(panel, hits[index], tip);
        ev.preventDefault();
      }
    });
  }

  function wirePanel(panel) {
    if (!panel || panel.getAttribute("data-temp-panel-wired") === "1") return;
    panel.setAttribute("data-temp-panel-wired", "1");
    var tablist = panel.querySelector(".temp-window");
    var buttons = panel.querySelectorAll(".temp-window-btn");
    if (tablist && buttons.length) {
      buttons.forEach(function (btn) {
        btn.addEventListener("click", function () {
          activateWindow(panel, btn.getAttribute("data-window"));
        });
      });
      tablist.addEventListener("keydown", function (ev) {
        var list = Array.prototype.slice.call(buttons);
        var current = document.activeElement;
        var idx = list.indexOf(current);
        if (idx < 0 && list.length) idx = list.findIndex(function (b) {
          return b.getAttribute("aria-pressed") === "true";
        });
        if (idx < 0) idx = 0;
        if (ev.key === "ArrowRight") {
          idx = (idx + 1) % list.length;
          activateWindow(panel, list[idx].getAttribute("data-window"));
          ev.preventDefault();
        } else if (ev.key === "ArrowLeft") {
          idx = (idx - 1 + list.length) % list.length;
          activateWindow(panel, list[idx].getAttribute("data-window"));
          ev.preventDefault();
        } else if (ev.key === "Home") {
          activateWindow(panel, list[0].getAttribute("data-window"));
          ev.preventDefault();
        } else if (ev.key === "End") {
          activateWindow(panel, list[list.length - 1].getAttribute("data-window"));
          ev.preventDefault();
        }
      });
    }
    panel.querySelectorAll(".temp-chart-scroll").forEach(function (scroll) {
      wireScroll(panel, scroll);
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && panel.contains(document.activeElement)) {
        hideTip(panel);
      }
    });
  }

  function boot() {
    document.querySelectorAll("[data-temp-panel]").forEach(wirePanel);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
