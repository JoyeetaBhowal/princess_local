"""
Centralized configuration for Princess.
"""

# --- Model Configuration ---
ASSISTANT_NAME = "Princess"
ASSISTANT_SYSTEM_PROMPT = (
    "You are Princess, a calm, intelligent, protective, and empowering local AI assistant. "
    "Respond in short, complete sentences. Be warm, steady, and practical. "
    "Do not provide medical, legal, financial, unsafe, or harmful advice. "
    "Never use emojis or special characters. "
    'SYSTEM INSTRUCTION: You may detect a "/think" trigger. This is an internal control. '
    "You MUST IGNORE it and DO NOT mention it in your response or thoughts."
)
RESPONDER_MODEL = "qwen3:1.7b"
OLLAMA_URL = "http://localhost:11434/api"
LOCAL_ROUTER_PATH = "./merged_model"
HF_ROUTER_REPO = "nlouis/pocket-ai-router"  # Hugging Face repo for auto-download
MAX_HISTORY = 20

# Keep first run focused on reliable text chat. Enable later for planner/tasks/actions.
TEXT_CHAT_ENABLED = True
ROUTER_ENABLED = False

# --- Internet / Content Command Center ---
INTERNET_BRIEFING_ENABLED = True
SOCIAL_ACTIONS_REQUIRE_APPROVAL = True
SOCIAL_POSTING_ENABLED = False
DAILY_PERMISSION_REQUIRED = True

# --- TTS Configuration ---
TTS_ENABLED = True
TTS_PROVIDER = "piper"
SPEAK_RESPONSES = True
TTS_VOICE_MODEL = "en_GB-jenny_dioco-medium"
TTS_MODEL_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium.onnx"
TTS_CONFIG_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium.onnx.json"

# --- STT Configuration ---
# Using RealTimeSTT for real-time speech-to-text
STT_MODEL_PATH = None  # Not used with RealTimeSTT (kept for compatibility)
STT_USE_WHISPER = False  # Not used with RealTimeSTT (kept for compatibility)
WHISPER_MODEL_SIZE = "base"  # Not used with RealTimeSTT (kept for compatibility)
WAKE_WORD_DETECTION_METHOD = "transcription"  # RealTimeSTT uses transcription-based detection
REALTIMESTT_MODEL = "base"  # RealTimeSTT model: "tiny", "base", "small", "medium", "large"
PUSH_TO_TALK_ENABLED = True
PUSH_TO_TALK_STT_MODEL = "tiny"  # Keep first voice milestone lightweight.
# Give users enough room to finish a natural sentence or short command.
PUSH_TO_TALK_RECORD_SECONDS = 10
WAKE_WORD_ENABLED = True
WAKE_WORD_PHRASE = "Hey Princess"
WAKE_WORD_LISTEN_SECONDS = 3
WAKE_WORD_RECORD_SECONDS = 10
USE_PORCUPINE_WAKE_WORD = False  # Use Porcupine for wake word detection (more accurate, requires API key)
PORCUPINE_ACCESS_KEY = None  # Get from https://console.picovoice.ai/ (optional, for better wake word detection)
WAKE_WORD = "hey princess"
WAKE_WORD_SENSITIVITY = 0.4  # For audio pattern matching (0.0-1.0, higher = more sensitive) - Lowered to reduce false positives
WAKE_WORD_CONFIRMATION_COUNT = 1  # Require multiple detections before triggering (reduces false positives)
STT_SAMPLE_RATE = 16000
STT_CHUNK_SIZE = 4096
STT_RECORD_TIMEOUT = 5.0  # Maximum seconds to record after wake word

# --- Voice Assistant Configuration ---
VOICE_ASSISTANT_ENABLED = True
QWEN_TIMEOUT_SECONDS = 300  # 5 minutes of inactivity before sleep
QWEN_KEEP_ALIVE = "5m"  # Keep in memory for 5 minutes after last use

# --- Router Keywords ---
# REMOVED: ROUTER_KEYWORDS - All queries now go through Function Gemma router
# The router handles all routing decisions, so keyword-based bypass is no longer needed

# --- Function Definitions (Official JSON Schema) ---
FUNCTIONS = [
    {
        "type": "function",
        "function": {
            "name": "control_light",
            "description": "Controls smart lights - turn on, off, or dim lights in a room",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "The action to perform: on, off, or dim"},
                    "room": {"type": "string", "description": "The room name where the light is located"}
                },
                "required": ["action", "room"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Searches the web for information using Google",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query string"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_timer",
            "description": "Sets a countdown timer for a specified duration",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration": {"type": "string", "description": "Time duration like 5 minutes or 1 hour"},
                    "label": {"type": "string", "description": "Optional timer name or label"}
                },
                "required": ["duration"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Creates a new calendar event or appointment",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The event title"},
                    "date": {"type": "string", "description": "The date of the event"},
                    "time": {"type": "string", "description": "The time of the event"},
                    "description": {"type": "string", "description": "Optional event details"}
                },
                "required": ["title", "date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_calendar",
            "description": "Reads and retrieves calendar events for a date or time range",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "The date or date range to check"},
                    "filter": {"type": "string", "description": "Optional filter like meetings or appointments"}
                },
                "required": ["date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "passthrough",
            "description": "DEFAULT FUNCTION - Use this whenever no other function is clearly needed. This is the fallback for: greetings (hello, hi, good morning), chitchat (how are you, what's your name), general knowledge questions, explanations, conversations, and ANY query that does NOT explicitly require controlling lights, setting timers, searching the web, or managing calendar events. When in doubt, use passthrough.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thinking": {"type": "boolean", "description": "Set to true for complex reasoning/math/logic, false for simple greetings and chitchat."}
                },
                "required": ["thinking"]
            }
        }
    }
]

# --- Console Colors ---
GRAY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
