"""
Approval queue for actions that must never run silently.

Social posting and account actions should pass through this queue before any
connector is allowed to publish, message, or change external state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Iterable
from uuid import uuid4


APPROVALS_PATH = Path("data") / "approvals.json"


@dataclass
class ApprovalItem:
    id: str
    title: str
    category: str
    action_type: str
    target: str
    content: str
    status: str
    created_at: str
    approved_at: str | None = None


class ApprovalQueue:
    """Small JSON-backed queue for user-approved work."""

    def __init__(self, path: Path | str = APPROVALS_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: list[ApprovalItem] = self._load()

    def add(
        self,
        title: str,
        category: str,
        action_type: str,
        target: str,
        content: str,
    ) -> ApprovalItem:
        item = ApprovalItem(
            id=uuid4().hex,
            title=title.strip() or "Untitled action",
            category=category.strip() or "General",
            action_type=action_type.strip() or "draft",
            target=target.strip() or "Manual",
            content=content.strip(),
            status="pending",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._items.insert(0, item)
        self._save()
        return item

    def list_all(self) -> list[ApprovalItem]:
        return list(self._items)

    def list_pending(self) -> list[ApprovalItem]:
        return [item for item in self._items if item.status == "pending"]

    def update_status(self, item_id: str, status: str) -> ApprovalItem | None:
        if status not in {"pending", "approved", "rejected"}:
            raise ValueError(f"Unsupported approval status: {status}")

        for item in self._items:
            if item.id == item_id:
                item.status = status
                item.approved_at = (
                    datetime.now().isoformat(timespec="seconds")
                    if status == "approved"
                    else None
                )
                self._save()
                return item
        return None

    def _load(self) -> list[ApprovalItem]:
        if not self.path.exists():
            return []

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return []
            return [ApprovalItem(**item) for item in raw if isinstance(item, dict)]
        except Exception as exc:
            print(f"[Approvals] Could not load queue: {exc}")
            return []

    def _save(self) -> None:
        payload = [asdict(item) for item in self._items]
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


approval_queue = ApprovalQueue()
