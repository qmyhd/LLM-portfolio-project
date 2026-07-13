"""Helpers for importing off-platform timeline content into ideas."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.message_cleaner import extract_ticker_symbols


_CONTENT_FIELDS = ("text", "message", "body", "content", "Text", "Message", "Body")
_DATE_FIELDS = ("date", "sent_at", "timestamp", "time", "Date", "Sent At", "Timestamp")
_AUTHOR_FIELDS = ("sender", "from", "author", "contact", "Sender", "From", "Author", "Contact")
_MESSAGE_ID_FIELDS = ("message_id", "id", "guid", "Message ID", "ID", "GUID")
_THREAD_FIELDS = ("chat", "chat_name", "conversation", "thread", "Chat", "Chat Name", "Conversation")


@dataclass(frozen=True)
class ImportedTimelineMessage:
    """Normalized message payload accepted by /ideas/import/messages."""

    content: str
    sentAt: str | None = None
    author: str | None = None
    authorId: str | None = None
    messageId: str | None = None
    threadKey: str | None = None
    symbols: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    sourceUrl: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "sentAt": self.sentAt,
            "author": self.author,
            "authorId": self.authorId,
            "messageId": self.messageId,
            "threadKey": self.threadKey,
            "symbols": self.symbols,
            "tags": self.tags,
            "sourceUrl": self.sourceUrl,
            "metadata": self.metadata,
        }


def _first_present(row: dict[str, Any], fields: tuple[str, ...]) -> Any:
    for field_name in fields:
        value = row.get(field_name)
        if value is not None and str(value).strip():
            return value
    return None


def _parse_timestamp(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None

    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"

    for fmt in (
        None,
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%y %I:%M %p",
    ):
        try:
            parsed = datetime.fromisoformat(raw) if fmt is None else datetime.strptime(raw, fmt)
            return parsed.isoformat()
        except ValueError:
            continue
    return raw


def normalize_imazing_row(
    row: dict[str, Any],
    *,
    default_thread_key: str | None = None,
    default_author: str | None = None,
) -> ImportedTimelineMessage | None:
    """Normalize one iMazing CSV/JSON row into an importable message."""
    content = _first_present(row, _CONTENT_FIELDS)
    if not content or not str(content).strip():
        return None

    raw_symbols = [ticker.lstrip("$").upper() for ticker in extract_ticker_symbols(str(content))]
    thread_key = _first_present(row, _THREAD_FIELDS) or default_thread_key
    author = _first_present(row, _AUTHOR_FIELDS) or default_author
    message_id = _first_present(row, _MESSAGE_ID_FIELDS)

    metadata = {
        "import_source": "imazing",
        "raw_fields": {key: value for key, value in row.items() if value not in (None, "")},
    }

    return ImportedTimelineMessage(
        content=str(content).strip(),
        sentAt=_parse_timestamp(_first_present(row, _DATE_FIELDS)),
        author=str(author).strip() if author else None,
        messageId=str(message_id).strip() if message_id else None,
        threadKey=str(thread_key).strip() if thread_key else None,
        symbols=raw_symbols,
        tags=["imessage"],
        metadata=metadata,
    )


def load_imazing_messages(
    path: str | Path,
    *,
    default_thread_key: str | None = None,
    default_author: str | None = None,
) -> list[ImportedTimelineMessage]:
    """Load iMazing CSV or JSON exports into normalized messages."""
    import_path = Path(path)
    suffix = import_path.suffix.lower()

    if suffix == ".csv":
        with import_path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    elif suffix == ".json":
        with import_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        rows = payload if isinstance(payload, list) else payload.get("messages", [])
    else:
        raise ValueError("iMazing import path must be a .csv or .json file")

    messages = [
        msg
        for row in rows
        if (msg := normalize_imazing_row(row, default_thread_key=default_thread_key, default_author=default_author))
    ]
    return messages


def build_import_payload(
    messages: list[ImportedTimelineMessage],
    *,
    source: str = "imessage",
    thread_key: str | None = None,
    default_author: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "threadKey": thread_key,
        "defaultAuthor": default_author,
        "messages": [message.to_api_dict() for message in messages],
    }
