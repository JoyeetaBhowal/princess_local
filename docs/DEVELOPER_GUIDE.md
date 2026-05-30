# Princess Developer Guide

This guide explains how to run, customize, copy, and extend Princess, a local
Windows AI assistant built with Python, PySide6, Ollama, local speech-to-text,
and local Piper text-to-speech.

Princess is designed to work locally first. Internet features such as news,
trends, and web search are optional layers. Any feature that posts, publishes,
or acts on an external account should require explicit user approval.

## What You Can Copy

You can copy the project as a complete local assistant or reuse individual
parts:

- The PySide6 desktop shell in `gui/app.py`
- The ChatGPT-style chat tab in `gui/tabs/chat.py`
- The Command Center in `gui/tabs/command_center.py`
- News and trends fetching in `core/news.py`
- Local chat history in `core/history.py`
- Push-to-talk and wake-word workers in `gui/handlers.py`
- Piper TTS wrapper in `core/tts.py`
- Approval-gated action queue in `core/approvals.py`

Keep internal module paths stable unless you understand all imports that depend
on them. For example, renaming folders such as `core` or `gui` requires import
updates across the project.

## Recommended Windows Setup

Use PowerShell or Anaconda Prompt.

```powershell
cd C:\AI
git clone https://github.com/nazirlouis/ada_local.git princess_local
cd C:\AI\princess_local

conda create -n princess python=3.11 -y
conda activate princess
pip install -r requirements.txt
```

Install Ollama from:

```text
https://ollama.com/download
```

Pull the recommended model:

```powershell
ollama pull qwen3:1.7b
ollama list
```

Run the app:

```powershell
cd C:\AI\princess_local
& C:\Users\LoneWolfe\miniconda3\envs\princess\python.exe main.py
```

If your Python path is different, replace it with the path to your Conda
environment.

## Main Configuration

Most user-facing configuration lives in `config.py`.

Important values:

```python
ASSISTANT_NAME = "Princess"
RESPONDER_MODEL = "qwen3:1.7b"
OLLAMA_URL = "http://localhost:11434/api"

TEXT_CHAT_ENABLED = True
VOICE_ASSISTANT_ENABLED = True
PUSH_TO_TALK_ENABLED = True
WAKE_WORD_ENABLED = True

TTS_ENABLED = True
TTS_PROVIDER = "piper"
SPEAK_RESPONSES = True

SOCIAL_ACTIONS_REQUIRE_APPROVAL = True
SOCIAL_POSTING_ENABLED = False
```

For a first run on a new machine, keep text chat working before enabling voice:

```python
TEXT_CHAT_ENABLED = True
VOICE_ASSISTANT_ENABLED = False
WAKE_WORD_ENABLED = False
```

Then enable features in this order:

1. Text chat
2. News and Command Center
3. Push-to-talk voice input
4. Text-to-speech
5. Wake word
6. External account connectors

## Project Structure

```text
main.py                         App entry point
config.py                       Central settings
requirements.txt                Python dependencies

core/
  approvals.py                  Approval queue for external actions
  history.py                    SQLite chat history
  llm.py                        Ollama HTTP session and model helpers
  news.py                       News and trends fetchers
  tts.py                        Piper TTS
  function_executor.py          Local command/action execution

gui/
  app.py                        Main window and tab registration
  handlers.py                   Chat, voice, wake word, and generation workers
  styles.py                     Global Fluent dark theme
  tabs/
    chat.py                     Main chat UI
    command_center.py           News, voice chat, drafts, approvals
    briefing.py                 News briefing UI
    planner.py                  Tasks, timers, schedule
    settings.py                 Runtime settings
  components/
    news_card.py                Clickable source news cards
    message_bubble.py           Chat message rendering
```

## How Chat Works

The chat flow is:

1. User types or speaks a prompt.
2. `gui/tabs/chat.py` emits a signal.
3. `gui/handlers.py` creates a background `ChatWorker`.
4. `ChatWorker` sends messages to Ollama.
5. Response text is added to the UI and saved in SQLite history.
6. If speech is enabled, completed sentences are sent to `core/tts.py`.

The chat input should remain usable even when voice features exist. Do not make
text chat depend on a microphone, wake word, Whisper, Piper, or PyAudio.

## How Command Center Works

`gui/tabs/command_center.py` combines:

- Signal Radar: categorized news and trends
- Mission Launcher: plan, queue, or send approved web tasks to the Web Agent
- Talk to Princess: a small conversational panel with local memory
- Creator Studio: local draft generation
- Permission Queue: approval-gated drafts/actions

News cards use `gui/components/news_card.py`. Clicking a card opens the source
URL with `QDesktopServices.openUrl`.

The Talk panel uses the same Ollama model as chat. Push-to-talk imports the
existing `VoiceInputWorker` from `gui/handlers.py`. Spoken responses reuse
`core/tts.py`.

The Mission Launcher emits a browser-task signal that `gui/app.py` routes to
the Web Agent tab. Browser tasks are intentionally explicit: the user clicks
`Run in Browser`, logs in manually when needed, and approves sensitive actions
before posting, sending, buying, booking, or changing account data.

## Approval-Gated External Actions

External actions should not run silently. This includes:

- Posting to social media
- Sending emails or messages
- Logging into external accounts
- Publishing articles
- Buying, selling, booking, or deleting data

Use `core/approvals.py` for anything that needs permission:

```python
from core.approvals import approval_queue

approval_queue.add(
    title="LinkedIn launch post",
    category="Content",
    action_type="post_draft",
    target="LinkedIn",
    content="Draft text here",
)
```

`SOCIAL_POSTING_ENABLED` should stay `False` until a real connector exists and
the user has explicitly approved posting.

## Adding a Social Connector Safely

Add one platform at a time. Prefer official APIs and OAuth. Do not ask users to
paste passwords into the app.

Recommended connector flow:

1. User connects account with OAuth.
2. Store only the minimum required token data.
3. Generate a draft locally.
4. Queue the draft in `approval_queue`.
5. User reviews it.
6. User clicks a clear final action such as `Post now`.
7. Connector posts only that approved item.
8. Store the result and source URL.

Do not build hidden background autoposting. If recurring posting is added later,
each queued post should still require approval unless the user creates a very
explicit rule.

## Adding a New Tab

1. Create a widget in `gui/tabs/your_tab.py`.
2. Import it in `gui/app.py`.
3. Add it in `_init_window()` with `addSubInterface`.
4. If it is heavy, wrap it with `LazyTab`.
5. Keep long-running work in `QThread` workers.

Example pattern:

```python
self.my_tab_lazy = LazyTab(MyTab, "myTabInterface")
self.addSubInterface(self.my_tab_lazy, FIF.ROBOT, "My Tab")
```

## Threading Rules

Keep the PySide6 UI thread responsive:

- Do network calls in a `QThread`.
- Do Ollama calls in a `QThread`.
- Do microphone recording and transcription in a `QThread`.
- Do not update widgets directly from non-UI threads. Use Qt signals.
- If a feature fails, show a status or warning and keep chat available.

## Local Data

Local app data is stored under `data/`:

- `data/chat_history.db`
- `data/tasks.db`
- `data/approvals.json`

These files are runtime state. If you copy the app for a new user, consider
removing runtime data first:

```powershell
Remove-Item .\data\chat_history.db -ErrorAction SilentlyContinue
Remove-Item .\data\tasks.db -ErrorAction SilentlyContinue
Remove-Item .\data\approvals.json -ErrorAction SilentlyContinue
```

Only run cleanup commands from the project folder and only when you mean to
reset local state.

## Testing and Verification

Compile Python files:

```powershell
& C:\Users\LoneWolfe\miniconda3\envs\princess\python.exe -m compileall config.py core gui main.py
```

Verify Ollama:

```powershell
curl http://localhost:11434/api/tags
ollama list
```

Verify PySide imports:

```powershell
& C:\Users\LoneWolfe\miniconda3\envs\princess\python.exe -c "from gui.app import create_app; print('GUI import OK')"
```

Run the app:

```powershell
cd C:\AI\princess_local
& C:\Users\LoneWolfe\miniconda3\envs\princess\python.exe main.py
```

Basic manual test checklist:

- App opens.
- Chat input accepts typing.
- New Chat resets the input and keeps it writable.
- Princess responds through Ollama.
- Command Center loads news.
- Clicking a news card opens the article source.
- Push-to-talk transcribes a short phrase.
- TTS speaks only when enabled.
- Wake word does not start unless enabled in config.

## Common Problems

### Ollama connection error

Check that Ollama is running:

```powershell
curl http://localhost:11434/api/tags
```

If needed:

```powershell
ollama serve
ollama pull qwen3:1.7b
```

### Chat input is locked

Make sure:

```python
TEXT_CHAT_ENABLED = True
```

The chat UI should never depend on voice state. If a new feature disables text
input, reset generation/listening state and keep `LineEdit` enabled.

### Microphone fails

Check Windows settings:

```text
Settings > Privacy & security > Microphone
Allow apps to access your microphone
Allow desktop apps to access your microphone
```

Test sounddevice:

```powershell
& C:\Users\LoneWolfe\miniconda3\envs\princess\python.exe -c "import sounddevice as sd; print(sd.query_devices())"
```

### News is empty

DuckDuckGo may rate-limit. `core/news.py` includes an RSS fallback. If both fail,
check internet access and firewall settings.

## Copying the App for Another Person

Recommended copy checklist:

1. Copy the project folder.
2. Remove local runtime data if you do not want to share history.
3. Create a new Conda environment.
4. Install requirements.
5. Pull the Ollama model.
6. Update `ASSISTANT_NAME` and persona in `config.py`.
7. Run `compileall`.
8. Launch and test text chat first.

Example:

```powershell
Copy-Item C:\AI\princess_local C:\AI\my_assistant_local -Recurse
cd C:\AI\my_assistant_local
conda create -n my_assistant python=3.11 -y
conda activate my_assistant
pip install -r requirements.txt
ollama pull qwen3:1.7b
python main.py
```

## Development Principles

- Local-first by default.
- Text chat must always remain available.
- Voice is additive, not a replacement for typing.
- Wake word is optional and reversible.
- TTS failure must not block text responses.
- News cards should open source URLs.
- External actions require explicit approval.
- Do not add unsafe, medical, legal, or financial advice behavior.
- Keep UI changes scoped and verify startup after edits.
