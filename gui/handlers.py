from PySide6.QtCore import QObject, Signal, QThread, QTimer
import json
import re
import time
import threading

from config import (
    ASSISTANT_SYSTEM_PROMPT, RESPONDER_MODEL, OLLAMA_URL, MAX_HISTORY,
    PUSH_TO_TALK_ENABLED, PUSH_TO_TALK_STT_MODEL, PUSH_TO_TALK_RECORD_SECONDS,
    ROUTER_ENABLED, TTS_ENABLED, SPEAK_RESPONSES, WAKE_WORD_PHRASE,
    WAKE_WORD_LISTEN_SECONDS, WAKE_WORD_RECORD_SECONDS
)
from core.llm import route_query, should_bypass_router, http_session
from core.tts import tts, SentenceBuffer
from core.history import history_manager
from core.model_manager import ensure_exclusive_qwen
from core.model_persistence import ensure_qwen_loaded, mark_qwen_used
from core.settings_store import settings as app_settings
from core.function_executor import executor as function_executor

# Functions that are actions (not passthrough)
ACTION_FUNCTIONS = {"control_light", "set_timer", "set_alarm", "create_calendar_event", "add_task", "web_search"}
AUDIO_CAPTURE_LOCK = threading.Lock()


# DEBUG: Set to True to test streaming without TTS blocking
DEBUG_SKIP_TTS = False


class ChatWorker(QObject):
    """Background worker for LLM processing with Qt signals."""
    
    # Signals for thread-safe UI updates
    thought_chunk = Signal(str)
    response_chunk = Signal(str)
    think_start = Signal(bool)  # Pass whether thinking is enabled
    think_end = Signal()
    simple_response = Signal(str)
    error = Signal(str)
    status = Signal(str)
    done = Signal()
    ui_update = Signal()
    toast = Signal(str, bool)  # message, success
    set_timer_signal = Signal(int, str)  # seconds, label
    reload_alarms = Signal()  # trigger alarm list reload
    reload_calendar = Signal()  # trigger calendar refresh
    search_start = Signal(str)  # query
    search_end = Signal()
    
    def __init__(self, user_text: str, messages: list, is_tts_enabled: bool, 
                 current_session_id: str, stop_event):
        super().__init__()
        self.user_text = user_text
        self.messages = messages
        self.is_tts_enabled = is_tts_enabled
        self.current_session_id = current_session_id
        self.stop_event = stop_event
        self.full_response = ""

    def _queue_tts_sentence(self, sentence: str):
        """Queue speech without letting TTS failures affect chat output."""
        if not self.is_tts_enabled or DEBUG_SKIP_TTS or self.stop_event.is_set():
            return
        try:
            if not tts.piper_exe and not tts.toggle(True):
                self.status.emit("TTS unavailable")
                return
            tts.queue_sentence(sentence)
        except Exception as e:
            self.status.emit(f"TTS warning: {e}")
        
    def process(self):
        """Background processing method."""
        try:
            if should_bypass_router(self.user_text):
                func_name = "nonthinking"
                params = {"prompt": self.user_text}
            else:
                self.status.emit("Routing...")
                func_name, params = route_query(self.user_text)
            
            # Handle action functions
            if func_name in ACTION_FUNCTIONS:
                self.status.emit(f"Executing {func_name}...")
                
                # Emit search start for web_search
                if func_name == "web_search":
                    query = params.get("query", "")
                    self.search_start.emit(query)
                
                result = function_executor.execute(func_name, params)
                
                # Emit search end for web_search
                if func_name == "web_search":
                    self.search_end.emit()
                
                # Emit toast notification
                self.toast.emit(result["message"], result["success"])
                
                # Emit GUI update signals for specific actions
                if func_name == "set_timer" and result["success"]:
                    seconds = result.get("data", {}).get("seconds", 0)
                    label = result.get("data", {}).get("label", "Timer")
                    self.set_timer_signal.emit(seconds, label)
                elif func_name == "set_alarm" and result["success"]:
                    self.reload_alarms.emit()
                elif func_name == "create_calendar_event" and result["success"]:
                    self.reload_calendar.emit()
                
                # Enable thinking for web_search
                enable_thinking = (func_name == "web_search")
                
                # Generate Qwen response with context
                self._generate_response_with_context(func_name, result, enable_thinking)
                
            # Handle get_system_info (context query)
            elif func_name == "get_system_info":
                self.status.emit("Gathering system info...")
                result = function_executor.execute(func_name, params)
                
                # Generate Qwen response with full system context
                self._generate_response_with_context(func_name, result, enable_thinking=True)
            
            # Handle thinking/nonthinking (direct passthrough)
            elif func_name in ("thinking", "nonthinking"):
                enable_thinking = (func_name == "thinking")
                self._stream_qwen_response(enable_thinking)
            
            # Unknown function - treat as nonthinking
            else:
                self._stream_qwen_response(False)

        except Exception as e:
            self.error.emit(str(e))
        
        finally:
            self.done.emit()
    
    def _generate_response_with_context(self, func_name: str, result: dict, enable_thinking: bool = False):
        """Generate a Qwen response with function result as context."""
        # Build system message with context
        if func_name == "get_system_info" and result.get("success"):
            data = result.get("data", {})
            context_parts = []
            
            if data.get("timers"):
                context_parts.append(f"Active timers: {data['timers']}")
            if data.get("alarms"):
                context_parts.append(f"Alarms: {data['alarms']}")
            if data.get("calendar_today"):
                context_parts.append(f"Today's events: {data['calendar_today']}")
            if data.get("tasks"):
                pending = [t for t in data['tasks'] if not t.get('completed')]
                context_parts.append(f"Pending tasks: {len(pending)} items")
            if data.get("smart_devices"):
                on_devices = [d['name'] for d in data['smart_devices'] if d.get('is_on')]
                context_parts.append(f"Devices on: {on_devices if on_devices else 'none'}")
            if data.get("weather"):
                w = data['weather']
                context_parts.append(f"Weather: {w.get('temp')}°F, {w.get('condition')}")
            if data.get("news"):
                news_items = data['news']
                if news_items:
                    news_titles = [item.get('title', '')[:50] for item in news_items[:3]]
                    context_parts.append(f"Top news: {', '.join(news_titles)}")
            
            context_msg = "SYSTEM CONTEXT:\n" + "\n".join(context_parts) if context_parts else ""
        else:
            # Action function result
            status = "succeeded" if result.get("success") else "failed"
            
            # Special handling for web_search to include full results
            if func_name == "web_search" and result.get("success") and result.get("data"):
                search_data = result.get("data", {})
                query = search_data.get("query", "")
                results = search_data.get("results", [])
                
                if results:
                    context_msg = f"SEARCH RESULTS for '{query}':\n\n"
                    for i, r in enumerate(results, 1):
                        title = r.get("title", "")
                        body = r.get("body", "")
                        url = r.get("url", "")
                        context_msg += f"{i}. {title}\n"
                        context_msg += f"   {body}\n"
                        context_msg += f"   URL: {url}\n\n"
                    context_msg += "Use the above search results to answer the user's question. Include relevant URLs in your response using markdown link format [text](url)."
                else:
                    context_msg = f"ACTION RESULT: {func_name} {status}. {result.get('message', '')}"
            else:
                context_msg = f"ACTION RESULT: {func_name} {status}. {result.get('message', '')}"
        
        # Prepare messages with context
        max_hist = app_settings.get("general.max_history", MAX_HISTORY)
        if len(self.messages) > max_hist:
            self.messages = [self.messages[0]] + self.messages[-(max_hist-1):]
        
        # Add context as system message and user's original question
        context_prompt = f"{context_msg}\n\nUser asked: {self.user_text}\n\nRespond naturally and concisely."
        self.messages.append({'role': 'user', 'content': context_prompt})
        
        self.ui_update.emit()
        self.status.emit("Generating response...")
        
        model = app_settings.get("models.chat", RESPONDER_MODEL)
        ollama_url = app_settings.get("ollama_url", OLLAMA_URL)
        if ROUTER_ENABLED:
            ensure_qwen_loaded()  # Use persistence manager
            mark_qwen_used()
            ensure_exclusive_qwen(model)
        
        payload = {
            "model": model,
            "messages": self.messages,
            "stream": True,
            "think": enable_thinking,  # Enable thinking for web_search
            "keep_alive": "5m"  # Longer keep-alive for voice assistant
        }
        
        sentence_buffer = SentenceBuffer()
        self.full_response = ""
        self.think_start.emit(enable_thinking)
        
        with http_session.post(f"{ollama_url}/api/chat", json=payload, stream=True) as r:
            r.raise_for_status()
            
            for line in r.iter_lines():
                if self.stop_event.is_set():
                    break
                    
                if line:
                    try:
                        chunk = json.loads(line.decode('utf-8'))
                        msg = chunk.get('message', {})
                        
                        # Handle thinking chunks (for web_search)
                        if 'thinking' in msg and msg['thinking']:
                            thought = msg['thinking']
                            self.thought_chunk.emit(thought)
                        
                        if 'content' in msg and msg['content']:
                            content = msg['content']
                            self.full_response += content
                            self.response_chunk.emit(content)
                            
                            if self.is_tts_enabled and not DEBUG_SKIP_TTS:
                                sentences = sentence_buffer.add(content)
                                for s in sentences:
                                    self._queue_tts_sentence(s)
                    except:
                        continue
        
        self.think_end.emit()
        
        if self.is_tts_enabled and not DEBUG_SKIP_TTS and not self.stop_event.is_set():
            rem = sentence_buffer.flush()
            if rem:
                self._queue_tts_sentence(rem)
        
        self.messages.append({'role': 'assistant', 'content': self.full_response})
        
        if self.current_session_id:
            history_manager.add_message(self.current_session_id, "assistant", self.full_response)
    
    def _stream_qwen_response(self, enable_thinking: bool):
        """Stream a direct Qwen response (for thinking/nonthinking)."""
        max_hist = app_settings.get("general.max_history", MAX_HISTORY)
        if len(self.messages) > max_hist:
            self.messages = [self.messages[0]] + self.messages[-(max_hist-1):]
        
        self.messages.append({'role': 'user', 'content': self.user_text})
        
        self.ui_update.emit()
        self.status.emit("Generating...")
        
        model = app_settings.get("models.chat", RESPONDER_MODEL)
        ensure_qwen_loaded()  # Use persistence manager
        mark_qwen_used()
        ensure_exclusive_qwen(model)
        ollama_url = app_settings.get("ollama_url", OLLAMA_URL)
        
        payload = {
            "model": model,
            "messages": self.messages,
            "stream": True,
            "think": enable_thinking,
            "keep_alive": "5m"  # Longer keep-alive for voice assistant
        }
        
        sentence_buffer = SentenceBuffer()
        self.full_response = ""
        self.think_start.emit(enable_thinking)

        if not ROUTER_ENABLED and not enable_thinking:
            payload["stream"] = False
            with http_session.post(f"{ollama_url}/api/chat", json=payload, timeout=120) as r:
                r.raise_for_status()
                self.full_response = r.json().get("message", {}).get("content", "")
            if self.full_response:
                self.simple_response.emit(self.full_response)
                self._queue_tts_sentence(self.full_response)
            self.messages.append({'role': 'assistant', 'content': self.full_response})
            self.status.emit("Ready")
            return

        with http_session.post(f"{ollama_url}/api/chat", json=payload, stream=True) as r:
            r.raise_for_status()
            
            for line in r.iter_lines():
                if self.stop_event.is_set():
                    break
                    
                if line:
                    try:
                        chunk = json.loads(line.decode('utf-8'))
                        msg = chunk.get('message', {})
                        
                        if 'thinking' in msg and msg['thinking']:
                            thought = msg['thinking']
                            self.thought_chunk.emit(thought)
                            
                        if 'content' in msg and msg['content']:
                            content = msg['content']
                            self.full_response += content
                            self.response_chunk.emit(content)
                            
                            if self.is_tts_enabled and not DEBUG_SKIP_TTS:
                                sentences = sentence_buffer.add(content)
                                for s in sentences:
                                    self._queue_tts_sentence(s)
                                    
                    except:
                        continue
        
        self.think_end.emit()
        
        if self.is_tts_enabled and not DEBUG_SKIP_TTS and not self.stop_event.is_set():
            rem = sentence_buffer.flush()
            if rem:
                self._queue_tts_sentence(rem)
        
        self.messages.append({'role': 'assistant', 'content': self.full_response})
        
        if self.current_session_id:
            history_manager.add_message(self.current_session_id, "assistant", self.full_response)


class VoiceInputWorker(QObject):
    """Record one bounded push-to-talk command and transcribe it."""

    _whisper_model = None
    _whisper_model_key = None

    transcript = Signal(str)
    error = Signal(str)
    status = Signal(str)
    done = Signal()

    def _record_and_transcribe(self, seconds: float):
        tmp_path = None
        import os
        import tempfile
        import wave
        import numpy as np
        import torch
        import sounddevice as sd
        from faster_whisper import WhisperModel

        with AUDIO_CAPTURE_LOCK:
            sample_rate = 16000
            frames = int(seconds * sample_rate)
            audio = sd.rec(frames, samplerate=sample_rate, channels=1, dtype="float32")
            sd.wait()

            peak = float(np.max(np.abs(audio))) if audio.size else 0.0
            if peak < 0.003:
                return None, "No microphone signal was detected."

            try:
                pcm16 = np.clip(audio, -1.0, 1.0)
                pcm16 = (pcm16 * 32767).astype(np.int16)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = tmp.name

                with wave.open(tmp_path, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(sample_rate)
                    wav_file.writeframes(pcm16.tobytes())

                device = "cuda" if torch.cuda.is_available() else "cpu"
                compute_type = "float16" if device == "cuda" else "int8"
                model_key = (PUSH_TO_TALK_STT_MODEL, device, compute_type)
                if VoiceInputWorker._whisper_model_key != model_key:
                    VoiceInputWorker._whisper_model = WhisperModel(
                        PUSH_TO_TALK_STT_MODEL,
                        device=device,
                        compute_type=compute_type,
                    )
                    VoiceInputWorker._whisper_model_key = model_key
                model = VoiceInputWorker._whisper_model
                segments, _info = model.transcribe(
                    tmp_path,
                    language="en",
                    vad_filter=True,
                    beam_size=1,
                )
                text = " ".join(segment.text.strip() for segment in segments).strip()
                return text, None
            finally:
                if tmp_path:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

    def process(self):
        try:
            self.status.emit(f"Listening... {PUSH_TO_TALK_RECORD_SECONDS}s")
            text, error = self._record_and_transcribe(PUSH_TO_TALK_RECORD_SECONDS)
            self.status.emit("Transcribing...")
            if error:
                self.error.emit(error)
                return
            if text:
                self.transcript.emit(text)
            else:
                self.error.emit("No speech was transcribed.")
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.done.emit()


class WakeWordWorker(VoiceInputWorker):
    """Local transcription-based wake listener for a custom phrase."""

    wake_detected = Signal()

    def __init__(self, stop_event):
        super().__init__()
        self.stop_event = stop_event
        self.phrase = WAKE_WORD_PHRASE.lower().strip()
        self.chunk_seconds = WAKE_WORD_LISTEN_SECONDS

    def _log_wake(self, message: str):
        try:
            from pathlib import Path
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            with (log_dir / "wake_word.log").open("a", encoding="utf-8") as log:
                log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
        except Exception:
            pass

    def _is_wake_phrase(self, text: str) -> bool:
        normalized = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        phrase = re.sub(r"[^a-z0-9 ]+", " ", self.phrase)
        phrase = re.sub(r"\s+", " ", phrase).strip()
        wake_variants = {
            phrase,
            phrase.replace("princess", "princes"),
            "princess",
            "princes",
            "princesses",
        }
        return any(variant and variant in normalized for variant in wake_variants)

    def _strip_wake_phrase(self, text: str) -> str:
        cleaned = re.sub(re.escape(WAKE_WORD_PHRASE), "", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bhey[\s,.-]+(princess|princes|princesses)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(princess|princes|princesses)\b", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip(" ,.!?")

    def process(self):
        try:
            self.status.emit(f"Listening for {WAKE_WORD_PHRASE}")
            self._log_wake(f"started phrase={WAKE_WORD_PHRASE!r} chunk_seconds={self.chunk_seconds}")
            while not self.stop_event.is_set():
                text, error = self._record_and_transcribe(self.chunk_seconds)
                if self.stop_event.is_set():
                    break
                if error:
                    if error == "No microphone signal was detected.":
                        self._log_wake("quiet_chunk")
                        time.sleep(0.1)
                        continue
                    if "microphone" in error.lower() or "device" in error.lower():
                        self.error.emit(
                            "I couldn't access the microphone. Please check Windows microphone permissions."
                        )
                        self._log_wake(f"microphone_error={error!r}")
                        break
                    self._log_wake(f"ignored_audio_error={error!r}")
                    continue
                if text:
                    self._log_wake(f"heard={text!r}")
                if text and self._is_wake_phrase(text):
                    self.wake_detected.emit()
                    self.status.emit("Wake word detected")
                    self._log_wake("wake_detected")
                    same_utterance_command = self._strip_wake_phrase(text)
                    if same_utterance_command:
                        self._log_wake(f"same_utterance_command={same_utterance_command!r}")
                        self.transcript.emit(same_utterance_command)
                        self.status.emit(f"Listening for {WAKE_WORD_PHRASE}")
                        continue
                    if self.stop_event.wait(0.4):
                        break
                    self.status.emit(f"Listening... {WAKE_WORD_RECORD_SECONDS}s")
                    command, command_error = self._record_and_transcribe(WAKE_WORD_RECORD_SECONDS)
                    if command_error:
                        self.error.emit("I couldn't understand that. Please try again.")
                        self._log_wake(f"command_error={command_error!r}")
                    elif command:
                        cleaned = self._strip_wake_phrase(command)
                        self._log_wake(f"command={command!r} cleaned={cleaned!r}")
                        self.transcript.emit(cleaned or command)
                    else:
                        self.error.emit("I couldn't understand that. Please try again.")
                        self._log_wake("command_empty")
                    self.status.emit(f"Listening for {WAKE_WORD_PHRASE}")
                else:
                    time.sleep(0.1)
        except Exception as e:
            self._log_wake(f"fatal_error={e!r}")
            self.error.emit(f"Wake word failed to start. Text and push-to-talk are still available. {e}")
        finally:
            self._log_wake("stopped")
            self.done.emit()


class ChatHandlers(QObject):
    """Encapsulates all chat-related event handlers and state."""
    
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        
        # State
        self.messages = [
            {'role': 'system', 'content': ASSISTANT_SYSTEM_PROMPT}
        ]
        self.current_session_id = None
        self.is_tts_enabled = bool(TTS_ENABLED and SPEAK_RESPONSES)
        self._stop_event = None
        self._worker = None
        self._thread = None
        self._voice_worker = None
        self._voice_thread = None
        self._wake_worker = None
        self._wake_thread = None
        self._wake_stop_event = None
        
        self.streaming_state = {
            'response_bubble': None,
            'thinking_ui': None,
            'search_indicator': None,
            'response_buffer': '',
            'thought_buffer': '',
            'is_generating': False,
            'thinking_enabled': False
        }

        # Throttling Timer for UI Updates
        self.ui_throttle_timer = QTimer(self)
        self.ui_throttle_timer.setInterval(100) # 10 tokens per second or so
        self.ui_throttle_timer.timeout.connect(self._flush_ui_buffers)
        self.last_scroll_time = 0
    
    def refresh_sidebar(self):
        """Reload the persistent sidebar with conversation history."""
        self.main_window.refresh_sidebar(self.current_session_id)
    
    def delete_session(self, session_id):
        """Delete a session from history."""
        history_manager.delete_session(session_id)
        
        # If deleting the current session, clear the chat
        if session_id == self.current_session_id:
            self.current_session_id = None
            self.messages = [self.messages[0]]  # Keep system prompt
            self.main_window.clear_chat_display()
        
        self.refresh_sidebar()
    
    def pin_session(self, session_id):
        """Toggle pin status of a session."""
        is_pinned = history_manager.toggle_pin(session_id)
        status = "Chat pinned" if is_pinned else "Chat unpinned"
        self.main_window.set_status(status)
        self.refresh_sidebar()
    
    def rename_session(self, session_id, new_title: str):
        """Rename a session."""
        history_manager.update_session_title(session_id, new_title)
        self.refresh_sidebar()

    def load_session(self, session_id):
        """Load a specific chat session."""
        self.current_session_id = session_id
        db_messages = history_manager.get_messages(session_id)
        
        # Reset message context (keep system prompt)
        self.messages = [self.messages[0]]
        self.main_window.clear_chat_display()
        
        for msg in db_messages:
            role = msg['role']
            content = msg['content']
            
            # Reconstruct LLM context
            self.messages.append({'role': role, 'content': content})
            
            # Reconstruct UI bubbles
            self.main_window.add_message_bubble(role, content)
        
        self.refresh_sidebar()  # Update highlight

    def init_new_session(self, first_message):
        """Create a new session in DB."""
        title = first_message[:30] + "..." if len(first_message) > 30 else first_message
        self.current_session_id = history_manager.create_session(title=title)
        return self.current_session_id
    
    def _on_think_start(self, thinking_enabled: bool):
        """Called when generation starts, with thinking mode flag."""
        self.streaming_state['thinking_enabled'] = thinking_enabled
        if thinking_enabled and self.streaming_state['thinking_ui']:
            self.streaming_state['thinking_ui'].setVisible(True)
        self.ui_throttle_timer.start()

    def _on_thought_chunk(self, text):
        self.streaming_state['thought_buffer'] += text

    def _on_response_chunk(self, text):
        self.streaming_state['response_buffer'] += text
            
    def _flush_ui_buffers(self):
        """Flush accumulated text to the UI components."""
        updated = False
        
        # Update Thinking UI
        if self.streaming_state['thought_buffer'] and self.streaming_state['thinking_ui']:
            self.streaming_state['thinking_ui'].add_text(self.streaming_state['thought_buffer'])
            self.streaming_state['thought_buffer'] = ''
            updated = True
            
        # Update Response Bubble
        if self.streaming_state['response_buffer'] and self.streaming_state['response_bubble']:
            self.streaming_state['response_bubble'].append_text(self.streaming_state['response_buffer'])
            self.streaming_state['response_buffer'] = ''
            updated = True
            
        if updated:
            self.main_window.scroll_to_bottom()

    def _on_think_end(self):
        # Final flush
        self._flush_ui_buffers()
        # Only mark complete if thinking was enabled
        if self.streaming_state.get('thinking_enabled') and self.streaming_state['thinking_ui']:
            self.streaming_state['thinking_ui'].complete()
                
    def _on_simple_response(self, text):
        self.main_window.add_message_bubble("assistant", text)
        
        # Save simple response to history
        if self.current_session_id:
            history_manager.add_message(self.current_session_id, "assistant", text)
    
    def _on_toast(self, message: str, success: bool):
        """Show toast notification for function execution result."""
        from gui.components.toast import ToastNotification
        ToastNotification.show_toast(self.main_window, message, success)
    
    def _on_set_timer(self, seconds: int, label: str):
        """Update timer GUI when set via voice command."""
        try:
            # Access timer component via planner lazy tab
            if hasattr(self.main_window, 'planner_lazy') and self.main_window.planner_lazy.actual_widget:
                planner = self.main_window.planner_lazy.actual_widget
                if hasattr(planner, 'timer_component'):
                    planner.timer_component.set_and_start(seconds, label)
        except Exception as e:
            print(f"[Handlers] Timer update failed: {e}")
    
    def _on_reload_alarms(self):
        """Reload alarms GUI when added via voice command."""
        try:
            # Access alarm component via planner lazy tab
            if hasattr(self.main_window, 'planner_lazy') and self.main_window.planner_lazy.actual_widget:
                planner = self.main_window.planner_lazy.actual_widget
                if hasattr(planner, 'alarm_component'):
                    planner.alarm_component.reload()
        except Exception as e:
            print(f"[Handlers] Alarm reload failed: {e}")

    def _on_reload_calendar(self):
        """Reload calendar GUI when event added via voice command."""
        try:
            # Access schedule component via planner lazy tab
            if hasattr(self.main_window, 'planner_lazy') and self.main_window.planner_lazy.actual_widget:
                planner = self.main_window.planner_lazy.actual_widget
                if hasattr(planner, 'schedule_component'):
                    planner.schedule_component.refresh_events()
        except Exception as e:
            print(f"[Handlers] Calendar reload failed: {e}")
    
    def _on_search_start(self, query: str):
        """Called when web search starts."""
        if self.streaming_state['search_indicator']:
            self.streaming_state['search_indicator'].add_query(query)
            self.streaming_state['search_indicator'].setVisible(True)
    
    def _on_search_end(self):
        """Called when web search completes."""
        if self.streaming_state['search_indicator']:
            self.streaming_state['search_indicator'].complete()
            
    def _on_error(self, text):
        self.main_window.add_message_bubble("system", f"Error: {text}", is_thinking=True)
            
    def _on_status(self, text):
        self.main_window.set_status(text)
        if text == "Ready":
            self._end_generation_state()

    def _on_done(self):
        self.ui_throttle_timer.stop()
        self._flush_ui_buffers() # Final final flush
        self._end_generation_state()
    
    def _start_generation_state(self):
        """Switch UI to generating mode."""
        self.streaming_state['is_generating'] = True
        self.main_window.set_generating_state(True)

    def _end_generation_state(self):
        """Switch UI back to idle mode."""
        self.streaming_state['is_generating'] = False
        self.main_window.set_generating_state(False)

    def stop_generation(self):
        """Stop current generation."""
        tts.stop()
        if self.streaming_state['is_generating'] and self._stop_event:
            self._stop_event.set()
            self.main_window.set_status("Stopping...")
            self.ui_throttle_timer.stop()

    def send_message(self, text: str):
        """Handle sending a new message."""
        tts.stop()  # Interrupt previous speech
        text = text.strip()
        if not text:
            return
        
        # Add User Message UI
        self.main_window.add_message_bubble("user", text)
        self.main_window.clear_input()
        
        # Start new session if needed
        if not self.current_session_id:
            self.init_new_session(text)
            self.refresh_sidebar()

        # Save to DB
        history_manager.add_message(self.current_session_id, "user", text)
        
        self._start_generation_state()
        
        # Create stop event
        import threading
        self._stop_event = threading.Event()
        
        # Create streaming UI containers
        from gui.components import MessageBubble, ThinkingExpander, SearchIndicator
        
        thinking_ui = ThinkingExpander()
        search_indicator = SearchIndicator()
        response_bubble = MessageBubble("assistant", "")
        
        self.streaming_state['thinking_ui'] = thinking_ui
        self.streaming_state['search_indicator'] = search_indicator
        self.streaming_state['response_bubble'] = response_bubble
        self.streaming_state['response_buffer'] = ''
        self.streaming_state['thought_buffer'] = ''
        self.streaming_state['thinking_enabled'] = False  # Will be set by think_start signal
        
        # Hide indicators initially - will be shown only if their respective modes are enabled
        thinking_ui.setVisible(False)
        search_indicator.setVisible(False)
        
        # Add to UI
        self.main_window.add_streaming_widgets(thinking_ui, search_indicator, response_bubble)

        # Start background worker
        self._thread = QThread(self)
        self._worker = ChatWorker(
            text, self.messages.copy(), self.is_tts_enabled,
            self.current_session_id, self._stop_event
        )
        self._worker.moveToThread(self._thread)
        
        # Connect signals
        self._thread.started.connect(self._worker.process)
        self._worker.think_start.connect(self._on_think_start)
        self._worker.thought_chunk.connect(self._on_thought_chunk)
        self._worker.response_chunk.connect(self._on_response_chunk)
        self._worker.think_end.connect(self._on_think_end)
        self._worker.simple_response.connect(self._on_simple_response)
        self._worker.error.connect(self._on_error)
        self._worker.status.connect(self._on_status)
        self._worker.toast.connect(self._on_toast)
        self._worker.set_timer_signal.connect(self._on_set_timer)
        self._worker.reload_alarms.connect(self._on_reload_alarms)
        self._worker.reload_calendar.connect(self._on_reload_calendar)
        self._worker.search_start.connect(self._on_search_start)
        self._worker.search_end.connect(self._on_search_end)
        self._worker.done.connect(self._on_done)
        self._worker.done.connect(self._thread.quit)
        self._worker.done.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        
        # Update messages reference
        self._worker.messages = self.messages
        
        self._thread.start()

    def listen_for_voice_input(self):
        """Capture one push-to-talk voice command, then send it as normal chat text."""
        if not PUSH_TO_TALK_ENABLED:
            self.main_window.set_status("Voice input disabled")
            return
        if self._voice_thread:
            return

        self.main_window.set_voice_listening_state(True)
        self.main_window.set_status("Starting voice input...")

        self._voice_thread = QThread(self)
        self._voice_worker = VoiceInputWorker()
        self._voice_worker.moveToThread(self._voice_thread)

        self._voice_thread.started.connect(self._voice_worker.process)
        self._voice_worker.status.connect(self._on_status)
        self._voice_worker.error.connect(self._on_voice_error)
        self._voice_worker.transcript.connect(self._on_voice_transcript)
        self._voice_worker.done.connect(self._on_voice_done)
        self._voice_worker.done.connect(self._voice_thread.quit)
        self._voice_worker.done.connect(self._voice_worker.deleteLater)
        self._voice_thread.finished.connect(self._on_voice_thread_finished)
        self._voice_thread.finished.connect(self._voice_thread.deleteLater)
        self._voice_thread.start()

    def start_wake_word_listener(self):
        """Start one background wake-word listener if enabled."""
        if self._wake_thread:
            self.main_window.set_status(f"Wake word already listening for {WAKE_WORD_PHRASE}")
            return

        import threading
        self._wake_stop_event = threading.Event()
        self._wake_thread = QThread(self)
        self._wake_worker = WakeWordWorker(self._wake_stop_event)
        self._wake_worker.moveToThread(self._wake_thread)

        self._wake_thread.started.connect(self._wake_worker.process)
        self._wake_worker.status.connect(self._on_status)
        self._wake_worker.error.connect(self._on_wake_error)
        self._wake_worker.wake_detected.connect(self._on_wake_detected)
        self._wake_worker.transcript.connect(self._on_wake_transcript)
        self._wake_worker.done.connect(self._wake_thread.quit)
        self._wake_worker.done.connect(self._wake_worker.deleteLater)
        self._wake_thread.finished.connect(self._on_wake_thread_finished)
        self._wake_thread.finished.connect(self._wake_thread.deleteLater)
        self._wake_thread.start()

    def stop_wake_word_listener(self):
        """Stop wake-word listener without affecting chat or push-to-talk."""
        if self._wake_stop_event:
            self._wake_stop_event.set()
        if self._wake_thread:
            self._wake_thread.quit()
            self._wake_thread.wait(8000)

    def _on_wake_detected(self):
        self.main_window.set_voice_listening_state(True)
        self.main_window.set_status("Wake word detected")

    def _on_wake_transcript(self, text: str):
        self.main_window.set_voice_listening_state(False)
        self.main_window.set_status(f"Heard: {text}")
        self.send_message(text)

    def _on_wake_error(self, text: str):
        self.main_window.set_voice_listening_state(False)
        self.main_window.add_message_bubble("system", text, is_thinking=True)
        self.main_window.set_status(f"Listening for {WAKE_WORD_PHRASE}")

    def _on_wake_thread_finished(self):
        self._wake_worker = None
        self._wake_thread = None
        self._wake_stop_event = None

    def _on_voice_transcript(self, text: str):
        self.main_window.set_status(f"Heard: {text}")
        self.send_message(text)

    def _on_voice_error(self, text: str):
        self.main_window.add_message_bubble("system", f"Voice error: {text}", is_thinking=True)
        self.main_window.set_status("Voice input failed")

    def _on_voice_done(self):
        self.main_window.set_voice_listening_state(False)

    def _on_voice_thread_finished(self):
        self._voice_worker = None
        self._voice_thread = None

    def clear_chat(self):
        """Start a fresh chat (reset session)."""
        tts.stop()
        if self._stop_event:
            self._stop_event.set()
        self.ui_throttle_timer.stop()
        self.streaming_state['is_generating'] = False
        self.current_session_id = None
        self.messages = [self.messages[0]]
        if hasattr(self.main_window.chat_tab, "reset_for_new_chat"):
            self.main_window.chat_tab.reset_for_new_chat()
        else:
            self.main_window.clear_chat_display()
            self.main_window.set_generating_state(False)
        self.refresh_sidebar()

    def toggle_tts(self, enabled: bool):
        """Toggle TTS on/off."""
        self.is_tts_enabled = enabled
        try:
            ok = tts.toggle(enabled)
        except Exception as e:
            ok = False
            self.main_window.set_status(f"TTS warning: {e}")

        if enabled and not ok:
            self.is_tts_enabled = False
            self.main_window.set_status("TTS unavailable")
        else:
            self.main_window.set_status("Speak responses on" if enabled else "Speak responses off")
