#!/usr/bin/env python3
"""
OSINT AIO — local catalog browser for the OSINT4ALL link collection.
Fetches links once via embedded browser (Start.me + Cloudflare), then works offline.
"""

# Bump for releases; shown in About and app metadata.
__version__ = "1.0.0"
# Set to your repo after publishing (Help → GitHub opens this).
REPO_URL = "https://github.com/0x696E7175696C696E65/OSINT-AIO"

import os
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from PyQt6.QtCore import QCoreApplication, QLocale, QUrl, Qt
from PyQt6.QtGui import QAction, QDesktopServices, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from catalog import Catalog, default_catalog_path, load_catalog, save_catalog
from catalog_widgets import ROLE_URL, CatalogSidePanel
from harvester import run_harvest_dialog
from network_blocklist import build_interceptor, build_suffix_set, url_should_block
from theme import apply_analyst_theme

SOURCE_PAGE_URL = "https://start.me/p/L1rEYQ/osint4all?locale=en"
ROOT = Path(__file__).resolve().parent
CATALOG_PATH = default_catalog_path(ROOT)
SEED_PATH = ROOT / "data" / "catalog.seed.json"
# Paths shown in dialogs (repo-relative after clone); I/O still uses CATALOG_PATH above.
CATALOG_DISPLAY_PATH = "data/catalog.json"
SEED_DISPLAY_PATH = "data/catalog.seed.json"

WELCOME_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"/>
<style>
body { font-family: 'Segoe UI', system-ui, sans-serif; max-width: 44rem; margin: 3rem auto;
  padding: 0 1.25rem; color: #e8eaed; background: #1a1d23; line-height: 1.55; }
h1 { font-weight: 600; letter-spacing: -0.02em; color: #fff; }
p { color: #b8c0cc; }
code { background: #2a2f38; padding: 0.15em 0.4em; border-radius: 4px; color: #8ec5ff; }
kbd { border: 1px solid #3d444f; padding: 0.1em 0.45em; border-radius: 4px; }
ul { color: #b8c0cc; }
</style></head><body>
<h1>Analyst workbench</h1>
<p><b>Resources</b> — pick an entry in the catalog pane to load it in this viewer.
Use the filter field to narrow by title, hostname, or category. Sites always open in a new tab.</p>
<ul>
<li><b>OSINT4ALL live</b> — toolbar or <kbd>File</kbd> opens the Start.me board in a <b>new tab</b>;
then run <b>Fetch catalog from web</b> to snapshot links into <code>data/catalog.json</code>.</li>
<li><b>Catalog links</b> — each resource opens in its own tab; this <b>Welcome</b> tab stays put.</li>
<li><b>Context menu</b> — right-click a resource to copy the URL or open in your system browser.</li>
<li><b>Keyboard</b> — <kbd>Enter</kbd> opens the focused resource.</li>
</ul>
<p style="font-size:0.9em;color:#8b919a;">Embedded viewer applies tracker/ad request blocking on a dedicated profile.</p>
</body></html>"""


def _fix_fontconfig_env() -> None:
    if os.environ.get("FONTCONFIG_FILE") == "":
        del os.environ["FONTCONFIG_FILE"]
    elif not os.environ.get("FONTCONFIG_FILE"):
        fc = Path("/etc/fonts/fonts.conf")
        if fc.is_file():
            os.environ["FONTCONFIG_FILE"] = str(fc)


def _quiet_chromium_stderr() -> None:
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
    if "--log-level=3" not in flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --log-level=3").strip()


def _webengine_import_error() -> Optional[str]:
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401

        return None
    except ImportError as e:
        return str(e) if str(e) else repr(e)


def _webengine_available() -> bool:
    return _webengine_import_error() is None


def _load_initial_catalog() -> Catalog:
    cat = load_catalog(CATALOG_PATH)
    if cat is not None and cat.link_count() > 0:
        return cat
    seed = load_catalog(SEED_PATH)
    if seed is not None and seed.link_count() > 0:
        return seed
    return Catalog(source_url=SOURCE_PAGE_URL, fetched_at="", categories=[])


class OsintAioWindow(QMainWindow):
    def __init__(self, browse_profile=None):
        super().__init__()
        self.setWindowTitle("OSINT AIO · Analyst Workbench")
        self.resize(1400, 880)
        self._catalog = _load_initial_catalog()
        self._last_pick_url: Optional[str] = None
        self._browse_profile = browse_profile
        self._block_suffixes = build_suffix_set(ROOT)

        err = _webengine_import_error()
        if err is not None:
            self._show_webengine_missing(err)
            return

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)

        split = QSplitter(Qt.Orientation.Horizontal)
        self._catalog_panel = CatalogSidePanel()
        tree = self._catalog_panel.tree()
        tree.setMinimumWidth(340)
        tree.currentItemChanged.connect(self._on_tree_pick)
        tree.link_open_requested.connect(self._on_link_open_requested)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._catalog_context_menu)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)

        self._welcome_view = self._make_welcome_view()
        self._welcome_view.setHtml(WELCOME_HTML, QUrl("about:blank"))
        self.tabs.addTab(self._welcome_view, "Welcome")
        self.tabs.tabBar().setTabButton(0, self.tabs.tabBar().ButtonPosition.RightSide, None)

        rv.addWidget(self.tabs)
        split.addWidget(self._catalog_panel)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        outer.addWidget(split)

        self.setCentralWidget(central)
        self._populate_tree(self._catalog)
        self._build_toolbar()
        self._build_menu()
        self._build_status()
        self._wire_web_view(self._welcome_view)

    def _make_welcome_view(self):
        from PyQt6.QtWebEngineWidgets import QWebEngineView

        from pages import WelcomeHomePage

        v = QWebEngineView()
        if self._browse_profile is not None:
            v.setPage(WelcomeHomePage(self._browse_profile, v))
        return v

    def _make_browse_view(self):
        from PyQt6.QtWebEngineWidgets import QWebEngineView

        from pages import QuietBrowsePage

        v = QWebEngineView()
        if self._browse_profile is not None:
            page = QuietBrowsePage(self._browse_profile, v)
            v.setPage(page)
        return v

    def _open_site_in_new_tab(self, url: QUrl, tab_title: str | None = None) -> None:
        view = self._make_browse_view()
        if tab_title:
            label = tab_title[:40] + ("…" if len(tab_title) > 40 else "")
        else:
            label = self._tab_label_for_url(url)
        idx = self.tabs.addTab(view, label)
        self.tabs.setCurrentIndex(idx)
        self._wire_web_view(view)
        view.load(url)

    def _open_catalog_url(self, url: str, title: str | None = None) -> None:
        self._last_pick_url = url
        self._open_site_in_new_tab(QUrl(url), title)

    def _on_link_open_requested(self, url: str) -> None:
        it = self._catalog_panel.tree().currentItem()
        t = it.text(0) if it is not None else None
        self._open_catalog_url(url, t)

    def _populate_tree(self, catalog: Catalog) -> None:
        self._catalog_panel.populate(catalog)
        n = catalog.link_count()
        c = len(catalog.categories)
        if n == 0:
            self.setWindowTitle("OSINT AIO · Analyst Workbench")
            self.statusBar().showMessage("No catalog loaded — fetch or import to begin.")
        else:
            self.setWindowTitle(f"OSINT AIO · {n} resources · {c} groups")
            self.statusBar().showMessage(
                f"Catalog: {n} links, {c} categories"
                + (f" · snapshot {catalog.fetched_at}" if catalog.fetched_at else "")
            )

    def _on_tree_pick(self, current, _prev) -> None:
        if current is None:
            return
        url = current.data(0, ROLE_URL)
        if not url:
            return
        self._open_catalog_url(str(url), current.text(0))

    def _catalog_context_menu(self, pos) -> None:
        tree = self._catalog_panel.tree()
        item = tree.itemAt(pos)
        if item is None:
            return
        url = item.data(0, ROLE_URL)
        if not url:
            return
        menu = QMenu(self)
        menu.addAction(
            "Open in new tab",
            lambda u=str(url), t=item.text(0): self._open_catalog_url(u, t),
        )
        menu.addAction(
            "Open in system browser",
            lambda u=str(url): QDesktopServices.openUrl(QUrl(u)),
        )
        menu.addSeparator()
        menu.addAction(
            "Copy URL",
            lambda u=str(url): QApplication.clipboard().setText(u),
        )
        vp = tree.viewport()
        menu.exec(vp.mapToGlobal(pos))

    def _open_osint4all_embedded(self) -> None:
        self._open_site_in_new_tab(QUrl(SOURCE_PAGE_URL), "OSINT4ALL live")
        self.statusBar().showMessage(
            "OSINT4ALL (live) — when the board has loaded, use File → Fetch catalog from web to snapshot links.",
            10000,
        )

    def _open_osint4all_external(self) -> None:
        QDesktopServices.openUrl(QUrl(SOURCE_PAGE_URL))

    def _show_webengine_missing(self, import_err: str):
        venv_py = ROOT / ".venv" / "bin" / "python"
        hint = (
            "PyQt6-WebEngine did not load (wrong Python or missing package).\n\n"
            f"Python running this app:\n{sys.executable}\n\n"
            f"pip error: {import_err}\n\n"
            "Fix — use the project venv (not system python):\n"
            f"  {venv_py}\n"
            "  or:  source .venv/bin/activate && python main.py\n\n"
            "Then install:\n"
            "  .venv/bin/pip install -r requirements.txt\n\n"
            "In PyCharm: Settings → Project → Python Interpreter → "
            "point to .venv/bin/python\n\n"
            "Arch: if import works but the window is blank/crashes, also install:\n"
            "  sudo pacman -S qt6-webengine"
        )
        msg = QLabel(hint)
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(msg)

    def _build_toolbar(self):
        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)

        act_back = QAction("← Back", self)
        act_back.triggered.connect(lambda: self._current_view().back())
        tb.addAction(act_back)

        act_fwd = QAction("Forward →", self)
        act_fwd.triggered.connect(lambda: self._current_view().forward())
        tb.addAction(act_fwd)

        act_reload = QAction("Reload", self)
        act_reload.triggered.connect(lambda: self._current_view().reload())
        tb.addAction(act_reload)

        tb.addSeparator()

        act_live = QAction("OSINT4ALL live", self)
        act_live.setToolTip(
            "Open the live OSINT4ALL Start.me page in a new tab (then File → Fetch catalog from web)."
        )
        act_live.triggered.connect(self._open_osint4all_embedded)
        act_live.setShortcut(QKeySequence("Ctrl+Shift+O"))
        tb.addAction(act_live)

        act_fetch = QAction("Fetch catalog", self)
        act_fetch.setToolTip(
            "Deep multi-pass scrape (many scroll positions, ~minutes). Saves data/catalog.json"
        )
        act_fetch.triggered.connect(self._action_fetch_catalog)
        tb.addAction(act_fetch)

        tb.addSeparator()

        act_external = QAction("Open in browser", self)
        act_external.setToolTip("Open the current viewer URL in the default system browser")
        act_external.triggered.connect(self._open_current_external)
        tb.addAction(act_external)

        self._act_back = act_back
        self._act_fwd = act_fwd

    def _build_menu(self):
        m_file = self.menuBar().addMenu("&File")
        m_live = QAction("Open OSINT4ALL in &new tab", self)
        m_live.triggered.connect(self._open_osint4all_embedded)
        m_live.setShortcut(QKeySequence("Ctrl+Shift+O"))
        m_file.addAction(m_live)
        m_live_ext = QAction("Open OSINT4ALL in &system browser", self)
        m_live_ext.triggered.connect(self._open_osint4all_external)
        m_file.addSeparator()
        m_file.addAction("Fetch catalog from web…", self._action_fetch_catalog)
        m_file.addSeparator()
        m_file.addAction("Import catalog JSON…", self._action_import_json)
        m_file.addAction("Export catalog JSON…", self._action_export_json)
        m_file.addSeparator()
        m_file.addAction("Exit", self.close)

        m_view = self.menuBar().addMenu("&View")
        m_view.addAction("Reload page", lambda: self._current_view().reload())

        m_help = self.menuBar().addMenu("&Help")
        act_gh = QAction("GitHub repository", self)
        act_gh.triggered.connect(self._open_repo_url)
        m_help.addAction(act_gh)
        m_help.addSeparator()
        m_help.addAction("About OSINT AIO", self._about)

    def _build_status(self):
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

    def _current_view(self):
        from PyQt6.QtWebEngineWidgets import QWebEngineView

        w = self.tabs.currentWidget()
        if isinstance(w, QWebEngineView):
            return w
        return self._welcome_view

    def _open_current_external(self) -> None:
        url = self._current_view().url()
        if url.isValid() and url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)

    def _action_fetch_catalog(self) -> None:
        if not _webengine_available():
            QMessageBox.warning(self, "WebEngine", "Qt WebEngine is not available.")
            return
        cat, err = run_harvest_dialog(SOURCE_PAGE_URL, parent=self)
        if cat is None:
            if err:
                QMessageBox.warning(self, "Fetch catalog", err)
            return
        try:
            save_catalog(cat, CATALOG_PATH)
        except OSError as e:
            QMessageBox.critical(self, "Fetch catalog", f"Could not save catalog:\n{e}")
            return
        self._catalog = cat
        self._populate_tree(cat)
        QMessageBox.information(
            self,
            "Catalog updated",
            f"Saved {cat.link_count()} links to:\n{CATALOG_DISPLAY_PATH}\n"
            f"(under your project folder)",
        )

    def _action_import_json(self) -> None:
        path, _f = QFileDialog.getOpenFileName(
            self,
            "Import catalog JSON",
            str(ROOT),
            "JSON (*.json);;All files (*)",
        )
        if not path:
            return
        p = Path(path)
        cat = load_catalog(p)
        if cat is None:
            QMessageBox.warning(
                self,
                "Import",
                "Could not read that file. Expected JSON with:\n"
                '  "source_url", "fetched_at", "categories": [\n'
                '    { "name": "…", "links": [ { "title", "url" } ] }\n  ]',
            )
            return
        if cat.link_count() == 0:
            QMessageBox.warning(
                self,
                "Import",
                "The file parsed but contains no valid http(s) links.",
            )
            return
        try:
            save_catalog(cat, CATALOG_PATH)
        except OSError as e:
            QMessageBox.critical(self, "Import", str(e))
            return
        self._catalog = cat
        self._populate_tree(cat)

    def _action_export_json(self) -> None:
        path, _f = QFileDialog.getSaveFileName(
            self,
            "Export catalog JSON",
            str(ROOT / "catalog-export.json"),
            "JSON (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            save_catalog(self._catalog, Path(path))
        except OSError as e:
            QMessageBox.critical(self, "Export", str(e))
            return
        QMessageBox.information(self, "Export", f"Wrote:\n{path}")

    def _on_load_progress_view(self, view, pct: int):
        if self.tabs.currentWidget() is view:
            self.statusBar().showMessage(f"Loading… {pct}%")

    def _on_load_finished_view(self, view):
        if self.tabs.currentWidget() is view:
            self.statusBar().showMessage(view.url().toString())

    def _on_tab_title_changed(self, view, title: str):
        idx = self.tabs.indexOf(view)
        if idx == 0:
            self.tabs.setTabText(0, "Welcome")
            return
        if idx >= 0 and title:
            self.tabs.setTabText(idx, title[:32] + ("…" if len(title) > 32 else ""))

    def _on_link_hovered(self, url: str):
        if url:
            self.statusBar().showMessage(url)
        else:
            u = self._current_view().url()
            self.statusBar().showMessage(u.toString() if u.isValid() else "")

    def _on_new_window(self, request):
        req_url = request.requestedUrl().toString()
        if url_should_block(req_url, self._block_suffixes):
            self.statusBar().showMessage("Blocked ad/tracker popup (not opened).", 4000)
            return

        view = self._make_browse_view()
        label = self._tab_label_for_url(request.requestedUrl())
        idx = self.tabs.addTab(view, label)
        self.tabs.setCurrentIndex(idx)
        self._wire_web_view(view)
        request.openIn(view)

    def _wire_web_view(self, view):
        from PyQt6.QtWebEngineCore import QWebEnginePage

        page = view.page()
        view.urlChanged.connect(lambda u, v=view: self._tab_url_line(v, u))
        view.loadProgress.connect(lambda p, v=view: self._on_load_progress_view(v, p))
        view.loadFinished.connect(
            lambda _ok, v=view: self._on_load_finished_view(v)
        )
        view.titleChanged.connect(lambda t, v=view: self._on_tab_title_changed(v, t))
        page.linkHovered.connect(self._on_link_hovered)
        page.newWindowRequested.connect(self._on_new_window)
        page.featurePermissionRequested.connect(
            lambda origin, feat, p=page: p.setFeaturePermission(
                origin,
                feat,
                QWebEnginePage.PermissionPolicy.PermissionDeniedByUser,
            )
        )

    def _tab_url_line(self, view, url: QUrl):
        if self.tabs.currentWidget() is view and url.isValid():
            self.statusBar().showMessage(url.toString())

    def _tab_label_for_url(self, url: QUrl) -> str:
        host = urlparse(url.toString()).hostname or "New tab"
        return host[:24] + ("…" if len(host) > 24 else "")

    def _close_tab(self, index: int):
        if index == 0:
            return
        self.tabs.removeTab(index)

    def _open_repo_url(self) -> None:
        QDesktopServices.openUrl(QUrl(REPO_URL))

    def _about(self) -> None:
        QMessageBox.about(
            self,
            f"About OSINT AIO {__version__}",
            f"<p style='margin-top:0'><b style='font-size:14pt'>OSINT AIO</b><br/>"
            f"<span style='color:#8b919a'>Version {__version__}</span></p>"
            "<p>Desktop <b>analyst workbench</b> for the public "
            "<b>OSINT4ALL</b> bookmark collection on Start.me. Keeps a <b>local JSON catalog</b> "
            "and opens resources in an embedded Chromium viewer—so you can keep working if the "
            "board is slow or unavailable.</p>"
            "<p><b>Highlights</b></p>"
            "<ul style='margin-left:1.2em;padding-left:0'>"
            "<li>Fetch / refresh catalog via in-app browser (Cloudflare-friendly)</li>"
            "<li>Filterable, color-coded category tree</li>"
            "<li>Tracker / ad request blocking + quieter console in the viewer</li>"
            "<li>Import / export catalog JSON</li>"
            "</ul>"
            f"<p><b>Source board</b><br/><a href=\"{SOURCE_PAGE_URL}\">{SOURCE_PAGE_URL}</a></p>"
            f"<p><b>Catalog file</b> (in the cloned repo)<br/>"
            f"<code style='font-size:10pt'>{CATALOG_DISPLAY_PATH}</code><br/>"
            f"<span style='color:#8b919a;font-size:9pt'>Also: <code>{SEED_DISPLAY_PATH}</code> as bundled starter data.</span></p>"
            f"<p><b>Project</b><br/><a href=\"{REPO_URL}\">{REPO_URL}</a></p>"
            "<p style='color:#8b919a;font-size:10pt;margin-bottom:0'>"
            "Not affiliated with Start.me or OSINT4ALL authors. Use ethically and in line with "
            "applicable law and site terms. PyQt6 + Qt WebEngine.</p>",
        )


def main():
    _fix_fontconfig_env()
    _quiet_chromium_stderr()

    QCoreApplication.setAttribute(
        Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True
    )
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
    app = QApplication(sys.argv)
    app.setApplicationName("OSINT AIO")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("OSINT AIO")
    apply_analyst_theme(app)

    browse_profile = None
    if _webengine_available():
        from PyQt6.QtWebEngineCore import QWebEngineProfile

        ua = QWebEngineProfile.defaultProfile().httpUserAgent() + " OSINT-AIO/1.0"
        QWebEngineProfile.defaultProfile().setHttpUserAgent(ua)

        browse_profile = QWebEngineProfile("osint-aio-browse")
        browse_profile.setUrlRequestInterceptor(build_interceptor(ROOT))
        browse_profile.setHttpUserAgent(ua)

    win = OsintAioWindow(browse_profile=browse_profile)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
