"""PreToolUse guard: Robinhood MCP tools are READ-ONLY.

Any MCP server whose name contains "robinhood" may only run tools whose name starts with an
allowed read prefix, or is in the small exact-name read allowlist. Everything else (place_*,
cancel_*, exercise_*, create_*/update_*/delete_*, and any tool Robinhood adds later) is denied.
Fails closed: unreadable input -> exit 2 (block).

To enable a future, deliberate order feature, change this file on purpose; do not loosen the
prefixes casually. See docs/integrations/robinhood-mcp.md. The live tool list and each tool's
expected verdict are pinned in docs/integrations/robinhood-mcp-tools.json and checked by
tests/test_robinhood_guard.py.

This file is the canonical copy (project scope, wired in .claude/settings.json). A copy may also
be installed at ~/.claude/hooks/ for user scope; keep them identical.
"""
import json
import sys

ALLOWED_PREFIXES = ("get_", "list_", "search_", "review_", "preview_")
# Read-only tools whose names don't fit a prefix. Verified read-only from the tool descriptions
# (2026-11-04): `search` resolves names to instruments; `run_scan` executes a saved screener.
ALLOWED_EXACT = frozenset({"search", "run_scan"})


def decide(tool_name: str):
    parts = tool_name.split("__")
    if len(parts) < 3 or parts[0] != "mcp":
        return None  # not an MCP tool; not our business
    server, tool = parts[1], "__".join(parts[2:])
    if "robinhood" not in server.lower():
        return None
    name = tool.lower()
    if name.startswith(ALLOWED_PREFIXES) or name in ALLOWED_EXACT:
        return None
    return (
        f"Blocked by robinhood_readonly_guard: '{tool}' on '{server}' is not a read-only tool. "
        "Robinhood MCP is read-only in this setup; no orders, cancels, or exercises. "
        "Draft the order for Qais to place himself in the Robinhood app instead."
    )


def main():
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
        tool_name = payload.get("tool_name", "")
    except Exception as exc:  # fail closed
        print(f"robinhood_readonly_guard: could not read hook input ({exc}); blocking.", file=sys.stderr)
        sys.exit(2)
    reason = decide(tool_name)
    if reason:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }))
    sys.exit(0)


if __name__ == "__main__":
    main()
