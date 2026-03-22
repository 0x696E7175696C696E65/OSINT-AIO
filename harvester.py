"""Fetch link catalog by loading Start.me in Qt WebEngine (default profile — no ad block)."""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)

from catalog import Catalog, catalog_from_harvest_rows
from network_blocklist import build_suffix_set, harvest_row_should_drop

ROOT = Path(__file__).resolve().parent

# Collect outbound http(s) links; group by nearest widget/heading. Skip start.me (stay external-only).
HARVEST_JS = r"""
(function() {
  function textClean(s) {
    if (!s) return "";
    return s.replace(/\s+/g, " ").trim();
  }
  function skipUrl(href) {
    if (!href || !/^https?:\/\//i.test(href)) return true;
    try {
      var u = new URL(href);
      if (/\.start\.me$/i.test(u.hostname) || u.hostname === "start.me")
        return true;
    } catch (e) { return true; }
    return false;
  }
  /* Never use ancestor.querySelector(heading) — on Start.me the link sits inside a huge
     column/scroller; the first heading in that subtree is the TOP of the column, so every
     widget in the column wrongly shares one category (~8 total).  Instead: find the title of
     the nearest *preceding* block (previous siblings up the chain) and optional widget root. */
  function goodTitle(raw) {
    var t = textClean(raw);
    if (t.length < 2 || t.length > 200) return "";
    var low = t.toLowerCase();
    if (/^(more|menu|close|share|edit|settings|options|open|add)$/i.test(low)) return "";
    return t;
  }
  function titleFromBlock(root) {
    if (!root || !root.querySelector) return "";
    var selHead = "h1, h2, h3, h4, h5, h6, [role='heading']";
    var scoped = selHead.split(", ").join(", :scope > ");
    var hit = root.querySelector(":scope > " + scoped);
    if (hit) {
      var t = goodTitle(hit.innerText || hit.textContent);
      if (t) return t;
    }
    hit = root.querySelector(
      ":scope > header, :scope > [class*='WidgetHeader'], :scope > [class*='widget-header'], " +
      ":scope > [class*='widget-title'], :scope > [class*='WidgetTitle'], :scope > [class*='group-title']"
    );
    if (hit) {
      var t2 = goodTitle(hit.innerText || hit.textContent);
      if (t2) return t2;
      var inner = hit.querySelector(selHead);
      if (inner) {
        var t3 = goodTitle(inner.innerText || inner.textContent);
        if (t3) return t3;
      }
    }
    var kids = root.children;
    var i, k, lim = Math.min(kids.length, 12);
    for (i = 0; i < lim; i++) {
      k = kids[i];
      if (!k || !k.querySelector) continue;
      var cn = (k.className && String(k.className)) || "";
      var tag = (k.tagName || "").toLowerCase();
      if (/^h[1-6]$/.test(tag) || /header|title|toolbar|heading|caption/i.test(cn)) {
        var h = k.querySelector(selHead) || (/^h[1-6]$/.test(tag) ? k : null);
        if (h) {
          var t4 = goodTitle(h.innerText || h.textContent);
          if (t4) return t4;
        }
      }
    }
    return "";
  }
  function nearestCategoryFromWidget(a) {
    var w = a.closest(
      "[data-widget-id], [data-widget-type], [data-widget-key], [data-testid*='widget'], " +
      "[class*='WidgetView'], [class*='BookmarkWidget'], [class*='BookmarksWidget'], " +
      "[class*='WidgetRoot'], [class*='widget-root'], article, section[aria-label]"
    );
    if (!w) return "";
    var lab = w.getAttribute("aria-label");
    if (lab) {
      var gt = goodTitle(lab);
      if (gt) return gt;
    }
    var t = titleFromBlock(w);
    if (t) return t;
    return "";
  }
  function nearestCategoryFromWalk(a) {
    var el = a;
    var depth = 0;
    while (el && depth < 32) {
      var sib = el.previousElementSibling;
      var steps = 0;
      while (sib && steps < 80) {
        var t = titleFromBlock(sib);
        if (t) return t;
        sib = sib.previousElementSibling;
        steps++;
      }
      el = el.parentElement;
      depth++;
    }
    return "";
  }
  function nearestCategory(a) {
    var t = nearestCategoryFromWidget(a);
    if (t) return t;
    t = nearestCategoryFromWalk(a);
    if (t) return t;
    return "Uncategorized";
  }
  var seen = new Set();
  var out = [];
  function pushLink(el, href, titleGuess) {
    if (skipUrl(href)) return;
    href = href.split("#")[0];
    if (seen.has(href)) return;
    seen.add(href);
    var title = textClean(titleGuess || el.innerText || el.getAttribute("title") ||
      el.getAttribute("aria-label") || "");
    if (!title) title = href;
    /* Short keys (u,t,c) keep JSON small — Qt WebEngine can truncate huge runJavaScript() results. */
    out.push({
      u: href,
      c: nearestCategory(el).slice(0, 200),
      t: title.slice(0, 300)
    });
  }
  function walkShadowRoots(root, fn) {
    fn(root);
    root.querySelectorAll("*").forEach(function(host) {
      if (host.shadowRoot) walkShadowRoots(host.shadowRoot, fn);
    });
  }
  var dataAttrs = ["data-href", "data-url", "data-link", "data-bookmark-url", "data-target-href",
    "data-uri", "data-bookmark", "data-target", "data-external-url"];
  walkShadowRoots(document, function(root) {
    root.querySelectorAll("a[href]").forEach(function(a) {
      pushLink(a, a.href, null);
    });
    dataAttrs.forEach(function(attr) {
      root.querySelectorAll("[" + attr + "]").forEach(function(el) {
        var raw = el.getAttribute(attr);
        if (!raw || !/^https?:\/\//i.test(raw)) return;
        pushLink(el, raw, el.innerText);
      });
    });
  });
  return JSON.stringify(out);
})()
"""

SCROLL_RESET_JS = r"""
(function() {
  window.__osintStep = 0;
  window.scrollTo(0, 0);
  return true;
})()
"""

# Try to expand collapsed rows / “show more” and nudge lazy loaders (capped clicks).
EXPAND_LAZY_JS = r"""
(function() {
  var clicks = 0;
  var maxClicks = 160;
  function clickEl(el) {
    if (!el || clicks >= maxClicks) return;
    try {
      el.click();
      clicks++;
    } catch (e) {}
  }
  document.querySelectorAll('[aria-expanded="false"]').forEach(function(el) {
    var role = (el.getAttribute("role") || "").toLowerCase();
    var tag = (el.tagName || "").toLowerCase();
    if (tag === "button" || role === "button" || tag === "a") clickEl(el);
  });
  var moreRe = /\b(more|show\s*more|view\s*all|load\s*more|see\s*all|expand|show\s*\d+|\+\s*\d+)\b/i;
  document.querySelectorAll("button, a, [role='button']").forEach(function(el) {
    if (clicks >= maxClicks) return;
    var t = (el.innerText || el.textContent || "").trim().slice(0, 48);
    if (t.length < 2 || t.length > 42) return;
    if (moreRe.test(t)) clickEl(el);
  });
  document.querySelectorAll("[class*='expand'], [class*='Expand'], [class*='toggle']").forEach(function(el) {
    if (clicks >= maxClicks) return;
    if (el.offsetParent === null) return;
    var t = (el.innerText || "").trim();
    if (t.length > 0 && t.length < 36) clickEl(el);
  });
  return clicks;
})()
"""

# Scroll nested overflow areas (widgets often use internal scrollers).
INNER_SCROLL_BOTTOM_JS = r"""
(function() {
  var n = 0;
  document.querySelectorAll("*").forEach(function(el) {
    if (n > 900) return;
    var st = window.getComputedStyle(el);
    if (!st) return;
    var oy = st.overflowY;
    if ((oy === "auto" || oy === "scroll") && el.scrollHeight > el.clientHeight + 30) {
      el.scrollTop = el.scrollHeight;
      n++;
    }
  });
  return n;
})()
"""

# Wide dashboards: horizontal columns with overflow-x.
INNER_SCROLL_RIGHT_JS = r"""
(function() {
  var n = 0;
  document.querySelectorAll("*").forEach(function(el) {
    if (n > 500) return;
    var st = window.getComputedStyle(el);
    if (!st) return;
    var ox = st.overflowX;
    if ((ox === "auto" || ox === "scroll") && el.scrollWidth > el.clientWidth + 30) {
      el.scrollLeft = el.scrollWidth;
      n++;
    }
  });
  return n;
})()
"""

# Wheel events sometimes trigger IntersectionObserver / lazy mounts that scrollTop alone misses.
NUDGE_WHEEL_JS = r"""
(function() {
  try {
    window.dispatchEvent(new WheelEvent("wheel", { deltaY: 600, bubbles: true, cancelable: true }));
  } catch (e) {}
  var i = 0;
  document.querySelectorAll("*").forEach(function(el) {
    if (i++ > 80) return;
    var st = window.getComputedStyle(el);
    if (!st) return;
    if ((st.overflowY === "auto" || st.overflowY === "scroll") && el.scrollHeight > el.clientHeight + 40) {
      try {
        el.dispatchEvent(new WheelEvent("wheel", { deltaY: 500, bubbles: true, cancelable: true }));
      } catch (e) {}
    }
  });
  return true;
})()
"""

SCROLL_WINDOW_BOTTOM_JS = r"""
(function() {
  var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight, 1);
  window.scrollTo({ top: h, left: 0, behavior: "instant" });
  return h;
})()
"""

# Incremental scroll + wheel on window and inner overflow nodes (down then up / right then left).
# Start.me virtualizes bookmark rows: instant scrollTo rarely mounts DOM; real scrolling does.
VIEWPORT_LAZY_SWEEP_JS = r"""
(function() {
  function wheel(el, dy, dx) {
    dx = dx || 0;
    try {
      el.dispatchEvent(new WheelEvent("wheel", { deltaY: dy, deltaX: dx, bubbles: true, cancelable: true }));
    } catch (e) {}
  }
  function sweepElY(el) {
    var ch = el.clientHeight || 400;
    var maxT = el.scrollHeight - ch;
    if (maxT <= 0) return;
    var step = Math.max(48, Math.floor(ch * 0.32));
    var t = 0;
    var g = 0;
    while (t <= maxT && g++ < 220) {
      el.scrollTop = t;
      wheel(el, step, 0);
      t += step;
    }
    el.scrollTop = maxT;
    g = 0;
    while (t >= 0 && g++ < 220) {
      el.scrollTop = t;
      wheel(el, -step, 0);
      t -= step;
    }
    el.scrollTop = 0;
  }
  function sweepElX(el) {
    var cw = el.clientWidth || 400;
    var maxL = el.scrollWidth - cw;
    if (maxL <= 0) return;
    var step = Math.max(64, Math.floor(cw * 0.28));
    var x = 0;
    var g = 0;
    while (x <= maxL && g++ < 220) {
      el.scrollLeft = x;
      wheel(el, 0, step);
      x += step;
    }
    el.scrollLeft = maxL;
    g = 0;
    while (x >= 0 && g++ < 220) {
      el.scrollLeft = x;
      wheel(el, 0, -step);
      x -= step;
    }
    el.scrollLeft = 0;
  }
  var de = document.documentElement;
  var vh = window.innerHeight || 720;
  var vw = window.innerWidth || 1200;
  var maxY = Math.max(0, de.scrollHeight - vh);
  var stepY = Math.max(56, Math.floor(vh * 0.26));
  var y = 0;
  var g = 0;
  while (y <= maxY && g++ < 220) {
    window.scrollTo(0, y);
    wheel(de, stepY, 0);
    wheel(document.body, stepY, 0);
    y += stepY;
  }
  window.scrollTo(0, maxY);
  g = 0;
  y = maxY;
  while (y >= 0 && g++ < 220) {
    window.scrollTo(0, y);
    wheel(de, -stepY, 0);
    wheel(document.body, -stepY, 0);
    y -= stepY;
  }
  window.scrollTo(0, 0);
  var maxX = Math.max(0, de.scrollWidth - vw);
  var stepX = Math.max(72, Math.floor(vw * 0.26));
  g = 0;
  var x = 0;
  var sy = window.scrollY || 0;
  while (x <= maxX && g++ < 220) {
    window.scrollTo(x, sy);
    wheel(de, 0, stepX);
    x += stepX;
  }
  window.scrollTo(maxX, sy);
  g = 0;
  x = maxX;
  while (x >= 0 && g++ < 220) {
    window.scrollTo(x, sy);
    wheel(de, 0, -stepX);
    x -= stepX;
  }
  window.scrollTo(0, 0);
  var cand = [];
  document.querySelectorAll("*").forEach(function(el) {
    var st = window.getComputedStyle(el);
    if (!st) return;
    if ((st.overflowY === "auto" || st.overflowY === "scroll") && el.scrollHeight > el.clientHeight + 28) {
      cand.push({ el: el, area: el.clientWidth * Math.min(el.scrollHeight, 12000) });
    }
  });
  cand.sort(function(a, b) { return b.area - a.area; });
  cand.slice(0, 55).forEach(function(c) { sweepElY(c.el); });
  cand.length = 0;
  document.querySelectorAll("*").forEach(function(el) {
    var st = window.getComputedStyle(el);
    if (!st) return;
    if ((st.overflowX === "auto" || st.overflowX === "scroll") && el.scrollWidth > el.clientWidth + 28) {
      cand.push({ el: el, area: el.clientHeight * Math.min(el.scrollWidth, 12000) });
    }
  });
  cand.sort(function(a, b) { return b.area - a.area; });
  cand.slice(0, 42).forEach(function(c) { sweepElX(c.el); });
  var wi = 0;
  document.querySelectorAll("[data-widget-id], [data-widget-type]").forEach(function(w) {
    if (wi++ > 140) return;
    try {
      w.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" });
    } catch (e) {}
  });
  return true;
})()
"""


def _js_board_and_inner_overflow_fraction(step: int, linear_total: int) -> str:
    """Scroll main horizontal axis + every inner scroller by fraction — Start.me is wide, not tall."""
    denom = max(int(linear_total) - 1, 1)
    s = max(0, int(step))
    return f"""
(function() {{
  var ratio = Math.min(1, Math.max(0, {s} / {denom}));
  var n = 0;
  var de = document.documentElement;
  var body = document.body;
  var dx = de.scrollWidth - de.clientWidth;
  if (dx > 0) {{
    de.scrollLeft = Math.floor(ratio * dx);
    body.scrollLeft = Math.floor(ratio * dx);
    n++;
  }}
  var dy = de.scrollHeight - de.clientHeight;
  if (dy > 0) {{
    /* Complement window.scrollTo — some layouts only move the scrolling element, not the window */
    de.scrollTop = Math.floor(ratio * dy);
    body.scrollTop = Math.floor(ratio * dy);
    n++;
  }}
  document.querySelectorAll("*").forEach(function(el) {{
    if (n > 1600) return;
    var st = window.getComputedStyle(el);
    if (!st) return;
    if ((st.overflowY === "auto" || st.overflowY === "scroll") && el.scrollHeight > el.clientHeight + 20) {{
      var my = el.scrollHeight - el.clientHeight;
      el.scrollTop = Math.floor(ratio * my);
      n++;
    }}
    if ((st.overflowX === "auto" || st.overflowX === "scroll") && el.scrollWidth > el.clientWidth + 20) {{
      var mx = el.scrollWidth - el.clientWidth;
      el.scrollLeft = Math.floor(ratio * mx);
      n++;
    }}
  }});
  return n;
}})()
"""


class HarvestDialog(QDialog):
    """
    Uses the default QWebEngineProfile (no request interceptor) so Start.me widgets still run.
    """

    # Many viewport positions + bottom/top anchors so lazy widgets and inner scrollers flush.
    _LINEAR_PASSES = 64
    _ANCHOR_EXTRA_PASSES = 2
    _DELAY_AFTER_SCROLL_MS = 3400
    _DELAY_AFTER_EXPAND_MS = 4500
    # Re-expand twice mid-scan — lazy columns often mount after first wave.
    _MID_SCAN_EXPAND_PASSES = frozenset({22, 44})

    def __init__(
        self,
        source_url: str,
        parent=None,
        settle_ms: int = 12000,
    ):
        super().__init__(parent)
        self.setWindowTitle("Fetching catalog from web…")
        # Wider view so Start.me lays out more columns (narrow dialogs hide off-screen widgets).
        self.resize(1280, 800)
        self._source_url = source_url
        self._settle_ms = settle_ms
        self._catalog: Catalog | None = None
        self._error: str | None = None
        self._load_ok: bool | None = None
        self._merged: dict[str, dict] = {}
        self._suffixes = build_suffix_set(ROOT)
        self._pass_index: int = 0
        self._total_passes = self._LINEAR_PASSES + self._ANCHOR_EXTRA_PASSES
        self._harvest_json_errors: int = 0

        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._after_settle)

        from PyQt6.QtWebEngineWidgets import QWebEngineView

        self._status = QLabel("Loading page…")
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._view = QWebEngineView(self)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self._status)
        lay.addWidget(self._bar)
        lay.addWidget(self._view, 1)
        lay.addWidget(buttons)

        self._view.loadFinished.connect(self._on_load_finished)

    def catalog(self) -> Catalog | None:
        return self._catalog

    def error_message(self) -> str | None:
        return self._error

    def start(self) -> None:
        self._merged.clear()
        self._view.load(QUrl(self._source_url))

    def _on_load_finished(self, ok: bool) -> None:
        self._load_ok = ok
        if not ok:
            self._error = (
                "The page failed to load. Check network, VPN, or TLS (wrong clock, proxy, or "
                "missing CA). Try again in a normal desktop browser first."
            )
            self._status.setText(self._error)
            self._bar.setRange(0, 1)
            self._bar.setValue(1)
            return
        self._status.setText(
            f"Waiting {self._settle_ms // 1000}s for Start.me to finish rendering…"
        )
        self._settle_timer.stop()
        self._settle_timer.start(self._settle_ms)

    def _after_settle(self) -> None:
        if self._load_ok is False:
            return
        self._bar.setRange(0, self._total_passes)
        self._bar.setValue(0)
        self._pass_index = 0
        self._status.setText("Expanding sections & scrolling inner panels (slow pass)…")

        def after_expand(_clicks=None) -> None:
            self._status.setText(
                "Waiting for lazy-loaded widgets… (this can take a few seconds)"
            )
            QTimer.singleShot(self._DELAY_AFTER_EXPAND_MS, self._start_linear_passes)

        def after_reset(_res=None) -> None:
            self._view.page().runJavaScript(EXPAND_LAZY_JS, after_expand)

        self._view.page().runJavaScript(SCROLL_RESET_JS, after_reset)

    def _start_linear_passes(self) -> None:
        if self._load_ok is False:
            return
        self._status.setText(
            f"Deep scan: {self._total_passes} harvest passes (slower, more complete)…"
        )

        def kickoff() -> None:
            self._run_harvest_pass(0)

        self._view.page().runJavaScript(
            SCROLL_RESET_JS, lambda _r: QTimer.singleShot(500, kickoff)
        )

    @staticmethod
    def _js_scroll_viewport_fraction(step: int, linear_total: int) -> str:
        denom = max(linear_total - 1, 1)
        return (
            "(function () {\n"
            "  var h = Math.max(document.body.scrollHeight, "
            "document.documentElement.scrollHeight, "
            "document.documentElement.offsetHeight, 1);\n"
            f"  var step = {int(step)};\n"
            f"  var denom = {denom};\n"
            f"  var lt = {int(linear_total)};\n"
            "  var y = (step >= lt - 1) ? h : Math.floor((h * step) / denom);\n"
            "  window.scrollTo({ top: y, left: 0, behavior: 'instant' });\n"
            "  return y;\n"
            "})()\n"
        )

    def _prepare_viewport_before_pass(self, p: int, callback) -> None:
        """Scroll / expand inner panels so pass `p` sees newly mounted links."""
        L = self._LINEAR_PASSES
        delay = self._DELAY_AFTER_SCROLL_MS

        if p <= 0:
            QTimer.singleShot(350, callback)
            return

        if p < L:

            def after_nudge(__=None) -> None:
                QTimer.singleShot(delay, callback)

            def after_board_inner(_rr=None) -> None:
                # Fraction JS already moves inner X/Y; max INNER_SCROLL_RIGHT would wipe horizontal progress.
                self._view.page().runJavaScript(NUDGE_WHEEL_JS, after_nudge)

            def after_scroll(_r=None) -> None:
                frac = _js_board_and_inner_overflow_fraction(p, L)
                self._view.page().runJavaScript(frac, after_board_inner)

            js = self._js_scroll_viewport_fraction(p, L)
            self._view.page().runJavaScript(js, after_scroll)
            return

        if p == L:

            def after_bottom(__=None) -> None:
                QTimer.singleShot(delay, callback)

            def inner_then_bottom(_x=None) -> None:
                self._view.page().runJavaScript(
                    INNER_SCROLL_RIGHT_JS,
                    lambda __: self._view.page().runJavaScript(
                        NUDGE_WHEEL_JS,
                        lambda ___: self._view.page().runJavaScript(
                            SCROLL_WINDOW_BOTTOM_JS, after_bottom
                        ),
                    ),
                )

            self._view.page().runJavaScript(
                INNER_SCROLL_BOTTOM_JS, inner_then_bottom
            )
            return

        # p == L + 1 — final pass: back to top for headers / first widgets
        self._view.page().runJavaScript(
            SCROLL_RESET_JS, lambda _r: QTimer.singleShot(delay, callback)
        )

    def _reapply_viewport_for_harvest_pass(self, p: int, callback) -> None:
        """Re-apply scroll position after VIEWPORT_LAZY_SWEEP_JS (sweep resets ranges). Mirrors _prepare logic."""
        L = self._LINEAR_PASSES
        if p < L:

            def after_board(_=None) -> None:
                callback()

            def after_y(_=None) -> None:
                frac = _js_board_and_inner_overflow_fraction(p, L)
                self._view.page().runJavaScript(frac, after_board)

            js = self._js_scroll_viewport_fraction(p, L)
            self._view.page().runJavaScript(js, after_y)
            return

        if p == L:

            def after_b(_=None) -> None:
                callback()

            def inner_then(_=None) -> None:
                self._view.page().runJavaScript(
                    NUDGE_WHEEL_JS,
                    lambda __: self._view.page().runJavaScript(SCROLL_WINDOW_BOTTOM_JS, after_b),
                )

            self._view.page().runJavaScript(
                INNER_SCROLL_BOTTOM_JS,
                lambda __: self._view.page().runJavaScript(INNER_SCROLL_RIGHT_JS, inner_then),
            )
            return

        def after_frac(_=None) -> None:
            callback()

        self._view.page().runJavaScript(
            SCROLL_RESET_JS,
            lambda _r: self._view.page().runJavaScript(
                _js_board_and_inner_overflow_fraction(0, L), after_frac
            ),
        )

    def _run_harvest_pass(self, p: int) -> None:
        if self._load_ok is False:
            return
        self._pass_index = p
        total = self._total_passes
        self._status.setText(
            f"Lazy scroll sweep (virtual lists)… pass {p + 1} of {total} "
            f"— {len(self._merged)} URLs so far"
        )
        self._bar.setValue(min(p, total - 1))

        def on_harvest(res) -> None:
            self._merge_js_result(res)
            if p >= total - 1:
                self._bar.setValue(total)
                self._finish_from_merged()
                return

            def run_next() -> None:
                self._run_harvest_pass(p + 1)

            next_p = p + 1
            if p in self._MID_SCAN_EXPAND_PASSES:
                self._status.setText(
                    "Mid-scan: re-expanding sections & lazy columns…"
                )

                def after_mid_expand(_clicks=None) -> None:
                    QTimer.singleShot(3400, lambda: self._prepare_viewport_before_pass(next_p, run_next))

                self._view.page().runJavaScript(EXPAND_LAZY_JS, after_mid_expand)
            else:
                self._prepare_viewport_before_pass(next_p, run_next)

        def run_harvest(_=None) -> None:
            self._status.setText(
                f"Extracting links… pass {p + 1} of {total} "
                f"({len(self._merged)} unique URLs collected)"
            )
            self._view.page().runJavaScript(HARVEST_JS, on_harvest)

        def after_reapply(_=None) -> None:
            QTimer.singleShot(400, run_harvest)

        def after_sweep(_=None) -> None:
            self._reapply_viewport_for_harvest_pass(p, after_reapply)

        self._view.page().runJavaScript(VIEWPORT_LAZY_SWEEP_JS, after_sweep)

    @staticmethod
    def _prefer_row_for_url(new: dict, old: dict) -> dict:
        """Later passes may see the link under its real widget header; upgrade Uncategorized."""
        n = (new.get("category") or "").strip().lower()
        o = (old.get("category") or "").strip().lower()
        n_ok = bool(n) and n != "uncategorized"
        o_ok = bool(o) and o != "uncategorized"
        if n_ok and not o_ok:
            return new
        if o_ok and not n_ok:
            return old
        return old

    @staticmethod
    def _normalize_harvest_row(r: dict) -> dict | None:
        """Map compact {u,t,c} from JS to full rows for catalog_from_harvest_rows."""
        u = r.get("u") or r.get("url")
        if not u or not isinstance(u, str):
            return None
        u = u.split("#", 0)[0].strip()
        if not u:
            return None
        title = r.get("t") if r.get("t") is not None else r.get("title")
        cat = r.get("c") if r.get("c") is not None else r.get("category")
        return {
            "url": u,
            "title": (title if isinstance(title, str) else u)[:500],
            "category": (cat if isinstance(cat, str) else "Uncategorized")[:220],
        }

    def _merge_js_result(self, res) -> None:
        if res is None:
            self._harvest_json_errors += 1
            return
        raw = str(res).strip()
        if not raw or raw == "null":
            self._harvest_json_errors += 1
            return
        try:
            rows = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            self._harvest_json_errors += 1
            return
        if not isinstance(rows, list):
            self._harvest_json_errors += 1
            return
        for r in rows:
            if not isinstance(r, dict):
                continue
            row = self._normalize_harvest_row(r)
            if row is None:
                continue
            u = row["url"]
            if u not in self._merged:
                self._merged[u] = row
            else:
                self._merged[u] = self._prefer_row_for_url(row, self._merged[u])

    def _finish_from_merged(self) -> None:
        rows = list(self._merged.values())
        filtered = [
            r
            for r in rows
            if isinstance(r, dict)
            and isinstance(r.get("url"), str)
            and not harvest_row_should_drop(r["url"], self._suffixes)
        ]
        if not filtered:
            self._error = (
                f"No usable external links after {len(rows)} raw hits "
                f"(all filtered as ads/trackers or empty). "
                "Try again, or Import a JSON catalog."
            )
            self._status.setText(self._error)
            return
        cat = catalog_from_harvest_rows(filtered, self._source_url)
        if cat.link_count() == 0:
            self._error = "Catalog built empty after filtering — unexpected."
            self._status.setText(self._error)
            return
        dropped = len(rows) - len(filtered)
        self._catalog = cat
        msg = (
            f"Done — {cat.link_count()} links in {len(cat.categories)} categories"
            + (f" ({dropped} ad/tracker URLs dropped)" if dropped else "")
        )
        if self._harvest_json_errors > 0:
            msg += f" — warning: {self._harvest_json_errors} harvest JSON parse miss(es); try fetch again if count seems low."
        self._status.setText(msg)
        self.accept()


def run_harvest_dialog(
    source_url: str,
    parent=None,
    settle_ms: int = 12000,
) -> tuple[Catalog | None, str | None]:
    dlg = HarvestDialog(source_url, parent=parent, settle_ms=settle_ms)
    dlg.start()
    code = dlg.exec()
    err = dlg.error_message()
    if code == QDialog.DialogCode.Accepted:
        return dlg.catalog(), None
    return None, err
