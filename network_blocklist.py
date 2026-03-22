"""Block ad / tracker hosts in the embedded browser and strip them from harvested catalogs."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInterceptor, QWebEngineUrlRequestInfo

# Suffix match (hostname equals or ends with ".suffix"). Keep practical for local browsing.
_DEFAULT_SUFFIXES: frozenset[str] = frozenset(
    {
        "doubleclick.net",
        "googlesyndication.com",
        "googleadservices.com",
        "google-analytics.com",
        "googletagmanager.com",
        "g.doubleclick.net",
        "pagead2.googlesyndication.com",
        "adservice.google.com",
        "adservice.google.nl",
        "adsafeprotected.com",
        "adnxs.com",
        "amazon-adsystem.com",
        "adsrvr.org",
        "rlcdn.com",
        "quantserve.com",
        "scorecardresearch.com",
        "facebook.net",
        "connect.facebook.net",
        "analytics.yahoo.com",
        "ads.yahoo.com",
        "taboola.com",
        "outbrain.com",
        "criteo.com",
        "pubmatic.com",
        "rubiconproject.com",
        "openx.net",
        "3lift.com",
        "casalemedia.com",
        "demdex.net",
        "adsystem.amazon.com",
        "smartadserver.com",
        "moatads.com",
        "chartbeat.net",
        "hotjar.com",
        "segment.io",
        "segment.com",
        "optimizely.com",
        "clarity.ms",
        "bat.bing.com",
        "ads-twitter.com",
        "safeframe.googlesyndication.com",
        "safeframe.googleapis.com",
        "gum.aidemsrv.com",
        "nextmillmedia.com",
        "pmbmonetize.live",
        "pub.network",
        "d.pub.network",
        "cookies.nextmillmedia.com",
        "sync.pmbmonetize.live",
        "edge.quantserve.com",
        "quantcount.com",
        "id5-sync.com",
        "liveramp.com",
        "adsymptotic.com",
        "adform.net",
        "360yield.com",
        "yieldmo.com",
        "contextweb.com",
        "bluekai.com",
        "krxd.net",
        "exelator.com",
        "tapad.com",
        "sitescout.com",
        "turn.com",
        "mathtag.com",
        "agkn.com",
        "ad.gt",
        "bttrack.com",
        "ipredictive.com",
        "zemanta.com",
    }
)


def _host_suffixes_for_path(path: Path) -> frozenset[str]:
    if not path.is_file():
        return frozenset()
    extra: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            extra.add(s.lower().lstrip("."))
    except OSError:
        return frozenset()
    return frozenset(extra)


def build_suffix_set(root: Path | None = None) -> frozenset[str]:
    base = root or Path(__file__).resolve().parent
    extra = _host_suffixes_for_path(base / "data" / "blocklist.txt")
    return _DEFAULT_SUFFIXES | extra


def host_matches_blocked_suffixes(host: str, suffixes: frozenset[str]) -> bool:
    h = host.lower().strip(".")
    if not h:
        return False
    if h in suffixes:
        return True
    for suf in suffixes:
        if h == suf or h.endswith("." + suf):
            return True
    return False


def url_should_block(url: str, suffixes: frozenset[str]) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https", "ws", "wss"):
        return False
    return host_matches_blocked_suffixes(p.hostname or "", suffixes)


def harvest_row_should_drop(url: str, suffixes: frozenset[str]) -> bool:
    """Drop harvested links that point at ads/trackers (noise from the Start.me page)."""
    return url_should_block(url, suffixes)


class AdTrackerInterceptor(QWebEngineUrlRequestInterceptor):
    def __init__(self, suffixes: frozenset[str]):
        super().__init__()
        self._suffixes = suffixes

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        u = info.requestUrl()
        if not u.isValid():
            return
        if url_should_block(u.toString(), self._suffixes):
            info.block(True)


def build_interceptor(root: Path | None = None) -> AdTrackerInterceptor:
    return AdTrackerInterceptor(build_suffix_set(root))
