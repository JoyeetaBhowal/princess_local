from __future__ import annotations

import json
import random
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    TitleLabel,
)

from config import (
    ASSISTANT_NAME,
    ASSISTANT_SYSTEM_PROMPT,
    DAILY_PERMISSION_REQUIRED,
    INTERNET_ENABLED,
    INTERNET_REQUIRES_APPROVAL,
    MAX_RESEARCH_RESULTS,
    OLLAMA_URL,
    RESPONDER_MODEL,
    SPEAK_RESPONSES,
    SOCIAL_ACTIONS_REQUIRE_APPROVAL,
    SOCIAL_POSTING_ENABLED,
    TTS_ENABLED,
    VOICE_ASSISTANT_ENABLED,
    WAKE_WORD_ENABLED,
    WAKE_WORD_PHRASE,
)
from core.approvals import approval_queue
from core.knowledge import knowledge_library
from core.llm import http_session
from core.news import news_manager
from core.tts import tts
from gui.components.news_card import NewsCard


class UpdatesLoaderThread(QThread):
    loaded = Signal(list)
    status_update = Signal(str)

    def run(self):
        updates = news_manager.get_categorized_updates(
            status_callback=self.status_update.emit,
            limit_per_category=4,
        )
        self.loaded.emit(updates)


class DraftWorker(QThread):
    drafted = Signal(str)
    error = Signal(str)
    status_update = Signal(str)

    def __init__(self, platform: str, topic: str, context: str):
        super().__init__()
        self.platform = platform
        self.topic = topic
        self.context = context

    def run(self):
        prompt = f"""
You are Princess, a calm and practical writing assistant.
Write a polished draft for {self.platform}.

Rules:
- Keep it truthful, useful, and natural.
- Do not include medical, legal, financial, unsafe, or harmful advice.
- Do not claim current facts that are not provided in the context.
- Do not say the post has been published.
- Return only the draft text.

Topic:
{self.topic}

Context:
{self.context}
"""
        try:
            self.status_update.emit("Writing draft locally...")
            response = http_session.post(
                f"{OLLAMA_URL}/chat",
                json={
                    "model": RESPONDER_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.5},
                },
                timeout=120,
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content", "").strip()
            if not content:
                raise RuntimeError("Ollama returned an empty draft.")
            self.drafted.emit(content)
        except Exception as exc:
            self.error.emit(str(exc))


class TalkWorker(QThread):
    response_ready = Signal(str, object)
    error = Signal(str)
    status_update = Signal(str)

    def __init__(self, user_text: str, messages: list, speak_response: bool):
        super().__init__()
        self.user_text = user_text
        self.messages = messages
        self.speak_response = speak_response

    def run(self):
        try:
            self.status_update.emit("Princess is thinking...")
            messages = list(self.messages)
            messages.append({"role": "user", "content": self.user_text})
            response = http_session.post(
                f"{OLLAMA_URL}/chat",
                json={
                    "model": RESPONDER_MODEL,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0.45},
                },
                timeout=120,
            )
            response.raise_for_status()
            answer = response.json().get("message", {}).get("content", "").strip()
            if not answer:
                raise RuntimeError("Princess did not return a response.")
            messages.append({"role": "assistant", "content": answer})
            if len(messages) > 13:
                messages = [messages[0]] + messages[-12:]
            if self.speak_response:
                try:
                    if tts.toggle(True):
                        tts.queue_sentence(answer)
                except Exception as exc:
                    self.status_update.emit(f"TTS warning: {exc}")
            self.response_ready.emit(answer, messages)
        except Exception as exc:
            self.error.emit(str(exc))


class PlanWorker(QThread):
    planned = Signal(str)
    error = Signal(str)
    status_update = Signal(str)

    def __init__(self, target_apps: str, task_text: str):
        super().__init__()
        self.target_apps = target_apps
        self.task_text = task_text

    def run(self):
        prompt = f"""
You are Princess, a calm command-center planner.
Turn the user's request into a short, safe execution plan.

Rules:
- Do not claim anything was completed.
- Do not ask for or store passwords, tokens, or private credentials.
- Mention any step that needs explicit user approval.
- For social posting, publishing, purchases, messages, or account changes, require approval before action.
- Keep the plan concise and practical.

Target apps:
{self.target_apps}

User request:
{self.task_text}
"""
        try:
            self.status_update.emit("Planning the workflow locally...")
            response = http_session.post(
                f"{OLLAMA_URL}/chat",
                json={
                    "model": RESPONDER_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.35},
                },
                timeout=120,
            )
            response.raise_for_status()
            plan = response.json().get("message", {}).get("content", "").strip()
            if not plan:
                raise RuntimeError("Princess returned an empty plan.")
            self.planned.emit(plan)
        except Exception as exc:
            self.error.emit(str(exc))


class KnowledgeIndexThread(QThread):
    indexed = Signal(object)
    error = Signal(str)
    status_update = Signal(str)

    def __init__(self, files: list[str]):
        super().__init__()
        self.files = files

    def run(self):
        indexed_docs = []
        for file_path in self.files:
            try:
                self.status_update.emit(f"Indexing {Path(file_path).name}...")
                indexed_docs.append(knowledge_library.index_file(file_path))
            except Exception as exc:
                self.error.emit(f"{Path(file_path).name}: {exc}")
        self.indexed.emit(indexed_docs)


class CommandCenterTab(QWidget):
    """Internet briefing, draft writing, and approval-gated work queue."""

    browser_task_requested = Signal(str)

    def __init__(self, parent=None, auto_load: bool = True):
        super().__init__(parent)
        self.setObjectName("commandCenterInterface")
        self.knowledge_dir = Path("data") / "knowledge"
        self.index_dir = Path("data") / "index"
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.all_updates = []
        self.selected_approval_id = None
        self._updates_thread = None
        self._draft_worker = None
        self._talk_worker = None
        self._plan_worker = None
        self._knowledge_worker = None
        self._voice_thread = None
        self._voice_worker = None
        self.mission_rows = {}
        self.command_messages = [
            {
                "role": "system",
                "content": (
                    ASSISTANT_SYSTEM_PROMPT
                    + " In Command Center, behave like an attentive operations partner. "
                    + "Listen carefully, remember the current conversation, summarize what you understood, "
                    + "and ask for permission before suggesting any external action."
                ),
            }
        ]

        self._setup_ui()
        self.refresh_approvals()
        if auto_load:
            self.load_updates()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        root.addWidget(self._build_command_header())

        columns = QHBoxLayout()
        columns.setSpacing(16)
        root.addLayout(columns, 1)

        columns.addWidget(self._build_updates_panel(), 2)

        middle_stack = QWidget(self)
        middle_layout = QVBoxLayout(middle_stack)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(14)
        middle_layout.addWidget(self._build_talk_panel(), 5)
        middle_layout.addWidget(self._build_action_panel(), 4)
        columns.addWidget(middle_stack, 4)

        columns.addWidget(self._build_right_rail(), 2)
        root.addWidget(self._build_bottom_status())

    def _build_command_header(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("commandHeader")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(18)

        core = QLabel("P", self)
        core.setObjectName("commandCore")
        core.setAlignment(Qt.AlignmentFlag.AlignCenter)
        core.setFixedSize(78, 78)
        layout.addWidget(core)

        title_block = QVBoxLayout()
        title = TitleLabel("Princess Command Center", self)
        subtitle = BodyLabel("Local-first personal AI for voice, research, memory, and execution.", self)
        title_block.addWidget(title)
        title_block.addWidget(subtitle)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        chips.addWidget(self._build_status_chip("LOCAL MODEL", RESPONDER_MODEL, "good"))
        chips.addWidget(self._build_status_chip("VOICE", "on" if VOICE_ASSISTANT_ENABLED else "off", "good" if VOICE_ASSISTANT_ENABLED else "muted"))
        chips.addWidget(self._build_status_chip("WAKE", "on" if WAKE_WORD_ENABLED else "off", "warn" if WAKE_WORD_ENABLED else "muted"))
        chips.addWidget(self._build_status_chip("INTERNET", "available" if INTERNET_ENABLED else "off", "good" if INTERNET_ENABLED else "muted"))
        chips.addWidget(self._build_status_chip("MEMORY", "local", "good"))
        chips.addWidget(self._build_status_chip("APPROVAL", "required" if SOCIAL_ACTIONS_REQUIRE_APPROVAL else "off", "good" if SOCIAL_ACTIONS_REQUIRE_APPROVAL else "warn"))
        title_block.addLayout(chips)
        layout.addLayout(title_block, 1)

        right = QVBoxLayout()
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.permission_label = CaptionLabel(self._permission_text(), self)
        self.permission_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right.addWidget(StrongBodyLabel("Operator Safety", self), 0, Qt.AlignmentFlag.AlignRight)
        right.addWidget(self.permission_label)
        layout.addLayout(right)
        return panel

    def _build_status_chip(self, label: str, value: str, tone: str) -> QWidget:
        chip = QFrame(self)
        chip.setObjectName(f"commandChip_{tone}")
        chip_layout = QVBoxLayout(chip)
        chip_layout.setContentsMargins(10, 6, 10, 6)
        chip_layout.setSpacing(1)
        chip_layout.addWidget(CaptionLabel(label, self))
        chip_layout.addWidget(StrongBodyLabel(value, self))
        return chip

    def _build_bottom_status(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("commandStatusBar")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)
        layout.addWidget(CaptionLabel("Local/private mode", self))
        layout.addWidget(CaptionLabel(f"Internet results max: {MAX_RESEARCH_RESULTS}", self))
        layout.addWidget(CaptionLabel("Heavy actions require approval", self))
        layout.addStretch()
        layout.addWidget(CaptionLabel("Last action: ready", self))
        return panel

    def _build_updates_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("commandPanelFun")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(StrongBodyLabel("Signal Radar", self))
        top.addStretch()
        self.shuffle_btn = PushButton(FIF.SYNC, "Shuffle", self)
        self.shuffle_btn.clicked.connect(self.shuffle_updates)
        top.addWidget(self.shuffle_btn)
        self.refresh_btn = PushButton(FIF.SYNC, "Refresh", self)
        self.refresh_btn.clicked.connect(self.load_updates)
        top.addWidget(self.refresh_btn)
        layout.addLayout(top)

        self.category_combo = ComboBox(self)
        self.category_combo.addItems(
            ["All", "Top Stories", "Technology", "Markets", "Science", "Culture", "Trending"]
        )
        self.category_combo.currentTextChanged.connect(self.render_updates)
        layout.addWidget(self.category_combo)

        self.updates_status = CaptionLabel("Ready", self)
        layout.addWidget(self.updates_status)

        self.internet_mode_label = CaptionLabel(
            "Internet mode: on" if INTERNET_ENABLED else "Internet mode: off | local only",
            self,
        )
        layout.addWidget(self.internet_mode_label)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        container = QWidget()
        self.updates_layout = QVBoxLayout(container)
        self.updates_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.updates_layout.setContentsMargins(0, 0, 0, 0)
        self.updates_layout.setSpacing(8)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)
        return panel

    def _build_action_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("commandPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.addWidget(StrongBodyLabel("Command Composer", self))
        title_block.addWidget(CaptionLabel("Give Princess a task. She can plan first, then act only when approved.", self))
        top.addLayout(title_block)
        top.addStretch()
        layout.addLayout(top)

        self.app_combo = ComboBox(self)
        self.app_combo.addItems(
            [
                "Web Research",
                "Browser",
                "Multi-app workflow",
                "Email",
                "Calendar",
                "Docs",
                "LinkedIn",
                "X",
                "Facebook",
                "Instagram",
            ]
        )
        layout.addWidget(self.app_combo)

        app_grid = QGridLayout()
        app_grid.setHorizontalSpacing(8)
        app_grid.setVerticalSpacing(8)
        app_grid.addWidget(self._build_app_tile("Research", "Web Research", "Find, compare, summarize"), 0, 0)
        app_grid.addWidget(self._build_app_tile("Browser", "Browser", "Run a web task"), 0, 1)
        app_grid.addWidget(self._build_app_tile("Social", "LinkedIn", "Draft, queue, approve"), 0, 2)
        app_grid.addWidget(self._build_app_tile("Calendar", "Calendar", "Plan before action"), 1, 0)
        app_grid.addWidget(self._build_app_tile("Docs", "Docs", "Article and notes"), 1, 1)
        app_grid.addWidget(self._build_app_tile("Workflow", "Multi-app workflow", "Coordinate steps"), 1, 2)
        layout.addLayout(app_grid)

        self.task_input = QTextEdit(self)
        self.task_input.setPlaceholderText(
            "Ask Princess anything, or give her a task..."
        )
        self.task_input.setMinimumHeight(74)
        layout.addWidget(self.task_input)

        actions = QHBoxLayout()
        self.plan_task_btn = PushButton(FIF.EDIT, "Plan", self)
        self.plan_task_btn.clicked.connect(self.plan_task)
        actions.addWidget(self.plan_task_btn)

        self.queue_task_btn = PushButton(FIF.ADD, "Queue Approval", self)
        self.queue_task_btn.clicked.connect(self.queue_task)
        actions.addWidget(self.queue_task_btn)

        self.run_browser_btn = PrimaryPushButton(FIF.GLOBE, "Run in Browser", self)
        self.run_browser_btn.clicked.connect(self.run_browser_task)
        actions.addWidget(self.run_browser_btn)
        layout.addLayout(actions)

        self.task_plan = QTextEdit(self)
        self.task_plan.setReadOnly(True)
        self.task_plan.setMinimumHeight(86)
        self.task_plan.setPlaceholderText("Princess will place a focused workflow plan here.")
        layout.addWidget(self.task_plan)

        self.task_status = CaptionLabel(
            "Manual login only. Princess does not store passwords or post without approval.",
            self,
        )
        layout.addWidget(self.task_status)
        return panel

    def _build_app_tile(self, title: str, target: str, hint: str) -> QWidget:
        tile = QFrame(self)
        tile.setObjectName("commandAppTile")
        tile.setCursor(Qt.CursorShape.PointingHandCursor)
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(10, 8, 10, 8)
        tile_layout.setSpacing(2)
        tile_layout.addWidget(StrongBodyLabel(title, self))
        hint_label = CaptionLabel(hint, self)
        hint_label.setWordWrap(True)
        tile_layout.addWidget(hint_label)
        tile.mousePressEvent = lambda event, selected=target: self._select_app_tile(selected)
        return tile

    def _select_app_tile(self, target: str):
        index = self.app_combo.findText(target)
        if index >= 0:
            self.app_combo.setCurrentIndex(index)
        presets = {
            "Web Research": "Find the latest important updates, group them by category, and summarize what I should pay attention to.",
            "Browser": "Open the web and help me complete this task step by step. Ask before any external action.",
            "LinkedIn": "Draft a thoughtful post from today's useful updates and queue it for my approval.",
            "Calendar": "Turn my goal into a schedule and queue any calendar action for approval.",
            "Docs": "Create an article outline, then draft the article locally before I approve publishing.",
            "Multi-app workflow": "Plan a workflow across research, drafting, browser work, and approvals without taking external action yet.",
        }
        if not self._task_text():
            self.task_input.setPlainText(presets.get(target, ""))
        self.task_status.setText(f"{target} selected. Describe the mission or use the preset.")

    def _use_prompt_chip(self, text: str):
        prompts = {
            "Summarize this PDF": "Summarize this PDF in clear sections and list the key ideas.",
            "Explain this simply": "Explain this concept like I am new to it, with a simple example.",
            "Research AI news": "Research the latest important AI news and summarize what matters.",
            "Plan my day": "Help me plan my day around priorities, energy, and realistic time blocks.",
            "Search my notes": "Search my local notes for this topic and explain the useful parts.",
            "Compare ideas": "Compare these ideas with pros, cons, and a clear recommendation.",
        }
        self.talk_input.setText(prompts.get(text, text))
        self.talk_input.setFocus()

    def _build_talk_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("commandPanelCore")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        top = QHBoxLayout()
        title_stack = QVBoxLayout()
        title_stack.addWidget(StrongBodyLabel("Princess Core", self))
        title_stack.addWidget(CaptionLabel("Chat, listen, think, speak, and keep the current mission in view.", self))
        top.addLayout(title_stack)
        top.addStretch()
        wake_text = f"Wake: {WAKE_WORD_PHRASE}" if WAKE_WORD_ENABLED else "Wake: off"
        self.wake_status = CaptionLabel(wake_text, self)
        top.addWidget(self.wake_status)
        self.speak_toggle = PushButton(FIF.VOLUME, "Speak on" if TTS_ENABLED and SPEAK_RESPONSES else "Speak off", self)
        self.speak_toggle.setCheckable(True)
        self.speak_toggle.setChecked(bool(TTS_ENABLED and SPEAK_RESPONSES))
        self.speak_toggle.clicked.connect(self._toggle_command_speech)
        top.addWidget(self.speak_toggle)
        layout.addLayout(top)

        core_status = QHBoxLayout()
        core_status.setSpacing(8)
        self.core_state_label = self._build_core_badge("State", "Ready")
        self.core_voice_label = self._build_core_badge("Input", "Text + voice")
        self.core_speech_label = self._build_core_badge(
            "Speech",
            "On" if TTS_ENABLED and SPEAK_RESPONSES else "Off",
        )
        core_status.addWidget(self.core_state_label)
        core_status.addWidget(self.core_voice_label)
        core_status.addWidget(self.core_speech_label)
        layout.addLayout(core_status)

        self.talk_log = QTextEdit(self)
        self.talk_log.setReadOnly(True)
        self.talk_log.setMinimumHeight(230)
        self.talk_log.setObjectName("commandCoreLog")
        self.talk_log.setPlaceholderText("Princess is ready. Ask a question, give a task, or use voice.")
        layout.addWidget(self.talk_log, 1)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        for text in [
            "Summarize this PDF",
            "Explain this simply",
            "Research AI news",
            "Plan my day",
            "Search my notes",
            "Compare ideas",
        ]:
            chip = PushButton(text, self)
            chip.setObjectName("commandPromptChip")
            chip.clicked.connect(lambda checked=False, value=text: self._use_prompt_chip(value))
            chip_row.addWidget(chip)
        layout.addLayout(chip_row)

        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        self.talk_input = LineEdit(self)
        self.talk_input.setObjectName("commandCoreInput")
        self.talk_input.setPlaceholderText("Ask Princess anything, or give her a task...")
        self.talk_input.returnPressed.connect(self.send_talk_message)
        self.talk_input.setClearButtonEnabled(True)
        self.talk_input.setMinimumHeight(44)
        self.talk_input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        input_row.addWidget(self.talk_input, 1)

        self.talk_voice_btn = PushButton(FIF.MICROPHONE, "Talk", self)
        self.talk_voice_btn.clicked.connect(self.listen_for_command_voice)
        input_row.addWidget(self.talk_voice_btn)

        self.talk_send_btn = PrimaryPushButton(FIF.SEND, "Ask", self)
        self.talk_send_btn.clicked.connect(self.send_talk_message)
        input_row.addWidget(self.talk_send_btn)
        layout.addLayout(input_row)

        self.talk_status = CaptionLabel("Ready to listen.", self)
        layout.addWidget(self.talk_status)
        return panel

    def _build_core_badge(self, label: str, value: str) -> QWidget:
        badge = QFrame(self)
        badge.setObjectName("commandCoreBadge")
        badge_layout = QVBoxLayout(badge)
        badge_layout.setContentsMargins(10, 6, 10, 6)
        badge_layout.setSpacing(1)
        badge_layout.addWidget(CaptionLabel(label, self))
        badge_layout.addWidget(StrongBodyLabel(value, self))
        return badge

    def _build_right_rail(self) -> QWidget:
        rail = QWidget(self)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self._build_active_mission_panel())
        layout.addWidget(self._build_knowledge_panel())
        layout.addWidget(self._build_approvals_panel(), 1)
        return rail

    def _build_active_mission_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("commandPanelFun")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        layout.addWidget(StrongBodyLabel("Active Mission", self))
        self.mission_state = CaptionLabel("Idle. Waiting for your next instruction.", self)
        self.mission_state.setWordWrap(True)
        layout.addWidget(self.mission_state)
        for label in ["Listening", "Thinking", "Searching", "Reading", "Approval"]:
            row, value_label = self._build_mission_row(label, "standby", return_value=True)
            self.mission_rows[label] = value_label
            layout.addWidget(row)
        return panel

    def _build_mission_row(self, label: str, value: str, return_value: bool = False):
        row = QFrame(self)
        row.setObjectName("commandMiniRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(8, 5, 8, 5)
        row_layout.addWidget(BodyLabel(label, self))
        row_layout.addStretch()
        value_label = CaptionLabel(value, self)
        row_layout.addWidget(value_label)
        if return_value:
            return row, value_label
        return row

    def refresh_knowledge_documents(self):
        if not hasattr(self, "knowledge_docs_layout"):
            return
        self._clear_layout(self.knowledge_docs_layout)
        docs = knowledge_library.list_documents()[:5]
        if not docs:
            self.knowledge_docs_layout.addWidget(CaptionLabel("No indexed files yet.", self))
            return
        for doc in docs:
            self.knowledge_docs_layout.addWidget(
                self._build_mission_row(doc.title, f"{doc.status} | {doc.chunk_count}")
            )

    def add_knowledge_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Add Knowledge Files",
            str(Path.home()),
            "Knowledge Files (*.txt *.md *.markdown *.csv *.pdf *.docx);;All Files (*.*)",
        )
        if not files:
            return
        self.add_knowledge_btn.setEnabled(False)
        self.knowledge_status.setText("Indexing local files...")
        self._set_mission_status("Reading", "active")
        self.mission_state.setText("Reading local files into the private knowledge index.")
        self._knowledge_worker = KnowledgeIndexThread(files)
        self._knowledge_worker.status_update.connect(self.knowledge_status.setText)
        self._knowledge_worker.indexed.connect(self._on_knowledge_indexed)
        self._knowledge_worker.error.connect(self._on_knowledge_error)
        self._knowledge_worker.finished.connect(self._on_knowledge_finished)
        self._knowledge_worker.start()

    def _on_knowledge_indexed(self, docs: object):
        count = len(docs) if docs else 0
        self.knowledge_status.setText(f"Indexed {count} file(s) locally.")
        self._set_mission_status("Reading", "done")
        self.mission_state.setText("Knowledge Library updated. You can search local files now.")
        self.refresh_knowledge_documents()

    def _on_knowledge_error(self, error: str):
        self.knowledge_status.setText("Some files could not be indexed.")
        self._set_mission_status("Reading", "error")
        self._warn(f"Knowledge indexing warning: {error}")

    def _on_knowledge_finished(self):
        self._knowledge_worker = None
        self.add_knowledge_btn.setEnabled(True)

    def search_knowledge(self):
        query = self.knowledge_search.text().strip()
        if not query:
            self.knowledge_status.setText("Enter a local knowledge search first.")
            return
        self._set_mission_status("Reading", "searching")
        results = knowledge_library.search(query, limit=5)
        if not results:
            self.knowledge_results.setPlainText("No local matches found yet.")
            self.knowledge_status.setText("No local matches found.")
            self._set_mission_status("Reading", "standby")
            return
        lines = []
        for index, item in enumerate(results, 1):
            lines.append(
                f"{index}. {item.get('title')} | chunk {item.get('chunk_index')}\n"
                f"{item.get('snippet')}\n"
            )
        self.knowledge_results.setPlainText("\n".join(lines))
        self.knowledge_status.setText(f"{len(results)} local result(s).")
        self._set_mission_status("Reading", "done")

    def _build_knowledge_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("commandPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        layout.addWidget(StrongBodyLabel("Knowledge Library", self))
        layout.addWidget(CaptionLabel("Local books, notes, PDFs, and data stay on this machine.", self))

        self.knowledge_search = LineEdit(self)
        self.knowledge_search.setPlaceholderText("Ask about your books or notes...")
        self.knowledge_search.returnPressed.connect(self.search_knowledge)
        layout.addWidget(self.knowledge_search)

        self.knowledge_docs_layout = QVBoxLayout()
        self.knowledge_docs_layout.setSpacing(6)
        layout.addLayout(self.knowledge_docs_layout)

        actions = QHBoxLayout()
        self.add_knowledge_btn = PushButton(FIF.ADD, "Add Files", self)
        self.add_knowledge_btn.clicked.connect(self.add_knowledge_files)
        actions.addWidget(self.add_knowledge_btn)
        self.search_knowledge_btn = PushButton(FIF.SEARCH, "Search", self)
        self.search_knowledge_btn.clicked.connect(self.search_knowledge)
        actions.addWidget(self.search_knowledge_btn)
        layout.addLayout(actions)

        self.knowledge_status = CaptionLabel("Local FTS index ready.", self)
        layout.addWidget(self.knowledge_status)

        self.knowledge_results = QTextEdit(self)
        self.knowledge_results.setReadOnly(True)
        self.knowledge_results.setMinimumHeight(90)
        self.knowledge_results.setPlaceholderText("Search results from local files will appear here.")
        layout.addWidget(self.knowledge_results)
        self.refresh_knowledge_documents()
        return panel

    def _build_draft_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("commandPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        layout.addWidget(StrongBodyLabel("Creator Studio", self))

        self.platform_combo = ComboBox(self)
        self.platform_combo.addItems(["Article", "LinkedIn", "X", "Facebook", "Instagram", "Manual Note"])
        layout.addWidget(self.platform_combo)

        self.topic_input = LineEdit(self)
        self.topic_input.setPlaceholderText("Topic or task")
        layout.addWidget(self.topic_input)

        self.context_edit = QTextEdit(self)
        self.context_edit.setPlaceholderText("Add context, links, constraints, or paste source notes.")
        self.context_edit.setMinimumHeight(110)
        layout.addWidget(self.context_edit)

        actions = QHBoxLayout()
        self.generate_btn = PrimaryPushButton(FIF.EDIT, "Generate Draft", self)
        self.generate_btn.clicked.connect(self.generate_draft)
        actions.addWidget(self.generate_btn)
        self.queue_btn = PushButton(FIF.ADD, "Queue Approval", self)
        self.queue_btn.clicked.connect(self.queue_current_draft)
        actions.addWidget(self.queue_btn)
        layout.addLayout(actions)

        self.draft_status = CaptionLabel("Drafts stay local until you approve an action.", self)
        layout.addWidget(self.draft_status)

        self.draft_edit = QTextEdit(self)
        self.draft_edit.setPlaceholderText("Princess will place draft text here.")
        layout.addWidget(self.draft_edit, 1)
        return panel

    def _build_approvals_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("commandPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        layout.addWidget(StrongBodyLabel("Permission Queue", self))
        self.approval_status = CaptionLabel("Nothing pending.", self)
        layout.addWidget(self.approval_status)

        self.approvals_list = QListWidget(self)
        self.approvals_list.currentItemChanged.connect(self._on_approval_selected)
        layout.addWidget(self.approvals_list, 1)

        self.approval_preview = QTextEdit(self)
        self.approval_preview.setReadOnly(True)
        self.approval_preview.setMinimumHeight(120)
        layout.addWidget(self.approval_preview)

        actions = QHBoxLayout()
        self.approve_btn = PrimaryPushButton(FIF.ACCEPT, "Approve", self)
        self.approve_btn.clicked.connect(lambda: self.update_selected_approval("approved"))
        actions.addWidget(self.approve_btn)
        self.reject_btn = PushButton(FIF.CANCEL, "Reject", self)
        self.reject_btn.clicked.connect(lambda: self.update_selected_approval("rejected"))
        actions.addWidget(self.reject_btn)
        layout.addLayout(actions)
        return panel

    def _permission_text(self) -> str:
        daily = "daily permission required" if DAILY_PERMISSION_REQUIRED else "daily permission optional"
        approval = "posting approval required" if SOCIAL_ACTIONS_REQUIRE_APPROVAL else "posting approval off"
        posting = "connectors disabled" if not SOCIAL_POSTING_ENABLED else "connectors enabled"
        internet = "internet approval required" if INTERNET_REQUIRES_APPROVAL else "internet approval optional"
        return f"{daily} | {approval} | {posting} | {internet}"

    def load_updates(self):
        if not INTERNET_ENABLED:
            self.updates_status.setText("Internet mode is off. Local chat still works.")
            return
        self.refresh_btn.setEnabled(False)
        self.updates_status.setText("Connecting to internet sources...")
        if hasattr(self, "mission_state"):
            self.mission_state.setText("Research Radar is checking current information.")
        self._set_mission_status("Searching", "active")
        self._clear_layout(self.updates_layout)

        self._updates_thread = UpdatesLoaderThread()
        self._updates_thread.status_update.connect(self.updates_status.setText)
        self._updates_thread.loaded.connect(self._on_updates_loaded)
        self._updates_thread.finished.connect(lambda: self.refresh_btn.setEnabled(True))
        self._updates_thread.start()

    def _on_updates_loaded(self, updates: list):
        self.all_updates = updates or []
        self.updates_status.setText(
            f"{len(self.all_updates)} updates loaded." if self.all_updates else "No updates available."
        )
        if hasattr(self, "mission_state"):
            self.mission_state.setText("Signal Radar refreshed. Local chat stayed available.")
        self._set_mission_status("Searching", "done" if self.all_updates else "standby")
        self.render_updates()

    def render_updates(self):
        self._clear_layout(self.updates_layout)
        selected = self.category_combo.currentText() if hasattr(self, "category_combo") else "All"
        updates = [
            item for item in self.all_updates
            if selected == "All" or item.get("category") == selected
        ]

        if not updates:
            empty = CaptionLabel("No items in this category yet.", self)
            self.updates_layout.addWidget(empty)
            return

        for item in updates:
            card = NewsCard(item, self)
            self.updates_layout.addWidget(card)

    def _build_update_item(self, item: dict) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("commandItem")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        title = BodyLabel(item.get("title") or "Untitled update", frame)
        title.setWordWrap(True)
        layout.addWidget(title)

        meta = CaptionLabel(
            f"{item.get('category', 'General')} | {item.get('source') or 'Unknown source'}",
            frame,
        )
        layout.addWidget(meta)
        return frame

    def shuffle_updates(self):
        if not self.all_updates:
            return
        selected = self.category_combo.currentText() if hasattr(self, "category_combo") else "All"
        if selected == "All":
            random.shuffle(self.all_updates)
        else:
            selected_items = [item for item in self.all_updates if item.get("category") == selected]
            random.shuffle(selected_items)
            other_items = [item for item in self.all_updates if item.get("category") != selected]
            self.all_updates = selected_items + other_items
        self.render_updates()

    def _task_text(self) -> str:
        return self.task_input.toPlainText().strip()

    def plan_task(self):
        task = self._task_text()
        if not task:
            self._warn("Describe the task first.")
            return
        if self._plan_worker:
            return

        self.plan_task_btn.setEnabled(False)
        self.task_status.setText("Planning a safe workflow...")
        self._plan_worker = PlanWorker(self.app_combo.currentText(), task)
        self._plan_worker.status_update.connect(self.task_status.setText)
        self._plan_worker.planned.connect(self._on_task_plan_ready)
        self._plan_worker.error.connect(self._on_task_plan_error)
        self._plan_worker.finished.connect(self._on_task_plan_finished)
        self._plan_worker.start()

    def _on_task_plan_ready(self, plan: str):
        self.task_plan.setPlainText(plan)
        self.task_status.setText("Plan ready. Queue it or run the browser step when you approve.")

    def _on_task_plan_error(self, error: str):
        self.task_status.setText("Planning failed. You can still queue or run the task manually.")
        self._warn(f"Planning failed: {error}")

    def _on_task_plan_finished(self):
        self._plan_worker = None
        self.plan_task_btn.setEnabled(True)

    def queue_task(self):
        task = self._task_text()
        if not task:
            self._warn("Describe the task before queuing it.")
            return

        target = self.app_combo.currentText()
        plan = self.task_plan.toPlainText().strip()
        content = task if not plan else f"Task:\n{task}\n\nPlan:\n{plan}"
        approval_queue.add(
            title=task[:80],
            category="Task",
            action_type="external_task",
            target=target,
            content=content,
        )
        self.task_status.setText("Queued for permission. Nothing external was changed.")
        self.refresh_approvals()

    def run_browser_task(self):
        task = self._task_text()
        if not task:
            self._warn("Describe what the browser should do first.")
            return

        target = self.app_combo.currentText()
        if target not in {"Web Research", "Browser", "Multi-app workflow"}:
            self.queue_task()
            self._warn("That connector is not active yet, so I queued it for approval instead.")
            return

        instruction = (
            f"{task}\n\n"
            "Safety: do not enter passwords, publish posts, send messages, make purchases, "
            "or change account settings without explicit user confirmation in the app."
        )
        self.browser_task_requested.emit(instruction)
        self.task_status.setText("Sent to Web Agent. Log in manually inside the browser if needed.")

    def _toggle_command_speech(self):
        enabled = self.speak_toggle.isChecked()
        self.speak_toggle.setText("Speak on" if enabled else "Speak off")
        self._set_core_badge(self.core_speech_label, "Speech", "On" if enabled else "Off")
        try:
            if not tts.toggle(enabled):
                self.speak_toggle.setChecked(False)
                self.speak_toggle.setText("Speak off")
                self._set_core_badge(self.core_speech_label, "Speech", "Off")
                self.talk_status.setText("Speech is unavailable, but text still works.")
                return
        except Exception as exc:
            self.speak_toggle.setChecked(False)
            self.speak_toggle.setText("Speak off")
            self._set_core_badge(self.core_speech_label, "Speech", "Off")
            self.talk_status.setText(f"Speech warning: {exc}")

    def send_talk_message(self):
        text = self.talk_input.text().strip()
        if not text or self._talk_worker:
            return
        self.talk_input.clear()
        self._append_talk("You", text)
        self._set_talk_busy(True)
        if hasattr(self, "mission_state"):
            self.mission_state.setText("Thinking through your request locally.")
        self._set_mission_status("Thinking", "active")
        self._set_mission_status("Listening", "standby")
        self._set_core_badge(self.core_state_label, "State", "Thinking")
        self._talk_worker = TalkWorker(text, self.command_messages, self.speak_toggle.isChecked())
        self._talk_worker.status_update.connect(self.talk_status.setText)
        self._talk_worker.response_ready.connect(self._on_talk_response)
        self._talk_worker.error.connect(self._on_talk_error)
        self._talk_worker.finished.connect(self._on_talk_finished)
        self._talk_worker.start()

    def _append_talk(self, speaker: str, text: str):
        self.talk_log.append(f"<b>{speaker}:</b> {text}")

    def _on_talk_response(self, answer: str, messages: object):
        self.command_messages = list(messages)
        self._append_talk(ASSISTANT_NAME, answer)
        self._set_mission_status("Thinking", "done")
        if self.speak_toggle.isChecked():
            self.talk_status.setText("Response ready. Speaking is queued.")
            if hasattr(self, "mission_state"):
                self.mission_state.setText("Speaking response while text remains available.")
            self._set_core_badge(self.core_state_label, "State", "Speaking")
            QTimer.singleShot(2500, lambda: self._set_core_badge(self.core_state_label, "State", "Ready"))
        else:
            self.talk_status.setText("Understood. I kept this in the current conversation.")
            if hasattr(self, "mission_state"):
                self.mission_state.setText("Response ready. Waiting for your next instruction.")
            self._set_core_badge(self.core_state_label, "State", "Ready")

    def _on_talk_error(self, error: str):
        self.talk_status.setText("I could not respond, but the rest of Command Center is still available.")
        if hasattr(self, "mission_state"):
            self.mission_state.setText("The last response failed. Text, voice, and local controls remain available.")
        self._set_mission_status("Thinking", "error")
        self._set_core_badge(self.core_state_label, "State", "Ready")
        self._warn(f"Talk failed: {error}")

    def _on_talk_finished(self):
        self._talk_worker = None
        self._set_talk_busy(False)

    def _set_talk_busy(self, busy: bool):
        self.talk_send_btn.setEnabled(not busy)
        self.talk_voice_btn.setEnabled(not busy and self._voice_thread is None)
        self.talk_input.setEnabled(True)
        self.talk_input.setReadOnly(False)
        if not busy:
            self.talk_input.setFocus()

    def listen_for_command_voice(self):
        if self._voice_thread:
            return
        try:
            from gui.handlers import VoiceInputWorker
        except Exception as exc:
            self._warn(f"Voice input is unavailable: {exc}")
            return

        self.talk_status.setText("Listening for your command...")
        if hasattr(self, "mission_state"):
            self.mission_state.setText("Listening through push-to-talk.")
        self._set_mission_status("Listening", "active")
        self._set_core_badge(self.core_state_label, "State", "Listening")
        self.talk_input.setEnabled(True)
        self.talk_input.setReadOnly(False)
        self.talk_voice_btn.setEnabled(False)
        self._voice_thread = QThread(self)
        self._voice_worker = VoiceInputWorker()
        self._voice_worker.moveToThread(self._voice_thread)
        self._voice_thread.started.connect(self._voice_worker.process)
        self._voice_worker.status.connect(self.talk_status.setText)
        self._voice_worker.transcript.connect(self._on_voice_transcript)
        self._voice_worker.error.connect(self._on_voice_error)
        self._voice_worker.done.connect(self._voice_thread.quit)
        self._voice_worker.done.connect(self._voice_worker.deleteLater)
        self._voice_thread.finished.connect(self._on_voice_finished)
        self._voice_thread.finished.connect(self._voice_thread.deleteLater)
        self._voice_thread.start()

    def _on_voice_transcript(self, text: str):
        self.talk_input.setText(text)
        self.talk_status.setText(f"Heard: {text}")
        if hasattr(self, "mission_state"):
            self.mission_state.setText("Voice captured. Sending it as a normal text command.")
        self._set_mission_status("Listening", "done")
        self.send_talk_message()

    def _on_voice_error(self, error: str):
        self.talk_status.setText("I could not understand that. Try again or type it.")
        if hasattr(self, "mission_state"):
            self.mission_state.setText("Voice capture failed. Text input is still available.")
        self._set_mission_status("Listening", "error")
        self._set_core_badge(self.core_state_label, "State", "Ready")
        self._warn(f"Voice input failed: {error}")

    def _on_voice_finished(self):
        self._voice_worker = None
        self._voice_thread = None
        self.talk_voice_btn.setEnabled(self._talk_worker is None)
        self.talk_input.setEnabled(True)
        self.talk_input.setReadOnly(False)
        if self._talk_worker is None:
            self._set_core_badge(self.core_state_label, "State", "Ready")

    def _set_core_badge(self, badge: QWidget, label: str, value: str):
        labels = badge.findChildren(QLabel)
        if len(labels) >= 2:
            labels[0].setText(label)
            labels[1].setText(value)

    def _set_mission_status(self, label: str, value: str):
        status_label = self.mission_rows.get(label)
        if status_label:
            status_label.setText(value)

    def generate_draft(self):
        topic = self.topic_input.text().strip()
        context = self.context_edit.toPlainText().strip()
        if not topic and not context:
            self._warn("Draft needs a topic or context.")
            return

        self.generate_btn.setEnabled(False)
        self.draft_status.setText("Writing draft locally...")
        self._draft_worker = DraftWorker(self.platform_combo.currentText(), topic, context)
        self._draft_worker.status_update.connect(self.draft_status.setText)
        self._draft_worker.drafted.connect(self._on_draft_ready)
        self._draft_worker.error.connect(self._on_draft_error)
        self._draft_worker.finished.connect(lambda: self.generate_btn.setEnabled(True))
        self._draft_worker.start()

    def _on_draft_ready(self, text: str):
        self.draft_edit.setPlainText(text)
        self.draft_status.setText("Draft ready. Queue it when you want an approval step.")

    def _on_draft_error(self, error: str):
        self.draft_status.setText("Draft failed. Text chat is still available.")
        self._warn(f"Draft failed: {error}")

    def queue_current_draft(self):
        content = self.draft_edit.toPlainText().strip()
        if not content:
            self._warn("There is no draft to queue.")
            return

        platform = self.platform_combo.currentText()
        topic = self.topic_input.text().strip() or platform
        approval_queue.add(
            title=topic[:80],
            category="Content",
            action_type="post_draft",
            target=platform,
            content=content,
        )
        self.draft_status.setText("Queued for approval. Nothing was posted.")
        self.refresh_approvals()

    def refresh_approvals(self):
        self.approvals_list.clear()
        self.selected_approval_id = None
        items = approval_queue.list_pending()
        self.approval_status.setText(f"{len(items)} pending approval(s).")

        for item in items:
            list_item = QListWidgetItem(f"{item.target}: {item.title}")
            list_item.setData(Qt.ItemDataRole.UserRole, item.id)
            self.approvals_list.addItem(list_item)

        self.approval_preview.clear()
        self.approve_btn.setEnabled(bool(items))
        self.reject_btn.setEnabled(bool(items))

    def _on_approval_selected(self, current: QListWidgetItem, previous: QListWidgetItem):
        if not current:
            self.selected_approval_id = None
            self.approval_preview.clear()
            return

        item_id = current.data(Qt.ItemDataRole.UserRole)
        self.selected_approval_id = item_id
        item = next((entry for entry in approval_queue.list_all() if entry.id == item_id), None)
        if item:
            preview = {
                "target": item.target,
                "status": item.status,
                "created_at": item.created_at,
                "content": item.content,
            }
            self.approval_preview.setPlainText(json.dumps(preview, indent=2))

    def update_selected_approval(self, status: str):
        if not self.selected_approval_id:
            self._warn("Select an approval item first.")
            return

        item = approval_queue.update_status(self.selected_approval_id, status)
        if not item:
            self._warn("Approval item was not found.")
            return

        if status == "approved" and not SOCIAL_POSTING_ENABLED:
            self._info("Approved for manual posting. Social connectors are still disabled.")
        elif status == "approved":
            self._info("Approved. A connector can now process this action.")
        else:
            self._info("Rejected. Nothing was posted.")

        self.refresh_approvals()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _warn(self, message: str):
        InfoBar.warning(
            title="Command Center",
            content=message,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=3500,
            parent=self,
        )

    def _info(self, message: str):
        InfoBar.success(
            title="Command Center",
            content=message,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=3500,
            parent=self,
        )
