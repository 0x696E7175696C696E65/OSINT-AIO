"""Catalog sidebar: filter, color-coded tree, two-line link rows."""

from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from catalog import Catalog

ROLE_URL = Qt.ItemDataRole.UserRole
ROLE_KIND = Qt.ItemDataRole.UserRole + 1  # "category" | "link" | "placeholder"
ROLE_FILTER = Qt.ItemDataRole.UserRole + 2
ROLE_ACCENT = Qt.ItemDataRole.UserRole + 3  # QColor for category stripe
ROLE_TINT = Qt.ItemDataRole.UserRole + 4  # QColor row background for category


def _category_colors(name: str) -> tuple[QColor, QColor]:
    """Stable accent (stripe) + dim row tint for a category name."""
    h = hashlib.sha256(name.encode("utf-8")).digest()
    hue = int.from_bytes(h[:2], "big") % 360
    stripe = QColor.fromHsv(hue, 200, 255)
    tint = QColor.fromHsv(hue, 35, 42)
    return stripe, tint


def _link_subtitle(url: str) -> str:
    try:
        p = urlparse(url)
    except Exception:
        return url[:80]
    host = p.netloc or ""
    path = (p.path or "").strip("/")
    if path:
        seg = path.replace("//", "/")[:56]
        if len(path) > 56:
            seg += "…"
        return f"{host}/{seg}" if host else seg
    return host or url[:80]


class CatalogItemDelegate(QStyledItemDelegate):
    """Category rows: colored stripe + label. Link rows: title + monospace target line."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        kind = index.data(ROLE_KIND)
        if kind == "placeholder":
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if kind == "category":
            stripe = index.data(ROLE_ACCENT)
            if not isinstance(stripe, QColor):
                stripe = QColor("#3d8bfd")
            tint = index.data(ROLE_TINT)
            selected = option.state & QStyle.StateFlag.State_Selected
            if selected:
                painter.fillRect(option.rect, QColor("#2a4a7a"))
            elif isinstance(tint, QColor):
                painter.fillRect(option.rect, tint)
            painter.fillRect(
                option.rect.left(),
                option.rect.top(),
                4,
                option.rect.height(),
                stripe,
            )
            text_rect = option.rect.adjusted(14, 0, -8, 0)
            painter.setPen(QColor("#e8eaed"))
            f = painter.font()
            f.setBold(True)
            f.setPointSize(max(f.pointSize(), 10))
            painter.setFont(f)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                index.data(Qt.ItemDataRole.DisplayRole) or "",
            )
            painter.restore()
            return

        if kind == "link":
            selected = option.state & QStyle.StateFlag.State_Selected
            if selected:
                painter.fillRect(option.rect, QColor("#3d8bfd"))
                title_col = QColor("#ffffff")
                sub_col = QColor("#dde8ff")
            else:
                painter.fillRect(option.rect, QColor("#1e222a"))
                title_col = QColor("#e8eaed")
                sub_col = QColor("#8b919a")

            url = index.data(ROLE_URL) or ""
            title = index.data(Qt.ItemDataRole.DisplayRole) or ""
            sub = _link_subtitle(str(url))

            margin_l = 8
            margin_t = 6
            w = option.rect.width() - margin_l - 8

            painter.setPen(title_col)
            tf = painter.font()
            tf.setBold(True)
            tf.setPointSize(max(tf.pointSize(), 10))
            painter.setFont(tf)
            tfm = painter.fontMetrics()
            y_base = option.rect.top() + margin_t
            elided_t = tfm.elidedText(title, Qt.TextElideMode.ElideRight, w)
            painter.drawText(
                option.rect.left() + margin_l, y_base + tfm.ascent(), elided_t
            )

            painter.setPen(sub_col)
            sf = QFont(tf)
            sf.setBold(False)
            sf.setPointSize(max(tf.pointSize() - 1, 8))
            sf.setFamilies(["JetBrains Mono", "Consolas", "DejaVu Sans Mono", "monospace"])
            painter.setFont(sf)
            sfm = painter.fontMetrics()
            y2 = y_base + tfm.height() + 4
            elided_s = sfm.elidedText(sub, Qt.TextElideMode.ElideMiddle, w)
            painter.drawText(option.rect.left() + margin_l, y2 + sfm.ascent(), elided_s)

            painter.restore()
            return

        super().paint(painter, option, index)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        kind = index.data(ROLE_KIND)
        w = max(220, option.rect.width())
        if kind == "link":
            h = 24 + max(10, option.fontMetrics.height()) + 8
            return QSize(w, h)
        if kind == "category":
            return QSize(w, 32)
        return super().sizeHint(option, index)


class CatalogTree(QTreeWidget):
    """Enter / Return opens the focused link in the analyst browser."""

    link_open_requested = pyqtSignal(str)

    def keyPressEvent(self, ev) -> None:
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            it = self.currentItem()
            if it is not None:
                u = it.data(0, ROLE_URL)
                if u:
                    self.link_open_requested.emit(str(u))
                    ev.accept()
                    return
        super().keyPressEvent(ev)


class CatalogSidePanel(QWidget):
    """Search + tree for the analyst workbench."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tree = CatalogTree()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(14)
        self._tree.setAnimated(True)
        self._tree.setUniformRowHeights(False)
        self._tree.setItemDelegate(CatalogItemDelegate(self._tree))

        title = QLabel("OSINT AIO · RESOURCE INDEX")
        title.setObjectName("catalogPanelTitle")

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter by title, host, URL, or category…")
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self._on_filter_text)

        self._stats = QLabel("")
        self._stats.setStyleSheet("color: #8b919a; font-size: 11px; padding: 2px 2px 6px;")

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #2d333d; max-height: 1px; border: none;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(8)
        lay.addWidget(title)
        lay.addWidget(self._filter)
        lay.addWidget(self._stats)
        lay.addWidget(line)
        lay.addWidget(self._tree, 1)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self._apply_filter)

    def tree(self) -> QTreeWidget:
        return self._tree

    def set_stats_text(self, text: str) -> None:
        self._stats.setText(text)

    def _on_filter_text(self, _t: str) -> None:
        self._debounce.start()

    def _apply_filter(self) -> None:
        needle = self._filter.text().lower().strip()
        tree = self._tree
        for i in range(tree.topLevelItemCount()):
            cat = tree.topLevelItem(i)
            k = cat.data(0, ROLE_KIND)
            if k == "placeholder":
                cat.setHidden(False)
                continue
            ctext = (cat.data(0, ROLE_FILTER) or "").lower()
            if not needle:
                cat.setHidden(False)
                for j in range(cat.childCount()):
                    cat.child(j).setHidden(False)
                continue
            cat_match = needle in ctext
            any_child = False
            for j in range(cat.childCount()):
                ch = cat.child(j)
                ftxt = (ch.data(0, ROLE_FILTER) or "").lower()
                vis = cat_match or needle in ftxt
                ch.setHidden(not vis)
                if vis:
                    any_child = True
            cat.setHidden(not any_child)

    def populate(self, catalog: Catalog) -> None:
        self._tree.clear()
        self._filter.clear()
        if catalog.link_count() == 0:
            ph = QTreeWidgetItem(["No resources loaded"])
            ph.setData(0, ROLE_KIND, "placeholder")
            ph.setDisabled(True)
            self._tree.addTopLevelItem(ph)
            self.set_stats_text("Import a catalog or fetch from OSINT4ALL.")
            return

        for cat in catalog.categories:
            stripe, tint = _category_colors(cat.name)
            label = f"{cat.name}  ·  {len(cat.links)} resources"
            parent = QTreeWidgetItem([label])
            parent.setData(0, ROLE_KIND, "category")
            parent.setData(0, ROLE_FILTER, f"{cat.name} {len(cat.links)}")
            parent.setData(0, ROLE_ACCENT, stripe)
            parent.setData(0, ROLE_TINT, tint)
            parent.setFirstColumnSpanned(True)
            for link in cat.links:
                child = QTreeWidgetItem([link.title])
                child.setData(0, ROLE_URL, link.url)
                child.setData(0, ROLE_KIND, "link")
                child.setData(
                    0,
                    ROLE_FILTER,
                    f"{link.title} {link.url} {_link_subtitle(link.url)}".lower(),
                )
                child.setToolTip(
                    0,
                    f"{link.title}\n\n{link.url}\n\nOpens in a new tab (Welcome tab stays fixed).",
                )
                parent.addChild(child)
            self._tree.addTopLevelItem(parent)

        self._tree.expandAll()
        n = catalog.link_count()
        c = len(catalog.categories)
        self.set_stats_text(f"{n} links · {c} categories · indexed for filter")
