"""
Global stylesheet for Princess.
"""

# Aura Theme Colors
# Background: #05080d (Deepest Navy)
# Surface: #0f1524 (Dark Navy)
# Accent: #33b5e5 (Cyan)
# Text: #e8eaed

AURA_STYLESHEET = """
/* Global Window Background */
FluentWindow {
    background-color: #05080d;
    color: #e8eaed;
}

/* Stacked Widget Background (Content Area) */
StackedWidget {
    background-color: #05080d;
    border: none;
}

/* Navigation Interface (Sidebar) */
NavigationInterface {
    background-color: #05080d;
    border-right: 1px solid #1a2236;
}

/* Cards (Surface) */
CardWidget {
    background-color: #0f1524;
    border: 1px solid #1a2236;
    border-radius: 10px;
}

/* Labels */
TitleLabel, SubtitleLabel, StrongBodyLabel {
    color: #e8eaed;
}

BodyLabel, CaptionLabel {
    color: #8b9bb4;
}

/* Standard QWidget used as containers */
QWidget#chatContent, QWidget#plannerPanel, QWidget#briefingView, QWidget#commandCenterInterface, QFrame#homeAutomationView {
    background-color: transparent;
}

QFrame#commandPanel {
    background-color: rgba(8, 17, 31, 0.94);
    border: 1px solid rgba(51, 181, 229, 0.20);
    border-radius: 14px;
}

QFrame#commandPanelFun {
    background-color: rgba(7, 21, 34, 0.96);
    border: 1px solid rgba(51, 181, 229, 0.35);
    border-radius: 14px;
}

QFrame#commandPanelHero, QFrame#commandPanelCore {
    background-color: rgba(9, 18, 34, 0.97);
    border: 1px solid rgba(123, 97, 255, 0.38);
    border-radius: 16px;
}

QFrame#commandPanelCore {
    border: 1px solid rgba(51, 214, 255, 0.52);
}

QFrame#commandPanel:hover,
QFrame#commandPanelFun:hover,
QFrame#commandPanelHero:hover,
QFrame#commandPanelCore:hover {
    border: 1px solid rgba(51, 214, 255, 0.70);
}

QFrame#commandHeader {
    background-color: rgba(5, 15, 30, 0.98);
    border: 1px solid rgba(51, 214, 255, 0.52);
    border-radius: 18px;
}

QFrame#commandStatusBar {
    background-color: rgba(6, 13, 24, 0.94);
    border: 1px solid rgba(51, 181, 229, 0.18);
    border-radius: 10px;
}

QLabel#commandCore {
    background-color: #071827;
    color: #33d6ff;
    border: 2px solid rgba(51, 214, 255, 0.75);
    border-radius: 39px;
    font-size: 34px;
    font-weight: 700;
}

QFrame#commandChip_good,
QFrame#commandChip_warn,
QFrame#commandChip_muted {
    background-color: rgba(13, 26, 43, 0.96);
    border-radius: 10px;
    min-width: 92px;
}

QFrame#commandChip_good {
    border: 1px solid rgba(51, 214, 255, 0.55);
}

QFrame#commandChip_warn {
    border: 1px solid rgba(255, 187, 51, 0.64);
}

QFrame#commandChip_muted {
    border: 1px solid rgba(139, 155, 180, 0.40);
}

QFrame#commandAppTile, QFrame#commandMiniRow {
    background-color: rgba(11, 27, 44, 0.94);
    border: 1px solid rgba(51, 181, 229, 0.24);
    border-radius: 10px;
}

QFrame#commandAppTile:hover {
    background-color: rgba(16, 40, 68, 0.98);
    border: 1px solid rgba(51, 214, 255, 0.72);
}

PushButton#commandPromptChip {
    background-color: rgba(12, 28, 48, 0.92);
    border: 1px solid rgba(123, 97, 255, 0.36);
    border-radius: 14px;
    padding: 6px 10px;
}

PushButton#commandPromptChip:hover {
    border: 1px solid rgba(51, 214, 255, 0.70);
    background-color: rgba(18, 45, 76, 0.96);
}

QFrame#commandCoreBadge {
    background-color: rgba(6, 20, 36, 0.94);
    border: 1px solid rgba(51, 214, 255, 0.28);
    border-radius: 10px;
    min-width: 110px;
}

TextEdit#commandCoreLog {
    background-color: rgba(4, 11, 22, 0.78);
    border: 1px solid rgba(51, 181, 229, 0.20);
    border-radius: 14px;
    padding: 10px;
    color: #e8eaed;
}

LineEdit#commandCoreInput {
    background-color: rgba(7, 18, 34, 0.98);
    border: 1px solid rgba(51, 214, 255, 0.35);
    border-radius: 18px;
    padding-left: 14px;
    padding-right: 14px;
    color: #ffffff;
}

LineEdit#commandCoreInput:focus {
    background-color: rgba(10, 28, 50, 0.98);
    border: 1px solid rgba(51, 214, 255, 0.85);
}

QFrame#commandItem {
    background-color: #141c2f;
    border: 1px solid #1f2a42;
    border-radius: 6px;
}

/* List Items (Session List) */
ListWidget {
    background-color: transparent;
    border: none;
}

ListWidget::item {
    color: #8b9bb4;
    border-radius: 6px;
    padding: 8px;
    margin: 2px;
}

ListWidget::item:hover {
    background-color: rgba(51, 181, 229, 0.1); /* Cyan tint */
    color: #e8eaed;
}

ListWidget::item:selected {
    background-color: rgba(51, 181, 229, 0.2);
    color: #33b5e5;
    border-left: 2px solid #33b5e5;
}

/* Input Fields */
LineEdit, TextEdit, PlainTextEdit {
    background-color: #0f1524;
    border: 1px solid #1a2236;
    border-radius: 8px;
    color: #e8eaed;
    selection-background-color: #33b5e5;
}

LineEdit:focus, TextEdit:focus {
    border: 1px solid #33b5e5;
    background-color: #141c2f;
}

/* ScrollBars */
QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #1a2236;
    min-height: 20px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: #33b5e5;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""
