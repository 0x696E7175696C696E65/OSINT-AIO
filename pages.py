"""Custom QWebEnginePage: cut down third-party console spam in the embedded browser."""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineCore import QWebEnginePage

# Substrings of messages that are routine on ad-heavy / tracker-heavy sites (still allow unknown errors).
_CONSOLE_NOISE_FRAGMENTS: tuple[str, ...] = (
    "CORS policy",
    "Google basic consent",
    "X-Frame-Options",
    "Mixed Content",
    "link preload",
    "Failed to fetch",
    "Failed to read a named property",
    "from accessing a frame with origin",
    "Buffer is not defined",
    "Error decoding tpids",
    "Error sending events",
    "Cannot read properties of null",
    "addEventListener",
    "gum.aidemsrv.com",
    "safeframe.googlesyndication.com",
    "nextmillmedia",
    "pmbmonetize",
    "quantserve",
    "pub.network",
)


class QuietBrowsePage(QWebEnginePage):
    def javaScriptConsoleMessage(
        self,
        level: QWebEnginePage.JavaScriptConsoleMessageLevel,
        message: str | None,
        lineNumber: int,
        sourceID: str | None,
    ) -> None:
        m = message or ""
        low = m.lower()
        for frag in _CONSOLE_NOISE_FRAGMENTS:
            if frag.lower() in low:
                return
        if level in (
            QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel,
            QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel,
        ):
            return
        super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)


class WelcomeHomePage(QuietBrowsePage):
    """Keeps the intro tab on about:blank / inline HTML; blocks main-frame http(s) loads."""

    def acceptNavigationRequest(
        self,
        url: QUrl,
        nav_type: QWebEnginePage.NavigationType,
        isMainFrame: bool,
    ) -> bool:
        if not isMainFrame:
            return super().acceptNavigationRequest(url, nav_type, isMainFrame)
        scheme = (url.scheme() or "").lower()
        if scheme in ("http", "https"):
            return False
        return super().acceptNavigationRequest(url, nav_type, isMainFrame)
