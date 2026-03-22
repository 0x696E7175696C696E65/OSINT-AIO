# OSINT AIO

**Local analyst workbench** for the public [**OSINT4ALL**](https://start.me/p/L1rEYQ/osint4all?locale=en) collection on Start.me. Snapshot external links into a JSON catalog, browse them in an embedded Chromium viewer with a dark UI, and keep working when the live board is down or slow.

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6%20WebEngine-green.svg)

<p align="center">
  <i>Add a screenshot here after your first run (<code>Viewer</code> + catalog pane).</i>
</p>

## Features

- **Fetch catalog** — Loads Start.me in Qt WebEngine (default profile, no ad block), then a **deep scan** tuned for virtualized bookmark lists:
  - ~**12s** initial settle, **expand** / “show more” clicks, **mid-scan re-expand** (two passes), ~**4.5s** wait after expand.
  - **66 harvest passes**: **64** viewport positions plus **bottom** and **top** anchor passes; ~**3.4s** between scroll steps.
  - **Fractional scrolling** on the document and on inner `overflow` panels (wide boards are mostly horizontal).
  - Before **each** extract pass, a **lazy scroll sweep**: small stepped **`scrollTo` + `WheelEvent`** down/up the page and through the largest inner scrollers, plus **`scrollIntoView`** on widget roots — this mirrors real scrolling so Start.me mounts rows (instant jumps alone often leave ~200 links missing).
  - Extraction: **`a[href]`** and bookmark-style **`data-*`** URLs, walking **open shadow roots**; compact JSON payload; categories from **per-widget** / **preceding-block** titles (not “first heading in the whole column”).
  - Fetch dialog uses a **1280×800** view so more columns lay out on screen.
  - Saves **`data/catalog.json`**; expect **several minutes** for a full OSINT4ALL-sized board.
- **Offline-first** — After a fetch, categories and URLs live on disk; the app does not depend on Start.me for day-to-day browsing.
- **Workbench UI** — Filterable tree, color-coded categories, context menu (open / copy URL), **Enter** to open the focused link.
- **Viewer** — Dedicated browser profile with built-in tracker/ad host blocking; optional extra rules in **`data/blocklist.txt`**.
- **Import / export** — Plain JSON schema for backup, sharing, or hand-editing.

## Quick start

```bash
git clone https://github.com/0x696E7175696C696E65/OSINT-AIO.git
cd OSINT-AIO
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

1. Use **OSINT4ALL live** (toolbar or **File**) to open the board in the viewer if you want.
2. **File → Fetch catalog from web…** to import links — keep the dialog open until it finishes (deep scan; be patient).
3. Pick resources in the left pane; each opens in a **new browser tab** (Welcome stays fixed).

**Shortcut:** `Ctrl+Shift+O` — open OSINT4ALL in the embedded viewer.

## Requirements

- **Python 3.10+** (3.12+ recommended).
- **PyQt6** and **PyQt6-WebEngine** (see `requirements.txt`).
- **Linux (Arch):** if the viewer is blank or crashes, install system Qt WebEngine, e.g. `sudo pacman -S qt6-webengine`.

## How it works

| Piece | Role |
|--------|------|
| **`main.py`** | Application shell: splitter UI, toolbar/menus, WebEngine views, catalog I/O triggers. |
| **`catalog.py`** | Loads/saves the catalog JSON; merges scraped rows into categories. |
| **`harvester.py`** | Fetch dialog: SPA settle, expand + mid-scan expand, fractional board/inner scroll, **lazy sweep** (wheel + incremental scroll) before each harvest pass, **66** passes total, DOM + **`data-*`** in light DOM and **shadow roots**; merge upgrades **Uncategorized** when a later pass finds a real category. |
| **`catalog_widgets.py`** | Left pane: filter field, tree, item delegate (titles + host/path lines). |
| **`network_blocklist.py`** | `QWebEngineUrlRequestInterceptor` for the **browse** profile only (harvest uses the default profile so Start.me still works). |
| **`pages.py`** | Custom `QWebEnginePage` to reduce noisy third-party console spam. |
| **`theme.py`** | Fusion dark palette + Qt Style Sheets. |

**Flow:**

1. **Harvest** uses the **default** `QWebEngineProfile` (no ad interceptor) so the board can load normally.
2. **Browsing** your catalog uses profile **`osint-aio-browse`** with the interceptor and a custom user-agent suffix.
3. Catalog file: **`data/catalog.json`** (created on first successful fetch). If missing, the app falls back to **`data/catalog.seed.json`** for a tiny demo set.

**JSON shape:**

```json
{
  "source_url": "https://start.me/p/L1rEYQ/osint4all?locale=en",
  "fetched_at": "2026-03-22T12:00:00Z",
  "categories": [
    {
      "name": "Category name",
      "links": [{ "title": "Label", "url": "https://..." }]
    }
  ]
}
```

## Configuration

| Path | Purpose |
|------|---------|
| `data/catalog.json` | Your live catalog (gitignored by default). |
| `data/catalog.seed.json` | Small bundled example; safe to commit. |
| `data/blocklist.txt` | Optional extra host suffixes to block in the viewer (one per line, `#` comments). |

**Help → GitHub repository** opens [github.com/0x696E7175696C696E65/OSINT-AIO](https://github.com/0x696E7175696C696E65/OSINT-AIO) (see **`REPO_URL`** in `main.py` if you fork).

## Disclaimer

- **Not affiliated** with Start.me, OSINT4ALL, or linked third-party sites.
- Respect **robots**, **terms of use**, and **local laws**. This tool is for legitimate research and education.
- Start.me layout can change; if fetch quality drops, adjust **`harvester.py`** (`HARVEST_JS`, `VIEWPORT_LAZY_SWEEP_JS`, and pass timings).

## License

MIT — see [LICENSE](LICENSE).
