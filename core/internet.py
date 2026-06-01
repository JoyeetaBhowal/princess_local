from __future__ import annotations


FRIENDLY_SEARCH_LIMIT_MESSAGE = "Internet search is temporarily limited. Local chat still works."


def friendly_internet_error(error: Exception | str) -> str:
    """Return a user-safe internet failure message."""
    text = str(error).lower()
    rate_limit_markers = [
        "403",
        "429",
        "ratelimit",
        "rate limit",
        "too many requests",
        "forbidden",
        "blocked",
    ]
    if any(marker in text for marker in rate_limit_markers):
        return FRIENDLY_SEARCH_LIMIT_MESSAGE
    return f"Internet search is unavailable right now. Local chat still works."


def internet_disabled_message() -> str:
    return "Internet mode is off. Local chat still works."
