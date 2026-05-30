from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal
import random
from gui.components.news_card import NewsCard
from core.news import news_manager

from qfluentwidgets import (
    PushButton, FluentIcon as FIF, ScrollArea, SegmentedWidget,
    TitleLabel, BodyLabel, CardWidget, InfoBar, InfoBarPosition
)

class NewsLoaderThread(QThread):
    loaded = Signal(list)
    status_update = Signal(str)
    
    def __init__(self, use_ai=True):
        super().__init__()
        self.use_ai = use_ai

    def run(self):
        news = news_manager.get_categorized_updates(status_callback=self.status_update.emit, limit_per_category=5)
        self.loaded.emit(news)

class BriefingView(QWidget):
    """
    The main Dashboard/Briefing view using Fluent Widgets.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("briefingView")
        self.all_news_items = []
        
        # Main Layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(30, 30, 30, 30)
        self.layout.setSpacing(20)
        
        # Header Area
        header_layout = QHBoxLayout()
        
        title_block = QVBoxLayout()
        title = TitleLabel("Briefing", self)
        subtitle = BodyLabel("Curated intelligence from global sources.", self)
        subtitle.setStyleSheet("color: #8a8a8a;")
        
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header_layout.addLayout(title_block)
        
        header_layout.addStretch()
        
        # Shuffle Button
        shuffle_btn = PushButton(FIF.ROTATE, "Shuffle")
        shuffle_btn.clicked.connect(self.shuffle_news)
        header_layout.addWidget(shuffle_btn)

        # Refresh Button
        refresh_btn = PushButton(FIF.SYNC, "Refresh")
        refresh_btn.clicked.connect(lambda: self.load_news(use_ai=True))
        header_layout.addWidget(refresh_btn)
        
        self.layout.addLayout(header_layout)
        
        # Breaking News (Using CardWidget for emphasis)
        self.breaking_widget = CardWidget()
        self.breaking_widget.setBorderRadius(10)
        self.breaking_widget.setFixedHeight(60)
        bk_layout = QHBoxLayout(self.breaking_widget)
        bk_layout.setContentsMargins(15, 0, 15, 0)
        
        bk_label = BodyLabel("BREAKING")
        bk_label.setStyleSheet("color: #ef5350; font-weight: bold;")
        bk_layout.addWidget(bk_label)
        
        self.bk_text = BodyLabel("Click Refresh to load intelligence.")
        bk_layout.addWidget(self.bk_text)
        bk_layout.addStretch()
        
        self.layout.addWidget(self.breaking_widget)
        
        # Category Filters (SegmentedWidget)
        self.pivot = SegmentedWidget()
        
        categories = ["All", "Top Stories", "Technology", "Markets", "Science", "Culture", "Trending"]
        for c in categories:
            self.pivot.addItem(routeKey=c, text=c)
            
        self.pivot.setCurrentItem("All")
        self.pivot.currentItemChanged.connect(lambda _: self.render_news())
        
        self.layout.addWidget(self.pivot)
        
        # News Grid (Scroll Area)
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.viewport().setStyleSheet("background: transparent;")
        
        container = QWidget()
        self.news_list_layout = QVBoxLayout(container)
        self.news_list_layout.setSpacing(15)
        self.news_list_layout.setContentsMargins(0, 0, 0, 20)
        self.news_list_layout.setAlignment(Qt.AlignTop)
        
        scroll.setWidget(container)
        self.layout.addWidget(scroll)
        
        # Load Data (No AI on startup to prevent model load)
        self.load_news(use_ai=False)

    def load_news(self, use_ai=True):
        if use_ai:
            self.bk_text.setText("Syncing global sources & Curating with AI...")
        else:
            self.bk_text.setText("Fetching latest headlines...")
        
        # Clear list
        while self.news_list_layout.count():
            item = self.news_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            
        self.thread = NewsLoaderThread(use_ai=use_ai)
        self.thread.status_update.connect(self.bk_text.setText)
        self.thread.loaded.connect(self.display_news)
        self.thread.start()
        
    def display_news(self, news_items):
        if not news_items:
            self.bk_text.setText("System offline. No news available.")
            InfoBar.warning(
                title="News Offline",
                content="Could not fetch latest news. Please check connection.",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3000,
                parent=self
            )
            return

        self.all_news_items = news_items
        self.render_news()

    def render_news(self):
        while self.news_list_layout.count():
            item = self.news_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        selected = self.pivot.currentRouteKey()
        news_items = [
            item for item in self.all_news_items
            if selected == "All" or item.get("category") == selected
        ]

        if news_items:
            first = news_items[0]
            self.bk_text.setText(f"{first.get('title')} ({first.get('source')})")
        else:
            self.bk_text.setText(f"No {selected.lower()} stories loaded yet.")

        # Populate List
        for item in news_items:
            card = NewsCard(item)
            self.news_list_layout.addWidget(card)

    def shuffle_news(self):
        if not self.all_news_items:
            return
        random.shuffle(self.all_news_items)
        self.render_news()
