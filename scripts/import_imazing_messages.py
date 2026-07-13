"""Build an /ideas/import/messages payload from an iMazing export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.content_import import build_import_payload, load_imazing_messages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_path", help="iMazing CSV or JSON export path")
    parser.add_argument("--thread-key", help="Stable timeline thread key, e.g. friends-market-chat")
    parser.add_argument("--default-author", help="Author to use when the export row has no sender")
    parser.add_argument("--output", help="Write JSON payload to this path instead of stdout")
    args = parser.parse_args()

    messages = load_imazing_messages(
        args.export_path,
        default_thread_key=args.thread_key,
        default_author=args.default_author,
    )
    payload = build_import_payload(
        messages,
        thread_key=args.thread_key,
        default_author=args.default_author,
    )
    rendered = json.dumps(payload, indent=2, ensure_ascii=False)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
