import csv
import json

from src.content_import import build_import_payload, load_imazing_messages, normalize_imazing_row


def test_normalize_imazing_row_extracts_symbols_and_metadata():
    msg = normalize_imazing_row(
        {
            "Text": "Adding $AAPL but 13F read is separate",
            "Date": "2026-06-01 14:30:00",
            "Sender": "Qais",
            "GUID": "imsg-1",
            "Chat Name": "Friends Market Chat",
        }
    )

    assert msg is not None
    assert msg.content == "Adding $AAPL but 13F read is separate"
    assert msg.sentAt == "2026-06-01T14:30:00"
    assert msg.author == "Qais"
    assert msg.messageId == "imsg-1"
    assert msg.threadKey == "Friends Market Chat"
    assert msg.symbols == ["AAPL"]
    assert msg.metadata["import_source"] == "imazing"


def test_load_imazing_csv_skips_empty_rows(tmp_path):
    export_path = tmp_path / "messages.csv"
    with export_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Text", "Date", "Sender"])
        writer.writeheader()
        writer.writerow({"Text": "", "Date": "2026-06-01 14:30:00", "Sender": "Qais"})
        writer.writerow({"Text": "Watching $MSFT", "Date": "2026-06-01 14:31:00", "Sender": ""})

    messages = load_imazing_messages(
        export_path,
        default_thread_key="friends-market-chat",
        default_author="Qais",
    )

    assert len(messages) == 1
    assert messages[0].author == "Qais"
    assert messages[0].threadKey == "friends-market-chat"
    assert messages[0].symbols == ["MSFT"]


def test_load_imazing_json_and_build_api_payload(tmp_path):
    export_path = tmp_path / "messages.json"
    export_path.write_text(
        json.dumps({"messages": [{"body": "Macro thread, no ticker", "timestamp": "2026-06-01T14:30:00Z"}]}),
        encoding="utf-8",
    )

    messages = load_imazing_messages(export_path, default_thread_key="macro-story")
    payload = build_import_payload(messages, thread_key="macro-story", default_author="Qais")

    assert payload["source"] == "imessage"
    assert payload["threadKey"] == "macro-story"
    assert payload["defaultAuthor"] == "Qais"
    assert payload["messages"][0]["content"] == "Macro thread, no ticker"
    assert payload["messages"][0]["sentAt"] == "2026-06-01T14:30:00+00:00"
