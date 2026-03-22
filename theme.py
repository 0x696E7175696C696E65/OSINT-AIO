"""Dark analyst-style application theme (Fusion + Qt Style Sheets)."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication


def apply_analyst_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    base = QColor("#1a1d23")
    panel = QColor("#22262e")
    text = QColor("#e8eaed")
    muted = QColor("#8b919a")
    accent = QColor("#3d8bfd")
    pal.setColor(QPalette.ColorRole.Window, base)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, panel)
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#2a2f38"))
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.Button, QColor("#2d333d"))
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.Highlight, accent)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.Link, QColor("#6eb3ff"))
    pal.setColor(QPalette.ColorRole.LinkVisited, QColor("#b388ff"))
    app.setPalette(pal)

    f = app.font()
    f.setPointSize(max(f.pointSize(), 10))
    app.setFont(f)

    app.setStyleSheet(
        """
        QMainWindow, QWidget { background-color: #1a1d23; color: #e8eaed; }
        QMenuBar {
            background-color: #22262e;
            color: #e8eaed;
            padding: 2px;
            border-bottom: 1px solid #2d333d;
        }
        QMenuBar::item:selected { background-color: #3d8bfd; color: #ffffff; }
        QMenu {
            background-color: #22262e;
            color: #e8eaed;
            border: 1px solid #3d444f;
        }
        QMenu::item:selected { background-color: #3d8bfd; color: #ffffff; }
        QToolBar {
            background-color: #22262e;
            border: none;
            border-bottom: 1px solid #2d333d;
            spacing: 6px;
            padding: 4px 6px;
        }
        QToolButton, QToolBar QToolButton {
            background-color: #2d333d;
            color: #e8eaed;
            border: 1px solid #3d444f;
            border-radius: 4px;
            padding: 5px 10px;
            margin: 1px;
        }
        QToolButton:hover { background-color: #3a4250; border-color: #3d8bfd; }
        QToolButton:pressed { background-color: #3d8bfd; color: #ffffff; }
        QStatusBar {
            background-color: #22262e;
            color: #8b919a;
            border-top: 1px solid #2d333d;
        }
        QSplitter::handle { background-color: #2d333d; width: 2px; }
        QTabWidget::pane { border: 1px solid #2d333d; background-color: #1a1d23; top: -1px; }
        QTabBar::tab {
            background-color: #2d333d;
            color: #8b919a;
            padding: 8px 16px;
            margin-right: 2px;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
        }
        QTabBar::tab:selected { background-color: #1a1d23; color: #e8eaed; border-bottom: 2px solid #3d8bfd; }
        QTabBar::tab:hover:!selected { color: #e8eaed; }
        QLineEdit {
            background-color: #2a2f38;
            color: #e8eaed;
            border: 1px solid #3d444f;
            border-radius: 4px;
            padding: 6px 10px;
            selection-background-color: #3d8bfd;
        }
        QLineEdit:focus { border-color: #3d8bfd; }
        QLabel#catalogPanelTitle {
            color: #8b919a;
            font-weight: 600;
            font-size: 11px;
            letter-spacing: 0.08em;
        }
        QTreeWidget {
            background-color: #1e222a;
            color: #e8eaed;
            border: 1px solid #2d333d;
            border-radius: 4px;
            outline: none;
            padding: 4px;
        }
        QTreeWidget::item { padding: 2px 0; min-height: 22px; }
        QTreeWidget::item:selected {
            background-color: #3d8bfd;
            color: #ffffff;
        }
        QTreeWidget::item:hover:!selected { background-color: #2a3140; }
        QHeaderView::section {
            background-color: #2d333d;
            color: #8b919a;
            padding: 8px 10px;
            border: none;
            border-bottom: 2px solid #3d8bfd;
            font-weight: 600;
            font-size: 11px;
        }
        QMessageBox { background-color: #22262e; }
        QMessageBox QLabel { color: #e8eaed; }
        """
    )
