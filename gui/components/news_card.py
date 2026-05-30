from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QCursor, QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout


class NewsCard(QFrame):
    """Clickable card for a single news story."""

    def __init__(self, article, parent=None):
        super().__init__(parent)
        self.article = article or {}
        self.url = self.article.get("url")

        self.setObjectName("newsCard")
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setFixedHeight(150)
        self.setToolTip("Open the original article")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(16)

        category = self.article.get("category", "Top Stories")
        accent = self._get_category_color(category)

        badge = QLabel(self._get_category_icon(category))
        badge.setFixedSize(58, 58)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f"""
            background-color: {accent}22;
            border: 1px solid {accent}55;
            border-radius: 14px;
            color: {accent};
            font-size: 16px;
            font-weight: 800;
        """)
        layout.addWidget(badge)

        content_layout = QVBoxLayout()
        content_layout.setSpacing(8)
        content_layout.setAlignment(Qt.AlignVCenter)

        headline = QLabel(self.article.get("title") or "Untitled story")
        headline.setWordWrap(True)
        headline.setStyleSheet("""
            color: #ffffff;
            font-size: 16px;
            font-weight: 650;
            font-family: 'Segoe UI';
        """)
        content_layout.addWidget(headline)

        body = self.article.get("body") or self.article.get("snippet")
        if body:
            summary = QLabel(str(body)[:150])
            summary.setWordWrap(True)
            summary.setStyleSheet("color: #8b9bb4; font-size: 12px;")
            content_layout.addWidget(summary)

        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(8)

        source = QLabel(self.article.get("source") or "Unknown source")
        source.setStyleSheet(f"color: {accent}; font-weight: 700; font-size: 12px;")
        meta_layout.addWidget(source)

        date = QLabel(self.article.get("date") or "Latest")
        date.setStyleSheet("color: #718096; font-size: 12px;")
        meta_layout.addWidget(date)
        meta_layout.addStretch()

        read = QLabel("Open source")
        read.setStyleSheet("color: #e8eaed; font-size: 12px; font-weight: 650;")
        meta_layout.addWidget(read)

        content_layout.addLayout(meta_layout)
        layout.addLayout(content_layout, 1)

        self.setStyleSheet("""
            QFrame#newsCard {
                background-color: #111625;
                border: 1px solid #1a2236;
                border-radius: 12px;
            }
            QFrame#newsCard:hover {
                background-color: #1a2236;
                border: 1px solid #33b5e5;
            }
        """)

    def _get_category_color(self, category):
        cat = str(category).lower()
        if "tech" in cat:
            return "#33b5e5"
        if "market" in cat or "finance" in cat or "business" in cat:
            return "#2ecc71"
        if "science" in cat:
            return "#b36cff"
        if "culture" in cat:
            return "#ff6b7a"
        if "trend" in cat:
            return "#ffbb33"
        return "#ff9f43"

    def _get_category_icon(self, category):
        cat = str(category).lower()
        if "tech" in cat:
            return "AI"
        if "market" in cat or "finance" in cat or "business" in cat:
            return "$"
        if "science" in cat:
            return "SC"
        if "culture" in cat:
            return "AR"
        if "trend" in cat:
            return "#"
        return "N"

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.url:
            QDesktopServices.openUrl(QUrl(self.url))
            event.accept()
            return
        super().mousePressEvent(event)
