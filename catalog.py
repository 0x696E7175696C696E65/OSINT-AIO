"""Local bookmark catalog: load/save JSON and merge scraped rows."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass
class Link:
    title: str
    url: str


@dataclass
class Category:
    name: str
    links: list[Link] = field(default_factory=list)


@dataclass
class Catalog:
    source_url: str
    fetched_at: str
    categories: list[Category] = field(default_factory=list)

    def link_count(self) -> int:
        return sum(len(c.links) for c in self.categories)


def default_catalog_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parent
    return base / "data" / "catalog.json"


def _normalize_http_url(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    u = url.strip()
    if not u.startswith(("http://", "https://")):
        return None
    try:
        p = urlparse(u)
    except Exception:
        return None
    if not p.netloc:
        return None
    return u.split("#", 1)[0].strip()


def catalog_from_harvest_rows(
    rows: list[dict[str, Any]], source_url: str
) -> Catalog:
    """Group flat JS rows {category, title, url} into a Catalog."""
    by_cat: dict[str, dict[str, str]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        url = _normalize_http_url(r.get("url"))
        if not url:
            continue
        raw = (r.get("category") or "Uncategorized") or "Uncategorized"
        cat = str(raw).strip() or "Uncategorized"
        cat = cat.replace("\n", " ").strip()[:200]
        title = (r.get("title") or url) or url
        title = str(title).replace("\n", " ").strip()[:500]
        if cat not in by_cat:
            by_cat[cat] = {}
        if url not in by_cat[cat]:
            by_cat[cat][url] = title

    categories = [
        Category(name=name, links=[Link(title=t, url=u) for u, t in links.items()])
        for name, links in sorted(by_cat.items(), key=lambda x: x[0].lower())
    ]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Catalog(source_url=source_url, fetched_at=now, categories=categories)


def catalog_to_json_dict(cat: Catalog) -> dict[str, Any]:
    return {
        "source_url": cat.source_url,
        "fetched_at": cat.fetched_at,
        "categories": [
            {
                "name": c.name,
                "links": [{"title": l.title, "url": l.url} for l in c.links],
            }
            for c in cat.categories
        ],
    }


def catalog_from_json_dict(data: dict[str, Any]) -> Catalog:
    source = str(data.get("source_url") or "")
    fetched = str(data.get("fetched_at") or "")
    raw_cats = data.get("categories") or []
    categories: list[Category] = []
    if isinstance(raw_cats, list):
        for c in raw_cats:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name") or "Uncategorized").strip() or "Uncategorized"
            links: list[Link] = []
            for L in c.get("links") or []:
                if not isinstance(L, dict):
                    continue
                url = _normalize_http_url(L.get("url"))
                if not url:
                    continue
                title = str(L.get("title") or url).strip()[:500] or url
                links.append(Link(title=title, url=url))
            if links:
                categories.append(Category(name=name, links=links))
    return Catalog(source_url=source, fetched_at=fetched, categories=categories)


def load_catalog(path: Path) -> Catalog | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return catalog_from_json_dict(data)


def save_catalog(cat: Catalog, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(catalog_to_json_dict(cat), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
